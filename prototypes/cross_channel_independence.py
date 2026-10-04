r"""Do the audio witness and the minimap channel fail on the same casts? Measured on the player's own casts.

    .\.venv\Scripts\python.exe prototypes\cross_channel_independence.py build  [--only sid,sid] [--no-demos] [--out DIR [--resume]]
    .\.venv\Scripts\python.exe prototypes\cross_channel_independence.py report [--dir DIR] [--record]

The question is the player's (2026-10-04): with the audio and minimap channels much better, cross-referencing
them for training is safe if their weaknesses do not overlap. Pre-registered in the store's
notes/predictions.jsonl (task cross-channel-independence-20261004) before any outcome was read.

`build` writes one row per cast to casts.jsonl in a NEW versioned directory under the store's analysis/
(`cross-channel-independence-<version>-<UTC stamp>`); it refuses a directory that already holds output unless
`--resume` continues it, so a rerun never overwrites evidence. The stored run is
analysis/cross-channel-independence-20261004/ (build 0.1.0, 680 casts). `report` reads a directory's
casts.jsonl and writes report-<version>.json beside it; `--record` appends its metrics rows.

Result (report 0.2.0 on the stored 0.1.0 casts)
-----------------------------------------------
Headline: stratified by minimap source (glyph follow, shape owner), the Mantel-Haenszel odds ratio of joint
failure on match casts is [metric:cross_channel_independence/stratified_source@matches#or_mh=2.694]
[[metric:cross_channel_independence/stratified_source@matches#ci_low=1.105],
[metric:cross_channel_independence/stratified_source@matches#ci_high=6.57]]; stratified by agent and slot it is
[metric:cross_channel_independence/stratified_agent_slot@matches#or_mh=2.466]
[[metric:cross_channel_independence/stratified_agent_slot@matches#ci_low=0.983],
[metric:cross_channel_independence/stratified_agent_slot@matches#ci_high=6.189]]. Under the pre-registered rule
(guess: odds ratio <= 2; refuted when the CI's lower bound exceeds 2; a point above 2 with the CI spanning 2 is
inconclusive) the player's guess that the channels fail independently is INCONCLUSIVE AND LEANS AGAINST: the
source-stratified interval excludes 1. The stratification was chosen after registration (by the verifier of
63578e9); the registered statistic is the pooled conditional odds ratio,
[metric:cross_channel_independence/pooled@matches#or_cmle=0.782], and that figure is a Simpson's-paradox
artefact: it lies below both source strata, because glyph casts pair rare audio failure with common minimap
failure and shape casts the reverse.

Dependence built in by construction: the shared tray gate. Every channel is anchored on the tray drop. Audio
takes the drop as the cast frame, cuts its window at neighbouring drops and excludes null frames by them; the
glyph window starts at the drop; the shape owner reads the drop time AND the truth slot's descriptor. So channel
B on shape casts is no blind witness: shape-owner "right" means "detected, given the truth slot", and its
precision of 1.0 holds by construction. A wrong tray cast, or a context both channels share (the player's own
ult in progress: 59c70f1ef720 at 2429.0 s, an E drop 4 s after an X drop, audio names X), fails both at once;
some of the coupling above is this gate, not the channels.

Borrowed labels. A label one channel lends the other declares `rests_on` its source witness and version
(e.g. `ability_shape:<sid>:<cast>@ability-shape-0.4.0`) AND the tray drop / player_cast it was anchored on
(`tray_drop:<sid>:<t_ms>`; the stored shape claims already declare `depends_on ...:player_cast`), so neither
the witness nor the tray ever counts again as an independent witness. A shape-owner label's slot IS the tray's.

Choices made after registration, each labelled in the report (`post_registration`):
* `absent_as_unobserved()` (the 63578e9 `normalise()`) moves B refusals for a missing or stale crop cache and
  A refusals `audio_not_live` / `no_audio_row` to "unobserved"; the report also gives the headline without it.
* the session stratification (`mh_by_session_*`) and the source / agent-slot / session-source strata.
* the NO_DESCRIPTOR comparisons, chosen after seeing the joint failures. The 63578e9 report's "without those
  four" dropped all 7 `no_radius_on_map` casts
  ([metric:cross_channel_independence/shape_drop_no_descriptor@matches#or_cmle=12.271] on
  [metric:cross_channel_independence/shape_drop_no_descriptor@matches#n_both=3] joint failures); dropping only
  the 4 Abyss joint failures gives
  [metric:cross_channel_independence/shape_drop_four_abyss@matches#or_cmle=3.116]
  [[metric:cross_channel_independence/shape_drop_four_abyss@matches#ci_low=0.429],
  [metric:cross_channel_independence/shape_drop_four_abyss@matches#ci_high=19.722]]. Of those 4 Recon Bolts on
  75a55a296d3b, audio refuses `bolt_unknown` on
  [metric:cross_channel_independence/corrections@matches#abyss_bolt_unknown=3]; at 658050 ms it is wrong and
  names C.
* the [metric:cross_channel_independence/corrections@matches#stale_cache_casts=15] casts of b3b9defb6fd7 (Skye)
  are a stale crop cache (`no_crop_cache:stale_rects`), not missing minimap owner rows; coverage now counts them
  apart.

Smoke. The registration said "smoke = stored smoke rows"; `build` reads the smoke stream
(events/smoke/<sid>.jsonl). No Clove session stores one (the match a1a995e6b19b, the demos 0c6c52a65b9e and
28f53bfddbbe), so every smoke cast is "unobserved"; where a stream exists, no onset rule was registered, and the
cast stays "unobserved" (`smoke_rows_unscored`) rather than gaining a rule after the fact.

Other corrections to the 63578e9 report: the glyph follow's parameters came from the glyph eval, whose items
in these matches number [metric:cross_channel_independence/corrections@matches#glyph_eval_items=181]
([metric:cross_channel_independence/corrections@matches#glyph_eval_items_heldout=178] held out, 3 unsplit, none
in its dev split), and only [metric:cross_channel_independence/corrections@matches#casts_with_glyph_item_near=33]
casts have an item within -0.5 to +3.5 s; "294 match casts" counted every cast of those sessions. Audio's
per-ability precision is in `audio_precision_by_ability_match`: Iso Q and C have
[metric:cross_channel_independence/corrections@matches#iso_q_casts=3] and
[metric:cross_channel_independence/corrections@matches#iso_c_casts=3] casts, too few to call safe (Iso Q:
[metric:cross_channel_independence/corrections@matches#iso_q_audio_right=2] right); Skye X
([metric:cross_channel_independence/corrections@matches#skye_x_audio_right=19] of
[metric:cross_channel_independence/corrections@matches#skye_x_audio_named=20]) belongs in the list of
abilities where audio may label the minimap, beside Sova C and Skye Q and E.

Truth. Matches: the tray's own casts (`ability_audio_fit.gate_snapshot` rows with `player_cast`; the slot that
dropped is the truth, the agent the identity arbiter's over the stored lineup). Demos: the player's census
(labels/demo_cast_class), whose `class` is also the player's word on what the minimap drew for that cast.

Channel A, audio. `ability_timeline.audio_cast_witness` at the versions in reticle/version.py
(ability-audio-0.4.0, ability-audio-params-0.2.6), recomputed in memory from the stored log-mel: 20 of the 21
matches store rows of 0.3.0 / 0.2.4. Demos go through `ability_audio_fit.demo_session`, as `--eval` scores them.
Nothing is written to the store's streams. Outcome: right, wrong (another slot) or refused (verdict None, with
its reason). Stratum: dev or held of the parameter set's split (halves split at the log-mel midpoint).

Channel B, minimap. What each ability draws comes from domain facts and the game-data texture table
(ability-states-gamedata-0.2.0), never by analogy (MINIMAP_SOURCE):

* glyph: `prototypes/minimap_glyph_eval.follow_item`, its proposer (`reticle.ability_icons.propose_icons`) and
  every parameter of minimap-glyph-follow-0.2.0, over the cached frames from the tray drop to +FOLLOW_MS,
  seeded at the stored self position (`ability_shapes.seed_from_track`; demos, which store no minimap table,
  at the stored team_vision self icon). The candidate set is the player's kit (`minimap_glyph_eval.kit`): the
  context names the agent, so the full gallery is not searched. The follow refuses when no clean frame is
  left; it names a kit slot otherwise.
* shape: the stored ability_shape rows of that cast, found or not. The shape owner searches only the dropped
  slot's descriptor, so this source detects and cannot name another slot: B can be right or refused, never
  wrong.
* not_drawn: a domain fact or the game data says the ability draws nothing on the minimap. The glyph follow
  still runs on these casts as a control (`control_*` fields) and never enters the 2x2.

Covariates: gunfire (audio-gate labels, intervals.gunfire overlapping [t-1, t+2] s), another death within +-2 s
(labels other_deaths), a neighbouring own cast within 2 s, crowding (stored team_vision icons other than the
self within 2 OCC_R x scale of the seed at the drop), the follow's skip reasons and how far it ended from the
seed.

Decodes nothing: log-mel, crop cache and stored streams only.

Wire: no (predictions.jsonl, cross-channel-independence-20261004). A measurement of two channels' error
coupling that decides how one channel's labels may train the other; it reads no new evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:  # Below Normal: the user's own jobs share this CPU
    import ctypes
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
except Exception:  # noqa: BLE001
    pass

import numpy as np  # noqa: E402

VERSION = "cross-channel-independence-0.2.0"
STORE = Path("C:/Users/grant/reticle-store")
ANALYSIS = STORE / "analysis"
#: The stored 0.1.0 build, measured at 63578e9; `report` reads it by default.
OUT = ANALYSIS / "cross-channel-independence-20261004"
FOLLOW_MS = 3000.0          # the matcher's own window; Guiding Light is gone by 4 s
GUNFIRE_WIN = (-1.0, 2.0)   # s around the drop
DEATH_WIN = 2.0
NEIGHBOUR_S = 2.0

#: Match agents: what each slot draws on the player's own minimap, with the fact it rests on.
MINIMAP_SOURCE = {
    ("Sova", "C"): ("glyph", "game data TX_UI_Minimap_Hunter_C; [domain:abilities/minimap-textures-sova]"),
    ("Sova", "Q"): ("not_drawn", "[domain:abilities/sova-shock-bolt-minimap-none]"),
    ("Sova", "E"): ("shape", "[domain:abilities/sova-recon-bolt-minimap-ring]"),
    ("Sova", "X"): ("shape", "[domain:abilities/sova-hunters-fury-minimap-beam]"),
    ("Phoenix", "C"): ("shape", "[domain:abilities/phoenix-blaze] [domain:abilities/phoenix-blaze-no-minimap-icon]"),
    ("Phoenix", "Q"): ("not_drawn", "[domain:abilities/phoenix-minimap-objects]"),
    ("Phoenix", "E"): ("not_drawn", "[domain:abilities/phoenix-minimap-objects]"),
    ("Phoenix", "X"): ("not_drawn", "[domain:abilities/phoenix-minimap-objects]"),
    ("Skye", "C"): ("shape", "[domain:abilities/skye-regrowth-minimap-ring]"),
    ("Skye", "Q"): ("glyph", "game data TX_UI_Minimap_Guide_Q (no domain fact for the own view)"),
    ("Skye", "E"): ("glyph", "[domain:abilities/skye-guiding-light-minimap-icon] [domain:abilities/minimap-textures-skye]"),
    ("Skye", "X"): ("glyph", "game data TX_UI_Minimap_Guide_X (no domain fact for the own view)"),
    ("Clove", "E"): ("smoke", "[domain:abilities/clove-rouse]"),
    ("Clove", "C"): ("not_drawn", "[domain:abilities/clove-rouse]: Ruse is the only Clove ability drawn"),
    ("Clove", "Q"): ("not_drawn", "[domain:abilities/clove-rouse]: Ruse is the only Clove ability drawn"),
    ("Clove", "X"): ("not_drawn", "[domain:abilities/clove-rouse]: Ruse is the only Clove ability drawn"),
    ("Iso", "Q"): ("glyph", "game data TX_UI_Minimap_Iso_Q_InActive; [domain:abilities/minimap-textures-iso]"),
    ("Iso", "C"): ("glyph", "game data TX_UI_MinimapIsoWall (no domain fact)"),
    ("Iso", "E"): ("not_drawn", "game data names no minimap texture (no domain fact)"),
    ("Iso", "X"): ("not_drawn", "game data names no minimap texture (no domain fact)"),
}
GAMEDATA = STORE / "reference" / "ability-states" / "ability-states-gamedata-0.2.0.json"


def demo_source(agent: str, slot: str, ability: str, G) -> tuple[str, str]:
    """A demo agent's slot: the match table where it covers it, else the glyph eval's own shape/smoke set
    (searched by no stored owner on demos), else the game data's minimap textures."""
    if (agent, slot) in MINIMAP_SOURCE:
        return MINIMAP_SOURCE[(agent, slot)]
    nm = (ability or "").lower()
    if nm in G.SHAPES or "smoke" in nm:
        return "shape", "minimap_glyph_eval.SHAPES (shape-class; no stored owner rows on demos)"
    tex = _gamedata_textures().get((agent, slot))
    if tex:
        return "glyph", "game data " + ",".join(tex[:3])
    return "not_drawn", "game data names no minimap texture"


