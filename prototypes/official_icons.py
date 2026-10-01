r"""Can the official ability glyphs, reduced to killfeed size, name killfeed ability icons?

    .\.venv\Scripts\python.exe prototypes\official_icons.py truth
    .\.venv\Scripts\python.exe prototypes\official_icons.py sheet
    .\.venv\Scripts\python.exe prototypes\official_icons.py failures
    .\.venv\Scripts\python.exe prototypes\official_icons.py measure

The store holds 118 official ability icons (`reference/assets/abilities/`,
valorant-api, glyph in the alpha channel), named by
`adjudication.weapon.ABILITY_CANONICAL_NAMES`. A killfeed icon is its white
glyph alone [domain:killfeed/weapon-slot-white-glyph], so this prototype draws
each glyph white over a flat background at killfeed size, cuts it with the
owner's white mask and grid (`extract_icon_observation`, `icon_grid`) and
scores it with the owner's aspect-gated IoU (`name_icon`) [owns:killfeed-weapon]
against the player-labelled ability exemplars of the mined gallery. It
measures only; nothing in `reticle/` reads the official glyphs this way.

`truth` keeps the gallery's `death:` ability exemplars whose label row in
`labels/killfeed_icon/` is the player's, sure and not a bad crop, named from
its ability stem (`weapon_icons.entry_labels`), and binds each back to its
stored `killfeed_weapon` row; the row's grid must equal the exemplar's. It
excludes group-named `kf:` exemplars, the `new:` NULL/cmd member, and the
Hot Hands box the BACKLOG names as cropped too tightly. `sheet` draws each
name's official glyph beside its exemplars (`<store>/analysis/
official-icons-20261001/official_vs_exemplars.png`); `failures` draws the
failing names at 6x (`failing_names.png`). `measure` writes `measure.json`
there. Predictions are logged under `official-icons-20261001`.

Results, 2026-10-01 (weapon-gallery-0.5.0)
------------------------------------------
Truth: [metric:official_icons/distribution@weapon-gallery-0.5.0#truth_n=127]
exemplars of [metric:official_icons/scope_all@weapon-gallery-0.5.0#entries=44]
entries and 8 names; the other
[metric:official_icons/distribution@weapon-gallery-0.5.0#excluded_n=65]
ability exemplars are 63 `kf:`, one `new:` and the Hot Hands crop. Every kept
exemplar re-cut from its crop-cache frame reproduces its stored grid.

The canvas size was fixed from geometry before any score: each name's
median glyph height over its official glyph's share of the canvas. Five of
eight names agree near the operating size,
[metric:official_icons/distribution@weapon-gallery-0.5.0#canvas_px=22.7] px;
Blade Storm, Resurrection and Headhunter fall off it. Drawn white over black
(the owner's cut then keeps alpha above 220/255), five glyphs with thin
strokes keep no white: Headhunter and Rendezvous, ZERO/point, Curveball and
Refract.

Top-1 over the 127 exemplars: the actor's kit
[metric:official_icons/scope_kit@weapon-gallery-0.5.0#top1=0.5906], the
match's agents [metric:official_icons/scope_match@weapon-gallery-0.5.0#top1=0.5748],
all icons [metric:official_icons/scope_all@weapon-gallery-0.5.0#top1=0.5748].
The owner would name only
[metric:official_icons/scope_all@weapon-gallery-0.5.0#named=0.252] at
NAME_MIN_IOU and NAME_MARGIN. Two names the killfeed draws with other art
cause most of the misses: Blade Storm, a single knife
[domain:killfeed/jett-blade-storm-icon] against the official fan of three
(own-name median IoU
[metric:official_icons/name_Blade_Storm@weapon-gallery-0.5.0#right_median=0.073],
49 exemplars), and Headhunter, a revolver
[domain:killfeed/chamber-gun-shaped-abilities] against a scope frame. With
those set apart (not pre-registered; both facts predate the run), top-1 is
[metric:official_icons/scope_kit_same_art@weapon-gallery-0.5.0#top1=0.974]
in the kit and
[metric:official_icons/scope_all_same_art@weapon-gallery-0.5.0#top1=0.9481]
over all icons
([metric:official_icons/scope_all_same_art@weapon-gallery-0.5.0#n=77]
exemplars; median margin
[metric:official_icons/scope_all_same_art@weapon-gallery-0.5.0#median_margin=0.181]).
Even there the owner's floor names only
[metric:official_icons/scope_all_same_art@weapon-gallery-0.5.0#named=0.4156];
the kit floor would name
[metric:official_icons/scope_all_same_art@weapon-gallery-0.5.0#named_kit_floor=0.9351].

Own name against best other name (median IoU): Aftershock
[metric:official_icons/name_Aftershock@weapon-gallery-0.5.0#right_median=0.651]
against [metric:official_icons/name_Aftershock@weapon-gallery-0.5.0#best_wrong_median=0.471];
Not Dead Yet [metric:official_icons/name_Not_Dead_Yet@weapon-gallery-0.5.0#right_median=0.78]
against [metric:official_icons/name_Not_Dead_Yet@weapon-gallery-0.5.0#best_wrong_median=0.59];
Resurrection [metric:official_icons/name_Resurrection@weapon-gallery-0.5.0#right_median=0.699]
against [metric:official_icons/name_Resurrection@weapon-gallery-0.5.0#best_wrong_median=0.447];
Orbital Strike [metric:official_icons/name_Orbital_Strike@weapon-gallery-0.5.0#right_median=0.558]
against [metric:official_icons/name_Orbital_Strike@weapon-gallery-0.5.0#best_wrong_median=0.423];
Annihilation [metric:official_icons/name_Annihilation@weapon-gallery-0.5.0#right_median=0.304]
against [metric:official_icons/name_Annihilation@weapon-gallery-0.5.0#best_wrong_median=0.342];
Boom Bot [metric:official_icons/name_Boom_Bot@weapon-gallery-0.5.0#right_median=0.0]
against [metric:official_icons/name_Boom_Bot@weapon-gallery-0.5.0#best_wrong_median=0.303].
Same-name exemplars of other entries score
[metric:official_icons/name_Aftershock@weapon-gallery-0.5.0#same_name_median=0.735],
[metric:official_icons/name_Not_Dead_Yet@weapon-gallery-0.5.0#same_name_median=0.768] and
[metric:official_icons/name_Resurrection@weapon-gallery-0.5.0#same_name_median=0.643]
for those three: where the art matches, the official glyph is about as close
as another killfeed exemplar. Over all names the official median is
[metric:official_icons/distribution@weapon-gallery-0.5.0#right_median=0.635]
against [metric:official_icons/distribution@weapon-gallery-0.5.0#same_name_median_of_names=0.732];
[metric:official_icons/distribution@weapon-gallery-0.5.0#names_right_median_above_kit_null=4]
of eight names clear the kit null of 0.513.

Annihilation draws the official swirl, but its fine strokes miss one
another on the 16x64 grid at every cut tried (one entry). Boom Bot draws the
official robot, but the strict cut drops its thin lower strokes, its aspect
rises past NAME_ASPECT_TOL and the gate zeroes two of three exemplars; a
looser cut (background 128) keeps them. The killfeed draws strokes bolder than
an area-reduced glyph (`failing_names.png`).

No official glyph collides with a gun exemplar: the highest scores
[metric:official_icons/distribution@weapon-gallery-0.5.0#gun_max=0.478]
(Owl Drone against Judge),
[metric:official_icons/distribution@weapon-gallery-0.5.0#gun_above_floor=0]
above NAME_MIN_IOU. All-icon top-1 ranges
[metric:official_icons/sensitivity@weapon-gallery-0.5.0#all_min=0.4567] to
[metric:official_icons/sensitivity@weapon-gallery-0.5.0#all_max=0.5827]
over three backgrounds and three canvas scales; the operating point sits near
the top. A leave-one-name-out canvas size leaves it at
[metric:official_icons/distribution@weapon-gallery-0.5.0#loo_canvas_all_top1=0.5748].

So the official glyphs name an ability whose killfeed icon is the official
art, at least as well as a second exemplar would, and never pass for a gun.
They cannot say which abilities draw other art: Blade Storm and Headhunter
would sit in a reference tier as wrong exemplars, and only a labelled
killfeed exemplar shows the difference. A reference tier needs a per-ability
check that the killfeed draws the official art (the player, or one labelled
entry) before its glyph stands in for an exemplar.
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
    ABILITY_CANONICAL_NAMES, MINED_NOT_GUN, NAME_KIT_MIN_IOU, NAME_MARGIN, NAME_MIN_IOU,
    WEAPON_ADJUDICATION_VERSION, WEAPON_GALLERY_VERSION, ability_agent, bind_entry,
    extract_icon_observation, load_ability_gallery, name_icon)
from reticle.killfeed import icon_grid, unpack_icon_grid  # noqa: E402
from reticle.store import Store  # noqa: E402

from killfeed_openset import _cell, _crops, load_keyed_gallery, session_agents  # noqa: E402
from weapon_icons import ENTRY_BOX_TOL, _entries_by_key, _key_of, entry_labels  # noqa: E402

VERSION = "official-icons-proto-0.1.0"
TASK = "official-icons-20261001"
OUT = Store().root / "analysis" / TASK
ASSETS = Store().root / "reference" / "assets" / "abilities"
RECORD = True                 # --dry skips metrics.record

#: The weapon box the BACKLOG crop-fault item names as cropping its icon too
#: tightly [domain:killfeed/phoenix-hot-hands-icon]; its exemplars are no truth.
TIGHT_CROPS = {("b3b9defb6fd7", 1731500)}
CROP_FAULTS = Store().root / "analysis" / "killfeed-openset-20261001" / "crop_faults.json"

#: The operating point, fixed before any score was seen: the glyph drawn white
#: over black (so the owner's white cut keeps alpha above 220/255), at the
#: canvas size the labelled exemplars' measured glyph heights give.
BACKGROUND = 0
#: The sensitivity grid around it: backgrounds (alpha cut 0.86, 0.72, 0.53)
#: and canvas scales.
BACKGROUNDS = (0, 128, 180)
SCALES = (0.75, 1.0, 1.25)
PAD = 3                       # px of background around the rendered glyph

#: Names whose killfeed icon a fact, recorded before this run, describes as
#: other art than the official glyph: a single thin knife for Blade Storm
#: [domain:killfeed/jett-blade-storm-icon], gun silhouettes for Chamber's
#: two [domain:killfeed/chamber-gun-shaped-abilities].
OTHER_ART = {"Blade Storm": "killfeed/jett-blade-storm-icon",
             "Headhunter": "killfeed/chamber-gun-shaped-abilities",
             "Tour De Force": "killfeed/chamber-gun-shaped-abilities"}


# ----------------------------------------------------------------------- truth

def truth() -> tuple[list[dict], dict]:
    """The ability exemplars of the owner's gallery whose names come from the
    player's per-entry labels (`labels/killfeed_icon/`, `by: player`, not
    unsure, not a bad crop; named from the ability stem, `entry_labels`), each
    bound back to its stored `killfeed_weapon` row. Every other ability
    exemplar is excluded with its reason."""
    g = load_keyed_gallery()
    labels = entry_labels()
    faults = {(r["session_id"], int(r["t_ms"]), int(r["slot"]))
              for r in json.loads(CROP_FAULTS.read_text(encoding="utf-8"))["rows_detail"]}
    store = Store()
    excluded, keep = Counter(), []
    cand = [i for i, n in enumerate(g["names"])
            if ability_agent(str(n)) is not None or MINED_NOT_GUN.get(str(n)) == "ability"]
    bound_cache: dict[str, tuple] = {}
    for i in cand:
        key, name = str(g["keys"][i]), str(g["names"][i])
        kind = key.split(":")[0]
        if kind == "kf":
            excluded[f"{name}: kf (group name propagated over a cluster)"] += 1
            continue
        if kind == "new":
            excluded[f"{name}: new (labels/killfeed_new_icon, not a per-entry label)"] += 1
            continue
        base, k = key.split("#")
        lab = labels.get(base)
        if lab is None or lab.get("by") != "player":
            excluded[f"{name}: no player label"] += 1
            continue
        if lab["answer"] != name:
            excluded[f"{name}: label names {lab['answer']}"] += 1
            continue
        sid = lab["session_id"]
        if sid not in bound_cache:
            bound_cache[sid] = (_entries_by_key(sid), store.read_events("killfeed_weapon", sid))
        entries, obs = bound_cache[sid]
        e = entries.get(_key_of(base))
        bound = bind_entry(e, obs) if e is not None else []
        x0, _, x1, _ = lab["ring"]
        rows = [o for o in bound if abs(o["wx0"] - x0) <= ENTRY_BOX_TOL
                and abs(o["wx1"] - x1) <= ENTRY_BOX_TOL]
        row = rows[int(k)] if int(k) < len(rows) else None
        if row is None or not np.array_equal(unpack_icon_grid(row["grid"]), g["masks"][i]):
            excluded[f"{name}: stored row does not reproduce the exemplar"] += 1
            continue
        if (sid, int(base.split(":")[2])) in TIGHT_CROPS:
            excluded[f"{name}: crop fault (cropped too tightly, BACKLOG)"] += 1
            continue
        if (sid, int(row["t_ms"]), int(row["slot"])) in faults:
            excluded[f"{name}: crop fault (crop_faults.json)"] += 1
            continue
        keep.append({"i": int(i), "key": key, "name": name, "agent": ability_agent(name),
                     "session_id": sid, "entry": base, "grid": g["masks"][i],
                     "aspect": float(g["aspects"][i]), "t_ms": float(row["t_ms"]),
                     "slot": int(row["slot"]), "wx0": int(row["wx0"]), "wx1": int(row["wx1"]),
                     "y0": int(row["y0"]), "y1": int(row["y1"]), "stem": lab.get("ability_stem")})
    return keep, {"candidates": len(cand), "kept": len(keep), "excluded": dict(excluded)}


def glyph_heights(rows: list[dict]) -> dict:
    """Each truth exemplar's white glyph, re-cut from its crop-cache frame
    with the owner's mask: its tight height, and whether the re-cut grid is
    the stored one (an instrument check of the crop path)."""
    crops = _crops(rows)
    for r in rows:
        c = crops.get(id(r))
        if c is None:
            r["glyph_h"] = None
            continue
        obs = extract_icon_observation(c)
        ys, _ = np.nonzero(obs.white_mask)
        r["glyph_h"] = int(ys.max() - ys.min() + 1) if len(ys) else None
        cut = icon_grid(obs.white_mask)
        r["recut_same"] = bool(cut is not None and np.array_equal(cut[0], r["grid"]))
        r["crop"] = c
    return {"n": len(rows), "with_crop": sum(r.get("glyph_h") is not None for r in rows),
            "recut_same": sum(bool(r.get("recut_same")) for r in rows)}


# -------------------------------------------------------------------- official

def official_raw() -> dict[str, tuple[np.ndarray, int]]:
    """Each official icon as the owner's loader gives it (tight to alpha >
    128), with its canvas height read from the file."""
    gal = load_ability_gallery(ASSETS)
    out = {}
    for stem, raw in sorted(gal.items()):
        canvas = cv2.imread(str(ASSETS / f"{stem}.png"), cv2.IMREAD_UNCHANGED).shape[0]
        out[stem] = (raw, canvas)
    return out


def canvas_px(rows: list[dict], raw: dict) -> dict:
    """The killfeed size of the official 128 px canvas, from geometry alone:
    per truth name, its exemplars' median glyph height over the official
    glyph's share of its canvas; the operating size is the median over names."""
    per = {}
    by = defaultdict(list)
    for r in rows:
        if r.get("glyph_h"):
            by[r["stem"]].append(r["glyph_h"])
    for stem, hs in sorted(by.items()):
        tight, canvas = raw[stem]
        per[ABILITY_CANONICAL_NAMES[stem]] = {
            "glyph_h_median": float(np.median(hs)), "n": len(hs),
            "official_share": round(tight.shape[0] / canvas, 3),
            "canvas_px": round(float(np.median(hs)) / (tight.shape[0] / canvas), 2)}
    size = float(np.median([v["canvas_px"] for v in per.values()]))
    return {"per_name": per, "canvas_px": round(size, 2)}


