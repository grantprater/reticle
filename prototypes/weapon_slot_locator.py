r"""Where `killfeed` puts the weapon-slot box, read from the ROI crop cache.

    .\.venv\Scripts\python.exe prototypes\weapon_slot_locator.py probe SESSION T_MS
    .\.venv\Scripts\python.exe prototypes\weapon_slot_locator.py eval [--sheet]

`probe` prints every bright component `killfeed._band_text` weighs in each
entry's band at one frame, and which it took. `eval` reruns the killfeed
reader from the cache over each player-labelled entry's life
(`labels/killfeed_icon/`), binds the entry as `adjudication.weapon` does, and
scores the box: on a labelled icon the box must stay on the player's ring
(control); on a `bad_crop` it must leave the ring the player rejected and
land between the two names. Decodes nothing. Predictions are `weapon-slot-
locator` in the store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.adjudication.death import session_entries  # noqa: E402
from reticle.adjudication.weapon import (ENTRY_BOX_TOL, bind_entry, entry_weapon,  # noqa: E402
                                         load_mined_gallery)
from reticle.killfeed import KillfeedPortraitReader  # noqa: E402
from reticle.passes import SessionContext  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

VERSION = "weapon-slot-locator-proto-0.1.0"
OUT = Store().root / "analysis" / "weapon_slot_locator"


def _session(sid: str):
    store = Store()
    man = store.read_manifest(sid)
    profile = get_profile(man["source_profile"])
    cache, why = RoiCache.load(store.root, man, profile, "killfeed")
    if cache is None:
        raise SystemExit(f"{sid}: no killfeed crop cache ({why})")
    ctx = SessionContext(store=store, manifest=man, profile=profile)
    return store, man, profile, cache, ctx


def labels() -> dict[str, dict]:
    last = {}
    for p in sorted((Store().root / "labels" / "killfeed_icon").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                last[r["key"]] = r
    return {k: r for k, r in last.items() if not r.get("uncertain")}


def rerun(sid: str, windows: list[tuple[float, float]]) -> tuple[list[dict], dict]:
    """The killfeed reader's weapon rows over the cached frames in `windows`."""
    store, man, profile, cache, ctx = _session(sid)
    reader = KillfeedPortraitReader(profile, ctx.wh, mask=ctx.kf_mask(), hz=2.0)
    want = sorted({float(t) for t in cache.t_ms if any(a <= t <= b for a, b in windows)})
    for smp in cache.samples(want, rois="killfeed"):
        reader.feed(smp)
    rows = [dict(r, kind="weapon_icon_observation") for r in reader.weapons]
    return rows, man


def _on_ring(o: dict, ring) -> bool:
    return abs(o["wx0"] - ring[0]) <= ENTRY_BOX_TOL and abs(o["wx1"] - ring[2]) <= ENTRY_BOX_TOL


def evaluate(write_sheet: bool = False) -> dict:
    labs = labels()
    by = defaultdict(list)
    for lab in labs.values():
        by[lab["session_id"]].append(lab)
    gallery = load_mined_gallery()
    store = Store()
    res, rows = Counter(), []
    for sid, ls in sorted(by.items()):
        try:
            _session(sid)
        except SystemExit as e:
            res["no_cache"] += len(ls)
            print(e)
            continue
        man = store.read_manifest(sid)
        import glob
        import pyarrow.parquet as pq
        hud = pq.read_table(glob.glob(str(store.root / "l1" / "hud" / "*" / f"session={sid}"
                                          / "hud.parquet"))[0]).to_pydict()
        ents = {(int(e["t_first"]), e["slot"]): e for e in session_entries(hud)}
        pick = {}
        for lab in ls:
            _, _, t, slot = lab["key"].split(":")
            e = ents.get((int(t), int(slot)))
            if e is not None:
                pick[lab["key"]] = e
        new, _ = rerun(sid, [(e["t_first"], e["t_last"]) for e in pick.values()])
        old = store.read_events("killfeed_weapon", sid)
        for lab in ls:
            e = pick.get(lab["key"])
            if e is None:
                res["no_entry"] += 1
                continue
            bound_old, bound_new = bind_entry(e, old), bind_entry(e, new)
            ring = lab["ring"]
            kind = "bad_crop" if lab["class"] == "bad_crop" else "control"
            on_old = sum(_on_ring(o, ring) for o in bound_old)
            on_new = sum(_on_ring(o, ring) for o in bound_new)
            named = entry_weapon(e, new, gallery=gallery)
            # The frame the player judged: the entry's row there, old and new.
            at = lambda rows: next((o for o in rows if o["t_ms"] == lab["t_ms"]), None)
            o_at, n_at = at(bound_old), at(bound_new)
            row = {"key": lab["key"], "kind": kind, "answer": lab.get("answer"),
                   "old_frames": len(bound_old), "new_frames": len(bound_new),
                   "old_on_ring": on_old, "new_on_ring": on_new,
                   "new_boxes": sorted({(o["wx0"], o["wx1"]) for o in bound_new})[:4],
                   "named": named.get("name") or named.get("category"),
                   "status": named["status"], "reason": named.get("reason"),
                   "t_ms": lab["t_ms"], "slot": lab["slot"], "ring": ring,
                   "old_at": o_at and [o_at["wx0"], o_at["wx1"]],
                   "new_at": n_at and [n_at["wx0"], n_at["wx1"]]}
            rows.append(row)
            if o_at is not None and _on_ring(o_at, ring):
                res[f"{kind}_label_frame_on_ring_old"] += 1
                res[f"{kind}_label_frame_on_ring_new"] += int(n_at is not None and _on_ring(n_at, ring))
                res[f"{kind}_label_frame_lost"] += int(n_at is None)
            if kind == "control":
                res["control"] += 1
                res["control_kept_ring"] += int(on_new >= max(1, on_old))
                res["control_named_right"] += int(row["named"] == lab["answer"])
            else:
                res["bad_crop"] += 1
                res["bad_left_ring"] += int(bool(bound_new) and on_new == 0)
                res["bad_named"] += int(named["status"] == "resolved")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "eval.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows),
                                    encoding="utf-8")
    if write_sheet:
        sheet(rows)
    return dict(res)