_GD: dict = {}


def _gamedata_textures() -> dict:
    import re
    if not _GD:
        d = json.load(open(GAMEDATA, encoding="utf-8"))["agents"]
        for ag, v in d.items():
            for k, ab in v["abilities"].items():
                s = json.dumps(ab)
                _GD[(ag, k)] = sorted(set(re.findall(r"TX_[A-Za-z0-9_]*[Mm]inimap[A-Za-z0-9_]*", s)))
    return _GD


# ------------------------------------------------------------------ channel A


def audio_rows_match(store, sid: str, g: dict) -> tuple[list[dict], dict]:
    from reticle.ability_timeline import audio_cast_witness
    res = audio_cast_witness(store.root, sid, g["rows"], g["agent"], g["kit_spans"])
    return res["rows"], res["coverage"]


def audio_rows_demo(sid: str, truth: list[dict]) -> tuple[list[dict], dict]:
    from reticle.ability_audio_fit import demo_session
    from reticle.ability_timeline import audio_cast_witness
    agent = truth[0]["agent"]
    s = demo_session(STORE, sid)
    rows = [{"t_ms": t["t_ms"], "slot": t["slot"], "player_cast": True} for t in truth]
    res = audio_cast_witness(STORE, sid, rows, agent, None, session=s)
    return res["rows"], res["coverage"]


