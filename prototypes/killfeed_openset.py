r"""Open-set killfeed icons: can the owner tell a new icon from a known one, and narrow by role?

    .\.venv\Scripts\python.exe prototypes\killfeed_openset.py heldout
    .\.venv\Scripts\python.exe prototypes\killfeed_openset.py refusals [sid ...]

Step 2 (role narrowing in the owner, groups of new rows):

    .\.venv\Scripts\python.exe prototypes\killfeed_openset.py kitnull
    .\.venv\Scripts\python.exe prototypes\killfeed_openset.py tiered
    .\.venv\Scripts\python.exe prototypes\killfeed_openset.py entries [sid ...]
    .\.venv\Scripts\python.exe prototypes\killfeed_openset.py groups [sid ...]
    .\.venv\Scripts\python.exe prototypes\killfeed_openset.py check <product>

`adjudication.weapon.name_icon` [owns:killfeed-weapon] scores an icon by its
best aspect-gated IoU over the mined gallery and refuses below NAME_MIN_IOU
(`no_close_exemplar`; `new` since weapon-adjudication-0.6.0) or under
NAME_MARGIN (`tie`; now `ambiguous`). This prototype measures whether that
score separates a NEW icon (its name absent from the gallery)
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

Step 2, 2026-10-01 (weapon-adjudication-0.7.0)
----------------------------------------------
The owner now narrows by role [domain:killfeed/entry-types]: the acting
agent's kit (`adjudication.death.entry_actor`, the arbiter over the left
name's claims without the icon's), then the match's agents, then the full
gallery as the surprise path. `kitnull` set the kit floor: no ability icon
scores above
[metric:killfeed_openset/kit_null@weapon-gallery-0.3.0#null_max_ability=0.513]
against another agent's abilities, so an ability-shaped kit name needs 0.52;
gun-shaped abilities keep 0.75, since a Sheriff reaches
[metric:killfeed_openset/kit_null@weapon-gallery-0.3.0#null_max_gun_shaped=0.82]
against Headhunter.

`tiered` reruns the held-out test with each icon decided by the tiers (its
caster as actor), scoring the best name's IoU minus that name's floor; the
before column is the 0.75 floor alone, so it differs from step 1's raw
score. On the unselected `death:` icons the AUROC stays
[metric:killfeed_openset/tiered_all_unselected@weapon-gallery-0.3.0#auroc_after=0.9925]
(before [metric:killfeed_openset/tiered_all_unselected@weapon-gallery-0.3.0#auroc_before=0.9925])
and new-at-5% rises to
[metric:killfeed_openset/tiered_all_unselected@weapon-gallery-0.3.0#new_flagged_after=1.0]
(before [metric:killfeed_openset/tiered_all_unselected@weapon-gallery-0.3.0#new_flagged_before=0.9728]);
known icons refused new fall from
[metric:killfeed_openset/tiered_all_unselected@weapon-gallery-0.3.0#known_refused_new_before=0.0612]
to [metric:killfeed_openset/tiered_all_unselected@weapon-gallery-0.3.0#known_refused_new_after=0.0272].
Held-out ability names named as some known name stay
[metric:killfeed_openset/tiered_ability_all@weapon-gallery-0.3.0#new_named_after=0.1111]
over all exemplars, as before: Headhunter held out reads as a Sheriff, a
gun-shaped confusion the kit floor does not touch.

`entries` compares weapon-adjudication-0.5.0 with this owner on stored rows:
no entry changes. a06f04a0059f names
[metric:killfeed_openset/entries@a06f04a0059f#named_after=179] entries before
and after, 5822b6646448
[metric:killfeed_openset/entries@5822b6646448#named_after=170] and
4f207c0c4e39 [metric:killfeed_openset/entries@4f207c0c4e39#named_after=159]
(no stored death verdicts there, so no actor). No entry took the surprise
path ([metric:killfeed_openset/entries@a06f04a0059f#surprise=0]), and every
audited entry agrees with the full search
([metric:killfeed_openset/entries@a06f04a0059f#audit_agrees=17],
[metric:killfeed_openset/entries@5822b6646448#audit_agrees=13],
[metric:killfeed_openset/entries@4f207c0c4e39#audit_agrees=24]). Breach's
Aftershock at 284.5 s keeps its name; its
[metric:killfeed_openset/entries@a06f04a0059f#kit_floor_frames=4] frames at
287.0-288.5 s are now named Aftershock by the kit floor and rest on the
killer, but the entry's name stood on six frames without the kit, so the
entry rests on the lineup alone.

`groups` writes the product the labeller reads
(`<store>/candidates/killfeed_new_icon/`): of
[metric:killfeed_openset/new_groups@a06f04a0059f+5822b6646448+4f207c0c4e39#rows_read=5174]
rows, [metric:killfeed_openset/new_groups@a06f04a0059f+5822b6646448+4f207c0c4e39#rows_new=140]
refuse new, in
[metric:killfeed_openset/new_groups@a06f04a0059f+5822b6646448+4f207c0c4e39#groups=26]
groups. Every row of the Warden entries refuses new
([metric:killfeed_openset/warden_group@4f207c0c4e39#warden_refused_new=98]), and
the largest group holds
[metric:killfeed_openset/warden_group@4f207c0c4e39#warden_share_largest=0.9694]
of them; the Aftershock rows are in no group
([metric:killfeed_openset/warden_group@4f207c0c4e39#aftershock_rows_grouped=0]).

Step 3 (the player's labels, 2026-10-01):

    .\.venv\Scripts\python.exe prototypes\killfeed_openset.py faults <product> <labels>

The player named [metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#rows=16] groups no icon ("Most of them were bad crops",
"or not even on a killfeed entry at all"). `faults` draws each exemplar's box
on the crop cache (`<store>/analysis/killfeed-openset-20261001/crop_faults/`)
and reads causes by eye: [metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#cause_not_on_entry=4] boxes on no entry,
[metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#cause_left_of_entry=2] left of the killer portrait,
[metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#cause_spans_killer_name=3] spanning the killer's name and the gun,
[metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#cause_truncated=4] cut pieces of an icon, [metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#cause_band_shifted=2] on a band
placed above the entry, and [metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#cause_faint=1] fading in. The box is
`killfeed._band_text`'s [owns:killfeed-weapon-descriptor]; no cross-reference
gates it. Each row trips at least one channel the reader does not use
([metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#caught_any=16]): every not-on-entry row has no killer name
([metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#not_on_entry__killer_name_unread=4]) and most have no counted track
([metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#not_on_entry__no_counted_track=3]); the band-shifted rows sit off the killer
portrait's top ([metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#band_shifted__band_off_portrait=2]); every truncated row is
its track's first or last frame ([metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#truncated__track_edge=4]). Only
[metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#bound_to_entry=7] rows bind to an entry the owner names.
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
    MINED_NOT_GUN, NAME_ASPECT_TOL, NAME_MARGIN, NAME_MIN_IOU, REFUSE_AMBIGUOUS, REFUSE_NEW,
    WEAPON_ADJUDICATION_VERSION,
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
                    if v.get("reason") == REFUSE_NEW:
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
                               "low_full": s["full"].get(REFUSE_NEW, 0),
                               "tie_full": s["full"].get(REFUSE_AMBIGUOUS, 0),
                               "low_narrow": s["narrow"].get(REFUSE_NEW, 0),
                               "tie_narrow": s["narrow"].get(REFUSE_AMBIGUOUS, 0),
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


# ---------------------------------------------------------------------- step 2

STEP2 = "killfeed-openset-proto-0.2.0"
#: The product `groups` writes and `label_killfeed_groups.py` reads.
GROUPS_VERSION = "killfeed-new-icon-groups-0.1.0"
GROUPS_DIR = Store().root / "candidates" / "killfeed_new_icon"
BEFORE_COMMIT = "692b683"     # master before step 2: weapon-adjudication-0.5.0
MEMBERS_KEPT = 24             # members a group's product row lists, spread by similarity


def kitnull() -> dict:
    """The kit floor's null: how high an icon of one agent's kit scores
    against another agent's abilities alone.

    `null_max_ability` (pre-registered) scores every ability-category gallery
    icon against each other agent's ability exemplars. `null_max_gun_shaped`
    and `null_max_ability_shaped` hold each name out of the gallery, narrow to
    another agent's kit tier (guns, unattributed names and that agent's
    abilities, `restrict_gallery`) and keep the cases where a kit ability
    ranks first, split by whether that ability's exemplars are ability-shaped
    (`kit_names`). `known_kit_*` scores each ability icon against its own
    kit tier with its entry held out."""
    from reticle.adjudication.weapon import ability_agent, kit_names
    g = load_keyed_gallery()
    names = g["names"]
    agents = sorted({ability_agent(str(n)) for n in names if ability_agent(str(n))})
    is_ab = np.array([ability_agent(str(n)) is not None for n in names])
    alone = {a: _icon_index(subset(g, np.array([ability_agent(str(n)) == a for n in names])))
             for a in agents}
    pre = []
    for i in np.nonzero([category(str(n)) == "ability" for n in names])[0]:
        own = ability_agent(str(names[i]))
        for a in agents:
            if a != own:
                pre.append(_name_icon(g["masks"][i], float(g["aspects"][i]), alone[a])["score"])
    shaped = {a: kit_names(g, a) for a in agents}
    held = {"gun_shaped": [], "ability_shaped": []}
    for nm in sorted(set(names.tolist())):
        own = ability_agent(nm)
        for a in agents:
            if a == own:
                continue
            keep = (names != nm) & (~is_ab | np.array([ability_agent(str(n)) == a for n in names]))
            ix = _icon_index(subset(g, keep))
            for i in np.nonzero(names == nm)[0]:
                v = _name_icon(g["masks"][i], float(g["aspects"][i]), ix)
                if ability_agent(v["best"]) == a:
                    held["ability_shaped" if v["best"] in shaped[a] else "gun_shaped"].append(
                        (v["score"], nm, v["best"], str(g["keys"][i])))
    known = []
    for i in np.nonzero(is_ab)[0]:
        a, ent = ability_agent(str(names[i])), g["entry"][i]
        keep = (g["entry"] != ent) & (~is_ab | np.array([ability_agent(str(n)) == a for n in names]))
        v = _name_icon(g["masks"][i], float(g["aspects"][i]), _icon_index(subset(g, keep)),
                       shaped[a])
        known.append((v["score"], str(names[i]), v.get("name"), v.get("reason")))
    from reticle.adjudication.weapon import NAME_KIT_MIN_IOU
    out = {"version": STEP2, "gallery": WEAPON_GALLERY_VERSION, "kits": {
               a: sorted({str(n) for n in names if ability_agent(str(n)) == a}) for a in agents},
           "ability_shaped": {a: sorted(s) for a, s in shaped.items()},
           "null_n_ability": len(pre), "null_max_ability": round(float(max(pre)), 3),
           "null_q99_ability": round(float(np.quantile(pre, 0.99)), 3)}
    for k, rows in held.items():
        rows.sort(reverse=True)
        out[f"null_n_{k}"] = len(rows)
        out[f"null_max_{k}"] = rows[0][0] if rows else None
        out[f"null_top_{k}"] = rows[:5]
    ks = [s for s, n, _, _ in known if n in {x for a in shaped for x in shaped[a]}]
    out["known_n_shaped"] = len(ks)
    out["known_shaped_below_kit_floor"] = round(float(np.mean(np.array(ks) < NAME_KIT_MIN_IOU)), 4)
    out["known_shaped_below_floor"] = round(float(np.mean(np.array(ks) < NAME_MIN_IOU)), 4)
    out["known_named"] = dict(Counter(f"{n}->{got or why}" for _, n, got, why in known))
    if RECORD:
        metrics.record("killfeed_openset", part="kit_null", session=WEAPON_GALLERY_VERSION,
                       values={k: out[k] for k in (
                           "null_n_ability", "null_max_ability", "null_q99_ability",
                           "null_n_gun_shaped", "null_max_gun_shaped", "null_n_ability_shaped",
                           "null_max_ability_shaped", "known_n_shaped",
                           "known_shaped_below_kit_floor", "known_shaped_below_floor")},
                       deps={"gallery": WEAPON_GALLERY_VERSION,
                             "code": metrics.fingerprint(kitnull)},
                       note=f"{TASK}: the kit floor's null, pre-registered as S1")
    return out


def _floor_of(name: str, kit: frozenset) -> float:
    from reticle.adjudication.weapon import NAME_KIT_MIN_IOU
    return NAME_KIT_MIN_IOU if name in kit else NAME_MIN_IOU


def _tiered_score(grid, aspect, tiers) -> dict:
    """The owner's tiered answer for one icon, with its score over the floor of
    the name it ranked first at the deciding tier (negative: refused new)."""
    from reticle.adjudication.weapon import name_frame
    v = name_frame(grid, aspect, tiers)
    kit = next((t["kit"] for t in tiers if t["tier"] == v["tier"]), frozenset())
    return dict(v, over=round(v["score"] - _floor_of(v["best"], kit), 4))


def heldout_tiered() -> dict:
    """Step 1's held-out experiment through the owner's tiers.

    Before: the lineup tier alone at NAME_MIN_IOU (weapon-adjudication-0.6.0).
    After: kit, lineup, then full (0.7.0), the actor being the ability's own
    caster for an ability icon and the stored entry's icon-free actor
    (`entry_actor`) for a labelled `death:` gun; a `kf:` gun has no actor.
    Score: the deciding name's score minus its floor. Known = entry left
    out; new = name left out."""
    from reticle.adjudication.weapon import ability_agent, candidate_tiers
    g = load_keyed_gallery()
    entries = Counter(n for n, _ in set(zip(g["names"], g["entry"])))
    scored = sorted(n for n, c in entries.items() if c >= MIN_ENTRIES)
    agents = {sid: session_agents(sid) for sid in sorted(set(g["session"]))}
    actors = {sid: stored_actors(sid) for sid in sorted(set(g["session"]))}
    rows = []
    for name in scored:
        without = subset(g, g["names"] != name)
        for i in np.nonzero(g["names"] == name)[0]:
            grid, aspect, sid, ent = g["masks"][i], float(g["aspects"][i]), g["session"][i], g["entry"][i]
            key = str(g["keys"][i])
            caster = ability_agent(name)
            if caster:
                actor = {"agent": caster, "entity_id": "caster"}
            else:
                did = "death:" + key.split("#")[0].split(":", 1)[1] if key.startswith("death:") else None
                actor = (actors[sid].get(did) or {}).get("actor") if did else None
            r = {"name": name, "category": category(name), "key": key, "session": sid,
                 "actor": (actor or {}).get("agent")}
            known_g = subset(g, g["entry"] != ent)
            for label, gal in (("known", known_g), ("new", without)):
                before = name_frame_before(grid, aspect, gal, agents[sid])
                after = _tiered_score(grid, aspect, candidate_tiers(gal, agents[sid] or None, actor))
                r[f"{label}_before"], r[f"{label}_before_named"] = before["over"], before["name"]
                r[f"{label}_after"], r[f"{label}_after_named"] = after["over"], after["name"]
                r[f"{label}_after_tier"] = after["tier"]
            rows.append(r)
    out = {"version": STEP2, "gallery": WEAPON_GALLERY_VERSION, "owner": WEAPON_ADJUDICATION_VERSION,
           "results": {}}
    for cat in ("all", "gun", "ability"):
        for subset_name, keep in (("all", lambda r: True),
                                  ("unselected", lambda r: r["key"].startswith("death:"))):
            rs = [r for r in rows if (cat == "all" or r["category"] == cat) and keep(r)]
            if not rs:
                continue
            res = {}
            for when in ("before", "after"):
                s = separation(rs, f"known_{when}", f"new_{when}")
                s["known_refused_new"] = round(float(np.mean([r[f"known_{when}"] < 0 for r in rs])), 4)
                s["new_named"] = round(float(np.mean([r[f"new_{when}_named"] is not None
                                                      for r in rs])), 4)
                s["known_named_right"] = round(float(np.mean([r[f"known_{when}_named"] == r["name"]
                                                              for r in rs])), 4)
                res[when] = s
            res["new_named_after_by_tier"] = dict(Counter(
                r["new_after_tier"] for r in rs if r["new_after_named"] is not None))
            out["results"][f"{cat}/{subset_name}"] = res
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "heldout_tiered_rows.json").write_text(json.dumps(rows, indent=0), encoding="utf-8")
    (OUT / "heldout_tiered.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    if RECORD:
        deps = {"gallery": WEAPON_GALLERY_VERSION, "owner": WEAPON_ADJUDICATION_VERSION,
                "code": metrics.fingerprint(heldout_tiered, _tiered_score, separation)}
        for k, res in out["results"].items():
            vals = {"n": res["after"]["n"]}
            for when in ("before", "after"):
                for m in ("auroc", "new_flagged", "known_refused_new", "new_named",
                          "known_named_right", "threshold"):
                    vals[f"{m}_{when}"] = res[when][m]
            metrics.record("killfeed_openset", part=f"tiered_{k.replace('/', '_')}",
                           session=WEAPON_GALLERY_VERSION, values=vals, deps=deps,
                           note=f"{TASK}: held-out icons through the owner's tiers, "
                                f"score over the deciding name's floor")
    return out


def name_frame_before(grid, aspect, gallery, agents) -> dict:
    """weapon-adjudication-0.6.0's answer: the lineup's set alone at NAME_MIN_IOU."""
    g = restrict_gallery(gallery, agents)[0] if agents else gallery
    v = _name_icon(grid, aspect, _icon_index(g))
    return dict(v, over=round(v["score"] - NAME_MIN_IOU, 4))


def stored_actors(sid: str) -> dict[str, dict]:
    """{death id: {"actor", "row"}} from the session's stored death verdicts:
    the acting agent `adjudication.death.entry_actor` names from each verdict's
    stored killer claims without the icon's. Empty when no verdict is stored."""
    from reticle.adjudication.death import entry_actor
    out = {}
    for row in Store().read_events("death", sid):
        if row.get("kind") != "death_verdict":
            continue
        ki = (row.get("metadata") or {}).get("killer_identity")
        out[row["death_id"]] = {"actor": entry_actor(row, ki, row.get("is_second_life")),
                                "row": row}
    return out