def render(raw: np.ndarray, canvas: int, size: float, background: int = BACKGROUND) -> np.ndarray:
    """The glyph as the killfeed would draw it: white, alpha-blended over a
    flat background, the 128 px canvas reduced to `size` px (INTER_AREA)."""
    s = size / canvas
    w, h = max(1, int(round(raw.shape[1] * s))), max(1, int(round(raw.shape[0] * s)))
    a = cv2.resize(raw[:, :, 3].astype(np.float32) / 255.0, (w, h), interpolation=cv2.INTER_AREA)
    a = np.pad(a, PAD)
    v = np.clip(a * 255.0 + (1 - a) * background, 0, 255).astype(np.uint8)
    return cv2.merge([v, v, v])


def official_gallery(raw: dict, size: float, background: int = BACKGROUND) -> dict:
    """The official glyphs as an owner-shaped gallery: each rendered crop
    through the owner's white mask (`extract_icon_observation`) and grid
    (`icon_grid`), named by ABILITY_CANONICAL_NAMES (a passive keeps its stem)."""
    names, masks, aspects, stems, crops, dropped = [], [], [], [], [], []
    for stem, (r, canvas) in raw.items():
        crop = render(r, canvas, size, background)
        cut = icon_grid(extract_icon_observation(crop).white_mask)
        if cut is None:
            dropped.append(stem)
            continue
        names.append(ABILITY_CANONICAL_NAMES.get(stem, stem))
        masks.append(cut[0])
        aspects.append(cut[1])
        stems.append(stem)
        crops.append(crop)
    return {"names": np.array(names), "masks": np.array(masks), "aspects": np.array(aspects),
            "stems": stems, "crops": crops, "dropped": dropped}