def a_outcome(row: dict | None) -> tuple[str, str | None]:
    if row is None:
        return "refused", "no_audio_row"
    if row.get("verdict") is None:
        return "refused", row.get("reason") or "no_verdict"
    return ("right" if row["verdict"] == row["slot"] else "wrong"), None


# ------------------------------------------------------------------ channel B


def shape_rows(sid: str) -> dict:
    """{(slot, round(cast_t_ms)): [shape rows]} from the stored ability_shape stream."""
    out = defaultdict(list)
    f = STORE / "events" / "ability_shape" / f"{sid}.jsonl"
    if f.exists():
        for ln in open(f, encoding="utf-8"):
            r = json.loads(ln)
            if r.get("kind") == "shape":
                out[(r["slot"], int(round(r["cast_t_ms"])))].append(r)
    return out


def shape_outcome(rows: list[dict] | None) -> tuple[str, str | None, dict]:
    if not rows:
        return "unobserved", "no_owner_rows", {}
    found = [r for r in rows if r.get("found")]
    info = {"n_samples": len(rows), "n_found": len(found), "ability": rows[0].get("ability")}
    if found:
        return "right", None, info
    why = Counter(r.get("reason") or "not_found" for r in rows).most_common(1)[0][0]
    return "refused", why, info


def smoke_tracks(sid: str) -> int | None:
    """The number of stored smoke track rows of the session (events/smoke), or None when it stores no stream."""
    f = STORE / "events" / "smoke" / f"{sid}.jsonl"
    if not f.exists():
        return None
    return sum(1 for ln in open(f, encoding="utf-8") if '"kind":"track"' in ln.replace(" ", ""))


def smoke_outcome(n_tracks: int | None) -> tuple[str, str, dict]:
    """A smoke cast is unobserved: no stream, or a stream with no onset rule registered to score it."""
    if n_tracks is None:
        return "unobserved", "no_smoke_stream", {}
    return "unobserved", "smoke_rows_unscored (no onset rule was registered)", {"n_tracks": n_tracks}


def self_seed_track(store, sid: str):
    """(t_ms, sx, sy) of the stored minimap table, or None."""
    try:
        man = store.read_manifest(sid)
        mm = store.read_minimap(sid, man["ingested_at"][:10])
    except (SystemExit, Exception):  # noqa: BLE001
        return None
    return (np.asarray(mm.column("t_ms").to_pylist(), float), mm.column("self_x").to_pylist(),
            mm.column("self_y").to_pylist())


def glyph_follows(store, sid: str, casts: list[dict], agent: str, G) -> dict:
    """{cast index: follow result} for every cast, by the glyph matcher's follow from the self seed."""
    import cv2
    from reticle import ability_shapes, geometry
    c, why, _ = G.crop_cache(sid)
    if c is None:
        return {i: {"refused": f"no_crop_cache:{why}"} for i in range(len(casts))}
    x0, y0, x1, y1 = c.rect_of("minimap")
    h = np.asarray(c.holds())
    plan = {i: [float(t) for t in h[(h >= r["t_ms"] - 1e-6) & (h <= r["t_ms"] + FOLLOW_MS)]]
            for i, r in enumerate(casts)}
    need_all = sorted({t for v in plan.values() for t in v})
    vis = G.vision_rows(sid, need_all)
    track = self_seed_track(store, sid)
    try:
        st = geometry.reference_static(sid, str(STORE))
        static_Y = G.luma(st if st.ndim == 3 else cv2.cvtColor(st, cv2.COLOR_GRAY2BGR))
    except (SystemExit, Exception):  # noqa: BLE001
        static_Y = None
    kit_keys = sorted(G.kit(agent))
    out = {}
    order = sorted(plan, key=lambda i: casts[i]["t_ms"])
    for b in range(0, len(order), 12):            # decode the cache in chunks: memory stays small
        chunk = order[b:b + 12]
        need = sorted({t for i in chunk for t in plan[i]})
        got = {s.t_ms: s.frame[y0:y1, x0:x1].copy() for s in c.samples(need, rois=["minimap"])}
        for i in chunk:
            r, ts = casts[i], plan[i]
            ts = [t for t in ts if t in got]
            if not ts:
                out[i] = {"refused": "no_cached_frame"}
                continue
            first = got[ts[0]]
            scale = first.shape[1] / 465.0
            seed, seed_src = None, None
            if track is not None:
                seed = ability_shapes.seed_from_track(track[0], track[1], track[2], r["t_ms"])
                seed_src = "minimap table self (seed_from_track)"
            if seed is None:
                for t in ts[:4]:
                    sel = [(x, y) for role, x, y in (vis.get(round(t, 3), (None, []))[1] or []) if role == "self"]
                    if sel:
                        seed, seed_src = sel[0], f"team_vision self at +{t - r['t_ms']:.0f} ms"
                        break
            if seed is None:
                out[i] = {"refused": "no_self_seed"}
                continue
            icons0 = vis.get(round(ts[0], 3), (None, []))[1] or []
            crowd = sum(1 for role, x, y in icons0 if role != "self"
                        and np.hypot(x - seed[0], y - seed[1]) <= 2 * G.OCC_R * scale)
            terms = G.icon_terms(sid, first.shape)
            sY = static_Y if static_Y is not None and static_Y.shape == first.shape[:2] else None
            item = {"kit": [f"{k[0]}:{k[1]}" for k in kit_keys], "scale": scale, "cx": float(seed[0]),
                    "cy": float(seed[1]), "t_held": ts[0]}
            f = G.follow_item(item, [(t, got[t]) for t in ts], vis, terms, sY)
            st_ = f["steps"]
            last = next((s for s in reversed(st_) if s.get("skip") is None), None)
            out[i] = {"pred": f.get("pred") if f["decided_by"] == "follow" else None,
                      "decided_by": f["decided_by"], "n_clean": f["n_clean"], "margin": f.get("margin"),
                      "mean": f.get("mean"), "seed": [float(seed[0]), float(seed[1])], "seed_source": seed_src,
                      "scale": scale, "crowd": crowd, "n_frames": len(ts),
                      "skips": dict(Counter(s["skip"] for s in st_ if s.get("skip"))),
                      "end_dist": (None if last is None else
                                   float(np.hypot(last["x"] - seed[0], last["y"] - seed[1]) / scale))}
        del got
    return out


