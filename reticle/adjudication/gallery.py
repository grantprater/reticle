"""Appearance galleries by phase, and held-out identity evaluation.

Milestone D of ``docs/ABILITY_ENTITY_INFERENCE_DESIGN.md``.  A gallery is per
``(ability_id, phase)`` because one average template per ability throws away
the thing that distinguishes a deploying wall from a pulsing device.

Two rules decide what may be scored, and both exist to stop a margin that is
really a session artefact:

* **Leave one session out.**  Components of one entity repeat across frames of
  one clip, so holding out a component while training on its neighbours scores
  the reader against itself.
* **Both test classes must share the test session.**  Training across sessions
  and testing within one means a classifier cannot win by learning the map,
  the profile or the capture; it has to separate two abilities a human labelled
  in the same footage.

Only a contrast that satisfies both is reported as recognition.  Everything
else enters the gallery and is named as not evaluable, which is a coverage
statement rather than a negative result.

Owns [owns:ability-appearance].
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .ability import _components, _labels
from ..revisions import current_revision, publish_revision


ABILITY_GALLERY_VERSION = "ability-gallery-0.2.0"

# Relative to the component's own observation time.  ``pre`` is the background
# the effect arrives against; it is evidence, not padding.
PHASES = (("pre", -2000.0, 0.0), ("onset", 0.0, 500.0),
          ("early", 500.0, 3000.0), ("sustained", 3000.0, 15000.0))

# The scalar summaries that already exist.  These are the baseline milestone D
# has to beat, not a strawman: a wall and a device differ in size before any
# temporal evidence is considered.
SCALAR_FEATURES = ("area", "aspect", "colour_frac", "n_observations",
                   "duration_ms", "diff_min")
TRACE_KEYS = ("g_mean", "dark_n", "bright_n", "detect", "self_d")


def load_series(root: Path, sid: str):
    path = root / "series" / f"{sid}.npz"
    if not path.is_file():
        return None
    z = np.load(path, allow_pickle=True)
    queries = json.loads(str(z["queries"]))
    index = {(int(q["x"]), int(q["y"]), float(q["t_ms"])): i
             for i, q in enumerate(queries)}
    return {"t_ms": np.asarray(z["t_ms"], float), "index": index,
            "arrays": {k: z[k] for k in TRACE_KEYS if k in z.files}}


def load_appearance_phases(root: Path) -> tuple[dict[str, dict], dict]:
    """Load the current immutable phase artifact, keyed by component ID."""
    out = root / "analysis" / "ability-phases"
    revision = current_revision(out)
    source = revision or out
    rows_path, manifest_path = source / "phases.jsonl", source / "manifest.json"
    if not rows_path.is_file() or not manifest_path.is_file():
        return {}, {"status": "unavailable", "reason": "run ability-phases first"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return ({row["component_id"]: row for row in rows}, {
        "status": "available",
        "producer_version": manifest.get("producer_version"),
        "revision_id": (manifest.get("revision") or {}).get("revision_id"),
        "rows": len(rows),
    })


def _summary(values: np.ndarray) -> dict:
    """Median and spread.  A mean over a lit/unlit trace is neither state.

    Non-finite samples are dropped rather than folded in.  ``self_d`` is NaN on
    frames where the self track did not fit, and that is absence of evidence:
    the fit fails when the widget is occluded, which is exactly when candidates
    are born, so folding it in would bias in the worst available direction.  A
    phase with nothing finite left yields no feature at all, so the shared-feature
    intersection drops it instead of imputing one.
    """
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {}
    return {"median": float(np.median(values)), "iqr": float(
        np.percentile(values, 75) - np.percentile(values, 25))}


def trace_features(series: dict, component: dict,
                   appearance_row: dict | None = None) -> dict:
    """Relative-time and observed-appearance shape for one component."""
    if not series:
        return {}
    key = (int(component["x"]), int(component["y"]), float(component["observed_t_ms"]))
    row = series["index"].get(key)
    if row is None:
        return {}
    t = series["t_ms"] - component["observed_t_ms"]
    out = {}
    for phase, lo, hi in PHASES:
        mask = (t >= lo) & (t < hi)
        if not mask.any():
            continue
        for name, array in series["arrays"].items():
            values = np.asarray(array[row][mask], float)
            for stat, value in _summary(values).items():
                out[f"relative_{phase}.{name}.{stat}"] = value
    if appearance_row:
        absolute_t = series["t_ms"]
        for appearance in ("bright", "dim"):
            spans = [p for p in appearance_row.get("appearance_segments", [])
                     if p.get("appearance") == appearance
                     and p.get("status") == "stable_appearance"]
            if not spans:
                continue
            mask = np.zeros(absolute_t.shape, dtype=bool)
            for span in spans:
                mask |= ((absolute_t >= span["from_ms"])
                         & (absolute_t <= span["to_ms"]))
            if not mask.any():
                continue
            for name, array in series["arrays"].items():
                values = np.asarray(array[row][mask], float)
                for stat, value in _summary(values).items():
                    out[f"appearance_{appearance}.{name}.{stat}"] = value
    return out


def scalar_features(component: dict) -> dict:
    raw = component.get("raw") or {}
    out = {}
    for name in SCALAR_FEATURES:
        value = raw.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[name] = float(value)
    return out


def build_examples(root: Path) -> list[dict]:
    root = Path(root)
    components = _components(root, _labels(root))
    cache: dict[str, dict | None] = {}
    appearance_rows, _ = load_appearance_phases(root)
    out = []
    for component in components:
        if component["label_state"] != "named":
            continue
        sid = component["session_id"]
        if sid not in cache:
            cache[sid] = load_series(root, sid)
        appearance_row = appearance_rows.get(component["component_id"])
        trace = trace_features(cache[sid], component, appearance_row)
        relative = {k: v for k, v in trace.items() if k.startswith("relative_")}
        bright = {k: v for k, v in trace.items() if k.startswith("appearance_bright.")}
        dim = {k: v for k, v in trace.items() if k.startswith("appearance_dim.")}
        out.append({
            "component_id": component["component_id"], "session_id": sid,
            "ability_id": component["label_ability_id"],
            "agent": component["label_ability_id"].split(":")[0],
            "origin": component["origin"],
            "scalar": scalar_features(component), "trace": trace,
            "relative": relative, "appearance_bright": bright,
            "appearance_dim": dim,
            "has_trace": bool(trace),
            "appearance_conditioned": bool(appearance_row),
            "appearance_segments": ((appearance_row or {}).get("appearance_segments") or []),
        })
    return out


def merged(example: dict, blocks: tuple[str, ...]) -> dict:
    """One flat feature dict for the chosen evidence blocks."""
    return {f"{block}.{name}": value for block in blocks
            for name, value in example[block].items()}


def shared_features(examples: list[dict], blocks: tuple[str, ...]) -> list[str]:
    """Only features every example carries.  Imputing a missing one would
    invent evidence, and the missingness is not random -- it tracks which
    sessions were decoded."""
    sets = [set(merged(e, blocks)) for e in examples]
    if not sets or not all(sets):
        return []
    return sorted(set.intersection(*sets))


def _matrix(examples: list[dict], names: list[str], blocks: tuple[str, ...]) -> np.ndarray:
    return np.array([[merged(e, blocks)[n] for n in names] for e in examples], float)


def nearest_centroid(train: list[dict], test: list[dict],
                     blocks: tuple[str, ...]) -> list[str] | None:
    """Median centroid per class on z-scored features.  No fitted threshold and
    no tuning, so there is nothing for the test session to leak into."""
    names = shared_features(train + test, blocks)
    if not names or len({e["ability_id"] for e in train}) < 2:
        return None
    x_train, x_test = _matrix(train, names, blocks), _matrix(test, names, blocks)
    if not np.isfinite(x_train).all() or not np.isfinite(x_test).all():
        return None
    mean, sd = x_train.mean(0), x_train.std(0)
    sd[sd == 0] = 1.0
    x_train, x_test = (x_train - mean) / sd, (x_test - mean) / sd
    classes = sorted({e["ability_id"] for e in train})
    centroids = np.array([np.median(x_train[[i for i, e in enumerate(train)
                                             if e["ability_id"] == c]], axis=0)
                          for c in classes])
    distance = ((x_test[:, None, :] - centroids[None, :, :]) ** 2).sum(-1)
    return [classes[i] for i in distance.argmin(1)]


def balanced_accuracy(truth: list[str], predicted: list[str]) -> float:
    """Accuracy would score the majority-class prior at 0.91 here."""
    per = defaultdict(lambda: [0, 0])
    for actual, guess in zip(truth, predicted):
        per[actual][1] += 1
        per[actual][0] += actual == guess
    return round(sum(hit / total for hit, total in per.values()) / len(per), 4)


MIN_PER_CLASS = 3
BLOCK_SETS = (("scalar",), ("relative",), ("appearance_bright",),
              ("appearance_dim",), ("appearance_bright", "relative"),
              ("appearance_dim", "relative"))
PERMUTATIONS = 200
PERMUTATION_SEED = 20260909


def eligible_contrasts(examples: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split the corpus into what can be scored and what cannot, with reasons.

    A test session qualifies only when it holds at least two labelled classes of
    one agent, each with ``MIN_PER_CLASS`` components, and each of those classes
    also occurs in another session to train on.  Testing within a session is
    what stops the map or the capture profile from supplying the margin;
    training outside it is what stops the reader from scoring itself.
    """
    by_agent = defaultdict(lambda: defaultdict(Counter))
    for e in examples:
        by_agent[e["agent"]][e["session_id"]][e["ability_id"]] += 1
    contrasts, excluded = [], []
    for agent, sessions in sorted(by_agent.items()):
        elsewhere = defaultdict(set)
        for sid, counts in sessions.items():
            for ability in counts:
                elsewhere[ability].add(sid)
        for sid, counts in sorted(sessions.items()):
            present = sorted(a for a, n in counts.items() if n >= MIN_PER_CLASS)
            trainable = [a for a in present if elsewhere[a] - {sid}]
            if len(present) < 2:
                excluded.append({"agent": agent, "test_session": sid,
                                 "classes": sorted(counts),
                                 "reason": "fewer_than_two_classes_in_one_session"})
            elif len(trainable) < 2:
                excluded.append({"agent": agent, "test_session": sid,
                                 "classes": present,
                                 "untrainable": sorted(set(present) - set(trainable)),
                                 "reason": "class_occurs_in_no_other_session"})
            else:
                contrasts.append({"agent": agent, "test_session": sid,
                                  "classes": trainable,
                                  "train_sessions": sorted(
                                      set().union(*(elsewhere[a] for a in trainable)) - {sid})})
    return contrasts, excluded


