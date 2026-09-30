r"""Run the first sound bank on one match and score it against video witnesses.

    .\.venv\Scripts\python.exe prototypes\sound_match.py [circle [--record]]
    .\.venv\Scripts\python.exe prototypes\sound_match.py knife [--record]
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

The circle scores the bank (2026-09-30)
---------------------------------------
`circle`, the default stage, scores the bank's own-view detections class by
class against the self audio circle [domain:minimap/self-audio-circle] and the
HUD. It reads `audio_circle.py score --per-frame`'s stored frames: a clean
onset follows two absent frames; its first three frames' radius sizes it (a
footstep's circle at 72 px or more, a reload's under); two small frames then
two large ones are a supersession onset. Windows, set in `notes/predictions.jsonl`
under `bank-vs-circle-20260930` before counting: an onset matches a sound when
onset minus sound lies in -0.10..+0.30 s; a claimed sound is contradicted when
every own-view frame 0.10-0.40 s after it is absent (a footstep also when all
are small). Every own-view instant on a 0.1 s grid, scored the same way, is
the base rate. Disagreements go to `analysis/bank-vs-circle-20260930/`.

| class | witness | recall | precision |
|---|---|---|---|
| footstep | large onsets, circle shown | [metric:sound_match/circle@4f207c0c4e39#footstep_recall=0.221] of [metric:sound_match/circle@4f207c0c4e39#footstep_onsets=95] | [metric:sound_match/circle@4f207c0c4e39#footstep_precision=0.53] (base [metric:sound_match/circle@4f207c0c4e39#base_large_precision=0.395]) |
| footstep, centred | the same | [metric:sound_match/circle@4f207c0c4e39#footstep_ild1_recall=0.105] | [metric:sound_match/circle@4f207c0c4e39#footstep_ild1_precision=0.595] |
| reload | small onsets, HUD refills | [metric:sound_match/circle@4f207c0c4e39#reload_bank_recall=0.0]: no reference | none claimed |
| own shot | HUD decrements | [metric:sound_match/circle@4f207c0c4e39#shot_recall=0.471] of [metric:sound_match/circle@4f207c0c4e39#shot_firing_brackets=70] | [metric:sound_match/circle@4f207c0c4e39#shot_precision=0.288] |
| knife equip | HUD gun to hidden | [metric:sound_match/circle@4f207c0c4e39#equip_knife_recall_right=0.432] of [metric:sound_match/circle@4f207c0c4e39#equip_knife_n=44] | [metric:sound_match/circle@4f207c0c4e39#equip_knife_equip_precision=0.653] |
| Classic, Vandal, Phantom equip | HUD gun changes | [metric:sound_match/circle@4f207c0c4e39#equip_bank_guns_recall_right=0.188] of [metric:sound_match/circle@4f207c0c4e39#equip_bank_guns_n=16] | [metric:sound_match/circle@4f207c0c4e39#equip_classic_equip_precision=0.444], [metric:sound_match/circle@4f207c0c4e39#equip_vandal_equip_precision=0.333], [metric:sound_match/circle@4f207c0c4e39#equip_phantom_equip_precision=0.2] |

The bank's footsteps agree with the circle at chance: an onset follows
[metric:sound_match/circle@4f207c0c4e39#footstep_onset_share=0.097] of them
and [metric:sound_match/circle@4f207c0c4e39#base_large_onset_share=0.09] of
all own-view instants, and onset-minus-detection histograms over +-2 s are
flat for every class. The front end, not only the class, fails: averaged round
the HUD's own equips, the features rise
[metric:sound_match/circle@4f207c0c4e39#triggered_hud_own_equips_band_mean_excess_max_db=3.96] dB
over random own-view instants at
[metric:sound_match/circle@4f207c0c4e39#triggered_hud_own_equips_band_mean_excess_max_lag_s=0.04] s,
but round footstep circles at most
[metric:sound_match/circle@4f207c0c4e39#triggered_large_onsets_band_mean_excess_max_db=1.98] dB,
at [metric:sound_match/circle@4f207c0c4e39#triggered_large_onsets_band_mean_excess_max_lag_s=0.65] s,
after the circle began. Own footsteps are not a time-locked sound in the
mixed match audio at this front end. The circle and the HUD agree on reloads:
[metric:sound_match/circle@4f207c0c4e39#reload_small_onsets_in_refill=5] of
[metric:sound_match/circle@4f207c0c4e39#reload_small_onsets=6] small onsets
fall in a refill window, and
[metric:sound_match/circle@4f207c0c4e39#reload_reloads_with_small=5] of
[metric:sound_match/circle@4f207c0c4e39#reload_reload_refills=8] own reloads
show a small circle. Firing brackets absent before are followed by an onset
[metric:sound_match/circle@4f207c0c4e39#shot_firing_absent_before_onset=9] of
[metric:sound_match/circle@4f207c0c4e39#shot_firing_absent_before=22] times,
quiet brackets [metric:sound_match/circle@4f207c0c4e39#shot_quiet_onset_share=0.212]
of the time: steps while firing, or a mechanic not yet known.

Knife runs (`knife`). The bank names
[metric:sound_match/knife@4f207c0c4e39#knife_n=176] knife equips;
[metric:sound_match/knife@4f207c0c4e39#implausible_pairs=36] pairs follow one
another within 10 s on a HUD that shows no change of held item. The instrument
holds: round 3 re-detects to the stored rows, and the level split recomputed
without the band filter differs by a median
[metric:sound_match/knife@4f207c0c4e39#ild_recomputed_abs_diff_median_db=0.11] dB.
The cause is template overlap. Scored as the bank scores, a knife reference
matches Classic equips at
[metric:sound_match/knife@4f207c0c4e39#knife_vs_classic_equip_median=0.886],
Vandal single shots at
[metric:sound_match/knife@4f207c0c4e39#knife_vs_vandal_single_median=0.871]
and jumps at [metric:sound_match/knife@4f207c0c4e39#knife_vs_jump_median=0.869],
against [metric:sound_match/knife@4f207c0c4e39#knife_vs_knife_equip_median=0.967]
for another knife: the patch is z-scored as a whole, so its spectral tilt
([metric:sound_match/knife@4f207c0c4e39#tilt_share_knife_equip=0.627] of its
variance) scores any high-band onset near 0.87, and theta 0.50 sits far below.
Removing each band's mean drops the jump match to
[metric:sound_match/knife@4f207c0c4e39#knife_vs_jump_tilt_free_median=0.717]
while knife against knife holds
[metric:sound_match/knife@4f207c0c4e39#knife_vs_knife_equip_tilt_free_median=0.928].
What the overlap catches: sustained loud sounds panned to one side (the
sheet `knife-runs.png`), the view's reloads (knife detections on one held gun
fall in reload windows
[metric:sound_match/knife@4f207c0c4e39#reload_share_knife_equip=0.265] of the
time against [metric:sound_match/knife@4f207c0c4e39#reload_base_same_gun_share=0.105]
for any instant), and others' sounds. Even HUD-matched knife equips beat
the runner-up by a median
[metric:sound_match/knife@4f207c0c4e39#hud_matched_margin_median=0.052], and
no threshold separates them: the score that keeps 80% of them keeps
[metric:sound_match/knife@4f207c0c4e39#threshold_contradicted_kept=0.722] of
the contradicted ones. Own-view knife detections the HUD contradicts are not
own footsteps on another surface: most show no circle.

References still missing: every reload; the Ghost, Sheriff or Bandit, and
Spectre the player held here, and the Phantom's and Operator's reloads seen
spectating; Iso's four abilities and every teammate's. The player records
them on the range; none is cut from this match.

Bank v2 (2026-09-30). The second range clip supplied those references;
`sound_bank2.py match` points `circle` at its detections (module globals
`OUT`, `EQUIP`, `SHOT`, `CIRCLE_OUT` swapped for the call, witnesses and
windows unchanged) and records `circle_values`' flattening under
`sound_bank2/match`.

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
    os.environ[_var] = "4"
THREADS = os.environ["OMP_NUM_THREADS"]   # read before the imports below reset it

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


def score_curves(a: float, b: float, rf, clen):
    """(t_off, audio [n, 2], rate, per-class score curves, features) for a..b s plus PAD_S."""
    t_off = max(0.0, a - PAD_S)
    x, rate = read_audio(t_off, b + PAD_S)
    D = sound_bank.features(x.mean(axis=1), rate)
    nf = D.shape[1]
    nfft = 1 << int(np.ceil(np.log2(nf + 200)))
    FD = np.fft.rfft(D, nfft, axis=1)
    cs1 = np.concatenate([[0.0], np.cumsum(D.sum(0))])
    cs2 = np.concatenate([[0.0], np.cumsum((D * D).sum(0))])
    S = {c: np.full(nf, -1.0) for c in sorted(clen)}
    for cls, tpl in rf:
        c = sound_bank.slide_corr(D, FD, nfft, cs1, cs2, tpl)
        np.maximum(S[cls][:len(c)], c, out=S[cls][:len(c)])
    return t_off, x, rate, S, D


def detect_chunk(r_no: int, a: float, b: float, rf, clen) -> list[dict]:
    t_off, x, rate, S, _ = score_curves(a, b, rf, clen)
    classes = sorted(clen)
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


def equip_rows(dets, s, spans, scheds, lo, hi) -> list[dict]:
    """Each HUD held-state change with the best equip detection in its window;
    the matched detection is marked `witness = 'equip_window'`."""
    tr = [x for x in transitions(s, spans) if lo <= x["t_new"] < hi]
    rows = []
    for x in tr:
        x["phase"] = phase_at(scheds, x["t_new"])
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
    return rows


def equip_witness(eq_dets, s, ts) -> Counter:
    """Each own-view equip detection's HUD verdict, set as `witness` (after `equip_rows`)."""
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
    return prec