def glyph_outcome(f: dict, slot: str) -> tuple[str, str | None]:
    if f.get("refused"):
        return "refused", f["refused"]
    if f.get("pred") is None:
        return "refused", f.get("decided_by") or "no_clean_frame"
    return ("right" if f["pred"].rsplit(":", 1)[1] == slot else "wrong"), None


# ------------------------------------------------------------------ covariates


def gate_labels(sid: str) -> dict | None:
    from reticle.ability_timeline import AUDIO_GATE_DIR
    p = STORE / AUDIO_GATE_DIR / "labels" / f"{sid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def covariates(t_s: np.ndarray, lab: dict | None, own_t_s: np.ndarray) -> dict:
    """Vectorised per-cast covariates."""
    n = len(t_s)
    out = {"gunfire": np.full(n, None, object), "death_near": np.full(n, None, object)}
    if lab is not None:
        g = np.asarray(lab.get("intervals", {}).get("gunfire") or np.zeros((0, 2)), float).reshape(-1, 2)
        lo, hi = t_s + GUNFIRE_WIN[0], t_s + GUNFIRE_WIN[1]
        out["gunfire"] = ((g[None, :, 0] < hi[:, None]) & (g[None, :, 1] > lo[:, None])).any(1) if len(g) \
            else np.zeros(n, bool)
        d = np.asarray(lab.get("other_deaths") or [], float)
        out["death_near"] = (np.abs(d[None, :] - t_s[:, None]) <= DEATH_WIN).any(1) if len(d) else np.zeros(n, bool)
    dt = np.abs(own_t_s[None, :] - t_s[:, None])
    dt[dt == 0] = np.inf
    out["neighbour"] = (dt <= NEIGHBOUR_S).any(1)
    return out


# ------------------------------------------------------------------ build


def audio_split() -> dict:
    """{sid: (stratum or None, midpoint s or None)} from the parameter set's declared split."""
    from reticle.version import ABILITY_AUDIO_PARAMS_VERSION
    from reticle.adjudication.ability_audio import params_path
    prov = json.loads((params_path(STORE, ABILITY_AUDIO_PARAMS_VERSION) / "provenance.json").read_text("utf-8"))
    out = {}
    for agent, sp in prov["split"].items():
        for kind in ("dev", "held"):
            for name in sp[kind]:
                sid, _, half = name.partition(":")
                out.setdefault(sid, {})[half or "all"] = kind
    return out


def half_mid_s(sid: str) -> float | None:
    from reticle.ability_timeline import AUDIO_GATE_DIR
    from reticle.adjudication.ability_audio import FPS
    fp = STORE / AUDIO_GATE_DIR / "features" / f"{sid}.npz"
    if not fp.is_file():
        return None
    with np.load(fp, allow_pickle=True) as z:
        return len(z["ok"]) / (2 * FPS)


def glyph_label_sessions() -> set:
    p = STORE / "analysis" / "minimap-glyphs-20261004" / "items.json"
    return {r["sid"] for r in json.load(open(p, encoding="utf-8"))["items"]} if p.exists() else set()


def build_session(store, sid, kind, agent, casts, audio_rows, split, lab, G, glyph_sids):
    """Rows for one session's casts: A, B, covariates."""
    shapes = shape_rows(sid)
    smoke = smoke_tracks(sid)
    by_t = {(r["slot"], int(round(r["t_ms"]))): r for r in audio_rows}
    t_s = np.array([c["t_ms"] / 1000.0 for c in casts])
    cov = covariates(t_s, lab, t_s)
    follows = glyph_follows(store, sid, casts, agent, G) if G.kit(agent) else {}
    sp = split.get(sid, {})
    mid = half_mid_s(sid) if ("first" in sp or "second" in sp) else None
    rows = []
    for i, c in enumerate(casts):
        slot = c["slot"]
        ar = by_t.get((slot, int(round(c["t_ms"]))))
        a, a_why = a_outcome(ar)
        if kind == "demo":
            src, basis = demo_source(agent, slot, c.get("ability"), G)
            stratum = "demo"
        else:
            src, basis = MINIMAP_SOURCE.get((agent, slot), ("unknown", "no table row"))
            stratum = sp.get("all") or (sp.get("first") if mid is not None and c["t_ms"] / 1000 < mid
                                        else sp.get("second"))
        f = follows.get(i, {"refused": "no_kit_glyphs"})
        g_out, g_why = glyph_outcome(f, slot)
        if src == "glyph":
            b, b_why, b_info = g_out, g_why, {}
        elif src == "shape":
            b, b_why, b_info = shape_outcome(shapes.get((slot, int(round(c["t_ms"])))))
        elif src == "smoke":
            b, b_why, b_info = smoke_outcome(smoke)
        elif src == "not_drawn":
            b, b_why, b_info = "not_drawn", None, {}
        else:
            b, b_why, b_info = "unobserved", "no_source_fact", {}
        rows.append({
            "version": VERSION, "sid": sid, "kind": kind, "agent": agent, "slot": slot,
            "ability": c.get("ability"), "t_ms": float(c["t_ms"]), "audio_stratum": stratum,
            "glyph_label_session": sid in glyph_sids,
            "A": a, "A_reason": a_why, "A_verdict": ar and ar.get("verdict"),
            "A_best_ref": ar and ar.get("best_ref"), "A_margin_ref": ar and ar.get("margin_ref"),
            "A_p_right": ar and ar.get("p_right"),
            "B_source": src, "B_basis": basis, "B": b, "B_reason": b_why, "B_info": b_info,
            "glyph": g_out, "glyph_reason": g_why, "glyph_follow": {k: v for k, v in f.items() if k != "mean"},
            "glyph_mean": f.get("mean"), "census_class": c.get("census_class"),
            "gunfire": None if cov["gunfire"][i] is None else bool(cov["gunfire"][i]),
            "death_near": None if cov["death_near"][i] is None else bool(cov["death_near"][i]),
            "neighbour": bool(cov["neighbour"][i]), "crowd": f.get("crowd")})
    return rows


