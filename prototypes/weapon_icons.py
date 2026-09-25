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

    .\.venv\Scripts\python.exe prototypes\weapon_icons.py gallery
    .\.venv\Scripts\python.exe prototypes\weapon_icons.py entries

`gallery` builds the owner's gallery from two label sets: the player's group
names (`labels/weapon_icon/`, propagated over the group) and the player's
per-entry names (`labels/killfeed_icon/`), which override a group's name for
that icon and add the entry's own stored descriptors (`killfeed_weapon`,
bound by `adjudication.weapon.bind_entry`) as exemplars. A group named only
"Ability" keeps no exemplar the player did not name. `entries` scores the
per-entry names, leaving one session out at a time.
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

from reticle.adjudication.weapon import (  # noqa: E402
    ICON_GRID as GRID, WEAPON_ADJUDICATION_VERSION, WEAPON_GALLERY_VERSION,
    ENTRY_BOX_TOL, bind_entry, extract_icon_observation, icon_grid,
    mined_gallery_path, name_icon)
from reticle.checks import KF_SIG_TOL, merge_split_tracks, track_entries  # noqa: E402
from reticle.decode import sample_at  # noqa: E402
from reticle.killfeed import analyse_killfeed, killfeed_roi  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import Store  # noqa: E402

VERSION = "weapon-icons-proto-0.2.0"
OUT = Store().root / "analysis" / "weapon_icons"
OFFSETS_MS = (500.0, 1000.0, 1500.0)     # after first sight: the entry is settled
CROP = (40, 160)                         # stored raw crop canvas, larger than any band
SAME_ICON = 0.75                         # IoU joining two icons into one group
ASPECT_TOL = 0.12                        # |log| aspect difference that keeps groups apart
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


def icon_bitmap(crop: np.ndarray) -> tuple[np.ndarray, float] | None:
    """The owner's white mask on the owner's grid, and the tight box's aspect."""
    return icon_grid(extract_icon_observation(crop).white_mask)


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
                    r["aspect"] = round(float(cut[1]), 3)
                    bms.append((r["icon"], cut[0]))
            rows.append(r)
    grid = np.zeros((len(crops), *GRID), np.uint8)
    for i, b in bms:
        grid[i] = b
    return rows, grid, np.array(crops)




def similarity(rows: list[dict], bms: np.ndarray) -> tuple[list[dict], np.ndarray]:
    """IoU between height-normalised icons, zero where the aspect ratios differ."""
    have = [r for r in rows if r["icon"] is not None]
    b = bms[[r["icon"] for r in have]].reshape(len(have), -1).astype(np.float32)
    inter = b @ b.T
    area = b.sum(1)
    iou = inter / np.maximum(area[:, None] + area[None, :] - inter, 1)
    a = np.log(np.array([r["aspect"] for r in have]))
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
                    "aspect": dict(Counter(round(r["aspect"], 1) for r in rs).most_common(3))})
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


def icon_key(r: dict) -> str:
    return f"kf:{r['session_id']}:{int(r['t_first'])}:{r['slot']}"


LABELS = Store().root / "labels" / "weapon_icon"
PER_NAME = 40                            # exemplars kept per name
HELD_OUT_EVERY = 4                       # every 4th session in sorted order


def player_names(have: list[dict]) -> None:
    """Attach the player's group name to every icon, and mark the ones they saw.

    `truth` is the name the player gave the icon's group (propagated, so it
    rests on the grouping); `seen` is set only on icons the labeller showed.
    """
    last: dict[str, dict] = {}
    for path in LABELS.glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                last[row["key"]] = row
    lead = {r["cluster"]: r for r in have if r.get("leader")}
    names, shown = {}, {}
    for c, r in lead.items():
        lab = last.get(icon_key(r))
        if not lab or lab["uncertain"] or lab["mixed"] or not lab["answer"]:
            continue
        name = lab.get("ability") or lab["answer"]
        names[c] = (name, lab["class"])
        for k in [lab["key"]] + lab["members_shown"]:
            shown[(k, c)] = name
    # Two entries born together can end in one slot, so the key alone collides
    # (11 of 3122 tracks); the group they were shown from settles which.
    for r in have:
        r["truth"], r["truth_class"] = names.get(r["cluster"], (None, None))
        r["seen"] = shown.get((icon_key(r), r["cluster"]))


