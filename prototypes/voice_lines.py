r"""Match the official ultimate voice lines against the match audio: whose ult, on which side?

    .\.venv\Scripts\python.exe prototypes\voice_lines.py templates
    .\.venv\Scripts\python.exe prototypes\voice_lines.py score --formulation F-A|F-B|F-C [--sessions SID ...] [--templates NAME ...]
    .\.venv\Scripts\python.exe prototypes\voice_lines.py check-merge --formulation F --session SID
    .\.venv\Scripts\python.exe prototypes\voice_lines.py evaluate [--formulations F ...] [--sessions SID ...] [--dry]
    .\.venv\Scripts\python.exe prototypes\voice_lines.py review [--formulation F]
    .\.venv\Scripts\python.exe prototypes\voice_lines.py report
    .\.venv\Scripts\python.exe prototypes\voice_lines.py heldout [--dry]

Purpose
-------
The game announces an ultimate cast with a fixed voice line, one for the
caster's allies and one for the caster's enemies
[domain:abilities/voice-lines-announce-casts]. The store holds the official
lines, `reference/assets/voicelines/<Agent>_ult_{ally,enemy}.mp3`, and for
the agent those lack (Gekko) the harvest index's `Ally Cast` and `Enemy Cast`
takes of his ultimate (`voicelines/casts/`). Which
variant fires carries the caster's side, so a matched line names an agent, a
side and a time. `docs/VOICE_LINES.md` is the design this file implements and
the store's `notes/predictions.jsonl` holds its predictions (task
`voice-lines`).

Method
------
`templates` decodes each mp3 with PyAV, resamples it to 48 kHz mono
(libswresample; two files are 44.1 kHz stereo), and runs it through
`audio_gate.logmel`, the front end that produced the cached session features:
64 mel bands from 60 Hz to 16 kHz, 2048-point frames, a 10 ms hop. It keeps
the frames whose window lies inside the clip, trims the leading and trailing
frames more than `ACTIVE_DB` below the loudest, and floors the rest at
`FLOOR_DB` below the template's maximum, so digital silence in the asset
cannot demand silence of the match. Only log-mel arrays and metadata are
stored; the waveform is read from the mp3 when F-B needs it.

`score` slides every template over one session and keeps its peaks:

- F-A: normalised cross-correlation of the template's log-mel (mean removed
  per band over the template, unit norm) against the cached session log-mel
  less its per-band median. The window's own per-band means are removed too,
  so the score is the cosine of the two centred patches, in [-1, 1]. FFT on
  the GPU; the window norms come from cumulative sums.
- F-B: GCC-PHAT. The capture's audio stream is decoded in memory with
  `audio_gate.decode_mono` (no video, no file written), cut into `CHUNK`
  sample chunks that overlap by the longest template, and each chunk's cross
  spectrum with the template waveform is divided by its magnitude over
  `PHAT_BAND`; the inverse FFT, scaled so a perfect match reads 1, is the
  score at each lag. The track keeps the largest lag score in each 10 ms frame.
- F-C: F-A on log-mel with each frame's mean over bands removed, template and
  session alike, so a gain change cannot move the score.

The score at frame k is the match of the template's first kept frame placed
at k * 10 ms: the line's onset. Peaks are local maxima at or above the
99th percentile of that template's track on that session, suppressed within
one template length of a higher peak.

0.2.0 keeps 0.1.0's stored peaks for the 56 templates it shares, scores
only Gekko's two (`score --templates`) and merges them per session;
`check-merge` rescores one session in full and compares.

`evaluate` classes every template per session from the identity arbiter's
lineup (`reticle.lineup.load_lineup`, `agent_identity` verdicts): `own` is the
player's agent's ally variant; `possible` an ally variant of a named ally or
an enemy variant of a named enemy; `impossible` an ally variant of an agent
neither named on the ally side nor the best guess or rival of an unresolved
ally slot, and an enemy variant of an agent not on a fully named enemy side;
`unknown` the rest. Impossible detections measure false alarms without a human
label. The operating point is the lowest threshold at which impossible
detections run at most `OP_RATE` per live minute (round_live and post_plant,
dead or alive, stalls excluded), pooled over the match sessions with a lineup.
0.2.0 evaluates two configurations: the stored peaks as they are, and after
cross-template suppression, where at one onset only the best-scoring template
stands (`SUPPRESS_S`). Own recall is reported with the fixed 1.5 s window and
with each agent's cast window (`CAST_WINDOW`: Phoenix's pips fall at expiry).
Every recorded part name carries `0.2.0`.
`review` writes a sheet of 30 stratified detections with a spectrogram and an
`ffplay` command into the source capture, at the suppressed operating point;
`report` rewrote the "Results 0.2.0" section of `docs/VOICE_LINES.md` from
the recorded runs; it now refuses, because the 0.2.0 verdicts and the
Production section follow that section. `port-check` compares the production
adjudicator's stored selections (`reticle ult-cast`) with 0.1.0's F-B
detections at the same threshold and records the comparison.

`heldout` tests the production threshold on sessions it was not chosen on,
from storage alone: the reader's `ult_line` peaks, the lineup classes of
`adjudication.ult_cast`, the live mask of `match_time`, and the player's X
casts that `ult_cast.player_x_drops` asks of the tray owner. It chooses the
operating point on half of the lineup sessions and scores the other half, both
ways, then leaves each session out in turn, and records `heldout-0.1.0`. The
cast window per agent (`CAST_WINDOW`) lives in `adjudication.ult_cast`, which
binds own lines to the tray with it; this file imports it.

What it does not do
-------------------
It emits no events, writes nothing under `events/` or `labels/`, and `reticle/`
does not import it; it imports F-B from `reticle.ult_lines`. It decodes no
video and writes no audio: F-B holds the decoded stream in memory only, and
the review sheet plays the source capture.
"""
from __future__ import annotations

import os
import sys

#: One heavy process at a time: four BLAS threads at Below Normal.
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_var] = "4"

import ctypes  # noqa: E402


def _below_normal() -> None:
    """Run at Below Normal priority, or stop (handle types declared, as `audio_bank`)."""
    if os.name != "nt":
        return
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.GetPriorityClass.argtypes = [ctypes.c_void_p]
    k.GetPriorityClass.restype = ctypes.c_uint32
    if not k.SetPriorityClass(k.GetCurrentProcess(), 0x4000):
        raise SystemExit("could not lower this process to Below Normal priority")


_below_normal()

import argparse  # noqa: E402
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import html  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "prototypes"))
with contextlib.redirect_stdout(io.StringIO()):
    import audio_gate as ag  # noqa: E402  the front end, decode, spectrogram, sessions
    import audio_bank  # noqa: E402  player_agent, tagged_agent, labels, census tables
#: F-B's template cut, correlation and peaks live in the production reader;
#: this prototype evaluates what `reticle ult-lines` runs.
from reticle.ult_lines import (decode_template, harvested_ults, nms_peaks,  # noqa: E402
                               phat_tracks, track_peaks, trim_floor)
#: The own-line window per agent lives with the adjudicator that binds own
#: lines to the tray; 0.2.0 measured it here.
from reticle.adjudication.ult_cast import CAST_WINDOW, OWN_WINDOW_S, cast_window  # noqa: E402

from reticle.audio_source import audio_path  # noqa: E402  which file holds the audio

STORE = ag.STORE
VERSION = "voice-lines-0.2.0"
#: Every recorded part name carries this; 0.1.0 recorded bare names
#: (`evaluate-F-B`), which docs/VOICE_LINES.md's 0.1.0 section cites.
TAG = VERSION.rsplit("-", 1)[1]
OUT = STORE / "analysis" / "voice-lines" / TAG
TEMPL, SCORES, DETS = OUT / "templates", OUT / "scores", OUT / "detections"
REPORT, REVIEW = OUT / "report", OUT / "review"
#: 0.1.0's peaks: 0.2.0 scores only the templates they lack and keeps the rest.
BASE_VERSION = "voice-lines-0.1.0"
BASE_SCORES = STORE / "analysis" / "voice-lines" / "0.1.0" / "scores"
VOICE = STORE / "reference" / "assets" / "voicelines"
#: The harvested cast lines and their index (prototypes/voice_line_harvest.py).
CASTS = VOICE / "casts"
DOC = ROOT / "docs" / "VOICE_LINES.md"

#: The session features' front end (`audio_gate`), which templates must share.
RATE, HOP, BANDS = 48000, ag.HOP, ag.BANDS
HOP_N = int(round(HOP * RATE))
#: Template trim: frames whose power lies within this of the loudest frame's.
ACTIVE_DB = 40.0
#: Template floor below its own maximum, dB.
FLOOR_DB = 50.0
#: F-B: chunk length in samples and the whitened band, Hz.
CHUNK = 1 << 20
PHAT_BAND = (100.0, 8000.0)
#: F-B: templates per batched inverse FFT.
PHAT_BATCH = 8
#: F-A, F-C: a window whose centred log-mel has less RMS than this per element,
#: dB, is flat (undecoded audio, digital silence) and scores 0.
MIN_RMS_DB = 1.0
#: Peaks at or above this quantile of the template's track are kept.
FLOOR_Q = 0.99
#: A detection is an own cast's when within this of the tray drop, seconds
#: (`adjudication.ult_cast.OWN_WINDOW_S`).
OWN_WIN = OWN_WINDOW_S
#: How far before an own X drop the lead witness looks for the own line (s).
LEAD_WIN = 20.0
#: Cross-template suppression: at one onset only the best-scoring template
#: stands. A stored peak falls when a higher standing peak of another template
#: lies within this many seconds. Chosen from 0.1.0's F-B detections at its
#: operating point: each of the 18 impossible detections with a stronger own
#: or possible detection of another template within 5 s sat within 1.11 s of
#: it, and none lay between 1.11 s and 5 s. `suppression-0.2.0-<F>` records
#: the same offsets on 0.2.0's detections, and the report cites them.
SUPPRESS_S = 1.2
#: Windows swept beside SUPPRESS_S, seconds.
SUPPRESS_SWEEP = (0.3, 0.6, 1.2, 2.5)
#: How far the window evidence looks for a stronger true detection, seconds.
OFFSET_PROBE_S = 5.0
#: Own recall window per agent, (earliest, latest) onset minus tray drop in s:
#: `CAST_WINDOW` and `cast_window`, imported from `adjudication.ult_cast`.
#: Phoenix reaches back 20 s, since Run it Back's pips fall at expiry
#: [domain:abilities/phoenix-run-it-back-expiry-flash]; every other agent keeps
#: (-OWN_WIN, OWN_WIN). No stored tray cast is re-dated.
#: The operating point: impossible detections per live minute.
OP_RATE = 0.1
#: A second common threshold for the per-session impossible rates (P5).
P5_RATE = 1.0
#: Review strata: (name, rows).
STRATA = (("own", 6), ("possible_ally", 7), ("possible_enemy", 7),
          ("borderline", 5), ("impossible", 5))
FORMULATIONS = ("F-A", "F-B", "F-C")
CLASSES = ("own", "possible", "impossible", "unknown")
VARIANTS = ("ally", "enemy")
#: The first sessions: ally side fully named on the top bar, and enemy side.
FIRST = ("043bafca271a", "b7d24102a6f6")
#: A witness the player heard: on `043bafca271a` at 1870.1 s, Vyse's ult line
#: (docs/AUDIO_GATE.md, "The player's review", row 10).
HEARD = (("043bafca271a", 1870.1, "Vyse", "row 10 of the audio-gate review"),)

_GPU = None


def gpu():
    """cupy, or numpy when no GPU is present (tests may run on numpy)."""
    return ag.gpu()


def _np(a):
    return ag._np(a)


def _free_gpu() -> None:
    ag._free_gpu()


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def template_sources() -> list[tuple[str, Path]]:
    """(name, mp3) of every ult line: `<Agent>_ult_<variant>.mp3`, then the
    harvested pair of each agent those lack (Gekko)."""
    out = {p.stem: p for p in VOICE.glob("*_ult_*.mp3")}
    idx = CASTS / "index.json"
    if idx.is_file():
        have = {n.rsplit("_ult_", 1)[0] for n in out}
        rows = json.loads(idx.read_text(encoding="utf-8"))
        out.update({n: CASTS / f for n, f in harvested_ults(rows, have).items()})
    return sorted(out.items())


def parse_name(path) -> tuple[str, str]:
    """(agent, variant) from `<Agent>_ult_<variant>[.mp3]`; KAY/O is spelled KAY_O."""
    stem = Path(path).stem
    agent, variant = stem.rsplit("_ult_", 1)
    if variant not in VARIANTS:
        raise SystemExit(f"{path.name}: unknown variant {variant!r}")
    return agent, variant


def prepare(T: np.ndarray, per_frame: bool = False) -> np.ndarray:
    """A template for the correlation: optionally each frame less its mean over
    bands (F-C), then each band less its mean over the template, unit norm."""
    T = np.asarray(T, np.float64)
    if per_frame:
        T = T - T.mean(axis=1, keepdims=True)
    T = T - T.mean(axis=0, keepdims=True)
    n = np.linalg.norm(T)
    return (T / n if n > 0 else T).astype(np.float32)


def cmd_templates() -> dict:
    """Decode the ult lines, store their log-mel and metadata, record the set."""
    TEMPL.mkdir(parents=True, exist_ok=True)
    meta = []
    same = 0
    for name, p in template_sources():
        agent, variant = parse_name(name)
        x = decode_template(p)
        L, ok, _rms = ag.logmel(x, np.ones(len(x), bool), RATE)
        T, k0, k1 = trim_floor(L, ok)
        rate, ch = source_format(p)
        base = BASE_SCORES.parent / "templates" / f"{name}.npz"
        if base.is_file():
            same += int(np.array_equal(np.load(base)["L"], T))
        rec = {"name": name, "agent": agent, "variant": variant,
               "file": p.relative_to(VOICE).as_posix(),
               "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
               "source_rate": rate, "source_channels": ch, "resampled": rate != RATE or ch != 1,
               "n_samples": len(x), "duration_s": round(len(x) / RATE, 3),
               "k0": k0, "k1": k1, "frames": k1 - k0,
               "onset_s": round(k0 * HOP, 3), "span_s": round((k1 - k0) * HOP, 3)}
        np.savez_compressed(TEMPL / f"{name}.npz", L=T, raw=L[k0:k1].astype(np.float32),
                            version=VERSION, meta=json.dumps(rec))
        meta.append(rec)
    (TEMPL / "templates.json").write_text(json.dumps(
        {"version": VERSION, "active_db": ACTIVE_DB, "floor_db": FLOOR_DB,
         "front_end": "audio_gate.logmel", "templates": meta}, indent=1), encoding="utf-8")
    _free_gpu()
    fr = [m["frames"] for m in meta]
    vals = {"templates": len(meta), "agents": len({m["agent"] for m in meta}),
            "resampled": sum(m["resampled"] for m in meta),
            "frames_min": min(fr), "frames_max": max(fr),
            "duration_min_s": min(m["duration_s"] for m in meta),
            "duration_max_s": max(m["duration_s"] for m in meta),
            "span_min_s": min(m["span_s"] for m in meta),
            "span_max_s": max(m["span_s"] for m in meta),
            "identical_to_0_1_0": same,
            "harvested": sum(m["file"].startswith("casts/") for m in meta)}
    for m in meta:
        if m["file"].startswith("casts/"):
            vals[f"{m['name']}_span_s"] = m["span_s"]
    from reticle import metrics
    metrics.record("voice_lines", part=f"templates-{TAG}", session="all", values=vals,
                   deps={"version": VERSION, "prep": metrics.fingerprint(
                       trim_floor, decode_template, ACTIVE_DB=ACTIVE_DB, FLOOR_DB=FLOOR_DB)},
                   context={"dir": str(TEMPL)})
    print(json.dumps(vals))
    return vals


def source_format(path: Path) -> tuple[int, int]:
    """(sample rate, channels) of an audio file as stored."""
    import av
    with av.open(str(path)) as c:
        st = c.streams.audio[0]
        return st.rate, st.channels


def load_line_templates(formulation: str) -> list[dict]:
    """Every stored template with its prepared array for `formulation`."""
    idx = json.loads((TEMPL / "templates.json").read_text(encoding="utf-8"))
    if idx["version"] != VERSION:
        raise SystemExit(f"templates {idx['version']} != {VERSION}; rerun `templates`")
    out = []
    for m in idx["templates"]:
        z = np.load(TEMPL / f"{m['name']}.npz")
        rec = dict(m)
        rec["T"] = prepare(z["L"], per_frame=formulation == "F-C")
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------

def _fast_len(n: int) -> int:
    return 1 << int(math.ceil(math.log2(max(n, 2))))


