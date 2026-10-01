r"""Open-set killfeed icons, step 1: can the owner's score tell a new icon from a known one?

    .\.venv\Scripts\python.exe prototypes\killfeed_openset.py heldout
    .\.venv\Scripts\python.exe prototypes\killfeed_openset.py refusals [sid ...]

`adjudication.weapon.name_icon` [owns:killfeed-weapon] scores an icon by its
best aspect-gated IoU over the mined gallery and refuses below NAME_MIN_IOU
(`no_close_exemplar`) or under NAME_MARGIN (`tie`). This prototype measures
whether that score separates a NEW icon (its name absent from the gallery)
from a KNOWN one, without changing the owner.

`heldout` scores every exemplar of each name with at least MIN_ENTRIES
distinct entries twice: against the gallery without that whole name (new) and
against the gallery without the exemplar's own entry (known; every frame of a
labelled entry goes, since a sibling frame is the same kill). It reports the
AUROC and the share of new icons flagged at the score that flags 5% of known
icons, over the full gallery and over the gallery `restrict_gallery` narrows to
the exemplar's match lineup (`lineup.load_lineup`, both sides, named agents
only), by category (gun, ability, other).

`refusals` names the stored `killfeed_weapon` rows of the given sessions with
the owner, splits the refusals by the owner's own reason, groups the
low-score rows with `weapon_icons.cluster` (leader clustering, IoU >= 0.75,
aspect tolerance 0.12), and draws one contact sheet per group of at least
SHEET_MIN rows (and for the three largest groups of two rows or more) under `<store>/analysis/killfeed-openset-20261001/`: each
member's stored grid, its killfeed crop from the crop cache, and the nearest
gallery exemplar. Stored rows only; no decode.

Predictions are logged in the store's `notes/predictions.jsonl` under
`killfeed-openset-20261001`.

Results, 2026-10-01 (weapon-gallery-0.3.0)
------------------------------------------
The gallery holds
[metric:killfeed_openset/heldout_all@weapon-gallery-0.3.0#gallery_gun=602] gun,
[metric:killfeed_openset/heldout_all@weapon-gallery-0.3.0#gallery_ability=191] ability and
[metric:killfeed_openset/heldout_all@weapon-gallery-0.3.0#gallery_other=7] other
exemplars; [metric:killfeed_openset/heldout_all@weapon-gallery-0.3.0#names=25]
names have five or more entries. Leaving the whole name out against leaving the entry out
separates them: AUROC
[metric:killfeed_openset/heldout_all@weapon-gallery-0.3.0#auroc_full=0.9952]
(guns [metric:killfeed_openset/heldout_gun@weapon-gallery-0.3.0#auroc_full=0.9949],
abilities [metric:killfeed_openset/heldout_ability@weapon-gallery-0.3.0#auroc_full=0.9942]),
and the 5% threshold
[metric:killfeed_openset/heldout_all@weapon-gallery-0.3.0#threshold_full=0.86]
flags [metric:killfeed_openset/heldout_all@weapon-gallery-0.3.0#new_at_5_full=1.0]
of the new icons. The lineup narrowing barely moves it
([metric:killfeed_openset/heldout_all@weapon-gallery-0.3.0#auroc_narrow=0.9956]):
it drops only ability names, and the nearest other name of a new icon is
almost always a gun.

The `kf:` exemplars inflate the known case: the gallery builder chose them by
clustering at IoU 0.75, so they resemble one another by construction. The
`death:` exemplars, stored descriptors of labelled entries, are the honest
known case: AUROC
[metric:killfeed_openset/heldout_all@weapon-gallery-0.3.0#auroc_unselected=0.9906]
over [metric:killfeed_openset/heldout_all@weapon-gallery-0.3.0#n_unselected=147]
icons, threshold
[metric:killfeed_openset/heldout_all@weapon-gallery-0.3.0#threshold_unselected=0.724],
new flagged [metric:killfeed_openset/heldout_all@weapon-gallery-0.3.0#new_at_5_unselected=0.9524].
For guns that sample is only
[metric:killfeed_openset/heldout_gun@weapon-gallery-0.3.0#n_unselected=28]
icons, and two labelled entries (an Ares at 043bafca271a 1632 s, a Phantom at
bdfdcf009dba 388 s) score no better against their own name than against any
other, so the gun threshold falls to
[metric:killfeed_openset/heldout_gun@weapon-gallery-0.3.0#threshold_unselected=0.468]
and flags only
[metric:killfeed_openset/heldout_gun@weapon-gallery-0.3.0#new_at_5_unselected=0.1071]
of new guns. At the owner's floor of 0.75 it flags
[metric:killfeed_openset/heldout_gun@weapon-gallery-0.3.0#new_below_floor_unselected=0.9286]
of new guns and
[metric:killfeed_openset/heldout_gun@weapon-gallery-0.3.0#known_below_floor_unselected=0.1429]
of known ones.

On stored rows every refusal is low-score; no row ties
([metric:killfeed_openset/refusals@a06f04a0059f#tie_full=0],
[metric:killfeed_openset/refusals@5822b6646448#tie_full=0],
[metric:killfeed_openset/refusals@4f207c0c4e39#tie_full=0]). Low-score rows:
[metric:killfeed_openset/refusals@a06f04a0059f#low_full=17],
[metric:killfeed_openset/refusals@5822b6646448#low_full=7] and, on the match no
exemplar came from,
[metric:killfeed_openset/refusals@4f207c0c4e39#low_full=128]. They fall into
[metric:killfeed_openset/groups@a06f04a0059f+5822b6646448+4f207c0c4e39#groups=35]
groups; the largest holds
[metric:killfeed_openset/groups@a06f04a0059f+5822b6646448+4f207c0c4e39#largest=114]
rows over about
[metric:killfeed_openset/groups@a06f04a0059f+5822b6646448+4f207c0c4e39#largest_entries=14]
entries of 4f207c0c4e39: an 85 px rifle with a thin dotted barrel that matches
no gallery gun (best Phantom, median
[metric:killfeed_openset/groups@a06f04a0059f+5822b6646448+4f207c0c4e39#largest_median_score=0.697]).
The next, [metric:killfeed_openset/groups@a06f04a0059f+5822b6646448+4f207c0c4e39#second_rows=4]
rows of one a06f04a0059f entry, is a 19 px teal square with a flame, an icon
the gallery lacks, scoring
[metric:killfeed_openset/groups@a06f04a0059f+5822b6646448+4f207c0c4e39#second_median_score=0.747]
against Aftershock, just under the floor.

The player's answers, 2026-10-01
--------------------------------
Group 0 is the Warden, a gun new to the game [domain:weapons/warden]
[domain:killfeed/warden-icon]: the step flagged a genuinely new icon, rightly.
A skin does not explain it, since a skin never changes the killfeed icon
[domain:killfeed/weapon-skin-same-icon].

Group 1 is Aftershock [domain:killfeed/ability-kill-icon], not Phoenix's Hot
Hands: a known ability flagged new, a false new. Its four rows are the late
frames (287.0-288.5 s, slot 1, after the stack rose) of death
`death:a06f04a0059f:284500:2`, whose earlier slot-2 frames the owner named
Aftershock; the stored entry verdict is Aftershock (6 of 10 frames named), so
the false new is per row, not per entry. The stored killer of that entry is
Breach (`identity:...:284500:2:killer`, from `killfeed_name_cluster` and
`killfeed_weapon`; the second rests on this icon, so only the name cluster is
independent of it). The gallery holds no other Breach ability, so narrowing to
the killer's kit leaves Aftershock the only ability candidate; a decision
narrowed that way would accept it and declare that it `rests_on` the killer's
identity. This step narrowed only by the match's agents, never by the
killer's kit. Adding a Warden exemplar and fixing this miss belong to the
labelling pass (step 2).
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reticle import metrics  # noqa: E402
from reticle.adjudication.weapon import (  # noqa: E402
    MINED_NOT_GUN, NAME_ASPECT_TOL, NAME_MARGIN, NAME_MIN_IOU, WEAPON_ADJUDICATION_VERSION,
    WEAPON_GALLERY_VERSION, _icon_index, _name_icon, entry_weapon, mined_gallery_path,
    name_icon, restrict_gallery)
from reticle.killfeed import unpack_icon_grid  # noqa: E402
from reticle.store import Store  # noqa: E402

VERSION = "killfeed-openset-proto-0.1.0"
TASK = "killfeed-openset-20261001"
MIN_ENTRIES = 5               # a name needs this many distinct entries to be scored
FALSE_NEW = 0.05              # the share of known icons the threshold may flag new
SHEET_MIN = 10                # rows a low-score group needs for a contact sheet
FAST = ("a06f04a0059f", "5822b6646448")   # tiers.FAST sessions with killfeed_weapon rows
OUT_OF_GALLERY = ("4f207c0c4e39",)        # a match no gallery exemplar came from
OUT = Store().root / "analysis" / TASK
RECORD = True                 # --dry skips metrics.record


# --------------------------------------------------------------------- gallery

def load_keyed_gallery() -> dict:
    """The owner's mined gallery with its keys, read from the owner's path."""
    z = np.load(mined_gallery_path())
    g = {k: z[k] for k in ("names", "masks", "aspects", "keys", "classes")}
    g["names"] = np.array([str(n) for n in g["names"]])
    g["entry"] = np.array([entry_of(str(k)) for k in g["keys"]])
    g["session"] = np.array([str(k).split(":")[1] for k in g["keys"]])
    return g


def entry_of(key: str) -> str:
    """One kill's id across both key forms: `kf:<sid>:<t>:<slot>` (one mined
    frame) and `death:<sid>:<t>:<slot>#<k>` (up to three labelled frames)."""
    _, sid, t, slot = key.split("#")[0].split(":")
    return f"{sid}:{t}:{slot}"


def category(name: str) -> str:
    c = MINED_NOT_GUN.get(name, "gun")
    return c if c in ("gun", "ability") else "other"


def subset(g: dict, keep: np.ndarray) -> dict:
    return {k: v[keep] for k, v in g.items() if isinstance(v, np.ndarray) and v.ndim >= 1}


def session_agents(sid: str) -> set[str]:
    """The match's agents, both sides, as the death adjudication passes them.
    `load_lineup` takes about 30 s a session, so its answer is kept in
    OUT/lineup_agents.json beside the lineup file's hash; a changed file reloads."""
    import hashlib
    from reticle.lineup import load_lineup
    f = Store().root / "lineups" / f"{sid}.json"
    sha = hashlib.sha256(f.read_bytes()).hexdigest()[:16] if f.is_file() else None
    cache_path = OUT / "lineup_agents.json"
    cache = json.loads(cache_path.read_text()) if cache_path.is_file() else {}
    if sid in cache and cache[sid]["lineup_sha"] == sha:
        return set(cache[sid]["agents"])
    lu = load_lineup(sid, Store().root) or {}
    agents = {r["agent"] for side in (lu.get("sides") or {}).values() for r in side
              if r.get("agent")}
    cache[sid] = {"lineup_sha": sha, "agents": sorted(agents)}
    OUT.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return agents