def held_out(have: list[dict]) -> set[str]:
    sids = sorted({r["session_id"] for r in have})
    return set(sids[HELD_OUT_EVERY - 1::HELD_OUT_EVERY])


KF_LABELS = Store().root / "labels" / "killfeed_icon"
ENTRY_FRAMES = 3                         # stored frames kept per labelled entry


def entry_labels() -> dict[str, dict]:
    """The player's per-entry names, last row per death key. Unsure rows and
    bad crops (the ring was not on the icon) name nothing."""
    last: dict[str, dict] = {}
    for path in sorted(KF_LABELS.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                last[row["key"]] = row
    return {k: r for k, r in last.items()
            if r.get("answer") and not r.get("uncertain") and r.get("class") != "bad_crop"}


def _entries_by_key(sid: str) -> dict[tuple[int, int], dict]:
    from reticle.adjudication.death import session_entries
    return {(int(e["t_first"]), e["slot"]): e for e in session_entries(_hud(sid))}


def _key_of(key: str) -> tuple[int, int]:
    _, _, t, slot = key.split(":")
    return int(t), int(slot)


def labelled_entries(labels: dict[str, dict]) -> list[dict]:
    """Each labelled entry's stored descriptors, bound as the reader binds them,
    kept only where the stored box is the ring the player named: a bound row
    whose box lies elsewhere can be a neighbour's icon (e37fdeca944f 592.0 s,
    a Vandal whose bound rows are a round icon)."""
    from reticle.killfeed import unpack_icon_grid
    store = Store()
    by: dict[str, list[dict]] = defaultdict(list)
    for lab in labels.values():
        by[lab["session_id"]].append(lab)
    out = []
    for sid, labs in sorted(by.items()):
        entries = _entries_by_key(sid)
        obs = store.read_events("killfeed_weapon", sid)
        for lab in labs:
            e = entries.get(_key_of(lab["key"]))
            bound = bind_entry(e, obs) if e is not None else []
            x0, _, x1, _ = lab["ring"]
            rows = [o for o in bound if abs(o["wx0"] - x0) <= ENTRY_BOX_TOL
                    and abs(o["wx1"] - x1) <= ENTRY_BOX_TOL]
            out.append({"key": lab["key"], "session_id": sid, "name": lab["answer"],
                        "class": lab["class"], "bound": len(bound), "on_ring": len(rows),
                        "grids": [unpack_icon_grid(o["grid"]) for o in rows],
                        "aspects": [float(o["aspect"]) for o in rows]})
    return out


def revise_truth(have: list[dict], labels: dict[str, dict]) -> Counter:
    """A per-entry name overrides the group's for that icon when the mined box
    is as wide as the ring the player named; an icon left in a group named
    only "Ability" keeps no name. Returns what changed."""
    changed = Counter()
    for r in have:
        lab = labels.get(f"death:{r['session_id']}:{int(r['t_first'])}:{r['slot']}")
        if lab is not None and abs(r["box_w"] - (lab["ring"][2] - lab["ring"][0])) > ENTRY_BOX_TOL:
            changed["box off the ring"] += 1
            lab = None
        if lab is not None and lab["answer"] != r["truth"]:
            changed[f"{r['truth']} -> {lab['answer']}"] += 1
            r["truth"], r["truth_class"] = lab["answer"], lab["class"]
        elif r["truth"] == "Ability":
            changed["Ability -> None"] += 1
            r["truth"], r["truth_class"] = None, None
    return changed


def build_gallery(have: list[dict], bms: np.ndarray, exclude: set[str],
                  entries: list[dict] = ()) -> dict:
    """Exemplars per player name, from sessions not in `exclude`, spread by group,
    then up to ENTRY_FRAMES stored frames of each labelled entry."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in have:
        if r["truth"] and r["session_id"] not in exclude:
            by[r["truth"]].append(r)
    names, cls, masks, aspects, keys = [], [], [], [], []
    for name, rs in sorted(by.items()):
        rs = sorted(rs, key=lambda r: icon_key(r))
        for k in np.linspace(0, len(rs) - 1, min(PER_NAME, len(rs))):
            r = rs[int(k)]
            names.append(name)
            cls.append(r["truth_class"])
            masks.append(bms[r["icon"]])
            aspects.append(r["aspect"])
            keys.append(icon_key(r))
    for e in entries:
        if e["session_id"] in exclude or not e["grids"]:
            continue
        n = len(e["grids"])
        for k in sorted({int(k) for k in np.linspace(0, n - 1, min(ENTRY_FRAMES, n))}):
            names.append(e["name"])
            cls.append(e["class"])
            masks.append(e["grids"][k])
            aspects.append(e["aspects"][k])
            keys.append(f"{e['key']}#{k}")
    return {"names": np.array(names), "classes": np.array(cls), "masks": np.array(masks),
            "aspects": np.array(aspects), "keys": np.array(keys)}


def evaluate_entries(have: list[dict], bms: np.ndarray, entries: list[dict]) -> dict:
    """Each labelled entry named by `entry_weapon` against a gallery built
    without its session: the per-entry names scored leaving one session out."""
    from reticle.adjudication.weapon import entry_weapon
    store = Store()
    res, rows, by_name = Counter(), [], defaultdict(Counter)
    for sid in sorted({e["session_id"] for e in entries}):
        g = build_gallery(have, bms, {sid}, entries)
        ents = _entries_by_key(sid)
        obs = store.read_events("killfeed_weapon", sid)
        for e in (e for e in entries if e["session_id"] == sid):
            ent = ents.get(_key_of(e["key"]))
            v = (entry_weapon(ent, obs, gallery=g) if ent is not None
                 else {"status": "refused", "reason": "no_entry"})
            got = v.get("name") or ("Environmental" if v.get("category") == "environmental"
                                    else None)
            outcome = ("refused" if v["status"] != "resolved"
                       else "right" if got == e["name"] else "wrong")
            res[f"{e['class']}:{outcome}"] += 1
            by_name[e["name"]][outcome] += 1
            rows.append((e["key"], e["name"], got, v.get("reason"), outcome))
    return {"by_class": dict(sorted(res.items())),
            "by_name": {n: dict(c) for n, c in sorted(by_name.items())},
            "wrong": [r for r in rows if r[4] == "wrong"],
            "refused": [r for r in rows if r[4] == "refused"]}


def write_gallery(gallery: dict, have: list[dict]) -> Path:
    """The owner's mined gallery file, with what it was built from."""
    import hashlib
    labels = sorted(LABELS.glob("*.jsonl"))
    provenance = {
        "version": WEAPON_GALLERY_VERSION, "built_by": f"prototypes/weapon_icons.py {VERSION}",
        "labels": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in labels},
        "mask": WEAPON_ADJUDICATION_VERSION, "same_icon": SAME_ICON,
        "aspect_tol": ASPECT_TOL, "per_name": PER_NAME,
        "sessions": sorted({r["session_id"] for r in have}),
        "names": dict(Counter(str(n) for n in gallery["names"])),
    }
    path = mined_gallery_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit(f"{path} exists; bump WEAPON_GALLERY_VERSION rather than overwrite it")
    np.savez_compressed(path, **gallery, provenance=json.dumps(provenance))
    print(f"wrote {len(gallery['names'])} exemplars over {len(provenance['names'])} names to {path}")
    return path


