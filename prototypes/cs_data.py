r"""Counter-Strike baseline data: download, parse and tidy two published sources.

    .\.venv\Scripts\python.exe prototypes\cs_data.py kaggle            # mm_master_demos.csv -> parquet
    .\.venv\Scripts\python.exe prototypes\cs_data.py esta [--n 100]    # ESTA online demos -> parquet
    .\.venv\Scripts\python.exe prototypes\cs_data.py tables [--record] # sizes, rank spread, WP tables

Plan and sources: docs/CS_TRANSFER_SAMPLE.md. Everything lands under
`<store>/external/cs/`, which must stay under `BUDGET_BYTES` (2 GB) at every
moment; each raw download is deleted once parsed and checked.

Sources and licences
--------------------
* `kaggle_mm/`: `mm_master_demos.csv` of the Kaggle dataset
  skihikingkevin/csgo-matchmaking-damage ("CS:GO Competitive Matchmaking
  Data"), CC BY-NC-SA 4.0. One row per damage event in CS:GO matchmaking,
  with ranks. The API is called with the player's Kaggle API token
  (`KAGGLE_API_TOKEN` in the repository's git-ignored `.env`) sent as
  `Authorization: Bearer <token>`, as `kagglesdk`'s `KaggleHttpClient.BearerAuth`
  does; the token is never printed, logged or stored elsewhere.
* `esta/`: 100 demos of `data/online/` in pnxenopoulos/esta on GitHub (awpy
  1.3.1 JSON, one `.json.xz` per demo), CC BY-SA 4.0. Professional matches.

Each directory holds a `SOURCE.json` with licence, source URL, retrieval date
and the files' byte counts. These data fit win-probability and coaching
baselines and priors only; they never feed a reader or anything shown in play.

Pseudonyms
----------
Steam ids are replaced by `pseudonym()`: a keyed splitmix64 mix of the id with a
64-bit salt kept at `<store>/external/cs/.pseudonym_salt` (created once, never
committed). The same id maps to the same pseudonym in both sources. Player
names are dropped.

Tables kept (zstd parquet)
--------------------------
kaggle_mm/damage.parquet  one row per damage event: match (file), map, round,
    tick, seconds, att_pid, vic_pid, att_side, vic_side, hp_dmg, arm_dmg,
    is_bomb_planted, bomb_site, wp_type, att_rank, vic_rank, positions.
kaggle_mm/rounds.parquet  one row per round: match, map, round, winner_side,
    round_type, ct_eq_val, t_eq_val, avg_match_rank.
kaggle_mm/kills.parquet   deaths rebuilt from damage: the damage row at which a
    victim's cumulative hp_dmg in the round reaches 100.
esta/rounds.parquet, esta/kills.parquet, esta/frames.parquet  per demo, from
    awpy's gameRounds, kills (with isTrade) and frames (2 Hz: alive counts,
    bomb planted and site, clock string, team equipment value).

Coarse-state table (`states.parquet` in each source dir)
--------------------------------------------------------
Side-neutral, as the VALORANT side states it (attackers plant; in CS the T
side attacks, the CT side defends). One row per event:

    source        str    "kaggle_mm" | "esta"
    match         str    match key within the source
    round         int16  round number
    event         str    "start" (freeze end), "kill" (state after the kill)
                         or "tick" (2 Hz frame; ESTA only)
    t_s           float32 seconds since freeze end (the round clock's start)
    atk_alive     int8   attackers alive (CS: T)
    def_alive     int8   defenders alive (CS: CT)
    planted       bool   bomb planted at t_s
    since_plant_s float32 seconds since the plant, null before it
    atk_load      float32 attackers' team equipment value at freeze end
    def_load      float32 defenders' team equipment value at freeze end
    skill         int8   matchmaking rank 1-18 (round's avg_match_rank,
                         rounded), 19 for professional (ESTA), null unknown
    atk_win       bool   the attackers won the round

    deciding      bool   the state ends the round: defenders at zero, or
                         attackers at zero before a plant

The matchmaking CSV's `seconds` count from the demo's start, and it records no
round start or plant time, so its `t_s` and `since_plant_s` are null; each side
starts with five. ESTA's `t_s` counts ticks from freeze end (awpy's own
`seconds` restart at the plant); its start counts come from the round's first
frame. `wp_table()` reads this table only.

Wire: no (notes/predictions.jsonl, task cs-data-20261004).
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as _dt
import json
import lzma
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle import metrics  # noqa: E402

VERSION = "cs-data-0.1.0"
REPO = Path(__file__).resolve().parent.parent
STORE = metrics.STORE
CS = STORE / "external" / "cs"
BUDGET_BYTES = 2_000_000_000
PRO_SKILL = 19

KAGGLE_API = "https://www.kaggle.com/api/v1"
KAGGLE_OWNER, KAGGLE_SLUG, KAGGLE_FILE = "skihikingkevin", "csgo-matchmaking-damage", "mm_master_demos.csv"
KAGGLE_LICENCE = "CC BY-NC-SA 4.0"
ESTA_LIST = "https://api.github.com/repos/pnxenopoulos/esta/contents/data/online"
ESTA_LICENCE = "CC BY-SA 4.0"
ZSTD = {"compression": "zstd", "compression_level": 9}

MM_COLUMNS = ["file", "map", "date", "round", "tick", "seconds", "att_side", "vic_side",
              "hp_dmg", "arm_dmg", "is_bomb_planted", "bomb_site", "wp_type",
              "att_id", "att_rank", "vic_id", "vic_rank",
              "att_pos_x", "att_pos_y", "vic_pos_x", "vic_pos_y",
              "winner_side", "round_type", "ct_eq_val", "t_eq_val", "avg_match_rank"]


# ---------------------------------------------------------------- utilities

def below_normal() -> None:
    """Run this process at Below Normal priority (Windows) or nice 10."""
    if os.name == "nt":
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
    else:  # pragma: no cover
        os.nice(10)


def env_value(path: Path, name: str) -> str | None:
    """The value of `name` in a dotenv file, unquoted; None when absent."""
    if not Path(path).exists():
        return None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip().removeprefix("export ").strip() == name:
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            return v
    return None


def tree_bytes(root: Path = CS) -> int:
    """Bytes under `root`, every file."""
    return sum(p.stat().st_size for p in Path(root).rglob("*") if p.is_file())


def check_budget(extra: int = 0, root: Path = CS) -> int:
    """Raise if the tree plus `extra` pending bytes would reach the budget."""
    used = tree_bytes(root)
    if used + extra >= BUDGET_BYTES:
        raise RuntimeError(f"external/cs would hold {used + extra} B, budget {BUDGET_BYTES} B")
    return used


def load_salt(path: Path | None = None) -> int:
    """The 64-bit pseudonym salt, created on first use."""
    path = Path(path or CS / ".pseudonym_salt")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{secrets.randbits(64)}\n", encoding="ascii")
    return int(path.read_text(encoding="ascii").strip())


_M1, _M2, _G = np.uint64(0xBF58476D1CE4E5B9), np.uint64(0x94D049BB133111EB), np.uint64(0x9E3779B97F4A7C15)


def pseudonym(ids, salt: int) -> np.ndarray:
    """Keyed splitmix64 of integer ids, as int64; 0 and negatives map to -1 (no player)."""
    a = np.asarray(ids)
    valid = a > 0
    x = a.astype(np.uint64, copy=True)
    with np.errstate(over="ignore"):
        x = x ^ np.uint64(salt & 0xFFFFFFFFFFFFFFFF)
        x = x + _G
        x = (x ^ (x >> np.uint64(30))) * _M1
        x = (x ^ (x >> np.uint64(27))) * _M2
        x = x ^ (x >> np.uint64(31))
    out = (x >> np.uint64(1)).astype(np.int64)
    out[~valid] = -1
    return out


def write_source(dirpath: Path, info: dict) -> None:
    """SOURCE.json beside the data: licence, origin and retrieval facts."""
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "SOURCE.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- Kaggle

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _kaggle_open(url: str, token: str):
    """Open a Kaggle API URL with the bearer token; follow a redirect without it."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                               "User-Agent": "reticle-cs-data"})
    try:
        return opener.open(req, timeout=120)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            # The signed storage URL carries its own credentials; the token stays home.
            return urllib.request.urlopen(e.headers["Location"], timeout=120)
        raise RuntimeError(f"Kaggle HTTP {e.code} for {url.split('?')[0]}") from None