def owner_before():
    """`adjudication.weapon` as master held it before step 2 (BEFORE_COMMIT),
    loaded beside the current one for the before/after comparison."""
    import importlib.util
    import subprocess
    src = subprocess.run(["git", "show", f"{BEFORE_COMMIT}:reticle/adjudication/weapon.py"],
                         capture_output=True, text=True, check=True,
                         cwd=Path(__file__).resolve().parents[1]).stdout
    spec = importlib.util.spec_from_loader("reticle.adjudication._weapon_before", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "reticle.adjudication"
    sys.modules[spec.name] = mod
    exec(compile(src, f"{BEFORE_COMMIT}:weapon.py", "exec"), mod.__dict__)
    return mod


def compare_entries(sids: list[str]) -> dict:
    """Each entry named before (BEFORE_COMMIT's owner, lineup only) and after
    (this owner: kit, lineup, full; the actor from the stored verdicts), per
    session; every change listed with both answers."""
    from reticle.adjudication.death import death_key, session_entries
    from reticle.adjudication.weapon import entry_weapon, load_mined_gallery
    from weapon_icons import _hud
    old = owner_before()
    gal = load_mined_gallery()
    out = {"version": STEP2, "before": old.WEAPON_ADJUDICATION_VERSION,
           "after": WEAPON_ADJUDICATION_VERSION, "sessions": {}, "changes": []}
    for sid in sids:
        obs, agents, actors = _rows(sid), session_agents(sid), stored_actors(sid)
        c = Counter()
        for e in session_entries(_hud(sid)):
            did = death_key(sid, e["t_ms"], e["slot"])
            actor = (actors.get(did) or {}).get("actor")
            b = old.entry_weapon(e, obs, gallery=gal, agents=agents or None)
            a = entry_weapon(e, obs, gallery=gal, agents=agents or None, actor=actor, key=did)
            c["entries"] += 1
            c["stored_verdict"] += did in actors
            c["actor"] += actor is not None
            c["named_before"] += b["status"] == "resolved"
            c["named_after"] += a["status"] == "resolved"
            c[f"after_{a['status']}:{a['reason']}"] += 1
            c["rests_on_actor"] += any(x["context"] == "actor" for x in a.get("rests_on", []))
            c["kit_floor_entries"] += bool(a.get("kit_floor_frames"))
            c["kit_floor_frames"] += a.get("kit_floor_frames", 0)
            c["surprise"] += bool(a.get("surprise"))
            c["surprise_frames_kept_apart"] += bool(a.get("surprise_frames")) and not a.get("surprise")
            if "audit" in a:
                c["audited"] += 1
                c["audit_agrees"] += a["audit"]["agrees"]
                if not a["audit"]["agrees"]:
                    out.setdefault("audit_disagreements", []).append(
                        {"death_id": did, "narrowed": [a["status"], a["name"], a["reason"]],
                         "full": [a["audit"]["status"], a["audit"]["name"], a["audit"]["reason"]]})
            if (b["status"], b["name"]) != (a["status"], a["name"]) or a.get("surprise"):
                out["changes"].append({
                    "death_id": did, "t_last": e["t_last"],
                    "before": [b["status"], b["name"], b.get("reason"), b.get("names")],
                    "after": [a["status"], a["name"], a.get("reason"), a.get("names")],
                    "actor": (actor or {}).get("agent"), "rests_on": a.get("rests_on"),
                    "tiers": a.get("tiers"), "surprise": a.get("surprise"),
                    "lost": b["status"] == "resolved" and a["status"] != "resolved"})
        out["sessions"][sid] = dict(c)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "compare_entries.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    if RECORD:
        deps = {"gallery": WEAPON_GALLERY_VERSION, "owner": WEAPON_ADJUDICATION_VERSION,
                "before": out["before"], "code": metrics.fingerprint(compare_entries)}
        for sid, c in out["sessions"].items():
            metrics.record("killfeed_openset", part="entries", session=sid, deps=deps,
                           values={k: c.get(k, 0) for k in (
                               "entries", "stored_verdict", "actor", "named_before", "named_after",
                               "rests_on_actor", "kit_floor_entries", "kit_floor_frames",
                               "surprise", "audited", "audit_agrees")},
                           note=f"{TASK}: entries named before and after role narrowing")
    return out


def group_new_rows(sids: list[str]) -> Path:
    """The product `label_killfeed_groups.py` reads: every stored row of the
    given sessions that the owner refuses as new, grouped across sessions.

    A bound row takes its entry's context (`entry_weapon(..., frames=True)`,
    the actor from the stored verdicts); a row bound to no counted entry is
    named with the lineup and the full gallery only. Rows of an entry the
    owner NAMED are left out even when one frame refused: the entry is known.

    Similarity rule: `weapon_icons.cluster`, leader clustering over the
    stored 16x64 grids, two icons joined at IoU >= SAME_ICON (0.75) with
    |log aspect ratio| within ASPECT_TOL (0.12), the icon with most
    neighbours leading each group. Each group lists its size, sessions,
    times, an exemplar (the leader) and up to MEMBERS_KEPT members spread
    over their similarity to the leader."""
    import hashlib
    from reticle.adjudication.death import death_key, session_entries
    from reticle.adjudication.weapon import (REFUSE_NEW, candidate_tiers, entry_weapon,
                                             load_mined_gallery, name_frame)
    from weapon_icons import ASPECT_TOL, SAME_ICON, _hud, cluster
    gal = load_mined_gallery()
    new, seen = [], 0
    for sid in sids:
        obs, agents, actors = _rows(sid), session_agents(sid), stored_actors(sid)
        by_key = {(o["t_ms"], o["slot"]): o for o in obs}
        bound = set()
        for e in session_entries(_hud(sid)):
            did = death_key(sid, e["t_ms"], e["slot"])
            v = entry_weapon(e, obs, gallery=gal, agents=agents or None,
                             actor=(actors.get(did) or {}).get("actor"), key=did, frames=True)
            for f in v.get("frames", []):
                bound.add((f["t_ms"], f["slot"]))
                if v["status"] != "resolved" and f["reason"] == REFUSE_NEW:
                    o = by_key[(f["t_ms"], f["slot"])]
                    new.append(dict(o, death_id=did, entry_status=v["status"],
                                    entry_reason=v["reason"], best=f["best"],
                                    score=f["score"]))
        tiers = candidate_tiers(gal, agents or None)
        for o in obs:
            seen += 1
            if (o["t_ms"], o["slot"]) in bound:
                continue
            f = name_frame(unpack_icon_grid(o["grid"]), o["aspect"], tiers)
            if f.get("reason") == REFUSE_NEW:
                new.append(dict(o, death_id=None, entry_status=None, entry_reason=None,
                                best=f["best"], score=f["score"]))
    bms = np.array([unpack_icon_grid(r["grid"]) for r in new]) if new else np.zeros((0, 16, 64))
    for i, r in enumerate(new):
        r["icon"] = i
    have = cluster(new, bms) if new else []
    groups = defaultdict(list)
    for r in have:
        groups[r["cluster"]].append(r)
    keep = ("session_id", "t_ms", "slot", "frame_idx", "y0", "y1", "wx0", "wx1", "aspect",
            "grid", "best", "score", "death_id", "entry_reason", "leader_iou")
    rows = []
    for k, (c, rs) in enumerate(sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))):
        rs = sorted(rs, key=lambda r: -r["leader_iou"])
        lead = next((r for r in rs if r.get("leader")), rs[0])
        pick = [rs[int(j)] for j in np.unique(np.linspace(0, len(rs) - 1,
                                                          min(MEMBERS_KEPT, len(rs))).astype(int))]
        times = defaultdict(list)
        for r in rs:
            times[r["session_id"]].append(r["t_ms"])
        rows.append({"group": f"g{k:03d}", "size": len(rs), "entries": _episodes(rs),
                     "sessions": dict(Counter(r["session_id"] for r in rs)),
                     "times": {s: sorted(t) for s, t in sorted(times.items())},
                     "death_ids": sorted({r["death_id"] for r in rs if r["death_id"]}),
                     "best": Counter(r["best"] for r in rs).most_common(3),
                     "median_score": round(float(np.median([r["score"] for r in rs])), 3),
                     "aspect_median": round(float(np.median([r["aspect"] for r in rs])), 2),
                     "exemplar": {k2: lead.get(k2) for k2 in keep},
                     "members": [{k2: r.get(k2) for k2 in keep} for r in pick]})
    body = {"version": GROUPS_VERSION, "built_by": f"prototypes/killfeed_openset.py {STEP2}",
            "owner": WEAPON_ADJUDICATION_VERSION, "gallery": WEAPON_GALLERY_VERSION,
            "sessions": sids, "rows_read": seen, "rows_new": len(new),
            "rule": {"cluster": "weapon_icons.cluster (leader)", "same_icon": SAME_ICON,
                     "aspect_tol": ASPECT_TOL, "rows": "refused new by the owner's tiers; "
                     "rows of a named entry left out"},
            "groups": rows}
    text = json.dumps(body, indent=1)
    sha = hashlib.sha256(text.encode()).hexdigest()[:12]
    GROUPS_DIR.mkdir(parents=True, exist_ok=True)
    path = GROUPS_DIR / f"{GROUPS_VERSION}-{sha}.json"
    path.write_text(text, encoding="utf-8")
    sizes = [g["size"] for g in rows]
    print(json.dumps({"product": str(path), "rows_new": len(new), "groups": len(rows),
                      "sizes": sizes[:15], "singletons": sum(s == 1 for s in sizes)}))
    if RECORD:
        metrics.record("killfeed_openset", part="new_groups", session="+".join(sids),
                       values={"rows_read": seen, "rows_new": len(new), "groups": len(rows),
                               "largest": sizes[0] if sizes else 0,
                               "singletons": sum(s == 1 for s in sizes)},
                       deps={"owner": WEAPON_ADJUDICATION_VERSION, "gallery": WEAPON_GALLERY_VERSION,
                             "product": GROUPS_VERSION, "code": metrics.fingerprint(group_new_rows)},
                       context={"product": path.name},
                       note=f"{TASK}: rows refused new, grouped across sessions")
    return path