def accept(baseline: dict) -> dict:
    """S1-S4 over the stored death streams: weapons named, player kills inside
    their ammo labels, identities and portrait streams unchanged."""
    import hashlib
    from reticle.adjudication.death import DEATH_ADJUDICATION_VERSION
    store = Store()
    per, tot = {}, Counter()
    for sid in hud_sessions():
        rows = store.read_events("death", sid)
        if not rows or rows[0].get("death_adjudication_version") != DEATH_ADJUDICATION_VERSION:
            per[sid] = {"skipped": "no current death stream"}
            continue
        deaths = rows[1:]
        hud = _hud(sid)
        kills = [r for r in deaths if r["kf_player_kill"]]
        labelled = [(r, a) for r in kills
                    if (a := ammo_label(r["t_ms"], hud["t_ms"], hud["ammo_mag"],
                                        hud["ammo_reserve"])).get("label")]
        base = baseline.get(sid, {})
        before = base.get("deaths") or {}
        v = {"deaths": len(deaths),
             "weapon_resolved": sum(r["weapon_evidence"]["status"] == "resolved" for r in deaths),
             "kills": len(kills), "kills_named": sum(bool(r["weapon"]) for r in kills),
             "kills_ammo_labelled": len(labelled),
             "kills_in_ammo_set": sum(r["weapon"] in a["label"] for r, a in labelled),
             "identity_changed": sum(before.get(r["death_id"], [r["victim"], r["killer"],
                                                                 r["status"]])
                                     != [r["victim"], r["killer"], r["status"]] for r in deaths),
             "identity_compared": sum(r["death_id"] in before for r in deaths),
             "portrait_identical": int(hashlib.sha256(
                 store.events_path("killfeed_portrait", sid).read_bytes()).hexdigest()
                 == base.get("portrait"))}
        v["disagreements"] = [(r["death_id"], r["weapon"], a["label"]) for r, a in labelled
                              if r["weapon"] not in a["label"]]
        per[sid] = v
        tot.update({k: x for k, x in v.items() if isinstance(x, int)})
    return {"sessions": per, "total": dict(tot)}