def hud_brackets(s, spans, lo, hi) -> tuple[list[dict], list[dict]]:
    """Consecutive gun samples on one segment at a held reserve, in one POV:
    (firing, where the magazine fell; quiet, where it held)."""
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
    return fire, quiet


def shot_witness(dets, s, ts, fire) -> Counter:
    """Each own-view shot detection placed by the HUD bracket that holds it, set as `witness`."""
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
    return shot_w


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
    rows = equip_rows(dets, s, spans, scheds, lo, hi)
    eq_dets = [d for d in dets if d["cls"] in EQUIP]
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
    res["equip_detections_own"] = dict(equip_witness(eq_dets, s, ts))
    res["equip_detections_own_by_class"] = {c: dict(Counter(d["witness"] for d in eq_dets
                                                            if d["pov"] == "own" and d["cls"] == c)) for c in EQUIP}

    # -- Shots against the magazine.
    fire, quiet = hud_brackets(s, spans, lo, hi)
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
    shot_w = shot_witness(dets, s, ts, fire)
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


# ---------------------------------------------------------------------------
# The self audio circle scores the bank (2026-09-30)
# ---------------------------------------------------------------------------

CIRCLE_VERSION = "bank-vs-circle-0.1.0"
CIRCLE_OUT = STORE / "analysis" / "bank-vs-circle-20260930"
CIRCLE_LISTEN = CIRCLE_OUT / "listen-20260930.csv"
# Windows set in `notes/predictions.jsonl` under bank-vs-circle-20260930 before any
# agreement was counted.
#: Circle onset minus audio time, s: 15 Hz frames, a one-frame fade-in, a circle that
#: lags the sound, and an audio-video offset near 0.1 s.
ONSET_WIN = (-0.10, 0.30)
#: After a sound at t, the frames that must show its circle (a circle lasts about 0.5 s).
SHOW_WIN = (0.10, 0.40)
SHOW_MIN = 3                      # finite frames SHOW_WIN needs for a verdict
CLEAN_FRAMES, CLEAN_GAP_S = 2, 0.25   # absent frames before an onset (audio_circle.drawn_runs)
REFILL_GAP_S = 3.0                # a magazine rise between read samples at most this far apart
REFILL_WIN = (-3.0, 0.3)          # a small onset from t_prev - 3.0 to t_new + 0.3 s of a refill
PRE_ABSENT_S = 0.5                # a HUD bracket's circle test needs this long absent before it
BASE_STEP_S = 0.1
MOVE_SOUNDS = ("footstep", "jump", "land")
LISTEN_MAX = 15


def _own_ild() -> float:
    """The level split that names a detection the player's own (`audio_circle.OWN_ILD_DB`)."""
    import audio_circle as ac
    return ac.OWN_ILD_DB


def _below_normal() -> None:
    """Below Normal priority (the brief's rule for this machine), verified."""
    if os.name != "nt":
        return
    import ctypes
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.GetPriorityClass.argtypes = [ctypes.c_void_p]
    k.GetPriorityClass.restype = ctypes.c_uint32
    k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
    got = k.GetPriorityClass(k.GetCurrentProcess())
    if got != 0x4000:
        raise SystemExit(f"priority class 0x{got:x}, not Below Normal")
    print("priority: Below Normal (0x4000), BLAS threads", THREADS, flush=True)


def circle_frames() -> dict:
    """The stored per-frame circle (`audio_circle.py score --per-frame`): state on the
    two sizes' band, and each drawn frame's size from its exact fit, else from the
    band's ring-score argmax in the stored curves. No crop is read."""
    import audio_circle as ac
    p = np.load(ac.PF_OUT / "per_frame.npz")
    z = np.load(ac.OUT / f"{SESSION}-curves-all.npz")
    t, st, rf = p["t"], p["state"], p["r_fit"]
    if not np.allclose(z["t_ms"] / 1000.0, t):
        raise SystemExit("per_frame.npz and the stored curves disagree on frame times")
    radii = z["radii"]
    kb = (radii >= ac.SIZE_BAND[0]) & (radii <= ac.SIZE_BAND[1])
    Cb = z["curve"][:, kb].astype(float)
    r_band = radii[kb][np.argmax(np.where(np.isfinite(Cb), Cb, -1e9), 1)]
    in_band = np.isfinite(rf) & (rf >= ac.SIZE_BAND[0]) & (rf <= ac.SIZE_BAND[1])
    r = np.where(in_band, rf, r_band)
    size = np.where(st == 1, np.where(r < ac.SIZE_CUT, 1, 2), 0)
    size[st < 0] = -1
    return {"t": t, "size": size, "r": np.where(st == 1, r, np.nan), "own": p["pov"] == "own",
            "pov": p["pov"], "r_from_fit": in_band & (st == 1), "size_cut": ac.SIZE_CUT,
            "band": list(ac.SIZE_BAND), "source": str(ac.PF_OUT / "per_frame.npz"), "pf_version": ac.PF_VERSION}


def circle_onsets(cf: dict) -> list[dict]:
    """Onsets after an absence (clean when CLEAN_FRAMES finite absent frames lead
    it within CLEAN_GAP_S), sized by the median radius of their first three frames,
    plus supersession onsets: inside a run, two small frames then two large ones."""
    t, size, r, own = cf["t"], cf["size"], cf["r"], cf["own"]
    fin = np.nonzero(size >= 0)[0]
    out, k, prev_end = [], 0, -1e9
    while k < len(fin):
        if size[fin[k]] == 0:
            k += 1
            continue
        j = k
        while j + 1 < len(fin) and size[fin[j + 1]] > 0:
            j += 1
        idx, pre = fin[k:j + 1], fin[max(0, k - CLEAN_FRAMES):k]
        clean = (len(pre) == CLEAN_FRAMES and bool((size[pre] == 0).all())
                 and t[idx[0]] - t[pre[0]] < CLEAN_GAP_S)
        is_own = bool(own[idx[0]] and (own[pre].all() if len(pre) else True))
        r0 = float(np.median(r[idx[:3]]))
        out.append({"t": float(t[idx[0]]), "size": "large" if r0 >= cf["size_cut"] else "small", "via": "absent",
                    "clean": clean, "own": is_own, "r": round(r0, 2), "run_end": float(t[idx[-1]]),
                    "gap_before": round(float(t[idx[0]] - prev_end), 3)})
        prev_end = float(t[idx[-1]])
        sz = size[idx]
        for m in range(2, len(sz) - 1):
            if sz[m] == 2 and sz[m + 1] == 2 and sz[m - 1] == 1 and sz[m - 2] == 1:
                out.append({"t": float(t[idx[m]]), "size": "large", "via": "supersede", "clean": True,
                            "own": bool(own[idx[m - 2]:idx[m + 1] + 1].all()),
                            "r": round(float(np.median(r[idx[m:m + 2]])), 2), "run_end": float(t[idx[-1]]),
                            "gap_before": 0.0})
        k = j + 1
    return sorted(out, key=lambda o: o["t"])


