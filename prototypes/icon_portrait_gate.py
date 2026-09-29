r"""Keep a teardrop fit as an agent icon only where a portrait of its side's lineup explains it.

    .\.venv\Scripts\python.exe prototypes\icon_portrait_gate.py --calibrate [--record]
    .\.venv\Scripts\python.exe prototypes\icon_portrait_gate.py --calibrate-teardrop [--per-session 60] [--record]
    .\.venv\Scripts\python.exe prototypes\icon_portrait_gate.py --calibrate-spike [--per-session 60] [--record]
    .\.venv\Scripts\python.exe prototypes\icon_portrait_gate.py --labels [--record] [--sheet PATH]
    .\.venv\Scripts\python.exe prototypes\icon_portrait_gate.py --sample [--sessions SID|SID:NAME:T0:T1 ...] [--n 40]
        [--turned-variant] [--tag=-X] [--record] [--out DIR]

`icon_teardrop` reads ally and enemy facings to a couple of degrees, and reads
things that are not agent icons as confidently: a red ping disc, a portrait
tile, red floor, red X marks, teardrop-shaped ability glyphs
(docs/STATISTICAL_ADJUDICATOR.md, E6). An agent icon holds the portrait of one
of its side's five agents; none of those things does. So this gate scores the
portrait inside each teardrop fit against the side's agents and keeps the fit
only where one of them explains it.

**It rests on the lineup prior.** The gallery is the side's lineup
(`lineup.load_lineup`, split by `identity.side_candidates`): named slots and
refused slots' best guesses. A side with a blind slot cannot reject a portrait
(an agent nobody represents may be the one drawn), so the gate abstains there
with `gallery_incomplete`. Every row carries `rests_on: "lineup"`; a result
the gate shaped must not count the lineup again as a witness.

**It names nobody.** The gate is a presence test: agent icon or not. It
stores fits, never the agent that attained one. A name for an icon is
`adjudication.identity`'s to decide, from a claim, if this is ever wired.

**The portrait score is the owner's, not restated.** The aligned crop
(`ally_portrait.align_icon` at the teardrop's centre; at the detector's
centre the labelled enemy icons fit several times worse), its features
(`ally_portrait.portrait_features` less `minimap.portrait_key`) and the
absolute fit to the closest reference (`identity.rendered_art_fit`, the mean
squared z-score under the rendered-art model) are the self icon's and the
teammate channel's. Rules, each fixed before the labels were scored:

    A  `identity.teammate_fit_refusal` at the stored `fit_max` (a piece
       median's P99 over automatic death bindings): the owner's own test
    B  the fit to the side's set is at most `b_max`, the P99 of the stored
       self-icon frames' fit to their own ally five (`--calibrate`, over the
       self_icon sessions this prototype does not evaluate on) -- primary
    Bt rule B with `bt_max` from the same self frames re-read at the self
       teardrop's centre (`--calibrate-teardrop`, `teardrop.fit_teardrop`
       on the crop cache): the first calibration fitted them at the ring
       fit's centre
    Bs rule Bt over only the self frames whose stored spike row (`reticle
       spike`, within SPIKE_GAP_MS) shows no accepted glyph within NEAR_PX
       (`--calibrate-spike`); a fit the stored row binds as a spike carrier
       (`spike.carrier_offset` at the detector's centre) is kept whatever
       its fit: a carried spike flags its carrier and never rejects it
    C  the closest of all 29 rendered references lies in the side's set: the
       other 24 stand as the null hypothesis a non-portrait falls to by
       chance about 24 times in 29. The full gallery is used only as that
       null; it names nobody and admits no one to the side
    BC both B and C

`--calibrate` reads stored `self_icon` rows only. `--labels` scores the
player's answers of `labels/icon_facing_20260928.jsonl`, per class: true
icons kept, not-icons rejected, the ability candidates rejected, and icons of
the other side's colour (the red key catches teammates) rejected.
`--sample` runs the gate on unlabelled frames outside the calibration minutes
of three sessions and writes contact sheets of what it rejects and a sample
of what it keeps, for the player to check. All three read the minimap crop
cache only, decode no video and write to the store only with `--record` (a
`metrics` row) or a sheet path.

Where it cannot work: a portrait the features cannot see (under
`ally_portrait`'s disc, occluded by another icon in a stack, or too small at
another widget scale), a widget drawn turned 180 degrees (the portraits
arrive upside down after the resample [domain:minimap/upright-icons-on-turned-map];
`--turned-variant` scores them turned as well, and a variant widget's crop
comes from the baked ROI the cache resamples it to), a red portrait
[domain:minimap/red-portrait-states], and an agent missing from the gallery.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import ctypes  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import icon_teardrop as it_  # noqa: E402
import label_icon_facing as lif  # noqa: E402
from reticle import ally_portrait, geometry, team_vision  # noqa: E402
from reticle.adjudication.identity import (load_ally_portrait_references,  # noqa: E402
                                           rendered_art_fit, side_candidates,
                                           teammate_fit_refusal)
from reticle.lineup import load_lineup  # noqa: E402
from reticle.minimap import portrait_key  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "icon-portrait-gate-0.3.0"
STORE = Path(DEFAULT_STORE)
LOTUS, ASCENT = it_.LOTUS, it_.ASCENT
LABELLED = (LOTUS, ASCENT)
#: 223d636bf8d2 fields Astra, whose placed stars draw as glyphs on the ally
#: minimap [domain:abilities/astra-star-ally-minimap-glyph].
SAMPLE_SESSIONS = (LOTUS, ASCENT, "223d636bf8d2")
PERCENTILE = 99.0
MATCH_PX = 3.0
ELSEWHERE_PX = 8.0
RULES = ("A", "B", "Bt", "Bs", "C", "BC")
CANDIDATES = "ability_candidates.json"


def _idle() -> None:
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)  # IDLE_PRIORITY_CLASS
    except Exception:
        pass


class Lite:
    """What `icon_teardrop.detections` and the crops need, for any session with
    baked geometry and a minimap crop cache (`sliver_error_model.Session` also
    wants the ability-light rows, which only two sessions hold)."""

    def __init__(self, sid: str):
        self.sid = sid
        man = geometry.manifest(sid, STORE)
        prof = get_profile(man["source_profile"])
        w, h = int(man["source"]["width"]), int(man["source"]["height"])
        self.inputs, why = team_vision.load_inputs(STORE, sid, prof, w, h)
        if self.inputs is None:
            raise SystemExit(f"{sid}: no team-vision inputs ({why})")
        self.floor, self.box = self.inputs.floor, self.inputs.box
        self.capture = man["source"]["path"]
        self.cache, why = RoiCache.load(STORE, man, prof, "minimap")
        if self.cache is None:
            raise SystemExit(f"{sid}: no minimap crop cache ({why})")
        self.cache_t = np.unique(np.asarray(self.cache.t_ms, dtype=float))
        # A variant widget (`widget_frame`) arrives resampled into the baked
        # frame at the baked ROI, which `rect_of` names; `placement` says
        # where it was drawn turned over.
        if self.cache.widget is not None:
            self.box = tuple(self.cache.rect_of("minimap"))

    def rotation(self, t_ms: float) -> int:
        seg = self.cache.widget.at(t_ms) if self.cache.widget is not None else None
        return int(seg["rotation"]) if seg else 0

    def crops(self, times):
        x0, y0, x1, y1 = self.box
        for smp in self.cache.samples([float(t) for t in times], rois=["minimap"]):
            yield smp.t_ms, smp.frame[y0:y1, x0:x1]


# ------------------------------------------------------------------ the gate

def side_gallery(lineup: dict | None, side: str) -> tuple[list[str], str | None]:
    """The names the side's lineup admits (named slots and refused slots' best
    guesses, `identity.side_candidates`) and, where the gate must abstain, why."""
    if not lineup:
        return [], "no_lineup"
    split = side_candidates(lineup.get("sides", {}).get(side, []))
    names = sorted(set(split["named"]) | {r for r in split["rivals"] if r})
    if split["blind"]:
        return names, "gallery_incomplete"
    return names, None


def features_at(crop: np.ndarray, x: float, y: float, turn: bool = False) -> dict:
    """The portrait's features at (x, y). `turn` rotates the aligned crop 180
    degrees first: on a widget drawn turned over, portraits stay upright on
    the screen and arrive upside down in the baked frame
    [domain:minimap/upright-icons-on-turned-map]."""
    img = ally_portrait.align_icon(crop, x, y)
    if turn:
        img = np.ascontiguousarray(img[::-1, ::-1])
    return ally_portrait.portrait_features(img, portrait_key(img))


def gate(feats: dict, names: list[str], refs: dict, b_max: float,
         bt_max: float | None = None, bs_max: float | None = None,
         carrier: bool = False) -> dict:
    """Each rule's verdict on one portrait: True keeps the fit as an agent icon.

    `fit_side` is the fit to the closest of the side's set, `fit_all` to the
    closest of every rendered reference; the agents that attain them are
    dropped here, because the gate names nobody. `Bt` and `Bs` are None
    until their calibrations have run. `Bs` keeps a spike carrier whatever
    its fit: a carried spike flags its carrier and never rejects it."""
    fs = rendered_art_fit(feats, names, refs)
    fa = rendered_art_fit(feats, sorted(refs["agents"]), refs)
    if fs is None or fa is None:
        return {"fit_side": None, "fit_all": None, **{r: None for r in RULES}, "why": "no_features"}
    refusal, _ = teammate_fit_refusal([fs[0]], refs.get("teammate_fit"))
    a = refusal is None if refs.get("teammate_fit") else None
    b = fs[0] <= b_max
    c = fs[0] <= fa[0] + 1e-9
    return {"fit_side": round(fs[0], 4), "fit_all": round(fa[0], 4),
            "A": a, "B": bool(b), "Bt": None if bt_max is None else bool(fs[0] <= bt_max),
            "Bs": None if bs_max is None else bool(carrier or fs[0] <= bs_max),
            "C": bool(c), "BC": bool(b and c), "why": None}


OUT = STORE / "analysis" / "portrait-gate-20260929"
#: The stored spike rows are a 1 s grid; a frame takes the row nearest in time
#: within half a step, or reads `spike_unread`.
SPIKE_GAP_MS = 500.0
#: A glyph whose centroid lies this near an icon's centre (scale 1.0 px) may
#: cover its portrait: a carried glyph's half-side plus the portrait's radius.
NEAR_PX = 20.0


class SpikeRows:
    """One session's stored spike frames (`reticle spike`, owner
    spike-observation), looked up by time."""

    def __init__(self, sid: str):
        p = STORE / "events" / "spike" / f"{sid}.jsonl"
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()
                if line.strip()] if p.exists() else []
        self.version = rows[0].get("spike_version") if rows else None
        self.frames = sorted((r for r in rows if r.get("kind") == "frame" and r.get("reason") is None),
                             key=lambda r: r["t_ms"])
        self.t = np.asarray([r["t_ms"] for r in self.frames], float)

    def at(self, t_ms: float) -> dict | None:
        if not len(self.t):
            return None
        i = int(np.searchsorted(self.t, t_ms))
        best = min((k for k in (i - 1, i) if 0 <= k < len(self.t)), key=lambda k: abs(self.t[k] - t_ms))
        return self.frames[best] if abs(self.t[best] - t_ms) <= SPIKE_GAP_MS else None


def spike_flags(row: dict | None, cx: float, cy: float, sc: float) -> dict:
    """What the stored spike reading says about an icon whose DETECTOR centre
    is (cx, cy): `spike` read or unread, `carrier` (an accepted carried
    glyph's carrier place holds it, `spike.carrier_offset`), `on_glyph` (the
    fit rings a glyph itself, `spike.on_glyph` with no other icons) and
    `near` (an accepted glyph within NEAR_PX)."""
    from reticle import spike
    if row is None:
        return {"spike": "unread", "carrier": False, "on_glyph": False, "near": None}
    rot = int(row.get("rotation") or 0)
    glyphs = spike.accepted(row.get("glyphs") or [])
    icon = [{"cx": cx, "cy": cy}]
    carrier = any(spike.carrier_offset(g, icon, sc, rot) is not None
                  for g in glyphs if g["state"] == "carried")
    on = spike.on_glyph(cx, cy, glyphs, sc, (), rot) is not None
    near = any(np.hypot(g["cx"] - cx, g["cy"] - cy) <= NEAR_PX * sc for g in glyphs)
    return {"spike": "read", "carrier": bool(carrier and not on), "on_glyph": on, "near": near}


def load_calibration() -> dict:
    """The first calibration, with `bt_max` from the teardrop-centred one
    and `bs_max` from the spike-clean one where they exist."""
    p = OUT / "calibration.json"
    if not p.exists():
        raise SystemExit(f"run --calibrate first ({p})")
    cal = json.loads(p.read_text(encoding="utf-8"))
    pt = OUT / "calibration_teardrop.json"
    cal["bt_max"] = json.loads(pt.read_text(encoding="utf-8"))["bt_max"] if pt.exists() else None
    ps = OUT / "calibration_spike.json"
    cal["bs_max"] = json.loads(ps.read_text(encoding="utf-8"))["bs_max"] if ps.exists() else None
    return cal


def calibrate_teardrop(exclude: tuple[str, ...], per_session: int, spike_clean: bool = False) -> dict:
    """`bt_max`: rule B's percentile, taken with each self frame re-read at
    the self teardrop's centre; with `spike_clean`, `bs_max` over the frames
    whose stored spike reading shows no accepted glyph near the icon.

    Up to `per_session` scored `self_icon` frames per session, evenly
    spaced; each frame's crop from the minimap crop cache at the rectangle
    `self_icon` read it from; `teardrop.fit_teardrop` at the stored centre,
    scaled by `minimap.widget_scale`. Frames the teardrop refuses are
    counted and left out, as the gate reads only teardrop fits. A frame with
    no spike reading within SPIKE_GAP_MS is left out of the clean set too:
    unread is not clean."""
    from reticle.minimap import widget_scale
    from reticle.teardrop import fit_teardrop
    refs = load_ally_portrait_references(STORE)
    fv = refs["features_version"]
    per, fits, clean, frames = {}, [], [], []
    for p in sorted((STORE / "events" / "self_icon").glob("*.jsonl")):
        sid = p.stem
        if sid in exclude:
            continue
        lineup = load_lineup(sid, STORE)
        names, why = side_gallery(lineup, "ally")
        if why:
            per[sid] = {"skipped": why}
            continue
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        head = rows[0] if rows and rows[0].get("kind") == "coverage" else {}
        if head.get("portrait_features_version") != fv:
            per[sid] = {"skipped": "features_version"}
            continue
        scored = [r for r in rows if r.get("kind") == "frame" and r.get("reason") is None
                  and r.get("cx") is not None]
        if not scored:
            per[sid] = {"skipped": "no_scored_frames"}
            continue
        pick = [scored[i] for i in np.unique(np.linspace(0, len(scored) - 1,
                                                         min(per_session, len(scored))).astype(int))]
        man = geometry.manifest(sid, STORE)
        cache, why = RoiCache.load(STORE, man, get_profile(man["source_profile"]), "minimap")
        if cache is None:
            per[sid] = {"skipped": f"no crop cache ({why})"}
            continue
        x0, y0, x1, y1 = cache.rect_of("minimap")
        by_t = {float(r["t_ms"]): r for r in pick}
        sp = SpikeRows(sid) if spike_clean else None
        f_s, f_c, refused, missing, flags = [], [], Counter(), 0, Counter()
        got = {float(s.t_ms): s.frame[y0:y1, x0:x1] for s in cache.samples(sorted(by_t), rois=["minimap"])}
        for t, r in by_t.items():
            crop = got.get(t)
            if crop is None:
                missing += 1
                continue
            sc = widget_scale(crop.shape[1])
            tf = fit_teardrop(crop, r["cx"], r["cy"], scale=sc)
            if not tf.get("read"):
                refused[tf.get("reason")] += 1
                continue
            g = gate(features_at(crop, tf["x"], tf["y"]), names, refs, math.inf)
            if g["fit_side"] is None:
                continue
            f_s.append(g["fit_side"])
            if sp is not None:
                fl = spike_flags(sp.at(t), r["cx"], r["cy"], sc)
                why = ("spike_unread" if fl["spike"] == "unread" else "carrier" if fl["carrier"]
                       else "on_glyph" if fl["on_glyph"] else "near" if fl["near"] else "clean")
                flags[why] += 1
                frames.append({"session": sid, "t_ms": t, "fit_side": g["fit_side"], "spike": why})
                if why == "clean":
                    f_c.append(g["fit_side"])
        per[sid] = {"picked": len(pick), "read": len(f_s), "refused": dict(refused), "missing": missing,
                    "width": int(x1 - x0), "fit_p50": round(float(np.median(f_s)), 3) if f_s else None,
                    "fit_p99": round(float(np.percentile(f_s, PERCENTILE)), 3) if f_s else None}
        if sp is not None:
            per[sid].update(spike_version=sp.version, spike=dict(flags), clean=len(f_c),
                            clean_p99=round(float(np.percentile(f_c, PERCENTILE)), 3) if f_c else None)
        fits += f_s
        clean += f_c
        print(sid, per[sid], flush=True)
    fits = np.asarray(fits)
    out = {"version": VERSION,
           "rule": f"bt_max = P{PERCENTILE:g} of identity.rendered_art_fit at the self teardrop's centre "
                   "(teardrop.fit_teardrop on the crop cache) of stored self_icon frames, to their ally set",
           "exclude": list(exclude), "per_session_max": per_session, "frames": int(len(fits)),
           "sessions": sorted(k for k, v in per.items() if v.get("read")),
           "bt_max": round(float(np.percentile(fits, PERCENTILE)), 4),
           "fit_pct": {str(q): round(float(np.percentile(fits, q)), 3) for q in (50, 90, 95, 97.5, 99)},
           "reference_version": refs.get("version"), "features_version": fv, "per_session": per}
    if spike_clean:
        clean = np.asarray(clean)
        # The B' tail: the 32 worst frames of every read frame, and how the
        # spike reading sorts them (prediction S4).
        tail = sorted(frames, key=lambda f: -f["fit_side"])[:32]
        out.update(rule=f"bs_max = P{PERCENTILE:g} of the same fits over frames whose stored spike row "
                        f"(within {SPIKE_GAP_MS:g} ms) shows no accepted glyph within {NEAR_PX:g} px x scale",
                   clean_frames=int(len(clean)),
                   bs_max=round(float(np.percentile(clean, PERCENTILE)), 4),
                   clean_pct={str(q): round(float(np.percentile(clean, q)), 3) for q in (50, 90, 95, 97.5, 99)},
                   spike=dict(Counter(f["spike"] for f in frames)),
                   tail32=dict(Counter(f["spike"] for f in tail)), tail=tail,
                   spike_gap_ms=SPIKE_GAP_MS, near_px=NEAR_PX)
    return out


# --------------------------------------------------------------- calibration

def calibrate(exclude: tuple[str, ...]) -> dict:
    """`b_max` from the stored self-icon frames, and rule C's keep rate there.

    Every scored `self_icon` frame of a session with a complete ally lineup,
    other than `exclude`: its stored `portrait_features` fitted to its ally
    set. The self rows' centre is the ring fit's, which the lobe pulls a few
    pixels off the portrait, and some frames are ability arcs or the spike the
    self key caught (docs/SELF_ICON_WITNESS.md); both widen the tail, so
    `b_max` errs toward keeping."""
    refs = load_ally_portrait_references(STORE)
    fv = refs["features_version"]
    per, fits, cs, sova = {}, [], [], []
    for p in sorted((STORE / "events" / "self_icon").glob("*.jsonl")):
        sid = p.stem
        if sid in exclude:
            continue
        lineup = load_lineup(sid, STORE)
        names, why = side_gallery(lineup, "ally")
        if why:
            per[sid] = {"skipped": why}
            continue
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        head = rows[0] if rows and rows[0].get("kind") == "coverage" else {}
        if head.get("portrait_features_version") != fv:
            per[sid] = {"skipped": "features_version"}
            continue
        player = (lineup.get("player") or {}).get("agent")
        f_s, c_s = [], []
        for r in rows:
            if r.get("kind") != "frame" or r.get("reason") is not None or not r.get("portrait_features"):
                continue
            g = gate(r["portrait_features"], names, refs, math.inf)
            if g["fit_side"] is None:
                continue
            f_s.append(g["fit_side"])
            c_s.append(g["C"])
        if not f_s:
            per[sid] = {"skipped": "no_scored_frames"}
            continue
        per[sid] = {"frames": len(f_s), "player": player, "fit_p50": round(float(np.median(f_s)), 3),
                    "fit_p99": round(float(np.percentile(f_s, PERCENTILE)), 3),
                    "c_keep": round(float(np.mean(c_s)), 3)}
        fits += f_s
        cs += c_s
        sova += [player == "Sova"] * len(f_s)
    fits, cs, sova = np.asarray(fits), np.asarray(cs), np.asarray(sova)
    out = {"version": VERSION, "rule": f"b_max = P{PERCENTILE:g} of identity.rendered_art_fit of stored "
                                        "self_icon frames to their ally set (side_candidates of the lineup)",
           "exclude": list(exclude), "frames": int(len(fits)),
           "sessions": sorted(k for k, v in per.items() if "frames" in v),
           "b_max": round(float(np.percentile(fits, PERCENTILE)), 4),
           "fit_pct": {str(q): round(float(np.percentile(fits, q)), 3) for q in (50, 90, 95, 97.5, 99)},
           "c_keep": round(float(cs.mean()), 4),
           "c_keep_not_sova": round(float(cs[~sova].mean()), 4) if (~sova).any() else None,
           "a_fit_max": (refs.get("teammate_fit") or {}).get("fit_max"),
           "a_keep": round(float(np.mean(fits <= (refs.get("teammate_fit") or {}).get("fit_max", math.inf))), 4),
           "reference_version": refs.get("version"), "features_version": fv, "per_session": per}
    return out


# -------------------------------------------------------------------- labels

def candidate_keys() -> tuple[set, set, set]:
    """The ability candidates still unconfirmed, those the player named an
    agent icon, and the items he named an ability glyph
    (`ability_candidates_verdicts.jsonl`, append-only beside the candidates
    file; the last verdict per key wins)."""
    d = lif.items_dir(STORE)
    cands = set(json.loads((d / CANDIDATES).read_text(encoding="utf-8"))["keys"])
    p = d / "ability_candidates_verdicts.jsonl"
    verdict = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                verdict[r["key"]] = r["verdict"]
    icons = {k for k, v in verdict.items() if v == "agent_icon"}
    glyphs = {k for k, v in verdict.items() if v == "ability_glyph"}
    return cands - icons - glyphs, icons & cands, glyphs


def item_class(it: dict, a: dict, cands: set, colour: str | None, glyphs: set = frozenset()) -> str:
    if it["key"] in glyphs:
        return "ability_glyph"
    if it["key"] in cands:
        return "ability_candidate"
    if a["answer"] == "not_icon":
        return "not_icon"
    if a["answer"] != "facing":
        return a["answer"]
    if colour is not None and colour != it["cls"]:
        return "other_colour"
    return "true_icon"


def label_rows(b_max: float, bt_max: float | None = None, bs_max: float | None = None) -> list[dict]:
    import icon_facing_eval as ife
    from reticle.minimap import widget_scale
    refs = load_ally_portrait_references(STORE)
    answers = lif.load_answers(lif.labels_path(STORE))
    index = json.loads((lif.items_dir(STORE) / "index.json").read_text(encoding="utf-8"))["items"]
    cands, named_icons, glyphs = candidate_keys()
    rows = []
    for sid in LABELLED:
        s = Lite(sid)
        sp = SpikeRows(sid)
        lineup = load_lineup(sid, STORE)
        its = [it for it in index if it["session"] == sid and it["key"] in answers]
        crops = dict(s.crops(sorted({it["t_ms"] for it in its})))
        for it in its:
            crop, a, cls = crops[it["t_ms"]], answers[it["key"]], it["cls"]
            names, why = side_gallery(lineup, cls)
            dets = it_.detections(crop, cls, s)
            det = min(dets, key=lambda d: math.hypot(d["cx"] - it["det_x"], d["cy"] - it["det_y"]),
                      default=None)
            if det is not None and math.hypot(det["cx"] - it["det_x"], det["cy"] - it["det_y"]) > MATCH_PX:
                det = None
            cx, cy = (det["cx"], det["cy"]) if det is not None else (it["det_x"], it["det_y"])
            f = it_.fit(crop, cls, cx, cy)
            x, y = (f["x"], f["y"]) if "x" in f else (cx, cy)
            colour = (ife.colour_at(crop, a["centre_x"], a["centre_y"])
                      if a.get("centre_x") is not None else None)
            row = {"key": it["key"], "session": sid, "t_ms": it["t_ms"], "side": cls,
                   "stratum": it["stratum"], "answer": a["answer"],
                   "class": item_class(it, a, cands, colour, glyphs),
                   "was_candidate": it["key"] in named_icons, "stacked": bool(it.get("stacked")),
                   "elsewhere": (a.get("centre_x") is not None and
                                 math.hypot(a["centre_x"] - it["ring_x"], a["centre_y"] - it["ring_y"])
                                 > ELSEWHERE_PX),
                   "detection_lost": det is None, "teardrop_read": bool(f.get("read")),
                   "teardrop_reason": f.get("reason"), "x": round(x, 2), "y": round(y, 2),
                   "deg": f.get("deg"), "rests_on": "lineup", "gallery": len(names),
                   "gallery_reason": why}
            fl = spike_flags(sp.at(it["t_ms"]), cx, cy, widget_scale(crop.shape[1]))
            row.update({f"spike_{k}": v for k, v in fl.items()})
            row.update(gate(features_at(crop, x, y), names, refs, b_max, bt_max, bs_max, fl["carrier"]))
            # The detector's centre, for the record only: the rules read the teardrop's.
            gd = gate(features_at(crop, cx, cy), names, refs, b_max)
            row["det_fit_side"], row["det_B"] = gd["fit_side"], gd["B"]
            row["_crop"] = crop
            rows.append(row)
    return rows


CLASSES_ORDER = ("true_icon", "not_icon", "ability_glyph", "ability_candidate", "other_colour", "cant_tell")


def label_table(rows: list[dict]) -> dict:
    """Per side and item class: items, teardrop reads, and each rule's KEPT count,
    over all items and over the items the teardrop reads."""
    out = {}
    for side in ("ally", "enemy"):
        for c in CLASSES_ORDER:
            sub = [r for r in rows if r["side"] == side and r["class"] == c]
            if not sub:
                continue
            d = {"n": len(sub), "td_read": sum(r["teardrop_read"] for r in sub)}
            for rule in RULES:
                d[f"kept_{rule}"] = sum(bool(r[rule]) for r in sub)
                d[f"kept_{rule}_td"] = sum(bool(r[rule]) for r in sub if r["teardrop_read"])
            d["fit_side"] = sorted(r["fit_side"] for r in sub if r["fit_side"] is not None)
            out[f"{side}/{c}"] = d
    return out


def show_table(tab: dict, b_max: float) -> None:
    print(f"\nb_max {b_max}   (kept counts; '/td' = among items the teardrop reads)")
    print(f"{'side/class':28s} {'n':>3s} {'td':>3s} " + " ".join(f"{r:>9s}" for r in RULES))
    for k, d in tab.items():
        cells = " ".join(f"{d[f'kept_{r}']:>3d}/{d[f'kept_{r}_td']:<3d}td" for r in RULES)
        print(f"{k:28s} {d['n']:3d} {d['td_read']:3d} {cells}")
        print(f"{'':28s} fit_side {d['fit_side']}")


# -------------------------------------------------------------------- sample

def sample_rows(n: int, b_max: float, bt_max: float | None = None,
                sessions: tuple[str, ...] = SAMPLE_SESSIONS,
                bs_max: float | None = None,
                turned_variant: bool = False) -> tuple[list[dict], dict]:
    from reticle.minimap import widget_scale
    refs = load_ally_portrait_references(STORE)
    rows, meta = [], {}
    for spec in sessions:
        # `sid` alone, or `sid:name:t0:t1` for a span of one session (either
        # bound may be empty); the span's rows carry `sid-name`.
        sid, *span = spec.split(":")
        label = f"{sid}-{span[0]}" if span else sid
        s = Lite(sid)
        sp = SpikeRows(sid)
        lineup = load_lineup(sid, STORE)
        gals = {side: side_gallery(lineup, side) for side in ("ally", "enemy")}
        meta[label] = {"capture": s.capture, "gallery": {k: {"n": len(v[0]), "reason": v[1]}
                                                         for k, v in gals.items()},
                       "variant_widget": s.cache.widget is not None}
        if span:
            t0 = float(span[1]) if len(span) > 1 and span[1] else -math.inf
            t1 = float(span[2]) if len(span) > 2 and span[2] else math.inf
            T = np.array([t for t in s.cache_t if not it_.held_out(t) and t0 <= t < t1])
            times = sorted(float(t) for t in T[np.linspace(0, len(T) - 1, n).astype(int)])
            meta[label]["span_ms"] = [t0, t1]
        else:
            times = it_.sample_times(s, n, calibration=False)
        rots = Counter()
        for t, crop in s.crops(times):
            meta[label]["width"] = int(crop.shape[1])
            rot = s.rotation(t)
            rots[rot] += 1
            for side in ("ally", "enemy"):
                key = it_.CLASSES[side].key(crop)
                names, why = gals[side]
                for d in it_.detections(crop, side, s):
                    f = it_.fit(None, side, d["cx"], d["cy"], key=key)
                    if not f.get("read"):
                        continue
                    row = {"session": label, "t_ms": float(t), "side": side, "x": round(f["x"], 2),
                           "y": round(f["y"], 2), "deg": round(f["deg"], 1), "ncc": round(f["ncc"], 3),
                           "rotation": rot, "rests_on": "lineup", "gallery": len(names),
                           "gallery_reason": why}
                    fl = spike_flags(sp.at(t), d["cx"], d["cy"], widget_scale(crop.shape[1]))
                    row.update({f"spike_{k}": v for k, v in fl.items()})
                    row.update(gate(features_at(crop, f["x"], f["y"]), names, refs, b_max, bt_max,
                                    bs_max, fl["carrier"]))
                    if turned_variant:
                        # The logged variant: the same gate on the portrait turned 180 degrees.
                        gu = gate(features_at(crop, f["x"], f["y"], turn=True), names, refs, b_max,
                                  bt_max, bs_max, fl["carrier"])
                        row["fit_side_up"], row["Bs_up"] = gu["fit_side"], gu["Bs"]
                    row["_crop"] = crop
                    rows.append(row)
        meta[label]["rotation_frames"] = {str(k): v for k, v in rots.items()}
        print(label, "done", dict(rots), flush=True)
    return rows, meta


def sample_table(rows: list[dict]) -> dict:
    out = {}
    for sid in sorted({r["session"] for r in rows}):
        for side in ("ally", "enemy"):
            sub = [r for r in rows if r["session"] == sid and r["side"] == side]
            if not sub:
                continue
            d = {"read": len(sub)}
            for rule in RULES + (("Bs_up",) if "Bs_up" in sub[0] else ()):
                d[f"reject_{rule}"] = round(sum(r[rule] is False for r in sub) / len(sub), 3)
            d["carrier"] = sum(bool(r.get("spike_carrier")) for r in sub)
            out[f"{sid}/{side}"] = d
    return out


# ------------------------------------------------------------------- sheets

def tile(r: dict, K: int = 18, Z: int = 6) -> np.ndarray:
    crop = r["_crop"]
    x0, y0 = int(round(r["x"])) - K, int(round(r["y"])) - K
    pad = cv2.copyMakeBorder(crop, K, K, K, K, cv2.BORDER_CONSTANT)
    big = cv2.resize(pad[y0 + K:y0 + 3 * K, x0 + K:x0 + 3 * K], None, fx=Z, fy=Z,
                     interpolation=cv2.INTER_NEAREST)

    def P(x, y):
        return int(round((x - x0 + 0.5) * Z)), int(round((y - y0 + 0.5) * Z))
    c = it_.CLASSES[r["side"]]
    col = (0, 220, 0) if r.get("teardrop_read", True) else (160, 160, 160)
    cv2.circle(big, P(r["x"], r["y"]), int(c.r_out * Z), col, 1)
    # The feature disc: 0.75 of DISC_R aligned px, at UPS * W_REF / width.
    disc = 0.75 * ally_portrait.DISC_R / (ally_portrait.UPS * ally_portrait.W_REF / crop.shape[1])
    cv2.circle(big, P(r["x"], r["y"]), int(disc * Z), (255, 255, 0), 1)
    if r.get("deg") is not None:
        a = math.radians(r["deg"])
        cv2.line(big, P(r["x"], r["y"]), P(r["x"] + c.L * math.cos(a), r["y"] + c.L * math.sin(a)), col, 1)
    top = f"{r['session'][:4]} {r['t_ms'] / 1000:.1f}s {r['side'][0]}"
    if r.get("class"):
        top += f" {r['class'][:9]}"
    fs = "-" if r["fit_side"] is None else f"{r['fit_side']:.2f}"
    fa = "-" if r["fit_all"] is None else f"{r['fit_all']:.2f}"
    flags = " ".join(f"{k}{'+' if r[k] else '-' if r[k] is False else '?'}" for k in ("A", "Bt", "Bs", "C"))
    if "Bs_up" in r:
        flags += f" up{'+' if r['Bs_up'] else '-' if r['Bs_up'] is False else '?'}"
    if r.get("rotation"):
        top += f" r{r['rotation']}"
    if r.get("spike_carrier"):
        flags += " CARRIER"
    elif r.get("spike_spike") == "unread":
        flags += " spike?"
    for i, text in enumerate((top, f"fit {fs} all {fa}", flags)):
        cv2.putText(big, text, (3, 13 + 14 * i), 0, 0.42, (0, 0, 0), 3)
        cv2.putText(big, text, (3, 13 + 14 * i), 0, 0.42, (255, 255, 255), 1)
    return big


def write_sheet(path: Path, rows: list[dict], cols: int = 8, limit: int = 64) -> None:
    rows = rows[:limit]
    if not rows:
        print("nothing for", path)
        return
    tiles = [tile(r) for r in rows]
    blank = np.zeros_like(tiles[0])
    grid = [np.hstack(tiles[i:i + cols] + [blank] * (cols - len(tiles[i:i + cols])))
            for i in range(0, len(tiles), cols)]
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.vstack(grid))
    print("wrote", path, len(rows), "tiles")


# --------------------------------------------------------------------- main

def _deps(cal: dict) -> dict:
    return {"prototype": VERSION, "reader": it_.VERSION, "b_max": cal["b_max"],
            "bt_max": cal.get("bt_max"), "bs_max": cal.get("bs_max"), "spike_gap_ms": SPIKE_GAP_MS,
            "a_fit_max": cal["a_fit_max"], "reference_version": cal["reference_version"],
            "features_version": cal["features_version"], "rests_on": "lineup",
            "centre": "teardrop"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--calibrate-teardrop", action="store_true",
                    help="rule Bt: the self frames re-read at the self teardrop's centre")
    ap.add_argument("--calibrate-spike", action="store_true",
                    help="rule Bs: as --calibrate-teardrop, over frames with no stored spike glyph near the icon")
    ap.add_argument("--per-session", type=int, default=60, help="--calibrate-teardrop/-spike: frames per session")
    ap.add_argument("--labels", action="store_true")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--sessions", nargs="+", default=list(SAMPLE_SESSIONS),
                    help="--sample: sessions, each `sid` or `sid:name:t0:t1` for a span")
    ap.add_argument("--turned-variant", action="store_true",
                    help="--sample: also score each portrait turned 180 degrees (Bs_up)")
    ap.add_argument("--tag", default="", help="--sample: suffix for the sheets and the metric part")
    ap.add_argument("--n", type=int, default=40, help="--sample: frames per session")
    ap.add_argument("--sheet", type=Path, help="--labels: contact sheet of every labelled item")
    ap.add_argument("--out", type=Path, default=STORE / "analysis" / "portrait-gate-20260929")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    _idle()
    from reticle import metrics
    if args.calibrate:
        cal = calibrate(tuple(SAMPLE_SESSIONS))
        print(json.dumps({k: v for k, v in cal.items() if k != "per_session"}, indent=1))
        for sid, v in cal["per_session"].items():
            print(" ", sid, v)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "calibration.json").write_text(json.dumps(cal, indent=1), encoding="utf-8")
        if args.record:
            metrics.record("icon_portrait_gate", part="calibration", session="self_icon-" + str(len(cal["sessions"])),
                           values={k: cal[k] for k in ("frames", "b_max", "c_keep", "c_keep_not_sova", "a_keep")}
                           | {f"fit_p{k}": v for k, v in cal["fit_pct"].items()},
                           deps={"prototype": VERSION, "percentile": PERCENTILE, "exclude": cal["exclude"],
                                 "reference_version": cal["reference_version"],
                                 "features_version": cal["features_version"]},
                           context={"sessions": cal["sessions"]},
                           note="per-icon rendered-art fit of stored self_icon frames to their ally set")
        return 0
    if args.calibrate_spike:
        cal = calibrate_teardrop(tuple(SAMPLE_SESSIONS), args.per_session, spike_clean=True)
        print(json.dumps({k: v for k, v in cal.items() if k not in ("per_session", "tail")}, indent=1))
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "calibration_spike.json").write_text(json.dumps(cal, indent=1), encoding="utf-8")
        if args.record:
            metrics.record("icon_portrait_gate", part="calibration-spike",
                           session="self_icon-" + str(len(cal["sessions"])),
                           values={"frames": cal["frames"], "clean_frames": cal["clean_frames"],
                                   "bs_max": cal["bs_max"]}
                           | {f"clean_p{k}": v for k, v in cal["clean_pct"].items()}
                           | {f"spike_{k}": v for k, v in cal["spike"].items()}
                           | {f"tail32_{k}": v for k, v in cal["tail32"].items()},
                           deps={"prototype": VERSION, "percentile": PERCENTILE, "exclude": cal["exclude"],
                                 "per_session_max": cal["per_session_max"], "spike_gap_ms": SPIKE_GAP_MS,
                                 "near_px": NEAR_PX, "reference_version": cal["reference_version"],
                                 "features_version": cal["features_version"]},
                           context={"sessions": cal["sessions"],
                                    "spike_versions": sorted({str(v.get("spike_version"))
                                                              for v in cal["per_session"].values()})},
                           note="teardrop-centred self fits over frames with no stored spike glyph near the icon")
        return 0
    if args.calibrate_teardrop:
        cal = calibrate_teardrop(tuple(SAMPLE_SESSIONS), args.per_session)
        print(json.dumps({k: v for k, v in cal.items() if k != "per_session"}, indent=1))
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "calibration_teardrop.json").write_text(json.dumps(cal, indent=1), encoding="utf-8")
        if args.record:
            metrics.record("icon_portrait_gate", part="calibration-teardrop",
                           session="self_icon-" + str(len(cal["sessions"])),
                           values={"frames": cal["frames"], "bt_max": cal["bt_max"]}
                           | {f"fit_p{k}": v for k, v in cal["fit_pct"].items()},
                           deps={"prototype": VERSION, "percentile": PERCENTILE, "exclude": cal["exclude"],
                                 "per_session_max": cal["per_session_max"],
                                 "reference_version": cal["reference_version"],
                                 "features_version": cal["features_version"]},
                           context={"sessions": cal["sessions"]},
                           note="per-icon rendered-art fit of stored self_icon frames at the self teardrop's centre")
        return 0
    cal = load_calibration()
    last = "Bs" if cal.get("bs_max") is not None else "Bt" if cal.get("bt_max") is not None else None
    suffix = f"-{last.lower()}" if last else ""
    if args.labels:
        rows = label_rows(cal["b_max"], cal.get("bt_max"), cal.get("bs_max"))
        tab = label_table(rows)
        show_table(tab, cal["b_max"])
        print("bt_max", cal.get("bt_max"), "bs_max", cal.get("bs_max"))
        print("carrier-flagged:", [(r["side"], r["class"], r["key"]) for r in rows if r.get("spike_carrier")])
        print("spike unread:", sum(r.get("spike_spike") == "unread" for r in rows))
        if args.sheet:
            order = {c: i for i, c in enumerate(CLASSES_ORDER)}
            write_sheet(args.sheet, sorted(rows, key=lambda r: (r["side"], order.get(r["class"], 9), r["t_ms"])),
                        limit=80)
        if args.json:
            args.json.write_text(json.dumps([{k: v for k, v in r.items() if k != "_crop"} for r in rows],
                                            indent=1), encoding="utf-8")
        if args.record:
            values = {}
            for k, d in tab.items():
                side, c = k.split("/")
                values[f"{side}_{c}_n"] = d["n"]
                values[f"{side}_{c}_td_read"] = d["td_read"]
                for rule in RULES:
                    values[f"{side}_{c}_kept_{rule}"] = d[f"kept_{rule}"]
                    values[f"{side}_{c}_kept_{rule}_td"] = d[f"kept_{rule}_td"]
            metrics.record("icon_portrait_gate", part="labels" + suffix, session="+".join(LABELLED), values=values,
                           deps=_deps(cal) | {"labels": lif.labels_path(STORE).name, "candidates": CANDIDATES},
                           note="per side and item class, the fits each rule keeps")
        return 0
    if args.sample:
        sessions = tuple(args.sessions)
        rows, meta = sample_rows(args.n, cal["b_max"], cal.get("bt_max"), sessions, cal.get("bs_max"),
                                 turned_variant=args.turned_variant)
        tag = f"{suffix}{args.tag}"
        tab = sample_table(rows)
        for k, d in tab.items():
            print(k, d)
        print(json.dumps(meta, indent=1))
        print("carrier-flagged:", [(r["session"], r["t_ms"], r["side"], r["fit_side"], r[last] if last else None)
                                   for r in rows if r.get("spike_carrier")])
        print("spike unread:", sum(r.get("spike_spike") == "unread" for r in rows))
        rng = np.random.default_rng(20260929)
        if last:
            # The latest rule's sheets: every fit it rejects, and a sample of those it keeps.
            rej = [r for r in rows if r[last] is False]
            kept = [r for r in rows if r[last]]
        else:
            rej = [r for r in rows if r["B"] is False or r["C"] is False]
            kept = [r for r in rows if r["B"] and r["C"]]
        rej.sort(key=lambda r: (r["side"], r["session"], r["t_ms"]))
        kept = [kept[i] for i in sorted(rng.choice(len(kept), min(48, len(kept)), replace=False))]
        kept.sort(key=lambda r: (r["side"], r["session"], r["t_ms"]))
        write_sheet(args.out / f"sample_rejected{tag}.png", rej, limit=96)
        write_sheet(args.out / f"sample_kept{tag}.png", kept, limit=48)
        if args.turned_variant:
            up = sorted((r for r in rows if r["Bs_up"] is False),
                        key=lambda r: (r["side"], r["session"], r["t_ms"]))
            write_sheet(args.out / f"sample_rejected{tag}-up.png", up, limit=96)
        counts = Counter((r["side"], r["Bt"], r["Bs"], r["C"]) for r in rows)
        print("side, Bt, Bs, C:", dict(counts))
        if args.json:
            args.json.write_text(json.dumps([{k: v for k, v in r.items() if k != "_crop"} for r in rows],
                                            indent=1), encoding="utf-8")
        if args.record:
            for label in meta:
                values = {}
                for side in ("ally", "enemy"):
                    d = tab.get(f"{label}/{side}")
                    if d:
                        values[f"{side}_read"] = d["read"]
                        values[f"{side}_carrier"] = d["carrier"]
                        for k, v in d.items():
                            if k.startswith("reject_"):
                                values[f"{side}_{k}"] = v
                metrics.record("icon_portrait_gate", part="sample" + tag, session=label, values=values,
                               deps=_deps(cal) | {"n": args.n, "turned_variant": args.turned_variant},
                               context={k: meta[label].get(k) for k in
                                        ("capture", "gallery", "width", "span_ms", "rotation_frames",
                                         "variant_widget")},
                               note="share of teardrop-read fits each rule rejects, unlabelled frames")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