def sheet(rows: list[dict]) -> None:
    """Each bad_crop entry's band at its labelled frame, the rejected ring in
    yellow and the new box in green, from the cache."""
    tiles = []
    for r in rows:
        if r["kind"] != "bad_crop":
            continue
        sid = r["key"].split(":")[1]
        store, man, profile, cache, ctx = _session(sid)
        (smp,) = list(cache.samples([float(r["t_ms"])], rois="killfeed")) or [None]
        if smp is None:
            continue
        x0, y0, x1, y1 = cache.rect_of("killfeed")
        roi = smp.frame[y0:y1, x0:x1].copy()
        reader = KillfeedPortraitReader(profile, ctx.wh, mask=ctx.kf_mask(), hz=2.0)
        reader.feed(smp)
        for o in reader.weapons:
            cv2.rectangle(roi, (o["wx0"], o["y0"]), (o["wx1"], o["y1"]), (0, 255, 0), 1)
        tiles.append((r["key"], roi))
    for k in range(0, len(tiles), 8):
        imgs = []
        for key, t in tiles[k:k + 8]:
            t = t.copy()
            cv2.putText(t, key[6:], (4, t.shape[0] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (0, 255, 255), 1)
            imgs.append(t)
        cv2.imwrite(str(OUT / f"bad_{k // 8}.png"), np.vstack(imgs))


def probe(sid: str, t_ms: float) -> None:
    from reticle import killfeed as K
    store, man, profile, cache, ctx = _session(sid)
    (smp,) = list(cache.samples([t_ms], rois="killfeed"))
    seen = []
    orig = K._band_text

    def spy(white, usable=None, plates=None, value=None):
        wb = white.astype(np.uint8)
        n, _, st, _ = cv2.connectedComponentsWithStats(wb, 8)
        out = orig(white, usable, plates, value)
        seen.append((st[1:], out if isinstance(out, str) else out[1:]))
        return out

    K._band_text = spy
    try:
        views = K.analyse_killfeed(smp.frame, K.killfeed_roi(profile), *ctx.wh, ctx.kf_mask(),
                                   profile.name)
    finally:
        K._band_text = orig
    for st, got in seen:
        print("band ->", got)
        for x, y, w, h, a in st:
            if a >= K.MIN_COMP_AREA:
                print(f"   x {x:4d}-{x + w:4d} y {y:2d}-{y + h:2d} area {a:5d}")
    for v in views:
        print("view", v.slot, v.y0, v.y1, v.wx0, v.wx1, v.verdict)


def regress(sids: list[str]) -> dict:
    """Every cached session's occupied frames rerun from the cache against the
    stored weapon rows: boxes moved and kill/death verdicts changed."""
    import glob
    import pyarrow.parquet as pq
    from reticle.trial import targets
    store = Store()
    tot, per = Counter(), {}
    for sid in sids:
        try:
            _, man, profile, cache, ctx = _session(sid)
        except SystemExit:
            continue
        hud = pq.read_table(glob.glob(str(store.root / "l1" / "hud" / "*" / f"session={sid}"
                                          / "hud.parquet"))[0]).to_pydict()
        want = targets(hud, "occupied", 2000.0)
        reader = KillfeedPortraitReader(profile, ctx.wh, mask=ctx.kf_mask(), hz=2.0)
        for smp in cache.samples(want, rois="killfeed"):
            reader.feed(smp)
        new = {(r["t_ms"], r["slot"]): r for r in reader.weapons}
        old = {(r["t_ms"], r["slot"]): r for r in store.read_events("killfeed_weapon", sid)
               if r.get("kind") == "weapon_icon_observation"}
        c = Counter(rows_old=len(old), rows_new=len(new))
        for k in set(old) | set(new):
            a, b = old.get(k), new.get(k)
            if a is None or b is None:
                c["row_added" if a is None else "row_lost"] += 1
                continue
            c["box_moved"] += (a["wx0"], a["wx1"]) != (b["wx0"], b["wx1"])
            if a["verdict"] != b["verdict"]:
                c[f"verdict_{a['verdict']}_to_{b['verdict']}"] += 1
        per[sid] = dict(c)
        tot.update(c)
        print(sid, dict(c))
    return {"total": dict(tot), "sessions": per}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe")
    p.add_argument("session")
    p.add_argument("t_ms", type=float)
    e = sub.add_parser("eval")
    e.add_argument("--sheet", action="store_true")
    r = sub.add_parser("regress")
    r.add_argument("sessions", nargs="*")
    for q in (e, r):
        q.add_argument("--baseline", action="store_true",
                       help="disable the line-art gate (ICON_V_MED_MIN = 0)")
    args = ap.parse_args()
    if getattr(args, "baseline", False):
        import reticle.killfeed as K
        K.ICON_V_MED_MIN = 0
    if args.cmd == "probe":
        probe(args.session, args.t_ms)
    elif args.cmd == "regress":
        import glob
        sids = args.sessions or sorted(Path(p).stem for p in glob.glob(str(
            Store().root / "roi_cache" / "killfeed" / "*" / "*.json")))
        print(json.dumps(regress(sids)["total"], indent=1))
    else:
        print(json.dumps(evaluate(args.sheet), indent=1))


if __name__ == "__main__":
    main()
