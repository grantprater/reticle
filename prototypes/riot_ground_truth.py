r"""Score stored outputs against Riot's own match records.

    .\.venv\Scripts\python.exe prototypes\riot_ground_truth.py SESSION [SESSION ...]
    .\.venv\Scripts\python.exe prototypes\riot_ground_truth.py --all [--record] [--json OUT]
    .\.venv\Scripts\python.exe prototypes\riot_ground_truth.py SESSION --list-misses

Why this exists
---------------
Every check before this one compared the pipeline with itself or with a figure
the player transcribed (`checks.KNOWN_KD`). Riot's match-details record is the
first independent witness of every kill: its game time, killer, victim, weapon,
assists and every living player's position and view angle at that instant,
plus each round's winner, plant and defuse. The records live in the store
(`<store>/external/riot/<match>.json`, `{"probe": {...}, "match": {...}}`) and
never in the repository; this file embeds none of them.

It reads stored streams only (`death`, the round table, the HUD killfeed
counts through `status.collect`, `combat_report_round`, `round_entity`,
`ally_icon`, `minimap_object`) and decodes nothing. It decides nothing about
the game: every name it compares comes from the owner that stores it.

The alignment and what it rests on
----------------------------------
Capture time is fitted as `t = a + b * gameTime` from Riot kills against the
stored deaths' first killfeed sample (`t_ms`, a 2 Hz grid). A coarse search
over `a` counts kills within `ALIGN_TOL_MS` of a stored death; a greedy
one-to-one assignment then refits `a` and `b` by least squares. The fit RESTS
ON THE KILLFEED, so killfeed timing scored after it measures jitter, not
offset; the HUD round starts and plant times are the independent cross-check.
`a` carries the killfeed's mean sampling lag (half a 500 ms step) and its
render latency; the minimap is read at `a + MINIMAP_LAG_MS + gameTime`, and
`--scan-lag` measures that lag on the self icon instead of assuming it.

The coordinate transform
------------------------
Riot positions are game units (centimetres). valorant-api's map record gives
`u = y * xMultiplier + xScalarToAdd`, `v = x * yMultiplier + yScalarToAdd` on
the map's display icon; the wiki art the geometry was fitted to is the same
asset (alpha IoU 0.996-1.000 at equal size), so `(u, v)` times the art side is
an art pixel, and the geometry npz's `shade_fit` (`prototypes/map_shade.py`'s
`_warp` then `wiki_map._place`) carries it into baked widget pixels, the frame
every stored minimap coordinate uses (`reticle/widget_frame.py`). The swap of
axes is checked on data, not assumed: `--axes` scores both.

Matching tolerances
-------------------
A Riot kill matches a stored death within `MATCH_TOL_MS` of the aligned time,
one to one, nearest first. The killfeed is sampled at 2 Hz, so a correct
entry lands 0-500 ms after the aligned instant plus render jitter; the
residual histogram (printed) shows where the tail begins. Teammates match
stored pieces within `GATE_M` metres, one to one, nearest first.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RIOT_TRUTH_VERSION = "riot-truth-0.1.0"
STORE = Path.home() / "reticle-store"
API_BASE = "https://valorant-api.com/v1/"

#: Coarse alignment: a kill counts toward an offset when a stored death lies
#: within this window of it. Wide enough to hold the 2 Hz grid and latency.
ALIGN_TOL_MS = 1500.0
ALIGN_STEP_MS = 250.0
#: A Riot kill and a stored death match within this many ms after alignment.
#: Two 500 ms killfeed samples plus render jitter either way; see `residuals`.
MATCH_TOL_MS = 1500.0
#: Two Riot kills closer than this are ambiguous for a time-only assignment.
AMBIGUOUS_MS = 500.0
#: The minimap read time relative to the killfeed-fitted offset. The fit's
#: offset includes about half a killfeed step of sampling lag plus the feed's
#: render delay. Measured with `--scan-lag` on the self icon (three sessions,
#: 2026-10-02): the median self error is least between -533 and -400 ms.
MINIMAP_LAG_MS = -450.0
#: The furthest a stored minimap frame may be from the asked instant.
FRAME_TOL_MS = 70.0
#: Teammate gate in metres (Riot units are centimetres).
GATE_M = 8.0

ABILITY_SLOT = {"Ability1": "Ability1", "Ability2": "Ability2",
                "GrenadeAbility": "Grenade", "Ultimate": "Ultimate"}
#: Names that mean one thing under two spellings.
SAME_NAME = {"melee": "tactical knife", "tactical knife": "tactical knife"}


# ----------------------------------------------------------------- reference

def canon(name: str | None) -> str | None:
    """One spelling per agent or weapon: `KAY/O` and `KAY_O` agree."""
    if name is None:
        return None
    s = str(name).strip().replace("/", "_").casefold()
    return SAME_NAME.get(s, s)


class Reference:
    """valorant-api agents, weapons and maps, cached under `api_dir`."""

    def __init__(self, api_dir: Path, fetch: bool = True):
        self.dir = Path(api_dir)
        self.agents = {a["uuid"].lower(): a["displayName"]
                       for a in self._get("agents", fetch)}
        self.weapons = {w["uuid"].lower(): w["displayName"]
                        for w in self._get("weapons", fetch)}
        self.maps = {m["mapUrl"]: m for m in self._get("maps", fetch)}

    def _get(self, what: str, fetch: bool) -> list[dict]:
        p = self.dir / f"{what}.json"
        if not p.is_file():
            if not fetch:
                raise SystemExit(f"no cached {p}; rerun without --offline")
            self.dir.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(API_BASE + what, p)
        return json.loads(p.read_text(encoding="utf-8"))["data"]

    def agent(self, uuid: str | None) -> str | None:
        return None if not uuid else self.agents.get(uuid.lower())

    def map_of(self, map_id: str) -> dict:
        return self.maps[map_id]


def weapon_name(fd: dict, killer_agent: str | None, ref: Reference) -> tuple[str | None, str]:
    """Riot's finishing damage as the name our gallery uses, and its kind.

    Kinds: `weapon`, `ability`, `melee`, `bomb`, `fall`, or `unmapped` for a
    weapon item valorant-api does not list (agent weapons such as Chamber's),
    which is cross-tabulated but not scored.
    """
    from reticle.adjudication.weapon import ABILITY_CANONICAL_NAMES

    dt = (fd or {}).get("damageType") or ""
    item = (fd or {}).get("damageItem") or ""
    if dt == "Weapon":
        name = ref.weapons.get(item.lower())
        if name:
            return name, "weapon"
        return f"unmapped:{killer_agent}:{item[:8] or 'empty'}", "unmapped"
    if dt == "Ability":
        slot = ABILITY_SLOT.get(item)
        stem = (killer_agent or "").replace("/", "_")
        name = ABILITY_CANONICAL_NAMES.get(f"{stem}_{slot}") if slot else None
        return (name or f"unmapped:{killer_agent}:{item}"), ("ability" if name else "unmapped")
    if dt == "Melee":
        return "Melee", "melee"
    if dt == "Bomb":
        return "Spike", "bomb"
    if dt == "Fall":
        return "Fall", "fall"
    return f"unmapped:{dt}:{item[:8]}", "unmapped"


# ----------------------------------------------------------------- riot data

def riot_records(store_root: Path) -> dict[str, dict]:
    """Session id -> Riot record, from each record's probe."""
    out = {}
    for p in sorted((Path(store_root) / "external" / "riot").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out[d["probe"]["session_id"]] = d
    return out


def identify_player(records: dict[str, dict], store_root: Path) -> dict[str, dict]:
    """Which Riot subject is the capturing player, per session, and why.

    An account in at least three records is the player's own (two accounts
    recur: 18 and 3 records). A record holding none falls back to the agent the
    lineup names as the player, which `rests_on` the lineup.
    """
    seen = Counter(p["subject"] for d in records.values() for p in d["match"]["players"])
    own = {s for s, n in seen.items() if n >= 3}
    out = {}
    for sid, d in records.items():
        mine = [p for p in d["match"]["players"] if p["subject"] in own]
        if len(mine) == 1:
            out[sid] = {"subject": mine[0]["subject"], "basis": "recurring_account"}
            continue
        lp = Path(store_root) / "lineups" / f"{sid}.json"
        agent = None
        if lp.is_file():
            agent = (json.loads(lp.read_text(encoding="utf-8")).get("player") or {}).get("agent")
        out[sid] = {"subject": None, "basis": "unidentified", "lineup_agent": agent,
                    "rests_on": "lineup.player"}
    return out


def resolve_lineup_player(d: dict, ident: dict, ref: Reference) -> dict:
    if ident.get("subject") or not ident.get("lineup_agent"):
        return ident
    hits = [p for p in d["match"]["players"]
            if canon(ref.agent(p["characterId"])) == canon(ident["lineup_agent"])]
    if len(hits) == 1:
        ident = dict(ident, subject=hits[0]["subject"], basis="lineup_agent")
    else:
        ident = dict(ident, basis=f"lineup_agent_ambiguous:{len(hits)}")
    return ident


# ----------------------------------------------------------------- alignment

def match_times(riot_ms, store_ms, offset_ms, slope=1.0, tol_ms=MATCH_TOL_MS):
    """One-to-one pairs (i, j, dt) of Riot and stored times, nearest first.

    `dt` is stored time minus the aligned Riot time.
    """
    s = sorted((t, j) for j, t in enumerate(store_ms))
    st = [t for t, _ in s]
    cands = []
    for i, g in enumerate(riot_ms):
        x = offset_ms + slope * g
        lo = bisect.bisect_left(st, x - tol_ms)
        hi = bisect.bisect_right(st, x + tol_ms)
        for k in range(lo, hi):
            cands.append((abs(st[k] - x), i, s[k][1], st[k] - x))
    cands.sort()
    used_i, used_j, pairs = set(), set(), []
    for _ad, i, j, dt in cands:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        pairs.append((i, j, dt))
    return pairs


def fit_alignment(riot_ms, store_ms, tol_ms=ALIGN_TOL_MS, step_ms=ALIGN_STEP_MS):
    """Fit `store = a + b * riot` and return the fit with its residuals.

    A coarse search counts riot times with a stored time within `tol_ms`; the
    best offset seeds a least-squares refit on the one-to-one pairs, twice.
    """
    riot = [float(x) for x in riot_ms]
    store = sorted(float(x) for x in store_ms)
    if not riot or not store:
        return None
    lo = store[0] - max(riot) - tol_ms
    hi = store[-1] - min(riot) + tol_ms
    best = (-1, 0.0)
    a = lo
    while a <= hi:
        n = 0
        for g in riot:
            x = a + g
            k = bisect.bisect_left(store, x - tol_ms)
            if k < len(store) and store[k] <= x + tol_ms:
                n += 1
        if n > best[0]:
            best = (n, a)
        a += step_ms
    a, b = best[1], 1.0
    pairs = []
    for _ in range(3):
        pairs = match_times(riot, store_ms, a, b, tol_ms)
        if len(pairs) < 3:
            break
        xs = [riot[i] for i, _j, _d in pairs]
        ys = [float(store_ms[j]) for _i, j, _d in pairs]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 1.0
        a = my - b * mx
    # The reported offset is the slope-1 fit, the model the brief asks for;
    # the slope is the drift check.
    pairs1 = match_times(riot, store_ms, a + (b - 1.0) * statistics.fmean(riot), 1.0, tol_ms)
    d1 = [float(store_ms[j]) - riot[i] for i, j, _ in pairs1]
    a1 = statistics.median(d1) if d1 else a
    pairs1 = match_times(riot, store_ms, a1, 1.0, tol_ms)
    res = [dt for _i, _j, dt in pairs1]
    med = statistics.median(res) if res else 0.0
    mad = statistics.median([abs(r - med) for r in res]) if res else 0.0
    return {"a_ms": a1, "slope": b, "a_ls_ms": a, "pairs": pairs1, "n_riot": len(riot),
            "n_store": len(store), "matched": len(pairs1), "coarse_hits": best[0],
            "residual_median_ms": med, "residual_mad_ms": mad,
            "drift_ms_over_match": (b - 1.0) * (max(riot) - min(riot))}


# ----------------------------------------------------------------- coordinates

def game_to_uv(x: float, y: float, m: dict, swap: bool = True) -> tuple[float, float]:
    """Riot game units to the map art's normalised (u, v)."""
    if swap:
        return (y * m["xMultiplier"] + m["xScalarToAdd"],
                x * m["yMultiplier"] + m["yScalarToAdd"])
    return (x * m["xMultiplier"] + m["xScalarToAdd"],
            y * m["yMultiplier"] + m["yScalarToAdd"])


def art_affine(art_hw: tuple[int, int], fit) -> list[list[float]]:
    """The 2x3 map from art pixel to baked widget pixel for a `shade_fit`.

    `map_shade._warp`'s rotation about the art centre with its scale, shifted
    into a square canvas of side `int(max(h, w) * scale * 1.6)`, then placed at
    `(dx, dy)` as `wiki_map._place` does.
    """
    h0, w0 = art_hw
    rot, scale, dx, dy = float(fit[0]), float(fit[1]), int(fit[2]), int(fit[3])
    t = math.radians(rot)
    al, be = scale * math.cos(t), scale * math.sin(t)
    cx, cy = w0 / 2.0, h0 / 2.0
    # cv2.getRotationMatrix2D(center, angle, scale)
    m = [[al, be, (1 - al) * cx - be * cy], [-be, al, be * cx + (1 - al) * cy]]
    side = int(max(h0, w0) * scale * 1.6)
    m[0][2] += side / 2 - w0 / 2 + dx
    m[1][2] += side / 2 - h0 / 2 + dy
    return m


def apply(m, x: float, y: float) -> tuple[float, float]:
    return (m[0][0] * x + m[0][1] * y + m[0][2], m[1][0] * x + m[1][1] * y + m[1][2])


class MapFrame:
    """Riot game units -> baked widget px for one (map, profile) geometry.

    `art_hw` is the full art's size, which `(u, v)` spans; `crop` is the
    footprint box `wiki_map.art_alpha` cuts before the fit warps it, as
    (x0, y0, h, w). The fit's rotation centre is the CROPPED art's centre.
    """

    def __init__(self, mapinfo: dict, art_hw, fit, swap: bool = True, crop=None):
        self.m = mapinfo
        self.art_hw = art_hw
        self.crop = crop or (0, 0, art_hw[0], art_hw[1])
        self.aff = art_affine((self.crop[2], self.crop[3]), fit)
        self.swap = swap
        # px per game unit, from a 1000-unit step at the map centre
        x0, y0 = self.to_px(0.0, 0.0)
        x1, y1 = self.to_px(1000.0, 0.0)
        self.px_per_unit = math.hypot(x1 - x0, y1 - y0) / 1000.0

    def to_px(self, x: float, y: float) -> tuple[float, float]:
        u, v = game_to_uv(x, y, self.m, self.swap)
        h0, w0 = self.art_hw
        # (u, v) spans the art's edges; pixel centres sit half a pixel in
        return apply(self.aff, u * w0 - 0.5 - self.crop[0], v * h0 - 0.5 - self.crop[1])

    def facing_deg(self, x: float, y: float, theta: float) -> float:
        """A game-plane direction `theta` (radians from +x toward +y) as image
        degrees, y down, the teardrop convention."""
        p0 = self.to_px(x, y)
        p1 = self.to_px(x + 100.0 * math.cos(theta), y + 100.0 * math.sin(theta))
        return math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0])) % 360.0


