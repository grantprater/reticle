r"""Score and prepare the enemy lane: the enemy proposal, X, "?" and enemy identity.

    .\.venv\Scripts\python.exe prototypes\enemy_lane_score.py --lineups [--record]
    .\.venv\Scripts\python.exe prototypes\enemy_lane_score.py --x --mode ring|teardrop [--record]
    .\.venv\Scripts\python.exe prototypes\enemy_lane_score.py --question --mode ring|teardrop [--record]
    .\.venv\Scripts\python.exe prototypes\enemy_lane_score.py --proposal [--record]
    .\.venv\Scripts\python.exe prototypes\enemy_lane_score.py --identity [--record]
    .\.venv\Scripts\python.exe prototypes\enemy_lane_score.py --queue331

Gap 3 of docs/ENTITY_EVENTS.md plans an enemy lane: enemy icons as
entities, named by the arbiter against the enemy side's five, ended by the
red "?" [domain:minimap/last-known-mark]. The stage-2 witnesses
(`minimap_objects_s2.py`, minimap-objects-s2-0.1.0) were scored on two 465 px
sessions with the ring fit alone as the enemy detector. This prototype
rescores them on the current readers and prepares the lane; it wires
nothing (`"wire": "no"`, task `enemy-lane-score-20260930` in the store's
`notes/predictions.jsonl`).

**The enemy proposal** (`proposals`). The ring fit finds (the enemy red key
with `minimap_ring_fit`'s gates, `icon_teardrop.detections`, the detector
stage 2 used); the icon-pose owner's enemy class poses each find
(`teardrop.IconPoseReader("enemy")`, teardrop-0.4.0 / icon-teardrop-0.2.0,
`teardrop.posed`). Mode `ring` keeps every find at the ring fit's centre, as
stage 2 did; mode `teardrop` keeps only finds the teardrop reads, at its
centre. `--x` and `--question` run stage 2's own functions unchanged with
the mode's enemy list (`use_mode` swaps `minimap_objects_s2.it_`).

**Enemy identity is the ally path, unchanged.** The ally path is
`ally_portrait.portrait_features` on the icon's aligned window (the key
excludes the teal and self pixels, `minimap.portrait_key`), scored by
`identity.claims_from_ally_icons` against references rendered from agent art
(`ally-portrait-refs-1.0.0`, which holds all 29 agents), each frame's icons
named together by `assign_side` at the table's margin. The only change is the
side: `claims_from_ally_icons(side="enemy")` takes the enemy side's five, with
no player removed. The candidate set is the lineup's enemy five
(`side_candidates`: named slots, refused slots as rivals), because the
lineup already decided which five agents the enemy fields
[domain:rounds/agent-uniqueness]; with a blind slot every icon refuses
(`lineup_incomplete`), and no 29-agent surprise path runs here. The margin
gate and the teammate fit were fitted on ally death bindings and are applied
unchanged; the per-side prior is the gallery. A variant (`key=red`) also
excludes the red ring's pixels from the disc, to measure whether the key
matters. `adjudication.identity.adjudicate_agent_identity` decides every
name; this file names nobody.

**331 px** (`--queue331`). No "?", X or enemy-identity labels exist at
331 px. On c40d950031bb, 223d636bf8d2 and bfad2778a372 it samples drawn
cache frames uniformly (seed `SEED`), takes every opportunity (a red blob of
the death owner's extractor, or a ring-fit find), and writes the sample to
`labels/enemy_lane_331_20260930/index.json` before any call. It then runs
every prototype on each item and freezes the calls in `calls.json`
(enemy, X, "?" or other red, and for an enemy call the arbiter's verdict),
and draws the queue: a uniform stratum of opportunities plus one stratum per
call (`queue.json`). `label_enemy_lane_331.py` asks the player.

Reads the crop cache and stored rows only; decodes no video. Geometry comes
through `icon_portrait_gate.Lite` (`reticle.geometry` manifests and the baked
`(map, profile)` npz via `team_vision.load_inputs`); each output names the
baked file and its mtime.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import ctypes  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import icon_portrait_gate as gate_  # noqa: E402
import icon_teardrop as it_  # noqa: E402
import minimap_objects as m1  # noqa: E402
import minimap_objects_s2 as s2  # noqa: E402
from reticle import ally_portrait, geometry, teardrop  # noqa: E402
from reticle.adjudication.death import extract_minimap_death_marks  # noqa: E402
from reticle.adjudication.identity import (adjudicate_agent_identity,  # noqa: E402
                                           claims_from_ally_icons,
                                           load_ally_portrait_references,
                                           rendered_art_scores, side_candidates)
from reticle.lineup import load_lineup  # noqa: E402
from reticle.minimap import portrait_key, widget_drawn, widget_scale  # noqa: E402
from reticle.version import ALLY_PORTRAIT_FEATURES_VERSION  # noqa: E402

VERSION = "enemy-lane-score-0.1.0"
TASK = "enemy-lane-score-20260930"
STORE = gate_.STORE
OUT = STORE / "analysis" / TASK
SESSIONS = s2.SESSIONS
ASCENT = s2.ASCENT
MARK_PX = s2.MARK_PX           # a detection lies on a labelled mark within this (px at 465)
S331 = ("c40d950031bb", "223d636bf8d2", "bfad2778a372")
SET331 = "enemy_lane_331_20260930"
SEED = 20260930
FRAMES_331 = 40                # drawn frames sampled per 331 px session
PER_STRATUM = 12               # items per stratum: uniform, enemy, x, question, other_red
ALL29: list[str] = []          # every rendered reference: the surprise path, a control only
SAME_PX = 6.0                 # two opportunities nearer than this (px at 465) are one


# ----------------------------------------------------------------- compute

BELOW_NORMAL = 0x4000


def below_normal() -> int:
    """Set this process to Below Normal and return the class the OS reports."""
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.GetPriorityClass.argtypes = [wintypes.HANDLE]
    k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    h = k.GetCurrentProcess()
    k.SetPriorityClass(h, BELOW_NORMAL)
    got = int(k.GetPriorityClass(h))
    print(f"priority class {got:#x} (Below Normal is {BELOW_NORMAL:#x})", flush=True)
    return got


def _j(obj) -> str:
    return json.dumps(obj, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))


def geometry_read(sid: str) -> dict:
    """Which baked geometry file this session reads, and when it was written."""
    p = geometry.path_of(sid, STORE)
    if p is None or not Path(p).exists():
        return {"key": geometry.key_of(sid, STORE), "path": None}
    st = Path(p).stat()
    z = np.load(p, allow_pickle=True)
    stamp = {k: str(z[k]) for k in ("built_by", "occ_built_by") if k in z.files}
    return {"key": geometry.key_of(sid, STORE), "path": str(p),
            "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
            "bytes": st.st_size, **stamp}


# ---------------------------------------------------------- the proposal

def proposals(crop: np.ndarray, s) -> list[dict]:
    """Ring-fit enemy finds, each posed by the enemy teardrop (`teardrop.posed`).

    Each row keeps the ring fit's centre under `ring`, the pose's origin and
    reason under `pose`, and `read` (the teardrop read the shape)."""
    sc = widget_scale(crop.shape[1])
    reader = teardrop.IconPoseReader("enemy", sc)
    out = []
    for d in it_.detections(crop, "enemy", s):
        p = teardrop.posed(d, reader.read(crop, d["cx"], d["cy"]))
        p["read"] = p["pose"]["origin"] == "teardrop"
        out.append(p)
    return out


class _Shim:
    """`icon_teardrop` as stage 2 sees it, with the enemy list of one mode."""

    def __init__(self, mode: str):
        self.mode = mode

    def detections(self, crop, cls, s):
        if cls != "enemy":
            return it_.detections(crop, cls, s)
        if self.mode == "ring":
            return it_.detections(crop, "enemy", s)
        return [p for p in proposals(crop, s) if p["read"]]

    def __getattr__(self, name):
        return getattr(it_, name)


def use_mode(mode: str) -> None:
    """Point stage 2's enemy icon list at `mode` (`ring` or `teardrop`)."""
    if mode not in ("ring", "teardrop"):
        raise SystemExit(f"--mode must be ring or teardrop, not {mode}")
    s2.it_ = _Shim(mode)
    s2.OUT = OUT / f"s2_{mode}"


