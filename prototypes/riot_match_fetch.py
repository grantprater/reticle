r"""Save the player's uncaptured Riot match records into the store.

The player runs this by hand, with the Riot client running and logged in to
one of the player's own accounts. No agent runs it.

    .\.venv\Scripts\python.exe prototypes\riot_match_fetch.py --account A --check
    .\.venv\Scripts\python.exe prototypes\riot_match_fetch.py --account A --dry-run
    .\.venv\Scripts\python.exe prototypes\riot_match_fetch.py --account A

`docs/MATCH_FETCH_KIT.md` holds the instructions for each account and the
Terms of Service exposure.

What it does
------------
1. Reads the Riot client's lockfile
   (`%LOCALAPPDATA%\Riot Games\Riot Client\Config\lockfile`, form
   `name:pid:port:password:protocol`), checks that the lockfile's process is
   alive, and asks the local client, on 127.0.0.1, for the logged-in
   account's access token, entitlement token and PUUID
   (`/entitlements/v1/token`).
2. Reads the game's build string from the `CI server version:` line of
   `%LOCALAPPDATA%\VALORANT\Saved\Logs\ShooterGame.log` and the shard from the
   `https://pd.<shard>.a.pvp.net` URLs in the same log.
3. Lists the account's match history
   (`pd.<shard>.a.pvp.net/match-history/v1/history/<puuid>`, 20 a page) and
   saves each page raw.
4. Downloads `match-details/v1/matches/<id>` for every listed match not
   already saved, oldest first, since the oldest age out first.

Two parts of this method are documented from the 2026-10-02 probe
(`docs/EXTERNAL_GROUND_TRUTH.md`): the PD endpoints, and the PD API answering
only with the game's build string in `X-Riot-ClientVersion` and a User-Agent
naming the tool. Two are added from the unofficial PD docs
(valapidocs.techchrism.me) and were never run here: taking the tokens from
the local client through the lockfile, and the `X-Riot-ClientPlatform`
header. The probe's own code is lost, so how it got its tokens is unknown.

What it writes
--------------
Under `<store>/external/riot-pd-v1/` (a store path, never the repository):

- `raw/<match>.json`: the response body, byte for byte;
- `provenance/<match>.json`: account label, PUUID, fetch time, endpoint,
  HTTP status, the response headers (with their `Date`), body SHA-256 and
  size, build string and shard; never a token;
- `history/<label>-<time>-<page>.json` and its `.provenance.json`;
- `accounts.jsonl`: append-only label-to-PUUID bindings; a label already bound
  to another PUUID stops the run, so a forgotten account switch cannot
  mislabel records;
- `fetch_log.jsonl`: append-only, one line per request outcome.

It skips every match whose ID names a file in `<store>/external/riot/` (the
22 captured matches, `{"probe", "match"}` wrapped) or in `raw/`, and every
match an earlier run logged as 404 (`--retry-missing` asks again). It never
overwrites: a file is written to `.part`, then hard-linked to its final name,
which fails if the name exists. A record's sidecar is linked before its body,
so a crash leaves at worst a sidecar without a body; the rerun refetches that
match and renames the orphan sidecar `<match>.orphan-<time>.json`, logging
the rename. A rerun resumes where the last stopped.

Rate and refusals
-----------------
One PD request per `--interval` seconds (default 2.5). HTTP 429 waits the
`Retry-After` seconds (60 if absent) and retries up to three times, then
stops. HTTP 401 or 403 stops the run (stale token or build string). A 404 is
logged and skipped: the record is gone or never existed. A network error
(refused connection, DNS failure, timeout) stops the run with its reason.

Hosts
-----
The script builds URLs for two hosts only, 127.0.0.1 and
`pd.<shard>.a.pvp.net`, and refuses to send a PD request to any other. It
follows no redirect: a 3xx reply stops the run, so the tokens never go to a
host the reply names. It ignores the system's proxy settings and connects
directly.

Requests
--------
`--check` reads local files only: the lockfile (its PID, to see whether the
client runs), the game log and the store; it sends nothing. `--dry-run` sends
one request to the local client, then one PD history request per 20 listed
matches (three for a 47-match history), and writes nothing. A full run sends
those, then one PD request per record fetched.

Riot's records are an external witness, never a reader's prior; this tool
decides nothing about the game.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

if sys.platform == "win32":  # Below Normal priority, as every script here
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(
            ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass

KIT = "riot_match_fetch"
KIT_VERSION = "1.0.0"
USER_AGENT = f"reticle-{KIT}/{KIT_VERSION} (personal match archive)"
OUT_NAME = "riot-pd-v1"
PAGE = 20
PLATFORM = base64.b64encode(json.dumps({
    "platformType": "PC", "platformOS": "Windows",
    "platformOSVersion": "10.0.19042.1.256.64bit",
    "platformChipset": "Unknown"}).encode()).decode()
LOCAL = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
LOCKFILE = Path(LOCAL) / "Riot Games" / "Riot Client" / "Config" / "lockfile"
GAME_LOG = Path(LOCAL) / "VALORANT" / "Saved" / "Logs" / "ShooterGame.log"
STORE = Path.home() / "reticle-store"
LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MATCH_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# response headers never stored
DROP_HEADERS = {"set-cookie", "authorization", "x-riot-entitlements-jwt"}


class FetchStop(RuntimeError):
    """Stops the run; files already written stay, and a rerun resumes."""


# ---------------------------------------------------------------- local inputs

def lockfile_pid(text: str) -> int:
    """The PID field of the lockfile, read without keeping the password."""
    parts = text.strip().split(":")
    if len(parts) != 5 or not parts[1].isdigit():
        raise FetchStop("lockfile is not name:pid:port:password:protocol")
    return int(parts[1])


def process_image(pid: int) -> str | None:
    """The executable path of a live process `pid`, "" if unnamed, or None.

    Reads the local process table only; it sends nothing.
    """
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            return ""
        return ""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not h:   # access denied means a live process we may not inspect
        return "" if ctypes.get_last_error() == 5 else None
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)) \
                or code.value != 259:          # STILL_ACTIVE
            return None
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return ""
    finally:
        k32.CloseHandle(h)


def read_lockfile(text: str) -> dict:
    """Parse the Riot client lockfile, `name:pid:port:password:protocol`."""
    parts = text.strip().split(":")
    if len(parts) != 5 or not parts[2].isdigit():
        raise FetchStop("lockfile is not name:pid:port:password:protocol; "
                        "is the Riot client running?")
    name, pid, port, password, protocol = parts
    return {"name": name, "pid": int(pid), "port": int(port),
            "password": password, "protocol": protocol}


def read_game_log(text: str) -> dict:
    """The last build string and the PD shards named in ShooterGame.log."""
    versions = re.findall(r"CI server version:\s*(\S+)", text)
    shards = sorted(set(re.findall(r"https://pd\.([a-z0-9-]+)\.a\.pvp\.net",
                                   text)))
    return {"client_version": versions[-1] if versions else None,
            "shards": shards}


def choose_shard(shards: list[str], override: str | None) -> str:
    if override:
        if not re.fullmatch(r"[a-z0-9-]{2,8}", override):
            raise FetchStop(f"--shard {override!r} is not a shard name")
        return override
    if len(shards) == 1:
        return shards[0]
    if not shards:
        raise FetchStop("ShooterGame.log names no pd.<shard>.a.pvp.net; "
                        "launch VALORANT once on this account, or pass --shard")
    raise FetchStop(f"ShooterGame.log names several shards {shards}; "
                    "pass --shard")


# ---------------------------------------------------------------- HTTP

@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


Opener = Callable[[str, dict], Response]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Follow no redirect: urllib would resend the tokens to its target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None   # urllib then raises HTTPError with the 3xx code


def build_opener(host: str) -> urllib.request.OpenerDirector:
    """A direct, redirect-refusing opener; certificate checks are off for
    127.0.0.1 only, whose Riot client presents a self-signed certificate."""
    ctx = ssl.create_default_context()
    if host == "127.0.0.1":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect(),
        urllib.request.HTTPSHandler(context=ctx))


def urllib_opener(url: str, headers: dict) -> Response:
    """GET `url`; an HTTP error returns its status, a network error stops."""
    host = urllib.parse.urlsplit(url).hostname or ""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with build_opener(host).open(req, timeout=30) as r:
            return Response(r.status, dict(r.headers.items()), r.read())
    except urllib.error.HTTPError as e:
        return Response(e.code, dict((e.headers or {}).items()), e.read())
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        where = "the Riot client" if host == "127.0.0.1" else host
        raise FetchStop(f"could not reach {where}: {reason}; files already "
                        "written stay, and a rerun resumes") from None


def _allowed(url: str, shard: str | None) -> bool:
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https":
        return False
    if p.hostname == "127.0.0.1":
        return True
    return shard is not None and p.hostname == f"pd.{shard}.a.pvp.net"


def local_tokens(lock: dict, opener: Opener) -> dict:
    """Ask the running Riot client for the account's tokens and PUUID."""
    url = f"https://127.0.0.1:{lock['port']}/entitlements/v1/token"
    basic = base64.b64encode(f"riot:{lock['password']}".encode()).decode()
    r = opener(url, {"Authorization": f"Basic {basic}",
                     "User-Agent": USER_AGENT})
    if 300 <= r.status < 400:
        raise FetchStop(f"local client redirected ({r.status}); refusing")
    if r.status != 200:
        raise FetchStop(f"local client answered {r.status} for its tokens; "
                        "log in to the Riot client and rerun")
    d = json.loads(r.body)
    for k in ("accessToken", "token", "subject"):
        if not d.get(k):
            raise FetchStop(f"local client's token reply lacks {k!r}")
    return {"access": d["accessToken"], "entitlement": d["token"],
            "puuid": d["subject"]}