def permutation_ceiling(train: list[dict], test: list[dict], truth: list[str],
                        blocks: tuple[str, ...]) -> dict | None:
    """What this split scores when the training labels carry no information.

    Two classes and 32 test rows leave a lot of room for a pleasing number to be
    luck, and the classes here are 3:1 imbalanced.  Shuffling the training
    labels keeps every other property of the split -- sizes, feature
    distributions, the imbalance -- so what it reaches is the bar an observed
    score has to clear.

    The statistic is the permutation p-value, not a percentile.  With two
    classes and two well-separated test clusters, a shuffled fit lands a perfect
    score whenever the two collapsed centroids happen to fall in the right
    order, which is about half the time -- so a 95th percentile is structurally
    1.0 here and could never be cleared.  The fraction of shuffles that match or
    beat the observed score says the same thing without that degeneracy: if half
    of them reach it, a perfect score is worth nothing.
    """
    rng = np.random.default_rng(PERMUTATION_SEED)
    labels = [e["ability_id"] for e in train]
    scores = []
    for _ in range(PERMUTATIONS):
        shuffled = list(rng.permutation(labels))
        permuted = [dict(e, ability_id=label) for e, label in zip(train, shuffled)]
        predicted = nearest_centroid(permuted, test, blocks)
        if predicted is None:
            return None
        scores.append(balanced_accuracy(truth, predicted))
    return {"permutations": PERMUTATIONS, "median": round(float(np.median(scores)), 4),
            "max": round(float(np.max(scores)), 4), "scores": scores}


