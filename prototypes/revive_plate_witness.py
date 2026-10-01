r"""Whether the killer's plate colour marks a revive entry.

    .\.venv\Scripts\python.exe prototypes\revive_plate_witness.py
    .\.venv\Scripts\python.exe prototypes\revive_plate_witness.py self [session]

Question. A revive banner is one colour end to end, its chevron dividing a
darker from a lighter shade of the reviving team's colour
[domain:killfeed/revive-entries]. A kill's plates differ. The weapon slot's
icon is the only revive witness `adjudication.death` has, and on bdfdcf009dba
at 1310.0 s it went unnamed on all six views, so a Sage revive was stored as an
ally Clove death with no killer. Is the killer's plate colour, read behind the
icon as `killfeed.victim_is_ally` already reads it, a second witness?

Method. For every entry in the player's `killfeed_icon` labels, run the
unchanged `killfeed.analyse_killfeed` on the `hud` roi-cache frames from the
entry's first sighting to 2.5 s later, keep the views in the labelled slot,
and read the killer's colour behind `wx0..wx1` with `victim_is_ally`'s
`ICON_PLATE_RATIO` rule. An entry reads same-side when most of its decided
views put killer and victim on one side. No decode; nothing is written.

Predictions and outcome: task `revive-plate-witness` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from reticle import killfeed as kfm  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

STORE = Path(r"C:\Users\grant\reticle-store")
REVIVES = ("Resurrection", "Not Dead Yet")
SPAN_MS = 2500.0


#: The killer's side from the plate behind the icon; measured here, now the reader's.
killer_ally = kfm.killer_is_ally


#: An entry keeps its icon column as the stack rises; another entry's icon
#: sits elsewhere, because the killer's name sets it.
FOLLOW_WX_PX = 4


def frame_views(frame, roi, w, h, mask, profile_name):
    """(view, killer_ally) for every view in one frame."""
    x0, y0, x1, y1 = roi.pixels(w, h)
    green, red, _white = kfm._plate_masks(frame[y0:y1, x0:x1],
                                          mask if mask is not None
                                          else np.ones((y1 - y0, x1 - x0), bool))
    return [(v, killer_ally(green, red, v.y0, v.y1, v.wx0, v.wx1) if v.wx1 > v.wx0 else None)
            for v in kfm.analyse_killfeed(frame, roi, w, h, mask, profile_name)]


def follow(frames, slot):
    """(victim_ally, killer_ally, reason) per frame for the entry first seen in
    `slot`. The stack only rises, so a later view sits in the same slot or a
    higher one (lower index) at the anchor's icon column."""
    out, anchor = [], None
    for views in frames:
        if anchor is None:
            got = [(v, ka) for v, ka in views if v.slot == slot]
        else:
            got = [(v, ka) for v, ka in views
                   if v.slot <= anchor[0] and v.wx1 > v.wx0
                   and abs(v.wx0 - anchor[1]) <= FOLLOW_WX_PX]
        if not got:
            continue
        v, ka = got[0]
        if v.verdict in ("empty_band", "unparsed", "occluded"):
            out.append((None, None, v.reason or v.verdict))
            continue
        anchor = (v.slot, v.wx0)
        out.append((v.victim_ally, ka, ""))
    return out