#: The Warden entries of 4f207c0c4e39: step 1's group 0, which the player
#: named the Warden [domain:killfeed/warden-icon], by the entry times the
#: step 1 contact sheet showed.
WARDEN_ENTRIES = ("286000:0", "286000:1", "433500:1", "458000:0", "794500:1", "834000:0",
                  "1783000:1", "1937500:0", "2160000:2", "2187000:0", "2195000:0", "2196500:1")
AFTERSHOCK_ROWS = ("a06f04a0059f", 287000.0, 288500.0)   # step 1's group 1


def check_groups(product: Path) -> dict:
    """S6 and the Aftershock fix on a group product: how many rows of the
    Warden entries refuse new and how many the largest group holds; whether
    any row of a06f04a0059f at 287.0-288.5 s is still in a group."""
    from reticle.adjudication.death import death_key, session_entries
    from reticle.adjudication.weapon import REFUSE_NEW, entry_weapon, load_mined_gallery
    from weapon_icons import _hud
    body = json.loads(Path(product).read_text(encoding="utf-8"))
    sid = OUT_OF_GALLERY[0]
    obs, agents, gal = _rows(sid), session_agents(sid), load_mined_gallery()
    ents = {death_key(sid, e["t_ms"], e["slot"]): e for e in session_entries(_hud(sid))}
    rows = []
    for i in WARDEN_ENTRIES:
        did = f"death:{sid}:{i}"
        v = entry_weapon(ents[did], obs, gallery=gal, agents=agents or None, key=did, frames=True)
        rows += [f for f in v["frames"]]
    largest = Counter(body["groups"][0]["times"].get(sid, []))
    s2, a, z = AFTERSHOCK_ROWS
    out = {"product": Path(product).name, "warden_rows": len(rows),
           "warden_refused_new": sum(f["reason"] == REFUSE_NEW for f in rows),
           "warden_in_largest": sum(largest[f["t_ms"]] > 0 for f in rows),
           "largest_size": body["groups"][0]["size"],
           "largest_entries": body["groups"][0]["entries"],
           "aftershock_rows_grouped": sum(a <= t <= z for g in body["groups"]
                                          for t in g["times"].get(s2, []))}
    out["warden_share_largest"] = round(out["warden_in_largest"] / max(out["warden_rows"], 1), 4)
    out["strays"] = [(f["t_ms"], f["slot"], f["best"]) for f in rows if not largest[f["t_ms"]]]
    if RECORD:
        metrics.record("killfeed_openset", part="warden_group", session=sid,
                       values={k: out[k] for k in ("warden_rows", "warden_refused_new",
                                                   "warden_in_largest", "warden_share_largest",
                                                   "largest_size", "largest_entries",
                                                   "aftershock_rows_grouped")},
                       deps={"owner": WEAPON_ADJUDICATION_VERSION, "gallery": WEAPON_GALLERY_VERSION,
                             "product": GROUPS_VERSION, "code": metrics.fingerprint(check_groups)},
                       context={"product": out["product"]},
                       note=f"{TASK}: the Warden rows and the Aftershock rows in the group product")
    return out