def build_dir(out: str | None, resume: bool) -> Path:
    """The directory a build writes: a new versioned one by default. A directory that already holds output is
    refused unless `resume` continues it, so a rerun never deletes or overwrites stored evidence."""
    if out is None:
        if resume:
            raise SystemExit("--resume needs --out naming the directory to continue")
        d = ANALYSIS / f"{VERSION}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    else:
        d = Path(out)
    if d.exists() and any(d.iterdir()) and not resume:
        raise SystemExit(f"refusing to write into {d}: it holds output; pass --resume to continue it, "
                         "or omit --out for a new versioned directory")
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_build(args) -> None:
    out_dir = build_dir(args.out, args.resume)      # refuse before any work
    from prototypes import minimap_glyph_eval as G
    from reticle.ability_audio_fit import demo_truth, gate_snapshot
    from reticle.store import Store
    from reticle.version import ABILITY_AUDIO_PARAMS_VERSION, ABILITY_AUDIO_VERSION
    G.build_extra(G.PROBE_STATES, answers=True)
    store = Store(str(STORE))
    only = set(args.only.split(",")) if args.only else None
    split = audio_split()
    glyph_sids = glyph_label_sessions()
    matches = sorted(p.stem for p in (STORE / "events" / "ability_state").glob("*.jsonl"))
    demos = [] if args.no_demos else sorted(p.stem for p in (STORE / "labels" / "demo_cast_class").glob("*.jsonl"))
    out_f = out_dir / ("casts.jsonl" if only is None else "casts-sample.jsonl")
    done = set()
    if args.resume and out_f.exists():
        done = {json.loads(ln)["sid"] for ln in open(out_f, encoding="utf-8")}
    print(f"writing {out_f}", flush=True)
    t0 = time.time()
    log = {"version": VERSION, "ability_audio": ABILITY_AUDIO_VERSION, "params": ABILITY_AUDIO_PARAMS_VERSION,
           "follow": G.FOLLOW_VERSION, "sessions": {}}
    for sid in matches + demos:
        if (only and sid not in only) or sid in done:
            continue
        kind = "demo" if sid in demos else "match"
        try:
            if kind == "match":
                g = gate_snapshot(store, [sid], {}).get(sid)
                if g is None:
                    log["sessions"][sid] = "no_agent"
                    continue
                agent = g["agent"]
                casts = [{"t_ms": r["t_ms"], "slot": r["slot"]} for r in g["rows"] if r["player_cast"]]
                arows, acov = audio_rows_match(store, sid, g)
                lab = gate_labels(sid)
            else:
                truth = demo_truth(STORE, sid)
                raw = {json.loads(x)["key"]: json.loads(x) for x in
                       (STORE / "labels" / "demo_cast_class" / f"{sid}.jsonl").read_text("utf-8").splitlines()
                       if x.strip()}
                agent = truth[0]["agent"]
                casts = [{"t_ms": t["t_ms"], "slot": t["slot"], "ability": raw[t["key"]].get("ability"),
                          "census_class": raw[t["key"]].get("class")} for t in truth]
                try:
                    arows, acov = audio_rows_demo(sid, truth)
                except Exception as e:  # noqa: BLE001
                    arows, acov = [], {"reason": f"demo_audio:{type(e).__name__}:{e}"}
                lab = gate_labels(sid)
            rows = build_session(store, sid, kind, agent, casts, arows, split, lab, G, glyph_sids)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            log["sessions"][sid] = f"error:{type(e).__name__}:{e}"
            continue
        with open(out_f, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, default=float) + "\n")
        log["sessions"][sid] = {"kind": kind, "agent": agent, "casts": len(rows),
                                "audio_coverage_reason": acov.get("reason")}
        print(f"{sid} {kind} {agent} casts {len(rows)} A {dict(Counter(r['A'] for r in rows))} "
              f"B {dict(Counter(r['B'] for r in rows))} {time.time() - t0:.0f}s", flush=True)
    log["wall_s"] = round(time.time() - t0, 1)
    json.dump(log, open(out_dir / ("build_log.json" if only is None else "build_log-sample.json"), "w"), indent=1)


# ------------------------------------------------------------------ report

FAIL = ("wrong", "refused")
OBS = ("right", "wrong", "refused")


def table(rows):
    """3x3 counts A x B over (right, wrong, refused) and the 2x2 fail table [[both ok? ...]]."""
    t3 = {a: {b: 0 for b in OBS} for a in OBS}
    for r in rows:
        t3[r["A"]][r["B"]] += 1
    af = np.array([r["A"] in FAIL for r in rows])
    bf = np.array([r["B"] in FAIL for r in rows])
    t2 = [[int((af & bf).sum()), int((af & ~bf).sum())], [int((~af & bf).sum()), int((~af & ~bf).sum())]]
    return t3, t2, af, bf


def odds(t2):
    from scipy.stats import fisher_exact
    from scipy.stats.contingency import odds_ratio
    n = sum(map(sum, t2))
    if n == 0:
        return None
    try:
        r = odds_ratio(t2, kind="conditional")
        ci = r.confidence_interval(0.95)
        est, lo, hi = float(r.statistic), float(ci.low), float(ci.high)
    except Exception as e:  # noqa: BLE001
        est, lo, hi = None, None, None
    p = float(fisher_exact(t2)[1])
    return {"or_cmle": est, "ci95": [lo, hi], "fisher_p": p}


def summary(rows) -> dict:
    if not rows:
        return {"n": 0}
    t3, t2, af, bf = table(rows)
    n = len(rows)
    pa, pb, pab = af.mean(), bf.mean(), (af & bf).mean()
    return {"n": n, "table3_A_rows_B_cols": t3, "table2_[[Afail&Bfail, Afail&Bok],[Aok&Bfail, Aok&Bok]]": t2,
            "P_A_fail": round(float(pa), 4), "P_B_fail": round(float(pb), 4), "P_both": round(float(pab), 4),
            "P_both_if_independent": round(float(pa * pb), 4),
            "n_both": int((af & bf).sum()), "n_both_expected": round(float(pa * pb * n), 2),
            "P_B_fail_given_A_fail": None if not af.any() else round(float(bf[af].mean()), 4),
            "P_B_fail_given_A_ok": None if af.all() else round(float(bf[~af].mean()), 4),
            "P_A_fail_given_B_fail": None if not bf.any() else round(float(af[bf].mean()), 4),
            "P_A_fail_given_B_ok": None if bf.all() else round(float(af[~bf].mean()), 4),
            **(odds(t2) or {})}


#: Strata of the Mantel-Haenszel estimates. All were chosen after registration (the registered statistic is the
#: pooled conditional odds ratio); "source" is the headline because the pooled figure mixes two minimap sources
#: whose failure rates run in opposite directions (Simpson's paradox).
STRATA = {
    "source": lambda r: r["B_source"],
    "agent_slot": lambda r: f"{r['agent']}:{r['slot']}",
    "session": lambda r: r["sid"],
    "session_source": lambda r: f"{r['sid']}:{r['B_source']}",
}


def mantel_haenszel(rows, key="sid") -> dict:
    """The Mantel-Haenszel odds ratio of joint failure over strata, with the Robins-Breslow-Greenland 95% CI.
    `key` is a row field or a function of the row. Vectorised: the four cells of every stratum come from one
    bincount over (stratum, cell)."""
    if not rows:
        return {"n": 0, "strata": 0, "or_mh": None}
    kf = key if callable(key) else (lambda r, k=key: r[k])
    labels, inv = np.unique(np.array([str(kf(r)) for r in rows]), return_inverse=True)
    af = np.fromiter((r["A"] in FAIL for r in rows), bool, len(rows))
    bf = np.fromiter((r["B"] in FAIL for r in rows), bool, len(rows))
    cell = 2 * (~af) + (~bf)                 # 0 both fail, 1 A fails only, 2 B fails only, 3 neither
    T = np.bincount(inv * 4 + cell, minlength=4 * len(labels)).reshape(-1, 4).astype(float)
    a, b, c, d = T.T
    n = T.sum(1)
    ok = n > 1
    tables = {str(lb): [int(x) for x in t] for lb, t in zip(labels, T)}
    a, b, c, d, n = a[ok], b[ok], c[ok], d[ok], n[ok]
    R, S = a * d / n, b * c / n
    out = {"n": len(rows), "strata": int(ok.sum()), "strata_tables_[both,A_only,B_only,neither]": tables}
    if R.sum() == 0 or S.sum() == 0:
        return {**out, "or_mh": None}
    P, Q = (a + d) / n, (b + c) / n
    orr = R.sum() / S.sum()
    var = ((P * R).sum() / (2 * R.sum() ** 2) + ((P * S + Q * R).sum()) / (2 * R.sum() * S.sum())
           + (Q * S).sum() / (2 * S.sum() ** 2))
    se = float(np.sqrt(var))
    return {**out, "or_mh": round(float(orr), 3),
            "ci95": [round(float(orr * np.exp(-1.96 * se)), 3), round(float(orr * np.exp(1.96 * se)), 3)]}