def _record(part: str, session: str, values: dict, deps: dict, note: str, context=None) -> None:
    from reticle import metrics
    metrics.record("enemy_lane_score", part=part, session=session, values=values,
                   deps={"prototype": VERSION, **deps}, context=context or {}, note=note)


# ------------------------------------------------------------- X, "?"

def run_x(mode: str, record: bool) -> int:
    use_mode(mode)
    t0 = time.time()
    s2.run_x(record=False)
    res = json.loads((s2.OUT / "x_deaths.json").read_text(encoding="utf-8"))
    lab = json.loads((s2.OUT / "x_labels.json").read_text(encoding="utf-8"))
    tab = Counter((r["set"], r["class"], r["x_here"]) for r in lab)
    values = {f"{st}_{cl}_{'x' if xh else 'not_x'}": n for (st, cl, xh), n in tab.items()}
    per = {}
    for sid, rows in res.items():
        for side in ("ally", "enemy"):
            sub = [r for r in rows if r["side"] == side]
            c = Counter(r["status"] for r in sub)
            per[f"{sid}_{side}_n"] = len(sub)
            per[f"{sid}_{side}_placed"] = c.get("placed", 0)
            per[f"{sid}_{side}_placed_frac"] = round(c.get("placed", 0) / max(1, len(sub)), 3)
    print(_j(per), f"\n{time.time() - t0:.0f} s", flush=True)
    if record:
        deps = {"mode": mode, "stage2": s2.VERSION, "teardrop": teardrop.__name__,
                "geometry": {sid: geometry_read(sid) for sid in SESSIONS}}
        _record(f"x-labels-{mode}", "+".join(SESSIONS) + "+c62c2b06bcfb", values, deps,
                "stage-2 X shape test at the player's labelled points, current readers")
        for sid in SESSIONS:
            _record(f"x-deaths-{mode}", sid, {k[len(sid) + 1:]: v for k, v in per.items() if k.startswith(sid)},
                    deps, "stored deaths bound to a shape-confirmed X where a same-side icon ended")
    return 0