#: Candidate readings of Riot's viewRadians as a game-plane angle. The data
#: chooses; every candidate's error is printed.
FACING_CONVENTIONS = {
    "theta": lambda r: r,
    "-theta": lambda r: -r,
    "pi/2-theta": lambda r: math.pi / 2 - r,
    "theta+pi/2": lambda r: r + math.pi / 2,
    "theta-pi/2": lambda r: r - math.pi / 2,
    "theta+pi": lambda r: r + math.pi,
    "-theta+pi": lambda r: math.pi - r,
    "-theta-pi/2": lambda r: -r - math.pi / 2,
}


def angle_err(a: float, b: float) -> float:
    d = (a - b) % 360.0
    return min(d, 360.0 - d)


def map_frame_for(sid: str, man: dict, ref: Reference, d: dict, store_root: Path,
                  swap: bool = True) -> tuple[MapFrame | None, str | None]:
    import numpy as np
    import cv2
    from reticle import geometry

    gp = geometry.path_of(sid, store_root)
    if gp is None or not gp.is_file():
        return None, "no_geometry"
    with np.load(gp) as z:
        if "shade_fit" not in z.files:
            return None, "no_shade_fit"
        fit = [float(v) for v in z["shade_fit"]]
        shape = z["labels"].shape
    mname = geometry.map_of(sid, store_root)
    art = cv2.imread(str(Path(store_root) / "reference" / "maps" / f"{mname}.png"),
                     cv2.IMREAD_UNCHANGED)
    if art is None:
        return None, "no_art"
    mi = ref.map_of(d["match"]["matchInfo"]["mapId"])
    if canon(mi["displayName"]) != canon(mname):
        return None, f"map_mismatch:{mi['displayName']}!={mname}"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from wiki_map import ALPHA_MIN
    ys, xs = np.where(art[:, :, 3] > ALPHA_MIN)
    crop = (int(xs.min()), int(ys.min()), int(ys.max() - ys.min() + 1), int(xs.max() - xs.min() + 1))
    mf = MapFrame(mi, art.shape[:2], fit, swap, crop)
    mf.widget_shape = shape
    # an icon's radius in px: 6 px on the 331 px widget, scaled with it
    mf.icon_px = 6.0 * shape[1] / 331.0
    return mf, None