def auroc(known, new) -> float:
    """P(a known score exceeds a new one), ties counted half."""
    k, n = np.asarray(known, float), np.asarray(new, float)
    if not len(k) or not len(n):
        return float("nan")
    gt = (k[:, None] > n[None, :]).sum()
    eq = (k[:, None] == n[None, :]).sum()
    return float((gt + 0.5 * eq) / (len(k) * len(n)))


def threshold(known) -> float:
    """The score below which FALSE_NEW of known icons fall."""
    return float(np.quantile(np.asarray(known, float), FALSE_NEW))


def separation(rows: list[dict], known_key: str, new_key: str, t: float | None = None) -> dict:
    known = [r[known_key] for r in rows]
    new = [r[new_key] for r in rows]
    t = threshold(known) if t is None else t
    return {"n": len(rows), "names": len({r["name"] for r in rows}),
            "auroc": round(auroc(known, new), 4), "threshold": round(t, 3),
            "known_flagged": round(float(np.mean(np.array(known) < t)), 4),
            "new_flagged": round(float(np.mean(np.array(new) < t)), 4),
            "known_median": round(float(np.median(known)), 3),
            "new_median": round(float(np.median(new)), 3)}


def name_ci(rows: list[dict], known_key: str, new_key: str) -> list[float]:
    """AUROC interval, resampling whole names (icons of one name are not independent)."""
    by = defaultdict(list)
    for r in rows:
        by[r["name"]].append(r)

    def stat(names):
        rs = [r for n in names for r in by[n]]
        return auroc([r[known_key] for r in rs], [r[new_key] for r in rs])
    lo, hi = metrics.bootstrap_ci(sorted(by), stat, n_boot=1000)
    return [round(lo, 4), round(hi, 4)]