class Pd:
    """The PD host, one request per `interval` seconds."""

    def __init__(self, shard: str, client_version: str, tokens: dict,
                 opener: Opener, interval: float = 2.5,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 max_429: int = 3):
        self.shard, self.client_version = shard, client_version
        self.tokens, self.opener = tokens, opener
        self.interval, self.sleep, self.clock = interval, sleep, clock
        self.max_429 = max_429
        self._last: float | None = None
        self.base = f"https://pd.{shard}.a.pvp.net"

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.tokens['access']}",
                "X-Riot-Entitlements-JWT": self.tokens["entitlement"],
                "X-Riot-ClientVersion": self.client_version,
                "X-Riot-ClientPlatform": PLATFORM,
                "User-Agent": USER_AGENT}

    def get(self, path: str) -> tuple[str, Response]:
        url = self.base + path
        if not _allowed(url, self.shard):
            raise FetchStop(f"refusing host of {url}")
        for attempt in range(self.max_429 + 1):
            if self._last is not None:
                wait = self.interval - (self.clock() - self._last)
                if wait > 0:
                    self.sleep(wait)
            r = self.opener(url, self.headers())
            self._last = self.clock()
            if 300 <= r.status < 400:
                raise FetchStop(
                    f"{path} answered {r.status}, a redirect to "
                    f"{_header(r.headers, 'Location')!r}; the kit follows "
                    "none, so the tokens went nowhere else")
            if r.status != 429:
                return url, r
            ra = _header(r.headers, "Retry-After")
            secs = float(ra) if ra and ra.strip().isdigit() else 60.0
            if attempt < self.max_429:
                print(f"  429 rate limited; waiting {secs:.0f} s")
                self.sleep(secs)
        raise FetchStop(f"HTTP 429 {self.max_429 + 1} times on {path}; "
                        "rerun later, it resumes")


