r"""Wallbangs and the other reasons a Riot kill has no 3D line of sight: a probe.

    .\.venv\Scripts\python.exe prototypes\wallbang_probe.py rays --map ascent [--set dev|confirm]
    .\.venv\Scripts\python.exe prototypes\wallbang_probe.py meshes [--export]
    .\.venv\Scripts\python.exe prototypes\wallbang_probe.py classify [--record]
    .\.venv\Scripts\python.exe prototypes\wallbang_probe.py render --map ascent --kill K --out PNG
    .\.venv\Scripts\python.exe prototypes\wallbang_probe.py cost --map ascent [--pairs N] [--record]
    .\.venv\Scripts\python.exe prototypes\wallbang_probe.py --self-test

Why this exists
---------------
The player asked whether the sightline work accounts for wallbangs. It does
not: `sightlines_3d` treats every Weapon-channel blocker as opaque, so a gun
kill through a wall reads as a kill without line of sight. This probe takes
every Riot gun kill the 3D gate calls blocked (killer eye 175 cm to victim
body centre 98 cm, exact positions, lowest floor) and asks why, so the
reach and engagement model can decide whether it needs a penetrable layer.

Classes, by fixed precedence (each is also computed alone)
----------------------------------------------------------
- (e) not a gun: Riot's `finishingDamage.damageType` is not `Weapon`, or its
  `damageItem` is no gun in valorant-api's weapon list. Excluded first.
- (b) posture or height: line of sight at another killer eye height (crouch,
  standing eye with StandingEyeOffset, jump apex) to another victim target
  (crouched, head, mid-jump), or on any pair of standable floors.
- (c) position error: line of sight standing, eye to body or head, with the
  killer and the victim each moved up to `POS_RADIUS_CM` (42 cm, the capsule
  radius [domain:game_data/character-eye-height]) in 8 directions at half and
  full radius, at the recorded floor height. A moved point counts only when
  the Pawn blockers leave it reachable from the recorded point. The radius
  is the body's half-width:
  the gate aims point to point, but a bullet kills on any part of a hitbox
  around the capsule axis, and Riot's integer-centimetre positions add
  nothing at this scale.
- (a) wallbang: the occluders on the eye-to-body or eye-to-head line are
  penetrable by the kill's weapon: each solid interval's path length times
  its surface's EnergyReductionMultiplier
  [domain:weapons/wall-penetration-surfaces] sums to at most `D0_CM` x
  the weapon tier's StoppingDistanceMultiplier
  [domain:weapons/wall-penetration-weapons], and no surface on the line is
  Impenetrable. Solid intervals pair entering and leaving crossings along the
  whole ray (`intervals`): the maps' architecture is single-sided shells, so
  a wall's outer face and inner face are often different meshes, and a
  crossing left unpaired adds no length.
- (d) the table is wrong (a missing or extra occluder, or a place to stand
  the floor model lacks): judged by eye on rendered rays (`render`), stored in
  `TABLE_WRONG`, never automatic.
- (f) unexplained: the rest.

Where the game stores penetration
---------------------------------
The facts and their asset paths: [domain:weapons/wall-penetration-surfaces]
and [domain:weapons/wall-penetration-weapons]. The readers, the crossings
and the solid-path rule live in `reticle/wall_penetration.py`, which this
probe imports. They read the exports themselves: `WallPenGlobals`, the `WallPen_*` classes, the physical
materials and `Projectile_Gun` from the store's
`reference/game-files/<build>/wallpen/`, the projectiles from `weapon-data`,
and each occluding mesh with its material chain from `wallpen-meshes/`
(`meshes --export`, the store's extractor at Below Normal, never while the
game runs). A crossing's surface: the hit triangle's collision section, that
section's material slot, the material's `PhysMaterial` through its parent
chain, the physical material's `SurfaceType`; a simple-collision mesh takes
its BodySetup's `PhysMaterial`, else slot 0's (`Surfaces`). Component-level
material overrides are not read.

No export gives the base stopping distance the multipliers scale, nor High's
EnergyReductionMultiplier. `D0_CM` (100 cm, a Medium gun through a surface of
multiplier 1) and `HIGH_ERM` (1.0) are placeholders: D0 reads
GlobalPenetrationCurve's 0-100 axis as effective centimetres, and High's
value follows the facts' exceptions. `classify` sweeps D0 (`D0_SWEEP`).

Data rules
----------
The development set (22 captured matches, 7 maps) scores the predictions
(`wallbang-probe-20261005` in the store's notes/predictions.jsonl). The six
maps without development kills are instrument checks on the confirmation
history, held-out replay, captured and ladder holdout matches excluded; no
hypothesis is scored there. Riot records are evaluation truth only: this
probe fits nothing for production, is never a reader input and is never
shown during play (`"wire": "no"`).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sightlines_3d as s3  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.wall_penetration import (HIGH_ERM, IMPENETRABLE_ERM, Surfaces, exports,  # noqa: E402,F401
                                      intervals, segment_hits, surface_names, surface_table)
from reticle.wall_penetration import index_paths as _index_paths  # noqa: E402
from reticle.wall_penetration import json_of as _json_of  # noqa: E402
from reticle.wall_penetration import obj_path as _obj_path  # noqa: E402

VERSION = "wallbang-probe-0.1.0"
STORE = s3.STORE
BUILD_ROOT = STORE / "reference" / "game-files" / s3.GAME_BUILD
WEAPON_DATA = BUILD_ROOT / "weapon-data"
#: Occluding meshes and their materials, exported by `meshes --export`.
MESH_SET = BUILD_ROOT / "wallpen-meshes"
OUT = STORE / "sightlines" / "wallbang"
DEV_MAPS = ("abyss", "ascent", "haven", "lotus", "split", "summit", "sunset")
CONFIRM_MAPS = ("bind", "breeze", "corrode", "fracture", "icebox", "pearl")

#: Placeholder: base stopping distance in cm of an EnergyReductionMultiplier-1
#: surface for a weapon whose StoppingDistanceMultiplier is 1. Not in the files.
D0_CM = 100.0
D0_SWEEP = (25.0, 50.0, 100.0, 200.0, 400.0)

EYE_CM = s3.EYE_CM
BODY_CM = s3.BODY_CM
_B = s3._game_body()
_EYE_FACT = __import__("tomllib").loads((s3.REPO / "domain" / "game_data.toml").read_text(encoding="utf-8"))[
    "character-eye-height"]["values"]
CAPSULE_R_CM = 100.0 * _EYE_FACT["capsule"]["radius_m"]
CROUCH_HALF_CM = _B["crouched_half_cm"]
CROUCH_EYE_CM = CROUCH_HALF_CM + 100.0 * _EYE_FACT["eye"]["crouched_eye_height_m"]
STANDING_OFFSET_EYE_CM = EYE_CM + 100.0 * _EYE_FACT["eye"]["standing_eye_offset_m"]
JUMP_CM = s3.JUMP_CM
#: Killer eye heights for (b): crouched (engine convention; the native crouch
#: code is unread), standing with StandingEyeOffset, standing, jump apex.
KILLER_EYES = (CROUCH_EYE_CM, STANDING_OFFSET_EYE_CM, EYE_CM, EYE_CM + JUMP_CM)
#: Victim targets for (b): crouched centre and eye, body centre, standing
#: eye with offset, head (standing eye), body and head at the jump apex.
VICTIM_TARGETS = (CROUCH_HALF_CM, CROUCH_EYE_CM, BODY_CM, STANDING_OFFSET_EYE_CM, EYE_CM,
                  BODY_CM + JUMP_CM, EYE_CM + JUMP_CM)
POS_RADIUS_CM = CAPSULE_R_CM
CONTROL_SAMPLE = 2000


def quiet() -> None:
    s3.quiet()
    for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(v, "1")


# ------------------------------------------------------------------ game files: penetration

def weapon_table() -> dict[str, dict]:
    """valorant-api weapon uuid (lowercase) -> name, UI tier and the projectiles' multipliers.

    The tier's multipliers are the modal pair over the tier's projectiles; a
    projectile's unset field is the component's native default, read as 1.0
    (Projectile_Gun's template sets neither)."""
    api = json.loads((STORE / "external" / "valorant-api" / "weapons.json").read_text(encoding="utf-8"))
    api = api.get("data", api)
    out = {}
    for w in api:
        tier = ((w.get("weaponStats") or {}).get("wallPenetration") or "None").split("::")[-1]
        folder = WEAPON_DATA / Path(w["assetPath"]).parent
        projs = {}
        for f in sorted(folder.glob("*.json")) if folder.exists() else []:
            for x in exports(f):
                if x.get("Type") == "WallPenetrationComponent":
                    p = x.get("Properties") or {}
                    projs[f.stem] = (float(p.get("PenetrationPowerMultiplier", 1.0)),
                                     float(p.get("StoppingDistanceMultiplier", 1.0)))
        out[w["uuid"].lower()] = {"name": w["displayName"], "tier": tier, "projectiles": projs,
                                  "asset": w["assetPath"]}
    by_tier = defaultdict(Counter)
    for w in out.values():
        for v in w["projectiles"].values():
            by_tier[w["tier"]][v] += 1
    by_tier["Medium"][(1.0, 1.0)] += 1  # rifles with no override inherit the defaults
    mult = {t: c.most_common(1)[0][0] for t, c in by_tier.items()}
    for w in out.values():
        w["ppm"], w["sdm"] = mult.get(w["tier"], (0.0, 0.0))
    return out


# ------------------------------------------------------------------ kills

def kill_rows(map_name: str, which: str) -> tuple[list[dict], dict]:
    """Every kill on the map with weapon, positions and the other living opponents."""
    import riot_ground_truth as rg
    if which == "dev":
        recs = rg.riot_records(STORE)
        excl = {}
        weapon_of = None
    else:
        import engagement_reach as er
        import pyarrow.parquet as pq
        records, _me, counts = er.ladder_records({map_name})
        hold = {r["match_id"] for r in pq.read_table(er.LADDER / "matches.parquet",
                                                     columns=["match_id", "holdout"]).to_pylist() if r["holdout"]}
        recs = {k: v for k, v in records.items() if k not in hold}
        excl = {"matches_on_map": len(records), "holdout_excluded": len(records) - len(recs)}
        weapon_of = {(r["match_id"], r["round"], r["time_in_round_ms"], r["killer"], r["victim"]): r["weapon_id"]
                     for r in pq.read_table(er.LADDER / "kills.parquet",
                                            columns=["match_id", "round", "time_in_round_ms", "killer", "victim",
                                                     "weapon_id"]).to_pylist()}
    out = []
    for sid, d in recs.items():
        m = d["match"]
        if m["matchInfo"].get("mapId") != s3.MAP_IDS[map_name]:
            continue
        team = {p["subject"]: p.get("teamId") for p in m.get("players") or []}
        for k in m.get("kills") or []:
            fd = k.get("finishingDamage") or {}
            item = fd.get("damageItem")
            if weapon_of is not None:
                item = weapon_of.get((sid, k.get("round"), k.get("roundTime"), k.get("killer"), k.get("victim")))
            loc = {p["subject"]: p["location"] for p in k.get("playerLocations") or []}
            kl = loc.get(k.get("killer"))
            kt = team.get(k.get("killer"))
            others = [(v["x"], v["y"]) for s_, v in loc.items()
                      if kt is not None and team.get(s_) not in (None, kt) and s_ != k.get("victim")]
            out.append({"sid": sid, "damage_type": fd.get("damageType"), "item": (item or "").lower() or None,
                        "killer_xy": (kl["x"], kl["y"]) if kl else None,
                        "victim_xy": (k["victimLocation"]["x"], k["victimLocation"]["y"]) if k.get("victimLocation") else None,
                        "others_xy": others})
    return out, excl


# ------------------------------------------------------------------ geometry

def los_any(wcast: s3.Caster, A: np.ndarray, B: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """A[n, m, 3], B[n, m, 3]: True where any valid pair m is clear."""
    n, m = valid.shape
    out = np.zeros(n, bool)
    if valid.any():
        ii = np.flatnonzero(valid.ravel())
        clear = ~wcast.occluded(A.reshape(-1, 3)[ii], B.reshape(-1, 3)[ii])
        hit = np.zeros(n * m, bool)
        hit[ii] = clear
        out = hit.reshape(n, m).any(axis=1)
    return out


def offsets() -> np.ndarray:
    """The recorded point, then 8 directions at half and full POS_RADIUS_CM."""
    ang = np.radians(np.arange(0, 360, 45))
    pts = [(0.0, 0.0)]
    for r in (0.5 * POS_RADIUS_CM, POS_RADIUS_CM):
        pts += [(r * math.cos(a), r * math.sin(a)) for a in ang]
    return np.asarray(pts)


def moved_points(pcast: s3.Caster, xy: np.ndarray, z: np.ndarray, clr: np.ndarray, h: float):
    """Points `h` above the recorded floor at every offset: (pts[n, k, 3], valid[n, k]).

    The floor height stays the recorded one, so a body overhanging a ledge
    keeps its height; an offset counts only when the Pawn blockers leave the
    straight way from the recorded point open at body height (a body never
    stands inside a wall)."""
    off = offsets()
    n, k = len(xy), len(off)
    P = (xy[:, None, :] + off[None]).reshape(-1, 2)
    zr = np.repeat(np.asarray(z, float), k)
    a = np.column_stack([np.repeat(xy, k, axis=0), zr + BODY_CM])
    b = np.column_stack([P, zr + BODY_CM])
    valid = np.ones(n * k, bool)
    mv = np.ones(n * k, bool)
    mv[::k] = False
    if mv.any():
        valid[mv] = ~pcast.occluded(a[mv], b[mv])
    pts = s3.eye_points(P, zr, np.repeat(np.asarray(clr, float), k), h)
    return pts.reshape(n, k, 3), valid.reshape(n, k)


def explain_blocked(wcast, pcast, kxy, kz, kc, kf, kcl, vxy, vz, vc, vf, vcl) -> dict:
    """The (b) and (c) tests for pairs whose standing eye-to-body line is blocked.

    Returns bool arrays: `head` (standing eye to head), `posture` (any killer
    eye height to any victim target), `floor_pair` (standing, any standable
    floor pair) and `position` (c)."""
    n = len(kxy)
    out = {}
    eye = s3.eye_points(kxy, kf, kcl, EYE_CM)
    out["head"] = ~wcast.occluded(eye, s3.eye_points(vxy, vf, vcl, EYE_CM)) if n else np.zeros(0, bool)
    A = np.stack([s3.eye_points(kxy, kf, kcl, h) for h in KILLER_EYES for _ in VICTIM_TARGETS], 1)
    B = np.stack([s3.eye_points(vxy, vf, vcl, h) for _ in KILLER_EYES for h in VICTIM_TARGETS], 1)
    out["posture"] = los_any(wcast, A, B, np.ones(A.shape[:2], bool))
    fp = np.zeros(n, bool)
    for li in range(s3.MAX_LAYERS):
        for lj in range(s3.MAX_LAYERS):
            g = ~np.isnan(kz[:, li]) & ~np.isnan(vz[:, lj])
            if g.any():
                e = s3.eye_points(kxy[g], kz[g, li], kc[g, li], EYE_CM)
                c = s3.eye_points(vxy[g], vz[g, lj], vc[g, lj], BODY_CM)
                fp[np.flatnonzero(g)] |= ~wcast.occluded(e, c)
    out["floor_pair"] = fp
    KE, kv = moved_points(pcast, kxy, kf, kcl, EYE_CM)
    VB, vv = moved_points(pcast, vxy, vf, vcl, BODY_CM)
    VH, _ = moved_points(pcast, vxy, vf, vcl, EYE_CM)
    k = KE.shape[1]
    A = np.repeat(KE, k, axis=1)
    valid = np.repeat(kv, k, axis=1) & np.tile(vv, (1, k))
    out["position"] = (los_any(wcast, A, np.tile(VB, (1, k, 1)), valid)
                       | los_any(wcast, A, np.tile(VH, (1, k, 1)), valid))
    out["moved_valid_share"] = float(np.r_[kv[:, 1:].ravel(), vv[:, 1:].ravel()].mean()) if n else float("nan")
    return out


def _is_gun(k: dict, weapons: dict) -> bool:
    return k["item"] in weapons and weapons[k["item"]]["tier"] != "None"


def cmd_rays(a) -> int:
    """Cast the gate's line and every class test for one map; store rays and crossings."""
    quiet()
    t0 = time.perf_counter()
    D = s3.load(a.map)
    T = D["tris"]
    widx = np.flatnonzero(D["weapon"])
    wcast = s3.Caster(T[D["weapon"]])
    pcast = s3.Caster(T[D["pawn"]])
    pcast.region = D["region"]
    weapons = weapon_table()
    kills, excl = kill_rows(a.map, a.set)
    dt = Counter(k["damage_type"] for k in kills)
    is_weapon = [k for k in kills if k["damage_type"] == "Weapon"]
    gun = [k for k in is_weapon if _is_gun(k, weapons) and k["killer_xy"] and k["victim_xy"]]
    e_counts = {f"damage_type:{t}": c for t, c in dt.items() if t != "Weapon"}
    e_counts["weapon_item_not_a_gun"] = sum(1 for k in is_weapon if not _is_gun(k, weapons))
    e_counts["gun_missing_position"] = sum(1 for k in is_weapon if _is_gun(k, weapons)
                                           and not (k["killer_xy"] and k["victim_xy"]))
    kxy = np.array([k["killer_xy"] for k in gun], float)
    vxy = np.array([k["victim_xy"] for k in gun], float)
    kz, kc, _ = s3.nearest_floors(pcast, kxy)
    vz, vc, _ = s3.nearest_floors(pcast, vxy)
    kf, kcl = s3.pick_floor(kz, kc)
    vf, vcl = s3.pick_floor(vz, vc)
    ok = ~np.isnan(kf) & ~np.isnan(vf)
    los = np.zeros(len(gun), bool)
    los[ok] = ~wcast.occluded(s3.eye_points(kxy[ok], kf[ok], kcl[ok], EYE_CM),
                              s3.eye_points(vxy[ok], vf[ok], vcl[ok], BODY_CM))
    bi = np.flatnonzero(ok & ~los)
    ex = explain_blocked(wcast, pcast, kxy[bi], kz[bi], kc[bi], kf[bi], kcl[bi], vxy[bi], vz[bi], vc[bi], vf[bi], vcl[bi])
    # control: the killer against every other living opponent; blocked pairs, a fixed sample
    ci = np.array([i for i, k in enumerate(gun) for _ in k["others_xy"]], np.int64)
    oxy = np.array([o for k in gun for o in k["others_xy"]], float).reshape(-1, 2)
    oz, oc, _ = s3.nearest_floors(pcast, oxy)
    of, ocl = s3.pick_floor(oz, oc)
    okc = ok[ci] & ~np.isnan(of)
    cl = np.zeros(len(ci), bool)
    cl[okc] = ~wcast.occluded(s3.eye_points(kxy[ci[okc]], kf[ci[okc]], kcl[ci[okc]], EYE_CM),
                              s3.eye_points(oxy[okc], of[okc], ocl[okc], BODY_CM))
    cb = np.flatnonzero(okc & ~cl)
    rng = np.random.default_rng(0)
    cs = np.sort(rng.choice(cb, min(len(cb), CONTROL_SAMPLE), replace=False)) if len(cb) else cb
    cki = ci[cs]
    cex = explain_blocked(wcast, pcast, kxy[cki], kz[cki], kc[cki], kf[cki], kcl[cki], oxy[cs], oz[cs], oc[cs], of[cs], ocl[cs])

    def lines(kk, txy, tf, tcl):
        e = s3.eye_points(kxy[kk], kf[kk], kcl[kk], EYE_CM)
        return (np.concatenate([e, e]),
                np.concatenate([s3.eye_points(txy, tf, tcl, BODY_CM), s3.eye_points(txy, tf, tcl, EYE_CM)]))

    # crossings for (a): standing eye to body, then to head; kills first, then controls
    A1, B1 = lines(bi, vxy[bi], vf[bi], vcl[bi])
    A2, B2 = lines(cki, oxy[cs], of[cs], ocl[cs])
    A, B = np.concatenate([A1, A2]), np.concatenate([B1, B2])
    ray, t, prim, facing, L = segment_hits(wcast, A, B)
    full = widx[prim]
    src = D["src"][full]
    first = np.full(int(D["src"].max()) + 1, -1, np.int64)
    srcs, fidx = np.unique(D["src"], return_index=True)
    first[srcs] = fidx
    local = full - first[src]
    seglen, open_s = intervals(ray, t, np.zeros_like(src), facing, L)
    OUT.mkdir(parents=True, exist_ok=True)
    nk = len(bi)
    res = {
        "map": a.map, "set": a.set, "table_version": D["provenance"].get("version"), "version": VERSION,
        "kills": len(kills), "gun_kills": len(gun), "gun_resolved": int(ok.sum()),
        "los3d_share": float(los[ok].mean()) if ok.any() else None,
        "blocked": int(nk), "control_pairs": int(okc.sum()), "control_blocked": int(len(cb)),
        "control_sample": int(len(cs)), "e": e_counts, "exclusions": excl,
        "moved_valid_share": ex["moved_valid_share"], "crossings": int(len(ray)),
        "seconds": time.perf_counter() - t0,
    }
    np.savez_compressed(
        OUT / f"{a.map}__{a.set}.npz",
        meta=json.dumps(res),
        k_item=np.array([gun[i]["item"] for i in bi], dtype="U36"),
        c_item=np.array([gun[i]["item"] for i in cki], dtype="U36"),
        k_sid=np.array([gun[i]["sid"] for i in bi], dtype="U64"),
        k_kxy=kxy[bi], k_vxy=vxy[bi], k_kf=kf[bi], k_vf=vf[bi], k_kcl=kcl[bi], k_vcl=vcl[bi],
        c_kxy=kxy[cki], c_oxy=oxy[cs],
        **{f"k_{n}": v for n, v in ex.items() if isinstance(v, np.ndarray)},
        **{f"c_{n}": v for n, v in cex.items() if isinstance(v, np.ndarray)},
        n_k=np.int64(nk), n_c=np.int64(len(cs)),
        h_ray=ray, h_t=t, h_full=full, h_src=src, h_local=local, h_facing=facing.astype(np.int8),
        h_len=seglen, h_open=open_s, L=L, A=A, B=B,
        gun_items=np.array([k["item"] for k in gun], dtype="U36"), gun_los=los, gun_ok=ok,
    )
    print(json.dumps(res, indent=1))
    return 0


# ------------------------------------------------------------------ occluding meshes and their surfaces

def _ray_files() -> list[Path]:
    return sorted(OUT.glob("*__dev.npz")) + sorted(OUT.glob("*__confirm.npz"))


def _extract(paths: list[str], out: Path, manifest: Path) -> None:
    """Export game paths with the store's extractor at Below Normal; never while the game runs."""
    tl = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    if "valorant" in tl or "riotclient" in tl:
        raise SystemExit("a VALORANT or Riot client process runs; not extracting")
    lst = manifest.with_suffix(".paths.txt")
    lst.write_text("\n".join(paths) + "\n", encoding="utf-8")
    exe = s3.EXTRACTOR / "src" / "bin" / "Release" / "net10.0" / "game-extract.exe"
    subprocess.run([str(exe), "export", "--paths", str(lst), "--out", str(out), "--manifest", str(manifest)],
                   cwd=str(s3.EXTRACTOR), check=True, creationflags=0x00004000 if sys.platform == "win32" else 0)


def occluder_meshes() -> dict[str, set[str]]:
    """Mesh object name ('Name.Name') of every placement a stored ray crosses, per map."""
    out: dict[str, set[str]] = defaultdict(set)
    for f in _ray_files():
        mp = f.stem.split("__")[0]
        with np.load(f) as z:
            srcs = np.unique(z["h_src"])
        D = s3.load(mp)
        meta = D["src_meta"]
        out[mp] |= {meta[int(s)]["mesh"] for s in srcs}
    return out


def cmd_meshes(a) -> int:
    """List (and with --export, extract) the occluding meshes, then their materials' parent chains."""
    per = occluder_meshes()
    names = sorted(set().union(*per.values()))
    idx = _index_paths({"StaticMesh"})
    paths, missing, ambiguous = [], [], 0
    for n in names:
        c = idx.get(n.split(".")[0].lower(), [])
        if not c:
            missing.append(n)
        ambiguous += len(c) > 1
        paths += c
    print(json.dumps({"maps": {k: len(v) for k, v in per.items()}, "meshes": len(names),
                      "paths": len(paths), "missing": len(missing), "ambiguous_names": ambiguous}, indent=1))
    if not a.export:
        return 0
    MESH_SET.mkdir(parents=True, exist_ok=True)
    todo = [p for p in paths if not _json_of(p).exists()]
    if todo:
        _extract(todo, MESH_SET, MESH_SET / f"manifest_meshes_{int(time.time())}.jsonl")
    # materials: walk each slot's parent chain to a Material
    seen: set[str] = set()
    frontier = set()
    for p in paths:
        for x in exports(_json_of(p)) if _json_of(p).exists() else []:
            if x.get("Type") == "StaticMesh":
                for s in (x.get("Properties") or {}).get("StaticMaterials") or []:
                    q = _obj_path(s.get("MaterialInterface"))
                    if q:
                        frontier.add(q)
            if x.get("Type") == "BodySetup":
                q = _obj_path((x.get("Properties") or {}).get("PhysMaterial"))
                if q:
                    frontier.add(q)
    for _ in range(12):
        todo = sorted(q for q in frontier - seen if not _json_of(q).exists())
        if todo:
            _extract(todo, MESH_SET, MESH_SET / f"manifest_materials_{int(time.time())}.jsonl")
        seen |= frontier
        nxt = set()
        for q in frontier:
            if not _json_of(q).exists():
                continue
            for x in exports(_json_of(q)):
                pr = x.get("Properties") or {}
                for key in ("Parent", "PhysMaterial"):
                    r_ = _obj_path(pr.get(key))
                    if r_:
                        nxt.add(r_)
        frontier = nxt - seen
        if not frontier:
            break
    print(json.dumps({"materials_and_physmats": len(seen)}, indent=1))
    return 0


def _load_rays(f: Path) -> dict:
    with np.load(f, allow_pickle=False) as z:
        d = {k: z[k] for k in z.files}
    d["meta"] = json.loads(str(d["meta"]))
    # path lengths follow the current `intervals` rule, never the stored one
    d["h_len"], d["h_open"] = intervals(d["h_ray"], d["h_t"], np.zeros_like(d["h_src"]), d["h_facing"], d["L"])
    return d


def ray_costs(d: dict, D: dict, surf: Surfaces, erm_of: np.ndarray) -> dict:
    """Per stored ray: effective thickness (sum of path length x ERM), raw thickness,
    whether an Impenetrable surface lies on it, open surfaces and unread surfaces."""
    nr = len(d["L"])
    ntris_of = np.bincount(D["src"], minlength=int(D["src"].max()) + 1)
    st, unread = surf.of(D["src_meta"], ntris_of, d["h_src"], d["h_local"])
    e = erm_of[np.minimum(st, len(erm_of) - 1)]
    impen = e >= IMPENETRABLE_ERM
    ray = d["h_ray"]
    return {"cost": np.bincount(ray, weights=d["h_len"] * np.where(impen, 0.0, e), minlength=nr),
            "thick": np.bincount(ray, weights=d["h_len"], minlength=nr),
            "impen": np.bincount(ray, weights=impen.astype(float), minlength=nr) > 0,
            "open": np.bincount(ray, weights=d["h_open"].astype(float), minlength=nr) > 0,
            "unread": np.bincount(ray, weights=unread.astype(float), minlength=nr) > 0,
            "crossings": np.bincount(ray, minlength=nr), "surface": st, "unread_crossing": unread}


def classify_rays(d: dict, rc: dict, weapons: dict, d0: float) -> dict:
    """Per stored kill and control pair: the (a) test at `d0`, and the primary class."""
    nk, nc = int(d["n_k"]), int(d["n_c"])
    sdm_k = np.array([weapons[i]["sdm"] for i in d["k_item"]], float)
    sdm_c = np.array([weapons[i]["sdm"] for i in d["c_item"]], float)

    def pen(lo, n, sdm):
        out = np.zeros(n, bool)
        for off in (lo, lo + n):  # body ray, then head ray
            r = slice(off, off + n)
            out |= ~rc["impen"][r] & (rc["cost"][r] <= d0 * sdm)
        return out

    res = {}
    for who, lo, n, sdm in (("k", 0, nk, sdm_k), ("c", 2 * nk, nc, sdm_c)):
        a_ = pen(lo, n, sdm)
        b_ = d[f"{who}_head"] | d[f"{who}_posture"] | d[f"{who}_floor_pair"]
        c_ = d[f"{who}_position"]
        prim = np.where(b_, "b", np.where(c_, "c", np.where(a_, "a", "f")))
        res[who] = {"a": a_, "b": b_, "c": c_, "primary": prim}
    return res


def cmd_classify(a) -> int:
    quiet()
    erm, cls_names, extra = surface_table()
    weapons = weapon_table()
    surf = Surfaces()
    names = surface_names()
    rows, per_map, weapon_rows = [], {}, defaultdict(Counter)
    sweep = defaultdict(lambda: defaultdict(Counter))
    surf_counts = {"dev": Counter(), "confirm": Counter()}
    unread_crossings = Counter()
    for f in _ray_files():
        mp, st = f.stem.split("__")
        d = _load_rays(f)
        D = s3.load(mp)
        rc = ray_costs(d, D, surf, erm)
        unread_crossings[st] += int(rc["unread_crossing"].sum())
        unread_crossings[st + "_all"] += len(rc["unread_crossing"])
        nk = int(d["n_k"])
        kr = np.r_[np.arange(nk), np.arange(nk, 2 * nk)]
        for s_ in rc["surface"][np.isin(d["h_ray"], kr)]:
            surf_counts[st][names.get(int(s_), str(s_))] += 1
        for d0 in D0_SWEEP:
            r = classify_rays(d, rc, weapons, d0)
            for who in ("k", "c"):
                sweep[st][d0][who + "_n"] += len(r[who]["a"])
                sweep[st][d0][who + "_a_any"] += int(r[who]["a"].sum())
                sweep[st][d0][who + "_a_primary"] += int((r[who]["primary"] == "a").sum())
        r = classify_rays(d, rc, weapons, a.d0)
        r["k"]["primary"] = apply_inspection(mp, st, d, r["k"]["primary"])
        m = d["meta"]
        pk = Counter(r["k"]["primary"].tolist())
        pc = Counter(r["c"]["primary"].tolist())
        sub = Counter()
        for i in range(nk):
            if r["k"]["primary"][i] == "b":
                sub["b_head" if d["k_head"][i] else ("b_posture" if d["k_posture"][i] else "b_floor_pair")] += 1
        per_map[mp] = {
            "set": st, "table_version": m["table_version"], "gun_resolved": m["gun_resolved"],
            "los3d_share": m["los3d_share"], "blocked": nk,
            "control_pairs": m["control_pairs"], "control_blocked": m["control_blocked"],
            "e": m["e"], "primary": {c: pk.get(c, 0) for c in "bcadf"}, "b_sub": dict(sub),
            "alone": {c: int(r["k"][c].sum()) for c in "abc"},
            "a_only": int((r["k"]["a"] & ~r["k"]["b"] & ~r["k"]["c"]).sum()),
            "residual": int((~r["k"]["b"] & ~r["k"]["c"]).sum()),
            "control_residual": int((~r["c"]["b"] & ~r["c"]["c"]).sum()),
            "control_a_only": int((r["c"]["a"] & ~r["c"]["b"] & ~r["c"]["c"]).sum()),
            "control_n": int(d["n_c"]), "control_primary": {c: pc.get(c, 0) for c in "bcaf"},
            "control_alone": {c: int(r["c"][c].sum()) for c in "abc"},
            "rays_open_surface": int(rc["open"][:2 * nk].sum()), "rays_unread_surface": int(rc["unread"][:2 * nk].sum()),
            "median_thickness_cm_body_ray": float(np.median(rc["thick"][:nk])) if nk else None,
            "median_cost_cm_body_ray": float(np.median(np.where(rc["impen"][:nk], np.inf, rc["cost"][:nk]))) if nk else None,
            "impenetrable_body_rays": int(rc["impen"][:nk].sum()),
        }
        for i, it in enumerate(d["gun_items"][d["gun_ok"]]):
            weapon_rows[(st, it)]["gun_kills"] += 1
        for i in range(nk):
            it = d["k_item"][i]
            weapon_rows[(st, it)]["blocked"] += 1
            weapon_rows[(st, it)]["a_primary"] += r["k"]["primary"][i] == "a"
            weapon_rows[(st, it)]["a_any"] += bool(r["k"]["a"][i])
            rows.append({"map": mp, "set": st, "i": i, "weapon": weapons[it]["name"], "tier": weapons[it]["tier"],
                         "primary": str(r["k"]["primary"][i]), "a": bool(r["k"]["a"][i]), "b": bool(r["k"]["b"][i]),
                         "c": bool(r["k"]["c"][i]), "head": bool(d["k_head"][i]), "posture": bool(d["k_posture"][i]),
                         "floor_pair": bool(d["k_floor_pair"][i]),
                         "cost_body": float(rc["cost"][i]), "cost_head": float(rc["cost"][nk + i]),
                         "thick_body": float(rc["thick"][i]), "impen_body": bool(rc["impen"][i]),
                         "impen_head": bool(rc["impen"][nk + i]), "open": bool(rc["open"][i] | rc["open"][nk + i]),
                         "crossings_body": int(rc["crossings"][i]), "dist_m": float(d["L"][i] / 100.0)})
    tot = {}
    for st in ("dev", "confirm"):
        mm = [v for v in per_map.values() if v["set"] == st]
        n = sum(v["blocked"] for v in mm)
        prim = {c: sum(v["primary"][c] for v in mm) for c in "bcadf"}
        alone = {c: sum(v["alone"][c] for v in mm) for c in "abc"}
        cn = sum(v["control_n"] for v in mm)
        calone = {c: sum(v["control_alone"][c] for v in mm) for c in "abc"}
        ecount = Counter()
        for v in mm:
            ecount.update(v["e"])
        cp = sum(v["control_pairs"] for v in mm)
        cbl = sum(v["control_blocked"] for v in mm)
        gr = sum(v["gun_resolved"] for v in mm)
        # post hoc: what a penetrable layer does to the gate's separation (kill minus control)
        c_los = 1.0 - cbl / cp if cp else None
        c_pen = calone["a"] / cn if cn else None
        sep = {"kill_los": 1.0 - n / gr, "control_los": c_los,
               "kill_los_or_pen": 1.0 - (n - alone["a"]) / gr,
               "control_los_or_pen": c_los + (1.0 - c_los) * c_pen if cp and cn else None}
        tot[st] = {"gun_resolved": gr, "blocked": n, "primary": prim, "separation": sep,
                   "primary_share": {c: prim[c] / n for c in prim} if n else None,
                   "alone": alone, "alone_share": {c: alone[c] / n for c in alone} if n else None,
                   "a_only": sum(v["a_only"] for v in mm),
                   "residual": sum(v["residual"] for v in mm),
                   "control_residual": sum(v["control_residual"] for v in mm),
                   "control_a_only": sum(v["control_a_only"] for v in mm),
                   "control_n": cn, "control_alone_share": {c: calone[c] / cn for c in calone} if cn else None,
                   "a_enrichment": (alone["a"] / n) / (calone["a"] / cn) if n and cn and calone["a"] else None,
                   "e": dict(ecount),
                   "sweep": {str(d0): {k_: v_ for k_, v_ in sweep[st][d0].items()} for d0 in D0_SWEEP},
                   "unread_crossing_share": unread_crossings[st] / max(1, unread_crossings[st + "_all"]),
                   "surfaces_on_kill_rays": dict(surf_counts[st].most_common())}
    wr = []
    for (st, it), c in weapon_rows.items():
        wr.append({"set": st, "weapon": weapons[it]["name"], "tier": weapons[it]["tier"], **c,
                   "a_primary_share": c["a_primary"] / c["gun_kills"] if c["gun_kills"] else None,
                   "a_any_share": c["a_any"] / c["gun_kills"] if c["gun_kills"] else None})
    wr.sort(key=lambda r: (r["set"], -(r["a_primary_share"] or 0)))
    out = {"version": VERSION, "d0_cm": a.d0, "high_erm": HIGH_ERM, "pos_radius_cm": POS_RADIUS_CM,
           "killer_eyes_cm": KILLER_EYES, "victim_targets_cm": VICTIM_TARGETS,
           "surface_classes": {names.get(i, str(i)): cls_names[i] for i in range(len(cls_names))},
           "curve": extra["curve"], "totals": tot, "maps": per_map, "weapons": wr}
    print(json.dumps(out, indent=1, default=str))
    if a.list:
        Path(a.list).write_text(json.dumps(rows, indent=0), encoding="utf-8")
    if a.record:
        _record(out)
    return 0



# ------------------------------------------------------------------ inspection

def _canvas(polys: np.ndarray, lo: np.ndarray, hi: np.ndarray, px: int, flip_y: bool = True):
    """A white canvas spanning [lo, hi] at `px` pixels on the long side, with a cm -> px map."""
    import cv2
    span = np.maximum(hi - lo, 1.0)
    sc = px / span.max()
    w, h = int(span[0] * sc) + 1, int(span[1] * sc) + 1
    img = np.full((h, w, 3), 255, np.uint8)

    def to(p):
        p = (np.asarray(p, float) - lo) * sc
        if flip_y:
            p[..., 1] = h - 1 - p[..., 1]
        return np.round(p).astype(np.int32)

    over = img.copy()
    if len(polys):
        cv2.fillPoly(over, list(to(polys)), (150, 150, 150))
        cv2.polylines(over, list(to(polys)), True, (90, 90, 90), 1)
    img = cv2.addWeighted(over, 0.5, img, 0.5, 0)
    return img, to


def cmd_render(a) -> int:
    """Plan and section of one stored kill's eye-to-body line over the table's geometry.

    Plan (left): Weapon-set triangles within 4 m of the line whose height span
    meets the line's band (eye and target heights, +-50 cm), north up. Section
    (right): triangles within 50 cm of the line's vertical plane, as (distance
    along the line, height). The line is red, the killer's eye blue, the
    victim's body centre red, its head a red triangle; crossings are black dots,
    listed with placement and surface."""
    import cv2
    d = _load_rays(OUT / f"{a.map}__{a.set}.npz")
    D = s3.load(a.map)
    i = a.kill
    A, B = d["A"][i], d["B"][i]
    W = D["tris"][D["weapon"]].astype(np.float64)
    u = (B - A)[:2]
    L2 = float(np.linalg.norm(u))
    u = u / max(L2, 1e-9)
    nrm = np.array([-u[1], u[0]])
    rel = W.mean(axis=1)[:, :2] - A[:2]
    s, q = rel @ u, rel @ nrm
    zlo, zhi = min(A[2], B[2]) - 50.0, max(A[2], B[2]) + 50.0
    near = (s > -400) & (s < L2 + 400) & (np.abs(q) < 400)
    band = near & (W[:, :, 2].max(1) >= zlo) & (W[:, :, 2].min(1) <= zhi)
    plane = near & (np.abs(q) < 50.0)
    _erm, cls_names, _ = surface_table()
    surf = Surfaces()
    names = surface_names()
    sel = d["h_ray"] == i
    ntris_of = np.bincount(D["src"], minlength=int(D["src"].max()) + 1)
    st, _unr = surf.of(D["src_meta"], ntris_of, d["h_src"][sel], d["h_local"][sel])
    frac = d["h_t"][sel] / d["L"][i]
    lo = np.minimum(A[:2], B[:2]) - 400
    hi = np.maximum(A[:2], B[:2]) + 400
    plan, to = _canvas(W[band][:, :, :2], lo, hi, 700)
    cv2.line(plan, tuple(to(A[:2])), tuple(to(B[:2])), (0, 0, 255), 2)
    cv2.circle(plan, tuple(to(A[:2])), 6, (255, 0, 0), -1)
    cv2.drawMarker(plan, tuple(to(B[:2])), (0, 0, 255), cv2.MARKER_CROSS, 14, 2)
    for p in A[:2] + (B[:2] - A[:2]) * frac[:, None]:
        cv2.circle(plan, tuple(to(p)), 3, (0, 0, 0), -1)
    SZ = np.stack([(W[plane][:, :, :2] - A[:2]) @ u, W[plane][:, :, 2]], axis=-1)
    slo = np.array([-200.0, min(A[2], B[2]) - 300])
    shi = np.array([L2 + 200.0, max(A[2], B[2]) + 400])
    sec, ts = _canvas(SZ, slo, shi, 900)
    cv2.line(sec, tuple(ts([0, A[2]])), tuple(ts([L2, B[2]])), (0, 0, 255), 2)
    cv2.circle(sec, tuple(ts([0, A[2]])), 6, (255, 0, 0), -1)
    cv2.drawMarker(sec, tuple(ts([L2, B[2]])), (0, 0, 255), cv2.MARKER_CROSS, 14, 2)
    cv2.drawMarker(sec, tuple(ts([L2, B[2] - BODY_CM + EYE_CM])), (0, 0, 255), cv2.MARKER_TRIANGLE_UP, 12, 2)
    for f_ in frac:
        cv2.circle(sec, tuple(ts([f_ * L2, A[2] + (B[2] - A[2]) * f_])), 3, (0, 0, 0), -1)
    lines = [f"{a.map} {a.set} #{i}  {float(d['L'][i]) / 100:.1f} m  eye z {A[2]:.0f}  target z {B[2]:.0f}"]
    for t_, sr, f_, ln, sf in zip(d["h_t"][sel], d["h_src"][sel], d["h_facing"][sel], d["h_len"][sel], st):
        mm = D["src_meta"][int(sr)]
        lines.append(f"{t_:6.0f}cm {'in ' if f_ < 0 else 'out'} len {ln:4.0f} {names.get(int(sf), sf)}/"
                     f"{cls_names[min(int(sf), 38)][8:]} {mm['level']}:{mm['actor'][:26]} {mm['mesh'].split('.')[0][:30]}")
    hgt = max(plan.shape[0], sec.shape[0])
    pad = lambda im: cv2.copyMakeBorder(im, 0, hgt - im.shape[0], 0, 10, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    top = np.hstack([pad(plan), pad(sec)])
    txt = np.full((18 * min(len(lines), 16) + 10, top.shape[1], 3), 255, np.uint8)
    for k_, ln in enumerate(lines[:16]):
        cv2.putText(txt, ln, (6, 16 + 18 * k_), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.imwrite(a.out, np.vstack([top, txt]))
    print("\n".join(lines))
    print(json.dumps({"killer_floor": float(d["k_kf"][i]), "victim_floor": float(d["k_vf"][i]),
                      "head": bool(d["k_head"][i]), "posture": bool(d["k_posture"][i]),
                      "floor_pair": bool(d["k_floor_pair"][i]), "position": bool(d["k_position"][i])}))
    return 0


#: (d) by eye on `render` (2026-10-05): the kills whose blocked line the table,
#: not the bullet, explains. Keyed by (map, set, stored index) with the
#: killer's recorded (x, y) so a changed ray file cannot misapply a verdict.
#: Each of the four sits beside Split's A-tower ascender rope; with the rope
#: side's feet at 4.75-5.75 m or higher (tested to 9.75 m; floors at 2.5 and 6.5 m)
#: the line clears, so the player hung on the rope, a height the floor model
#: (standable floors only) cannot hold.
TABLE_WRONG = {
    ("split", "dev", 7): ((4257, -6169), "rope: victim on Split's A-tower ascender, between floors"),
    ("split", "dev", 15): ((4019, -5942), "rope: victim on Split's A-tower ascender, between floors"),
    ("split", "dev", 19): ((3590, -5947), "rope: killer on Split's A-tower ascender, between floors"),
    ("split", "dev", 42): ((5079, -6677), "rope: victim on Split's A-tower ascender, between floors"),
}


def apply_inspection(mp: str, st: str, d: dict, prim: np.ndarray) -> np.ndarray:
    prim = prim.copy()
    for (m_, s_, i), (xy, _why) in TABLE_WRONG.items():
        if m_ == mp and s_ == st and i < len(prim):
            if np.allclose(d["k_kxy"][i], xy, atol=1.0) and prim[i] == "f":
                prim[i] = "d"
    return prim


def _record(out: dict) -> None:
    sys.path.insert(0, str(s3.REPO))
    from reticle import metrics
    deps = {"version": VERSION, "d0_cm": out["d0_cm"], "high_erm": HIGH_ERM, "pos_radius_cm": POS_RADIUS_CM,
            "eye_cm": EYE_CM, "body_cm": BODY_CM, "tables": {m: v["table_version"] for m, v in out["maps"].items()},
            "game_build": s3.GAME_BUILD}
    ctx = {"placeholders": ["d0_cm", "high_erm", "crouch_eye_cm"], "killer_eyes_cm": KILLER_EYES,
           "victim_targets_cm": VICTIM_TARGETS, "inspected_table_wrong": len(TABLE_WRONG)}
    for st, t in out["totals"].items():
        vals = {"gun_resolved": t["gun_resolved"], "blocked": t["blocked"], "a_only": t["a_only"],
                "residual": t["residual"], "control_n": t["control_n"], "control_residual": t["control_residual"],
                "control_a_only": t["control_a_only"], "a_enrichment": t["a_enrichment"],
                "unread_crossing_share": t["unread_crossing_share"]}
        for c, v in t["primary"].items():
            vals[f"primary_{c}"] = v
            vals[f"primary_{c}_share"] = v / t["blocked"]
        for c, v in t["alone"].items():
            vals[f"alone_{c}"] = v
            vals[f"alone_{c}_share"] = v / t["blocked"]
        for c, v in t["control_alone_share"].items():
            vals[f"control_alone_{c}_share"] = v
        vals["a_share_of_gun_kills"] = t["primary"]["a"] / t["gun_resolved"]
        for k_, v_ in t["separation"].items():
            vals["sep." + k_] = v_
        sp = t["separation"]
        vals["sep.gain"] = ((sp["kill_los_or_pen"] - sp["control_los_or_pen"])
                            - (sp["kill_los"] - sp["control_los"]))
        vals["residual_a_share"] = t["a_only"] / t["residual"] if t["residual"] else None
        vals["control_residual_a_share"] = t["control_a_only"] / t["control_residual"] if t["control_residual"] else None
        for d0, s in t["sweep"].items():
            k = f"d{int(float(d0))}"
            vals[f"{k}.a_primary"] = s["k_a_primary"]
            vals[f"{k}.a_any"] = s["k_a_any"]
            vals[f"{k}.control_a_primary"] = s["c_a_primary"]
            vals[f"{k}.control_a_any"] = s["c_a_any"]
        for c, v in t["e"].items():
            vals["e." + c.replace("damage_type:", "")] = v
        for w in out["weapons"]:
            if w["set"] == st:
                vals[f"weapon.{w['weapon']}.gun_kills"] = w["gun_kills"]
                vals[f"weapon.{w['weapon']}.a_primary"] = w.get("a_primary", 0)
                vals[f"weapon.{w['weapon']}.a_any"] = w.get("a_any", 0)
        vals = {k: v for k, v in vals.items() if isinstance(v, (int, float)) and v is not None}
        note = ("development set (22 captured matches); scores wallbang-probe-20261005 W1-W5" if st == "dev" else
                "instrument check on the confirmation history (held-out replay, captured and ladder holdout "
                "matches excluded); no hypothesis scored")
        metrics.record("wallbang_probe", part=f"classify/{st}", values=vals, deps=deps, context=dict(ctx, set=st),
                       note=note)
    for mp, v in out["maps"].items():
        vals = {"blocked": v["blocked"], "gun_resolved": v["gun_resolved"], "los3d_share": v["los3d_share"],
                "a_only": v["a_only"], "residual": v["residual"], "control_n": v["control_n"],
                "control_a_only": v["control_a_only"], "control_residual": v["control_residual"],
                "median_thickness_cm_body_ray": v["median_thickness_cm_body_ray"],
                "rays_open_surface": v["rays_open_surface"], "rays_unread_surface": v["rays_unread_surface"]}
        for c, n in v["primary"].items():
            vals[f"primary_{c}"] = n
        for c, n in v["alone"].items():
            vals[f"alone_{c}"] = n
        for c, n in v["control_alone"].items():
            vals[f"control_alone_{c}"] = n
        for c, n in v["e"].items():
            vals["e." + c.replace("damage_type:", "")] = n
        vals = {k: x for k, x in vals.items() if isinstance(x, (int, float)) and x is not None}
        metrics.record("wallbang_probe", part=f"classify/{mp}", values=vals, deps=deps, context=dict(ctx, set=v["set"]),
                       note="per-map counts; " + ("development set" if v["set"] == "dev" else "instrument check"))


# ------------------------------------------------------------------ what a penetrable layer would cost

def cmd_cost(a) -> int:
    """Time the penetrable layer on a sample of one map's cell pairs and extrapolate.

    The visibility table casts one occlusion ray per cell pair; a penetrable
    layer would also, for each blocked pair, find every crossing, pair the
    crossings into solid intervals and look up each crossing's surface. Both
    are timed on the same random pairs (seeded), on one core at Below Normal."""
    quiet()
    D = s3.load(a.map)
    W = s3.Caster(D["tris"][D["weapon"]])
    widx = np.flatnonzero(D["weapon"])
    n = len(D["cell_z"])
    pts = s3.eye_points(D["cell_xy"].astype(np.float64), D["cell_z"].astype(np.float64),
                        D["cell_clear"].astype(np.float64), EYE_CM)
    rng = np.random.default_rng(0)
    i = rng.integers(0, n, a.pairs)
    j = rng.integers(0, n, a.pairs)
    keep = i != j
    i, j = i[keep], j[keep]
    t0 = time.perf_counter()
    occ = W.occluded(pts[i], pts[j])
    t_occ = time.perf_counter() - t0
    bi, bj = i[occ], j[occ]
    t1 = time.perf_counter()
    ray, t, prim, facing, L = segment_hits(W, pts[bi], pts[bj])
    full = widx[prim]
    src = D["src"][full]
    seglen, _open = intervals(ray, t, np.zeros_like(src), facing, L)
    t_hits = time.perf_counter() - t1
    t2 = time.perf_counter()
    first = np.full(int(D["src"].max()) + 1, -1, np.int64)
    srcs, fidx = np.unique(D["src"], return_index=True)
    first[srcs] = fidx
    erm, _names, _ = surface_table()
    surf = Surfaces()
    ntris_of = np.bincount(D["src"], minlength=int(D["src"].max()) + 1)
    st, unread = surf.of(D["src_meta"], ntris_of, src, full - first[src])
    e = erm[np.minimum(st, len(erm) - 1)]
    cost = np.bincount(ray, weights=seglen * np.where(e >= IMPENETRABLE_ERM, 0.0, e), minlength=len(bi))
    impen = np.bincount(ray, weights=(e >= IMPENETRABLE_ERM).astype(float), minlength=len(bi)) > 0
    t_surf = time.perf_counter() - t2
    pairs = n * (n - 1) // 2
    blocked_share = float(occ.mean())
    per_occ = t_occ / len(i)
    per_extra = (t_hits + t_surf) / max(len(bi), 1)
    q = np.where(impen, 255, np.minimum(np.round(cost / 5.0), 254)).astype(np.uint8)
    import zlib
    sample_bytes = np.zeros(len(i), np.uint8)
    sample_bytes[occ] = q
    ratio = len(zlib.compress(sample_bytes.tobytes(), 6)) / len(sample_bytes)
    meshes_needed = {D["src_meta"][int(s)]["mesh"] for s in np.unique(D["src"][widx])}
    have = sum(1 for m_ in meshes_needed if any(_json_of(p).exists() for p in surf.idx.get(m_.split(".")[0].lower(), [])))
    res = {"map": a.map, "table_version": D["provenance"].get("version"), "cells": n, "pairs": pairs,
           "sample_pairs": int(len(i)), "blocked_share": blocked_share,
           "seconds_per_pair_occlusion": per_occ, "seconds_per_blocked_pair_layer": per_extra,
           "layer_build_seconds": pairs * blocked_share * per_extra,
           "table_build_seconds_same_rate": pairs * per_occ,
           "layer_over_table": (blocked_share * per_extra) / per_occ,
           "crossings_per_blocked_pair": len(ray) / max(len(bi), 1),
           "seconds_crossings_sample": t_hits, "seconds_surfaces_sample": t_surf, "seconds_occlusion_sample": t_occ,
           "bytes_tier_mask_2bit": pairs // 4, "bytes_uint8_cost": pairs,
           "uint8_zlib_ratio_on_sample": ratio, "bytes_uint8_cost_zlib_estimate": int(pairs * ratio),
           "vis_bits_bytes": int(len(D["vis_bits"])),
           "weapon_meshes": len(meshes_needed), "weapon_meshes_exported": have,
           "unread_crossing_share_sample": float(unread.mean()) if len(unread) else None}
    print(json.dumps(res, indent=1))
    if a.record:
        sys.path.insert(0, str(s3.REPO))
        from reticle import metrics
        metrics.record("wallbang_probe", part=f"cost/{a.map}",
                       values={k: v for k, v in res.items() if isinstance(v, (int, float))},
                       deps={"version": VERSION, "table": res["table_version"], "d0_cm": D0_CM},
                       context={"sample_seed": 0, "cpu": "one core, Below Normal, other work on the CPU"},
                       note="timing on a seeded sample of cell pairs, extrapolated to the map's table; post hoc")
    return 0


# ------------------------------------------------------------------ self-test

def classify_line(caster: s3.Caster, a: np.ndarray, b: np.ndarray, surface_of_tri: np.ndarray, erm: np.ndarray,
                  sdm: float, d0: float = D0_CM) -> dict:
    """The (a) test on explicit lines: crossings, solid path, effective thickness, verdict."""
    ray, t, prim, facing, L = segment_hits(caster, a, b)
    seglen, open_s = intervals(ray, t, np.zeros_like(prim), facing, L)
    e = erm[surface_of_tri[prim]]
    impen = np.bincount(ray, weights=(e >= IMPENETRABLE_ERM).astype(float), minlength=len(a)) > 0
    cost = np.bincount(ray, weights=seglen * np.where(e >= IMPENETRABLE_ERM, 0.0, e), minlength=len(a))
    thick = np.bincount(ray, weights=seglen, minlength=len(a))
    return {"thick": thick, "cost": cost, "impen": impen, "penetrable": ~impen & (cost <= d0 * sdm),
            "crossings": np.bincount(ray, minlength=len(a)), "open": np.bincount(ray, weights=open_s.astype(float),
                                                                             minlength=len(a)) > 0}


def _self_test() -> int:
    """A line through a thin wall, a thick wall, an impenetrable wall and a single-sided plane."""
    import trimesh

    def box(c, e):
        return np.asarray(trimesh.creation.box(extents=e).triangles) + np.asarray(c, float)

    thin = box((0, 0, 150), (10, 400, 300))        # 10 cm concrete at x = 0
    thick = box((0, 1000, 150), (150, 400, 300))   # 150 cm at x = 0, y = 1000
    steel = box((0, 2000, 150), (10, 400, 300))    # 10 cm, impenetrable surface
    plane = np.array([[[0, 2900, 0], [0, 3100, 0], [0, 3100, 300]],
                      [[0, 2900, 0], [0, 3100, 300], [0, 2900, 300]]], float)
    T = np.concatenate([thin, thick, steel, plane]).astype(np.float32)
    surf = np.r_[np.full(len(thin), 1), np.full(len(thick), 1), np.full(len(steel), 13), np.full(len(plane), 6)]
    erm, _names, _ = surface_table()
    c = s3.Caster(T)
    a = np.array([[-500, y, 160] for y in (0, 1000, 2000, 3000, 500)], float)
    b = np.array([[500, y, 160] for y in (0, 1000, 2000, 3000, 500)], float)
    r = classify_line(c, a, b, surf, erm, sdm=1.0)
    assert abs(r["thick"][0] - 10) < 0.5 and r["penetrable"][0], r
    assert abs(r["thick"][1] - 150) < 0.5 and not r["penetrable"][1], r
    assert r["impen"][2] and not r["penetrable"][2], r
    assert r["open"][3] and r["thick"][3] == 0 and r["penetrable"][3], r
    assert r["crossings"][4] == 0 and r["penetrable"][4], r
    r_low = classify_line(c, a, b, surf, erm, sdm=0.05)       # a weak weapon stops in 10 cm of concrete
    assert not r_low["penetrable"][0], r_low
    print("wallbang_probe self-test: ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("rays")
    r.add_argument("--map", required=True)
    r.add_argument("--set", default="dev", choices=["dev", "confirm"])
    m = sub.add_parser("meshes")
    m.add_argument("--export", action="store_true")
    c = sub.add_parser("classify")
    c.add_argument("--record", action="store_true")
    c.add_argument("--d0", type=float, default=D0_CM)
    c.add_argument("--list", default=None, help="write the per-kill rows (store only) to this JSON")
    v = sub.add_parser("render")
    v.add_argument("--map", required=True)
    v.add_argument("--set", default="dev", choices=["dev", "confirm"])
    v.add_argument("--kill", type=int, required=True)
    v.add_argument("--out", required=True)
    k = sub.add_parser("cost")
    k.add_argument("--map", default="ascent")
    k.add_argument("--pairs", type=int, default=200_000)
    k.add_argument("--record", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    return {"rays": cmd_rays, "meshes": cmd_meshes, "classify": cmd_classify, "render": cmd_render,
            "cost": cmd_cost}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