def heldout() -> dict:
    g = load_keyed_gallery()
    entries = Counter(n for n, _ in set(zip(g["names"], g["entry"])))
    scored = sorted(n for n, c in entries.items() if c >= MIN_ENTRIES)
    agents = {sid: session_agents(sid) for sid in sorted(set(g["session"]))}
    rows = []
    for name in scored:
        without = subset(g, g["names"] != name)
        idx_new = _icon_index(without)
        idx_new_n: dict[str, dict] = {}
        for i in np.nonzero(g["names"] == name)[0]:
            grid, aspect, sid, ent = g["masks"][i], float(g["aspects"][i]), g["session"][i], g["entry"][i]
            r = {"name": name, "category": category(name), "key": str(g["keys"][i]), "session": sid}
            v = _name_icon(grid, aspect, idx_new)
            r["new"], r["new_best"] = v["score"], v["best"]
            r["known_exemplar"] = name_icon(grid, aspect, subset(g, np.arange(len(g["names"])) != i))["score"]
            r["known"] = name_icon(grid, aspect, subset(g, g["entry"] != ent))["score"]
            k_sess = subset(g, g["session"] != sid)
            r["known_session"] = (name_icon(grid, aspect, k_sess)["score"]
                                  if name in set(k_sess["names"]) else None)
            # Narrowed: the match's lineup drops the abilities nobody there casts.
            if sid not in idx_new_n:
                idx_new_n[sid] = _icon_index(restrict_gallery(without, agents[sid])[0])
            r["new_narrow"] = _name_icon(grid, aspect, idx_new_n[sid])["score"]
            narrow, dropped = restrict_gallery(subset(g, g["entry"] != ent), agents[sid])
            r["own_name_dropped"] = name in dropped
            r["known_narrow"] = name_icon(grid, aspect, narrow)["score"]
            rows.append(r)
    out = {"version": VERSION, "gallery": WEAPON_GALLERY_VERSION,
           "owner": WEAPON_ADJUDICATION_VERSION, "min_entries": MIN_ENTRIES,
           "gallery_size": {c: int(sum(category(n) == c for n in g["names"]))
                            for c in ("gun", "ability", "other")},
           "gallery_names": {c: len({n for n in g["names"] if category(n) == c})
                             for c in ("gun", "ability", "other")},
           "scored_names": scored,
           "unscored_names": sorted(n for n, c in entries.items() if c < MIN_ENTRIES),
           "lineup_agents": {s: len(a) for s, a in agents.items()},
           "results": {}}
    pooled_full = threshold([r["known"] for r in rows])
    pooled_narrow = threshold([r["known_narrow"] for r in rows])
    for cat in ("all", "gun", "ability", "other"):
        rs = [r for r in rows if cat == "all" or r["category"] == cat]
        if not rs:
            continue
        res = {"full": separation(rs, "known", "new"),
               "full_pooled_threshold": separation(rs, "known", "new", pooled_full),
               "narrow": separation(rs, "known_narrow", "new_narrow"),
               "narrow_pooled_threshold": separation(rs, "known_narrow", "new_narrow", pooled_narrow),
               "exemplar_out": separation(rs, "known_exemplar", "new"),
               "own_name_dropped": sum(r["own_name_dropped"] for r in rs)}
        ses = [r for r in rs if r["known_session"] is not None]
        if ses:
            res["session_out"] = separation(ses, "known_session", "new")
        # The `kf:` exemplars were chosen by clustering at IoU >= 0.75, so their
        # known scores are high by construction; the `death:` exemplars are the
        # stored descriptors of labelled entries, taken as the reader wrote them.
        un = [r for r in rs if r["key"].startswith("death:")]
        if un:
            res["unselected"] = separation(un, "known", "new")
            res["unselected_narrow"] = separation(un, "known_narrow", "new_narrow")
            res["unselected_owner_floor"] = separation(un, "known", "new", NAME_MIN_IOU)
            res["all_new_at_unselected_threshold"] = round(float(np.mean(
                [r["new"] < res["unselected"]["threshold"] for r in rs])), 4)
        if len({r["name"] for r in rs}) >= 3:
            res["full"]["auroc_ci_names"] = name_ci(rs, "known", "new")
            res["narrow"]["auroc_ci_names"] = name_ci(rs, "known_narrow", "new_narrow")
        out["results"][cat] = res
    per = {}
    for name in scored:
        rs = [r for r in rows if r["name"] == name]
        per[name] = {"n": len(rs), "category": rs[0]["category"],
                     "known_median": round(float(np.median([r["known"] for r in rs])), 3),
                     "new_median": round(float(np.median([r["new"] for r in rs])), 3),
                     "new_flagged": round(float(np.mean([r["new"] < pooled_full for r in rs])), 3),
                     "nearest_when_new": Counter(r["new_best"] for r in rs).most_common(2),
                     "own_name_dropped": sum(r["own_name_dropped"] for r in rs)}
    out["per_name"] = per
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "heldout_rows.json").write_text(json.dumps(rows, indent=0), encoding="utf-8")
    (OUT / "heldout.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    deps = {"gallery": WEAPON_GALLERY_VERSION, "owner": WEAPON_ADJUDICATION_VERSION,
            "code": metrics.fingerprint(heldout, separation, auroc, threshold, min_entries=MIN_ENTRIES,
                                        false_new=FALSE_NEW)}
    for cat, res in out["results"].items():
        vals = {"auroc_full": res["full"]["auroc"], "new_at_5_full": res["full"]["new_flagged"],
                "auroc_narrow": res["narrow"]["auroc"], "new_at_5_narrow": res["narrow"]["new_flagged"],
                "auroc_exemplar_out": res["exemplar_out"]["auroc"],
                "threshold_full": res["full"]["threshold"], "n": res["full"]["n"],
                "names": res["full"]["names"], "own_name_dropped": res["own_name_dropped"]}
        if cat == "all":
            vals.update({f"gallery_{c}": n for c, n in out["gallery_size"].items()})
        if "session_out" in res:
            vals["auroc_session_out"] = res["session_out"]["auroc"]
        if "unselected" in res:
            vals.update(auroc_unselected=res["unselected"]["auroc"],
                        new_at_5_unselected=res["unselected"]["new_flagged"],
                        threshold_unselected=res["unselected"]["threshold"],
                        n_unselected=res["unselected"]["n"],
                        auroc_unselected_narrow=res["unselected_narrow"]["auroc"],
                        new_at_5_unselected_narrow=res["unselected_narrow"]["new_flagged"],
                        known_below_floor_unselected=res["unselected_owner_floor"]["known_flagged"],
                        new_below_floor_unselected=res["unselected_owner_floor"]["new_flagged"],
                        all_new_at_unselected_threshold=res["all_new_at_unselected_threshold"])
        if RECORD:
            metrics.record("killfeed_openset", part=f"heldout_{cat}", session="weapon-gallery-0.3.0",
                           values=vals, deps=deps, note=f"{TASK}: new = whole name left out")
    return out


