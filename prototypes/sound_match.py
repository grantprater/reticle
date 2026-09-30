r"""Run the first sound bank on one match and score it against video witnesses.

    .\.venv\Scripts\python.exe prototypes\sound_match.py decode
    .\.venv\Scripts\python.exe prototypes\sound_match.py refs
    .\.venv\Scripts\python.exe prototypes\sound_match.py detect [--round N]
    .\.venv\Scripts\python.exe prototypes\sound_match.py score [--round N] [--record]

Why this exists
---------------
`sound_bank.py` built references from the player's labels on one range clip.
This file asks which of its classes transfer to a match: the Iso capture on
Split, session 4f207c0c4e39 (`C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`,
game audio only [domain:capture/game-audio-track-only]). The player approved
decoding its audio once (2026-09-29). Predictions and outcomes are in the
store's `notes/predictions.jsonl` under `sound-match-20260929`.

Stages
------
`decode` writes the match's audio once to `<store>/analysis/sound-match/`
as 16-bit stereo PCM; every later stage reads that file. `refs` cuts every
labelled range reference exactly as `sound_bank bank` does. `detect` runs
the bank unchanged (theta 0.50, `sound_bank.detect`) over each round and
keeps each detection's left-right level difference (ILD). `score` reads
only stored streams, never video:

- Held item: the 2 Hz HUD stream. A drawn ammo counter is a gun, named by
  its segment's full reserve [domain:weapons/magazine-and-reserve]; a read
  HUD without one is the knife or an ability
  [domain:abilities/ammo-hidden-while-non-gun-held]. A witnessed equip is a
  change whose two states each hold two samples; a detection matches it from
  0.3 s before the last old sample to 0.3 s after the first new one.
- Shots: the magazine falling while the reserve holds, on one gun segment.
- POV: whose kit the tray shows (`tray-kit` spans). When the player is dead
  the HUD, the audio and the tray all follow the spectated teammate.
- Footsteps: the self track's displacement over +-0.5 s (`minimap`).
- Phase: the gametime owner's barrier drop.

Findings (2026-09-29)
---------------------
Knife equips transfer. Of the gun->hidden changes in the player's own view,
[metric:sound_match/score@4f207c0c4e39#equip_own_nongun_detected=21] of
[metric:sound_match/score@4f207c0c4e39#equip_own_nongun_n=44] hold an equip
detection, [metric:sound_match/score@4f207c0c4e39#equip_own_nongun_right=19]
of them the knife. Most misses are abilities: on 6 of 8 viewed crops a
purple overlay, believed an Iso ability's viewmodel, covers the counter
within 0.5 s. Gun equips do not transfer: recall
[metric:sound_match/score@4f207c0c4e39#equip_own_bank_guns_recall=0.5], the
right gun [metric:sound_match/score@4f207c0c4e39#equip_own_bank_guns_right=3]
of [metric:sound_match/score@4f207c0c4e39#equip_own_bank_guns_detected=8];
the match's other guns have no reference and mostly read as classic_equip.

The audio-video offset, audio onset minus the first HUD sample showing the
new state, has median
[metric:sound_match/score@4f207c0c4e39#equip_own_all_right_offset_median=-0.12] s
(p10 [metric:sound_match/score@4f207c0c4e39#equip_own_all_right_offset_p10=-0.377],
p90 [metric:sound_match/score@4f207c0c4e39#equip_own_all_right_offset_p90=0.099])
over [metric:sound_match/score@4f207c0c4e39#equip_own_all_right_n=22] equips.
At 2 Hz the bracket bounds it; a finer witness must sharpen it.

Own shots do not transfer:
[metric:sound_match/score@4f207c0c4e39#shots_own_vp_detected=14] of
[metric:sound_match/score@4f207c0c4e39#shots_own_vp_brackets=35] Vandal and
Phantom firing brackets hold a shot detection, though crops confirm the
drops. Spectated brackets fare better
([metric:sound_match/score@4f207c0c4e39#shots_other_vp_recall=0.829]).
Shot classes fire mostly on others' guns: where one gun is held on both
sides, [metric:sound_match/score@4f207c0c4e39#shot_own_quiet_frac=0.712] of
own-view shot detections fall while the magazine holds.

Footsteps transfer weakly: the fast bin fires
[metric:sound_match/score@4f207c0c4e39#steps_live_fast_rate=1.297] per second
and the still bin [metric:sound_match/score@4f207c0c4e39#steps_live_still_rate=0.517].
Buy-menu classes do not transfer:
[metric:sound_match/score@4f207c0c4e39#buy_in_buy_phase=139] of
[metric:sound_match/score@4f207c0c4e39#buy_n=545] fall in buy phases.

Stereo separates own sounds from others' without the bank: matched own
equips differ left to right by a median
[metric:sound_match/score@4f207c0c4e39#stereo_matched_equips_abs_ild_median=0.28] dB,
shots in firing brackets
[metric:sound_match/score@4f207c0c4e39#stereo_firing_shots_abs_ild_median=0.71] dB,
shots where the magazine held
[metric:sound_match/score@4f207c0c4e39#stereo_quiet_shots_abs_ild_median=2.18] dB.

This is a prototype; nothing in `reticle/` uses it.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import wave
from collections import Counter, defaultdict
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_var] = "1"

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "prototypes"))
with contextlib.redirect_stdout(io.StringIO()):
    import audio_probe  # noqa: E402
    import sound_bank  # noqa: E402
    import sound_demo  # noqa: E402

VERSION = "sound-match-0.1.0"
STORE = Path.home() / "reticle-store"
OUT = STORE / "analysis" / "sound-match"
SESSION = "4f207c0c4e39"
CAPTURE = r"C:\Users\grant\Videos\2026-09-27 19-40-58.mp4"
WAV = OUT / f"{SESSION}-audio.wav"
REFS = OUT / "refs-20260929.npz"
DETS = OUT / "detections-20260929.jsonl"
RESULT = OUT / "score-20260929.json"
LISTEN = OUT / "listen-20260929.csv"

# ---------------------------------------------------------------------------
# Decode once
# ---------------------------------------------------------------------------


def decode(force: bool = False) -> None:
    """The match's audio, once, to a 16-bit stereo WAV at the file's own rate."""
    if WAV.is_file() and not force:
        print(f"{WAV} exists; not decoding again")
        return
    x, rate = audio_probe.decode(CAPTURE)
    peak = float(np.abs(x).max())
    clipped = int((np.abs(x) > 1.0).sum())
    q = np.clip(np.round(x * 32767.0), -32768, 32767).astype("<i2")
    del x
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = WAV.with_suffix(".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(q.tobytes())
    tmp.replace(WAV)
    man = json.loads((STORE / "manifests" / f"{SESSION}.json").read_text(encoding="utf-8"))
    meta = {"version": VERSION, "session_id": SESSION, "source_path": CAPTURE,
            "content_key": man["source"]["content_key"], "rate": int(rate),
            "frames": int(len(q)), "duration_s": len(q) / rate, "peak": peak,
            "clipped_samples": clipped, "format": "PCM 16-bit stereo, the decoder's own rate",
            "why": "the player approved decoding this match's audio once (2026-09-29); "
                   "every later stage reads this file, never the capture"}
    WAV.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1))


def read_audio(t0: float, t1: float) -> tuple[np.ndarray, int]:
    """[n, 2] float64 of the cached WAV between t0 and t1 seconds."""
    with wave.open(str(WAV), "rb") as w:
        rate = w.getframerate()
        n = w.getnframes()
        a = max(0, int(round(t0 * rate)))
        b = min(n, int(round(t1 * rate)))
        w.setpos(a)
        raw = w.readframes(b - a)
    x = np.frombuffer(raw, "<i2").reshape(-1, 2).astype(np.float64) / 32767.0
    return x, rate


def wav_duration() -> float:
    with wave.open(str(WAV), "rb") as w:
        return w.getnframes() / w.getframerate()


# ---------------------------------------------------------------------------
# References and detection
# ---------------------------------------------------------------------------

HOP = sound_bank.HOP
LEAD_S = sound_bank.LEAD_S
PAD_S = 5.0                      # context read around each round chunk
EQUIP = ("knife_equip", "classic_equip", "vandal_equip", "phantom_equip")
SHOT = tuple(f"{g}_{k}" for g in ("vandal", "phantom") for k in ("single", "burst", "spray"))
MOVE = ("footstep", "jump", "land")
BUY = ("buy_menu_open", "purchase", "buy_menu_close")


def refs() -> dict:
    """Every labelled range reference as a feature patch, exactly as `bank` cuts it."""
    ev = sound_bank.events()
    m, rate = sound_bank.audio()
    D = sound_bank.features(m, rate)
    rr = [e for e in ev if e["cls"] != "other"]
    clen = sound_bank.class_len(rr)
    arrays, meta = {}, []
    for i, e in enumerate(rr):
        n = clen[e["cls"]]
        f0 = int(round((e["t0"] - LEAD_S) / HOP))
        arrays[f"r{i}"] = D[:, f0:f0 + n]
        meta.append({"i": i, "cls": e["cls"], "t0": e["t0"], "variant": e["variant"], "key": e["key"]})
    OUT.mkdir(parents=True, exist_ok=True)
    info = {"version": VERSION, "bank": sound_bank.VERSION, "source_session": sound_bank.SESSION,
            "labels": str(sound_demo.LABELS), "class_len": clen, "refs": meta}
    np.savez_compressed(REFS, info=json.dumps(info), **arrays)
    print(f"{len(rr)} references in {len(clen)} classes -> {REFS}")
    return info


def load_refs() -> tuple[list[tuple[str, np.ndarray]], dict[str, int], dict]:
    z = np.load(REFS)
    info = json.loads(str(z["info"]))
    return [(r["cls"], z[f"r{r['i']}"]) for r in info["refs"]], info["class_len"], info


def rounds() -> list[dict]:
    import pyarrow.parquet as pq
    p = next((STORE / "l2" / "rounds").glob(f"date=*/session={SESSION}/rounds.parquet"))
    return sorted(pq.read_table(p).to_pylist(), key=lambda r: r["round_no"])


def chunks() -> list[tuple[int, float, float]]:
    """(round, t0, t1): each round from its start to the next round's start."""
    rr = rounds()
    starts = [r["t_start_ms"] / 1000.0 for r in rr] + [wav_duration()]
    return [(r["round_no"], starts[i], starts[i + 1]) for i, r in enumerate(rr)]