def _header(headers: dict, name: str) -> str | None:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


def kept_headers(headers: dict) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in DROP_HEADERS}


# ---------------------------------------------------------------- store

def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat()


def write_new(path: Path, data: bytes) -> None:
    """Write `data` at `path`; raise FileExistsError if `path` exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    part = path.with_name(path.name + ".part")
    with open(part, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.link(part, path)   # fails, on NTFS and POSIX, if `path` exists
    finally:
        part.unlink()


def append_line(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def known_matches(store: Path, out: Path) -> set[str]:
    """Match IDs already saved: the captured records and earlier runs."""
    ids = {p.stem for p in (store / "external" / "riot").glob("*.json")}
    ids |= {p.stem for p in (out / "raw").glob("*.json")}
    return {i for i in ids if MATCH_RE.match(i)}


def missing_matches(out: Path) -> set[str]:
    """Match IDs an earlier run logged as 404."""
    path = out / "fetch_log.jsonl"
    if not path.exists():
        return set()
    rows = [json.loads(s) for s in path.read_text(encoding="utf-8")
            .splitlines() if s.strip()]
    return {r["match"] for r in rows if r.get("outcome") == "missing"}


def bind_account(out: Path, label: str, puuid: str, write: bool) -> None:
    """Refuse a label already bound to another PUUID, and the reverse."""
    path = out / "accounts.jsonl"
    rows = []
    if path.exists():
        rows = [json.loads(s) for s in path.read_text(encoding="utf-8")
                .splitlines() if s.strip()]
    for r in rows:
        if r["label"] == label and r["puuid"] != puuid:
            raise FetchStop(f"label {label!r} is bound to another account; "
                            "is the Riot client logged in to the right one?")
        if r["puuid"] == puuid and r["label"] != label:
            raise FetchStop(f"this account is already labelled "
                            f"{r['label']!r}; rerun with --account "
                            f"{r['label']}")
    if write and not any(r["label"] == label for r in rows):
        append_line(path, {"label": label, "puuid": puuid,
                           "bound_at": now_iso(), "kit_version": KIT_VERSION})


def sidecar(label: str, puuid: str, url: str, r: Response, pd: Pd,
               fetched_at: str, **extra) -> dict:
    return {"kit": KIT, "kit_version": KIT_VERSION, "account_label": label,
            "puuid": puuid, "endpoint": url, "method": "GET",
            "fetched_at": fetched_at, "http_status": r.status,
            "response_date": _header(r.headers, "Date"),
            "response_headers": kept_headers(r.headers),
            "body_sha256": hashlib.sha256(r.body).hexdigest(),
            "body_bytes": len(r.body), "client_version": pd.client_version,
            "shard": pd.shard, "user_agent": USER_AGENT, **extra}


# ---------------------------------------------------------------- the run

def list_history(pd: Pd, puuid: str, label: str, out: Path | None,
                 stamp: str) -> list[dict]:
    """Every history entry, paging 20 at a time; saves pages if `out`."""
    entries, start, total, page = [], 0, None, 0
    while total is None or start < total:
        path = (f"/match-history/v1/history/{puuid}"
                f"?startIndex={start}&endIndex={start + PAGE}")
        fetched_at = now_iso()
        url, r = pd.get(path)
        if r.status in (401, 403):
            raise FetchStop(f"history answered {r.status}; the token or the "
                            "build string is stale: relaunch VALORANT once, "
                            "close it, and rerun")
        if r.status != 200:
            raise FetchStop(f"history answered {r.status}")
        d = json.loads(r.body)
        if out is not None:
            name = f"{label}-{stamp}-{page:02d}"
            write_new(out / "history" / f"{name}.provenance.json",
                      json.dumps(sidecar(label, puuid, url, r, pd,
                                         fetched_at), indent=1).encode())
            write_new(out / "history" / f"{name}.json", r.body)
        got = d.get("History") if isinstance(d, dict) else None
        if (not isinstance(got, list) or "Total" not in d
                or not all(isinstance(e, dict) and isinstance(
                    e.get("MatchID"), str) for e in got)):
            keys = sorted(d) if isinstance(d, dict) else type(d).__name__
            raise FetchStop(f"history reply has an unexpected shape (keys "
                            f"{keys}); the kit assumed History[].MatchID "
                            "and Total from unofficial docs")
        entries += got
        total = int(d["Total"])
        if not got:
            break
        start += len(got)
        page += 1
    seen, uniq = set(), []
    for e in entries:
        if e["MatchID"] not in seen:
            seen.add(e["MatchID"])
            uniq.append(e)
    return uniq


def plan(entries: list[dict], known: set[str]) -> list[dict]:
    """Uncaptured entries, oldest first."""
    todo = [e for e in entries if e["MatchID"] not in known
            and MATCH_RE.match(e["MatchID"])]
    return sorted(todo, key=lambda e: e.get("GameStartTime", 0))


def _when(e: dict) -> str:
    ms = e.get("GameStartTime")
    if not ms:
        return "?"
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC")


def fetch(pd: Pd, todo: list[dict], label: str, puuid: str, out: Path,
          limit: int | None = None) -> dict:
    """Download each planned record; returns counts by outcome."""
    counts = {"saved": 0, "skipped_existing": 0, "missing": 0, "failed": 0,
              "orphan_sidecars_moved": 0}
    log = out / "fetch_log.jsonl"
    for i, e in enumerate(todo[:limit] if limit else todo):
        mid = e["MatchID"]
        raw = out / "raw" / f"{mid}.json"
        if raw.exists():
            counts["skipped_existing"] += 1
            continue
        fetched_at = now_iso()
        url, r = pd.get(f"/match-details/v1/matches/{mid}")
        row = {"match": mid, "account_label": label, "fetched_at": fetched_at,
               "http_status": r.status, "response_date":
               _header(r.headers, "Date"), "endpoint": url}
        if r.status in (401, 403):
            append_line(log, {**row, "outcome": "stopped"})
            raise FetchStop(f"match-details answered {r.status}; the token "
                            "expired or the build string is stale; rerun")
        if r.status == 404:
            append_line(log, {**row, "outcome": "missing"})
            counts["missing"] += 1
            print(f"  [{i + 1}/{len(todo)}] {_when(e)} 404, not found")
            continue
        if r.status != 200:
            append_line(log, {**row, "outcome": "failed"})
            counts["failed"] += 1
            print(f"  [{i + 1}/{len(todo)}] {_when(e)} HTTP {r.status}")
            continue
        try:
            json.loads(r.body)
        except ValueError:
            append_line(log, {**row, "outcome": "not_json"})
            counts["failed"] += 1
            continue
        prov = out / "provenance" / f"{mid}.json"
        if prov.exists():   # an earlier run stopped between the two writes
            stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
            orphan = prov.with_name(f"{mid}.orphan-{stamp}.json")
            os.rename(prov, orphan)   # fails rather than overwrite
            append_line(log, {**row, "outcome": "orphan_sidecar_moved",
                              "moved_to": orphan.name})
            counts["orphan_sidecars_moved"] += 1
        write_new(prov, json.dumps(sidecar(
            label, puuid, url, r, pd, fetched_at,
            match_id=mid, history_entry=e), indent=1).encode())
        write_new(raw, r.body)
        append_line(log, {**row, "outcome": "saved",
                          "body_sha256": hashlib.sha256(r.body).hexdigest()})
        counts["saved"] += 1
        print(f"  [{i + 1}/{len(todo)}] {_when(e)} saved "
              f"({len(r.body) // 1024} KiB)")
    return counts


def run_fetch(args, opener: Opener = urllib_opener,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        alive: Callable[[int], str | None] = process_image) -> int:
    label = args.account
    if not LABEL_RE.match(label):
        raise FetchStop("--account takes 1-32 letters, digits, - or _")
    store = Path(args.store)
    out = store / "external" / OUT_NAME
    lock_path, log_path = Path(args.lockfile), Path(args.game_log)
    if not lock_path.exists():
        raise FetchStop(f"no lockfile at {lock_path}; start the Riot client "
                        "and log in")
    if not log_path.exists():
        raise FetchStop(f"no game log at {log_path}; launch VALORANT once")
    pid = lockfile_pid(lock_path.read_text(encoding="utf-8"))
    image = alive(pid)
    info = read_game_log(log_path.read_text(encoding="utf-8",
                                            errors="replace"))
    if not info["client_version"]:
        raise FetchStop("ShooterGame.log has no 'CI server version:' line; "
                        "launch VALORANT once, then close it")
    shard = choose_shard(info["shards"], args.shard)
    known = known_matches(store, out)
    missing = missing_matches(out)
    print(f"build {info['client_version']}, shard {shard}, "
          f"{len(known)} match records already saved, "
          f"{len(missing)} logged as 404")
    if image is None:
        state = (f"not running: the lockfile names PID {pid}, which is "
                 "gone (a stale lockfile)")
    else:
        state = f"running (PID {pid}{', ' + Path(image).name if image else ''})"
    print(f"Riot client: {state}")
    if args.check:
        print("check only: sent nothing")
        return 0
    if image is None:
        raise FetchStop(f"Riot client {state}; start it and log in")
    lock = read_lockfile(lock_path.read_text(encoding="utf-8"))
    tokens = local_tokens(lock, opener)
    puuid = tokens["puuid"]
    bind_account(out, label, puuid, write=not args.dry_run)
    pd = Pd(shard, info["client_version"], tokens, opener,
            interval=args.interval, sleep=sleep, clock=clock)
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    entries = list_history(pd, puuid, label,
                           None if args.dry_run else out, stamp)
    todo = plan(entries, known if getattr(args, "retry_missing", False)
                else known | missing)
    span = (f"{_when(min(entries, key=lambda e: e.get('GameStartTime', 0)))}"
            f" to {_when(max(entries, key=lambda e: e.get('GameStartTime', 0)))}"
            if entries else "empty")
    print(f"account {label}: history lists {len(entries)} matches ({span}); "
          f"{len(todo)} not yet saved")
    if args.dry_run:
        for e in todo[:args.limit] if args.limit else todo:
            print(f"  would fetch {e['MatchID']}  {_when(e)}  "
                  f"queue={e.get('QueueID', '?') or '?'}")
        print("dry run: wrote nothing")
        return 0
    counts = fetch(pd, todo, label, puuid, out, args.limit)
    print(f"account {label}: " + ", ".join(f"{k} {v}" for k, v in
                                           counts.items()))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--account", required=True,
                    help="the player's label for the logged-in account, "
                         "e.g. A, B or C; bound to its PUUID on first use")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="read the local files only; send nothing")
    mode.add_argument("--dry-run", action="store_true",
                      help="ask the local client for tokens and list the "
                           "history from Riot (one PD request per 20 "
                           "matches); print what would be fetched; write "
                           "nothing")
    ap.add_argument("--retry-missing", action="store_true",
                    help="ask again for matches an earlier run logged as 404")
    ap.add_argument("--limit", type=int, default=None,
                    help="fetch at most N records this run")
    ap.add_argument("--interval", type=float, default=2.5,
                    help="seconds between PD requests (minimum 1.0)")
    ap.add_argument("--shard", default=None,
                    help="PD shard (na, eu, ap, kr) when the log names several")
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--lockfile", default=str(LOCKFILE))
    ap.add_argument("--game-log", default=str(GAME_LOG))
    args = ap.parse_args(argv)
    args.interval = max(1.0, args.interval)
    try:
        return run_fetch(args)
    except FetchStop as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