class CircleWitness:
    """Verdicts on a claimed own sound from the stored circle."""

    def __init__(self, cf: dict, onsets: list[dict]):
        self.cf = cf
        self.t = cf["t"]
        ok = [o for o in onsets if o["clean"] and o["own"]]
        self.on = {s: np.array([o["t"] for o in ok if o["size"] == s]) for s in ("large", "small")}
        self.on["any"] = np.sort(np.concatenate([self.on["large"], self.on["small"]]))

    def onset_near(self, t: float, size: str = "any") -> bool:
        d = self.on[size] - t
        return bool(((d >= ONSET_WIN[0]) & (d <= ONSET_WIN[1])).any())

    def verdict(self, t: float, size: str | None) -> str:
        """'onset' (a clean onset of that size in ONSET_WIN), 'drawn' (the circle shows
        through SHOW_WIN without a new onset: an extension), 'absent', 'small_only' (a
        footstep claim over a reload-sized circle), or 'unknown' (under SHOW_MIN own-view
        finite frames)."""
        a, b = np.searchsorted(self.t, t + SHOW_WIN[0]), np.searchsorted(self.t, t + SHOW_WIN[1], "right")
        sz, own = self.cf["size"][a:b], self.cf["own"][a:b]
        if not own.all() or (sz >= 0).sum() < SHOW_MIN:
            return "unknown"
        sz = sz[sz >= 0]
        if (sz == 0).all():
            return "absent"
        if size == "large" and not (sz == 2).any():
            return "small_only"
        if self.onset_near(t, size or "any"):
            return "onset"
        return "drawn"

    def absent_before(self, t: float) -> bool | None:
        a, b = np.searchsorted(self.t, t - PRE_ABSENT_S), np.searchsorted(self.t, t)
        sz, own = self.cf["size"][a:b], self.cf["own"][a:b]
        if not own.all() or (sz >= 0).sum() < SHOW_MIN:
            return None
        return bool((sz[sz >= 0] == 0).all())

    def onset_in(self, a: float, b: float, size: str = "any") -> bool:
        return bool(((self.on[size] >= a) & (self.on[size] <= b)).any())


def _verdicts(W: CircleWitness, times, size) -> dict:
    c = Counter(W.verdict(t, size) for t in times)
    det = c["onset"] + c["drawn"] + c["absent"] + c["small_only"]
    return {"n": len(times), **{k: c[k] for k in ("onset", "drawn", "absent", "small_only", "unknown")},
            "precision": round((c["onset"] + c["drawn"]) / det, 3) if det else None,
            "onset_share": round(c["onset"] / det, 3) if det else None}


def _share(k: int, n: int):
    return round(k / n, 3) if n else None


def hud_refills(s: list[dict], spans) -> list[dict]:
    """Own-view magazine rises between read samples at most REFILL_GAP_S apart:
    'reload' on one gun segment (the reserve paid for it), 'switch' across segments."""
    out, last = [], None
    for h in s:
        if h["state"] != "gun" or h["mag"] is None:
            continue
        if last is not None and h["mag"] > last["mag"] and h["t"] - last["t"] <= REFILL_GAP_S \
                and pov_at(spans, last["t"]) == "own" and pov_at(spans, h["t"]) == "own":
            kind = "reload" if last["seg"] == h["seg"] else "switch"
            out.append({"t_prev": last["t"], "t_new": h["t"], "kind": kind, "gun": h["gun"],
                        "mag": [last["mag"], h["mag"]], "res": [last["res"], h["res"]]})
        last = h
    return out


TRIG_LAGS = np.round(np.arange(-1.5, 1.0, 0.01), 2)
TRIG_RANDOM_N = 300


def triggered(events: dict[str, list[float]], own_grid: np.ndarray) -> dict:
    """The audio round each event list, as the bank's front end sees it: the mean over
    events of the features (dB above the +-4 s context median) at lags -1.5..+1.0 s,
    minus the same round TRIG_RANDOM_N random own-view instants (seed 0). Per list:
    the band-mean excess per 0.1 s bin, and the largest single-band excess and its lag.
    The HUD's own equips are the anchor: a sound the HUD dates must peak near lag 0."""
    rng = np.random.default_rng(0)
    ev = dict(events)
    ev["random_own"] = sorted(rng.choice(own_grid, TRIG_RANDOM_N, replace=False).tolist())
    acc = {k: [] for k in ev}
    for _, a, b in chunks():
        off = max(0.0, a - PAD_S)
        x, rate = read_audio(off, b + PAD_S)
        D = sound_bank.features(x.mean(axis=1), rate)
        for k, tt in ev.items():
            for t in tt:
                if a <= t < b:
                    f = np.round((t + TRIG_LAGS - off) / HOP).astype(int)
                    if f[0] >= 0 and f[-1] < D.shape[1]:
                        acc[k].append(D[:, f])
    base = np.mean(acc["random_own"], axis=0)
    out = {}
    for k, v in acc.items():
        if k == "random_own" or not v:
            continue
        X = np.mean(v, axis=0) - base
        kb, kl = np.unravel_index(int(np.argmax(X)), X.shape)
        out[k] = {"n": len(v), "band_mean_excess_db_per_100ms": np.round(X.mean(0).reshape(-1, 10).mean(1), 2).tolist(),
                  "band_mean_excess_max_db": round(float(X.mean(0).max()), 2),
                  "band_mean_excess_max_lag_s": float(TRIG_LAGS[int(np.argmax(X.mean(0)))]),
                  "single_band_excess_max_db": round(float(X[kb, kl]), 2), "single_band": int(kb),
                  "single_band_lag_s": float(TRIG_LAGS[kl])}
    return out


