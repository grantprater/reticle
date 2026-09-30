r"""Test whether footstep audio loops, and score the first common-sound bank.

    .\.venv\Scripts\python.exe prototypes\sound_bank.py loop [--record]
    .\.venv\Scripts\python.exe prototypes\sound_bank.py bank [--record]

Why this exists
---------------
The player reviewed every candidate `sound_demo.py` cut from his range clip,
`C:\Users\grant\Videos\2026-09-29 18-50-03.mp4` (session a01863947bab), into
`<store>/labels/sound_demo_20260929.jsonl`. The agreed audio order is clean
references, then a common-sound bank, then the audio-video offset, then
fingerprinting. This file takes the second step on that one clip and asks one
question of the footsteps first: does the game play a fixed loop of samples per
surface, draw from a random pool, or vary each step? A loop or a pool makes a
footstep an exact template; a varied step needs a class model. The player's
belief is [domain:abilities/footstep-audio-loop-belief]; the answer is
[domain:abilities/footstep-shuffled-sample-pool].

Both stages decode only this clip's audio, in memory (`audio_probe.decode`);
nothing is written but the result files under
`<store>/analysis/sound-bank/`. Predictions and outcomes are in the store's
`notes/predictions.jsonl` under `sound-bank-20260929`.

`loop`
------
The walking phase (after 170 s) splits into continuous runs where successive
steps lie under 0.6 s apart. Each step's waveform, band-passed 100 Hz-6 kHz
and taken at 16 kHz, is cut from 20 ms before its onset for 170 ms; a pair's
score is the peak normalised cross-correlation over +-30 ms of lag, maximised
over resample ratios 0.95-1.05 (0.25% steps, then 0.05% around the best),
so a pitch-jittered replay of one sample still scores near 1. A second,
pitch-tolerant feature correlates the steps' log-frequency power spectra
(48 bins per octave) over +-4 bins of shift. The instrument is checked first:
a step against itself at a 7 ms offset, the same step added onto another
step's preceding 230 ms (its reverb tail and the range's mix) with and without
a 2% pitch shift, and every knife equip against every footstep.

`bank`
------
One reference per labelled event (the player's 'buy menu close' names form a
class; his other 'other' rows are kept as ground truth and never become
references). The front end is the audio bank's log-mel (64 bands, 10 ms hop)
as dB above a +-4 s context median, floored at 0. A reference is its event's
patch from 20 ms before the onset, of its class's length (median span plus
0.1 s, 0.2-1.0 s), and it scores a z-scored patch correlation at every frame.
Leave-one-out means a reference never scores within its own event's span.
Two readings: at the labelled onset (+-50 ms) the best class names the event;
and over the whole clip, class peaks over a threshold of 0.50 are kept
greedily by score, each claiming its span, and a detection matches a
labelled onset within 0.10 s.

Findings (2026-09-29)
---------------------
The instrument works: a step against itself scores
[metric:sound_bank/loop@a01863947bab#self_7ms=1.0], a knife equip against a
step [metric:sound_bank/loop@a01863947bab#knife_vs_step_median=0.106] at the
median, and a step added onto another step's preceding 230 ms still scores
[metric:sound_bank/loop@a01863947bab#synthetic_dup_min=0.793] at worst
([metric:sound_bank/loop@a01863947bab#synthetic_pitch_min=0.784] at +2%
pitch, where the ratio-1.0 score falls to
[metric:sound_bank/loop@a01863947bab#synthetic_pitch_raw_median=0.547]).
That floor is the limit the clip's reverb tails and running mix set: a real
replay scoring under about 0.8 would be read as a different sample.

Footsteps are neither a fixed loop nor varied per step. Exact replays exist:
[metric:sound_bank/loop@a01863947bab#frac_steps_with_partner_080=0.68] of
the steps have a partner in their run at 0.80 or more. No replay needed a
pitch change: on surface A none of the
[metric:sound_bank/loop@a01863947bab#pool0_same_sample_pairs=272] same-sample
pairs moved the ratio by 0.5%
([metric:sound_bank/loop@a01863947bab#pool0_same_sample_ratio_off_05pct=0.0]).
The ratio search only lifts different samples of one surface, whose median is
[metric:sound_bank/loop@a01863947bab#pool0_other_sample_median=0.721] against
[metric:sound_bank/loop@a01863947bab#pool0_same_sample_median=0.922] for one
sample. The pre-registered lag test found no fixed step lag (the modal lag
holds [metric:sound_bank/loop@a01863947bab#modal_lag_share=0.136] of them).
Post hoc, surface A's 70 steps fall into 8 samples of 8 or 9 plays, and every
block of eight plays holds eight different samples
([metric:sound_bank/loop@a01863947bab#pool0_bag_distinct=8] of
[metric:sound_bank/loop@a01863947bab#pool0_bag_blocks=8]; shuffled labels
never did in 500 tries), each block in its own order
([metric:sound_bank/loop@a01863947bab#pool0_distinct_orders=8]): a shuffled
cycle, carried across pauses and other surfaces. Surface B fits a cycle of
seven only when `sound_demo`'s cluster defines its pool
([metric:sound_bank/loop@a01863947bab#var_fB_bag_distinct=6] of
[metric:sound_bank/loop@a01863947bab#var_fB_bag_blocks=6]); surface C has
too few repeats to test.

`sound_demo`'s clusters fA, fB and fC are surfaces, not samples: the walk
changes cluster [metric:sound_bank/loop@a01863947bab#switches=27] times where
a within-run shuffle gives
[metric:sound_bank/loop@a01863947bab#switches_shuffle_mean=84.451]. Sample
identity is the sharper surface label: five fC steps (172.6, 172.9, 210.0,
210.3, 211.9 s) replay surface A's samples, and the fA steps at 177.5-178.1 s
and 184.4-186.3 s are none of surface A's samples: the 177.8 s step recurs at
186.3 s inside an fC stretch, and the fC step at 177.2 s recurs at 187.5 s.

The bank names the class at a labelled onset for
[metric:sound_bank/bank@a01863947bab#onset_exact=222] of
[metric:sound_bank/bank@a01863947bab#onset_n=240] events, and the gun for
[metric:sound_bank/bank@a01863947bab#shots_gun_right=26] of
[metric:sound_bank/bank@a01863947bab#shots_n=30] shots: two Phantom bursts
read as Vandal bursts and two Vandal sprays as Phantom bursts. Equips
separate (knife
[metric:sound_bank/bank@a01863947bab#knife_equip_onset_correct=16] of 16,
Vandal and Phantom never confused). Detection over the clip at 0.50 finds
footsteps with recall [metric:sound_bank/bank@a01863947bab#footstep_recall=0.98]
and precision [metric:sound_bank/bank@a01863947bab#footstep_precision=0.765];
most of its false detections sit within a second of a labelled sound
(a later part of an equip, a shot's tail), and only
[metric:sound_bank/bank@a01863947bab#background_detections=18] of all
[metric:sound_bank/bank@a01863947bab#detections=474] fall farther away.
Purchase and the buy menu's close, with one reference each, name none of
their events.

This is a prototype; nothing in `reticle/` uses it.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
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
    import sound_demo  # noqa: E402  (imports the audio bank's front end)

VERSION = "sound-bank-0.1.0"
STORE = Path.home() / "reticle-store"
OUT = STORE / "analysis" / "sound-bank"
SESSION = sound_demo.SESSION
CAPTURE = sound_demo.CAPTURE

# ---------------------------------------------------------------------------
# Labelled events
# ---------------------------------------------------------------------------


def events() -> list[dict]:
    """Every reviewed candidate with the player's last answer as its class."""
    man = json.loads(sound_demo.MANIFEST.read_text(encoding="utf-8"))
    ans = sound_demo._answered(sound_demo.LABELS)
    out = []
    for c in man["candidates"]:
        r = ans.get(c["key"])
        if r is None or r["answer"] not in ("accept", "relabel"):
            continue
        lab = r["label"]
        if lab == "other":
            name = (r.get("other_name") or "").lower()
            lab = "buy_menu_close" if "buy menu clos" in name else "other"
        out.append({"key": c["key"], "t0": c["t0"], "t1": c["t1"], "cls": lab,
                    "variant": r.get("variant"), "other_name": r.get("other_name"),
                    "phase": c["phase"]})
    return sorted(out, key=lambda e: e["t0"])