def ncc_tracks(W: np.ndarray, temps: list[np.ndarray], xp=None,
               min_rms: float = MIN_RMS_DB) -> np.ndarray:
    """[templates, frames] cosine of each prepared template against the
    per-band-centred window of W starting at each frame; -1 where the window
    runs past the end, 0 where it is flat (RMS below `min_rms` per element)."""
    xp = xp or gpu()
    n, B = W.shape
    mmax = max(len(t) for t in temps)
    nfft = _fast_len(n + mmax)
    Wg = xp.asarray(W, dtype=xp.float32)
    FW = xp.fft.rfft(Wg.T, n=nfft, axis=1)
    W64 = Wg.astype(xp.float64)
    cs1 = xp.concatenate([xp.zeros((1, B), xp.float64), xp.cumsum(W64, axis=0)], axis=0)
    cs2 = xp.concatenate([xp.zeros((1, B), xp.float64), xp.cumsum(W64 ** 2, axis=0)], axis=0)
    del W64
    out = np.full((len(temps), n), -1.0, np.float32)
    for j, T in enumerate(temps):
        m = len(T)
        if m > n:
            continue
        FT = xp.fft.rfft(xp.asarray(T, xp.float32).T, n=nfft, axis=1)
        c = xp.fft.irfft((FW * xp.conj(FT)).sum(axis=0), n=nfft)[:n - m + 1]
        S1 = cs1[m:] - cs1[:n - m + 1]
        S2 = cs2[m:] - cs2[:n - m + 1]
        var = (S2 - S1 ** 2 / m).sum(axis=1)
        flat = var < (min_rms ** 2) * m * B
        r = c / xp.sqrt(xp.maximum(var, 1e-9))
        out[j, :n - m + 1] = _np(xp.where(flat, 0.0, r).astype(xp.float32))
    return out


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def _manifest(sid: str) -> dict:
    return json.loads((STORE / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))


def _has_features(sid: str) -> bool:
    return (ag.FEAT / f"{sid}.npz").is_file()


def match_sessions() -> list[str]:
    return [s for s in audio_bank.match_sessions() if _has_features(s)]


def demo_sessions() -> list[str]:
    return [s for s in audio_bank.demo_sessions() if _has_features(s)]


def session_features(sid: str) -> dict:
    """The cached log-mel of one session, checked against its manifest."""
    f = ag.load_features(sid)
    key = _manifest(sid)["source"]["content_key"]
    if str(f["content_key"]) != key:
        raise SystemExit(f"{sid}: cached features are of {f['content_key']}, "
                         f"the manifest names {key}; rerun audio_gate features")
    return f


def session_matrix(f: dict, formulation: str) -> np.ndarray:
    W = ag.median_removed(f, np)
    if formulation == "F-C":
        W = W - W.mean(axis=1, keepdims=True)
    return W


def score_path(F: str, sid: str) -> Path:
    return SCORES / F / f"{sid}.npz"


def base_path(F: str, sid: str) -> Path:
    return BASE_SCORES / F / f"{sid}.npz"


def merge_peaks(new: dict, new_names: list[str], base: dict, names: list[str]) -> dict:
    """One peak set over `names`: the templates in `new_names` from `new`, every
    other one from `base` (a 0.1.0 peak file), template indices renumbered."""
    bnames = [str(n) for n in base["names"]]
    missing = [n for n in names if n not in new_names and n not in bnames]
    if missing:
        raise SystemExit(f"neither scored nor in the base peaks: {missing}")
    src = {n: ("new", new_names.index(n)) if n in new_names else ("base", bnames.index(n))
           for n in names}
    tpl, frm, sc = [], [], []
    per = {k: [] for k in ("floor", "median", "max")}
    for j, n in enumerate(names):
        which, i = src[n]
        z = new if which == "new" else base
        m = z["tpl"] == i
        tpl.append(np.full(int(m.sum()), j, np.int16))
        frm.append(z["frame"][m].astype(np.int32))
        sc.append(z["score"][m].astype(np.float32))
        for k in per:
            per[k].append(float(z[k][i]))
    return {"tpl": np.concatenate(tpl), "frame": np.concatenate(frm),
            "score": np.concatenate(sc),
            **{k: np.asarray(v, np.float32) for k, v in per.items()}}


def template_waves(temps: list[dict]) -> list[np.ndarray]:
    """Each template's kept span as a 48 kHz waveform, for F-B."""
    out = []
    for t in temps:
        y = decode_template(VOICE / t["file"])
        out.append(y[t["k0"] * HOP_N:t["k1"] * HOP_N])
    return out


def session_tracks(F: str, sid: str, f: dict, temps: list[dict],
                   waves: list[np.ndarray] | None) -> tuple[np.ndarray, dict]:
    """[templates, frames] score tracks of one session, aligned to its log-mel
    frames, and what it took. F-B decodes the capture's audio in memory."""
    n = len(f["L"])
    info = {"n_frames": n}
    if F == "F-B":
        td = time.time()
        x, filled, rate = ag.decode_mono(audio_path(_manifest(sid), STORE))
        info["decode_s"] = round(time.time() - td, 1)
        if rate != RATE:
            raise SystemExit(f"{sid}: audio at {rate} Hz, templates at {RATE}")
        info["filled_fraction"] = round(float(filled.mean()), 4)
        del filled
        tracks = phat_tracks(x, waves)
        del x
        if tracks.shape[1] != n:
            info["frames_waveform"] = int(tracks.shape[1])
            tr = np.full((len(temps), n), -1.0, np.float32)
            k = min(n, tracks.shape[1])
            tr[:, :k] = tracks[:, :k]
            tracks = tr
    else:
        W = session_matrix(f, F)
        tracks = ncc_tracks(W, [t["T"] for t in temps])
        del W
    return tracks, info


def cmd_check_merge(F: str, sid: str) -> dict:
    """Rescore every template on one session in memory and compare its peaks
    with the stored file, which merged newly scored templates onto 0.1.0's."""
    from reticle import metrics
    temps = load_line_templates(F)
    f = session_features(sid)
    waves = template_waves(temps) if F == "F-B" else None
    tracks, info = session_tracks(F, sid, f, temps, waves)
    full = track_peaks(tracks, [len(t["T"]) for t in temps])
    del tracks
    _free_gpu()
    stored = load_peaks(F, sid)
    if [str(n) for n in stored["names"]] != [t["name"] for t in temps]:
        raise SystemExit("stored template order differs")
    a = sorted(zip(full["tpl"].tolist(), full["frame"].tolist(), full["score"].tolist()))
    b = sorted(zip(stored["tpl"].tolist(), stored["frame"].tolist(), stored["score"].tolist()))
    same = [x[:2] for x in a] == [x[:2] for x in b]
    vals = {"peaks_full": len(a), "peaks_stored": len(b), "same_peaks": int(same),
            "max_score_diff": float(max(abs(x[2] - y[2]) for x, y in zip(a, b))) if same else None,
            "max_floor_diff": _r(float(np.max(np.abs(full["floor"] - stored["floor"]))), 6)}
    differ = {}
    if not same:
        fa, fb = {x[:2] for x in a}, {x[:2] for x in b}
        vals["peaks_only_full"] = len(fa - fb)
        vals["peaks_only_stored"] = len(fb - fa)
        for j, t in enumerate(temps):
            if {x for x in fa if x[0] == j} != {x for x in fb if x[0] == j}:
                differ[t["name"]] = round(float(abs(full["floor"][j] - stored["floor"][j])), 6)
        vals["templates_differing"] = len(differ)
        odd = [x[2] for x in a if x[:2] in fa - fb] + [x[2] for x in b if x[:2] in fb - fa]
        vals["differing_peak_max_score"] = _r(float(max(odd)), 4)
    metrics.record("voice_lines", part=part("merge-check", F), session=sid, values=vals,
                   deps={"version": VERSION, "score": _score_fp(F)},
                   context={**info, "differing_floor_diff": differ})
    if differ:
        print(json.dumps(differ))
    print(json.dumps(vals))
    return vals


def cmd_port_check(sids: list[str], pooled: bool = False) -> dict:
    """Compare `reticle ult-cast`'s selected peaks with 0.1.0's F-B detections
    at the same threshold: counts by class, peaks only one side holds, class
    and round changes, and the largest score difference between matched peaks
    (0.1.0 stored scores to four decimals). With `pooled`, one run over all
    the sessions is recorded as `all-sessions` instead of one per session,
    with the impossible rate per live minute at the port's threshold: 0.1.0's
    live impossible detections plus the port's extra impossible peaks that
    fall in live time (`match_time`), over 0.1.0's live minutes."""
    from reticle import metrics
    base = STORE / "analysis" / "voice-lines" / "0.1.0" / "detections"
    out, ctxs, deps = {}, {}, {}
    for sid in sids:
        rows = [json.loads(x) for x in (STORE / "events" / "ult_cast" / f"{sid}.jsonl")
                .read_text(encoding="utf-8").splitlines() if x.strip()]
        cov = rows[0]
        port = {(r["template"], round(r["t_s"], 2)): r for r in rows
                if r.get("kind") in ("cast", "refusal")}
        old = [json.loads(x) for x in (base / f"{sid}.jsonl").read_text(encoding="utf-8")
               .splitlines() if x.strip()]
        old = [r for r in old if r["formulation"] == "F-B"]
        if {r["tau"] for r in old} - {cov["threshold"]}:
            raise SystemExit(f"{sid}: 0.1.0 detections at {sorted({r['tau'] for r in old})}, "
                             f"the port at {cov['threshold']}")
        proto = {(r["template"], round(r["t_s"], 2)): r for r in old}
        match, only_port = {}, []
        for k, r in port.items():
            hit = next((q for q in proto if q[0] == k[0] and abs(q[1] - k[1]) <= 0.015), None)
            if hit is None:
                only_port.append(k)
            else:
                match[k] = hit
        only_proto = sorted(set(proto) - set(match.values()))
        changed = [(k, proto[q]["class"], port[k]["class"]) for k, q in match.items()
                   if proto[q]["class"] != port[k]["class"]]
        moved = [(k, proto[q]["round"], port[k]["round"]) for k, q in match.items()
                 if proto[q]["round"] != port[k]["round"]]
        count = lambda rs: {c: sum(r["class"] == c for r in rs) for c in CLASSES}
        vals = {"port_selected": len(port), "proto_detections": len(proto), "matched": len(match),
                "only_port": len(only_port), "only_proto": len(only_proto),
                "class_changed": len(changed), "round_changed": len(moved),
                "max_score_diff": _r(max((abs(port[k]["score"] - proto[q]["score"])
                                          for k, q in match.items()), default=0.0), 4),
                **{f"port_{c}": n for c, n in count(port.values()).items()},
                **{f"proto_{c}": n for c, n in count(proto.values()).items()}}
        ctx = {"only_port": [{"template": k[0], "t_s": k[1], "score": port[k]["score"],
                              "class": port[k]["class"]} for k in sorted(only_port)],
               "only_proto": [{"template": k[0], "t_s": k[1], "score": proto[k]["score"],
                               "class": proto[k]["class"], "live": proto[k]["live"]}
                              for k in only_proto],
               "class_changed": [{"template": k[0], "t_s": k[1], "was": a, "now": b}
                                 for k, a, b in changed],
               "round_changed": [{"template": k[0], "t_s": k[1], "was": a, "now": b}
                                 for k, a, b in moved],
               "ult_cast_inputs": cov.get("inputs")}
        deps = {"ult_cast_version": cov.get("ult_cast_version"),
                "ult_line_version": cov.get("inputs", {}).get("ult_line"),
                "base": BASE_VERSION, "threshold": cov["threshold"]}
        if not pooled:
            metrics.record("ult_lines", part="port-check-0.1.0", session=sid, values=vals,
                           deps=deps, context=ctx)
        print(sid, json.dumps(vals))
        if any(ctx[k] for k in ("only_port", "only_proto", "class_changed", "round_changed")):
            print("  ", json.dumps(ctx))
        out[sid], ctxs[sid] = vals, ctx
    if pooled and out:
        tot = {k: sum(v[k] for v in out.values()) for k in next(iter(out.values()))
               if k != "max_score_diff"}
        tot["max_score_diff"] = max(v["max_score_diff"] for v in out.values())
        tot["sessions"] = len(out)
        base = _latest().get(("evaluate-F-B", "all-matches"), {})
        extra = 0
        for sid, c in ctxs.items():
            imp = [d for d in c["only_port"] if d["class"] == "impossible"]
            if not imp:
                continue
            cov = json.loads((STORE / "events" / "ult_line" / f"{sid}.jsonl")
                             .read_text(encoding="utf-8").splitlines()[0])
            live = match_time(sid, int(cov["n_frames"]))["live"]
            extra += sum(bool(live[min(int(d["t_s"] / STEP), len(live) - 1)]) for d in imp)
        gone = sum(1 for c in ctxs.values() for d in c["only_proto"]
                   if d["class"] == "impossible" and d["live"])
        tot["only_port_live_impossible"], tot["only_proto_live_impossible"] = extra, gone
        extra -= gone
        if base.get("live_minutes"):
            tot["live_impossible"] = base["impossible_n"] + extra
            tot["impossible_per_live_min"] = _r(tot["live_impossible"] / base["live_minutes"], 4)
        metrics.record("ult_lines", part="port-check-0.1.0", session="all-sessions",
                       values=tot, deps=deps,
                       context={"sessions": sorted(out),
                                "differing": {s: c for s, c in ctxs.items()
                                              if any(c[k] for k in ("only_port", "only_proto",
                                                                    "class_changed",
                                                                    "round_changed"))}})
        print("all-sessions", json.dumps(tot))
    return out


def cmd_score(F: str, sids: list[str], only: list[str] | None = None) -> None:
    """Score the templates on each session in turn and store the peaks. With
    `only`, score just those templates and take every other one's peaks from
    0.1.0's file for that session: a template's peaks depend on its own track
    alone (its floor is its own 99th percentile), so the merge equals a full
    rescoring up to FFT rounding."""
    from reticle import metrics
    temps_all = load_line_templates(F)
    names = [t["name"] for t in temps_all]
    temps = [t for t in temps_all if only is None or t["name"] in only]
    if only is not None and len(temps) != len(set(only)):
        raise SystemExit(f"unknown templates: {sorted(set(only) - set(names))}")
    lengths = [len(t["T"]) for t in temps]
    lengths_all = [len(t["T"]) for t in temps_all]
    (SCORES / F).mkdir(parents=True, exist_ok=True)
    waves = template_waves(temps) if F == "F-B" else None
    t_all = time.time()
    n_peaks = 0
    walls = {}
    for sid in sids:
        t0 = time.time()
        f = session_features(sid)
        n = len(f["L"])
        tracks, info = session_tracks(F, sid, f, temps, waves)
        pk = track_peaks(tracks, lengths)
        del tracks
        _free_gpu()
        n_peaks += len(pk["score"])
        if only is not None:
            bz = np.load(base_path(F, sid))
            if str(bz["version"]) != BASE_VERSION or str(bz["content_key"]) != str(f["content_key"]):
                raise SystemExit(f"{base_path(F, sid)}: not {BASE_VERSION} peaks of this capture")
            pk = merge_peaks(pk, [t["name"] for t in temps], {k: bz[k] for k in bz.files}, names)
            info["scored"] = [t["name"] for t in temps]
            info["from_base"] = BASE_VERSION
        walls[sid] = round(time.time() - t0, 1)
        info["wall_s"] = walls[sid]
        np.savez_compressed(score_path(F, sid), **pk, names=np.array(names),
                            lengths=np.asarray(lengths_all, np.int32), hop_s=HOP, n_frames=n,
                            floor_q=FLOOR_Q, formulation=F, version=VERSION,
                            content_key=str(f["content_key"]), info=json.dumps(info))
        print(f"  {F} {sid}: {len(pk['score'])} peaks, {info}")
    metrics.record("voice_lines", part=f"score-{TAG}-{F}", session=_label(sids),
                   values={"sessions": len(sids), "peaks": n_peaks,
                           "templates_scored": len(temps),
                           "wall_s": round(time.time() - t_all, 1),
                           "wall_s_max": max(walls.values()) if walls else None},
                   deps={"version": VERSION, "score": _score_fp(F)},
                   context={"walls": walls, "threads": os.environ.get("OMP_NUM_THREADS"),
                            "scored": [t["name"] for t in temps],
                            "base": None if only is None else str(BASE_SCORES)})


def _score_fp(F: str) -> str:
    from reticle import metrics
    fn = (phat_tracks,) if F == "F-B" else (ncc_tracks, session_matrix)
    return metrics.fingerprint(*fn, prepare, trim_floor, nms_peaks, track_peaks, FLOOR_Q=FLOOR_Q,
                               CHUNK=CHUNK, PHAT_BAND=list(PHAT_BAND), FLOOR_DB=FLOOR_DB,
                               ACTIVE_DB=ACTIVE_DB)


def _label(sids: list[str]) -> str:
    ms, ds = set(match_sessions()), set(demo_sessions())
    s = set(sids)
    if s == ms | ds:
        return "all"
    if s == ms:
        return "all-matches"
    if s == ds:
        return "demos"
    return "+".join(sorted(s)) if len(s) <= 3 else f"subset-{len(s)}"


def load_peaks(F: str, sid: str) -> dict | None:
    p = score_path(F, sid)
    if not p.is_file():
        return None
    z = np.load(p)
    if str(z["version"]) != VERSION:
        raise SystemExit(f"{p}: {z['version']} != {VERSION}; rerun `score`")
    return {k: z[k] for k in z.files}


# ---------------------------------------------------------------------------
# What each session allows: the lineup, the player's agent, live time, casts
# ---------------------------------------------------------------------------