# -------------------------------------------------------------------- refusals

def _rows(sid: str) -> list[dict]:
    return [o for o in Store().read_events("killfeed_weapon", sid)
            if o.get("kind") == "weapon_icon_observation" and o.get("grid")]


def _entry_split(sid: str, obs: list[dict], gallery: dict, agents: set[str], index: dict) -> Counter:
    """Production's unit: each counted entry named by `entry_weapon`; a refused
    entry is split by its bound frames' own reasons."""
    from reticle.adjudication.death import session_entries
    from reticle.adjudication.weapon import bind_entry
    from weapon_icons import _hud
    c = Counter()
    for e in session_entries(_hud(sid)):
        v = entry_weapon(e, obs, gallery=gallery, agents=agents or None)
        if v["status"] == "resolved":
            c["resolved"] += 1
            continue
        reasons = Counter(_name_icon(unpack_icon_grid(o["grid"]), o["aspect"], index).get("reason")
                          or "named" for o in bind_entry(e, obs))
        top = reasons.most_common(1)[0][0] if reasons else "no_observation"
        c[f"refused:{v['reason']}:frames_mostly_{top}"] += 1
    return c


def split_refusals(sids: list[str]) -> dict:
    from weapon_icons import cluster
    gal = load_keyed_gallery()
    full = {k: gal[k] for k in ("names", "masks", "aspects")}
    held = json.loads((OUT / "heldout.json").read_text())["results"]["all"]
    t_full, t_un = held["full"]["threshold"], held["unselected"]["threshold"]
    low, summary = [], {}
    for sid in sids:
        obs = _rows(sid)
        agents = session_agents(sid)
        narrow, dropped = restrict_gallery(full, agents)
        idx_f, idx_n = _icon_index(full), _icon_index(narrow)
        s = {"rows": len(obs), "lineup_agents": sorted(agents), "dropped_names": dropped}
        for label, idx in (("full", idx_f), ("narrow", idx_n)):
            c = Counter()
            for o in obs:
                v = _name_icon(unpack_icon_grid(o["grid"]), o["aspect"], idx)
                c[v.get("reason") or "named"] += 1
                if label == "narrow":
                    c["below_threshold_full"] += v["score"] < t_full
                    c["below_threshold_unselected"] += v["score"] < t_un
                    if v.get("reason") == "no_close_exemplar":
                        low.append(dict(o, best=v["best"], score=v["score"]))
            s[label] = dict(c)
        s["entries_narrow"] = dict(_entry_split(sid, obs, full, agents, idx_n))
        summary[sid] = s
    # Group the low-score rows of every session by mutual similarity.
    bms = np.array([unpack_icon_grid(r["grid"]) for r in low]) if low else np.zeros((0, 16, 64))
    for i, r in enumerate(low):
        r["icon"] = i
    have = cluster(low, bms) if low else []
    groups = defaultdict(list)
    for r in have:
        groups[r["cluster"]].append(r)
    glist = []
    for c, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        glist.append({"group": c, "rows": len(rs), "episodes": _episodes(rs),
                      "sessions": dict(Counter(r["session_id"] for r in rs)),
                      "best": Counter(r["best"] for r in rs).most_common(2),
                      "median_score": round(float(np.median([r["score"] for r in rs])), 3),
                      "aspect_median": round(float(np.median([r["aspect"] for r in rs])), 2)})
    sizes = [g["rows"] for g in glist]
    out = {"version": VERSION, "gallery": WEAPON_GALLERY_VERSION, "sessions": summary,
           "threshold_full": t_full, "threshold_unselected": t_un, "low_rows": len(low), "groups": len(glist),
           "group_sizes": sizes, "groups_ge_sheet_min": sum(n >= SHEET_MIN for n in sizes),
           "singletons": sum(n == 1 for n in sizes), "group_table": glist[:40]}
    sheets = []
    for k, g in enumerate(glist):
        if g["rows"] >= SHEET_MIN or (k < 3 and g["rows"] > 1):
            sheets.append(str(contact_sheet(g, groups[g["group"]], gal)))
    out["sheets"] = sheets
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "refusals.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    deps = {"gallery": WEAPON_GALLERY_VERSION, "owner": WEAPON_ADJUDICATION_VERSION,
            "code": metrics.fingerprint(split_refusals, _entry_split, cluster)}
    for sid, s in summary.items():
        if not RECORD:
            break
        metrics.record("killfeed_openset", part="refusals", session=sid,
                       values={"rows": s["rows"],
                               "low_full": s["full"].get("no_close_exemplar", 0),
                               "tie_full": s["full"].get("tie", 0),
                               "low_narrow": s["narrow"].get("no_close_exemplar", 0),
                               "tie_narrow": s["narrow"].get("tie", 0),
                               "named_narrow": s["narrow"].get("named", 0)},
                       deps=deps, note=f"{TASK}: owner's reasons over stored rows")
    if RECORD:
        metrics.record("killfeed_openset", part="groups", session="+".join(sids),
                       values={"low_rows": len(low), "groups": len(glist),
                               "groups_ge_10": out["groups_ge_sheet_min"],
                               "largest": sizes[0] if sizes else 0,
                               "largest_entries": glist[0]["episodes"] if glist else 0,
                               "largest_median_score": glist[0]["median_score"] if glist else 0,
                               "second_rows": sizes[1] if len(sizes) > 1 else 0,
                               "second_median_score": glist[1]["median_score"] if len(glist) > 1 else 0,
                               "singletons": out["singletons"]},
                       deps=deps, note=f"{TASK}: weapon_icons.cluster over narrow low-score rows")
    return out