# ----------------------------------------------------------------- stored data

def _stream_rows(path: Path):
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def stored_deaths(store_root: Path, sid: str, deaths_from: Path | None = None) -> list[dict]:
    """The `death_verdict` rows; `deaths_from` reads `<dir>/events/death/<sid>.jsonl`
    instead, such as a trial's in-memory adjudication
    (`prototypes/killfeed_trial_deaths.py`)."""
    root = Path(deaths_from) if deaths_from else Path(store_root)
    return [r for r in _stream_rows(root / "events" / "death" / f"{sid}.jsonl")
            if r.get("kind") == "death_verdict"]


def near_any(sorted_ts, t, tol) -> bool:
    k = bisect.bisect_left(sorted_ts, t - tol)
    return k < len(sorted_ts) and sorted_ts[k] <= t + tol


def minimap_rows(store_root: Path, sid: str, want_ms: list[float], tol_ms: float):
    """Frames, pieces and facings near the asked instants, streamed."""
    ts = sorted(want_ms)
    frames, self_by_frame, facing = {}, {}, {}
    icons = defaultdict(list)
    for r in _stream_rows(Path(store_root) / "events" / "ally_icon" / f"{sid}.jsonl"):
        k = r.get("kind")
        if k not in ("frame", "icon") or not near_any(ts, r["t_ms"], tol_ms):
            continue
        if k == "frame":
            frames[r["frame_idx"]] = (r["t_ms"], bool(r.get("widget_drawn")))
            if r.get("self"):
                self_by_frame[r["frame_idx"]] = r["self"]
        else:
            facing[r["observation_key"]] = r.get("facing")
            icons[r["frame_idx"]].append((r["cx"], r["cy"], r.get("reason"), r.get("facing")))
    obs = defaultdict(list)
    ents = {}
    for r in _stream_rows(Path(store_root) / "events" / "round_entity" / f"{sid}.jsonl"):
        k = r.get("kind")
        if k == "entity":
            ents[r["id"]] = r
        elif k == "observation" and near_any(ts, r["t_ms"], tol_ms):
            obs[r["frame_idx"]].append(r)
    enemies = {}
    for r in _stream_rows(Path(store_root) / "events" / "minimap_object" / f"{sid}.jsonl"):
        if r.get("kind") == "frame" and near_any(ts, r["t_ms"], tol_ms):
            enemies[r["frame_idx"]] = (r["t_ms"], r.get("reason"), r.get("enemies") or [])
    return frames, self_by_frame, facing, obs, ents, enemies, icons


# ----------------------------------------------------------------- scoring

def greedy_pairs(a_pts, b_pts, gate):
    """One-to-one (i, j, dist) pairs within `gate`, nearest first."""
    c = []
    for i, p in enumerate(a_pts):
        for j, q in enumerate(b_pts):
            dd = math.hypot(p[0] - q[0], p[1] - q[1])
            if dd <= gate:
                c.append((dd, i, j))
    c.sort()
    ui, uj, out = set(), set(), []
    for dd, i, j in c:
        if i in ui or j in uj:
            continue
        ui.add(i)
        uj.add(j)
        out.append((i, j, dd))
    return out


def score_session(sid: str, d: dict, ident: dict, ref: Reference, store_root: Path,
                  status_rec: dict | None, opts) -> dict:
    from reticle.store import Store
    from reticle import widget_frame

    store = Store(store_root)
    man = store.read_manifest(sid)
    m = d["match"]
    who = {p["subject"]: p for p in m["players"]}
    agent_of = {s: ref.agent(p["characterId"]) for s, p in who.items()}
    me = ident.get("subject")
    my_team = who[me]["teamId"] if me in who else None
    out = {"session": sid, "capture": man["source"]["path"], "profile": man["source_profile"],
           "widget": None, "cohort": widget_frame.cohort(man), "player_basis": ident.get("basis"),
           "map": m["matchInfo"]["mapId"].rsplit("/", 1)[-1]}

    deaths = stored_deaths(store_root, sid, getattr(opts, "deaths_from", None))
    kills = sorted(m["kills"], key=lambda k: k["gameTime"])
    if not deaths:
        out["refused"] = "no_stored_deaths"
        # K/D against the scoreboard's known values needs no stored death
        out["kd"] = score_kd(sid, m, me, kills, [], [], who, agent_of, None, status_rec)
        return out
    # Revive entries are not kills; Riot lists kills only.
    kill_like = [r for r in deaths if not r.get("is_revive")]
    st = [float(r["t_ms"]) for r in kill_like]
    al = fit_alignment([k["gameTime"] for k in kills], st)
    out["align"] = {k: v for k, v in al.items() if k != "pairs"}
    a = al["a_ms"]

    # -- residual histogram on the match tolerance
    pairs = match_times([k["gameTime"] for k in kills], st, a, 1.0, opts.match_tol)
    res = sorted(dt for _i, _j, dt in pairs)
    out["align"]["residual_p05_p95_ms"] = (res[int(0.05 * (len(res) - 1))],
                                           res[int(0.95 * (len(res) - 1))]) if res else None
    wide = match_times([k["gameTime"] for k in kills], st, a, 1.0, 5000.0)
    hist = Counter(int(math.floor(dt / 250.0)) for _i, _j, dt in wide)
    out["align"]["residual_hist_250ms"] = {f"{b * 250}": n for b, n in sorted(hist.items())}

    # -- round starts (HUD, independent of the killfeed) and roundTime zero
    rstart = {}
    for k in kills:
        rstart.setdefault(k["round"], k["gameTime"] - k["roundTime"])
    rounds = store.read_rounds(sid, man["ingested_at"][:10]).to_pylist() \
        if store.rounds_path(sid, man["ingested_at"][:10]).exists() else []
    out["rounds"] = score_rounds(rounds, m, rstart, a, my_team, opts)

    # -- deaths
    out["deaths"], out["death_rows"] = score_deaths(kills, kill_like, pairs, who, agent_of,
                                                     my_team, ref, a)
    out["deaths"]["revive_entries"] = len(deaths) - len(kill_like)

    # -- K/D for the player and per player
    out["kd"] = score_kd(sid, m, me, kills, kill_like, pairs, who, agent_of, my_team, status_rec)
    out["assists"] = score_assists(store_root, sid, m, me, rounds, rstart, a)

    # -- minimap at kill instants
    if not opts.no_minimap:
        mf, why = map_frame_for(sid, man, ref, d, store_root, swap=not opts.unswapped)
        if mf is None:
            out["minimap"] = {"refused": why}
        else:
            out["widget"] = mf.widget_shape[1]
            out["minimap"] = score_minimap(sid, store_root, kills, a, mf, who, agent_of,
                                           me, my_team, opts)
    return out


def _round_pair(rounds, t):
    for r in rounds:
        if r["t_start_ms"] <= t <= (r["t_close_ms"] or r["t_end_ms"]):
            return r
    return None


def score_rounds(rounds, m, rstart, a, my_team, opts) -> dict:
    allr = sorted(m["roundResults"], key=lambda r: r["roundNum"])
    # A surrender awards the remaining rounds with nothing played.
    rr = [r for r in allr if r.get("roundResultCode") != "Surrendered"]
    out = {"riot_rounds": len(rr), "riot_surrendered": len(allr) - len(rr),
           "stored_rounds": len(rounds), "paired": 0,
           "winner_right": 0, "winner_wrong": 0, "winner_unread": 0,
           "plant_both": 0, "plant_riot_only": 0, "plant_store_only": 0,
           "plant_dt_ms": [], "start_dt_ms": [], "start_dt_by_source": defaultdict(list),
           "site": "no stored owner names a plant site",
           "defuse": "no stored owner times a defuse", "unpaired_riot": [], "rows": []}
    for r in rr:
        n = r["roundNum"]
        if n not in rstart:
            out["unpaired_riot"].append({"round": n + 1, "reason": "no_riot_kill_to_time_it"})
            continue
        t0 = a + rstart[n]
        s = _round_pair(rounds, t0)
        if s is None:
            out["unpaired_riot"].append({"round": n + 1, "t_ms": round(t0)})
            continue
        out["paired"] += 1
        won = None if my_team is None else (r["winningTeam"] == my_team)
        if s["won"] is None or won is None:
            out["winner_unread"] += 1
        elif s["won"] == won:
            out["winner_right"] += 1
        else:
            out["winner_wrong"] += 1
        dstart = t0 - s["t_start_ms"]
        out["start_dt_by_source"][s["start_source"]].append(dstart)
        if s["start_source"] == "clock_reset":
            out["start_dt_ms"].append(dstart)
        rp = (r.get("plantRoundTime") or 0) > 0
        row = {"riot_round": n + 1, "stored_round": s["round_no"], "won_riot": won,
               "won_store": s["won"], "start_source": s["start_source"],
               "barrier_minus_start_ms": round(dstart), "riot_result": r.get("roundResultCode")}
        if rp and s["spike_planted"]:
            out["plant_both"] += 1
            tp = t0 + r["plantRoundTime"]
            if s["plant_t_ms"] is not None:
                out["plant_dt_ms"].append(s["plant_t_ms"] - tp)
                row["plant_dt_ms"] = round(s["plant_t_ms"] - tp)
        elif rp:
            out["plant_riot_only"] += 1
            row["plant"] = "riot_only"
        elif s["spike_planted"]:
            out["plant_store_only"] += 1
            row["plant"] = "store_only"
        out["rows"].append(row)
    out["start_dt_by_source"] = dict(out["start_dt_by_source"])
    return out