def norm_agent(a: str | None) -> str | None:
    """The asset spelling of an agent name (KAY/O is KAY_O)."""
    return None if a is None else a.replace("/", "_")


def lineup_sides(sid: str) -> dict | None:
    """Per side, the agents the identity arbiter names, the best guess and
    rival of each slot it leaves unresolved, and whether all five are named."""
    from reticle import lineup
    with contextlib.redirect_stdout(io.StringIO()):
        lu = lineup.load_lineup(sid, STORE)
    if lu is None:
        return None
    ai = {v.get("entity_id"): v for v in lu.get("agent_identity") or []}
    out = {"board": lu.get("board_state") or {}, "version": lu.get("version"),
           "disagreements": [{"side": x.get("side"), "top_bar": norm_agent(x.get("top_bar")),
                              "with_board": norm_agent(x.get("with_board"))}
                             for x in lu.get("board_disagreements") or []],
           "top_bar": {side: sorted({norm_agent(a) for sl in (lu.get("top_bar_sides") or {})
                                     .get(side, []) for a in (sl.get("best_guess"), sl.get("rival"))
                                     if a}) for side in VARIANTS}}
    for side in VARIANTS:
        slots = lu["sides"][side]
        named, soft, refused = [], set(), 0
        for i, s in enumerate(slots):
            v = ai.get(f"{sid}:{side}:slot:{i}") or {}
            if v.get("status") == "resolved" and v.get("agent"):
                named.append(norm_agent(v["agent"]))
            else:
                refused += 1
                soft |= {norm_agent(a) for a in (s.get("best_guess"), s.get("rival")) if a}
        out[side] = {"named": named, "soft": sorted(soft), "refused": refused,
                     "complete": refused == 0 and len(slots) == 5}
    return out


def template_class(agent: str, variant: str, sides: dict | None, player: str | None) -> str:
    """own, possible, impossible or unknown, for one template in one session.

    The ally variant of the player's agent is `own`. A named agent's variant
    of its side is `possible`. An ally variant is `impossible` when its agent
    is neither named on the ally side nor the best guess or rival of an
    unresolved ally slot; an enemy variant only when the enemy side is fully
    named. Everything else, and every template of a session without a
    lineup, is `unknown`.
    """
    if variant == "ally" and player is not None and agent == player:
        return "own"
    if sides is None:
        return "unknown"
    s = sides[variant]
    if agent in s["named"]:
        return "possible"
    if variant == "ally":
        return "unknown" if agent in s["soft"] else "impossible"
    return "impossible" if s["complete"] else "unknown"


def round_of(t_s: float, rrows: list[dict]) -> int | None:
    """The round a moment belongs to, by `rounds.in_round_window`."""
    from reticle.rounds import in_round_window
    ends = {r["t_end_ms"] for r in rrows}
    e = [{"t_first": t_s * 1000.0}]
    for r in rrows:
        if in_round_window(e, r["t_start_ms"], r["t_end_ms"], r["t_close_ms"], ends):
            return int(r["round_no"])
    return None


def round_unique(keys: list, rounds: list) -> np.ndarray:
    """Per detection, whether no other detection shares its key (agent and
    variant) in its round; a detection with no round is never unique."""
    from collections import Counter
    c = Counter((k, r) for k, r in zip(keys, rounds) if r is not None)
    return np.array([r is not None and c[(k, r)] == 1 for k, r in zip(keys, rounds)], bool)


def own_x_casts(sid: str) -> tuple[list[dict], list[dict], dict]:
    """(accepted own X casts, spectated X drops, provenance) of a match session.

    Accepted is the audio gate's own-cast rule restricted to the X slot: a
    tray drop the owner (`ability_timeline.player_tray_casts`, stored as
    `player_cast`) accepts and does not mark suspect, or one the player
    labelled in `labels/tray_object`. A spectated drop is an X drop after the
    player's death that is neither forced nor co-occurring with another
    slot's drop: the tray then shows a teammate's kit
    [domain:hud/tray-after-player-death].
    """
    rows = [json.loads(x) for x in (STORE / "events" / "tray_drop" / f"{sid}.jsonl")
            .read_text(encoding="utf-8").splitlines() if x.strip()]
    tray_version = rows[0].get("tray_version") if rows else None
    drops = [r for r in rows if r.get("kind") == "drop"]
    verified = audio_bank._labels(sid)
    key = lambda r: f"{sid}:{round(r['t_ms'])}:{r['slot']}"
    own, spect = [], []
    for r in drops:
        if r["slot"] != "X":
            continue
        if (r["player_cast"] and not r.get("suspect")) or key(r) in verified:
            v = verified.get(key(r))
            own.append({"t": r["t_ms"] / 1000.0, "key": key(r), "verified": v is not None,
                        "ability": v.get("ability") if v else None})
        elif (r.get("reason") == "after_player_death" and not r.get("cooccur")
              and not r.get("forced")):
            spect.append({"t": r["t_ms"] / 1000.0, "key": key(r)})
    lab = STORE / "labels" / "tray_object" / f"{sid}.jsonl"
    extra = [v for k, v in verified.items() if v.get("slot") == "X"
             and k not in {c["key"] for c in own}]
    for v in extra:             # a verified X cast the tray table no longer holds
        own.append({"t": float(v["t_drop_s"]), "key": v["key"], "verified": True,
                    "ability": v.get("ability")})
    prov = {"tray_drop": tray_version, "labels_tray_object": ag._sha(lab)}
    return sorted(own, key=lambda c: c["t"]), spect, prov


def demo_x_casts(sid: str) -> list[dict]:
    """A demo's own X casts: census rows the eye check kept (not false, not the
    menu), and Run it Back dated from decoded frames where the tray is blind
    [domain:abilities/phoenix-run-it-back-expiry-flash]."""
    out = {}
    for p in audio_bank.CENSUS_TABLES:
        if not p.is_file():
            continue
        for c in json.loads(p.read_text(encoding="utf-8"))["casts"]:
            if (c["sid"] == sid and c["slot"] == "X" and c.get("census", True)
                    and c.get("tray_verdict") not in ("false", "menu")):
                t = c["t_ms"] / 1000.0
                out.setdefault(round(t, 1), {"t": t, "key": f"{sid}:{round(c['t_ms'])}:X",
                                             "verified": False, "ability": c.get("ability"),
                                             "source": p.parent.name})
    for name, s, t, why in ag.TRAY_BLIND:
        if s == sid and name == "run_it_back":
            out.setdefault(round(t, 1), {"t": t, "key": f"{sid}:tray_blind:{name}",
                                         "verified": False, "ability": "Run It Back",
                                         "source": why})
    return sorted(out.values(), key=lambda c: c["t"])


STEP = 0.1


def match_time(sid: str, n_frames: int) -> dict:
    """Live mask (round_live, post_plant, dead or alive, not stalled) and
    stalled mask at 100 ms, and the round rows."""
    from reticle import cli, gametime, stalls
    from reticle.ability_timeline import CAST_PHASES
    from reticle.store import Store
    store = Store(STORE)
    date = cli._date_of(_manifest(sid))
    hud = store.read_hud(sid, date)
    rrows = store.read_rounds(sid, date).to_pylist()
    stall_list = stalls.for_session(store, sid, date)
    with contextlib.redirect_stdout(io.StringIO()):
        gt = gametime.build_session_gametime(sid, hud, rrows, stall_list=stall_list)
    nb = int(math.ceil(n_frames * HOP / STEP))
    phase = np.empty(nb, object)
    stalled = np.zeros(nb, bool)
    for j in range(nb):
        g = gt.game_time_at((j + 0.5) * STEP * 1000.0)
        phase[j], stalled[j] = g.phase, g.is_stalled
    live = np.isin(phase, CAST_PHASES) & ~stalled
    return {"live": live, "stalled": stalled, "rounds": rrows, "gametime": gt, "hud": hud,
            "provenance": {"rounds": rrows[0].get("round_version") if rrows else None,
                           "gametime": gametime.GAMETIME_VERSION,
                           "stalls": "reticle.stalls" if stall_list is not None else None}}


def podcast_sessions() -> list[str]:
    return ag.podcast_sessions()[0]


def session_context(sid: str, n_frames: int, names: list[str]) -> dict:
    """What evaluation needs of one session, from stored tables only."""
    demo = "ability-demo" in _manifest(sid).get("tags", [])
    ctx = {"sid": sid, "demo": demo, "capture": _manifest(sid)["source"]["path"]}
    if demo:
        ctx["player"] = norm_agent(audio_bank.tagged_agent(sid))
        ctx["player_why"] = "manifest tag"
        ctx["sides"] = None
        nb = int(math.ceil(n_frames * HOP / STEP))
        ctx["live"] = np.ones(nb, bool)
        ctx["stalled"] = np.zeros(nb, bool)
        ctx["rounds"] = []
        ctx["own"] = demo_x_casts(sid)
        ctx["spect"] = []
        ctx["provenance"] = {"census": [str(p.relative_to(STORE)) for p in audio_bank.CENSUS_TABLES]}
    else:
        agent, why = audio_bank.player_agent(sid)
        ctx["player"], ctx["player_why"] = norm_agent(agent), why
        ctx["sides"] = lineup_sides(sid)
        tm = match_time(sid, n_frames)
        ctx.update(live=tm["live"], stalled=tm["stalled"], rounds=tm["rounds"])
        own, spect, prov = own_x_casts(sid)
        at = lambda t: min(max(int(t / STEP), 0), len(tm["stalled"]) - 1)
        ctx["own"] = [c for c in own if not tm["stalled"][at(c["t"])]]
        ctx["spect"] = [c for c in spect if tm["live"][at(c["t"])]]
        ctx["provenance"] = {**tm["provenance"], **prov,
                             "lineup": (ctx["sides"] or {}).get("version"),
                             "board": (ctx["sides"] or {}).get("board")}
    ctx["live_min"] = float(ctx["live"].sum()) * STEP / 60.0
    ctx["podcast"] = sid in podcast_sessions()
    agents = [n.rsplit("_ult_", 1) for n in names]
    ctx["classes"] = [template_class(a, v, ctx["sides"], ctx["player"]) for a, v in agents]
    return ctx


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def session_detections(F: str, ctx: dict) -> dict | None:
    """Every stored peak of one session with its class, liveness, round and
    offset from the nearest own X cast."""
    pk = load_peaks(F, ctx["sid"])
    if pk is None:
        return None
    names = [str(n) for n in pk["names"]]
    agents = [n.rsplit("_ult_", 1) for n in names]
    t = pk["frame"].astype(np.float64) * HOP
    j = pk["tpl"].astype(np.int64)
    cls = np.array([ctx["classes"][k] for k in j], object)
    at = np.clip((t / STEP).astype(np.int64), 0, len(ctx["live"]) - 1)
    live = ctx["live"][at]
    own_t = np.array([c["t"] for c in ctx["own"]], float)
    dt = np.full(len(t), np.nan)
    if len(own_t):
        i = np.argmin(np.abs(t[:, None] - own_t[None, :]), axis=1)
        d = t - own_t[i]
        dt = np.where(np.abs(d) <= OWN_WIN, d, np.nan)
    return {"sid": ctx["sid"], "t": t, "j": j, "score": pk["score"].astype(np.float64),
            "cls": cls, "live": live, "dt": dt, "names": names,
            "agent": np.array([a for a, _v in agents], object)[j],
            "variant": np.array([v for _a, v in agents], object)[j],
            "floor": pk["floor"], "lengths": pk["lengths"]}


def best_near(d: dict, casts: list[dict], cls: str = "own", lo: float = -OWN_WIN,
              hi: float = OWN_WIN) -> tuple[np.ndarray, np.ndarray]:
    """Per cast, the highest score of a `cls` detection with onset minus drop
    in [lo, hi], and that offset (-inf and NaN where none)."""
    best = np.full(len(casts), -np.inf)
    lag = np.full(len(casts), np.nan)
    m = d["cls"] == cls
    for i, c in enumerate(casts):
        dt = d["t"] - c["t"]
        w = m & (dt >= lo) & (dt <= hi)
        if w.any():
            k = np.flatnonzero(w)[np.argmax(d["score"][w])]
            best[i], lag[i] = d["score"][k], d["t"][k] - c["t"]
    return best, lag


def suppress(t: np.ndarray, j: np.ndarray, score: np.ndarray,
             window: float) -> tuple[np.ndarray, np.ndarray]:
    """(keep mask, the index of the peak that dropped each dropped peak or -1).

    Greedy by score: a peak stands unless a standing, higher peak of another
    template lies within `window` seconds; it is then dropped by the highest
    such peak. A dropped peak drops nothing, and peaks of one template never
    drop each other (their own NMS already spaced them). Above any threshold
    the result equals suppression among the peaks above it, because only
    higher peaks decide a peak's fate.
    """
    import bisect
    t = np.asarray(t, np.float64)
    order = np.argsort(-np.asarray(score, np.float64), kind="stable")
    keep = np.zeros(len(t), bool)
    by = np.full(len(t), -1, np.int64)
    ts: list[float] = []
    idx: list[int] = []
    for i in order:
        a = bisect.bisect_left(ts, t[i] - window)
        b = bisect.bisect_right(ts, t[i] + window)
        rivals = [idx[q] for q in range(a, b) if j[idx[q]] != j[i]]
        if rivals:
            by[i] = max(rivals, key=lambda k: (score[k], -k))
            continue
        keep[i] = True
        q = bisect.bisect_right(ts, t[i])
        ts.insert(q, float(t[i]))
        idx.insert(q, int(i))
    return keep, by


#: The per-peak arrays of a session's detections.
PER_PEAK = ("t", "j", "score", "cls", "live", "dt", "agent", "variant")


def apply_suppression(d: dict, window: float | None) -> dict:
    """The detections cross-template suppression leaves; `kept` and `dropped_by`
    index the unsuppressed peaks."""
    if window is None:
        return d
    keep, by = suppress(d["t"], d["j"], d["score"], window)
    out = dict(d)
    for k in PER_PEAK:
        out[k] = d[k][keep]
    out["kept"], out["dropped_by"] = keep, by
    return out


def operating_tau(imp_scores: np.ndarray, live_min: float, rate: float = OP_RATE) -> float:
    """The lowest threshold with at most `rate` impossible detections per live minute."""
    allow = int(math.floor(rate * live_min + 1e-9))
    s = np.sort(np.asarray(imp_scores, np.float64))[::-1]
    if len(s) <= allow:
        return float(s[-1]) if len(s) else 0.0
    return float(np.nextafter(s[allow], np.inf))


def _r(x, n=3):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def _q(v, q):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    return _r(float(np.quantile(v, q))) if len(v) else None


def rates_at(ds: list[dict], ctxs: dict, tau: float) -> dict:
    """Pooled counts and rates at tau over sessions with a lineup."""
    n = {c: 0 for c in CLASSES}
    ally = enemy = 0
    tm_imp = tm_pos = 0.0
    live = 0.0
    for d in ds:
        c = ctxs[d["sid"]]
        live += c["live_min"]
        k = (d["score"] >= tau) & d["live"]
        for cl in CLASSES:
            n[cl] += int((k & (d["cls"] == cl)).sum())
        pos = k & (d["cls"] == "possible")
        ally += int((pos & (d["variant"] == "ally")).sum())
        enemy += int((pos & (d["variant"] == "enemy")).sum())
        tm_imp += c["classes"].count("impossible") * c["live_min"]
        tm_pos += c["classes"].count("possible") * c["live_min"]
    per = lambda x: x / live if live else float("nan")
    fa = n["impossible"] / tm_imp if tm_imp else float("nan")
    return {"live_minutes": live, "n": n, "impossible_per_min": per(n["impossible"]),
            "possible_per_min": per(n["possible"]), "own_per_min": per(n["own"]),
            "possible_or_own_per_min": per(n["possible"] + n["own"]),
            "possible_ally_per_min": per(ally), "possible_enemy_per_min": per(enemy),
            "n_possible_ally": ally, "n_possible_enemy": enemy,
            "false_per_template_min": fa,
            "expected_false_possible_per_min": fa * tm_pos / live if live else float("nan")}


def sweep(ds: list[dict], ctxs: dict, n: int = 300) -> dict:
    """Curves over thresholds: impossible, possible and own rates, own recall."""
    live = [d for d in ds if ctxs[d["sid"]]["sides"] is not None]
    pooled = np.concatenate([d["score"][d["live"]] for d in live]) if live else np.zeros(0)
    taus = np.unique(np.quantile(pooled, 1 - np.geomspace(0.9, 1e-5, n))) if len(pooled) else []
    casts = [(d, ctxs[d["sid"]]["own"], cast_window(ctxs[d["sid"]]["player"])) for d in ds
             if ctxs[d["sid"]]["player"] is not None and not ctxs[d["sid"]]["demo"]]
    best = np.concatenate([best_near(d, cs)[0] for d, cs, _w in casts]) if casts else np.zeros(0)
    best_aw = (np.concatenate([best_near(d, cs, lo=w[0], hi=w[1])[0] for d, cs, w in casts])
               if casts else np.zeros(0))
    out = {k: [] for k in ("tau", "impossible", "possible", "own", "recall", "recall_agent")}
    for tau in taus:
        r = rates_at(live, ctxs, tau)
        out["tau"].append(float(tau))
        out["impossible"].append(r["impossible_per_min"])
        out["possible"].append(r["possible_per_min"])
        out["own"].append(r["own_per_min"])
        out["recall"].append(float((best >= tau).mean()) if len(best) else float("nan"))
        out["recall_agent"].append(float((best_aw >= tau).mean()) if len(best_aw) else float("nan"))
    return {k: np.asarray(v) for k, v in out.items()}