def detect_chunk(r_no: int, a: float, b: float, rf, clen) -> list[dict]:
    t_off = max(0.0, a - PAD_S)
    x, rate = read_audio(t_off, b + PAD_S)
    D = sound_bank.features(x.mean(axis=1), rate)
    nf = D.shape[1]
    nfft = 1 << int(np.ceil(np.log2(nf + 200)))
    FD = np.fft.rfft(D, nfft, axis=1)
    cs1 = np.concatenate([[0.0], np.cumsum(D.sum(0))])
    cs2 = np.concatenate([[0.0], np.cumsum((D * D).sum(0))])
    classes = sorted(clen)
    S = {c: np.full(nf, -1.0) for c in classes}
    for cls, tpl in rf:
        c = sound_bank.slide_corr(D, FD, nfft, cs1, cs2, tpl)
        np.maximum(S[cls][:len(c)], c, out=S[cls][:len(c)])
    dets = sound_bank.detect(S, clen)
    # Stereo: level difference in the 100 Hz-6 kHz band over each detection's span.
    L = sound_bank.bandpass(x[:, 0], rate) ** 2
    R = sound_bank.bandpass(x[:, 1], rate) ** 2
    cl, cr = np.concatenate([[0.0], np.cumsum(L)]), np.concatenate([[0.0], np.cumsum(R)])
    out = []
    for d in dets:
        t = t_off + d["t"]
        if not (a <= t < b):
            continue
        f = int(round((d["t"] - LEAD_S) / HOP))
        sc = sorted(((float(S[c][f]), c) for c in classes if c != d["cls"]), reverse=True)
        i0 = int(round(d["t"] * rate))
        i1 = i0 + int(round(max(0.1, clen[d["cls"]] * HOP) * rate))
        el, er = cl[min(i1, len(cl) - 1)] - cl[i0], cr[min(i1, len(cr) - 1)] - cr[i0]
        out.append({"round": r_no, "t": round(t, 3), "cls": d["cls"], "score": round(d["score"], 4),
                    "second": sc[0][1], "second_score": round(sc[0][0], 4),
                    "ild_db": round(float(10 * np.log10((el + 1e-12) / (er + 1e-12))), 2),
                    "level_db": round(float(10 * np.log10((el + er) / max(1, i1 - i0) + 1e-12)), 1)})
    return out


