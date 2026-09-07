r"""Segment the audio into discrete SOUND EVENTS and align them to tray casts.

    .\.venv\Scripts\python.exe prototypes\audio_events.py <session> [--gate 0.002]
    .\.venv\Scripts\python.exe prototypes\audio_events.py <session> --align

Why this exists, and why it is not `audio_probe.py`
-----------------------------------------------------
`audio_probe.py` asked whether marks sit on spectral-flux PEAKS and found they
do not -- at +/-0.3 s a random moment in those clips already sits beside a
near-maximal peak, because the clip is saturated with footsteps. Its verdict
was that onset cannot be the supervisor and the channel needs IDENTITY, via a
matched filter, which needs a reference cut at a known cast time.

**The tray now supplies that cast time**, and the missing piece was never the
statistic -- it was the RECORDING. the player recorded `b9558488a607` on 2026-09-06
to a deliberate protocol: equip, hold the target while STATIONARY, cast, pause,
repeat. This file measures what that bought.

A sound event here is a contiguous run of 50 ms RMS bins above a gate, at least
0.10 s long. That is deliberately cruder than spectral flux: the question is
not "is there an onset" -- there are always onsets -- but "where are the
ISLANDS of sound in a clip that is mostly silent", which only exists as a
question once the recording has silence in it.

RESULT on `b9558488a607` (Omen, 83 s, spaced casts, 2026-09-06)
-----------------------------------------------------------------
**THE TRAY AND THE AUDIO AGREE TO WITHIN ONE 50 ms BIN ON 6 CASTS OF 6.**

    slot  tray cast   audio event    dur    peak    offset
    C        8.4 s    8.40-10.70    2.30    22.3    +0.00
    C       21.0 s   21.00-23.15    2.15    21.1    +0.00
    Q       36.8 s   36.85-38.55    1.70    25.6    +0.05
    E       46.8 s   46.80-48.70    1.90    12.8    +0.00
    E       54.9 s   54.90-56.85    1.95    14.8    +0.00
    X       74.9 s   74.95-79.35    4.40    33.0    +0.05

Two INDEPENDENT readers -- a teal pixel count in the bottom-left HUD, and an
RMS envelope of the audio track -- landing on the same instant six times out of
six. Neither was fitted to the other and they share no code, no pixels and no
failure mode. **This is the strongest label-free cross-channel check in the
repo**, the same class as the killfeed anchor and the camera-pan facing test,
and it validates the tray reader as much as it validates the audio.

The cast sounds are also the LOUDEST events in the clip -- peaks 12.8-33.0
against 2-10 for everything else -- and the two Shrouded Step casts come out at
2.30 s / 2.15 s and 22.3 / 21.1, near-identical because they are the same
ability twice. A built-in replicate, for free.

**THE EQUIP SOUND IS VISIBLE, and it is the claim arriving independently.**
The player said (2026-09-06) that every ability has a separate equip and cast sound and
that the equip is self-only. Two events in this clip are near-identical to each
other and to nothing else:

    3.65 - 4.80 s   dur 1.15   peak 9.2     -4.75 s before the first C cast
    13.90 - 15.05 s dur 1.15   peak 9.4     -7.10 s before the second C cast

Same duration to the bin, same peak to 2%, one before each of the two teleport
casts, and the player equipped exactly twice. Candidates for the other slots are weaker
and are NOT claimed: X has a 0.55 s / 16.9 event at -1.95 s, the second E a
0.45 s / 10.5 at -3.90 s, and **the first E cast has NOTHING before it** back
to 40 s. So either that equip is silent, or E was already up -- which is the
honest reason coverage stays UNVERIFIED, exactly as the player hedged it.

WHAT THE PROTOCOL BOUGHT, stated so the next recording keeps it
------------------------------------------------------------------
**The second teleport cast has FIVE SECONDS OF DIGITAL SILENCE in front of it**
(every 50 ms bin at the 0.0002 noise floor, against a cast peak of 21.1). That
is a reference cut with zero contamination -- not a good signal-to-noise ratio,
an absence of anything to be confused with. No amount of filtering recovers
that from a clip where the player was running.

So the earlier worry, that the corpus might need re-recording because the
player is moving, was aimed at the right problem with the wrong instrument (see
`BACKLOG.md` -- a "still" test built on the max of a track statistic said 0 of 6
casts here were stationary, on a clip whose median speed is 0.0 px/s). **The
protocol is what matters, and it is three rules:**

    stand still while casting     removes the loudest contaminant
    pause between casts           gives silence to cut against, and stops two
                                  abilities' sounds overlapping
    equip, hold, then cast        separates the equip sound from the cast sound
                                  by more than their own durations

CAUTIONS
--------
* **the gate is a level and this HUD's own rule says never trust one.** 0.002
  is 10x the measured silence floor of this clip and it is NOT portable: a real
  match has ambience under everything and no bin will sit at 0.0002. This file
  is for controlled clips. On a match, come back to a matched filter against the
  references these clips produce, which is the whole point of cutting them;
* **the audio is STEREO and must be summed to mono first.** `audio_probe.decode`
  returns `(n, 2)`, and `flux_test` hands that straight to `spectrogram`, which
  is a latent defect in that file rather than here;
* **this clip is quiet** -- peak 0.102 full-scale, RMS 0.0057. Loud enough to
  measure, but if OBS can record hotter without clipping, a later sitting would
  give the dictionary more to work with.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
with contextlib.redirect_stdout(io.StringIO()):
    import ability_hud
    import audio_probe

STORE = pathlib.Path.home() / "reticle-store"

#: RMS bin. 50 ms is short against every ability sound measured (0.45-4.40 s)
#: and long enough that one bin is not a click.
BIN_S = 0.05
#: Above this RMS a bin is SOUND. Ten times `b9558488a607`'s measured silence
#: floor of 0.0002. A level, and therefore not portable -- see the docstring.
GATE = 0.002
#: Shorter than this is not an event. Below it the segmentation returns the
#: encoder's own noise as hundreds of one-bin fragments.
MIN_EVENT_S = 0.10


def envelope(x, rate, bin_s=BIN_S):
    """RMS per bin, mono. Stereo is SUMMED, not indexed -- see the docstring."""
    if x.ndim == 2:
        x = x.mean(axis=1)
    n = max(1, int(bin_s * rate))
    sq = np.convolve(x.astype(np.float64) ** 2, np.ones(n) / n, "same")
    return np.sqrt(sq)[::n]


def events(env, bin_s=BIN_S, gate=GATE, min_s=MIN_EVENT_S):
    """Contiguous runs above the gate, as (t0, t1, peak)."""
    loud = env > gate
    out, i = [], 0
    while i < len(loud):
        if not loud[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(loud) and loud[j + 1]:
            j += 1
        if (j - i + 1) * bin_s >= min_s:
            out.append((i * bin_s, (j + 1) * bin_s, float(env[i:j + 1].max())))
        i = j + 1
    return out


def load(sid, step_s=0.1):
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
    ts, counts, clean = ability_hud.scan(sid, step_s=step_s)
    casts = ability_hud.casts(ts, counts, clean)
    x, rate = audio_probe.decode(man["source"]["path"])
    return casts, x, rate


def cut(sid, out_dir, step_s=0.1, pad_pre=0.10, pad_post=0.30):
    """Write one WAV per cast-aligned sound event: the ability's REFERENCE.

    **The cut is bounded by the measured event, not by a fixed length.** An
    ability's sound runs 1.70-4.40 s on `b9558488a607` and a fixed window would
    either truncate the ult or pad the others with whatever came next.

    `pad_pre` catches the attack transient the RMS gate crosses slightly late;
    `pad_post` catches the tail decaying back under it. Both are small and
    stated rather than fitted -- this is a cut, not a detector, and a reference
    with a little silence on it costs a matched filter nothing.

    Named `<agent>_<slot>_<ability>__<sid>_<t>.wav` so the provenance travels
    with the file: which session, which second. A reference whose origin has to
    be looked up is one nobody re-cuts when the recording is superseded.
    """
    import wave
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import cast_motion as cm

    agent = cm.tagged_agent(sid) or "unknown"
    cmap = cm.class_map()
    ab = {}
    for (ag, slot), (_cls, name) in cmap.items():
        if ag == agent:
            ab[slot] = name

    casts, x, rate = load(sid, step_s)
    env = envelope(x, rate)
    evs = events(env)
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mono = x.mean(axis=1) if x.ndim == 2 else x
    written = []
    for t, slot, *_rest in casts:
        near = [e for e in evs if abs(e[0] - t) <= 2 * BIN_S]
        if not near:
            continue
        t0, t1, pk = near[0]
        a = max(0, int((t0 - pad_pre) * rate))
        b = min(len(mono), int((t1 + pad_post) * rate))
        seg = mono[a:b]
        name = ab.get(slot, f"slot{slot}").lower().replace(" ", "-")
        fn = out_dir / f"{agent}_{slot}_{name}__{sid}_{t:.1f}s.wav"
        pcm = np.clip(seg * 32767.0, -32768, 32767).astype("<i2")
        with wave.open(str(fn), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(rate))
            w.writeframes(pcm.tobytes())
        written.append((fn.name, t1 - t0 + pad_pre + pad_post, pk))
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--gate", type=float, default=GATE)
    ap.add_argument("--step", type=float, default=0.1, help="tray sample step")
    ap.add_argument("--align", action="store_true",
                    help="one row per CAST: the audio event that starts nearest it")
    ap.add_argument("--cut", metavar="DIR",
                    help="write one WAV per cast-aligned event: the references")
    a = ap.parse_args(argv)

    if a.cut:
        got = cut(a.session, a.cut, a.step)
        print(f"{len(got)} references written to {a.cut}" + chr(10))
        print(f"{'file':<58}{'dur':>6}{'peak':>8}")
        for n, d, pk in got:
            print(f"{n:<58}{d:>6.2f}{pk*1000:>8.1f}")
        return 0

    casts, x, rate = load(a.session, a.step)
    env = envelope(x, rate)
    ev = events(env, gate=a.gate)
    dur = len(x) / rate
    floor = float(np.percentile(env, 10))
    print(f"{a.session}: {dur:.0f}s, {len(casts)} tray casts, {len(ev)} sound "
          f"events above {a.gate:g} rms; 10th-pct floor {floor:.5f}\n")

    if a.align:
        print(f"{'slot':<5}{'tray':>8}{'audio event':>16}{'dur':>6}{'peak':>7}"
              f"{'offset':>9}")
        hit = 0
        for t, slot, *_ in casts:
            near = sorted(ev, key=lambda e: abs(e[0] - t))
            if not near:
                print(f"{slot:<5}{t:>8.1f}{'--':>16}")
                continue
            t0, t1, pk = near[0]
            off = t0 - t
            hit += abs(off) <= 2 * BIN_S
            print(f"{slot:<5}{t:>8.1f}{f'{t0:.2f}-{t1:.2f}':>16}{t1-t0:>6.2f}"
                  f"{pk*1000:>7.1f}{off:>+9.2f}")
        print(f"\n{hit}/{len(casts)} casts have a sound event starting within "
              f"{2*BIN_S*1000:.0f} ms of the tray time")
        return 0

    ct = {round(t, 2): s for t, s, *_ in casts}
    print(f"{'start':>8}{'end':>8}{'dur':>6}{'peak':>8}   nearest cast")
    for t0, t1, pk in ev:
        d = sorted((abs(t0 - t), t, s) for t, s in ct.items())
        tag = "--"
        if d and d[0][0] < 12:
            tag = f"{d[0][2]} @ {d[0][1]:.1f}s   {t0 - d[0][1]:+.2f}s"
        print(f"{t0:>8.2f}{t1:>8.2f}{t1-t0:>6.2f}{pk*1000:>8.1f}   {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
