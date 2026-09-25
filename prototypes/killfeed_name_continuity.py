r"""Does one killfeed name image mark one player for a whole match?

    .\.venv\Scripts\python.exe prototypes\killfeed_name_continuity.py extract [SID ...]
    .\.venv\Scripts\python.exe prototypes\killfeed_name_continuity.py score [SID ...]
    .\.venv\Scripts\python.exe prototypes\killfeed_name_continuity.py sheet SID

Stage 2 of the inference architecture (`docs/BEHAVIOUR_MODEL_DESIGN.md`). A
name should belong to one player, hence one agent, for the match; if its
pixels repeat, entries join into players and match identity becomes an
assignment of five names to five agents per side.

`extract` reads each stored death verdict's entry from the `hud` ROI crop
cache (killfeed ROI; no decode) at 0.5 s and 1.0 s past its onset, in its
first slot, and cuts each name's white-text mask (`killfeed._plate_masks`)
between the portrait and the weapon icon: the killer's from its portrait's
right edge to the icon, the victim's from the icon to its portrait, keeping
the last ink group (gaps over `killfeed.NAME_GAP`) so a headshot or wallbang
mark is dropped. The player's own entries print "Me" and are kept apart.
Masks go to `<store>/analysis/killfeed_names_<sid>.npz`.

`score` compares every pair of name crops in a session: two match when their
widths and heights differ by at most 1 px and their binary IoU, best over
+-1 px shifts, reaches `IOU_MIN`. The check is independent of the pixels
compared: a pair is one player when both roles sit on one team and the
reference channels (`reliability.REFERENCE_CHANNELS`) -- or, in the wider
tier, the resolved verdict -- name one agent [domain:rounds/agent-uniqueness].
It prints recall and precision per tier, the two frames of one entry as the
stability floor, and each name cluster that recurs in another session with
the same agent, the signature of a hidden name that prints the agent's.

`sheet` draws each cluster's crop with its agents, for inspection.
Predictions and outcome: `killfeed-name-continuity` in the store's
`notes/predictions.jsonl`.
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
from reticle import killfeed as kf  # noqa: E402
from reticle.adjudication.reliability import REFERENCE_CHANNELS  # noqa: E402
from reticle.passes import SessionContext  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

SIDS = ("043bafca271a 223d636bf8d2 3694746e4e54 5822b6646448 587c15b07779 59c70f1ef720 "
        "7010b3d62460 75a55a296d3b 96aa1ae9b96f 9acf02f98283 a06f04a0059f a1a995e6b19b "
        "b3b9defb6fd7 b7d24102a6f6 bdfdcf009dba bfad2778a372 c40d950031bb e37fdeca944f "
        "ff636d173b07").split()
STORE = Store()
OFFSETS_MS = (500.0, 1000.0)
IOU_MIN = 0.8
#: Set from the two frames of one entry (labels-free); see `score`.
NCC_MIN = 0.9
TEXT_SHARE = 0.8
#: Names measured at most 14 px tall, the headshot crosshair 16-17 px.
MAX_TEXT_H = 15


def _path(sid):
    return STORE.root / "analysis" / f"killfeed_names_{sid}.npz"


def _groups(cols: np.ndarray) -> list[tuple[int, int]]:
    xs = np.where(cols)[0]
    if xs.size == 0:
        return []
    out, start = [], xs[0]
    for a, b in zip(xs[:-1], xs[1:]):
        if b - a > kf.NAME_GAP:
            out.append((int(start), int(a) + 1))
            start = b
    out.append((int(start), int(xs[-1]) + 1))
    return out


def _text_rows(white: np.ndarray, a: int, z: int) -> tuple[int, int] | None:
    """The rows the killer's name occupies: the band's text line."""
    region = white[:, max(a, 0):max(z, 0)] > 0
    rows = np.where(region.sum(axis=1) >= 2)[0]
    return (int(rows[0]), int(rows[-1]) + 1) if rows.size else None


def _cut(white: np.ndarray, whiteness: np.ndarray, a: int, z: int, rows, last: bool):
    """The name's columns inside [a, z): all text groups for the killer, the last
    one for the victim. A group is text when at least `TEXT_SHARE` of its ink
    over the band's full height lies on the text line; a portrait's white art
    runs above and below it."""
    a, z = max(a, 0), max(z, 0)
    full = white[:, a:z] > 0
    line = np.zeros_like(full)
    line[max(rows[0] - 2, 0):rows[1] + 4] = full[max(rows[0] - 2, 0):rows[1] + 4]
    keep = [g for g in _groups(line.any(axis=0))
            if g[1] - g[0] >= 3 and g[1] <= (z - a) - 2
            and np.ptp(np.where(line[:, g[0]:g[1]].any(axis=1))[0]) < MAX_TEXT_H
            and line[:, g[0]:g[1]].sum() >= TEXT_SHARE * max(1, full[:, g[0]:g[1]].sum())]
    if not keep:
        return None
    g0, g1 = keep[-1]
    ys = np.where(line[:, g0:g1].any(axis=1))[0]
    r0, r1 = int(ys[0]), int(ys[-1]) + 1
    # The whiteness keeps the band's full height: a name's own ink rows vary
    # by a pixel with the plate behind it, and the band is centred on the text.
    return (line[r0:r1, g0:g1], whiteness[:, a + g0:a + g1].astype(np.float32), a + g0)


def _reference(ver: dict) -> str | None:
    refs = {c["agent"] for c in ver.get("claims", []) if c["channel"] in REFERENCE_CHANNELS
            and c.get("agent") and not c.get("depends_on")}
    return next(iter(refs)) if len(refs) == 1 else None


def extract(sid: str) -> list[dict]:
    man = STORE.read_manifest(sid)
    prof = get_profile(man["source_profile"])
    ctx = SessionContext(store=STORE, manifest=man, profile=prof)
    reader = kf.KillfeedPortraitReader(prof, ctx.wh, mask=ctx.kf_mask(), hz=2.0, spans=None)
    cache, _ = RoiCache.load(STORE.root, man, prof, "killfeed")
    x0, y0, x1, y1 = reader.roi.pixels(reader.w, reader.h)
    rows = [r for r in STORE.read_events("death", sid) if r.get("kind") == "death_verdict"]
    out = []
    for r in rows:
        for k, off in enumerate(OFFSETS_MS):
            smp = next(iter(cache.samples([float(r["t_ms"]) + off], rois="killfeed")), None)
            if smp is None:
                continue
            views = kf.analyse_killfeed(smp.frame, reader.roi, reader.w, reader.h, reader.mask, prof.name)
            v = next((v for v in views if v.slot == r["slot"] and v.wx1 > v.wx0), None)
            if v is None:
                continue
            crop = smp.frame[y0:y1, x0:x1]
            mask = reader.mask if reader.mask is not None else np.ones(crop.shape[:2], bool)
            _, _, white = kf._plate_masks(crop, mask)
            white = white[v.y0:v.y1]
            whiteness = crop[v.y0:v.y1].min(axis=2)
            meta = r.get("metadata") or {}
            if not v.killer_run:
                continue
            # The victim's portrait bounds its name: portrait art can pass as
            # a narrow text group.
            obs = {o["role"]: o for o in kf.portrait_observations(
                smp.frame, reader.roi, reader.w, reader.h, views=[v], mask=reader.mask,
                profile_name=prof.name) if o.get("slot") == v.slot and "x0" in o}
            rows_ = _text_rows(white, *v.killer_run)
            if rows_ is None:
                continue
            for role, key in (("killer", "killer_identity"), ("victim", "identity")):
                if role == "killer":
                    cut = _cut(white, whiteness, 0, v.wx0 - 1, rows_, last=True)
                else:
                    z = obs["victim"]["x0"] if "victim" in obs else white.shape[1]
                    cut = _cut(white, whiteness, v.wx1 + 1, z, rows_, last=True)
                if cut is None:
                    continue
                ver = meta.get(key) or {}
                team = r["side"] if role == "victim" else {"ally": "enemy", "enemy": "ally"}.get(r["side"])
                me = (v.verdict == "kill" and role == "killer") or (v.verdict == "death" and role == "victim")
                img = crop[v.y0:v.y1][:, cut[2]:cut[2] + cut[0].shape[1]]
                out.append({"death_id": r["death_id"], "t_ms": r["t_ms"], "frame": k, "role": role,
                            "team": team, "me": bool(me), "agent": ver.get("agent"),
                            "status": ver.get("status"), "reference": _reference(ver),
                            "mask": cut[0], "gray": cut[1], "image": img})
    np.savez_compressed(_path(sid), items=np.array(out, dtype=object))
    return out


def load(sid: str) -> list[dict]:
    return list(np.load(_path(sid), allow_pickle=True)["items"])


def iou(a: np.ndarray, b: np.ndarray) -> float:
    if abs(a.shape[0] - b.shape[0]) > 1 or abs(a.shape[1] - b.shape[1]) > 1:
        return 0.0
    h, w = max(a.shape[0], b.shape[0]) + 2, max(a.shape[1], b.shape[1]) + 2
    pa = np.zeros((h, w), bool)
    pa[1:1 + a.shape[0], 1:1 + a.shape[1]] = a
    best = 0.0
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            pb = np.zeros((h, w), bool)
            hh, ww = min(b.shape[0], h - dy), min(b.shape[1], w - dx)
            pb[dy:dy + hh, dx:dx + ww] = b[:hh, :ww]
            union = (pa | pb).sum()
            if union:
                best = max(best, (pa & pb).sum() / union)
    return float(best)


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised correlation of two whiteness crops, best over +-1 px
    horizontal and +-2 px vertical shifts; 0 when their widths differ by more
    than 1 px."""
    if abs(a.shape[0] - b.shape[0]) > 2 or abs(a.shape[1] - b.shape[1]) > 1:
        return 0.0
    best = -1.0
    for dy in (-2, -1, 0, 1, 2):
        for dx in (-1, 0, 1):
            ya, yb = max(0, dy), max(0, -dy)
            xa, xb = max(0, dx), max(0, -dx)
            h = min(a.shape[0] - ya, b.shape[0] - yb)
            w = min(a.shape[1] - xa, b.shape[1] - xb)
            if h < 3 or w < 3:
                continue
            p = a[ya:ya + h, xa:xa + w].ravel(); q = b[yb:yb + h, xb:xb + w].ravel()
            p = p - p.mean(); q = q - q.mean()
            d = float(np.sqrt((p * p).sum() * (q * q).sum()))
            if d > 0:
                best = max(best, float((p * q).sum()) / d)
    return best


