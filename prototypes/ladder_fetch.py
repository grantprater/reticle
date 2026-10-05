r"""Fetch a small, polite, rank-stratified sample of ranked VALORANT matches.

    .\.venv\Scripts\python.exe prototypes\ladder_fetch.py status
    .\.venv\Scripts\python.exe prototypes\ladder_fetch.py seed --owners
    .\.venv\Scripts\python.exe prototypes\ladder_fetch.py seed --leaderboard --pages 1
    .\.venv\Scripts\python.exe prototypes\ladder_fetch.py dry-run
    .\.venv\Scripts\python.exe prototypes\ladder_fetch.py crawl --max-matches N --max-requests R
    .\.venv\Scripts\python.exe prototypes\ladder_fetch.py parse
    .\.venv\Scripts\python.exe prototypes\ladder_fetch.py measure-riot [--out DIR]
    .\.venv\Scripts\python.exe prototypes\ladder_fetch.py measure-v4 [--record]
    .\.venv\Scripts\python.exe prototypes\ladder_fetch.py project

`docs/LADDER_SAMPLE.md` holds the source, its terms, the politeness settings,
the storage, the schema, the strata and the use.

Use
---
The records FIT win-probability and coaching baselines and priors. They never
feed a reader, a reader's threshold or anything shown during play. A match
that evaluates a fitted model is held out of its fit: the parsed `matches`
table marks the player's captured matches (`captured`) and a fixed hash split
(`holdout`).

Source
------
HenrikDev's unofficial VALORANT API (`https://api.henrikdev.xyz`), v4. One
request to `/valorant/v4/by-puuid/matches/{region}/{platform}/{puuid}`
`?mode=competitive&size=N` returns that player's last N competitive matches
with full rounds, kills and positions, so a snowball costs about one request
per visited player, not one per match. `/valorant/v4/match/{region}/{id}`
fetches one match; `/valorant/v3/leaderboard/{region}/{platform}` seeds the
top tiers.

Politeness, a requirement
-------------------------
From v4.0.0 the key's quota counts units, not calls: the call plus every Riot
request HenrikDev makes in the background to build the reply; a cached reply
costs the call alone (docs.henrikdev.xyz/general/rate-limiting.md). A list of
ten uncached matches can cost a dozen units. So:

- the limiter reads `X-RateLimit-Limit`, `X-RateLimit-Remaining` and
  `X-RateLimit-Reset` on every response and sends a call only when the
  remaining quota, less the call's predicted cost, stays at or above
  `fraction` (default 0.5) of the limit; its own ledger also keeps the units
  spent in any 60 s within the limit less that reserve: on the Basic key (30
  a minute), 15 units a minute; and never more than one call per 4 s;
- a call's cost is the drop in `Remaining` since the previous reply in the
  same window (or `Limit - Remaining` in a fresh one); the largest cost per
  match measured so far predicts the next call; a call whose cost the headers
  do not show is charged its prediction;
- a daily and a total cap on calls and on units, and a match cap, checked
  before each call; the caps are command-line defaults, and only the counts
  persist, in the state file;
- `Retry-After` (or `X-RateLimit-Reset`) honoured on 429; 429, 5xx and network
  errors back off exponentially (base 8 s, doubling, at most 600 s) for at
  most four retries; three failed requests in a row stop the run;
- a run that starts within a minute of the last call waits out that minute;
- the state file resumes a run; a player is listed once; a stored match is
  never requested again by id, and a list reply's already-stored matches are
  counted and not parsed twice;
- `mode=competitive` on every list, and the parser keeps
  `metadata.queue.id == "competitive"` only, inside a season and date window.

Secrets and identities
----------------------
The API key comes from the environment (`HENRIKDEV_API_KEY` or
`HENRIK_API_KEY`), the store file `<store>/external/ladder/henrikdev/api_key`,
or the repository's git-ignored `.env` (`HENRIK_API_KEY=...`; a worktree reads
the main checkout's); it goes only into the `Authorization` header and is never
printed, logged or stored elsewhere.
Account ids, names, tags and match ids stay in the store: the console prints
counts only. The parsed tables replace every PUUID with a keyed BLAKE2b
pseudonym (salt in the store) and drop names and tags.

Store layout (`<store>/external/ladder/henrikdev/v4/`)
------------------------------------------------------
- `raw/<seq>-<kind>.json.gz`: each 200 response body, gzip level 9;
- `manifest.jsonl`: one row per request (endpoint, fetched_at, status, bytes,
  gz_bytes, sha256, the match ids a body holds, the file, the rate-limit
  headers, and the call's unit cost with its basis); append-only;
- `state.json`: call and unit counts, window, frontier, visited players,
  stored matches with their stratum, history probes; rewritten atomically;
- `parsed/<PARSER_VERSION>/*.parquet`: the tables, rebuilt from raw.

Riot schema
-----------
HenrikDev reshapes Riot's match-details record. `riot_to_v4` carries a stored
Riot record (`<store>/external/riot/`, read through
`riot_ground_truth.riot_records`) into the v4 shape, so the 22 captured
matches parse through the same code; `measure-v4` measures bytes and quota
units per match on the stored v4 replies. The differences it absorbs are in
`docs/LADDER_SAMPLE.md`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
if sys.platform == "win32":  # Below Normal priority, as every script here
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(
            ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass

import pyarrow as pa  # noqa: E402
import pyarrow.compute as pc  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

VERSION = "ladder-fetch-0.2.0"
PARSER_VERSION = "ladder-parse-0.1.0"
HOST = "api.henrikdev.xyz"
BASE = f"https://{HOST}"
API_VERSION = "v4"
USER_AGENT = f"reticle-ladder-fetch/{VERSION} (personal research sample)"
STORE = Path.home() / "reticle-store"
KEY_ENV = "HENRIKDEV_API_KEY"
KEY_ENV_ALT = "HENRIK_API_KEY"   # the name the player used in .env
#: Documented per-minute limits by key tier (README of Henrik-3/
#: unofficial-valorant-api: "Basic Key: 30req/min", "Enhanced Key: 90req/min").
DOC_LIMIT_PER_MIN = {"basic": 30, "enhanced": 90}
#: Rank strata, lowest first, matched on the first word of the tier name the
#: API returns ("Gold 2" -> Gold). Unranked and unknown names stay None.
STRATA = ("Iron", "Bronze", "Silver", "Gold", "Platinum", "Diamond",
          "Ascendant", "Immortal", "Radiant")
#: Proposed share of matches per stratum: flatter than the ladder's own
#: population so the extremes carry enough matches to compare.
QUOTA_SHARE = {"Iron": 0.06, "Bronze": 0.10, "Silver": 0.13, "Gold": 0.14,
               "Platinum": 0.14, "Diamond": 0.13, "Ascendant": 0.12,
               "Immortal": 0.12, "Radiant": 0.06}
HOLDOUT_MOD = 5     # one match in five, by match-id hash, is held out
FRONTIER_MAX = 5000


class Stop(RuntimeError):
    """Stops the run; files already written stay, and a rerun resumes."""


# ---------------------------------------------------------------- config

@dataclass
class Politeness:
    key_tier: str = "basic"
    fraction: float = 0.5           # of the documented per-minute limit
    daily_cap: int = 250            # requests per UTC day
    total_cap: int = 250            # requests ever, until raised by approval
    daily_unit_cap: float = 2500    # quota units per UTC day
    total_unit_cap: float = 2500    # quota units ever, until raised
    max_matches: int = 20           # stored matches, until raised by approval
    max_retries: int = 4
    backoff_base_s: float = 8.0
    backoff_max_s: float = 600.0
    max_consecutive_errors: int = 3
    list_size: int = 10
    #: a call's cost before any is measured: the call, Riot's match list, and
    #: one match-details request per match asked for
    prior_base_units: float = 2.0
    prior_units_per_match: float = 1.0

    @property
    def limit(self) -> int:
        return DOC_LIMIT_PER_MIN[self.key_tier]

    @property
    def per_min(self) -> float:
        """Units a minute the run may spend: the limit less the reserve."""
        return self.limit * min(self.fraction, 0.5)

    @property
    def reserve(self) -> float:
        """Units the key keeps unspent: `Remaining` never planned below it."""
        return self.limit - self.per_min

    @property
    def interval_s(self) -> float:
        """The shortest gap between two calls, one-unit calls included."""
        return 60.0 / self.per_min


def today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat()


@dataclass
class State:
    version: str = VERSION
    region: str = "na"
    platform: str = "pc"
    since: str | None = None        # ISO date; matches before it are out
    seasons: list[str] = field(default_factory=list)   # e.g. ["e11a1"]
    target_matches: int = 2000      # quota base, not a permission
    requests_total: int = 0
    requests_by_day: dict[str, int] = field(default_factory=dict)
    units_total: float = 0.0
    units_by_day: dict[str, float] = field(default_factory=dict)
    units_unmeasured: int = 0       # calls charged their prediction
    units_per_match_max: float | None = None   # the largest measured
    last_call_epoch: float | None = None
    probes: dict[str, dict] = field(default_factory=dict)
    consecutive_errors: int = 0
    seq: int = 0
    frontier: list[dict] = field(default_factory=list)
    visited: list[str] = field(default_factory=list)
    matches: dict[str, dict] = field(default_factory=dict)
    duplicates_seen: int = 0
    out_of_scope_seen: int = 0

    @classmethod
    def load(cls, path: Path) -> "State":
        if not path.exists():
            return cls(since=(dt.date.today() - dt.timedelta(days=90))
                       .isoformat())
        d = json.loads(path.read_text(encoding="utf-8"))
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def requests_today(self) -> int:
        return self.requests_by_day.get(today(), 0)

    def units_today(self) -> float:
        return self.units_by_day.get(today(), 0.0)


def out_dir(store: Path) -> Path:
    return Path(store) / "external" / "ladder" / "henrikdev" / API_VERSION


def parse_env(text: str) -> dict[str, str]:
    """`NAME=value` lines; `#` comments, `export ` and quotes dropped."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[name] = value
    return out


