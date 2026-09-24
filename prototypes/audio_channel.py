r"""Audio as an identity channel for the local player's abilities.

    .\.venv\Scripts\python.exe prototypes\audio_channel.py witness  <session>
    .\.venv\Scripts\python.exe prototypes\audio_channel.py retrieve [--record]
    .\.venv\Scripts\python.exe prototypes\audio_channel.py transfer <src> <dst> [--record]

Why this exists
---------------
`audio_events.py` showed that tray casts and RMS sound events agree to one
50 ms bin on a quiet, spaced-cast Omen clip. That established TIMING. This file
asks the next question the entity channel needs: can the audio say WHICH ability,
and which PHASE of it (equip, cast, activation, end) [domain:abilities/ability-sound-phases],
including where the tray is blind? It was run as a control loop: state a prediction, measure, and revise
the instrument or the belief. The predictions are logged in the store's
`notes/predictions.jsonl` under `audio-channel-control`.

Three instruments, each independent of the others
-------------------------------------------------
* **Tray** (`ability_hud`): a charge bar falling. It sees spent charges only.
* **Equip witness** (`witness`, new): the white glyph fraction of `hud_ammo`.
  The ammo counter disappears while the player holds anything that is not a
  gun [domain:abilities/ammo-hidden-while-non-gun-held]. That makes it an equip/unequip witness sharing no pixels with the tray and
  no signal with the audio. It fires for the KNIFE too; it means "non-gun
  held", never "ability equipped". Its level is composited over the world (bright
  scenes lift it to 0.3-0.6), so only the hidden state (< 0.02) is trusted.
* **Audio**: log-mel (64 bands, 60 Hz-16 kHz, 10 ms hop) with the clip's
  per-band median removed, so stationary ambience cancels.

What the loop found (2026-09-24; Omen `b9558488a607`, `e78e75b2d191`; Deadlock `29eff6920e8f`)
-----------------------------------------------------------------------------------------------
1. **Onset alone cannot supervise on a normal clip.** On Deadlock a random moment
   already sits beside a 13 dB rise, and equip onsets rank only 0.77-0.90
   against that null. This repeats `audio_probe.py`'s finding.
2. **Identity works within a session.** A 0.6 s log-mel template slid over the
   whole clip finds its same-ability partner first in
   [metric:audio_channel/retrieve#corr_hits=15] of 16 directed queries (Omen C/Q/E/X equips, C/E casts;
   Deadlock Sonic Sensor equips and casts). The audio named an equip the player
   CANCELLED (Omen 24.1 s, matching the Paranoia equip at 0.96), which the tray
   cannot see; the video confirmed Paranoia was held and not thrown.
3. **Voice lines are additive masks** [domain:abilities/ability-voice-line-mask]. The miss is Omen's ult equip at 60.3 s, voiced, against the
   unvoiced one at 72.9 s. Correlation penalises added energy, so a one-sided
   `coverage` score (fraction of the reference's loud cells the observation
   reaches) recovers it at 1.00 from the clean reference. Coverage alone is too
   permissive: loud broadband events cover every template
   ([metric:audio_channel/retrieve#cover_hits=12] of 16). A high-band-only correlation
   did NOT fix the voiced pair (logged P8, wrong).
4. **Cross-session transfer is partial.** Templates from `b9558488a607` find
   the C, Q and X casts in `e78e75b2d191` as their top peak, but Dark Cover's
   cast does not transfer (window max 0.38-0.54). There it is cast from inside
   the phased view and the orb flies off. The E-equip template also matches
   KNIFE equips and swings at 0.84-0.87, above the true E equip (0.81). A bank
   therefore needs a reject class (knife, gun, footsteps) and references from
   more than one session before any threshold means anything.
5. **Self sounds carry a stable stereo signature.** Omen's C equip reads
   +1.95/+1.94 dB L-R and his Q equip -1.03/-0.76 dB, likely the hand holding
   it. So ILD is an identity feature for self sounds, not a position cue. No
   position claim is made.
6. **Phases observed.** Deadlock's tray X drop (45.3 s) is the ult EQUIP
   [domain:abilities/deadlock-ult-tray-drop-at-equip]; the
   fire is at 50.2 s, a separate onset. Barrier Mesh has a separate activation
   onset (13.2 s) after its cast (11.9 s). The GravNet detonation (42.0 s)
   coincides with the gun-return onset and is not separable by onset alone;
   its minimap flash is a better witness [domain:abilities/deadlock-gravnet-detonation-flash].

What this does not do
---------------------
It emits no events and decides nothing; `reticle/` does not import it. The
retrieval labels are video-verified by the agent, not player-labelled.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
with contextlib.redirect_stdout(io.StringIO()):
    import audio_probe

STORE = Path.home() / "reticle-store"
CACHE = STORE / "analysis" / "audio_channel"
VERSION = "audio-channel-0.1.0"
HOP = 0.01
TEMPLATE_S = 0.6
PRE_S = 0.05
#: `hud_ammo` in `reticle/profiles.py`, as frame fractions.
AMMO_ROI = (0.654, 0.917, 0.729, 0.977)
HIDDEN = 0.02
SHOWN = 0.04

#: Same-ability pairs, times in seconds, each checked against the video
#: (viewmodel and outcome) on 2026-09-24. Equip times are witness onsets.
PAIRS = {
    "b9558488a607": {"equip C": (3.55, 13.75), "equip Q": (24.15, 33.05),
                     "equip E": (39.05, 50.95), "equip X": (60.3, 72.95),
                     "cast C": (8.4, 21.0), "cast E": (46.8, 54.9)},
    "29eff6920e8f": {"equip Q": (17.25, 27.42), "cast Q": (24.56, 33.40)},
}


def _source(sid: str) -> str:
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
    return man["source"]["path"]


def witness(sid: str, step_s: float = 0.1) -> tuple[np.ndarray, np.ndarray]:
    """(t, white fraction of the ammo counter), cached under the store."""
    import av
    import cv2
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"ammo_{sid}_{step_s}.npz"
    if path.is_file():
        a = np.load(path)
        return a["ts"], a["wf"]
    x0, y0, x1, y1 = AMMO_ROI
    ts, wf, nxt = [], [], 0.0
    with av.open(_source(sid)) as c:
        st = c.streams.video[0]
        for fr in c.decode(st):
            t = float(fr.pts * st.time_base)
            if t + 1e-3 < nxt:
                continue
            nxt = t + step_s
            im = fr.to_ndarray(format="bgr24")
            h, w = im.shape[:2]
            hsv = cv2.cvtColor(im[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)],
                               cv2.COLOR_BGR2HSV)
            wf.append(float(((hsv[..., 2] > 200) & (hsv[..., 1] < 40)).mean()))
            ts.append(t)
    np.savez(path, ts=ts, wf=wf, version=VERSION)
    return np.asarray(ts), np.asarray(wf)


def held_windows(ts, wf) -> list[tuple[float, float]]:
    """Intervals with the ammo counter hidden after at least 0.3 s shown."""
    out, start = [], None
    for i in range(3, len(ts)):
        hid, was = wf[i] < HIDDEN, wf[i - 1] < HIDDEN
        if hid and not was and (wf[i - 3:i] > SHOWN).all():
            start = ts[i]
        if start is not None and not hid and was:
            out.append((float(start), float(ts[i])))
            start = None
    return out


def _mel_fb(rate, nfft, n=64, fmin=60.0, fmax=16000.0):
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    imel = lambda m: 700 * (10 ** (m / 2595) - 1)
    pts = imel(np.linspace(mel(fmin), mel(fmax), n + 2))
    f = np.fft.rfftfreq(nfft, 1 / rate)
    fb = np.zeros((n, len(f)))
    for i in range(n):
        a, b, c = pts[i:i + 3]
        fb[i] = np.clip(np.minimum((f - a) / (b - a), (c - f) / (c - b)), 0, None)
    return fb


def logmel(sid: str, nfft: int = 2048) -> np.ndarray:
    """[frames, 64] log-mel, frame i describing time i*HOP, ambience removed."""
    x, rate = audio_probe.decode(_source(sid))
    m = x.mean(axis=1)
    h = int(HOP * rate)
    n = (len(m) - nfft) // h
    idx = np.arange(nfft)[None] + h * np.arange(n)[:, None]
    P = np.abs(np.fft.rfft(m[idx] * np.hanning(nfft), axis=1)) ** 2
    L = 10 * np.log10(P @ _mel_fb(rate, nfft).T + 1e-10)
    L = np.vstack([np.full((nfft // 2 // h, L.shape[1]), L.min()), L])
    return L - np.median(L, axis=0)


def template(L, t):
    return L[int((t - PRE_S) / HOP):int((t - PRE_S + TEMPLATE_S) / HOP)]


def corr_curve(L, tm) -> np.ndarray:
    """Normalised cross-correlation of a template at every frame."""
    k = len(tm)
    W = np.lib.stride_tricks.sliding_window_view(L, (k, L.shape[1]))[:, 0]
    W = W.reshape(len(W), -1)
    W = (W - W.mean(1, keepdims=True)) / (W.std(1, keepdims=True) + 1e-9)
    t = tm.ravel()
    t = (t - t.mean()) / (t.std() + 1e-9)
    out = np.full(len(L), -1.0)
    out[:len(W)] = W @ t / len(t)
    return out


def coverage_curve(L, tm, tol: float = 3.0) -> np.ndarray:
    """Fraction of the template's loud cells the observation reaches.

    One-sided on purpose: a voice line or ambience only ADDS energy, so an
    observation louder than the reference is not evidence against it. The gain
    offset is the 20th percentile of observation-minus-template, bounded to
    +/-tol dB, so a much quieter event cannot match.
    """
    k = len(tm)
    loud = tm > np.percentile(tm, 70)
    W = np.lib.stride_tricks.sliding_window_view(L, (k, L.shape[1]))[:, 0]
    D = W[:, loud] - tm[loud][None]
    g = np.clip(np.percentile(D, 20, axis=1), -tol, tol)
    out = np.zeros(len(L))
    out[:len(W)] = ((D - g[:, None]) >= -tol).mean(1)
    return out


def retrieve(record: bool = False) -> dict:
    """Does each labelled event's partner win over the whole clip?"""
    hits = {"corr": 0, "cover": 0, "prod": 0}
    n, misses = 0, []
    for sid, pairs in PAIRS.items():
        L = logmel(sid)
        for label, (a, b) in pairs.items():
            for q, p in ((a, b), (b, a)):
                tm = template(L, q)
                c1 = corr_curve(L, tm)
                c2 = coverage_curve(L, tm)
                curves = {"corr": c1, "cover": c2, "prod": np.clip(c1, 0, None) * c2}
                n += 1
                for name, c in curves.items():
                    c = c.copy()
                    c[max(0, int((q - 0.65) / HOP)):int((q + 0.55) / HOP)] = -9
                    j = int((p - PRE_S) / HOP)
                    true = c[max(0, j - 20):j + 21].max()
                    c[max(0, j - 60):j + 61] = -9
                    rival = c.max()
                    if true > rival:
                        hits[name] += 1
                    else:
                        misses.append((name, sid, label, q, round(float(true), 2),
                                       round(float(rival), 2),
                                       round(int(np.argmax(c)) * HOP + PRE_S, 2)))
    print(f"{n} directed queries")
    for k, v in hits.items():
        print(f"  {k:<6} partner is top match {v}/{n}")
    for m in misses:
        print("  miss", *m)
    if record:
        from reticle import metrics
        metrics.record("audio_channel", part="retrieve",
                       values={"n": n, "corr_hits": hits["corr"],
                               "cover_hits": hits["cover"], "prod_hits": hits["prod"]},
                       deps={"version": VERSION, "sessions": sorted(PAIRS),
                             "template_s": TEMPLATE_S},
                       note="labels video-verified by agent, not player")
    return {"n": n, **hits}