def same_name(a: dict, b: dict) -> bool:
    return ncc(a["gray"], b["gray"]) >= NCC_MIN


def clusters(items: list[dict]) -> list[list[int]]:
    """Greedy: a crop joins the first cluster whose first member it matches."""
    out: list[list[int]] = []
    for i, it in enumerate(items):
        for c in out:
            if same_name(items[c[0]], it):
                c.append(i)
                break
        else:
            out.append([i])
    return out


def score(sids: list[str]) -> dict:
    total = defaultdict(Counter)
    reps, dist, errs = [], defaultdict(list), []
    for sid in sids:
        items = [it for it in load(sid) if not it["me"]]
        # Stability floor: the two frames of one entry role.
        by = defaultdict(list)
        for it in items:
            by[(it["death_id"], it["role"])].append(it)
        within = [ncc(p[0]["gray"], p[1]["gray"]) for p in by.values() if len(p) == 2]
        dist["within"] += within
        stab = Counter("match" if x >= NCC_MIN else "differ" for x in within)
        one = [p[0] for p in by.values()]
        res = Counter(stab_match=stab["match"], stab_pairs=sum(stab.values()))
        for i in range(len(one)):
            for j in range(i + 1, len(one)):
                a, b = one[i], one[j]
                x = ncc(a["gray"], b["gray"])
                m = x >= NCC_MIN
                for tier, key in (("ref", "reference"), ("res", "agent")):
                    if a[key] is None or b[key] is None:
                        continue
                    if tier == "res" and (a["status"] != "resolved" or b["status"] != "resolved"):
                        continue
                    same = a["team"] == b["team"] and a[key] == b[key]
                    dist[f"{tier}_{'same' if same else 'diff'}"].append(x)
                    if m != same:
                        errs.append((sid, tier, round(x, 3), a["death_id"], a["role"], a["team"], a[key],
                                     b["death_id"], b["role"], b["team"], b[key]))
                    res[f"{tier}_{'tp' if m and same else 'fn' if same else 'fp' if m else 'tn'}"] += 1
        cl = clusters(one)
        for c in cl:
            agents = Counter((one[i]["team"], one[i]["agent"]) for i in c if one[i]["status"] == "resolved")
            reps.append({"sid": sid, "mask": one[c[0]]["mask"], "gray": one[c[0]]["gray"], "image": one[c[0]]["image"],
                         "n": len(c), "agents": dict(agents)})
        res["clusters"] = len(cl)
        res["roles"] = len(one)
        total[sid] = res
        rt = lambda t: (res[f"{t}_tp"] / max(1, res[f"{t}_tp"] + res[f"{t}_fn"]),
                        res[f"{t}_tp"] / max(1, res[f"{t}_tp"] + res[f"{t}_fp"]))
        print(sid, f"roles {len(one)} clusters {len(cl)} stable {stab['match']}/{sum(stab.values())}",
              "ref recall %.3f precision %.3f" % rt("ref"), f"(tp {res['ref_tp']} fn {res['ref_fn']} fp {res['ref_fp']})",
              "res recall %.3f precision %.3f" % rt("res"), f"(tp {res['res_tp']} fn {res['res_fn']} fp {res['res_fp']})",
              flush=True)
    agg = sum(total.values(), Counter())
    for t in ("ref", "res"):
        tp, fn, fp = agg[f"{t}_tp"], agg[f"{t}_fn"], agg[f"{t}_fp"]
        print(f"ALL {t}: recall {tp / max(1, tp + fn):.3f} precision {tp / max(1, tp + fp):.3f} "
              f"(tp {tp} fn {fn} fp {fp})")
    print(f"ALL stability {agg['stab_match']}/{agg['stab_pairs']}")
    for k, v in sorted(dist.items()):
        if v:
            print(f"   ncc {k}: n {len(v)} quantiles 1/5/50/95/99",
                  np.round(np.quantile(v, [.01, .05, .5, .95, .99]), 3).tolist())
    # Clusters recurring across sessions with one agent: hidden names.
    hidden = []
    for i, a in enumerate(reps):
        if not a["agents"]:
            continue
        ag = max(a["agents"], key=a["agents"].get)[1]
        hits = {b["sid"] for b in reps if b["sid"] != a["sid"] and b["agents"]
                and max(b["agents"], key=b["agents"].get)[1] == ag and same_name(a, b)}
        if hits:
            hidden.append((a["sid"], ag, a["n"], sorted(hits)))
    per = Counter(h[0] for h in hidden)
    print(f"recurring same-agent clusters: {len(hidden)} in {len(per)} sessions:", dict(per))
    for h in hidden:
        print("  ", h)
    return {"total": {k: dict(v) for k, v in total.items()}, "recurring": hidden, "reps": reps,
            "errors": errs}