def permutation_p(observed: float, control: dict | None) -> float | None:
    """Fraction of shuffles reaching the observed score, with the standard +1."""
    if not control:
        return None
    at_least = sum(score >= observed - 1e-12 for score in control["scores"])
    return round((at_least + 1) / (control["permutations"] + 1), 4)


def evaluate(examples: list[dict]) -> tuple[list[dict], list[dict]]:
    contrasts, excluded = eligible_contrasts(examples)
    results = []
    for contrast in contrasts:
        classes = set(contrast["classes"])
        test = [e for e in examples if e["session_id"] == contrast["test_session"]
                and e["ability_id"] in classes]
        train = [e for e in examples if e["session_id"] != contrast["test_session"]
                 and e["ability_id"] in classes]
        truth = [e["ability_id"] for e in test]
        majority = Counter(e["ability_id"] for e in train).most_common(1)[0][0]
        scores = {"prior": {"balanced_accuracy": balanced_accuracy(truth, [majority] * len(truth)),
                            "accuracy": round(sum(t == majority for t in truth) / len(truth), 4),
                            "features": 0}}
        for blocks in BLOCK_SETS:
            name = "+".join(blocks)
            # An appearance mode is legitimately absent on some objects. Score
            # only a declared covered subset, and require every class on both
            # sides so missingness cannot silently decide the label.
            covered_train = [e for e in train if all(e[block] for block in blocks)]
            covered_test = [e for e in test if all(e[block] for block in blocks)]
            train_counts = Counter(e["ability_id"] for e in covered_train)
            test_counts = Counter(e["ability_id"] for e in covered_test)
            enough = all(train_counts[c] >= MIN_PER_CLASS
                         and test_counts[c] >= MIN_PER_CLASS for c in classes)
            predicted = (nearest_centroid(covered_train, covered_test, blocks)
                         if enough else None)
            if predicted is None:
                shared = shared_features(covered_train + covered_test, blocks)
                scores[name] = {
                    "balanced_accuracy": None, "accuracy": None,
                    "features": len(shared),
                    "n_train_covered": len(covered_train),
                    "n_test_covered": len(covered_test),
                    "coverage_by_class": {
                        c: {"train": train_counts[c], "test": test_counts[c]}
                        for c in sorted(classes)},
                    "unavailable": ("fewer than three covered examples per class and split"
                                    if not enough else "no feature shared by covered examples")}
                continue
            covered_truth = [e["ability_id"] for e in covered_test]
            observed = balanced_accuracy(covered_truth, predicted)
            chance = permutation_ceiling(covered_train, covered_test, covered_truth, blocks)
            p_value = permutation_p(observed, chance)
            scores[name] = {
                "balanced_accuracy": observed,
                "shuffled_label_control": ({k: v for k, v in chance.items() if k != "scores"}
                                           if chance else None),
                "permutation_p": p_value,
                "above_chance": (None if p_value is None else bool(p_value <= 0.05)),
                "accuracy": round(sum(t == p for t, p in zip(covered_truth, predicted))
                                  / len(covered_truth), 4),
                "features": len(shared_features(covered_train + covered_test, blocks)),
                "n_train_covered": len(covered_train),
                "n_test_covered": len(covered_test),
                "coverage_by_class": {
                    c: {"train": train_counts[c], "test": test_counts[c]}
                    for c in sorted(classes)},
                "per_class_recall": {c: balanced_accuracy(
                    [t for t in covered_truth if t == c],
                    [p for t, p in zip(covered_truth, predicted) if t == c])
                    for c in sorted(classes)},
            }
        results.append({**contrast, "n_test": len(test), "n_train": len(train),
                        "test_class_counts": dict(sorted(Counter(truth).items())),
                        "traces_in_test": sum(e["has_trace"] for e in test),
                        "traces_in_train": sum(e["has_trace"] for e in train),
                        "scores": scores})
    return results, excluded


