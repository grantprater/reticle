r"""Cut the player's non-ability sound demo into candidates and ask him to name them.

    .\.venv\Scripts\python.exe prototypes\sound_demo.py witness
    .\.venv\Scripts\python.exe prototypes\sound_demo.py cut
    .\.venv\Scripts\python.exe prototypes\sound_demo.py review --serve [--open]

Why this exists
---------------
The audio bank (`audio_bank.py`) names ability casts and keeps a reject class
of everything else, but that reject class is unnamed: knife and gun equips,
shots, footsteps and jumps are what an ability template confuses itself with
(`audio_channel.py`, finding 4). On 2026-09-29 the player recorded one
shooting-range clip, `C:\Users\grant\Videos\2026-09-29 18-50-03.mp4`
(session a01863947bab, not ingested), performing common non-ability sounds in
a stated order. This file turns that clip into proposed labels he confirms or
corrects; a verified label comes only from his review.

Stages
------
`witness` decodes the clip's video once, 20 Hz, and stores fixed-ROI readings
only: the magazine and reserve through the stage 02 digit reader
(`reticle.ocr.read_bottom_hud`, the `hud-scan` owner's reader), the ammo
counter's white fraction (`audio_channel`'s equip witness: hidden means a
non-gun is held [domain:abilities/ammo-hidden-while-non-gun-held]), and a
buy-menu score. The full-load pair names the held gun
[domain:weapons/magazine-and-reserve]. The range has infinite ammo enabled,
so the magazine is not expected to fall per shot; `cut` reports what it did.

`cut` decodes the audio (`audio_probe.decode`), finds sound events with
`audio_events`' RMS envelope and a gate set from this clip's own floor, splits
long events at `audio_bank.onset_curve` peaks where the player walks, and
gives each candidate a proposed class from the player's stated order and the
video witness, keeping both where they disagree. Footstep and jump candidates
are clustered by their mean log-mel (`audio_channel._mel_fb`, the bank's front
end) into candidate surface variants [domain:abilities/footstep-surface-variants]
[domain:abilities/jump-surface-variants]. The manifest goes to
`<store>/analysis/sound-demo/candidates-20260929.json`.

`review --serve` serves a page through `reticle.clipserve`: the source
capture's window plays in the browser by HTTP range, and `/snippet/<i>.wav`
decodes the candidate's audio span in memory and plays it alone. Nothing is
copied to disk. Answers append to `<store>/labels/sound_demo_20260929.jsonl`.

This is a labeller and a candidate cutter; it decides nothing, and nothing in
`reticle/` uses it. Predictions are logged in the store's
`notes/predictions.jsonl` under `sound-demo-20260929`.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import datetime as _dt
import io
import json
import os
import sys
import threading
import urllib.parse
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_var] = "1"


def _idle() -> None:
    """Run at Idle priority; the declared handle types matter on x64."""
    if os.name != "nt":
        return
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.GetPriorityClass.argtypes = [ctypes.c_void_p]
    k.GetPriorityClass.restype = ctypes.c_uint32
    k.SetPriorityClass(k.GetCurrentProcess(), 0x40)


import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "prototypes"))
with contextlib.redirect_stdout(io.StringIO()):
    import audio_bank  # noqa: E402  (sets Below Normal; main() drops to Idle)
    import audio_channel  # noqa: E402
    import audio_events  # noqa: E402
    import audio_probe  # noqa: E402

VERSION = "sound-demo-0.1.0"
STORE = Path.home() / "reticle-store"
OUT = STORE / "analysis" / "sound-demo"
CAPTURE = r"C:\Users\grant\Videos\2026-09-29 18-50-03.mp4"
SESSION = "a01863947bab"
MANIFEST = OUT / "candidates-20260929.json"
WITNESS = OUT / "witness-20260929.npz"
LABELS = STORE / "labels" / "sound_demo_20260929.jsonl"
STEP_S = 0.05

#: The buy menu's card grid, as frame fractions: the sidearm column and the
#: player card left of it. Measured on this clip's 30.0 s frame.
BUY_ROI = (0.07, 0.10, 0.40, 0.30)

# ---------------------------------------------------------------------------
# Video witness
# ---------------------------------------------------------------------------


def witness(force: bool = False) -> dict[str, np.ndarray]:
    """Per-sample fixed-ROI readings of the clip, cached under the store."""
    if WITNESS.is_file() and not force:
        z = np.load(WITNESS)
        return {k: z[k] for k in z.files}
    import av
    import cv2
    cv2.setNumThreads(1)
    from reticle.ocr import Templates, read_bottom_hud
    from reticle.profiles import get_profile
    prof = get_profile("valorant-16x9")
    tpl = Templates.load(prof.name)
    x0, y0, x1, y1 = audio_channel.AMMO_ROI
    bx0, by0, bx1, by1 = BUY_ROI
    rows: dict[str, list] = {k: [] for k in ("t", "mag", "reserve", "white", "buy_edge",
                                             "buy_dark", "buy_ref")}
    ref = None
    nxt = 0.0
    with av.open(CAPTURE) as c:
        st = c.streams.video[0]
        st.thread_type = "SLICE"
        st.thread_count = 1
        for fr in c.decode(st):
            t = float(fr.pts * st.time_base)
            if t + 1e-3 < nxt:
                continue
            nxt = t + STEP_S
            im = fr.to_ndarray(format="bgr24")
            h, w = im.shape[:2]
            b = read_bottom_hud(im, prof, tpl, w, h)
            hsv = cv2.cvtColor(im[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)],
                               cv2.COLOR_BGR2HSV)
            g = cv2.cvtColor(im[int(by0 * h):int(by1 * h), int(bx0 * w):int(bx1 * w)],
                             cv2.COLOR_BGR2GRAY)
            e = cv2.Canny(g, 60, 160) > 0
            if ref is None and abs(t - 30.0) < STEP_S:
                ref = e.astype(np.float32)
            rows["t"].append(t)
            rows["mag"].append(-1 if b.ammo_mag is None else b.ammo_mag)
            rows["reserve"].append(-1 if b.ammo_reserve is None else b.ammo_reserve)
            rows["white"].append(float(((hsv[..., 2] > 200) & (hsv[..., 1] < 40)).mean()))
            rows["buy_edge"].append(e)
            rows["buy_dark"].append(float(g.mean()))
    E = np.stack(rows.pop("buy_edge")).astype(np.float32)
    if ref is None:
        raise SystemExit("no frame at 30.0 s to take the buy-menu reference from")
    # Fraction of the reference's edge pixels present: the menu's card outlines.
    rows["buy_ref"] = list((E * ref[None]).sum((1, 2)) / max(1.0, ref.sum()))
    out = {k: np.asarray(v) for k, v in rows.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(WITNESS, **out, version=VERSION)
    return out


#: Full-load ammo pairs of the guns in the player's order
#: [domain:weapons/magazine-and-reserve]. A reserve alone names the gun when
#: the magazine is unread (it flickers while firing).
GUNS = {"classic": (12, 36), "vandal": (25, 50), "phantom": (30, 60)}
#: Witness states shorter than this are digit flicker, not an equip.
MIN_STATE_S = 0.15
BUY_ON = 0.5


def held_states(wt: dict) -> list[tuple[float, float, str]]:
    """(t0, t1, state) runs: knife, classic, vandal, phantom, buy or unread."""
    t = wt["t"]
    by_res = {r: g for g, (m, r) in GUNS.items()}
    by_mag = {m: g for g, (m, r) in GUNS.items()}
    lab = []
    for i in range(len(t)):
        if wt["buy_ref"][i] > BUY_ON:
            lab.append("buy")
        elif wt["white"][i] < audio_channel.HIDDEN and wt["mag"][i] < 0 and wt["reserve"][i] < 0:
            lab.append("knife")
        elif int(wt["reserve"][i]) in by_res:
            lab.append(by_res[int(wt["reserve"][i])])
        elif int(wt["mag"][i]) in by_mag:
            lab.append(by_mag[int(wt["mag"][i])])
        else:
            lab.append("unread")
    runs: list[list] = []
    for i, s in enumerate(lab):
        if runs and runs[-1][2] == s:
            runs[-1][1] = float(t[i])
        else:
            runs.append([float(t[i]), float(t[i]), s])
    # Drop flicker and unread runs into their neighbours.
    keep = [r for r in runs if r[2] != "unread" and r[1] - r[0] + STEP_S >= MIN_STATE_S]
    out: list[list] = []
    for r in keep:
        if out and out[-1][2] == r[2]:
            out[-1][1] = r[1]
        else:
            out.append(list(r))
    return [(a, b + STEP_S, s) for a, b, s in out]


# ---------------------------------------------------------------------------
# Audio candidates
# ---------------------------------------------------------------------------

#: 10 ms RMS bins, and the event gate: about twice the floor of the clip's
#: quiet stretches (1-1.5e-4 in its silent seconds, 2026-09-29), low enough
#: for the Classic's equip and the quietest footsteps. A level; this clip only.
BIN_S = 0.01
MIN_EVENT_S = 0.04
#: Gate per phase kind. Equip and menu sounds peak at 1.5e-3 or more and sit
#: over 3-5e-4 of handling noise; shots peak at 1e-2 or more and ring for a
#: second, so `audio_events`' own 2e-3 separates them; footsteps need 3e-4.
GATE = {"equip": 6e-4, "buy": 6e-4, "shot": 2e-3, "move": 3e-4}
#: Runs closer than this are one sound (a two-part equip, a spray's dip).
MERGE_GAP = {"equip": 0.45, "buy": 0.08, "shot": 0.25, "move": 0.06}
#: A shot run peaks at least this loud (every shot measured 1.1e-2 or more;
#: the Phantom's equip reaches 8.6e-3), and starts this long after an equip.
SHOT_PEAK, SHOT_AFTER_EQUIP_S = 1e-2, 1.2
#: A shot is a peak at least this share of its run's peak, rising this many
#: times over the minimum of the 50 ms before it.
SHOT_SHARE, SHOT_RISE = 0.35, 1.6
#: An equip sound starts within this window of the HUD's switch, seconds.
EQUIP_WINDOW = (-0.3, 0.8)
#: A step is a peak this far from its neighbours, at least this loud.
STEP_SEP_S, STEP_MIN = 0.18, 6e-4
#: A jump is a quieter takeoff and a louder landing whose peaks are this far
#: apart, with no step this close before the takeoff or after the landing.
AIR_S, JUMP_QUIET_S = (0.45, 0.80), 0.7
#: A step this much later than the walk's cadence may be a jump or landing.
CADENCE_BREAK_S = 0.5
#: A movement run this long that holds no step onset is kept as one unknown sound.
LONG_S = 1.2
#: The audio bank's front end: 64 bands, 60 Hz-16 kHz, 2048-point frames.
BANDS, FMIN, FMAX, NFFT = audio_bank.BANDS, audio_bank.FMIN, audio_bank.FMAX, audio_bank.NFFT
SNIP_PAD = (0.10, 0.15)


def _sound_runs(env: np.ndarray, gap: float, gate: float) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b, pk in audio_events.events(env, BIN_S, gate, MIN_EVENT_S):
        if out and a - out[-1][1] < gap:
            out[-1][1], out[-1][2] = b, max(out[-1][2], pk)
        else:
            out.append([a, b, pk])
    return out


def _peaks(env: np.ndarray, a: float, b: float, share: float, sep: float,
           floor: float = 0.0, rise: float = 0.0) -> list[float]:
    """Local maxima of the envelope in [a, b) above share x the span's peak
    (and above `floor`), each `rise` times over the minimum of the 50 ms before it."""
    i0, i1 = int(round(a / BIN_S)), int(round(b / BIN_S))
    seg = env[i0:i1]
    if len(seg) < 3:
        return [a]
    thr = max(share * seg.max(), floor)
    idx = [i for i in range(1, len(seg) - 1)
           if seg[i] >= thr and seg[i] >= seg[i - 1] and seg[i] > seg[i + 1]
           and (rise <= 0 or seg[i] >= rise * env[max(0, i0 + i - 5):i0 + i].min(initial=np.inf))]
    idx.sort(key=lambda i: -seg[i])
    kept: list[int] = []
    for i in idx:
        if all(abs(i - j) * BIN_S >= sep for j in kept):
            kept.append(i)
    return sorted((i0 + i) * BIN_S for i in kept)


def _onset(env: np.ndarray, a: float, pk: float) -> float:
    """Start of the rise into a peak: the last bin under a quarter of it."""
    i = int(round(pk / BIN_S))
    lo = int(round(a / BIN_S))
    while i > lo and env[i - 1] > 0.25 * env[int(round(pk / BIN_S))]:
        i -= 1
    return i * BIN_S


def logmel(m: np.ndarray, rate: int) -> np.ndarray:
    """[frames, 64] log-mel at 10 ms, frame i centred on i*HOP (the bank's front end)."""
    h = int(audio_channel.HOP * rate)
    pad = np.concatenate([np.zeros(NFFT // 2, m.dtype), m, np.zeros(NFFT, m.dtype)])
    n = len(m) // h
    idx = np.arange(NFFT)[None] + h * np.arange(n)[:, None]
    fb = audio_channel._mel_fb(rate, NFFT, BANDS, FMIN, FMAX)
    out = np.empty((n, BANDS), np.float32)
    win = np.hanning(NFFT)
    for s in range(0, n, 2000):
        P = np.abs(np.fft.rfft(pad[idx[s:s + 2000]] * win, axis=1)) ** 2
        out[s:s + 2000] = 10 * np.log10(P @ fb.T + 1e-10)
    return out


def _kmeans(X: np.ndarray, k: int, seed: int = 0, iters: int = 100) -> tuple[np.ndarray, float]:
    """Plain k-means, best of 10 starts (k-means++), and its inertia."""
    rng = np.random.default_rng(seed)
    best, best_in = None, np.inf
    for _ in range(10):
        c = [X[rng.integers(len(X))]]
        for _ in range(1, k):
            d = np.min([((X - ci) ** 2).sum(1) for ci in c], axis=0)
            c.append(X[rng.choice(len(X), p=d / d.sum())])
        C = np.array(c)
        for _ in range(iters):
            lab = np.argmin(((X[:, None] - C[None]) ** 2).sum(2), 1)
            C2 = np.array([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
            if np.allclose(C2, C):
                break
            C = C2
        inertia = float(((X - C[lab]) ** 2).sum())
        if inertia < best_in:
            best, best_in = lab, inertia
    return best, best_in


def _silhouette(X: np.ndarray, lab: np.ndarray) -> float:
    D = np.sqrt(((X[:, None] - X[None]) ** 2).sum(2))
    s = []
    for i in range(len(X)):
        same = lab == lab[i]
        if same.sum() < 2:
            s.append(0.0)
            continue
        a = D[i, same].sum() / (same.sum() - 1)
        b = min(D[i, lab == j].mean() for j in set(lab.tolist()) if j != lab[i])
        s.append((b - a) / max(a, b))
    return float(np.mean(s))


def cluster(X: np.ndarray, ks=range(2, 7)) -> dict:
    """Candidate variants: k-means on z-scored band means, k by silhouette."""
    Z = (X - X.mean(0)) / (X.std(0) + 1e-6)
    res = {}
    for k in ks:
        if k >= len(Z):
            break
        lab, _ = _kmeans(Z, k)
        res[k] = (lab, _silhouette(Z, lab))
    if not res:
        return {"k": 1, "labels": [0] * len(X), "silhouette": {}}
    k = max(res, key=lambda k: res[k][1])
    lab = res[k][0]
    # Name clusters by size, largest first, so A is the commonest.
    order = [j for j, _ in sorted(((j, -(lab == j).sum()) for j in range(k)), key=lambda p: p[1])]
    ren = {j: i for i, j in enumerate(order)}
    return {"k": k, "labels": [ren[int(j)] for j in lab],
            "silhouette": {str(kk): round(v[1], 3) for kk, v in res.items()}}


def _held_at(states, t: float) -> str | None:
    for a, b, s in states:
        if a <= t < b:
            return s
    return None


def _transitions(states) -> list[tuple[float, str, str]]:
    return [(states[i][0], states[i - 1][2], states[i][2]) for i in range(1, len(states))]


def _cand(a, b, env, phase, proposed, witness, note, **kw) -> dict:
    pk = float(env[int(round(a / BIN_S)):max(int(round(b / BIN_S)), int(round(a / BIN_S)) + 1)].max())
    return dict(t0=a, t1=b, peak=pk, phase=phase, proposed=proposed, witness=witness,
                witness_note=note, **kw)


def _move_candidates(env, runs, name, states) -> list[dict]:
    """Steps, jumps and landings after the last shot, from the envelope alone.

    A jump is a quiet takeoff and a louder landing AIR_S apart with quiet
    around the pair; everything else splits into steps at envelope peaks.
    Nothing in the video witnesses a jump cheaply, so these rest on the audio
    and the player's order ("jump repeating, then mostly walking").
    """
    out: list[dict] = []
    used = set()
    strong = [i for i, r in enumerate(runs) if r[2] >= STEP_MIN]
    tpk = {i: float(np.argmax(env[int(round(runs[i][0] / BIN_S)):int(round(runs[i][1] / BIN_S)) + 1])
                    * BIN_S + runs[i][0]) for i in strong}
    for n in range(len(strong) - 1):
        i, j = strong[n], strong[n + 1]
        (a, b, p1), (c, d, p2) = runs[i], runs[j]
        before = a - runs[strong[n - 1]][1] if n else 9.0
        after = runs[strong[n + 2]][0] - d if n + 2 < len(strong) else 9.0
        air = tpk[j] - tpk[i]
        if (AIR_S[0] <= air <= AIR_S[1] and before >= JUMP_QUIET_S and after >= JUMP_QUIET_S
                and p2 > p1 and i not in used):
            w = {"held": _held_at(states, a), "air_s": round(air, 2)}
            out.append(_cand(a, b, env, name, "jump", w,
                             f"quieter sound {air:.2f} s (peak to peak) before a louder one, "
                             f"quiet {before:.1f} s before and {after:.1f} s after"))
            out.append(_cand(c, d, env, name, "land", w,
                             f"louder sound {air:.2f} s after the takeoff candidate"))
            used |= {i, j}
    steps: list[dict] = []
    for i, (a, b, pk) in enumerate(runs):
        if i in used:
            continue
        w = {"held": _held_at(states, a)}
        pks = _peaks(env, a, b, 0.0, STEP_SEP_S, floor=STEP_MIN)
        if not pks:
            if b - a >= LONG_S:
                out.append(_cand(a, b, env, name, "other", w,
                                 f"{b - a:.2f} s of sound with no step onset"))
            else:
                steps.append(_cand(a, b, env, name, "footstep", w, "a quiet step"))
            continue
        starts = sorted({round(max(a, _onset(env, a, p)), 2) for p in pks})
        if starts[0] - a >= STEP_SEP_S:
            starts.insert(0, a)
        for j, s0 in enumerate(starts):
            s1 = starts[j + 1] if j + 1 < len(starts) else b
            if s1 - s0 < MIN_EVENT_S:
                continue
            steps.append(_cand(s0, s1, env, name, "footstep", w,
                               f"step {j + 1} of {len(starts)} in a {b - a:.2f} s run"))
    # A step that breaks the walk's cadence may be a jump or its landing.
    steps.sort(key=lambda c: c["t0"])
    for j in range(1, len(steps) - 1):
        gp = steps[j]["t0"] - steps[j - 1]["t0"]
        gn = steps[j + 1]["t0"] - steps[j]["t0"]
        if max(gp, gn) >= CADENCE_BREAK_S and min(gp, gn) <= 0.4:
            steps[j]["witness_note"] += (f"; cadence breaks ({gp:.2f} s after the last step, "
                                         f"{gn:.2f} s before the next): a jump or landing?")
            steps[j]["cadence_break"] = True
    return out + steps


def _order_fit(shots: list[dict], gun: str) -> None:
    """Propose the order's single* burst* spray* sequence that disagrees least
    with the audio's shot counts, keeping the count's reading beside it.

    Where several sequences tie, a shot they label differently takes the
    count's reading and says the order cannot place it.
    """
    shapes = [c["audio_shape"] for c in shots]
    n = len(shapes)
    seqs = []
    for i in range(n + 1):
        for j in range(i, n + 1):
            seq = ["single"] * i + ["burst"] * (j - i) + ["spray"] * (n - j)
            seqs.append((sum(a != b for a, b in zip(seq, shapes)), seq))
    low = min(m for m, _ in seqs)
    best = [seq for m, seq in seqs if m == low]
    for k, c in enumerate(shots):
        opts = {seq[k] for seq in best}
        if len(opts) > 1:
            c["order_shape"] = None
            c["witness_note"] += (f"; the order cannot place it (it allows "
                                  f"{' or '.join(sorted(opts))}), so the shot count decides")
            continue
        s = opts.pop()
        c["order_shape"] = s
        c["proposed"] = f"{gun}_{s}"
        if s != c["audio_shape"]:
            c["witness_note"] += (f"; THE ORDER SAYS {s} (its neighbours), THE SHOT COUNT SAYS "
                                  f"{c['audio_shape']}")


def cut() -> dict:
    """Candidate sound events with proposed classes and their witnesses."""
    wt = witness()
    states = held_states(wt)
    trans = _transitions(states)
    buys = [(a, b) for a, b, s in states if s == "buy"]
    if len(buys) != 2:
        raise SystemExit(f"expected the order's two buy-menu visits, the witness shows {buys}")
    x, rate = audio_probe.decode(CAPTURE)
    m = x.mean(axis=1)
    env = audio_events.envelope(m, rate, BIN_S)
    dur = len(m) / rate

    def after_equip(t: float) -> bool:
        return any(0 <= t - tr[0] < SHOT_AFTER_EQUIP_S for tr in trans if tr[2] in GUNS)

    shot_runs = [r for r in _sound_runs(env, MERGE_GAP["shot"], GATE["shot"])
                 if r[2] >= SHOT_PEAK and _held_at(states, r[0]) in GUNS and not after_equip(r[0])]
    first_shot = {g: min(r[0] for r in shot_runs if _held_at(states, r[0]) == g)
                  for g in ("vandal", "phantom")}
    last_shot = max(r[1] for r in shot_runs)
    # Phases of the player's order, bounded by the witness.
    phases = [("equip_knife_classic", "equip", 0.0, buys[0][0] - 0.2),
              ("buy_vandal", "buy", buys[0][0] - 0.2, buys[0][1] - 0.1),
              ("equip_vandal_knife", "equip", buys[0][1] - 0.1, first_shot["vandal"] - 0.2),
              ("shots_vandal", "shot", first_shot["vandal"] - 0.2, buys[1][0] - 0.2),
              ("buy_phantom", "buy", buys[1][0] - 0.2, buys[1][1] - 0.1),
              ("equip_phantom_knife", "equip", buys[1][1] - 0.1, first_shot["phantom"] - 0.2),
              ("shots_phantom", "shot", first_shot["phantom"] - 0.2, last_shot + 0.3),
              ("jump_walk", "move", last_shot + 0.3, dur)]

    cands: list[dict] = []
    for name, k, p0, p1 in phases:
        runs = [r for r in _sound_runs(env, MERGE_GAP[k], GATE[k]) if p0 <= r[0] < p1]
        if k == "buy":
            menu = buys[0] if "vandal" in name else buys[1]
            for j, (a, b, _) in enumerate(runs):
                prop = ("buy_menu_open" if j == 0 else
                        "purchase" if j == len(runs) - 1 else "buy_menu_select")
                note = (f"the menu opens at {menu[0]:.2f} s ({a - menu[0]:+.2f} s)" if j == 0 else
                        f"the last sound before the menu closes at {menu[1]:.2f} s"
                        if j == len(runs) - 1 else "between the opening and the last sound")
                cands.append(_cand(a, b, env, name, prop,
                                   {"buy_menu_s": [round(menu[0], 2), round(menu[1], 2)]}, note))
        elif k == "equip":
            for a, b, _ in runs:
                near = [tr for tr in trans if EQUIP_WINDOW[0] <= a - tr[0] <= EQUIP_WINDOW[1]]
                near.sort(key=lambda tr: abs(a - tr[0]))
                if near:
                    t_sw, frm, to = near[0]
                    prop = f"{to}_equip" if to in ("knife", *GUNS) else "other"
                    w = {"held_before": frm, "held_after": to, "switch_s": round(t_sw, 2),
                         "offset_s": round(a - t_sw, 2)}
                    note = f"the HUD switches {frm} -> {to} at {t_sw:.2f} s ({a - t_sw:+.2f} s)"
                else:
                    held = _held_at(states, a)
                    prop, w = "other", {"held": held}
                    note = f"no HUD switch near it; {held} held"
                cands.append(_cand(a, b, env, name, prop, w, note))
        elif k == "shot":
            gun = "vandal" if "vandal" in name else "phantom"
            for a, b, pk in runs:
                held = _held_at(states, a)
                if pk < SHOT_PEAK or after_equip(a):
                    near = [tr for tr in trans if EQUIP_WINDOW[0] <= a - tr[0] <= EQUIP_WINDOW[1]]
                    if near:
                        t_sw, frm, to = near[0]
                        cands.append(_cand(a, b, env, name, f"{to}_equip" if to != "buy" else "other",
                                           {"held_before": frm, "held_after": to,
                                            "switch_s": round(t_sw, 2), "offset_s": round(a - t_sw, 2)},
                                           f"the HUD switches {frm} -> {to} at {t_sw:.2f} s "
                                           f"({a - t_sw:+.2f} s)"))
                    else:
                        cands.append(_cand(a, b, env, name, "other", {"held": held},
                                           f"a quieter sound between shots; {held} held"))
                    continue
                n = len(_peaks(env, a, b, SHOT_SHARE, 0.07, rise=SHOT_RISE))
                shape = "single" if n == 1 else ("burst" if n <= 5 else "spray")
                w = {"held": held, "shots_heard": n,
                     "magazine": "flat: the range's infinite ammo keeps it full"}
                note = f"the HUD holds {held} ({'x'.join(map(str, GUNS.get(held, ('?',))))}); {n} shot onsets heard"
                if held != gun:
                    note += f"; THE ORDER SAYS {gun}, THE HUD SAYS {held}"
                cands.append(_cand(a, b, env, name, f"{gun}_{shape}", w, note, shots=n,
                                   audio_shape=shape))
            _order_fit([c for c in cands if c["phase"] == name and "audio_shape" in c], gun)
        else:
            cands += _move_candidates(env, runs, name, states)

    # Spectral features and the surface-variant clusters.
    L = logmel(m, rate)
    med = np.median(L, axis=0)
    for c in cands:
        # The shape of the spectrum around the loudest 10 ms in 16 bands,
        # loudness removed, and how fast the sound dies: a surface should
        # change the colour and the ring of a step, not only its level.
        f0 = int(round(c["t0"] / audio_channel.HOP))
        f1 = max(f0 + 3, int(round(c["t1"] / audio_channel.HOP)))
        pk = f0 + int(np.argmax(L[f0:f1].max(1)))
        seg = (L[max(f0, pk - 3):pk + 9] - med).mean(0).reshape(16, 4).mean(1)
        c["mel_shape"] = (seg - seg.mean()).round(2).tolist()
        ipk = int(round(c["t0"] / BIN_S)) + int(np.argmax(env[int(round(c["t0"] / BIN_S)):
                                                               max(int(round(c["t1"] / BIN_S)),
                                                                   int(round(c["t0"] / BIN_S)) + 1)]))
        c["decay_db"] = [round(float(20 * np.log10((env[min(ipk + k, len(env) - 1)] + 1e-6)
                                                   / (env[ipk] + 1e-6))), 2) for k in (8, 16)]
    variants = {}
    for cls, tag, members in (("footstep", "f", ("footstep",)), ("jump", "j", ("jump", "land"))):
        idx = [i for i, c in enumerate(cands) if c["proposed"] in members]
        if not idx:
            continue
        X = np.array([cands[i]["mel_shape"] + cands[i]["decay_db"] for i in idx])
        cl = cluster(X)
        for i, j in zip(idx, cl["labels"]):
            cands[i]["proposed_variant"] = f"{tag}{chr(65 + j)}"
        v = variants[cls] = {"k": cl["k"], "silhouette": cl["silhouette"], "clusters": {}}
        for j in range(cl["k"]):
            ts = sorted(cands[i]["t0"] for i, lab in zip(idx, cl["labels"]) if lab == j)
            v["clusters"][f"{tag}{chr(65 + j)}"] = {
                "n": len(ts), "span_s": [round(ts[0], 1), round(ts[-1], 1)],
                "centroid": X[np.array(cl["labels"]) == j].mean(0).round(2).tolist()}
    # The player believes jumps share the footsteps' variants: name each jump
    # and landing's nearest footstep cluster, so his review can test it.
    if "footstep" in variants:
        cen = {n: np.array(c["centroid"]) for n, c in variants["footstep"]["clusters"].items()}
        for c in cands:
            if c["proposed"] in ("jump", "land"):
                d = {n: float(np.linalg.norm(np.array(c["mel_shape"] + c["decay_db"]) - v))
                     for n, v in cen.items()}
                c["nearest_footstep_variant"] = min(d, key=d.get)

    cands.sort(key=lambda c: c["t0"])
    for i, c in enumerate(cands):
        c["key"] = f"{SESSION}:{int(round(c['t0'] * 1000))}"
        c["i"] = i
        c["t0"], c["t1"], c["peak"] = round(c["t0"], 3), round(c["t1"], 3), round(float(c["peak"]), 5)
        c["env"] = [round(float(v) * 1e4, 2) for v in
                    env[int((c["t0"] - SNIP_PAD[0]) / BIN_S):int((c["t1"] + SNIP_PAD[1]) / BIN_S)]]
    man = {"version": VERSION, "session_id": SESSION, "source_path": CAPTURE,
           "created": _dt.datetime.now().isoformat(timespec="seconds"),
           "front_end": {"bin_s": BIN_S, "gate": GATE, "shot_after_equip_s": SHOT_AFTER_EQUIP_S, "merge_gap": MERGE_GAP,
                         "shot_peak": SHOT_PEAK, "hop": audio_channel.HOP, "nfft": NFFT,
                         "bands": BANDS, "fmin": FMIN, "fmax": FMAX},
           "order_file": str(ORDER_FILE), "phases": [[n, round(a, 2), round(b, 2)] for n, _k, a, b in phases],
           "held_states": [[round(a, 2), round(b, 2), s] for a, b, s in states],
           "variants": variants, "candidates": cands}
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(man, indent=1), encoding="utf-8")
    return man


#: The player's stated order is kept verbatim outside the repository (quotes
#: stay private); the phases in `cut` follow it: knife and Classic equips; the
#: buy menu for the Vandal; Vandal and knife equips; Vandal single shots,
#: bursts, sprays; the buy menu for the Phantom; Phantom and knife equips;
#: Phantom single shots, bursts, sprays; jumps; walking on several surfaces
#: with a few jumps.
ORDER_FILE = OUT / "order-20260929.txt"


def _summary(man: dict) -> None:
    from collections import Counter
    cands = man["candidates"]
    print(f"{len(cands)} candidates from {man['source_path']} ({man['session_id']})")
    for n, a, b in man["phases"]:
        cs = [c for c in cands if c["phase"] == n]
        print(f"  {n:<22}{a:7.2f}-{b:7.2f}  {dict(Counter(c['proposed'] for c in cs))}")
    print("proposed:", dict(Counter(c["proposed"] for c in cands)))
    print("variants:", json.dumps(man["variants"]))
    print(f"manifest {MANIFEST}")


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

TOOL = "sound_demo review 1"
#: Class keys. Digits for "which of these", letters for the rest; O asks for
#: a name, so an unlisted sound is never forced into a listed class.
CLASSES = [("1", "knife_equip"), ("2", "classic_equip"), ("3", "vandal_equip"),
           ("4", "phantom_equip"), ("5", "vandal_single"), ("6", "vandal_burst"),
           ("7", "vandal_spray"), ("8", "phantom_single"), ("9", "phantom_burst"),
           ("0", "phantom_spray"), ("J", "jump"), ("L", "land"), ("F", "footstep"),
           ("B", "buy_menu_open"), ("E", "buy_menu_select"), ("P", "purchase"),
           ("O", "other")]
VARIANT_CLASSES = ("footstep", "jump", "land")
ANSWERS = {"accept", "relabel", "split", "reject", "unsure"}
WINDOW_S = (1.0, 1.0)


def _answered(labels: Path) -> dict[str, dict]:
    last: dict[str, dict] = {}
    if labels.is_file():
        for line in labels.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                last[row["key"]] = row
    return last


def review_items(man: dict) -> list[dict]:
    items = []
    for c in man["candidates"]:
        it = {k: c.get(k) for k in ("key", "i", "t0", "t1", "peak", "phase", "proposed",
                                    "proposed_variant", "witness", "witness_note", "shots",
                                    "audio_shape", "order_shape", "nearest_footstep_variant",
                                    "cadence_break", "env")}
        it.update({"start_s": max(0.0, c["t0"] - WINDOW_S[0]), "end_s": c["t1"] + WINDOW_S[1],
                   "snip": [round(c["t0"] - SNIP_PAD[0], 3), round(c["t1"] + SNIP_PAD[1], 3)],
                   "video": "/video/" + urllib.parse.quote(Path(man["source_path"]).name)})
        items.append(it)
    return items


def snippet_wav(t0: float, t1: float) -> bytes:
    """The capture's audio over [t0, t1] as a 16-bit stereo WAV, in memory.

    `audio_bank.read_spans` places each AAC frame by its own pts, so the
    snippet starts where the manifest says; nothing is written to disk.
    """
    import wave
    _, x, filled, rate = next(audio_bank.read_spans(CAPTURE, [(max(0.0, t0), t1)]))
    pcm = np.clip(x * 32767.0, -32768, 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Sound demo review</title>
<style>
:root { --bg:#141414; --fg:#e6e6e6; --dim:#9a9a9a; --ok:#4caf50; --bad:#e53935; --warn:#f0b429; --acc:#4fc3f7; }
body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.35 Consolas, monospace; }
#wrap { display:flex; gap:12px; padding:10px; }
#left { flex:0 0 auto; }
#main { width:min(58vw, 1100px); display:block; background:#000; border:3px solid #000; }
#main.at { border-color:var(--acc); }
#bar { position:relative; height:8px; background:#333; margin-top:4px; }
#bar i { position:absolute; top:0; bottom:0; background:#888; width:2px; }
#bar b { position:absolute; top:-3px; bottom:-3px; background:rgba(79,195,247,.45); }
#right { flex:1 1 auto; min-width:380px; }
#envc { width:100%; height:120px; background:#000; display:block; }
#info { margin-top:8px; white-space:pre-wrap; }
.big { font-size:20px; font-weight:bold; }
.prop { color:var(--acc); }
.dim { color:var(--dim); }
.warn { color:var(--warn); }
.ans { color:var(--ok); }
#classes { margin-top:8px; display:flex; flex-wrap:wrap; gap:4px; }
#classes button { background:#222; color:var(--fg); border:1px solid #444; font:12px Consolas, monospace; padding:3px 6px; cursor:pointer; }
#classes button.p { border-color:var(--acc); color:var(--acc); }
#keys { margin-top:10px; color:var(--dim); }
#msg { margin-top:6px; color:var(--warn); min-height:1.3em; }
</style></head><body>
<div id="wrap">
 <div id="left">
  <video id="main" muted playsinline preload="auto"></video>
  <div id="bar"><b id="span"></b><i id="play"></i></div>
  <div id="rel" class="dim"></div>
  <div id="media" class="dim"></div>
  <div id="ctx" class="dim" style="margin-top:8px;white-space:pre-wrap"></div>
 </div>
 <div id="right">
  <canvas id="envc" width="700" height="120"></canvas>
  <div id="info"></div>
  <div id="classes"></div>
  <div id="msg"></div>
  <div id="keys">Y accept the proposal &nbsp; digit/letter = relabel (buttons) &nbsp; O other (name it)<br>
  W two events &nbsp; X reject (no event here) &nbsp; U unsure &nbsp; M name the surface<br>
  G accept this and the rest of its run (same proposal, same variant, consecutive)<br>
  R replay the sound &nbsp; V video window with sound &nbsp; A back &nbsp; S skip &nbsp; T note &nbsp; Q/ESC quit</div>
 </div>
</div>
<audio id="snd" preload="auto"></audio>
<script>
let items = [], meta = {}, answered = {}, idx = 0, pending = {}, surf = {};
const main = document.getElementById('main'), snd = document.getElementById('snd');
const cv = document.getElementById('envc'), ctx = cv.getContext('2d');
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

function surfaces() {
  surf = {};
  for (const it of items) {
    const a = answered[it.key];
    if (a && a.variant && it.proposed_variant && a.variant !== it.proposed_variant) surf[it.proposed_variant] = a.variant;
  }
}
function nextOpen(from) {
  for (let i = from; i < items.length; i++) if (!answered[items[i].key]) return i;
  return items.length;
}
function isVar(c) { return meta.variant_classes.includes(c); }
function drawEnv(it) {
  const e = it.env || [], W = cv.width, H = cv.height;
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
  if (!e.length) return;
  const db = e.map(v => 20 * Math.log10(Math.max(v, 0.3)));   // units of 1e-4
  const lo = 20 * Math.log10(0.3), hi = Math.max(...db) + 3;
  const t0 = it.snip[0], t1 = it.snip[1], sx = W / e.length;
  ctx.fillStyle = 'rgba(79,195,247,0.18)';
  ctx.fillRect((it.t0 - t0) / (t1 - t0) * W, 0, (it.t1 - it.t0) / (t1 - t0) * W, H);
  ctx.strokeStyle = '#e6e6e6'; ctx.beginPath();
  db.forEach((v, i) => { const y = H - (v - lo) / (hi - lo) * (H - 6) - 3; i ? ctx.lineTo(i * sx, y) : ctx.moveTo(0, y); });
  ctx.stroke();
  ctx.fillStyle = '#9a9a9a'; ctx.font = '11px Consolas';
  ctx.fillText(`RMS envelope ${t0.toFixed(2)}-${t1.toFixed(2)} s, dB; shaded = candidate`, 4, 12);
}
function playSnd() {
  const it = items[idx]; if (!it) return;
  snd.src = `/snippet/${it.i}.wav`; snd.currentTime = 0;
  snd.play().then(() => { $('msg').textContent = ''; })
    .catch(() => { $('msg').textContent = 'press R to play the sound (the browser blocks sound until a key is pressed)'; });
}
function show(i) {
  if (i >= items.length) { done(); return; }
  idx = Math.max(0, i);
  const it = items[idx];
  if (main.getAttribute('src') !== it.video) main.src = it.video;
  main.muted = true; main.currentTime = it.start_s; main.play().catch(() => {});
  const win = it.end_s - it.start_s;
  $('span').style.left = (100 * (it.t0 - it.start_s) / win) + '%';
  $('span').style.width = (100 * (it.t1 - it.t0) / win) + '%';
  drawEnv(it);
  const a = answered[it.key];
  const n = Object.keys(answered).length;
  const pv = it.proposed_variant ? ` <span class="prop">${esc(it.proposed_variant)}</span>` +
    (surf[it.proposed_variant] ? ` (you named ${esc(it.proposed_variant)} "${esc(surf[it.proposed_variant])}")` : '') : '';
  let w = Object.entries(it.witness || {}).map(([k, v]) => `${k}: ${esc(JSON.stringify(v))}`).join('\n  ');
  $('info').innerHTML =
    `<span class="big">proposed: <span class="prop">${esc(it.proposed)}</span></span>${pv}\n` +
    `<span class="${/SAYS|cannot|cadence/.test(it.witness_note) ? 'warn' : ''}">${esc(it.witness_note)}</span>\n` +
    `witness:\n  ${w}\n` +
    (it.nearest_footstep_variant ? `nearest footstep variant: ${esc(it.nearest_footstep_variant)}\n` : '') +
    `\ncandidate ${it.i} at ${it.t0.toFixed(2)}-${it.t1.toFixed(2)} s (${(it.t1 - it.t0).toFixed(2)} s), ` +
    `peak ${(it.peak * 1e3).toFixed(2)}e-3, phase ${esc(it.phase)}\n` +
    `item ${idx + 1} / ${items.length}; ${n} answered\n` +
    (a ? `answered <span class="ans">${esc(a.answer)}</span> ${esc(a.label || (a.labels || []).join(' + ') || '')}` +
         (a.variant ? ` [${esc(a.variant)}]` : '') + (a.note ? ': ' + esc(a.note) : '') : '') +
    (pending[it.key] ? `\nnote pending: ${esc(pending[it.key])}` : '');
  const nb = k => items[k] ? `${items[k].t0.toFixed(2)} s ${items[k].proposed}` +
    (answered[items[k].key] ? ` -> ${answered[items[k].key].label || answered[items[k].key].answer}` : '') : '';
  $('ctx').textContent = `before: ${nb(idx - 2)}\n        ${nb(idx - 1)}\nafter:  ${nb(idx + 1)}\n        ${nb(idx + 2)}`;
  document.querySelectorAll('#classes button').forEach(b => b.classList.toggle('p', b.dataset.c === it.proposed));
  $('msg').textContent = '';
  playSnd();
}
function done() {
  main.pause();
  $('info').innerHTML = `<span class="big">All ${items.length} candidates answered.</span>\nA goes back; Q quits.`;
  idx = items.length;
}
function tick() {
  const it = items[idx];
  if (it && main.readyState >= 2) {
    if (main.currentTime >= it.end_s || main.currentTime < it.start_s - 0.5) main.currentTime = it.start_s;
    const dt = main.currentTime;
    main.classList.toggle('at', dt >= it.t0 && dt <= it.t1);
    $('play').style.left = (100 * (dt - it.start_s) / (it.end_s - it.start_s)) + '%';
    $('rel').textContent = `video ${dt.toFixed(2)} s; candidate ${it.t0.toFixed(2)}-${it.t1.toFixed(2)} s` +
      (main.muted ? ' (video muted; V for its sound)' : '');
  }
  requestAnimationFrame(tick);
}
async function post(body) {
  const r = await fetch('/answer', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify(body)});
  if (!r.ok) { $('msg').textContent = 'NOT SAVED: ' + await r.text(); return null; }
  return await r.json();
}
function variantFor(it, label) {
  if (!isVar(label)) return null;
  return surf[it.proposed_variant] || it.proposed_variant || null;
}
async function send(answer, extra) {
  const it = items[idx];
  if (!it) return;
  const body = Object.assign({key: it.key, answer: answer, note: pending[it.key] || null}, extra || {});
  const row = await post(body);
  if (!row) return;
  answered[it.key] = row; delete pending[it.key]; surfaces();
  const nx = nextOpen(idx + 1);
  show(nx < items.length ? nx : idx + 1);
}
function label(c) {
  const it = items[idx]; if (!it) return;
  if (c === 'other') {
    main.pause();
    const name = prompt('Name this sound (other):', '');
    if (!name) return;
    send('relabel', {label: 'other', other_name: name});
    return;
  }
  send(c === it.proposed ? 'accept' : 'relabel', {label: c, variant: variantFor(it, c)});
}
async function acceptRun() {
  const it = items[idx]; if (!it) return;
  let k = idx; const run = [];
  while (k < items.length && items[k].proposed === it.proposed &&
         items[k].proposed_variant === it.proposed_variant && !answered[items[k].key]) {
    if (k > idx && items[k].t0 - items[k - 1].t1 > 1.0) break;
    run.push(k); k++;
  }
  if (!confirm(`Accept ${it.proposed}${it.proposed_variant ? ' ' + it.proposed_variant : ''} for ${run.length} consecutive candidates (${items[run[0]].t0.toFixed(2)}-${items[run[run.length - 1]].t1.toFixed(2)} s)?`)) return;
  for (const j of run) {
    const row = await post({key: items[j].key, answer: 'accept', label: items[j].proposed,
                            variant: variantFor(items[j], items[j].proposed), batch_from: it.key});
    if (!row) return;
    answered[items[j].key] = row;
  }
  surfaces(); const nx = nextOpen(idx + 1); show(nx < items.length ? nx : idx + 1);
}
function split() {
  const it = items[idx]; if (!it) return;
  main.pause();
  const w = prompt('Two events: the first and second class, comma separated (e.g. knife_equip,classic_equip)',
                   it.proposed + ',');
  if (!w) return;
  const parts = w.split(',').map(s => s.trim()).filter(Boolean);
  if (parts.length !== 2) { $('msg').textContent = 'give exactly two classes'; return; }
  send('split', {labels: parts});
}
function nameSurface() {
  const it = items[idx]; if (!it) return;
  main.pause();
  const cur = surf[it.proposed_variant] || '';
  const w = prompt(`Surface for this sound, and where on the range if you can tell ` +
                   `(it also becomes the default for cluster ${it.proposed_variant || '(none)'}; ` +
                   `give two clusters the same name to merge them):`, cur);
  if (!w) return;
  const lab = isVar(it.proposed) ? it.proposed : 'footstep';
  send(lab === it.proposed ? 'accept' : 'relabel', {label: lab, variant: w});
}
function addNote() {
  const it = items[idx]; if (!it) return;
  main.pause();
  const w = prompt('Note for candidate ' + it.i, '');
  if (w) { pending[it.key] = pending[it.key] ? pending[it.key] + ' | ' + w : w; show(idx); }
}
document.addEventListener('keydown', ev => {
  if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
  const k = ev.key.toUpperCase();
  const cls = meta.classes.find(([key]) => key === k);
  if (k === 'Y') { const it = items[idx]; if (it) send('accept', {label: it.proposed, variant: variantFor(it, it.proposed)}); }
  else if (cls) label(cls[1]);
  else if (k === 'W') split();
  else if (k === 'X') send('reject', {label: null});
  else if (k === 'U') send('unsure', {label: null});
  else if (k === 'M') nameSurface();
  else if (k === 'G') acceptRun();
  else if (k === 'A') show(Math.max(0, idx - 1));
  else if (k === 'S') show(Math.min(items.length, idx + 1));
  else if (k === 'R') playSnd();
  else if (k === 'V') { const it = items[idx]; if (it) { main.muted = !main.muted; main.currentTime = it.start_s; main.play().catch(() => {}); } }
  else if (k === 'T') addNote();
  else if (k === 'Q' || k === 'ESCAPE') {
    main.pause(); snd.pause(); fetch('/quit', {method: 'POST'});
    document.body.innerHTML = '<p style="padding:20px">Saved. The server stopped; close this tab.</p>';
  }
});
snd.addEventListener('loadeddata', () => { $('media').dataset.snd = snd.duration.toFixed(2);
  $('media').textContent = `sound loaded (${snd.duration.toFixed(2)} s)` + ($('media').dataset.vid ? `; video ${$('media').dataset.vid}` : ''); });
main.addEventListener('loadeddata', () => { $('media').dataset.vid = `${main.videoWidth}x${main.videoHeight}`;
  $('media').textContent = ($('media').dataset.snd ? `sound loaded (${$('media').dataset.snd} s); ` : '') + `video ${main.videoWidth}x${main.videoHeight}`; });
snd.addEventListener('error', () => { $('msg').textContent = 'SOUND ERROR ' + (snd.error ? snd.error.code : ''); });
main.addEventListener('error', () => { const e = main.error; $('msg').textContent = 'VIDEO ERROR ' + (e ? e.code : ''); });
(async () => {
  meta = await (await fetch('/meta.json')).json();
  items = await (await fetch('/items.json')).json();
  answered = await (await fetch('/answered')).json();
  const box = $('classes');
  for (const [key, c] of meta.classes) {
    const b = document.createElement('button'); b.textContent = `${key} ${c}`; b.dataset.c = c;
    b.onclick = () => label(c); box.appendChild(b);
  }
  surfaces();
  show(nextOpen(0));
  requestAnimationFrame(tick);
})();
</script></body></html>
"""


def make_handler(items: list[dict], man: dict, labels: Path, html: Path):
    from reticle.clipserve import RangeHandler
    by_key = {it["key"]: it for it in items}
    names = {c for _, c in CLASSES}
    lock = threading.Lock()
    meta = {"classes": CLASSES, "variant_classes": list(VARIANT_CLASSES),
            "manifest": str(MANIFEST), "version": man["version"]}

    class Handler(RangeHandler):
        html_path = html
        videos_dir = Path(man["source_path"]).parent

        def route_get(self, req_path: str) -> bool:
            if req_path == "/items.json":
                self.send_bytes(json.dumps(items).encode(), "application/json")
            elif req_path == "/meta.json":
                self.send_bytes(json.dumps(meta).encode(), "application/json")
            elif req_path == "/answered":
                with lock:
                    rows = _answered(labels)
                self.send_bytes(json.dumps(rows).encode(), "application/json")
            elif req_path.startswith("/snippet/") and req_path.endswith(".wav"):
                try:
                    it = items[int(req_path[len("/snippet/"):-len(".wav")])]
                except (ValueError, IndexError):
                    self.send_error(404)
                    return True
                self.send_bytes(snippet_wav(*it["snip"]), "audio/wav")
            else:
                return False
            return True

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/quit":
                self.send_bytes(b"bye", "text/plain")
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path != "/answer":
                self.send_error(404)
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                it = by_key[body["key"]]
                ans = body.get("answer")
                if ans not in ANSWERS:
                    raise ValueError(f"answer must be one of {sorted(ANSWERS)}")
                lab = body.get("label")
                labs = body.get("labels")
                if ans in ("accept", "relabel") and lab not in names:
                    raise ValueError(f"unknown class {lab!r}")
                if ans == "split" and (not isinstance(labs, list) or len(labs) != 2
                                       or any(x not in names for x in labs)):
                    raise ValueError(f"a split names two known classes, got {labs!r}")
            except (KeyError, ValueError, TypeError) as exc:
                self.send_bytes(f"refused: {exc!r}".encode(), "text/plain", 400)
                return
            note = body.get("note")
            row = {"key": it["key"], "answer": ans,
                   "label": lab if ans in ("accept", "relabel") else None,
                   "labels": labs if ans == "split" else None,
                   "other_name": str(body["other_name"])[:200] if body.get("other_name") else None,
                   "variant": str(body["variant"])[:200] if body.get("variant") else None,
                   "note": str(note)[:500] if note else None,
                   "batch_from": body.get("batch_from"),
                   "proposed": it["proposed"], "proposed_variant": it.get("proposed_variant"),
                   "witness": it.get("witness"), "witness_note": it.get("witness_note"),
                   "session_id": man["session_id"], "source_path": man["source_path"],
                   "t_ms": int(round(it["t0"] * 1000)),
                   "span_ms": [int(round(it["t0"] * 1000)), int(round(it["t1"] * 1000))],
                   "compared_against_derived": True, "by": "player",
                   "manifest": str(MANIFEST), "manifest_version": man["version"],
                   "manifest_created": man["created"], "tool": TOOL,
                   "at": _dt.datetime.now().isoformat(timespec="seconds")}
            with lock:
                labels.parent.mkdir(parents=True, exist_ok=True)
                with labels.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
                    f.flush()
            self.send_bytes(json.dumps(row).encode(), "application/json")

    return Handler


def review(serve_it: bool, open_browser: bool, port: int, labels: Path) -> int:
    if not MANIFEST.is_file():
        raise SystemExit(f"{MANIFEST} does not exist; run `cut` first")
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = review_items(man)
    html = OUT / "review-20260929.html"
    html.write_text(PAGE, encoding="utf-8")
    done = _answered(labels)
    print(f"{len(items)} candidates from {man['source_path']} ({man['session_id']}); "
          f"{sum(1 for it in items if it['key'] in done)} answered in {labels}")
    if not serve_it:
        print(f"page {html}; pass --serve to review")
        return 0
    from reticle.clipserve import serve
    return serve(make_handler(items, man, labels, html), port, "the sound demo review",
                 open_browser=open_browser)


def main(argv=None) -> int:
    _idle()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("witness")
    w.add_argument("--force", action="store_true")
    c = sub.add_parser("cut")
    c.add_argument("--list", action="store_true", help="print every candidate")
    r = sub.add_parser("review")
    r.add_argument("--serve", action="store_true", help="serve the review page")
    r.add_argument("--open", action="store_true", help="open the page in the default browser")
    r.add_argument("--port", type=int, default=8767)
    r.add_argument("--labels", default=str(LABELS))
    a = ap.parse_args(argv)
    if a.cmd == "review":
        return review(a.serve, a.open, a.port, Path(a.labels))
    if a.cmd == "witness":
        wt = witness(a.force)
        print(f"{len(wt['t'])} samples; mag read {np.mean(wt['mag'] >= 0):.2f}")
        for s in held_states(wt):
            print(f"  {s[0]:7.2f}-{s[1]:7.2f} {s[2]}")
    elif a.cmd == "cut":
        man = cut()
        if a.list:
            for c in man["candidates"]:
                print(f"{c['i']:4d} {c['t0']:8.2f} {c['t1'] - c['t0']:5.2f} {c['peak'] * 1e3:6.2f} "
                      f"{c['phase']:<20} {c['proposed']:<16} {c.get('proposed_variant', ''):<3} "
                      f"{c['witness_note']}")
        _summary(man)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