def audio() -> tuple[np.ndarray, int]:
    x, rate = audio_probe.decode(CAPTURE)
    return x.mean(axis=1).astype(np.float64), int(rate)


# ---------------------------------------------------------------------------
# Loop test
# ---------------------------------------------------------------------------

BAND = (100.0, 6000.0)
DEC = 3                          # 48 kHz -> 16 kHz
PRE_S, LEN_S, LAG_S = 0.02, 0.17, 0.03
RUN_GAP_S = 0.6
WALK_FROM_S = 170.0
COARSE = np.round(np.arange(0.95, 1.0501, 0.0025), 4)
FINE_STEP = 0.0005
REFINE_FROM = 0.4
DUP = 0.80                       # the pre-registered duplicate score
LOGF_BPO, LOGF_SHIFT = 48, 4


def bandpass(m: np.ndarray, rate: int) -> np.ndarray:
    n = 1 << int(np.ceil(np.log2(len(m))))
    F = np.fft.rfft(m, n)
    f = np.fft.rfftfreq(n, 1.0 / rate)
    F[(f < BAND[0]) | (f > BAND[1])] = 0
    return np.fft.irfft(F, n)[:len(m)]


class Wave:
    """The band-passed clip at 48 kHz, read at 16 kHz on any resample ratio."""

    def __init__(self, m: np.ndarray, rate: int):
        if rate != 48000:
            raise SystemExit(f"expected 48 kHz audio, got {rate}")
        self.f = bandpass(m, rate)
        self.rate = rate
        self.la = int(round(LEN_S * rate / DEC))
        self.lb = self.la + 2 * int(round(LAG_S * rate / DEC))
        self.nfft = 1 << int(np.ceil(np.log2(self.la + self.lb)))

    def query(self, t0: float, ratios) -> np.ndarray:
        """[R, la] the step from t0 - PRE_S, time-scaled by each ratio (pitch x r)."""
        p0 = (t0 - PRE_S) * self.rate
        k = np.arange(self.la) * DEC
        pos = p0 + np.asarray(ratios)[:, None] * k[None]
        return np.interp(pos, np.arange(len(self.f)), self.f)

    def ref(self, t0: float, shift_s: float = 0.0) -> np.ndarray:
        i0 = int(round((t0 - PRE_S - LAG_S + shift_s) * self.rate))
        return self.f[i0:i0 + self.lb * DEC:DEC].copy()


def prep(A: np.ndarray, nfft: int) -> tuple[np.ndarray, np.ndarray, int]:
    """A query's conjugate spectrum, row norms and length, reused across partners."""
    return np.conj(np.fft.rfft(A, nfft, axis=1)), np.sqrt((A * A).sum(1)) + 1e-18, A.shape[1]


def ncc(A, b: np.ndarray, nfft: int) -> tuple[np.ndarray, np.ndarray]:
    """Peak NCC of each query row sliding inside b, and its lag (samples)."""
    FA, na, la = A if isinstance(A, tuple) else prep(A, nfft)
    lb = len(b)
    Fb = np.fft.rfft(b, nfft)
    c = np.fft.irfft(FA * Fb[None], nfft, axis=1)[:, :lb - la + 1]
    e = np.concatenate([[0.0], np.cumsum(b * b)])
    nb = np.sqrt(np.maximum(e[la:] - e[:-la], 1e-18))[:lb - la + 1]
    s = c / (na[:, None] * nb[None])
    j = s.argmax(1)
    return s[np.arange(len(s)), j], j