# ---------------------------------------------------------------------- step 3

STEP3 = "killfeed-openset-proto-0.3.0"
CROP_FAULTS_DIR = OUT / "crop_faults"

#: Why each group the player named `not_icon` (and g024, `other`) is not an
#: icon, read by eye on 2026-10-01 from its box drawn on the crop cache's
#: killfeed frames half a second before, at and after (`faults` draws them):
#: `not_on_entry`, no killfeed entry under the box (scenery, a band of HUD);
#: `left_of_entry`, an entry in the slot but the box left of its killer
#: portrait (scenery, the assist panel); `spans_killer_name`, the box holds the
#: killer's name and the gun as one blob; `truncated`, a cut piece of the
#: icon; `band_shifted`, the band placed above the entry, cutting the icon's
#: lower half; `faint`, the right box on an icon fading in.
CROP_FAULT_CAUSES = {
    "g008": "spans_killer_name", "g009": "spans_killer_name", "g010": "spans_killer_name",
    "g011": "truncated", "g012": "truncated", "g013": "faint", "g015": "not_on_entry",
    "g016": "truncated", "g017": "band_shifted", "g018": "band_shifted",
    "g019": "not_on_entry", "g020": "not_on_entry", "g022": "not_on_entry",
    "g023": "left_of_entry", "g024": "left_of_entry", "g025": "truncated"}

