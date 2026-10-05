r"""Gate the expensive passes on sound: does anything other than footsteps, gunfire and ambience sound here?

    .\.venv\Scripts\python.exe prototypes\audio_gate.py features (--sessions SID ... | --matches | --demos | --fast)
    .\.venv\Scripts\python.exe prototypes\audio_gate.py labels [--sessions SID ...] [--record]
    .\.venv\Scripts\python.exe prototypes\audio_gate.py fit --formulation F0|F1|F2|F2c|F3|F4|F4b --loso [--sessions SID ...]
    .\.venv\Scripts\python.exe prototypes\audio_gate.py evaluate [--formulations F ...] [--sessions SID ...] [--dry]
    .\.venv\Scripts\python.exe prototypes\audio_gate.py review --formulation F --top K
    .\.venv\Scripts\python.exe prototypes\audio_gate.py report

Add `--idle` to any command to run on one thread at Idle priority, for when
another heavy job shares the machine.

Purpose
-------
The expensive passes (dense minimap sampling, the ring and line sweeps, the
timer-bar read, a census montage) should run only where something happened.
The player's direction is to gate them on any sound that is not footsteps,
gunfire or ambience. `docs/AUDIO_GATE.md` is the design this file implements:
labels mined from stored tables, five formulations scored alike, and eight
predictions under task `audio-gate` in the store's `notes/predictions.jsonl`.

Method
------
`features` decodes each capture's audio stream once with PyAV, mixes stereo to
mono and stores the front end of `audio_bank`/`audio_channel` for the whole
capture: 64 mel bands from 60 Hz to 16 kHz, 2048-point frames at the file's
native rate, a 10 ms hop, as absolute dB in float16, with the per-band session
median beside it. With torch present it also stores the 128-band Kaldi
filterbank of the 16 kHz mono mix that the AudioSet tagger reads. Both are
magnitudes; no audio leaves the capture.

`labels` mines 100 ms frame labels from stored tables only, each interval
carrying the table and version it came from: own casts from `events/tray_drop`
(`player_cast`, not `suspect`, 0.3 s before to 1.5 s after the drop) plus the
player's `labels/tray_object` answers; own gunfire from the 2 Hz HUD table
(`fire_rule`: the magazine falls while the reserve stands still); known others
from the player's kills and deaths (`events/death`), round starts, barrier
drops, round ends and plants (`rounds`, `gametime`) and tray drops the
owner refused; buy phase from `gametime`; background from the rest of the live
round (`classify_blocks`). Live time is `round_live` plus `post_plant` while the
player lives: after the player's first death in a round the tray shows a
spectated teammate's kit [domain:hud/tray-after-player-death], and
`ability_timeline.player_tray_casts` draws the same line. Stalled spans (`reticle.stalls`) leave every count.

`fit` scores each match session with a model fitted on the others:
F0 loudness (rank of RMS and of spectral flux, the larger), F1 the bank's
`corr` against every cast template in `audio-bank/0.2.0/demo_bank` (a demo
without its own), F2 a four-class logistic regression on 0.5 s log-mel
context, F2c the same without the podcast sessions in training, F3 a Gaussian
fitted to non-cast frames only, F4 the AudioSet tagger's non-background mass
and F4b its embeddings through the F2 classifier. `evaluate` smooths each gate over
three frames, thresholds it, merges frames closer than 0.3 s into detections,
and sweeps the threshold to trade recall on the casts against unexplained
detections per live minute. `review` lists the unexplained detections for the
player with a spectrogram and an `ffplay` command into the source capture.

What it does not do
-------------------
It emits no events, writes nothing under `events/` or `labels/`, and `reticle/`
does not import it. It decodes no video, reads no `roi_cache`, and writes no
audio: no WAV and no clip, only log-mel magnitudes, scores and spectrogram
images under `analysis/audio-gate/`.
"""
from __future__ import annotations

import os
import sys

#: One heavy process at a time: four BLAS threads at Below Normal, or one at
#: Idle with `--idle` when another heavy job shares the machine.
IDLE = "--idle" in sys.argv
THREADS = "1" if IDLE else "4"
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_var] = THREADS

import argparse  # noqa: E402
import contextlib  # noqa: E402
import ctypes  # noqa: E402
import hashlib  # noqa: E402
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
    import audio_bank  # noqa: E402  the front end, the bank, Below Normal priority
from reticle import ult_lines  # noqa: E402  the audio decode and the log-mel front end
from reticle.ult_lines import decode_mono, log_mel  # noqa: E402
from reticle.audio_source import audio_path  # noqa: E402  which file holds the audio


def _idle_priority() -> None:
    """Drop from Below Normal (set by `audio_bank` on import) to Idle."""
    if os.name != "nt":
        return
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    if not k.SetPriorityClass(k.GetCurrentProcess(), 0x40):
        raise SystemExit("could not lower this process to Idle priority")


if IDLE:
    _idle_priority()

STORE = audio_bank.STORE
VERSION = "audio-gate-0.1.0"
OUT = STORE / "analysis" / "audio-gate" / VERSION.rsplit("-", 1)[1]
FEAT, LABELS, SCORES = OUT / "features", OUT / "labels", OUT / "scores"
DETS, REPORT, REVIEW, MODELS = OUT / "detections", OUT / "report", OUT / "review", OUT / "models"
DOC = ROOT / "docs" / "AUDIO_GATE.md"

#: The front end of `audio_bank`, unchanged.
HOP, NFFT, BANDS, FMIN, FMAX = (audio_bank.HOP, audio_bank.NFFT, audio_bank.BANDS,
                                audio_bank.FMIN, audio_bank.FMAX)
if (HOP, NFFT, BANDS, FMIN, FMAX) != (ult_lines.HOP, ult_lines.NFFT, ult_lines.BANDS,
                                     ult_lines.FMIN, ult_lines.FMAX):
    raise SystemExit("audio_bank's front end differs from reticle.ult_lines'")
#: 10 ms frames per 100 ms label frame; label frame j spans [j, j + 1) * STEP.
BLOCK, STEP = 10, 0.1
#: F2 context: this many label frames, centred (0.5 s).
CTX_BLOCKS = 5

#: The HUD reader's own acceptance threshold for a glyph read (`reticle hud
#: --min-confidence`, `ocr.read_bottom_hud`); a pair of HUD samples is read for
#: gunfire only when both clear it.
HUD_MIN_CONF = 0.82
#: Two HUD rows are consecutive when this close (the table is 2 Hz).
HUD_MAX_GAP_S = 0.75

#: Own-cast window around a tray drop, seconds.
CAST_WIN = (-0.3, 1.5)
#: Background keeps this far from a tray drop, own gunfire, a known other, and
#: any other death.
BG_GAP_CAST, BG_GAP_FIRE, BG_GAP_OTHER, BG_GAP_DEATH = 3.0, 1.0, 2.0, 1.0
#: A detection whose onset lies this close to an event is explained by it.
EXPLAIN_S = 1.5
#: A cast is found when a detection's onset lies in this window around its drop.
RECALL_WIN = (-0.5, 1.0)
#: Detections: smooth over this many frames; frames closer than MERGE_S join.
SMOOTH, MERGE_S = 3, 0.3
MERGE_BLOCKS = int(round(MERGE_S / STEP))
#: Operating points read off each curve, unexplained detections per live minute.
RATES = (1, 3, 5, 10, 20)
#: The fixed recall for the per-session table (P7) and the P1 check.
FIXED_RECALL = (0.5, 0.7, 0.8)
#: The class order of the label arrays; -1 is unlabelled.
CLASSES = ("own_cast", "gunfire", "background", "buy")
CAST, FIRE, BG, BUY, NONE = 0, 1, 2, 3, -1
#: Explanation codes of a detection onset.
EXPLAIN = ("own_cast", "own_gunfire", "known_other", "unexplained")
#: The formulations, in the fixed order their curves are coloured.
FORMULATIONS = ("F0", "F1", "F2", "F3", "F4", "F4b")
#: F1: bank template length in label frames' 10 ms frames, and the context the
#: bank's median is taken over (seconds before, after), as `audio_bank`.
F1_T = audio_bank.T
F1_CTX = (audio_bank.CTX_PRE, audio_bank.CTX_POST)
#: F2: small L2 on the weights; Adam on the full batch.
L2, LR, MAX_ITER, TOL = 1e-3, 0.05, 10000, 1e-7
#: F3: the covariance shrinks toward its diagonal by this much.
SHRINK = 0.1
#: F4: the tagger, its window and step, seconds.
AST_MODEL = "MIT/ast-finetuned-audioset-10-10-0.4593"
AST_RATE, AST_WIN, AST_STEP = 16000, 1.0, 0.5

#: The fast tier: two matches with 21 verified casts, four re-recorded demos.
FAST_MATCHES = ("a06f04a0059f", "a1a995e6b19b")
FAST_DEMOS = ("aab12e41dcfc", "6afc32cb46b4", "fc02a2c1ac01", "0c6c52a65b9e")
#: Casts the tray cannot date. Run it Back on the Phoenix demo, bracketed by
#: decoded frames [domain:abilities/phoenix-run-it-back-expiry-flash]; the
#: Regrowth channel on the re-recorded Skye demo, dated by the first frame of
#: its ring [domain:abilities/skye-regrowth-no-tray-drop]; and the Skye demo
#: drop the design counted as a second Regrowth, which the player says is the
#: settings menu dimming the tray [domain:hud/menu-dims-tray].
TRAY_BLIND = (("run_it_back", "6afc32cb46b4", 43.2, "Run it Back, decoded frames 42.8-43.6 s"),
              ("regrowth_fc02a2c1ac01", "fc02a2c1ac01", 5.17,
               "Regrowth ring first drawn 5.17 s (demo_cast_census sweep)"),
              ("regrowth_6ab7a9e99235", "6ab7a9e99235", 27.567,
               "C drop at 27.57 s; the player: the menu dimming the tray, no cast"))
SMOKE_SESSION = "a06f04a0059f"

_GPU = None


def gpu():
    """cupy, or numpy when no GPU is present (tests run on numpy)."""
    global _GPU
    if _GPU is None:
        try:
            import cupy as cp
            cp.zeros(1)
            _GPU = cp
        except Exception:  # noqa: BLE001  no CUDA: fall back to the CPU
            _GPU = np
    return _GPU


def _np(a):
    return a.get() if hasattr(a, "get") else np.asarray(a)


def _free_gpu() -> None:
    xp = gpu()
    if xp is not np:
        xp.get_default_memory_pool().free_all_blocks()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def _manifest(sid: str) -> dict:
    return json.loads((STORE / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))


def match_sessions() -> list[str]:
    return audio_bank.match_sessions()


def demo_sessions() -> list[str]:
    return audio_bank.demo_sessions()


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else None


# ---------------------------------------------------------------------------
# Front end
# ---------------------------------------------------------------------------

# `decode_mono` is `reticle.ult_lines.decode_mono`, imported above.


def logmel(x: np.ndarray, filled: np.ndarray, rate: int, chunk: int = 8192):
    """(absolute log-mel dB [n, 64], ok [n], RMS dB [n]); frame k centred on k * HOP.

    `ult_lines.log_mel` on this module's GPU choice; the production voice-line
    reader shares the front end these features were cached with.
    """
    return log_mel(x, filled, rate, chunk=chunk, xp=gpu())


def ast_fbank(x: np.ndarray, rate: int, chunk_s: float = 60.0) -> np.ndarray:
    """The AudioSet tagger's input features for the whole capture: [frames, 128].

    The 16 kHz mono mix, resampled on the GPU in chunks with margins, through
    the same Kaldi filterbank `ASTFeatureExtractor` calls (Hanning window,
    128 bins, 25 ms frames, 10 ms shift). Frame i covers samples
    [160 i, 160 i + 400) of the 16 kHz signal. Every step is per frame, so a
    window cut from this equals the extractor's output on that window's audio.
    """
    import torch
    import torchaudio
    from torchaudio.compliance import kaldi
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    g = math.gcd(rate, AST_RATE)
    iu, ou = rate // g, AST_RATE // g
    step = int(chunk_s * AST_RATE) // ou * ou
    margin = 400 * iu
    n_out = len(x) * AST_RATE // rate
    y = np.zeros(n_out, np.float32)
    for o0 in range(0, n_out, step):
        o1 = min(n_out, o0 + step)
        i0, i1 = o0 * rate // AST_RATE, o1 * rate // AST_RATE
        lo, hi = i0 - margin, i1 + margin
        seg = np.zeros(hi - lo, np.float32)
        a, b = max(lo, 0), min(hi, len(x))
        seg[a - lo:b - lo] = x[a:b]
        r = torchaudio.functional.resample(torch.from_numpy(seg).to(dev), rate, AST_RATE)
        skip = margin * AST_RATE // rate
        y[o0:o1] = r[skip:skip + (o1 - o0)].float().cpu().numpy()
    n_frames = 1 + (len(y) - 400) // 160 if len(y) >= 400 else 0
    out = np.empty((n_frames, 128), np.float16)
    per = 6000
    for f0 in range(0, n_frames, per):
        f1 = min(n_frames, f0 + per)
        w = torch.from_numpy(y[160 * f0:160 * (f1 - 1) + 400]).to(dev).unsqueeze(0)
        fb = kaldi.fbank(w, sample_frequency=AST_RATE, window_type="hanning", num_mel_bins=128)
        out[f0:f1] = fb.cpu().numpy().astype(np.float16)
    del y
    if dev == "cuda":
        torch.cuda.empty_cache()
    return out


def cmd_features(sids: list[str], force: bool = False) -> None:
    """Decode each session once; store the 10 ms log-mel and the tagger's filterbank."""
    try:
        import torch  # noqa: F401
        with_ast = True
    except ImportError:
        with_ast = False
        print("torch is missing: the tagger's filterbank is not stored")
    FEAT.mkdir(parents=True, exist_ok=True)
    for sid in sids:
        out = FEAT / f"{sid}.npz"
        ast_out = FEAT / f"{sid}.ast.npz"
        man = _manifest(sid)
        key = man["source"]["content_key"]
        have = out.is_file() and str(np.load(out)["content_key"]) == key
        have_ast = ast_out.is_file() or not with_ast
        if have and have_ast and not force:
            print(f"  {sid}: cached")
            continue
        t = time.time()
        x, filled, rate = decode_mono(audio_path(man, STORE))
        td = time.time() - t
        if not have or force:
            L, ok, rms = logmel(x, filled, rate)
            med = np.median(L[ok], axis=0) if ok.any() else np.zeros(BANDS, np.float32)
            np.savez_compressed(out, L=L.astype(np.float16), ok=ok, rms=rms.astype(np.float16),
                                med=med.astype(np.float32), t0_s=0.0, hop_s=HOP, rate=rate,
                                content_key=key, version=VERSION, n_samples=len(x),
                                filled_fraction=float(filled.mean()))
            _free_gpu()
        if with_ast and (not ast_out.is_file() or force):
            fb = ast_fbank(x, rate)
            np.savez_compressed(ast_out, fbank=fb, shift_s=0.01, frame_s=0.025,
                                rate=AST_RATE, content_key=key, version=VERSION)
        print(f"  {sid}: {len(x) / rate / 60:.1f} min decoded in {td:.1f} s, "
              f"stored in {time.time() - t:.1f} s")
        del x, filled