def env_files(repo: Path) -> list[Path]:
    """The checkout's `.env`, then, in a git worktree, the main checkout's."""
    files = [repo / ".env"]
    git = repo / ".git"
    if git.is_file():          # a worktree: "gitdir: <main>/.git/worktrees/x"
        try:
            gd = Path(git.read_text(encoding="utf-8").split("gitdir:", 1)[1]
                      .strip())
            cd = gd / "commondir"
            common = (gd / cd.read_text(encoding="utf-8").strip()) \
                if cd.is_file() else gd.parents[1]
            files.append(common.resolve().parent / ".env")
        except (IndexError, OSError):
            pass
    return files


def read_key(store: Path, repo: Path | None = None) -> str | None:
    """The API key from the environment, the store or `.env`; never printed."""
    for name in (KEY_ENV, KEY_ENV_ALT):
        k = os.environ.get(name, "").strip()
        if k:
            return k
    p = Path(store) / "external" / "ladder" / "henrikdev" / "api_key"
    if p.is_file():
        k = p.read_text(encoding="utf-8").strip()
        if k:
            return k
    for f in env_files(repo or Path(__file__).resolve().parents[1]):
        if f.is_file():
            env = parse_env(f.read_text(encoding="utf-8"))
            for name in (KEY_ENV_ALT, KEY_ENV):
                if env.get(name, "").strip():
                    return env[name].strip()
    return None


# ---------------------------------------------------------------- HTTP

@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


Opener = Callable[[str, dict], Response]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None   # the key never follows a redirect


def urllib_opener(url: str, headers: dict) -> Response:
    """GET `url`; an HTTP error returns its status, a network error status 0."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                         _NoRedirect())
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(req, timeout=60) as r:
            return Response(r.status, dict(r.headers.items()), r.read())
    except urllib.error.HTTPError as e:
        return Response(e.code, dict((e.headers or {}).items()), e.read())
    except (urllib.error.URLError, OSError) as e:
        return Response(0, {}, str(getattr(e, "reason", e)).encode())


def header(headers: dict, name: str) -> str | None:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


def wait_hint_s(headers: dict) -> float | None:
    """Seconds `Retry-After` or `X-RateLimit-Reset` asks for, if either does."""
    for name in ("Retry-After", "X-RateLimit-Reset"):
        v = header(headers, name)
        if not v:
            continue
        v = v.strip()
        try:
            return max(0.0, float(v))
        except ValueError:
            pass
        try:   # an HTTP date
            from email.utils import parsedate_to_datetime
            when = parsedate_to_datetime(v)
            return max(0.0, (when - dt.datetime.now(when.tzinfo))
                       .total_seconds())
        except (TypeError, ValueError):
            pass
    return None


def rate_headers(headers: dict) -> dict:
    """`X-RateLimit-Limit`, `-Remaining` and `-Reset` (seconds), as numbers."""
    out = {}
    for k, name in (("limit", "X-RateLimit-Limit"),
                    ("remaining", "X-RateLimit-Remaining"),
                    ("reset_s", "X-RateLimit-Reset")):
        v = header(headers, name)
        try:
            out[k] = float(v) if v is not None else None
        except ValueError:
            out[k] = None
    return out


class Limiter:
    """Paces calls by the key's quota units, measured on `clock`.

    `wait(expected)` returns when a call costing `expected` units leaves the
    last reported `Remaining` at or above `reserve` and the units spent in the
    last 60 s, plus `expected`, within `limit - reserve`; and no sooner than
    `interval` after the previous call. `observe` reads a reply's rate-limit
    headers and returns the call's cost with its basis. With `reserve` 0 and
    no headers it is a plain one-call-per-`interval` limiter.
    """

    WINDOW_S = 60.0

    def __init__(self, interval: float, sleep: Callable[[float], None],
                 clock: Callable[[], float], limit: float | None = None,
                 reserve: float = 0.0):
        self.interval, self.sleep, self.clock = interval, sleep, clock
        self.limit, self.reserve = limit, reserve
        self._last: float | None = None
        self._hold_until: float | None = None
        self._remaining: float | None = None
        self._window_end: float | None = None
        self._ledger: list[tuple[float, float]] = []   # (sent at, units)

    @property
    def budget(self) -> float | None:
        return None if self.limit is None else self.limit - self.reserve

    def _due(self, expected: float) -> float:
        now = self.clock()
        due = now if self._last is None else self._last + self.interval
        if self._hold_until is not None:
            due = max(due, self._hold_until)
        if self._remaining is not None and self._window_end is not None \
                and now < self._window_end \
                and self._remaining - expected < self.reserve:
            due = max(due, self._window_end + 1.0)
        b = self.budget
        if b is not None:
            recent = [(t, u) for t, u in self._ledger
                      if t > now - self.WINDOW_S]
            self._ledger = recent
            spent = sum(u for _, u in recent)
            for t, u in recent:              # oldest first
                if spent + expected <= b:
                    break
                spent -= u
                due = max(due, t + self.WINDOW_S + 0.01)
        return due

    def wait(self, expected: float = 1.0) -> None:
        if self.budget is not None and expected > self.budget:
            raise Stop(f"a call predicted at {expected:.0f} units exceeds the "
                       f"{self.budget:.0f}-unit minute; lower --list-size")
        for _ in range(4):        # a wait may expire a window; look again
            due, now = self._due(expected), self.clock()
            if due <= now:
                break
            self.sleep(due - now)
        self._last = self.clock()

    def hold(self, seconds: float) -> None:
        """No request before `seconds` from now."""
        self._hold_until = self.clock() + seconds

    def observe(self, headers: dict, sent_at: float, expected: float
                ) -> tuple[float, str, dict]:
        """The call's units and how they were found; updates the pace."""
        rh = rate_headers(headers)
        now = self.clock()
        lim, rem, reset = rh["limit"], rh["remaining"], rh["reset_s"]
        if lim is not None:
            self.limit = lim
        units, basis = expected, "predicted"
        if rem is not None:
            same = (self._remaining is not None and self._window_end is not None
                    and sent_at < self._window_end)
            if same and self._remaining - rem >= 0:
                units, basis = self._remaining - rem, "remaining_drop"
            elif self.limit is not None:
                units, basis = self.limit - rem, "fresh_window"
            self._remaining = rem
            self._window_end = now + (reset if reset is not None
                                      else self.WINDOW_S)
            if rem <= 0:
                self.hold(reset if reset is not None else self.WINDOW_S)
        self._ledger.append((sent_at, units))
        return units, basis, rh


