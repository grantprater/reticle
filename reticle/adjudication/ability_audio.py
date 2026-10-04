"""Which ability of the player's kit the audio around a tray cast sounds like.

Owns [owns:ability-audio].

A whitened matched filter over the stored audio-gate log-mel
(`ult_lines.log_mel`: 64 mel bands, 60 Hz to 16 kHz, 10 ms hop, less the
session's median per band), scored against the game's own ability sounds
(`reference/game-files/audio`, `ability-audio-ref-0.2.0`). It decodes no
video and no capture audio; the reference files are decoded once, when the
parameters are fitted.

**Why whitened.** The capture's background (footsteps, ambience, enemy
fire) is loud and correlated across bands and in time, so a plain
correlation scores every template high on it and the kit's abilities read
alike. The separability probe (2026-10-03) whitened both sides: the bands by
the background's covariance, Sigma^-1/2 with shrinkage SHRINK toward its
diagonal, fitted on dev background frames; time by an AR(2) prewhitening
filter fitted on the same frames. Templates are prewhitened once. Held-out
top-1 over the kit rose from 29/58 to 42/58 (Sova), 33/56 to 53/56 (Skye) and
5/13 to 11/13 (Iso); the band whitening carries most of the gain.

**The candidate set is the player's kit**, named by context: the tray shows
the player's kit while the player lives, and the ability-cast owner
(`ability_timeline.player_tray_casts`) passes only drops under it. Each slot
whose ability has references is a class; a slot without one is never guessed.
`none` is a class too, where the parameter set has references for it: the
agent's own sounds that no slot claims, so such a sound wins as `none` rather
than as the nearest slot. Which files those are is the fit's rule, stored in
the parameters' provenance; a file the reference table leaves unmapped is not
`none` by default, since on Sova and Skye those files are ties between the
kit's own abilities.

**A score.** Per reference file, the Pearson correlation of its whitened
template with every lag of the whitened capture (FFT correlation), less its
median over the session's null frames, over the span from that median to the
null's 99.9th percentile: 1.0 is a level the background reaches once in a
thousand frames. A class's track is the maximum over its files, and a cast's
score for a class is that track's maximum from PRE_S before the drop to
POST_S after it.

**A verdict** names the best class with its score, the runner-up and the
margin, or refuses, first match wins:

* `none_wins` -- the `none` class scores best;
* `below_null` -- the best class's score is under its threshold, the level
  the class's track reaches once per live minute on the dev sessions'
  unexplained frames (stored with the parameters);
* `pairwise_tie` -- the margin over the best rival is under TIE_MARGIN.

The scores are not calibrated into likelihoods and are not pooled into
`adjudication.identity`; that is a later task.

**Parameters** (`ability-audio-params-*`, under `reference/ability-audio/` in
the store) are fitted per agent on named dev sessions only, and carry their
session list, the shrinkage, the AR coefficients, the template rule, the
candidate rule and the reference table's version;
`prototypes/ability_audio_eval.py` fits them and scores the held sessions
through `ability_timeline.audio_cast_witness`. Every function here but
`reference_logmel`, `load_params` and `save_params` is pure.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.ndimage import maximum_filter1d
from scipy.signal import lfilter

from ..ult_lines import BANDS, FMAX, FMIN, RATE, log_mel, release_gpu, to_host

#: Bands compared: the game files hold nothing above 12 kHz.
BAND_LO, BAND_HI = 80.0, 11000.0
#: Template frames kept: frame power within this of the loudest (dB).
ACTIVE_DB = 30.0
#: Template cells floored this far below the template's maximum (dB).
TEMPLATE_DB = 40.0
#: A longer clip keeps the first MAX_TEMPLATE_S of its active span.
MAX_TEMPLATE_S = 1.5
#: Shrinkage of the background covariance toward its diagonal.
SHRINK = 0.1
#: Eigenvalues of the covariance are floored at this share of the largest.
EIG_FLOOR = 1e-4
#: A background run shorter than this (frames) gives no AR lag pairs.
AR_MIN_RUN = 20
#: The window of a cast's score around the drop (s): the probe's.
PRE_S = 2.0
POST_S = 3.0
#: Frames of the log-mel per second.
FPS = 100
#: The least margin of the best class over the runner-up.
TIE_MARGIN = 0.25
#: The none class's name.
NONE = "none"
#: The refusals, in the order they are tested.
REFUSALS = ("none_wins", "below_null", "pairwise_tie")
#: The false fires per live minute a class threshold allows on dev.
THRESHOLD_FF_PER_MIN = 1.0
#: Two peaks of a track count as one false fire within this (frames).
PEAK_GAP = 100
#: A frame within this of an own cast, a gunfire span or a known other
#: sound is explained, not background (s): the audio gate's labels.
EXPLAIN_S = 1.5
#: The audio gate's class code for a background frame.
CLS_BACKGROUND = 2
#: Where the parameter sets live, under the store root.
PARAMS_DIR = Path("reference") / "ability-audio"


def band_centres() -> np.ndarray:
    """The centre (Hz) of each of `ult_lines`'s mel bands."""
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    imel = lambda m: 700 * (10 ** (m / 2595) - 1)
    return imel(np.linspace(mel(FMIN), mel(FMAX), BANDS + 2))[1:-1]