def summarise(F: str, ds: list[dict], ctxs: dict, tau: float | None = None) -> dict:
    """Every pooled, per-session and witness value of one formulation."""
    lin = [d for d in ds if ctxs[d["sid"]]["sides"] is not None and not ctxs[d["sid"]]["demo"]]
    if not lin:
        raise SystemExit("no match session with a lineup among those evaluated")
    live_min = sum(ctxs[d["sid"]]["live_min"] for d in lin)
    imp = np.concatenate([d["score"][d["live"] & (d["cls"] == "impossible")] for d in lin])
    tau_own = operating_tau(imp, live_min)
    tau = tau_own if tau is None else tau
    r = rates_at(lin, ctxs, tau)
    v = {"tau_op": _r(tau, 4), "tau_computed": _r(tau_own, 4), "sessions": len(lin),
         "live_minutes": _r(live_min, 1), "impossible_n": r["n"]["impossible"],
         "impossible_per_min": _r(r["impossible_per_min"], 3),
         "possible_n": r["n"]["possible"], "possible_per_min": _r(r["possible_per_min"], 3),
         "possible_ally_per_min": _r(r["possible_ally_per_min"], 3),
         "possible_enemy_per_min": _r(r["possible_enemy_per_min"], 3),
         "possible_ally_n": r["n_possible_ally"], "possible_enemy_n": r["n_possible_enemy"],
         "own_n": r["n"]["own"], "own_per_min": _r(r["own_per_min"], 3),
         "possible_or_own_per_min": _r(r["possible_or_own_per_min"], 3),
         "false_per_template_min": _r(r["false_per_template_min"], 5),
         "expected_false_possible_per_min": _r(r["expected_false_possible_per_min"], 4),
         "floor_max": _r(max(float(np.max(d["floor"])) for d in lin), 4)}
    v["complete"] = int(tau >= v["floor_max"] - 1e-9)

    # Own casts: accepted and verified X drops.
    matches = [d for d in ds if not ctxs[d["sid"]]["demo"] and ctxs[d["sid"]]["player"]]
    b_all, l_all, ver, agent_of = [], [], [], []
    b_enemy = []
    for d in matches:
        cs = ctxs[d["sid"]]["own"]
        b, lag = best_near(d, cs)
        b_all.append(b)
        l_all.append(lag)
        ver += [c["verified"] for c in cs]
        agent_of += [ctxs[d["sid"]]["player"]] * len(cs)
        # The player's agent's enemy variant near the same casts.
        pl = ctxs[d["sid"]]["player"]
        m = (d["agent"] == pl) & (d["variant"] == "enemy") & (d["score"] >= tau)
        b_enemy.append(np.array([bool((m & (np.abs(d["t"] - c["t"]) <= OWN_WIN)).any())
                                 for c in cs], bool))
    b_all = np.concatenate(b_all) if b_all else np.zeros(0)
    l_all = np.concatenate(l_all) if l_all else np.zeros(0)
    b_enemy = np.concatenate(b_enemy) if b_enemy else np.zeros(0, bool)
    ver = np.asarray(ver, bool)
    agent_of = np.asarray(agent_of, object)
    hit = b_all >= tau
    v.update({"own_casts": int(len(b_all)), "own_hits": int(hit.sum()),
              "own_recall": _r(hit.mean()) if len(hit) else None,
              "verified_casts": int(ver.sum()), "verified_hits": int((hit & ver).sum()),
              "verified_recall": _r((hit & ver).sum() / ver.sum()) if ver.any() else None,
              "own_enemy_variant_hits": int(b_enemy.sum())})
    for a in sorted(set(agent_of)):
        m = agent_of == a
        v[f"own_recall_{a}"] = _r(hit[m].mean())
        v[f"own_casts_{a}"] = int(m.sum())
        mv = m & ver
        if mv.any():
            v[f"verified_recall_{a}"] = _r(hit[mv].mean())
            v[f"verified_casts_{a}"] = int(mv.sum())
    lag = l_all[hit]
    v.update({"onset_n": int(len(lag)), "onset_median_s": _q(lag, 0.5),
              "onset_q25_s": _q(lag, 0.25), "onset_q75_s": _q(lag, 0.75)})
    if len(lag):
        v["onset_iqr_s"] = _r(np.quantile(lag, 0.75) - np.quantile(lag, 0.25))
    # The same casts with each agent's cast window (CAST_WINDOW).
    b_aw = [best_near(d, ctxs[d["sid"]]["own"], lo=cast_window(ctxs[d["sid"]]["player"])[0],
                      hi=cast_window(ctxs[d["sid"]]["player"])[1])[0] for d in matches]
    b_aw = np.concatenate(b_aw) if b_aw else np.zeros(0)
    hit_aw = b_aw >= tau
    v.update({"own_hits_agent_window": int(hit_aw.sum()),
              "own_recall_agent_window": _r(hit_aw.mean()) if len(hit_aw) else None,
              "verified_hits_agent_window": int((hit_aw & ver).sum()),
              "verified_recall_agent_window": _r((hit_aw & ver).sum() / ver.sum())
              if ver.any() else None})
    for a in sorted(set(agent_of)):
        m = agent_of == a
        v[f"own_recall_agent_window_{a}"] = _r(hit_aw[m].mean())
        if (m & ver).any():
            v[f"verified_recall_agent_window_{a}"] = _r(hit_aw[m & ver].mean())
    for a, (lo, hi) in CAST_WINDOW.items():
        # Chance that an own detection at this agent's live rate lands in the window.
        da = [d for d in matches if ctxs[d["sid"]]["player"] == a]
        mins = sum(ctxs[d["sid"]]["live_min"] for d in da)
        n_own = sum(int(((d["cls"] == "own") & d["live"] & (d["score"] >= tau)).sum()) for d in da)
        if mins:
            v[f"agent_window_chance_{a}"] = _r(1.0 - math.exp(-n_own / mins * (hi - lo) / 60.0))
    lagv = l_all[hit & ver]
    v.update({"onset_verified_n": int(len(lagv)), "onset_verified_median_s": _q(lagv, 0.5)})
    if len(lagv):
        v["onset_verified_iqr_s"] = _r(np.quantile(lagv, 0.75) - np.quantile(lagv, 0.25))

    # Per session, the enemy to ally ratio, the round invariant and the rates.
    per = {}
    ratios, uniq_all, uniq_pos = [], [], []
    tau5 = operating_tau(imp, live_min, P5_RATE)
    pod = {"imp": [0, 0.0], "rest": [0, 0.0], "imp5": [0, 0.0], "rest5": [0, 0.0]}
    for d in lin:
        c = ctxs[d["sid"]]
        k = (d["score"] >= tau) & d["live"]
        rr = [round_of(t, c["rounds"]) for t in d["t"][k]]
        keys = [f"{a}_{w}" for a, w in zip(d["agent"][k], d["variant"][k])]
        u = round_unique(keys, rr)
        has_round = np.array([x is not None for x in rr], bool)
        uniq_all.append(u[has_round])
        pos = np.isin(d["cls"][k], ["own", "possible"])
        uniq_pos.append(u[has_round & pos])
        ally = int((pos & (d["variant"][k] == "ally")).sum())
        enemy = int((pos & (d["variant"][k] == "enemy")).sum())
        if ally:
            ratios.append(enemy / ally)
        n_imp = int((d["cls"][k] == "impossible").sum())
        n_imp5 = int(((d["score"] >= tau5) & d["live"] & (d["cls"] == "impossible")).sum())
        grp = "imp" if c["podcast"] else "rest"
        pod[grp][0] += n_imp
        pod[grp][1] += c["live_min"]
        pod[grp + "5"][0] += n_imp5
        pod[grp + "5"][1] += c["live_min"]
        b, _l = best_near(d, c["own"])
        lo, hi = cast_window(c["player"])
        b_w, _l = best_near(d, c["own"], lo=lo, hi=hi)
        per[d["sid"]] = {
            "live_minutes": _r(c["live_min"], 1), "podcast": int(c["podcast"]),
            "impossible_n": n_imp, "impossible_per_min": _r(n_imp / c["live_min"], 3),
            "impossible_per_min_at_p5": _r(n_imp5 / c["live_min"], 3),
            "possible_ally_n": int(((d["cls"][k] == "possible") & (d["variant"][k] == "ally")).sum()),
            "possible_enemy_n": int(((d["cls"][k] == "possible") & (d["variant"][k] == "enemy")).sum()),
            "own_n": int((d["cls"][k] == "own").sum()),
            "possible_per_min": _r(int((d["cls"][k] == "possible").sum()) / c["live_min"], 3),
            "enemy_ally_ratio": _r(enemy / ally) if ally else None,
            "own_casts": len(c["own"]), "own_hits": int((b >= tau).sum()),
            "own_hits_agent_window": int((b_w >= tau).sum()),
            "templates_impossible": c["classes"].count("impossible"),
            "templates_possible": c["classes"].count("possible"),
            "board_applied": int(bool((c["sides"] or {}).get("board", {}).get("applied"))),
            "round_unique_fraction": _r(u[has_round].mean()) if has_round.any() else None}
    ua = np.concatenate(uniq_all) if uniq_all else np.zeros(0, bool)
    up = np.concatenate(uniq_pos) if uniq_pos else np.zeros(0, bool)
    v.update({"enemy_ally_ratio_median": _r(float(np.median(ratios))) if ratios else None,
              "enemy_ally_sessions": len(ratios),
              "enemy_ally_ratio_pooled": _r(r["n_possible_enemy"] / (r["n_possible_ally"] + r["n"]["own"]))
              if (r["n_possible_ally"] + r["n"]["own"]) else None,
              "round_n": int(len(ua)), "round_unique_fraction": _r(ua.mean()) if len(ua) else None,
              "round_n_possible": int(len(up)),
              "round_unique_fraction_possible": _r(up.mean()) if len(up) else None})
    rate = lambda g: pod[g][0] / pod[g][1] if pod[g][1] else float("nan")
    v.update({"tau_p5": _r(tau5, 4),
              "podcast_impossible_per_min": _r(rate("imp"), 3),
              "rest_impossible_per_min": _r(rate("rest"), 3),
              "podcast_ratio": _r(rate("imp") / rate("rest")) if rate("rest") else None,
              "podcast_impossible_per_min_at_p5": _r(rate("imp5"), 3),
              "rest_impossible_per_min_at_p5": _r(rate("rest5"), 3),
              "podcast_ratio_at_p5": _r(rate("imp5") / rate("rest5")) if rate("rest5") else None,
              "podcast_sessions": sum(ctxs[d["sid"]]["podcast"] for d in lin)})

    # Cross-talk: impossible detections within OWN_WIN of a higher possible or own one.
    near = total = 0
    for d in lin:
        k = (d["score"] >= tau) & d["live"]
        imp_k = np.flatnonzero(k & (d["cls"] == "impossible"))
        tru = np.flatnonzero(np.isin(d["cls"], ["own", "possible"]) & (d["score"] >= tau))
        for i in imp_k:
            total += 1
            w = tru[np.abs(d["t"][tru] - d["t"][i]) <= OWN_WIN]
            near += int(bool((d["score"][w] > d["score"][i]).any()))
    v["impossible_beside_true_n"] = near
    v["impossible_beside_true_fraction"] = _r(near / total) if total else None
    return {"values": v, "per_session": per, "tau": tau}


def _lineup_matches(ds: list[dict], ctxs: dict) -> list[dict]:
    return [d for d in ds if ctxs[d["sid"]]["sides"] is not None and not ctxs[d["sid"]]["demo"]]


def window_offsets(ds: list[dict], ctxs: dict, tau: float) -> tuple[np.ndarray, int]:
    """(onset of each live impossible detection at tau minus that of the highest
    own or possible detection at tau of another template that outscores it
    within OFFSET_PROBE_S, the number of live impossible detections)."""
    offs, n_imp = [], 0
    for d in _lineup_matches(ds, ctxs):
        k = d["score"] >= tau
        tru = np.flatnonzero(k & np.isin(d["cls"], ["own", "possible"]))
        for i in np.flatnonzero(k & d["live"] & (d["cls"] == "impossible")):
            n_imp += 1
            w = tru[(np.abs(d["t"][tru] - d["t"][i]) <= OFFSET_PROBE_S)
                    & (d["score"][tru] > d["score"][i]) & (d["j"][tru] != d["j"][i])]
            if len(w):
                b = w[np.argmax(d["score"][w])]
                offs.append(float(d["t"][i] - d["t"][b]))
    return np.asarray(offs), n_imp


def removals(ds0: list[dict], ctxs: dict, tau: float, window: float) -> tuple[dict, list[dict]]:
    """What suppression at `window` removes from the unsuppressed live
    detections at tau, by class and by the class of the peak that removed it.
    A removed possible or own detection that was the only one of its agent and
    variant in its round (unsuppressed, at tau) would be a real loss. For the
    player's tray casts it also counts the hits at tau the rule costs, under
    the fixed and the per-agent cast window."""
    v = {f"removed_{c}": 0 for c in CLASSES}
    v.update({"removed_possible_alone": 0, "removed_own_alone": 0, "removed_own_at_cast": 0,
              "own_hits_unsuppressed": 0, "own_hits_suppressed": 0,
              "own_hits_agent_window_unsuppressed": 0, "own_hits_agent_window_suppressed": 0,
              "removed_possible_by_impossible": 0, "removed_possible_by_true": 0,
              "removed_possible_by_unknown": 0, "removed_own_by_impossible": 0,
              "removed_own_by_true": 0, "removed_own_by_unknown": 0})
    rows = []
    for d in _lineup_matches(ds0, ctxs):
        c = ctxs[d["sid"]]
        keep, by = suppress(d["t"], d["j"], d["score"], window)
        k = (d["score"] >= tau) & d["live"]
        ki = np.flatnonzero(k)
        rr = [round_of(t, c["rounds"]) for t in d["t"][ki]]
        u = round_unique([f"{a}_{w}" for a, w in zip(d["agent"][ki], d["variant"][ki])], rr)
        alone = np.zeros(len(d["t"]), bool)
        alone[ki] = u
        casts = c["own"] if c.get("player") else []
        lo, hi = cast_window(c.get("player"))
        at_cast = np.zeros(len(d["t"]), bool)
        if casts:
            dk = {**d, "cls": np.where(keep, d["cls"], "dropped")}
            for key, (a, b_) in (("own_hits", (-OWN_WIN, OWN_WIN)),
                                 ("own_hits_agent_window", (lo, hi))):
                v[f"{key}_unsuppressed"] += int((best_near(d, casts, lo=a, hi=b_)[0] >= tau).sum())
                v[f"{key}_suppressed"] += int((best_near(dk, casts, lo=a, hi=b_)[0] >= tau).sum())
            for cst in casts:
                dt = d["t"] - cst["t"]
                at_cast |= (dt >= lo) & (dt <= hi)
        for i in np.flatnonzero(k & ~keep):
            cl, b = str(d["cls"][i]), int(by[i])
            v[f"removed_{cl}"] += 1
            bc = str(d["cls"][b])
            kind = "impossible" if bc == "impossible" else "true" if bc in ("own", "possible") else "unknown"
            if cl in ("possible", "own"):
                v[f"removed_{cl}_by_{kind}"] += 1
                v[f"removed_{cl}_alone"] += int(alone[i])
                if cl == "own":
                    v["removed_own_at_cast"] += int(at_cast[i])
                rows.append({"session_id": d["sid"], "t_s": round(float(d["t"][i]), 2),
                             "template": d["names"][d["j"][i]], "class": cl,
                             "score": round(float(d["score"][i]), 4), "alone_in_round": bool(alone[i]),
                             "in_own_cast_window": bool(at_cast[i]) if cl == "own" else None,
                             "dropped_by": d["names"][d["j"][b]], "dropped_by_class": bc,
                             "dropped_by_score": round(float(d["score"][b]), 4),
                             "offset_s": round(float(d["t"][i] - d["t"][b]), 2)})
    v["own_hits_lost"] = v["own_hits_unsuppressed"] - v["own_hits_suppressed"]
    v["own_hits_agent_window_lost"] = (v["own_hits_agent_window_unsuppressed"]
                                       - v["own_hits_agent_window_suppressed"])
    return v, rows


