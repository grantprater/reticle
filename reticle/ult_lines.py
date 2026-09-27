r"""Match the official ultimate voice lines against a capture's audio.

    .\.venv\Scripts\python.exe -m reticle ult-lines <session> | --all

Owns [owns:ult-line].

Ported from `prototypes/voice_lines.py`, formulation F-B, whose docstring and
`docs/VOICE_LINES.md` hold the measurements behind every constant; the
prototypes now import these functions from here. Each agent's ultimate has two
heard lines: the ally line, which the caster's team hears, and the enemy line,
which the other team hears; the caster hears the ally line at the cast
[domain:abilities/caster-hears-own-ult-line]. Each line is one template, cut
from its official clip to the frames within ACTIVE_DB of the loudest one on
the audio gate's 10 ms log-mel front end (`log_mel`: 64 mel bands, a
2048-point Hann window).

The correlation is GCC-PHAT on the waveform: each template's spectrum against
the capture's, whitened to unit magnitude over PHAT_BAND, so the score is the
share of the band that agrees in phase and a perfect match reads 1. Only the
capture's audio stream is decoded, in memory (`decode_mono`); no video frame is
decoded and no audio is written. Chunks of CHUNK samples step by CHUNK less the
longest template, so every lag of every template sees its whole window in one
chunk, and frame k holds the best lag in [k, k + 1) hops. The FFTs run on the
GPU with cupy and fall back to numpy (`array_module`).

What is stored. Each template keeps the peaks of its track at or above its own
99th percentile (FLOOR_Q), none within one template length of a higher peak of
the same template. Each peak is a raw row: when, which template, its agent and
variant, the score and the floor, under the capture's `content_key`. The
reader consults no lineup and stores no class; `adjudication.ult_cast` selects
and classes peaks. Two templates may peak at one onset -- a line that resembles
another, or two ultimates at once -- and both stay: cross-template suppression
was measured and declined (`docs/VOICE_LINES.md`, "Verdicts at 0.2.0").

The templates. `templates/ult_lines.json` lists name, agent, variant, file and
hash: the 56 `<Agent>_ult_<variant>.mp3` files under
`<store>/reference/assets/voicelines/`, and for an agent they lack, the first
take of the harvest index's `Ally Cast` and `Enemy Cast` rows of the one
ability that has them (`harvested_ults`; Gekko's Thrash). Agents are spelled as
the asset files and the lineup spell them (`KAY_O`). A file whose hash differs
from the manifest refuses the run.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

import numpy as np

#: The capture's and the templates' sample rate; templates are resampled to it.
RATE = 48000
#: The audio gate's front end: hop (s), window, mel bands and their range (Hz).
HOP, NFFT, BANDS, FMIN, FMAX = 0.01, 2048, 64, 60.0, 16000.0
HOP_N = int(round(HOP * RATE))
#: Template span: frames whose power lies within this of the loudest frame's (dB).
ACTIVE_DB = 40.0
#: The span's log-mel floor below its own maximum (dB). F-B reads only the
#: span; the prototype's log-mel formulations read the floored template.
FLOOR_DB = 50.0
#: Chunk length in samples, and the whitened band (Hz).
CHUNK = 1 << 20
PHAT_BAND = (100.0, 8000.0)
#: Templates per batched inverse FFT.
PHAT_BATCH = 8
#: A peak is kept at or above this quantile of its own template's track.
FLOOR_Q = 0.99
#: Where the official lines live, under the store root.
VOICE_DIR = Path("reference") / "assets" / "voicelines"
#: The declared template set.
MANIFEST = Path(__file__).resolve().parent / "templates" / "ult_lines.json"
#: The harvest index's sections that hold an ultimate's two heard lines.
ULT_SECTIONS = {"Ally Cast": "ally", "Enemy Cast": "enemy"}
VARIANTS = ("ally", "enemy")


# ---------------------------------------------------------------------------
# Arrays
# ---------------------------------------------------------------------------

def array_module():
    """cupy when a CUDA device is present, else numpy. `RETICLE_ULT_LINES=cpu`
    forces numpy; `=gpu` refuses to fall back."""
    mode = os.environ.get("RETICLE_ULT_LINES", "auto").lower()
    if mode not in ("auto", "cpu", "gpu"):
        raise ValueError(f"RETICLE_ULT_LINES must be auto, cpu or gpu, not {mode!r}")
    if mode == "cpu":
        return np
    try:
        import cupy as cp
        if cp.cuda.runtime.getDeviceCount() < 1:
            raise RuntimeError("no CUDA device")
        cp.zeros(1)
        return cp
    except Exception:
        if mode == "gpu":
            raise
        return np


def to_host(a) -> np.ndarray:
    """A numpy array, from cupy or numpy."""
    return a.get() if hasattr(a, "get") else np.asarray(a)


def release_gpu(xp) -> None:
    """Return cupy's pooled blocks between sessions."""
    if xp is not np:
        xp.get_default_memory_pool().free_all_blocks()