def _refusal_of_identity(meta: dict | None) -> str | None:
    if not meta:
        return "no_identity_row"
    if meta.get("agent"):
        return None
    return meta.get("reason") or meta.get("status") or "unnamed"


def reorder_clusters(pairs, kills, deaths, agent_of, a, tol_ms=MATCH_TOL_MS):
    """Re-pair kills that fall within `AMBIGUOUS_MS` of each other by names.

    Time alone cannot order kills a killfeed sample apart: two trades 200 ms
    apart land in one 2 Hz sample, and nearest-first pairs them arbitrarily,
    which scores a swapped pair as two wrong names. Inside such a cluster this
    keeps the permutation whose stored names agree most with Riot's (ties keep
    the time order). The re-pairing RESTS ON the stored names, so name scores
    on clustered pairs are an upper bound; the unambiguous pairs carry the
    headline. Recall and precision do not change.
    """
    from itertools import permutations

    by_i = {i: (j, dt) for i, j, dt in pairs}
    order = sorted(by_i, key=lambda i: kills[i]["gameTime"])
    clusters, cur = [], []
    for i in order:
        if cur and kills[i]["gameTime"] - kills[cur[-1]]["gameTime"] >= AMBIGUOUS_MS:
            clusters.append(cur)
            cur = []
        cur.append(i)
    if cur:
        clusters.append(cur)

    def agree(i, j):
        k, s = kills[i], deaths[j]
        return (int(canon(s.get("victim")) == canon(agent_of.get(k["victim"])))
                + int(canon(s.get("killer")) == canon(agent_of.get(k.get("killer")))))

    out, clustered = [], set()
    for cl in clusters:
        if len(cl) == 1 or len(cl) > 6:
            out += [(i, by_i[i][0], by_i[i][1]) for i in cl]
            continue
        clustered |= set(cl)
        js = [by_i[i][0] for i in cl]
        best, best_score = js, sum(agree(i, j) for i, j in zip(cl, js))
        for perm in permutations(js):
            if any(abs(float(deaths[j]["t_ms"]) - (a + kills[i]["gameTime"])) > tol_ms
                   for i, j in zip(cl, perm)):
                continue
            sc = sum(agree(i, j) for i, j in zip(cl, perm))
            if sc > best_score:
                best, best_score = list(perm), sc
        out += [(i, j, float(deaths[j]["t_ms"]) - (a + kills[i]["gameTime"]))
                for i, j in zip(cl, best)]
    return out, clustered


def score_deaths(kills, deaths, pairs, who, agent_of, my_team, ref, a) -> tuple[dict, list]:
    pairs, clustered = reorder_clusters(pairs, kills, deaths, agent_of, a)
    out = {"riot_kills": len(kills), "stored_deaths": len(deaths), "matched": len(pairs)}
    out["recall"] = len(pairs) / len(kills) if kills else None
    out["precision"] = len(pairs) / len(deaths) if deaths else None
    c = Counter()
    reasons = defaultdict(Counter)
    wcross = Counter()
    jitter = []
    rows = []
    # recall by Riot's damage kind: a reader can miss one kind of entry whole
    got_i = {i for i, _j, _dt in pairs}
    for i, k in enumerate(kills):
        kl = agent_of.get(k["killer"]) if k.get("killer") else None
        kind = weapon_name(k.get("finishingDamage"), kl, ref)[1]
        c[f"riot_kind_{kind}"] += 1
        c[f"matched_kind_{kind}"] += int(i in got_i)
    for i, j, dt in pairs:
        k, s = kills[i], deaths[j]
        jitter.append(dt)
        amb = i in clustered
        v_true = agent_of.get(k["victim"])
        kl_true = agent_of.get(k["killer"]) if k.get("killer") else None
        v_side = None if my_team is None else ("ally" if who[k["victim"]]["teamId"] == my_team else "enemy")
        meta = s.get("metadata") or {}
        for role, truth, got, idm in (("victim", v_true, s.get("victim"), meta.get("identity")),
                                      ("killer", kl_true, s.get("killer"), meta.get("killer_identity"))):
            if got is None:
                c[f"{role}_refused"] += 1
                if not amb:
                    c[f"{role}_refused_unamb"] += 1
                reasons[role][_refusal_of_identity(idm) or s.get("reason") or "none"] += 1
            elif canon(got) == canon(truth):
                c[f"{role}_right"] += 1
                if not amb:
                    c[f"{role}_right_unamb"] += 1
            else:
                c[f"{role}_wrong"] += 1
                if not amb:
                    c[f"{role}_wrong_unamb"] += 1
        if v_side is not None and s.get("side") in ("ally", "enemy"):
            c["side_right" if s["side"] == v_side else "side_wrong"] += 1
            if not amb:
                c["side_right_unamb" if s["side"] == v_side else "side_wrong_unamb"] += 1
        c["ambiguous_pairs"] += int(amb)
        wtrue, wkind = weapon_name(k.get("finishingDamage"), kl_true, ref)
        we = s.get("weapon_evidence") or {}
        got = s.get("weapon")
        if wkind == "unmapped":
            wcross[(wtrue, got)] += 1
            c["weapon_unmapped_riot"] += 1
        elif got is None:
            c["weapon_refused"] += 1
            reasons["weapon"][we.get("reason") or we.get("status") or "none"] += 1
        elif canon(got) == canon(wtrue):
            c["weapon_right"] += 1
        else:
            c["weapon_wrong"] += 1
            wcross[(wtrue, got)] += 1
        rows.append({"t_ms": s["t_ms"], "dt_ms": round(dt), "round": k["round"] + 1,
                     "victim": [v_true, s.get("victim")], "killer": [kl_true, s.get("killer")],
                     "weapon": [wtrue, got], "side": [v_side, s.get("side")], "ambiguous": amb,
                     "death_id": s.get("death_id")})
    matched_i = {i for i, _j, _ in pairs}
    matched_j = {j for _i, j, _ in pairs}
    misses = []
    for i, k in enumerate(kills):
        if i in matched_i:
            continue
        misses.append({"t_ms": round(a + k["gameTime"]), "round": k["round"] + 1,
                       "victim": agent_of.get(k["victim"]),
                       "killer": agent_of.get(k.get("killer")),
                       "victim_side": None if my_team is None else
                       ("ally" if who[k["victim"]]["teamId"] == my_team else "enemy"),
                       "weapon": weapon_name(k.get("finishingDamage"),
                                             agent_of.get(k.get("killer")), ref)[0]})
    false = [{"t_ms": deaths[j]["t_ms"], "death_id": deaths[j].get("death_id"),
              "victim": deaths[j].get("victim"), "killer": deaths[j].get("killer"),
              "side": deaths[j].get("side"), "second_life": deaths[j].get("is_second_life"),
              "status": deaths[j].get("status")}
             for j in range(len(deaths)) if j not in matched_j]
    out.update(c)
    out["refusal_reasons"] = {k: dict(v) for k, v in reasons.items()}
    out["weapon_cross"] = {f"{t} -> {g}": n for (t, g), n in wcross.most_common()}
    out["jitter_ms"] = _summ(jitter)
    out["misses"] = misses
    out["false"] = false
    return out, rows


def _summ(xs):
    xs = sorted(xs)
    if not xs:
        return None
    med = statistics.median(xs)
    return {"n": len(xs), "median": round(med, 1),
            "mad": round(statistics.median([abs(x - med) for x in xs]), 1),
            "p05": round(xs[int(0.05 * (len(xs) - 1))], 1),
            "p95": round(xs[int(0.95 * (len(xs) - 1))], 1),
            "max_abs": round(max(abs(x) for x in xs), 1)}