def _episodes(rs: list[dict]) -> int:
    """Roughly the entries behind a group's rows: runs of frames no more than
    1 s apart, each counting as many entries as it shows at once."""
    n = 0
    for sid in {r["session_id"] for r in rs}:
        ts = sorted(r["t_ms"] for r in rs if r["session_id"] == sid)
        run = [ts[0]]
        for t in ts[1:] + [None]:
            if t is not None and t - run[-1] <= 1000:
                run.append(t)
                continue
            n += max(Counter(run).values())
            run = [t]
    return n


def _crops(rs: list[dict]) -> dict[int, np.ndarray]:
    """Each row's killfeed icon crop from the session's crop cache, keyed by id."""
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    store = Store()
    got = {}
    for sid in sorted({r["session_id"] for r in rs}):
        man = store.read_manifest(sid)
        cache, why = RoiCache.load(store.root, man, get_profile(man.get("source_profile", "valorant-16x9")))
        if cache is None:
            continue
        x0, y0, _, _ = cache.rect_of("killfeed")
        mine = [r for r in rs if r["session_id"] == sid]
        by_t = defaultdict(list)
        for r in mine:
            by_t[float(r["t_ms"])].append(r)
        for smp in cache.samples(sorted(by_t), rois="killfeed"):
            for r in by_t[smp.t_ms]:
                got[id(r)] = smp.frame[y0 + r["y0"]:y0 + r["y1"], x0 + r["wx0"]:x0 + r["wx1"]].copy()
    return got