# ---------------------------------------------------------------------------
# Decode and the log-mel front end
# ---------------------------------------------------------------------------

def decode_mono(path: str) -> tuple[np.ndarray, np.ndarray, int]:
    """(mono float32, filled mask, rate): the whole audio stream, decoded once.

    The demuxer reads the interleaved video packets and never decodes them.
    Each AAC frame is placed by its own pts, so a gap in the stream stays a gap
    (unfilled).
    """
    import av
    with av.open(str(path)) as c:
        st = c.streams.audio[0]
        rate = st.rate
        dur = float(st.duration * st.time_base) if st.duration else c.duration / 1e6
        x = np.zeros(int(math.ceil((dur + 2.0) * rate)), np.float32)
        filled = np.zeros(len(x), bool)
        end = 0
        for pkt in c.demux(st):
            for fr in pkt.decode():
                if fr.pts is None:
                    continue
                a = fr.to_ndarray()
                if a.ndim == 1 or a.shape[0] != 2:
                    raise ValueError(f"{path}: expected planar stereo, got {a.shape}")
                i = int(round(float(fr.pts * st.time_base) * rate))
                j = i + a.shape[1]
                if j > len(x):
                    grow = max(j - len(x), rate * 10)
                    x = np.concatenate([x, np.zeros(grow, np.float32)])
                    filled = np.concatenate([filled, np.zeros(grow, bool)])
                lo = max(i, 0)
                if j > lo:
                    x[lo:j] = a[:, lo - i:].mean(axis=0)
                    filled[lo:j] = True
                    end = max(end, j)
    return x[:end], filled[:end], rate


def mel_filterbank(rate: int, nfft: int, n: int = BANDS, fmin: float = FMIN,
                   fmax: float = FMAX) -> np.ndarray:
    """[n, nfft // 2 + 1] triangular mel filters on the HTK mel scale."""
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    imel = lambda m: 700 * (10 ** (m / 2595) - 1)
    pts = imel(np.linspace(mel(fmin), mel(fmax), n + 2))
    f = np.fft.rfftfreq(nfft, 1 / rate)
    fb = np.zeros((n, len(f)))
    for i in range(n):
        a, b, c = pts[i:i + 3]
        fb[i] = np.clip(np.minimum((f - a) / (b - a), (c - f) / (c - b)), 0, None)
    return fb