def load_features(sid: str) -> dict:
    z = np.load(FEAT / f"{sid}.npz")
    if str(z["version"]) != VERSION:
        raise SystemExit(f"{sid}: features {z['version']} != {VERSION}; rerun `features`")
    return {k: z[k] for k in z.files}


# ---------------------------------------------------------------------------
# Pooling and features per 100 ms frame
# ---------------------------------------------------------------------------

def pool_blocks(W, xp=np):
    """(mean, max) over each run of BLOCK frames; the tail shorter than a block is dropped."""
    nb = len(W) // BLOCK
    X = W[:nb * BLOCK].reshape(nb, BLOCK, W.shape[1])
    return X.mean(axis=1), X.max(axis=1)


def diff_sums(W, xp=np):
    """Per block, the sum and the sum of squares of first differences (the first frame's is 0)."""
    d = xp.concatenate([xp.zeros((1, W.shape[1]), W.dtype), W[1:] - W[:-1]], axis=0)
    nb = len(W) // BLOCK
    D = d[:nb * BLOCK].reshape(nb, BLOCK, W.shape[1])
    return D.sum(axis=1), (D ** 2).sum(axis=1)


def context_features(bmean, bmax, s1, s2, k: int = CTX_BLOCKS, xp=np):
    """[nb, 3 * bands]: over k centred blocks, the per-band mean, max and the
    standard deviation of first differences. Edge blocks repeat."""
    p = k // 2
    pad = lambda a: xp.concatenate([xp.repeat(a[:1], p, 0), a, xp.repeat(a[-1:], p, 0)], 0)
    M, X, A, B = pad(bmean), pad(bmax), pad(s1), pad(s2)
    nb = len(bmean)
    mean = sum(M[i:i + nb] for i in range(k)) / k
    mx = X[0:nb]
    for i in range(1, k):
        mx = xp.maximum(mx, X[i:i + nb])
    n = k * BLOCK
    m1 = sum(A[i:i + nb] for i in range(k)) / n
    m2 = sum(B[i:i + nb] for i in range(k)) / n
    sd = xp.sqrt(xp.maximum(m2 - m1 ** 2, 0))
    return xp.concatenate([mean, mx, sd], axis=1)


def median_removed(f: dict, xp=np):
    """The 10 ms log-mel less the session's per-band median; undecodable frames at 0."""
    W = xp.asarray(f["L"].astype(np.float32)) - xp.asarray(f["med"])
    W[xp.asarray(~f["ok"])] = 0
    return W


def f2_features(f: dict, xp=None):
    """The 192 F2 features of every 100 ms frame of one session, on the GPU."""
    xp = xp or gpu()
    W = median_removed(f, xp)
    bmean, bmax = pool_blocks(W, xp)
    s1, s2 = diff_sums(W, xp)
    return context_features(bmean, bmax, s1, s2, xp=xp).astype(xp.float32)


def rank01(x: np.ndarray) -> np.ndarray:
    """Rank within the array mapped to [0, 1]; ties keep their order."""
    r = np.empty(len(x), np.float64)
    r[np.argsort(x, kind="stable")] = np.arange(len(x))
    return (r / max(len(x) - 1, 1)).astype(np.float32)


def smooth(s: np.ndarray, k: int = SMOOTH) -> np.ndarray:
    """Centred moving mean over k frames; the edges average what they have."""
    s = np.asarray(s, np.float64)
    c = np.convolve(s, np.ones(k), mode="same")
    n = np.convolve(np.ones(len(s)), np.ones(k), mode="same")
    return (c / n).astype(np.float32)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def fire_rule(t, mag, res, conf, min_conf: float = HUD_MIN_CONF,
              max_gap: float = HUD_MAX_GAP_S):
    """(fire intervals, reloads, swaps) from consecutive HUD rows, times in seconds.

    A pair counts only when both rows clear the reader's confidence and carry a
    magazine and a reserve. The magazine falling while the reserve stands still
    is fire in (t_prev, t_cur]. The magazine rising while the reserve falls is a
    reload; any other change moves both and is a swap. This is the prototype's
    rule, checked by P0, not a domain fact.
    """
    fires, reloads, swaps = [], [], []
    for i in range(1, len(t)):
        a, b = i - 1, i
        if t[b] - t[a] > max_gap:
            continue
        if conf[a] is None or conf[b] is None or conf[a] < min_conf or conf[b] < min_conf:
            continue
        if None in (mag[a], mag[b], res[a], res[b]):
            continue
        if mag[b] < mag[a] and res[b] == res[a]:
            fires.append((float(t[a]), float(t[b])))
        elif mag[b] > mag[a] and res[b] < res[a]:
            reloads.append((float(t[a]), float(t[b])))
        elif mag[b] != mag[a] or res[b] != res[a]:
            swaps.append((float(t[a]), float(t[b])))
    return fires, reloads, swaps


def _near_points(c: np.ndarray, pts, gap: float) -> np.ndarray:
    """Whether each time lies strictly within `gap` of any point."""
    if len(pts) == 0:
        return np.zeros(len(c), bool)
    p = np.sort(np.asarray(pts, float))
    i = np.searchsorted(p, c)
    d = np.full(len(c), np.inf)
    ok = i < len(p)
    d[ok] = p[i[ok]] - c[ok]
    ok = i > 0
    d[ok] = np.minimum(d[ok], c[ok] - p[i[ok] - 1])
    return d < gap


def _near_intervals(c: np.ndarray, iv, gap: float) -> np.ndarray:
    """Whether each time lies strictly within `gap` of any interval [a, b]."""
    out = np.zeros(len(c), bool)
    for a, b in iv:
        out |= (c > a - gap) & (c < b + gap)
    return out


def _overlaps(nb: int, iv, step: float = STEP) -> np.ndarray:
    """Frames whose span [j, j + 1) * step overlaps any interval (a, b]."""
    s = np.arange(nb) * step
    out = np.zeros(nb, bool)
    for a, b in iv:
        j0, j1 = int(math.floor(a / step + 1e-9)), int(math.ceil(b / step - 1e-9))
        out[max(j0, 0):max(min(j1, nb), 0)] = True
    return out & (s >= 0)


def classify_blocks(nb: int, *, live, buy, stalled, casts, drops_live, fires, others,
                    other_deaths, step: float = STEP) -> np.ndarray:
    """The class of every 100 ms frame: CAST, FIRE, BG, BUY or NONE (unlabelled).

    `live` marks frames in `round_live` or `post_plant` while the player lives;
    `buy` marks `buy_phase`. An own cast labels the frames overlapping
    CAST_WIN around its drop; own gunfire the frames overlapping its interval.
    Background is live time at least BG_GAP_CAST from every tray drop the
    player could have made (`drops_live`, casts or refused), BG_GAP_FIRE from
    own gunfire, BG_GAP_OTHER from a known other and BG_GAP_DEATH from any
    other death. Stalled frames carry no label. A cast outranks gunfire, which
    outranks buy phase and background.
    """
    c = (np.arange(nb) + 0.5) * step
    live, buy, stalled = (np.asarray(v, bool) for v in (live, buy, stalled))
    cls = np.full(nb, NONE, np.int8)
    bg = (live & ~_near_points(c, list(casts) + list(drops_live), BG_GAP_CAST)
          & ~_near_intervals(c, fires, BG_GAP_FIRE) & ~_near_points(c, others, BG_GAP_OTHER)
          & ~_near_points(c, other_deaths, BG_GAP_DEATH))
    cls[buy] = BUY
    cls[bg] = BG
    cls[_overlaps(nb, fires, step) & (live | buy)] = FIRE
    cls[_overlaps(nb, [(t + CAST_WIN[0], t + CAST_WIN[1]) for t in casts], step)] = CAST
    cls[stalled] = NONE
    return cls


def explain_codes(nb: int, casts, fires, others, step: float = STEP):
    """(code, event time) for a detection whose onset is frame j's start.

    Own cast first, then own gunfire, then a known other, each within EXPLAIN_S;
    code 3 is unexplained and its time NaN.
    """
    s = np.arange(nb) * step
    code = np.full(nb, 3, np.int8)
    when = np.full(nb, np.nan)
    groups = ([(t, t) for t in casts], list(fires), [(t, t) for t in others])
    for k in (2, 1, 0):
        iv = groups[k]
        if not iv:
            continue
        a = np.array([x[0] for x in iv])
        b = np.array([x[1] for x in iv])
        d = np.maximum(np.maximum(a[None] - s[:, None], s[:, None] - b[None]), 0)
        best = d.argmin(axis=1) if len(iv) < 5000 else None
        if best is None:
            continue
        hit = d[np.arange(nb), best] <= EXPLAIN_S + 1e-9
        code[hit] = k
        when[hit] = a[best[hit]]
    return code, when


def _col(table, name):
    return table.column(name).to_pylist() if name in table.column_names else None


def self_speed(mm, nb: int) -> np.ndarray:
    """Median self speed on the minimap (ROI px/s) in each 100 ms frame; NaN unread."""
    t = np.asarray(_col(mm, "t_ms"), float) / 1000.0
    x = np.array([np.nan if v is None else v for v in _col(mm, "self_x")], float)
    y = np.array([np.nan if v is None else v for v in _col(mm, "self_y")], float)
    good = np.isfinite(x) & np.isfinite(y)
    t, x, y = t[good], x[good], y[good]
    out = np.full(nb, np.nan, np.float32)
    if len(t) < 2:
        return out
    dt = np.diff(t)
    ok = (dt > 0) & (dt <= 0.2)
    v = np.hypot(np.diff(x), np.diff(y))[ok] / dt[ok]
    mid = ((t[1:] + t[:-1]) / 2)[ok]
    j = (mid / STEP).astype(int)
    keep = (j >= 0) & (j < nb)
    for jj in np.unique(j[keep]):
        out[jj] = np.median(v[keep][j[keep] == jj])
    return out


def mine_labels(sid: str) -> tuple[dict, dict]:
    """(JSON record, per-frame arrays) of one match session, from stored tables only."""
    from reticle import cli, gametime, rounds, stalls
    from reticle.ability_timeline import CAST_PHASES, DEATH_LEAD_MS
    from reticle.store import Store
    store = Store(STORE)
    man = _manifest(sid)
    date = cli._date_of(man)
    f = np.load(FEAT / f"{sid}.npz")
    nb = len(f["L"]) // BLOCK
    hud = store.read_hud(sid, date)
    rt = store.read_rounds(sid, date)
    rrows = rt.to_pylist()
    stall_list = stalls.for_session(store, sid, date)
    with contextlib.redirect_stdout(io.StringIO()):
        gt = gametime.build_session_gametime(sid, hud, rrows, stall_list=stall_list)
    # The player's first death per round, as `ability_timeline.player_tray_casts`
    # finds it: the rounds owner's death instants in the rounds owner's window.
    deaths = [{"t_first": x} for x in rounds.player_death_times(hud)]
    ends = {r["t_end_ms"] for r in rrows}
    first = {}
    for r in rrows:
        mine = rounds.in_round_window(deaths, r["t_start_ms"], r["t_end_ms"], r["t_close_ms"], ends)
        first[r["round_no"]] = min((e["t_first"] for e in mine), default=None)
    c_ms = (np.arange(nb) + 0.5) * STEP * 1000.0
    phase = np.empty(nb, object)
    stalled = np.zeros(nb, bool)
    alive = np.ones(nb, bool)
    for j, t in enumerate(c_ms):
        g = gt.game_time_at(float(t))
        phase[j], stalled[j] = g.phase, g.is_stalled
        fd = first.get(g.round_no)
        alive[j] = fd is None or t < fd - DEATH_LEAD_MS
    live = np.isin(phase, CAST_PHASES) & alive & ~stalled
    buy = (phase == "buy_phase") & ~stalled

    tray = store.read_events("tray_drop", sid)
    tray_version = tray[0].get("tray_version") if tray else None
    drops = [r for r in tray if r.get("kind") == "drop"]
    verified = audio_bank._labels(sid)
    key = lambda r: f"{sid}:{round(r['t_ms'])}:{r['slot']}"
    casts = [r for r in drops if (r["player_cast"] and not r.get("suspect")) or key(r) in verified]
    cast_t = [r["t_ms"] / 1000.0 for r in casts]
    refused = [r for r in drops if r not in casts and r.get("reason") in
               ("forced", "cooccur_among_casts")]
    refused_t = [r["t_ms"] / 1000.0 for r in refused]

    t_h = np.asarray(_col(hud, "t_ms"), float) / 1000.0
    fires, reloads, swaps = fire_rule(t_h, _col(hud, "ammo_mag"), _col(hud, "ammo_reserve"),
                                      _col(hud, "bottom_confidence"))
    hud_version = (hud.schema.metadata or {}).get(b"hud_version", b"").decode() or None

    dv = [r for r in store.read_events_kind("death", sid, "death_verdict")
          if r.get("kind") == "death_verdict"]
    death_version = dv[0].get("death_adjudication_version") if dv else None
    mine_d = [r for r in dv if r.get("kf_player_kill") or r.get("kf_player_death")]
    other_d = [r["t_ms"] / 1000.0 for r in dv if r not in mine_d]
    others = [{"t": r["t_ms"] / 1000.0, "kind": "player_death" if r.get("kf_player_death")
               else "player_kill", "source": f"events/death {death_version}"} for r in mine_d]
    round_version = rrows[0].get("round_version") if rrows else None
    for r in rrows:
        others.append({"t": r["t_start_ms"] / 1000.0, "kind": "round_start",
                       "source": f"rounds {round_version}"})
        others.append({"t": r["t_end_ms"] / 1000.0, "kind": "round_end",
                       "source": f"rounds {round_version}"})
        if r.get("plant_t_ms") is not None:
            others.append({"t": r["plant_t_ms"] / 1000.0, "kind": "plant",
                           "source": f"rounds {round_version}"})
    for s in gt.schedules:
        others.append({"t": s.t_live_ms / 1000.0, "kind": "barrier_drop",
                       "source": f"gametime {gametime.GAMETIME_VERSION}"})
    for t in refused_t:
        others.append({"t": t, "kind": "tray_drop_refused", "source": f"events/tray_drop {tray_version}"})
    others.sort(key=lambda o: o["t"])
    other_t = [o["t"] for o in others]
    drops_live = [r["t_ms"] / 1000.0 for r in drops
                  if 0 <= int(r["t_ms"] / 1000.0 / STEP) < nb and live[int(r["t_ms"] / 1000.0 / STEP)]]

    cls = classify_blocks(nb, live=live, buy=buy, stalled=stalled, casts=cast_t,
                          drops_live=drops_live, fires=fires, others=other_t,
                          other_deaths=other_d)
    code, when = explain_codes(nb, cast_t, fires, other_t)
    try:
        mm = store.read_minimap(sid, date)
        speed = self_speed(mm, nb)
        mm_version = "l1/minimap " + (mm.schema.metadata or {}).get(
            b"minimap_version", b"").decode()
    except SystemExit:
        speed, mm_version = np.full(nb, np.nan, np.float32), None
    ammo = np.array([v is not None for v in _col(hud, "ammo_mag")])
    t_ammo = t_h[ammo]
    ammo_near = _near_points((np.arange(nb) + 0.5) * STEP, t_ammo, 0.5)

    lab_path = STORE / "labels" / "tray_object" / f"{sid}.jsonl"
    prov = {"own_cast": f"events/tray_drop {tray_version} player_cast and not suspect; "
                        f"labels/tray_object sha256:{_sha(lab_path)}",
            "gunfire": f"l1/hud {hud_version} ammo_mag/ammo_reserve/bottom_confidence, "
                       f"{VERSION} fire_rule (min_conf {HUD_MIN_CONF})",
            "known_other": f"events/death {death_version} (kf_player_kill, kf_player_death); "
                           f"rounds {round_version}; gametime {gametime.GAMETIME_VERSION}; "
                           f"events/tray_drop {tray_version} refused drops",
            "buy": f"gametime {gametime.GAMETIME_VERSION} buy_phase over rounds {round_version}",
            "live": f"gametime {gametime.GAMETIME_VERSION} round_live, post_plant; alive per "
                    f"rounds.player_death_times over l1/hud {hud_version}, less "
                    f"{DEATH_LEAD_MS:.0f} ms",
            "stalled": "reticle.stalls over l1/primitives" if stall_list is not None
                       else "no primitives table: stalls unknown",
            "speed": mm_version or "no minimap table"}
    from reticle.screen import _runs     # [start, end) runs of a boolean array
    runs = lambda m: [[round(a * STEP, 1), round(b * STEP, 1)]
                      for a, b in _runs(np.asarray(m, bool))]
    rec = {"version": VERSION, "session_id": sid, "content_key": man["source"]["content_key"],
           "step_s": STEP, "n_frames": nb, "provenance": prov,
           "counts": {**{c: int((cls == i).sum()) for i, c in enumerate(CLASSES)},
                      "unlabelled": int((cls == NONE).sum()), "live": int(live.sum()),
                      "stalled": int(stalled.sum()),
                      "live_minutes": round(float(live.sum()) * STEP / 60.0, 2),
                      "casts": len(casts), "casts_verified": len(verified),
                      "casts_live": sum(1 for t in cast_t if 0 <= int(t / STEP) < nb
                                        and live[int(t / STEP)] and not stalled[int(t / STEP)]),
                      "casts_refused": len(refused), "fires": len(fires),
                      "reloads": len(reloads), "swaps": len(swaps),
                      "known_others": len(others), "other_deaths": len(other_d),
                      "live_frames_near_ammo_read": int((live & ammo_near).sum())},
           "casts": [{"t": round(r["t_ms"] / 1000.0, 3), "key": key(r), "slot": r["slot"],
                      "verified": key(r) in verified,
                      "player_cast": bool(r["player_cast"])} for r in casts],
           "fires": [[round(a, 3), round(b, 3)] for a, b in fires],
           "reloads": [[round(a, 3), round(b, 3)] for a, b in reloads],
           "swaps": [[round(a, 3), round(b, 3)] for a, b in swaps],
           "known_others": [{**o, "t": round(o["t"], 3)} for o in others],
           "other_deaths": [round(t, 3) for t in other_d],
           "intervals": {c: runs(cls == i) for i, c in enumerate(CLASSES)} | {
               "live": runs(live), "stalled": runs(stalled)}}
    arrays = {"cls": cls, "live": live, "buy": buy, "stalled": stalled, "code": code,
              "when": when.astype(np.float32), "speed": speed}
    return rec, arrays