def subset(g: dict, keep) -> dict:
    keep = np.asarray(keep, bool)
    return {"names": g["names"][keep], "masks": g["masks"][keep], "aspects": g["aspects"][keep]}


def pair(grid_a, aspect_a, grid_b, aspect_b) -> float:
    """The owner's score of one icon against one exemplar (aspect-gated IoU)."""
    return name_icon(grid_a, aspect_a, {"names": np.array(["x"]), "masks": grid_b[None],
                                        "aspects": np.array([aspect_b])})["score"]


# --------------------------------------------------------------------- measure

def score_scopes(rows: list[dict], off: dict) -> dict:
    """Each truth exemplar named against the official gallery at three
    candidate scopes: the actor's kit (its own agent's icons), the match's
    agents (`session_agents`), and all icons. Top-1 is the owner's `best`;
    `named` is whether the owner would name it (floor and margin)."""
    agents_of = {s: session_agents(s) for s in sorted({r["session_id"] for r in rows})}
    off_agent = np.array([ability_agent(str(n)) or s.rsplit("_", 1)[0]
                          for n, s in zip(off["names"], off["stems"])])
    out = {}
    for scope in ("kit", "match", "all"):
        res = []
        for r in rows:
            if scope == "kit":
                keep = off_agent == r["agent"]
            elif scope == "match":
                keep = np.isin(off_agent, sorted(agents_of[r["session_id"]]))
            else:
                keep = np.ones(len(off_agent), bool)
            g = subset(off, keep)
            v = name_icon(r["grid"], r["aspect"], g)
            right = r["name"] in set(g["names"].tolist())
            res.append({"name": r["name"], "best": v["best"], "score": v["score"],
                        "margin": v["margin"], "top1": v["best"] == r["name"] and v["score"] > 0,
                        "named": v.get("name") == r["name"], "own_in_scope": right,
                        "named_kit_floor": (v["best"] == r["name"] and v["score"] >= NAME_KIT_MIN_IOU
                                            and v["margin"] >= NAME_MARGIN),
                        "entry": r["entry"], "n_candidates": int(keep.sum())})
        out[scope] = res
    return {"scopes": out, "agents": {s: sorted(a) for s, a in agents_of.items()}}