def run_question(mode: str, record: bool) -> int:
    use_mode(mode)
    t0 = time.time()
    s2.run_question(record=False, n_sample=40)
    got = json.loads((s2.OUT / "question_witness.json").read_text(encoding="utf-8"))
    values = {}
    for mk in ("question", "enemy", "other_red"):
        sub = [r for r in got["labels"] if r["mark"] == mk]
        values[f"{mk}_n"] = len(sub)
        values[f"{mk}_witness"] = sum(r["witness"] for r in sub)
    for k, v in Counter(c["set"] for c in got["candidates"]).items():
        values[f"candidates_{k}"] = v
    print(_j(values), f"\n{time.time() - t0:.0f} s", flush=True)
    if record:
        _record(f"question-{mode}", "+".join(SESSIONS), values,
                {"mode": mode, "stage2": s2.VERSION,
                 "geometry": {sid: geometry_read(sid) for sid in SESSIONS}},
                "stage-2 '?' witness at the player's labelled marks, current readers")
    return 0


# ------------------------------------------------------------ labels

def minimap_frames(s, sid: str) -> list[dict]:
    """The non-uncertain labels/minimap frames on the session's box, last row per time."""
    last = {}
    for line in (STORE / "labels" / "minimap" / f"{sid}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("uncertain") and list(r.get("roi") or []) == list(s.box):
                last[r["t_ms"]] = r
    return sorted(last.values(), key=lambda r: r["t_ms"])


def nearest(dets: list[dict], x: float, y: float, px: float):
    best = min(dets, key=lambda d: math.hypot(d["cx"] - x, d["cy"] - y), default=None)
    if best is None or math.hypot(best["cx"] - x, best["cy"] - y) > px:
        return None
    return best


def run_proposal(record: bool) -> int:
    """The enemy proposal at every labels/minimap mark, by mark kind."""
    rows, extra = [], []
    for sid in SESSIONS:
        s = gate_.Lite(sid)
        frames = minimap_frames(s, sid)
        snap = {r["t_ms"]: m1._cache_near(s, float(r["t_ms"])) for r in frames}
        cr = dict(s.crops(sorted({v for v in snap.values() if v is not None})))
        for r in frames:
            tc = snap[r["t_ms"]]
            if tc is None or tc not in cr:
                continue
            props = proposals(cr[tc], s)
            used = set()
            for mk in r.get("marks", []):
                ring = nearest([{**p, "cx": p["ring"]["cx"], "cy": p["ring"]["cy"]} for p in props],
                               mk["x"], mk["y"], MARK_PX)
                read = nearest([p for p in props if p["read"]], mk["x"], mk["y"], MARK_PX)
                if ring is not None:
                    used.add((ring["ring"]["cx"], ring["ring"]["cy"]))
                rows.append({"session": sid, "t_ms": tc, "mark": mk["kind"], "x": mk["x"], "y": mk["y"],
                             "ring": ring is not None, "read": read is not None,
                             "reason": None if ring is None else ring["pose"]["reason"]})
            for p in props:
                if (p["ring"]["cx"], p["ring"]["cy"]) not in used:
                    extra.append({"session": sid, "t_ms": tc, "read": p["read"],
                                  "reason": p["pose"]["reason"]})
        print(sid, "proposal done", flush=True)
    values = {}
    for mk in ("enemy", "question", "other_red"):
        sub = [r for r in rows if r["mark"] == mk]
        values[f"{mk}_n"] = len(sub)
        values[f"{mk}_ring"] = sum(r["ring"] for r in sub)
        values[f"{mk}_read"] = sum(r["read"] for r in sub)
        for why, n in Counter(r["reason"] for r in sub if r["ring"] and not r["read"]).items():
            values[f"{mk}_refused_{why}"] = n
    values["unmarked_ring"] = len(extra)
    values["unmarked_read"] = sum(e["read"] for e in extra)
    for why, n in Counter(e["reason"] for e in extra if not e["read"]).items():
        values[f"unmarked_refused_{why}"] = n
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "proposal.json").write_text(_j({"marks": rows, "unmarked": extra}), encoding="utf-8")
    print(_j(values), flush=True)
    if record:
        _record("proposal", "+".join(SESSIONS), values,
                {"teardrop": "teardrop-0.4.0/icon-teardrop-0.2.0", "mark_px": MARK_PX,
                 "geometry": {sid: geometry_read(sid) for sid in SESSIONS}},
                "the enemy proposal (ring fit, then the enemy teardrop) at labels/minimap marks")
    return 0