def g1_verdict(est: float | None, lo: float | None) -> str:
    """The pre-registered rule for the player's guess (odds ratio of joint failure <= 2)."""
    if est is None or lo is None:
        return "undetermined"
    if lo > 2:
        return "refuted"
    if est > 2:
        return "inconclusive, leans against (point estimate above 2, CI spans 2)"
    return "holds (point estimate <= 2)"


#: Shape-owner refusals where the owner holds no descriptor for the map: the minimap cannot be read for that
#: ability there (a coverage gap of the appearance facts), the sensitivity arm moves them to unobserved.
#: Chosen after registration and after seeing the joint failures (post_registration).
NO_DESCRIPTOR = ("no_radius_on_map", "no_descriptor")


def rr(rows, cov, ch) -> dict | None:
    on = [r for r in rows if r.get(cov) is True or (isinstance(r.get(cov), (int, float)) and
                                                     not isinstance(r.get(cov), bool) and r[cov] > 0)]
    off = [r for r in rows if r.get(cov) is False or r.get(cov) == 0]
    if not on or not off:
        return {"n_on": len(on), "n_off": len(off)}
    f_on = np.mean([r[ch] in FAIL for r in on])
    f_off = np.mean([r[ch] in FAIL for r in off])
    return {"n_on": len(on), "n_off": len(off), "fail_on": round(float(f_on), 4), "fail_off": round(float(f_off), 4),
            "rr": None if f_off == 0 else round(float(f_on / f_off), 3)}


def joint_conditions(rows) -> dict:
    out = {}
    for cov in ("gunfire", "death_near", "neighbour", "crowd"):
        out[cov] = {"A": rr(rows, cov, "A"), "B": rr(rows, cov, "B"),
                    "both_fail": None}
        on = [r for r in rows if r.get(cov) not in (None, False, 0)]
        off = [r for r in rows if r.get(cov) in (False, 0)]
        if on and off:
            j_on = np.mean([r["A"] in FAIL and r["B"] in FAIL for r in on])
            j_off = np.mean([r["A"] in FAIL and r["B"] in FAIL for r in off])
            out[cov]["both_fail"] = {"on": round(float(j_on), 4), "off": round(float(j_off), 4)}
            out[cov]["or_within_on"] = summary(on).get("or_cmle")
            out[cov]["or_within_off"] = summary(off).get("or_cmle")
    return out


#: B refusals that say the stored input is absent, not that the minimap failed: the cast was never observed.
UNOBSERVED_PREFIX = ("no_crop_cache", "no_cached_frame")


def absent_as_unobserved(r: dict) -> dict:
    """Move refusals that say an input is absent to "unobserved". Chosen after registration (post_registration):
    the registration counted every refusal as a failure; the report gives the headline both ways."""
    if r["B"] == "refused" and str(r.get("B_reason") or "").startswith(UNOBSERVED_PREFIX):
        r = {**r, "B": "unobserved"}
    if r["A"] == "refused" and r.get("A_reason") in ("audio_not_live", "no_audio_row"):
        r = {**r, "A": "unobserved"}     # the gate's frame is not live, or the demo has no stored log-mel
    return r


#: What the tray gate shares between the channels; stated in every report beside the headline.
SHARED_GATE = (
    "Dependence built in by construction: every channel is anchored on the tray drop. Audio takes the drop as the "
    "cast frame, cuts its window at neighbouring drops and excludes null frames by them; the glyph window starts at "
    "the drop; the shape owner reads the drop time and the truth slot's descriptor. Shape-owner 'right' means "
    "'detected, given the truth slot', and its precision of 1.0 holds by construction. A wrong tray cast, or a "
    "context both channels share, fails both at once.")

BORROWED_LABEL = (
    "A borrowed label declares rests_on its source witness and version (e.g. "
    "ability_shape:<sid>:<cast>@ability-shape-0.4.0) and the tray drop / player_cast it was anchored on "
    "(tray_drop:<sid>:<t_ms>); a shape-owner label's slot is the tray's.")

POST_REGISTRATION = {
    "normalise": "moves B refusals no_crop_cache*/no_cached_frame and A refusals audio_not_live/no_audio_row to "
                 "unobserved; the registration counted every refusal as a failure",
    "strata": "every Mantel-Haenszel stratification (source, agent_slot, session, session_source); the "
              "registered statistic is the pooled conditional odds ratio",
    "no_descriptor": "the NO_DESCRIPTOR comparisons, chosen after seeing the joint failures",
    "stale_cache": "b3b9defb6fd7's casts are a stale crop cache (no_crop_cache:stale_rects), counted apart from "
                   "missing owner rows",
}


def coverage_of(R) -> dict:
    """Which channels observe each cast; an unobserved B names why (draws nothing, stale or missing crop cache,
    no smoke stream, no owner rows)."""
    cov = Counter()
    for r in R:
        a_obs = r["A"] in OBS
        why = str(r.get("B_reason") or "")
        if not a_obs and r["B"] in ("not_drawn", "unobserved"):
            cov["neither"] += 1
        elif r["B"] == "not_drawn":
            cov["audio_only:minimap_draws_nothing"] += 1
        elif r["B"] == "unobserved" and why.startswith(UNOBSERVED_PREFIX):
            cov["audio_only:stale_or_missing_crop_cache"] += 1
        elif r["B"] == "unobserved" and r["B_source"] == "smoke":
            cov["audio_only:no_smoke_rows"] += 1
        elif r["B"] == "unobserved":
            cov["audio_only:no_minimap_owner_rows"] += 1
        elif not a_obs:
            cov["minimap_only:audio_not_scored"] += 1
        else:
            cov["both"] += 1
    return {"n": len(R), **dict(cov),
            "audio_not_scored_reasons": dict(Counter(r["A_reason"] for r in R if r["A"] in ("refused", "unobserved"))),
            "unobserved_B_by_session_reason": {f"{s}|{w}": n for (s, w), n in sorted(Counter(
                (r["sid"], r["B_reason"]) for r in R if r["B"] == "unobserved").items())}}