def evaluate(rows: list[dict], have: list[dict], bms: np.ndarray) -> dict:
    player_names(have)
    labels = entry_labels()
    revise_truth(have, labels)
    out_s = held_out(have)
    gallery = build_gallery(have, bms, out_s, labelled_entries(labels))
    test = [r for r in have if r["session_id"] in out_s]
    for r in test:
        r["named"] = name_icon(bms[r["icon"]], r["aspect"], gallery)
    acc = [r for r in test if r["named"]["name"]]
    seen = [r for r in test if r["seen"]]
    seen_acc = [r for r in seen if r["named"]["name"]]
    kills = [r for r in acc if r["role"] == "player_kill" and r["ammo"].get("label")]
    truth = [r for r in acc if r["truth"]]
    chamber = {"Headhunter": {"Sheriff"}, "Tour De Force": {"Marshal", "Outlaw", "Operator"}}
    confused = [r for r in acc if r["truth"] and (
        r["named"]["name"] in chamber.get(r["truth"], ()) or
        r["truth"] in chamber.get(r["named"]["name"], ()))]
    wrong = [(icon_key(r), r["seen"] or r["truth"], r["named"]["name"]) for r in acc
             if (r["seen"] or r["truth"]) and r["named"]["name"] != (r["seen"] or r["truth"])]
    return {
        "held_out": sorted(out_s), "gallery": len(gallery["names"]),
        "test_icons": len(test), "accepted": len(acc),
        "seen": len(seen), "seen_accepted": len(seen_acc),
        "seen_correct": sum(r["named"]["name"] == r["seen"] for r in seen_acc),
        "kills_labelled_accepted": len(kills),
        "kills_in_ammo_set": sum(r["named"]["name"] in r["ammo"]["label"] for r in kills
                                 if r["truth_class"] != "Not a gun"),
        "kills_named_not_gun": sum(r["truth_class"] == "Not a gun" for r in kills),
        "group_labelled_accepted": len(truth),
        "group_agree": sum(r["named"]["name"] == r["truth"] for r in truth),
        "chamber_confusions": len(confused),
        "refusals": dict(Counter(r["named"].get("reason") for r in test if not r["named"]["name"])),
        "wrong": wrong[:20],
    }


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
    sub.add_parser("evaluate")
    sub.add_parser("gallery")
    sub.add_parser("entries")
    ac = sub.add_parser("accept")
    ac.add_argument("baseline", type=Path, help="JSON of pre-scan portrait hashes and deaths")
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
    elif args.cmd == "evaluate":
        rows, bms, _ = load_all()
        have = cluster(rows, bms)
        res = evaluate(rows, have, bms)
        print(json.dumps(res, indent=1))
        from reticle import metrics
        from reticle.adjudication.weapon import WEAPON_ADJUDICATION_VERSION as OWNER
        metrics.record("weapon_icons", part="gallery-heldout", session="corpus",
                       values={k: v for k, v in res.items() if isinstance(v, int)},
                       deps={"version": VERSION, "gallery": WEAPON_GALLERY_VERSION,
                             "mask": OWNER, "per_name": PER_NAME,
                             "entry_frames": ENTRY_FRAMES, "held_out": res["held_out"]},
                       context={"refusals": res["refusals"], "wrong": res["wrong"]})
    elif args.cmd == "accept":
        from reticle import metrics
        from reticle.adjudication.weapon import WEAPON_ADJUDICATION_VERSION as WAV
        from reticle.killfeed import KILLFEED_WEAPON_VERSION
        res = accept(json.loads(args.baseline.read_text(encoding="utf-8")))
        for sid, v in res["sessions"].items():
            print(sid, json.dumps(v))
        t = res["total"]
        print("total", json.dumps(t))
        deps = {"reader": KILLFEED_WEAPON_VERSION, "owner": WAV, "gallery": WEAPON_GALLERY_VERSION}
        for sid, v in res["sessions"].items():
            if "skipped" not in v:
                metrics.record("weapon_reader", part="accept", session=sid, deps=deps,
                               values={k: x for k, x in v.items() if isinstance(x, int)},
                               context={"disagreements": v["disagreements"]},
                               controls=[{"name": "kills inside ammo set",
                                          "observed": v["kills_in_ammo_set"],
                                          "expected": v["kills_ammo_labelled"]}])
        metrics.record("weapon_reader", part="accept", session="corpus", deps=deps, values=t,
                       controls=[{"name": "no identity change", "observed": t["identity_changed"],
                                  "expected": 0}])
    elif args.cmd == "gallery":
        rows, bms, _ = load_all()
        have = cluster(rows, bms)
        player_names(have)
        labels = entry_labels()
        print("truth revised:", dict(revise_truth(have, labels)))
        write_gallery(build_gallery(have, bms, set(), labelled_entries(labels)), have)
    elif args.cmd == "entries":
        rows, bms, _ = load_all()
        have = cluster(rows, bms)
        player_names(have)
        labels = entry_labels()
        print("truth revised:", dict(revise_truth(have, labels)))
        res = evaluate_entries(have, bms, labelled_entries(labels))
        print(json.dumps(res, indent=1))
        from reticle import metrics
        from reticle.adjudication.weapon import WEAPON_ADJUDICATION_VERSION as OWNER
        values = {k.replace(":", "_"): v for k, v in res["by_class"].items()}
        for name in ("Not Dead Yet", "Resurrection"):
            for outcome in ("right", "wrong", "refused"):
                values[f"{name.replace(' ', '_').lower()}_{outcome}"] = \
                    res["by_name"].get(name, {}).get(outcome, 0)
        metrics.record("weapon_icons", part="entries-loso", session="corpus", values=values,
                       deps={"version": VERSION, "gallery": WEAPON_GALLERY_VERSION,
                             "mask": OWNER, "entry_frames": ENTRY_FRAMES},
                       context={"wrong": res["wrong"], "by_name": res["by_name"]},
                       note="leave one session out over labels/killfeed_icon; e37fdeca944f "
                            "592.0 s is labelled Vandal on the neighbouring entry's ring, "
                            "and the frame shows Clove -> Clove with the Not Dead Yet icon")
    elif args.cmd == "review":
        rows, bms, _ = load_all()
        have = cluster(rows, bms)
        cases = disagreements(have, score(have))
        print(f"{len(cases)} labelled kills disagree with their group's majority")
        review(cases, OUT / "disagreements.png")


if __name__ == "__main__":
    main()