def kaggle_download(dest: Path, token: str) -> dict:
    """Stream mm_master_demos.csv (or its zip) to `dest`; return byte facts."""
    url = f"{KAGGLE_API}/datasets/download/{KAGGLE_OWNER}/{KAGGLE_SLUG}/{urllib.parse.quote(KAGGLE_FILE)}"
    t0 = time.time()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    n = 0
    with _kaggle_open(url, token) as r, open(tmp, "wb") as f:
        expected = int(r.headers.get("Content-Length") or 0)
        check_budget(expected)
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
            n += len(b)
    if expected and n != expected:
        tmp.unlink()
        raise RuntimeError(f"short download {n} of {expected} B")
    with open(tmp, "rb") as f:
        is_zip = f.read(4) == b"PK\x03\x04"
    final = dest.with_suffix(".zip") if is_zip else dest
    os.replace(tmp, final)
    return {"path": final, "bytes": n, "zip": is_zip, "seconds": round(time.time() - t0, 1)}


def _csv_stream(path: Path):
    """A binary stream of the CSV, from a plain file or the zip's one member."""
    if zipfile.is_zipfile(path):
        z = zipfile.ZipFile(path)
        name = [n for n in z.namelist() if n.endswith(".csv")][0]
        return z.open(name)
    return open(path, "rb")


def csv_data_rows(path: Path) -> int:
    """The CSV's data rows, counted as newlines less the header.

    The matchmaking CSV quotes no field that holds a newline, so a line is a row."""
    n, last = 0, b"\n"
    with _csv_stream(path) as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            n += b.count(b"\n")
            last = b[-1:]
    return n - 1 + (0 if last == b"\n" else 1)


def _np(x, dtype=None) -> np.ndarray:
    """A numpy array from a pyarrow array, chunked array or array-like."""
    if isinstance(x, (pa.Array, pa.ChunkedArray)):
        x = x.to_numpy(zero_copy_only=False)
    return np.asarray(x, dtype) if dtype is not None else np.asarray(x)


def mm_convert(src: Path, out_dir: Path, salt: int) -> dict:
    """Stream the matchmaking CSV into damage.parquet with pseudonymised ids.

    Returns the parquet row count and the CSV's own data-row count."""
    out_dir.mkdir(parents=True, exist_ok=True)
    types = {"att_id": pa.int64(), "vic_id": pa.int64(), "round": pa.int16(), "tick": pa.int32(),
             "seconds": pa.float32(), "hp_dmg": pa.int16(), "arm_dmg": pa.int16(),
             "att_rank": pa.int8(), "vic_rank": pa.int8(), "ct_eq_val": pa.int32(),
             "t_eq_val": pa.int32(), "avg_match_rank": pa.float32(), "is_bomb_planted": pa.bool_(),
             "att_pos_x": pa.float32(), "att_pos_y": pa.float32(),
             "vic_pos_x": pa.float32(), "vic_pos_y": pa.float32()}
    conv = pacsv.ConvertOptions(include_columns=MM_COLUMNS, column_types=types,
                                strings_can_be_null=True)
    tmp = out_dir / "damage.parquet.part"
    rows = 0
    writer = None
    with _csv_stream(src) as f:
        reader = pacsv.open_csv(f, read_options=pacsv.ReadOptions(block_size=1 << 24),
                                convert_options=conv)
        for batch in reader:
            t = pa.Table.from_batches([batch])
            for col in ("att_id", "vic_id"):
                ids = pc.fill_null(t[col], 0).to_numpy()
                pid = pa.array(pseudonym(ids, salt), pa.int64())
                t = t.set_column(t.schema.get_field_index(col), col.replace("_id", "_pid"), pid)
            t = t.rename_columns([("match" if n == "file" else n) for n in t.column_names])
            if writer is None:
                writer = pq.ParquetWriter(tmp, t.schema, **ZSTD)
            writer.write_table(t)
            rows += t.num_rows
    if writer is None:
        raise RuntimeError(f"{src} held no rows")
    writer.close()
    os.replace(tmp, out_dir / "damage.parquet")
    return {"parquet_rows": rows, "csv_rows": csv_data_rows(src)}