def log_mel(x: np.ndarray, filled: np.ndarray, rate: int, chunk: int = 8192, xp=None):
    """(absolute log-mel dB [n, BANDS], ok [n], RMS dB [n]); frame k centred on k * HOP.

    `ok` is false where the NFFT-point window reaches outside the decoded
    audio. RMS is the mono mix's power over the hop around the centre, in dB.
    """
    xp = xp or array_module()
    h = int(round(HOP * rate))
    n = len(x) // h
    fb = xp.asarray(mel_filterbank(rate, NFFT).T.astype(np.float32))
    win = xp.asarray(np.hanning(NFFT).astype(np.float32))
    cum = np.concatenate([[0], np.cumsum(filled, dtype=np.int64)])
    L = np.empty((n, BANDS), np.float32)
    ok = np.zeros(n, bool)
    rms = np.empty(n, np.float32)
    half = NFFT // 2
    for k0 in range(0, n, chunk):
        k1 = min(n, k0 + chunk)
        lo, hi = k0 * h - half, (k1 - 1) * h + half
        seg = np.zeros(hi - lo, np.float32)
        a, b = max(lo, 0), min(hi, len(x))
        seg[a - lo:b - lo] = x[a:b]
        g = xp.asarray(seg)
        idx = (xp.arange(k1 - k0)[:, None] * h) + xp.arange(NFFT)[None]
        P = xp.abs(xp.fft.rfft(g[idx] * win, axis=1)) ** 2
        L[k0:k1] = to_host(10 * xp.log10(P.astype(xp.float32) @ fb + 1e-10))
        c = idx[:, half - h // 2:half - h // 2 + h]
        rms[k0:k1] = to_host(10 * xp.log10((g[c] ** 2).mean(axis=1) + 1e-10))
        first = np.arange(k0, k1) * h - half
        inside = (first >= 0) & (first + NFFT <= len(x))
        full = np.zeros(k1 - k0, bool)
        full[inside] = (cum[first[inside] + NFFT] - cum[first[inside]]) == NFFT
        ok[k0:k1] = full
    return L, ok, rms


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def decode_template(path: Path) -> np.ndarray:
    """An official line as RATE mono float32, resampled by libswresample where needed."""
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


def harvested_ults(rows: list[dict], have: set[str]) -> dict[str, str]:
    """{template name: file} for each agent `have` lacks, from the harvest
    index: the first take of the one ability whose sections are `Ally Cast`
    and `Enemy Cast`, the ultimate's ally- and enemy-heard lines. The 56 ult
    files are byte-identical to those rows of the other agents. Agents are
    spelled as the asset files spell them (KAY/O is KAY_O)."""
    out, ability = {}, {}
    for r in sorted(rows, key=lambda r: r["file"]):
        var = ULT_SECTIONS.get(r.get("section", ""))
        agent = str(r["agent"]).replace("/", "_")
        if var is None or agent in have:
            continue
        if ability.setdefault(agent, r["ability"]) != r["ability"]:
            raise ValueError(f"{agent}: ally/enemy cast lines under two abilities, "
                             f"{ability[agent]!r} and {r['ability']!r}")
        out.setdefault(f"{agent}_ult_{var}", r["file"])
    return out


def template_digest(path: Path) -> str:
    """The first 16 hex digits of a file's SHA-256."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def manifest_from_assets(voice_dir: Path) -> list[dict]:
    """The template entries the assets hold: every `<Agent>_ult_<variant>.mp3`,
    then the harvested pair of each agent those lack. It writes nothing; the
    declared set is MANIFEST, which `reticle ult-lines --check-manifest`
    compares with this."""
    voice_dir = Path(voice_dir)
    files = {p.stem: p.name for p in voice_dir.glob("*_ult_*.mp3")}
    idx = voice_dir / "casts" / "index.json"
    if idx.is_file():
        have = {n.rsplit("_ult_", 1)[0] for n in files}
        rows = json.loads(idx.read_text(encoding="utf-8"))
        files.update({n: f"casts/{f}" for n, f in harvested_ults(rows, have).items()})
    out = []
    for name in sorted(files):
        agent, variant = name.rsplit("_ult_", 1)
        if variant not in VARIANTS:
            raise ValueError(f"{name}: unknown variant {variant!r}")
        out.append({"name": name, "agent": agent, "variant": variant, "file": files[name],
                    "sha256": template_digest(voice_dir / files[name])})
    return out


def templates_key(entries: list[dict]) -> str:
    """A short hash over each template's name and file hash."""
    s = "\n".join(f"{e['name']} {e['sha256']}" for e in entries)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def load_manifest(path: Path = MANIFEST) -> dict:
    """The declared template set, with the key its entries hash to."""
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    m["key"] = templates_key(m["templates"])
    return m


def build_templates(voice_dir: Path, entries: list[dict], xp=None) -> list[dict]:
    """Each declared line decoded, checked against its hash, and cut to its
    active span: the entry plus k0, k1, frames, span_s and the waveform `wave`."""
    out = []
    for e in entries:
        p = Path(voice_dir) / e["file"]
        if not p.is_file():
            raise ValueError(f"{e['name']}: {p} is missing")
        got = template_digest(p)
        if got != e["sha256"]:
            raise ValueError(f"{e['name']}: {p} hashes to {got}, the manifest says {e['sha256']}")
        y = decode_template(p)
        L, ok, _rms = log_mel(y, np.ones(len(y), bool), RATE, xp=xp)
        _T, k0, k1 = trim_floor(L, ok)
        out.append({**e, "k0": k0, "k1": k1, "frames": k1 - k0,
                    "span_s": round((k1 - k0) * HOP, 3),
                    "wave": y[k0 * HOP_N:k1 * HOP_N]})
    return out


# ---------------------------------------------------------------------------
# Correlation and peaks
# ---------------------------------------------------------------------------

def phat_tracks(x: np.ndarray, waves: list[np.ndarray], rate: int = RATE,
                chunk: int = CHUNK, band=PHAT_BAND, hop_n: int = HOP_N, xp=None,
                batch: int = PHAT_BATCH) -> np.ndarray:
    """[templates, frames] GCC-PHAT of each template waveform against x: the
    largest lag score in each hop, a perfect match reading 1.

    Chunks of `chunk` samples step by `chunk` less the longest template
    (rounded up to a hop), so every lag of every template sees its full
    window in one chunk. Frame k holds lags [k * hop_n, (k + 1) * hop_n).
    """
    xp = xp or array_module()
    J = len(waves)
    mmax = int(math.ceil(max(len(w) for w in waves) / hop_n)) * hop_n
    step = (chunk - mmax) // hop_n * hop_n
    if step <= 0:
        raise ValueError("chunk shorter than the longest template")
    nf = chunk // 2 + 1
    f = np.arange(nf) * rate / chunk
    mask = xp.asarray(((f >= band[0]) & (f <= band[1])).astype(np.float32))
    K = float(to_host(mask).sum())
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
            out[j0:j0 + batch, f0:f1] = to_host(r.reshape(r.shape[0], nfr, hop_n).max(axis=2))
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
# One capture
# ---------------------------------------------------------------------------

def read_capture(path: str, templates: list[dict], xp=None) -> tuple[dict, dict]:
    """(what the read took, the peaks of every template) for one capture's audio."""
    xp = xp or array_module()
    t0 = time.time()
    x, filled, rate = decode_mono(path)
    info = {"decode_s": round(time.time() - t0, 1), "rate": rate,
            "filled_fraction": round(float(filled.mean()), 4) if len(filled) else 0.0,
            "backend": "cupy" if xp is not np else "numpy"}
    del filled
    if rate != RATE:
        raise ValueError(f"{path}: audio at {rate} Hz, templates at {RATE}")
    t1 = time.time()
    tracks = phat_tracks(x, [t["wave"] for t in templates], xp=xp)
    info["n_frames"] = int(tracks.shape[1])
    del x
    peaks = track_peaks(tracks, [t["frames"] for t in templates])
    del tracks
    release_gpu(xp)
    info["score_s"] = round(time.time() - t1, 1)
    return info, peaks


def _num(v: float, n: int = 6):
    """A float for JSON, or None where it is not finite."""
    v = float(v)
    return round(v, n) if math.isfinite(v) else None


def observations(session_id: str, content_key: str, version: str, templates: list[dict],
                 manifest_key: str, info: dict, peaks: dict) -> list[dict]:
    """The stream's rows: one coverage row, then one row per peak in time order."""
    common = {"session_id": session_id, "ult_line_version": version, "content_key": content_key}
    per = {t["name"]: {"floor": _num(peaks["floor"][j]), "median": _num(peaks["median"][j]),
                       "max": _num(peaks["max"][j]), "peaks": int((peaks["tpl"] == j).sum()),
                       "frames": t["frames"]}
           for j, t in enumerate(templates)}
    rows = [{**common, "kind": "coverage", "templates": len(templates),
             "templates_key": manifest_key, "floor_q": FLOOR_Q, "hop_s": HOP,
             "phat_band_hz": list(PHAT_BAND), "chunk": CHUNK, "peaks": int(len(peaks["score"])),
             **info, "per_template": per}]
    order = np.lexsort((peaks["tpl"], peaks["frame"]))
    for i in order:
        t = templates[int(peaks["tpl"][i])]
        frame = int(peaks["frame"][i])
        rows.append({**common, "kind": "peak", "t_s": round(frame * HOP, 2), "frame": frame,
                     "template": t["name"], "agent": t["agent"], "variant": t["variant"],
                     "score": _num(peaks["score"][i]), "floor": per[t["name"]]["floor"]})
    return rows