#: The cross-references `faults` scores, each a channel other than the
#: weapon reader's own box (`killfeed._band_text`, [owns:killfeed-weapon-descriptor]).
FAULT_GATES = {
    "killer_name_unread": "killfeed_name reads no killer name on the row's frame and slot",
    "width_off_entry": "the box's width differs by more than ENTRY_BOX_TOL from the modal "
                       "width of the overlapping boxes in the slot within 1 s",
    "no_counted_track": "no counted entry track of 1 s or more (`session_entries`) covers "
                        "the row's time within one slot",
    "track_edge": "the row is the first or last frame of the track that covers it",
    "band_off_portrait": "the box's top differs by more than 3 px from the killer "
                         "portrait's (`killfeed_portrait`)"}


def _fault_features(row: dict, sid: str, entries: list[dict], streams: dict) -> dict:
    from reticle.adjudication.weapon import ENTRY_BOX_TOL
    t, s = row["t_ms"], row["slot"]

    def at(name, role):
        return next((r for r in streams[name] if r.get("t_ms") == t and r.get("slot") == s
                     and r.get("role") == role
                     and str(r.get("kind", "")).endswith("_observation")), {})
    kn, vn, kp = at("killfeed_name", "killer"), at("killfeed_name", "victim"), \
        at("killfeed_portrait", "killer")
    cover = sorted((e for e in entries if e["t_first"] <= t <= e["t_last"]
                    and abs(e["slot"] - s) <= 1), key=lambda e: abs(e["slot"] - s))
    track = cover[0] if cover else None
    w = row["wx1"] - row["wx0"]
    near = [r for r in streams["killfeed_weapon"] if r.get("kind") == "weapon_icon_observation"
            and r["slot"] == s and 0 < abs(r["t_ms"] - t) <= 1000
            and min(r["wx1"], row["wx1"]) > max(r["wx0"], row["wx0"])]
    widths = Counter(r["wx1"] - r["wx0"] for r in near)
    mode = widths.most_common(1)[0][0] if widths else None
    unread = lambda r: (r.get("reason") or None) if r else "no_row"
    f = {"group": row["group"], "session_id": sid, "t_ms": t, "slot": s,
         "box": [row["wx0"], row["wx1"], row["y0"], row["y1"]], "width": w, "width_mode": mode,
         "killer_name": unread(kn), "victim_name": unread(vn),
         "killer_portrait": [kp.get("x0"), kp.get("x1"), kp.get("y0")] if kp else None,
         "track": [track["slot"], track["t_first"], track["t_last"]] if track else None,
         "death_id": row.get("death_id")}
    f["gates"] = {
        "killer_name_unread": f["killer_name"] is not None,
        "width_off_entry": mode is not None and abs(w - mode) > ENTRY_BOX_TOL,
        "no_counted_track": track is None or track["t_last"] - track["t_first"] < 1000,
        "track_edge": track is not None and t in (track["t_first"], track["t_last"]),
        "band_off_portrait": bool(kp) and kp.get("y0") is not None
                             and abs(row["y0"] - kp["y0"]) > 3}
    return f