def circle(record: bool) -> dict:
    """Score the bank's own-sound detections, class by class, against the circle and the HUD."""
    dets = load_dets()
    spans, scheds, track = pov_spans(), phases(), self_track()
    s = hud_samples()
    ts = np.array([x["t"] for x in s])
    lo, hi = chunks()[0][1], chunks()[-1][2]
    for d in dets:
        d["pov"] = pov_at(spans, d["t"])
        d["phase"] = phase_at(scheds, d["t"])
        d["speed"] = speed_at(track, d["t"]) if d["pov"] == "own" else None
    own = [d for d in dets if d["pov"] == "own"]
    cf = circle_frames()
    ons = circle_onsets(cf)
    W = CircleWitness(cf, ons)
    t = cf["t"]
    res: dict = {"version": CIRCLE_VERSION, "session_id": SESSION, "source_path": CAPTURE,
                 "circle": {"source": cf["source"], "version": cf["pf_version"], "band": cf["band"],
                            "size_cut": cf["size_cut"],
                            "drawn_frames_sized_by_fit": int(cf["r_from_fit"].sum()),
                            "drawn_frames": int((cf["size"] > 0).sum())},
                 "windows": {"onset": ONSET_WIN, "show": SHOW_WIN, "show_min": SHOW_MIN,
                             "clean": [CLEAN_FRAMES, CLEAN_GAP_S], "refill_gap_s": REFILL_GAP_S,
                             "refill_win": REFILL_WIN, "pre_absent_s": PRE_ABSENT_S, "shot_slack_s": SLACK_S}}
    # The witness's own false-positive rate: it is never drawn while spectating.
    oth = (cf["pov"] == "other") & (cf["size"] >= 0)
    res["circle"]["spectating_drawn_share"] = round(float((cf["size"][oth] > 0).mean()), 4)
    res["circle"]["spectating_onsets"] = sum(1 for o in ons if o["clean"] and not o["own"] and o["via"] == "absent")
    ok_on = [o for o in ons if o["clean"] and o["own"]]
    res["circle"]["onsets"] = dict(Counter(f"{o['size']}|{o['via']}" for o in ok_on))
    res["circle"]["onsets_unclean_own"] = sum(1 for o in ons if o["own"] and not o["clean"])

    # Base rates: every own-view instant on a 0.1 s grid treated as a claimed sound.
    grid = np.array([g for g in np.arange(lo, hi, BASE_STEP_S) if pov_at(spans, g) == "own"])
    res["base"] = {"large": _verdicts(W, grid, "large"), "any": _verdicts(W, grid, None)}
    dis: list[dict] = []

    # The instrument: does the audio hold a time-locked sound at circle onsets at all?
    anchor = [r["t_new"] for r in equip_rows(dets, s, spans, scheds, lo, hi) if r["stable"] and r["pov"] == "own"]
    for d in dets:
        d.pop("witness", None)
    res["triggered"] = triggered({"large_onsets": [o["t"] for o in ok_on if o["size"] == "large" and o["via"] == "absent"],
                                  "small_onsets": [o["t"] for o in ok_on if o["size"] == "small"],
                                  "hud_own_equips": anchor}, grid)

    def near_dets(a: float, b: float, pool=own):
        return [d for d in pool if a <= d["t"] <= b]

    # -- Footsteps against large onsets.
    L = [o for o in ok_on if o["size"] == "large"]
    fs = {}
    sets = {"footstep": [d for d in own if d["cls"] == "footstep"],
            "footstep_ild1": [d for d in own if d["cls"] == "footstep" and abs(d["ild_db"]) < _own_ild()],
            "move_sounds": [d for d in own if d["cls"] in MOVE_SOUNDS]}
    for name, sel in sets.items():
        tt = np.array([d["t"] for d in sel])
        hit = [o for o in L if (((o["t"] - tt) >= ONSET_WIN[0]) & ((o["t"] - tt) <= ONSET_WIN[1])).any()]
        fs[name] = {"onsets": len(L), "onsets_matched": len(hit), "recall": _share(len(hit), len(L)),
                    **_verdicts(W, tt, "large")}
    fs["recall_by_via"] = {v: _share(sum(1 for o in L if o["via"] == v and (
        np.abs(np.array([d["t"] for d in sets["footstep"]]) - o["t"] + 0.1) <= 0.2).any()),
        sum(1 for o in L if o["via"] == v)) for v in ("absent", "supersede")}
    fs["bank_at_large_onsets"] = dict(Counter(
        (max(nd, key=lambda d: d["score"])["cls"] if (nd := near_dets(o["t"] - ONSET_WIN[1], o["t"] - ONSET_WIN[0], dets))
         else "none") for o in L))
    res["footsteps"] = fs
    ft = np.array([d["t"] for d in sets["footstep"]])
    for o in L:
        if not (((o["t"] - ft) >= ONSET_WIN[0]) & ((o["t"] - ft) <= ONSET_WIN[1])).any():
            nd = near_dets(o["t"] - ONSET_WIN[1], o["t"] - ONSET_WIN[0], dets)
            dis.append({"kind": "large_onset_no_footstep", "t": o["t"], "via": o["via"], "r": o["r"],
                        "gap_before": o["gap_before"],
                        "speed": speed_at(track, o["t"]),
                        "bank": [{"t": d["t"], "cls": d["cls"], "score": d["score"], "ild_db": d["ild_db"],
                                  "pov": d["pov"]} for d in nd]})
    for d in sets["footstep"]:
        v = W.verdict(d["t"], "large")
        d["circle"] = v
        if v in ("absent", "small_only"):
            dis.append({"kind": f"footstep_{v}", "t": d["t"], "cls": d["cls"], "score": d["score"],
                        "ild_db": d["ild_db"], "speed": d["speed"]})

    # -- Reloads: the bank has no reload reference; the two witnesses against each other.
    S_on = [o for o in ok_on if o["size"] == "small" and o["via"] == "absent"]
    refills = hud_refills(s, spans)
    rel = [r for r in refills if r["kind"] == "reload"]
    fs_t = np.array([d["t"] for d in sets["footstep"]])
    for r in refills:
        a, b = r["t_prev"] + REFILL_WIN[0], r["t_new"] + REFILL_WIN[1]
        r["small"] = W.onset_in(a, b, "small") or bool(
            ((t >= a) & (t <= b) & (cf["size"] == 1)).any())
        r["large"] = bool(((t >= a) & (t <= b) & (cf["size"] == 2)).any())
        r["own_footsteps"] = int(((fs_t >= a) & (fs_t <= b)).sum())
        r["bank"] = dict(Counter(d["cls"] for d in near_dets(a, b)))
    s_hit = [o for o in S_on if any(r["t_prev"] + REFILL_WIN[0] <= o["t"] <= r["t_new"] + REFILL_WIN[1] for r in refills)]
    s_hit_rel = [o for o in S_on if any(r["t_prev"] + REFILL_WIN[0] <= o["t"] <= r["t_new"] + REFILL_WIN[1] for r in rel)]
    res["reloads"] = {
        "bank_reload_class": None, "bank_recall": 0.0,
        "small_onsets": len(S_on), "small_onsets_in_refill": len(s_hit), "small_onsets_in_reload": len(s_hit_rel),
        "small_onset_precision_vs_refill": _share(len(s_hit), len(S_on)),
        "refills": len(refills), "reload_refills": len(rel),
        "reloads_with_small": sum(r["small"] for r in rel),
        "reloads_large_only": sum(1 for r in rel if not r["small"] and r["large"]),
        "reloads_no_circle": sum(1 for r in rel if not r["small"] and not r["large"]),
        "reloads_with_footstep": sum(1 for r in rel if r["own_footsteps"]),
        "reloads_with_footstep_small": sum(1 for r in rel if r["own_footsteps"] and r["small"]),
        "reloads_no_footstep": sum(1 for r in rel if not r["own_footsteps"]),
        "reloads_no_footstep_small": sum(1 for r in rel if not r["own_footsteps"] and r["small"]),
        "switch_refills": len(refills) - len(rel), "switch_with_small": sum(r["small"] for r in refills if r["kind"] == "switch"),
        "bank_at_small_onsets": dict(Counter(
            (max(nd, key=lambda d: d["score"])["cls"] if (nd := near_dets(o["t"] - ONSET_WIN[1], o["t"] - ONSET_WIN[0], dets))
             else "none") for o in S_on)),
        "bank_in_reload_windows": dict(sum((Counter(r["bank"]) for r in rel), Counter())),
        "refill_rows": refills}
    for o in S_on:
        if o not in s_hit:
            dis.append({"kind": "small_onset_no_refill", "t": o["t"], "r": o["r"], "run_end": o["run_end"]})
    for r in rel:
        if not r["small"]:
            dis.append({"kind": "reload_no_small", "t": r["t_prev"], "t_new": r["t_new"], "gun": r["gun"],
                        "mag": r["mag"], "res": r["res"], "large": r["large"], "own_footsteps": r["own_footsteps"]})

    # -- Own shots against HUD decrements and against the circle's absence.
    fire, quiet = hud_brackets(s, spans, lo, hi)
    fo, qo = [b for b in fire if b["pov"] == "own"], [b for b in quiet if b["pov"] == "own"]
    shots_own = [d for d in own if d["cls"] in SHOT]
    shot_w = shot_witness(dets, s, ts, fire)

    def bracket_hit(b, pool):
        return any(b["t_prev"] - SLACK_S <= d["t"] <= b["t_new"] + SLACK_S for d in pool)

    def circle_after(br):
        rows = [(b, W.absent_before(b["t_prev"])) for b in br]
        rows = [b for b, a in rows if a]
        return len(rows), sum(W.onset_in(b["t_prev"], b["t_new"] + ONSET_WIN[1]) for b in rows)
    fa, fa_on = circle_after(fo)
    qa, qa_on = circle_after(qo)
    sh = {"firing_brackets": len(fo),
          "recall": _share(sum(bracket_hit(b, shots_own) for b in fo), len(fo)),
          "recall_ild1": _share(sum(bracket_hit(b, [d for d in shots_own if abs(d["ild_db"]) < _own_ild()])
                                    for b in fo), len(fo)),
          "detections": len(shots_own), "witness": dict(shot_w),
          "precision": _share(shot_w["firing"], shot_w["firing"] + shot_w["quiet_same_gun"]),
          "firing_absent_before": fa, "firing_absent_before_onset": fa_on, "firing_onset_share": _share(fa_on, fa),
          "quiet_absent_before": qa, "quiet_absent_before_onset": qa_on, "quiet_onset_share": _share(qa_on, qa),
          "shot_dets_circle": _verdicts(W, [d["t"] for d in shots_own if d["witness"] == "firing"], None)}
    res["shots"] = sh
    for b in fo:
        if not bracket_hit(b, shots_own):
            dis.append({"kind": "firing_no_shot", "t": b["t_prev"], "t_new": b["t_new"], "gun": b["gun"],
                        "drop": b["drop"], "bank": [d["cls"] for d in near_dets(b["t_prev"] - SLACK_S, b["t_new"] + SLACK_S)]})
    for d in shots_own:
        if d["witness"] == "quiet_same_gun":
            dis.append({"kind": "shot_quiet_same_gun", "t": d["t"], "cls": d["cls"], "score": d["score"],
                        "ild_db": d["ild_db"], "circle": W.verdict(d["t"], None)})
        elif d["witness"] == "firing" and W.onset_near(d["t"]):
            dis.append({"kind": "shot_with_onset", "t": d["t"], "cls": d["cls"], "score": d["score"],
                        "ild_db": d["ild_db"]})

    # -- Equips against HUD held-state changes (the HUD shows no weapon name; the
    # counter's presence and its segment's reserve name what is held).
    rows = equip_rows(dets, s, spans, scheds, lo, hi)
    st_own = [r for r in rows if r["stable"] and r["pov"] == "own"]
    eq_dets = [d for d in dets if d["cls"] in EQUIP]
    ew = equip_witness(eq_dets, s, ts)
    eq = {}
    for kind, sel in (("knife", [r for r in st_own if r["kind"] == "nongun"]),
                      ("bank_guns", [r for r in st_own if r["kind"] == "gun" and r["gun"]
                                     and any(g in r["gun"].split("|") for g in BANK_GUNS)]),
                      ("other_guns", [r for r in st_own if r["kind"] == "gun" and not (
                          r["gun"] and any(g in r["gun"].split("|") for g in BANK_GUNS))])):
        eq[kind] = {"n": len(sel), "detected": sum(1 for r in sel if r["det"]),
                    "right": sum(1 for r in sel if r["right"]),
                    "recall_right": _share(sum(1 for r in sel if r["right"]), len(sel))}
    for c in EQUIP:
        w = Counter(d["witness"] for d in eq_dets if d["pov"] == "own" and d["cls"] == c)
        bad = w["contradicted_same_gun"] + w["hidden_both_sides"]
        eq[c] = {"own_dets": sum(w.values()), **dict(w), "precision": _share(w["equip_window"], w["equip_window"] + bad)}
    eq["witness"] = dict(ew)
    ea = [r for r in st_own if W.absent_before(r["t_prev"])]
    eq["hud_changes_absent_before"] = len(ea)
    eq["hud_changes_onset"] = sum(W.onset_in(r["t_prev"], r["t_new"] + ONSET_WIN[1]) for r in ea)
    eq["hud_changes_onset_share"] = _share(eq["hud_changes_onset"], len(ea))
    res["equips"] = eq
    for r in st_own:
        if not r["det"]:
            dis.append({"kind": "equip_missed", "t": r["t_prev"], "t_new": r["t_new"], "to": r["gun"] or "hidden",
                        "from": r["from"], "bank": r["other_near"]})
    for d in eq_dets:
        if d["pov"] == "own" and d.get("witness") in ("contradicted_same_gun", "hidden_both_sides"):
            dis.append({"kind": "equip_contradicted", "t": d["t"], "cls": d["cls"], "score": d["score"],
                        "second": d["second"], "second_score": d["second_score"], "ild_db": d["ild_db"],
                        "witness": d["witness"], "circle": W.verdict(d["t"], None)})

    # Knife runs, in any view (the HUD follows the view): the second of each pair.
    _, kr = knife_runs([d for d in dets if d["cls"] == "knife_equip"], s)
    res["equips"]["knife_implausible_runs"] = len(kr)
    for r in kr:
        for d in r[1:]:
            dis.append({"kind": "knife_run", "t": d["t"], "cls": d["cls"], "score": d["score"],
                        "second": d["second"], "second_score": d["second_score"], "ild_db": d["ild_db"],
                        "pov": d["pov"], "run_start": r[0]["t"]})

    _print_circle(res)
    CIRCLE_OUT.mkdir(parents=True, exist_ok=True)
    (CIRCLE_OUT / "circle-score.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    (CIRCLE_OUT / "disagreements.jsonl").write_text("".join(json.dumps(x, default=float) + "\n" for x in dis),
                                                    encoding="utf-8")
    print(f"{len(dis)} disagreements -> {CIRCLE_OUT / 'disagreements.jsonl'}: "
          f"{dict(Counter(x['kind'] for x in dis))}")
    circle_listen(dis)
    if record:
        _record_circle(res)
    return res


