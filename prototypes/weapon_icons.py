r"""Weapon identity from mined killfeed icons, named by the player's ammo pair.

    .\.venv\Scripts\python.exe prototypes\weapon_icons.py mine <session|all>
    .\.venv\Scripts\python.exe prototypes\weapon_icons.py cluster
    .\.venv\Scripts\python.exe prototypes\weapon_icons.py sheet [--cluster N]

`mine` crops the divider icon of every counted killfeed track from one frame
0.5-1.5 s after first sight, with the white mask `adjudication.weapon` owns,
and labels the player's own kills with the full-load ammo pair read before
them [domain:weapons/magazine-and-reserve]. `cluster` groups the icons with no
labels and scores each group against those ammo labels; `sheet` renders the
groups for an eye. An ability kill puts the ability's icon in the same slot
[domain:killfeed/ability-kill-icon], so ability icons group here too. Nothing is named by hand: the ammo pair names a group,
three shared pairs stay ties, and a disagreement is stored, not voted away.

Predictions are logged in the store's `notes/predictions.jsonl` under
`weapon-icons`.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import glob
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle.adjudication.weapon import extract_icon_observation  # noqa: E402
from reticle.checks import KF_SIG_TOL, merge_split_tracks, track_entries  # noqa: E402
from reticle.decode import sample_at  # noqa: E402
from reticle.killfeed import analyse_killfeed, killfeed_roi  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import Store  # noqa: E402

VERSION = "weapon-icons-proto-0.1.0"
OUT = Store().root / "analysis" / "weapon_icons"
OFFSETS_MS = (500.0, 1000.0, 1500.0)     # after first sight: the entry is settled
MIN_TIGHT_W = 12                         # narrower than any gun or ability icon
GRID = (16, 64)                          # h, w of a height-normalised icon
CROP = (40, 160)                         # stored raw crop canvas, larger than any band
AMMO_BEFORE_MS = 3000.0                  # the kill's read must be this recent
LABEL_LOOKBACK_MS = 90000.0              # longer than any round's live phase

# [domain:weapons/magazine-and-reserve], read into a table; the domain file is
# the source and this dict is checked against its claim text in `_check_table`.
FULL_LOAD = {
    "Classic": (12, 36), "Shorty": (2, 6), "Frenzy": (15, 45), "Ghost": (13, 39),
    "Bandit": (8, 24), "Sheriff": (6, 24), "Stinger": (20, 60), "Spectre": (30, 90),
    "Bucky": (5, 10), "Judge": (5, 15), "Bulldog": (24, 72), "Guardian": (12, 36),
    "Phantom": (30, 60), "Vandal": (25, 50), "Marshal": (5, 15), "Outlaw": (2, 10),
    "Operator": (5, 10), "Ares": (50, 100), "Odin": (100, 200),
}
BY_PAIR: dict[tuple[int, int], tuple[str, ...]] = defaultdict(tuple)
for _n, _p in FULL_LOAD.items():
    BY_PAIR[_p] += (_n,)


def _check_table() -> None:
    from reticle import domain
    claim = " ".join(domain.load()["weapons/magazine-and-reserve"].claim.split())
    for n, (m, r) in FULL_LOAD.items():
        if f"{n} {m} | {r}" not in claim:
            raise SystemExit(f"FULL_LOAD drifted from the domain table at {n}")


def hud_sessions() -> list[str]:
    root = Store().root / "l1" / "hud"
    return sorted({p.split("session=")[1].split(os.sep)[0]
                   for p in glob.glob(str(root / "*" / "session=*" / "hud.parquet"))})


def _hud(sid: str) -> dict[str, list]:
    import pyarrow.parquet as pq
    path = glob.glob(str(Store().root / "l1" / "hud" / "*" / f"session={sid}" / "hud.parquet"))[0]
    return pq.read_table(path).to_pydict()


def _continuous(a: tuple[int, int], b: tuple[int, int]) -> str | None:
    """How one gun gets from read a to read b, or None when no single gun can."""
    (ma, ra), (mb, rb) = a, b
    if rb == ra and mb <= ma:
        return "fire"
    if mb > ma and mb + rb == ma + ra:
        return "reload"
    return None


def ammo_label(t_kill: float, t: list, mag: list, res: list) -> dict:
    """Every gun the player's ammo reads before a kill are consistent with.

    Reads are chained back from the kill while one gun explains each step --
    firing keeps the reserve, a reload conserves magazine plus reserve. A swap,
    buy or pickup breaks the chain. The chain's first read names guns whose full
    reserve it equals and whose magazine holds every read after it; a reload that
    left reserve pins the magazine capacity exactly
    [domain:weapons/magazine-and-reserve]. A partly fired Bandit and a full
    Sheriff both read 6 | 24, so that label stays both.
    """
    reads = [i for i, ti in enumerate(t) if t_kill - LABEL_LOOKBACK_MS <= ti < t_kill
             and mag[i] is not None and res[i] is not None]
    if not reads or t_kill - t[reads[-1]] > AMMO_BEFORE_MS:
        return {"label": None, "reason": "no_ammo_read"}
    last = reads[-1]
    kill_pair = [mag[last], res[last]]
    start, pin = len(reads) - 1, None
    while start > 0:
        a, b = reads[start - 1], reads[start]
        step = _continuous((mag[a], res[a]), (mag[b], res[b]))
        if step is None:
            break
        if step == "reload" and res[b] > 0 and pin is None:
            pin = mag[b]
        start -= 1
    j = reads[start]
    m_max = max(mag[k] for k in reads[start:])
    guns = [n for n, (m, r) in FULL_LOAD.items()
            if r == res[j] and m >= m_max and (pin is None or m == pin)]
    out = {"pair": [mag[j], res[j]], "full_t_ms": t[j], "kill_pair": kill_pair,
           "chain_s": round((t[last] - t[j]) / 1000.0, 1), "pin": pin}
    if not guns:
        return dict(out, label=None, reason="chain_starts_below_full_reserve")
    return dict(out, label=sorted(guns))


def _same(a: dict, b: dict) -> bool:
    """One entry seen by two walks: overlapping lives in a slot, one divider."""
    return (a["slot"] == b["slot"] and a["t_first"] <= b["t_last"] and b["t_first"] <= a["t_last"]
            and (a.get("sig") is None or b.get("sig") is None
                 or abs(a["sig"] - b["sig"]) <= KF_SIG_TOL))


def icon_bitmap(crop: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """The owner's white mask cut to its tight box, and that box height-normalised."""
    white = extract_icon_observation(crop).white_mask
    ys, xs = np.nonzero(white)
    if len(xs) < 10 or xs.max() - xs.min() + 1 < MIN_TIGHT_W:
        return None
    tight = white[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return tight, cv2.resize(tight.astype(np.uint8), GRID[::-1], interpolation=cv2.INTER_AREA)


def mine(sid: str) -> Path:
    store = Store()
    man = store.read_manifest(sid)
    src = man["source"]
    profile = get_profile(man.get("source_profile", "valorant-16x9"))
    roi = killfeed_roi(profile)
    hud = _hud(sid)
    t = hud["t_ms"]
    kills = merge_split_tracks([tr for tr in track_entries(
        t, hud["kf_kill_mask"], hud["kf_kill_wx"]) if tr.get("counted")])
    others = [tr for tr in track_entries(t, hud["kf_entry_mask"], hud["kf_entry_wx"])
              if tr.get("counted") and not any(_same(tr, k) for k in kills)]
    tracks = ([dict(tr, role="player_kill") for tr in kills]
              + [dict(tr, role="other") for tr in others])
    want: dict[float, list[int]] = defaultdict(list)
    for k, tr in enumerate(tracks):
        for off in OFFSETS_MS:
            want[tr["t_first"] + off].append(k)
    got: dict[int, list] = defaultdict(list)
    for s in sample_at(src["path"], sorted(want), float(src["fps"])):
        h, w = s.frame.shape[:2]
        rx0, ry0, _, _ = roi.pixels(w, h)
        views = None
        for k in want.get(s.t_ms) or want[min(want, key=lambda x: abs(x - s.t_ms))]:
            views = views if views is not None else analyse_killfeed(
                s.frame, roi, w, h, profile_name=profile.name)
            tr = tracks[k]
            v = [v for v in views if v.wx1 > v.wx0 and v.slot <= tr["slot_first"] and (
                v.slot == tr["slot_first"] if tr.get("sig") is None
                else abs(v.wx0 - tr["sig"]) <= KF_SIG_TOL)]
            # Entries with one gun share a divider column, so the column alone
            # can pick a neighbour: the killfeed's own verdict must match the
            # walk that found the track, and the nearest slot wins.
            want_kill = tr["role"] == "player_kill"
            v = sorted((v for v in v if (v.verdict == "kill") == want_kill),
                       key=lambda v: tr["slot_first"] - v.slot)
            if not v:
                continue
            v = v[0]
            crop = s.frame[ry0 + v.y0:ry0 + v.y1, rx0 + v.wx0:rx0 + v.wx1]
            got[k].append((s.t_ms, v, crop))
    rows, crops = [], []
    for k, tr in enumerate(tracks):
        row = {"session_id": sid, "track": k, "slot": tr["slot"], "t_first": tr["t_first"],
               "profile": profile.name, "version": VERSION}
        is_kill = tr["role"] == "player_kill"
        row["role"] = tr["role"]
        best = next(((t_ms, v, crop) for t_ms, v, crop in got.get(k, [])
                     if icon_bitmap(crop) is not None), None)
        if best is None:
            row["icon"] = None
            row["reason"] = "no_sample" if not got.get(k) else "no_tight_icon"
        else:
            t_ms, v, crop = best
            row["icon"] = len(crops)
            row.update(t_ms=t_ms, verdict=v.verdict, band_h=int(v.y1 - v.y0),
                       box_w=int(v.wx1 - v.wx0))
            c = np.zeros((*CROP, 3), np.uint8)
            cc = crop[:CROP[0], :CROP[1]]
            c[:cc.shape[0], :cc.shape[1]] = cc
            crops.append(c)
        if is_kill:
            row["ammo"] = ammo_label(tr["t_first"], t, hud["ammo_mag"], hud["ammo_reserve"])
        rows.append(row)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{sid}.npz"
    np.savez_compressed(out, crops=np.array(crops).reshape(-1, *CROP, 3),
                        rows=json.dumps(rows))
    n_icon = sum(r["icon"] is not None for r in rows)
    nk = [r for r in rows if r["role"] == "player_kill"]
    print(f"{sid}: {len(tracks)} tracks, {n_icon} icons, {len(nk)} player kills, "
          f"{sum(bool(r['ammo'].get('label')) for r in nk)} ammo-labelled; wrote {out}")
    return out


def load_all() -> tuple[list[dict], np.ndarray, np.ndarray]:
    """Every mined crop, with its mask recomputed by the owner's current rule."""
    rows, bms, crops = [], [], []
    for p in sorted(OUT.glob("*.npz")):
        z = np.load(p)
        base = len(crops)
        for c in z["crops"]:
            pad = np.zeros((*CROP, 3), np.uint8)
            pad[:c.shape[0], :c.shape[1]] = c[:CROP[0], :CROP[1]]
            crops.append(pad)
        for r in json.loads(str(z["rows"])):
            if r["icon"] is not None:
                r["icon"] += base
                cut = icon_bitmap(np.ascontiguousarray(
                    crops[r["icon"]][:r["band_h"], :r["box_w"]]))
                if cut is None:
                    r["icon"], r["reason"] = None, "no_tight_icon"
                else:
                    r["tight_h"], r["tight_w"] = cut[0].shape
                    bms.append((r["icon"], cut[1]))
            rows.append(r)
    grid = np.zeros((len(crops), *GRID), np.uint8)
    for i, b in bms:
        grid[i] = b
    return rows, grid, np.array(crops)


SAME_ICON = 0.75                         # IoU on the normalised grid
ASPECT_TOL = 0.12                        # |log| of the tight aspect ratio


def similarity(rows: list[dict], bms: np.ndarray) -> tuple[list[dict], np.ndarray]:
    """IoU between height-normalised icons, zero where the aspect ratios differ."""
    have = [r for r in rows if r["icon"] is not None]
    b = bms[[r["icon"] for r in have]].reshape(len(have), -1).astype(np.float32)
    inter = b @ b.T
    area = b.sum(1)
    iou = inter / np.maximum(area[:, None] + area[None, :] - inter, 1)
    a = np.log(np.array([r["tight_w"] / r["tight_h"] for r in have]))
    iou[np.abs(a[:, None] - a[None, :]) > ASPECT_TOL] = 0.0
    return have, iou


def cluster(rows: list[dict], bms: np.ndarray) -> list[dict]:
    """Leader clustering: the icon with most neighbours founds each group."""
    have, iou = similarity(rows, bms)
    near = iou >= SAME_ICON
    free = np.ones(len(have), bool)
    leaders = []
    while free.any():
        deg = (near & free[None, :]).sum(1) * free
        i = int(deg.argmax())
        leaders.append(i)
        free &= ~near[i]
        free[i] = False
    lead = np.array(leaders)
    best = iou[:, lead]
    assign = np.where(best.max(1) >= SAME_ICON, best.argmax(1), -1)
    assign[lead] = np.arange(len(lead))
    for r, c, s in zip(have, assign, best.max(1)):
        r["cluster"], r["leader_iou"] = int(c), round(float(s), 3)
    for i in lead:
        have[i]["leader"] = True
    return have


def score(have: list[dict]) -> list[dict]:
    """Each group against the ammo labels on the player's kills in it."""
    groups: dict[int, list[dict]] = defaultdict(list)
    for r in have:
        groups[r["cluster"]].append(r)
    out = []
    for c, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        lab = [r["ammo"]["label"] for r in rs
               if r["role"] == "player_kill" and r["ammo"].get("label")]
        labels = Counter(" / ".join(x) for x in lab)
        unique = Counter(x[0] for x in lab if len(x) == 1)
        major = unique.most_common(1)[0][0] if unique else None
        out.append({"cluster": c, "n": len(rs), "kills": sum(r["role"] == "player_kill" for r in rs),
                    "labels": dict(labels.most_common()), "major": major,
                    "unique": sum(unique.values()),
                    "unique_agree": unique.get(major, 0),
                    "consistent": sum(major in x for x in lab), "labelled": len(lab),
                    "profiles": dict(Counter(r["profile"] for r in rs)),
                    "sessions": len({r["session_id"] for r in rs}),
                    "tight_w": dict(Counter(r["tight_w"] for r in rs).most_common(3))})
    return out


def sheet(have: list[dict], crops: np.ndarray, groups: list[dict], path: Path,
          per: int = 10) -> None:
    lines = []
    for g in groups:
        rs = [r for r in have if r["cluster"] == g["cluster"]]
        rs = sorted(rs, key=lambda r: -r["leader_iou"])
        pick = rs[:per - 2] + rs[-2:] if len(rs) > per else rs
        cells = [cv2.resize(crops[r["icon"]], (192, 60), interpolation=cv2.INTER_NEAREST)
                 for r in pick]
        cells += [np.zeros((60, 192, 3), np.uint8)] * (per - len(cells))
        label = np.zeros((60, 300, 3), np.uint8)
        text = f"#{g['cluster']} n={g['n']} k={g['kills']}"
        cv2.putText(label, text, (4, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.putText(label, str(g["labels"])[:40], (4, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (160, 220, 160), 1)
        lines.append(np.hstack([label] + cells))
    cv2.imwrite(str(path), np.vstack(lines))


def disagreements(have: list[dict], groups: list[dict], min_labels: int = 5) -> list[dict]:
    """Labelled kills whose group's majority gun is not among their ammo label."""
    major = {g["cluster"]: g["major"] for g in groups
             if g["unique"] >= min_labels}
    return [r for r in have if r["role"] == "player_kill" and r["ammo"].get("label")
            and r["cluster"] in major and major[r["cluster"]] not in r["ammo"]["label"]]


def review(cases: list[dict], path: Path) -> None:
    """Killfeed at the crop, and the ammo counter at the full read and at the kill."""
    store = Store()
    by_sid: dict[str, list[dict]] = defaultdict(list)
    for r in cases:
        by_sid[r["session_id"]].append(r)
    panels = []
    for sid, rs in sorted(by_sid.items()):
        man = store.read_manifest(sid)
        profile = get_profile(man.get("source_profile", "valorant-16x9"))
        kf = killfeed_roi(profile)
        ammo = next(r for r in profile.rois if r.name == "hud_ammo")
        want = defaultdict(list)
        for r in rs:
            want[r["t_ms"]].append((r, "kf"))
            want[r["ammo"]["full_t_ms"]].append((r, "full"))
            want[r["t_first"] - 500.0].append((r, "kill"))
        shots: dict[tuple, np.ndarray] = {}
        src = man["source"]
        for s in sample_at(src["path"], sorted(want), float(src["fps"])):
            h, w = s.frame.shape[:2]
            for r, what in want.get(s.t_ms) or want[min(want, key=lambda x: abs(x - s.t_ms))]:
                x0, y0, x1, y1 = (kf if what == "kf" else ammo).pixels(w, h)
                shots[(id(r), what)] = s.frame[y0:y1, x0:x1].copy()
        for r in rs:
            parts = [shots.get((id(r), k)) for k in ("kf", "full", "kill")]
            if any(p is None for p in parts):
                continue
            kfp = cv2.resize(parts[0], None, fx=0.8, fy=0.8)
            am = [cv2.resize(p, (240, int(240 * p.shape[0] / p.shape[1]))) for p in parts[1:]]
            right = np.vstack(am)
            hgt = max(kfp.shape[0], right.shape[0]) + 24
            pan = np.zeros((hgt, kfp.shape[1] + right.shape[1] + 10, 3), np.uint8)
            pan[24:24 + kfp.shape[0], :kfp.shape[1]] = kfp
            pan[24:24 + right.shape[0], kfp.shape[1] + 10:] = right
            a = r["ammo"]
            cv2.putText(pan, f"{sid} {r['t_first'] / 1000:.1f}s grp{r['cluster']} slot{r['slot']} "
                             f"label {'/'.join(a['label'])} full {a['pair']} kill {a['kill_pair']}",
                        (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            panels.append(pan)
    wmax = max(p.shape[1] for p in panels)
    cv2.imwrite(str(path), np.vstack([np.pad(p, ((0, 6), (0, wmax - p.shape[1]), (0, 0)))
                                      for p in panels]))


def corpus_score(rows: list[dict], have: list[dict], groups: list[dict]) -> dict:
    """The M1-M4 figures, and the kill walk against the scoreboard's K/D."""
    from reticle.checks import KNOWN_KD
    kills = [r for r in rows if r["role"] == "player_kill"]
    labelled = [r for r in kills if r["ammo"].get("label")]
    scored = [g for g in groups if g["unique"] >= 5]
    known = {s for s in {r["session_id"] for r in rows} if s in KNOWN_KD}
    return {
        "tracks": len(rows), "icons": len(have),
        "kills": len(kills), "kills_labelled": len(labelled),
        "kills_unique": sum(len(r["ammo"]["label"]) == 1 for r in labelled),
        "kills_cropped_own_entry": sum(r.get("verdict") == "kill" for r in kills),
        "groups": len(groups), "groups_scored": len(scored),
        "groups_scored_pure": sum(g["unique_agree"] >= 0.9 * g["unique"] for g in scored),
        "disagreements": len(disagreements(have, groups)),
        "kills_known_sessions": sum(r["session_id"] in known for r in kills),
        "known_kd_kills": sum(KNOWN_KD[s][0] for s in known),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mine")
    m.add_argument("session")
    c = sub.add_parser("cluster")
    c.add_argument("--min", type=int, default=2, help="smallest group on the sheet")
    sub.add_parser("review")
    args = ap.parse_args()
    _check_table()
    if args.cmd == "mine":
        for sid in hud_sessions() if args.session == "all" else [args.session]:
            mine(sid)
    elif args.cmd == "cluster":
        rows, bms, crops = load_all()
        have = cluster(rows, bms)
        groups = score(have)
        for g in groups:
            if g["n"] >= args.min:
                print(json.dumps(g))
        print(f"{len(have)} icons, {len(groups)} groups, "
              f"{sum(g['n'] == 1 for g in groups)} singletons")
        (OUT / "clusters.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in have), encoding="utf-8")
        values = corpus_score(rows, have, groups)
        print(json.dumps(values))
        from reticle import metrics
        from reticle.adjudication.weapon import WEAPON_ADJUDICATION_VERSION
        metrics.record("weapon_icons", part="corpus", session="corpus", values=values,
                       deps={"version": VERSION, "mask": WEAPON_ADJUDICATION_VERSION,
                             "same_icon": SAME_ICON, "aspect_tol": ASPECT_TOL},
                       context={"sessions": len({r["session_id"] for r in rows})},
                       controls=[{"name": "kill walk vs KNOWN_KD",
                                  "observed": values["kills_known_sessions"],
                                  "expected": values["known_kd_kills"], "tol": 1}],
                       note="tol 1: production's killfeed counts bfad2778a372 at 20 against "
                            "19 on the scoreboard (reticle kd); this walk reproduces it")
        big = [g for g in groups if g["n"] >= args.min]
        for k in range(0, len(big), 30):
            sheet(have, crops, big[k:k + 30], OUT / f"clusters_{k // 30}.png")
    elif args.cmd == "review":
        rows, bms, _ = load_all()
        have = cluster(rows, bms)
        cases = disagreements(have, score(have))
        print(f"{len(cases)} labelled kills disagree with their group's majority")
        review(cases, OUT / "disagreements.png")


if __name__ == "__main__":
    main()