def _fault_sheet(rows: list[dict]) -> list[Path]:
    """Each row's box drawn on its crop-cache killfeed frame, with the frames
    half a second before and after; one PNG per group."""
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    store, paths = Store(), []
    CROP_FAULTS_DIR.mkdir(parents=True, exist_ok=True)
    for sid in sorted({r["session_id"] for r in rows}):
        man = store.read_manifest(sid)
        cache, _ = RoiCache.load(store.root, man, get_profile(man.get("source_profile",
                                                                       "valorant-16x9")))
        if cache is None:
            continue
        x0, y0, x1, y1 = cache.rect_of("killfeed")
        mine = [r for r in rows if r["session_id"] == sid]
        ts = sorted({float(r["t_ms"] + d) for r in mine for d in (-500, 0, 500)})
        frames = {smp.t_ms: smp.frame[y0:y1, x0:x1] for smp in cache.samples(ts, rois="killfeed")}
        for r in mine:
            tiles = []
            for d in (-500, 0, 500):
                f = frames.get(float(r["t_ms"] + d))
                if f is None:
                    continue
                f = f.copy()
                if d == 0:
                    cv2.rectangle(f, (r["wx0"], r["y0"]), (r["wx1"] - 1, r["y1"] - 1),
                                  (0, 0, 255), 1)
                a = max(0, r["y0"] - 40)
                band = np.zeros((120, f.shape[1], 3), np.uint8)
                c = f[a:r["y1"] + 40][:120]
                band[:c.shape[0]] = c
                cv2.putText(band, f"{r['group']} {sid} {(r['t_ms'] + d) / 1000:.1f}s s{r['slot']}"
                            + (" BOX" if d == 0 else ""), (2, 114), cv2.FONT_HERSHEY_SIMPLEX,
                            0.4, (0, 255, 255), 1)
                tiles.append(band)
            path = CROP_FAULTS_DIR / f"{r['group']}_{sid}_{int(r['t_ms'])}.png"
            cv2.imwrite(str(path), np.vstack(tiles))
            paths.append(path)
    return paths


