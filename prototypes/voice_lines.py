r"""Match the official ultimate voice lines against the match audio: whose ult, on which side?

    .\.venv\Scripts\python.exe prototypes\voice_lines.py templates
    .\.venv\Scripts\python.exe prototypes\voice_lines.py score --formulation F-A|F-B|F-C [--sessions SID ...]
    .\.venv\Scripts\python.exe prototypes\voice_lines.py evaluate [--formulations F ...] [--sessions SID ...] [--dry]
    .\.venv\Scripts\python.exe prototypes\voice_lines.py review [--formulation F]
    .\.venv\Scripts\python.exe prototypes\voice_lines.py report

Purpose
-------
The game announces an ultimate cast with a fixed voice line, one for the
caster's allies and one for the caster's enemies
[domain:abilities/voice-lines-announce-casts]. The store holds the official
lines, `reference/assets/voicelines/<Agent>_ult_{ally,enemy}.mp3`. Which
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
`review` writes a sheet of 30 stratified detections with a spectrogram and an
`ffplay` command into the source capture; `report` rewrites the Results
section of `docs/VOICE_LINES.md` from the recorded runs.

What it does not do
-------------------
It emits no events, writes nothing under `events/` or `labels/`, and `reticle/`
does not import it. It decodes no video and writes no audio: F-B holds the
decoded stream in memory only, and the review sheet plays the source capture.
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

STORE = ag.STORE
VERSION = "voice-lines-0.1.0"
OUT = STORE / "analysis" / "voice-lines" / VERSION.rsplit("-", 1)[1]
TEMPL, SCORES, DETS = OUT / "templates", OUT / "scores", OUT / "detections"
REPORT, REVIEW = OUT / "report", OUT / "review"
VOICE = STORE / "reference" / "assets" / "voicelines"
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
#: A detection is an own cast's when within this of the tray drop, seconds.
OWN_WIN = 1.5
#: How far before an own X drop the lead witness looks for the own line (s).
LEAD_WIN = 20.0
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

def template_files() -> list[Path]:
    return sorted(VOICE.glob("*_ult_*.mp3"))


def parse_name(path: Path) -> tuple[str, str]:
    """(agent, variant) from `<Agent>_ult_<variant>.mp3`; KAY/O is spelled KAY_O."""
    stem = path.stem
    agent, variant = stem.rsplit("_ult_", 1)
    if variant not in VARIANTS:
        raise SystemExit(f"{path.name}: unknown variant {variant!r}")
    return agent, variant


def decode_template(path: Path) -> np.ndarray:
    """The mp3 as 48 kHz mono float32, resampled by libswresample where needed."""
    import av
    xs = []
    with av.open(str(path)) as c:
        st = c.streams.audio[0]
        rs = av.AudioResampler(format="flt", layout="mono", rate=RATE)
        for fr in c.decode(st):
            for o in rs.resample(fr):
                xs.append(o.to_ndarray().reshape(-1))
        for o in rs.resample(None):
            xs.append(o.to_ndarray().reshape(-1))
    return np.concatenate(xs).astype(np.float32)


def trim_floor(L: np.ndarray, ok: np.ndarray, active_db: float = ACTIVE_DB,
               floor_db: float = FLOOR_DB) -> tuple[np.ndarray, int, int]:
    """(floored log-mel of the active span, first frame, last frame + 1).

    Frames whose window reaches outside the clip leave; the span runs from the
    first to the last frame within `active_db` of the loudest frame's power;
    values below the span's maximum less `floor_db` rise to that floor.
    """
    idx = np.flatnonzero(ok)
    if len(idx) == 0:
        raise ValueError("no frame lies inside the clip")
    power = 10 * np.log10(np.sum(10 ** (L[idx].astype(np.float64) / 10), axis=1) + 1e-12)
    act = idx[power >= power.max() - active_db]
    k0, k1 = int(act[0]), int(act[-1]) + 1
    T = L[k0:k1].astype(np.float32)
    return np.maximum(T, T.max() - floor_db), k0, k1


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
    """Decode the 56 lines, store their log-mel and metadata, record the set."""
    TEMPL.mkdir(parents=True, exist_ok=True)
    meta = []
    for p in template_files():
        agent, variant = parse_name(p)
        x = decode_template(p)
        L, ok, _rms = ag.logmel(x, np.ones(len(x), bool), RATE)
        T, k0, k1 = trim_floor(L, ok)
        rate, ch = source_format(p)
        rec = {"name": p.stem, "agent": agent, "variant": variant, "file": p.name,
               "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
               "source_rate": rate, "source_channels": ch, "resampled": rate != RATE or ch != 1,
               "n_samples": len(x), "duration_s": round(len(x) / RATE, 3),
               "k0": k0, "k1": k1, "frames": k1 - k0,
               "onset_s": round(k0 * HOP, 3), "span_s": round((k1 - k0) * HOP, 3)}
        np.savez_compressed(TEMPL / f"{p.stem}.npz", L=T, raw=L[k0:k1].astype(np.float32),
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
            "span_max_s": max(m["span_s"] for m in meta)}
    from reticle import metrics
    metrics.record("voice_lines", part="templates", session="all", values=vals,
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


def phat_tracks(x: np.ndarray, waves: list[np.ndarray], rate: int = RATE,
                chunk: int = CHUNK, band=PHAT_BAND, hop_n: int = HOP_N, xp=None,
                batch: int = PHAT_BATCH) -> np.ndarray:
    """[templates, frames] GCC-PHAT of each template waveform against x: the
    largest lag score in each hop, a perfect match reading 1.

    Chunks of `chunk` samples step by `chunk` less the longest template
    (rounded up to a hop), so every lag of every template sees its full
    window in one chunk. Frame k holds lags [k * hop_n, (k + 1) * hop_n).
    """
    xp = xp or gpu()
    J = len(waves)
    mmax = int(math.ceil(max(len(w) for w in waves) / hop_n)) * hop_n
    step = (chunk - mmax) // hop_n * hop_n
    if step <= 0:
        raise ValueError("chunk shorter than the longest template")
    nf = chunk // 2 + 1
    f = np.arange(nf) * rate / chunk
    mask = xp.asarray(((f >= band[0]) & (f <= band[1])).astype(np.float32))
    K = float(_np(mask).sum())
    scale = chunk / (2.0 * K)
    Y = xp.stack([xp.conj(xp.fft.rfft(xp.asarray(w, xp.float32), n=chunk)) for w in waves])
    n_frames = len(x) // hop_n
    out = np.full((J, n_frames), -1.0, np.float32)
    for c0 in range(0, n_frames * hop_n, step):
        seg = np.zeros(chunk, np.float32)
        s = x[c0:c0 + chunk]
        seg[:len(s)] = s
        X = xp.fft.rfft(xp.asarray(seg))
        f0 = c0 // hop_n
        f1 = min(n_frames, f0 + step // hop_n)
        nfr = f1 - f0
        for j0 in range(0, J, batch):
            G = X[None, :] * Y[j0:j0 + batch]
            G = G / (xp.abs(G) + 1e-20) * mask[None, :]
            r = xp.fft.irfft(G, n=chunk, axis=1)[:, :nfr * hop_n] * scale
            out[j0:j0 + batch, f0:f1] = _np(r.reshape(r.shape[0], nfr, hop_n).max(axis=2))
            del G, r
    return out


def nms_peaks(s: np.ndarray, m: int, floor: float) -> np.ndarray:
    """Frames of the local maxima of s at or above floor, greedy by score, none
    within m frames of a higher kept peak; sorted by frame."""
    s = np.asarray(s, np.float32)
    if len(s) == 0:
        return np.zeros(0, np.int64)
    left = np.r_[-np.inf, s[:-1]]
    right = np.r_[s[1:], -np.inf]
    cand = np.flatnonzero((s >= floor) & (s >= left) & (s > right))
    order = cand[np.argsort(-s[cand], kind="stable")]
    taken = np.zeros(len(s), bool)
    keep = []
    for k in order:
        if not taken[k]:
            keep.append(k)
            taken[max(0, k - m + 1):k + m] = True
    return np.sort(np.asarray(keep, np.int64))


def track_peaks(tracks: np.ndarray, lengths: list[int], q: float = FLOOR_Q) -> dict:
    """Peaks of every template's track: arrays of template index, frame and
    score, and per template its floor, median and maximum."""
    tpl, frm, sc = [], [], []
    floors, med, mx = [], [], []
    for j, s in enumerate(tracks):
        v = s[s > -1.0]
        fl = float(np.quantile(v, q)) if len(v) else 1.0
        pk = nms_peaks(s, lengths[j], fl)
        tpl.append(np.full(len(pk), j, np.int16))
        frm.append(pk.astype(np.int32))
        sc.append(s[pk].astype(np.float32))
        floors.append(fl)
        med.append(float(np.median(v)) if len(v) else np.nan)
        mx.append(float(v.max()) if len(v) else np.nan)
    return {"tpl": np.concatenate(tpl), "frame": np.concatenate(frm),
            "score": np.concatenate(sc), "floor": np.asarray(floors, np.float32),
            "median": np.asarray(med, np.float32), "max": np.asarray(mx, np.float32)}


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


def cmd_score(F: str, sids: list[str]) -> None:
    """Score every template on each session in turn; store the peaks."""
    from reticle import metrics
    temps = load_line_templates(F)
    lengths = [len(t["T"]) for t in temps]
    (SCORES / F).mkdir(parents=True, exist_ok=True)
    waves = None
    if F == "F-B":
        waves = []
        for t in temps:
            y = decode_template(VOICE / t["file"])
            waves.append(y[t["k0"] * HOP_N:t["k1"] * HOP_N])
    t_all = time.time()
    n_peaks = 0
    walls = {}
    for sid in sids:
        t0 = time.time()
        f = session_features(sid)
        n = len(f["L"])
        info = {"n_frames": n}
        if F == "F-B":
            td = time.time()
            x, filled, rate = ag.decode_mono(_manifest(sid)["source"]["path"])
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
        pk = track_peaks(tracks, lengths)
        del tracks
        _free_gpu()
        n_peaks += len(pk["score"])
        walls[sid] = round(time.time() - t0, 1)
        info["wall_s"] = walls[sid]
        np.savez_compressed(score_path(F, sid), **pk, names=np.array([t["name"] for t in temps]),
                            lengths=np.asarray(lengths, np.int32), hop_s=HOP, n_frames=n,
                            floor_q=FLOOR_Q, formulation=F, version=VERSION,
                            content_key=str(f["content_key"]), info=json.dumps(info))
        print(f"  {F} {sid}: {len(pk['score'])} peaks, {info}")
    metrics.record("voice_lines", part=f"score-{F}", session=_label(sids),
                   values={"sessions": len(sids), "peaks": n_peaks,
                           "wall_s": round(time.time() - t_all, 1),
                           "wall_s_max": max(walls.values()) if walls else None},
                   deps={"version": VERSION, "score": _score_fp(F)},
                   context={"walls": walls, "threads": os.environ.get("OMP_NUM_THREADS")})


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
    return {"live": live, "stalled": stalled, "rounds": rrows,
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


def best_near(d: dict, casts: list[dict], cls: str = "own") -> tuple[np.ndarray, np.ndarray]:
    """Per cast, the highest score of a `cls` detection within OWN_WIN and its
    onset minus the drop (-inf and NaN where none)."""
    best = np.full(len(casts), -np.inf)
    lag = np.full(len(casts), np.nan)
    m = d["cls"] == cls
    for i, c in enumerate(casts):
        w = m & (np.abs(d["t"] - c["t"]) <= OWN_WIN)
        if w.any():
            k = np.flatnonzero(w)[np.argmax(d["score"][w])]
            best[i], lag[i] = d["score"][k], d["t"][k] - c["t"]
    return best, lag


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
    casts = [(d, [c for c in ctxs[d["sid"]]["own"]]) for d in ds
             if ctxs[d["sid"]]["player"] is not None and not ctxs[d["sid"]]["demo"]]
    best = np.concatenate([best_near(d, cs)[0] for d, cs in casts]) if casts else np.zeros(0)
    out = {k: [] for k in ("tau", "impossible", "possible", "own", "recall")}
    for tau in taus:
        r = rates_at(live, ctxs, tau)
        out["tau"].append(float(tau))
        out["impossible"].append(r["impossible_per_min"])
        out["possible"].append(r["possible_per_min"])
        out["own"].append(r["own_per_min"])
        out["recall"].append(float((best >= tau).mean()) if len(best) else float("nan"))
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


def write_detections(F: str, ds: list[dict], ctxs: dict, tau: float) -> int:
    """detections/<sid>.jsonl: one row per peak at or above tau; rows of the
    other formulations already there stay."""
    DETS.mkdir(parents=True, exist_ok=True)
    total = 0
    for d in ds:
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
                   "live": bool(d["live"][i]), "round": round_of(t, c["rounds"])}
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


def _bgr(h: str) -> tuple[int, int, int]:
    return int(h[5:7], 16), int(h[3:5], 16), int(h[1:3], 16)


def plot_curves(curves: dict, ykey: str, ylabel: str, ymax: float | None, title: str, out: Path,
                ops: dict | None = None, xmax: float = 10.0) -> Path:
    """y against impossible detections per live minute (log x, 0.003 to
    `xmax`), one line per formulation, direct labels, the operating rate
    dashed. `ymax` None scales y to the curves within the x range."""
    import cv2
    W, H, l, r, t, b = 960, 600, 80, 150, 64, 60
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
        col = _bgr(COLOURS.get(F, "#52514e"))
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
        rates_at, best_near, summarise, round_unique, round_of, witnesses,
        OP_RATE=OP_RATE, OWN_WIN=OWN_WIN, P5_RATE=P5_RATE)}


def cmd_evaluate(formulations: list[str], sids: list[str], dry: bool) -> dict:
    """Operating points, rates, recall, timing, round invariant, witnesses and
    curves per formulation; records the metrics unless dry."""
    from reticle import metrics
    full = set(sids) >= set(match_sessions())
    ctxs, results, curves, ops = {}, {}, {}, {}
    latest = _latest()
    for F in formulations:
        ds = []
        for sid in sids:
            pk = load_peaks(F, sid)
            if pk is None:
                print(f"  {F} {sid}: no scores")
                continue
            if sid not in ctxs:
                names = [str(n) for n in pk["names"]]
                ctxs[sid] = session_context(sid, int(pk["n_frames"]), names)
            ds.append(session_detections(F, ctxs[sid]))
        if not ds:
            continue
        tau = None
        if not full:
            tau = latest.get((f"evaluate-{F}", "all-matches"), {}).get("tau_op")
            print(f"{F}: a subset of the matches, evaluated at the recorded all-matches "
                  f"threshold {tau}" if tau is not None else
                  f"{F}: a subset, no recorded threshold; computing one")
        s = summarise(F, ds, ctxs, tau)
        tau = s["tau"]
        w = witnesses(F, ds, ctxs, tau)
        ag_tab = agent_table(F, ds, ctxs, tau)
        c = sweep(ds, ctxs)
        curves[F] = c
        ops[F] = (s["values"]["impossible_per_min"], s["values"]["possible_per_min"])
        results[F] = {"values": s["values"], "per_session": s["per_session"], "witness": w,
                      "agents": ag_tab}
        print(f"{F}: " + json.dumps(s["values"]))
        print(f"{F} witnesses: " + json.dumps(w))
        for sid, pv in s["per_session"].items():
            print(f"  {sid}: " + json.dumps(pv))
        if dry:
            continue
        n_rows = write_detections(F, ds, ctxs, tau)
        suffix = "" if full else "-subset"
        label = "all-matches" if full else _label(sids)
        deps = _deps(F)
        metrics.record("voice_lines", part=f"evaluate-{F}{suffix}", session=label,
                       values={**s["values"], "detection_rows": n_rows}, deps=deps,
                       context={"sessions": sorted(s["per_session"]),
                                "podcast": podcast_sessions()})
        for sid, pv in s["per_session"].items():
            metrics.record("voice_lines", part=f"evaluate-{F}{suffix}", session=sid, values=pv,
                           deps=deps, context={"tau": tau, "provenance": _jsonable(
                               ctxs[sid]["provenance"])})
        metrics.record("voice_lines", part=f"witness-{F}{suffix}", session=label, values=w,
                       deps=deps, context={"heard": [list(h) for h in HEARD]})
        metrics.record("voice_lines", part=f"agents-{F}{suffix}", session=label, values=ag_tab,
                       deps=deps)
    if not dry and ctxs:
        REPORT.mkdir(parents=True, exist_ok=True)
        tag = "" if full else "_subset"
        if curves:
            plot_curves(curves, "possible", "possible-template detections per live minute",
                        None,
                        "Possible against impossible detections, 19 match sessions with a lineup"
                        if full else "Possible against impossible detections, subset",
                        REPORT / f"curves_possible{tag}.png", ops)
            plot_curves(curves, "recall", "own ult recall (accepted X casts)", 1.0,
                        "Own ult recall against impossible detections",
                        REPORT / f"curves_own_recall{tag}.png",
                        {F: (results[F]["values"]["impossible_per_min"],
                             results[F]["values"]["own_recall"] or 0) for F in results})
        (REPORT / f"evaluate{tag}.json").write_text(json.dumps(
            {"version": VERSION, "sessions": sids, "results": results,
             "curves": {F: {k: [None if not np.isfinite(x) else round(float(x), 5) for x in a]
                            for k, a in c.items()} for F, c in curves.items()},
             "lineups": {sid: _jsonable(c["sides"]) for sid, c in ctxs.items()},
             "players": {sid: [c["player"], c["player_why"]] for sid, c in ctxs.items()}},
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
                    "templates_impossible_median": float(np.median(
                        [c["classes"].count("impossible") for c in lin])),
                    "templates_possible_median": float(np.median(
                        [c["classes"].count("possible") for c in lin]))}
            metrics.record("voice_lines", part="lineup", session="all-matches", values=vals,
                           deps={"version": VERSION, "classes": metrics.fingerprint(
                               template_class, lineup_sides)})
            print("lineup: " + json.dumps(vals))
    return results


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
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


def review_rows(F: str, sids: list[str], tau: float, seed: int = 0) -> list[dict]:
    """30 detections in the strata of STRATA: own-class, possible ally,
    possible enemy and impossible at or above tau, drawn at random with a fixed
    seed, and the highest possible or own peaks just below tau."""
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
        d = session_detections(F, ctx)
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
    tau = _latest().get((f"evaluate-{F}", "all-matches"), {}).get("tau_op")
    if tau is None:
        raise SystemExit(f"no recorded operating point for {F}; run evaluate first")
    rows = review_rows(F, sids, tau)
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
        mp3 = VOICE / f"{r['template']}.mp3"
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
        f"<h1>Ultimate voice lines, {F}, operating threshold {tau}</h1>"
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
    metrics.record("voice_lines", part="review", session="all-matches",
                   values={"rows": len(items), "formulation_tau": tau,
                           **{f"rows_{k}": sum(it["stratum"] == k for it in items)
                              for k, _n in STRATA},
                           "sessions": len({it["session_id"] for it in items})},
                   deps={"version": VERSION, "formulation": F},
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


#: The Results section's closing list: what this prototype leaves undone.
NOT_DONE = (
    "No events, labels or `reticle/` module: a matched line is not yet an "
    "identity claim, and nothing is wired until the player has judged the review sheet.",
    "No verdict on P0 to P6; the measured values stand beside them for the orchestrator.",
    "One pooled threshold per formulation; no threshold per template, per session or per "
    "agent, and no calibration of each template's own null distribution.",
    "Only the 56 ultimate lines; the ability and callout lines "
    "[domain:abilities/voice-lines-announce-casts] and Gekko's ult line (no asset) are "
    "not matched.",
    "No cross-template suppression: two templates may both fire on one line, and the "
    "impossible rate counts such cross-talk as false alarms.",
    "The review sheet awaits the player; no row of it is judged here. It shows the "
    "formulation with the highest own recall only.",
    "Own recall keeps the fixed 1.5 s window for every agent. Phoenix's X drops trail "
    "the own line by seconds (Witnesses); no recall with a window per agent is reported "
    "as an operating result, and nothing here re-dates a Phoenix cast.",
    "The own line is tested on four of the player's agents only: Clove has one own X "
    "cast on the matches and none on its demo (`0c6c52a65b9e`).",
    "No audio left a capture: no WAV and no clips. F-B decoded each capture's audio "
    "stream in memory with PyAV; no video was decoded and no `roi_cache` was read.",
    "Nothing was written to the store's `notes/predictions.jsonl`, `events/` or `labels/`.",
    "The tests run under `unittest`; the venv has no pytest.",
)


def cmd_report() -> None:
    """Rewrite the Results section of docs/VOICE_LINES.md from the recorded runs."""
    rows = _latest()
    Fs = [F for F in FORMULATIONS if (f"evaluate-{F}", "all-matches") in rows]
    T = lambda part, session, key: tok(rows, part, session, key)
    E = lambda F, key, s="all-matches": T(f"evaluate-{F}", s, key)
    Wt = lambda F, key: T(f"witness-{F}", "all-matches", key)
    L = []
    L.append("## Results\n")
    L.append("Generated by `python prototypes/voice_lines.py report` from the runs recorded in "
             "the store's `notes/metrics.jsonl` (`voice-lines-0.1.0`); every figure cites its "
             "run. Outputs sit under `<store>/analysis/voice-lines/0.1.0/`.\n")
    L.append("### What ran\n")
    L.append(f"- Templates: {T('templates', 'all', 'templates')} lines of "
             f"{T('templates', 'all', 'agents')} agents, {T('templates', 'all', 'resampled')} "
             f"resampled to 48 kHz mono; kept spans {T('templates', 'all', 'span_min_s')} s to "
             f"{T('templates', 'all', 'span_max_s')} s ({T('templates', 'all', 'frames_min')} to "
             f"{T('templates', 'all', 'frames_max')} frames).")
    L.append(f"- Lineups: {T('lineup', 'all-matches', 'with_lineup')} of "
             f"{T('lineup', 'all-matches', 'match_sessions')} match sessions have one, the "
             f"scoreboard constraint applied on {T('lineup', 'all-matches', 'board_applied')}; "
             f"the arbiter names {T('lineup', 'all-matches', 'ally_named')} ally and "
             f"{T('lineup', 'all-matches', 'enemy_named')} enemy slots, and the enemy side is "
             f"complete on {T('lineup', 'all-matches', 'enemy_complete')}. A session classes a "
             f"median of {T('lineup', 'all-matches', 'templates_impossible_median')} templates "
             f"impossible and {T('lineup', 'all-matches', 'templates_possible_median')} possible. "
             f"The player's agent is known on {T('lineup', 'all-matches', 'player_known')} matches.")
    for F in Fs:
        L.append(f"- {F}: {T(f'score-{F}', 'all', 'sessions')} sessions scored in "
                 f"{T(f'score-{F}', 'all', 'wall_s')} s (slowest session "
                 f"{T(f'score-{F}', 'all', 'wall_s_max')} s), "
                 f"{T(f'score-{F}', 'all', 'peaks')} peaks kept.")
    L.append("")
    L.append("### Operating points\n")
    L.append(f"Pooled over the {E(Fs[0], 'sessions') if Fs else '-'} match sessions with a "
             f"lineup, {E(Fs[0], 'live_minutes') if Fs else '-'} live minutes. The threshold "
             "is the lowest at which impossible templates fire at most 0.1 times per live "
             "minute. \"Complete\" is 1 when the threshold lies above every template's stored "
             "floor, so no peak below the floor was lost.\n")
    L.append("| | " + " | ".join(Fs) + " |")
    L.append("|---|" + "---|" * len(Fs))
    rows_def = (
        ("Threshold", "tau_op"), ("Complete", "complete"),
        ("Impossible detections", "impossible_n"), ("Impossible per live min", "impossible_per_min"),
        ("False alarms per template per live min", "false_per_template_min"),
        ("Possible per live min", "possible_per_min"),
        ("Possible ally-variant per live min", "possible_ally_per_min"),
        ("Possible enemy-variant per live min", "possible_enemy_per_min"),
        ("Own-template per live min", "own_per_min"),
        ("Expected false possible per live min", "expected_false_possible_per_min"),
        ("Own X casts", "own_casts"), ("Own recall", "own_recall"),
        ("Verified X casts", "verified_casts"), ("Verified recall", "verified_recall"),
        ("Own agent's enemy variant at an own cast", "own_enemy_variant_hits"),
        ("Onset minus drop, median (s)", "onset_median_s"),
        ("Onset minus drop, 25th percentile (s)", "onset_q25_s"),
        ("Onset minus drop, 75th percentile (s)", "onset_q75_s"),
        ("Onset minus drop, IQR (s)", "onset_iqr_s"),
        ("Enemy to ally ratio, median session", "enemy_ally_ratio_median"),
        ("Sessions with an ally-variant detection", "enemy_ally_sessions"),
        ("Enemy to ally ratio, pooled", "enemy_ally_ratio_pooled"),
        ("Detections alone for their line in their round", "round_unique_fraction"),
        ("... possible and own only", "round_unique_fraction_possible"),
        ("Impossible beside a higher possible or own detection", "impossible_beside_true_fraction"),
    )
    for label, key in rows_def:
        L.append(f"| {label} | " + " | ".join(E(F, key) for F in Fs) + " |")
    L.append("")
    agents = sorted({k.split("_", 2)[2] for F in Fs
                     for k in rows.get((f"evaluate-{F}", "all-matches"), {})
                     if k.startswith("own_recall_")})
    if agents:
        L.append("Own recall by the player's agent (accepted X casts; verified in brackets):\n")
        L.append("| Agent | " + " | ".join(Fs) + " |")
        L.append("|---|" + "---|" * len(Fs))
        for a in agents:
            L.append(f"| {a} | " + " | ".join(
                f"{E(F, f'own_recall_{a}')} of {E(F, f'own_casts_{a}')} "
                f"({E(F, f'verified_recall_{a}')} of {E(F, f'verified_casts_{a}')})"
                for F in Fs) + " |")
        L.append("")
    L.append("### Curves\n")
    L.append("- `<store>/analysis/voice-lines/0.1.0/report/curves_possible.png`: possible-template "
             "detections against impossible-template detections per live minute, one line per "
             "formulation, the operating point marked.")
    L.append("- `<store>/analysis/voice-lines/0.1.0/report/curves_own_recall.png`: own ult recall "
             "against the same axis.")
    L.append("- `<store>/analysis/voice-lines/0.1.0/review/index.html`: the review sheet.\n")
    L.append("### Per session\n")
    sids = sorted({s for (p, s) in rows if p == f"evaluate-{Fs[0]}" and s != "all-matches"},
                  key=lambda s: (-(rows[(f"evaluate-{Fs[0]}", s)].get("podcast") or 0), s)) if Fs else []
    for F in Fs:
        L.append(f"{F} at its operating threshold; the impossible rate is also given at the "
                 f"common threshold where the pooled impossible rate is 1 per live minute "
                 f"({E(F, 'tau_p5')}). (podcast) marks the sessions the audio gate's speech cut "
                 "named.\n")
        L.append("| Session | Live min | Impossible/min | Impossible/min at 1/min threshold | "
                 "Possible ally | Possible enemy | Own | Own X casts found | Enemy/ally | "
                 "Alone in round |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for s in sids:
            pod = " (podcast)" if rows.get((f"evaluate-{F}", s), {}).get("podcast") else ""
            L.append(f"| `{s}`{pod} | {E(F, 'live_minutes', s)} | {E(F, 'impossible_per_min', s)} | "
                     f"{E(F, 'impossible_per_min_at_p5', s)} | {E(F, 'possible_ally_n', s)} | "
                     f"{E(F, 'possible_enemy_n', s)} | {E(F, 'own_n', s)} | "
                     f"{E(F, 'own_hits', s)} of {E(F, 'own_casts', s)} | "
                     f"{E(F, 'enemy_ally_ratio', s)} | {E(F, 'round_unique_fraction', s)} |")
        L.append("")
        L.append(f"Podcast sessions ({E(F, 'podcast_sessions')}) against the rest: "
                 f"{E(F, 'podcast_impossible_per_min')} and {E(F, 'rest_impossible_per_min')} "
                 f"impossible per live minute at the operating threshold, ratio "
                 f"{E(F, 'podcast_ratio')}; {E(F, 'podcast_impossible_per_min_at_p5')} and "
                 f"{E(F, 'rest_impossible_per_min_at_p5')} at the 1/min threshold, ratio "
                 f"{E(F, 'podcast_ratio_at_p5')}.\n")
    L.append("### Detections by agent\n")
    for F in Fs[:1] + [x for x in Fs[1:] if x == "F-B"]:
        tab = rows.get((f"agents-{F}", "all-matches"), {})
        names = sorted({k.rsplit("_", 2)[0] for k in tab if k.endswith("_n")})
        L.append(f"{F} at its operating threshold: live detections by class, and the number of "
                 "sessions in which the template is of that class. Lines with no detection and "
                 "no possible session are left out.\n")
        L.append("| Line | Own (sessions) | Possible (sessions) | Impossible (sessions) |")
        L.append("|---|---|---|---|")
        for n in names:
            vals = [tab.get(f"{n}_{c}_n", 0) for c in ("own", "possible", "impossible")]
            ses = [tab.get(f"{n}_{c}_sessions", 0) for c in ("own", "possible")]
            if not any(vals) and not any(ses):
                continue
            cell = lambda c: (f"{T(f'agents-{F}', 'all-matches', f'{n}_{c}_n')} "
                              f"({T(f'agents-{F}', 'all-matches', f'{n}_{c}_sessions')})")
            L.append(f"| {n} | {cell('own')} | {cell('possible')} | {cell('impossible')} |")
        L.append("")
    L.append("### Witnesses\n")
    L.append("Agreement is consistency, not accuracy. Each witness below observes the cast "
             "through another channel than the audio it checks.\n")
    for F in Fs:
        L.append(f"- {F}. The tray's own X drops are the recall above. The line the player "
                 f"heard on `043bafca271a` at 1870.1 s (Vyse): the enemy variant scores "
                 f"{Wt(F, 'heard_043bafca271a_Vyse_enemy_score')}, onset "
                 f"{Wt(F, 'heard_043bafca271a_Vyse_enemy_dt_s')} s from the heard time, "
                 f"detected {Wt(F, 'heard_043bafca271a_Vyse_enemy_detected')} (1 is detected); "
                 f"the ally variant scores {Wt(F, 'heard_043bafca271a_Vyse_ally_score')}. "
                 f"Spectated X drops (a teammate's kit on the tray after the player's death, "
                 f"neither forced nor co-occurring): {Wt(F, 'spectated_x_with_ally_line')} of "
                 f"{Wt(F, 'spectated_x_drops')} have a possible ally-variant detection within "
                 f"1.5 s ({Wt(F, 'spectated_x_fraction')}; chance {Wt(F, 'spectated_x_chance')}). "
                 f"Demos: {Wt(F, 'demo_x_hits')} of {Wt(F, 'demo_x_casts')} own X casts found, "
                 f"other templates firing {Wt(F, 'demo_other_per_min')} times per capture minute "
                 f"over {Wt(F, 'demo_minutes')} minutes. The lineup: on "
                 f"{Wt(F, 'board_disagreements')} slots the scoreboard overrode the top bar's "
                 f"agent; on those slots' sides the board's agent's line fires "
                 f"{Wt(F, 'board_agent_lines')} times in live time and the top bar's "
                 f"{Wt(F, 'top_bar_agent_lines')}. Of {Wt(F, 'impossible_live')} live impossible "
                 f"detections, {Wt(F, 'impossible_top_bar_proposed')} name an agent the top bar "
                 f"proposed on that side, a lineup conflict rather than a plain false alarm.")
        agents_lead = sorted({k.split("_")[1] for k in rows.get((f"witness-{F}", "all-matches"), {})
                              if k.startswith("lead_") and k.endswith("_casts")})
        if agents_lead:
            L.append(f"  Own X drops against the own line anywhere from 20 s before to 1.5 s "
                     f"after the drop, by the player's agent (hits of casts; median, 25th and "
                     f"75th percentile of onset minus drop in s; chance of a hit at that "
                     f"agent's own-line rate): " + "; ".join(
                         f"{a} {Wt(F, f'lead_{a}_hits')} of {Wt(F, f'lead_{a}_casts')}, "
                         f"{Wt(F, f'lead_{a}_median_s')} ({Wt(F, f'lead_{a}_q25_s')} to "
                         f"{Wt(F, f'lead_{a}_q75_s')}), chance {Wt(F, f'lead_{a}_chance')}"
                         for a in agents_lead) + ".")
    L.append("")
    L.append("### Outcomes\n")
    L.append("Measured values beside each prediction; the orchestrator judges them.\n")
    L.append("| Id | Prediction (abridged) | " + " | ".join(Fs) + " |")
    L.append("|---|---|" + "---|" * len(Fs))
    pred = (
        ("P0", "own ally line within 1.5 s of >= 0.8 of accepted X casts at 0.1 impossible/min",
         lambda F: f"recall {E(F, 'own_recall')}; verified {E(F, 'verified_recall')}"),
        ("P1", "possible detections 0.3 to 1.5 per live min at that point",
         lambda F: f"{E(F, 'possible_per_min')} (with own {E(F, 'possible_or_own_per_min')})"),
        ("P2", "F-A matches or beats F-B on own recall at the same impossible rate",
         lambda F: f"own recall {E(F, 'own_recall')} at {E(F, 'impossible_per_min')}/min"),
        ("P3", "enemy-variant detections >= half the ally-variant on the median session",
         lambda F: f"median {E(F, 'enemy_ally_ratio_median')} over {E(F, 'enemy_ally_sessions')} sessions"),
        ("P4", ">= 0.95 of detections alone for their agent and variant in their round",
         lambda F: f"{E(F, 'round_unique_fraction')} of {E(F, 'round_n')}"),
        ("P5", "podcast sessions >= 2x the impossible rate of the rest at a common threshold",
         lambda F: f"{E(F, 'podcast_ratio')} at the operating point; {E(F, 'podcast_ratio_at_p5')} at 1/min"),
        ("P6", "own onset minus drop IQR <= 0.5 s",
         lambda F: f"IQR {E(F, 'onset_iqr_s')}, median {E(F, 'onset_median_s')}, n {E(F, 'onset_n')}"),
    )
    for pid, text, cell in pred:
        L.append(f"| {pid} | {text} | " + " | ".join(cell(F) for F in Fs) + " |")
    L.append("")
    L.append("### What was not done\n")
    L.extend(f"- {x}" for x in NOT_DONE)
    L.append("")
    doc = DOC.read_text(encoding="utf-8") if DOC.is_file() else "# Voice lines\n\n"
    head = doc.split("## Results", 1)[0].rstrip() + "\n\n"
    DOC.write_text(head + "\n".join(L), encoding="utf-8", newline="\n")
    print(f"wrote {DOC}")


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
    ev = sub.add_parser("evaluate")
    ev.add_argument("--formulations", nargs="*", choices=FORMULATIONS)
    ev.add_argument("--sessions", nargs="*")
    ev.add_argument("--dry", action="store_true", help="print only; record and write nothing")
    rv = sub.add_parser("review")
    rv.add_argument("--formulation", choices=FORMULATIONS)
    rv.add_argument("--sessions", nargs="*")
    sub.add_parser("report")
    a = ap.parse_args(argv)
    print(f"{VERSION}: {os.environ['OMP_NUM_THREADS']} BLAS threads, Below Normal priority")
    every = match_sessions() + demo_sessions()
    if a.cmd == "templates":
        cmd_templates()
    elif a.cmd == "score":
        cmd_score(a.formulation, a.sessions or every)
    elif a.cmd == "evaluate":
        have = [F for F in FORMULATIONS if (SCORES / F).is_dir()]
        cmd_evaluate(a.formulations or have, a.sessions or every, a.dry)
    elif a.cmd == "review":
        F = a.formulation
        if F is None:
            rows = _latest()
            got = [(rows[(f"evaluate-{x}", "all-matches")].get("own_recall") or 0, x)
                   for x in FORMULATIONS if (f"evaluate-{x}", "all-matches") in rows]
            if not got:
                raise SystemExit("no recorded evaluation; run evaluate first")
            F = max(got)[1]
        cmd_review(F, a.sessions or match_sessions())
    elif a.cmd == "report":
        cmd_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