# --------------------------------------------------------------- lineups

def run_lineups(record: bool) -> int:
    """How often a stored lineup names each side's five, with each slot's reason."""
    rows = []
    for p in sorted((STORE / "lineups").glob("*.json")):
        sid = p.stem
        lu = load_lineup(sid, STORE)
        if not lu:
            rows.append({"session": sid, "lineup": None})
            continue
        row = {"session": sid, "keys": sorted(lu)}
        # The file as the lineup reader wrote it, before the scoreboard's constraint.
        raw = json.loads(p.read_text(encoding="utf-8"))
        for side in ("ally", "enemy"):
            row[f"{side}_file_named"] = sum(1 for r in (raw.get("sides") or {}).get(side, []) if r.get("agent"))
        for side in ("ally", "enemy"):
            slots = lu.get("sides", {}).get(side, [])
            sp = side_candidates(slots)
            row[side] = {"named": sorted(sp["named"]), "rivals": sp["rivals"],
                         "blind": len([b for b in sp["blind"]]),
                         "reasons": [str(r.get("reason"))[:120] for r in slots if not r.get("agent")]}
        rows.append(row)
        print(sid, "ally", len(row["ally"]["named"]), "enemy", len(row["enemy"]["named"]),
              row["enemy"]["reasons"], flush=True)
    have = [r for r in rows if r.get("enemy")]
    values = {"lineups": len(rows), "with_lineup": len(have),
              "enemy_five_named": sum(len(r["enemy"]["named"]) == 5 for r in have),
              "enemy_no_blind": sum(r["enemy"]["blind"] == 0 for r in have),
              "ally_five_named": sum(len(r["ally"]["named"]) == 5 for r in have),
              "ally_no_blind": sum(r["ally"]["blind"] == 0 for r in have),
              "enemy_five_named_in_file": sum(r["enemy_file_named"] == 5 for r in have),
              "ally_five_named_in_file": sum(r["ally_file_named"] == 5 for r in have)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "lineups.json").write_text(_j(rows), encoding="utf-8")
    print(_j(values), flush=True)
    if record:
        _record("lineups", "store", values, {"source": "reticle.lineup.load_lineup"},
                "each stored lineup's side coverage: named slots and blind slots per side")
    return 0


# -------------------------------------------------------------- identity

def _canon(name) -> str | None:
    return None if name is None else re.sub(r"[^a-z]", "", str(name).lower())


def red_key(img: np.ndarray) -> np.ndarray:
    """The enemy class's own key on the aligned window, at its ring-cover threshold."""
    return teardrop.redness(img) >= 0.5


def describe(crop: np.ndarray, p: dict, key: str, turn: bool) -> dict:
    """The ally path's portrait features at the proposal's centre."""
    img = ally_portrait.align_icon(crop, p["cx"], p["cy"])
    if turn:
        img = np.ascontiguousarray(img[::-1, ::-1])
    keyed = portrait_key(img)
    if key == "red":
        keyed = keyed | red_key(img)
    return ally_portrait.stored(ally_portrait.portrait_features(img, keyed))


def frame_claims(sid: str, tc: float, crop, props: list[dict], lineup: dict, refs: dict,
                 key: str, turn: bool) -> tuple[list[dict], list[dict]]:
    """One identity claim per proposal of one frame, all named together."""
    icons = []
    for i, p in enumerate(props):
        icons.append({"frame_idx": int(round(tc)), "t_ms": tc, "index": i,
                      "observation_key": f"{tc:.1f}:{i}", "cx": p["cx"], "cy": p["cy"],
                      "r": p.get("r"), "composition": None, "reason": None,
                      "portrait_features": describe(crop, p, key, turn),
                      "portrait_features_version": ALLY_PORTRAIT_FEATURES_VERSION})
    claims = claims_from_ally_icons(icons, lineup, gallery={}, session_id=sid,
                                    source_version=VERSION, references=refs, side="enemy")
    return icons, claims