def suppression_stats(F: str, ds0: list[dict], ctxs: dict, tau0: float, tau1: float,
                      windows: tuple = ()) -> tuple[dict, dict]:
    """The window evidence (offsets at the unsuppressed operating point), what
    SUPPRESS_S removes at the suppressed operating point, and a sweep of other
    windows, each at its own operating point."""
    offs, n_imp = window_offsets(ds0, ctxs, tau0)
    a = np.abs(offs)
    v = {"window_s": SUPPRESS_S, "tau_unsuppressed": _r(tau0, 4), "tau_suppressed": _r(tau1, 4),
         "offsets_impossible_n": n_imp, "offsets_n": int(len(a)),
         "offsets_abs_median_s": _q(a, 0.5), "offsets_abs_q90_s": _q(a, 0.9),
         "offsets_abs_max_s": _r(a.max(), 2) if len(a) else None}
    edges = (0.0, 0.3, 0.6, 1.2, 2.5, OFFSET_PROBE_S)
    key = lambda x: f"{x:g}".replace(".", "p")
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (a <= hi) & ((a > lo) if lo > 0 else (a >= 0))
        v[f"offsets_{key(lo)}_to_{key(hi)}_s"] = int(m.sum())
    rem, rows = removals(ds0, ctxs, tau1, SUPPRESS_S)
    v.update(rem)
    for w in windows:
        dsw = [apply_suppression(d, w) for d in ds0]
        sw = summarise(F, dsw, ctxs)["values"]
        rw, _rows = removals(ds0, ctxs, sw["tau_op"], w)
        wk = "w" + key(w)
        for k in ("tau_op", "impossible_n", "possible_per_min", "own_recall",
                  "own_recall_agent_window", "verified_recall", "round_unique_fraction",
                  "round_unique_fraction_possible", "impossible_beside_true_fraction"):
            v[f"{wk}_{k}"] = sw[k]
        v[f"{wk}_removed_possible_alone"] = rw["removed_possible_alone"]
        v[f"{wk}_removed_own_alone"] = rw["removed_own_alone"]
        v[f"{wk}_own_hits_agent_window_lost"] = rw["own_hits_agent_window_lost"]
    return v, {"offsets_s": [round(float(x), 2) for x in offs], "removed": rows}


def gekko_table(ds: list[dict], ctxs: dict, tau: float, agent: str = "Gekko") -> tuple[dict, list]:
    """The added agent's two lines on the match sessions: per class, sessions
    and live detections at tau; per session where a line is possible or fires,
    its class, detections and highest live peak."""
    v, rows = {}, []
    for w in VARIANTS:
        name = f"{agent}_ult_{w}"
        tally = {c: [0, 0] for c in CLASSES}
        for d in ds:
            c = ctxs[d["sid"]]
            if c["demo"] or name not in d["names"]:
                continue
            j = d["names"].index(name)
            cl = c["classes"][j]
            mj = (d["j"] == j) & d["live"]
            m = mj & (d["score"] >= tau)
            tally[cl][0] += 1
            tally[cl][1] += int(m.sum())
            if cl in ("own", "possible") or m.any():
                v[f"{d['sid']}_{w}_class"] = cl
                v[f"{d['sid']}_{w}_n"] = int(m.sum())
                v[f"{d['sid']}_{w}_max_score"] = _r(float(d["score"][mj].max()), 4) if mj.any() else None
                rows += [{"session_id": d["sid"], "template": name, "class": cl,
                          "t_s": round(float(d["t"][i]), 2), "score": round(float(d["score"][i]), 4),
                          "round": round_of(float(d["t"][i]), c["rounds"])}
                         for i in np.flatnonzero(m)]
        for cl, (ns, nd) in tally.items():
            v[f"{w}_{cl}_sessions"] = ns
            v[f"{w}_{cl}_n"] = nd
    return v, rows


def agent_table(F: str, ds: list[dict], ctxs: dict, tau: float) -> dict:
    """Per agent and variant: sessions it is possible in, and live detections at tau by class."""
    lin = [d for d in ds if ctxs[d["sid"]]["sides"] is not None and not ctxs[d["sid"]]["demo"]]
    names = lin[0]["names"] if lin else []
    v = {}
    for j, n in enumerate(names):
        for cl in ("own", "possible", "impossible"):
            v[f"{n}_{cl}_sessions"] = sum(ctxs[d["sid"]]["classes"][j] == cl for d in lin)
            v[f"{n}_{cl}_n"] = int(sum(((d["j"] == j) & (d["cls"] == cl) & d["live"]
                                        & (d["score"] >= tau)).sum() for d in lin))
    return v


def witnesses(F: str, ds: list[dict], ctxs: dict, tau: float) -> dict:
    """Independent checks: the line the player heard, spectated X drops, demos."""
    v = {}
    by = {d["sid"]: d for d in ds}
    for sid, t, agent, _why in HEARD:
        d = by.get(sid)
        if d is None:
            continue
        m = (d["agent"] == agent) & (np.abs(d["t"] - t) <= 3.0)
        for w in VARIANTS:
            mw = m & (d["variant"] == w)
            if mw.any():
                k = np.flatnonzero(mw)[np.argmax(d["score"][mw])]
                v[f"heard_{sid}_{agent}_{w}_score"] = _r(d["score"][k], 4)
                v[f"heard_{sid}_{agent}_{w}_dt_s"] = _r(d["t"][k] - t, 2)
                v[f"heard_{sid}_{agent}_{w}_detected"] = int(d["score"][k] >= tau)
                v[f"heard_{sid}_{agent}_{w}_class"] = str(d["cls"][k])
    # A spectated teammate's X drop against possible ally-variant detections.
    n = hit = 0
    cover = live = 0
    for d in ds:
        c = ctxs[d["sid"]]
        if c["demo"] or c["sides"] is None:
            continue
        k = (d["score"] >= tau) & (d["cls"] == "possible") & (d["variant"] == "ally")
        tk = d["t"][k]
        for s in c["spect"]:
            n += 1
            hit += int(bool((np.abs(tk - s["t"]) <= OWN_WIN).any()))
        grid = (np.arange(len(c["live"])) + 0.5) * STEP
        m = np.zeros(len(grid), bool)
        for t in tk:
            m |= np.abs(grid - t) <= OWN_WIN
        cover += int((m & c["live"]).sum())
        live += int(c["live"].sum())
    v.update({"spectated_x_drops": n, "spectated_x_with_ally_line": hit,
              "spectated_x_fraction": _r(hit / n) if n else None,
              "spectated_x_chance": _r(cover / live) if live else None})
    # Demos: the player's own ult line at each demo X cast.
    dn = dh = 0
    lags, other, minutes = [], 0, 0.0
    for d in ds:
        c = ctxs[d["sid"]]
        if not c["demo"]:
            continue
        b, lag = best_near(d, c["own"])
        dn += len(b)
        dh += int((b >= tau).sum())
        lags += list(lag[b >= tau])
        other += int(((d["score"] >= tau) & (d["cls"] != "own")).sum())
        minutes += c["live_min"]
        for cst, bb, ll in zip(c["own"], b, lag):
            at = f"{cst['t']:.1f}".replace(".", "p")
            v[f"demo_{d['sid']}_{at}_score"] = _r(bb, 4) if np.isfinite(bb) else None
            v[f"demo_{d['sid']}_{at}_dt_s"] = _r(ll, 2)
    # The lineup: slots where the scoreboard overrode the top bar, and
    # impossible detections of an agent the top bar proposed on that side.
    n_dis = board_lines = top_lines = imp_top = imp_all = 0
    for d in ds:
        c = ctxs[d["sid"]]
        if c["demo"] or c["sides"] is None:
            continue
        k = (d["score"] >= tau) & d["live"]
        for x in c["sides"]["disagreements"]:
            n_dis += 1
            m = k & (d["variant"] == x["side"])
            board_lines += int((m & (d["agent"] == x["with_board"])).sum())
            top_lines += int((m & (d["agent"] == x["top_bar"])).sum())
        for i in np.flatnonzero(k & (d["cls"] == "impossible")):
            imp_all += 1
            imp_top += int(d["agent"][i] in c["sides"]["top_bar"][d["variant"][i]])
    v.update({"board_disagreements": n_dis, "board_agent_lines": board_lines,
              "top_bar_agent_lines": top_lines, "impossible_top_bar_proposed": imp_top,
              "impossible_live": imp_all})
    # Own X drops against the own line from LEAD_WIN s before to OWN_WIN s
    # after the drop, by the player's agent: a drop may date something other
    # than the cast. Chance is the probability that an own detection at that
    # agent's sessions' live rate falls in a window of that length.
    lead = {}
    for d in ds:
        c = ctxs[d["sid"]]
        if c["demo"] or c["player"] is None:
            continue
        a = lead.setdefault(norm_agent(c["player"]),
                            {"casts": 0, "hits": 0, "lags": [], "own_live": 0, "minutes": 0.0})
        k = (d["score"] >= tau) & (d["cls"] == "own")
        a["own_live"] += int((k & d["live"]).sum())
        a["minutes"] += c["live_min"]
        for cst in c["own"]:
            a["casts"] += 1
            w = k & (d["t"] >= cst["t"] - LEAD_WIN) & (d["t"] <= cst["t"] + OWN_WIN)
            if w.any():
                i = np.flatnonzero(w)[np.argmax(d["score"][w])]
                a["hits"] += 1
                a["lags"].append(float(d["t"][i] - cst["t"]))
    for name, a in sorted(lead.items()):
        if not a["casts"]:
            continue
        rate = a["own_live"] / a["minutes"] if a["minutes"] else 0.0
        v[f"lead_{name}_casts"] = a["casts"]
        v[f"lead_{name}_hits"] = a["hits"]
        v[f"lead_{name}_median_s"] = _q(a["lags"], 0.5) if a["lags"] else None
        v[f"lead_{name}_q25_s"] = _q(a["lags"], 0.25) if a["lags"] else None
        v[f"lead_{name}_q75_s"] = _q(a["lags"], 0.75) if a["lags"] else None
        v[f"lead_{name}_chance"] = _r(1.0 - np.exp(-rate * (LEAD_WIN + OWN_WIN) / 60.0), 3)
    v.update({"demo_x_casts": dn, "demo_x_hits": dh,
              "demo_onset_median_s": _q(lags, 0.5) if lags else None,
              "demo_other_per_min": _r(other / minutes, 3) if minutes else None,
              "demo_minutes": _r(minutes, 1)})
    return v


def write_detections(F: str, ds0: list[dict], ds1: list[dict], ctxs: dict, tau: float) -> int:
    """detections/<sid>.jsonl: one row per unsuppressed peak at or above tau,
    marked `suppressed` with the peak that dropped it; rows of the other
    formulations already there stay."""
    DETS.mkdir(parents=True, exist_ok=True)
    total = 0
    for d, d1 in zip(ds0, ds1):
        c = ctxs[d["sid"]]
        p = DETS / f"{d['sid']}.jsonl"
        keep = []
        if p.is_file():
            keep = [x for x in p.read_text(encoding="utf-8").splitlines()
                    if x.strip() and json.loads(x).get("formulation") != F]
        own_by_t = {round(x["t"], 3): x for x in c["own"]}
        rows = []
        for i in np.flatnonzero(d["score"] >= tau):
            t = float(d["t"][i])
            row = {"session_id": d["sid"], "version": VERSION, "formulation": F,
                   "tau": round(tau, 4), "t_s": round(t, 2), "template": d["names"][d["j"][i]],
                   "agent": str(d["agent"][i]), "variant": str(d["variant"][i]),
                   "score": round(float(d["score"][i]), 4), "class": str(d["cls"][i]),
                   "live": bool(d["live"][i]), "round": round_of(t, c["rounds"]),
                   "suppressed": not bool(d1["kept"][i]), "window_s": SUPPRESS_S}
            b = int(d1["dropped_by"][i])
            if b >= 0:
                row["dropped_by"] = d["names"][d["j"][b]]
                row["dropped_by_score"] = round(float(d["score"][b]), 4)
            if np.isfinite(d["dt"][i]):
                row["own_cast_dt_s"] = round(float(d["dt"][i]), 2)
                near = min(own_by_t.values(), key=lambda x: abs(x["t"] - t))
                row["own_cast_verified"] = near["verified"]
            rows.append(json.dumps(row))
        total += len(rows)
        p.write_text("".join(x + "\n" for x in keep + rows), encoding="utf-8")
    return total


# ---------------------------------------------------------------------------
# Curves
# ---------------------------------------------------------------------------

#: The reference categorical order, slots 1 to 3 (validated, light surface).
COLOURS = {"F-A": "#2a78d6", "F-B": "#eb6834", "F-C": "#1baf7a"}
#: A reference curve (F-B without suppression, as 0.1.0 measured it).
REFERENCE = "#8a8984"


def _bgr(h: str) -> tuple[int, int, int]:
    return int(h[5:7], 16), int(h[3:5], 16), int(h[1:3], 16)