def score_kd(sid, m, me, kills, deaths, pairs, who, agent_of, my_team, status_rec) -> dict:
    from reticle.checks import KNOWN_KD, KNOWN_DIVERGENCE

    out = {}
    if me in who:
        st = who[me]["stats"]
        out["riot"] = (st["kills"], st["deaths"], st["assists"])
        out["riot_kills_array"] = (sum(1 for k in kills if k.get("killer") == me),
                                   sum(1 for k in kills if k["victim"] == me))
    out["known_kd"] = KNOWN_KD.get(sid)
    if out.get("riot") and out["known_kd"]:
        out["known_vs_riot"] = "agree" if tuple(out["known_kd"]) == out["riot"][:2] else "DIFFER"
    if status_rec:
        out["status_tracked"] = (status_rec.get("kills"), status_rec.get("deaths"))
        out["status_verdict"] = status_rec.get("verdict")
        if out.get("riot") and status_rec.get("kills") is not None:
            out["tracked_vs_riot"] = (status_rec["kills"] - out["riot"][0],
                                      status_rec["deaths"] - out["riot"][1])
    out["allowance"] = KNOWN_DIVERGENCE.get(sid)
    # Per player: stored deaths credited by (side, agent), every player.
    if my_team is not None:
        side_of = {s: ("ally" if p["teamId"] == my_team else "enemy") for s, p in who.items()}
        sk, sd = Counter(), Counter()
        for r in deaths:
            vs = r.get("side")
            if r.get("victim"):
                sd[(vs, canon(r["victim"]))] += 1
            if r.get("killer") and vs in ("ally", "enemy"):
                ks = vs if r.get("same_side") else ("enemy" if vs == "ally" else "ally")
                sk[(ks, canon(r["killer"]))] += 1
        rows = []
        exact = 0
        for s, p in who.items():
            key = (side_of[s], canon(agent_of[s]))
            dup = sum(1 for s2 in who if (side_of[s2], canon(agent_of[s2])) == key) > 1
            rk = sum(1 for k in kills if k.get("killer") == s)
            rd = sum(1 for k in kills if k["victim"] == s)
            row = {"agent": agent_of[s], "side": side_of[s], "me": s == me, "riot": (rk, rd),
                   "store": (sk[key], sd[key]), "duplicate_agent_on_side": dup}
            if (sk[key], sd[key]) == (rk, rd):
                exact += 1
            rows.append(row)
        out["players"] = rows
        out["players_exact"] = exact
    return out


def score_assists(store_root, sid, m, me, rounds, rstart, a) -> dict:
    """The player's per-round kills, deaths and assists from the combat report
    owner against Riot's kills array."""
    rows = [r for r in _stream_rows(Path(store_root) / "events" / "combat_report_round" / f"{sid}.jsonl")
            if r.get("kind") == "round"]
    if not rows or me is None:
        return {"refused": "no_combat_report_round" if not rows else "player_unidentified"}
    by_round = {}
    for n, g0 in rstart.items():
        t0 = a + g0
        s = next((r for r in rows if r["t_start_ms"] <= t0 <= r["t_end_ms"]), None)
        if s:
            by_round[n] = s
    c = Counter()
    for n, s in by_round.items():
        rk = sum(1 for k in m["kills"] if k["round"] == n and k.get("killer") == me)
        rd = sum(1 for k in m["kills"] if k["round"] == n and k["victim"] == me)
        ra = sum(1 for k in m["kills"] if k["round"] == n and me in (k.get("assistants") or []))
        for name, got, truth in (("kills", s.get("kills_verdict"), rk),
                                 ("deaths", s.get("deaths_verdict"), rd),
                                 ("assists", s.get("assists"), ra)):
            if got is None:
                c[f"{name}_unread"] += 1
            elif got == truth:
                c[f"{name}_right"] += 1
            else:
                c[f"{name}_wrong"] += 1
        c["riot_assists"] += ra
        c["store_assists"] += s.get("assists") or 0
    c["rounds_paired"] = len(by_round)
    return dict(c)


def score_minimap(sid, store_root, kills, a, mf: MapFrame, who, agent_of, me, my_team, opts) -> dict:
    lag = opts.minimap_lag
    lags = [lag] if not opts.scan_lag else [x * 66.67 for x in range(-12, 13)]
    want = [a + k["gameTime"] + L for k in kills for L in lags]
    frames, self_by_frame, facing, obs, ents, enemies, icons = minimap_rows(
        store_root, sid, want, FRAME_TOL_MS)
    fts = sorted((t, f) for f, (t, _d) in frames.items())
    ft = [t for t, _ in fts]
    gate = GATE_M * 100.0 * mf.px_per_unit
    out = {"px_per_m": round(mf.px_per_unit * 100.0, 3), "gate_px": round(gate, 2),
           "lag_ms": lag}

    def frame_at(t):
        k = bisect.bisect_left(ft, t)
        best = None
        for kk in (k - 1, k):
            if 0 <= kk < len(ft) and abs(ft[kk] - t) <= FRAME_TOL_MS:
                if best is None or abs(ft[kk] - t) < abs(ft[best] - t):
                    best = kk
        return None if best is None else fts[best][1]

    if opts.scan_lag:
        scan = {}
        for L in lags:
            errs = []
            for k in kills:
                f = frame_at(a + k["gameTime"] + L)
                if f is None or f not in self_by_frame:
                    continue
                loc = next((p for p in k["playerLocations"] if p["subject"] == me), None)
                if loc is None:
                    continue
                px = mf.to_px(loc["location"]["x"], loc["location"]["y"])
                sx, sy = self_by_frame[f][0], self_by_frame[f][1]
                errs.append(math.hypot(px[0] - sx, px[1] - sy))
            scan[round(L)] = (len(errs), round(statistics.median(errs), 2) if errs else None)
        out["lag_scan_self_median_px"] = scan

    c = Counter()
    miss_rows = []
    reader_err, reader_fac = [], defaultdict(list)
    has_tracker = (Path(store_root) / "events" / "round_entity" / f"{sid}.jsonl").is_file()
    out["tracker"] = "round_entity" if has_tracker else "no_round_entity_stream"
    pos_err, self_err, fac_err = [], [], defaultdict(list)
    enemy_err = []
    id_reasons = Counter()
    rows = []
    for k in kills:
        t = a + k["gameTime"] + lag
        f = frame_at(t)
        if f is None:
            c["kill_no_frame"] += 1
            continue
        if not frames[f][1]:
            c["kill_widget_not_drawn"] += 1
            continue
        c["kill_frames"] += 1
        locs = {p["subject"]: p for p in k["playerLocations"]}
        allies = [s for s, p in locs.items() if who[s]["teamId"] == my_team and s != k["victim"]]
        foes = [s for s, p in locs.items() if who[s]["teamId"] != my_team and s != k["victim"]]
        # self, from the ally reader's self fit
        if me in locs and f in self_by_frame:
            px = mf.to_px(locs[me]["location"]["x"], locs[me]["location"]["y"])
            self_err.append(math.hypot(px[0] - self_by_frame[f][0], px[1] - self_by_frame[f][1]))
        pieces = [o for o in obs.get(f, []) if o.get("family") in ("ally", "self")]
        truth_px = [mf.to_px(locs[s]["location"]["x"], locs[s]["location"]["y"]) for s in allies]
        got_px = [(o["x"], o["y"]) for o in pieces]
        pr = greedy_pairs(truth_px, got_px, gate)
        c["riot_allies"] += len(allies)
        if has_tracker:
            c["tracker_riot_allies"] += len(allies)
            c["store_pieces"] += len(pieces)
            c["matched"] += len(pr)
            c["missed"] += len(allies) - len(pr)
            c["phantom"] += len(pieces) - len(pr)
        hit = {i for i, _j, _d in pr}
        H, W = mf.widget_shape
        for i, (x, y) in enumerate(truth_px):
            if has_tracker and i not in hit:
                if not (0 <= x < W and 0 <= y < H):
                    c["missed_outside_widget"] += 1
                elif any(math.hypot(x - q[0], y - q[1]) < 2 * mf.icon_px
                         for ii, q in enumerate(truth_px) if ii != i):
                    c["missed_stacked"] += 1
                if opts.list_misses and len(miss_rows) < 400:
                    miss_rows.append({"t_ms": round(t), "agent": agent_of.get(allies[i]),
                                      "px": (round(x, 1), round(y, 1))})
        # the same teammates against the ally reader's own fits (with its self
        # fit), accepted and refused: is a miss the reader's or the tracker's?
        own = [(x, y, fa) for x, y, why, fa in icons.get(f, []) if why is None]
        anyi = [(x, y) for x, y, _why, _fa in icons.get(f, [])]
        sf = [tuple(self_by_frame[f][:2])] if f in self_by_frame else []
        rpr = greedy_pairs(truth_px, [(x, y) for x, y, _ in own] + sf, gate)
        c["reader_matched"] += len(rpr)
        c["reader_matched_any"] += len(greedy_pairs(truth_px, anyi + sf, gate))
        c["reader_icons"] += len(own) + len(sf)
        for i, j, dd in rpr:
            reader_err.append(dd)
            if j < len(own) and own[j][2] is not None:
                loc = locs[allies[i]]
                for name, fn in FACING_CONVENTIONS.items():
                    tdeg = mf.facing_deg(loc["location"]["x"], loc["location"]["y"],
                                         fn(loc["viewRadians"]))
                    reader_fac[name].append(angle_err(tdeg, own[j][2]))
        if not has_tracker:
            continue
        for i, j, dd in pr:
            s, o = allies[i], pieces[j]
            pos_err.append(dd)
            ent = ents.get(o.get("entity_id")) or {}
            got = ent.get("agent")
            truth = agent_of.get(s)
            if got is None:
                c["id_refused"] += 1
                id_reasons[ent.get("identity_status") or "no_entity_row"] += 1
            elif canon(got) == canon(truth):
                c["id_right"] += 1
            else:
                c["id_wrong"] += 1
            fdeg = facing.get(o.get("observation_key"))
            if fdeg is not None:
                loc = locs[s]
                for name, fn in FACING_CONVENTIONS.items():
                    tdeg = mf.facing_deg(loc["location"]["x"], loc["location"]["y"],
                                         fn(loc["viewRadians"]))
                    fac_err[name].append(angle_err(tdeg, fdeg))
            else:
                c["facing_unread"] += 1
        # enemies where the store read them
        # minimap_object frames share frame_idx with the ally reader
        ef = enemies.get(f)
        if ef is not None and ef[1] is None:
            e_px = [(e["x"], e["y"]) for e in ef[2]]
            t_px = [mf.to_px(locs[s]["location"]["x"], locs[s]["location"]["y"]) for s in foes]
            epr = greedy_pairs(t_px, e_px, gate)
            c["enemy_frames"] += 1
            c["enemy_store"] += len(e_px)
            c["enemy_matched"] += len(epr)
            c["enemy_unmatched_store"] += len(e_px) - len(epr)
            enemy_err.extend(dd for _i, _j, dd in epr)
        rows.append({"t_ms": round(t), "frame": f, "allies": len(allies), "pieces": len(pieces),
                     "matched": len(pr)})
    out.update(c)
    out["miss_rows"] = miss_rows
    m2m = 1.0 / (mf.px_per_unit * 100.0)
    out["pos_err_px"] = _summ(pos_err)
    out["pos_err_m"] = None if not pos_err else round(statistics.median(pos_err) * m2m, 2)
    out["self_err_px"] = _summ(self_err)
    out["self_err_m"] = None if not self_err else round(statistics.median(self_err) * m2m, 2)
    out["enemy_err_px"] = _summ(enemy_err)
    out["id_refusal_reasons"] = dict(id_reasons)
    out["facing_by_convention"] = {n: _summ(v) for n, v in fac_err.items()}
    out["facing_err_samples"] = {n: v for n, v in fac_err.items()}
    out["pos_err_samples"] = pos_err
    out["reader_err_samples"] = reader_err
    out["reader_facing_samples"] = dict(reader_fac)
    out["reader_pos_err_px"] = _summ(reader_err)
    out["self_err_samples"] = self_err
    out["enemy_err_samples"] = enemy_err
    return out