def run_identity(record: bool) -> int:
    sid = ASCENT
    s = gate_.Lite(sid)
    lineup = load_lineup(sid, STORE)
    split = side_candidates(lineup["sides"]["enemy"])
    print("enemy five", split, flush=True)
    refs = load_ally_portrait_references(STORE)
    fit_max = (refs.get("teammate_fit") or {}).get("fit_max")
    ALL29[:] = sorted(refs["agents"])
    # A decoy gallery: another match's enemy five (Lotus), to show what a
    # wrong prior does to names the margin gate still passes.
    decoy = load_lineup(s2.LOTUS, STORE)
    last, hist = {}, defaultdict(list)
    for line in (STORE / "labels" / "minimap_agent" / f"{sid}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            last[(r["t_ms"], r["x"], r["y"])] = r
            hist[(r["t_ms"], r["x"], r["y"])].append(r)
    labels = sorted(last.values(), key=lambda r: r["t_ms"])
    snap = {r["t_ms"]: m1._cache_near(s, float(r["t_ms"])) for r in labels}
    cr = dict(s.crops(sorted({v for v in snap.values() if v is not None})))
    per_frame = {}
    for tc in sorted(set(v for v in snap.values() if v is not None)):
        if tc not in cr:
            continue
        props = proposals(cr[tc], s)
        turn = s.rotation(tc) == 180
        out = {"props": props}
        for key, lu in (("teal_self", lineup), ("red", lineup), ("decoy", decoy)):
            icons, claims = frame_claims(sid, tc, cr[tc], props, lu, refs,
                                         "red" if key == "red" else "teal_self", turn)
            verdicts = {v["entity_id"]: v for v in adjudicate_agent_identity(claims)}
            out[key] = [{"claim": c, "verdict": verdicts.get(c["entity_id"])} for c in claims]
            if key == "teal_self":
                # The surprise path, as a control only: the best of all 29 references.
                out["all29"] = []
                for ic in icons:
                    sc29 = rendered_art_scores(ic["portrait_features"], ALL29, refs)
                    out["all29"].append(max(sc29, key=sc29.get) if sc29 else None)
        per_frame[tc] = out
    rows = []
    for r in labels:
        tc = snap[r["t_ms"]]
        f = per_frame.get(tc)
        base = {"t_ms": r["t_ms"], "x": r["x"], "y": r["y"], "kind": r["marked_kind"],
                "agent": r.get("agent"), "by": r.get("by") or "player",
                "uncertain": bool(r.get("uncertain"))}
        if f is None:
            rows.append({**base, "status": "no_cache_frame"})
            continue
        i = next((k for k, p in sorted(enumerate(f["props"]),
                                       key=lambda kp: math.hypot(kp[1]["cx"] - r["x"], kp[1]["cy"] - r["y"]))
                  if math.hypot(p["cx"] - r["x"], p["cy"] - r["y"]) <= MARK_PX), None)
        if i is None:
            rows.append({**base, "status": "no_proposal"})
            continue
        row = {**base, "status": "proposed", "read": f["props"][i]["read"],
               "pose_reason": f["props"][i]["pose"]["reason"], "icons_in_frame": len(f["props"])}
        row["all29"] = f["all29"][i]
        for key in ("teal_self", "red", "decoy"):
            c, v = f[key][i]["claim"], f[key][i]["verdict"]
            row[key] = {"named": v.get("agent") if v else None, "claim_reason": c["reason"],
                        "best_guess": c["evidence"].get("best_guess"),
                        "margin": c["evidence"].get("margin"), "fit": c["evidence"].get("fit"),
                        "verdict_status": v.get("status") if v else None}
        rows.append(row)
    values = {"enemy_five": sorted(split["named"]), "enemy_blind": len(split["blind"]),
              "fit_max_ally": fit_max,
              "decoy_five": sorted(side_candidates(decoy["sides"]["enemy"])["named"])}
    prov = [h for h in hist.values() if any(r.get("by") == "claude-provisional" for r in h)]
    values["provisional_rows"] = sum(r.get("by") == "claude-provisional" for h in hist.values() for r in h)
    values["provisional_keys"] = len(prov)
    values["provisional_keys_last_player"] = sum((h[-1].get("by") or "player") == "player" for h in prov)
    values["provisional_keys_player_agrees"] = sum(
        _canon(h[-1].get("agent")) == _canon(next(r for r in h if r.get("by") == "claude-provisional")["agent"])
        for h in prov if (h[-1].get("by") or "player") == "player")
    groups = {"player_enemy": lambda r: r["by"] == "player" and r["kind"] == "enemy" and not r["uncertain"],
              "provisional_enemy": lambda r: r["by"] == "claude-provisional" and r["kind"] == "enemy",
              "player_question": lambda r: r["by"] == "player" and r["kind"] == "question"}
    for g, pred in groups.items():
        sub = [r for r in rows if pred(r)]
        values[f"{g}_n"] = len(sub)
        values[f"{g}_proposed"] = sum(r["status"] == "proposed" for r in sub)
        prop = [r for r in sub if r["status"] == "proposed"]
        values[f"{g}_proposed_read"] = sum(r["read"] for r in prop)
        for key in ("teal_self", "red"):
            named = [r for r in prop if r[key]["named"]]
            right = [r for r in named if _canon(r[key]["named"]) == _canon(r["agent"])]
            guess_right = [r for r in prop if _canon(r[key]["best_guess"]) == _canon(r["agent"])]
            values[f"{g}_{key}_named"] = len(named)
            values[f"{g}_{key}_right"] = len(right)
            values[f"{g}_{key}_best_guess_right"] = len(guess_right)
            values[f"{g}_{key}_over_fit_max"] = sum(1 for r in prop if r[key]["fit"] is not None
                                                     and fit_max is not None and r[key]["fit"] > fit_max)
            reasons = Counter(_reason_kind(r[key]["claim_reason"]) for r in prop if not r[key]["named"])
            for why, n in reasons.items():
                values[f"{g}_{key}_refused_{why}"] = n
            if g == "player_enemy" and key == "teal_self":
                values[f"{g}_all29_right"] = sum(_canon(r["all29"]) == _canon(r["agent"]) for r in prop)
                dn = [r for r in prop if r["decoy"]["named"]]
                values[f"{g}_decoy_named"] = len(dn)
                values[f"{g}_decoy_right"] = sum(_canon(r["decoy"]["named"]) == _canon(r["agent"]) for r in dn)
                values[f"{g}_decoy_over_fit_max"] = sum(1 for r in prop if r["decoy"]["fit"] is not None
                                                        and fit_max is not None and r["decoy"]["fit"] > fit_max)
                values[f"{g}_decoy_fit_median"] = float(np.median([r["decoy"]["fit"] for r in prop]))
                values[f"{g}_fit_median"] = float(np.median([r[key]["fit"] for r in prop]))
            if g == "player_enemy":
                read_named = [r for r in named if r["read"]]
                values[f"{g}_{key}_read_named"] = len(read_named)
                values[f"{g}_{key}_read_right"] = sum(_canon(r[key]["named"]) == _canon(r["agent"])
                                                      for r in read_named)
                values[f"{g}_{key}_confusions"] = dict(Counter(
                    f"{_canon(r['agent'])}->{_canon(r[key]['named'])}" for r in named
                    if _canon(r[key]["named"]) != _canon(r["agent"])))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "identity.json").write_text(_j(rows), encoding="utf-8")
    print(_j(values), flush=True)
    if record:
        flat = {k: v for k, v in values.items() if not isinstance(v, (list, dict))}
        _record("identity", sid, flat,
                {"references": refs.get("version"), "features": ALLY_PORTRAIT_FEATURES_VERSION,
                 "margin_min": refs.get("margin_min"), "gallery": "lineup enemy five (side_candidates)",
                 "labels": "labels/minimap_agent (last row per key; claude-provisional apart)",
                 "geometry": geometry_read(sid)},
                "the ally identification path, side=enemy, against the player's enemy agent labels",
                context={"enemy_five": values["enemy_five"],
                         "confusions": values.get("player_enemy_teal_self_confusions")})
    return 0