def build_gallery(examples: list[dict]) -> list[dict]:
    """Per ``(ability_id, phase)``, never one average template per ability."""
    scalar = defaultdict(list)
    phased = defaultdict(list)
    for e in examples:
        scalar[e["ability_id"]].append(e)
        for name, value in e["trace"].items():
            phase = name.split(".", 1)[0]
            phased[(e["ability_id"], phase)].append((name, value, e["session_id"]))
    rows = []
    for ability, group in sorted(scalar.items()):
        rows.append({
            "ability_id": ability, "phase": "static", "block": "scalar",
            "n": len(group), "sessions": sorted({e["session_id"] for e in group}),
            "features": {name: _summary(np.array([e["scalar"][name] for e in group
                                                  if name in e["scalar"]], float))
                         for name in SCALAR_FEATURES
                         if any(name in e["scalar"] for e in group)},
        })
    for (ability, phase), entries in sorted(phased.items()):
        by_name = defaultdict(list)
        sessions = set()
        for name, value, sid in entries:
            by_name[name].append(value)
            sessions.add(sid)
        rows.append({
            "ability_id": ability, "phase": phase, "block": "trace",
            "n": len({e["component_id"] for e in examples
                      if e["ability_id"] == ability and e["trace"]}),
            "sessions": sorted(sessions),
            "features": {name: _summary(np.array(values, float))
                         for name, values in sorted(by_name.items())},
        })
    return rows