# ----------------------------------------------------------------- pooling

POOL_KEYS_DEATH = ("riot_kills", "stored_deaths", "matched", "victim_right", "victim_wrong",
                   "victim_refused", "killer_right", "killer_wrong", "killer_refused",
                   "victim_right_unamb", "victim_wrong_unamb", "killer_right_unamb",
                   "killer_wrong_unamb", "weapon_right", "weapon_wrong", "weapon_refused",
                   "weapon_unmapped_riot", "side_right", "side_wrong", "revive_entries",
                   "side_right_unamb", "side_wrong_unamb", "ambiguous_pairs",
                   "victim_refused_unamb", "killer_refused_unamb")
POOL_KEYS_DEATH += tuple(f"{p}_kind_{k}" for p in ("riot", "matched")
                         for k in ("weapon", "ability", "unmapped", "bomb", "melee", "fall"))


def pool(results: list[dict], conv: str | None) -> dict:
    ok = [r for r in results if "deaths" in r]
    P = {"sessions": len(ok)}
    D = Counter()
    for r in ok:
        for k in POOL_KEYS_DEATH:
            D[k] += r["deaths"].get(k, 0) or 0
    P["deaths"] = dict(D)
    P["deaths"]["recall"] = D["matched"] / D["riot_kills"] if D["riot_kills"] else None
    P["deaths"]["precision"] = D["matched"] / D["stored_deaths"] if D["stored_deaths"] else None
    for role in ("victim", "killer", "weapon"):
        n = D[f"{role}_right"] + D[f"{role}_wrong"]
        P["deaths"][f"{role}_right_of_named"] = D[f"{role}_right"] / n if n else None
    rr = defaultdict(Counter)
    for r in ok:
        for role, cnt in r["deaths"].get("refusal_reasons", {}).items():
            rr[role].update(cnt)
    P["deaths"]["refusal_reasons"] = {k: dict(v.most_common()) for k, v in rr.items()}
    wc = Counter()
    for r in ok:
        wc.update(r["deaths"].get("weapon_cross", {}))
    P["deaths"]["weapon_cross_top"] = dict(wc.most_common(25))
    jit = []
    for r in ok:
        a = r["align"]
        jit.append(a["residual_mad_ms"])
    R = Counter()
    sdt, pdt = [], []
    for r in ok:
        x = r["rounds"]
        for k in ("riot_rounds", "stored_rounds", "paired", "winner_right", "winner_wrong",
                  "winner_unread", "plant_both", "plant_riot_only", "plant_store_only"):
            R[k] += x[k]
        R["count_equal_sessions"] += int(x["riot_rounds"] == x["stored_rounds"])
        sdt += x["start_dt_ms"]
        pdt += x["plant_dt_ms"]
    P["rounds"] = dict(R)
    P["rounds"]["barrier_minus_clock_reset_ms"] = _summ(sdt)
    P["rounds"]["plant_dt_ms"] = _summ(pdt)
    P["rounds"]["plant_within_1500"] = sum(1 for x in pdt if abs(x) <= 1500)
    K = Counter()
    for r in results:
        kd = r.get("kd") or {}
        if kd.get("known_vs_riot"):
            K["known_scored"] += 1
            K["known_agree"] += kd["known_vs_riot"] == "agree"
        if kd.get("tracked_vs_riot") is not None:
            K["tracked_scored"] += 1
            K["tracked_exact"] += kd["tracked_vs_riot"] == (0, 0)
        if kd.get("players"):
            K["players"] += len(kd["players"])
            K["players_exact"] += kd["players_exact"]
    P["kd"] = dict(K)
    A = Counter()
    for r in ok:
        if "refused" not in r.get("assists", {}):
            A.update(r["assists"])
    P["assists"] = dict(A)
    # minimap by widget and cohort
    MM = {}
    for grp in ("331", "465", "variant", "all"):
        sel = [r for r in ok if isinstance(r.get("minimap"), dict) and "refused" not in r["minimap"]
               and (grp == "all" or (grp == "variant" and r["cohort"] != "standard")
                    or (grp != "variant" and r["cohort"] == "standard" and str(r.get("widget")) == grp))]
        if not sel:
            continue
        C = Counter()
        pe, se, ee, re_ = [], [], [], []
        fe, rfe = defaultdict(list), defaultdict(list)
        idr = Counter()
        for r in sel:
            mm = r["minimap"]
            for k in ("kill_frames", "kill_no_frame", "kill_widget_not_drawn", "riot_allies",
                      "tracker_riot_allies",
                      "reader_matched", "reader_matched_any", "reader_icons",
                      "missed_outside_widget", "missed_stacked",
                      "store_pieces", "matched", "missed", "phantom", "id_right", "id_wrong",
                      "id_refused", "facing_unread", "enemy_frames", "enemy_store",
                      "enemy_matched", "enemy_unmatched_store"):
                C[k] += mm.get(k, 0)
            pe += mm["pos_err_samples"]
            se += mm["self_err_samples"]
            ee += mm["enemy_err_samples"]
            re_ += mm.get("reader_err_samples", [])
            for n, v in mm.get("reader_facing_samples", {}).items():
                rfe[n] += v
            idr.update(mm["id_refusal_reasons"])
            for n, v in mm["facing_err_samples"].items():
                fe[n] += v
        G = dict(C)
        G["sessions"] = len(sel)
        G["pos_err_px"] = _summ(pe)
        G["self_err_px"] = _summ(se)
        G["enemy_err_px"] = _summ(ee)
        G["reader_pos_err_px"] = _summ(re_)
        G["reader_facing_by_convention"] = {n: _summ(v) for n, v in rfe.items()}
        G["id_refusal_reasons"] = dict(idr)
        G["facing_by_convention"] = {n: _summ(v) for n, v in fe.items()}
        if conv and fe.get(conv):
            v = fe[conv]
            G["facing_within_30"] = sum(1 for x in v if x <= 30) / len(v)
        if conv and rfe.get(conv):
            v = rfe[conv]
            G["reader_facing_within_30"] = sum(1 for x in v if x <= 30) / len(v)
        MM[grp] = G
    P["minimap"] = MM
    return P


# ----------------------------------------------------------------- recording