def summary(res: list[dict]) -> dict:
    n = len(res)
    ent = defaultdict(list)
    for x in res:
        ent[x["entry"]].append(x["top1"])
    return {"n": n, "top1": round(sum(x["top1"] for x in res) / n, 4),
            "named": round(sum(x["named"] for x in res) / n, 4),
            "named_kit_floor": round(sum(x["named_kit_floor"] for x in res) / n, 4),
            "own_in_scope": round(sum(x["own_in_scope"] for x in res) / n, 4),
            "entries": len(ent),
            "entries_top1_majority": round(sum(np.mean(v) > 0.5 for v in ent.values()) / len(ent), 4),
            "median_margin": round(float(np.median([x["margin"] if x["top1"] else -x["margin"]
                                                    for x in res])), 3)}


def per_name_table(rows: list[dict], off: dict) -> dict:
    """Per truth name: the exemplars' score against their own official icon
    (right) and against the best other official icon (best wrong), over all
    icons, and the same-name exemplar-to-exemplar score across entries."""
    table = {}
    own = {}
    for r in rows:
        sc = np.array([pair(r["grid"], r["aspect"], m, a)
                       for m, a in zip(off["masks"], off["aspects"])])
        is_own = off["names"] == r["name"]
        # An official glyph no white survives in can never be named: it scores 0.
        r["right"] = float(sc[is_own].max()) if is_own.any() else 0.0
        r["official_dropped"] = not is_own.any()
        wrong = np.where(is_own, -1, sc)
        r["best_wrong"] = float(wrong.max())
        r["best_wrong_name"] = str(off["names"][int(wrong.argmax())])
        own.setdefault(r["name"], []).append(r)
    for name, rs in sorted(own.items()):
        same = [pair(a["grid"], a["aspect"], b["grid"], b["aspect"])
                for k, a in enumerate(rs) for b in rs[k + 1:] if a["entry"] != b["entry"]]
        wrong_names = Counter(r["best_wrong_name"] for r in rs)
        table[name] = {
            "n": len(rs), "entries": len({r["entry"] for r in rs}),
            "right_median": round(float(np.median([r["right"] for r in rs])), 3),
            "right_max": round(float(max(r["right"] for r in rs)), 3),
            "best_wrong_median": round(float(np.median([r["best_wrong"] for r in rs])), 3),
            "best_wrong_name": wrong_names.most_common(1)[0][0],
            "right_beats_wrong": round(float(np.mean([r["right"] > r["best_wrong"] for r in rs])), 3),
            "same_name_pairs": len(same),
            "same_name_median": round(float(np.median(same)), 3) if same else None,
            "aspect_exemplar_median": round(float(np.median([r["aspect"] for r in rs])), 3),
            "aspect_official": (round(float(off["aspects"][off["names"] == name][0]), 3)
                                if (off["names"] == name).any() else None),
        }
    return table