def _cell(img: np.ndarray, w: int = 192, h: int = 48) -> np.ndarray:
    if img.ndim == 2:
        img = cv2.cvtColor((img * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    s = min(w / img.shape[1], h / img.shape[0])
    r = cv2.resize(img, (max(1, int(img.shape[1] * s)), max(1, int(img.shape[0] * s))),
                   interpolation=cv2.INTER_NEAREST)
    out = np.full((h, w, 3), 40, np.uint8)
    out[:r.shape[0], :r.shape[1]] = r
    return out


def contact_sheet(g: dict, rs: list[dict], gal: dict, per: int = 12) -> Path:
    """Members spread over the group's similarity to its leader: the stored
    grid above the cached crop; the first column is the nearest gallery
    exemplar of the group's most frequent best name."""
    rs = sorted(rs, key=lambda r: -r["leader_iou"])
    pick = [rs[int(k)] for k in np.linspace(0, len(rs) - 1, min(per, len(rs)))]
    crops = _crops(pick)
    name = g["best"][0][0]
    lead = next(r for r in rs if r.get("leader")) if any(r.get("leader") for r in rs) else rs[0]
    lg = unpack_icon_grid(lead["grid"]).reshape(-1).astype(np.float32)
    cand = np.nonzero(gal["names"] == name)[0]
    m = gal["masks"][cand].reshape(len(cand), -1).astype(np.float32)
    iou = (m @ lg) / np.maximum(m.sum(1) + lg.sum() - m @ lg, 1)
    ex = gal["masks"][cand[int(iou.argmax())]]
    head = np.full((48, 192, 3), 40, np.uint8)
    cv2.putText(head, f"#{g['group']} rows={g['rows']} ent~{g['episodes']}", (3, 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
    cv2.putText(head, f"best {name} med {g['median_score']}", (3, 34),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 220, 160), 1)
    top = [head] + [_cell(unpack_icon_grid(r["grid"])) for r in pick]
    bottom = [_cell(ex)] + [_cell(crops[id(r)]) if id(r) in crops else _cell(np.zeros((16, 64)))
                            for r in pick]
    cap = [np.full((16, 192, 3), 20, np.uint8) for _ in range(len(pick) + 1)]
    cv2.putText(cap[0], f"gallery {name}", (3, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 120), 1)
    for c, r in zip(cap[1:], pick):
        cv2.putText(c, f"{r['session_id'][:6]} {r['t_ms'] / 1000:.1f}s s{r['slot']} {r['score']:.2f}",
                    (3, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (200, 200, 200), 1)
    sheet = np.vstack([np.hstack(top), np.hstack(bottom), np.hstack(cap)])
    path = OUT / f"group_{g['group']:03d}_{g['rows']}rows.png"
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), sheet)
    return path


def main() -> None:
    global RECORD
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="measure without recording metrics")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("heldout")
    r = sub.add_parser("refusals")
    r.add_argument("sids", nargs="*", default=list(FAST + OUT_OF_GALLERY))
    a = ap.parse_args()
    RECORD = not a.dry
    out = heldout() if a.cmd == "heldout" else split_refusals(a.sids)
    print(json.dumps({k: v for k, v in out.items() if k not in ("per_name", "group_table")}, indent=1))


if __name__ == "__main__":
    main()