def load_labels(sid: str) -> tuple[dict, dict]:
    rec = json.loads((LABELS / f"{sid}.json").read_text(encoding="utf-8"))
    z = np.load(LABELS / f"{sid}.npz")
    return rec, {k: z[k] for k in z.files}


def band_centres() -> np.ndarray:
    """Centre frequency of each mel band of the front end, Hz."""
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    imel = lambda m: 700 * (10 ** (m / 2595) - 1)
    return imel(np.linspace(mel(FMIN), mel(FMAX), BANDS + 2))[1:-1]


def p0_check(f: dict, cls: np.ndarray) -> dict:
    """Mean 1-4 kHz level over the session median of own-gunfire and background frames."""
    W = median_removed(f, np)
    bmean, _ = pool_blocks(W, np)
    cf = band_centres()
    sel = (cf >= 1000) & (cf <= 4000)
    e = bmean[:, sel].mean(axis=1)
    g, b = e[cls == FIRE], e[cls == BG]
    if len(g) == 0 or len(b) == 0:
        return {"n_gunfire_frames": int(len(g)), "n_background_frames": int(len(b))}
    return {"gunfire_db": round(float(g.mean()), 2), "background_db": round(float(b.mean()), 2),
            "diff_db": round(float(g.mean() - b.mean()), 2), "louder": int(g.mean() > b.mean()),
            "n_gunfire_frames": int(len(g)), "n_background_frames": int(len(b)),
            "bands": int(sel.sum())}