def gun_collisions(off: dict) -> dict:
    """Each official glyph named against the gallery's gun exemplars alone."""
    g = load_keyed_gallery()
    guns = np.array([MINED_NOT_GUN.get(str(n), "gun") == "gun" for n in g["names"]])
    gg = {"names": g["names"][guns], "masks": g["masks"][guns], "aspects": g["aspects"][guns]}
    hits = []
    for name, m, a in zip(off["names"], off["masks"], off["aspects"]):
        v = name_icon(m, float(a), gg)
        hits.append((v["score"], str(name), v["best"]))
    hits.sort(reverse=True)
    return {"n": len(hits), "above_floor": [h for h in hits if h[0] >= NAME_MIN_IOU],
            "max": hits[0][0], "top5": hits[:5]}


def measure() -> dict:
    rows, prov = truth()
    hts = glyph_heights(rows)
    raw = official_raw()
    size = canvas_px(rows, raw)
    out = {"version": VERSION, "gallery": WEAPON_GALLERY_VERSION,
           "owner": WEAPON_ADJUDICATION_VERSION, "provenance": prov, "heights": hts,
           "canvas": size, "operating": {"background": BACKGROUND, "canvas_px": size["canvas_px"]}}
    off = official_gallery(raw, size["canvas_px"])
    out["official_n"] = len(off["names"])
    out["official_dropped"] = off["dropped"]
    sc = score_scopes(rows, off)
    out["agents"] = sc["agents"]
    out["scopes"] = {k: summary(v) for k, v in sc["scopes"].items()}
    # Not pre-registered: the names a fact recorded before this run says the
    # killfeed draws with other art than the official glyph, set apart.
    out["scopes_same_art"] = {k: summary([x for x in v if x["name"] not in OTHER_ART])
                              for k, v in sc["scopes"].items()}
    out["per_name_scope"] = {k: {n: dict(Counter(f"{'right' if x['top1'] else 'wrong:' + x['best']}"
                                                  for x in v if x["name"] == n))
                                  for n in sorted({x["name"] for x in v})}
                             for k, v in sc["scopes"].items()}
    out["per_name"] = per_name_table(rows, off)
    rights = [r["right"] for r in rows]
    by_name_same = [v["same_name_median"] for v in out["per_name"].values() if v["same_name_median"]]
    out["right_median"] = round(float(np.median(rights)), 3)
    out["right_above_kit_null"] = round(float(np.mean(np.array(rights) > 0.513)), 4)
    out["names_right_median_above_kit_null"] = sum(
        v["right_median"] > 0.513 for v in out["per_name"].values())
    out["same_name_median_of_names"] = round(float(np.median(by_name_same)), 3)
    out["guns"] = gun_collisions(off)
    # The sensitivity grid: background (alpha cut) by canvas scale.
    grid = {}
    for b in BACKGROUNDS:
        for s in SCALES:
            o = official_gallery(raw, size["canvas_px"] * s, b)
            res = score_scopes(rows, o)["scopes"]
            grid[f"bg{b}_x{s}"] = {k: summary(v)["top1"] for k, v in res.items()}
    out["sensitivity"] = grid
    # Leave one name out of the canvas size: no name's own exemplars set the
    # scale its official glyph is drawn at.
    loo = []
    for name in size["per_name"]:
        others = [v["canvas_px"] for n, v in size["per_name"].items() if n != name]
        o = official_gallery(raw, float(np.median(others)))
        mine = [r for r in rows if r["name"] == name]
        loo += score_scopes(mine, o)["scopes"]["all"]
    out["loo_canvas_all_top1"] = summary(loo)["top1"]
    if RECORD:
        deps = {"gallery": WEAPON_GALLERY_VERSION, "owner": WEAPON_ADJUDICATION_VERSION,
                "assets": "valorant-api abilities (118)", "code": metrics.fingerprint(measure)}
        for k, v in out["scopes"].items():
            metrics.record("official_icons", part=f"scope_{k}", session=WEAPON_GALLERY_VERSION,
                           values=v, deps=deps,
                           context={"canvas_px": size["canvas_px"], "background": BACKGROUND},
                           note=f"{TASK}: official glyphs naming player-labelled killfeed ability exemplars")
            metrics.record("official_icons", part=f"scope_{k}_same_art",
                           session=WEAPON_GALLERY_VERSION, values=out["scopes_same_art"][k],
                           deps=deps,
                           context={"canvas_px": size["canvas_px"], "background": BACKGROUND,
                                    "other_art": sorted(OTHER_ART)},
                           note=f"{TASK}: not pre-registered; names a fact says draw other art set apart")
        metrics.record("official_icons", part="distribution", session=WEAPON_GALLERY_VERSION,
                       values={"right_median": out["right_median"],
                               "right_above_kit_null": out["right_above_kit_null"],
                               "names_right_median_above_kit_null": out["names_right_median_above_kit_null"],
                               "same_name_median_of_names": out["same_name_median_of_names"],
                               "canvas_px": size["canvas_px"], "truth_n": prov["kept"],
                               "excluded_n": sum(prov["excluded"].values()),
                               "gun_max": out["guns"]["max"],
                               "gun_above_floor": len(out["guns"]["above_floor"]),
                               "loo_canvas_all_top1": out["loo_canvas_all_top1"]},
                       deps=deps, note=f"{TASK}: official-vs-exemplar against same-name exemplars")
        alls = [v["all"] for v in grid.values()]
        metrics.record("official_icons", part="sensitivity", session=WEAPON_GALLERY_VERSION,
                       values={"all_min": min(alls), "all_max": max(alls),
                               **{f"all_{k}": v["all"] for k, v in grid.items()}},
                       deps=deps, note=f"{TASK}: all-icon top-1 over background x canvas scale")
        for name, v in out["per_name"].items():
            metrics.record("official_icons", part=f"name_{name.replace(' ', '_').replace('/', '_')}",
                           session=WEAPON_GALLERY_VERSION,
                           values={k: v[k] for k in ("n", "entries", "right_median",
                                                     "best_wrong_median", "right_beats_wrong",
                                                     "same_name_median", "aspect_exemplar_median",
                                                     "aspect_official")},
                           deps=deps, note=f"{TASK}: per-name right vs best wrong")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "measure.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return out