def _round_starts(match, rnd) -> np.ndarray:
    new = np.ones(len(rnd), bool)
    new[1:] = (match[1:] != match[:-1]) | (rnd[1:] != rnd[:-1])
    return new


def mm_tables(damage: pa.Table) -> tuple[pa.Table, pa.Table]:
    """(rounds, kills) rebuilt from matchmaking damage rows.

    A death is the damage row at which the victim's cumulative hp_dmg in the
    round first reaches 100. Rounds are those with at least one damage row; a
    round whose rows name more than one winner is kept with `winner_conflict`."""
    d = damage.sort_by([("match", "ascending"), ("round", "ascending"), ("tick", "ascending")])
    m = _np(d["match"])
    r = _np(d["round"])
    new = _round_starts(m, r)
    first = np.flatnonzero(new)
    gid = np.cumsum(new) - 1
    rounds = d.take(pa.array(first)).select(
        ["match", "map", "round", "winner_side", "round_type", "ct_eq_val", "t_eq_val",
         "avg_match_rank"])
    win = _np(d["winner_side"])
    same = ~new[1:]
    disagree = np.zeros(len(first), bool)
    np.logical_or.at(disagree, gid[1:][same], win[1:][same] != win[:-1][same])
    rounds = rounds.append_column("winner_conflict", pa.array(disagree))

    vic = _np(d["vic_pid"])
    order = np.lexsort((_np(d["tick"]), vic, gid))
    g, v = gid[order], vic[order]
    hp = _np(d["hp_dmg"]).astype(np.int64)[order]
    hp = np.where(hp > 0, hp, 0)
    key_new = np.ones(len(order), bool)
    key_new[1:] = (g[1:] != g[:-1]) | (v[1:] != v[:-1])
    cs = np.cumsum(hp)
    base = np.maximum.accumulate(np.where(key_new, cs - hp, 0))
    crossed = ((cs - base) >= 100) & (v > 0)
    prev = np.zeros(len(order), bool)
    prev[1:] = crossed[:-1] & ~key_new[1:]
    death = crossed & ~prev
    kills = d.take(pa.array(order[death])).select(
        ["match", "round", "tick", "seconds", "att_pid", "vic_pid", "att_side", "vic_side",
         "is_bomb_planted", "wp_type", "att_rank", "vic_rank",
         "att_pos_x", "att_pos_y", "vic_pos_x", "vic_pos_y"])
    kills = kills.sort_by([("match", "ascending"), ("round", "ascending"), ("tick", "ascending")])
    return rounds, kills


def _side_alive(match, rnd, vic_is_atk, start_atk=5, start_def=5):
    """(attackers, defenders) alive after each kill; rows sorted by round, then time."""
    new = _round_starts(match, rnd)
    gid = np.cumsum(new) - 1

    def grp_cumsum(x):
        c = np.cumsum(x)
        return c - (c - x)[new][gid]

    va = np.asarray(vic_is_atk, bool).astype(np.int32)
    sa = np.broadcast_to(np.asarray(start_atk, np.int32), len(rnd))
    sd = np.broadcast_to(np.asarray(start_def, np.int32), len(rnd))
    return (sa - grp_cumsum(va)).astype(np.int8), (sd - grp_cumsum(1 - va)).astype(np.int8)


STATE_SCHEMA = pa.schema([
    ("source", pa.string()), ("match", pa.string()), ("round", pa.int16()), ("event", pa.string()),
    ("t_s", pa.float32()), ("atk_alive", pa.int8()), ("def_alive", pa.int8()),
    ("planted", pa.bool_()), ("since_plant_s", pa.float32()), ("atk_load", pa.float32()),
    ("def_load", pa.float32()), ("skill", pa.int8()), ("atk_win", pa.bool_()),
    ("deciding", pa.bool_())])


def state_table(source, match, rnd, event, t_s, atk, dfn, planted, since, atk_load, def_load,
                skill, atk_win) -> pa.Table:
    """Rows of the side-neutral coarse-state schema (`STATE_SCHEMA`)."""
    n = len(rnd)
    a = _np(atk).astype(np.int8)
    d = _np(dfn).astype(np.int8)
    planted = _np(planted).astype(bool)
    sk = (np.full(n, skill, np.float32) if np.isscalar(skill)
          else np.asarray(pa.array(_np(skill)).cast(pa.float32()).to_numpy(zero_copy_only=False),
                          np.float32))
    bad_sk = np.isnan(sk) | (sk <= 0)
    cols = {
        "source": pa.array(np.full(n, source, object), pa.string()),
        "match": pa.array(_np(match), pa.string()),
        "round": pa.array(_np(rnd).astype(np.int16)),
        "event": pa.array(np.full(n, event, object), pa.string()),
        "t_s": pa.array(_np(t_s, np.float32)) if t_s is not None else pa.nulls(n, pa.float32()),
        "atk_alive": pa.array(a), "def_alive": pa.array(d), "planted": pa.array(planted),
        "since_plant_s": (pa.array(_np(since, np.float32),
                                   mask=~planted | ~np.isfinite(_np(since, np.float32)))
                          if since is not None
                          else pa.nulls(n, pa.float32())),
        "atk_load": pa.array(_np(atk_load, np.float64), pa.float64()).cast(pa.float32()),
        "def_load": pa.array(_np(def_load, np.float64), pa.float64()).cast(pa.float32()),
        "skill": pa.array(np.rint(np.where(bad_sk, 0, sk)).astype(np.int8), mask=bad_sk),
        "atk_win": pa.array(_np(atk_win).astype(bool)),
        "deciding": pa.array((d <= 0) | ((a <= 0) & ~planted)),
    }
    return pa.table(cols, schema=STATE_SCHEMA)