def cmd_labels(sids: list[str], record: bool) -> None:
    from reticle import metrics
    LABELS.mkdir(parents=True, exist_ok=True)
    totals: dict = {}
    p0_rows = {}
    for sid in sids:
        t = time.time()
        rec, arr = mine_labels(sid)
        (LABELS / f"{sid}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
        np.savez_compressed(LABELS / f"{sid}.npz", **arr)
        c = rec["counts"]
        p0 = p0_check(load_features(sid), arr["cls"])
        p0_rows[sid] = p0
        print(f"  {sid}: " + " ".join(f"{k} {v}" for k, v in c.items())
              + f" | P0 {p0.get('gunfire_db')} vs {p0.get('background_db')} dB "
              f"({time.time() - t:.1f} s)")
        for k, v in c.items():
            totals[k] = round(totals.get(k, 0) + v, 2)
        if record:
            deps = {"version": VERSION, "rule": metrics.fingerprint(
                fire_rule, classify_blocks, mine_labels, HUD_MIN_CONF=HUD_MIN_CONF,
                CAST_WIN=CAST_WIN, BG=(BG_GAP_CAST, BG_GAP_FIRE, BG_GAP_OTHER, BG_GAP_DEATH))}
            metrics.record("audio_gate", part="labels", session=sid,
                           values={**{f"frames_{k}": v for k, v in c.items()
                                      if k in CLASSES or k in ("unlabelled", "live", "stalled")},
                                   "gunfire_windows": c["fires"], "reloads": c["reloads"],
                                   "swaps": c["swaps"], "casts": c["casts"],
                                   "casts_verified": c["casts_verified"],
                                   "live_minutes": c["live_minutes"],
                                   "casts_live": c["casts_live"],
                                   "casts_per_live_min": round(c["casts_live"] / c["live_minutes"], 3)
                                   if c["live_minutes"] else None},
                           deps=deps, context={"provenance": rec["provenance"]})
            metrics.record("audio_gate", part="p0", session=sid, values=p0,
                           deps={"version": VERSION, "check": metrics.fingerprint(p0_check)})
    if record and len(sids) > 1:
        louder = sum(p.get("louder", 0) for p in p0_rows.values())
        metrics.record("audio_gate", part="labels", session="all-matches",
                       values={**{f"frames_{k}": v for k, v in totals.items()
                                  if k in CLASSES or k in ("unlabelled", "live", "stalled")},
                               "gunfire_windows": totals["fires"], "casts": totals["casts"],
                               "casts_verified": totals["casts_verified"],
                               "live_minutes": round(totals["live_minutes"], 1),
                               "casts_live": totals["casts_live"],
                               "casts_per_live_min": round(totals["casts_live"]
                                                           / totals["live_minutes"], 3),
                               "sessions": len(sids)},
                       deps={"version": VERSION}, context={"sessions": sids})
        diffs = [p["diff_db"] for p in p0_rows.values() if "diff_db" in p]
        metrics.record("audio_gate", part="p0", session="all-matches",
                       values={"sessions": len(sids), "sessions_louder": louder,
                               "sessions_with_gunfire": len(diffs),
                               "diff_db_median": round(float(np.median(diffs)), 2) if diffs else None,
                               "diff_db_min": round(float(min(diffs)), 2) if diffs else None},
                       deps={"version": VERSION, "check": metrics.fingerprint(p0_check)},
                       context={"sessions": sids})
    print("totals: " + " ".join(f"{k} {v}" for k, v in totals.items()))


# ---------------------------------------------------------------------------
# Formulations
# ---------------------------------------------------------------------------

def loso_splits(sessions: list[str]):
    """(held-out session, training sessions) for each session in turn."""
    for s in sessions:
        yield s, [x for x in sessions if x != s]


def fit_logreg(X, y, k: int, *, l2: float = L2, lr: float = LR, max_iter: int = MAX_ITER,
               tol: float = TOL, xp=np) -> dict:
    """Multinomial logistic regression, class-balanced, small L2, full-batch Adam.

    Returns the weights with the lowest penalised loss seen (Adam at a fixed
    step can climb back out of a minimum), their weighted training log-loss
    without the penalty, the iterations run and the iteration of the best.
    """
    n, d = X.shape
    y = xp.asarray(y).astype(xp.int64)
    counts = xp.bincount(y, minlength=k).astype(xp.float32)
    cw = n / (k * xp.maximum(counts, 1))
    sw = cw[y]
    sw = (sw / sw.sum()).astype(xp.float32)
    W = xp.zeros((d, k), xp.float32)
    b = xp.zeros(k, xp.float32)
    mW, vW, mb, vb = (xp.zeros_like(W), xp.zeros_like(W), xp.zeros_like(b), xp.zeros_like(b))
    rows = xp.arange(n)
    prev = float("inf")
    best = (float("inf"), float("nan"), W.copy(), b.copy(), 0)
    it = 0
    for it in range(1, max_iter + 1):
        Z = X @ W + b
        Z = Z - Z.max(axis=1, keepdims=True)
        E = xp.exp(Z)
        P = E / E.sum(axis=1, keepdims=True)
        ce = float(-(sw * xp.log(P[rows, y] + 1e-12)).sum())
        loss = ce + 0.5 * l2 * float((W ** 2).sum())
        if loss < best[0]:
            best = (loss, ce, W.copy(), b.copy(), it)
        if abs(prev - loss) < tol * max(1.0, abs(loss)):
            break
        prev = loss
        G = P
        G[rows, y] -= 1
        G *= sw[:, None]
        gW = X.T @ G + l2 * W
        gb = G.sum(axis=0)
        for p, g, m, v in ((W, gW, mW, vW), (b, gb, mb, vb)):
            m *= 0.9
            m += 0.1 * g
            v *= 0.999
            v += 0.001 * g * g
            p -= lr * (m / (1 - 0.9 ** it)) / (xp.sqrt(v / (1 - 0.999 ** it)) + 1e-8)
    return {"W": best[2], "b": best[3], "loss": best[1], "iterations": it, "best_at": best[4]}


def predict_proba(X, model: dict, xp=np):
    Z = X @ model["W"] + model["b"]
    Z = Z - Z.max(axis=1, keepdims=True)
    E = xp.exp(Z)
    return E / E.sum(axis=1, keepdims=True)


def fit_gauss(X, shrink: float = SHRINK, xp=np) -> dict:
    """One Gaussian, full covariance shrunk toward its diagonal."""
    mu = X.mean(axis=0)
    D = X - mu
    C = (D.T @ D) / max(len(X) - 1, 1)
    C = (1 - shrink) * C + shrink * xp.diag(xp.diag(C))
    return {"mu": mu, "P": xp.linalg.inv(C.astype(xp.float64)).astype(xp.float32)}


def mahalanobis(X, g: dict, xp=np):
    D = X - g["mu"]
    return xp.sqrt(xp.maximum(((D @ g["P"]) * D).sum(axis=1), 0))


def f0_score(f: dict) -> np.ndarray:
    """Loudness: the larger of the per-session ranks of RMS and of spectral flux."""
    rms = f["rms"].astype(np.float64)
    rms[~f["ok"]] = np.median(rms[f["ok"]]) if f["ok"].any() else 0
    nb = len(rms) // BLOCK
    p = (10 ** (rms[:nb * BLOCK] / 10)).reshape(nb, BLOCK).mean(axis=1)
    r = 10 * np.log10(p + 1e-12)
    bmean, _ = pool_blocks(median_removed(f, np), np)
    flux = np.concatenate([[0.0], np.maximum(bmean[1:] - bmean[:-1], 0).sum(axis=1)])
    return np.maximum(rank01(r), rank01(flux))


def bank_templates():
    """The cast-phase template of every cast in `audio-bank/0.2.0/demo_bank`, z-scored."""
    with contextlib.redirect_stdout(io.StringIO()):
        bank, A, med = audio_bank.load("demo_bank")
        refs = audio_bank.refs_from(bank, A, med)
    d = refs["phases"]["cast"]
    return d["z"].astype(np.float32), [bank[refs["rows"][j][0]]["key"] for j in d["idx"]]


def f1_score(f: dict, Z: np.ndarray, batch: int = 2048) -> np.ndarray:
    """The bank's `corr` at every 100 ms frame, the maximum over its templates.

    Each frame's query is the 0.6 s patch starting there, less the per-band
    median of the context `audio_bank` takes (5 s before to 3 s after the
    patch's centre, on a 1 s grid), undecodable frames at that median.
    """
    xp = gpu()
    L = xp.asarray(f["L"].astype(np.float32))
    ok = xp.asarray(f["ok"])
    n = len(L)
    nb = n // BLOCK
    pre, post = int(round(F1_CTX[0] / HOP)), int(round(F1_CTX[1] / HOP))
    na = int(math.ceil(n * HOP)) + 1
    med = xp.empty((na, BANDS), xp.float32)
    sess = xp.asarray(f["med"])
    for a0 in range(0, na, 128):
        a = xp.arange(a0, min(na, a0 + 128))
        idx = (a[:, None] * int(round(1 / HOP)) - pre) + xp.arange(pre + post)[None]
        inside = (idx >= 0) & (idx < n)
        ic = xp.clip(idx, 0, n - 1)
        good = inside & ok[ic]
        V = L[ic]
        V[~good] = xp.nan
        m = xp.nanmedian(V, axis=1)
        bad = ~good.any(axis=1)
        m[bad] = sess
        med[a0:a0 + len(a)] = m
    Zt = xp.asarray(Z).T
    out = np.full(nb, -1.0, np.float32)
    T = F1_T
    for j0 in range(0, nb, batch):
        j = xp.arange(j0, min(nb, j0 + batch))
        idx = j[:, None] * BLOCK + xp.arange(T)[None]
        inside = idx < n
        ic = xp.clip(idx, 0, n - 1)
        anchor = xp.clip(xp.rint(j * STEP + T * HOP / 2).astype(xp.int64), 0, na - 1)
        P = L[ic] - med[anchor][:, None, :]
        P[~(inside & ok[ic])] = 0
        P = P.reshape(len(j), -1)
        P = P - P.mean(axis=1, keepdims=True)
        P = P / (xp.linalg.norm(P, axis=1, keepdims=True) + 1e-9)
        out[j0:j0 + len(j)] = _np((P @ Zt).max(axis=1))
    _free_gpu()
    return out


def _window_index(nb: int, n_windows: int) -> np.ndarray:
    """The tagger window whose centre is nearest each 100 ms frame's centre."""
    c = (np.arange(nb) + 0.5) * STEP
    return np.clip(np.rint((c - AST_WIN / 2) / AST_STEP), 0, max(n_windows - 1, 0)).astype(int)


def ast_run(sid: str, model=None, batch: int = 48) -> Path:
    """The tagger's class posteriors and pooled embeddings for every 1 s window
    at a 0.5 s step, from the stored filterbank; cached under `ast/`."""
    import torch
    out = OUT / "ast" / f"{sid}.npz"
    if out.is_file():
        return out
    fb = np.load(FEAT / f"{sid}.ast.npz")["fbank"]
    per = int(round(AST_WIN / 0.01)) - 2          # 98 Kaldi frames in 1 s
    hop = int(round(AST_STEP / 0.01))
    nw = max(0, (len(fb) - per) // hop + 1)
    mean, std = -4.2677393, 4.5689974             # ASTFeatureExtractor's AudioSet stats
    probs = np.empty((nw, model.config.num_labels), np.float16)
    emb = np.empty((nw, model.config.hidden_size), np.float16)
    fbt = torch.from_numpy(fb.astype(np.float32)).cuda()
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
        for w0 in range(0, nw, batch):
            w = torch.arange(w0, min(nw, w0 + batch), device="cuda")
            idx = w[:, None] * hop + torch.arange(per, device="cuda")[None]
            x = torch.zeros((len(w), 1024, 128), device="cuda")
            x[:, :per] = fbt[idx]
            x = (x - mean) / (std * 2)
            o = model.audio_spectrogram_transformer(x)
            pooled = o.pooler_output if hasattr(o, "pooler_output") else o[1]
            logits = model.classifier(pooled)
            probs[w0:w0 + len(w)] = torch.sigmoid(logits.float()).cpu().numpy()
            emb[w0:w0 + len(w)] = pooled.float().cpu().numpy()
    del fbt
    torch.cuda.empty_cache()
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, probs=probs, emb=emb, t0_s=0.0, step_s=AST_STEP, win_s=AST_WIN,
                        model=AST_MODEL, version=VERSION)
    return out


#: The tagger's classes whose mass is background for the gate: gunfire,
#: footsteps and movement, silence, and generic ambience. Speech is not among
#: them: voice lines sit inside own-cast windows.
AST_BACKGROUND = ("Gunshot, gunfire", "Machine gun", "Fusillade", "Artillery fire", "Cap gun",
                  "Walk, footsteps", "Run", "Shuffle", "Silence", "Noise",
                  "Environmental noise", "Inside, small room", "Inside, large room or hall",
                  "Inside, public space", "Outside, urban or manmade",
                  "Outside, rural or natural", "Wind", "Rustle", "Hum", "Static", "Echo")


def _ast_model():
    import torch
    from transformers import ASTForAudioClassification
    with contextlib.redirect_stderr(io.StringIO()):
        m = ASTForAudioClassification.from_pretrained(AST_MODEL)
    return m.to("cuda" if torch.cuda.is_available() else "cpu").eval()


def ast_frames(sid: str, nb: int) -> dict:
    z = np.load(OUT / "ast" / f"{sid}.npz")
    return {"probs": z["probs"], "emb": z["emb"], "wi": _window_index(nb, len(z["probs"]))}


def save_scores(F: str, sid: str, score: np.ndarray, **info) -> None:
    (SCORES / F).mkdir(parents=True, exist_ok=True)
    np.savez_compressed(SCORES / F / f"{sid}.npz", score=np.asarray(score, np.float32),
                        info=json.dumps(info), version=VERSION)


def load_scores(F: str, sid: str) -> np.ndarray | None:
    p = SCORES / F / f"{sid}.npz"
    return np.load(p)["score"] if p.is_file() else None


def podcast_sessions() -> tuple[list[str], float | None]:
    """The sessions above the speech cut, and the cut, from the stored speech file."""
    p = REPORT / "speech.json"
    if not p.is_file():
        return [], None
    d = json.loads(p.read_text(encoding="utf-8"))
    return list(d["above_cut"]), d["cut"]


def cmd_fit(F: str, sessions: list[str], demos: list[str]) -> None:
    """Score every held-out match session with a model fitted on the others, and
    every demo with the model fitted on all the match sessions."""
    t0 = time.time()
    # cupy loaded first leaves torch's cuBLASLt uninitialised on this machine
    # (CUBLAS_STATUS_NOT_INITIALIZED), so the tagger runs without cupy.
    xp = np if F == "F4" else gpu()
    folds = {}
    if F == "F0":
        for s in sessions + demos:
            save_scores(F, s, f0_score(load_features(s)), fold="none: no fit")
    elif F == "F1":
        Z, keys = bank_templates()
        print(f"  {len(keys)} cast templates")
        for s in sessions + demos:
            t = time.time()
            # A demo's own casts sit in the bank: score it without them.
            own = np.array([k.split(":")[0] == s for k in keys])
            save_scores(F, s, f1_score(load_features(s), Z[~own]), fold="leave own templates out",
                        templates=int((~own).sum()), own_templates_dropped=int(own.sum()))
            print(f"  {s}: {time.time() - t:.1f} s ({int(own.sum())} own templates dropped)")
    elif F == "F4":
        model = _ast_model()
        names = [model.config.id2label[i] for i in range(model.config.num_labels)]
        bg = [names.index(c) for c in AST_BACKGROUND if c in names]
        missing = [c for c in AST_BACKGROUND if c not in names]
        if missing:
            print(f"  not in the tagger's classes: {missing}")
        for s in sessions + demos:
            t = time.time()
            ast_run(s, model)
            nb = len(np.load(FEAT / f"{s}.npz")["ok"]) // BLOCK
            a = ast_frames(s, nb)
            gate = 1.0 - a["probs"][:, bg].astype(np.float32).sum(axis=1)
            save_scores(F, s, gate[a["wi"]], fold="none: pretrained",
                        background_classes=[names[i] for i in bg])
            print(f"  {s}: {time.time() - t:.1f} s")
        del model
    else:
        base = {"F2": "F2", "F2c": "F2", "F3": "F3", "F4b": "F2"}[F]
        X, y = {}, {}
        for s in sessions + demos:
            f = load_features(s)
            nb = len(f["ok"]) // BLOCK
            if F == "F4b":
                a = ast_frames(s, nb)
                X[s] = xp.asarray(a["emb"][a["wi"]].astype(np.float32))
            else:
                X[s] = f2_features(f, xp)
            if s in sessions:
                y[s] = load_labels(s)[1]["cls"][:nb]
        pool = list(sessions)
        if F == "F2c":
            pod, cut = podcast_sessions()
            if cut is None:
                raise SystemExit("F2c needs report/speech.json: run F4 and `evaluate` first")
            pool = [s for s in sessions if s not in pod]
            print(f"  training without {pod} (speech fraction above {cut})")

        def fit_on(train):
            Xt = xp.concatenate([X[s][xp.asarray(y[s] >= 0)] for s in train])
            yt = np.concatenate([y[s][y[s] >= 0] for s in train])
            mu, sd = Xt.mean(axis=0), Xt.std(axis=0) + 1e-6
            Xt = (Xt - mu) / sd
            if base == "F2":
                m = fit_logreg(Xt, xp.asarray(yt), len(CLASSES), xp=xp)
                info = {"loss": round(m["loss"], 4), "iterations": m["iterations"],
                        "best_at": m["best_at"],
                        "frames": int(len(yt)),
                        "per_class": np.bincount(yt, minlength=len(CLASSES)).tolist()}
                return (lambda Xs: _np(predict_proba((Xs - mu) / sd, m, xp)[:, CAST])), info
            keep = yt != CAST
            g = fit_gauss(Xt[xp.asarray(keep)], xp=xp)
            info = {"frames": int(keep.sum())}
            return (lambda Xs: rank01(_np(mahalanobis((Xs - mu) / sd, g, xp)))), info

        for held in sessions:
            t = time.time()
            train = [s for s in pool if s != held]
            score_fn, info = fit_on(train)
            save_scores(F, held, score_fn(X[held]), fold="loso", train=train, **info)
            folds[held] = info
            _free_gpu()
            print(f"  {held}: {info} ({time.time() - t:.1f} s)")
        if demos:
            score_fn, info = fit_on(pool)
            for s in demos:
                save_scores(F, s, score_fn(X[s]), fold="all-matches", train=pool, **info)
        del X
        _free_gpu()
    wall = round(time.time() - t0, 1)
    (REPORT / "fits").mkdir(parents=True, exist_ok=True)
    (REPORT / "fits" / f"{F}.json").write_text(json.dumps(
        {"formulation": F, "sessions": sessions, "demos": demos, "folds": folds,
         "wall_s": wall, "threads": THREADS}, indent=1), encoding="utf-8")
    if len(sessions) > len(FAST_MATCHES):
        from reticle import metrics
        v = {"wall_s": wall, "threads": int(THREADS), "sessions": len(sessions),
             "demos": len(demos)}
        losses = [f["loss"] for f in folds.values() if "loss" in f]
        its = [f["iterations"] for f in folds.values() if "iterations" in f]
        if losses:
            v.update(loss_median=round(float(np.median(losses)), 4),
                     loss_max=round(float(max(losses)), 4),
                     iterations_median=int(np.median(its)), iterations_max=int(max(its)),
                     best_at_median=int(np.median([f["best_at"] for f in folds.values()])),
                     max_iter=MAX_ITER)
        frames = [f["frames"] for f in folds.values() if "frames" in f]
        if frames:
            v["train_frames_median"] = int(np.median(frames))
        metrics.record("audio_gate", part=f"fit-{F}", session="all-matches", values=v,
                       deps={"version": VERSION, "fit": metrics.fingerprint(
                           fit_logreg, fit_gauss, L2=L2, LR=LR, MAX_ITER=MAX_ITER, TOL=TOL,
                           SHRINK=SHRINK)},
                       context={"gpu": xp.__name__, "folds": folds})
    print(f"{F}: {len(sessions)} sessions, {len(demos)} demos in {time.time() - t0:.1f} s")


# ---------------------------------------------------------------------------
# Detections and scores
# ---------------------------------------------------------------------------

def detect(s: np.ndarray, tau: float, merge: int = MERGE_BLOCKS) -> tuple[np.ndarray, np.ndarray]:
    """(first frame, last frame) of each detection: frames at or above tau,
    joined when fewer than `merge` frames apart (closer than MERGE_S)."""
    idx = np.flatnonzero(s >= tau)
    if len(idx) == 0:
        return idx, idx
    cut = np.flatnonzero(np.diff(idx) >= merge)
    return idx[np.r_[0, cut + 1]], idx[np.r_[cut, len(idx) - 1]]


def recall_hits(onsets: np.ndarray, casts: np.ndarray, win=RECALL_WIN):
    """(hit per cast, onset minus drop of the nearest onset in the window, NaN if none)."""
    onsets = np.sort(np.asarray(onsets, float))
    casts = np.asarray(casts, float)
    hit = np.zeros(len(casts), bool)
    lag = np.full(len(casts), np.nan)
    lo = np.searchsorted(onsets, casts + win[0] - 1e-9, side="left")
    hi = np.searchsorted(onsets, casts + win[1] + 1e-9, side="right")
    for i in range(len(casts)):
        if hi[i] > lo[i]:
            d = onsets[lo[i]:hi[i]] - casts[i]
            hit[i] = True
            lag[i] = d[np.argmin(np.abs(d))]
    return hit, lag


def covered(on: np.ndarray, off: np.ndarray, casts: np.ndarray, win=RECALL_WIN) -> np.ndarray:
    """Whether some detection window overlaps each cast's recall window: the
    gate is open there even when the detection began earlier."""
    a, b = on * STEP, (off + 1) * STEP
    return np.array([bool(((a < c + win[1]) & (b > c + win[0])).any()) for c in casts], bool)


def rates(on: np.ndarray, live: np.ndarray, code: np.ndarray, live_min: float) -> tuple[float, float]:
    """(detections, unexplained detections) per live minute; onsets outside live time do not count."""
    inl = live[on]
    return (float(inl.sum()) / live_min if live_min else float("nan"),
            float((inl & (code[on] == 3)).sum()) / live_min if live_min else float("nan"))


def session_data(F: str, sid: str) -> dict | None:
    s = load_scores(F, sid)
    if s is None:
        return None
    rec, arr = load_labels(sid)
    nb = min(len(s), len(arr["cls"]))
    stalled = arr["stalled"][:nb]
    frame = lambda t: min(max(int(t / STEP), 0), nb - 1)
    casts = [c for c in rec["casts"] if not stalled[frame(c["t"])]]
    return {"sid": sid, "s": smooth(s[:nb]), "live": arr["live"][:nb], "code": arr["code"][:nb],
            "when": arr["when"][:nb], "speed": arr["speed"][:nb],
            "live_min": float(arr["live"][:nb].sum()) * STEP / 60.0,
            "all": np.array([c["t"] for c in casts]),
            "verified": np.array([c["t"] for c in casts if c["verified"]])}


def sweep(data: list[dict], taus: np.ndarray) -> dict:
    """Pooled curve over sessions: per tau, detections and unexplained per live
    minute and recall on the verified and on all casts."""
    live_min = sum(d["live_min"] for d in data)
    nv = sum(len(d["verified"]) for d in data)
    na = sum(len(d["all"]) for d in data)
    out = {k: np.zeros(len(taus)) for k in ("det", "unexpl", "rv", "ra")}
    for i, tau in enumerate(taus):
        det = un = hv = ha = 0
        for d in data:
            on, _off = detect(d["s"], tau)
            inl = d["live"][on]
            det += int(inl.sum())
            un += int((inl & (d["code"][on] == 3)).sum())
            t = on * STEP
            hv += int(recall_hits(t, d["verified"])[0].sum())
            ha += int(recall_hits(t, d["all"])[0].sum())
        out["det"][i] = det / live_min if live_min else np.nan
        out["unexpl"][i] = un / live_min if live_min else np.nan
        out["rv"][i] = hv / nv if nv else np.nan
        out["ra"][i] = ha / na if na else np.nan
    return {"tau": taus, **out, "live_min": live_min, "n_verified": nv, "n_all": na}


def taus_for(data: list[dict], n: int = 240) -> np.ndarray:
    pooled = np.concatenate([d["s"][d["live"]] for d in data])
    q = 1 - np.geomspace(0.6, 2e-5, n)
    return np.unique(np.quantile(pooled, q))


def at_rate(c: dict, rate: float) -> int | None:
    """The curve index with the highest verified recall at or below `rate` unexplained per minute."""
    ok = np.flatnonzero(c["unexpl"] <= rate + 1e-12)
    if len(ok) == 0:
        return None
    return int(ok[np.lexsort((c["ra"][ok], c["rv"][ok]))[-1]])


def at_recall(c: dict, r: float) -> int | None:
    """The curve index with the fewest unexplained per minute at verified recall >= r."""
    ok = np.flatnonzero(c["rv"] >= r - 1e-12)
    if len(ok) == 0:
        return None
    return int(ok[np.argmin(c["unexpl"][ok])])


def duty(data: list[dict], tau: float, pad: float = EXPLAIN_S) -> float:
    """Share of live frames inside a detection widened by `pad` seconds each side:
    the time a downstream reader behind the gate would still run."""
    k = int(round(pad / STEP))
    cov = liv = 0
    for d in data:
        on, off = detect(d["s"], tau)
        nb = len(d["s"])
        m = np.zeros(nb + 1, np.int64)
        np.add.at(m, np.clip(on - k, 0, nb), 1)
        np.add.at(m, np.clip(off + 1 + k, 0, nb), -1)
        w = np.cumsum(m)[:nb] > 0
        cov += int((w & d["live"]).sum())
        liv += int(d["live"].sum())
    return cov / liv if liv else float("nan")


def _r(x, n=3):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def summarise(F: str, data: list[dict], suffix: str = "") -> tuple[dict, dict]:
    """(metric values, curve) of one formulation over some sessions."""
    c = sweep(data, taus_for(data))
    v = {}
    for rate in RATES:
        i = at_rate(c, rate)
        v[f"{F}_recall_verified_at_{rate}{suffix}"] = _r(c["rv"][i]) if i is not None else 0.0
        v[f"{F}_recall_all_at_{rate}{suffix}"] = _r(c["ra"][i]) if i is not None else 0.0
    for rate in (1, 3, 10):
        i = at_rate(c, rate)
        v[f"{F}_duty_at_{rate}{suffix}"] = _r(duty(data, float(c["tau"][i]))) if i is not None else 0.0
    for r in FIXED_RECALL:
        i = at_recall(c, r)
        v[f"{F}_unexplained_per_min_at_recall_{str(r).replace('.', '_')}{suffix}"] = (
            _r(c["unexpl"][i], 2) if i is not None else None)
    i = at_recall(c, 0.7)
    v[f"{F}_duty_at_recall_0_7{suffix}"] = _r(duty(data, float(c["tau"][i]))) if i is not None else None
    i = at_rate(c, 3)
    tau = float(c["tau"][i]) if i is not None else float("inf")
    lags = []
    cov = []
    for d in data:
        on, off = detect(d["s"], tau)
        lags += list(recall_hits(on * STEP, d["all"])[1])
        cov += list(covered(on, off, d["verified"]))
    v[f"{F}_covered_verified_at_3{suffix}"] = _r(np.mean(cov)) if cov else None
    lags = np.array(lags)
    lags = lags[np.isfinite(lags)]
    v[f"{F}_onset_median_s{suffix}"] = _r(np.median(lags), 2) if len(lags) else None
    v[f"{F}_onset_abs_median_s{suffix}"] = _r(np.median(np.abs(lags)), 2) if len(lags) else None
    v[f"{F}_detections_per_min_at_3{suffix}"] = _r(c["det"][i], 2) if i is not None else None
    v[f"{F}_recall_verified_max{suffix}"] = _r(np.nanmax(c["rv"]))
    v[f"{F}_live_minutes{suffix}"] = _r(c["live_min"], 1)
    v[f"{F}_n_verified{suffix}"] = int(c["n_verified"])
    v[f"{F}_n_all{suffix}"] = int(c["n_all"])
    c["tau_at_3"] = tau
    return v, c


def write_detections(F: str, d: dict, tau: float) -> list[dict]:
    on, off = detect(d["s"], tau)
    rows = []
    for a, b in zip(on, off):
        k = int(d["code"][a])
        rows.append({"t_on_s": round(a * STEP, 2), "t_off_s": round((b + 1) * STEP, 2),
                     "peak": round(float(d["s"][a:b + 1].max()), 4),
                     "explanation": EXPLAIN[k],
                     "event_t_s": None if k == 3 else round(float(d["when"][a]), 3),
                     "live": bool(d["live"][a]),
                     "speed": None if not np.isfinite(d["speed"][a])
                     else round(float(d["speed"][a]), 1)})
    (DETS / F).mkdir(parents=True, exist_ok=True)
    (DETS / F / f"{d['sid']}.jsonl").write_text(
        "".join(json.dumps({"session_id": d["sid"], "formulation": F, "tau": round(tau, 5),
                            "version": VERSION, **r}) + "\n" for r in rows), encoding="utf-8")
    return rows


def demo_casts() -> dict[str, list[float]]:
    """The re-recorded demos' real casts: census true, the tray drop seen real."""
    d = json.loads((STORE / "analysis" / "demo-cast-census-rerecorded" / "casts.json")
                   .read_text(encoding="utf-8"))
    out: dict = {}
    for c in d["casts"]:
        if c.get("census") and c.get("tray_verdict") == "real":
            out.setdefault(c["sid"], []).append(c["t_ms"] / 1000.0)
    return out


def demo_drops() -> dict[str, list[float]]:
    """Every census drop time per demo (any verdict), to explain demo detections."""
    out: dict = {}
    for p in audio_bank.CENSUS_TABLES:
        if p.is_file():
            for c in json.loads(p.read_text(encoding="utf-8"))["casts"]:
                out.setdefault(c["sid"], []).append(c["t_ms"] / 1000.0)
    return out


def demo_eval(F: str, tau: float) -> dict:
    """Recall on the re-recorded demos' real casts and the tray-blind casts at tau."""
    v = {}
    casts, drops = demo_casts(), demo_drops()
    hits = n = det = un = 0
    minutes = 0.0
    for sid, ts in sorted(casts.items()):
        s = load_scores(F, sid)
        if s is None:
            continue
        s = smooth(s)
        on, _ = detect(s, tau)
        h, _lag = recall_hits(on * STEP, np.array(ts))
        hits += int(h.sum())
        n += len(ts)
        minutes += len(s) * STEP / 60.0
        det += len(on)
        known = drops.get(sid, []) + [t for _n, x, t, _w in TRAY_BLIND if x == sid]
        un += int((~_near_points(on * STEP, known, EXPLAIN_S + 1e-9)).sum())
    v[f"{F}_recall"] = _r(hits / n) if n else None
    v[f"{F}_n_casts"] = n
    v[f"{F}_detections_per_min"] = _r(det / minutes, 2) if minutes else None
    v[f"{F}_unexplained_per_min"] = _r(un / minutes, 2) if minutes else None
    tb = {}
    for name, sid, t, _why in TRAY_BLIND:
        s = load_scores(F, sid)
        if s is None:
            continue
        ss = smooth(s)
        on, _ = detect(ss, tau)
        h, lag = recall_hits(on * STEP, np.array([t]))
        j0, j1 = int((t + RECALL_WIN[0]) / STEP), int((t + RECALL_WIN[1]) / STEP) + 1
        rk = rank01(ss)
        tb[f"{F}_{name}_fired"] = int(h[0])
        tb[f"{F}_{name}_rank"] = _r(float(rk[j0:j1].max()))
        tb[f"{F}_{name}_lag_s"] = _r(lag[0], 2) if h[0] else None
    return {"transfer": v, "tray_blind": tb}


def smoke_eval(F: str, d: dict, tau: float) -> dict:
    """Stored smoke onsets on the smoke session with a detection onset within EXPLAIN_S."""
    from reticle.store import Store
    rows = Store(STORE).read_events("smoke", d["sid"])
    onsets = np.array([r["first_ms"] / 1000.0 for r in rows
                       if r.get("kind") == "track" and r.get("onset_status") == "observed"])
    on, _ = detect(d["s"], tau)
    t = on * STEP
    near = _near_points(onsets, t, EXPLAIN_S + 1e-9)
    nb = len(d["s"])
    fr = np.clip((onsets / STEP).astype(int), 0, nb - 1)
    inl = d["live"][fr]
    c = (np.arange(nb) + 0.5) * STEP
    chance = float(_near_points(c[d["live"]], t, EXPLAIN_S + 1e-9).mean()) if d["live"].any() else None
    return {"onsets": int(len(onsets)), "onsets_live": int(inl.sum()),
            f"{F}_fraction_within_1_5": _r(near.mean()) if len(onsets) else None,
            f"{F}_fraction_within_1_5_live": _r(near[inl].mean()) if inl.any() else None,
            f"{F}_chance_live": _r(chance)}


#: Stored minimap tables that date an onset on the match sessions. events/ability
#: holds only demos; events/minimap_dark holds 4 Hz masks whose onsets are the
#: smoke tracks; ability_shape fits start from the player's own tray casts.
WITNESSES = {
    "ping": "events/ping: every stored minimap ping of the player's team, its first frame",
    "ability_shape": "events/ability_shape: first found crop per own tray cast "
                     "(Regrowth ring, Recon Bolt ring, Hunter's Fury line)",
    "smoke": "events/smoke over events/minimap_dark: observed smoke-track onsets",
    "unnamed_ally_piece": "events/round_entity: first frame of each ally-family piece the "
                          "identity arbiter abstained on (rings, devices, fragments)",
}


def witness_onsets(sid: str) -> dict[str, np.ndarray]:
    """Onset times in seconds per witness table on one session."""
    from reticle.store import Store
    st = Store(STORE)
    out = {"ping": np.array([r["t_ms"] / 1000.0 for r in st.read_events("ping", sid)
                             if r.get("kind") != "coverage" and "t_ms" in r])}
    first: dict = {}
    for r in st.read_events("ability_shape", sid):
        if r.get("kind") == "shape" and r.get("found"):
            k = (r.get("ability"), r.get("cast_t_ms"))
            first[k] = min(first.get(k, np.inf), r["t_ms"] / 1000.0)
    out["ability_shape"] = np.array(sorted(first.values()))
    out["smoke"] = np.array([r["first_ms"] / 1000.0 for r in st.read_events("smoke", sid)
                             if r.get("kind") == "track" and r.get("onset_status") == "observed"])
    out["unnamed_ally_piece"] = np.array([
        r["first_seen_ms"] / 1000.0 for r in st.read_events_kind("round_entity", sid, "entity")
        if r.get("kind") == "entity" and r.get("family") == "ally"
        and r.get("identity_status") == "abstained"])
    return out


def witness_eval(F: str, data: list[dict], tau: float, onsets: dict) -> dict:
    """Per witness, pooled over sessions: the share of its live onsets with a
    detection onset within EXPLAIN_S, and the share of unexplained live
    detections with one of its onsets within EXPLAIN_S; each beside its chance
    rate, the share of live frames within EXPLAIN_S of the other side."""
    g = EXPLAIN_S + 1e-9
    acc: dict = {}
    cover = liv = 0
    for d in data:
        on, _ = detect(d["s"], tau)
        t = on * STEP
        nb = len(d["s"])
        c = (np.arange(nb) + 0.5) * STEP
        live_c = c[d["live"]]
        d_cover = int(_near_points(live_c, t, g).sum())
        cover += d_cover
        liv += len(live_c)
        un = t[d["live"][on] & (d["code"][on] == 3)]
        for w, ons in onsets[d["sid"]].items():
            a = acc.setdefault(w, dict.fromkeys(
                ("sessions", "n", "n_live", "near", "un", "un_near", "w_cover", "d_cover",
                 "liv"), 0))
            if len(ons) == 0:           # no table, or nothing in it: the session says nothing
                continue
            fr = np.clip((ons / STEP).astype(int), 0, nb - 1)
            lo = ons[d["live"][fr]]
            a["sessions"] += 1
            a["n"] += len(ons)
            a["n_live"] += len(lo)
            a["near"] += int(_near_points(lo, t, g).sum())
            a["un"] += len(un)
            a["un_near"] += int(_near_points(un, ons, g).sum())
            a["w_cover"] += int(_near_points(live_c, ons, g).sum())
            a["d_cover"] += d_cover
            a["liv"] += len(live_c)
    v = {f"{F}_detection_cover_live": _r(cover / liv) if liv else None}
    for w, a in acc.items():
        v[f"{w}_sessions"] = a["sessions"]
        v[f"{w}_onsets"] = a["n"]
        v[f"{w}_onsets_live"] = a["n_live"]
        v[f"{F}_{w}_onsets_near"] = _r(a["near"] / a["n_live"]) if a["n_live"] else None
        v[f"{F}_{w}_onsets_chance"] = _r(a["d_cover"] / a["liv"]) if a["liv"] else None
        v[f"{F}_{w}_unexplained_near"] = _r(a["un_near"] / a["un"]) if a["un"] else None
        v[f"{w}_cover_live"] = _r(a["w_cover"] / a["liv"]) if a["liv"] else None
    return v


# ---------------------------------------------------------------------------
# Speech: which sessions carry podcast audio
# ---------------------------------------------------------------------------

#: A session whose share of 1 s windows with a Speech posterior above 0.5 is
#: above this cut carries podcast audio (the player, 2026-09-26: continuous
#: speech mixed in for minutes at a time). The fractions run 0.05 to 0.22 with
#: no gap; the cut falls where the six sessions above it are the six whose
#: sustained-speech share (below) is at least 0.05, so both measures name the
#: same sessions. Set after the tagger ran on all twenty; not tuned on recall.
SPEECH_CUT: float | None = 0.18
SPEECH_P = 0.5
#: Sustained speech: a 60 s stretch in which more than 60% of the windows
#: carry a Speech posterior above 0.2. Speech under the game mix sits near
#: 0.5, so the stricter SPEECH_P misses a podcast's quiet stretches.
SUSTAIN_P, SUSTAIN_S, SUSTAIN_SHARE = 0.2, 60.0, 0.6


def speech_of(sid: str) -> dict | None:
    """Speech posterior per tagger window, its share above SPEECH_P, and its
    mean over buy-phase windows."""
    p = OUT / "ast" / f"{sid}.npz"
    if not p.is_file():
        return None
    z = np.load(p)
    from transformers import AutoConfig
    with contextlib.redirect_stderr(io.StringIO()):
        cfg = AutoConfig.from_pretrained(AST_MODEL)
    k = [cfg.id2label[i] for i in range(cfg.num_labels)].index("Speech")
    sp = z["probs"][:, k].astype(np.float32)
    out = {"speech": sp, "speech_fraction": _r(float((sp > SPEECH_P).mean()))}
    w = int(round(SUSTAIN_S / AST_STEP))
    if len(sp) >= w:
        k = np.convolve((sp > SUSTAIN_P).astype(float), np.ones(w) / w, mode="valid")
        out["speech_sustained_fraction"] = _r(float((k > SUSTAIN_SHARE).mean()))
    idx = np.flatnonzero(sp > SPEECH_P)
    if len(idx):                        # runs above SPEECH_P, gaps up to 1.5 s bridged
        cut = np.flatnonzero(np.diff(idx) > int(round(1.5 / AST_STEP)))
        run = np.r_[idx[cut], idx[-1]] - np.r_[idx[0], idx[cut + 1]]
        out["speech_longest_run_s"] = _r(float(run.max()) * AST_STEP + AST_WIN, 1)
    if (LABELS / f"{sid}.npz").is_file():
        arr = load_labels(sid)[1]
        wi = _window_index(len(arr["buy"]), len(sp))
        b = arr["buy"]
        out["speech_buy_mean"] = _r(float(sp[wi[b]].mean())) if b.any() else None
        out["speech_live_fraction"] = _r(float((sp[wi[arr["live"]]] > SPEECH_P).mean())) \
            if arr["live"].any() else None
    return out


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

#: Curve colours, the reference categorical order, one slot per formulation.
COLOURS = {"F0": "#2a78d6", "F1": "#eb6834", "F2": "#1baf7a", "F3": "#eda100",
           "F4": "#e87ba4", "F4b": "#008300", "F2c": "#4a3aa7"}


def _bgr(h: str) -> tuple[int, int, int]:
    return int(h[5:7], 16), int(h[3:5], 16), int(h[1:3], 16)


def plot_curves(curves: dict, key: str, title: str, out: Path) -> Path:
    """Recall against unexplained detections per live minute, log x, one line per formulation."""
    import cv2
    W, H, l, r, t, b = 960, 600, 80, 150, 50, 60
    img = np.full((H, W, 3), _bgr("#fcfcfb"), np.uint8)
    ink, ink2, grid = _bgr("#0b0b0b"), _bgr("#52514e"), _bgr("#e6e5e0")
    x0, x1 = math.log10(0.1), math.log10(100)
    px = lambda v: int(l + (math.log10(max(v, 0.1)) - x0) / (x1 - x0) * (W - l - r))
    py = lambda v: int(H - b - v * (H - t - b))
    font = cv2.FONT_HERSHEY_SIMPLEX
    for v in (0.1, 0.3, 1, 3, 10, 30, 100):
        cv2.line(img, (px(v), t), (px(v), H - b), grid, 1)
        cv2.putText(img, f"{v:g}", (px(v) - 10, H - b + 20), font, 0.45, ink2, 1, cv2.LINE_AA)
    for v in np.arange(0, 1.01, 0.2):
        cv2.line(img, (l, py(v)), (W - r, py(v)), grid, 1)
        cv2.putText(img, f"{v:.1f}", (l - 40, py(v) + 5), font, 0.45, ink2, 1, cv2.LINE_AA)
    for yy in range(t, H - b, 8):
        cv2.line(img, (px(3), yy), (px(3), yy + 4), ink2, 1)
    cv2.putText(img, title, (l, 30), font, 0.6, ink, 1, cv2.LINE_AA)
    cv2.putText(img, "unexplained detections per live minute (log)", (l + 220, H - 15), font,
                0.5, ink2, 1, cv2.LINE_AA)
    cv2.putText(img, "recall", (10, t - 12), font, 0.5, ink2, 1, cv2.LINE_AA)
    placed: list = []
    for n, (F, c) in enumerate(curves.items()):
        col = _bgr(COLOURS.get(F, "#52514e"))
        o = np.argsort(c["unexpl"])
        pts = np.array([[px(u), py(v)] for u, v in zip(c["unexpl"][o], c[key][o])
                        if np.isfinite(u) and np.isfinite(v) and u <= 100], np.int32)
        if len(pts) > 1:
            cv2.polylines(img, [pts], False, col, 2, cv2.LINE_AA)
            top = pts[np.argmin(pts[:, 1])]     # label the curve at its best recall
            x, y = min(int(top[0]) + 6, W - r + 6), int(top[1]) - 6
            while any(abs(x - a) < 40 and abs(y - c) < 14 for a, c in placed):
                y += 14                         # step below a label already there
            placed.append((x, y))
            cv2.putText(img, F, (x, y), font, 0.5, ink, 1, cv2.LINE_AA)
        cv2.line(img, (W - r + 30, t + 20 + 22 * n), (W - r + 60, t + 20 + 22 * n), col, 2)
        cv2.putText(img, F, (W - r + 66, t + 25 + 22 * n), font, 0.5, ink, 1, cv2.LINE_AA)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img)
    return out


