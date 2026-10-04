r"""The game's kill icons against the mined gallery, scored on the player's labels.

    .\.venv\Scripts\python.exe prototypes\game_killicons.py [--json OUT] [--record]
    .\.venv\Scripts\python.exe prototypes\game_killicons.py --inventory OUT

Every exemplar of the mined gallery (`weapon-gallery-0.6.0`) is a stored
`killfeed_weapon` grid the player named. Each is named by
`adjudication.weapon._name_icon` (NAME_MIN_IOU, NAME_MARGIN, NAME_ASPECT_TOL)
against four galleries:

* `mined`: the mined exemplars of the other sessions (leave one session out);
* `game`: the game's kill icons (`load_game_icons`), mirrored as drawn;
* `game_one_phase`: one placement per icon instead of GAME_ICON_PHASES;
* `game_soft`: the drawn alpha kept soft in the grid, not cut as the reader cuts;
* `game_unmirrored`: the same textures without the mirror;
* `union`: `mined` plus `game`, what `load_gallery` served at weapon-gallery-0.7.0;
* `served`: `game` plus the mined exemplars of `MINED_ONLY_NAMES` of the
  other sessions, what `load_gallery` serves since weapon-gallery-0.8.0;
* `served_loio`: `served` without the exemplar's own name, the
  leave-one-icon-out harness of `prototypes/weapon_null_eval.py` (branch
  `whitened-weapon-null-20261004`, a test harness only) under the
  owner's IoU rule: a name given is an unseen icon misnamed. With the closed
  set complete, production meets this case only for an icon the build's
  DamageTypes do not list.

The game icons never saw a capture, so every exemplar is held out from them.
A label the game set lacks (Not Dead Yet, Resurrection, NULL/cmd; Blade
Storm until weapon-gallery-0.8.0 added its dagger) is right only when
refused: a name there would be wrong. The
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

VERSION = "game-killicons-eval-0.2.0"
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


def inventory(store_root=None) -> list[dict]:
    """Every DamageType of the build and the kill icon it draws: the packages
    under ShooterGame/ outside Console/ whose file name holds `dmgtype` or
    `damagetype` in any case (index.tsv.gz; Dmgtype_GoldenGun_SpikeRush has a
    lower-case t), each read from the `damage-types` export: its parent
    class, its KillIcon, own or inherited through the parents, the exported
    file that holds it (a `dedup` row points at the first file with the same
    bytes) and the gallery name drawing it, or why the gallery leaves it out."""
    import gzip
    import re
    from reticle.adjudication.weapon import (GAME_KILL_ICONS, GAME_KILL_ICONS_EXCLUDED,
                                             game_build_dir)
    d = game_build_dir(store_root)
    c = "ShooterGame/Content/"
    dts = []
    with gzip.open(d / "index.tsv.gz", "rt", encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            p = line.split("\t")[0]
            if (p.startswith("ShooterGame/") and "/Console/" not in p and p.endswith(".uasset")
                    and re.search(r"dmgtype|damagetype", p.rsplit("/", 1)[-1], re.I)):
                dts.append(p[len(c):-len(".uasset")])
    parent, icon = {}, {}
    for k in dts:
        for o in json.loads((d / "damage-types" / c / f"{k}.json").read_text(encoding="utf-8")):
            if o.get("Type") == "BlueprintGeneratedClass" and o.get("Super"):
                parent[k] = o["Super"]["ObjectPath"].replace("/Game/", "").rsplit(".", 1)[0]
            if "KillIcon" in (o.get("Properties") or {}):
                t = (o["Properties"]["KillIcon"].get("Texture") or {}).get("ObjectPath")
                icon[k] = t.replace("/Game/", "").rsplit(".", 1)[0] if t else None
    files = {}
    for export in ("killfeed-icons", "damage-type-icons", "minimap"):
        for line in (d / export / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("output"):
                files.setdefault(r["game_path"][len(c):-len(".uasset")].lower(),
                                 (r["output"].replace("\\", "/"), r.get("status")))
    by_file = {rel.lower(): n for n, (rel, _cat) in GAME_KILL_ICONS.items()}
    out_of = {v["texture"].lower(): n for n, v in GAME_KILL_ICONS_EXCLUDED.items()}
    rows = []
    for k in sorted(dts):
        cur = k
        while cur is not None and cur not in icon:
            cur = parent.get(cur)
        tex = icon.get(cur) if cur else None
        f, status = files.get(tex.lower(), (None, None)) if tex else (None, None)
        rows.append({"damage_type": k, "parent": parent.get(k), "kill_icon": tex,
                     "how": ("own" if cur == k else f"inherited from {cur}") if tex else "none",
                     "file": f, "export_status": status,
                     "gallery": by_file.get((f or "").lower()),
                     "excluded": out_of.get((f or "").lower())})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", type=Path)
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--inventory", type=Path,
                    help="write the DamageType inventory (`inventory`) to this JSON and stop")
    args = ap.parse_args(argv)
    if args.inventory:
        rows = inventory()
        drawn = [r for r in rows if r["kill_icon"]]
        print(f"DamageTypes {len(rows)}; with a KillIcon {len(drawn)} "
              f"({sum(r['how'] == 'own' for r in drawn)} own); textures "
              f"{len({r['kill_icon'] for r in drawn})}; in the gallery "
              f"{sum(bool(r['gallery']) for r in drawn)}; excluded "
              f"{sum(bool(r['excluded']) for r in drawn)}; neither "
              f"{[r['damage_type'] for r in drawn if not (r['gallery'] or r['excluded'])]}")
        args.inventory.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        return 0
    from reticle.adjudication.weapon import (WEAPON_GALLERY_VERSION, _icon_index, _name_icon,
                                             load_game_icons, MINED_ONLY_NAMES,
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
           for k in ("mined", "game", "game_one_phase", "game_soft", "game_unmirrored", "union",
                     "served", "served_loio")}
    wrong = defaultdict(list)
    for sid in sorted(set(sids)):
        rest = _sub(mined, sids != sid)
        mi = _icon_index(rest)
        ui = _icon_index(_cat(rest, game))
        only = _sub(rest, np.isin(rest["names"].astype(str), sorted(MINED_ONLY_NAMES)))
        si = _icon_index(_cat(only, game))
        mknown = {str(n) for n in rest["names"]}
        sknown = {str(n) for n in only["names"]} | gnames
        served = _cat(only, game)
        loio = {}
        for k in np.nonzero(sids == sid)[0]:
            q, a, t = mined["masks"][k], float(mined["aspects"][k]), names[k]
            for label, idx, known in (("mined", mi, mknown), ("game", gi, gnames),
                                      ("game_one_phase", g1, gnames),
                                      ("game_soft", gs, gnames),
                                      ("game_unmirrored", gu, gnames),
                                      ("union", ui, mknown | gnames),
                                      ("served", si, sknown)):
                v = _name_icon(q, a, idx)
                o = outcome(t, v, known)
                res[label][t][o] += 1
                if o == "wrong":
                    wrong[label].append((str(mined["keys"][k]), t, v["name"], v["score"],
                                        v["margin"]))
            # Leave one icon out: the served gallery without the label's name
            # (and the game name it maps to); a name given is an unseen icon
            # misnamed.
            drop = {t, SAME_AS.get(t, t)}
            if t not in loio:
                loio[t] = _icon_index(_sub(served, ~np.isin(served["names"].astype(str),
                                                            sorted(drop))))
            v = _name_icon(q, a, loio[t])
            o = "misnamed" if v["name"] is not None else f"refused_{v['reason']}"
            res["served_loio"][t][o] += 1
            if o == "misnamed":
                wrong["served_loio"].append((str(mined["keys"][k]), t, v["name"], v["score"],
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
    print("per name (mined | game | union | served):")
    for n in sorted(set(names)):
        print(f"  {n:16s} {dict(res['mined'][n])} | {dict(res['game'][n])} | "
              f"{dict(res['union'][n])} | {dict(res['served'][n])}")
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