def audio_precision(rows) -> dict:
    """{agent:slot: casts, named, right} of the audio witness over every match cast it scored, minimap or not."""
    out = {}
    by = defaultdict(list)
    for r in rows:
        by[f"{r['agent']}:{r['slot']}"].append(r["A"])
    for k, A in sorted(by.items()):
        a = np.array(A)
        named = np.isin(a, ("right", "wrong"))
        out[k] = {"casts": len(a), "named": int(named.sum()), "right": int((a == "right").sum()),
                  "precision": None if not named.any() else round(float((a == "right").sum() / named.sum()), 4)}
    return out


def glyph_eval_overlap(rows) -> dict:
    """How far the glyph eval's labelled items (on which the follow's parameters were fitted) overlap these match
    casts: items per split in the match sessions, and casts with an item within -0.5 to +3.5 s of the drop."""
    p = ANALYSIS / "minimap-glyphs-20261004" / "items.json"
    if not p.exists():
        return {"items_file": None}
    items = json.load(open(p, encoding="utf-8"))["items"]
    match = [r for r in rows if r["kind"] == "match"]
    sids = {r["sid"] for r in match}
    it = [i for i in items if i["sid"] in sids]
    near = 0
    for sid in sorted({i["sid"] for i in it}):
        ti = np.array([i["t_ms"] for i in it if i["sid"] == sid], float)
        tc = np.array([r["t_ms"] for r in match if r["sid"] == sid], float)
        d = ti[None, :] - tc[:, None]
        near += int(((d >= -500) & (d <= 3500)).any(1).sum())
    return {"sessions_with_items": len({i["sid"] for i in it}),
            "match_casts_in_those_sessions": sum(r["sid"] in {i["sid"] for i in it} for r in match),
            "items_by_split": dict(Counter(i.get("split") for i in it)),
            "casts_with_item_within_-0.5_+3.5_s": near}


def smoke_stream_check(rows) -> dict:
    """The smoke stream of every session holding a smoke-source cast: the registration's 'stored smoke rows'."""
    return {sid: smoke_tracks(sid) for sid in sorted({r["sid"] for r in rows if r["B_source"] == "smoke"})}


def headline(match) -> dict:
    """The source-stratified Mantel-Haenszel estimate, its agent-slot companion, and the pre-registered verdict."""
    out = {}
    for k in ("source", "agent_slot"):
        m = mantel_haenszel(match, STRATA[k])
        lo = (m.get("ci95") or [None])[0]
        out[k] = {**{x: m[x] for x in ("n", "strata", "or_mh") if x in m}, "ci95": m.get("ci95"),
                  "excludes_1": None if lo is None else bool(lo > 1 or m["ci95"][1] < 1),
                  "G1_verdict": g1_verdict(m.get("or_mh"), lo)}
    return out


def cmd_report(args) -> None:
    d = Path(args.dir)
    raw = [json.loads(ln) for ln in open(d / "casts.jsonl", encoding="utf-8")]
    rows = [absent_as_unobserved(r) for r in raw]
    both = [r for r in rows if r["A"] in OBS and r["B"] in OBS]
    match = [r for r in both if r["kind"] == "match"]
    raw_match = [r for r in raw if r["kind"] == "match" and r["A"] in OBS and r["B"] in OBS]
    shape = [r for r in match if r["B_source"] == "shape"]
    glyph = [r for r in match if r["B_source"] == "glyph"]
    pooled = summary(match)
    rep = {"version": VERSION, "casts_version": sorted({r["version"] for r in raw}), "n_casts": len(rows),
           "headline": {"estimate": "Mantel-Haenszel odds ratio of joint failure on match casts both channels "
                                    "observe, stratified by minimap source (post_registration)",
                        **headline(match),
                        "rule": "pre-registered G1: guess holds at odds ratio <= 2; refuted when the 95% CI's "
                                "lower bound exceeds 2; a point estimate above 2 with the CI spanning 2 is "
                                "inconclusive",
                        "registered_pooled_or": {"or_cmle": pooled.get("or_cmle"), "ci95": pooled.get("ci95"),
                                                 "note": "Simpson's paradox: below both source strata"},
                        "without_normalise": headline(raw_match)},
           "shared_gate": SHARED_GATE, "borrowed_label": BORROWED_LABEL, "post_registration": POST_REGISTRATION,
           "coverage": {}, "pooled_match": pooled, "pooled_match_held_audio": summary(
               [r for r in match if r["audio_stratum"] == "held"]),
           "pooled_match_glyph_only": summary(glyph),
           "pooled_match_shape_only": summary(shape),
           "pooled_demo": summary([r for r in both if r["kind"] == "demo"]),
           "per_agent_ability": {}, "conditions_match": joint_conditions(match),
           "conditions_match_glyph": joint_conditions(glyph)}
    for kind in ("match", "demo"):
        rep["coverage"][kind] = coverage_of([r for r in rows if r["kind"] == kind])
    by = defaultdict(list)
    for r in both:
        by[(r["kind"], r["agent"], r["slot"])].append(r)
    for (kind, agent, slot), R in sorted(by.items()):
        rep["per_agent_ability"][f"{kind}:{agent}:{slot}"] = {"ability": R[0].get("ability"),
                                                              "B_source": R[0]["B_source"], **summary(R)}
    by_agent = defaultdict(list)
    for r in match:
        by_agent[r["agent"]].append(r)
    rep["per_agent_match"] = {a: summary(R) for a, R in sorted(by_agent.items())}
    rep["audio_precision_by_ability_match"] = audio_precision([r for r in rows if r["kind"] == "match"
                                                               and r["A"] in OBS])
    # B's failures: wrong vs refused, and the controls on casts that draw nothing
    g = [r for r in rows if r["kind"] == "match" and r["B_source"] == "glyph"]
    rep["glyph_failures_match"] = {"n": len(g), **dict(Counter(r["B"] for r in g)),
                                   "refusal_reasons": dict(Counter(r["B_reason"] for r in g if r["B"] == "refused"))}
    ctl = [r for r in rows if r["B"] == "not_drawn"]
    rep["glyph_control_on_not_drawn"] = {
        "n": len(ctl), "named_a_slot": sum(r["glyph"] in ("right", "wrong") for r in ctl),
        "named_the_true_slot": sum(r["glyph"] == "right" for r in ctl),
        "by_kind": {k: dict(Counter(r["glyph"] for r in ctl if r["kind"] == k)) for k in ("match", "demo")}}
    rep["glyph_eval_overlap"] = glyph_eval_overlap(rows)
    rep["smoke_stream_check"] = smoke_stream_check(rows)
    # sensitivity arms: every one chosen after registration
    no_desc = [r for r in shape if str(r.get("B_reason") or "").startswith(NO_DESCRIPTOR)]
    shape_s = [r for r in shape if r not in no_desc]
    jf_nd = [r for r in no_desc if r["A"] in FAIL]
    shape_4 = [r for r in shape if r not in jf_nd]
    rep["sensitivity"] = {
        "post_registration": True,
        **{f"mh_by_{k}_pooled_match": mantel_haenszel(match, f) for k, f in STRATA.items()},
        "mh_by_session_shape": mantel_haenszel(shape),
        "mh_by_session_glyph": mantel_haenszel(glyph),
        "no_descriptor_casts": {"n": len(no_desc), "A": dict(Counter(f"{r['A']}:{r['A_reason'] or r['A_verdict']}"
                                                                     for r in no_desc))},
        "shape_without_all_no_descriptor_casts": summary(shape_s),
        "shape_without_the_no_descriptor_joint_failures": {
            "dropped": [{k: r[k] for k in ("sid", "t_ms", "A", "A_reason", "A_verdict")} for r in jf_nd],
            **summary(shape_4)},
        "mh_by_session_shape_without_no_descriptor": mantel_haenszel(shape_s),
        "pooled_match_without_no_descriptor": summary(
            [r for r in match if not str(r.get("B_reason") or "").startswith(NO_DESCRIPTOR)]),
        "sova_E_without_no_descriptor": summary([r for r in shape_s if r["agent"] == "Sova" and r["slot"] == "E"]),
        "glyph_label_session": summary([r for r in glyph if r["glyph_label_session"]]),
        "glyph_not_label_session": summary([r for r in glyph if not r["glyph_label_session"]]),
        "shape_audio_held": summary([r for r in shape if r["audio_stratum"] == "held"]),
        "shape_audio_dev": summary([r for r in shape if r["audio_stratum"] == "dev"])}
    rep["direction"] = direction(match)
    rep["direction_shape"] = direction(shape, b_note="shape owner: detection given the truth slot; it cannot name "
                                                     "another slot, so its precision is 1.0 by construction")
    rep["direction_glyph"] = direction(glyph)
    jf = [r for r in match if r["A"] in FAIL and r["B"] in FAIL]
    rep["joint_failures_match"] = [{k: r[k] for k in ("sid", "agent", "slot", "t_ms", "A", "A_reason", "A_verdict",
                                                      "B_source", "B", "B_reason", "gunfire", "death_near",
                                                      "neighbour", "crowd")} for r in jf]
    rep["A_fail_reasons_by_B"] = {b: dict(Counter(f"{r['A']}:{r['A_reason']}" for r in match
                                                  if r["B"] == b and r["A"] in FAIL)) for b in OBS}
    rep["census_vs_rule_demo"] = dict(Counter(f"{r['B_source']}|{r.get('census_class')}"
                                              for r in rows if r["kind"] == "demo"))
    out_f = d / f"report-{VERSION}.json"
    if out_f.exists():
        raise SystemExit(f"refusing to overwrite {out_f}")
    json.dump(rep, open(out_f, "w"), indent=1, default=float)
    if args.record:
        record_metrics(rep, d)
    print(f"wrote {out_f}")
    print(json.dumps({k: rep[k] for k in ("headline", "coverage", "glyph_eval_overlap", "smoke_stream_check")},
                     indent=1, default=float))


