r"""Fit the "not a teammate" threshold on automatic death bindings; test on labels.

    .\.venv\Scripts\python.exe prototypes\ally_teammate_fit.py fit [--write]

Comparative rendered-art scoring always favours some teammate, so an ability
icon inside an ally ring, or a fit on bare floor, takes a teammate's name.
`identity.rendered_art_fit` measures how well an icon fits its CLOSEST
teammate reference at all; `identity.teammate_fit_refusal` refuses a piece
whose median icon fit exceeds `fit_max`.

Positives are automatic: the pieces (split as `ally_track_identity.pieces_of`
splits them) that end a segment bound to a killfeed ally death by the 200 ms
rule of `ally_rendered_art_eval.segments`. `fit_max` is their 99th percentile.
The player's labels (`labels/death_icon`) only test it: how many of the
`not_portrait` icons lie in refused pieces, and how many agent-labelled icons
are lost. `--write` stores `<store>/reference/ally_portrait/teammate_fit.json`
with its provenance, keyed to the table's calibration digest.

Storage only; no decode. Predictions and outcome: `ally-teammate-fit` in the
store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle.adjudication.identity import (TEAMMATE_FIT_FILE,  # noqa: E402
                                           load_ally_portrait_references,
                                           rendered_art_fit)
from reticle.ally_portrait import REFERENCE_DIR  # noqa: E402

import ally_rendered_art_eval as ev  # noqa: E402
import ally_track_identity as ati  # noqa: E402

STORE = ev.STORE
PERCENTILE = 99.0
VERSION = "teammate-fit-1.0.0"


def all_labels() -> dict:
    out = {}
    for p in sorted((STORE.root / "labels" / "death_icon").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return {r["observation_key"]: r for r in out.values()}


def session_pieces(sid, refs, gate):
    d = ati.session_data(sid)
    if d is None or not d["names"]:
        return None, []
    feats = {e["observation_key"]: e.get("portrait_features")
             for e in STORE.read_events("ally_icon", sid) if e.get("kind") == "icon"}
    pieces = ati.pieces_of(d, True, gate)
    for p in pieces:
        fits = [rendered_art_fit(feats.get(k), d["names"], refs) for k in p["keys"]]
        got = [f[0] for f in fits if f is not None]
        p["fit"] = float(np.median(got)) if got else None
    return d, pieces


def fit_threshold(write: bool) -> dict:
    refs = load_ally_portrait_references(STORE.root)
    gate = refs["margin_min"]
    labs = all_labels()
    sids = sorted(p.stem for p in (STORE.root / "events" / "ally_icon").glob("*.jsonl"))
    pos, lab_rows, used = [], [], []
    lo, hi = ev.WINDOW_MS
    for sid in sids:
        d, pieces = session_pieces(sid, refs, gate)
        if d is None:
            continue
        used.append(sid)
        for t, _v, _ in d["deaths"]:
            ends = [p for p in pieces if t - lo <= max(p["t"]) <= t + hi]
            if len(ends) == 1 and max(ends[0]["t"]) <= t - ev.LEAD_MS and ends[0]["fit"] is not None:
                pos.append(ends[0]["fit"])
        by_key = {k: p for p in pieces for k in p["keys"]}
        for k, r in labs.items():
            if k.startswith(sid) and k in by_key:
                lab_rows.append((r.get("class"), by_key[k]["fit"], len(by_key[k]["keys"])))
        print(sid, len(pieces), len(pos), flush=True)
    fit_max = float(np.percentile(pos, PERCENTILE))
    c = Counter()
    for cls, fit, _n in lab_rows:
        c[f"{cls}_n"] += 1
        c[f"{cls}_over"] += fit is not None and fit > fit_max
        c[f"{cls}_unread"] += fit is None
    npf = [f for cls, f, _ in lab_rows if cls == "not_portrait" and f is not None]
    out = {"fit_max": round(fit_max, 4), "positives": len(pos),
           "positive_median": round(float(np.median(pos)), 4),
           "not_portrait_median": round(float(np.median(npf)), 4) if npf else None,
           "not_portrait_fits": sorted(round(f, 3) for f in npf), **c}
    print(json.dumps(out))
    if write:
        table = {"version": VERSION, "fit_max": round(fit_max, 4),
                 "calibration_sha": refs["calibration"]["sha"],
                 "references_version": refs["version"],
                 "rule": "median over a piece's icons of identity.rendered_art_fit; "
                         f"fit_max = P{PERCENTILE:g} over pieces ending a segment bound to "
                         "a killfeed ally death (200 ms rule, ally_rendered_art_eval.segments)",
                 "positives": len(pos), "percentile": PERCENTILE, "sessions": used,
                 "fitted_by": "prototypes/ally_teammate_fit.py"}
        path = STORE.root.joinpath(*REFERENCE_DIR, TEAMMATE_FIT_FILE)
        path.write_text(json.dumps(table, indent=1), encoding="utf-8")
        print("wrote", path)
    return out


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("step", choices=("fit",))
    a.add_argument("--write", action="store_true")
    fit_threshold(a.parse_args().write)
