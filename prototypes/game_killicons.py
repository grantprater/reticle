r"""The game's kill icons against the mined gallery, scored on the player's labels.

    .\.venv\Scripts\python.exe prototypes\game_killicons.py [--json OUT] [--record]

Every exemplar of the mined gallery (`weapon-gallery-0.6.0`) is a stored
`killfeed_weapon` grid the player named. Each is named by
`adjudication.weapon._name_icon` (NAME_MIN_IOU, NAME_MARGIN, NAME_ASPECT_TOL)
against four galleries:

* `mined`: the mined exemplars of the other sessions (leave one session out);
* `game`: the game's kill icons (`load_game_icons`), mirrored as drawn;
* `game_one_phase`: one placement per icon instead of GAME_ICON_PHASES;
* `game_soft`: the drawn alpha kept soft in the grid, not cut as the reader cuts;
* `game_unmirrored`: the same textures without the mirror;
* `union`: `mined` plus `game`, what `load_gallery` serves.

The game icons never saw a capture, so every exemplar is held out from them.
A label the game set lacks (Blade Storm, Not Dead Yet, Resurrection,
NULL/cmd) is right only when refused: a name there would be wrong. The
player named the spike hexagon `Environmental`
[domain:killfeed/environmental-self-entry]; `Spike` counts as that name.

Wire: no. It scores the owner's gallery; the owner reads the game icons.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

VERSION = "game-killicons-eval-0.1.0"
#: Labels whose name differs from the game set's for one icon.
SAME_AS = {"Environmental": "Spike"}


def _session(key: str) -> str:
    return key.split(":")[1]


def _sub(g: dict, keep: np.ndarray) -> dict:
    return {k: (v[keep] if isinstance(v, np.ndarray) and v.ndim and len(v) == len(keep) else v)
            for k, v in g.items()}


def _cat(a: dict, b: dict) -> dict:
    return {k: np.concatenate([a[k].astype(np.float32) if k == "masks" else a[k],
                               b[k].astype(np.float32) if k == "masks" else b[k]])
            for k in ("names", "masks", "aspects")}


def outcome(truth: str, v: dict, known: set) -> str:
    """right / wrong / refused_new / refused_ambiguous, against `known` names."""
    want = SAME_AS.get(truth, truth) if SAME_AS.get(truth) in known else truth
    if v["name"] is None:
        return "right_refused" if want not in known else f"refused_{v['reason']}"
    return "right" if v["name"] in (want, truth) else "wrong"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", type=Path)
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    from reticle.adjudication.weapon import (WEAPON_GALLERY_VERSION, _icon_index, _name_icon,
                                             load_game_icons, load_mined_gallery,
                                             MINED_GALLERY_VERSION, mined_gallery_path)
    mined = dict(np.load(mined_gallery_path()))
    game, why = load_game_icons()
    if game is None:
        raise SystemExit(f"game icons refused: {why}")
    names = [str(n) for n in mined["names"]]
    sids = np.array([_session(str(k)) for k in mined["keys"]])
    gnames = {str(n) for n in game["names"]}
    gi = _icon_index(game)
    gu = _icon_index(load_game_icons(mirror=False)[0])
    gs = _icon_index(load_game_icons(soft=True)[0])
    g1 = _icon_index(load_game_icons(phases=((0.0, 0.0),))[0])
    res = {k: defaultdict(Counter)
           for k in ("mined", "game", "game_one_phase", "game_soft", "game_unmirrored", "union")}
    wrong = defaultdict(list)
    for sid in sorted(set(sids)):
        rest = _sub(mined, sids != sid)
        mi = _icon_index(rest)
        ui = _icon_index(_cat(rest, game))
        mknown = {str(n) for n in rest["names"]}
        for k in np.nonzero(sids == sid)[0]:
            q, a, t = mined["masks"][k], float(mined["aspects"][k]), names[k]
            for label, idx, known in (("mined", mi, mknown), ("game", gi, gnames),
                                      ("game_one_phase", g1, gnames),
                                      ("game_soft", gs, gnames),
                                      ("game_unmirrored", gu, gnames),
                                      ("union", ui, mknown | gnames)):
                v = _name_icon(q, a, idx)
                o = outcome(t, v, known)
                res[label][t][o] += 1
                if o == "wrong":
                    wrong[label].append((str(mined["keys"][k]), t, v["name"], v["score"],
                                         v["margin"]))
    totals = {lab: dict(sum(per.values(), Counter())) for lab, per in res.items()}
    shared = sorted(n for n in set(names) if SAME_AS.get(n, n) in gnames)
    shared_tot = {lab: dict(sum((per[n] for n in shared), Counter())) for lab, per in res.items()}
    out = {"version": VERSION, "mined": MINED_GALLERY_VERSION, "gallery": WEAPON_GALLERY_VERSION,
           "game": game["provenance"]["build"], "exemplars": len(names),
           "totals": totals, "shared_names": shared, "shared_totals": shared_tot,
           "by_name": {lab: {n: dict(c) for n, c in sorted(per.items())}
                       for lab, per in res.items()},
           "wrong": {k: v for k, v in wrong.items()}}
    for lab in res:
        print(f"{lab:16s} all {totals[lab]}")
        print(f"{'':16s} shared {shared_tot[lab]}")
    print("per name (mined | game | union):")
    for n in sorted(set(names)):
        print(f"  {n:16s} {dict(res['mined'][n])} | {dict(res['game'][n])} | {dict(res['union'][n])}")
    for lab, rows in wrong.items():
        print(f"wrong {lab}: {len(rows)}")
        for r in rows[:40]:
            print("   ", r)
    if args.json:
        args.json.write_text(json.dumps(out, indent=1), encoding="utf-8")
    if args.record:
        from reticle import metrics
        from reticle.adjudication.weapon import WEAPON_ADJUDICATION_VERSION
        for lab in res:
            vals = {k: int(v) for k, v in shared_tot[lab].items()}
            vals["n"] = int(sum(shared_tot[lab].values()))
            vals.update({f"all_{k}": int(v) for k, v in totals[lab].items()})
            vals["all_n"] = int(sum(totals[lab].values()))
            metrics.record("game_killicons", part=lab, session=WEAPON_GALLERY_VERSION,
                           values=vals,
                           deps={"version": VERSION, "mined": MINED_GALLERY_VERSION,
                                 "game": game["provenance"]["build"],
                                 "owner": WEAPON_ADJUDICATION_VERSION},
                           context={"wrong": wrong.get(lab, [])[:40]},
                           note="labelled exemplars of the mined gallery; mined and union "
                                "leave the exemplar's session out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