#: The bands compared.
BMASK = (band_centres() >= BAND_LO) & (band_centres() <= BAND_HI)


# ---------------------------------------------------------------------------
# Frames, masks and the fit
# ---------------------------------------------------------------------------

def session_frames(L: np.ndarray, med: np.ndarray) -> np.ndarray:
    """The compared bands of a stored log-mel less its session median, float32."""
    return (np.asarray(L, np.float32) - np.asarray(med, np.float32))[:, BMASK]


def runs(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(starts, ends) of the True runs of a boolean array."""
    d = np.diff(np.concatenate([[0], np.asarray(mask, np.int8), [0]]))
    return np.flatnonzero(d == 1), np.flatnonzero(d == -1)


def explained(n: int, casts_s, spans_s, others_s, explain_s: float = EXPLAIN_S,
              step_s: float = 1.0 / FPS) -> np.ndarray:
    """Per frame: 0 within `explain_s` of an own cast, 1 of a gunfire span
    (start, end), 2 of another known sound, 3 unexplained; a closer kind's
    code wins in that order. Vectorised over frames."""
    s = np.arange(n) * step_s
    code = np.full(n, 3, np.int8)
    for k, iv in ((2, [(t, t) for t in others_s]), (1, [tuple(x) for x in spans_s]),
                  (0, [(t, t) for t in casts_s])):
        if not iv:
            continue
        a = np.array([x[0] for x in iv], float)
        b = np.array([x[1] for x in iv], float)
        o = np.argsort(a)
        a, b = a[o], b[o]
        i = np.searchsorted(a, s)
        d = np.full(n, np.inf)
        for j in (i - 1, i):
            jj = np.clip(j, 0, len(a) - 1)
            d = np.minimum(d, np.maximum(np.maximum(a[jj] - s, s - b[jj]), 0))
        code[d <= explain_s + 1e-9] = k
    return code


def background(live: np.ndarray, cls: np.ndarray, code: np.ndarray) -> np.ndarray:
    """The null frames: live, the audio gate's background class, unexplained."""
    return np.asarray(live, bool) & (np.asarray(cls) == CLS_BACKGROUND) & (code == 3)


def fit_band_whitener(Xbg: np.ndarray, shrink: float = SHRINK) -> tuple[np.ndarray, np.ndarray, float]:
    """(mean, Sigma^-1/2 symmetric, condition number) of background frames,
    the covariance shrunk toward its diagonal by `shrink`."""
    X = np.asarray(Xbg, np.float64)
    mu = X.mean(0)
    S = np.cov(X.T)
    S = (1 - shrink) * S + shrink * np.diag(np.diag(S))
    ev, V = np.linalg.eigh(S)
    ev = np.maximum(ev, ev.max() * EIG_FLOOR)
    return mu, (V / np.sqrt(ev)) @ V.T, float(ev.max() / ev.min())


def fit_ar2(Y: np.ndarray, mask: np.ndarray, min_run: int = AR_MIN_RUN) -> np.ndarray:
    """AR(2) coefficients of band-whitened frames `Y`, by least squares over
    the lag pairs inside every run of `mask` longer than `min_run`."""
    s, e = runs(mask)
    keep = (e - s) > min_run
    idx = np.concatenate([np.arange(a + 2, b) for a, b in zip(s[keep], e[keep])]
                         or [np.zeros(0, int)])
    y, l1, l2 = Y[idx].ravel(), Y[idx - 1].ravel(), Y[idx - 2].ravel()
    return np.linalg.lstsq(np.stack([l1, l2], 1), y, rcond=None)[0]


def ar_filter(ar) -> np.ndarray:
    """The FIR prewhitening filter of AR(2) coefficients: [1, -a1, -a2]."""
    return np.array([1.0, -float(ar[0]), -float(ar[1])])


def whiten_frames(X: np.ndarray, mu: np.ndarray, P: np.ndarray, ar) -> np.ndarray:
    """Band-whitened, then time-prewhitened frames, float32."""
    return lfilter(ar_filter(ar), [1.0], (np.asarray(X, np.float64) - mu) @ P,
                   axis=0).astype(np.float32)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def reference_logmel(path) -> np.ndarray:
    """Absolute log-mel dB [n, BANDS] of a reference clip: decoded mono at its
    own rate by PyAV, resampled to RATE by `scipy.signal.resample_poly`
    (Kaiser-windowed polyphase FIR, beta 5), padded by one window each side,
    and put through `ult_lines.log_mel`. Reads a file."""
    from math import gcd

    import av
    from scipy.signal import resample_poly
    chunks = []
    with av.open(str(path)) as c:
        st = c.streams.audio[0]
        rate = st.rate
        rs = av.AudioResampler(format="flt", layout="mono", rate=rate)
        for fr in c.decode(st):
            for o in rs.resample(fr):
                chunks.append(o.to_ndarray().reshape(-1))
        for o in rs.resample(None):
            chunks.append(o.to_ndarray().reshape(-1))
    x = np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)
    if rate != RATE:
        g = gcd(RATE, rate)
        x = resample_poly(x, RATE // g, rate // g, window=("kaiser", 5.0)).astype(np.float32)
    pad = np.zeros(2048, np.float32)
    y = np.concatenate([pad, x, pad])
    L, _ok, _rms = log_mel(y, np.ones(len(y), bool), RATE, xp=np)
    return L.astype(np.float32)


def template(L: np.ndarray) -> np.ndarray | None:
    """The z-scored, unit-norm template [m, compared bands] of a clip's
    absolute log-mel: the frames within ACTIVE_DB of the loudest, at most
    MAX_TEMPLATE_S of them, cells floored TEMPLATE_DB under the span's
    maximum. None for a silent clip."""
    Lb = np.asarray(L, np.float64)[:, BMASK]
    p = 10 * np.log10((10 ** (Lb / 10)).sum(axis=1) + 1e-12)
    if not np.isfinite(p).any() or p.max() < -90:
        return None
    act = np.flatnonzero(p >= p.max() - ACTIVE_DB)
    a, b = act[0], act[-1] + 1
    b = min(b, a + int(round(MAX_TEMPLATE_S * FPS)))
    if b - a < 3:
        b = a + 3
    T = Lb[a:b]
    T = np.maximum(T, T.max() - TEMPLATE_DB)
    Tz = T - T.mean()
    n = np.linalg.norm(Tz)
    return None if n < 1e-6 else (Tz / n).astype(np.float32)


def whiten_template(Tz: np.ndarray, P: np.ndarray, ar) -> np.ndarray:
    """A template whitened like the capture (bands by P, time by the AR
    filter, its first two frames dropped as the filter's start-up), then
    zero-mean and unit-norm."""
    W = lfilter(ar_filter(ar), [1.0], np.asarray(Tz, np.float64) @ P, axis=0)[2:]
    W = W - W.mean()
    return (W / np.linalg.norm(W)).astype(np.float32)


# ---------------------------------------------------------------------------
# Tracks and scores
# ---------------------------------------------------------------------------

class Corpus:
    """The FFT of a whitened capture, cached for lagged Pearson tracks.
    `xp` is numpy or cupy (`ult_lines.array_module`)."""

    def __init__(self, Xw: np.ndarray, max_len: int, xp=np):
        self.xp = xp
        self.N, self.nb = Xw.shape
        g = xp.asarray(Xw)
        self.nfft = 1 << int(np.ceil(np.log2(self.N + max_len)))
        self.FX = xp.fft.rfft(g, n=self.nfft, axis=0)
        z = xp.zeros(1, xp.float64)
        self.s1 = xp.concatenate([z, xp.cumsum(g.sum(axis=1, dtype=xp.float64))])
        self.s2 = xp.concatenate([z, xp.cumsum((g.astype(xp.float64) ** 2).sum(axis=1))])

    def track(self, W: np.ndarray):
        """Pearson correlation of template `W` with the capture at every lag
        k (frames k to k + m), -1 where the template overruns the end. The
        numerator sums the bands before the inverse FFT, which is the same
        sum taken once."""
        xp, m = self.xp, W.shape[0]
        FT = xp.fft.rfft(xp.asarray(W[::-1]), n=self.nfft, axis=0)
        num = xp.fft.irfft((self.FX * FT).sum(axis=1), n=self.nfft)[m - 1:self.N]
        S1 = self.s1[m:] - self.s1[:-m]
        S2 = self.s2[m:] - self.s2[:-m]
        r = num / xp.sqrt(xp.maximum(S2 - S1 ** 2 / (m * self.nb), 1e-3))
        out = xp.full(self.N, -1.0, xp.float32)
        out[:len(r)] = r.astype(xp.float32)
        return out


def class_tracks(Xw: np.ndarray, templates: list[np.ndarray], labels: list[str],
                 null_mask: np.ndarray, xp=np) -> dict[str, np.ndarray]:
    """{class: track}: per template its Pearson track less its median over
    the null frames, over the span to their 99.9th percentile; a class's
    track the maximum over its templates. Host float32."""
    if not templates:
        return {}
    nidx = np.flatnonzero(null_mask)
    if not len(nidx):
        raise ValueError("no null frames to calibrate against")
    C = Corpus(Xw, max(t.shape[0] for t in templates), xp)
    ni = xp.asarray(nidx)
    out = {}
    for W, lab in zip(templates, labels):
        tr = C.track(W)
        q50, q999 = xp.quantile(tr[ni], xp.asarray([0.5, 0.999]))
        v = (tr - q50) / xp.maximum(q999 - q50, 1e-3)
        out[lab] = v if lab not in out else xp.maximum(out[lab], v)
    host = {k: to_host(v).astype(np.float32) for k, v in out.items()}
    del C
    release_gpu(xp)
    return host


def window_max(track: np.ndarray, pre: int = int(PRE_S * FPS),
               post: int = int(POST_S * FPS)) -> np.ndarray:
    """Per frame k, the track's maximum over frames k - pre to k + post - 1."""
    size = pre + post
    # maximum_filter1d centres its window; the origin shifts it to [k-pre, k+post).
    return maximum_filter1d(np.asarray(track, np.float32), size=size,
                            origin=pre - (size // 2), mode="nearest")


def cast_scores(tracks: dict[str, np.ndarray], frames, classes: list[str]) -> np.ndarray:
    """[casts, classes]: each class's window maximum at each cast frame."""
    f = np.clip(np.asarray(frames, int), 0, len(next(iter(tracks.values()))) - 1)
    return np.stack([window_max(tracks[c])[f] for c in classes], axis=1)


def identify(scores: np.ndarray, classes: list[str], thresholds: dict[str, float],
             tie_margin: float = TIE_MARGIN) -> list[dict]:
    """Per row of `scores`: the best class, its score, the runner-up, the
    margin, the refusal (REFUSALS, first match wins) and the verdict (the
    best class unless refused). The decisions are vectorised; the rows are
    their record."""
    scores = np.asarray(scores, float).reshape(-1, len(classes))
    n, k = scores.shape
    order = np.argsort(-scores, axis=1, kind="stable")
    rows = np.arange(n)
    s1 = scores[rows, order[:, 0]] if k else np.zeros(n)
    s2 = scores[rows, order[:, 1]] if k > 1 else np.full(n, np.nan)
    margin = s1 - s2
    thr = np.array([np.nan if thresholds.get(c) is None else float(thresholds[c])
                    for c in classes] or [np.nan])[order[:, 0] if k else np.zeros(n, int)]
    is_none = np.array([c == NONE for c in classes] or [False])[order[:, 0] if k else
                                                                  np.zeros(n, int)]
    below = ~is_none & (np.isnan(thr) | (s1 < np.nan_to_num(thr, nan=np.inf)))
    tie = ~is_none & ~below & (margin < tie_margin)
    why = np.where(is_none, REFUSALS[0], np.where(below, REFUSALS[1],
                                                  np.where(tie, REFUSALS[2], "")))
    r4 = lambda v: None if not np.isfinite(v) else round(float(v), 4)
    out = []
    for i in range(n):
        best = classes[order[i, 0]]
        out.append({"best": best, "score": r4(s1[i]),
                    "runner_up": classes[order[i, 1]] if k > 1 else None,
                    "runner_up_score": r4(s2[i]), "margin": r4(margin[i]),
                    "threshold": r4(thr[i]), "reason": why[i] or None,
                    "verdict": None if why[i] else best,
                    "scores": {c: round(float(v), 4) for c, v in zip(classes, scores[i])}})
    return out


def false_fire_peaks(track: np.ndarray, live: np.ndarray, code: np.ndarray,
                     gap: int = PEAK_GAP) -> np.ndarray:
    """A track's peak values on live, unexplained frames, peaks at least
    `gap` frames apart (`scipy.signal.find_peaks`)."""
    from scipy.signal import find_peaks
    t = np.where(live, track, -1e3).astype(np.float32)
    pk, _ = find_peaks(t, height=-999, distance=gap)
    return track[pk[(code[pk] == 3) & live[pk]]]


def threshold_at(peaks: list[np.ndarray], live_min: float,
                 ff_per_min: float = THRESHOLD_FF_PER_MIN) -> float | None:
    """The least score at which the peaks fire at most `ff_per_min` per live
    minute; None without live minutes."""
    if live_min <= 0:
        return None
    v = np.sort(np.concatenate(peaks) if peaks else np.zeros(0))[::-1]
    k = int(np.floor(ff_per_min * live_min))
    # Firing at score >= thr counts the peaks at or above it; the k+1-th
    # highest peak must fall strictly below.
    return float(np.nextafter(v[k], np.inf)) if k < len(v) else float(v[-1]) if len(v) else 0.0


# ---------------------------------------------------------------------------
# The parameter set
# ---------------------------------------------------------------------------

def params_path(store_root, version: str) -> Path:
    return Path(store_root) / PARAMS_DIR / version


def save_params(store_root, version: str, agents: dict, provenance: dict) -> Path:
    """Write a parameter set: per agent `mu`, `P`, `ar`, the whitened
    templates and their classes and files, the class thresholds; and the
    provenance JSON. Refuses to overwrite an existing set."""
    d = params_path(store_root, version)
    if d.exists():
        raise FileExistsError(f"{d} exists; a parameter set is never overwritten")
    d.mkdir(parents=True)
    arrays = {}
    meta = {}
    for agent, a in agents.items():
        key = agent.replace("/", "_")
        arrays[f"{key}__mu"] = a["mu"]
        arrays[f"{key}__P"] = a["P"]
        arrays[f"{key}__ar"] = np.asarray(a["ar"], float)
        lens = np.array([t.shape[0] for t in a["templates"]], int)
        arrays[f"{key}__T"] = np.concatenate(a["templates"]).astype(np.float32)
        arrays[f"{key}__lens"] = lens
        meta[agent] = {"key": key, "classes": a["labels"], "files": a["files"],
                       "slots": a["slots"], "thresholds": a["thresholds"],
                       "dev": a["dev"], "fit": a["fit"]}
    np.savez(d / "params.npz", **arrays)
    (d / "provenance.json").write_text(json.dumps({**provenance, "version": version,
                                                   "agents": meta}, indent=1),
                                       encoding="utf-8")
    return d


def load_params(store_root, version: str, agent: str) -> tuple[dict | None, str | None]:
    """(an agent's parameters, None) or (None, the reason there are none:
    `no_params:<version>` or `no_params_for:<agent>`)."""
    d = params_path(store_root, version)
    if not (d / "provenance.json").is_file():
        return None, f"no_params:{version}"
    prov = json.loads((d / "provenance.json").read_text(encoding="utf-8"))
    meta = next((m for a, m in prov["agents"].items()
                 if a.replace("/", "_") == str(agent).replace("/", "_")), None)
    if meta is None:
        return None, f"no_params_for:{agent}"
    z = np.load(d / "params.npz")
    k = meta["key"]
    T, lens = z[f"{k}__T"], z[f"{k}__lens"]
    cuts = np.concatenate([[0], np.cumsum(lens)])
    return {"version": prov["version"], "mu": z[f"{k}__mu"], "P": z[f"{k}__P"],
            "ar": z[f"{k}__ar"],
            "templates": [T[a:b] for a, b in zip(cuts[:-1], cuts[1:])],
            "labels": meta["classes"], "files": meta["files"], "slots": meta["slots"],
            "thresholds": meta["thresholds"], "dev": meta["dev"], "fit": meta["fit"],
            "provenance": {k2: v for k2, v in prov.items() if k2 != "agents"}}, None