def mm_states(rounds: pa.Table, kills: pa.Table) -> pa.Table:
    """Coarse-state rows for the matchmaking source: start and each kill, no clock.

    Each side starts with five; the CSV carries demo time, not round time, so
    `t_s` and `since_plant_s` stay null."""
    rk = rounds.select(["match", "round", "winner_side", "ct_eq_val", "t_eq_val", "avg_match_rank"])
    kj = kills.join(rk, keys=["match", "round"], join_type="inner").sort_by(
        [("match", "ascending"), ("round", "ascending"), ("tick", "ascending")])
    km, kr = _np(kj["match"]), _np(kj["round"])
    a, d = _side_alive(km, kr, _np(kj["vic_side"]) == "Terrorist")
    kill = state_table("kaggle_mm", km, kr, "kill", None, a, d, _np(kj["is_bomb_planted"]), None,
                       kj["t_eq_val"], kj["ct_eq_val"], kj["avg_match_rank"],
                       _np(kj["winner_side"]) == "Terrorist")
    n = rounds.num_rows
    start = state_table("kaggle_mm", rounds["match"], rounds["round"], "start", np.zeros(n),
                        np.full(n, 5), np.full(n, 5), np.zeros(n, bool), None,
                        rounds["t_eq_val"], rounds["ct_eq_val"], rounds["avg_match_rank"],
                        _np(rounds["winner_side"]) == "Terrorist")
    return pa.concat_tables([start, kill])


# ---------------------------------------------------------------- ESTA

def esta_list() -> list[dict]:
    """The online demos' names, sizes and URLs, sorted by name."""
    req = urllib.request.Request(ESTA_LIST, headers={"User-Agent": "reticle-cs-data"})
    with urllib.request.urlopen(req, timeout=60) as r:
        items = json.loads(r.read())
    return sorted(({"name": i["name"], "size": i["size"], "url": i["download_url"]}
                   for i in items if i["name"].endswith(".json.xz")), key=lambda i: i["name"])


def _clock_s(s):
    try:
        mm, ss = str(s).split(":")
        return int(mm) * 60 + int(ss)
    except (ValueError, AttributeError):
        return None


_KILL_FIELDS = (("tick", "tick"), ("awpy_seconds", "seconds"), ("att_sid", "attackerSteamID"),
                ("vic_sid", "victimSteamID"), ("ass_sid", "assisterSteamID"),
                ("traded_sid", "playerTradedSteamID"), ("att_side", "attackerSide"),
                ("vic_side", "victimSide"), ("att_x", "attackerX"), ("att_y", "attackerY"),
                ("vic_x", "victimX"), ("vic_y", "victimY"), ("weapon", "weapon"),
                ("weapon_class", "weaponClass"), ("is_trade", "isTrade"),
                ("is_first", "isFirstKill"), ("is_headshot", "isHeadshot"),
                ("is_teamkill", "isTeamkill"), ("is_suicide", "isSuicide"),
                ("distance", "distance"))


def esta_parse(d: dict, salt: int) -> dict:
    """Round, kill and 2 Hz frame tables of one awpy-1.3.1 demo dict, plus its checks.

    Frames after a round's endTick (awpy keeps frames to endOfficialTick) are dropped.
    awpy's `seconds` restart at the plant, so it is kept as `awpy_seconds` and
    `t_s` counts from freeze end by tick: (tick - freezeTimeEndTick) / tickRate."""
    demo, tick_rate = d["demoId"], float(d["tickRate"])
    rounds_raw = [g for g in d["gameRounds"] if not g.get("isWarmup")]
    R = {k: [] for k in ("round", "start_tick", "freeze_end_tick", "end_tick", "plant_tick",
                         "plant_s", "winner_side", "end_reason", "ct_eq_val", "t_eq_val",
                         "ct_buy", "t_buy", "ct_score", "t_score", "ct_start", "t_start")}
    K = {k: [] for k, _ in _KILL_FIELDS}
    K["round"], K["t_s"] = [], []
    F = {k: [] for k in ("round", "tick", "t_s", "awpy_seconds", "clock_s", "ct_alive", "t_alive",
                         "planted", "bombsite", "ct_eq", "t_eq")}
    for g in rounds_raw:
        rn, fe, pt = g["roundNum"], g["freezeTimeEndTick"], g.get("bombPlantTick")
        fr = [f for f in g.get("frames") or [] if f["tick"] <= g["endTick"]]
        for k, v in (("round", rn), ("start_tick", g["startTick"]), ("freeze_end_tick", fe),
                     ("end_tick", g["endTick"]), ("plant_tick", pt),
                     ("plant_s", None if pt is None else (pt - fe) / tick_rate),
                     ("winner_side", g["winningSide"]), ("end_reason", g["roundEndReason"]),
                     ("ct_eq_val", g.get("ctFreezeTimeEndEqVal")),
                     ("t_eq_val", g.get("tFreezeTimeEndEqVal")), ("ct_buy", g.get("ctBuyType")),
                     ("t_buy", g.get("tBuyType")), ("ct_score", g["ctScore"]),
                     ("t_score", g["tScore"]),
                     ("ct_start", fr[0]["ct"]["alivePlayers"] if fr else 5),
                     ("t_start", fr[0]["t"]["alivePlayers"] if fr else 5)):
            R[k].append(v)
        for k in g.get("kills") or []:
            K["round"].append(rn)
            K["t_s"].append((k["tick"] - fe) / tick_rate)
            for col, src in _KILL_FIELDS:
                K[col].append(k.get(src))
        for f in fr:
            for k, v in (("round", rn), ("tick", f["tick"]), ("t_s", (f["tick"] - fe) / tick_rate),
                         ("awpy_seconds", f["seconds"]),
                         ("clock_s", _clock_s(f.get("clockTime"))),
                         ("ct_alive", f["ct"]["alivePlayers"]), ("t_alive", f["t"]["alivePlayers"]),
                         ("planted", bool(f.get("bombPlanted"))), ("bombsite", f.get("bombsite") or None),
                         ("ct_eq", f["ct"].get("teamEqVal")), ("t_eq", f["t"].get("teamEqVal"))):
                F[k].append(v)
    rounds = pa.table(R)
    rounds = pa.table({"match": pa.array([demo] * rounds.num_rows, pa.string()),
                       "map": pa.array([d["mapName"]] * rounds.num_rows, pa.string()),
                       **{c: rounds[c] for c in rounds.column_names}})
    for c in ("ct_start", "t_start"):
        rounds = rounds.set_column(rounds.schema.get_field_index(c), c, rounds[c].cast(pa.int8()))
    rounds = rounds.set_column(rounds.schema.get_field_index("round"), "round",
                               rounds["round"].cast(pa.int32()))
    for c in ("plant_tick", "plant_s"):
        rounds = rounds.set_column(rounds.schema.get_field_index(c), c,
                                   rounds[c].cast(pa.int32() if c == "plant_tick" else pa.float32()))
    kcols = {}
    for c, vals in K.items():
        if c.endswith("_sid"):
            ids = np.array([int(x or 0) for x in vals], np.uint64).astype(np.int64)
            kcols[c.replace("_sid", "_pid")] = pa.array(pseudonym(ids, salt), pa.int64())
        elif c.startswith("is_"):
            kcols[c] = pa.array([bool(x) for x in vals], pa.bool_())
        elif c in ("att_side", "vic_side", "weapon", "weapon_class"):
            kcols[c] = pa.array(vals, pa.string())
        elif c in ("round", "tick"):
            kcols[c] = pa.array(vals, pa.int32())
        else:
            kcols[c] = pa.array(vals, pa.float32())
    kills = pa.table({"match": pa.array([demo] * len(K["round"]), pa.string()), **kcols})
    ftypes = {"round": pa.int32(), "tick": pa.int32(), "t_s": pa.float32(),
              "awpy_seconds": pa.float32(),
              "clock_s": pa.int16(), "ct_alive": pa.int8(), "t_alive": pa.int8(),
              "planted": pa.bool_(), "bombsite": pa.string(), "ct_eq": pa.float32(),
              "t_eq": pa.float32()}
    frames = pa.table({"match": pa.array([demo] * len(F["round"]), pa.string()),
                       **{c: pa.array(v, ftypes[c]) for c, v in F.items()}})
    last = rounds_raw[-1] if rounds_raw else {}
    scored = (last.get("endCTScore") or 0) + (last.get("endTScore") or 0)
    tk, fr_r = np.asarray(F["tick"]), np.asarray(F["round"])
    same = fr_r[1:] == fr_r[:-1]
    gaps = np.diff(tk)[same]
    return {"rounds": rounds, "kills": kills, "frames": frames,
            "check": {"demo": demo, "map": d["mapName"], "rounds": len(rounds_raw),
                      "scored": scored, "rounds_ok": len(rounds_raw) == scored,
                      "tick_rate": tick_rate, "frames": len(F["round"]), "kills": len(K["round"]),
                      "median_gap_s": float(np.median(gaps) / tick_rate) if len(gaps) else None}}