def _print_circle(res: dict) -> None:
    c = res["circle"]
    print(f"circle: onsets {c['onsets']}, unclean own {c['onsets_unclean_own']}, "
          f"drawn while spectating {c['spectating_drawn_share']} of frames")
    for k, v in res["triggered"].items():
        print(f"triggered audio, {k} (n {v['n']}): band-mean excess max {v['band_mean_excess_max_db']} dB at "
              f"{v['band_mean_excess_max_lag_s']:+.2f} s; single band {v['single_band']} "
              f"{v['single_band_excess_max_db']} dB at {v['single_band_lag_s']:+.2f} s")
    b = res["base"]
    print(f"base rate, every own-view instant: large {b['large']}\n                               any {b['any']}")
    print(f"{'class':<16}{'witness':<34}{'n':>6}{'hit':>6}{'recall':>8}{'prec':>7}{'onset':>7}")
    for k in ("footstep", "footstep_ild1", "move_sounds"):
        f = res["footsteps"][k]
        print(f"{k:<16}{'large onsets / circle shown':<34}{f['onsets']:>6}{f['onsets_matched']:>6}"
              f"{f['recall']!s:>8}{f['precision']!s:>7}{f['onset_share']!s:>7}   dets {f['n']} "
              f"(onset {f['onset']}, drawn {f['drawn']}, absent {f['absent']}, small {f['small_only']}, unknown {f['unknown']})")
    print(f"  recall by onset kind {res['footsteps']['recall_by_via']}; bank at large onsets "
          f"{res['footsteps']['bank_at_large_onsets']}")
    r = res["reloads"]
    print(f"{'reload':<16}{'small onsets vs HUD refills':<34}{r['small_onsets']:>6}{r['small_onsets_in_refill']:>6}"
          f"{'-':>8}{r['small_onset_precision_vs_refill']!s:>7}   bank has no reload reference (recall 0)")
    print(f"  reload refills {r['reload_refills']}: small {r['reloads_with_small']}, large only "
          f"{r['reloads_large_only']}, none {r['reloads_no_circle']}; with an own footstep "
          f"{r['reloads_with_footstep_small']}/{r['reloads_with_footstep']} small, without "
          f"{r['reloads_no_footstep_small']}/{r['reloads_no_footstep']} small; switches {r['switch_refills']} "
          f"(small {r['switch_with_small']})")
    print(f"  bank at small onsets {r['bank_at_small_onsets']}")
    s = res["shots"]
    print(f"{'own shot':<16}{'HUD magazine decrements':<34}{s['firing_brackets']:>6}{'':>6}{s['recall']!s:>8}"
          f"{s['precision']!s:>7}   ild<1 recall {s['recall_ild1']}; witness {s['witness']}")
    print(f"  circle onset after absent: firing {s['firing_absent_before_onset']}/{s['firing_absent_before']}, "
          f"quiet control {s['quiet_absent_before_onset']}/{s['quiet_absent_before']}; firing shot dets "
          f"{s['shot_dets_circle']}")
    e = res["equips"]
    for k in ("knife", "bank_guns", "other_guns"):
        print(f"{'equip ' + k:<16}{'HUD held-state changes':<34}{e[k]['n']:>6}{e[k]['right']:>6}"
              f"{e[k]['recall_right']!s:>8}")
    for c in EQUIP:
        print(f"  {c:<16} own dets {e[c]['own_dets']}, precision {e[c]['precision']}: "
              f"{ {k: v for k, v in e[c].items() if k not in ('own_dets', 'precision')} }")
    print(f"  circle onset after HUD change (absent before): {e['hud_changes_onset']}/{e['hud_changes_absent_before']}")