def main() -> int:
    store = Store(STORE)
    labels = {}
    for f in glob.glob(str(STORE / "labels" / "killfeed_icon" / "*.jsonl")):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            labels.setdefault(r["session_id"], []).append(r)
    tally = Counter()
    rows = []
    for sid, labs in sorted(labels.items()):
        man = json.loads((STORE / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
        profile = get_profile(man["source_profile"])
        cache, why = RoiCache.load(STORE, man, profile, "hud")
        if cache is None:
            print(f"{sid}: no hud cache ({why})")
            continue
        roi = kfm.killfeed_roi(profile)
        w, h = man["source"]["width"], man["source"]["height"]
        mask = store.read_kf_mask(sid)
        t_all = np.unique(np.asarray(cache.t_ms, float))
        for lab in labs:
            t0 = float(lab.get("t_first") or lab["t_ms"])
            ts = t_all[(t_all >= t0) & (t_all <= t0 + SPAN_MS)]
            frames = [frame_views(smp.frame, roi, w, h, mask, profile.name)
                      for smp in cache.samples(list(ts), rois=["killfeed"])]
            views = follow(frames, int(lab["slot"]))
            decided = [(va, ka) for va, ka, _ in views if va is not None and ka is not None]
            same = sum(1 for va, ka in decided if va == ka)
            verdict = ("same" if decided and 2 * same > len(decided)
                       else "differ" if decided else "undecided")
            # A `bad_crop` label names nothing, so it is neither witness nor foil.
            kind = ("revive" if lab.get("answer") in REVIVES
                    else "unnamed" if lab.get("answer") is None else "named")
            tally[(kind, verdict)] += 1
            rows.append({"sid": sid, "t": t0 / 1000, "slot": lab["slot"], "answer": lab.get("answer"),
                         "kind": kind, "verdict": verdict, "same": same, "decided": len(decided),
                         "views": len(views),
                         "reasons": dict(Counter(r for _, _, r in views if r))})
    for r in rows:
        if r["kind"] == "revive" and r["verdict"] != "same" or r["kind"] == "named" and r["verdict"] == "same":
            print(r)
    print()
    for k in sorted(tally):
        print(k, tally[k])
    return 0


def plates_typed_revive(v: dict) -> bool:
    """Whether the plates typed a death row's entry a revive.

    Rows before death-adjudication-0.25.0 say so as `revive_witness ==
    "plates"`: the icon went unnamed, the victim's side fielded a reviver and
    two names printed. From 0.25.0 the row carries `entry_type`
    (`adjudication.death.decide_entry_type`); the plates type a revive under
    its rule 3, with the icon and the ring both silent. No exact equivalent:
    the ring, absent before, now speaks on some entries the plates alone
    typed, and the context gate replaces the fielded-reviver check."""
    et = v.get("entry_type")
    if et is None:
        return v.get("revive_witness") == "plates"
    return et.get("type") == "revive" and et.get("rule") == 3


def self_entries(only: str | None = None) -> int:
    """Whether a same-side entry's killer and victim print one name.

    A self entry (a Clove revive's expiry, a spike death, a self-kill) is one
    colour end to end too: 59c70f1ef720 1849.5 s, an expiry, read as a plate
    revive at death-adjudication-0.14.0. Population: every stored verdict that
    reads same-side, and every icon-named revive. Each role is cut as the
    name clusters cut it (`followed_views` over the verdict's portrait
    witnesses, `role_crops`), and `ncc >= NCC_MIN` is one name."""
    from reticle.adjudication.killfeed_names import NCC_MIN, followed_views, ncc, role_crops
    store = Store(STORE)
    tally, rows = Counter(), []
    for p in sorted((STORE / "events" / "death").glob(f"{only or '*'}.jsonl")):
        sid = p.stem
        names = store.read_events("killfeed_name", sid)
        for line in p.read_text(encoding="utf-8").splitlines():
            v = json.loads(line)
            if v.get("kind") != "death_verdict":
                continue
            icon = (v.get("weapon_evidence") or {}).get("name")
            if not (v.get("same_side") or icon in REVIVES):
                continue
            obs = [o for w in v.get("witnesses") or [] if w.get("channel") == "killfeed_portrait"
                   for o in (w.get("evidence") or {}).get("observations") or []]
            views = followed_views(obs)
            crops = role_crops([{"entity_id": r, "role": r, "team": v["side"], "views": views}
                                for r in ("killer", "victim")], names, sid)
            k, g = crops["killer"]["gray"], crops["victim"]["gray"]
            score = None if k is None or g is None else ncc(k, g)
            read = ("unread" if score is None else "one" if score >= NCC_MIN else "two")
            kind = icon if icon in REVIVES or icon == "Environmental" else (
                "plates" if plates_typed_revive(v) else f"same_side:{icon}")
            tally[(kind, read)] += 1
            rows.append((sid, v["t_ms"] / 1000, kind, read, None if score is None else round(score, 3),
                         crops["killer"]["reason"], crops["victim"]["reason"]))
    for r in rows:
        if r[2] not in REVIVES or (r[2] == "Resurrection") == (r[3] == "one"):
            print(r)
    print()
    for k in sorted(tally):
        print(k, tally[k])
    return 0


if __name__ == "__main__":
    raise SystemExit(self_entries(*sys.argv[2:3]) if sys.argv[1:2] == ["self"] else main())