def record_metrics(P: dict, results: list[dict], conv: str | None) -> list[str]:
    from reticle import metrics

    vers = Counter()
    for r in results:
        vers.update(r.get("versions", {}).values())
    deps = {"riot_truth": RIOT_TRUTH_VERSION, "match_tol_ms": MATCH_TOL_MS,
            "gate_m": GATE_M, "minimap_lag_ms": MINIMAP_LAG_MS,
            "facing_convention": conv}
    ctx = {"sessions": sorted(r["session"] for r in results if "deaths" in r),
           "stored_versions": sorted(vers)}
    toks = []
    d = P["deaths"]
    vals = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()
            if isinstance(v, (int, float)) and v is not None}
    metrics.record("riot_truth", part="deaths", values=vals, deps=deps, context=ctx)
    for f in ("recall", "precision", "victim_right_of_named", "killer_right_of_named",
              "weapon_right_of_named", "victim_refused", "killer_refused", "weapon_refused",
              "victim_right_unamb", "victim_wrong_unamb", "killer_right_unamb", "killer_wrong_unamb",
              "side_wrong", "riot_kind_weapon", "matched_kind_weapon", "riot_kind_ability",
              "matched_kind_ability", "riot_kind_unmapped", "matched_kind_unmapped",
              "riot_kind_bomb", "matched_kind_bomb"):
        toks.append(f"[metric:riot_truth/deaths#{f}={vals.get(f)}]")
    rv = {k: v for k, v in P["rounds"].items() if isinstance(v, (int, float))}
    for k in ("barrier_minus_clock_reset_ms", "plant_dt_ms"):
        s = P["rounds"].get(k) or {}
        rv[f"{k}_median"] = s.get("median")
        rv[f"{k}_mad"] = s.get("mad")
    metrics.record("riot_truth", part="rounds", values=rv, deps=deps, context=ctx)
    for f in ("riot_rounds", "stored_rounds", "count_equal_sessions", "winner_right", "winner_wrong",
              "plant_both", "plant_riot_only", "plant_store_only", "plant_within_1500",
              "plant_dt_ms_median"):
        toks.append(f"[metric:riot_truth/rounds#{f}={rv.get(f)}]")
    metrics.record("riot_truth", part="kd", values=dict(P["kd"]), deps=deps, context=ctx)
    for f in ("known_scored", "known_agree", "tracked_scored", "tracked_exact",
              "players", "players_exact"):
        toks.append(f"[metric:riot_truth/kd#{f}={P['kd'].get(f)}]")
    if P.get("assists"):
        metrics.record("riot_truth", part="assists", values=dict(P["assists"]), deps=deps,
                       context=ctx)
        for f in ("assists_right", "assists_wrong", "assists_unread", "riot_assists", "store_assists"):
            toks.append(f"[metric:riot_truth/assists#{f}={P['assists'].get(f)}]")
    al = {}
    for r in results:
        if "align" in r:
            al[r["session"]] = r["align"]
    av = {"sessions": len(al),
          "max_abs_drift_ms": round(max(abs(a["drift_ms_over_match"]) for a in al.values()), 1),
          "max_mad_ms": round(max(a["residual_mad_ms"] for a in al.values()), 1),
          "median_mad_ms": round(statistics.median(a["residual_mad_ms"] for a in al.values()), 1)}
    metrics.record("riot_truth", part="align", values=av, deps=deps, context=ctx)
    for f in av:
        toks.append(f"[metric:riot_truth/align#{f}={av[f]}]")
    for grp, G in P["minimap"].items():
        v = {k: x for k, x in G.items() if isinstance(x, (int, float))}
        for k in ("pos_err_px", "self_err_px", "enemy_err_px", "reader_pos_err_px"):
            s = G.get(k) or {}
            v[f"{k}_median"] = s.get("median")
            v[f"{k}_p95"] = s.get("p95")
        if conv:
            s = (G.get("facing_by_convention") or {}).get(conv) or {}
            v["facing_err_median"] = s.get("median")
            s = (G.get("reader_facing_by_convention") or {}).get(conv) or {}
            v["reader_facing_err_median"] = s.get("median")
        metrics.record("riot_truth", part=f"minimap/{grp}", values=v, deps=deps, context=ctx)
        for f in ("pos_err_px_median", "pos_err_px_p95", "self_err_px_median", "riot_allies",
                  "tracker_riot_allies", "matched", "missed", "missed_stacked", "phantom",
                  "id_right", "id_wrong", "id_refused", "facing_err_median", "facing_within_30",
                  "reader_matched", "reader_pos_err_px_median", "reader_facing_err_median",
                  "reader_facing_within_30", "enemy_matched", "enemy_store", "enemy_err_px_median"):
            if f in v:
                toks.append(f"[metric:riot_truth/minimap/{grp}#{f}={v[f]}]")
    for r in results:
        if "deaths" not in r:
            continue
        sv = {"recall": round(r["deaths"]["recall"], 4), "precision": round(r["deaths"]["precision"], 4),
              "matched": r["deaths"]["matched"], "riot_kills": r["deaths"]["riot_kills"],
              "stored_deaths": r["deaths"]["stored_deaths"],
              "offset_ms": round(r["align"]["a_ms"], 1), "slope": round(r["align"]["slope"], 7),
              "residual_mad_ms": round(r["align"]["residual_mad_ms"], 1)}
        metrics.record("riot_truth", part="session", session=r["session"], values=sv, deps=deps,
                       context={"stored_versions": sorted(r.get("versions", {}).values())})
    return toks


def stream_versions(store_root: Path, sid: str) -> dict:
    out = {}
    for kind, key in (("death", "death_adjudication_version"),
                      ("round_entity", "round_entity_version"),
                      ("ally_icon", "ally_icon_version")):
        for r in _stream_rows(Path(store_root) / "events" / kind / f"{sid}.jsonl"):
            if r.get(key):
                out[kind] = r[key]
            break
    return out


# ----------------------------------------------------------------- report

def _pct(n, d):
    return "-" if not d else f"{n}/{d} ({n / d:.1%})"


def print_session(r: dict, list_misses: bool):
    sid = r["session"]
    print(f"\n== {sid}  {r['map']}  {r['profile']}  cohort={r['cohort']}  player={r['player_basis']}")
    print(f"   capture {r['capture']}")
    if "refused" in r:
        print(f"   REFUSED {r['refused']}")
        kd = r.get("kd") or {}
        print(f"   K/D riot {kd.get('riot')} known {kd.get('known_kd')} ({kd.get('known_vs_riot')}) "
              f"tracked {kd.get('status_tracked')} delta {kd.get('tracked_vs_riot')}")
        return
    a = r["align"]
    print(f"   align a={a['a_ms'] / 1000:.3f} s slope={a['slope']:.7f} drift={a['drift_ms_over_match']:.0f} ms "
          f"matched {a['matched']}/{a['n_riot']} riot, {a['n_store']} stored; residual median "
          f"{a['residual_median_ms']:.0f} MAD {a['residual_mad_ms']:.0f} ms p05/p95 {a['residual_p05_p95_ms']}")
    d = r["deaths"]
    print(f"   deaths recall {_pct(d['matched'], d['riot_kills'])} precision {_pct(d['matched'], d['stored_deaths'])}"
          f"  victim R/W/ref {d.get('victim_right', 0)}/{d.get('victim_wrong', 0)}/{d.get('victim_refused', 0)}"
          f"  killer {d.get('killer_right', 0)}/{d.get('killer_wrong', 0)}/{d.get('killer_refused', 0)}"
          f"  weapon {d.get('weapon_right', 0)}/{d.get('weapon_wrong', 0)}/{d.get('weapon_refused', 0)}"
          f" (+{d.get('weapon_unmapped_riot', 0)} unmapped)  side R/W {d.get('side_right', 0)}/{d.get('side_wrong', 0)}")
    kd = r["kd"]
    print(f"   K/D riot {kd.get('riot')} known {kd.get('known_kd')} ({kd.get('known_vs_riot')}) "
          f"tracked {kd.get('status_tracked')} delta {kd.get('tracked_vs_riot')}; players exact "
          f"{kd.get('players_exact')}/{len(kd.get('players') or [])}")
    ro = r["rounds"]
    print(f"   rounds riot {ro['riot_rounds']} stored {ro['stored_rounds']} paired {ro['paired']} "
          f"winners R/W/unread {ro['winner_right']}/{ro['winner_wrong']}/{ro['winner_unread']} plants both "
          f"{ro['plant_both']} riot-only {ro['plant_riot_only']} store-only {ro['plant_store_only']} "
          f"plant dt {_summ(ro['plant_dt_ms'])} barrier-start {_summ(ro['start_dt_ms'])}")
    if r.get("assists"):
        print(f"   combat report per round {r['assists']}")
    mm = r.get("minimap")
    if mm:
        if "refused" in mm:
            print(f"   minimap REFUSED {mm['refused']}")
        else:
            print(f"   minimap px/m {mm['px_per_m']} gate {mm['gate_px']} px; frames {mm.get('kill_frames', 0)} "
                  f"(no frame {mm.get('kill_no_frame', 0)}, undrawn {mm.get('kill_widget_not_drawn', 0)}); allies "
                  f"{mm.get('riot_allies', 0)} matched {mm.get('matched', 0)} missed {mm.get('missed', 0)} "
                  f"phantom {mm.get('phantom', 0)} (outside {mm.get('missed_outside_widget', 0)}, stacked "
                  f"{mm.get('missed_stacked', 0)}; reader matched {mm.get('reader_matched', 0)}, with refused "
                  f"{mm.get('reader_matched_any', 0)}); pos err {mm['pos_err_px']} ({mm['pos_err_m']} m); self err "
                  f"{mm['self_err_px']} ({mm['self_err_m']} m); id R/W/ref {mm.get('id_right', 0)}/"
                  f"{mm.get('id_wrong', 0)}/{mm.get('id_refused', 0)}")
            best = sorted(((v or {}).get("median", 999), n) for n, v in mm["facing_by_convention"].items())
            print(f"   facing medians by convention {best[:3]}")
            if mm.get("enemy_frames"):
                print(f"   enemies frames {mm['enemy_frames']} store {mm['enemy_store']} matched "
                      f"{mm['enemy_matched']} err {mm['enemy_err_px']}")
            if mm.get("lag_scan_self_median_px"):
                print(f"   lag scan (ms: n, self median px) {mm['lag_scan_self_median_px']}")
    if list_misses:
        print("   MISSES (Riot kill, no stored death):")
        for x in d["misses"]:
            print(f"     {x['t_ms'] / 1000:8.1f} s  R{x['round']:<2} {x['killer']} -> {x['victim']} "
                  f"({x['victim_side']}) {x['weapon']}")
        print("   FALSE (stored death, no Riot kill):")
        for x in d["false"]:
            print(f"     {x['t_ms'] / 1000:8.1f} s  {x['death_id']} {x['killer']} -> {x['victim']} "
                  f"({x['side']}) second_life={x['second_life']} status={x['status']}")
        wrong = [w for w in r["death_rows"] if (w["victim"][1] and canon(w["victim"][0]) != canon(w["victim"][1]))
                 or (w["killer"][1] and canon(w["killer"][0]) != canon(w["killer"][1]))]
        print("   WRONG NAMES (riot, store):")
        for w in wrong:
            print(f"     {w['t_ms'] / 1000:8.1f} s  victim {w['victim']} killer {w['killer']} "
                  f"ambiguous={w['ambiguous']} {w['death_id']}")