#: Tray slot of each cast template cut from `b9558488a607`.
TRANSFER_REFS = {"C": 8.4, "Q": 36.85, "E": 46.8, "X": 74.95}


def transfer(src: str, dst: str, record: bool = False) -> dict:
    """Slide `src`'s cast templates over `dst`; check against dst's tray casts."""
    casts_path = sorted((STORE / "casts").glob(f"{dst}.step*.json"))
    if not casts_path:
        raise SystemExit(f"{dst}: no cached tray casts under casts/")
    casts = json.loads(casts_path[0].read_text(encoding="utf-8"))
    step = float(re.search(r"\.step(\d+(?:\.\d+)?)\.", casts_path[0].name).group(1))
    Ls, Ld = logmel(src), logmel(dst)
    values = {}
    for slot, t in TRANSFER_REFS.items():
        c = corr_curve(Ld, template(Ls, t))
        top = int(np.argmax(c)) * HOP + PRE_S
        own = [ct for ct, s, *_ in casts if s == slot]
        in_own = any(ct - step - 0.15 <= top <= ct + 0.15 for ct in own)
        win = [float(c[int((ct - step - 0.2) / HOP):int((ct + 0.1) / HOP)].max())
               for ct in own]
        values[f"{slot}_top_in_slot"] = int(in_own)
        values[f"{slot}_min_window"] = round(min(win), 2) if win else None
        print(f"{slot}: top {top:.2f} ({c.max():.2f}) in own window: {in_own}; "
              f"own-window maxima {[round(w, 2) for w in win]}")
    if record:
        from reticle import metrics
        metrics.record("audio_channel", part="transfer", session=dst,
                       values=values, deps={"version": VERSION, "src": src,
                                            "template_s": TEMPLATE_S})
    return values


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("witness")
    w.add_argument("session")
    r = sub.add_parser("retrieve")
    r.add_argument("--record", action="store_true")
    t = sub.add_parser("transfer")
    t.add_argument("src")
    t.add_argument("dst")
    t.add_argument("--record", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "witness":
        ts, wf = witness(a.session)
        for s, e in held_windows(ts, wf):
            print(f"non-gun held {s:7.2f} - {e:7.2f}  ({e - s:.1f} s)")
    elif a.cmd == "retrieve":
        retrieve(a.record)
    else:
        transfer(a.src, a.dst, a.record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