def audio_inventory(root: Path) -> dict:
    """Reference availability, which is not recognition.

    Every source-linked cut comes from one session, so scoring it against that
    session would be a template confirming its own training cast.  There is no
    independently anchored use of the same ability elsewhere with decoded audio,
    so the audio half of this milestone has nothing it can honestly be scored on.
    """
    sfx = sorted((root / "reference/assets/ability_sfx").glob("*.wav"))
    voicelines = sorted((root / "reference/assets/voicelines").glob("*.mp3"))
    sources = sorted({p.stem.split("__")[1].split("_")[0] for p in sfx if "__" in p.stem})
    return {
        "source_linked_cuts": len(sfx), "cut_sessions": sources,
        "cut_agents": sorted({p.stem.split("_")[0] for p in sfx}),
        "voicelines": len(voicelines),
        "voiceline_scope": "ultimate callouts only, ally and enemy",
        "evaluable": False,
        "reason": ("every cut is from one session and no other session has a labelled use "
                   "of the same ability with decoded audio, so any score would be the "
                   "template recognising its own training cast"),
    }


def build_gallery_bundle(root: str | Path) -> dict:
    root = Path(root).resolve()
    _, appearance_source = load_appearance_phases(root)
    examples = build_examples(root)
    gallery = build_gallery(examples)
    results, excluded = evaluate(examples)
    parameters = fit_parameters(root, session_durations(root))
    per_ability = defaultdict(lambda: [0, 0, set()])
    for e in examples:
        row = per_ability[e["ability_id"]]
        row[0] += 1
        row[1] += e["has_trace"]
        row[2].add(e["session_id"])
    coverage = [{"ability_id": ability, "named": n, "with_trace": traced,
                 "sessions": sorted(sessions),
                 "held_out_evaluable": any(ability in r["classes"] for r in results)}
                for ability, (n, traced, sessions) in sorted(per_ability.items())]
    summary = {
        "named_examples": len(examples),
        "examples_with_trace": sum(e["has_trace"] for e in examples),
        "examples_appearance_conditioned": sum(e["appearance_conditioned"] for e in examples),
        "abilities": len(per_ability),
        "gallery_rows": len(gallery),
        "parameter_fits": len(parameters),
        "bearings_determined": sum(1 for r in parameters
                                   if r.get("bearing") and r["bearing"]["resultant"] >= 0.9),
        "right_censored_lifetimes": sum(1 for r in parameters
                                        if r["lifetime_ms"]["right_censored"]),
        "scored_contrasts": len(results),
        "excluded_contrasts": len(excluded),
        "abilities_held_out_evaluable": sum(c["held_out_evaluable"] for c in coverage),
    }
    return {
        "manifest": {
            "schema_version": 1, "producer_version": ABILITY_GALLERY_VERSION,
            "store_root": str(root), "summary": summary,
            "relative_time_bins": [{"name": n, "from_ms": lo, "to_ms": hi}
                                   for n, lo, hi in PHASES],
            "appearance_source": appearance_source,
            "audio": audio_inventory(root),
            "limits": [
                "Balanced accuracy is the score; plain accuracy flatters the majority prior.",
                "A contrast is scored only when both classes share the test session and "
                "every class also occurs in a training session.",
                "Galleries are per relative-time bin and observed appearance; one "
                "average template per ability is not built.",
                "A gallery row for a single-session ability is coverage, not a validated model.",
                "Audio is a reference inventory and is not scored.",
                "Relative-time bins are not lifecycle phases: a human label marks when "
                "the labeller saw the thing, so `pre` can already contain the effect.",
                "Bright/dim galleries are observed appearance, not active/inactive state.",
                "Fitted lifetimes are observation bounds; a run to clip end is censored, not expiry.",
            ],
        },
        "coverage": coverage, "gallery": gallery, "parameters": parameters,
        "evaluation": results, "excluded": excluded,
    }