def esta_states(rounds: pa.Table, kills: pa.Table, frames: pa.Table) -> pa.Table:
    """Coarse-state rows for ESTA: freeze end, each kill (suicides included) and each frame."""
    rk = rounds.select(["match", "round", "winner_side", "ct_eq_val", "t_eq_val", "plant_s",
                        "ct_start", "t_start"]).cast(pa.schema([
                            ("match", pa.string()), ("round", pa.int32()), ("winner_side", pa.string()),
                            ("ct_eq_val", pa.float64()), ("t_eq_val", pa.float64()),
                            ("plant_s", pa.float32()), ("ct_start", pa.int8()), ("t_start", pa.int8())]))
    n = rounds.num_rows
    out = [state_table("esta", rounds["match"], rounds["round"], "start", np.zeros(n),
                       rounds["t_start"], rounds["ct_start"], np.zeros(n, bool), None,
                       rounds["t_eq_val"], rounds["ct_eq_val"], PRO_SKILL,
                       _np(rounds["winner_side"]) == "T")]
    sort = [("match", "ascending"), ("round", "ascending"), ("tick", "ascending")]
    kj = kills.join(rk, keys=["match", "round"], join_type="inner").sort_by(sort)
    if kj.num_rows:
        km, kr = _np(kj["match"]), _np(kj["round"])
        a, d = _side_alive(km, kr, _np(kj["vic_side"]) == "T", _np(kj["t_start"]), _np(kj["ct_start"]))
        sec = _np(kj["t_s"], np.float32)
        ps = _np(pc.fill_null(kj["plant_s"], np.inf), np.float32)
        planted = ps <= sec
        out.append(state_table("esta", km, kr, "kill", sec, a, d, planted, sec - ps,
                               kj["t_eq_val"], kj["ct_eq_val"], PRO_SKILL,
                               _np(kj["winner_side"]) == "T"))
    fj = frames.join(rk, keys=["match", "round"], join_type="inner").sort_by(sort)
    if fj.num_rows:
        sec = _np(fj["t_s"], np.float32)
        ps = _np(pc.fill_null(fj["plant_s"], np.nan), np.float32)
        out.append(state_table("esta", fj["match"], fj["round"], "tick", sec, fj["t_alive"],
                               fj["ct_alive"], _np(fj["planted"]), sec - ps,
                               fj["t_eq_val"], fj["ct_eq_val"], PRO_SKILL,
                               _np(fj["winner_side"]) == "T"))
    return pa.concat_tables(out)


def _fetch(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "reticle-cs-data"})
    n = 0
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
            n += len(b)
    return n


