"""Open the audio track for the first time, and look at it.

    .\\.venv\\Scripts\\python.exe prototypes\\audio_probe.py <session> [--from S] [--seconds N]

Why this exists
---------------
Nothing in this repo has ever opened the audio. `NOTES.md` deferred it "until a
demo clip supplies clean isolated reference audio per ability" -- and that
condition was already met and nobody had checked: **every capture carries a
stereo 48 kHz AAC track**, read straight out of the MP4 sample-entry boxes, the
two 2026-09-02 Cypher clips included. So the reference audio has existed for
eighteen sessions.

Audio is not a confirmation signal, it is the SUPERVISOR. An ability is an
event, and these SFX are fixed deterministic assets, so an onset at time *t*
says an icon appeared on the minimap within a couple of frames of *t* -- which
makes every other candidate in that window a negative BY CONSTRUCTION. That
turns an unlabelled 1300-3900-blob discrimination problem into temporal
anchoring with free labels, and it reaches abilities with no minimap footprint
at all.

This file does only the first step, deliberately: decode, render, and LOOK.
CLAUDE.md records three recurrences of measuring before looking, and the third
one got a real gate (`review_candidates.py`) precisely because a labelling GUI
was twice launched against candidates nobody had rendered. A matched filter
built against a spectrogram nobody has seen is the same mistake in a new domain.

Two facts about the format that decide the method, both worth stating before any
correlation is written:

* **AAC is lossy and does not preserve waveform phase.** A time-domain matched
  filter -- the obvious first reach -- will underperform for a reason that looks
  like the method failing rather than the container. Correlate MAGNITUDE
  SPECTROGRAMS instead;
* **the player plays with HRTF on.** That is a filter, so a reference recorded with
  it off would correlate worse against normal play. The reference bank should be
  cut from footage recorded the way he actually plays, and an HRTF-off pass is
  only worth asking for if BEARING estimation becomes a goal -- which is the one
  thing HRTF genuinely complicates.

`--marks` overlays the timestamps of the labelled ability objects, so the
question the render answers is specific: is there a visible transient where the
minimap says a device was placed?

What it found, 2026-09-03: onset detection is DEAD, and why
------------------------------------------------------------
The track decodes cleanly -- 41.9 s / 44.1 s, 48 kHz, 2 channels, L/R
correlation 0.77 and 0.86, so the stereo image is intact and pan really does
carry bearing. Everything after that is a negative.

`--sheet` renders each labelled onset magnified with CONTROL rows drawn from
times the labels say no device was placed. **The marked rows are not
distinguishable from the controls by eye.** `--flux` turns that impression into
a measurement: the percentile rank of peak spectral flux within a tolerance of
each mark, against 2000 random times *from the same clip*, so footsteps, gunfire
and ambience are in both samples.

    tol       eb10db50b1fb              79a706a7ce4c
              marks / null (median)     marks / null (median)
    +/-0.02s  0.785 / 0.799 (0.814)     0.916 / 0.810 (0.822)
    +/-0.05s  0.875 / 0.867 (0.884)     0.930 / 0.884 (0.886)
    +/-0.10s  0.962 / 0.901 (0.947)     0.949 / 0.924 (0.943)
    +/-0.30s  0.967 / 0.950 (0.991)     0.995 / 0.966 (0.990)

Marks sit where random times sit, at every tolerance. Two of 32 p-values fall
under 0.05, which is what 32 tests give by chance -- the Bonferroni threshold
here is 0.0016, and `judgement.py` exists because of exactly this kind of
uncorrected fishing. **At +/-0.3 s the null median rank is 0.99**: a random
moment in these clips is already beside a near-maximal flux peak, because the
clip is saturated with footsteps. A generic onset detector cannot be a supervisor
here; there is no shortage of onsets, only of *labelled* ones.

**Two causes, and this experiment cannot separate them.** Either the timestamps
are wrong for the purpose -- they are minimap-track FIRST OBSERVATIONS, and real
objects fragment into up to nine tracks, so a row's `t_ms` need not be a birth
at all -- or a trapwire placement is simply not acoustically salient against
this density. Saying which would need a cast time from somewhere else.

**So the dependency runs the other way, and that is the plan correction.** The
audio channel needs IDENTITY (a matched filter for one specific SFX), not onset;
a matched filter needs a reference; a reference must be cut at a known cast
time; and the cheapest exact cast time is the **ability HUD**, the bottom-left
tray, which has no ROI in `profiles.py` and which nothing has ever read. Build
that first, then come back and cut references at HUD-confirmed casts. Recorded
as a wrong prediction (0.7 confidence) rather than quietly dropped.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import av
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from ability_eval import join, STORE                              # noqa: E402

SR = 48000
N_FFT = 1024
HOP = 256


def decode(path, t0=0.0, dur=None):
    """Stereo float32 [n, 2] at the file's own rate, plus that rate.

    Resampled to a fixed layout so downstream code never has to branch on what
    the encoder chose, but NOT downmixed: the stereo difference is the only
    bearing information the capture contains, and throwing it away here would be
    expensive to undo.
    """
    with av.open(str(path)) as c:
        st = next((s for s in c.streams if s.type == "audio"), None)
        if st is None:
            raise SystemExit(f"{path}: no audio stream")
        rate = st.rate
        if t0:
            c.seek(int(t0 / st.time_base), stream=st)
        res = av.AudioResampler(format="fltp", layout="stereo", rate=rate)
        chunks, got = [], 0.0
        want = None if dur is None else dur * rate
        for frame in c.decode(st):
            for f in res.resample(frame):
                a = f.to_ndarray()                    # (channels, samples), planar
                chunks.append(a.T.astype(np.float32))
                got += a.shape[1]
            if want is not None and got >= want:
                break
    if not chunks:
        raise SystemExit(f"{path}: decoded no audio")
    x = np.concatenate(chunks, axis=0)
    return (x[: int(want)] if want else x), rate


def spectrogram(x, n_fft=N_FFT, hop=HOP):
    """Log magnitude STFT of a mono mix. numpy only -- no new dependency."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    n = 1 + (len(m) - n_fft) // hop
    if n < 1:
        raise SystemExit("clip too short for one STFT frame")
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    win = np.hanning(n_fft).astype(np.float32)
    S = np.abs(np.fft.rfft(m[idx] * win, axis=1))
    return 20.0 * np.log10(S + 1e-6).T                # [freq, time]