def pair_score(w: Wave, ti: float, b: np.ndarray, qa=None) -> tuple[float, float, float]:
    """(best score over ratios, its ratio, the ratio-1.0 score) of the step at ti in b."""
    s, _ = ncc(qa if qa is not None else w.query(ti, COARSE), b, w.nfft)
    raw = float(s[np.argmin(np.abs(COARSE - 1.0))])
    k = int(s.argmax())
    best, r = float(s[k]), float(COARSE[k])
    if best >= REFINE_FROM:
        fine = np.round(np.arange(r - 0.0025, r + 0.00251, FINE_STEP), 5)
        sf, _ = ncc(w.query(ti, fine), b, w.nfft)
        if sf.max() > best:
            best, r = float(sf.max()), float(fine[int(sf.argmax())])
    return best, r, raw


def logf_spectra(m: np.ndarray, rate: int, onsets: list[float]) -> np.ndarray:
    """z-scored log power on a log-frequency axis, one row per onset."""
    n = int(round(LEN_S * rate))
    nfft = 16384
    f = np.fft.rfftfreq(nfft, 1.0 / rate)
    nb = int(np.floor(np.log2(BAND[1] / BAND[0]) * LOGF_BPO))
    grid = BAND[0] * 2.0 ** (np.arange(nb) / LOGF_BPO)
    win = np.hanning(n)
    rows = []
    for t0 in onsets:
        i0 = int(round((t0 - PRE_S) * rate))
        P = np.abs(np.fft.rfft(m[i0:i0 + n] * win, nfft)) ** 2
        # Average the bins each log-frequency band covers, then log.
        lo, hi = grid / 2 ** (0.5 / LOGF_BPO), grid * 2 ** (0.5 / LOGF_BPO)
        c = np.concatenate([[0.0], np.cumsum(P)])
        a, b = np.searchsorted(f, lo), np.maximum(np.searchsorted(f, hi), np.searchsorted(f, lo) + 1)
        v = np.log10((c[b] - c[a]) / (b - a) + 1e-14)
        rows.append((v - v.mean()) / (v.std() + 1e-9))
    return np.array(rows)


def logf_score(X: np.ndarray, i: int, j: int) -> float:
    k = LOGF_SHIFT
    a, b = X[i], X[j]
    return max(float(np.corrcoef(a[max(0, s):len(a) + min(0, s)],
                                 b[max(0, -s):len(b) + min(0, -s)])[0, 1]) for s in range(-k, k + 1))


def walking_runs(ev: list[dict]) -> list[list[dict]]:
    steps = [e for e in ev if e["cls"] == "footstep" and e["t0"] >= WALK_FROM_S]
    runs: list[list[dict]] = []
    for e in steps:
        if runs and e["t0"] - runs[-1][-1]["t0"] < RUN_GAP_S:
            runs[-1].append(e)
        else:
            runs.append([e])
    return runs


PAIRS = OUT / "loop-pairs-20260929.json"
FIGURE = OUT / "loop-pair-scores-20260929.png"
#: Post hoc, after the pre-registered 0.80 read the histogram: its valley lies
#: at 0.60-0.65, so a surface's pool is an average-linkage group at 0.62, and
#: one sample is an average-linkage group at 0.85 inside it. A step joins a
#: sample of three or more plays when it averages 0.75 against its plays.
POOL_T, ID_T, ASSIGN_T, MIN_PLAYS = 0.62, 0.85, 0.75, 3
BAG_NULL = 500
#: Pools and samples read the ratio-searched score. No replayed sample needed
#: a ratio off 1.000 by 0.5%, but the search lifts some different-sample pairs
#: of one surface over 0.80; on the ratio-1.0 score ("raw") two of surface A's
#: samples leave its pool at POOL_T, so the pool reading depends on this choice.
POOL_SCORE = "score"
#: The variant reading's sample threshold (its pool is the agent's cluster).
VAR_ID_T = 0.80