def run_esta(n: int, salt: int, out_dir: Path = CS / "esta") -> dict:
    """Download, parse, check and delete `n` ESTA online demos; write the tables.

    Resumable: `checks.jsonl` lists each parsed demo; its per-demo parts stay
    under `parts/` until all are parsed, then merge into one file per table."""
    t0 = time.time()
    parts = out_dir / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    listing = esta_list()[:n]
    done_path = out_dir / "checks.jsonl"
    done = {}
    if done_path.exists():
        for line in done_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                c = json.loads(line)
                done[c["file"]] = c
    checks, peak = [], 0
    for i, item in enumerate(listing):
        if item["name"] in done:
            checks.append(done[item["name"]])
            continue
        peak = max(peak, check_budget(item["size"]) + item["size"])
        xz = out_dir / item["name"]
        got = _fetch(item["url"], xz)
        if got != item["size"]:
            xz.unlink()
            raise RuntimeError(f"{item['name']}: {got} B of {item['size']}")
        with lzma.open(xz) as fh:
            p = esta_parse(json.loads(fh.read()), salt)
        stem = item["name"].split(".")[0]
        for t in ("rounds", "kills", "frames"):
            pq.write_table(p[t], parts / f"{t}__{stem}.parquet", **ZSTD)
        c = dict(p["check"], file=item["name"], xz_bytes=got)
        with open(done_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(c) + "\n")
        xz.unlink()
        checks.append(c)
        print(f"esta {i + 1}/{len(listing)} {stem[:8]} rounds={c['rounds']} ok={c['rounds_ok']}",
              flush=True)
    for t in ("rounds", "kills", "frames"):
        merged = pq.read_table(out_dir / f"{t}.parquet") if (out_dir / f"{t}.parquet").exists() else None
        tabs = []
        for c in checks:
            part = parts / f"{t}__{c['file'].split('.')[0]}.parquet"
            if part.exists():
                tabs.append(pq.read_table(part))
            elif merged is not None:  # parsed by an earlier run and already merged
                tabs.append(merged.filter(pc.equal(merged["match"], c["demo"])))
            else:
                raise RuntimeError(f"{c['file']} is listed in checks.jsonl but has no table")
        pq.write_table(pa.concat_tables(tabs, promote_options="permissive"),
                       out_dir / f"{t}.parquet", **ZSTD)
    for p_ in parts.glob("*.parquet"):
        p_.unlink()
    parts.rmdir()
    rounds, kills, frames = (pq.read_table(out_dir / f"{t}.parquet") for t in ("rounds", "kills", "frames"))
    pq.write_table(esta_states(rounds, kills, frames), out_dir / "states.parquet", **ZSTD)
    raw = sum(c["xz_bytes"] for c in checks)
    write_source(out_dir, {
        "source": "ESTA, pnxenopoulos/esta on GitHub, data/online/", "listing": ESTA_LIST,
        "licence": ESTA_LICENCE, "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "attribution": "Xenopoulos and Silva, ESTA: An Esports Trajectory and Action Dataset (2022)",
        "retrieved": _dt.date.today().isoformat(), "demos": len(checks),
        "selection": f"first {n} of the online listing sorted by file name",
        "raw_xz_bytes": raw, "raw_deleted": True, "pseudonym": "keyed splitmix64 of steam id",
        "names_dropped": True, "producer": f"prototypes/cs_data.py {VERSION}"})
    out = {"demos": len(checks), "raw_xz_bytes": raw, "peak_tree_bytes": peak,
           "seconds": round(time.time() - t0, 1)}
    with open(out_dir / "run.jsonl", "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(out) + "\n")
    return out


# ---------------------------------------------------------------- Kaggle run

def run_kaggle(salt: int, out_dir: Path = CS / "kaggle_mm") -> dict:
    """Download the matchmaking CSV, convert, check rows, write tables, delete the raw file."""
    t0 = time.time()
    raw_dir = out_dir / "raw"
    existing = sorted(raw_dir.glob("mm_master_demos.*")) if raw_dir.exists() else []
    if existing:
        raw = {"path": existing[0], "bytes": existing[0].stat().st_size,
               "zip": zipfile.is_zipfile(existing[0]), "seconds": None}
    else:
        token = env_value(Path.home() / "reticle" / ".env", "KAGGLE_API_TOKEN")
        if not token:
            raise RuntimeError("KAGGLE_API_TOKEN not found in .env")
        raw = kaggle_download(raw_dir / KAGGLE_FILE, token)
    raw_path = Path(raw["path"])
    csv_bytes = (zipfile.ZipFile(raw_path).infolist()[0].file_size if raw["zip"]
                 else raw_path.stat().st_size)
    conv = mm_convert(raw_path, out_dir, salt)
    if conv["parquet_rows"] != conv["csv_rows"]:
        raise RuntimeError(f"row mismatch {conv}; raw file kept at {raw_path}")
    rounds, kills = mm_tables(pq.read_table(out_dir / "damage.parquet"))
    pq.write_table(rounds, out_dir / "rounds.parquet", **ZSTD)
    pq.write_table(kills, out_dir / "kills.parquet", **ZSTD)
    pq.write_table(mm_states(rounds, kills), out_dir / "states.parquet", **ZSTD)
    raw_path.unlink()
    raw_dir.rmdir()
    write_source(out_dir, {
        "source": f"Kaggle dataset {KAGGLE_OWNER}/{KAGGLE_SLUG} "
                  f"('CS:GO Competitive Matchmaking Data'), file {KAGGLE_FILE}",
        "url": f"https://www.kaggle.com/datasets/{KAGGLE_OWNER}/{KAGGLE_SLUG}",
        "licence": KAGGLE_LICENCE, "licence_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "use": "non-commercial analytics compared with the player's games; pseudonymised; never published",
        "retrieved": _dt.date.today().isoformat(), "raw_download_bytes": raw["bytes"],
        "raw_was_zip": bool(raw["zip"]), "csv_bytes": csv_bytes, "csv_rows": conv["csv_rows"],
        "parquet_rows": conv["parquet_rows"], "raw_deleted": True, "columns_kept": MM_COLUMNS,
        "pseudonym": "keyed splitmix64 of steam id",
        "clock": "the CSV's seconds are demo time, not round time; states carry no t_s",
        "producer": f"prototypes/cs_data.py {VERSION}"})
    out = {"raw_download_bytes": raw["bytes"], "download_s": raw["seconds"], "csv_bytes": csv_bytes,
           **conv, "rounds": rounds.num_rows, "kills": kills.num_rows,
           "seconds": round(time.time() - t0, 1)}
    (out_dir / "run.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------- first look

STATES = ((5, 5), (4, 4), (3, 3), (2, 2), (1, 1), (4, 5), (5, 4))
# avg_match_rank spans 7 (Gold Nova I) to 16 (Legendary Eagle Master) in this file.
RANK_BANDS = (("gold_nova", 7, 10), ("mg_dmg", 11, 14), ("le_lem", 15, 16))


def wp_table(states: pa.Table, event: str = "kill") -> pa.Table:
    """Attackers' win share by (atk_alive, def_alive, planted) over `event` rows.

    Kill rows before the round's first kill are not states; deciding rows are kept
    (they are the states the kill left)."""
    s = states.filter(pc.equal(states["event"], event))
    a = _np(s["atk_alive"]).astype(np.int64)
    d = _np(s["def_alive"]).astype(np.int64)
    p = _np(s["planted"]).astype(np.int64)
    w = _np(s["atk_win"]).astype(np.float64)
    ok = (a >= 0) & (d >= 0) & (a <= 5) & (d <= 5)
    key = (a * 6 + d) * 2 + p
    n = np.bincount(key[ok], minlength=72)
    k = np.bincount(key[ok], weights=w[ok], minlength=72)
    idx = np.flatnonzero(n)
    return pa.table({"atk_alive": pa.array((idx // 2) // 6, pa.int8()),
                     "def_alive": pa.array((idx // 2) % 6, pa.int8()),
                     "planted": pa.array((idx % 2).astype(bool)),
                     "n": pa.array(n[idx]), "atk_win": pa.array(k[idx] / n[idx])})


def wp_values(states: pa.Table, event: str = "kill") -> dict:
    """Named cells of the WP table: defender (CT) win share and n, as the scout named them."""
    t = wp_table(states, event)
    cell = {(int(a), int(d), bool(p)): (int(n), float(w)) for a, d, p, n, w in zip(
        *(t[c].to_pylist() for c in ("atk_alive", "def_alive", "planted", "n", "atk_win")))}
    out = {}
    for atk, dfn in STATES:
        for pl, tag in ((False, "noplant"), (True, "plant")):
            n, w = cell.get((atk, dfn, pl), (0, float("nan")))
            out[f"def_win_{atk}v{dfn}_{tag}"] = round(1 - w, 4) if n else None
            out[f"n_{atk}v{dfn}_{tag}"] = n
    return out


def first_kill(states: pa.Table) -> dict:
    """Share of rounds the side left with everyone wins, after the first kill, before a plant."""
    s = states.filter(pc.equal(states["event"], "kill"))
    m, r = _np(s["match"]), _np(s["round"])
    first = _round_starts(m, r)
    a, d = _np(s["atk_alive"])[first], _np(s["def_alive"])[first]
    pl = _np(s["planted"])[first].astype(bool)
    w = _np(s["atk_win"])[first].astype(bool)
    keep = ~pl & (a != d)
    side_full_win = np.where(a[keep] > d[keep], w[keep], ~w[keep])
    return {"first_kill_rounds": int(keep.sum()),
            "first_kill_full_side_win": round(float(side_full_win.mean()), 4) if keep.any() else None}


def rank_spread(rounds: pa.Table) -> dict:
    """Rounds and matches per rounded avg_match_rank (0 = unranked or unknown)."""
    rk = np.rint(np.nan_to_num(_np(rounds["avg_match_rank"], np.float64), nan=0)).astype(np.int64)
    rk = np.clip(rk, 0, 18)
    n = np.bincount(rk, minlength=19)
    m = _np(rounds["match"])
    _, first = np.unique(m, return_index=True)
    nm = np.bincount(rk[first], minlength=19)
    out = {f"rounds_rank_{i}": int(n[i]) for i in range(19)}
    out.update({f"matches_rank_{i}": int(nm[i]) for i in range(19)})
    out["rounds"] = int(n.sum())
    out["matches"] = int(len(first))
    out["share_rank_below_13"] = round(float(n[1:13].sum() / max(n[1:].sum(), 1)), 4)
    out["share_rank_17_up"] = round(float(n[17:].sum() / max(n[1:].sum(), 1)), 4)
    return out


def _skill_band(states: pa.Table, lo: int, hi: int) -> pa.Table:
    sk = states["skill"]
    return states.filter(pc.and_(pc.greater_equal(sk, lo), pc.less_equal(sk, hi)))


def frame_kill_agreement(rounds: pa.Table, kills: pa.Table, frames: pa.Table) -> dict:
    """Share of ESTA frames whose alive counts equal the round's start counts less the
    kills logged at or before the frame's tick: the kill log and frames cross-checked."""
    matches = np.unique(_np(rounds["match"]).astype(str))

    def key(t, tick):
        c = np.searchsorted(matches, _np(t["match"]).astype(str)).astype(np.int64)
        return (c * 1000 + _np(t["round"]).astype(np.int64)) * 10_000_000 + tick

    kk = key(kills, _np(kills["tick"]).astype(np.int64))
    o = np.argsort(kk, kind="stable")
    kk = kk[o]
    vic_t = (_np(kills["vic_side"]) == "T")[o].astype(np.int64)
    cum_t = np.concatenate([[0], np.cumsum(vic_t)])
    cum_ct = np.concatenate([[0], np.cumsum(1 - vic_t)])
    fs = frames.join(rounds.select(["match", "round", "ct_start", "t_start"]),
                     keys=["match", "round"], join_type="inner")
    hi = np.searchsorted(kk, key(fs, _np(fs["tick"]).astype(np.int64)), "right")
    lo = np.searchsorted(kk, key(fs, np.zeros(fs.num_rows, np.int64)), "left")
    exp_t = _np(fs["t_start"]).astype(np.int64) - (cum_t[hi] - cum_t[lo])
    exp_ct = _np(fs["ct_start"]).astype(np.int64) - (cum_ct[hi] - cum_ct[lo])
    agree = (exp_t == _np(fs["t_alive"])) & (exp_ct == _np(fs["ct_alive"]))
    return {"frames": int(len(agree)), "frame_kill_alive_agree": round(float(agree.mean()), 4)}


def _dir_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def report(record: bool = False) -> list[tuple[str, dict]]:
    """Sizes, row counts, rank spread and first-look WP tables per source."""
    deps = {"version": VERSION, "pyarrow": pa.__version__, "numpy": np.__version__}
    series = []
    km = CS / "kaggle_mm"
    if (km / "states.parquet").exists():
        src = json.loads((km / "SOURCE.json").read_text(encoding="utf-8"))
        run = json.loads((km / "run.json").read_text(encoding="utf-8")) if (km / "run.json").exists() else {}
        rounds = pq.read_table(km / "rounds.parquet")
        kills = pq.read_table(km / "kills.parquet")
        states = pq.read_table(km / "states.parquet")
        kst = states.filter(pc.equal(states["event"], "kill"))
        # A rebuilt side at zero before a plant must lose; a defender wipe must lose.
        a, d = _np(kst["atk_alive"]), _np(kst["def_alive"])
        pl, w = _np(kst["planted"]).astype(bool), _np(kst["atk_win"]).astype(bool)
        last = np.zeros(kst.num_rows, bool)
        if kst.num_rows:
            last[:-1] = _round_starts(_np(kst["match"]), _np(kst["round"]))[1:]
            last[-1] = True
        wiped_loser = np.where(w, d <= 0, a <= 0)
        sizes = {"raw_download_bytes": src["raw_download_bytes"], "csv_bytes": src["csv_bytes"],
                 "kept_bytes": _dir_bytes(km), "damage_parquet_bytes": (km / "damage.parquet").stat().st_size,
                 "csv_rows": src["csv_rows"], "parquet_rows": src["parquet_rows"],
                 "rounds": rounds.num_rows, "matches": len(pc.unique(rounds["match"])),
                 "kills": kills.num_rows, "state_rows": states.num_rows,
                 "winner_conflict_rounds": int(pc.sum(rounds["winner_conflict"]).as_py() or 0),
                 "negative_alive_rows": int(((a < 0) | (d < 0)).sum()),
                 "impossible_rows": int((((d <= 0) & ~w) | ((a <= 0) & ~pl & w)).sum()),
                 "round_last_kill_loser_wiped_share": round(float(wiped_loser[last].mean()), 4) if last.any() else None,
                 "convert_s": run.get("seconds"), "download_s": run.get("download_s")}
        ctl = [{"name": "parquet rows equal CSV rows", "observed": src["parquet_rows"],
                "expected": src["csv_rows"], "tol": 0}]
        series.append(("kaggle_mm", sizes, ctl, {"source": src["source"], "licence": src["licence"]}))
        series.append(("kaggle_mm_ranks", rank_spread(rounds), [], {"rank": "avg_match_rank rounded"}))
        series.append(("kaggle_mm_wp", {**wp_values(states), **first_kill(states)}, [],
                       {"event": "kill", "states": "after each rebuilt death"}))
        for band, lo, hi in RANK_BANDS:
            b = _skill_band(states, lo, hi)
            series.append((f"kaggle_mm_wp_{band}", {
                "rounds": int(pc.sum(pc.equal(b["event"], "start")).as_py() or 0),
                **{k: v for k, v in wp_values(b).items() if any(s in k for s in ("4v4", "2v2", "1v1"))},
                **first_kill(b)}, [], {"event": "kill", "ranks": f"{lo}-{hi}"}))
    es = CS / "esta"
    if (es / "states.parquet").exists():
        src = json.loads((es / "SOURCE.json").read_text(encoding="utf-8"))
        checks = [json.loads(x) for x in (es / "checks.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        rounds = pq.read_table(es / "rounds.parquet")
        kills = pq.read_table(es / "kills.parquet")
        frames = pq.read_table(es / "frames.parquet")
        states = pq.read_table(es / "states.parquet")
        gaps = [c["median_gap_s"] for c in checks if c.get("median_gap_s") is not None]
        sizes = {"demos": len(checks), "raw_xz_bytes": src["raw_xz_bytes"], "kept_bytes": _dir_bytes(es),
                 "rounds": rounds.num_rows, "kills": kills.num_rows, "frames": frames.num_rows,
                 "state_rows": states.num_rows,
                 "demos_rounds_ok": sum(bool(c["rounds_ok"]) for c in checks),
                 "median_frame_gap_s": round(float(np.median(gaps)), 4) if gaps else None,
                 "trades": int(pc.sum(kills["is_trade"]).as_py() or 0),
                 "maps": len(pc.unique(rounds["map"])),
                 "run_s": round(sum(json.loads(x)["seconds"] for x in (es / "run.jsonl").read_text(
                     encoding="utf-8").splitlines() if x.strip()), 1) if (es / "run.jsonl").exists() else None}
        ctl = [{"name": "rounds parsed equal final score sum", "observed": sizes["demos_rounds_ok"],
                "expected": len(checks), "tol": 0}]
        sizes.update(frame_kill_agreement(rounds, kills, frames))
        series.append(("esta", sizes, ctl, {"source": src["source"], "licence": src["licence"]}))
        series.append(("esta_wp", {**wp_values(states), **first_kill(states)}, [],
                       {"event": "kill", "states": "after each kill"}))
        series.append(("esta_wp_ticks", wp_values(states, "tick"), [],
                       {"event": "tick", "states": "2 Hz frames, round live"}))
    tb = tree_bytes()
    series.append(("tree", {"external_cs_bytes": tb, "budget_bytes": BUDGET_BYTES}, [
        {"name": "external/cs under budget", "observed": tb < BUDGET_BYTES, "expected": True, "ok": tb < BUDGET_BYTES}],
        {"path": "reticle-store/external/cs"}))
    for part, values, ctl, ctx in series:
        print(part, json.dumps(values))
        if record:
            metrics.record("cs_data", part=part, values=values, deps=deps, context=ctx,
                           controls=ctl, note="cs-data-20261004; prototypes/cs_data.py")
    return [(p, v) for p, v, _c, _x in series]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("kaggle", help="download and convert mm_master_demos.csv")
    e = sub.add_parser("esta", help="download and parse ESTA online demos")
    e.add_argument("--n", type=int, default=100)
    t = sub.add_parser("tables", help="sizes, rank spread and first-look WP tables")
    t.add_argument("--record", action="store_true", help="append cs_data metrics rows")
    args = ap.parse_args(argv)
    below_normal()
    if args.cmd == "kaggle":
        print(json.dumps(run_kaggle(load_salt())))
    elif args.cmd == "esta":
        print(json.dumps(run_esta(args.n, load_salt())))
    else:
        report(args.record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