def _reason_kind(reason: str | None) -> str:
    if not reason:
        return "none"
    r = str(reason)
    if r.startswith("margin"):
        return "margin_below_gate"
    return re.split(r"[ :]", r)[0]


# ------------------------------------------------------------------ 331

def calls_at(s, t: float, crop, opps: list[dict], sc: float) -> None:
    """Every prototype's call on each opportunity of one frame, in place."""
    props = proposals(crop, s)
    use_mode("teardrop")
    qs = s2.question_frames(s, [t]).get(t) or []
    for o in opps:
        x, y = o["x"], o["y"]
        read = nearest([p for p in props if p["read"]], x, y, s2.ICON_PX * sc)
        ring = nearest([{**p, "cx": p["ring"]["cx"], "cy": p["ring"]["cy"]} for p in props], x, y,
                       s2.ICON_PX * sc)
        xs = s2.x_shape(crop, "red", x, y, sc)
        q = next((c for c in qs if math.hypot(c["x"] - x, c["y"] - y) <= s2.PLACE_PX * sc), None)
        o["calls"] = {"enemy_read": read is not None, "enemy_ring": ring is not None,
                      "pose_reason": None if ring is None else ring["pose"]["reason"],
                      "x": bool(xs["x"]), "x_why": xs.get("why"), "question": q is not None,
                      "question_age_ms": None if q is None else q["age_ms"]}
        o["call"] = ("x" if xs["x"] else "enemy" if read is not None
                     else "question" if q is not None else "other_red")
        o["_prop"] = None if read is None else props.index(read)
    o_props = props
    return o_props