def plot_curves(curves: dict, ykey: str, ylabel: str, ymax: float | None, title: str, out: Path,
                ops: dict | None = None, xmax: float = 10.0) -> Path:
    """y against impossible detections per live minute (log x, 0.003 to
    `xmax`), one line per formulation, direct labels, the operating rate
    dashed. `ymax` None scales y to the curves within the x range."""
    import cv2
    font = cv2.FONT_HERSHEY_SIMPLEX
    wide = max(cv2.getTextSize(str(F), font, 0.5, 1)[0][0] for F in curves)
    W, H, l, t, b = 960, 600, 80, 64, 60
    r = max(150, 76 + wide)
    img = np.full((H, W, 3), _bgr("#fcfcfb"), np.uint8)
    ink, ink2, grid = _bgr("#0b0b0b"), _bgr("#52514e"), _bgr("#e6e5e0")
    xmin = 0.003
    if ymax is None:
        top = [float(np.nanmax(c[ykey][c["impossible"] <= xmax])) for c in curves.values()
               if np.any(c["impossible"] <= xmax)]
        ymax = max(top) if top else 1.0
        step = 10 ** math.floor(math.log10(ymax / 5)) if ymax > 0 else 0.1
        ymax = math.ceil(ymax / step / 5) * step * 5 if ymax > 0 else 1.0
    x0, x1 = math.log10(xmin), math.log10(xmax)
    px = lambda v: int(l + (math.log10(min(max(v, xmin), xmax)) - x0) / (x1 - x0) * (W - l - r))
    py = lambda v: int(H - b - min(max(v, 0), ymax) / ymax * (H - t - b))
    font = cv2.FONT_HERSHEY_SIMPLEX
    for v in (0.003, 0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30):
        if v > xmax:
            continue
        cv2.line(img, (px(v), t), (px(v), H - b), grid, 1)
        (tw, _th), _ = cv2.getTextSize(f"{v:g}", font, 0.45, 1)
        cv2.putText(img, f"{v:g}", (px(v) - tw // 2, H - b + 20), font, 0.45, ink2, 1, cv2.LINE_AA)
    for v in np.linspace(0, ymax, 6):
        cv2.line(img, (l, py(v)), (W - r, py(v)), grid, 1)
        lab = f"{v:.3g}"
        (tw, _th), _ = cv2.getTextSize(lab, font, 0.45, 1)
        cv2.putText(img, lab, (l - 8 - tw, py(v) + 5), font, 0.45, ink2, 1, cv2.LINE_AA)
    for yy in range(t, H - b, 8):
        cv2.line(img, (px(OP_RATE), yy), (px(OP_RATE), yy + 4), ink2, 1)
    cv2.putText(img, title, (l, 24), font, 0.6, ink, 1, cv2.LINE_AA)
    cv2.putText(img, "impossible-template detections per live minute (log)", (l + 150, H - 15),
                font, 0.5, ink2, 1, cv2.LINE_AA)
    cv2.putText(img, ylabel, (l, t - 14), font, 0.5, ink2, 1, cv2.LINE_AA)
    marks = []
    for n, (F, c) in enumerate(curves.items()):
        col = _bgr(COLOURS.get(F, REFERENCE))
        o = np.argsort(c["impossible"])
        pts = np.array([[px(u), py(v)] for u, v in zip(c["impossible"][o], c[ykey][o])
                        if np.isfinite(u) and np.isfinite(v) and 0 < u <= xmax], np.int32)
        if len(pts) > 1:
            cv2.polylines(img, [pts], False, col, 2, cv2.LINE_AA)
        if ops and F in ops and ops[F] is not None:
            marks.append((py(ops[F][1]), px(ops[F][0]), F, col))
        cv2.line(img, (W - r + 30, t + 20 + 22 * n), (W - r + 60, t + 20 + 22 * n), col, 2)
        cv2.putText(img, F, (W - r + 66, t + 25 + 22 * n), font, 0.5, ink, 1, cv2.LINE_AA)
    last = None
    for y, x, F, col in sorted(marks):
        cv2.circle(img, (x, y), 6, _bgr("#fcfcfb"), -1, cv2.LINE_AA)
        cv2.circle(img, (x, y), 5, col, -1, cv2.LINE_AA)
    for y, x, F, col in sorted(marks):                 # above the dot, or below when crowded
        ly = y - 10
        if last is not None and ly < last + 16:
            ly = max(y + 22, last + 16)
        cv2.putText(img, F, (x + 10, ly), font, 0.5, ink, 1, cv2.LINE_AA)
        last = ly
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img)
    return out


# ---------------------------------------------------------------------------
# Commands: evaluate
# ---------------------------------------------------------------------------

def _latest() -> dict:
    from reticle import metrics, quoted
    idx = quoted.latest_pass(metrics.load(STORE / "notes" / "metrics.jsonl"))
    return {(series.split("/", 1)[1], s): row["values"] for (series, s), row in idx.items()
            if series.startswith("voice_lines/")}


def _deps(F: str) -> dict:
    from reticle import metrics
    return {"version": VERSION, "score": _score_fp(F), "evaluate": metrics.fingerprint(
        template_class, lineup_sides, own_x_casts, demo_x_casts, match_time, operating_tau,
        rates_at, best_near, summarise, round_unique, round_of, witnesses, suppress,
        cast_window, removals, window_offsets, gekko_table,
        OP_RATE=OP_RATE, OWN_WIN=OWN_WIN, P5_RATE=P5_RATE, SUPPRESS_S=SUPPRESS_S,
        CAST_WINDOW={k: list(v) for k, v in CAST_WINDOW.items()})}


def part(kind: str, F: str | None = None, *extra: str) -> str:
    """A recorded part name carrying the version: `evaluate-0.2.0-F-B`."""
    return "-".join([kind, TAG, *([F] if F else []), *extra])


def cmd_evaluate(formulations: list[str], sids: list[str], dry: bool) -> dict:
    """Per formulation, the templates without and with cross-template
    suppression, each at its own operating point: rates, own recall with the
    fixed and the per-agent cast window, timing, the round invariant, what
    suppression removes, witnesses, Gekko's lines and curves. Records the
    metrics unless dry; a subset of the matches is scored at the recorded
    all-matches thresholds."""
    from reticle import metrics
    full = set(sids) >= set(match_sessions())
    suffix = "" if full else "-subset"
    label = "all-matches" if full else _label(sids)
    ctxs, results, curves, ops = {}, {}, {}, {}
    latest = _latest()
    for F in formulations:
        ds0 = []
        for sid in sids:
            pk = load_peaks(F, sid)
            if pk is None:
                print(f"  {F} {sid}: no scores")
                continue
            if sid not in ctxs:
                ctxs[sid] = session_context(sid, int(pk["n_frames"]), [str(n) for n in pk["names"]])
            ds0.append(session_detections(F, ctxs[sid]))
        if not ds0:
            continue
        tau0 = tau1 = None
        if not full:
            tau0 = latest.get((part("evaluate", F, "unsuppressed"), "all-matches"), {}).get("tau_op")
            tau1 = latest.get((part("evaluate", F), "all-matches"), {}).get("tau_op")
            print(f"{F}: a subset of the matches, at the recorded all-matches thresholds "
                  f"{tau0} (unsuppressed) and {tau1}")
        ds1 = [apply_suppression(d, SUPPRESS_S) for d in ds0]
        s0 = summarise(F, ds0, ctxs, tau0)
        s1 = summarise(F, ds1, ctxs, tau1)
        tau0, tau1 = s0["tau"], s1["tau"]
        sup, sup_ctx = suppression_stats(F, ds0, ctxs, tau0, tau1, SUPPRESS_SWEEP if full else ())
        w = witnesses(F, ds1, ctxs, tau1)
        ag_tab = agent_table(F, ds1, ctxs, tau1)
        gk, gk_rows = gekko_table(ds1, ctxs, tau1)
        curves[F] = sweep(ds1, ctxs)
        ops[F] = s1["values"]
        if F == "F-B":
            curves["F-B unsuppressed"] = sweep(ds0, ctxs)
            ops["F-B unsuppressed"] = s0["values"]
        results[F] = {"unsuppressed": s0["values"], "values": s1["values"],
                      "per_session": s1["per_session"], "suppression": sup,
                      "suppression_rows": sup_ctx, "witness": w, "agents": ag_tab,
                      "gekko": gk, "gekko_rows": gk_rows}
        print(f"{F} unsuppressed: " + json.dumps(s0["values"]))
        print(f"{F} suppressed: " + json.dumps(s1["values"]))
        print(f"{F} suppression: " + json.dumps(sup))
        print(f"{F} gekko: " + json.dumps(gk))
        print(f"{F} witnesses: " + json.dumps(w))
        for sid, pv in s1["per_session"].items():
            print(f"  {sid}: " + json.dumps(pv))
        if dry:
            continue
        n_rows = write_detections(F, ds0, ds1, ctxs, tau1)
        deps = _deps(F)
        ctx_run = {"sessions": sorted(s1["per_session"]), "podcast": podcast_sessions(),
                   "window_s": SUPPRESS_S, "cast_window": {k: list(v) for k, v in CAST_WINDOW.items()}}
        metrics.record("voice_lines", part=part("evaluate", F, "unsuppressed") + suffix,
                       session=label, values=s0["values"], deps=deps, context=ctx_run)
        metrics.record("voice_lines", part=part("evaluate", F) + suffix, session=label,
                       values={**s1["values"], "detection_rows": n_rows}, deps=deps, context=ctx_run)
        for sid, pv in s1["per_session"].items():
            metrics.record("voice_lines", part=part("evaluate", F) + suffix, session=sid, values=pv,
                           deps=deps, context={"tau": tau1, "provenance": _jsonable(
                               ctxs[sid]["provenance"])})
        metrics.record("voice_lines", part=part("suppression", F) + suffix, session=label,
                       values=sup, deps=deps, context=_jsonable(sup_ctx))
        metrics.record("voice_lines", part=part("witness", F) + suffix, session=label, values=w,
                       deps=deps, context={"heard": [list(h) for h in HEARD]})
        metrics.record("voice_lines", part=part("agents", F) + suffix, session=label,
                       values=ag_tab, deps=deps)
        metrics.record("voice_lines", part=part("gekko", F) + suffix, session=label, values=gk,
                       deps=deps, context={"detections": gk_rows})
    if not dry and ctxs:
        REPORT.mkdir(parents=True, exist_ok=True)
        tag = "" if full else "_subset"
        if curves:
            pos = {k: {"impossible": c["impossible"], "y": c["possible"]} for k, c in curves.items()}
            plot_curves(pos, "y", "possible-template detections per live minute", None,
                        "Possible against impossible detections, 0.2.0, "
                        + ("19 match sessions with a lineup" if full else "subset"),
                        REPORT / f"curves_possible{tag}.png",
                        {k: (o["impossible_per_min"], o["possible_per_min"]) for k, o in ops.items()})
            rec = {k: {"impossible": c["impossible"], "y": c["recall_agent"]}
                   for k, c in curves.items() if k in FORMULATIONS}
            rops = {k: (o["impossible_per_min"], o["own_recall_agent_window"] or 0)
                    for k, o in ops.items() if k in FORMULATIONS}
            if "F-B unsuppressed" in curves:
                ref = "F-B unsuppressed, 1.5 s window"
                c0 = curves["F-B unsuppressed"]
                rec[ref] = {"impossible": c0["impossible"], "y": c0["recall"]}
                rops[ref] = (ops["F-B unsuppressed"]["impossible_per_min"],
                             ops["F-B unsuppressed"]["own_recall"] or 0)
            plot_curves(rec, "y", "own ult recall, each agent's cast window", 1.0,
                        "Own ult recall against impossible detections, 0.2.0",
                        REPORT / f"curves_own_recall{tag}.png", rops)
        (REPORT / f"evaluate{tag}.json").write_text(json.dumps(_jsonable(
            {"version": VERSION, "sessions": sids, "window_s": SUPPRESS_S, "results": results,
             "curves": {F: {k: [None if not np.isfinite(x) else round(float(x), 5) for x in a]
                            for k, a in c.items()} for F, c in curves.items()},
             "lineups": {sid: c["sides"] for sid, c in ctxs.items()},
             "players": {sid: [c["player"], c["player_why"]] for sid, c in ctxs.items()}}),
            indent=1), encoding="utf-8")
        if full:
            lin = [c for c in ctxs.values() if c["sides"] is not None and not c["demo"]]
            vals = {"match_sessions": sum(not c["demo"] for c in ctxs.values()),
                    "with_lineup": len(lin),
                    "board_applied": sum(bool(c["sides"]["board"].get("applied")) for c in lin),
                    "ally_named": sum(len(c["sides"]["ally"]["named"]) for c in lin),
                    "enemy_named": sum(len(c["sides"]["enemy"]["named"]) for c in lin),
                    "enemy_complete": sum(c["sides"]["enemy"]["complete"] for c in lin),
                    "player_known": sum(c["player"] is not None for c in ctxs.values()
                                        if not c["demo"]),
                    "templates": len(next(iter(ctxs.values()))["classes"]),
                    "templates_impossible_median": float(np.median(
                        [c["classes"].count("impossible") for c in lin])),
                    "templates_possible_median": float(np.median(
                        [c["classes"].count("possible") for c in lin]))}
            metrics.record("voice_lines", part=part("lineup"), session="all-matches", values=vals,
                           deps={"version": VERSION, "classes": metrics.fingerprint(
                               template_class, lineup_sides)})
            print("lineup: " + json.dumps(vals))
    return results


def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, np.ndarray):
        return _jsonable(x.tolist())
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    return x


# ---------------------------------------------------------------------------
# Review sheet
# ---------------------------------------------------------------------------

def spectrogram_png(sid: str, t: float, span: float, out: Path, before: float = 1.5,
                    after: float = 3.0, f: dict | None = None) -> Path:
    """The median-removed log-mel from `before` s ahead of t to `after` s past
    it, as `audio_gate.spectrogram_png` draws it, with the template's span
    marked: onset magenta, end cyan."""
    import cv2
    f = f or ag.load_features(sid)
    W = ag.median_removed(f, np)
    k0, k1 = int((t - before) / HOP), int((t + after) / HOP)
    seg = np.zeros((k1 - k0, BANDS), np.float32)
    a, b = max(k0, 0), min(k1, len(W))
    seg[a - k0:b - k0] = W[a:b]
    v = np.clip((seg + 6.0) / 36.0, 0, 1).T[::-1]
    img = cv2.applyColorMap((v * 255).astype(np.uint8), cv2.COLORMAP_MAGMA)
    img = cv2.resize(img, (seg.shape[0] * 2, BANDS * 3), interpolation=cv2.INTER_NEAREST)
    x = int(before / HOP) * 2
    cv2.line(img, (x, 0), (x, img.shape[0]), (255, 0, 255), 1)
    xe = int((before + span) / HOP) * 2
    if xe < img.shape[1]:
        cv2.line(img, (xe, 0), (xe, img.shape[0]), (255, 255, 0), 1)
    for k in range(0, seg.shape[0] + 1, 50):
        cv2.line(img, (k * 2, img.shape[0] - 8), (k * 2, img.shape[0]), (200, 200, 200), 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img)
    return out


def review_rows(F: str, sids: list[str], tau: float, seed: int = 0,
                window: float | None = SUPPRESS_S) -> list[dict]:
    """30 detections in the strata of STRATA, after cross-template suppression
    at `window`: own-class, possible ally, possible enemy and impossible at or
    above tau, drawn at random with a fixed seed, and the highest possible or
    own peaks just below tau."""
    rng = np.random.default_rng(seed)
    pool = {k: [] for k, _n in STRATA}
    names_len = {}
    for sid in sids:
        pk = load_peaks(F, sid)
        if pk is None:
            continue
        names = [str(n) for n in pk["names"]]
        ctx = session_context(sid, int(pk["n_frames"]), names)
        if ctx["demo"]:
            continue
        d = apply_suppression(session_detections(F, ctx), window)
        for j, n in enumerate(names):
            names_len[n] = int(pk["lengths"][j])
        for i in range(len(d["t"])):
            if not d["live"][i]:
                continue
            cl, var, sc = d["cls"][i], d["variant"][i], d["score"][i]
            row = {"session_id": sid, "t_s": round(float(d["t"][i]), 2),
                   "template": d["names"][d["j"][i]], "agent": str(d["agent"][i]),
                   "variant": str(var), "score": round(float(sc), 4), "class": str(cl),
                   "own_cast_dt_s": None if not np.isfinite(d["dt"][i]) else round(float(d["dt"][i]), 2),
                   "round": None, "capture": ctx["capture"], "_rounds": ctx["rounds"]}
            if sc >= tau:
                key = ("own" if cl == "own" else "possible_ally" if cl == "possible" and var == "ally"
                       else "possible_enemy" if cl == "possible" else
                       "impossible" if cl == "impossible" else None)
                if key:
                    pool[key].append(row)
            elif cl in ("own", "possible"):
                pool["borderline"].append(row)
    out = []
    for key, n in STRATA:
        rows = pool[key]
        if key == "borderline":
            pick = sorted(rows, key=lambda r: -r["score"])[:n]
        else:
            idx = rng.permutation(len(rows))[:n]
            pick = [rows[i] for i in sorted(idx)]
        for r in pick:
            r["stratum"] = key
            r["span_s"] = names_len.get(r["template"], 0) * HOP
            r["round"] = round_of(r["t_s"], r.pop("_rounds"))
            out.append(r)
    return out


def cmd_review(F: str, sids: list[str]) -> Path:
    """The review sheet: 30 stratified detections at the operating point."""
    from reticle import metrics
    tau = _latest().get((part("evaluate", F), "all-matches"), {}).get("tau_op")
    if tau is None:
        raise SystemExit(f"no recorded operating point for {F}; run evaluate first")
    rows = review_rows(F, sids, tau)
    files = {m["name"]: m["file"] for m in json.loads(
        (TEMPL / "templates.json").read_text(encoding="utf-8"))["templates"]}
    out = REVIEW
    out.mkdir(parents=True, exist_ok=True)
    feats = {}
    items = []
    for n, r in enumerate(rows):
        sid, t = r["session_id"], r["t_s"]
        if sid not in feats:
            feats.clear()
            feats[sid] = ag.load_features(sid)
        png = spectrogram_png(sid, t, r["span_s"], out / f"{n:03d}_{sid}_{t:.1f}.png", f=feats[sid])
        ss = max(0.0, round(t - 1.0, 1))
        mp3 = VOICE / files[r["template"]]
        items.append({**r, "rank": n + 1, "clock": f"{int(t // 60)}:{t % 60:04.1f}",
                      "png": png.name,
                      "play": f'ffplay -ss {ss} -t 5 -nodisp -autoexit "{r["capture"]}"',
                      "play_template": f'ffplay -nodisp -autoexit "{mp3}"'})
    (out / "sheet.json").write_text(json.dumps({"formulation": F, "tau": tau, "rows": items},
                                               indent=1), encoding="utf-8")
    trs = "\n".join(
        f"<tr><td>{it['rank']}</td><td>{it['stratum']}</td>"
        f"<td>{it['session_id']}<br><small>{html.escape(it['capture'])}</small></td>"
        f"<td>{it['t_s']:.1f} s<br>{it['clock']}<br>round {it['round']}</td>"
        f"<td><b>{html.escape(it['agent'])}</b>, {it['variant']} variant<br>score {it['score']}"
        f"<br>class {it['class']}"
        f"{'' if it['own_cast_dt_s'] is None else '<br>own X drop ' + format(-it['own_cast_dt_s'], '+.2f') + ' s from onset'}"
        f"</td><td><img src=\"{it['png']}\"></td>"
        f"<td><code>{html.escape(it['play'])}</code><br><small>the line itself:</small><br>"
        f"<code>{html.escape(it['play_template'])}</code></td><td></td></tr>"
        for it in items)
    (out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Ult voice lines</title>"
        "<style>body{font:14px sans-serif;background:#fcfcfb;color:#0b0b0b;margin:16px}"
        "td{border-bottom:1px solid #e6e5e0;padding:6px;vertical-align:top}"
        "code{font-size:12px;user-select:all}</style>"
        f"<h1>Ultimate voice lines {TAG}, {F}, operating threshold {tau}, "
        f"one template per onset within {SUPPRESS_S} s</h1>"
        "<p>Each row is a moment the named agent's ultimate line matched the match audio. "
        "The class says what the lineup allows: <b>own</b> is the player's agent's ally line, "
        "<b>possible</b> a named ally's ally line or a named enemy's enemy line, "
        "<b>impossible</b> a line no agent in this match can speak (a false alarm unless the "
        "lineup is wrong). <b>borderline</b> rows sit just below the threshold. The "
        "spectrogram runs 1.5 s before to 3 s after the onset (magenta); cyan marks the "
        "line's end. The first command plays 5 s of the capture from 1 s before the onset; "
        "the second plays the official line. Say whether you hear that agent's ult line, "
        "and which variant.</p><table><tr><th>#</th><th>stratum</th><th>session</th>"
        "<th>onset</th><th>template</th><th>spectrogram</th><th>listen</th>"
        f"<th>heard</th></tr>{trs}</table>", encoding="utf-8")
    metrics.record("voice_lines", part=part("review"), session="all-matches",
                   values={"rows": len(items), "formulation_tau": tau,
                           **{f"rows_{k}": sum(it["stratum"] == k for it in items)
                              for k, _n in STRATA},
                           "sessions": len({it["session_id"] for it in items})},
                   deps={"version": VERSION, "formulation": F, "window_s": SUPPRESS_S},
                   context={"sheet": str(out / "sheet.json")})
    print(f"{len(items)} rows -> {out / 'index.html'}")
    return out / "index.html"


# ---------------------------------------------------------------------------
# The doc's Results section
# ---------------------------------------------------------------------------

def tok(rows: dict, part: str, session: str, key: str) -> str:
    """The value as a citation of its recorded run, or a dash where none exists."""
    v = rows.get((part, session), {}).get(key)
    if v is None:
        return "-"
    return f"[metric:voice_lines/{part}@{session}#{key}={v}]"