def crop_faults(product: Path, labels: Path) -> dict:
    """The groups the player said are no icon, as crop faults of the weapon
    reader's box: each exemplar drawn on the crop cache (`_fault_sheet`), its
    cause by eye (`CROP_FAULT_CAUSES`), and which cross-reference
    (`FAULT_GATES`) would have caught it, from stored rows only."""
    from reticle.adjudication.death import session_entries
    from weapon_icons import _hud
    body = json.loads(Path(product).read_text(encoding="utf-8"))
    last = {}
    for line in Path(labels).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            last[r["group"]] = r
    groups = {g["group"]: g for g in body["groups"]}
    picked = sorted(k for k, r in last.items() if r.get("class") in ("not_icon", "other"))
    rows = [dict(groups[k]["exemplar"], group=k) for k in picked]
    feats, cache = [], {}
    for r in rows:
        sid = r["session_id"]
        if sid not in cache:
            cache[sid] = (session_entries(_hud(sid)),
                          {k: Store().read_events(k, sid) for k in
                           ("killfeed_name", "killfeed_portrait", "killfeed_weapon")})
        f = _fault_features(r, sid, *cache[sid])
        f["cause"] = CROP_FAULT_CAUSES.get(r["group"], "unread")
        f["label"] = last[r["group"]].get("class")
        feats.append(f)
    sheets = _fault_sheet(rows)
    causes = Counter(f["cause"] for f in feats)
    by_cause = {}
    for c in sorted(causes):
        fs = [f for f in feats if f["cause"] == c]
        by_cause[c] = {g: sum(f["gates"][g] for f in fs) for g in FAULT_GATES}
        by_cause[c]["any"] = sum(any(f["gates"].values()) for f in fs)
        by_cause[c]["rows"] = len(fs)
    out = {"version": STEP3, "product": Path(product).name, "labels": Path(labels).name,
           "rows": len(feats), "causes": dict(causes), "gates": FAULT_GATES,
           "caught_by_cause": by_cause,
           "caught_any": sum(any(f["gates"].values()) for f in feats),
           "bound_to_entry": sum(f["death_id"] is not None for f in feats),
           "rows_detail": feats, "sheets": [str(p) for p in sheets]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "crop_faults.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    if RECORD:
        vals = {"rows": len(feats), "caught_any": out["caught_any"],
                "bound_to_entry": out["bound_to_entry"]}
        vals.update({f"cause_{c}": n for c, n in causes.items()})
        for c, gs in by_cause.items():
            vals.update({f"{c}__{g}": n for g, n in gs.items() if g != "rows"})
        metrics.record("killfeed_openset", part="crop_faults", session="+".join(body["sessions"]),
                       values=vals, deps={"product": Path(product).name,
                                          "labels": Path(labels).name,
                                          "code": metrics.fingerprint(crop_faults, _fault_features)},
                       note=f"{TASK}: the player's not_icon groups as weapon-box crop faults")
    return out


def main() -> None:
    global RECORD
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="measure without recording metrics")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("heldout")
    r = sub.add_parser("refusals")
    r.add_argument("sids", nargs="*", default=list(FAST + OUT_OF_GALLERY))
    sub.add_parser("kitnull")
    sub.add_parser("tiered")
    sub.add_parser("check").add_argument("product")
    f = sub.add_parser("faults")
    f.add_argument("product")
    f.add_argument("labels")
    for name in ("entries", "groups"):
        x = sub.add_parser(name)
        x.add_argument("sids", nargs="*", default=list(FAST + OUT_OF_GALLERY))
    a = ap.parse_args()
    RECORD = not a.dry
    if a.cmd == "groups":
        group_new_rows(a.sids)
        return
    if a.cmd == "faults":
        out = crop_faults(Path(a.product), Path(a.labels))
        print(json.dumps({k: v for k, v in out.items() if k not in ("rows_detail", "gates")},
                         indent=1))
        return
    if a.cmd == "check":
        print(json.dumps(check_groups(Path(a.product)), indent=1))
        return
    out = {"heldout": heldout, "kitnull": kitnull, "tiered": heldout_tiered}.get(a.cmd)
    out = out() if out else compare_entries(a.sids) if a.cmd == "entries" else split_refusals(a.sids)
    print(json.dumps({k: v for k, v in out.items() if k not in ("per_name", "group_table")}, indent=1))


if __name__ == "__main__":
    main()