def run_queue331() -> int:
    rng = random.Random(SEED)
    base = STORE / "labels" / SET331
    if (base / "calls.json").exists():
        raise SystemExit(f"{base / 'calls.json'} exists; the calls are frozen.")
    refs = load_ally_portrait_references(STORE)
    lites = {sid: gate_.Lite(sid) for sid in S331}
    lineups_full = {sid: load_lineup(sid, STORE) for sid in S331}
    if (base / "index.json").exists():
        # The sample is frozen: calls are computed on it, never on a redraw.
        sample = json.loads((base / "index.json").read_text(encoding="utf-8"))["items"]
        print("sample reused", len(sample), flush=True)
    else:
        sample = draw_sample331(rng, lites, base)
    return freeze_calls331(sample, lites, lineups_full, refs, base)


def draw_sample331(rng, lites: dict, base: Path) -> list[dict]:
    sample, geo = [], {}
    for sid in S331:
        s = lites[sid]
        geo[sid] = geometry_read(sid)
        sgray = s.inputs.static
        import cv2
        sgray = cv2.cvtColor(sgray, cv2.COLOR_BGR2GRAY).astype(np.float64)
        T = list(s.cache_t)
        cand = sorted(rng.sample(T, min(len(T), FRAMES_331 * 3)))
        drawn = []
        for t, crop in s.crops(cand):
            if widget_drawn(crop, sgray, s.floor):
                drawn.append(float(t))
        pick = sorted(rng.sample(drawn, min(len(drawn), FRAMES_331)))
        for t, crop in s.crops(pick):
            sc = widget_scale(crop.shape[1])
            opps = []
            for _a, bx, by in extract_minimap_death_marks(crop, s.floor)[1]:
                opps.append({"x": round(float(bx), 1), "y": round(float(by), 1), "source": "red_blob"})
            for d in it_.detections(crop, "enemy", s):
                if all(math.hypot(d["cx"] - o["x"], d["cy"] - o["y"]) > SAME_PX * sc for o in opps):
                    opps.append({"x": round(float(d["cx"]), 1), "y": round(float(d["cy"]), 1),
                                 "source": "ring_fit"})
            for i, o in enumerate(opps):
                sample.append({"key": f"{sid}|{t:.1f}|{o['x']:.1f},{o['y']:.1f}", "session": sid,
                               "t_ms": float(t), "x": o["x"], "y": o["y"], "source": o["source"],
                               "width": int(crop.shape[1])})
        print(sid, "frames", len(pick), "opportunities", sum(r["session"] == sid for r in sample), flush=True)
    base.mkdir(parents=True, exist_ok=True)
    (base / "index.json").write_text(_j({"set": SET331, "prototype": VERSION, "seed": SEED,
                                         "frames_per_session": FRAMES_331, "geometry": geo,
                                         "written": datetime.now(timezone.utc).isoformat(),
                                         "items": sample}), encoding="utf-8")
    print("sample written", len(sample), flush=True)
    return sample