# ----------------------------------------------------------------------- sheet

def sheet(per: int = 6) -> Path:
    """Per truth name, one row: the official glyph (alpha at 128 px), its
    killfeed-size render and the owner's grid of it, then up to `per` of the
    name's labelled exemplars, each as its crop-cache crop over its stored grid."""
    rows, _ = truth()
    glyph_heights(rows)
    raw = official_raw()
    size = canvas_px(rows, raw)["canvas_px"]
    offs = [official_gallery(raw, size, b) for b in (BACKGROUND, BACKGROUNDS[-1])]
    stem_of = {v: k for k, v in ABILITY_CANONICAL_NAMES.items()}
    by = defaultdict(list)
    for r in rows:
        by[r["name"]].append(r)
    lines = []
    W, H = 96, 40
    for name, rs in sorted(by.items()):
        stem = stem_of[name]
        alpha = raw[stem][0][:, :, 3]
        head = np.full((H * 2, W * 2, 3), 40, np.uint8)
        cv2.putText(head, name[:14], (3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
        cv2.putText(head, f"{stem}", (3, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (200, 200, 120), 1)
        cv2.putText(head, f"n={len(rs)} canvas {size:.1f}px", (3, 50), cv2.FONT_HERSHEY_SIMPLEX,
                    0.34, (200, 200, 200), 1)
        cv2.putText(head, "cols: bg0, bg180", (3, 68), cv2.FONT_HERSHEY_SIMPLEX,
                    0.34, (200, 200, 200), 1)
        ofull = _cell(cv2.cvtColor(alpha, cv2.COLOR_GRAY2BGR), W, H * 2)
        okf = []
        for off in offs:
            if stem in off["stems"]:
                k = off["stems"].index(stem)
                okf.append(np.vstack([_cell(off["crops"][k], W, H),
                                      _cell(off["masks"][k].astype(float), W, H)]))
            else:
                blank = np.full((H, W, 3), 0, np.uint8)
                cv2.putText(blank, "no white", (3, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.34,
                            (0, 0, 255), 1)
                crop = render(raw[stem][0], raw[stem][1], size, BACKGROUND)
                okf.append(np.vstack([_cell(crop, W, H), blank]))
        okf = np.hstack(okf)
        pick = [rs[int(j)] for j in np.linspace(0, len(rs) - 1, min(per, len(rs)))]
        cells = []
        for r in pick:
            c = r.get("crop")
            top = _cell(c, W, H) if c is not None else np.zeros((H, W, 3), np.uint8)
            cells.append(np.vstack([top, _cell(r["grid"].astype(float), W, H)]))
        while len(cells) < per:
            cells.append(np.full((H * 2, W, 3), 20, np.uint8))
        line = np.hstack([head, ofull, okf] + cells)
        lines.append(np.vstack([line, np.full((4, line.shape[1], 3), 90, np.uint8)]))
    img = np.vstack(lines)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "official_vs_exemplars.png"
    cv2.imwrite(str(path), img)
    return path


#: The names `measure` found failing, drawn larger by `failures`.
FAILING = ("Annihilation", "Boom Bot", "Headhunter", "Blade Storm")


def failures(names=FAILING, zoom: int = 6) -> Path:
    """Per failing name, at `zoom`x without smoothing: the official glyph
    rendered at the operating point and its white mask, then each of up to
    three exemplars' crop-cache crop and its white mask (the owner's cut)."""
    rows, _ = truth()
    glyph_heights(rows)
    raw = official_raw()
    size = canvas_px(rows, raw)["canvas_px"]
    stem_of = {v: k for k, v in ABILITY_CANONICAL_NAMES.items()}
    H = 44 * zoom

    def big(img):
        if img.ndim == 2:
            img = cv2.cvtColor(img.astype(np.uint8) * 255, cv2.COLOR_GRAY2BGR)
        img = cv2.resize(img, (img.shape[1] * zoom, img.shape[0] * zoom),
                         interpolation=cv2.INTER_NEAREST)
        out = np.full((H, img.shape[1] + 8, 3), 60, np.uint8)
        out[:min(H, img.shape[0]), :img.shape[1]] = img[:H]
        return out
    lines = []
    for name in names:
        stem = stem_of[name]
        crop = render(raw[stem][0], raw[stem][1], size, BACKGROUND)
        cells = [big(crop), big(extract_icon_observation(crop).white_mask)]
        rs = [r for r in rows if r["name"] == name]
        for r in [rs[int(j)] for j in np.linspace(0, len(rs) - 1, min(3, len(rs)))]:
            cells += [big(r["crop"]), big(extract_icon_observation(r["crop"]).white_mask)]
        line = np.hstack(cells)
        cv2.putText(line, f"{name} ({stem}) official | exemplars", (4, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        lines.append(line)
    w = max(x.shape[1] for x in lines)
    img = np.vstack([np.pad(x, ((0, 6), (0, w - x.shape[1]), (0, 0))) for x in lines])
    path = OUT / "failing_names.png"
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return path


def main() -> None:
    global RECORD
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="measure without recording metrics")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("truth", "sheet", "failures", "measure"):
        sub.add_parser(c)
    a = ap.parse_args()
    RECORD = not a.dry
    if a.cmd == "truth":
        rows, prov = truth()
        hts = glyph_heights(rows)
        size = canvas_px(rows, official_raw())
        print(json.dumps({"provenance": prov, "heights": hts, "canvas": size,
                          "by_name": dict(Counter(r["name"] for r in rows)),
                          "entries": dict(Counter(r["name"] for r in
                                                  {r["entry"]: r for r in rows}.values()))},
                         indent=1))
    elif a.cmd == "sheet":
        print(sheet())
    elif a.cmd == "failures":
        print(failures())
    else:
        out = measure()
        print(json.dumps({k: v for k, v in out.items() if k not in ("agents",)}, indent=1,
                         default=str))


if __name__ == "__main__":
    main()
