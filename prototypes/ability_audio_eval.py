r"""The audio witness's fit and evaluation with the probe's inputs, through
the wired command (`reticle ability-audio-fit`, `ability_audio_fit`).

    .\.venv\Scripts\python.exe prototypes\ability_audio_eval.py --gate OUT.json --iso-audio DIR
    .\.venv\Scripts\python.exe prototypes\ability_audio_eval.py --gate-in G.json --fit ROOT --iso-audio DIR
    .\.venv\Scripts\python.exe prototypes\ability_audio_eval.py --gate-in G.json --eval ROOT --json OUT --iso-audio DIR

Until 2026-10-04 this file held a hard-coded split, the reference rule and
the fit; they moved into `reticle/ability_audio_fit.py`, with the split
declared as a rule (`ability_audio.split_sessions`) and the demos scored.
What stays here is the probe's two inputs the store lacks:

* Iso on 4f207c0c4e39. The identity arbiter's verdict there is a
  disagreement (ability_tray Iso, self_icon Phoenix), so it names no agent;
  the probe and the player name Iso, and the gate snapshot records that
  basis (`--supply`).
* The log-mel and labels of that session and of three demos (29eff6920e8f
  Deadlock, 5a50d1374a84 Iso, e78e75b2d191 Omen) exist only in the probe's
  scratch directory (`--iso-audio`), unstamped; their stamps say so.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ISO = "4f207c0c4e39"
STORE = "C:/Users/grant/reticle-store"


def main(argv=None) -> int:
    import argparse

    from reticle.ability_audio_fit import main as fit_main
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate")
    ap.add_argument("--gate-in")
    ap.add_argument("--fit")
    ap.add_argument("--eval")
    ap.add_argument("--json")
    ap.add_argument("--agent", action="append")
    ap.add_argument("--iso-audio", help="the probe's directory of features/ and labels/")
    a = ap.parse_args(argv)
    args = argparse.Namespace(store=STORE, gate=a.gate, gate_in=a.gate_in, fit=a.fit,
                              eval=a.eval, json=a.json, agent=a.agent,
                              supply=[f"{ISO}=Iso"],
                              audio_dir=[a.iso_audio] if a.iso_audio else [])
    return fit_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