def _deps() -> dict:
    from reticle import metrics
    return {"version": VERSION, "scoring": metrics.fingerprint(
        detect, recall_hits, sweep, summarise, smooth, explain_codes, SMOOTH=SMOOTH,
        MERGE_S=MERGE_S, RECALL_WIN=RECALL_WIN, EXPLAIN_S=EXPLAIN_S)}


def cmd_evaluate(formulations: list[str], sessions: list[str], dry: bool) -> dict:
    """Curves, operating points, per-session rates, demos, tray-blind casts and
    smokes for every formulation with stored scores; records the metrics."""
    from reticle import metrics
    rep = OUT / "report-dry" if dry else REPORT
    rep.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    speech = {s: speech_of(s)
              for s in list(sessions) + [d for d in EVAL_DEMOS if d not in sessions]}
    if any(v is not None for v in speech.values()):
        fr = {s: v["speech_fraction"] for s, v in speech.items() if v}
        above = sorted(s for s, v in fr.items() if SPEECH_CUT is not None and v > SPEECH_CUT)
        (rep / "speech.json").write_text(json.dumps(
            {"cut": SPEECH_CUT, "above_cut": above, "p": SPEECH_P,
             "sessions": {s: {k: v[k] for k in v if k != "speech"} for s, v in speech.items() if v}},
            indent=1), encoding="utf-8")
    pod, cut = podcast_sessions() if not dry else (
        json.loads((rep / "speech.json").read_text())["above_cut"] if (rep / "speech.json").is_file()
        else [], SPEECH_CUT)
    loso: dict = {"sessions": len(sessions)}
    per: dict = {s: {} for s in sessions}
    tb: dict = {}
    tr: dict = {}
    sm: dict = {}
    wit: dict = {}
    onsets = {s: witness_onsets(s) for s in sessions}
    curves, curves_clean = {}, {}
    for F in formulations:
        data = [d for d in (session_data(F, s) for s in sessions) if d is not None]
        if len(data) < len(sessions):
            print(f"{F}: scores for {len(data)} of {len(sessions)} sessions; skipped")
            continue
        v, c = summarise(F, data)
        loso.update(v)
        curves[F] = c
        if cut is not None and pod:
            clean = [d for d in data if d["sid"] not in pod]
            vc, cc = summarise(F, clean, "_clean")
            loso.update(vc)
            curves_clean[F] = cc
        tau = c["tau_at_3"]
        i07 = at_recall(c, 0.7)
        tau07 = float(c["tau"][i07]) if i07 is not None else None
        tau_r = {r: float(c["tau"][i]) for r in FIXED_RECALL
                 if (i := at_recall(c, r)) is not None}
        un_speed, live_speed = [], []
        sp_un, sp_live = [], []
        for d in data:
            on, _ = detect(d["s"], tau)
            det, un = rates(on, d["live"], d["code"], d["live_min"])
            h = recall_hits(on * STEP, d["all"])[0]
            p = per[d["sid"]]
            p["live_minutes"] = _r(d["live_min"], 1)
            p["casts"] = int(len(d["all"]))
            p["verified"] = int(len(d["verified"]))
            p[f"{F}_detections_per_min_at_3"] = _r(det, 2)
            p[f"{F}_unexplained_per_min_at_3"] = _r(un, 2)
            p[f"{F}_recall_all_at_3"] = _r(h.mean()) if len(h) else None
            for r, tr_ in tau_r.items():
                onr, _ = detect(d["s"], tr_)
                p[f"{F}_unexplained_per_min_at_recall_{str(r).replace('.', '_')}"] = _r(rates(
                    onr, d["live"], d["code"], d["live_min"])[1], 2)
            rows = write_detections(F, d, tau)
            un_speed += [r["speed"] for r in rows if r["live"] and r["explanation"] ==
                         "unexplained" and r["speed"] is not None]
            sp = d["speed"][d["live"]]
            live_speed.append(sp[np.isfinite(sp)])
            if speech.get(d["sid"]):
                # the tagger's Speech posterior at each unexplained onset and over live time
                ps = speech[d["sid"]]["speech"]
                wi = _window_index(len(d["s"]), len(ps))
                u = on[d["live"][on] & (d["code"][on] == 3)]
                sp_un.append(ps[wi[u]] > SPEECH_P)
                sp_live.append(ps[wi[d["live"]]] > SPEECH_P)
        ls = np.concatenate(live_speed) if live_speed else np.array([])
        loso[f"{F}_unexplained_speed_median"] = _r(np.median(un_speed), 1) if un_speed else None
        loso["live_speed_median"] = _r(np.median(ls), 1) if len(ls) else None
        loso[f"{F}_live_moving_fraction"] = _r(float((ls > 5).mean())) if len(ls) else None
        loso[f"{F}_unexplained_moving_fraction"] = _r(float(
            (np.array(un_speed) > 5).mean())) if un_speed else None
        if sp_un:
            loso[f"{F}_unexplained_speech_fraction"] = _r(float(np.concatenate(sp_un).mean()))
            loso["live_speech_fraction"] = _r(float(np.concatenate(sp_live).mean()))
        de = demo_eval(F, tau)
        tr.update(de["transfer"])
        tb.update(de["tray_blind"])
        smk = next((d for d in data if d["sid"] == SMOKE_SESSION), None)
        if smk is not None:
            sm.update(smoke_eval(F, smk, tau))
        wit.update(witness_eval(F, data, tau, onsets))
        (rep / f"{F}.json").write_text(json.dumps({
            "formulation": F, "version": VERSION, "sessions": [d["sid"] for d in data],
            "tau_at_3": tau, "tau_at_recall_0_7": tau07, "values": v,
            "curve": {k: [float(x) for x in c[k]] for k in ("tau", "det", "unexpl", "rv", "ra")},
            "per_session": {d["sid"]: {k: x for k, x in per[d["sid"]].items()
                                       if k.startswith(F + "_") or "_" not in k[:3]}
                            for d in data},
            "demo_transfer": de["transfer"], "tray_blind": de["tray_blind"]}, indent=1),
            encoding="utf-8")
        print(f"{F}: recall verified @1/3/10 {v[f'{F}_recall_verified_at_1']}/"
              f"{v[f'{F}_recall_verified_at_3']}/{v[f'{F}_recall_verified_at_10']}, all @3 "
              f"{v[f'{F}_recall_all_at_3']}, unexplained at recall 0.7 "
              f"{v[f'{F}_unexplained_per_min_at_recall_0_7']}, onset "
              f"{v[f'{F}_onset_median_s']} s, demos {de['transfer'][f'{F}_recall']}")
    if pod:
        # P7: do the podcast sessions carry the most unexplained detections at fixed recall?
        for F in curves:
            key = f"{F}_unexplained_per_min_at_recall_0_5"
            vals = {s: per[s].get(key) for s in sessions if per[s].get(key) is not None}
            if len(vals) < len(sessions):
                continue                # the gate never reaches recall 0.5
            top = sorted(vals, key=lambda s: -vals[s])[:len(pod)]
            loso[f"{F}_podcast_in_top_k"] = sum(s in pod for s in top)
            sf = [speech[s]["speech_fraction"] for s in vals if speech.get(s)]
            uv = [vals[s] for s in vals if speech.get(s)]
            if len(sf) > 2:
                rs = lambda a: np.argsort(np.argsort(a)).astype(float)
                loso[f"{F}_speech_spearman"] = _r(float(np.corrcoef(rs(sf), rs(uv))[0, 1]))
        loso["podcast_k"] = len(pod)
    main = [F for F in curves if F != "F2c"]
    if main:
        best = max(main, key=lambda F: (loso[f"{F}_recall_verified_at_3"],
                                        loso[f"{F}_recall_all_at_3"]))
        loso["best_formulation"] = best
    if curves:
        plot_curves(curves, "rv", "Recall on the verified casts, leave one session out",
                    rep / "curves_verified.png")
        plot_curves(curves, "ra", "Recall on all tray casts, leave one session out",
                    rep / "curves_all.png")
    if curves_clean:
        plot_curves(curves_clean, "rv", f"Recall on the verified casts, sessions at or below "
                    f"speech fraction {cut}", rep / "curves_verified_clean.png")
    summary = {"version": VERSION, "sessions": sessions, "loso": loso, "per_session": per,
               "tray_blind": tb, "demo_transfer": tr, "smokes": sm, "witness": wit,
               "speech": {s: {k: v[k] for k in v if k != "speech"} for s, v in speech.items() if v},
               "podcast_sessions": pod, "speech_cut": cut, "wall_s": round(time.time() - t0, 1)}
    (rep / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    if not dry:
        deps = _deps()
        ctx = {"sessions": sessions, "formulations": list(curves), "podcast": pod, "cut": cut}
        metrics.record("audio_gate", part="loso", session="all-matches", values=loso, deps=deps,
                       context=ctx)
        for s, p in per.items():
            if p:
                metrics.record("audio_gate", part="loso", session=s, values=p, deps=deps)
        if tb:
            metrics.record("audio_gate", part="tray-blind", session="demos", values=tb, deps=deps,
                           context={"casts": [list(x) for x in TRAY_BLIND]})
        if tr:
            metrics.record("audio_gate", part="demo-transfer", session="demos", values=tr,
                           deps=deps, context={"demos": sorted(demo_casts())})
        if sm:
            metrics.record("audio_gate", part="smokes", session=SMOKE_SESSION, values=sm,
                           deps=deps)
        if wit:
            metrics.record("audio_gate", part="witness", session="all-matches", values=wit,
                           deps={**deps, "witness": metrics.fingerprint(witness_onsets,
                                                                        witness_eval)},
                           context={"witnesses": WITNESSES, "operating_point": "3 per live minute",
                                    "sessions": sessions})
        for s, v in speech.items():
            if v:
                metrics.record("audio_gate", part="speech", session=s,
                               values={k: v[k] for k in v if k != "speech"},
                               deps={"version": VERSION, "model": AST_MODEL, "p": SPEECH_P})
    print(f"evaluated in {time.time() - t0:.1f} s -> {rep}")
    return summary


# ---------------------------------------------------------------------------
# Review sheet
# ---------------------------------------------------------------------------

def spectrogram_png(sid: str, t: float, out: Path, before: float = 1.5, after: float = 3.0) -> Path:
    """The median-removed log-mel from `before` s ahead of t to `after` s past it;
    low bands at the bottom, the onset marked, ticks every 0.5 s."""
    import cv2
    f = load_features(sid)
    W = median_removed(f, np)
    k0, k1 = int((t - before) / HOP), int((t + after) / HOP)
    seg = np.zeros((k1 - k0, BANDS), np.float32)
    a, b = max(k0, 0), min(k1, len(W))
    seg[a - k0:b - k0] = W[a:b]
    v = np.clip((seg + 6.0) / 36.0, 0, 1).T[::-1]
    img = cv2.applyColorMap((v * 255).astype(np.uint8), cv2.COLORMAP_MAGMA)
    img = cv2.resize(img, (seg.shape[0] * 2, BANDS * 3), interpolation=cv2.INTER_NEAREST)
    x = int(before / HOP) * 2
    cv2.line(img, (x, 0), (x, img.shape[0]), (255, 0, 255), 1)
    for k in range(0, seg.shape[0] + 1, 50):
        cv2.line(img, (k * 2, img.shape[0] - 8), (k * 2, img.shape[0]), (200, 200, 200), 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img)
    return out


def cmd_review(F: str, top: int, sessions: list[str]) -> Path:
    """The top unexplained live detections by peak, with what the player needs to listen."""
    import html
    rows = []
    for sid in sessions:
        p = DETS / F / f"{sid}.jsonl"
        if not p.is_file():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            if r["live"] and r["explanation"] == "unexplained":
                rows.append(r)
    rows.sort(key=lambda r: -r["peak"])
    rows = rows[:top]
    out = REVIEW / F
    out.mkdir(parents=True, exist_ok=True)
    sp_cache: dict = {}
    items = []
    for n, r in enumerate(rows):
        sid, t = r["session_id"], r["t_on_s"]
        path = _manifest(sid)["source"]["path"]
        if sid not in sp_cache:
            sp_cache[sid] = speech_of(sid)
        sp = sp_cache[sid]
        p_speech = None
        if sp is not None:
            wi = int(np.clip(round((t + STEP / 2 - AST_WIN / 2) / AST_STEP), 0, len(sp["speech"]) - 1))
            p_speech = round(float(sp["speech"][wi]), 3)
        png = spectrogram_png(sid, t, out / f"{n:03d}_{sid}_{t:.1f}.png")
        ss = max(0.0, round(t - 0.5, 1))
        items.append({"rank": n + 1, "session_id": sid, "capture": path, "t_on_s": t,
                      "clock": f"{int(t // 60)}:{t % 60:04.1f}", "t_off_s": r["t_off_s"],
                      "peak": r["peak"], "speed": r["speed"], "speech_p": p_speech,
                      "tag": "speech" if p_speech is not None and p_speech > SPEECH_P else "",
                      "png": png.name, "play": f'ffplay -ss {ss} -t 3 -nodisp "{path}"'})
    (out / "sheet.json").write_text(json.dumps(items, indent=1), encoding="utf-8")
    from reticle import metrics
    metrics.record("audio_gate", part=f"review-{F}", session="all-matches",
                   values={"rows": len(items), "speech_tagged": sum(it["tag"] == "speech"
                                                                    for it in items),
                           "sessions": len({it["session_id"] for it in items})},
                   deps={"version": VERSION, "top": top},
                   context={"sheet": str(out / "sheet.json")})
    trs = "\n".join(
        f"<tr><td>{it['rank']}</td><td>{it['session_id']}<br><small>{html.escape(it['capture'])}"
        f"</small></td><td>{it['t_on_s']:.1f} s<br>{it['clock']}</td><td>{it['peak']}</td>"
        f"<td>{'' if it['speed'] is None else it['speed']}</td><td><b>{it['tag']}</b> "
        f"{'' if it['speech_p'] is None else it['speech_p']}</td>"
        f"<td><img src=\"{it['png']}\"></td><td><code>{html.escape(it['play'])}</code></td></tr>"
        for it in items)
    (out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Unexplained sounds</title>"
        "<style>body{font:14px sans-serif;background:#fcfcfb;color:#0b0b0b;margin:16px}"
        "td{border-bottom:1px solid #e6e5e0;padding:6px;vertical-align:top}"
        "code{font-size:12px;user-select:all}</style>"
        f"<h1>Unexplained detections, {F}, top {len(items)} by peak</h1>"
        "<p>Each row is a live-round moment the gate fired with no own cast, own gunfire "
        "or known event within 1.5 s. The spectrogram runs 1.5 s before to 3 s after the "
        "onset (magenta). Rows tagged <b>speech</b> have a Speech posterior above 0.5 and "
        "can be skipped. Paste the command to hear 3 s from half a second before the onset. "
        "Say what each sound is.</p><table><tr><th>#</th><th>session</th><th>onset</th>"
        f"<th>peak</th><th>speed</th><th>speech</th><th>spectrogram</th><th>listen</th></tr>{trs}"
        "</table>", encoding="utf-8")
    print(f"{len(items)} rows -> {out / 'index.html'}")
    return out / "index.html"


# ---------------------------------------------------------------------------
# The doc's Results section
# ---------------------------------------------------------------------------

def _latest() -> dict:
    from reticle import metrics, quoted
    idx = quoted.latest_pass(metrics.load(STORE / "notes" / "metrics.jsonl"))
    return {(series.split("/", 1)[1], s): row["values"] for (series, s), row in idx.items()
            if series.startswith("audio_gate/")}


def tok(rows: dict, part: str, session: str, key: str) -> str:
    """The value as a citation of its recorded run, or a dash where none exists."""
    v = rows.get((part, session), {}).get(key)
    if v is None:
        return "-"
    return f"[metric:audio_gate/{part}@{session}#{key}={v}]"


#: The Results section's closing list: what this prototype leaves undone.
NOT_DONE = (
    "No events, labels or `reticle/` module: the gate stays a prototype until the player "
    "has judged the review sheet.",
    "No verdict on P0 to P7; the measured values stand beside them for the player.",
    "No recall per agent or per ability, and no threshold per session or per map: one "
    "pooled threshold per gate.",
    "Teammates' and enemies' abilities stay unlabelled inside background; the witness "
    "table bounds their share of the unexplained detections only where a minimap table "
    "dates them.",
    "F4 was not fine-tuned, and its background classes are a fixed list, not fitted.",
    "No audio left a capture: no WAV and no clips; the review sheet plays the source with "
    "`ffplay`. No video was decoded and no `roi_cache` was read.",
    "Nothing was appended to the store's `notes/predictions.jsonl`.",
    "The tests run under `unittest`; the venv has no pytest.",
)


def cmd_report() -> None:
    """Rewrite the Results section of docs/AUDIO_GATE.md from the recorded runs;
    every figure is a citation of the run that produced it."""
    from reticle.ability_timeline import DEATH_LEAD_MS
    rows = _latest()
    summ = json.loads((REPORT / "summary.json").read_text(encoding="utf-8"))
    L = rows.get(("loso", "all-matches"), {})
    A = "all-matches"
    t = lambda part, key, session=A: tok(rows, part, session, key)
    best = L.get("best_formulation")
    forms = [F for F in (*FORMULATIONS, "F2c") if f"{F}_recall_verified_at_3" in L]
    pod, cut = summ.get("podcast_sessions") or [], summ.get("speech_cut")
    sessions = summ["sessions"]
    out = ["## Results", "",
           "Generated by `python prototypes/audio_gate.py report` from the runs recorded in "
           f"the store's `notes/metrics.jsonl` (`{VERSION}`); every figure cites its run. "
           "Outputs sit under `<store>/analysis/audio-gate/0.1.0/`.", ""]

    fits = [F for F in forms if (f"fit-{F}", A) in rows]
    out += ["### What ran", "",
            f"- {t('labels', 'sessions')} match sessions, {t('labels', 'live_minutes')} live "
            f"minutes (the player alive in a live round), {t('labels', 'casts')} own casts, "
            f"{t('labels', 'casts_verified')} of them labelled by the player, and "
            f"{t('labels', 'gunfire_windows')} own-gunfire windows. The player casts "
            f"{t('labels', 'casts_per_live_min')} times per live minute.",
            "- Wall time per formulation, one heavy process, GPU for the fits and the tagger: "
            + ", ".join(f"{F} {t(f'fit-{F}', 'wall_s')} s" for F in fits)
            + f"; CPU threads {t('fit-F2', 'threads')}.",
            "- F2's logistic regression per fold: log-loss median "
            f"{t('fit-F2', 'loss_median')}, max {t('fit-F2', 'loss_max')}; iterations "
            f"median {t('fit-F2', 'iterations_median')}, max {t('fit-F2', 'iterations_max')} "
            f"of {t('fit-F2', 'max_iter')}. Adam at a fixed step climbs back out of its "
            "minimum, so each fold keeps its lowest-loss iterate, found at a median iteration "
            f"of {t('fit-F2', 'best_at_median')}. A first run capped at 3000 iterations "
            "stopped short: on the fold that holds out `9acf02f98283` the loss fell from "
            f"{tok(rows, 'fit-check', '9acf02f98283', 'loss_at_3000')} to "
            f"{tok(rows, 'fit-check', '9acf02f98283', 'loss_converged')} by convergence, and "
            "the held-out cast posteriors of the two fits rank-correlate at "
            f"{tok(rows, 'fit-check', '9acf02f98283', 'held_out_rank_corr')}.", ""]

    out += ["### Method as fixed", "",
            "- Front end: `audio_channel`'s, 64 mel bands 60 Hz to 16 kHz, NFFT 2048 at the "
            "native 48 kHz, 10 ms hop, stereo averaged, per-band session median removed. "
            "PyAV demuxes the audio stream once and places it by pts. A frame is 100 ms: "
            "the mean and the max over ten 10 ms rows.",
            f"- Own gunfire: two consecutive 2 Hz HUD samples at most {HUD_MAX_GAP_S} s apart, "
            f"both with `bottom_confidence` at or above {HUD_MIN_CONF} (the reader's threshold) "
            "and a read magazine; the magazine falls and the reserve holds, so the shots fall "
            "in (t_prev, t_cur]. A reload or a swap moves the reserve and is not fire.",
            "- Live time is `round_live` and `post_plant` from gametime, ended "
            f"{DEATH_LEAD_MS / 1000:.0f} s before the player's first death in the round "
            "(`rounds.player_death_times`); stalls are excluded everywhere. Frames after the "
            "death stay unlabelled: the tray then shows a spectated teammate's kit "
            "[domain:hud/tray-after-player-death], so no drop there is the player's cast.",
            f"- Own cast: {CAST_WIN[0]} s to +{CAST_WIN[1]} s around the drop, including the "
            "player's labels. Background keeps "
            f"{BG_GAP_CAST:.0f} s from casts and from every tray drop in live time, "
            f"{BG_GAP_FIRE:.0f} s from own gunfire, {BG_GAP_OTHER:.0f} s from known others and "
            f"{BG_GAP_DEATH:.0f} s from other deaths. Known others add the barrier drop "
            "(gametime `t_live`) and the tray drops the reader refused as forced or "
            "co-occurring.",
            f"- A detection is explained when its onset lies within {EXPLAIN_S} s of an own "
            "cast, else own gunfire, else a known other; only onsets in live time count "
            "toward rates.",
            f"- Scores are smoothed over {SMOOTH} frames; frames at or above a threshold merge "
            f"when closer than {MERGE_S} s. The threshold sweeps 240 quantiles of the pooled "
            "live scores; recall and rates pool the held-out sessions. \"At 3/min\" is the "
            "threshold with the highest verified recall at or below 3 unexplained per live "
            "minute; \"at recall r\" is the one with the fewest unexplained at verified "
            "recall r or more. Recall falls again at low thresholds, where merged detections "
            "swallow casts, so a gate can peak below r (column \"at best\"). "
            f"A cast counts when an onset lies {RECALL_WIN[0]} s to "
            f"+{RECALL_WIN[1]} s from its drop.",
            f"- Duty: the share of live time within {EXPLAIN_S} s of a detection window, the "
            "time a pass behind the gate would still run. \"Inside a window\" counts a cast "
            "whose recall window overlaps a detection window, however early it began.",
            "- F0: the larger of the per-session ranks of frame RMS and spectral flux. "
            "F1: the bank's cast-phase templates (`audio_bank.refs_from`), 0.6 s patches "
            "z-scored against an 8 s local median, the maximum correlation at each 100 ms frame. "
            f"F2: 192 features per frame (mean, max and first-difference spread per band over "
            f"{CTX_BLOCKS} centred frames), z-scored with the training fold, a multinomial "
            f"logistic regression, class-balanced, L2 {L2}, Adam on the GPU. F3: one Gaussian "
            f"over the gunfire, background and buy frames, covariance shrunk {SHRINK} toward its "
            "diagonal, Mahalanobis distance ranked within the held-out session. F4: "
            f"`{AST_MODEL}` on {AST_WIN:.0f} s windows at a {AST_STEP} s step over a 16 kHz "
            "Kaldi filterbank; the gate is 1 minus the summed background posteriors "
            f"({len(AST_BACKGROUND)} classes named in `AST_BACKGROUND`; Speech is not one). "
            "F4b: F2's classifier on F4's 768-d pooled embeddings. F2c: F2 with the podcast "
            "sessions left out of every training fold, scoring every session.", ""]

    def table(cols, sfx=""):
        """One row per gate; `cols` pairs a header with a loso key stem."""
        rows_ = [f"| Gate | {' | '.join(h for h, _k in cols)} |",
                 "|---|" + "---|" * len(cols)]
        for F in forms:
            rows_.append(f"| {F} | " + " | ".join(t("loso", f"{F}_{k}{sfx}") for _h, k in cols)
                         + " |")
        return rows_
    recall_cols = [("Verified recall at 1/min", "recall_verified_at_1"),
                   ("at 3/min", "recall_verified_at_3"),
                   ("at 10/min", "recall_verified_at_10"),
                   ("at best", "recall_verified_max"),
                   ("All casts at 3/min", "recall_all_at_3"),
                   ("Verified casts inside a window at 3/min", "covered_verified_at_3")]
    cost_cols = [("Unexplained/min at recall 0.5", "unexplained_per_min_at_recall_0_5"),
                 ("at recall 0.7", "unexplained_per_min_at_recall_0_7"),
                 ("Duty at 1/min", "duty_at_1"), ("at 3/min", "duty_at_3"),
                 ("at 10/min", "duty_at_10"), ("at recall 0.7", "duty_at_recall_0_7"),
                 ("Onset minus drop at 3/min, median (s)", "onset_median_s")]
    clean_cols = [("Verified recall at 3/min", "recall_verified_at_3"),
                  ("at best", "recall_verified_max"),
                  ("All casts at 3/min", "recall_all_at_3"),
                  ("Unexplained/min at recall 0.5", "unexplained_per_min_at_recall_0_5"),
                  ("at recall 0.7", "unexplained_per_min_at_recall_0_7"),
                  ("Duty at 3/min", "duty_at_3")]
    out += ["### Formulations, leave one session out", "",
            f"Over all {t('loso', 'sessions')} sessions ({t('loso', 'F2_n_verified')} verified "
            f"casts, {t('loso', 'F2_n_all')} in all, stalled casts excluded). A dash marks a "
            f"point the gate never reaches. The best gate by verified recall at 3/min is {best}.",
            "", "Recall:", ""]
    out += table(recall_cols) + ["", "Cost:", ""] + table(cost_cols) + [""]
    if pod:
        out += [f"Over the sessions at or below speech fraction {cut}, without "
                f"{', '.join('`' + s + '`' for s in pod)}:", ""]
        out += table(clean_cols, "_clean") + [""]
    out += ["Transfer, fitted on all matches and scored on the re-recorded demos' real casts "
            "at each gate's 3/min threshold: " + ", ".join(
                f"{F} {tok(rows, 'demo-transfer', 'demos', f'{F}_recall')} of "
                f"{tok(rows, 'demo-transfer', 'demos', f'{F}_n_casts')}" for F in forms)
            + ". F1 scores each demo without that demo's own templates.",
            ""]

    out += ["### Curves", ""] + [
        f"- `<store>/analysis/audio-gate/0.1.0/report/{n}`: {d}" for n, d in (
            ("curves_verified.png", "verified recall against unexplained per live minute, "
                                    "all sessions"),
            ("curves_all.png", "recall on all tray casts, all sessions"),
            ("curves_verified_clean.png", "verified recall, the sessions at or below the "
                                          "speech cut"))
        if (REPORT / n).is_file()] + [
        f"- `<store>/analysis/audio-gate/0.1.0/review/{best}/index.html`: the top unexplained "
        f"detections of {best}, each with its capture path, time, spectrogram and an `ffplay` "
        "command.", ""]

    Fb = best or "F2"
    runs_ = {s: rows.get(("speech", s), {}).get("speech_longest_run_s") for s in sessions}
    runs_ = {s: v for s, v in runs_.items() if v is not None}
    s_long = max(runs_, key=runs_.get) if runs_ else None
    longest = (f"{tok(rows, 'speech', s_long, 'speech_longest_run_s')} s, on `{s_long}`"
               if s_long else "-")
    out += ["### Per session", "",
            f"Sorted by speech fraction, the share of {AST_WIN:.0f} s tagger windows with a "
            f"Speech posterior above {SPEECH_P}. Sustained speech is the share of {SUSTAIN_S:.0f} s "
            f"stretches in which more than {SUSTAIN_SHARE:.0%} of the windows carry a Speech "
            f"posterior above {SUSTAIN_P}. The fractions form a continuum with no gap; the "
            f"stated cut, {cut}, puts above it exactly the sessions whose sustained speech is "
            "0.05 or more, so both measures name the same sessions, marked (podcast). No "
            f"session holds a Speech posterior above {SPEECH_P} for minutes at a time: the "
            f"longest run, gaps up to 1.5 s bridged, lasts {longest}. The sustained stretches "
            f"hover around {SPEECH_P}, which splits them into short runs. The demos, which "
            "carry no podcast, read "
            + ", ".join(f"{tok(rows, 'speech', s, 'speech_fraction')}" for s in EVAL_DEMOS
                        if ("speech", s) in rows)
            + ". Rates are at each gate's pooled thresholds.",
            "",
            f"| Session | Speech fraction | Sustained speech | Speech posterior in buy phase, "
            "mean | Live min | "
            f"Casts | {Fb} unexplained/min | {Fb} recall, all casts | {Fb} unexplained/min at "
            "recall 0.5 |",
            "|---|---|---|---|---|---|---|---|---|"]
    sp = {s: rows.get(("speech", s), {}).get("speech_fraction") for s in sessions}
    for s in sorted(sessions, key=lambda s: -(sp[s] if sp[s] is not None else -1)):
        mark = " (podcast)" if s in pod else ""
        out.append(f"| `{s}`{mark} | {tok(rows, 'speech', s, 'speech_fraction')} | "
                   f"{tok(rows, 'speech', s, 'speech_sustained_fraction')} | "
                   f"{tok(rows, 'speech', s, 'speech_buy_mean')} | "
                   f"{tok(rows, 'loso', s, 'live_minutes')} | {tok(rows, 'loso', s, 'casts')} | "
                   f"{tok(rows, 'loso', s, f'{Fb}_unexplained_per_min_at_3')} | "
                   f"{tok(rows, 'loso', s, f'{Fb}_recall_all_at_3')} | "
                   f"{tok(rows, 'loso', s, f'{Fb}_unexplained_per_min_at_recall_0_5')} |")
    out += [""]

    W = rows.get(("witness", A), {})
    ws = [w for w in WITNESSES if f"{w}_onsets" in W]
    out += ["### Witnesses", "",
            f"Stored minimap onsets against {Fb}'s detections at its 3/min threshold. "
            "Agreement is consistency, not accuracy: a detection beside a ping shows that "
            "two channels coincide, not that either is right. Each chance column is the share "
            f"of live time within {EXPLAIN_S} s of the other side. `events/ability` holds only "
            "demos, and `events/minimap_dark` holds masks whose onsets are the smoke tracks, "
            "so neither adds a row.", "",
            "| Witness | Sessions | Live onsets | Onsets with a detection | Chance | "
            "Unexplained detections with an onset | Chance |", "|---|---|---|---|---|---|---|"]
    for w in ws:
        out.append(f"| {WITNESSES[w]} | "
                   f"{t('witness', f'{w}_sessions')} | {t('witness', f'{w}_onsets_live')} | "
                   f"{t('witness', f'{Fb}_{w}_onsets_near')} | "
                   f"{t('witness', f'{Fb}_{w}_onsets_chance')} | "
                   f"{t('witness', f'{Fb}_{w}_unexplained_near')} | "
                   f"{t('witness', f'{w}_cover_live')} |")
    out += ["", f"The tagger's Speech posterior exceeds {SPEECH_P} at "
            f"{t('loso', f'{Fb}_unexplained_speech_fraction')} of {Fb}'s unexplained onsets at "
            f"3/min, against {t('loso', 'live_speech_fraction')} of live time; "
            f"{tok(rows, f'review-{Fb}', A, 'speech_tagged')} of the "
            f"{tok(rows, f'review-{Fb}', A, 'rows')} rows on the review sheet carry the "
            "speech tag. The tagger and the gate hear the same audio, so this too is "
            "consistency, not a second witness.", ""]

    S = SMOKE_SESSION
    rb = "run_it_back"
    rg = "regrowth_fc02a2c1ac01"
    out += ["### Outcomes", "",
            "Measured values beside each prediction; the player judges them.", "",
            f"- **P0.** Gunfire frames carry more 1 to 4 kHz energy than background on "
            f"{t('p0', 'sessions_louder')} of {t('p0', 'sessions_with_gunfire')} sessions with "
            f"gunfire; the median difference is {t('p0', 'diff_db_median')} dB and the least "
            f"{t('p0', 'diff_db_min')} dB.",
            "- **P1.** " + (
                f"F0 needs {t('loso', 'F0_unexplained_per_min_at_recall_0_8')} unexplained "
                "per minute for verified recall 0.8"
                if L.get("F0_unexplained_per_min_at_recall_0_8") is not None
                else "F0 never reaches verified recall 0.8")
            + f"; its verified recall at 20/min is {t('loso', 'F0_recall_verified_at_20')}, "
            f"its maximum {t('loso', 'F0_recall_verified_max')}, and it needs "
            f"{t('loso', 'F0_unexplained_per_min_at_recall_0_7')} unexplained per minute for "
            "recall 0.7.",
            f"- **P2.** F2's verified recall at 3/min is {t('loso', 'F2_recall_verified_at_3')}"
            + (f"; without the podcast sessions {t('loso', 'F2_recall_verified_at_3_clean')}; "
               f"F2c's {t('loso', 'F2c_recall_verified_at_3')}" if pod else "") + ".",
            f"- **P3.** F3's verified recall at 5/min is {t('loso', 'F3_recall_verified_at_5')}.",
            f"- **P4.** At {Fb}'s 3/min threshold, Run it Back fired "
            f"{tok(rows, 'tray-blind', 'demos', f'{Fb}_{rb}_fired')} (1 is fired), with a "
            f"highest in-session rank of {tok(rows, 'tray-blind', 'demos', f'{Fb}_{rb}_rank')} "
            "in its recall window; the Regrowth cast on `fc02a2c1ac01` fired "
            f"{tok(rows, 'tray-blind', 'demos', f'{Fb}_{rg}_fired')}, rank "
            f"{tok(rows, 'tray-blind', 'demos', f'{Fb}_{rg}_rank')}. The demos hold one "
            "Regrowth cast, not the two P4 assumed: the player read the drop on "
            "`6ab7a9e99235` at 27.6 s as the in-game menu dimming the tray "
            "[domain:hud/menu-dims-tray].",
            f"- **P5.** {Fb}'s median onset minus drop is {t('loso', f'{Fb}_onset_median_s')} s; "
            f"the median absolute offset {t('loso', f'{Fb}_onset_abs_median_s')} s.",
            f"- **P6.** On `{S}`, {tok(rows, 'smokes', S, 'onsets_live')} of "
            f"{tok(rows, 'smokes', S, 'onsets')} observed smoke onsets fall in live time. "
            f"{Fb} has a detection within {EXPLAIN_S} s of "
            f"{tok(rows, 'smokes', S, f'{Fb}_fraction_within_1_5')} of all onsets and "
            f"{tok(rows, 'smokes', S, f'{Fb}_fraction_within_1_5_live')} of the live ones; "
            f"chance is {tok(rows, 'smokes', S, f'{Fb}_chance_live')}.",
            "- **P7.** The player named no sessions; the tagger's speech fraction stands in. "
            + (f"Of the {t('loso', 'podcast_k')} sessions above the cut, "
               f"{t('loso', f'{Fb}_podcast_in_top_k')} are among the {t('loso', 'podcast_k')} "
               f"with the most {Fb} unexplained detections per minute at recall 0.5, where "
               "every session shares one pooled threshold; the rank correlation of speech "
               f"fraction with that rate is {t('loso', f'{Fb}_speech_spearman')}. F0 reads "
               f"{t('loso', 'F0_podcast_in_top_k')} of {t('loso', 'podcast_k')} and "
               f"{t('loso', 'F0_speech_spearman')}."
               if pod else "No session lies above the speech cut."), ""]

    out += ["### What was not done", ""] + [f"- {x}" for x in NOT_DONE] + [""]
    doc = DOC.read_text(encoding="utf-8")
    i = doc.index("## Results")
    DOC.write_text(doc[:i] + "\n".join(out), encoding="utf-8", newline="\n")
    print(f"wrote the Results section of {DOC}")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

#: The demos the evaluation reads: the re-recorded ones and the tray-blind ones.
EVAL_DEMOS = tuple(dict.fromkeys(FAST_DEMOS + tuple(x[1] for x in TRAY_BLIND)))


def _with_features(sids: list[str]) -> list[str]:
    return [s for s in sids if (FEAT / f"{s}.npz").is_file()]


def main(argv: list[str] | None = None) -> int:
    argv = [a for a in (sys.argv[1:] if argv is None else argv) if a != "--idle"]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("features")
    f.add_argument("--sessions", nargs="*")
    f.add_argument("--matches", action="store_true", help="every match session")
    f.add_argument("--demos", action="store_true",
                   help="the demos the evaluation reads (re-recorded and tray-blind)")
    f.add_argument("--fast", action="store_true", help="the fast tier")
    f.add_argument("--force", action="store_true")
    lb = sub.add_parser("labels")
    lb.add_argument("--sessions", nargs="*")
    lb.add_argument("--record", action="store_true")
    fi = sub.add_parser("fit")
    fi.add_argument("--formulation", required=True, choices=FORMULATIONS + ("F2c",))
    fi.add_argument("--loso", action="store_true", required=True)
    fi.add_argument("--sessions", nargs="*")
    fi.add_argument("--demos", nargs="*")
    ev = sub.add_parser("evaluate")
    ev.add_argument("--formulations", nargs="*")
    ev.add_argument("--sessions", nargs="*")
    ev.add_argument("--dry", action="store_true", help="write report-dry/, record nothing")
    rv = sub.add_parser("review")
    rv.add_argument("--formulation", required=True)
    rv.add_argument("--top", type=int, default=40)
    rv.add_argument("--sessions", nargs="*")
    sub.add_parser("report")
    a = ap.parse_args(argv)
    print(f"{VERSION}: {THREADS} thread(s), {'Idle' if IDLE else 'Below Normal'} priority")
    if a.cmd == "features":
        sids = list(a.sessions or [])
        if a.matches:
            sids += match_sessions()
        if a.demos:
            sids += list(EVAL_DEMOS)
        if a.fast:
            sids += list(FAST_MATCHES + FAST_DEMOS)
        cmd_features(list(dict.fromkeys(sids)), a.force)
    elif a.cmd == "labels":
        cmd_labels(a.sessions or _with_features(match_sessions()), a.record)
    elif a.cmd == "fit":
        demos = _with_features(list(EVAL_DEMOS)) if a.demos is None else a.demos
        cmd_fit(a.formulation, a.sessions or _with_features(match_sessions()), demos)
    elif a.cmd == "evaluate":
        have = [F for F in FORMULATIONS + ("F2c",) if (SCORES / F).is_dir()]
        cmd_evaluate(a.formulations or have, a.sessions or _with_features(match_sessions()), a.dry)
    elif a.cmd == "review":
        cmd_review(a.formulation, a.top, a.sessions or _with_features(match_sessions()))
    elif a.cmd == "report":
        cmd_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