def pair_table(force: bool = False) -> dict:
    """Instrument checks and every walking-step pair's scores, cached in the store."""
    if PAIRS.is_file() and not force:
        d = json.loads(PAIRS.read_text(encoding="utf-8"))
        if d.get("version") == VERSION and "instrument" in d:
            return d
    ev = events()
    m, rate = audio()
    w = Wave(m, rate)
    runs = walking_runs(ev)
    steps = [e for r in runs for e in r]
    run_of = {e["key"]: k for k, r in enumerate(runs) for e in r}
    pos_of = {e["key"]: p for r in runs for p, e in enumerate(r)}

    # Instrument.
    inst = {}
    s0 = steps[len(steps) // 2]
    inst["self_7ms"] = pair_score(w, s0["t0"], w.ref(s0["t0"], 0.007))[0]
    syn, synp = [], []
    for e in steps[5:len(steps):12]:
        other = steps[(steps.index(e) + 40) % len(steps)]
        i0 = int(round((other["t0"] - 0.23) * rate))
        bg = w.f[i0:i0 + w.lb * DEC:DEC]
        syn.append(pair_score(w, e["t0"], w.ref(e["t0"]) + bg)[0])
        # The same step replayed 2% higher: time-compressed by 1.02.
        p0 = (e["t0"] - PRE_S - LAG_S) * rate
        up = np.interp(p0 + np.arange(w.lb) * DEC * 1.02, np.arange(len(w.f)), w.f)
        synp.append(pair_score(w, e["t0"], up + bg))
    inst["synthetic_dup_min"] = float(min(syn))
    inst["synthetic_dup_median"] = float(np.median(syn))
    inst["synthetic_pitch_min"] = float(min(s for s, _, _ in synp))
    inst["synthetic_pitch_ratio_median"] = float(np.median([r for _, r, _ in synp]))
    inst["synthetic_pitch_raw_median"] = float(np.median([raw for _, _, raw in synp]))
    knives = [e for e in ev if e["cls"] == "knife_equip"]
    kf = [pair_score(w, k["t0"], w.ref(s["t0"]))[0] for k in knives for s in steps[::4]]

    refs = {e["key"]: w.ref(e["t0"]) for e in steps}
    X = logf_spectra(m, rate, [e["t0"] for e in steps])
    pairs = []
    for i, a in enumerate(steps):
        qa = prep(w.query(a["t0"], COARSE), w.nfft)
        for j in range(i + 1, len(steps)):
            b = steps[j]
            s, r, raw = pair_score(w, a["t0"], refs[b["key"]], qa)
            same_run = run_of[a["key"]] == run_of[b["key"]]
            pairs.append({"i": i, "j": j, "score": round(s, 4), "ratio": r, "raw": round(raw, 4),
                          "logf": round(logf_score(X, i, j), 4), "same_run": same_run,
                          "lag": pos_of[b["key"]] - pos_of[a["key"]] if same_run else None})
    d = {"version": VERSION, "session_id": SESSION, "source_path": CAPTURE,
         "steps": [{k: e[k] for k in ("key", "t0", "variant")} for e in steps],
         "runs": [[e["key"] for e in r] for r in runs], "instrument": inst,
         "knife_vs_step": [round(v, 4) for v in kf], "pairs": pairs}
    OUT.mkdir(parents=True, exist_ok=True)
    PAIRS.write_text(json.dumps(d), encoding="utf-8")
    return d


def _agglo(M: np.ndarray, idx: list[int], thr: float) -> list[list[int]]:
    """Average-linkage groups of idx whose mean pair score stays >= thr."""
    cl = [[i] for i in idx]
    while True:
        best, arg = thr, None
        for x in range(len(cl)):
            for y in range(x + 1, len(cl)):
                s = float(np.mean(M[np.ix_(cl[x], cl[y])]))
                if s > best:
                    best, arg = s, (x, y)
        if arg is None:
            return sorted(cl, key=lambda c: (-len(c), min(c)))
        x, y = arg
        cl[x] = cl[x] + cl[y]
        del cl[y]


def _bag_blocks(seq: np.ndarray, K: int) -> tuple[float, int, int, int]:
    """Best phase's share of K-blocks whose assigned plays are all distinct."""
    best = (-1.0, 0, 0, 0)
    for ph in range(K):
        ok = tot = 0
        for b0 in range(ph, len(seq) - K + 1, K):
            blk = [x for x in seq[b0:b0 + K] if x >= 0]
            tot += 1
            ok += len(blk) == len(set(blk))
        best = max(best, (ok / max(tot, 1), ok, tot, ph))
    return best


def _score_matrix(d: dict) -> np.ndarray:
    n = len(d["steps"])
    M = np.eye(n)
    for p in d["pairs"]:
        M[p["i"], p["j"]] = M[p["j"], p["i"]] = p[POOL_SCORE]
    return M


def pools(d: dict, by_variant: bool = False) -> list[dict]:
    """Post hoc: surface pools, their samples, and the shuffle-bag test per pool.

    By default a pool is an average-linkage group at POOL_T and a sample one at
    ID_T inside it. `by_variant` instead takes samples at VAR_ID_T over all
    steps and pools them by their majority `sound_demo` cluster (fA, fB, fC):
    the agent's clusters decide the pool there, so it is the weaker reading.
    """
    steps, n = d["steps"], len(d["steps"])
    M = _score_matrix(d)
    R = np.ones((n, n))
    for p in d["pairs"]:
        R[p["i"], p["j"]] = R[p["j"], p["i"]] = p["ratio"]
    rng = np.random.default_rng(0)
    out = []
    if by_variant:
        ids = _agglo(M, list(range(n)), VAR_ID_T)
        maj = [Counter(steps[i]["variant"] for i in c).most_common(1)[0][0] for c in ids]
        groups = [(sorted(i for c, v in zip(ids, maj) if v == var for i in c),
                   [c for c, v in zip(ids, maj) if v == var and len(c) >= MIN_PLAYS])
                  for var in ("fA", "fB", "fC")]
    else:
        groups = [(sorted(pool), None) for pool in _agglo(M, list(range(n)), POOL_T)]
    for pool, samples in groups:
        if len(pool) < 2 * MIN_PLAYS:
            continue
        if samples is None:
            samples = [c for c in _agglo(M, pool, ID_T) if len(c) >= MIN_PLAYS]
        lab = []
        for i in pool:
            s = [float(np.mean([M[i, j] for j in c if j != i])) if any(j != i for j in c) else -1.0
                 for c in samples]
            k = int(np.argmax(s)) if s else -1
            lab.append(k if k >= 0 and s[k] >= ASSIGN_T else -1)
        seq = np.array(lab)
        bags = {}
        for K in range(max(2, len(samples) - 2), len(samples) + 3):
            obs = _bag_blocks(seq, K)
            null = np.array([_bag_blocks(rng.permutation(seq), K)[0] for _ in range(BAG_NULL)])
            bags[K] = {"distinct": obs[1], "blocks": obs[2], "phase": obs[3],
                       "null_mean": round(float(null.mean()), 3),
                       "p": round(float((null >= obs[0]).mean()), 4)}
        # Block orders at the best K's phase: a fixed loop repeats one order.
        Kb = max(bags, key=lambda K: (bags[K]["distinct"] / max(1, bags[K]["blocks"]), K))
        ph = bags[Kb]["phase"]
        orders = ["".join("abcdefghijklmnop"[x] if x >= 0 else "." for x in seq[b0:b0 + Kb])
                  for b0 in range(ph, len(seq) - Kb + 1, Kb)]
        last, gaps = {}, []
        for pos, x in enumerate(seq):
            if x >= 0:
                if x in last:
                    gaps.append(pos - last[x])
                last[x] = pos
        same, diff, same_r = [], [], []
        for a in range(len(pool)):
            for b in range(a + 1, len(pool)):
                if seq[a] >= 0 and seq[b] >= 0:
                    (same if seq[a] == seq[b] else diff).append(M[pool[a], pool[b]])
                    if seq[a] == seq[b]:
                        same_r.append(R[pool[a], pool[b]])
        spans, cur = [], None
        for i in pool:
            t = steps[i]["t0"]
            if cur and t - cur[1] < 0.45:
                cur[1] = t
            else:
                cur = [t, t]
                spans.append(cur)
        out.append({"steps": len(pool), "variants": dict(Counter(steps[i]["variant"] for i in pool)),
                    "samples": len(samples), "plays": [len(c) for c in samples],
                    "unassigned": int((seq < 0).sum()), "bag": bags, "best_K": Kb,
                    "orders": orders, "distinct_orders": len(set(o for o in orders if "." not in o)),
                    "full_orders": sum("." not in o for o in orders),
                    "gaps": dict(sorted(Counter(gaps).items())),
                    "same_sample_median": float(np.median(same)) if same else None,
                    "same_sample_pairs": len(same),
                    "same_sample_ratio_off_05pct": (float(np.mean(np.abs(np.array(same_r) - 1) >= 0.005))
                                                    if same_r else None),
                    "same_sample_ratio_exact": (float(np.mean(np.abs(np.array(same_r) - 1) < 1e-6))
                                                if same_r else None),
                    "other_sample_median": float(np.median(diff)) if diff else None,
                    "spans": [[round(a, 2), round(b + 0.31, 2)] for a, b in spans if b > a],
                    "sequence": "/".join("".join("abcdefghijklmnop"[x] if x >= 0 else "."
                                                 for x, t in zip(seq, [steps[i]["t0"] for i in pool])
                                                 if a <= t <= b) for a, b in spans),
                    "keys": [steps[i]["key"] for i in pool], "labels": seq.tolist()})
    return out


def loop_test(record: bool, force: bool = False) -> dict:
    d = pair_table(force)
    steps, pairs, inst = d["steps"], d["pairs"], d["instrument"]
    runs = d["runs"]
    kf = np.array(d["knife_vs_step"])
    inst = dict(inst, knife_vs_step_median=float(np.median(kf)),
                knife_vs_step_p99=float(np.percentile(kf, 99)), knife_vs_step_max=float(kf.max()))
    print(f"{len(steps)} walking steps in {len(runs)} runs ({[len(r) for r in runs]})")
    print("instrument:", {k: round(v, 3) for k, v in inst.items()})
    within = [p for p in pairs if p["same_run"]]
    sc = np.array([p["score"] for p in within])
    part = defaultdict(float)
    for p in within:
        part[p["i"]] = max(part[p["i"]], p["score"])
        part[p["j"]] = max(part[p["j"]], p["score"])
    frac_partner = float(np.mean([part[i] >= DUP for i in range(len(steps))]))
    dups = [p for p in pairs if p["score"] >= DUP]
    fwd = {}
    for p in sorted((p for p in within if p["score"] >= DUP), key=lambda p: p["lag"]):
        fwd.setdefault(p["i"], p["lag"])
    modal = Counter(fwd.values()).most_common(1)[0] if fwd else (None, 0)
    var = {k: s["variant"] for k, s in enumerate(steps)}

    def switches(seqs):
        return sum(sum(a != b for a, b in zip(s, s[1:])) for s in seqs)
    key_var = {s["key"]: s["variant"] for s in steps}
    seqs = [[key_var[k] for k in r] for r in runs]
    rng = np.random.default_rng(0)
    null = [switches([list(rng.permutation(s)) for s in seqs]) for _ in range(2000)]
    res = {
        "n_steps": len(steps), "n_runs": len(runs), "n_pairs": len(pairs),
        "n_pairs_within": len(within), **inst,
        "within_median": float(np.median(sc)), "within_max": float(sc.max()),
        "within_060_080": int(((sc >= 0.6) & (sc < DUP)).sum()),
        "within_ge_080": int((sc >= DUP).sum()),
        "frac_steps_with_partner_080": frac_partner, "all_ge_080": len(dups),
        "dup_ratio_off_05pct": float(np.mean([abs(p["ratio"] - 1) >= 0.005 for p in dups])),
        "dup_raw_below_080": float(np.mean([p["raw"] < DUP for p in dups])),
        "modal_lag": modal[0], "modal_lag_share": modal[1] / max(1, len(fwd)),
        "logf_within_median": float(np.median([p["logf"] for p in within])),
        "logf_within_p99": float(np.percentile([p["logf"] for p in within], 99)),
        "switches": switches(seqs), "switches_shuffle_mean": float(np.mean(null)),
        "dup_cross_cluster": sum(var[p["i"]] != var[p["j"]] for p in dups),
    }
    pl = pools(d)
    pv = pools(d, by_variant=True)
    for tag, p in [("pool0", pl[0])] + [(f"var_{v}", p) for v, p in zip(("fA", "fB", "fC"), pv)]:
        b = p["bag"][p["best_K"]]
        res.update({f"{tag}_steps": p["steps"], f"{tag}_samples": p["samples"],
                    f"{tag}_unassigned": p["unassigned"], f"{tag}_best_K": p["best_K"],
                    f"{tag}_bag_distinct": b["distinct"], f"{tag}_bag_blocks": b["blocks"],
                    f"{tag}_bag_p": b["p"], f"{tag}_distinct_orders": p["distinct_orders"],
                    f"{tag}_full_orders": p["full_orders"],
                    f"{tag}_min_gap": min(p["gaps"]) if p["gaps"] else None,
                    f"{tag}_same_sample_median": p["same_sample_median"],
                    f"{tag}_same_sample_pairs": p["same_sample_pairs"],
                    f"{tag}_same_sample_ratio_off_05pct": p["same_sample_ratio_off_05pct"],
                    f"{tag}_same_sample_ratio_exact": p["same_sample_ratio_exact"],
                    f"{tag}_other_sample_median": p["other_sample_median"]})
    print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in res.items()}))
    for k, p in enumerate(pl + pv):
        print(f"\n{'pool' if k < len(pl) else 'variant pool'} {k if k < len(pl) else k - len(pl)}: "
              f"{p['steps']} steps {p['variants']}, {p['samples']} samples "
              f"(plays {p['plays']}), {p['unassigned']} unassigned; gaps {p['gaps']}")
        for K, b in p["bag"].items():
            print(f"   K={K}: {b['distinct']}/{b['blocks']} blocks distinct at phase {b['phase']} "
                  f"(shuffled labels {b['null_mean']}, p {b['p']})")
        print(f"   orders at K={p['best_K']}: {' '.join(p['orders'])}")
        print(f"   spans: {p['spans']}")
        print(f"   sequence: {p['sequence']}")
    # Figure: within-run pairs split by the post hoc sample identity.
    lab = {}
    for p in pl:
        for key, x in zip(p["keys"], p["labels"]):
            if x >= 0:
                lab[key] = (id(p), x)
    keys = [s["key"] for s in steps]
    same = [q["score"] for q in within if keys[q["i"]] in lab and lab.get(keys[q["i"]]) == lab.get(keys[q["j"]])]
    other = [q["score"] for q in within if not (keys[q["i"]] in lab and lab.get(keys[q["i"]]) == lab.get(keys[q["j"]]))]
    draw_hist(FIGURE, [("within-run pairs, same sample (post hoc)", same, (180, 90, 20)),
                       ("within-run pairs, other pairs", other, (60, 160, 60)),
                       ("knife equip vs step (null)", list(kf), (40, 40, 200))], inst)
    print(f"figure {FIGURE}")
    (OUT / "loop-pools-20260929.json").write_text(json.dumps(
        {"version": VERSION, "session_id": SESSION, "summary": res, "pools": pl}, indent=1),
        encoding="utf-8")
    if record:
        from reticle import metrics
        metrics.record("sound_bank", part="loop", session=SESSION,
                       values={k: (round(v, 4) if isinstance(v, float) else v)
                               for k, v in res.items()},
                       deps=_deps({"band": BAND, "len_s": LEN_S, "lag_s": LAG_S, "dup": DUP,
                                   "coarse": [float(COARSE[0]), float(COARSE[-1]), 0.0025],
                                   "run_gap_s": RUN_GAP_S, "walk_from_s": WALK_FROM_S,
                                   "pool_t": POOL_T, "id_t": ID_T, "assign_t": ASSIGN_T,
                                   "var_id_t": VAR_ID_T, "pool_score": POOL_SCORE}))
    return res