def freeze_calls331(sample: list[dict], lites: dict, lineups_full: dict, refs: dict, base: Path) -> int:
    """Every prototype's call on each sampled item, then the queue drawn from them."""
    by = defaultdict(list)
    for it in sample:
        by[(it["session"], it["t_ms"])].append(it)
    calls = {}
    for (sid, t), its in sorted(by.items()):
        s = lites[sid]
        crop = dict(s.crops([t]))[t]
        sc = widget_scale(crop.shape[1])
        opps = [dict(it) for it in its]
        props = calls_at(s, t, crop, opps, sc)
        lineup = lineups_full[sid]
        _icons, claims = frame_claims(sid, t, crop, props, lineup, refs, "teal_self", s.rotation(t) == 180)
        verdicts = {v["entity_id"]: v for v in adjudicate_agent_identity(claims)}
        for o in opps:
            ident = None
            if o["_prop"] is not None:
                c = claims[o["_prop"]]
                v = verdicts.get(c["entity_id"])
                ident = {"entity_id": c["entity_id"], "named": v.get("agent") if v else None,
                         "claim_reason": c["reason"], "best_guess": c["evidence"].get("best_guess"),
                         "margin": c["evidence"].get("margin"), "fit": c["evidence"].get("fit")}
            calls[o["key"]] = {"call": o["call"], "calls": o["calls"], "identity": ident}
    # The queue: a uniform stratum over opportunities, then one stratum per call.
    keys = [it["key"] for it in sample]
    rng2 = random.Random(SEED + 1)
    queue, taken = [], set()
    for k in rng2.sample(keys, min(PER_STRATUM, len(keys))):
        queue.append({"key": k, "stratum": "uniform"})
        taken.add(k)
    for call in ("enemy", "x", "question", "other_red"):
        pool = [k for k in keys if calls[k]["call"] == call and k not in taken]
        # Round-robin over sessions so one session does not fill a stratum.
        per = defaultdict(list)
        for k in rng2.sample(pool, len(pool)):
            per[k.split("|")[0]].append(k)
        got = []
        while len(got) < PER_STRATUM and any(per.values()):
            for sid in S331:
                if per[sid] and len(got) < PER_STRATUM:
                    got.append(per[sid].pop())
        for k in got:
            queue.append({"key": k, "stratum": call})
            taken.add(k)
    rng2.shuffle(queue)
    lineups = {}
    for sid in S331:
        lu = lineups_full[sid]
        sp = side_candidates(lu["sides"]["enemy"]) if lu else None
        lineups[sid] = None if sp is None else {"named": sorted(sp["named"]),
                                                "rivals": sorted(r for r in sp["rivals"] if r),
                                                "blind": len(sp["blind"])}
    (base / "calls.json").write_text(_j({"prototype": VERSION, "frozen": datetime.now(timezone.utc).isoformat(),
                                         "references": refs.get("version"), "calls": calls}), encoding="utf-8")
    (base / "queue.json").write_text(_j({"seed": SEED + 1, "per_stratum": PER_STRATUM,
                                         "enemy_lineups": lineups, "items": queue}), encoding="utf-8")
    print("calls frozen", Counter(c["call"] for c in calls.values()),
          "queue", Counter(q["stratum"] for q in queue), flush=True)
    print("lineups", _j(lineups), flush=True)
    return 0


def run_score331(record: bool) -> int:
    """The frozen calls against the player's answers, per stratum (QF1-QF5)."""
    base = STORE / "labels" / SET331
    calls = json.loads((base / "calls.json").read_text(encoding="utf-8"))["calls"]
    queue = json.loads((base / "queue.json").read_text(encoding="utf-8"))["items"]
    ans = {}
    p = STORE / "labels" / f"{SET331}.jsonl"
    for line in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        if line.strip():
            r = json.loads(line)
            ans[r["key"]] = r                       # the last row for a key wins
    values = {"answered": sum(q["key"] in ans for q in queue), "queue": len(queue)}
    for q in queue:
        a = ans.get(q["key"])
        if a is None:
            continue
        if a.get("uncertain"):
            values["unsure"] = values.get("unsure", 0) + 1
            continue
        k = f"{q['stratum']}_{a['answer']}"
        values[k] = values.get(k, 0) + 1
        ident = calls[q["key"]].get("identity") or {}
        if a["answer"] == "enemy_icon" and a.get("agent") and ident.get("named"):
            values["id_both_named"] = values.get("id_both_named", 0) + 1
            values["id_agree"] = values.get("id_agree", 0) + (_canon(a["agent"]) == _canon(ident["named"]))
    print(_j(values), flush=True)
    if record:
        _record("score331", "+".join(S331), values, {"calls": str(base / "calls.json")},
                "the frozen 331 px calls against the player's answers, by stratum")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for k in ("lineups", "x", "question", "proposal", "identity", "queue331", "score331"):
        ap.add_argument(f"--{k}", action="store_true")
    ap.add_argument("--mode", default="teardrop")
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    if below_normal() != BELOW_NORMAL:
        print("warning: priority not Below Normal", flush=True)
    if args.lineups:
        return run_lineups(args.record)
    if args.x:
        return run_x(args.mode, args.record)
    if args.question:
        return run_question(args.mode, args.record)
    if args.proposal:
        return run_proposal(args.record)
    if args.identity:
        return run_identity(args.record)
    if args.queue331:
        return run_queue331()
    if args.score331:
        return run_score331(args.record)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
