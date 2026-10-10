"""Ability component, entity-grouping, and property hypotheses.

This is milestone C of ``docs/ABILITY_ENTITY_INFERENCE_DESIGN.md``.  It creates
alternatives for the match-wide adjudicator; it is not a final classifier.
Human component identity can support a parent edge.  It cannot prove that
several components form one physical entity.

Owns [owns:ability-hypothesis].

It also joins the minimap ability discs into tracks, `disc_tracks` [owns:ability-disc-track]
(stage 3 of `docs/MINIMAP_GLYPH_CHANNEL.md`, "Disc tracks"): pure over the
stored `ability_glyph` disc rows, whose `rests_on` carries the proposer's
verify link (`ability_icons.verified_continuations`), and the stored
`ability_icon` verify rows, which say why a track ended. It reads no pixels
and names nothing.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from ..ability_timeline import build_timeline


#: 0.3.1 (2026-10-09): Dark Cover's origin driver is fixed, not global.
ABILITY_ENTITY_VERSION = "ability-entities-0.3.1"
#: Refuses a candidate that is the team's drawn light. Decided here from stored
#: `ability_light` evidence and the stored `team_vision`; the reader stores the
#: raw lit decision and decides nothing.
#: 0.3.0 (2026-09-28): a sliver is witnessed by the stored team vision, not a
#: self raycast restated here with jitter, both lobes and relaxed walls.
LIGHT_REFUSAL_VERSION = "ability-light-refusal-0.3.0"
LIT_SHARE_MIN = 0.6
#: A sliver the clean mask's opening starves: raw lit over this share of the
#: box's known floor, and inside the team's adjudicated vision over
#: `VISION_SHARE_MIN` of it.
RAW_LIT_MIN = 0.35
VISION_SHARE_MIN = 0.20


def _vision_frames(root: Path, sid: str) -> tuple[dict, list, float | None]:
    """Stored `team_vision` frame rows by time, the sorted times, and the cache rate."""
    rows = _jsonl(root / "events" / "team_vision" / f"{sid}.jsonl")
    hz = next((r.get("cache_hz") for r in rows if r.get("kind") == "coverage"), None)
    frames = {float(r["t_ms"]): r for r in rows if r.get("kind") == "frame"}
    return frames, sorted(frames), hz


def light_applies(store, session_id: str) -> tuple[str, str | None]:
    """Whether `reticle ability-light` has any instant to read on a session:
    ("applies", None) where `_components` holds a detector candidate or a
    human label of it, else ("not_applicable", why). The command reads the
    light at those instants only, so a session with none is never its work."""
    root = Path(store.root)
    if any(c["session_id"] == session_id for c in _components(root, _labels(root))):
        return "applies", None
    return ("not_applicable", "no_ability_candidates: no detector candidate or label in "
            "labels/ability_candidates or labels/ability, so `reticle ability-light` reads "
            "nothing")


def light_refusals(root: Path, components: list[dict]) -> dict[str, dict]:
    """Decide, per component, whether its box is the team's drawn light.

    Refuses when `lighting.clean_lit`, rebuilt from the stored raw decision,
    covers at least `LIT_SHARE_MIN` of the box. The opening in `clean_lit`
    starves a cone narrowed to a sliver against a wall; such a box is refused
    when the raw decision covers `RAW_LIT_MIN` of it AND the team's stored
    adjudicated vision (`reticle vision`, owned by `team_vision`) covers
    `VISION_SHARE_MIN` of it at the nearest stored frame within one cache
    period. A dark object in the box is never refused.

    **Order.** This rule reads the vision at the candidate's instant; the
    vision reads no ability entity. When smokes block the vision's rays, the
    vision at t may consume only entities accepted before t, so the loop breaks
    by time and nothing iterates. See `team_vision`.

    Every decision records its `basis`, and a missing vision row is `unread`
    with a reason, not a pass.
    """
    import numpy as np

    from .. import geometry, lighting

    out: dict[str, dict] = {}
    by_session = defaultdict(list)
    for c in components:
        by_session[c["session_id"]].append(c)
    for sid, rows in by_session.items():
        frames = {float(r["t_ms"]): r for r in _jsonl(root / "events" / "ability_light" / f"{sid}.jsonl")
                  if r.get("kind") == "frame"}
        geo = geometry.path_of(sid, root)
        if not frames or geo is None or not geo.is_file():
            for c in rows:
                out[c["component_id"]] = {"status": "unread",
                                          "reason": "no_light_evidence" if not frames else "no_geometry"}
            continue
        with np.load(geo) as z:
            ref = lighting.reference(z)
        vision, vision_t, vision_hz = _vision_frames(root, sid)
        vision_t = np.asarray(vision_t, float)
        max_dt = 1000.0 / float(vision_hz) if vision_hz else 0.0

        cache, vcache = {}, {}
        for c in rows:
            frame = frames.get(float(c["observed_t_ms"]))
            if ref is None or frame is None or frame.get("raw_lit") is None:
                out[c["component_id"]] = {"status": "unread", "reason": (
                    "no_lighting_reference" if ref is None else
                    "no_light_frame" if frame is None else frame.get("reason"))}
                continue
            t = float(c["observed_t_ms"])
            if t not in cache:
                raw_mask = lighting.unpack_mask(frame["raw_lit"])
                raw_dark = lighting.unpack_mask(frame["raw_dark"]) if frame.get("raw_dark") else None
                clean_mask = lighting.clean_lit(raw_mask, ref)
                cache[t] = (raw_mask, raw_dark, clean_mask)
            raw_lit, raw_dark, clean_lit = cache[t]
            bx, by, bw, bh = c.get("box") or [int(c["x"]) - 6, int(c["y"]) - 6, 12, 12]
            win = (slice(max(0, by), by + bh), slice(max(0, bx), bx + bw))
            known = ref.known[win]
            if not known.any():
                out[c["component_id"]] = {"status": "unread", "reason": "box_off_known_floor"}
                continue
            clean_share = float(clean_lit[win][known].mean())
            raw_share = float(raw_lit[win][known].mean())
            is_dark = bool(raw_dark[win][known].any()) if raw_dark is not None else False

            # The team's vision at the nearest stored frame, or why there is none.
            seen = {"status": "unread", "reason": "no_team_vision"}
            if vision_t.size:
                j = int(np.argmin(np.abs(vision_t - t)))
                dt = float(vision_t[j] - t)
                row = vision[float(vision_t[j])]
                if abs(dt) > max_dt:
                    seen = {"status": "unread", "reason": "no_vision_frame_near"}
                elif row.get("observable") is None:
                    seen = {"status": "unread", "reason": f"widget_{row.get('widget')}",
                            "dt_ms": round(dt, 1)}
                else:
                    key = float(vision_t[j])
                    if key not in vcache:
                        vcache[key] = lighting.unpack_mask(row["observable"])
                    share = float(vcache[key][win][known].mean())
                    seen = {"status": "read", "share": round(share, 3), "dt_ms": round(dt, 1),
                            "version": row.get("team_vision_version")}

            basis = None
            if is_dark:
                basis = None
            elif clean_share >= LIT_SHARE_MIN:
                basis = "clean_lit"
            elif (raw_share >= RAW_LIT_MIN and seen["status"] == "read"
                  and seen["share"] >= VISION_SHARE_MIN):
                basis = "raw_lit_in_team_vision"
            refused = basis is not None
            out[c["component_id"]] = {
                "status": "refused" if refused else "passed",
                "reason": "drawn_light" if refused else None,
                "basis": basis, "dark": is_dark,
                "lit_share": round(clean_share, 3),
                "raw_lit_share": round(raw_share, 3),
                "team_vision": seen,
                "rule_version": LIGHT_REFUSAL_VERSION}
    return out


ONSET_GROUP_VERSION = "ability-onset-group-0.1.0"
PERSISTENCE_GROUP_VERSION = "ability-persistence-group-0.1.0"
BEARING_GROUP_VERSION = "ability-bearing-group-0.1.0"
PARENT_PRE_MS = 2000.0
PARENT_POST_MS = 6000.0
ONSET_MS = 300.0
DIST_PX = 60.0
BEARING_TOL_DEG = 15.0
ORPHAN_GAP_MS = 3000.0
ORPHAN_DIST_PX = 120.0
#: "The same place" for an object that does not translate. Tight on purpose: a
#: second device deployed nearby is a different entity, and only a placed
#: ability qualifies at all.
PERSIST_DIST_PX = 12.0

# Versioned domain hypotheses already recorded by the entity model.  These are
# candidate factors until the recording patch and source evidence validate them.
PARAMETER_RULES = {
    "killjoy:alarmbot": {"origin_driver": "enemy-reactive", "bearing_driver": "absent", "extent": "none"},
    "killjoy:turret": {"origin_driver": "fixed", "bearing_driver": "enemy-reactive", "extent": "none"},
    "sova:owl drone": {"origin_driver": "piloted", "bearing_driver": "piloted", "extent": "none"},
    "tejo:stealth drone": {"origin_driver": "piloted", "bearing_driver": "piloted", "extent": "none"},
    "fade:prowler": {"origin_driver": "piloted", "bearing_driver": "piloted", "extent": "none"},
    "skye:trailblazer": {"origin_driver": "piloted", "bearing_driver": "piloted", "extent": "none"},
    "skye:guiding light": {"origin_driver": "piloted", "bearing_driver": "piloted", "extent": "none"},
    "cypher:spycam": {"origin_driver": "fixed", "bearing_driver": "aimed", "extent": "none"},
    "breach:rolling thunder": {"origin_driver": "fixed", "bearing_driver": "fixed", "extent": "trajectory"},
    "cypher:trapwire": {"origin_driver": "fixed", "bearing_driver": "fixed", "extent": "extending"},
    "phoenix:blaze": {"origin_driver": "fixed", "bearing_driver": "fixed", "extent": "freeform"},
    "viper:toxic screen": {"origin_driver": "fixed", "bearing_driver": "fixed", "extent": "extending"},
    "sova:hunter's fury": {"origin_driver": "fixed", "bearing_driver": "fixed", "extent": "trajectory"},
    "viper:poison cloud": {"origin_driver": "fixed", "bearing_driver": "absent", "extent": "radius"},
    "viper:viper's pit": {"origin_driver": "fixed", "bearing_driver": "absent", "extent": "radius"},
    "jett:cloudburst": {"origin_driver": "fixed", "bearing_driver": "absent", "extent": "radius"},
    "brimstone:sky smoke": {"origin_driver": "fixed", "bearing_driver": "absent", "extent": "radius"},
    # Placed within 80 m of Omen, not global (player, 2026-10-09)
    # [domain:abilities/omen-dark-cover-body-relative-placement].
    "omen:dark cover": {"origin_driver": "fixed", "bearing_driver": "absent", "extent": "radius"},
}


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _key(row: dict) -> tuple:
    return (row.get("session_id"), row.get("t_ms"), row.get("x"), row.get("y"))


def _labels(root: Path) -> dict[tuple, dict]:
    """Last append-only answer wins for each preserved source coordinate."""
    out = {}
    folder = root / "labels" / "ability"
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        if ".bak" in path.name:
            continue
        for line_no, row in enumerate(_jsonl(path), 1):
            row = dict(row, _source_path=path.relative_to(root).as_posix(),
                       _source_line=line_no)
            out[_key(row)] = row
    return out


def _label_state(label: dict | None) -> str:
    if not label:
        return "unreviewed"
    if label.get("not_ability"):
        return "clutter"
    if label.get("uncertain"):
        return "uncertain"
    if label.get("agent") and label.get("ability"):
        return "named"
    return "generic" if label.get("category_id") else "unreviewed"


def _ability_id(label: dict | None) -> str | None:
    if label and label.get("agent") and label.get("ability"):
        return f"{label['agent'].casefold()}:{label['ability'].casefold()}"
    return None


def _components(root: Path, labels: dict[tuple, dict]) -> list[dict]:
    """Detector candidates and human labels are both components.

    A label whose coordinates no detector candidate reproduces is still a
    human observation of a thing on the minimap.  Joining on the exact key
    only, and emitting the remainder as ``human_label`` components, keeps the
    corroborated and uncorroborated cases distinguishable without inventing
    an agreement a fuzzy join would manufacture.
    """
    out, consumed = [], set()
    folder = root / "labels" / "ability_candidates"
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        if ".bak" in path.name or ".prefilter" in path.name:
            continue
        sid = path.stem
        for line_no, raw in enumerate(_jsonl(path), 1):
            key = (sid, raw.get("t_ms"), raw.get("x"), raw.get("y"))
            label = labels.get(key)
            if label:
                consumed.add(key)
            out.append({
                "component_id": f"component:{sid}:{raw.get('t_ms')}:{raw.get('x')}:{raw.get('y')}",
                "session_id": sid, "origin": "detector_candidate",
                "observed_t_ms": float(raw.get("t_ms", 0)),
                "observed_end_ms": float(raw.get("t_ms", 0)) + float(raw.get("duration_ms") or 0),
                "x": raw.get("x"), "y": raw.get("y"), "box": raw.get("box"),
                "n_observations": raw.get("n_observations"),
                "source_evidence": [{"path": path.relative_to(root).as_posix(),
                                     "record": line_no}],
                "label_evidence": ({"path": label["_source_path"],
                                    "record": label["_source_line"]} if label else None),
                "label_state": _label_state(label),
                "label_ability_id": _ability_id(label),
                "category_id": label.get("category_id") if label else None,
                "raw": raw,
            })
    for key, label in labels.items():
        if key in consumed:
            continue
        sid, t_ms, x, y = key
        out.append({
            "component_id": f"component:{sid}:{t_ms}:{x}:{y}",
            "session_id": sid, "origin": "human_label",
            "observed_t_ms": float(t_ms or 0),
            "observed_end_ms": float(t_ms or 0) + float(label.get("duration_ms") or 0),
            "x": x, "y": y, "box": label.get("box"),
            "n_observations": label.get("n_observations"),
            "source_evidence": [{"path": label["_source_path"],
                                 "record": label["_source_line"]}],
            "label_evidence": {"path": label["_source_path"],
                               "record": label["_source_line"]},
            "label_state": _label_state(label),
            "label_ability_id": _ability_id(label),
            "category_id": label.get("category_id"),
            "raw": {k: v for k, v in label.items() if not k.startswith("_")},
        })
    return sorted(out, key=lambda r: (r["session_id"], r["observed_t_ms"], r["component_id"]))


def _distance(a: dict, b: dict) -> float:
    return math.hypot(float(a["x"]) - float(b["x"]), float(a["y"]) - float(b["y"]))


def onset_groups(rows: list[dict]) -> list[list[dict]]:
    groups = []
    for row in sorted(rows, key=lambda r: (r["observed_t_ms"], r["component_id"])):
        for group in groups:
            if (abs(group[0]["observed_t_ms"] - row["observed_t_ms"]) <= ONSET_MS
                    and any(_distance(row, member) <= DIST_PX for member in group)):
                group.append(row)
                break
        else:
            groups.append([row])
    return groups


def persistence_groups(rows: list[dict]) -> list[list[dict]]:
    """Observations at one position are one entity, however far apart in time.

    A placed ability does not translate, so re-observing a thing where a thing
    already was is the same thing in a later phase -- not a second deployment
    and not a rebirth. Onset grouping cannot say this: it needs a shared onset
    within 300 ms, which a transformation twenty seconds later does not have.

    Transitively linked, so a slow drift across several observations stays one
    group rather than breaking at whichever pair first exceeds the radius.
    """
    groups: list[list[dict]] = []
    for row in sorted(rows, key=lambda r: (r["observed_t_ms"], r["component_id"])):
        for group in groups:
            if any(_distance(row, member) <= PERSIST_DIST_PX for member in group):
                group.append(row)
                break
        else:
            groups.append([row])
    return groups


def bearing_groups(rows: list[dict]) -> list[list[dict]]:
    """Order-independent circular grouping around the earliest component."""
    rows = sorted(rows, key=lambda r: (r["observed_t_ms"], r["component_id"]))
    if len(rows) < 2:
        return [rows] if rows else []
    origin = rows[0]
    angles = sorted(((math.degrees(math.atan2(r["y"] - origin["y"],
                                              r["x"] - origin["x"])) % 360.0, r)
                     for r in rows[1:]), key=lambda pair: (pair[0], pair[1]["component_id"]))
    if not angles:
        return [[origin]]
    gaps = [(angles[i + 1][0] - angles[i][0], i) for i in range(len(angles) - 1)]
    gaps.append((360.0 - angles[-1][0] + angles[0][0], len(angles) - 1))
    cuts = {i for gap, i in gaps if gap > BEARING_TOL_DEG}
    if not cuts:
        return [[origin] + [row for _, row in angles]]
    start = (max(cuts) + 1) % len(angles)
    groups, current = [], []
    for offset in range(len(angles)):
        idx = (start + offset) % len(angles)
        current.append(angles[idx][1])
        if idx in cuts:
            groups.append([origin] + current)
            current = []
    if current:
        groups.append([origin] + current)
    return groups


def _mean_bearing(group: list[dict]) -> float | None:
    if len(group) < 2:
        return None
    origin = group[0]
    angles = [math.atan2(r["y"] - origin["y"], r["x"] - origin["x"])
              for r in group[1:]]
    return round(math.degrees(math.atan2(sum(math.sin(a) for a in angles),
                                         sum(math.cos(a) for a in angles))), 1)


def _time_clusters(rows: list[dict], gap_ms: float = ORPHAN_GAP_MS) -> list[list[dict]]:
    """Components that could plausibly be one object share a clip.

    Time alone is not enough. Two components a human has given DIFFERENT ability
    names cannot be one entity -- the label already settles it -- and two objects
    on opposite sides of the map are not one either. Grouping them anyway
    produces a question with no true answer, which is what the first real pass
    hit on its first screen.
    """
    clusters = []
    for row in sorted(rows, key=lambda r: (r["observed_t_ms"], r["component_id"])):
        for cluster in clusters:
            last = cluster[-1]
            named = {c["label_ability_id"] for c in cluster if c["label_ability_id"]}
            mine = row["label_ability_id"]
            if named and mine and mine not in named:
                continue
            if (row["observed_t_ms"] - last["observed_t_ms"] <= gap_ms
                    and _distance(row, last) <= ORPHAN_DIST_PX):
                cluster.append(row)
                break
        else:
            clusters.append([row])
    return clusters


def _orphan_reason(parents: list, contradictions: list, session_uses: list,
                   same_ability: list, named: str | None, label_state: str) -> str | None:
    """Why a component has no parent.  A silent use channel and a use just
    outside the window are different findings, and neither is a group.
    A component a human called clutter is answered, not orphaned."""
    if parents or label_state == "clutter":
        return None
    if contradictions:
        return "only_contradicted_parents"
    if not session_uses:
        return "no_use_claims_in_session"
    if named and not same_ability:
        return "no_use_claim_of_named_ability"
    return "outside_parent_window"


def build_entities(root: str | Path) -> dict:
    root = Path(root).resolve()
    timeline = build_timeline(root)
    labels = _labels(root)
    components = _components(root, labels)
    light = light_refusals(root, components)
    # A human name outranks the light; the disagreement is kept, not resolved.
    refused = {cid for cid, v in light.items() if v["status"] == "refused"}
    refused -= {c["component_id"] for c in components if c["label_state"] == "named"}
    uses = timeline["use_claims"]
    uses_by_session = defaultdict(list)
    for use in uses:
        uses_by_session[use["session_id"]].append(use)

    import numpy as np

    series_cache = {}
    for sid in uses_by_session:
        series_path = root / "series" / f"{sid}.npz"
        series_cache[sid] = np.load(series_path) if series_path.is_file() else None

    def _caster_pos(sid: str, t_ms: float) -> tuple[float | None, float | None]:
        z = series_cache.get(sid)
        if z is None or "self_x" not in z or "t_ms" not in z:
            return None, None
        t_arr = z["t_ms"]
        idx = int(np.argmin(np.abs(t_arr - t_ms)))
        if abs(t_arr[idx] - t_ms) > 1000.0:
            return None, None
        cx, cy = float(z["self_x"][0, idx]), float(z["self_y"][0, idx])
        if math.isnan(cx) or math.isnan(cy) or cx <= 0 or cy <= 0:
            return None, None
        return cx, cy

    time_counts = Counter((u["session_id"], u["observed_t_ms"]) for u in uses)

    component_claims = []
    compatible_by_use = defaultdict(list)
    for component in components:
        parents = []
        contradictions = []
        is_light = component["component_id"] in refused
        for use in ([] if is_light else uses_by_session.get(component["session_id"], [])):
            dt = component["observed_t_ms"] - use["observed_t_ms"]
            if not -PARENT_PRE_MS <= dt <= PARENT_POST_MS:
                continue
            named = component.get("label_ability_id")
            if named and named != use.get("ability_id"):
                contradictions.append({"use_claim_id": use["use_claim_id"],
                                       "reason": "human_named_other_ability"})
                continue
            if component["label_state"] == "clutter":
                contradictions.append({"use_claim_id": use["use_claim_id"],
                                       "reason": "human_marked_clutter"})
                continue

            agent = (use.get("agent") or "").lower()
            ability = (use.get("ability") or "").lower()
            key = (agent, ability)
            status = "supported" if named == use.get("ability_id") else "candidate"

            is_batch = (use.get("status") == "suspect" and
                        time_counts[(use["session_id"], use["observed_t_ms"])] >= BATCH_DESATURATION_THRESHOLD)
            if is_batch and status != "supported":
                contradictions.append({"use_claim_id": use["use_claim_id"],
                                       "reason": "batch_desaturation_artefact"})
                continue

            if key in NO_MINIMAP_ABILITIES and status != "supported":
                contradictions.append({"use_claim_id": use["use_claim_id"],
                                       "reason": "domain_non_minimap_ability"})
                continue

            if key in (LOCAL_PLACEMENT_ABILITIES | AREA_SMOKE_ABILITIES):
                cx, cy = _caster_pos(use["session_id"], use["observed_t_ms"])
                if cx is not None and cy is not None:
                    d = math.hypot(component["x"] - cx, component["y"] - cy)
                    if d > PLACEMENT_REACH_PX and status != "supported":
                        contradictions.append({"use_claim_id": use["use_claim_id"],
                                               "reason": "outside_placement_reach"})
                        continue

            parents.append({"use_claim_id": use["use_claim_id"], "status": status,
                            "use_claim_status": use.get("status"),
                            "reason": ("matching_human_component_identity" if status == "supported"
                                       else "temporal_compatibility")})
            compatible_by_use[use["use_claim_id"]].append(component)
        session_uses = uses_by_session.get(component["session_id"], [])
        named = component.get("label_ability_id")
        same = [u for u in session_uses if u.get("ability_id") == named] if named else session_uses
        nearest = (min(same, key=lambda u: (abs(component["observed_t_ms"] - u["observed_t_ms"]),
                                            u["use_claim_id"])) if same else None)
        component_claims.append({
            "component_id": component["component_id"],
            "session_id": component["session_id"],
            "origin": component["origin"],
            "label_state": component["label_state"],
            "possible_parents": sorted(parents, key=lambda r: r["use_claim_id"]),
            "contradicted_parents": sorted(contradictions, key=lambda r: r["use_claim_id"]),
            "orphan_reason": (None if is_light else
                              _orphan_reason(parents, contradictions, session_uses, same,
                                             named, component["label_state"])),
            "light": light.get(component["component_id"]),
            "refusal": light[component["component_id"]]["reason"] if is_light else None,
            "nearest_use_claim_id": nearest["use_claim_id"] if nearest else None,
            "nearest_use_dt_ms": (round(component["observed_t_ms"] - nearest["observed_t_ms"], 1)
                                  if nearest else None),
            "clutter_alternative": component["label_state"] != "named",
            "unobserved_prior_use_alternative": component["label_state"] != "named",
            "source_evidence": component["source_evidence"],
            "label_evidence": component["label_evidence"],
        })

    hypotheses, properties, review = [], [], []
    for use in uses:
        candidates = compatible_by_use.get(use["use_claim_id"], [])
        supported = [c for c in candidates if c.get("label_ability_id") == use.get("ability_id")]
        agent = (use.get("agent") or "").lower()
        ability = (use.get("ability") or "").lower()
        key = (agent, ability)
        is_batch = (use.get("status") == "suspect" and
                    time_counts[(use["session_id"], use["observed_t_ms"])] >= BATCH_DESATURATION_THRESHOLD)

        if supported:
            null_status = "contradicted"
            null_reason = "matching_human_component_exists"
        elif key in NO_MINIMAP_ABILITIES:
            null_status = "confirmed_absent"
            null_reason = "domain_invar_no_minimap_entity"
        elif is_batch:
            null_status = "refused"
            null_reason = "simultaneous_multi_slot_desaturation_artefact"
        else:
            null_status = "candidate"
            null_reason = "ability_may_have_no_minimap_child_or_reader_missed_it"

        hypotheses.append({
            "hypothesis_id": f"entity:null:{use['use_claim_id']}",
            "use_claim_id": use["use_claim_id"], "relation": "spawned_by",
            "grouping_method": "no_observed_spatial_child",
            "component_ids": [], "status": null_status,
            "status_reason": null_reason,
        })
        methods = [("onset_proximity", ONSET_GROUP_VERSION, onset_groups(candidates))]
        rule = PARAMETER_RULES.get(use.get("ability_id"))
        if rule and rule["extent"] in ("extending", "trajectory"):
            methods.append(("bearing", BEARING_GROUP_VERSION, bearing_groups(candidates)))
        # A piloted object translates for its whole life, so position
        # persistence would collapse a flight path into a point. Every other
        # deployed thing holds still, which is what makes the alternative sound.
        if not (rule and rule["origin_driver"] == "piloted"):
            methods.append(("position_persistence", PERSISTENCE_GROUP_VERSION,
                            persistence_groups(candidates)))
        seen_groups = set()
        for method, version, groups in methods:
            for group in groups:
                members = tuple(sorted(c["component_id"] for c in group))
                signature = (method, members)
                if not members or signature in seen_groups:
                    continue
                seen_groups.add(signature)
                human_supported = [c for c in group if c in supported]
                hid = hashlib.sha256((use["use_claim_id"] + method + "|".join(members)).encode()).hexdigest()[:16]
                hypotheses.append({
                    "hypothesis_id": f"entity:{hid}",
                    "use_claim_id": use["use_claim_id"], "relation": "spawned_by",
                    "grouping_method": method, "grouping_version": version,
                    "component_ids": list(members),
                    "status": "supported_components" if human_supported else "proposal",
                    "status_reason": ("contains_matching_human_named_components" if human_supported
                                       else "components_only_temporally_compatible"),
                    "grouping_resolved": len(group) == 1,
                    "grouping_limit": (None if len(group) == 1 else
                                        "component identity does not prove common physical entity"),
                    "treats_appearance_change_as": (
                        "a later PHASE of one entity" if method == "position_persistence"
                        else "a separate observation, which splits a transforming entity"),
                })
                properties.extend(_properties(use, group, f"entity:{hid}", method, rule))

        skip_review = (not candidates) and (key in NO_MINIMAP_ABILITIES or is_batch)
        if not skip_review and (len(candidates) != 1 or not supported):
            review.append({
                "review_id": f"ability-group:{use['use_claim_id']}",
                "session_id": use["session_id"], "use_claim_id": use["use_claim_id"],
                "ability_id": use.get("ability_id"),
                "clip_start_ms": max(0.0, use["observed_t_ms"] - PARENT_PRE_MS),
                "clip_end_ms": use["observed_t_ms"] + PARENT_POST_MS,
                "component_ids": sorted(c["component_id"] for c in candidates),
                "question": "Which ringed components are parts of the same entity, separate entities, clutter, or missing?",
                "classes": ["same_entity", "separate_entities", "clutter", "missing_component", "other", "unsure"],
                "status": "unreviewed",
            })

    parented = {r["component_id"] for r in component_claims if r["possible_parents"]}
    orphans = [c for c in components
               if c["component_id"] not in parented and c["label_state"] != "clutter"
               and c["component_id"] not in refused]
    reason_by_id = {r["component_id"]: r["orphan_reason"] for r in component_claims}
    by_session = defaultdict(list)
    for component in orphans:
        by_session[component["session_id"]].append(component)
    for sid, rows in sorted(by_session.items()):
        for cluster in _time_clusters(rows):
            abilities = sorted({c["label_ability_id"] for c in cluster if c["label_ability_id"]})
            review.append({
                "review_id": f"ability-orphan:{sid}:{int(cluster[0]['observed_t_ms'])}",
                "session_id": sid, "use_claim_id": None,
                "ability_id": abilities[0] if len(abilities) == 1 else None,
                "named_abilities": abilities,
                "clip_start_ms": max(0.0, cluster[0]["observed_t_ms"] - PARENT_PRE_MS),
                "clip_end_ms": max(c["observed_end_ms"] for c in cluster) + PARENT_POST_MS,
                "component_ids": sorted(c["component_id"] for c in cluster),
                "orphan_reasons": sorted({reason_by_id[c["component_id"]] for c in cluster
                                          if reason_by_id.get(c["component_id"])}),
                "question": "No ability use was claimed for these components. Did a use occur here that the use channel missed, are they a still-living entity from an earlier use, or clutter?",
                "classes": ["missed_use", "earlier_use_persisting", "clutter", "other", "unsure"],
                "status": "unreviewed",
            })

    orphan_claims = [r for r in component_claims if r["orphan_reason"]]
    summary = {
        "use_claims": len(uses), "components": len(components),
        "components_by_origin": dict(sorted(Counter(c["origin"] for c in components).items())),
        "orphan_components": len(orphan_claims),
        "light_refused": len(refused),
        "light_status": dict(sorted(Counter(v["status"] for v in light.values()).items())),
        "light_refused_but_human_named": sum(
            1 for c in components if c["label_state"] == "named"
            and light.get(c["component_id"], {}).get("status") == "refused"),
        "orphan_reasons": dict(sorted(Counter(r["orphan_reason"] for r in orphan_claims).items())),
        "human_named_without_supported_parent": sum(
            1 for r in component_claims
            if r["label_state"] == "named"
            and not any(p["status"] == "supported" for p in r["possible_parents"])),
        "human_named_components": sum(c["label_state"] == "named" for c in components),
        "human_clutter_components": sum(c["label_state"] == "clutter" for c in components),
        "component_parent_edges": sum(len(r["possible_parents"]) for r in component_claims),
        # A human name matching a claim the reader itself flagged is not the same
        # evidence as one matching a clean claim, and the gate number must not
        # quietly pool them.
        "supported_parent_edges": sum(
            sum(p["status"] == "supported" and p.get("use_claim_status") != "suspect"
                for p in r["possible_parents"]) for r in component_claims),
        "supported_parent_edges_on_suspect_claims": sum(
            sum(p["status"] == "supported" and p.get("use_claim_status") == "suspect"
                for p in r["possible_parents"]) for r in component_claims),
        "entity_hypotheses": len(hypotheses), "property_claims": len(properties),
        "review_windows": len(review),
        "grouping_methods": dict(sorted(Counter(h["grouping_method"] for h in hypotheses).items())),
    }
    return {
        "manifest": {
            "schema_version": 1, "producer_version": ABILITY_ENTITY_VERSION,
            "timeline_version": timeline["manifest"]["producer_version"],
            "store_root": str(root), "summary": summary,
            "limits": [
                "Group hypotheses are alternatives, not final adjudications.",
                "Human component identity does not prove multi-component grouping.",
                "Parent windows are candidate-generation bounds, not ability lifetime laws.",
                "Parameter rules require patch and source validation before becoming hard constraints.",
                "Onset grouping splits an entity that transforms; position persistence keeps "
                "it whole. Both are offered, and they disagree exactly where it matters.",
            ],
        },
        "component_claims": component_claims,
        "entity_hypotheses": sorted(hypotheses, key=lambda r: (r["use_claim_id"], r["hypothesis_id"])),
        "properties": sorted(properties, key=lambda r: (r["hypothesis_id"], r["property"])),
        "review": sorted(review, key=lambda r: (r["session_id"], r["clip_start_ms"])),
    }


def _properties(use: dict, group: list[dict], hypothesis_id: str,
                method: str, rule: dict | None) -> list[dict]:
    source = "human_observed" if any(c["label_state"] == "named" for c in group) else "detector_observed"
    times = [c["observed_t_ms"] for c in group]
    ends = [c["observed_end_ms"] for c in group]
    rows = [
        {"hypothesis_id": hypothesis_id, "property": "existence_interval_ms",
         "value": [min(times), max(ends)], "units": "source_ms", "source_kind": source,
         "status": "observed_components"},
        {"hypothesis_id": hypothesis_id, "property": "component_count",
         "value": len(group), "units": "components", "source_kind": source,
         "status": "observed_components"},
        {"hypothesis_id": hypothesis_id, "property": "origin",
         "value": [group[0]["x"], group[0]["y"]] if method == "bearing" else None,
         "units": "minimap_roi_px", "source_kind": "inferred" if method == "bearing" else "unknown",
         "status": "proposal" if method == "bearing" else "unresolved"},
        {"hypothesis_id": hypothesis_id, "property": "bearing",
         "value": _mean_bearing(group) if method == "bearing" else None,
         "units": "degrees_image_xy", "source_kind": "inferred" if method == "bearing" else "unknown",
         "status": "proposal" if method == "bearing" else "unresolved"},
    ]
    if rule:
        for prop in ("origin_driver", "bearing_driver", "extent"):
            rows.append({
                "hypothesis_id": hypothesis_id, "property": prop,
                "value": rule[prop], "units": None, "source_kind": "reference_derived",
                "status": "domain_hypothesis_needs_patch_validation",
                "rule_scope": use.get("ability_id"),
            })
        if rule.get("extent") == "trajectory":
            rows.append({
                "hypothesis_id": hypothesis_id, "property": "trajectory_schema",
                "value": "beam(x0, y0, theta, L, w)", "units": None,
                "source_kind": "reference_derived",
                "status": "domain_hypothesis_needs_patch_validation",
                "rule_scope": use.get("ability_id"),
            })
    return rows


def write_entities(bundle: dict, out: str | Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("component_claims", "entity_hypotheses", "properties", "review"):
        (out / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in bundle[name]),
            encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(bundle["manifest"], indent=2, sort_keys=True),
                                       encoding="utf-8")
    return out


#: Maximum placement reach in widget pixels from caster to a placed device or smoke.
PLACEMENT_REACH_PX = 60.0

#: Standard pre-cast placement preview window (ms).
PLACEMENT_WINDOW_PRE_MS = 2000.0

#: Standard post-cast onset window for devices and smokes (ms).
PLACEMENT_WINDOW_POST_MS = 4000.0

#: Extended window for re-usable or extending abilities (ms).
EXTENDING_WINDOW_POST_MS = 6000.0

#: Threshold of simultaneous slot drops indicating HUD wipe / menu artefact.
BATCH_DESATURATION_THRESHOLD = 3

NO_MINIMAP_ABILITIES = {
    ("jett", "tailwind"), ("jett", "blade storm"), ("skye", "regrowth"),
    ("cypher", "neural theft")
}
EXTENDING_ABILITIES = {
    ("viper", "toxic screen"), ("sova", "hunter's fury")
}
LOCAL_PLACEMENT_ABILITIES = {
    ("killjoy", "alarmbot"), ("killjoy", "turret"), ("killjoy", "nanoswarm"), ("killjoy", "lockdown"),
    ("viper", "poison cloud"), ("viper", "snake bite"),
    ("cypher", "trapwire"), ("cypher", "spycam"), ("cypher", "cyber cage")
}
AREA_SMOKE_ABILITIES = {
    ("jett", "cloudburst"), ("viper", "poison cloud"), ("viper", "viper's pit")
}
PILOTED_SUMMON_ABILITIES = {
    ("sova", "owl drone"), ("skye", "trailblazer"), ("skye", "guiding light"), ("skye", "seekers")
}
PROJECTILE_REMOTE_ABILITIES = {
    ("sova", "recon bolt"), ("sova", "shock bolt")
}


def predict_ability_births(tray_casts: list[dict],
                           caster_position_fn,
                           candidates: list[dict],
                           agent: str,
                           kit: dict[str, str]) -> list[dict]:
    """Test cross-channel predict-update hypotheses from tray casts to minimap entities.

    Pure over stored observations; decodes no video. Implements context-allowed
    candidate gating and physical invariants:
      1. Batch desaturation (>=3 simultaneous slot drops) is refused as a HUD wipe artefact.
      2. Domain non-minimap abilities (Tailwind, Blade Storm, Regrowth) predict an empty
         candidate set; confirmed absent when no non-clutter candidate is found.
      3. Remote projectiles (Sova bolts) are confirmed remote.
      4. Local devices, area smokes, extending walls, and piloted summons gate candidates
         strictly within placement reach (d <= 60 px) and ability-appropriate time windows.
      5. Unobserved caster position is marked honestly as censored, never guessed.
    """
    time_counts: dict[float, int] = {}
    for c in tray_casts:
        t_s = float(c["t_s"])
        time_counts[t_s] = time_counts.get(t_s, 0) + 1

    out = []
    agent_key = (agent or "").lower()

    for c in tray_casts:
        t_s = float(c["t_s"])
        t_ms = t_s * 1000.0
        slot = c["slot"]
        suspect = bool(c.get("suspect", False))
        ability = kit.get(slot, "Unknown")
        key = (agent_key, ability.lower())

        if suspect and time_counts.get(t_s, 0) >= BATCH_DESATURATION_THRESHOLD:
            out.append({
                "cast": c, "agent": agent, "slot": slot, "ability": ability,
                "status": "fail:batch_desat_wipe",
                "reason": "simultaneous_multi_slot_desaturation_artefact",
                "gated_candidates": [],
            })
            continue

        cx, cy = caster_position_fn(t_ms)
        caster_valid = (cx is not None and cy is not None
                        and not math.isnan(cx) and not math.isnan(cy))

        if key in NO_MINIMAP_ABILITIES:
            near = []
            if caster_valid:
                near = [cd for cd in candidates
                        if abs(float(cd["t_ms"]) - t_ms) <= PLACEMENT_WINDOW_POST_MS
                        and not cd.get("not_ability", False)
                        and cd.get("label_state") != "clutter"
                        and math.hypot(float(cd["x"]) - cx, float(cd["y"]) - cy) <= PLACEMENT_REACH_PX]
            if not near:
                out.append({
                    "cast": c, "agent": agent, "slot": slot, "ability": ability,
                    "status": "pass:confirmed_absent",
                    "reason": "domain_invar_no_minimap_entity",
                    "gated_candidates": [],
                })
            else:
                out.append({
                    "cast": c, "agent": agent, "slot": slot, "ability": ability,
                    "status": "fail:unexpected_candidate",
                    "reason": "candidate_found_for_domain_non_entity",
                    "gated_candidates": near,
                })
            continue

        if key in PROJECTILE_REMOTE_ABILITIES:
            out.append({
                "cast": c, "agent": agent, "slot": slot, "ability": ability,
                "status": "pass:remote_flight",
                "reason": "projectile_lands_remote",
                "gated_candidates": [],
            })
            continue

        if not caster_valid:
            out.append({
                "cast": c, "agent": agent, "slot": slot, "ability": ability,
                "status": "fail:caster_unobserved",
                "reason": "caster_position_missing_or_nan",
                "gated_candidates": [],
            })
            continue

        window_post = EXTENDING_WINDOW_POST_MS if key in EXTENDING_ABILITIES else PLACEMENT_WINDOW_POST_MS
        near = [cd for cd in candidates
                if -PLACEMENT_WINDOW_PRE_MS <= (float(cd["t_ms"]) - t_ms) <= window_post
                and not cd.get("not_ability", False)
                and cd.get("label_state") != "clutter"
                and math.hypot(float(cd["x"]) - cx, float(cd["y"]) - cy) <= PLACEMENT_REACH_PX]

        if near:
            out.append({
                "cast": c, "agent": agent, "slot": slot, "ability": ability,
                "status": "pass:corroborated_birth",
                "reason": "candidates_within_reach",
                "gated_candidates": near,
            })
        else:
            out.append({
                "cast": c, "agent": agent, "slot": slot, "ability": ability,
                "status": "fail:unobserved_birth",
                "reason": "no_candidates_within_reach",
                "gated_candidates": [],
            })
    return out


# ------------------------------------------------------------------ minimap disc tracks

#: A step between two fixes of one track longer than this (px x MapScale.scale)
#: is a stored surprise: the verify bound another object, or a moving one. It
#: is the stage 1 follow's starting reach (`prototypes/minimap_glyph_eval.py`
#: REACH[0], 4 px x scale), a design choice; the verify itself searches only
#: VERIFY_HALF_BASE about its last fix, so a placed icon steps far less.
JUMP_REACH_BASE = 4.0
#: The span over which a track's first-second speed is read (ms after its birth).
FIRST_SECOND_MS = 1000.0
#: Why a track ended, in the order `disc_tracks` decides it.
TRACK_ENDS = ("stream_end", "frame_unread:<reason>", "verify_lost", "verify_held_unbound",
              "no_verify_row")


def disc_tracks(session_id: str, discs: dict, frames: dict, verify: dict | None) -> dict:
    """Join a session's stored minimap ability discs into tracks.

    Pure over stored rows, vectorised (`scipy.sparse.csgraph`):

    - `discs`: arrays over the `ability_glyph` context disc rows, one per
      proposed disc and sample: `t_ms`, `i`, `disc` (its id), `pred` (the
      disc it continues, from its `rests_on`; '' for none), `cx`, `cy`,
      `scale` (MapScale.scale) and `reason` (the reader's gate; '' where
      scored). The link is the proposer's verify, as the reader stored it;
      this function adds no reach of its own, so a gated sample never ends a
      track: a dimmed device stays one object while the verify holds it.
    - `frames`: arrays over the stream's frame rows, `t_ms` and `reason`
      ('' where read).
    - `verify`: arrays over the stored `ability_icon` verify rows, `t_ms` (the
      sample that verified), `of` (the disc's index in the sample before),
      `lost` (neither its live score nor its disabled drawing holds it) and,
      optionally, `disabled` (its disabled drawing holds it,
      `ability_icons.held_disabled`); None where no proposer stream is given.

    Each track stores its path length, its displacement and speed over its
    first second and its lifetime, in crop px and in base px (px over the
    fix's scale). `onset` says why its birth is one: `observed` (the sample
    before was read and continued no disc into it), `after_unread:<reason>`
    or `stream_start`. `end` says why it ended: `verify_lost` (the stored
    verify's `score` is None), `verify_held_unbound`, `frame_unread:<reason>`
    (the next sample is unread: not live, widget not drawn, the round over),
    `no_verify_row` or `stream_end`. A step past JUMP_REACH_BASE x scale is a
    stored surprise (`jump_past_reach`), never a split. A track turns
    disabled without a break: `disabled_ms` is the first fix the verify
    reached through the disabled drawing (the owner's death dims a device,
    player 2026-10-09), else None.

    Returns {"track": per disc row, its track's index; "tracks": one dict per
    track, in birth order}."""
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    t = np.asarray(discs["t_ms"], float)
    n = len(t)
    if n == 0:
        return {"track": np.zeros(0, np.int64), "tracks": []}
    ii = np.asarray(discs["i"], np.int64)
    ids = np.asarray(discs["disc"], object).astype(str)
    pred = np.asarray(discs["pred"], object).astype(str)
    cx = np.asarray(discs["cx"], float)
    cy = np.asarray(discs["cy"], float)
    scale = np.asarray(discs["scale"], float)
    why = np.asarray(discs["reason"], object).astype(str)

    by_id = np.argsort(ids, kind="stable")
    sorted_ids = ids[by_id]
    pos = np.clip(np.searchsorted(sorted_ids, pred), 0, n - 1)
    linked = (pred != "") & (sorted_ids[pos] == pred)
    src = np.flatnonzero(linked)
    dst = by_id[pos[linked]]
    graph = coo_matrix((np.ones(len(src)), (src, dst)), shape=(n, n))
    ncomp, comp = connected_components(graph, directed=False)

    so = np.lexsort((ii, t, comp))
    cs = comp[so]
    starts = np.r_[0, np.flatnonzero(np.diff(cs)) + 1]
    ends = np.r_[starts[1:], n]
    birth, last = so[starts], so[ends - 1]
    nfix = ends - starts
    # Number the tracks in birth order.
    rank = np.lexsort((ii[birth], t[birth]))
    new_of = np.empty(ncomp, np.int64)
    new_of[cs[starts][rank]] = np.arange(ncomp)
    track = new_of[comp]

    seg_of = np.searchsorted(starts, np.arange(n), side="right") - 1
    same = cs[1:] == cs[:-1]
    step = np.hypot(np.diff(cx[so]), np.diff(cy[so]))
    step_base = step / scale[so][1:]
    path_px = np.bincount(seg_of[1:][same], weights=step[same], minlength=ncomp)
    path_base = np.bincount(seg_of[1:][same], weights=step_base[same], minlength=ncomp)
    jump = np.r_[False, same & (step > JUMP_REACH_BASE * scale[so][1:])]
    step = np.r_[0.0, step]

    t0 = t[birth]
    within = (t[so] - t0[seg_of]) <= FIRST_SECOND_MS
    lw = so[np.maximum.reduceat(np.where(within, np.arange(n), -1), starts)]
    disp_px = np.hypot(cx[lw] - cx[birth], cy[lw] - cy[birth])
    disp_base = disp_px / scale[birth]
    dt1 = t[lw] - t0
    speed = np.where(dt1 > 0, disp_base / np.where(dt1 > 0, dt1, 1.0) * 1000.0, np.nan)
    scored = np.add.reduceat((why[so] == "").astype(np.int64), starts)

    ft = np.asarray(frames["t_ms"], float)
    fr = np.asarray(frames["reason"], object).astype(str)
    fo = np.argsort(ft, kind="stable")
    ft, fr = ft[fo], fr[fo]
    nf = len(ft)
    if nf:
        kp = np.searchsorted(ft, t0, side="left") - 1
        rp = fr[np.clip(kp, 0, None)]
        onset = np.where(kp < 0, "stream_start",
                         np.where(rp == "", "observed", np.char.add("after_unread:", rp)))
        kn = np.searchsorted(ft, t[last], side="right")
        nxt = np.clip(kn, 0, nf - 1)
        end = np.where(kn >= nf, "stream_end",
                       np.where(fr[nxt] != "", np.char.add("frame_unread:", fr[nxt]),
                                "no_verify_row")).astype(object)
    else:
        onset = np.full(ncomp, "stream_start")
        end = np.full(ncomp, "stream_end", dtype=object)
        nxt = np.zeros(ncomp, np.int64)
    if verify is not None and len(verify["t_ms"]) and nf:
        # One key per (verifying sample, verified index): t x 64 + index is
        # exact in float64 for any t_ms the stream stores and < 64 candidates.
        vkey = np.asarray(verify["t_ms"], float) * 64.0 + np.asarray(verify["of"], float)
        vlost = np.asarray(verify["lost"], bool)
        vo = np.argsort(vkey, kind="stable")
        vkey, vlost = vkey[vo], vlost[vo]
        want = ft[nxt] * 64.0 + ii[last]
        kv = np.clip(np.searchsorted(vkey, want), 0, len(vkey) - 1)
        hit = (vkey[kv] == want) & (end == "no_verify_row")
        end[hit] = np.where(vlost[kv[hit]], "verify_lost", "verify_held_unbound")

    # The fix each track first reached through the disabled drawing: the
    # verify row of a step is keyed by the step's later sample and the
    # earlier fix's index.
    dis_at = np.full(ncomp, np.nan)
    if verify is not None and "disabled" in verify and len(verify["t_ms"]) and n > 1:
        dkey = np.asarray(verify["t_ms"], float) * 64.0 + np.asarray(verify["of"], float)
        dflag = np.asarray(verify["disabled"], bool)
        do = np.argsort(dkey, kind="stable")
        dkey, dflag = dkey[do], dflag[do]
        step_key = t[so][1:] * 64.0 + ii[so][:-1]
        kd = np.clip(np.searchsorted(dkey, step_key), 0, len(dkey) - 1)
        via = same & (dkey[kd] == step_key) & dflag[kd]
        if via.any():
            p = np.flatnonzero(via) + 1
            seg = seg_of[p]
            first = np.full(ncomp, np.inf)
            np.minimum.at(first, seg, t[so][p])
            dis_at = np.where(np.isfinite(first), first, np.nan)

    cut = starts[1:]
    f_t, f_i, f_x, f_y = (np.split(a[so], cut) for a in (t, ii, cx, cy))
    f_r, f_s, f_d = (np.split(a[so], cut) for a in (why, scale, ids))
    f_j, f_st = np.split(jump, cut), np.split(step, cut)
    rows: list = [None] * ncomp
    for c in range(ncomp):
        b = birth[c]
        tid = f"{session_id}:adisc:{round(float(t[b]), 3)}:{int(ii[b])}"
        jumps = [{"t_ms": float(f_t[c][j]), "step_px": round(float(f_st[c][j]), 2),
                  "reach_px": round(float(JUMP_REACH_BASE * f_s[c][j]), 2)}
                 for j in np.flatnonzero(f_j[c])]
        rows[int(new_of[cs[starts[c]]])] = {
            "kind": "track", "track": tid, "entity_id": tid,
            "birth_ms": float(t[b]), "last_ms": float(t[last[c]]),
            "lifetime_ms": round(float(t[last[c]] - t[b]), 3),
            "fixes": int(nfix[c]), "scored_fixes": int(scored[c]),
            "birth_xy": [float(cx[b]), float(cy[b])], "scale": float(scale[b]),
            "path_px": round(float(path_px[c]), 3), "path_base": round(float(path_base[c]), 3),
            "first_second": {"dt_ms": round(float(dt1[c]), 3), "disp_px": round(float(disp_px[c]), 3),
                             "disp_base": round(float(disp_base[c]), 3),
                             "speed_base_per_s": None if not np.isfinite(speed[c])
                             else round(float(speed[c]), 3)},
            "onset": str(onset[c]), "end": str(end[c]),
            "disabled_ms": None if not np.isfinite(dis_at[c]) else float(dis_at[c]),
            "jumps": jumps, "surprises": ["jump_past_reach"] if jumps else [],
            "fix": {"t_ms": f_t[c].tolist(), "i": f_i[c].tolist(), "cx": f_x[c].tolist(),
                    "cy": f_y[c].tolist(), "reason": [r or None for r in f_r[c].tolist()],
                    "disc": f_d[c].tolist()},
        }
    return {"track": track, "tracks": rows}