def write_gallery(bundle: dict, out: str | Path) -> Path:
    out = Path(out)
    files = {}
    for name in ("coverage", "gallery", "parameters", "evaluation", "excluded"):
        files[f"{name}.jsonl"] = "".join(
            json.dumps(row, sort_keys=True) + "\n" for row in bundle[name])
    publish_revision(
        out, artifact="ability_gallery", producer_version=ABILITY_GALLERY_VERSION,
        files=files, manifest=bundle["manifest"],
    )
    return out


CENSOR_MS = 1000.0


def _circular(angles_deg: list[float]) -> dict:
    """Bearing with its uncertainty.  A plain mean of 350 and 10 degrees is 180,
    which points the opposite way, so the resultant vector is the only summary
    allowed here.  ``resultant`` near 0 means the bearing is not determined."""
    radians = [math.radians(a) for a in angles_deg]
    n = len(radians)
    c, s = sum(math.cos(r) for r in radians) / n, sum(math.sin(r) for r in radians) / n
    resultant = math.hypot(c, s)
    return {
        "mean_deg": round(math.degrees(math.atan2(s, c)) % 360.0, 1),
        "resultant": round(resultant, 4),
        "circular_sd_deg": (round(math.degrees(math.sqrt(-2 * math.log(resultant))), 1)
                            if resultant > 1e-9 else None),
        "n": n,
    }


def fit_parameters(root: Path, durations: dict[str, float]) -> list[dict]:
    """Parameters conditioned on each identity alternative, never averaged across them.

    Milestone C emitted origin and bearing as placeholders on a single member.
    These are fitted across every member of the hypothesis, carry their own
    spread, and mark a lifetime that runs to the end of the clip as right
    censored rather than reporting the clip length as an expiry.
    """
    from ..ability_timeline import build_timeline
    from .ability import build_entities

    bundle = build_entities(root)
    ability_of = {u["use_claim_id"]: u.get("ability_id")
                  for u in build_timeline(root)["use_claims"]}
    components = {c["component_id"]: c for c in _components(root, _labels(root))}
    rows = []
    for hypothesis in bundle["entity_hypotheses"]:
        members = [components[cid] for cid in hypothesis["component_ids"] if cid in components]
        if not members:
            continue
        sid = members[0]["session_id"]
        xs = [float(m["x"]) for m in members]
        ys = [float(m["y"]) for m in members]
        start = min(m["observed_t_ms"] for m in members)
        end = max(m["observed_end_ms"] for m in members)
        duration = durations.get(sid)
        row = {
            "hypothesis_id": hypothesis["hypothesis_id"],
            "use_claim_id": hypothesis["use_claim_id"],
            "conditioned_on": ability_of.get(hypothesis["use_claim_id"]),
            "grouping_method": hypothesis["grouping_method"],
            "session_id": sid, "n_components": len(members),
            "origin": {"x": round(float(np.median(xs)), 1), "y": round(float(np.median(ys)), 1),
                       "spread_px": round(float(np.median(
                           [math.hypot(x - np.median(xs), y - np.median(ys))
                            for x, y in zip(xs, ys)])), 2)},
            "lifetime_ms": {"observed_from": start, "observed_to": end,
                            "right_censored": bool(duration and end >= duration - CENSOR_MS),
                            "note": "observation bounds, not an ability lifetime law"},
        }
        if len(members) >= 2:
            origin = min(members, key=lambda m: (m["observed_t_ms"], m["component_id"]))
            row["bearing"] = _circular([
                math.degrees(math.atan2(float(m["y"]) - float(origin["y"]),
                                        float(m["x"]) - float(origin["x"]))) % 360.0
                for m in members if m["component_id"] != origin["component_id"]])
        rows.append(row)
    return rows


def session_durations(root: Path) -> dict[str, float]:
    out = {}
    for path in sorted((root / "manifests").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        duration = (data.get("source") or {}).get("duration_ms")
        if duration:
            out[path.stem] = float(duration)
    return out
