r"""Fit the calibration that `reticle.ally_portrait.build_references` renders under.

    .\.venv\Scripts\python.exe prototypes\ally_portrait_calibration.py fit
    .\.venv\Scripts\python.exe prototypes\ally_portrait_calibration.py scale

Purpose. `minimap_feature_bank` showed that references rendered from the
game's minimap portrait art, scored on the 3x3 Lab grid, native-scale HOG and
the horizontal profile, name the player's labelled ally icons. Its render
parameters, affine Lab colour map and per-feature variances were fitted per
held-out fold. This fits them once on every session's automatic labels (death
bindings ending more than 200 ms before the killfeed death; never the
player's labels) and writes them to `<store>/reference/ally_portrait/
calibration.json` with their provenance, for the reticle builder to read.

`fit` also sets the assignment margin the identity owner refuses under: the
5th percentile of the four-candidate top-two margin over automatic-label icons
whose best candidate is the bound agent.

`scale` refits the renderer on the 331 px and the 465 px sessions apart, to
test whether the parameters need a widget-scale key.

Reuses `minimap_feature_bank.Bank` (its cached bank of aligned icons). The
features are `reticle.ally_portrait.portrait_features`; the bank's copies agree
exactly on 80 icons of both widget sizes. No decode.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle import ally_portrait as ap  # noqa: E402
from reticle.version import ALLY_PORTRAIT_FEATURES_VERSION  # noqa: E402

import ally_icon_separability as asep  # noqa: E402
import minimap_feature_bank as fb  # noqa: E402

OUT = fb.mic.STORE.root.joinpath(*ap.REFERENCE_DIR)
VERSION = "ally-portrait-calibration-1.0.0"


def widths() -> dict:
    return {p.stem: int(next(iter(pickle.loads(p.read_bytes()).values()))["w"])
            for p in asep.OUT.glob("*.pkl")}


def scores(bank, refs, var, sid):
    """Per icon of `sid`'s automatic rows: summed family log likelihood per agent."""
    rows = [r for r in bank.rows if r[1] == sid]
    ii = np.array([r[0] for r in rows])
    tot = 0.0
    for f in ap.FAMILIES:
        X = bank.fams[f][ii].astype(np.float64)
        v = var[f]
        tot = tot - 0.5 * ((((X[:, None, :] - refs[f][None]) ** 2) / v) + np.log(v)).mean(2)
    return rows, tot


def run_fit() -> dict:
    bank = fb.Bank()
    art = fb.load_art()
    p = fb.fit_renderer(bank, art, bank.sids)
    rend = {}
    for a in bank.agents:
        if a in art:
            img = fb.rendered_image(art[a], p)
            rend[a] = ap.portrait_features(img, asep.key_mask(img))
    var, gap, refs = {}, {}, {}
    for f in ap.FAMILIES:
        M, v, _, _ = bank.fit(f, bank.sids)
        Ra = np.full_like(M, np.nan)
        for a, x in rend.items():
            Ra[bank.aix[a]] = x[f]
        both = np.isfinite(M[:, 0]) & np.isfinite(Ra[:, 0])
        gap[f] = ((Ra[both] - M[both]) ** 2).mean(0) + 1e-6
        var[f], refs[f] = v, Ra
    tv = {f: var[f] + gap[f] for f in ap.FAMILIES}
    margins, right, n = [], 0, 0
    for s in bank.sids:
        rows, S = scores(bank, refs, tv, s)
        cs = [c for c in fb.cands_of(bank, s) if np.isfinite(S[0, c])]
        for r, sc in zip(rows, S):
            order = sorted(cs, key=lambda c: -sc[c])
            n += 1
            if len(order) >= 2 and order[0] == r[2]:
                right += 1
                margins.append(sc[order[0]] - sc[order[1]])
    margin_min = float(np.percentile(margins, 5))
    cal = {"version": VERSION, "features_version": ALLY_PORTRAIT_FEATURES_VERSION,
           "q": p["q"], "sigma": p["sigma"], "dy": p["dy"], "err": p["err"],
           "bg": [float(v) for v in p["bg"]], "W": np.asarray(p["W"]).tolist(),
           "var": {f: var[f].tolist() for f in ap.FAMILIES},
           "gap": {f: gap[f].tolist() for f in ap.FAMILIES},
           "margin_min": margin_min,
           "provenance": {
               "fitted": str(date.today()), "by": "prototypes/ally_portrait_calibration.py",
               "labels": "automatic death bindings ending more than 200 ms before the "
                         "killfeed death (minimap_feature_bank.auto_units); never the "
                         "player's labels",
               "sessions": sorted(bank.sids), "icons": len(bank.rows),
               "art_agents_covered": int(sum(np.isfinite(refs[ap.FAMILIES[0]][:, 0]))),
               "margin_rule": "5th percentile of the four-candidate top-two margin over "
                              "automatic icons whose best candidate is the bound agent",
               "auto_top1": right / max(n, 1)}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ap.CALIBRATION_FILE).write_text(json.dumps(cal, indent=1), encoding="utf-8")
    print({k: cal[k] for k in ("q", "sigma", "dy", "err", "margin_min")},
          "auto top1", round(right / n, 4), n)
    return cal


def run_scale() -> dict:
    bank = fb.Bank()
    art = fb.load_art()
    w = widths()
    out = {}
    for size in (331, 465):
        sids = [s for s in bank.sids if w.get(s) == size]
        p = fb.fit_renderer(bank, art, sids)
        out[size] = {"sessions": len(sids), "q": p["q"], "sigma": p["sigma"],
                     "dy": p["dy"], "err": round(p["err"], 2)}
    print(out)
    return out


def main() -> None:
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("step", choices=("fit", "scale"))
    step = ap_.parse_args().step
    {"fit": run_fit, "scale": run_scale}[step]()


if __name__ == "__main__":
    main()
