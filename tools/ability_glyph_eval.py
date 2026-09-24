"""Score the ability glyph classifier against human labels, per split.

    .\\.venv\\Scripts\\python.exe tools\\ability_glyph_eval.py [--gate agent]

The evaluation set is every human-labelled detector candidate
(`labels/ability`) on the solo ability demos and on the match sessions. The
label is independent of the classifier; the classifier's own output never
labels anything here.

Splits are fixed before any change and never by frame:

* **same-session held-out** -- within each solo demo clip, candidates whose
  onset falls in the second half of the clip. Neighbouring frames of one cast
  stay on one side because a cast lives inside one contiguous block. This is
  not generalisation: the same clip, map and capture supply both halves.
* **same-session dev** -- the first half of each clip.
* **match transfer** -- labelled match sessions, scored only.

`--gate agent` passes each session's witnessed ability vocabulary to the
classifier: the solo demo's tagged agent, or the stored scoreboard lineup for
a match. The vocabulary comes from `lineup.ability_label`, so no ability name
is restated here. Each candidate yields one of: correct, wrong (a name that is
not the label), refused (null with a reason), and, for a candidate the player
marked not an ability, false_name or refused.

The tool decodes one frame per candidate from the source video and keeps no
pixels: features are cached under the store with the extractor's version.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reticle import metrics  # noqa: E402
from reticle.adjudication import gallery  # noqa: E402
from reticle.adjudication.ability import _components, _labels  # noqa: E402
from reticle.adjudication.identity import side_candidates  # noqa: E402
from reticle.lineup import ability_label, load_lineup  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

EVAL_VERSION = "ability-glyph-eval-0.1.0"
#: Onset frames catch an effect fading in; 150 ms later it is drawn.
OFFSET_MS = 150.0
MIN_SIDE = 32
PAD = 8
DEMO_FLAGS = {"ability-demo", "custom-game", "infinite-abilities", "spectator",
              "spaced-casts", "stationary-at-casts"}


def _manifest(root: Path, sid: str) -> dict:
    return json.loads((root / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))


def demo_agent(manifest: dict) -> str | None:
    tags = manifest.get("tags") or []
    if "ability-demo" not in tags:
        return None
    agents = [t for t in tags if ":" not in t and t not in DEMO_FLAGS]
    if len(agents) != 1:
        return None
    # Manifest tags are lowercase and unpunctuated (`kayo`); the reference
    # catalogue keys agents by display name (`KAY/O`).
    catalogue = json.loads((Path(DEFAULT_STORE) / "reference" / "abilities.json")
                           .read_text(encoding="utf-8"))["agents"]
    fold = {"".join(ch for ch in name.casefold() if ch.isalnum()): name for name in catalogue}
    return fold.get(agents[0])


def lineup_agents(root: Path, sid: str) -> tuple[list[str] | None, str | None]:
    """Every agent either side may field, from `lineup.load_lineup`.

    A refused slot's best guess enters as a rival, as `side_candidates` rules;
    a blind slot leaves the vocabulary incomplete, so gating refuses.
    """
    got = load_lineup(sid, root)
    if not got:
        return None, "no stored lineup"
    agents = []
    for side, rows in (got.get("sides") or {}).items():
        split = side_candidates(rows)
        if split["blind"]:
            return None, f"blind lineup slot on {side}; vocabulary incomplete"
        agents += split["named"] + split["rivals"]
    return sorted(set(agents)), None


def vocabulary(root: Path, agents: list[str]) -> set[str]:
    out = set()
    for agent in agents:
        for key in ("C", "Q", "E", "X"):
            label = ability_label(agent, key, root)
            if label:
                out.add(label)
    return out


def crop(frame, comp: dict, roi: list[int]):
    x0, y0 = roi[0], roi[1]
    box = comp.get("box") or [comp["x"] - 8, comp["y"] - 8, 16, 16]
    side = max(MIN_SIDE, max(int(box[2]), int(box[3])) + PAD)
    cx, cy = int(comp["x"]) + x0, int(comp["y"]) + y0
    half = side // 2
    h, w = frame.shape[:2]
    ya, yb, xa, xb = max(0, cy - half), min(h, cy + half), max(0, cx - half), min(w, cx + half)
    return frame[ya:yb, xa:xb]


def features(root: Path, comps: list[dict]) -> dict[str, dict]:
    """Glyph features per component, decoded once and cached without pixels."""
    cache_path = root / "analysis" / "ability-glyph-eval" / "features.jsonl"
    cache = {}
    if cache_path.is_file():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("eval_version") == EVAL_VERSION:
                cache[row["component_id"]] = row
    todo = defaultdict(list)
    for comp in comps:
        if comp["component_id"] not in cache:
            todo[comp["session_id"]].append(comp)
    new = []
    for sid, rows in sorted(todo.items()):
        manifest = _manifest(root, sid)
        cap = cv2.VideoCapture(manifest["source"]["path"])
        for comp in sorted(rows, key=lambda c: c["observed_t_ms"]):
            cap.set(cv2.CAP_PROP_POS_MSEC, comp["observed_t_ms"] + OFFSET_MS)
            ok, frame = cap.read()
            roi = comp["raw"].get("roi")
            patch = crop(frame, comp, roi) if ok and roi else None
            feats = gallery.extract_glyph_features(patch) if patch is not None else {}
            row = {"component_id": comp["component_id"], "eval_version": EVAL_VERSION,
                   "features": feats, "shape": list(patch.shape[:2]) if patch is not None else None,
                   "refusal": None if feats else "frame or roi unavailable"}
            cache[comp["component_id"]] = row
            new.append(row)
        cap.release()
    if new:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("a", encoding="utf-8") as fh:
            for row in new:
                fh.write(json.dumps(row) + "\n")
    return cache


def outcome(comp: dict, result: dict) -> str:
    predicted = result.get("ability_id")
    if comp["label_state"] == "clutter":
        return "refused_clutter" if predicted is None else "false_name"
    if predicted is None:
        return "refused"
    return "correct" if predicted == comp["label_ability_id"] else "wrong"


def classify_features(feats: dict, allowed: set[str] | None) -> dict:
    """Run the owner's classifier on cached features through a synthetic call.

    The owner classifies patches; re-extracting from a stored feature dict is
    done by `gallery.classify_glyph_features`.
    """
    if allowed is None:
        return gallery.classify_glyph_features(feats)
    return gallery.classify_glyph_features(feats, allowed=allowed)


def run(root: Path, gate: str | None) -> dict:
    comps = [c for c in _components(root, _labels(root))
             if c["label_state"] in ("named", "clutter")]
    feats = features(root, comps)
    split_of, vocab_of, reasons = {}, {}, Counter()
    for sid in sorted({c["session_id"] for c in comps}):
        manifest = _manifest(root, sid)
        agent = demo_agent(manifest)
        if agent:
            split_of[sid] = "demo"
            vocab_of[sid] = vocabulary(root, [agent])
        else:
            split_of[sid] = "match"
            agents, why = lineup_agents(root, sid)
            vocab_of[sid] = vocabulary(root, agents) if agents else None
            if why:
                reasons[f"{sid}: {why}"] += 0
    counts = defaultdict(Counter)
    rows = []
    for comp in comps:
        sid = comp["session_id"]
        row = feats[comp["component_id"]]
        if not row["features"]:
            reasons[row["refusal"]] += 1
            continue
        if split_of[sid] == "demo":
            duration = float(_manifest(root, sid)["source"]["duration_ms"])
            split = "held_out" if comp["observed_t_ms"] >= duration / 2 else "dev"
        else:
            split = "match"
        allowed = vocab_of[sid] if gate == "agent" else None
        if gate == "agent" and allowed is None:
            reasons["no stored lineup for this match"] += 1
            continue
        result = classify_features(row["features"], allowed)
        kind = outcome(comp, result)
        counts[split][kind] += 1
        rows.append({"component_id": comp["component_id"], "split": split,
                     "label": comp["label_ability_id"] or comp["label_state"],
                     "predicted": result.get("ability_id"), "outcome": kind,
                     "refusal_reason": result.get("refusal_reason")})
    summary = {}
    for split, c in sorted(counts.items()):
        named = c["correct"] + c["wrong"] + c["refused"]
        summary[split] = {**dict(c), "named": named,
                          "accuracy_named": round(c["correct"] / named, 3) if named else None,
                          "wrong_rate_named": round(c["wrong"] / named, 3) if named else None}
        metrics.record("ability_glyph_eval", part=f"{gate or 'ungated'}-{split}", session="",
                       values=summary[split],
                       deps={"eval": EVAL_VERSION, "classifier": gallery.GLYPH_CLASSIFIER_VERSION,
                             "gate": gate or "none", "eval_set": "named+clutter, all origins"},
                       context={"skipped": dict(reasons)})
    return {"summary": summary, "skipped": dict(reasons), "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--gate", choices=("agent",), default=None)
    parser.add_argument("--rows", action="store_true", help="print every scored row")
    args = parser.parse_args(argv)
    result = run(Path(args.store).resolve(), args.gate)
    if not args.rows:
        result.pop("rows")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