def print_pool(P: dict, conv):
    d = P["deaths"]
    print("\n==== POOLED over", P["sessions"], "sessions")
    print(f"deaths: riot {d['riot_kills']} stored {d['stored_deaths']} matched {d['matched']} "
          f"recall {d['recall']:.4f} precision {d['precision']:.4f}")
    for role in ("victim", "killer", "weapon"):
        print(f"  {role}: right {d.get(role + '_right', 0)} wrong {d.get(role + '_wrong', 0)} "
              f"refused {d.get(role + '_refused', 0)} right/named {d.get(role + '_right_of_named')}")
    print(f"  unambiguous victim R/W {d.get('victim_right_unamb')}/{d.get('victim_wrong_unamb')} killer "
          f"{d.get('killer_right_unamb')}/{d.get('killer_wrong_unamb')}; side R/W {d.get('side_right')}/{d.get('side_wrong')}"
          f"; riot items unmapped {d.get('weapon_unmapped_riot')}; revive entries {d.get('revive_entries')}")
    kinds = [f"{k}: {d.get('matched_kind_' + k, 0)}/{d['riot_kind_' + k]}"
             for k in ("weapon", "ability", "unmapped", "bomb", "melee", "fall")
             if d.get("riot_kind_" + k)]
    print("  recall by riot kind " + ", ".join(kinds))
    print(f"  refusal reasons {json.dumps(d['refusal_reasons'])}")
    print(f"  weapon cross (riot -> store) {json.dumps(d['weapon_cross_top'])}")
    print(f"rounds: {json.dumps(P['rounds'])}")
    print(f"kd: {json.dumps(P['kd'])}")
    print(f"combat report per round: {json.dumps(P['assists'])}")
    for grp, G in P["minimap"].items():
        best = sorted(((v or {}).get("median", 999), n) for n, v in G["facing_by_convention"].items())
        print(f"minimap[{grp}] sessions {G['sessions']} frames {G.get('kill_frames')} allies {G.get('riot_allies')} "
              f"matched {G.get('matched')} missed {G.get('missed')} phantom {G.get('phantom')} reader "
              f"{G.get('reader_matched')}/{G.get('reader_matched_any')} of {G.get('reader_icons')} icons; missed outside "
              f"widget {G.get('missed_outside_widget', 0)} stacked {G.get('missed_stacked', 0)}; id R/W/ref "
              f"{G.get('id_right')}/{G.get('id_wrong')}/{G.get('id_refused')} pos {G['pos_err_px']} self "
              f"{G['self_err_px']} enemy {G['enemy_err_px']} ({G.get('enemy_matched')}/{G.get('enemy_store')}) "
              f"facing best {best[:2]} within30 {G.get('facing_within_30')} id refusals {G['id_refusal_reasons']}")
        print(f"  tracker allies {G.get('tracker_riot_allies')}; reader pos {G.get('reader_pos_err_px')} reader facing "
              f"{(G.get('reader_facing_by_convention') or {}).get(conv)} within30 {G.get('reader_facing_within_30')}")


def _below_normal() -> None:
    """Run at Below Normal priority: the player's own jobs share this CPU."""
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
        else:
            import os
            os.nice(10)
    except Exception:                                   # noqa: BLE001 -- best effort
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sessions", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--api-cache", default=None,
                    help="valorant-api cache directory (default <store>/external/valorant-api)")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--match-tol", type=float, default=MATCH_TOL_MS)
    ap.add_argument("--minimap-lag", type=float, default=MINIMAP_LAG_MS)
    ap.add_argument("--scan-lag", action="store_true", help="scan the minimap lag on the self icon")
    ap.add_argument("--unswapped", action="store_true", help="score the unswapped axis formula")
    ap.add_argument("--no-minimap", action="store_true")
    ap.add_argument("--no-status", action="store_true", help="skip status.collect (HUD K/D)")
    ap.add_argument("--facing", default="auto", help="viewRadians convention for the headline")
    ap.add_argument("--list-misses", action="store_true")
    ap.add_argument("--deaths-from", default=None,
                    help="score <dir>/events/death/<sid>.jsonl instead of the store's deaths")
    ap.add_argument("--record", action="store_true", help="append metrics to notes/metrics.jsonl")
    ap.add_argument("--json", default=None, help="write full results (private: keep outside the repo)")
    args = ap.parse_args(argv)
    _below_normal()

    root = Path(args.store)
    ref = Reference(Path(args.api_cache) if args.api_cache else root / "external" / "valorant-api",
                    fetch=not args.offline)
    recs = riot_records(root)
    idents = identify_player(recs, root)
    sids = sorted(recs) if args.all else args.sessions
    status_by = {}
    if not args.no_status:
        from reticle import status
        from reticle.store import Store
        status_by = {s["sid"]: s for s in status.collect(Store(root))["sessions"]
                     if s.get("sid") in sids}
    results = []
    for sid in sids:
        if sid not in recs:
            print(f"{sid}: no Riot record in {root / 'external' / 'riot'}")
            continue
        ident = resolve_lineup_player(recs[sid], idents[sid], ref)
        try:
            r = score_session(sid, recs[sid], ident, ref, root, status_by.get(sid), args)
        except FileNotFoundError as e:
            r = {"session": sid, "refused": f"missing:{e}", "capture": "", "profile": "",
                 "cohort": "", "player_basis": ident.get("basis"), "map": ""}
        r["versions"] = stream_versions(root, sid)
        results.append(r)
        print_session(r, args.list_misses)
    conv = args.facing
    P = pool(results, None)
    if conv == "auto":
        allm = P["minimap"].get("all") or {}
        fb = allm.get("facing_by_convention") or {}
        conv = min(fb, key=lambda n: (fb[n] or {}).get("median", 999)) if fb else None
    P = pool(results, conv)
    print_pool(P, conv)
    print(f"facing convention used: {conv}")
    if args.json:
        slim = []
        for r in results:
            r = json.loads(json.dumps(r, default=str))
            for k in ("pos_err_samples", "self_err_samples", "enemy_err_samples", "facing_err_samples",
                      "reader_err_samples", "reader_facing_samples"):
                (r.get("minimap") or {}).pop(k, None)
            slim.append(r)
        Path(args.json).write_text(json.dumps({"pool": P, "sessions": slim}, indent=1, default=str),
                                   encoding="utf-8")
    if args.record:
        for t in record_metrics(P, results, conv):
            print(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