def ability_marks(sid):
    """Onset times (seconds) of the confirmed ability objects."""
    rows, _ = join(sid)
    return sorted({r["t_ms"] / 1000.0 for r in rows if r["_true"]})


def render(S, rate, t0, out: Path, marks=(), hop=HOP, height=420):
    """Spectrogram as an image, low frequencies at the bottom, marks drawn on.

    Structural colour is reserved for the QUESTION, matching `glance.py` and
    `overlay.py`: the magenta verticals are where the minimap says a device was
    placed. The image is the answer to "is there a transient there".
    """
    v = S.copy()
    lo, hi = np.percentile(v, 5), np.percentile(v, 99.5)
    v = np.clip((v - lo) / max(1e-6, hi - lo), 0, 1)
    img = cv2.applyColorMap((v * 255).astype(np.uint8), cv2.COLORMAP_MAGMA)
    img = cv2.flip(img, 0)
    scale = height / img.shape[0]
    img = cv2.resize(img, (img.shape[1], height), interpolation=cv2.INTER_NEAREST)
    secs = S.shape[1] * hop / rate
    for s in marks:
        x = int((s - t0) / secs * img.shape[1])
        if 0 <= x < img.shape[1]:
            cv2.line(img, (x, 0), (x, img.shape[0]), (255, 0, 255), 1)
            cv2.putText(img, f"{s:.1f}", (x + 2, 14), cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (255, 0, 255), 1, cv2.LINE_AA)
    for k in range(0, int(secs) + 1, 5):
        x = int(k / secs * img.shape[1])
        if 0 <= x < img.shape[1]:
            cv2.line(img, (x, img.shape[0] - 8), (x, img.shape[0]), (200, 200, 200), 1)
            cv2.putText(img, f"{t0 + k:.0f}s", (x + 2, img.shape[0] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.putText(img, f"0-{rate // 2} Hz, low at bottom   magenta = labelled ability onset",
                (6, img.shape[0] - 26), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                (255, 255, 255), 1, cv2.LINE_AA)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img)
    return out


#: Half-width of a window around a mark, seconds. Wide enough to show what the
#: transient sits in, narrow enough that one row renders near 1:1.
PAD = 2.0


def sheet(x, rate, marks, out: Path, controls=(), pad=PAD, row_h=200):
    """One row per labelled onset, plus CONTROL rows from times with no label.

    The whole-clip render is unreadable for this question: at 7857 px wide it
    arrives downsampled about 4x and the marks vanish, which is
    `glance.py`'s acuity finding in a new domain -- *the fix is magnification at
    a STATED factor, not a bigger image*. Each row here is 4 s at hop 256, so
    ~750 STFT frames, which survives the trip.

    The controls are the mechanism, and they are not mine: a control row is
    drawn from a time the labels say NO device was placed, so if the marked
    rows and the control rows look alike, the finding is that this transient is
    not separable by eye at this resolution -- and the next move is a matched
    filter scored against the labels, not a threshold picked off this picture.
    """
    rows = []
    for s, kind in [(m, "MARK") for m in marks] + [(c, "ctrl") for c in controls]:
        a, b = int(max(0, s - pad) * rate), int((s + pad) * rate)
        seg = x[a:b]
        if len(seg) < N_FFT * 2:
            continue
        S = spectrogram(seg)
        v = np.clip((S - np.percentile(S, 5)) /
                    max(1e-6, np.percentile(S, 99.5) - np.percentile(S, 5)), 0, 1)
        img = cv2.flip(cv2.applyColorMap((v * 255).astype(np.uint8),
                                         cv2.COLORMAP_MAGMA), 0)
        img = cv2.resize(img, (img.shape[1], row_h), interpolation=cv2.INTER_NEAREST)
        cx = img.shape[1] // 2
        col = (255, 0, 255) if kind == "MARK" else (0, 255, 255)
        cv2.line(img, (cx, 0), (cx, row_h), col, 1)
        cv2.putText(img, f"{kind} {s:.2f}s", (4, 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, col, 1, cv2.LINE_AA)
        rows.append(img)
    if not rows:
        raise SystemExit("no rows to render")
    w = min(r.shape[1] for r in rows)
    grid = np.vstack([r[:, :w] for r in rows])
    cv2.putText(grid, f"+/-{pad}s around each time, {rate} Hz, low at bottom",
                (4, grid.shape[0] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (255, 255, 255), 1, cv2.LINE_AA)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), grid)
    return out


def flux(S):
    """Spectral flux: summed positive frame-to-frame change. The standard onset
    envelope, and half-wave rectified so a sound STARTING counts and a sound
    stopping does not."""
    d = np.diff(S, axis=1)
    return np.maximum(d, 0).sum(axis=0)


def flux_test(x, rate, marks, tol=0.3, n_null=2000, seed=0, hop=HOP):
    """Do the labelled onsets sit on flux peaks more than random times do?

    The sheet showed no visible difference between marked and control rows, and
    an impression is not a result. This is the measurement: for each mark, the
    PERCENTILE RANK of the largest flux value within `tol` seconds of it,
    against the same statistic computed at random times. If the marks are real
    onsets their ranks cluster near 1.0; if audio says nothing about them the
    two distributions coincide.

    The null is drawn from the same clip, so ambience, footsteps and gunfire are
    in BOTH samples -- which is the whole point. A null of silence would prove
    only that the clip contains sound.
    """
    S = spectrogram(x)
    f = flux(S)
    fps = rate / hop
    order = np.argsort(np.argsort(f)) / max(1, len(f) - 1)   # percentile rank per frame

    def rank_at(t):
        c = int(t * fps)
        w = int(tol * fps)
        a, b = max(0, c - w), min(len(order), c + w + 1)
        return float(order[a:b].max()) if b > a else float("nan")

    got = [rank_at(m) for m in marks]
    rng = np.random.default_rng(seed)
    dur = len(x) / rate
    null = [rank_at(t) for t in rng.uniform(tol, dur - tol, n_null)]
    got = [g for g in got if not np.isnan(g)]
    null = [n for n in null if not np.isnan(n)]
    # One-sided: how often does a random time beat a given mark?
    p = [float(np.mean([n >= g for n in null])) for g in got]
    return got, null, p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--from", dest="t0", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--marks", action="store_true",
                    help="overlay the labelled ability onsets")
    ap.add_argument("--sheet", action="store_true",
                    help="one magnified row per labelled onset, plus controls")
    ap.add_argument("--flux", action="store_true",
                    help="do labelled onsets sit on flux peaks more than random times?")
    args = ap.parse_args()
    sid = args.session

    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    path = man["source"]["path"]
    x, rate = decode(path, args.t0, args.seconds)
    dur = len(x) / rate
    peak = float(np.abs(x).max())
    rms = float(np.sqrt((x ** 2).mean()))
    corr = float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]) if x.shape[1] == 2 else 1.0
    print(f"{sid}: {path}")
    print(f"   {dur:.1f}s  {rate} Hz  {x.shape[1]}ch  "
          f"peak {peak:.3f}  rms {rms:.4f}  L/R corr {corr:.3f}")
    if corr > 0.999:
        print("   L/R correlation ~1.0 -- effectively MONO. No bearing information.")
    else:
        print("   L and R differ -- stereo image is intact, so pan carries bearing.")

    marks = ability_marks(sid) if (args.marks or args.sheet or args.flux) else ()
    if marks:
        print(f"   labelled ability onsets: {[round(m, 2) for m in marks]}")

    if args.flux:
        if not marks:
            raise SystemExit("no labelled onsets to test")
        got, null, p = flux_test(x, rate, marks)
        print(f"\n   flux percentile rank within +/-0.3s "
              f"({len(null)} random times as the null, same clip):")
        for m, g, pv in zip(marks, got, p):
            print(f"      mark {m:6.2f}s   rank {g:.3f}   "
                  f"p={pv:.3f} {'<-- stands out' if pv < 0.05 else ''}")
        print(f"      null       mean rank {np.mean(null):.3f}   "
              f"median {np.median(null):.3f}")
        print(f"      marks      mean rank {np.mean(got):.3f}")
        print("\n   A mark is only evidence of an audible placement if its rank")
        print("   beats the null. Ranks near the null mean the audio says nothing")
        print("   about these timestamps -- which is a fact about the TIMESTAMPS")
        print("   as much as about the audio: they are minimap-track first")
        print("   observations, not cast times.")
        return 0

    if args.sheet:
        # Controls from times at least 3 s clear of every mark, spread over the
        # clip. Drawn from the labels (the absence of one), not from my eye.
        cand = [round(t, 2) for t in np.arange(PAD, dur - PAD, 1.0)]
        ctrl = [t for t in cand if all(abs(t - m) > 3.0 for m in marks)]
        ctrl = ctrl[:: max(1, len(ctrl) // 4)][:4]
        print(f"   controls (no labelled device): {ctrl}")
        out = sheet(x, rate, marks, STORE / "glances" / f"audio-sheet-{sid}.png", ctrl)
        print(f"   wrote {out}")
        print("   LOOK AT IT before writing a matched filter.")
        return 0

    S = spectrogram(x)
    out = render(S, rate, args.t0,
                 STORE / "glances" / f"audio-{sid}-{int(args.t0)}s.png", marks)
    print(f"   wrote {out}")
    print("   LOOK AT IT before writing a matched filter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