def sheet(sid: str, reps: list[dict]) -> Path:
    tiles = []
    for r in (r for r in reps if r["sid"] == sid):
        img = cv2.resize(r["image"], None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        tile = np.full((img.shape[0] + 14, 420, 3), 20, np.uint8)
        tile[14:, :min(420, img.shape[1])] = img[:, :420]
        label = f"n{r['n']} " + " ".join(f"{t[0]}:{a}x{n}" for (t, a), n in r["agents"].items())
        cv2.putText(tile, label[:70], (2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (230, 230, 230), 1)
        tiles.append(tile)
    while len(tiles) % 3:
        tiles.append(np.zeros_like(tiles[0]))
    h = max(t.shape[0] for t in tiles)
    tiles = [np.pad(t, ((0, h - t.shape[0]), (0, 0), (0, 0))) for t in tiles]
    grid = np.vstack([np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)])
    out = STORE.root / "analysis" / f"killfeed_names_{sid}.png"
    cv2.imwrite(str(out), grid)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("extract", "score", "sheet"))
    ap.add_argument("sids", nargs="*")
    args = ap.parse_args()
    sids = args.sids or SIDS
    if args.cmd == "extract":
        for sid in sids:
            print(sid, len(extract(sid)), flush=True)
    elif args.cmd == "score":
        score(sids)
    else:
        print(sheet(sids[0], score(sids)["reps"] if len(sids) > 1 else score(sids)["reps"]))