class Client:
    """HenrikDev GETs under the politeness rules; counts persist in State."""

    RETRY = {0, 429, 500, 502, 503, 504}

    def __init__(self, key: str, state: State, pol: Politeness,
                 opener: Opener = urllib_opener,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 save: Callable[[], None] = lambda: None,
                 epoch: Callable[[], float] = time.time):
        if not key:
            raise Stop("no API key; see docs/LADDER_SAMPLE.md, 'The key'")
        self.key, self.state, self.pol = key, state, pol
        self.opener, self.sleep, self.save = opener, sleep, save
        self.epoch = epoch
        self.limiter = Limiter(pol.interval_s, sleep, clock,
                               limit=pol.limit, reserve=pol.reserve)
        if state.last_call_epoch is not None:   # a previous run's window
            since = epoch() - state.last_call_epoch
            if 0 <= since < Limiter.WINDOW_S:
                self.limiter.hold(Limiter.WINDOW_S - since + 1.0)
        self.last: dict = {}

    def expected_units(self, n_matches: int) -> float:
        per = self.state.units_per_match_max
        per = self.pol.prior_units_per_match if per is None else per
        return min(self.pol.prior_base_units + per * max(n_matches, 0),
                   self.limiter.budget or float("inf"))

    def _check_caps(self, expected: float) -> None:
        s, p = self.state, self.pol
        if s.requests_total >= p.total_cap:
            raise Stop(f"total request cap reached ({p.total_cap})")
        if s.requests_today() >= p.daily_cap:
            raise Stop(f"daily request cap reached ({p.daily_cap}); "
                       "rerun tomorrow, it resumes")
        if s.units_total + expected > p.total_unit_cap:
            raise Stop(f"total unit cap reached ({s.units_total:.0f} of "
                       f"{p.total_unit_cap:.0f}, next call ~{expected:.0f})")
        if s.units_today() + expected > p.daily_unit_cap:
            raise Stop(f"daily unit cap reached ({p.daily_unit_cap:.0f}); "
                       "rerun tomorrow, it resumes")

    def get(self, path: str, params: dict | None = None,
            n_matches: int = 0) -> tuple[str, Response]:
        """GET `path`; `n_matches` is how many match records it may build."""
        q = urllib.parse.urlencode(params or {})
        rel = path + (f"?{q}" if q else "")
        url = BASE + rel
        if urllib.parse.urlsplit(url).hostname != HOST:
            raise Stop("refusing a host other than the API's")
        expected = self.expected_units(n_matches)
        for attempt in range(self.pol.max_retries + 1):
            self._check_caps(expected)
            self.limiter.wait(expected)
            sent_at = self.limiter.clock()
            r = self.opener(url, {"Authorization": self.key,
                                  "User-Agent": USER_AGENT,
                                  "Accept": "application/json"})
            s = self.state
            units, basis, rh = self.limiter.observe(r.headers, sent_at,
                                                    expected)
            s.requests_total += 1
            s.requests_by_day[today()] = s.requests_today() + 1
            s.units_total += units
            s.units_by_day[today()] = s.units_today() + units
            s.units_unmeasured += basis == "predicted"
            s.last_call_epoch = self.epoch()
            self.last = {"units": units, "units_basis": basis,
                         "units_expected": expected, "rate": rh}
            if r.status not in self.RETRY:
                s.consecutive_errors = 0
                if r.status == 200 and basis != "predicted":
                    self._learn(r, units)
                self.save()
                return rel, r
            s.consecutive_errors += 1
            self.save()
            if s.consecutive_errors >= self.pol.max_consecutive_errors:
                raise Stop(f"{s.consecutive_errors} failed requests in a row "
                           f"(last HTTP {r.status or 'network error'}); "
                           "stopping; rerun later, it resumes")
            back = min(self.pol.backoff_max_s,
                       self.pol.backoff_base_s * 2 ** attempt)
            hint = wait_hint_s(r.headers) if r.status == 429 else None
            wait = max(back, hint or 0.0)
            print(f"  HTTP {r.status or 'network error'}; waiting {wait:.0f} s")
            self.limiter.hold(wait)
        raise Stop(f"{self.pol.max_retries + 1} attempts failed on one request")

    def _learn(self, r: Response, units: float) -> None:
        """The largest measured cost per match predicts the next call."""
        try:
            n = len(matches_of(r.body))
        except (ValueError, AttributeError):
            return
        if n:
            per = max(0.0, units - self.pol.prior_base_units) / n
            cur = self.state.units_per_match_max
            self.state.units_per_match_max = per if cur is None else \
                max(cur, per)


# ---------------------------------------------------------------- store