#: The 0.2.0 section's closing list: what this version leaves undone.
NOT_DONE = (
    "No verdicts; the measured values stand beside P0 to P6 for the orchestrator.",
    "The suppression window was chosen on the same 19 sessions it is scored on; no session "
    "was held out. Suppression compares raw scores across templates; no template's scores "
    "are calibrated against its own null distribution.",
    "Only Phoenix has a cast window of its own; no other agent's window was fitted, and no "
    "stored tray cast was re-dated. The wider window's chance of a hit is reported, not "
    "subtracted.",
    "Gekko: one take of each variant; his recast lines and the other harvested cast lines "
    "are not matched, and no witness was matched to his detections, so they are counts "
    "against the lineup only.",
    "Suppression's own-line losses were counted, not examined: no removed detection was "
    "listened to, and no rule keeps an own line that a tray cast witnesses.",
    "The review sheet awaits the player; it shows F-B only.",
    "No events, labels or `reticle/` module. Nothing was written to the store's "
    "`notes/predictions.jsonl`, `events/` or `labels/`.",
    "No audio left a capture: F-B decoded each capture's audio stream in memory again to "
    "score Gekko's two lines; no video was decoded and no `roi_cache` was read.",
)


def cmd_report() -> None:
    """Rewrite the "Results 0.2.0" section of docs/VOICE_LINES.md from the
    recorded runs; everything before it, 0.1.0's results and verdicts, stays."""
    rows = _latest()
    Fs = [F for F in FORMULATIONS if (part("evaluate", F), "all-matches") in rows]
    if not Fs:
        raise SystemExit("no recorded 0.2.0 evaluation")
    T = lambda pt, session, key: tok(rows, pt, session, key)
    E = lambda F, key, sid="all-matches": T(part("evaluate", F), sid, key)
    U = lambda F, key: T(part("evaluate", F, "unsuppressed"), "all-matches", key)
    O = lambda F, key: T(f"evaluate-{F}", "all-matches", key)
    SP = lambda F, key: T(part("suppression", F), "all-matches", key)
    Wt = lambda F, key: T(part("witness", F), "all-matches", key)
    G = lambda F, key: T(part("gekko", F), "all-matches", key)
    TP = lambda key: T(part("templates"), "all", key)
    odd = rows.get((part("merge-check", "F-B"), "043bafca271a"), {}).get("differing_peak_max_score")
    tau_b = rows.get((part("evaluate", "F-B"), "all-matches"), {}).get("tau_op")
    merge_vs_tau = "" if odd is None or tau_b is None else (
        f", {'below' if odd < tau_b else 'at or above'} F-B's operating threshold "
        f"{E('F-B', 'tau_op')}")
    L = ["## Results 0.2.0\n"]
    L.append("Generated by `python prototypes/voice_lines.py report` from the runs recorded in "
             "the store's `notes/metrics.jsonl` under part names that carry `0.2.0`; the 0.1.0 "
             "columns cite 0.1.0's runs. Outputs sit under "
             "`<store>/analysis/voice-lines/0.2.0/`. Three changes, each measured at the same "
             "impossible rate as 0.1.0: at most 0.1 impossible detections per live minute.\n")
    L.append("### What changed\n")
    L.append(f"- **Gekko.** The 56 ult files lack him. His ultimate's two heard lines come from "
             f"the harvest index, the `Ally Cast` and `Enemy Cast` takes of Thrash "
             f"(`casts/Gekko__thrash__ally-cast__1.mp3`, `casts/Gekko__thrash__enemy-cast__1.mp3`); "
             f"the other agents' rows of those two sections are byte-identical to their ult files. "
             f"The templates span {TP('Gekko_ult_ally_span_s')} s and {TP('Gekko_ult_enemy_span_s')} s. "
             f"{TP('identical_to_0_1_0')} of the other 56 templates are identical to 0.1.0's, so "
             f"their stored peaks stand and only Gekko's two were scored, one session at a time: "
             f"F-B in {T(part('score', 'F-B'), 'all', 'wall_s')} s over "
             f"{T(part('score', 'F-B'), 'all', 'sessions')} sessions, decoding each capture's "
             f"audio again in memory. On `043bafca271a` a full rescoring of all "
             f"{T(part('lineup'), 'all-matches', 'templates')} templates gives the same peaks as "
             f"the merged file under F-A (same peaks "
             f"{T(part('merge-check', 'F-A'), '043bafca271a', 'same_peaks')}, where 1 is the same; "
             f"largest score difference "
             f"{T(part('merge-check', 'F-A'), '043bafca271a', 'max_score_diff')}). Under F-B it "
             f"does not (same peaks {T(part('merge-check', 'F-B'), '043bafca271a', 'same_peaks')}): "
             f"the merged Gekko peaks come from a shorter chunk step than a full rescoring uses, "
             f"and the FFT rounds differently. {T(part('merge-check', 'F-B'), '043bafca271a', 'templates_differing')} "
             f"templates differ, both Gekko's, with "
             f"{T(part('merge-check', 'F-B'), '043bafca271a', 'peaks_only_full')} peaks found only "
             f"by the full rescoring and "
             f"{T(part('merge-check', 'F-B'), '043bafca271a', 'peaks_only_stored')} only in the "
             f"merged file, of {T(part('merge-check', 'F-B'), '043bafca271a', 'peaks_stored')}; "
             f"the p99 floor moves by at most "
             f"{T(part('merge-check', 'F-B'), '043bafca271a', 'max_floor_diff')}, and the highest "
             f"of the differing peaks scores "
             f"{T(part('merge-check', 'F-B'), '043bafca271a', 'differing_peak_max_score')}"
             f"{merge_vs_tau}.")
    L.append(f"- **Cross-template suppression.** At one onset only the best-scoring template "
             f"stands: a stored peak falls when a higher standing peak of another template lies "
             f"within {SUPPRESS_S} s. Only higher peaks decide a peak's fate, so the rule is the "
             f"same above any threshold. The window comes from the offsets between an impossible "
             f"detection and the stronger own or possible detection it sits beside: at 0.2.0's "
             f"unsuppressed F-B operating point, {SP('F-B', 'offsets_n')} of "
             f"{SP('F-B', 'offsets_impossible_n')} impossible detections have one within 5 s; "
             f"{SP('F-B', 'offsets_0_to_0p3_s')} lie within 0.3 s, "
             f"{SP('F-B', 'offsets_0p3_to_0p6_s')} within 0.3 to 0.6 s, "
             f"{SP('F-B', 'offsets_0p6_to_1p2_s')} within 0.6 to 1.2 s, "
             f"{SP('F-B', 'offsets_1p2_to_2p5_s')} within 1.2 to 2.5 s and "
             f"{SP('F-B', 'offsets_2p5_to_5_s')} within 2.5 to 5 s (median "
             f"{SP('F-B', 'offsets_abs_median_s')} s, largest {SP('F-B', 'offsets_abs_max_s')} s). "
             f"{SUPPRESS_S} s is the smallest tenth of a second that holds all of them, with none "
             f"out to 5 s; the choice was made on 0.1.0's F-B detections, which lack only Gekko's "
             f"two lines. F-A and F-C have {SP('F-A', 'offsets_n')} and {SP('F-C', 'offsets_n')} "
             f"such offsets of {SP('F-A', 'offsets_impossible_n')} and "
             f"{SP('F-C', 'offsets_impossible_n')}; their false alarms are not cross-talk "
             f"(\"Detections by agent\" below).")
    L.append("- **A cast window per agent.** Own recall counts an own line with onset minus "
             "tray drop from -20 s to +1.5 s for Phoenix, whose Run it Back pips fall at expiry "
             "[domain:abilities/phoenix-run-it-back-expiry-flash] while the caster hears the "
             "line at the cast [domain:abilities/caster-hears-own-ult-line]; every other agent "
             "keeps -1.5 s to +1.5 s. No stored tray cast is re-dated. Both recalls are "
             "reported.\n")
    L.append("### Operating points, 0.1.0 against 0.2.0\n")
    L.append("Pooled over the match sessions with a lineup. \"0.2.0 unsuppressed\" adds only "
             "Gekko's two templates to 0.1.0; \"0.2.0\" adds suppression. Each column sits at "
             "its own operating threshold. 0.1.0 did not measure the per-agent window (-).\n")
    rows_def = (
        ("Threshold", "tau_op"), ("Impossible detections", "impossible_n"),
        ("Impossible per live min", "impossible_per_min"),
        ("Possible per live min", "possible_per_min"),
        ("Possible ally-variant per live min", "possible_ally_per_min"),
        ("Possible enemy-variant per live min", "possible_enemy_per_min"),
        ("Own-template per live min", "own_per_min"),
        ("Own recall, 1.5 s window", "own_recall"),
        ("Verified recall, 1.5 s window", "verified_recall"),
        ("Own recall, each agent's window", "own_recall_agent_window"),
        ("Verified recall, each agent's window", "verified_recall_agent_window"),
        ("Onset minus drop, median (s)", "onset_median_s"),
        ("Onset minus drop, IQR (s)", "onset_iqr_s"),
        ("Enemy to ally ratio, median session", "enemy_ally_ratio_median"),
        ("Detections alone for their line in their round", "round_unique_fraction"),
        ("... possible and own only", "round_unique_fraction_possible"),
        ("Impossible beside a higher possible or own detection", "impossible_beside_true_fraction"),
        ("Podcast to rest impossible ratio", "podcast_ratio"),
        ("... at the 1/min threshold", "podcast_ratio_at_p5"))
    for F in Fs:
        L.append(f"{F}:\n")
        L.append("| | 0.1.0 | 0.2.0 unsuppressed | 0.2.0 |")
        L.append("|---|---|---|---|")
        for label, key in rows_def:
            L.append(f"| {label} | {O(F, key)} | {U(F, key)} | {E(F, key)} |")
        L.append("")
    L.append("### What suppression removes\n")
    for F in Fs:
        L.append(f"- {F}, at the suppressed operating threshold {SP(F, 'tau_suppressed')}: from the "
                 f"unsuppressed live detections it removes {SP(F, 'removed_impossible')} impossible, "
                 f"{SP(F, 'removed_possible')} possible, {SP(F, 'removed_own')} own and "
                 f"{SP(F, 'removed_unknown')} unknown. Of the possible ones, "
                 f"{SP(F, 'removed_possible_by_true')} fell to a higher possible or own line, "
                 f"{SP(F, 'removed_possible_by_impossible')} to a higher impossible line and "
                 f"{SP(F, 'removed_possible_by_unknown')} to an unknown one; "
                 f"{SP(F, 'removed_possible_alone')} were the only detection of their agent and "
                 f"variant in their round, so each is a real loss if its line was spoken. Of the "
                 f"own ones, {SP(F, 'removed_own_by_true')} fell to a possible line, "
                 f"{SP(F, 'removed_own_by_impossible')} to an impossible one, "
                 f"{SP(F, 'removed_own_alone')} were alone in their round, and "
                 f"{SP(F, 'removed_own_at_cast')} lay in the cast window of one of the player's "
                 f"tray casts. At the same threshold the rule costs "
                 f"{SP(F, 'own_hits_lost')} of {SP(F, 'own_hits_unsuppressed')} cast hits with the "
                 f"1.5 s window and {SP(F, 'own_hits_agent_window_lost')} of "
                 f"{SP(F, 'own_hits_agent_window_unsuppressed')} with each agent's window.")
    L.append("")
    L.append("Other windows, each at its own operating threshold (losses as above):\n")
    for F in Fs:
        L.append(f"{F}:\n")
        L.append("| Window (s) | Threshold | Possible per live min | Own recall, 1.5 s | "
                 "Own recall, agent window | Alone in round | Impossible beside a true line | "
                 "Possible lost | Own lost | Cast hits lost, agent window |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for w in SUPPRESS_SWEEP:
            k = "w" + f"{w:g}".replace(".", "p")
            L.append(f"| {w:g} | {SP(F, k + '_tau_op')} | {SP(F, k + '_possible_per_min')} | "
                     f"{SP(F, k + '_own_recall')} | {SP(F, k + '_own_recall_agent_window')} | "
                     f"{SP(F, k + '_round_unique_fraction')} | "
                     f"{SP(F, k + '_impossible_beside_true_fraction')} | "
                     f"{SP(F, k + '_removed_possible_alone')} | {SP(F, k + '_removed_own_alone')} | "
                     f"{SP(F, k + '_own_hits_agent_window_lost')} |")
        L.append("")
    agents = sorted({k.rsplit("_", 1)[1] for F in Fs
                     for k in rows.get((part("evaluate", F), "all-matches"), {})
                     if k.startswith("own_recall_agent_window_")})
    L.append("### Own recall by the player's agent\n")
    L.append("At the 0.2.0 operating threshold: accepted X casts found with the 1.5 s window, "
             "then with each agent's window; verified casts in brackets.\n")
    L.append("| Agent | Casts (verified) | " + " | ".join(Fs) + " |")
    L.append("|---|---|" + "---|" * len(Fs))
    for a in agents:
        L.append(f"| {a} | {E(Fs[0], f'own_casts_{a}')} ({E(Fs[0], f'verified_casts_{a}')}) | "
                 + " | ".join(f"{E(F, f'own_recall_{a}')} to {E(F, f'own_recall_agent_window_{a}')} "
                              f"({E(F, f'verified_recall_{a}')} to "
                              f"{E(F, f'verified_recall_agent_window_{a}')})" for F in Fs) + " |")
    L.append("")
    for a in CAST_WINDOW:
        L.append(f"The chance that an own line at the {a} sessions' live rate lands in {a}'s "
                 f"{CAST_WINDOW[a][1] - CAST_WINDOW[a][0]:g} s window: "
                 + ", ".join(f"{F} {E(F, f'agent_window_chance_{a}')}" for F in Fs) + ".\n")
    L.append("### Gekko\n")
    for F in Fs:
        tab = rows.get((part("gekko", F), "all-matches"), {})
        L.append(f"- {F} at its 0.2.0 threshold, live detections: the ally line is possible on "
                 f"{G(F, 'ally_possible_sessions')} session, firing {G(F, 'ally_possible_n')} "
                 f"times, and impossible on {G(F, 'ally_impossible_sessions')}, firing "
                 f"{G(F, 'ally_impossible_n')} times; the enemy line is possible on "
                 f"{G(F, 'enemy_possible_sessions')} sessions, firing {G(F, 'enemy_possible_n')} "
                 f"times, and impossible on {G(F, 'enemy_impossible_sessions')}, firing "
                 f"{G(F, 'enemy_impossible_n')} times.")
        sess = sorted({k.split("_", 1)[0] for k in tab if k.endswith("_class")})
        for sid in sess:
            for w in VARIANTS:
                if f"{sid}_{w}_class" in tab:
                    top = (f"highest live peak {G(F, f'{sid}_{w}_max_score')}"
                           if tab.get(f"{sid}_{w}_max_score") is not None
                           else "no live peak above the template's p99 floor")
                    L.append(f"  - `{sid}`, {w} line: class {G(F, f'{sid}_{w}_class')}, "
                             f"{G(F, f'{sid}_{w}_n')} live detections, {top}.")
    L.append("")
    L.append("### Detections by agent\n")
    L.append("Live detections at each 0.2.0 threshold of the lines that fire as impossible, "
             "with the sessions where the line is impossible:\n")
    L.append("| Line | " + " | ".join(Fs) + " |")
    L.append("|---|" + "---|" * len(Fs))
    names = sorted({k.rsplit("_", 2)[0] for F in Fs
                    for k, v in rows.get((part("agents", F), "all-matches"), {}).items()
                    if k.endswith("_impossible_n") and v})
    for n in names:
        L.append(f"| {n} | " + " | ".join(
            f"{T(part('agents', F), 'all-matches', f'{n}_impossible_n')} "
            f"({T(part('agents', F), 'all-matches', f'{n}_impossible_sessions')})" for F in Fs) + " |")
    L.append("")
    F = "F-B" if "F-B" in Fs else Fs[0]
    L.append(f"### Per session, {F} 0.2.0\n")
    L.append("(podcast) marks the sessions the audio gate's speech cut named. Own X casts found: "
             "1.5 s window, then each agent's window.\n")
    L.append("| Session | Live min | Impossible/min | Impossible/min at 1/min threshold | "
             "Possible ally | Possible enemy | Own | Own X casts found | Enemy/ally | Alone in round |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    sids = sorted({sid for (pt, sid) in rows if pt == part("evaluate", F) and sid != "all-matches"},
                  key=lambda x: (-(rows[(part("evaluate", F), x)].get("podcast") or 0), x))
    for sid in sids:
        pod = " (podcast)" if rows[(part("evaluate", F), sid)].get("podcast") else ""
        L.append(f"| `{sid}`{pod} | {E(F, 'live_minutes', sid)} | {E(F, 'impossible_per_min', sid)} | "
                 f"{E(F, 'impossible_per_min_at_p5', sid)} | {E(F, 'possible_ally_n', sid)} | "
                 f"{E(F, 'possible_enemy_n', sid)} | {E(F, 'own_n', sid)} | "
                 f"{E(F, 'own_hits', sid)}, {E(F, 'own_hits_agent_window', sid)} of "
                 f"{E(F, 'own_casts', sid)} | {E(F, 'enemy_ally_ratio', sid)} | "
                 f"{E(F, 'round_unique_fraction', sid)} |")
    L.append("")
    L.append(f"### Witnesses, {F} 0.2.0\n")
    L.append(f"- The line the player heard on `043bafca271a` at 1870.1 s (Vyse): the enemy "
             f"variant scores {Wt(F, 'heard_043bafca271a_Vyse_enemy_score')}, onset "
             f"{Wt(F, 'heard_043bafca271a_Vyse_enemy_dt_s')} s from the heard time, detected "
             f"{Wt(F, 'heard_043bafca271a_Vyse_enemy_detected')} (1 is detected).")
    L.append(f"- Spectated X drops: {Wt(F, 'spectated_x_with_ally_line')} of "
             f"{Wt(F, 'spectated_x_drops')} have a possible ally-variant detection within 1.5 s "
             f"(chance {Wt(F, 'spectated_x_chance')}).")
    L.append(f"- Demos: {Wt(F, 'demo_x_hits')} of {Wt(F, 'demo_x_casts')} own X casts found; "
             f"other templates fire {Wt(F, 'demo_other_per_min')} times per capture minute.")
    L.append(f"- The lineup: on {Wt(F, 'board_disagreements')} slots the scoreboard overrode "
             f"the top bar; the board's agent's line fires {Wt(F, 'board_agent_lines')} times on "
             f"those sides and the top bar's {Wt(F, 'top_bar_agent_lines')}. Of "
             f"{Wt(F, 'impossible_live')} live impossible detections, "
             f"{Wt(F, 'impossible_top_bar_proposed')} name an agent the top bar proposed on that "
             f"side.")
    L.append("")
    L.append("### Outcomes at 0.2.0\n")
    L.append("The measured values beside each prediction, at the 0.2.0 operating point; no "
             "verdicts.\n")
    L.append("| Id | Prediction (abridged) | " + " | ".join(Fs) + " |")
    L.append("|---|---|" + "---|" * len(Fs))
    pred = (
        ("P0", "own ally line within 1.5 s of >= 0.8 of accepted X casts",
         lambda F: f"{E(F, 'own_recall')}; each agent's window {E(F, 'own_recall_agent_window')}"),
        ("P1", "possible detections 0.3 to 1.5 per live min",
         lambda F: f"{E(F, 'possible_per_min')}"),
        ("P2", "F-A matches or beats F-B on own recall",
         lambda F: f"{E(F, 'own_recall')} at {E(F, 'impossible_per_min')}/min"),
        ("P3", "enemy-variant >= half the ally-variant detections, median session",
         lambda F: f"{E(F, 'enemy_ally_ratio_median')} over {E(F, 'enemy_ally_sessions')} sessions"),
        ("P4", ">= 0.95 of detections alone for their line in their round",
         lambda F: f"{E(F, 'round_unique_fraction')} of {E(F, 'round_n')}"),
        ("P5", "podcast sessions >= 2x the impossible rate of the rest",
         lambda F: f"{E(F, 'podcast_ratio')}; {E(F, 'podcast_ratio_at_p5')} at 1/min"),
        ("P6", "own onset minus drop IQR <= 0.5 s",
         lambda F: f"{E(F, 'onset_iqr_s')}, n {E(F, 'onset_n')}"))
    for pid, text, cell in pred:
        L.append(f"| {pid} | {text} | " + " | ".join(cell(F) for F in Fs) + " |")
    L.append("")
    L.append("### Curves and review\n")
    L.append("- `<store>/analysis/voice-lines/0.2.0/report/curves_possible.png`: possible against "
             "impossible detections per live minute, each formulation with suppression, F-B "
             "without it in grey.")
    L.append("- `<store>/analysis/voice-lines/0.2.0/report/curves_own_recall.png`: own recall with "
             "each agent's window, and F-B without suppression with the 1.5 s window in grey.")
    L.append(f"- `<store>/analysis/voice-lines/0.2.0/review/index.html`: "
             f"{T(part('review'), 'all-matches', 'rows')} rows at the F-B 0.2.0 threshold "
             f"{T(part('review'), 'all-matches', 'formulation_tau')}, stratified as in 0.1.0.\n")
    L.append("### What was not done in 0.2.0\n")
    L.extend(f"- {x}" for x in NOT_DONE)
    L.append("")
    doc = DOC.read_text(encoding="utf-8")
    kept = [m for m in ("### Verdicts at 0.2.0", "## Production") if m in doc]
    if kept:
        raise SystemExit(f"docs/VOICE_LINES.md holds {kept} after the results this would "
                         f"rewrite; edit the section by hand")
    head = doc.split("## Results 0.2.0", 1)[0].rstrip() + "\n\n"
    DOC.write_text(head + "\n".join(L), encoding="utf-8", newline="\n")
    print(f"wrote {DOC}")


# ---------------------------------------------------------------------------
# Commands: heldout
# ---------------------------------------------------------------------------

#: The held-out run's recorded part.
HELDOUT_PART = "heldout-0.1.0"


def poisson_interval(k: int, level: float = 0.95) -> tuple[float, float]:
    """The exact (Garwood) interval of a Poisson mean given `k` counts."""
    a = (1.0 - level) / 2.0

    def cdf(n, mu):             # P(X <= n)
        term = total = math.exp(-mu)
        for i in range(1, n + 1):
            term *= mu / i
            total += term
        return total

    def solve(f, lo, hi):
        for _ in range(200):
            mid = (lo + hi) / 2.0
            lo, hi = (mid, hi) if f(mid) else (lo, mid)
        return (lo + hi) / 2.0

    top = 10.0 * k + 20.0
    lower = 0.0 if k == 0 else solve(lambda mu: 1.0 - cdf(k - 1, mu) < a, 0.0, top)
    upper = solve(lambda mu: cdf(k, mu) > a, 0.0, top)
    return lower, upper


def heldout_session(sid: str) -> dict | None:
    """What the held-out threshold needs of one match session, from storage:
    the live impossible scores, the live minutes, and per X cast inside a round
    the best own-class score within the player's agent's window. None for a
    session without a lineup."""
    from reticle import lineup
    from reticle.adjudication import ult_cast as uc
    from reticle.rounds import player_death_times
    from reticle.store import Store
    from reticle.version import TRAY_VERSION, ULT_LINE_VERSION
    store = Store(STORE)
    with contextlib.redirect_stdout(io.StringIO()):
        lu = lineup.load_lineup(sid, STORE)
    sides = uc.lineup_sides(lu, sid)
    if sides is None:
        return None
    player = uc.player_agent(lu, sid)
    rows = store.read_events("ult_line", sid)
    if not rows or rows[0].get("ult_line_version") != ULT_LINE_VERSION:
        raise SystemExit(f"{sid}: no current ult_line peaks; run `reticle ult-lines {sid}`")
    drops = store.read_events("tray_drop", sid)
    if not drops or drops[0].get("tray_version") != TRAY_VERSION:
        raise SystemExit(f"{sid}: no current tray drops; run `reticle tray {sid}`")
    peaks = [r for r in rows if r.get("kind") == "peak"]
    tm = match_time(sid, int(rows[0]["n_frames"]))
    gt, rr = tm["gametime"], tm["rounds"]
    casts = [c for c in uc.player_x_drops(drops, lambda t: gt.game_time_at(t).phase, rr,
                                          player_death_times(tm["hud"]))
             if c["player_cast"] and uc.round_of(c["t_ms"], rr) is not None]
    t = np.array([p["frame"] for p in peaks], np.float64) * HOP
    score = np.array([p["score"] for p in peaks], np.float64)
    cls = np.array([uc.template_class(norm_agent(p["agent"]), p["variant"], sides, player)[0]
                    for p in peaks], object)
    live = tm["live"][np.clip((t / STEP).astype(np.int64), 0, len(tm["live"]) - 1)]
    window = uc.cast_window(player)
    own_t, own_s = t[cls == "own"] * 1000.0, score[cls == "own"]
    best = np.array([max((s_ for o, s_ in zip(own_t, own_s)
                          if uc.in_window(o, float(c["t_ms"]), window)), default=-np.inf)
                     for c in casts], np.float64)
    return {"sid": sid, "player": player, "live_min": float(tm["live"].sum()) * STEP / 60.0,
            "imp": score[live & (cls == "impossible")], "best": best,
            "provenance": {"ult_line": rows[0].get("ult_line_version"),
                           "tray_drop": drops[0].get("tray_version"), **tm["provenance"],
                           "lineup": (lu or {}).get("version")}}


def heldout_tau(ss: list[dict]) -> float:
    """The operating point over `ss`: the lowest threshold with at most OP_RATE
    live impossible selections per live minute, pooled."""
    return operating_tau(np.concatenate([s["imp"] for s in ss]),
                         sum(s["live_min"] for s in ss))


def heldout_score(ss: list[dict], tau: float) -> dict:
    """Live impossible selections and own recall within each agent's window, at tau."""
    n_imp = int(sum(int((s["imp"] >= tau).sum()) for s in ss))
    live = sum(s["live_min"] for s in ss)
    best = np.concatenate([s["best"] for s in ss])
    lo, hi = poisson_interval(n_imp)
    return {"impossible_n": n_imp, "live_minutes": live, "impossible_per_min": n_imp / live,
            "impossible_per_min_lo": lo / live, "impossible_per_min_hi": hi / live,
            "casts": int(len(best)), "own_hits": int((best >= tau).sum()),
            "own_recall": float((best >= tau).mean()) if len(best) else float("nan")}


def cmd_heldout(dry: bool) -> dict:
    """The production threshold's operating point chosen on some lineup sessions
    and scored on the others: two alternating halves, both ways, and each
    session left out in turn. Stored data only; nothing is decoded."""
    from reticle import metrics
    from reticle.adjudication import ult_cast as uc
    from reticle.version import TRAY_VERSION, ULT_CAST_VERSION, ULT_LINE_VERSION
    ss = [x for x in (heldout_session(sid) for sid in sorted(match_sessions())) if x]
    by = {s["sid"]: s for s in ss}
    sids = sorted(by)
    half = {"a": [by[x] for x in sids[0::2]], "b": [by[x] for x in sids[1::2]]}
    other = {"a": "b", "b": "a"}
    v = {"sessions": len(ss), "live_minutes": _r(sum(s["live_min"] for s in ss), 1),
         "x_casts": int(sum(len(s["best"]) for s in ss)), "threshold": uc.THRESHOLD}

    tau = heldout_tau(ss)
    for name, at in (("pooled", tau), ("at_threshold", uc.THRESHOLD)):
        r = heldout_score(ss, at)
        key = (lambda k: f"pooled_{k}") if name == "pooled" else (lambda k: f"{k}_at_threshold")
        v.update({key("impossible_n"): r["impossible_n"],
                  key("impossible_per_min"): _r(r["impossible_per_min"], 4),
                  key("own_hits"): r["own_hits"], key("own_recall"): _r(r["own_recall"])})
    v["pooled_tau"] = round(tau, 6)

    # Two folds: choose on one half, score the other.
    for f in ("a", "b"):
        train, test = half[f], half[other[f]]
        t_f = heldout_tau(train)
        tr, te = heldout_score(train, t_f), heldout_score(test, t_f)
        v.update({f"tau_{f}": round(t_f, 6), f"sessions_{f}": len(train),
                  f"train_live_minutes_{f}": _r(tr["live_minutes"], 1),
                  f"train_impossible_n_{f}": tr["impossible_n"],
                  f"train_impossible_per_min_{f}": _r(tr["impossible_per_min"], 4),
                  f"train_own_recall_{f}": _r(tr["own_recall"]),
                  f"heldout_live_minutes_{f}": _r(te["live_minutes"], 1),
                  f"heldout_impossible_n_{f}": te["impossible_n"],
                  f"heldout_impossible_per_min_{f}": _r(te["impossible_per_min"], 4),
                  f"heldout_impossible_per_min_lo_{f}": _r(te["impossible_per_min_lo"], 4),
                  f"heldout_impossible_per_min_hi_{f}": _r(te["impossible_per_min_hi"], 4),
                  f"heldout_casts_{f}": te["casts"], f"heldout_own_hits_{f}": te["own_hits"],
                  f"heldout_own_recall_{f}": _r(te["own_recall"])})

    # Leave one session out.
    loo_tau, loo = [], []
    for s in ss:
        t_s = heldout_tau([x for x in ss if x is not s])
        r = heldout_score([s], t_s)
        loo_tau.append(t_s)
        loo.append(r)
        v[f"loo_tau_{s['sid']}"] = round(t_s, 6)
        v[f"loo_impossible_n_{s['sid']}"] = r["impossible_n"]
        v[f"loo_live_minutes_{s['sid']}"] = _r(r["live_minutes"], 1)
    n_imp = sum(r["impossible_n"] for r in loo)
    live = sum(r["live_minutes"] for r in loo)
    hits, casts = sum(r["own_hits"] for r in loo), sum(r["casts"] for r in loo)
    lo, hi = poisson_interval(n_imp)
    v.update({"loo_tau_min": round(min(loo_tau), 6),
              "loo_tau_median": round(float(np.median(loo_tau)), 6),
              "loo_tau_max": round(max(loo_tau), 6),
              "loo_tau_max_shift": round(max(abs(x - uc.THRESHOLD) for x in loo_tau), 6),
              "loo_impossible_n": n_imp, "loo_impossible_per_min": _r(n_imp / live, 4),
              "loo_impossible_per_min_lo": _r(lo / live, 4),
              "loo_impossible_per_min_hi": _r(hi / live, 4),
              "loo_own_hits": hits, "loo_own_recall": _r(hits / casts) if casts else None,
              "loo_sessions_over_rate": sum(r["impossible_per_min"] > OP_RATE for r in loo)})
    print(json.dumps(v, indent=1))
    if not dry:
        metrics.record("voice_lines", part=HELDOUT_PART, session="all-matches", values=v,
                       deps={"version": VERSION, "ult_line_version": ULT_LINE_VERSION,
                             "tray_version": TRAY_VERSION, "ult_cast_version": ULT_CAST_VERSION,
                             "heldout": metrics.fingerprint(
                                 heldout_session, heldout_tau, heldout_score, operating_tau,
                                 poisson_interval, match_time, OP_RATE=OP_RATE,
                                 CAST_WINDOW={k: list(w) for k, w in CAST_WINDOW.items()})},
                       context={"fold_a": sids[0::2], "fold_b": sids[1::2],
                                "folds": "sorted session ids alternated; tau_a is chosen on "
                                         "fold_a and scored on fold_b, tau_b the reverse",
                                "provenance": {s["sid"]: s["provenance"] for s in ss}})
        print(f"recorded voice_lines/{HELDOUT_PART}@all-matches")
    return v


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("templates")
    sc = sub.add_parser("score")
    sc.add_argument("--formulation", required=True, choices=FORMULATIONS)
    sc.add_argument("--sessions", nargs="*")
    sc.add_argument("--templates", nargs="*",
                    help="score only these; every other template's peaks come from 0.1.0")
    ev = sub.add_parser("evaluate")
    ev.add_argument("--formulations", nargs="*", choices=FORMULATIONS)
    ev.add_argument("--sessions", nargs="*")
    ev.add_argument("--dry", action="store_true", help="print only; record and write nothing")
    mc = sub.add_parser("check-merge")
    mc.add_argument("--formulation", required=True, choices=FORMULATIONS)
    mc.add_argument("--session", required=True)
    rv = sub.add_parser("review")
    rv.add_argument("--formulation", choices=FORMULATIONS)
    rv.add_argument("--sessions", nargs="*")
    sub.add_parser("report")
    pc = sub.add_parser("port-check")
    pc.add_argument("--sessions", nargs="+", required=True)
    pc.add_argument("--pooled", action="store_true",
                    help="record one run over all the sessions, not one per session")
    ho = sub.add_parser("heldout")
    ho.add_argument("--dry", action="store_true", help="print only; record nothing")
    a = ap.parse_args(argv)
    print(f"{VERSION}: {os.environ['OMP_NUM_THREADS']} BLAS threads, Below Normal priority")
    every = match_sessions() + demo_sessions()
    if a.cmd == "templates":
        cmd_templates()
    elif a.cmd == "score":
        cmd_score(a.formulation, a.sessions or every, a.templates)
    elif a.cmd == "check-merge":
        cmd_check_merge(a.formulation, a.session)
    elif a.cmd == "evaluate":
        have = [F for F in FORMULATIONS if (SCORES / F).is_dir()]
        cmd_evaluate(a.formulations or have, a.sessions or every, a.dry)
    elif a.cmd == "review":
        F = a.formulation
        if F is None:
            rows = _latest()
            got = [(rows[(part("evaluate", x), "all-matches")].get("own_recall_agent_window") or 0, x)
                   for x in FORMULATIONS if (part("evaluate", x), "all-matches") in rows]
            if not got:
                raise SystemExit("no recorded evaluation; run evaluate first")
            F = max(got)[1]
        cmd_review(F, a.sessions or match_sessions())
    elif a.cmd == "report":
        cmd_report()
    elif a.cmd == "port-check":
        cmd_port_check(a.sessions, a.pooled)
    elif a.cmd == "heldout":
        cmd_heldout(a.dry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