def circle_listen(dis: list[dict]) -> None:
    """At most LISTEN_MAX disagreements for the player to hear, by a fixed rule per
    category: the bank's highest scores where it claims a sound the witness denies,
    and the onsets farthest from any detection where the witness shows a sound the
    bank missed."""
    def top(kind, n, key, pred=lambda x: True):
        return sorted([x for x in dis if x["kind"] == kind and pred(x)], key=key)[:n]
    pick = [
        ("large_onset_no_footstep", top("large_onset_no_footstep", 3, lambda x: (len(x["bank"]), -x["gap_before"])),
         "circle drew a footstep-sized circle; the bank heard no footstep", "was this your footstep, and on what surface?"),
        ("footstep_absent", top("footstep_absent", 3, lambda x: -x["score"], lambda x: abs(x["ild_db"]) < _own_ild()),
         "bank: centred footstep; no circle within 0.4 s", "was this your footstep?"),
        ("small_onset_no_refill", top("small_onset_no_refill", 2, lambda x: x["t"]),
         "reload-sized circle; no HUD refill within 3 s", "what did you do here: a reload you cancelled, or another sound?"),
        ("reload_no_small", top("reload_no_small", 2, lambda x: (x["large"], x["t"])),
         "HUD refilled the magazine; no reload-sized circle", "did you reload here, and did you hear it?"),
        ("equip_contradicted", top("equip_contradicted", 2, lambda x: -x["score"],
                                   lambda x: x["cls"] == "knife_equip" and abs(x["ild_db"]) < _own_ild()),
         "bank: centred knife equip; the HUD shows the same item on both sides", "what is this sound?"),
        ("shot_quiet_same_gun", top("shot_quiet_same_gun", 2, lambda x: -x["score"],
                                    lambda x: abs(x["ild_db"]) < _own_ild()),
         "bank: centred own shot; the magazine held", "whose shot is this?"),
        ("shot_with_onset", top("shot_with_onset", 1, lambda x: -x["score"]),
         "own shot on a falling magazine, and a circle began", "did you step while firing?"),
        ("knife_run", top("knife_run", 1, lambda x: -x["score"], lambda x: abs(x["ild_db"]) < _own_ild()),
         "bank: a second centred knife equip with no held-item change on the HUD since the last",
         "what is this sound?"),
    ]
    lines = ["category,t_s,mmss,class,score,ild_db,witness_verdict,question,source_path"]
    for cat, rows, verdict, q in pick:
        for x in rows:
            if len(lines) > LISTEN_MAX:
                break
            cls = x.get("cls") or (x["bank"][0]["cls"] if x.get("bank") and isinstance(x["bank"][0], dict)
                                   else x.get("gun") or "")
            sc = "" if x.get("score") is None else f"{x['score']:.3f}"
            ild = "" if x.get("ild_db") is None else f"{x['ild_db']}"
            lines.append(f"{cat},{x['t']:.2f},{int(x['t'] // 60)}:{x['t'] % 60:05.2f},{cls},{sc},{ild},"
                         f"\"{verdict}\",\"{q}\",\"{CAPTURE}\"")
    CIRCLE_OUT.mkdir(parents=True, exist_ok=True)
    CIRCLE_LISTEN.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"listen list: {len(lines) - 1} rows -> {CIRCLE_LISTEN}")


def _record_circle(res: dict) -> None:
    from reticle import metrics
    vals = circle_values(res)
    metrics.record("sound_match", part="circle", session=SESSION, values=vals,
                   deps={"version": CIRCLE_VERSION, "bank": sound_bank.VERSION, "theta": sound_bank.THETA,
                         "circle": res["circle"]["version"], "windows": res["windows"], "own_ild_db": _own_ild(),
                         "dets": str(OUT / "detections"), "per_frame": res["circle"]["source"]},
                   context={"hud": "hud-0.16.0 2 Hz", "tray_kit": "tray-kit-0.1.0", "minimap": "minimap-0.7.0",
                            "gametime": "gametime-0.1.0"})
    print(f"recorded {len(vals)} values under sound_match/circle@{SESSION}")


def circle_values(res: dict) -> dict:
    """The circle stage's result flattened to metric values (`sound_bank2.py` reuses it)."""
    vals = {}
    for k in ("footstep", "footstep_ild1", "move_sounds"):
        for f, v in res["footsteps"][k].items():
            if v is not None:
                vals[f"{k}_{f}"] = v
    for k in ("large", "any"):
        for f, v in res["base"][k].items():
            if v is not None:
                vals[f"base_{k}_{f}"] = v
    for f, v in res["reloads"].items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v is not None:
            vals[f"reload_{f}"] = v
    for f, v in res["shots"].items():
        if isinstance(v, (int, float)) and v is not None:
            vals[f"shot_{f}"] = v
    for f, v in res["shots"]["witness"].items():
        vals[f"shot_witness_{f}"] = v
    for k, w in res["equips"].items():
        if isinstance(w, dict):
            for f, v in w.items():
                if isinstance(v, (int, float)) and v is not None:
                    vals[f"equip_{k}_{f}"] = v
        elif isinstance(w, (int, float)) and w is not None:
            vals[f"equip_{k}"] = w
    for k, v in res["circle"]["onsets"].items():
        vals[f"onsets_{k.replace('|', '_')}"] = v
    vals["onsets_unclean_own"] = res["circle"]["onsets_unclean_own"]
    for k, v in res["triggered"].items():
        for f in ("n", "band_mean_excess_max_db", "band_mean_excess_max_lag_s", "single_band_excess_max_db",
                  "single_band_lag_s"):
            vals[f"triggered_{k}_{f}"] = v[f]
    vals["spectating_drawn_share"] = res["circle"]["spectating_drawn_share"]
    return vals


# ---------------------------------------------------------------------------
# Why the bank fires runs of knife equips (2026-09-30)
# ---------------------------------------------------------------------------

#: The instrument check re-detects this round (it holds a knife run at 285.5-286.1 s).
KNIFE_CHECK_ROUND = 3
#: A pair of knife detections is implausible when this close and the HUD, read at
#: every sample between them, shows no change of held item.
KNIFE_PAIR_S = 10.0
KNIFE_SHEET_TIMES = (285.83, 364.82, 1241.28, 1534.51, 1663.18, 1673.11, 2191.60, 41.50)


def _zc(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    den = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / den) if den > 0 else 0.0


def _best_zc(A, B, tilt_free=False, min_ov=20, max_lag=10) -> float:
    """Best z-scored patch correlation over +-max_lag frames with min_ov frames of
    overlap: `sound_bank.slide_corr`'s score between two references. `tilt_free`
    first removes each band's mean over the patch (the spectral tilt)."""
    out = -1.0
    for L in range(-max_lag, max_lag + 1):
        i0, i1 = max(0, -L), min(A.shape[1], B.shape[1] - L)
        if i1 - i0 < min_ov:
            continue
        a, b = A[:, i0:i1], B[:, i0 + L:i1 + L]
        if tilt_free:
            a, b = a - a.mean(1, keepdims=True), b - b.mean(1, keepdims=True)
        out = max(out, _zc(a, b))
    return out


def template_overlap(rf) -> dict:
    """Each knife reference against every other range reference, as the bank scores
    them, and with the spectral tilt removed; the tilt's share of a patch's variance."""
    knives = [(i, t) for i, (c, t) in enumerate(rf) if c == "knife_equip"]
    raw, flat = defaultdict(list), defaultdict(list)
    for i, A in knives:
        for j, (c, B) in enumerate(rf):
            if j != i:
                raw[c].append(_best_zc(A, B))
                flat[c].append(_best_zc(A, B, tilt_free=True))

    def tilt_share(T):
        v = T.var()
        return float(np.broadcast_to(T.mean(1, keepdims=True), T.shape).var() / v) if v > 0 else None
    by = defaultdict(list)
    for c, T in rf:
        by[c].append(tilt_share(T))
    return {"knife_vs": {c: {"pairs": len(v), "median": round(float(np.median(v)), 3),
                             "p90": round(float(np.percentile(v, 90)), 3),
                             "tilt_free_median": round(float(np.median(flat[c])), 3)}
                         for c, v in sorted(raw.items(), key=lambda kv: -np.median(kv[1]))},
            "tilt_share_median": {c: round(float(np.median(v)), 3) for c, v in sorted(by.items())}}