def detect(only: int | None) -> None:
    rf, clen, info = load_refs()
    d = OUT / "detections"
    d.mkdir(parents=True, exist_ok=True)
    for r_no, a, b in chunks():
        if only is not None and r_no != only:
            continue
        rows = detect_chunk(r_no, a, b, rf, clen)
        (d / f"r{r_no:02d}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        print(f"round {r_no:>2} {a:7.1f}-{b:7.1f} s: {len(rows)} detections "
              f"{dict(Counter(r['cls'] for r in rows).most_common(6))}", flush=True)


def load_dets(only: int | None = None) -> list[dict]:
    rows = []
    for p in sorted((OUT / "detections").glob("r*.jsonl")):
        if only is not None and p.name != f"r{only:02d}.jsonl":
            continue
        rows += [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted(rows, key=lambda r: r["t"])


# ---------------------------------------------------------------------------
# Witnesses (stored streams only; nothing here decodes video)
# ---------------------------------------------------------------------------

#: Full magazine | reserve per gun [domain:weapons/magazine-and-reserve].
FULL = {"classic": (12, 36), "shorty": (2, 6), "frenzy": (15, 45), "ghost": (13, 39),
        "bandit": (8, 24), "sheriff": (6, 24), "stinger": (20, 60), "spectre": (30, 90),
        "bucky": (5, 10), "judge": (5, 15), "bulldog": (24, 72), "guardian": (12, 36),
        "phantom": (30, 60), "vandal": (25, 50), "marshal": (5, 15), "outlaw": (2, 10),
        "operator": (5, 10), "ares": (50, 100), "odin": (100, 200)}
BANK_GUNS = ("classic", "vandal", "phantom")
STABLE = 2                        # samples each state must hold around a witnessed equip
SLACK_S = 0.3                     # the match window's slack either side of the bracket
SPEED_HALF_S = 0.5
SPEED_BINS = (("still", 0.0, 2.0), ("slow", 2.0, 8.0), ("mid", 8.0, 14.0), ("fast", 14.0, 40.0),
              ("misfit", 40.0, 1e9))
RANGE_STEP_S = 0.31               # the range's median step interval while moving
LISTEN_PER = 5


def _table(kind: str, name: str):
    import pyarrow.parquet as pq
    p = next((STORE / kind).glob(f"*/date=*/session={SESSION}/{name}.parquet"), None) \
        or next((STORE / kind).glob(f"date=*/session={SESSION}/{name}.parquet"))
    return pq.read_table(p)


def hud_samples() -> list[dict]:
    """2 Hz held state: 'gun' (the counter is drawn), 'hidden' (HUD read, no
    counter: knife or ability), or 'unread' (no bottom HUD or the menu open)."""
    menu = {json.loads(line)["t_ms"] for line in
            (STORE / "events" / "menu_open" / f"{SESSION}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("kind") == "open"}
    out = []
    for r in _table("l1", "hud").to_pylist():
        mag, res, hp = r["ammo_mag"], r["ammo_reserve"], r["hp"]
        if r["t_ms"] in menu or (hp is None and mag is None and res is None):
            st = "unread"
        elif mag is None and res is None:
            st = "hidden"
        else:
            st = "gun"
        out.append({"t": r["t_ms"] / 1000.0, "state": st, "mag": mag, "res": res})
    out.sort(key=lambda s: s["t"])
    _segments(out)
    return out


def _same_gun(p: dict, q: dict) -> bool:
    """Whether two consecutive counter reads can be one gun: firing, a reload, or an unread digit."""
    if None in (p["mag"], p["res"], q["mag"], q["res"]):
        return True
    if q["res"] == p["res"]:
        return q["mag"] <= p["mag"]
    return q["res"] < p["res"] and q["mag"] > p["mag"] and q["mag"] + q["res"] <= p["mag"] + p["res"]


def gun_name(mags: list[int], ress: list[int]) -> str:
    """The guns whose full reserve equals the segment's largest reserve and
    whose magazine holds its largest magazine; 'unknown' when none does."""
    if not ress:
        return "unknown"
    R, M = max(ress), max(mags) if mags else 0
    c = sorted(g for g, (m, r) in FULL.items() if r == R and m >= M)
    return "|".join(c) if c else "unknown"


def _segments(s: list[dict]) -> None:
    seg, prev = -1, None
    for x in s:
        if x["state"] != "gun":
            x["seg"] = None
            prev = None
            continue
        if prev is None or not _same_gun(prev, x):
            seg += 1
        x["seg"] = seg
        prev = x
    by = defaultdict(lambda: ([], []))
    for x in s:
        if x["seg"] is not None:
            if x["mag"] is not None:
                by[x["seg"]][0].append(x["mag"])
            if x["res"] is not None:
                by[x["seg"]][1].append(x["res"])
    names = {k: gun_name(*v) for k, v in by.items()}
    for x in s:
        x["gun"] = names.get(x["seg"]) if x["seg"] is not None else None


def pov_spans() -> list[tuple[float, float, str]]:
    """(t0, t1, 'own'|'other'): whose kit the tray shows (tray-kit spans)."""
    rows = [json.loads(line) for line in
            (STORE / "events" / "tray_kit" / f"{SESSION}.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted((r["t_first_ms"] / 1000.0 - 0.25, r["t_last_ms"] / 1000.0 + 0.25, "own" if r["own"] else "other")
                  for r in rows if r["kind"] == "span")


def pov_at(spans, t: float) -> str | None:
    for a, b, k in spans:
        if a <= t <= b:
            return k
    return None


def self_track() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    t = _table("l1", "minimap")
    tm = t.column("t_ms").to_numpy() / 1000.0
    x = np.array(t.column("self_x").to_pylist(), dtype=float)
    y = np.array(t.column("self_y").to_pylist(), dtype=float)
    o = np.argsort(tm)
    return tm[o], x[o], y[o]


def speed_at(track, t: float) -> float | None:
    """Self displacement over t +- 0.5 s, stored minimap px/s; None without both ends."""
    tm, x, y = track
    a, b = np.searchsorted(tm, t - SPEED_HALF_S), np.searchsorted(tm, t + SPEED_HALF_S, "right")
    idx = [i for i in range(a, b) if np.isfinite(x[i])]
    if len(idx) < 2 or tm[idx[-1]] - tm[idx[0]] < 0.7:
        return None
    i, j = idx[0], idx[-1]
    return float(np.hypot(x[j] - x[i], y[j] - y[i]) / (tm[j] - tm[i]))


def speed_bin(v: float | None) -> str | None:
    if v is None:
        return None
    return next(n for n, lo, hi in SPEED_BINS if lo <= v < hi)


def phases():
    """The gametime owner's schedule: buy phase until the barriers drop."""
    from reticle import gametime
    rr = rounds()
    gt = gametime.build_session_gametime(SESSION, _table("l1", "hud"), rr)
    return gt.schedules


def phase_at(scheds, t: float) -> str:
    ms = t * 1000.0
    for s in scheds:
        if s.t_start_ms <= ms < s.t_live_ms:
            return "buy"
        if s.t_live_ms <= ms <= s.t_end_ms:
            return "live"
    return "post_or_inter"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def transitions(s: list[dict], spans) -> list[dict]:
    """HUD held-state changes between consecutive samples, marked stable when
    both states hold STABLE samples and the POV is the same on both sides."""
    out = []
    for i in range(1, len(s)):
        p, q = s[i - 1], s[i]
        if "unread" in (p["state"], q["state"]):
            continue
        if p["state"] == q["state"] and p["seg"] == q["seg"]:
            continue
        if q["state"] == "hidden":
            kind, gun = "nongun", None
        else:
            kind, gun = "gun", q["gun"]
        before = s[max(0, i - STABLE):i]
        after = s[i:i + STABLE]
        stable = (len(before) == STABLE and len(after) == STABLE
                  and all(x["state"] == p["state"] and x["seg"] == p["seg"] for x in before)
                  and all(x["state"] == q["state"] and x["seg"] == q["seg"] for x in after))
        pa, pb = pov_at(spans, p["t"]), pov_at(spans, q["t"])
        out.append({"t_prev": p["t"], "t_new": q["t"], "kind": kind, "gun": gun, "from": p["gun"] or p["state"],
                    "stable": stable, "pov": pa if pa == pb else None})
    return out


def _gun_ok(det_cls: str, gun: str | None) -> bool:
    return gun is not None and det_cls.split("_")[0] in gun.split("|")


def _bracket(s: list[dict], ts: np.ndarray, t: float):
    """The HUD samples either side of t."""
    i = int(np.searchsorted(ts, t, "right"))
    if i == 0 or i >= len(s):
        return None, None
    return s[i - 1], s[i]


def score(only: int | None, record: bool, fig_round: int | None) -> dict:
    dets = load_dets(only)
    if not dets:
        raise SystemExit("no detections; run `detect` first")
    rset = {d["round"] for d in dets}
    ch = [c for c in chunks() if c[0] in rset]
    lo, hi = min(c[1] for c in ch), max(c[2] for c in ch)
    s = [x for x in hud_samples()]
    ts = np.array([x["t"] for x in s])
    spans = pov_spans()
    track = self_track()
    scheds = phases()
    for d in dets:
        d["pov"] = pov_at(spans, d["t"])
        d["phase"] = phase_at(scheds, d["t"])
        d["speed"] = speed_at(track, d["t"]) if d["pov"] == "own" else None
        d["bin"] = speed_bin(d["speed"])
    res: dict = {"version": VERSION, "session_id": SESSION, "source_path": CAPTURE,
                 "rounds": sorted(rset), "span_s": [lo, hi]}

    # -- Detections by class, POV and phase.
    by = Counter((d["cls"], d["pov"] or "none", d["phase"]) for d in dets)
    res["counts"] = {f"{c}|{p}|{ph}": v for (c, p, ph), v in sorted(by.items())}
    own_s = sum(max(0.0, min(b, hi) - max(a, lo)) for a, b, k in spans if k == "own")
    other_s = sum(max(0.0, min(b, hi) - max(a, lo)) for a, b, k in spans if k == "other")
    res["pov_seconds"] = {"own": round(own_s, 1), "other": round(other_s, 1), "total": round(hi - lo, 1)}

    # -- Equips against the HUD held-state changes.
    tr = [x for x in transitions(s, spans) if lo <= x["t_new"] < hi]
    for x in tr:
        x["phase"] = phase_at(scheds, x["t_new"])
    eq_dets = [d for d in dets if d["cls"] in EQUIP]
    rows = []
    for x in tr:
        a, b = x["t_prev"] - SLACK_S, x["t_new"] + SLACK_S
        near = [d for d in dets if a <= d["t"] <= b]
        eq = [d for d in near if d["cls"] in EQUIP]
        best = max(eq, key=lambda d: d["score"]) if eq else None
        if x["kind"] == "nongun":
            right = best is not None and best["cls"] == "knife_equip"
        else:
            right = best is not None and _gun_ok(best["cls"], x["gun"])
        rows.append({**x, "det": best["cls"] if best else None, "det_t": best["t"] if best else None,
                     "det_score": best["score"] if best else None,
                     "offset": round(best["t"] - x["t_new"], 3) if best else None,
                     "ild_db": best["ild_db"] if best else None,
                     "other_near": sorted({d["cls"] for d in near if d["cls"] not in EQUIP}),
                     "right": right})
        if best is not None:
            best["witness"] = "equip_window"
    res["equip_transitions"] = rows

    def eq_summary(sel):
        n = len(sel)
        det = [r for r in sel if r["det"]]
        ok = [r for r in det if r["right"]]
        off = np.array([r["offset"] for r in ok]) if ok else np.array([])
        return {"n": n, "detected": len(det), "right": len(ok),
                "recall": round(len(det) / n, 3) if n else None,
                "class_right": round(len(ok) / len(det), 3) if det else None,
                "offset_median": round(float(np.median(off)), 3) if len(off) else None,
                "offset_p10": round(float(np.percentile(off, 10)), 3) if len(off) else None,
                "offset_p90": round(float(np.percentile(off, 90)), 3) if len(off) else None,
                "offset_in_bracket": round(float(np.mean((off >= -0.5 - 1e-6) & (off <= 0.0 + 1e-6))), 3) if len(off) else None,
                # P3's pre-registered range, [-0.60, +0.15] s.
                "offset_in_p3": round(float(np.mean((off >= -0.6 - 1e-6) & (off <= 0.15 + 1e-6))), 3) if len(off) else None,
                "confusion": dict(Counter(f"{r['gun'] or 'nongun'}->{r['det']}" for r in sel))}
    eqs = {}
    for pov in ("own", "other"):
        st = [r for r in rows if r["stable"] and r["pov"] == pov]
        eqs[pov] = {
            "bank_guns": eq_summary([r for r in st if r["kind"] == "gun" and r["gun"]
                                     and any(g in r["gun"].split("|") for g in BANK_GUNS)]),
            "other_guns": eq_summary([r for r in st if r["kind"] == "gun" and not (
                r["gun"] and any(g in r["gun"].split("|") for g in BANK_GUNS))]),
            "nongun": eq_summary([r for r in st if r["kind"] == "nongun"]),
            "by_gun": {g: eq_summary([r for r in st if r["kind"] == "gun" and r["gun"] and g in r["gun"].split("|")])
                       for g in BANK_GUNS},
            "unstable_n": sum(1 for r in rows if not r["stable"] and r["pov"] == pov)}
        # Reported beside the pre-registered pooling: buy-phase equips follow a purchase.
        for ph in ("live", "buy"):
            sp = [r for r in st if r["phase"] == ph]
            eqs[pov][f"{ph}_bank_guns"] = eq_summary([r for r in sp if r["kind"] == "gun" and r["gun"]
                                                      and any(g in r["gun"].split("|") for g in BANK_GUNS)])
            eqs[pov][f"{ph}_nongun"] = eq_summary([r for r in sp if r["kind"] == "nongun"])
        eqs[pov]["all_right"] = eq_summary([r for r in st if r["right"]])
    res["equips"] = eqs

    # Equip precision: an equip detection with the same gun on both sides is contradicted.
    prec = Counter()
    for d in eq_dets:
        if d["pov"] != "own":
            continue
        if d.get("witness") == "equip_window":
            prec["matched"] += 1
            continue
        p, q = _bracket(s, ts, d["t"])
        if p is None or "unread" in (p["state"], q["state"]):
            d["witness"] = "hud_unread"
        elif p["state"] == q["state"] == "gun" and p["seg"] == q["seg"]:
            d["witness"] = "contradicted_same_gun"
        elif p["state"] == q["state"] == "hidden":
            d["witness"] = "hidden_both_sides"
        else:
            d["witness"] = "near_unmatched_change"
        prec[d["witness"]] += 1
    res["equip_detections_own"] = dict(prec)
    res["equip_detections_own_by_class"] = {c: dict(Counter(d["witness"] for d in eq_dets
                                                            if d["pov"] == "own" and d["cls"] == c)) for c in EQUIP}

    # -- Shots against the magazine.
    fire, quiet = [], []
    for i in range(1, len(s)):
        p, q = s[i - 1], s[i]
        if not (lo <= q["t"] < hi) or p["state"] != "gun" or q["state"] != "gun" or p["seg"] != q["seg"]:
            continue
        if None in (p["mag"], q["mag"], p["res"], q["res"]) or p["res"] != q["res"]:
            continue
        pv = pov_at(spans, p["t"])
        if pv is None or pv != pov_at(spans, q["t"]):
            continue
        b = {"t_prev": p["t"], "t_new": q["t"], "gun": q["gun"], "drop": p["mag"] - q["mag"], "pov": pv}
        (fire if b["drop"] > 0 else quiet).append(b)
    for b in fire:
        near = [d for d in dets if b["t_prev"] - SLACK_S <= d["t"] <= b["t_new"] + SLACK_S and d["cls"] in SHOT]
        b["det"] = [d["cls"] for d in near]
        b["gun_right"] = any(_gun_ok(d["cls"], b["gun"]) for d in near)
    sh = {}
    for pov in ("own", "other"):
        fb = [b for b in fire if b["pov"] == pov]
        vp = [b for b in fb if b["gun"] and any(g in b["gun"].split("|") for g in ("vandal", "phantom"))]
        hit = [b for b in vp if b["det"]]
        sh[pov] = {"firing_brackets": len(fb), "vp_brackets": len(vp), "vp_detected": len(hit),
                   "vp_recall": round(len(hit) / len(vp), 3) if vp else None,
                   "vp_gun_right": sum(b["gun_right"] for b in hit),
                   "vp_gun_right_frac": round(sum(b["gun_right"] for b in hit) / len(hit), 3) if hit else None,
                   "other_gun_brackets": len(fb) - len(vp),
                   "other_gun_detected": sum(1 for b in fb if b not in vp and b["det"]),
                   "other_gun_confusion": dict(Counter(f"{b['gun']}->{b['det'][0] if b['det'] else None}"
                                                       for b in fb if b not in vp)),
                   "quiet_brackets": sum(1 for b in quiet if b["pov"] == pov)}
    # Each shot detection placed by the HUD bracket that holds it.
    shot_w = Counter()
    fire_t = [(b["t_prev"] - SLACK_S, b["t_new"] + SLACK_S) for b in fire]
    for d in dets:
        if d["cls"] not in SHOT or d["pov"] != "own":
            continue
        p, q = _bracket(s, ts, d["t"])
        if any(a <= d["t"] <= b for a, b in fire_t):
            w = "firing"
        elif p is None or "unread" in (p["state"], q["state"]):
            w = "hud_unread"
        elif p["state"] == "hidden" or q["state"] == "hidden":
            w = "non_gun_held"
        elif p["seg"] == q["seg"] and p["mag"] is not None and p["mag"] == q["mag"] and p["res"] == q["res"]:
            w = "quiet_same_gun"
        else:
            w = "other_gun_bracket"
        d["witness"] = w
        shot_w[w] += 1
    sh["own_detections"] = dict(shot_w)
    sh["own_detections_by_class"] = {c: dict(Counter(d["witness"] for d in dets
                                                     if d["pov"] == "own" and d["cls"] == c)) for c in SHOT}
    gunwise = shot_w["firing"] + shot_w["quiet_same_gun"]
    sh["own_quiet_frac"] = round(shot_w["quiet_same_gun"] / gunwise, 3) if gunwise else None
    res["shots"] = sh

    # -- Footsteps against the self track's speed.
    grid = np.arange(lo, hi, 0.1)
    expo = Counter()
    for t in grid:
        if pov_at(spans, t) != "own":
            continue
        ph = phase_at(scheds, t)
        expo[(ph, speed_bin(speed_at(track, t)))] += 0.1
    fs = {}
    for ph in ("live", "buy"):
        row = {}
        for name, _, _ in SPEED_BINS:
            sec = expo[(ph, name)]
            dd = [d for d in dets if d["cls"] == "footstep" and d["pov"] == "own" and d["phase"] == ph and d["bin"] == name]
            row[name] = {"seconds": round(sec, 1), "steps": len(dd),
                         "rate": round(len(dd) / sec, 3) if sec > 5 else None,
                         "ild_abs_median": round(float(np.median([abs(d["ild_db"]) for d in dd])), 2) if dd else None}
        row["unknown_speed_seconds"] = round(expo[(ph, None)], 1)
        row["unknown_speed_steps"] = sum(1 for d in dets if d["cls"] == "footstep" and d["pov"] == "own"
                                         and d["phase"] == ph and d["bin"] is None)
        fs[ph] = row
    st, fa = fs["live"]["still"]["rate"], fs["live"]["fast"]["rate"]
    fs["fast_over_still"] = round(fa / st, 2) if st and fa else None
    fs["fast_rate_over_range_cadence"] = round(fa * RANGE_STEP_S, 3) if fa else None
    fs["other_pov_rate"] = round(sum(1 for d in dets if d["cls"] == "footstep" and d["pov"] == "other")
                                 / other_s, 3) if other_s else None
    res["footsteps"] = fs

    # -- Stereo.
    def med_abs(v):
        return round(float(np.median(np.abs(v))), 2) if len(v) else None
    res["stereo"] = {
        "matched_equips_abs_ild_median": med_abs([r["ild_db"] for r in rows if r["right"] and r["pov"] == "own"]),
        "firing_shots_abs_ild_median": med_abs([d["ild_db"] for d in dets if d.get("witness") == "firing"]),
        "quiet_shots_abs_ild_median": med_abs([d["ild_db"] for d in dets if d.get("witness") == "quiet_same_gun"]),
        "steps_still_abs_ild_median": fs["live"]["still"]["ild_abs_median"],
        "steps_fast_abs_ild_median": fs["live"]["fast"]["ild_abs_median"]}

    # -- Buy-menu classes against the buy phase.
    bd = [d for d in dets if d["cls"] in BUY]
    res["buy_classes"] = {"n": len(bd), "in_buy_phase": sum(1 for d in bd if d["phase"] == "buy"),
                          "by_class": dict(Counter(f"{d['cls']}|{d['phase']}" for d in bd))}
    res["move_other"] = {c: dict(Counter(f"{d['pov']}|{d['phase']}" for d in dets if d["cls"] == c)) for c in ("jump", "land")}

    _print(res)
    listen(dets)
    OUT.mkdir(parents=True, exist_ok=True)
    (RESULT if only is None else OUT / f"score-r{only:02d}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    fr = fig_round if fig_round is not None else (only if only is not None else None)
    if fr is not None:
        figure(fr, dets, s, rows, track, scheds, spans)
    if record and only is None:
        _record(res)
    return res


def _print(res: dict) -> None:
    print(json.dumps({k: res[k] for k in ("pov_seconds",)}, indent=None))
    for pov in ("own", "other"):
        e = res["equips"][pov]
        for k in ("bank_guns", "other_guns", "nongun", "live_bank_guns", "buy_bank_guns", "live_nongun", "buy_nongun", "all_right"):
            v = e[k]
            print(f"equip {pov:<5} {k:<10} n={v['n']:>3} det={v['detected']:>3} right={v['right']:>3} "
                  f"recall={v['recall']} class={v['class_right']} off med={v['offset_median']} "
                  f"p10={v['offset_p10']} p90={v['offset_p90']} in_bracket={v['offset_in_bracket']}")
            print(f"      confusion {v['confusion']}")
    print("equip detections own:", res["equip_detections_own"])
    print("  by class:", res["equip_detections_own_by_class"])
    print("shot detections own by class:", res["shots"]["own_detections_by_class"])
    print("shots:", json.dumps(res["shots"]))
    print("footsteps:", json.dumps(res["footsteps"]))
    print("stereo:", res["stereo"])
    print("buy:", res["buy_classes"])
    print("jump/land:", res["move_other"])


def listen(dets: list[dict]) -> None:
    """A small stratified list of unwitnessed detections for the player to hear."""
    rng = np.random.default_rng(0)
    cats = {
        "footstep_own_still": [d for d in dets if d["cls"] == "footstep" and d["pov"] == "own" and d["bin"] == "still"],
        "footstep_own_fast": [d for d in dets if d["cls"] == "footstep" and d["pov"] == "own" and d["bin"] == "fast"],
        "shot_own_quiet_same_gun": [d for d in dets if d.get("witness") == "quiet_same_gun"],
        "shot_own_non_gun_held": [d for d in dets if d["cls"] in SHOT and d.get("witness") == "non_gun_held"],
        "equip_own_contradicted": [d for d in dets if d.get("witness") == "contradicted_same_gun"],
        "jump_or_land": [d for d in dets if d["cls"] in ("jump", "land")],
        "buy_class_outside_buy": [d for d in dets if d["cls"] in BUY and d["phase"] != "buy"],
    }
    lines = ["category,t_s,mmss,class,score,second,second_score,pov,phase,self_speed_px_s,ild_db,source_path"]
    for cat, v in cats.items():
        if not v:
            continue
        pick = sorted(rng.choice(len(v), size=min(LISTEN_PER, len(v)), replace=False))
        for k in pick:
            d = v[int(k)]
            sp = "" if d["speed"] is None else f"{d['speed']:.1f}"
            lines.append(f"{cat},{d['t']:.2f},{int(d['t'] // 60)}:{d['t'] % 60:05.2f},{d['cls']},{d['score']:.3f},"
                         f"{d['second']},{d['second_score']:.3f},{d['pov']},{d['phase']},{sp},{d['ild_db']},"
                         f"\"{CAPTURE}\"")
    LISTEN.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"listen list: {len(lines) - 1} rows -> {LISTEN}")


def figure(r_no: int, dets, s, rows, track, scheds, spans) -> Path:
    """One round's timeline: HUD held state and magazine, bank detections by
    class, the self track's speed (cv2; the venv has no plotting library)."""
    import cv2
    a, b = next((c[1], c[2]) for c in chunks() if c[0] == r_no)
    classes = list(EQUIP) + list(SHOT) + list(MOVE) + list(BUY)
    W, L, R = 1900, 130, 20
    top, hud_h, gap, det_h, spd_h, bot = 70, 110, 16, 22 * len(classes), 140, 50
    H = top + hud_h + gap + det_h + gap + spd_h + bot
    im = np.full((H, W, 3), 255, np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    pw = W - L - R

    def X(t):
        return int(L + (t - a) / (b - a) * pw)
    y_hud, y_det = top, top + hud_h + gap
    y_spd = y_det + det_h + gap
    for x0, x1, k in spans:                       # POV shading, BGR
        if x1 > a and x0 < b:
            cv2.rectangle(im, (X(max(a, x0)), top), (X(min(b, x1)), y_spd + spd_h),
                          (246, 233, 219) if k == "own" else (219, 227, 246), -1)
    for sc in scheds:                             # buy phase: hatched
        x0, x1 = max(a, sc.t_start_ms / 1000), min(b, sc.t_live_ms / 1000)
        if x1 > x0:
            for xx in range(X(x0), X(x1), 12):
                cv2.line(im, (xx, top), (xx, top + 12), (150, 150, 150), 1)
            cv2.putText(im, "buy", (X(x0) + 2, top + 26), font, 0.4, (90, 90, 90), 1, cv2.LINE_AA)
    col_gun = {"vandal": (40, 39, 214), "phantom": (180, 119, 31), "classic": (44, 160, 44)}
    ss = [x for x in s if a <= x["t"] < b]
    for x in ss:                                  # held-state bar
        if x["state"] == "unread":
            continue
        c = (150, 150, 150) if x["state"] == "hidden" else col_gun.get((x["gun"] or "").split("|")[0], (189, 103, 148))
        cv2.rectangle(im, (X(x["t"]), y_hud + hud_h - 14), (X(x["t"] + 0.5), y_hud + hud_h - 2), c, -1)
    pts = [(X(x["t"]), int(y_hud + hud_h - 18 - x["mag"] / 32 * (hud_h - 24))) for x in ss if x["mag"] is not None]
    for p, q in zip(pts, pts[1:]):
        cv2.line(im, p, q, (60, 60, 60), 1, cv2.LINE_AA)
    cv2.putText(im, "magazine", (8, y_hud + 40), font, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(im, "held (bar)", (8, y_hud + hud_h - 4), font, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    for r in rows:                                # witnessed HUD changes
        if a <= r["t_new"] < b and r["pov"]:
            c = (44, 160, 44) if r["right"] else ((14, 127, 255) if r["det"] else (40, 39, 214))
            xx = X(r["t_new"])
            if r["stable"]:
                cv2.line(im, (xx, y_hud), (xx, y_det + det_h), c, 2)
            else:
                for yy in range(y_hud, y_det + det_h, 8):
                    cv2.line(im, (xx, yy), (xx, yy + 3), c, 1)
    for i, c in enumerate(classes):
        yy = y_det + 11 + 22 * i
        cv2.line(im, (L, yy), (L + pw, yy), (225, 225, 225), 1)
        cv2.putText(im, c, (8, yy + 4), font, 0.42, (0, 0, 0), 1, cv2.LINE_AA)
    face = {"equip_window": (44, 160, 44), "firing": (44, 160, 44), "contradicted_same_gun": (40, 39, 214),
            "quiet_same_gun": (40, 39, 214), "non_gun_held": (40, 39, 214)}
    for d in dets:
        if not (a <= d["t"] < b):
            continue
        p = (X(d["t"]), y_det + 11 + 22 * classes.index(d["cls"]))
        rad = int(3 + 6 * max(0.0, d["score"] - 0.5) / 0.5)
        if d.get("witness") in face:
            cv2.circle(im, p, rad, face[d["witness"]], -1, cv2.LINE_AA)
        cv2.circle(im, p, rad, (40, 40, 40), 1, cv2.LINE_AA)
    g = np.arange(a, b, 0.1)                      # self speed
    v = [speed_at(track, t) for t in g]
    for lim, name in ((2.0, "2"), (8.0, "8"), (14.0, "14")):
        yy = int(y_spd + spd_h - lim / 40 * spd_h)
        cv2.line(im, (L, yy), (L + pw, yy), (200, 200, 200), 1)
        cv2.putText(im, name, (L - 22, yy + 4), font, 0.38, (90, 90, 90), 1, cv2.LINE_AA)
    prev = None
    for t, q in zip(g, v):
        p = None if q is None else (X(t), int(y_spd + spd_h - min(q, 40) / 40 * spd_h))
        if p and prev:
            cv2.line(im, prev, p, (70, 70, 70), 1, cv2.LINE_AA)
        prev = p
    for d in dets:
        if a <= d["t"] < b and d["cls"] == "footstep":
            cv2.line(im, (X(d["t"]), y_spd), (X(d["t"]), y_spd + 10),
                     (180, 119, 31) if d["pov"] == "own" else (14, 127, 255), 2)
    cv2.putText(im, "self speed", (8, y_spd + 60), font, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(im, "(minimap px/s)", (8, y_spd + 78), font, 0.4, (0, 0, 0), 1, cv2.LINE_AA)
    for k in range(int(np.ceil(a / 10) * 10), int(b) + 1, 10):
        cv2.line(im, (X(k), y_spd + spd_h), (X(k), y_spd + spd_h + 5), (0, 0, 0), 1)
        cv2.putText(im, f"{k}", (X(k) - 12, y_spd + spd_h + 20), font, 0.42, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(im, f"{SESSION} round {r_no}, capture seconds {a:.0f}-{b:.0f}: range bank on the match vs stored "
                f"witnesses", (L, 22), font, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(im, "blue band: own POV (tray shows Iso)   pink band: spectating   hatch: buy phase   "
                "vertical: HUD equip, green named right, orange wrong class, red missed, dotted unstable   "
                "dots: green witnessed, red contradicted by the HUD, hollow unwitnessed; size = score",
                (L, 46), font, 0.42, (60, 60, 60), 1, cv2.LINE_AA)
    p = OUT / f"round-{r_no:02d}-timeline.png"
    cv2.imwrite(str(p), im)
    print(f"figure -> {p}")
    return p


def _record(res: dict) -> None:
    from reticle import metrics
    vals = {}
    for pov in ("own", "other"):
        for k in ("bank_guns", "other_guns", "nongun", "live_bank_guns", "buy_bank_guns", "live_nongun", "buy_nongun", "all_right"):
            for f, v in res["equips"][pov][k].items():
                if f != "confusion" and v is not None:
                    vals[f"equip_{pov}_{k}_{f}"] = v
        for g in BANK_GUNS:
            for f in ("n", "detected", "right", "offset_median"):
                v = res["equips"][pov]["by_gun"][g][f]
                if v is not None:
                    vals[f"equip_{pov}_{g}_{f}"] = v
    for k, v in res["equip_detections_own"].items():
        vals[f"equip_det_own_{k}"] = v
    for c, w in res["equip_detections_own_by_class"].items():
        for k, v in w.items():
            vals[f"equip_det_own_{c}_{k}"] = v
    for c, w in res["shots"]["own_detections_by_class"].items():
        for k, v in w.items():
            vals[f"shot_det_own_{c}_{k}"] = v
    for pov in ("own", "other"):
        for f, v in res["shots"][pov].items():
            if not isinstance(v, dict) and v is not None:
                vals[f"shots_{pov}_{f}"] = v
    for k, v in res["shots"]["own_detections"].items():
        vals[f"shot_det_own_{k}"] = v
    if res["shots"]["own_quiet_frac"] is not None:
        vals["shot_own_quiet_frac"] = res["shots"]["own_quiet_frac"]
    for ph in ("live", "buy"):
        for name, _, _ in SPEED_BINS:
            for f, v in res["footsteps"][ph][name].items():
                if v is not None:
                    vals[f"steps_{ph}_{name}_{f}"] = v
    for f in ("fast_over_still", "fast_rate_over_range_cadence", "other_pov_rate"):
        if res["footsteps"][f] is not None:
            vals[f"steps_{f}"] = res["footsteps"][f]
    for k, v in res["stereo"].items():
        if v is not None:
            vals[f"stereo_{k}"] = v
    vals["buy_n"] = res["buy_classes"]["n"]
    vals["buy_in_buy_phase"] = res["buy_classes"]["in_buy_phase"]
    vals["own_pov_s"] = res["pov_seconds"]["own"]
    vals["other_pov_s"] = res["pov_seconds"]["other"]
    vals["detections"] = sum(res["counts"].values())
    for c in EQUIP + SHOT + MOVE + BUY:
        vals[f"det_{c}"] = sum(v for k, v in res["counts"].items() if k.split("|")[0] == c)
    _, _, info = load_refs()
    metrics.record("sound_match", part="score", session=SESSION, values=vals,
                   deps={"version": VERSION, "bank": sound_bank.VERSION, "theta": sound_bank.THETA,
                         "refs": len(info["refs"]), "labels": info["labels"], "stable": STABLE,
                         "slack_s": SLACK_S, "speed_half_s": SPEED_HALF_S,
                         "speed_bins": [list(b[:3]) for b in SPEED_BINS], "wav": str(WAV)},
                   context={"hud": "hud-0.16.0 2 Hz", "tray_kit": "tray-kit-0.1.0", "minimap": "minimap-0.7.0",
                            "gametime": "gametime-0.1.0"})
    print(f"recorded {len(vals)} values under sound_match/score@{SESSION}")


def main(argv=None) -> int:
    sound_demo._idle()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("decode")
    p.add_argument("--force", action="store_true")
    sub.add_parser("refs")
    p = sub.add_parser("detect")
    p.add_argument("--round", type=int)
    p = sub.add_parser("score")
    p.add_argument("--round", type=int)
    p.add_argument("--record", action="store_true")
    p.add_argument("--figure-round", type=int)
    a = ap.parse_args(argv)
    if a.cmd == "decode":
        decode(a.force)
    elif a.cmd == "refs":
        refs()
    elif a.cmd == "detect":
        detect(a.round)
    else:
        score(a.round, a.record, a.figure_round)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