def append_line(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def save_raw(out: Path, state: State, kind: str, endpoint: str, r: Response,
             fetched_at: str, match_ids: list[str],
             cost: dict | None = None) -> dict:
    """Write a 200 body gzip-compressed and its manifest row; never overwrite.

    `cost` is the client's account of the call (`Client.last`): units, their
    basis, the prediction and the rate-limit headers.
    """
    state.seq += 1
    row = {"seq": state.seq, "kind": kind, "endpoint": endpoint,
           "fetched_at": fetched_at, "status": r.status,
           "response_date": header(r.headers, "Date"),
           "request_id": header(r.headers, "X-Request-ID"),
           "bytes": len(r.body), "sha256": hashlib.sha256(r.body).hexdigest(),
           "match_ids": match_ids, "fetcher": VERSION, **(cost or {})}
    if r.status == 200:
        name = f"{state.seq:06d}-{kind}.json.gz"
        path = out / "raw" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        gz = gzip.compress(r.body, compresslevel=9, mtime=0)
        with open(path, "xb") as f:      # fails rather than overwrite
            f.write(gz)
        row.update(file=name, gz_bytes=len(gz))
    append_line(out / "manifest.jsonl", row)
    return row


def read_manifest(out: Path) -> list[dict]:
    p = out / "manifest.jsonl"
    if not p.exists():
        return []
    return [json.loads(s) for s in p.read_text(encoding="utf-8").splitlines()
            if s.strip()]


def known_riot_matches(store: Path) -> set[str]:
    """Match ids with a stored Riot record: the captures and the fetch kit."""
    ids = {p.stem for p in (Path(store) / "external" / "riot").glob("*.json")}
    ids |= {p.stem for p in (Path(store) / "external" / "riot-pd-v1" / "raw")
            .glob("*.json")}
    return ids


def owner_puuids(store: Path) -> dict[str, str]:
    """The player's accounts, label -> PUUID, from the store only.

    Three sources, merged: `external/ladder/owner_seeds.json` written by the
    player (`[{"label": "A", "puuid": "..."}]`), the fetch kit's
    `external/riot-pd-v1/accounts.jsonl`, and the accounts
    `riot_ground_truth.identify_player` names as recurring in the captured
    records.
    """
    store = Path(store)
    out: dict[str, str] = {}
    p = store / "external" / "ladder" / "owner_seeds.json"
    if p.is_file():
        for r in json.loads(p.read_text(encoding="utf-8")):
            if r.get("puuid"):
                out[str(r.get("label") or f"seed{len(out)}")] = r["puuid"]
    p = store / "external" / "riot-pd-v1" / "accounts.jsonl"
    if p.is_file():
        for s in p.read_text(encoding="utf-8").splitlines():
            if s.strip():
                r = json.loads(s)
                out.setdefault(f"kit-{r['label']}", r["puuid"])
    if (store / "external" / "riot").is_dir():
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import riot_ground_truth as rgt
        recs = rgt.riot_records(store)
        ident = rgt.identify_player(recs, store)
        subs = sorted({v["subject"] for v in ident.values()
                       if v.get("basis") == "recurring_account"})
        have = set(out.values())
        for i, s in enumerate(x for x in subs if x not in have):
            out[f"recurring-{i}"] = s
    return out


# ---------------------------------------------------------------- strata

def stratum(tier_name: str | None) -> str | None:
    if not tier_name:
        return None
    w = str(tier_name).split()[0].capitalize()
    return w if w in STRATA else None


def match_stratum(tier_names: list[str | None]) -> str | None:
    """The median ranked player's stratum, or None with no ranked player."""
    idx = sorted(STRATA.index(s) for s in map(stratum, tier_names) if s)
    return STRATA[idx[(len(idx) - 1) // 2]] if idx else None


def quotas(target: int) -> dict[str, int]:
    return {s: round(target * QUOTA_SHARE[s]) for s in STRATA}


def choose_next(state: State) -> dict | None:
    """The frontier player to list next: owners first, then the player
    closest to the stratum furthest below its quota."""
    visited = set(state.visited)
    todo = [f for f in state.frontier if f["puuid"] not in visited]
    if not todo:
        return None
    owners = [f for f in todo if f.get("kind") == "owner"]
    if owners:
        return owners[0]
    q = quotas(state.target_matches)
    have = {s: 0 for s in STRATA}
    for m in state.matches.values():
        if m.get("stratum") in have:
            have[m["stratum"]] += 1
    deficit = {s: 1 - have[s] / max(q[s], 1) for s in STRATA}
    top = max(deficit.values())
    targets = [STRATA.index(s) for s in STRATA if deficit[s] == top]
    ranked = [f for f in todo if f.get("stratum") in STRATA]
    if not ranked:
        return todo[0]
    # the candidate nearest any most-starved stratum; the snowball drifts
    # toward a stratum it cannot yet reach, one lobby at a time
    return min(ranked, key=lambda f: (
        min(abs(STRATA.index(f["stratum"]) - t) for t in targets),
        -(f.get("seen_ms") or 0)))


def add_frontier(state: State, entries: list[dict]) -> int:
    have = {f["puuid"] for f in state.frontier} | set(state.visited)
    new = [e for e in entries if e["puuid"] not in have]
    state.frontier.extend(new)
    if len(state.frontier) > FRONTIER_MAX:   # keep owners and the newest
        visited = set(state.visited)
        keep = [f for f in state.frontier if f.get("kind") == "owner"
                or f["puuid"] not in visited]
        state.frontier = sorted(keep, key=lambda f: f.get("kind") != "owner"
                                )[:FRONTIER_MAX]
    return len(new)


# ---------------------------------------------------------------- matches

def started_ms(m: dict) -> int | None:
    s = (m.get("metadata") or {}).get("started_at")
    if not s:
        return None
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
               .timestamp() * 1000)


def match_in_window(m: dict, state: State) -> tuple[bool, str]:
    md = m.get("metadata") or {}
    if (md.get("queue") or {}).get("id") != "competitive":
        return False, "queue"
    if not md.get("is_completed", True):
        return False, "incomplete"
    if state.seasons and (md.get("season") or {}).get("short") not in \
            state.seasons:
        return False, "season"
    t = started_ms(m)
    if state.since and t is not None:
        since = dt.datetime.fromisoformat(state.since).replace(
            tzinfo=dt.timezone.utc).timestamp() * 1000
        if t < since:
            return False, "before_window"
    return True, ""


def matches_of(body: bytes) -> list[dict]:
    d = json.loads(body)
    data = d.get("data") if isinstance(d, dict) else None
    if isinstance(data, dict):
        return [data]
    return [m for m in (data or []) if isinstance(m, dict)]


def register(state: State, ms: list[dict], kind: str, known: set[str]) -> dict:
    """Record a reply's matches; return counts. Expands the frontier."""
    c = {"new": 0, "duplicate": 0, "out_of_scope": 0, "frontier_added": 0}
    for m in ms:
        mid = (m.get("metadata") or {}).get("match_id")
        if not mid:
            continue
        if mid in state.matches or mid in known:
            c["duplicate"] += 1
            state.duplicates_seen += 1
            continue
        ok, why = match_in_window(m, state)
        if not ok:
            c["out_of_scope"] += 1
            state.out_of_scope_seen += 1
            continue
        players = m.get("players") or []
        tiers = [(p.get("tier") or {}).get("name") for p in players]
        state.matches[mid] = {"stratum": match_stratum(tiers), "via": kind,
                              "started_ms": started_ms(m)}
        c["new"] += 1
        c["frontier_added"] += add_frontier(state, [
            {"puuid": p["puuid"], "kind": "snowball",
             "stratum": stratum((p.get("tier") or {}).get("name")),
             "seen_ms": started_ms(m)} for p in players if p.get("puuid")])
    return c


# ---------------------------------------------------------------- commands

def list_path(state: State, puuid: str) -> str:
    return (f"/valorant/v4/by-puuid/matches/{state.region}/{state.platform}/"
            f"{puuid}")


def fetch_list(client: Client, state: State, out: Path, puuid: str,
               size: int, start: int = 0, kind: str = "list"
               ) -> tuple[int, list[dict]]:
    """One competitive list call, stored raw; (status, its matches)."""
    params = {"mode": "competitive", "size": size}
    if start:
        params["start"] = start
    fetched_at = now_iso()
    rel, r = client.get(list_path(state, puuid), params, n_matches=size)
    ms = matches_of(r.body) if r.status == 200 else []
    save_raw(out, state, kind, rel, r, fetched_at,
             [(m.get("metadata") or {}).get("match_id") for m in ms],
             cost=client.last)
    if r.status in (401, 403):
        client.save()
        raise Stop(f"HTTP {r.status}: the key is missing, wrong or revoked")
    return r.status, ms


def list_player(client: Client, state: State, out: Path, f: dict, size: int,
                known: set[str]) -> dict:
    status, ms = fetch_list(client, state, out, f["puuid"], size)
    state.visited.append(f["puuid"])
    if status != 200:
        client.save()
        return {"status": status}
    c = register(state, ms, f.get("kind", "snowball"), known)
    client.save()
    return {"status": 200, "returned": len(ms), **c}


def probe_history(client: Client, state: State, out: Path, f: dict,
                  first: int, returned: int, budget: int, known: set[str],
                  starts=(20, 40, 80, 160)) -> dict:
    """How deep a player's competitive list pages, in `start` index.

    A list of `first` that returned fewer matches already shows the depth.
    Otherwise one-match lists at growing `start` find the first empty page,
    then halve the gap while `budget` match records remain; each non-empty
    probe builds one match (stored and registered like any list's). The
    result brackets the depth: `deeper_than` matches exist, `at_most` do not
    exceed. Stored in `state.probes` under the owner's label.
    """
    res = {"first_size": first, "first_returned": returned, "probes": []}
    if returned < first:
        res.update(deeper_than=returned, at_most=returned, exact=True)
        return res
    lo, hi = returned - 1, None          # index lo exists; hi is empty
    for st in starts:
        if budget <= 0 or (hi is not None):
            break
        status, ms = fetch_list(client, state, out, f["puuid"], 1, start=st,
                                kind="probe")
        res["probes"].append({"start": st, "status": status, "n": len(ms)})
        if status != 200:
            break
        register(state, ms, f.get("kind", "owner"), known)
        budget -= len(ms)
        if ms:
            lo = st
        else:
            hi = st
    while hi is not None and hi - lo > 1 and budget > 0:
        st = (lo + hi) // 2
        status, ms = fetch_list(client, state, out, f["puuid"], 1, start=st,
                                kind="probe")
        res["probes"].append({"start": st, "status": status, "n": len(ms)})
        if status != 200:
            break
        register(state, ms, f.get("kind", "owner"), known)
        budget -= len(ms)
        if ms:
            lo = st
        else:
            hi = st
    res.update(deeper_than=lo + 1, at_most=hi, exact=hi == lo + 1)
    client.save()
    return res


def fit_size(client: Client, size: int) -> int:
    """The largest list size whose predicted units fit one minute's budget."""
    b = client.limiter.budget
    if b is None:
        return size
    while size > 1 and client.pol.prior_base_units + size * (
            client.state.units_per_match_max
            or client.pol.prior_units_per_match) > b:
        size -= 1
    return size


def crawl(client: Client, state: State, out: Path, pol: Politeness,
          known: set[str], owners_only: bool = False,
          max_requests: int | None = None) -> dict:
    tot = {"lists": 0, "new": 0, "duplicate": 0, "out_of_scope": 0}
    start = state.requests_total
    while True:
        if len(state.matches) >= pol.max_matches:
            print(f"match cap reached ({pol.max_matches})")
            break
        if max_requests is not None and \
                state.requests_total - start >= max_requests:
            print(f"this run's request budget reached ({max_requests})")
            break
        f = choose_next(state)
        if f is None or (owners_only and f.get("kind") != "owner"):
            break
        size = fit_size(client, min(pol.list_size,
                                    pol.max_matches - len(state.matches)))
        c = list_player(client, state, out, f, size, known)
        tot["lists"] += 1
        for k in ("new", "duplicate", "out_of_scope"):
            tot[k] += c.get(k, 0)
        print(f"  list {tot['lists']} ({f.get('kind')}, "
              f"{f.get('stratum') or '?'}): HTTP {c['status']}, "
              f"{c.get('new', 0)} new, {c.get('duplicate', 0)} stored, "
              f"{c.get('out_of_scope', 0)} out of scope")
    return tot


def seed_owners(state: State, store: Path) -> int:
    own = owner_puuids(store)
    return add_frontier(state, [{"puuid": p, "kind": "owner", "label": k}
                                for k, p in own.items()])


def seed_leaderboard(client: Client, state: State, out: Path, pages: int,
                     size: int) -> int:
    added = 0
    for page in range(1, pages + 1):
        fetched_at = now_iso()
        rel, r = client.get(f"/valorant/v3/leaderboard/{state.region}/"
                            f"{state.platform}", {"size": size, "page": page})
        save_raw(out, state, "leaderboard", rel, r, fetched_at, [],
                 cost=client.last)
        if r.status != 200:
            client.save()
            raise Stop(f"leaderboard answered HTTP {r.status}")
        d = json.loads(r.body).get("data") or {}
        rows = d.get("players") if isinstance(d, dict) else d
        # a frontier hint only: the leaderboard holds the top tiers, and each
        # player's tier at match time comes from the match itself
        added += add_frontier(state, [
            {"puuid": p["puuid"], "kind": "leaderboard",
             "stratum": "Immortal",
             "leaderboard_rank": p.get("leaderboard_rank")}
            for p in rows or [] if p.get("puuid")
            and not p.get("is_anonymized") and not p.get("is_banned")])
        client.save()
    return added


# ---------------------------------------------------------------- parsing

def _col(arr: pa.Array, *path: str) -> pa.Array:
    """Nested struct field, or nulls when the path is absent in this batch."""
    for name in path:
        t = arr.type
        if not pa.types.is_struct(t) or t.get_field_index(name) < 0:
            return pa.nulls(len(arr))
        arr = pc.struct_field(arr, name)
    return arr


def _explode(lists: pa.Array) -> tuple[pa.Array, pa.Array]:
    """A list column's items and, per item, the index of its row."""
    if not (pa.types.is_list(lists.type) or
            pa.types.is_large_list(lists.type)):
        return pa.array([], pa.struct([])), pa.array([], pa.int64())
    return pc.list_flatten(lists), pc.list_parent_indices(lists)


def _pseudo(salt: bytes, owners: set[str]):
    """Keyed BLAKE2b pseudonyms, hashed once per distinct id, never per row."""
    cache: dict = {}
    own = pa.array(sorted(owners), pa.string())

    def pid(col: pa.Array) -> pa.Array:
        if len(col) == 0:
            return pa.array([], pa.string())
        d = pc.dictionary_encode(col.cast(pa.string()))
        dic = d.dictionary.to_pylist()
        for u in dic:
            if u not in cache:
                cache[u] = hashlib.blake2b(u.encode(), key=salt,
                                           digest_size=8).hexdigest()
        return pc.take(pa.array([cache[u] for u in dic], pa.string()),
                       d.indices)

    def is_owner(col: pa.Array) -> pa.Array:
        return pc.fill_null(pc.is_in(col.cast(pa.string()), own), False)
    return pid, is_owner


def _strata(tier_name: pa.Array) -> pa.Array:
    """The first word of each tier name when it names a stratum, else null."""
    if len(tier_name) == 0:
        return pa.array([], pa.string())
    w = pc.list_element(pc.split_pattern(
        pc.fill_null(tier_name.cast(pa.string()), ""), " ", max_splits=1), 0)
    return pc.if_else(pc.is_in(w, pa.array(STRATA)), w,
                      pa.scalar(None, pa.string()))


def parse_matches(ms: list[dict], salt: bytes, owners: set[str],
                  captured: set[str]) -> dict[str, pa.Table]:
    """Six tables from v4 match objects; every PUUID pseudonymised.

    Arrow infers one nested type for the batch and every column is a struct
    field or a list flatten over it; no per-row Python.
    """
    pid, is_owner = _pseudo(salt, owners)
    M = pa.array(ms)
    md = _col(M, "metadata")
    mids = _col(md, "match_id").cast(pa.string())
    idx = pa.array(range(len(ms)), pa.int64())

    # players
    pl, ppar = _explode(_col(M, "players"))
    p_puuid = _col(pl, "puuid")
    p_stratum = _strata(_col(pl, "tier", "name"))
    p_owner = is_owner(p_puuid)
    players = pa.table({
        "match_id": pc.take(mids, ppar), "player": pid(p_puuid),
        "is_owner": p_owner, "team": _col(pl, "team_id"),
        "party": pid(_col(pl, "party_id")),
        "agent": _col(pl, "agent", "name"), "tier_id": _col(pl, "tier", "id"),
        "tier_name": _col(pl, "tier", "name"), "stratum": p_stratum,
        "account_level": _col(pl, "account_level"),
        "score": _col(pl, "stats", "score"),
        "kills": _col(pl, "stats", "kills"),
        "deaths": _col(pl, "stats", "deaths"),
        "assists": _col(pl, "stats", "assists"),
        "afk_rounds": _col(pl, "behavior", "afk_rounds"),
        "rounds_in_spawn": _col(pl, "behavior", "rounds_in_spawn")})

    # per match: the median ranked player's stratum (lower median), owners
    si = pc.index_in(p_stratum, pa.array(STRATA))
    g = pa.table({"m": ppar, "si": si, "own": p_owner}).group_by("m")\
        .aggregate([("si", "list"), ("own", "any")])
    med = [None] * len(ms)
    for m_, xs in zip(g["m"].to_pylist(), g["si_list"].to_pylist()):
        xs = sorted(x for x in xs if x is not None)   # one list per match
        med[m_] = STRATA[xs[(len(xs) - 1) // 2]] if xs else None
    has_owner = pc.fill_null(pc.is_in(idx, pc.filter(g["m"], g["own_any"])
                                      .combine_chunks()), False)

    # teams -> winner
    tm, tpar = _explode(_col(M, "teams"))
    won = pc.fill_null(_col(tm, "won"), False) if len(tm) else \
        pa.array([], pa.bool_())
    winner_i = pc.filter(tpar, won)
    winner_t = pc.filter(_col(tm, "team_id"), won)
    pos = pc.index_in(idx, winner_i)
    winning_team = pc.take(winner_t.cast(pa.string()), pos) if len(winner_t) \
        else pa.nulls(len(ms), pa.string())
    hold = pa.array([int(hashlib.sha256(x.encode()).hexdigest(), 16)
                     % HOLDOUT_MOD == 0 for x in mids.to_pylist()])  # per match
    cap = pc.is_in(mids, pa.array(sorted(captured), pa.string()))
    matches = pa.table({
        "match_id": mids, "map": _col(md, "map", "name"),
        "map_id": _col(md, "map", "id"),
        "game_version": _col(md, "game_version"),
        "season": _col(md, "season", "short"),
        "queue": _col(md, "queue", "id"),
        "started_at": _col(md, "started_at"),
        "game_length_ms": _col(md, "game_length_in_ms"),
        "region": _col(md, "region"), "cluster": _col(md, "cluster"),
        "rounds": pc.fill_null(pc.list_value_length(_col(M, "rounds")), 0)
        if pa.types.is_list(_col(M, "rounds").type)
        else pa.nulls(len(ms), pa.int32()),
        "winning_team": winning_team,
        "stratum": pa.array(med, pa.string()),
        "has_owner": has_owner, "captured": cap,
        "holdout": pc.or_(hold, cap)})

    # rounds
    rd, rpar = _explode(_col(M, "rounds"))
    rid = _col(rd, "id")
    rounds = pa.table({
        "match_id": pc.take(mids, rpar), "round": rid,
        "winning_team": _col(rd, "winning_team"),
        "result": _col(rd, "result"), "ceremony": _col(rd, "ceremony"),
        "plant_ms": _col(rd, "plant", "round_time_in_ms"),
        "plant_site": _col(rd, "plant", "site"),
        "plant_x": _col(rd, "plant", "location", "x"),
        "plant_y": _col(rd, "plant", "location", "y"),
        "planter": pid(_col(rd, "plant", "player", "puuid")),
        "defuse_ms": _col(rd, "defuse", "round_time_in_ms"),
        "defuse_x": _col(rd, "defuse", "location", "x"),
        "defuse_y": _col(rd, "defuse", "location", "y"),
        "defuser": pid(_col(rd, "defuse", "player", "puuid"))})

    # economy, per round per player
    st, sp = _explode(_col(rd, "stats"))
    economy = pa.table({
        "match_id": pc.take(mids, pc.take(rpar, sp)),
        "round": pc.take(rid, sp),
        "player": pid(_col(st, "player", "puuid")),
        "team": _col(st, "player", "team"),
        "loadout_value": _col(st, "economy", "loadout_value"),
        "remaining": _col(st, "economy", "remaining"),
        "spent": _col(st, "economy", "spent"),
        "weapon": _col(st, "economy", "weapon", "name"),
        "weapon_id": _col(st, "economy", "weapon", "id"),
        "armor": _col(st, "economy", "armor", "name"),
        "armor_id": _col(st, "economy", "armor", "id"),
        "score": _col(st, "stats", "score"),
        "kills": _col(st, "stats", "kills"),
        "was_afk": _col(st, "was_afk"),
        "received_penalty": _col(st, "received_penalty"),
        "stayed_in_spawn": _col(st, "stayed_in_spawn")})

    # kills; assistants rebuilt as a list of pseudonyms
    kl, kpar = _explode(_col(M, "kills"))
    kidx = pa.array(range(len(kl)), pa.int64())
    al = _col(kl, "assistants")
    if pa.types.is_list(al.type):
        a_items, _ = _explode(al)
        lens = pc.fill_null(pc.list_value_length(al), 0).cast(pa.int32())
        offs = pa.concat_arrays([pa.array([0], pa.int32()),
                                 pc.cumulative_sum(lens)])
        assistants = pa.ListArray.from_arrays(
            offs, pid(_col(a_items, "puuid")))
    else:
        assistants = pa.nulls(len(kl), pa.list_(pa.string()))
    kills = pa.table({
        "match_id": pc.take(mids, kpar), "kill": kidx,
        "round": _col(kl, "round"),
        "time_in_round_ms": _col(kl, "time_in_round_in_ms"),
        "time_in_match_ms": _col(kl, "time_in_match_in_ms"),
        "killer": pid(_col(kl, "killer", "puuid")),
        "killer_team": _col(kl, "killer", "team"),
        "victim": pid(_col(kl, "victim", "puuid")),
        "victim_team": _col(kl, "victim", "team"),
        "assistants": assistants,
        "weapon_id": _col(kl, "weapon", "id"),
        "weapon": _col(kl, "weapon", "name"),
        "weapon_type": _col(kl, "weapon", "type"),
        "secondary_fire": _col(kl, "secondary_fire_mode"),
        "victim_x": _col(kl, "location", "x"),
        "victim_y": _col(kl, "location", "y")})

    # positions of every listed player at kills, plants and defuses
    parts = []
    loc, lp = _explode(_col(kl, "player_locations"))
    if len(loc):
        parts.append(("kill", loc, pc.take(kpar, lp), pc.take(kidx, lp),
                      pc.take(_col(kl, "round"), lp)))
    for ev in ("plant", "defuse"):
        loc, lp = _explode(_col(rd, ev, "player_locations"))
        if len(loc):
            parts.append((ev, loc, pc.take(rpar, lp),
                          pa.nulls(len(loc), pa.int64()), pc.take(rid, lp)))
    schema = {"match_id": pa.string(), "event": pa.string(),
              "kill": pa.int64(), "round": pa.int64(), "player": pa.string(),
              "team": pa.string(), "x": pa.float64(), "y": pa.float64(),
              "view_radians": pa.float64()}
    cols: dict[str, list] = {k: [] for k in schema}
    for ev, loc, par, kk, rr in parts:
        got = {"match_id": pc.take(mids, par),
               "event": pa.array([ev], pa.string()).take(
                   pa.array([0] * len(loc))),
               "kill": kk, "round": rr,
               "player": pid(_col(loc, "player", "puuid")),
               "team": _col(loc, "player", "team"),
               "x": _col(loc, "location", "x"),
               "y": _col(loc, "location", "y"),
               "view_radians": _col(loc, "view_radians")}
        for k, t in schema.items():
            cols[k].append(got[k].cast(t))
    positions = pa.table({k: pa.concat_arrays(v) if v else pa.array([], t)
                          for (k, v), t in zip(cols.items(), schema.values())})
    return {"matches": matches, "players": players, "rounds": rounds,
            "economy": economy, "kills": kills, "positions": positions}


def write_tables(tables: dict[str, pa.Table], where: Path) -> dict[str, int]:
    where.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for name, t in tables.items():
        p = where / f"{name}.parquet"
        pq.write_table(t, p, compression="zstd")
        sizes[name] = p.stat().st_size
    return sizes


def salt_of(out: Path) -> bytes:
    p = out / "pseudonym_salt"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "x", encoding="utf-8") as f:
            f.write(secrets.token_hex(16))
    return bytes.fromhex(p.read_text(encoding="utf-8").strip())


def stored_matches(out: Path, state: State) -> list[dict]:
    """Every in-scope match the raw files hold, first copy only."""
    seen, ms = set(), []
    for row in read_manifest(out):
        if row.get("status") != 200 or not row.get("file") or \
                row["kind"] not in ("list", "match", "probe"):
            continue
        body = gzip.decompress((out / "raw" / row["file"]).read_bytes())
        for m in matches_of(body):
            mid = (m.get("metadata") or {}).get("match_id")
            if mid and mid not in seen and mid in state.matches:
                seen.add(mid)
                ms.append(m)
    return ms


# ---------------------------------------------------------------- Riot shape

def riot_to_v4(rec: dict, ref=None) -> dict:
    """A stored Riot match-details record in HenrikDev's v4 shape.

    `ref` (`riot_ground_truth.Reference`) names agents and weapons; without it
    the names stay None. Riot's per-round `spent` and kills' `damageType`
    are kept as `spent` and `weapon.type`; Riot records no tier name, so the
    tier name stays None and the stratum unknown.
    """
    m = rec.get("match", rec)
    mi = m["matchInfo"]
    team_of = {p["subject"]: p["teamId"] for p in m["players"]}

    def who(s):
        return None if not s else {"puuid": s, "name": None, "tag": None,
                                   "team": team_of.get(s)}

    def locs(xs):
        return [{"player": who(x.get("subject")),
                 "view_radians": x.get("viewRadians"),
                 "location": x.get("location")} for x in xs or []]

    agent = (lambda u: ref.agent(u)) if ref else (lambda u: None)
    weapon = (lambda u: ref.weapons.get((u or "").lower())) if ref \
        else (lambda u: None)
    start = dt.datetime.fromtimestamp(mi["gameStartMillis"] / 1000,
                                      dt.timezone.utc)
    return {
        "metadata": {
            "match_id": mi["matchId"], "map": {"id": mi["mapId"], "name": None},
            "game_version": mi.get("gameVersion"),
            "game_length_in_ms": mi.get("gameLengthMillis"),
            "started_at": start.isoformat().replace("+00:00", "Z"),
            "is_completed": mi.get("isCompleted"),
            "queue": {"id": mi.get("queueID"), "name": None},
            "season": {"id": mi.get("seasonId"), "short": None},
            "platform": "pc", "region": None,
            "cluster": mi.get("gamePodId")},
        "players": [{
            "puuid": p["subject"], "name": p.get("gameName"),
            "tag": p.get("tagLine"), "team_id": p["teamId"],
            "platform": "pc", "party_id": p.get("partyId"),
            "agent": {"id": p.get("characterId"),
                      "name": agent(p.get("characterId"))},
            "tier": {"id": p.get("competitiveTier"), "name": None},
            "account_level": p.get("accountLevel"),
            "stats": {k: (p.get("stats") or {}).get(k) for k in
                      ("score", "kills", "deaths", "assists")}}
            for p in m["players"]],
        "teams": [{"team_id": t["teamId"], "won": t.get("won"),
                   "rounds": {"won": t.get("roundsWon"),
                              "lost": t.get("roundsPlayed", 0)
                              - t.get("roundsWon", 0)}}
                  for t in m.get("teams") or []],
        "rounds": [{
            "id": r["roundNum"], "result": r.get("roundResultCode"),
            "ceremony": r.get("roundCeremony"),
            "winning_team": r.get("winningTeam"),
            "plant": None if not r.get("bombPlanter") else {
                "round_time_in_ms": r.get("plantRoundTime"),
                "site": r.get("plantSite"), "location": r.get("plantLocation"),
                "player": who(r.get("bombPlanter")),
                "player_locations": locs(r.get("plantPlayerLocations"))},
            "defuse": None if not r.get("bombDefuser") else {
                "round_time_in_ms": r.get("defuseRoundTime"),
                "location": r.get("defuseLocation"),
                "player": who(r.get("bombDefuser")),
                "player_locations": locs(r.get("defusePlayerLocations"))},
            "stats": [{
                "player": who(e["subject"]),
                "economy": {"loadout_value": e.get("loadoutValue"),
                            "remaining": e.get("remaining"),
                            "spent": e.get("spent"),
                            "weapon": {"id": e.get("weapon"),
                                       "name": weapon(e.get("weapon"))},
                            "armor": {"id": e.get("armor"), "name": None}}}
                for e in r.get("playerEconomies") or []]}
            for r in m.get("roundResults") or []],
        "kills": [{
            "round": k.get("round"), "time_in_round_in_ms": k.get("roundTime"),
            "time_in_match_in_ms": k.get("gameTime"),
            "killer": who(k.get("killer")), "victim": who(k.get("victim")),
            "assistants": [who(a) for a in k.get("assistants") or []],
            "weapon": {"id": (k.get("finishingDamage") or {}).get("damageItem"),
                       "name": weapon((k.get("finishingDamage") or {})
                                      .get("damageItem")),
                       "type": (k.get("finishingDamage") or {})
                       .get("damageType")},
            "secondary_fire_mode": (k.get("finishingDamage") or {})
            .get("isSecondaryFireMode"),
            "location": k.get("victimLocation"),
            "player_locations": locs(k.get("playerLocations"))}
            for k in m.get("kills") or []]}


# ---------------------------------------------------------------- reports

def measure(ms: list[dict], bodies: list[bytes], tables_dir: Path,
            salt: bytes, owners: set[str], captured: set[str]) -> dict:
    raw = [len(b) for b in bodies]
    gz = [len(gzip.compress(b, compresslevel=9, mtime=0)) for b in bodies]
    t0 = time.perf_counter()
    tables = parse_matches(ms, salt, owners, captured)
    parse_s = time.perf_counter() - t0
    sizes = write_tables(tables, tables_dir)
    n = len(ms)
    return {"matches": n, "raw_bytes_per_match": sum(raw) / n,
            "gz_bytes_per_match": sum(gz) / n,
            "parsed_bytes_per_match": sum(sizes.values()) / n,
            "parsed_bytes_by_table": sizes,
            "rows": {k: t.num_rows for k, t in tables.items()},
            "kill_positions": int(pc.sum(pc.equal(
                tables["positions"]["event"], "kill")).as_py() or 0),
            "parse_s": parse_s}


def calls_of(out: Path) -> list[dict]:
    """Manifest rows of calls that list matches, with their match counts."""
    return [r for r in read_manifest(out)
            if r.get("kind") in ("list", "probe", "match")]


def measure_v4(out: Path, tables_dir: Path, salt: bytes, owners: set[str],
               captured: set[str]) -> dict:
    """Bytes, rows and quota units per match from the stored v4 replies.

    Every match record a 200 reply holds counts once, first copy only, in or
    out of the sample's window, so the bytes describe v4 records as they
    come. Units come from the manifest (`units`, `units_basis`).
    """
    rows = calls_of(out)
    seen, ms, raw_b, gz_b, recs = set(), [], 0, 0, 0
    for row in rows:
        if row.get("status") != 200 or not row.get("file"):
            continue
        gzb = (out / "raw" / row["file"]).read_bytes()
        body = gzip.decompress(gzb)
        got = matches_of(body)
        if got:
            raw_b += len(body)
            gz_b += len(gzb)
            recs += len(got)
        for m in got:
            mid = (m.get("metadata") or {}).get("match_id")
            if mid and mid not in seen:
                seen.add(mid)
                ms.append(m)
    if not ms:
        raise Stop("no stored v4 match records; run dry-run first")
    t0 = time.perf_counter()
    tables = parse_matches(ms, salt, owners, captured)
    parse_s = time.perf_counter() - t0
    sizes = write_tables(tables, tables_dir)
    kill_pos = int(pc.sum(pc.equal(tables["positions"]["event"], "kill"))
                   .as_py() or 0)
    n = len(ms)
    measured = [r for r in rows if r.get("units_basis") in
                ("remaining_drop", "fresh_window")]
    empty = [r["units"] for r in measured
             if r.get("status") == 200 and not r.get("match_ids")]
    full = [(r["units"], len(r["match_ids"])) for r in measured
            if r.get("status") == 200 and r.get("match_ids")]
    units_all = sum(r.get("units") or 0 for r in rows)
    base = (sum(empty) / len(empty)) if empty else 1.0
    lists = [(r["units"], len(r["match_ids"])) for r in measured
             if r.get("status") == 200 and r.get("match_ids")
             and r["kind"] == "list"]
    return {
        "matches": n, "records": recs,
        "calls": len(rows), "calls_measured": len(measured),
        "units": units_all,
        "units_per_call": units_all / max(len(rows), 1),
        "units_per_empty_call": (sum(empty) / len(empty)) if empty else None,
        # a record's marginal units: a call's units less an empty call's
        "units_per_record": (sum(u - base for u, _ in full) /
                             sum(k for _, k in full)) if full else None,
        "units_per_record_list": (sum(u - base for u, _ in lists) /
                                  sum(k for _, k in lists)) if lists else None,
        "units_per_record_max": max(((u - base) / k for u, k in full),
                                    default=None),
        "units_by_call": [{"kind": r["kind"], "status": r.get("status"),
                           "n": len(r.get("match_ids") or []),
                           "units": r.get("units"),
                           "basis": r.get("units_basis"),
                           "remaining": (r.get("rate") or {}).get("remaining"),
                           "limit": (r.get("rate") or {}).get("limit")}
                          for r in rows],
        "raw_bytes_per_match": raw_b / recs, "gz_bytes_per_match": gz_b / recs,
        "parsed_bytes_per_match": sum(sizes.values()) / n,
        "parsed_bytes_by_table": sizes,
        "rows": {k: t.num_rows for k, t in tables.items()},
        "kill_positions": kill_pos,
        "kill_positions_per_kill": kill_pos / max(tables["kills"].num_rows, 1),
        "parse_s": parse_s}


#: The snowball's share of a list's records that are new, in-window matches:
#: high when only the shared lobby repeats (9 of 10), low when half repeat or
#: fall out of the window. Unmeasured until a crawl runs past the owners.
NEW_SHARE = (0.9, 0.5)


def projection(per_match: dict, pol: Politeness, units_per_record=None,
               base_units=None, size: int = 10,
               ns=(500, 1000, 2000)) -> list[dict]:
    """Calls, quota units, hours and disk per sample size, [low, high].

    Low: `NEW_SHARE[0]` of a list's records are new, a repeated (cached)
    record costs nothing, and a record costs the mean measured marginal
    units. High: `NEW_SHARE[1]` are new and every record costs the largest
    measured marginal units (`units_per_record_max`). An empty call's units
    are the base. `units_per_record` (one number or a [low, high] pair)
    overrides the measurement; without either, the priors. Hours spend
    `pol.per_min` units a minute.
    """
    if units_per_record is None:
        lo = per_match.get("units_per_record")
        hi = per_match.get("units_per_record_max")
        units_per_record = (pol.prior_units_per_match,) * 2 if lo is None \
            else (lo, hi if hi is not None else lo)
    elif not isinstance(units_per_record, (tuple, list)):
        units_per_record = (units_per_record,) * 2
    u_lo, u_hi = units_per_record
    base = base_units if base_units is not None else \
        per_match.get("units_per_empty_call") or pol.prior_base_units
    gz = (per_match["gz_bytes_per_match"],
          per_match.get("riot_gz_bytes_per_match",
                        per_match["gz_bytes_per_match"]))
    gz = (min(gz), max(gz))
    lo_new, hi_new = size * NEW_SHARE[0], size * NEW_SHARE[1]
    per_lo = (base + lo_new * u_lo) / lo_new      # repeats free
    per_hi = (base + size * u_hi) / hi_new        # repeats full price
    rows = []
    for n in ns:
        calls = [n / lo_new, n / hi_new]
        units = [n * per_lo, n * per_hi]
        rows.append({
            "matches": n, "calls": [round(x) for x in calls],
            "units": [round(x) for x in units],
            "hours_at_polite_rate": [round(x / pol.per_min / 60, 1)
                                     for x in units],
            "days_at_daily_unit_cap": [max(1, -(-round(x) //
                                                round(pol.daily_unit_cap)))
                                       for x in units],
            "raw_gz_MB": [round(n * g / 1e6, 1) for g in gz],
            "parsed_MB": round(n * per_match["parsed_bytes_per_match"] / 1e6,
                               1),
            "quotas": quotas(n)})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--key-tier", choices=sorted(DOC_LIMIT_PER_MIN),
                    default="basic")
    ap.add_argument("--daily-cap", type=int, default=250)
    ap.add_argument("--total-cap", type=int, default=250)
    ap.add_argument("--daily-unit-cap", type=float, default=2500)
    ap.add_argument("--total-unit-cap", type=float, default=2500)
    ap.add_argument("--max-matches", type=int, default=20)
    ap.add_argument("--list-size", type=int, default=10)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    s = sub.add_parser("seed")
    s.add_argument("--owners", action="store_true")
    s.add_argument("--leaderboard", action="store_true")
    s.add_argument("--pages", type=int, default=1)
    s.add_argument("--size", type=int, default=200)
    dr = sub.add_parser("dry-run")
    dr.add_argument("--details", type=int, default=20,
                    help="match records the dry run may build, at most 20")
    dr.add_argument("--probe-share", type=float, default=0.4,
                    help="of --details, kept for paging probes")
    c = sub.add_parser("crawl")
    c.add_argument("--max-requests", type=int, default=None)
    sub.add_parser("parse")
    me = sub.add_parser("measure-riot")
    me.add_argument("--out", default=None)
    me.add_argument("--record", action="store_true",
                    help="append the figures to the metrics log")
    mv = sub.add_parser("measure-v4")
    mv.add_argument("--record", action="store_true",
                    help="append the figures to the metrics log")
    pj = sub.add_parser("project")
    pj.add_argument("--units-per-record", type=float, default=None)
    pj.add_argument("--base-units", type=float, default=None)
    w = sub.add_parser("window")
    w.add_argument("--since", default=None)
    w.add_argument("--seasons", default=None)
    w.add_argument("--region", default=None)
    w.add_argument("--target", type=int, default=None)
    a = ap.parse_args(argv)

    store = Path(a.store)
    out = out_dir(store)
    spath = out / "state.json"
    state = State.load(spath)
    pol = Politeness(key_tier=a.key_tier, daily_cap=a.daily_cap,
                     total_cap=a.total_cap, max_matches=a.max_matches,
                     list_size=a.list_size, daily_unit_cap=a.daily_unit_cap,
                     total_unit_cap=a.total_unit_cap)
    key = read_key(store)

    def client() -> Client:
        return Client(key or "", state, pol, save=lambda: state.save(spath))
    try:
        if a.cmd == "status":
            have = {s: 0 for s in STRATA}
            for m in state.matches.values():
                if m.get("stratum") in have:
                    have[m["stratum"]] += 1
            q = quotas(state.target_matches)
            print(f"{VERSION}; key {'present' if key else 'absent'}; "
                  f"{pol.per_min:.0f} units/min of {pol.limit}, at most one "
                  f"call per {pol.interval_s:.1f} s; caps {pol.daily_cap} "
                  f"calls and {pol.daily_unit_cap:.0f} units a day, "
                  f"{pol.total_cap} calls and {pol.total_unit_cap:.0f} units "
                  f"in all, {pol.max_matches} matches")
            print(f"units: {state.units_total:.0f} total, "
                  f"{state.units_today():.0f} today, "
                  f"{state.units_unmeasured} calls charged their prediction;"
                  f" largest measured units per match "
                  f"{state.units_per_match_max}")
            print(f"requests: {state.requests_total} total, "
                  f"{state.requests_today()} today; matches stored "
                  f"{len(state.matches)}; duplicates seen "
                  f"{state.duplicates_seen}; out of scope "
                  f"{state.out_of_scope_seen}")
            print(f"window: since {state.since}, seasons "
                  f"{state.seasons or 'any'}, region {state.region}")
            visited = set(state.visited)
            print(f"frontier: {sum(f['puuid'] not in visited for f in state.frontier)}"
                  f" unvisited of {len(state.frontier)}; owners "
                  f"{sum(f.get('kind') == 'owner' for f in state.frontier)}")
            for s in STRATA:
                print(f"  {s:<10}{have[s]:>6} / {q[s]}")
            return 0
        if a.cmd == "window":
            if a.since:
                state.since = dt.date.fromisoformat(a.since).isoformat()
            if a.seasons is not None:
                state.seasons = [x for x in a.seasons.split(",") if x]
            if a.region:
                state.region = a.region
            if a.target:
                state.target_matches = a.target
            state.save(spath)
            print(f"window since {state.since}, seasons {state.seasons}, "
                  f"region {state.region}, target {state.target_matches}")
            return 0
        if a.cmd == "seed":
            n = 0
            if a.owners:
                n += seed_owners(state, store)
            if a.leaderboard:
                n += seed_leaderboard(client(), state, out, a.pages, a.size)
            state.save(spath)
            print(f"frontier +{n} players")
            return 0
        if a.cmd == "dry-run":
            # the player's accounts only: at most 20 match records built,
            # split between one list per account and paging probes
            details = max(0, min(a.details, 20))
            pol.total_cap = min(pol.total_cap, state.requests_total + 24)
            pol.total_unit_cap = min(pol.total_unit_cap,
                                     state.units_total + 120)
            cl = client()      # no key stops here, before anything is sent
            seed_owners(state, store)
            visited = set(state.visited)
            owners = [f for f in state.frontier if f.get("kind") == "owner"
                      and f["puuid"] not in visited]
            if not owners:
                print("dry run: no unvisited owner account")
                return 0
            per = details // len(owners)
            size = fit_size(cl, max(1, min(pol.list_size,
                                           round(per * (1 - a.probe_share)))))
            known = known_riot_matches(store)
            for i, f in enumerate(owners):
                c = list_player(cl, state, out, f, size, known)
                label = f.get("label") or f"owner{i}"
                print(f"  account {i + 1}: list of {size}: HTTP "
                      f"{c['status']}, {c.get('returned', 0)} returned, "
                      f"{c.get('new', 0)} new, {c.get('duplicate', 0)} held,"
                      f" {c.get('out_of_scope', 0)} out of scope; "
                      f"{cl.last.get('units')} units "
                      f"({cl.last.get('units_basis')})")
                if c["status"] != 200:
                    continue
                pr = probe_history(cl, state, out, f, size, c["returned"],
                                   per - c["returned"], known)
                state.probes[label] = pr
                state.save(spath)
                print(f"  account {i + 1}: competitive list pages past "
                      f"{pr['deeper_than']} matches, at most "
                      f"{pr['at_most']} ({len(pr['probes'])} probes)")
            state.save(spath)
            print(f"dry run: {state.requests_total} calls, "
                  f"{state.units_total:.0f} units, {len(state.matches)} "
                  f"matches in the sample")
            return 0
        if a.cmd == "crawl":
            r = crawl(client(), state, out, pol, known_riot_matches(store),
                      max_requests=a.max_requests)
            state.save(spath)
            print(f"crawl: {r}")
            return 0
        if a.cmd == "parse":
            ms = stored_matches(out, state)
            if not ms:
                print("no stored matches")
                return 0
            tables = parse_matches(ms, salt_of(out),
                                   set(owner_puuids(store).values()),
                                   known_riot_matches(store))
            sizes = write_tables(tables, out / "parsed" / PARSER_VERSION)
            print(f"parsed {len(ms)} matches: " + ", ".join(
                f"{k} {t.num_rows} rows" for k, t in tables.items())
                + f"; {sum(sizes.values()) / 1e3:.0f} KB")
            return 0
        if a.cmd == "measure-riot":
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import riot_ground_truth as rgt
            ref = rgt.Reference(store / "external" / "valorant-api",
                                fetch=False)
            recs = rgt.riot_records(store)
            ms = [riot_to_v4(d, ref) for d in recs.values()]
            bodies = [json.dumps({"status": 200, "data": m},
                                 separators=(",", ":")).encode() for m in ms]
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                where = Path(a.out) if a.out else Path(tmp)
                res = measure(ms, bodies, where, secrets.token_bytes(16),
                              set(owner_puuids(store).values()),
                              {m["metadata"]["match_id"] for m in ms})
            riot = [json.dumps(d["match"], separators=(",", ":")).encode()
                    for d in recs.values()]
            res["riot_raw_bytes_per_match"] = sum(map(len, riot)) / len(riot)
            res["riot_gz_bytes_per_match"] = sum(
                len(gzip.compress(b, compresslevel=9, mtime=0))
                for b in riot) / len(riot)
            res.update(measured_at=now_iso(), fetcher=VERSION,
                       parser=PARSER_VERSION)
            mpath = out / "measure" / "last.json"
            mpath.parent.mkdir(parents=True, exist_ok=True)
            mpath.write_text(json.dumps(res, indent=1), encoding="utf-8")
            print(json.dumps(res, indent=1))
            if a.record:
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
                from reticle import metrics
                n = res["matches"]
                vals = {k: round(res[k]) for k in (
                    "raw_bytes_per_match", "gz_bytes_per_match",
                    "parsed_bytes_per_match", "riot_raw_bytes_per_match",
                    "riot_gz_bytes_per_match")}
                vals.update(matches=n, kills=res["rows"]["kills"],
                            kill_positions=res["kill_positions"],
                            economy_rows=res["rows"]["economy"],
                            rounds=res["rows"]["rounds"])
                metrics.record("ladder_fetch", part="measure", values=vals,
                               deps={"fetcher": VERSION,
                                     "parser": PARSER_VERSION,
                                     "records": "external/riot"},
                               context={"source": "riot_to_v4 transcode"})
            return 0
        if a.cmd == "measure-v4":
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                res = measure_v4(out, Path(tmp), salt_of(out),
                                 set(owner_puuids(store).values()),
                                 known_riot_matches(store))
            res.update(measured_at=now_iso(), fetcher=VERSION,
                       parser=PARSER_VERSION)
            mpath = out / "measure" / "v4.json"
            mpath.parent.mkdir(parents=True, exist_ok=True)
            mpath.write_text(json.dumps(res, indent=1), encoding="utf-8")
            print(json.dumps({k: v for k, v in res.items()
                              if k != "units_by_call"}, indent=1))
            if a.record:
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
                from reticle import metrics
                vals = {k: round(res[k]) for k in (
                    "raw_bytes_per_match", "gz_bytes_per_match",
                    "parsed_bytes_per_match", "calls", "units")}
                for k in ("units_per_call", "units_per_empty_call",
                          "units_per_record", "units_per_record_list",
                          "units_per_record_max",
                          "kill_positions_per_kill"):
                    if res[k] is not None:
                        vals[k] = round(res[k], 2)
                vals.update(matches=res["matches"], records=res["records"],
                            calls_measured=res["calls_measured"],
                            kills=res["rows"]["kills"],
                            kill_positions=res["kill_positions"],
                            rounds=res["rows"]["rounds"])
                metrics.record("ladder_fetch", part="measure_v4",
                               values=vals,
                               deps={"fetcher": VERSION,
                                     "parser": PARSER_VERSION,
                                     "records": "external/ladder/henrikdev/v4"},
                               context={"source": "HenrikDev v4 dry run, the "
                                        "player's accounts"})
            return 0
        if a.cmd == "project":
            mpath = out / "measure" / "v4.json"
            if not mpath.exists():
                mpath = out / "measure" / "last.json"
            if not mpath.exists():
                print(f"no {mpath}; run measure-v4 or measure-riot first")
                return 2
            per = json.loads(mpath.read_text(encoding="utf-8"))
            print(f"from {mpath.name}; {pol.per_min:.0f} units/min, daily "
                  f"unit cap {pol.daily_unit_cap:.0f}; [low, high] brackets")
            print(json.dumps(projection(per, pol, a.units_per_record,
                                        a.base_units, pol.list_size),
                             indent=1))
            return 0
    except Stop as e:
        state.save(spath)
        print(f"stopped: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