def draw_hist(path: Path, series, inst, bins: int = 40) -> None:
    """Pair-score histograms as a PNG (cv2; the venv has no plotting library)."""
    import cv2
    W, H, L, B, T = 1000, 560, 70, 60, 150
    im = np.full((H, W, 3), 255, np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    fr = [np.histogram(v, bins=bins, range=(0, 1))[0] / max(1, len(v)) for _, v, _ in series]
    ymax = max(f.max() for f in fr) * 1.08
    pw, ph = W - L - 20, H - B - T
    bw = pw / bins
    for s, ((name, v, col), f) in enumerate(zip(series, fr)):
        for k, h in enumerate(f):
            x0 = int(L + k * bw + s * bw / len(series))
            cv2.rectangle(im, (x0, int(T + ph - h / ymax * ph)),
                          (int(x0 + bw / len(series)) - 1, T + ph), col, -1)
        cv2.rectangle(im, (L + 10, 40 + 20 * s), (L + 24, 54 + 20 * s), col, -1)
        cv2.putText(im, f"{name} (n={len(v)})", (L + 32, 53 + 20 * s), font, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.rectangle(im, (L, T), (L + pw, T + ph), (0, 0, 0), 1)
    for k in range(0, 11):
        x = int(L + k / 10 * pw)
        cv2.line(im, (x, T + ph), (x, T + ph + 5), (0, 0, 0), 1)
        cv2.putText(im, f"{k / 10:.1f}", (x - 10, T + ph + 20), font, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    for v in np.linspace(0, ymax, 5):
        y = int(T + ph - v / ymax * ph)
        cv2.putText(im, f"{v:.2f}", (L - 45, y + 5), font, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    marks = [("A", "step vs itself at 7 ms", inst["self_7ms"]),
             ("B", "step added onto another's preceding 230 ms (median)", inst["synthetic_dup_median"]),
             ("C", "same, lowest of 13", inst["synthetic_dup_min"]),
             ("D", "same at +2% pitch, lowest of 13", inst["synthetic_pitch_min"])]
    for n, (tag, name, v) in enumerate(marks):
        x = int(L + min(v, 0.999) * pw)
        cv2.line(im, (x, T), (x, T + ph), (0, 0, 0), 1)
        cv2.putText(im, tag, (x - 14, T + 14 + 14 * n), font, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(im, f"{tag}: {name} = {v:.2f}", (L + 520, 53 + 20 * n), font, 0.45, (0, 0, 0), 1,
                    cv2.LINE_AA)
    cv2.putText(im, "Footstep pair scores: peak waveform NCC over +-30 ms lag and pitch ratio 0.95-1.05",
                (L, 22), font, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(im, "score (170 ms from 20 ms before onset, 100 Hz-6 kHz, 16 kHz)",
                (L + pw // 2 - 230, H - 20), font, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(im, "share of each series", (5, T - 8), font, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), im)


# ---------------------------------------------------------------------------
# Common-sound bank
# ---------------------------------------------------------------------------

HOP = 0.01
CTX_S = 4.0
LEAD_S = 0.02
THETA = 0.50
TOL_S = 0.10
#: A sensitivity reading, not the pre-registered one: the cutter's onsets
#: may sit on a different part of a multi-part sound from one event to the next.
TOL_WIDE_S = 0.25
NEAR_S = (0.5, 1.0)
ONSET_SLACK_S = 0.05
SD_MIN = 0.5                     # dB; a flatter patch is silence and scores 0


def features(m: np.ndarray, rate: int) -> np.ndarray:
    """[64, frames] log-mel dB above a +-4 s context median, floored at 0."""
    L = sound_demo.logmel(m, rate)                     # [frames, 64]
    n = len(L)
    blk = int(round(1.0 / HOP))
    ctx = int(round(CTX_S / HOP))
    med = np.empty_like(L)
    for b0 in range(0, n, blk):
        med[b0:b0 + blk] = np.median(L[max(0, b0 - ctx):b0 + blk + ctx], axis=0)
    return np.maximum(L - med, 0.0).T.astype(np.float64)


def class_len(ev: list[dict]) -> dict[str, int]:
    by = defaultdict(list)
    for e in ev:
        by[e["cls"]].append(e["t1"] - e["t0"])
    return {c: int(round(min(1.0, max(0.2, float(np.median(v)) + 0.1)) / HOP)) for c, v in by.items()}


def slide_corr(D: np.ndarray, FD: np.ndarray, nfft: int, cs1, cs2, tpl: np.ndarray) -> np.ndarray:
    """z-scored patch correlation of `tpl` [64, n] starting at every frame of D."""
    nb, n = tpl.shape
    Tz = (tpl - tpl.mean()) / (tpl.std() + 1e-9)
    FT = np.fft.rfft(Tz, nfft, axis=1)
    num = np.fft.irfft((np.conj(FT) * FD).sum(0), nfft)[:D.shape[1] - n + 1]
    N = nb * n
    s1 = cs1[n:] - cs1[:-n]
    s2 = cs2[n:] - cs2[:-n]
    var = np.maximum(s2 / N - (s1 / N) ** 2, 0.0)
    sd = np.sqrt(var)
    out = num / (N * np.maximum(sd, 1e-9))
    out[sd < SD_MIN] = 0.0
    return out


def bank(record: bool) -> dict:
    ev = [e for e in events()]
    m, rate = audio()
    D = features(m, rate)
    nf = D.shape[1]
    nfft = 1 << int(np.ceil(np.log2(nf + 200)))
    FD = np.fft.rfft(D, nfft, axis=1)
    col1, col2 = D.sum(0), (D * D).sum(0)
    cs1 = np.concatenate([[0.0], np.cumsum(col1)])
    cs2 = np.concatenate([[0.0], np.cumsum(col2)])
    refs = [e for e in ev if e["cls"] != "other"]
    clen = class_len(refs)
    classes = sorted(clen)
    print(f"{len(refs)} references in {len(classes)} classes; lengths (s):",
          {c: clen[c] * HOP for c in classes})
    # Per class: the self-excluded best reference score at every frame.
    S = {c: np.full(nf, -1.0) for c in classes}
    Sv = {v: np.full(nf, -1.0) for v in ("fA", "fB", "fC")}
    for e in refs:
        n = clen[e["cls"]]
        f0 = int(round((e["t0"] - LEAD_S) / HOP))
        tpl = D[:, f0:f0 + n]
        c = slide_corr(D, FD, nfft, cs1, cs2, tpl)
        c = np.concatenate([c, np.zeros(nf - len(c))])
        a = max(0, int(round((e["t0"] - LEAD_S) / HOP)) - n - int(TOL_S / HOP))
        b = int(round((e["t1"] + TOL_S) / HOP))
        c[a:b] = -1.0
        np.maximum(S[e["cls"]], c, out=S[e["cls"]])
        if e["cls"] == "footstep" and e["variant"] in Sv:
            np.maximum(Sv[e["variant"]], c, out=Sv[e["variant"]])

    def at_onset(Sc, e):
        f = int(round((e["t0"] - LEAD_S) / HOP))
        k = int(round(ONSET_SLACK_S / HOP))
        return float(Sc[max(0, f - k):f + k + 1].max())

    # Reading 1: the class named at each labelled onset.
    onset = []
    for e in ev:
        sc = {c: at_onset(S[c], e) for c in classes}
        best = max(sc, key=sc.get)
        row = {"t0": e["t0"], "true": e["cls"], "named": best, "score": sc[best],
               "true_score": sc.get(e["cls"])}
        if e["cls"] == "footstep" and e["variant"] in Sv:
            sv = {v: at_onset(Sv[v], e) for v in Sv}
            row["variant"], row["variant_named"] = e["variant"], max(sv, key=sv.get)
        onset.append(row)
    conf1 = Counter((r["true"], r["named"]) for r in onset)

    # Reading 2: detection over the whole clip.
    cand = []
    for c in classes:
        s = S[c]
        n = clen[c]
        pk = np.where((s[1:-1] >= THETA) & (s[1:-1] >= s[:-2]) & (s[1:-1] > s[2:]))[0] + 1
        for f in sorted(pk, key=lambda f: -s[f]):
            cand.append((float(s[f]), f, c))
    cand.sort(key=lambda d: -d[0])
    taken = np.zeros(nf, bool)
    dets = []
    for sc, f, c in cand:
        if taken[f]:
            continue
        dets.append({"t": (f * HOP) + LEAD_S, "cls": c, "score": sc})
        a = max(0, f - int(TOL_S / HOP))
        taken[a:f + max(int(0.15 / HOP), int(0.8 * clen[c]))] = True
    dets.sort(key=lambda d: d["t"])
    per, conf2 = match(dets, ev, classes, conf1, TOL_S)
    per_wide, conf2_wide = match([dict(d) for d in dets], ev, classes, conf1, TOL_WIDE_S)
    _print_bank(classes, per, conf1, conf2, onset)
    res = {"per_class": per, "confusion_onset": {f"{a}|{b}": v for (a, b), v in conf1.items()},
           "confusion_detect": {f"{a}|{b}": v for (a, b), v in conf2.items()}}
    shots = [r for r in onset if r["true"].split("_")[0] in ("vandal", "phantom")
             and r["true"].split("_")[1] in ("single", "burst", "spray")]
    vals = {"shots_n": len(shots),
            "shots_gun_right": sum(r["named"].split("_")[0] == r["true"].split("_")[0] for r in shots),
            "shots_exact": sum(r["named"] == r["true"] for r in shots),
            "onset_n": len(onset), "onset_exact": sum(r["named"] == r["true"] for r in onset),
            "variant_n": sum(1 for r in onset if "variant" in r),
            "variant_right": sum(1 for r in onset if "variant" in r and r["variant"] == r["variant_named"]),
            "detections": len(dets),
            "near_detections": sum(1 for d in dets if d.get("where") == "near"),
            "background_detections": sum(1 for d in dets if d.get("where") == "background")}
    for c, p in per.items():
        vals.update({f"{c}_n": p["n"], f"{c}_onset_correct": p["onset_correct"], f"{c}_tp": p["tp"],
                     f"{c}_det": p["det"]})
        if p["recall"] is not None:
            vals[f"{c}_recall"] = p["recall"]
        if p["precision"] is not None:
            vals[f"{c}_precision"] = p["precision"]
            vals[f"{c}_background"] = p["background"]
        if p["precision_bg"] is not None:
            vals[f"{c}_precision_bg"] = p["precision_bg"]
    for (a, b), v in conf1.items():
        if a != b:
            vals[f"onset_{a}_as_{b}"] = v
    for c, p in per_wide.items():
        vals[f"{c}_tp_wide"] = p["tp"]
        if p["precision_bg"] is not None:
            vals[f"{c}_precision_bg_wide"] = p["precision_bg"]
    print(f"\nat {TOL_WIDE_S} s tolerance:")
    _print_bank(classes, per_wide, Counter(), conf2_wide, [])
    res["per_class_wide"] = per_wide
    res["summary"] = vals
    print(json.dumps(vals))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "bank-20260929.json").write_text(json.dumps(
        {"version": VERSION, "session_id": SESSION, "source_path": CAPTURE,
         "theta": THETA, "tol_s": TOL_S, "class_len_s": {c: clen[c] * HOP for c in classes},
         "onset": onset, "detections": dets, **res}, indent=1), encoding="utf-8")
    if record:
        from reticle import metrics
        metrics.record("sound_bank", part="bank", session=SESSION, values=vals,
                       deps=_deps({"theta": THETA, "tol_s": TOL_S, "tol_wide_s": TOL_WIDE_S, "near_s": NEAR_S, "ctx_s": CTX_S, "lead_s": LEAD_S,
                                   "onset_slack_s": ONSET_SLACK_S, "sd_min": SD_MIN}))
    return res


def match(dets: list[dict], ev: list[dict], classes, conf1, tol: float):
    """Match detections to labelled onsets within tol (every labelled event,
    'other' included); per-class counts and the detection confusion."""
    used = set()
    for d in sorted(dets, key=lambda d: -d["score"]):
        near = [k for k, e in enumerate(ev) if k not in used and abs(e["t0"] - d["t"]) <= tol]
        if near:
            k = min(near, key=lambda k: abs(ev[k]["t0"] - d["t"]))
            used.add(k)
            d["match"] = k
    got = {d["match"]: d for d in dets if "match" in d}
    conf2 = Counter()
    for k, e in enumerate(ev):
        conf2[(e["cls"], got[k]["cls"] if k in got else "missed")] += 1
    # An unmatched detection near a labelled span (0.5 s before it to 1 s
    # after) is a later part, tail or onset jitter of a labelled sound; one
    # farther from every span is on the background.
    for d in dets:
        if "match" not in d:
            d["where"] = ("near" if any(e["t0"] - NEAR_S[0] <= d["t"] <= e["t1"] + NEAR_S[1] for e in ev)
                          else "background")
            conf2[(d["where"], d["cls"])] += 1
    per = {}
    for c in classes:
        n_true = sum(1 for e in ev if e["cls"] == c)
        n_det = sum(1 for d in dets if d["cls"] == c)
        tp = conf2[(c, c)]
        n_bg = conf2[("background", c)]
        per[c] = {"n": n_true, "det": n_det, "tp": tp, "background": n_bg,
                  "recall": round(tp / n_true, 3) if n_true else None,
                  "precision": round(tp / n_det, 3) if n_det else None,
                  # Precision counting only detections off every labelled span as false.
                  "precision_bg": round(tp / (tp + n_bg), 3) if tp + n_bg else None,
                  "onset_correct": conf1[(c, c)]}
    return per, conf2


def _print_bank(classes, per, conf1, conf2, onset) -> None:
    print(f"\n{'class':<16}{'n':>4}{'onset':>7}{'det':>5}{'tp':>4}{'bg':>4}{'recall':>8}{'prec':>7}{'prec_bg':>8}")
    for c in classes:
        p = per[c]
        print(f"{c:<16}{p['n']:>4}{p['onset_correct']:>7}{p['det']:>5}{p['tp']:>4}{p['background']:>4}"
              f"{str(p['recall']):>8}{str(p['precision']):>7}{str(p['precision_bg']):>8}")
    print("\nonset confusions (true -> named: count):")
    for (a, b), v in sorted(conf1.items()):
        if a != b:
            print(f"  {a} -> {b}: {v}")
    print("\ndetection confusions (true -> detected: count):")
    for (a, b), v in sorted(conf2.items()):
        if a != b:
            print(f"  {a} -> {b}: {v}")
    vc = Counter((r["variant"], r["variant_named"]) for r in onset if "variant" in r)
    print("\nfootstep variant at onset (true -> named: count):", dict(vc))


def _deps(params: dict) -> dict:
    lab = sound_demo.LABELS
    return {"version": VERSION, "labels": str(lab), "labels_rows":
            sum(1 for line in lab.read_text(encoding="utf-8").splitlines() if line.strip()),
            "manifest_version": json.loads(sound_demo.MANIFEST.read_text(encoding="utf-8"))["version"],
            **{k: (list(v) if isinstance(v, tuple) else v) for k, v in params.items()}}


def main(argv=None) -> int:
    sound_demo._idle()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("loop", "bank"):
        p = sub.add_parser(name)
        p.add_argument("--record", action="store_true", help="append the run to metrics")
        if name == "loop":
            p.add_argument("--force", action="store_true", help="recompute the cached pair table")
    a = ap.parse_args(argv)
    if a.cmd == "loop":
        loop_test(a.record, a.force)
    else:
        bank(a.record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
