"""A replay parse, a Riot record and a capture, put on one clock and one map.

[owns:replay-alignment] [owns:replay-self]

What a kept VALORANT replay holds is external truth about its match
(docs/EXTERNAL_GROUND_TRUTH.md, which holds the use policy). vrfkit decodes a
replay into Parquet tables under `<store>/external/replays/parsed/vrfkit-<ver>/
<match>/export/`; this module reads them (`Replay`), names the agents through
valorant-api's cached tables (`Reference`), fits the replay-to-capture clock
offset on STORED deaths (`fit_alignment`, `capture_replay_context`) and maps
world units to baked widget pixels (`MapFrame`, `to_px`, `facing_px_deg`).

It also decides which replay player is the capturing player
(`capture_replay_context`, `decide_player`). Riot's match record decides
where it names him (`riot_records`, `identify_player`). The replay always
votes too: `replay_self_pick` names the replay player whose living path holds
the stored `ally_icon` self fit within `SELF_ID_RADIUS_M` on the most frames
(`choose_self_subject`), and `spawn_teams` splits the ten by spawn. With a
Riot player the replay's verdict is a stored cross-check; without one it is
used, `rests_on` `ally_icon.self`, or the context names its refusal.

These functions were the prototypes' (`riot_ground_truth`, `replay_truth`)
until 2026-10-05, when the replay layer (`replay_layer`) joined the pipeline;
the prototypes now import them from here, so one definition serves both.

Nothing here is shown during play, and nothing here reads pixels. A reader
or adjudicator never imports this module: only the replay layer, `plan` and
`doctor` do, and the scorers in `prototypes/`.

Format facts this rests on: [domain:replay/vrf-container],
[domain:replay/vrf-position-stream], [domain:replay/vrf-tick-pattern],
[domain:replay/vrf-round-started-opens-buy-phase],
[domain:replay/vrf-minimap-axes-cross].
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import statistics
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np

from .agent_names import canonical_agent
from .store import DEFAULT_STORE

REPLAY_SOURCE_VERSION = "replay-source-0.2.0"
VRFKIT_VERSION = "0.2.5"
API_BASE = "https://valorant-api.com/v1/"

#: Hidden or unspawned pawns park here (vrfkit tools/minimap.py: x -50,879..
#: -49,091, z -49,920..-49,785); judged on x and z, since a fall crosses that z.
PARK_X, PARK_Z, PARK_RADIUS = -50000.0, -49900.0, 2000.0
#: The longest gap between two movement samples a position is interpolated
#: across; a wider gap reads as no position (NaN), never a guess.
MAX_GAP_MS = 250.0
#: Coarse alignment: a kill counts toward an offset when a stored death lies
#: within this window of it. Wide enough to hold the 2 Hz grid and latency.
ALIGN_TOL_MS = 1500.0
ALIGN_STEP_MS = 250.0
#: A Riot kill and a stored death match within this many ms after alignment.
#: Two 500 ms killfeed samples plus render jitter either way.
MATCH_TOL_MS = 1500.0
#: The minimap read time relative to the killfeed-fitted offset. The fit's
#: offset includes about half a killfeed step of sampling lag plus the feed's
#: render delay. Measured with `--scan-lag` on the self icon (three sessions,
#: 2026-10-02): the median self error is least between -533 and -400 ms.
MINIMAP_LAG_MS = -450.0
#: Names that mean one thing under two spellings.
SAME_NAME = {"melee": "tactical knife", "tactical knife": "tactical knife"}
#: Teams from the replay: each player's position this long after the round's
#: start (buy phase, players in spawn) splits the ten into two spawn groups.
SPAWN_PROBE_MS = 2000.0
#: Replay self identification. A self-track frame counts for a replay player
#: when its icon lies within this many metres of the player's living
#: position: 2 m holds the self error's p90 on c817691bcd15 (96 cm) and the
#: bulk of 9acf02f98283's (median 75 cm), and stays inside a stack's spread.
SELF_ID_RADIUS_M = 2.0
#: Fewer self-track frames than this (60 s at 15 Hz) refuse `track_too_short`.
SELF_ID_MIN_FRAMES = 900
#: A best share under this refuses `no_fit`: no path follows the icon.
SELF_ID_MIN_SHARE = 0.30
#: The best share must lead the runner-up's by this much, else
#: `margin_too_small`. Chosen on the development matches only, by the rule
#: logged before they ran (`replay-self-id-20261006`): half the smaller of
#: c817691bcd15's and 9acf02f98283's margins, rounded down to 0.05, never
#: below 0.10. Their margins were 0.5701 and 0.5656 (2026-10-06), so the cut
#: is 0.25. The held-out match never informed it.
SELF_ID_MARGIN = 0.25
#: What the replay's choice of the player rests on.
SELF_ID_RESTS_ON = "ally_icon.self"


def replays_dir(root=DEFAULT_STORE) -> Path:
    return Path(root) / "external" / "replays"


def parsed_root(root=DEFAULT_STORE) -> Path:
    return replays_dir(root) / "parsed" / f"vrfkit-{VRFKIT_VERSION}"


def parsed_dir(match: str, root=DEFAULT_STORE) -> Path:
    return parsed_root(root) / match


def replay_manifest(root=DEFAULT_STORE) -> dict:
    """The kept replays' manifest (`external/replays/manifest.json`), or an
    empty one where none is stored."""
    p = replays_dir(root) / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"files": []}


def replay_entry(sid: str, root=DEFAULT_STORE, manifest: dict | None = None) -> dict | None:
    """The kept replay whose manifest entry names capture session `sid`."""
    man = replay_manifest(root) if manifest is None else manifest
    return next((f for f in man.get("files") or [] if f.get("capture_session") == sid), None)


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ----------------------------------------------------------------- reference

def canon_name(name: str | None) -> str | None:
    """One spelling per agent, weapon or map: the agent spelling
    (`agent_names.canonical_agent`) casefolded, then `SAME_NAME`."""
    if name is None:
        return None
    s = canonical_agent(name).casefold()
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


# ----------------------------------------------------------------- riot data

def riot_records(store_root: Path) -> dict[str, dict]:
    """Session id -> Riot record, from each record's probe."""
    out = {}
    for p in sorted((Path(store_root) / "external" / "riot").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out[d["probe"]["session_id"]] = d
    return out


def riot_record_path(sid: str, store_root=DEFAULT_STORE) -> Path | None:
    """The stored Riot record whose probe names session `sid`."""
    for p in sorted((Path(store_root) / "external" / "riot").glob("*.json")):
        if f'"{sid}"' in p.read_text(encoding="utf-8"):
            d = json.loads(p.read_text(encoding="utf-8"))
            if d["probe"]["session_id"] == sid:
                return p
    return None


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

    The retired `map_shade._warp`'s rotation about the art centre with its scale, shifted
    into a square canvas of side `int(max(h, w) * scale * 1.6)`, then placed at
    `(dx, dy)` as `wiki_map._place` does. The offsets are whole pixels in a
    capture fit and fractional in an official one (`reticle/map_asset.py`);
    truncating them moved Lotus positions by 0.7-1.0 px.
    """
    h0, w0 = art_hw
    rot, scale, dx, dy = (float(v) for v in fit[:4])
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


def map_frame_for(sid: str, man: dict, ref: Reference, d: dict, store_root: Path,
                  swap: bool = True) -> tuple[MapFrame | None, str | None]:
    from . import geometry

    gp = geometry.path_of(sid, store_root)
    if gp is None or not gp.is_file():
        return None, "no_geometry"
    mname = geometry.map_of(sid, store_root)
    mi = ref.map_of(d["match"]["matchInfo"]["mapId"])
    return map_frame_for_geometry(gp, mname, mi, store_root, swap)


def map_frame_for_geometry(gp: Path, mname: str, mi: dict, store_root: Path,
                           swap: bool = True) -> tuple[MapFrame | None, str | None]:
    """The MapFrame of one baked geometry npz `gp` of map `mname`, whose
    valorant-api entry is `mi`; no session needed (`prototypes/sightlines.py`)."""
    import cv2

    from .geometry import ART_ALPHA_MIN

    with np.load(gp) as z:
        if "shade_fit" not in z.files:
            return None, "no_shade_fit"
        fit = [float(v) for v in z["shade_fit"]]
        shape = z["labels"].shape
    art = cv2.imread(str(Path(store_root) / "reference" / "maps" / f"{mname}.png"),
                     cv2.IMREAD_UNCHANGED)
    if art is None:
        return None, "no_art"
    if canon_name(mi["displayName"]) != canon_name(mname):
        return None, f"map_mismatch:{mi['displayName']}!={mname}"
    ys, xs = np.where(art[:, :, 3] > ART_ALPHA_MIN)
    crop = (int(xs.min()), int(ys.min()), int(ys.max() - ys.min() + 1), int(xs.max() - xs.min() + 1))
    mf = MapFrame(mi, art.shape[:2], fit, swap, crop)
    mf.widget_shape = shape
    # an icon's radius in px: 6 px on the 331 px widget, scaled with it
    mf.icon_px = 6.0 * shape[1] / 331.0
    return mf, None


def to_px(mf, x, y):
    """`MapFrame.to_px`, vectorised over arrays: same constants, same affine."""
    u, v = game_to_uv(np.asarray(x, float), np.asarray(y, float), mf.m, mf.swap)
    h0, w0 = mf.art_hw
    ax = u * w0 - 0.5 - mf.crop[0]
    ay = v * h0 - 0.5 - mf.crop[1]
    A = mf.aff
    return A[0][0] * ax + A[0][1] * ay + A[0][2], A[1][0] * ax + A[1][1] * ay + A[1][2]


def facing_px_deg(mf, x, y, yaw_deg):
    """A world yaw as image degrees (y down), `MapFrame.facing_deg` vectorised."""
    th = np.radians(yaw_deg)
    x0, y0 = to_px(mf, x, y)
    x1, y1 = to_px(mf, x + 100.0 * np.cos(th), y + 100.0 * np.sin(th))
    return np.mod(np.degrees(np.arctan2(y1 - y0, x1 - x0)), 360.0)


def frames_to_replay(t_cap, a_ms: float, lag_ms: float):
    """Capture ms of a stored minimap frame -> the replay ms it shows."""
    return np.asarray(t_cap, float) - a_ms - lag_ms


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


def split_deaths(deaths: list[dict], legacy=()) -> tuple[list[dict], list[dict]]:
    """(rows Riot may list as kills, second-life rows counted apart).

    Revive entries are not kills; Riot lists kills only. A Run It Back death
    is no kill in Riot's record either [domain:rounds/resurrection-mechanics]:
    it is counted apart, never false and never right. `legacy` holding
    `second-life` keeps it among the kills, as 0.1.0 did.
    """
    kill_like = [r for r in deaths if not r.get("is_revive")]
    if "second-life" in set(legacy or ()):
        return kill_like, []
    return ([r for r in kill_like if not r.get("is_second_life")],
            [r for r in kill_like if r.get("is_second_life")])


# ----------------------------------------------------------------- the replay

class Replay:
    """One vrfkit export as numpy arrays: per-player tracks and the event list.

    `players[subject]` holds `t` (replay ms), `x`, `y`, `z` (cm), `yaw` and
    `pitch` (degrees) over every pawn the player owned, sorted by time, park-slot rows
    removed. `events` holds the server's event list with killer and victim
    resolved to subjects through `character_net_guids`.
    """

    def __init__(self, match: str, root=DEFAULT_STORE):
        import pyarrow.parquet as pq

        self.match = match
        self.dir = parsed_dir(match, root)
        ex = self.dir / "export"
        self.manifest = json.loads((ex / "manifest.json").read_text(encoding="utf-8"))
        self.guid_subject = {}
        self.subjects = []
        for p in self.manifest.get("players") or []:
            s = p.get("subject")
            if not s:
                continue
            self.subjects.append(s)
            for g in (p.get("character_net_guids") or [p.get("character_net_guid")]):
                if g:
                    self.guid_subject[int(g)] = s
        mv = pq.read_table(ex / "movement.parquet",
                           columns=["time_ms", "character_net_guid", "pos_x", "pos_y", "pos_z",
                                    "yaw", "pitch", "timestamp"])
        g = mv["character_net_guid"].to_numpy().astype(np.int64)
        t = mv["time_ms"].to_numpy().astype(np.float64)
        x = mv["pos_x"].to_numpy().astype(np.float64)
        y = mv["pos_y"].to_numpy().astype(np.float64)
        z = mv["pos_z"].to_numpy().astype(np.float64)
        yaw = mv["yaw"].to_numpy().astype(np.float64)
        pitch = mv["pitch"].to_numpy(zero_copy_only=False).astype(np.float64)
        self.movement_rows = int(t.size)
        park = (np.abs(x - PARK_X) <= PARK_RADIUS) & (np.abs(z - PARK_Z) <= PARK_RADIUS)
        self.park_rows = int(park.sum())
        self.raw = {"g": g, "t": t, "x": x, "y": y, "z": z, "yaw": yaw, "pitch": pitch,
                    "park": park}
        self.players = {}
        for s in self.subjects:
            gs = [k for k, v in self.guid_subject.items() if v == s]
            m = np.isin(g, gs) & ~park
            o = np.argsort(t[m], kind="stable")
            self.players[s] = {"t": t[m][o], "x": x[m][o], "y": y[m][o], "z": z[m][o],
                               "yaw": yaw[m][o], "pitch": pitch[m][o]}
        self.unjoined_rows = int((~np.isin(g, list(self.guid_subject))).sum())
        ev = pq.read_table(ex / "events.parquet").to_pylist()
        self.events = []
        for r in ev:
            e = {"group": r.get("group"), "t": float(r.get("time1") or 0.0),
                 "metadata": r.get("metadata"), "word0": r.get("word0"), "word1": r.get("word1")}
            if e["group"] == "characterDeath":
                e["killer"] = self.guid_subject.get(r.get("word0"))
                e["victim"] = self.guid_subject.get(r.get("word1"))
            self.events.append(e)
        self.events.sort(key=lambda e: e["t"])
        self.duration_ms = float(self.manifest.get("duration_ms") or
                                 max(e["t"] for e in self.events))

    # -- events
    def group(self, name: str) -> list[dict]:
        return [e for e in self.events if e["group"] == name]

    def round_starts(self) -> np.ndarray:
        return np.array([e["t"] for e in self.group("roundStarted")], float)

    def map_url(self) -> str | None:
        for k in ("level_names_and_times", "levelNamesAndTimes"):
            v = self.manifest.get(k) or (self.manifest.get("replay_info") or {}).get(k)
            if v:
                return v[0]["name"] if isinstance(v[0], dict) else v[0]
        hdr = self.manifest.get("header") or {}
        for k in ("level_names_and_times", "levelNamesAndTimes"):
            if hdr.get(k):
                v = hdr[k]
                return v[0]["name"] if isinstance(v[0], dict) else v[0]
        return None

    def loadouts(self) -> dict:
        """subject -> characterId, from the header's playerLoadouts JSON."""
        gsd = self.manifest.get("game_specific_data")
        if gsd is None:
            gsd = (self.manifest.get("header") or {}).get("game_specific_data")
        out = {}

        def walk(o):
            if isinstance(o, str):
                try:
                    walk(json.loads(o))
                except ValueError:
                    pass
            elif isinstance(o, dict):
                if "subject" in o and "characterId" in o:
                    out[o["subject"]] = o["characterId"]
                elif "Subject" in o and "CharacterID" in o:
                    out[o["Subject"]] = o["CharacterID"]
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(gsd)
        return out

    # -- positions
    def sample(self, s: str, t) -> dict:
        """Position and yaw of player `s` at replay times `t` (vectorised).

        Linear between the bracketing samples when both lie within
        `MAX_GAP_MS` of each other; NaN otherwise. Yaw comes from the nearer
        sample (an angle is not interpolated across a wrap)."""
        P = self.players[s]
        t = np.atleast_1d(np.asarray(t, float))
        n = P["t"].size
        out = {k: np.full(t.shape, np.nan) for k in ("x", "y", "z", "yaw")}
        if n < 2:
            return out
        i = np.clip(np.searchsorted(P["t"], t, side="right"), 1, n - 1)
        t0, t1 = P["t"][i - 1], P["t"][i]
        ok = (t >= t0) & (t <= t1) & ((t1 - t0) <= MAX_GAP_MS)
        span = np.where(t1 > t0, t1 - t0, 1.0)
        w = np.clip((t - t0) / span, 0.0, 1.0)
        for k in ("x", "y", "z"):
            v = P[k][i - 1] * (1 - w) + P[k][i] * w
            out[k] = np.where(ok, v, np.nan)
        near = np.where(w < 0.5, i - 1, i)
        out["yaw"] = np.where(ok, P["yaw"][near], np.nan)
        return out

    def alive(self, s: str, t) -> np.ndarray:
        """True where `s` is alive by the event list: after a round start and
        before that round's death of `s` (a revive is not modelled)."""
        t = np.atleast_1d(np.asarray(t, float))
        rs = self.round_starts()
        if rs.size == 0:
            return np.zeros(t.shape, bool)
        r_idx = np.searchsorted(rs, t, side="right") - 1
        alive = r_idx >= 0
        deaths = np.array([e["t"] for e in self.group("characterDeath") if e.get("victim") == s])
        if deaths.size:
            d_round = np.searchsorted(rs, deaths, side="right") - 1
            # earliest death per round
            first = {}
            for r, dt in zip(d_round, deaths):
                first[int(r)] = min(first.get(int(r), np.inf), float(dt))
            fd = np.array([first.get(int(r), np.inf) for r in range(rs.size)])
            alive &= ~(t >= fd[np.clip(r_idx, 0, rs.size - 1)])
        return alive


def sample_stats(x, nd=2) -> dict | None:
    """n, median, p90, p95, mean and max of a numeric sample (NaNs dropped)."""
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return None
    q = np.percentile(a, [50, 90, 95])
    return {"n": int(a.size), "median": round(float(q[0]), nd), "p90": round(float(q[1]), nd),
            "p95": round(float(q[2]), nd), "mean": round(float(a.mean()), nd),
            "max": round(float(a.max()), nd)}


# ----------------------------------------------------------------- the player

def spawn_teams(rp: Replay, rs: np.ndarray) -> dict:
    """Two spawn groups per round from each player's position `SPAWN_PROBE_MS`
    after the round starts, split by 2-means seeded with the two farthest
    players. Labels `A`/`B` follow round 0's split; `agree` counts the rounds
    whose split equals it."""
    subs = list(rp.subjects)
    parts = []
    for t0 in rs:
        xy = np.array([[rp.sample(s, [t0 + SPAWN_PROBE_MS])[k][0] for k in ("x", "y")]
                       for s in subs])
        ok = np.all(np.isfinite(xy), axis=1)
        if ok.sum() < 4:
            parts.append(None)
            continue
        d = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
        d[~ok, :] = 0
        d[:, ~ok] = 0
        i, j = np.unravel_index(np.argmax(d), d.shape)
        c = np.array([xy[i], xy[j]])
        lab = np.zeros(len(subs), np.int64)
        for _ in range(10):
            dd = np.hypot(xy[:, None, 0] - c[None, :, 0], xy[:, None, 1] - c[None, :, 1])
            lab = np.argmin(dd, axis=1)
            c = np.array([xy[ok & (lab == q)].mean(axis=0) for q in (0, 1)])
        parts.append(np.where(ok, lab, -1))
    ref = next((p for p in parts if p is not None and (p >= 0).all()), None)
    if ref is None:
        return {"team": {}, "agree": 0, "rounds": len(parts), "basis": "spawn_cluster_failed"}
    agree = 0
    for p in parts:
        if p is None:
            continue
        ok = p >= 0
        if np.all(p[ok] == ref[ok]) or np.all(p[ok] == 1 - ref[ok]):
            agree += 1
    return {"team": {s: "AB"[int(ref[k])] for k, s in enumerate(subs)}, "agree": agree,
            "rounds": len(parts), "basis": "spawn_cluster"}


def living_widget_px(rp: Replay, mf, subs, t_rep):
    """(n, k) widget px, image-degree facing and a living mask for subjects
    `subs` at replay times `t_rep`; NaN where dead (`Replay.alive`) or
    unsampled."""
    t_rep = np.asarray(t_rep, float)
    n, k = t_rep.size, len(subs)
    X, Y, YAW = (np.full((n, k), np.nan) for _ in range(3))
    L = np.zeros((n, k), bool)
    for c, s in enumerate(subs):
        q = rp.sample(s, t_rep)
        live = rp.alive(s, t_rep) & np.isfinite(q["x"])
        px, py = to_px(mf, q["x"], q["y"])
        L[:, c] = live
        X[:, c] = np.where(live, px, np.nan)
        Y[:, c] = np.where(live, py, np.nan)
        YAW[:, c] = np.where(live, facing_px_deg(mf, q["x"], q["y"], q["yaw"]), np.nan)
    return X, Y, YAW, L


def ally_icon_self_track(sid: str, root=DEFAULT_STORE) -> dict:
    """The stored self-icon track: `ally_icon`'s frame rows with the widget
    drawn and a self fit, in frame order (`t_ms`, `x`, `y` in widget px)."""
    t, x, y, fi = [], [], [], []
    p = Path(root) / "events" / "ally_icon" / f"{sid}.jsonl"
    if p.is_file():
        with p.open(encoding="utf-8") as f:
            for line in f:
                if '"kind":"frame"' not in line and '"kind": "frame"' not in line:
                    continue
                r = json.loads(line)
                if r.get("kind") != "frame" or not r.get("widget_drawn") or not r.get("self"):
                    continue
                fi.append(r["frame_idx"])
                t.append(r["t_ms"])
                x.append(r["self"][0])
                y.append(r["self"][1])
    o = np.argsort(np.asarray(fi, np.int64), kind="stable")
    x, y = np.asarray(x, float)[o], np.asarray(y, float)[o]
    m = np.isfinite(x)
    return {"t_ms": np.asarray(t, float)[o][m], "x": x[m], "y": y[m]}


def choose_self_subject(dist_m, subjects, radius_m: float = SELF_ID_RADIUS_M,
                        min_frames: int = SELF_ID_MIN_FRAMES,
                        min_share: float = SELF_ID_MIN_SHARE,
                        margin: float = SELF_ID_MARGIN) -> dict:
    """Which replay subject the self-icon track follows, or a refusal.

    `dist_m` is (n_frames, k): metres from each self-track frame's icon to
    subject `subjects[c]`, NaN where that subject is dead or unsampled. Each
    subject's share is the fraction of ALL n frames within `radius_m` (a dead
    subject misses, so a teammate the dead player spectates scores only those
    frames). The best subject wins when the track has `min_frames`, its share
    reaches `min_share`, and it leads the runner-up by `margin`; otherwise
    `subject` is None and `reason` says which test failed. The candidate set
    is every replay subject: before the player is known no context narrows it.
    """
    D = np.asarray(dist_m, float).reshape(-1, len(subjects))
    n = int(D.shape[0])
    within = np.isfinite(D) & (D <= radius_m)
    share = within.sum(axis=0) / max(1, n)
    alive = np.isfinite(D).sum(axis=0)
    med = np.array([float(np.median(D[np.isfinite(D[:, c]), c])) if alive[c] else np.nan
                    for c in range(D.shape[1])])
    o = np.argsort(-share, kind="stable")
    cands = [{"subject": subjects[c], "share_within": round(float(share[c]), 4),
              "frames_alive": int(alive[c]),
              "median_m_alive": None if not np.isfinite(med[c]) else round(float(med[c]), 3)}
             for c in o]
    best = cands[0] if cands else None
    second = cands[1] if len(cands) > 1 else None
    lead = None if best is None else round(best["share_within"] - (second["share_within"]
                                                                  if second else 0.0), 4)
    out = {"frames": n, "radius_m": radius_m, "min_frames": min_frames, "min_share": min_share,
           "margin_cut": margin, "margin": lead, "best": best, "runner_up": second,
           "candidates": cands, "subject": None, "reason": None}
    if n < min_frames:
        out["reason"] = f"track_too_short:{n}<{min_frames}"
    elif best is None or best["share_within"] < min_share:
        out["reason"] = f"no_fit:best_share<{min_share}"
    elif lead < margin:
        out["reason"] = f"margin_too_small:{lead}<{margin}"
    else:
        out["subject"] = best["subject"]
    return out


def replay_self_pick(sid: str, rp: Replay, mf, a: float, spawn: dict,
                     root=DEFAULT_STORE, margin: float = SELF_ID_MARGIN) -> dict:
    """`choose_self_subject` on the stored self-icon track
    (`ally_icon_self_track`), put on replay time by the fitted offset `a` and
    `MINIMAP_LAG_MS`, against each replay subject's living position in widget
    px (`living_widget_px`). `spawn` is `spawn_teams`'s split, recorded beside
    the pick. The verdict `rests_on` `ally_icon.self`: a self fit scored later
    is no longer independent of it."""
    T = ally_icon_self_track(sid, root)
    t_rep = frames_to_replay(T["t_ms"], a, MINIMAP_LAG_MS)
    subs = list(rp.subjects)
    X, Y, _yaw, _L = living_widget_px(rp, mf, subs, t_rep)
    px_per_m = mf.px_per_unit * 100.0
    D = np.hypot(X - T["x"][:, None], Y - T["y"][:, None]) / px_per_m
    pick = choose_self_subject(D, subs, margin=margin)
    pick["rests_on"] = SELF_ID_RESTS_ON
    pick["track"] = "ally_icon frame rows: widget_drawn and self not null"
    pick["teams"] = {"basis": spawn["basis"], "spawn_cluster_rounds_agreeing": spawn["agree"],
                     "spawn_cluster_rounds": spawn["rounds"]}
    return pick


def same_side(team_a: dict, me_a, team_b: dict, me_b, subjects) -> bool | None:
    """Whether two team labellings put the same subjects on each player's side."""
    if not team_a or not team_b or me_a is None or me_b is None:
        return None
    side_a = {s for s in subjects if team_a.get(s) is not None and team_a.get(s) == team_a.get(me_a)}
    side_b = {s for s in subjects if team_b.get(s) is not None and team_b.get(s) == team_b.get(me_b)}
    return side_a == side_b


def decide_player(pick: dict, spawn_team: dict, riot_me, riot_team: dict, agent: dict,
                  subjects) -> dict:
    """The capturing player and the teams, and the record of how.

    Riot's player, where its record names one, decides; the replay's pick is
    stored beside it with whether it agrees (`riot_cross_check`; a
    disagreement is flagged, never resolved silently). Without a Riot player
    the pick and the spawn split are used (`used` `replay_self_track`), or
    `refused` names the pick's reason. Returns `me`, `team`, `player_basis`
    and `team_source` (None where Riot's stand), `refused` and
    `self_identity`."""
    rme = pick["subject"]
    si = {"replay": {**pick, "agent": agent.get(rme) if rme else None,
                     "best_agent": agent.get((pick["best"] or {}).get("subject")),
                     "runner_up_agent": agent.get((pick["runner_up"] or {}).get("subject"))}}
    out = {"me": riot_me, "team": riot_team, "player_basis": None, "team_source": None,
           "refused": None, "self_identity": si}
    if riot_me is not None:
        self_ok = None if rme is None else rme == riot_me
        team_ok = same_side(spawn_team, rme if rme else riot_me, riot_team, riot_me, subjects)
        best_ok = (pick["best"] or {}).get("subject") == riot_me
        si["riot_cross_check"] = {"present": True, "self_agrees": self_ok, "best_agrees": best_ok,
                                  "team_agrees": team_ok, "riot_agent": agent.get(riot_me),
                                  "disagreement": self_ok is False or team_ok is False}
        si["used"] = "riot_record"
        return out
    si["riot_cross_check"] = {"present": False}
    if rme is None or not spawn_team:
        si["used"] = None
        out.update(me=None, team={},
                   refused=f"no_player_or_team:replay_self:{pick['reason'] or 'no_spawn_teams'}")
        return out
    si["used"] = "replay_self_track"
    out.update(me=rme, team=spawn_team, player_basis="replay_self_track",
               team_source="replay_spawn_split")
    return out


def capture_replay_context(sid: str, geometry: Path | None = None, root=DEFAULT_STORE,
                           require_player: bool = True) -> dict:
    """What every user of one capture's replay needs, built once from STORED events.

    The replay, the agents (playerLoadouts), the replay-to-capture offset
    `a` fitted on replay kills against the stored deaths (capture ms = replay
    ms + `a`), the stored rounds, the baked `MapFrame`, and the player and
    teams (`decide_player`: Riot's player where its record names one, else
    the replay's pick on the stored self track, `out["self_identity"]`
    either way). `geometry` names the baked npz whose `shade_fit` places the
    map (default: the session's own, `geometry.path_of`), so one capture can
    be placed before and after a geometry rebuild; the report names the file
    and its fit. `ctx["out"]` is the report's head; a refusal sets
    `ctx["out"]["refused"]` and leaves the later keys out. The replay layer
    and the prototypes' scorers use it. Where neither Riot nor the replay
    names the player it refuses `no_player_or_team:replay_self:<reason>`,
    unless `require_player` is false: then the context is whole, `me` is
    None, `team`, `allies` and `foes` are empty, and `out["self_refused"]`
    holds the reason.
    """
    from . import geometry as _geo
    from .store import Store

    root = Path(root)
    store = Store(root)
    man = store.read_manifest(sid)
    recs = riot_records(root)
    d = recs.get(sid)
    entry = replay_entry(sid, root)
    if entry is None:
        return {"out": {"session": sid, "refused": "no_replay_for_session"}}
    match = Path(entry["file"]).stem
    rp = Replay(match, root)
    ref = Reference(root / "external" / "valorant-api", fetch=False)
    out = {"session": sid, "capture": man["source"]["path"], "profile": man["source_profile"],
           "replay_source_version": REPLAY_SOURCE_VERSION, "vrfkit": VRFKIT_VERSION,
           "minimap_lag_ms": MINIMAP_LAG_MS}
    # Riot's player and teams (external, like the replay); decided below
    ident = identify_player(recs, root).get(sid, {}) if d else {}
    riot_me = ident.get("subject")
    riot_team = {p["subject"]: p["teamId"] for p in d["match"]["players"]} if d else {}
    if riot_me is None or not riot_team:
        riot_me, riot_team = None, {}
    out["player_basis"] = ident.get("basis")
    out["team_source"] = "riot_record" if d else None
    out["allies"] = []
    agent = {s: ref.agent(c) for s, c in rp.loadouts().items()}

    # -- alignment: replay kills against stored deaths (killfeed first sample)
    deaths = stored_deaths(root, sid)
    kill_like, _second = split_deaths(deaths)
    st = [float(r["t_ms"]) for r in kill_like]
    rk = [e["t"] for e in rp.group("characterDeath")]
    al = fit_alignment(rk, st)
    if al is None:
        out["refused"] = "no_alignment:no_stored_deaths_or_replay_kills"
        return {"out": out}
    a = al["a_ms"]
    out["align"] = {k: v for k, v in al.items() if k != "pairs"}
    # the independent cross-check: stored round starts against roundStarted
    date = man["ingested_at"][:10]
    rounds = store.read_rounds(sid, date).to_pylist() if store.rounds_path(sid, date).exists() else []
    rs = rp.round_starts()
    if rounds and rs.size:
        t0 = np.array([r["t_start_ms"] for r in rounds], float)
        cand = rs + a
        dd = t0[:, None] - cand[None, :]
        j = np.argmin(np.abs(dd), axis=1)
        diff = dd[np.arange(t0.size), j]
        out["align"]["stored_round_start_minus_replay_ms"] = sample_stats(diff, 1)
        out["align"]["stored_round_start_rows"] = [
            {"round_no": r["round_no"], "source": r["start_source"], "diff_ms": round(float(x), 1)}
            for r, x in zip(rounds, diff)]
        src = np.array([r["start_source"] for r in rounds])
        out["align"]["stored_round_start_by_source"] = {
            k: {**sample_stats(diff[src == k], 1), "within_1s": int(np.sum(np.abs(diff[src == k]) <= 1000))}
            for k in sorted(set(src))}
        pl = np.array([e["t"] for e in rp.group("spikePlanted")]) + a
        sp = np.array([r["plant_t_ms"] for r in rounds if r.get("plant_t_ms")], float)
        if pl.size and sp.size:
            dp = sp[:, None] - pl[None, :]
            jp = np.argmin(np.abs(dp), axis=1)
            out["align"]["stored_plant_minus_replay_ms"] = sample_stats(dp[np.arange(sp.size), jp], 1)

    gp = Path(geometry) if geometry else _geo.path_of(sid, root)
    if gp is None or not Path(gp).is_file():
        mf, why = None, "no_geometry"
    else:
        mf, why = map_frame_for_geometry(Path(gp), _geo.map_of(sid, root),
                                         ref.map_of(rp.map_url()), root)
    if mf is not None:
        with np.load(gp) as z:
            out["geometry"] = {"path": str(gp).replace("\\", "/"),
                               "default": geometry is None,
                               "shade_fit": [round(float(v), 6) for v in z["shade_fit"]],
                               "built_by": str(z["built_by"]) if "built_by" in z.files else None,
                               "shade_built_by": (str(z["shade_built_by"])
                                                  if "shade_built_by" in z.files else None)}
    if mf is None:
        out["refused"] = f"map_frame:{why}"
        return {"out": out}
    # the vectorised transform must reproduce MapFrame.to_px
    probe = [(0.0, 0.0), (1234.0, -5678.0), (-4000.0, 3000.0)]
    vx, vy = to_px(mf, [p[0] for p in probe], [p[1] for p in probe])
    assert max(math.hypot(vx[i] - mf.to_px(*p)[0], vy[i] - mf.to_px(*p)[1])
               for i, p in enumerate(probe)) < 1e-6
    cm_per_px = 1.0 / mf.px_per_unit
    H, W = mf.widget_shape
    out["px_per_m"] = round(mf.px_per_unit * 100.0, 3)
    out["widget"] = [int(W), int(H)]

    # -- who is the player: Riot decides where it can; the replay always votes
    spawn = spawn_teams(rp, rs)
    pick = replay_self_pick(sid, rp, mf, a, spawn, root)
    who = decide_player(pick, spawn["team"], riot_me, riot_team, agent, rp.subjects)
    me, team = who["me"], who["team"]
    if who["player_basis"]:
        out["player_basis"], out["team_source"] = who["player_basis"], who["team_source"]
    out["self_identity"] = who["self_identity"]
    if who["refused"]:
        if require_player:
            out["refused"] = who["refused"]
            return {"out": out}
        out["self_refused"] = who["refused"]
    allies = [s for s in rp.subjects if me and team.get(s) == team[me]]
    foes = [s for s in rp.subjects if me and s in team and team[s] != team[me]]
    out["allies"] = [agent.get(s) for s in allies]
    return {"out": out, "store": store, "man": man, "rp": rp, "ref": ref, "me": me,
            "team": team, "allies": allies, "foes": foes, "agent": agent, "a": a,
            "rounds": rounds, "rs": rs, "mf": mf, "cm_per_px": cm_per_px, "match": match,
            "geometry_path": gp, "riot": d}