def audio_sheet(items, path: Path, dets, cf, pre: float = 1.5, post: float = 1.0, cols: int = 2) -> Path:
    """Panels round chosen times: the bank's features (dB above the +-4 s context
    median), the raw log-mel, the mixed level (black) and left-right difference
    (blue, +-12 dB), the bank's detections (class, score, ILD) and the circle per
    frame (green large, orange small, grey unknown, pink spectating). A cyan line
    marks the time."""
    import cv2
    font = cv2.FONT_HERSHEY_SIMPLEX
    panels = []
    for t0, label in items:
        off = max(0.0, t0 - pre - 5)
        x, rate = read_audio(off, t0 + post + 5)
        m = x.mean(1)
        f0, f1 = int(round((t0 - pre - off) / HOP)), int(round((t0 + post - off) / HOP))
        D = sound_bank.features(m, rate)[:, f0:f1]
        Lm = sound_demo.logmel(m, rate).T[:, f0:f1]
        n, h = f1 - f0, int(rate * HOP)
        a0 = int(round((t0 - pre - off) * rate))
        Lb, Rb = sound_bank.bandpass(x[:, 0], rate) ** 2, sound_bank.bandpass(x[:, 1], rate) ** 2
        el = Lb[a0:a0 + n * h].reshape(n, h).sum(1)
        er = Rb[a0:a0 + n * h].reshape(n, h).sum(1)
        lvl, ild = 10 * np.log10((el + er) / h + 1e-12), 10 * np.log10((el + 1e-12) / (er + 1e-12))
        W, xs = n * 2, np.arange(n) * 2

        def img(A, lo, hi):
            a = (np.clip((A - lo) / (hi - lo), 0, 1)[::-1] * 255).astype(np.uint8)
            return cv2.applyColorMap(cv2.resize(a, (W, 128), interpolation=cv2.INTER_NEAREST), cv2.COLORMAP_MAGMA)
        strip = np.full((90, W, 3), 255, np.uint8)
        lv = (lvl - lvl.min()) / (np.ptp(lvl) + 1e-9)
        cv2.line(strip, (0, 25), (W, 25), (230, 180, 180), 1)
        for i in range(1, n):
            cv2.line(strip, (int(xs[i - 1]), int(85 - 40 * lv[i - 1])), (int(xs[i]), int(85 - 40 * lv[i])), (0, 0, 0), 1)
            cv2.line(strip, (int(xs[i - 1]), int(25 - np.clip(ild[i - 1], -12, 12))),
                     (int(xs[i]), int(25 - np.clip(ild[i], -12, 12))), (200, 0, 0), 1)
        ds = np.full((60, W, 3), 255, np.uint8)
        for k, d in enumerate([d for d in dets if t0 - pre <= d["t"] <= t0 + post]):
            xx = int((d["t"] - (t0 - pre)) / (pre + post) * W)
            cv2.line(ds, (xx, 0), (xx, 12), (0, 0, 200), 2)
            cv2.putText(ds, f"{d['cls'][:10]} {d['score']:.2f} {d['ild_db']:+.0f}", (xx + 2, 12 + 15 * (k % 3)),
                        font, 0.36, (0, 0, 0), 1, cv2.LINE_AA)
        cs = np.full((16, W, 3), 255, np.uint8)
        tt = cf["t"]
        for i in np.nonzero((tt >= t0 - pre) & (tt <= t0 + post))[0]:
            xx = int((tt[i] - (t0 - pre)) / (pre + post) * W)
            c = {-1: (200, 200, 200), 0: (255, 255, 255), 1: (0, 160, 255), 2: (0, 160, 0)}[int(cf["size"][i])]
            if not cf["own"][i] and cf["size"][i] <= 0:
                c = (230, 200, 230)
            cv2.rectangle(cs, (xx, 0), (xx + max(2, W // 38), 15), c, -1)
        st = np.vstack([img(D, 0, 25), np.full((3, W, 3), 128, np.uint8),
                        img(Lm, np.percentile(Lm, 5), np.percentile(Lm, 99.5)), strip, ds, cs])
        x0 = int(pre / (pre + post) * W)
        cv2.line(st, (x0, 0), (x0, st.shape[0]), (255, 255, 0), 1)
        band = np.zeros((22, W, 3), np.uint8)
        cv2.putText(band, label, (4, 16), font, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        panels.append(np.vstack([band, st]))
    blank = np.zeros_like(panels[0])
    rows = [np.hstack([np.pad(p, ((0, 6), (0, 6), (0, 0))) for p in
                       panels[i:i + cols] + [blank] * (cols - len(panels[i:i + cols]))])
            for i in range(0, len(panels), cols)]
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.vstack(rows))
    print(f"sheet -> {path}")
    return path


def knife_runs(K: list[dict], s: list[dict]) -> tuple[list, list]:
    """(pairs, runs) of knife detections (time-sorted) no more than KNIFE_PAIR_S apart
    with a HUD read at every sample between them and no held-item change: the knife
    cannot be equipped twice without something else drawn between. An ability drawn
    between hides the counter too, so a knife-ability-knife pair counts here."""
    def no_change(p, q):
        seg = [x for x in s if p["t"] <= x["t"] <= q["t"]]
        if not seg or any(x["state"] == "unread" for x in seg):
            return False
        return len({(x["state"], x["seg"]) for x in seg}) == 1
    pairs = [(p, q) for p, q in zip(K, K[1:]) if q["t"] - p["t"] <= KNIFE_PAIR_S and no_change(p, q)]
    runs, cur = [], []
    for p, q in pairs:
        if cur and cur[-1] is p:
            cur.append(q)
        else:
            if cur:
                runs.append(cur)
            cur = [p, q]
    if cur:
        runs.append(cur)
    return pairs, runs


def knife(record: bool) -> dict:
    """Why the bank names so many knife equips in match audio: the instrument first
    (re-detection, the level split), then the witnesses (HUD, view, reload windows,
    circle), the references' overlap, and the threshold."""
    rf, clen, info = load_refs()
    dets = load_dets()
    spans, scheds = pov_spans(), phases()
    s = hud_samples()
    ts = np.array([x["t"] for x in s])
    res: dict = {"version": CIRCLE_VERSION, "session_id": SESSION, "source_path": CAPTURE}

    # -- Instrument 1: re-detect one round from the cached audio; it must equal the stored rows.
    r_no, a, b = next(c for c in chunks() if c[0] == KNIFE_CHECK_ROUND)
    again = detect_chunk(r_no, a, b, rf, clen)
    stored = [d for d in dets if d["round"] == r_no]
    same = len(again) == len(stored) and all(
        (p["t"], p["cls"], p["score"], p["ild_db"]) == (q["t"], q["cls"], q["score"], q["ild_db"])
        for p, q in zip(again, stored))
    res["redetect_round"] = {"round": r_no, "stored": len(stored), "again": len(again), "identical": same}
    # -- Instrument 2: the level split recomputed plainly (unfiltered RMS per channel over the span).
    chk = []
    for d in [d for d in dets if d["cls"] == "knife_equip"][::6]:
        x, rate = read_audio(d["t"], d["t"] + max(0.1, clen["knife_equip"] * HOP))
        el, er = (x[:, 0] ** 2).sum(), (x[:, 1] ** 2).sum()
        chk.append(abs(10 * np.log10((el + 1e-12) / (er + 1e-12)) - d["ild_db"]))
    res["ild_recomputed"] = {"n": len(chk), "abs_diff_median_db": round(float(np.median(chk)), 2),
                             "abs_diff_p90_db": round(float(np.percentile(chk, 90)), 2)}

    # -- Witnesses. The HUD follows the view, so it witnesses spectated equips too.
    for d in dets:
        d["pov"], d["phase"] = pov_at(spans, d["t"]), phase_at(scheds, d["t"])
    equip_rows(dets, s, spans, scheds, 0.0, 1e9)
    for d in dets:
        if d["cls"] not in EQUIP or d.get("witness") == "equip_window":
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
    K = [d for d in dets if d["cls"] == "knife_equip"]
    own_ild = _own_ild()

    def summ(sel):
        if not sel:
            return {"n": 0}
        m = np.array([d["score"] - d["second_score"] for d in sel])
        il = np.array([abs(d["ild_db"]) for d in sel])
        return {"n": len(sel), "score_median": round(float(np.median([d["score"] for d in sel])), 3),
                "margin_median": round(float(np.median(m)), 3), "margin_under_005": round(float((m < 0.05).mean()), 3),
                "ild_abs_median": round(float(np.median(il)), 2), "ild_over_1db": round(float((il > own_ild).mean()), 3),
                "ild_under_01db": round(float((il < 0.1).mean()), 3),
                "second": dict(Counter(d["second"] for d in sel).most_common(5))}
    bad = ("contradicted_same_gun", "hidden_both_sides")
    res["knife"] = {"n": len(K), "by_pov_witness": dict(Counter(f"{d['pov']}|{d['witness']}" for d in K)),
                    "hud_matched": summ([d for d in K if d["witness"] == "equip_window"]),
                    "hud_contradicted": summ([d for d in K if d["witness"] in bad]),
                    "hud_contradicted_own": summ([d for d in K if d["witness"] in bad and d["pov"] == "own"]),
                    "hud_unread": summ([d for d in K if d["witness"] == "hud_unread"])}

    # Implausible runs: knife pairs with no held-item change on a fully read HUD between them.
    pairs, runs = knife_runs(K, s)
    in_runs = [d for r in runs for d in r]
    res["knife"]["implausible_pairs"] = len(pairs)
    res["knife"]["implausible_runs"] = len(runs)
    res["knife"]["implausible_run_dets"] = summ(in_runs)
    res["knife"]["implausible_run_pov"] = dict(Counter(str(d["pov"]) for d in in_runs))
    res["knife"]["implausible_run_rows"] = [[{"t": d["t"], "score": d["score"], "second": d["second"],
                                              "second_score": d["second_score"], "ild_db": d["ild_db"],
                                              "pov": d["pov"], "witness": d["witness"]} for d in r] for r in runs]

    # Reload windows (any view): a magazine rise on one gun segment, from t_prev - 3 s to t_new + 0.3 s.
    rel, last = [], None
    for h in s:
        if h["state"] != "gun" or h["mag"] is None:
            continue
        if last is not None and h["mag"] > last["mag"] and h["t"] - last["t"] <= REFILL_GAP_S and last["seg"] == h["seg"]:
            rel.append((last["t"] + REFILL_WIN[0], h["t"] + REFILL_WIN[1]))
        last = h

    def same_gun(t):
        p, q = _bracket(s, ts, t)
        return p is not None and p["state"] == q["state"] == "gun" and p["seg"] == q["seg"]
    lo, hi = chunks()[0][1], chunks()[-1][2]
    gg = [g for g in np.arange(lo, hi, BASE_STEP_S) if same_gun(g)]
    in_rel = lambda t: any(a_ <= t <= b_ for a_, b_ in rel)     # noqa: E731
    res["reload_windows"] = {"n": len(rel), "base_same_gun_share": round(float(np.mean([in_rel(g) for g in gg])), 3),
                             "by_class": {}}
    for c in EQUIP + ("footstep", "jump", "land", "vandal_single", "phantom_single", "buy_menu_close"):
        sel = [d for d in dets if d["cls"] == c and same_gun(d["t"])]
        res["reload_windows"]["by_class"][c] = {"same_gun_dets": len(sel),
                                                "in_reload": round(float(np.mean([in_rel(d["t"]) for d in sel])), 3)
                                                if sel else None}

    # The circle: do own-view knife detections the HUD contradicts fall on own footsteps?
    cf = circle_frames()
    W = CircleWitness(cf, circle_onsets(cf))
    ko = [d for d in K if d["pov"] == "own"]
    res["knife"]["own_circle"] = {w: dict(Counter(W.verdict(d["t"], None) for d in ko if (d["witness"] in bad) == (w == "contradicted")))
                                  for w in ("contradicted", "other")}

    # -- The references: overlap as the bank scores it, and with the spectral tilt removed.
    res["templates"] = template_overlap(rf)

    # -- Threshold: the knife score keeping 80% of HUD-matched knife equips, and what else it keeps.
    mt = np.array([d["score"] for d in K if d["witness"] == "equip_window"])
    th = float(np.percentile(mt, 20))
    bd = [d for d in K if d["witness"] in bad]
    res["threshold"] = {"theta_keep_80_matched": round(th, 3),
                        "contradicted_kept": _share(sum(d["score"] >= th for d in bd), len(bd)),
                        "run_dets_kept": _share(sum(d["score"] >= th for d in in_runs), len(in_runs)),
                        "sweep": {f"{t:.2f}": {"matched": _share(int((mt >= t).sum()), len(mt)),
                                               "contradicted": _share(sum(d["score"] >= t for d in bd), len(bd))}
                                  for t in (0.5, 0.6, 0.7, 0.8, 0.85, 0.9)}}
    _print_knife(res)
    audio_sheet([(t, f"{t:.2f} s  " + ", ".join(f"{d['cls'][:5]} {d['witness'][:12]}" for d in K
                                               if abs(d['t'] - t) < 0.05)) for t in KNIFE_SHEET_TIMES],
                CIRCLE_OUT / "knife-runs.png", dets, cf)
    CIRCLE_OUT.mkdir(parents=True, exist_ok=True)
    (CIRCLE_OUT / "knife.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    if record:
        _record_knife(res)
    return res


def _print_knife(res: dict) -> None:
    print("re-detect:", res["redetect_round"], " level split recomputed:", res["ild_recomputed"])
    k = res["knife"]
    print(f"knife detections {k['n']}: {k['by_pov_witness']}")
    for key in ("hud_matched", "hud_contradicted", "hud_contradicted_own", "hud_unread", "implausible_run_dets"):
        print(f"  {key:<22} {k[key]}")
    print(f"  implausible pairs {k['implausible_pairs']} in {k['implausible_runs']} runs, views {k['implausible_run_pov']}")
    print(f"  own-view circle verdicts {k['own_circle']}")
    print("reload windows:", res["reload_windows"]["n"], "base", res["reload_windows"]["base_same_gun_share"],
          {c: v["in_reload"] for c, v in res["reload_windows"]["by_class"].items()})
    print("knife reference vs other references (median, tilt-free median):")
    for c, v in res["templates"]["knife_vs"].items():
        print(f"  {c:<16} {v['median']:.3f}  {v['tilt_free_median']:.3f}  (pairs {v['pairs']})")
    print("tilt share of patch variance:", res["templates"]["tilt_share_median"])
    print("threshold:", {k_: v for k_, v in res["threshold"].items() if k_ != "sweep"})
    print("  sweep:", res["threshold"]["sweep"])


def _record_knife(res: dict) -> None:
    from reticle import metrics
    vals = {"redetect_identical": int(res["redetect_round"]["identical"]),
            "ild_recomputed_abs_diff_median_db": res["ild_recomputed"]["abs_diff_median_db"]}
    k = res["knife"]
    vals["knife_n"] = k["n"]
    for key in ("hud_matched", "hud_contradicted", "hud_contradicted_own", "hud_unread", "implausible_run_dets"):
        for f, v in k[key].items():
            if isinstance(v, (int, float)):
                vals[f"{key}_{f}"] = v
    vals["implausible_pairs"], vals["implausible_runs"] = k["implausible_pairs"], k["implausible_runs"]
    vals["reload_base_same_gun_share"] = res["reload_windows"]["base_same_gun_share"]
    for c, v in res["reload_windows"]["by_class"].items():
        if v["in_reload"] is not None:
            vals[f"reload_share_{c}"] = v["in_reload"]
            vals[f"reload_same_gun_dets_{c}"] = v["same_gun_dets"]
    for c, v in res["templates"]["knife_vs"].items():
        vals[f"knife_vs_{c}_median"] = v["median"]
        vals[f"knife_vs_{c}_tilt_free_median"] = v["tilt_free_median"]
    for c, v in res["templates"]["tilt_share_median"].items():
        vals[f"tilt_share_{c}"] = v
    for f, v in res["threshold"].items():
        if f != "sweep" and v is not None:
            vals[f"threshold_{f}"] = v
    metrics.record("sound_match", part="knife", session=SESSION, values=vals,
                   deps={"version": CIRCLE_VERSION, "bank": sound_bank.VERSION, "theta": sound_bank.THETA,
                         "pair_s": KNIFE_PAIR_S, "check_round": KNIFE_CHECK_ROUND, "refill_win": REFILL_WIN,
                         "dets": str(OUT / "detections")},
                   context={"hud": "hud-0.16.0 2 Hz", "tray_kit": "tray-kit-0.1.0"})
    print(f"recorded {len(vals)} values under sound_match/knife@{SESSION}")


def main(argv=None) -> int:
    _below_normal()
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        argv = ["circle"]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("circle", help="the default: score the bank against the circle and the HUD")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("knife", help="why the bank fires runs of knife equips")
    p.add_argument("--record", action="store_true")
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
    if a.cmd == "circle":
        circle(a.record)
    elif a.cmd == "knife":
        knife(a.record)
    elif a.cmd == "decode":
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