def record_metrics(rep: dict, d: Path) -> None:
    """Append the corrected headline and the corrected counts to the metrics log."""
    import hashlib
    from reticle import metrics
    casts = d / "casts.jsonl"
    deps = {"casts_sha": hashlib.sha256(casts.read_bytes()).hexdigest()[:16], "report": VERSION,
            "code": metrics.fingerprint(mantel_haenszel, summary, absent_as_unobserved)}
    note = f"{VERSION} report on {d.name}/casts.jsonl ({', '.join(rep['casts_version'])}); post_registration strata"
    for part in ("source", "agent_slot"):
        h = rep["headline"][part]
        metrics.record("cross_channel_independence", part=f"stratified_{part}", session="matches",
                       values={"n": h["n"], "strata": h["strata"], "or_mh": h["or_mh"], "ci_low": h["ci95"][0],
                               "ci_high": h["ci95"][1]}, deps=deps, context={"verdict": h["G1_verdict"]}, note=note)
    m = rep["sensitivity"]["mh_by_session_source_pooled_match"]
    metrics.record("cross_channel_independence", part="stratified_session_source", session="matches",
                   values={"n": m["n"], "strata": m["strata"], "or_mh": m["or_mh"], "ci_low": m["ci95"][0],
                           "ci_high": m["ci95"][1]}, deps=deps, note=note)
    for part, key in (("shape_drop_four_abyss", "shape_without_the_no_descriptor_joint_failures"),
                      ("shape_drop_no_descriptor", "shape_without_all_no_descriptor_casts")):
        s = rep["sensitivity"][key]
        metrics.record("cross_channel_independence", part=part, session="matches",
                       values={"n": s["n"], "n_both": s["n_both"], "or_cmle": round(s["or_cmle"], 3),
                               "ci_low": round(s["ci95"][0], 3), "ci_high": round(s["ci95"][1], 3)},
                       deps=deps, note=note + "; chosen after seeing the joint failures")
    ap = rep["audio_precision_by_ability_match"]
    nd = rep["sensitivity"]["no_descriptor_casts"]["A"]
    cov = rep["coverage"]["match"]
    ge = rep["glyph_eval_overlap"]
    metrics.record("cross_channel_independence", part="corrections", session="matches", values={
        "glyph_eval_items": sum(ge["items_by_split"].values()),
        "glyph_eval_items_heldout": ge["items_by_split"].get("heldout", 0),
        "casts_with_glyph_item_near": ge["casts_with_item_within_-0.5_+3.5_s"],
        "skye_x_audio_named": ap["Skye:X"]["named"], "skye_x_audio_right": ap["Skye:X"]["right"],
        "iso_q_casts": ap["Iso:Q"]["casts"], "iso_c_casts": ap["Iso:C"]["casts"],
        "iso_q_audio_right": ap["Iso:Q"]["right"],
        "stale_cache_casts": cov.get("audio_only:stale_or_missing_crop_cache", 0),
        "abyss_bolt_unknown": sum(v for k, v in nd.items() if k.endswith("bolt_unknown"))},
        deps=deps, note=note)


def direction(rows, b_note: str | None = None) -> dict:
    """When one channel names a slot, how often is the other channel right, and how often is the name itself
    right (the label's precision if it trained the other channel)."""
    out = {}
    for src, oth in (("A", "B"), ("B", "A")):
        named = [r for r in rows if r[src] in ("right", "wrong")]
        out[f"{src}_named"] = {"n": len(named), "precision": None if not named else
                               round(float(np.mean([r[src] == "right" for r in named])), 4),
                               f"{oth}_fail_among_{src}_right": None if not named else
                               round(float(np.mean([r[oth] in FAIL for r in named if r[src] == "right"] or [np.nan])), 4)}
    if b_note:
        out["B_named"]["note"] = b_note
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--only")
    b.add_argument("--no-demos", action="store_true")
    b.add_argument("--out", help="output directory; default a new versioned one under analysis/")
    b.add_argument("--resume", action="store_true", help="continue the --out directory's casts")
    r = sub.add_parser("report")
    r.add_argument("--dir", default=str(OUT), help="a build directory holding casts.jsonl")
    r.add_argument("--record", action="store_true", help="append the metrics rows")
    a = ap.parse_args()
    {"build": cmd_build, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
