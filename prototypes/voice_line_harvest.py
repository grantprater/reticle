"""Harvest ability-cast voice lines from each agent's wiki Quotes page.

    .\\.venv\\Scripts\\python.exe prototypes\\voice_line_harvest.py harvest [--agents A,B] [--dry-run]
    .\\.venv\\Scripts\\python.exe prototypes\\voice_line_harvest.py report
    .\\.venv\\Scripts\\python.exe prototypes\\voice_line_harvest.py ult-ready [--agents A,B] [--dry-run] [--record]

Why this exists
----------------
`ability_reference.py` already harvests the 56 ultimate-cast lines (ally and
enemy) as matched-filter references -- the wiki's own words for why: *"a
matched filter needs a reference cut at a KNOWN cast time"*. That covers one
line per ultimate. Every ability also has a per-agent Quotes page
(`<Agent>/Quotes`) that lists the cast/activate/end lines for EVERY ability,
often several distinct lines per ability, which is the reference set a
matched filter for basic and signature abilities needs and the ultimate
harvest does not supply.

This module fetches those pages, keeps only the sections about ability use
(cast, activate, deactivate, recall, and the like -- never match-start,
round, kill, or other non-ability barks), and downloads the audio.

The 403 this module works around
---------------------------------
Direct `https://valorant.fandom.com/wiki/<title>` fetches, the style
`ability_reference.py` uses, now return HTTP 403 from this network for EVERY
page tried, including the one `ability_reference.py` itself already depends
on (`wiki/Abilities`) -- so this is a platform-wide tightening since the
2026-09-04 harvest, not a Quotes-page peculiarity. The MediaWiki parse API
(`api.php?action=parse&prop=text`) on the same host answers normally and
returns the same rendered HTML `_rows`/`_text` already know how to read, so
every page fetch here goes through it instead of a raw `/wiki/` GET. Direct
CDN asset fetches (`static.wikia.nocookie.net/.../*.mp3`) are unaffected and
use the same plain GET `ability_reference._download` does.

Page structure, read off Reyna/Killjoy/Viper/Miks/Veto's Quotes pages
-----------------------------------------------------------------------
One `<h2>` section titled "Abilities" holds one `<h3>` per ability (named as
the wiki names it: "Leer", "Fuel", "Turret", ...). Most abilities then have
one `<h4>` per action ("Cast", "Activate", "Deactivate", "Recall",
"Ally Cast", "Enemy Cast", "Destroyed", "Kill", "Triggered", ...); an ability
with exactly one category of line omits the redundant `<h4>` and lists its
`<li>` lines directly under the `<h3>` -- treated here as an implicit "Cast"
section. Each `<li>` holds one or more `<audio src=...>` tags (redundant
takes of the SAME line) followed by the line's text, sometimes with a nested
`<ul><li>(translation)</li></ul>` for a non-English line. A few ultimates
(Reyna's Empress, Veto's Evolution) push their real content to a
`<Agent>/Quotes/<Subpage>` page reached by a "Main article:" link inside the
ability's own `<h3>`; that subpage repeats the OTHER abilities' sections
verbatim (same CDN URLs) and adds the subpage-only ones, so this module
follows every such link and lets URL-level dedup discard the repeats.

What counts as ability use, and what does not
------------------------------------------------
Scoping to the "Abilities" `<h2>` already excludes the top-level Match
Start / Round Start / Kill / Headshot / Melee / Round End / Ping / Radio /
Unused / Removed sections that sit beside it. Two categories still nest
INSIDE an ability's own `<h3>` and are not cast/equip/end lines: reactions to
the ability's own outcome ("Destroyed", "Triggered" for a trap set off by an
enemy, "Kill", "Kill assist", "Detain(ed)"). `_is_ability_use` keeps a section
whose name contains a casting/activating/ending word and excludes one that
names a kill, an assist, a spotted/wounded/healed reaction, or a deployable
being destroyed or detaining -- ability effects, not the agent using the
ability. This is a keyword classifier over ~30 agents' worth of section
names the wiki did not standardize, so it is a measured approximation, not a
certainty; `report` prints the section names it kept per ability so a reader
can check the calls.

Rate limit and provenance
--------------------------
One request per second, page fetches and asset downloads alike, enforced by
a single module-level throttle; a 429 or 5xx backs off and retries rather
than failing the run. `index.json` records one entry per downloaded file
(agent, ability, section, the line as printed, the source CDN url, the local
file name, its byte count, and the fetch time) and is also the skip list: a
source url already in it is never re-fetched, so a second run only pulls
what a first run missed.

Ult-ready lines (`ult-ready`)
-----------------------------
No page lists a ready line under its ultimate's heading. Every agent's page
lists it as one reply of the Ultimate Status radio command, under Radio
Commands > Menu and Wheel Index > "Ultimate Status", beside a not-ready and an
almost-ready reply, each with two takes (all 29 pages, 2026-09-27).
`section_items` finds a heading by name at any level; `ult_status_state`
names each reply by its words, and a take whose wiki file name
(`SkyeUltReady1.mp3`) names another reply is refused, not guessed. The ready
takes go to `voicelines/ult_ready/<Agent>__ultimate-status__<n>.mp3`, n
counting the ready takes in page order, with an `index.json` of the cast
index's record schema; `ability` is the agent's ultimate as the cast index
names it. A url already indexed is skipped, a file already present is kept,
and a file that holds another take refuses the new one: nothing is
overwritten. `--record` records the counts as `voice_line_harvest/ult-ready`.
"""

from __future__ import annotations

import argparse
import ctypes
import html as _html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_reference as ar  # noqa: E402  (reuse _text/_slug/UA, same tree)

STORE = Path.home() / "reticle-store"
VOICE = STORE / "reference" / "assets" / "voicelines"
CASTS = VOICE / "casts"
INDEX = CASTS / "index.json"
ULT_READY = VOICE / "ult_ready"
ULT_READY_INDEX = ULT_READY / "index.json"

API = "https://valorant.fandom.com/api.php"
UA = ar.UA

# Agents to cover, corpus lineups first, in the order the task specifies.
# The wiki page differs from the in-game display name only for KAY/O.
AGENT_ORDER = [
    "Reyna", "Clove", "Sova", "Phoenix", "Miks", "Jett", "Sage", "Omen",
    "Skye", "Raze", "Breach", "Chamber", "Waylay", "Neon", "Yoru",
    "Deadlock", "Gekko", "Fade", "Iso", "Killjoy", "Cypher", "KAY/O",
    "Tejo", "Astra", "Brimstone", "Harbor", "Veto", "Viper", "Vyse",
]
WIKI_PAGE_OVERRIDE = {"KAY/O": "KAYO/Quotes"}

# Section names, normalized to lowercase, that mark a line the agent speaks
# while casting/activating/ending an ability -- never a reaction to its
# outcome (kill, destroyed, detain, spotted, ...), which stays excluded even
# when nested under the ability's own heading.
ABILITY_USE_HINTS = (
    "cast", "activate", "deactivate", "equip", "unequip", "recall",
    "detonate", "trigger", "deploy", "throw", "summon", "resummon",
    "dismiss", "arm", "form", "pulse", "place", "teleport", "scan",
    "release", "unleash", "toggle", "prime", "channel", "charge",
    "launch", "fire", "flash", "seal", "reveal", "swap",
)
NON_ABILITY_HINTS = (
    "kill", "assist", "death", "spot", "wound", "heal", "headshot",
    "melee", "defuse", "destroyed", "detain", "mvp", "reload",
    "wipe", "elimination",
)

ABILITIES_HEAD_IDS = ("Abilities", "Ability_Specific_Quotes", "Ability-Specific_Quotes")
HEAD_RE = re.compile(
    r'<h([34])>(?:<span id="[^"]*"></span>)?'
    r'<span class="mw-headline"[^>]*>(.*?)</span><span class="mw-editsection"',
    re.S)
AUDIO_SRC_RE = re.compile(r'<audio[^>]+src="([^"]+)"')
MAIN_ARTICLE_RE = re.compile(r'Main article:\s*<a href="/wiki/([^"#]+)')
#: A heading at any level, anchored on its edit link as HEAD_RE is.
ANY_HEAD_RE = re.compile(
    r'<h([2-5])>(?:<span id="[^"]*"></span>)?'
    r'<span class="mw-headline"[^>]*>(.*?)</span><span class="mw-editsection"',
    re.S)
#: The heading that lists the ult-ready line on every agent's page: one reply
#: of the Ultimate Status radio command (Radio Commands > Menu and Wheel Index).
ULT_STATUS_SECTION = "Ultimate Status"
#: The reply each of the wiki's file-name tags names.
STATUS_TAGS = {"UltReady": "ready", "UltAlmost": "almost", "UltDown": "not"}


class HarvestError(RuntimeError):
    """A source did not answer. Raised at the cause so the caller can say which."""


# ---------------------------------------------------------------- throttle


_last_request = [0.0]
MIN_INTERVAL = 1.0  # one request per second, page fetch or asset alike


def _throttle() -> None:
    now = time.monotonic()
    wait = _last_request[0] + MIN_INTERVAL - now
    if wait > 0:
        time.sleep(wait)
    _last_request[0] = time.monotonic()


def _lower_priority() -> None:
    """Below Normal, single logical thread of CPU work. Network-bound; this
    is a courtesy to the user's own jobs on the same machine, not a need."""
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    if sys.platform == "win32":
        try:
            BELOW_NORMAL = 0x00004000
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL)
        except Exception:  # noqa: BLE001 - best effort, never fatal
            pass


# ---------------------------------------------------------------- fetch


def _api_parse(title: str, tries: int = 5) -> str:
    """Rendered HTML of a wiki page via the MediaWiki parse API.

    Direct `/wiki/<title>` fetches return 403 from this network (see the
    module docstring); this endpoint on the same host still answers. Retries
    with backoff on 429/5xx and on transient errors.
    """
    url = f"{API}?action=parse&page={urllib.parse.quote(title, safe='')}&format=json&prop=text"
    last = None
    for i in range(tries):
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            data = json.loads(body)
            if "error" in data:
                raise HarvestError(f"{title}: {data['error'].get('info')}")
            return data["parse"]["text"]["*"]
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 429 or e.code >= 500:
                time.sleep(5.0 * (i + 1))
                continue
            raise HarvestError(f"{title}: {last}") from e
        except HarvestError:
            raise
        except Exception as e:  # noqa: BLE001 - reported, not swallowed
            last = repr(e)
            time.sleep(2.0 * (i + 1))
    raise HarvestError(f"{title}: {last}")


def _opensearch(term: str, limit: int = 20) -> list[str]:
    url = f"{API}?action=opensearch&search={urllib.parse.quote(term)}&format=json&limit={limit}"
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return data[1] if len(data) > 1 else []


def _resolve_quotes_page(agent: str) -> str | None:
    """`<Agent>/Quotes`, the wiki's override, or a discovered match."""
    if agent in WIKI_PAGE_OVERRIDE:
        return WIKI_PAGE_OVERRIDE[agent]
    guess = f"{agent}/Quotes"
    try:
        _api_parse(guess, tries=1)
        return guess
    except HarvestError:
        pass
    for title in _opensearch(agent):
        if title.lower() == guess.lower() or (
                title.lower().endswith("/quotes")
                and agent.lower().replace("/", "") in title.lower().replace("/", "")):
            return title
    return None


def _download_asset(url: str, dest: Path, tries: int = 5) -> int:
    last = None
    for i in range(tries):
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            return len(body)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 429 or e.code >= 500:
                time.sleep(5.0 * (i + 1))
                continue
            raise HarvestError(f"{url}: {last}") from e
        except Exception as e:  # noqa: BLE001
            last = repr(e)
            time.sleep(2.0 * (i + 1))
    raise HarvestError(f"{url}: {last}")


# ---------------------------------------------------------------- parse


def _is_ability_use(section_name: str) -> bool:
    n = section_name.lower()
    if any(k in n for k in NON_ABILITY_HINTS):
        return False
    return any(k in n for k in ABILITY_USE_HINTS)


def _li_blocks(container: str) -> list[str]:
    """Top-level `<li>` bodies, nested `<ul><li>` (a translation gloss) kept
    inside the body rather than split into its own item."""
    tag_re = re.compile(r'<li\b[^>]*>|</li>')
    depth = 0
    start = None
    out = []
    for m in tag_re.finditer(container):
        if m.group(0).startswith("<li"):
            if depth == 0:
                start = m.end()
            depth += 1
        else:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(container[start:m.start()])
                start = None
    return out


def _line_text(block: str) -> str:
    """The line as printed: quoted text plus a nested translation, if any,
    with the audio-button markup and its bare file-page URL removed."""
    nested = ""
    m = re.search(r"<ul>(.*)</ul>", block, re.S)
    main = block
    if m:
        nested = ar._text(m.group(1))
        main = block[:m.start()] + block[m.end():]
    txt = ar._text(main)
    txt = re.sub(r"https://valorant\.fandom\.com/wiki/File:\S*?\.(?:mp3|ogg)", "", txt)
    txt = txt.replace("\xa0", " ")
    txt = re.sub(r"\s+", " ", txt).strip()
    if nested:
        txt = f"{txt} {nested}".strip()
    return txt


def _abilities_region(html: str) -> tuple[int, int] | None:
    for head_id in ABILITIES_HEAD_IDS:
        m = re.search(rf'<h2><span class="mw-headline" id="{head_id}">', html)
        if m:
            nxt = re.search(r"<h2>", html[m.end():])
            end = m.end() + nxt.start() if nxt else len(html)
            return m.start(), end
    return None


def parse_page(html: str) -> tuple[list[dict], dict[tuple[str, str], int], list[str]]:
    """Ability-use items, {(ability, section): excluded-line-count}, subpages.

    An item is {"ability", "section", "text", "urls"} for one `<li>`. Counts
    key on the RAW audio-file count, matching what `report` calls a line's
    number of takes; subpages are wiki page titles found via a "Main
    article:" link inside the Abilities section, to be parsed the same way.
    """
    region = _abilities_region(html)
    items: list[dict] = []
    excluded: dict[tuple[str, str], int] = {}
    subpages: list[str] = []
    if region is None:
        return items, excluded, subpages
    start, end = region
    body_all = html[start:end]
    heads = list(HEAD_RE.finditer(body_all))
    cur_ability = None
    cur_section = None
    for i, head in enumerate(heads):
        level = head.group(1)
        name = ar._text(head.group(2))
        body_start = head.end()
        body_end = heads[i + 1].start() if i + 1 < len(heads) else len(body_all)
        body = body_all[body_start:body_end]
        if level == "3":
            cur_ability = name
            cur_section = None
        else:
            cur_section = name
        for sp in MAIN_ARTICLE_RE.findall(body):
            title = _html.unescape(sp).replace("_", " ")
            if title not in subpages:
                subpages.append(title)
        blocks = _li_blocks(body)
        if not blocks or cur_ability is None:
            continue
        section_name = cur_section or "Cast"
        # An h3 with no h4 child is normally a single-line ability (Reyna's
        # Devour); one whose own name parenthetically cross-references OTHER
        # abilities ("Deafen and Nearsight whispers (Prowler, Seize and
        # Nightfall)", Fade) is a shared reaction bark, not a cast line, and
        # no genuine ability name in the roster contains "(".
        use = _is_ability_use(section_name) and not (cur_section is None and "(" in cur_ability)
        for b in blocks:
            urls = AUDIO_SRC_RE.findall(b)
            if not urls:
                continue
            if use:
                items.append({"ability": cur_ability, "section": section_name,
                              "text": _line_text(b), "urls": urls})
            else:
                key = (cur_ability, section_name)
                excluded[key] = excluded.get(key, 0) + len(urls)
    return items, excluded, subpages


def _other_line_count(html: str, region: tuple[int, int] | None) -> int:
    """`<li>` count outside the Abilities section, past the table of contents
    (which is itself one long `<li>` list) -- the "count them, leave them"
    tally for match-start/round/kill/ping/etc. sections."""
    body = html[html.find("<h2"):] if "<h2" in html else ""
    total = len(re.findall(r"<li[ >]", body))
    if region:
        start, end = region
        total -= len(re.findall(r"<li[ >]", html[start:end]))
    return max(total, 0)


# ---------------------------------------------------------------- filenames


def _fileslug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "x"


def _ext(url: str) -> str:
    m = re.search(r"\.(mp3|ogg)(?:[/?]|$)", url, re.I)
    return m.group(1).lower() if m else "mp3"


# ---------------------------------------------------------------- harvest


def load_index(path: Path = INDEX) -> list[dict]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def save_index(rows: list[dict], path: Path = INDEX) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")


def harvest_agent(agent: str, rows: list[dict], seen_urls: set[str],
                   dry_run: bool = False) -> dict:
    """Fetch one agent's Quotes page (and any linked subpage), download every
    new ability-use line's audio, append to `rows`. Returns a per-agent
    summary dict for `report`."""
    summary = {"agent": agent, "page": None, "error": None, "abilities": {},
               "other_lines": 0, "downloaded": 0, "bytes": 0}
    page = _resolve_quotes_page(agent)
    if page is None:
        summary["error"] = "no Quotes page found"
        return summary
    summary["page"] = page

    try:
        html = _api_parse(page)
    except HarvestError as e:
        summary["error"] = str(e)
        return summary

    region = _abilities_region(html)
    if region is None:
        summary["error"] = "page has no Abilities section"
        return summary
    items, excluded, subpages = parse_page(html)
    for item in items:
        item["page"] = page
    summary["other_lines"] += _other_line_count(html, region)
    for (ab, sec), n in excluded.items():
        summary["abilities"].setdefault(ab, {}).setdefault("excluded", 0)
        summary["abilities"][ab]["excluded"] += n

    seen_pages = {page}
    for sp in subpages:
        if sp in seen_pages:
            continue
        seen_pages.add(sp)
        try:
            sub_html = _api_parse(sp)
        except HarvestError as e:
            print(f"   subpage FAILED {sp}: {e}", file=sys.stderr)
            continue
        sub_region = _abilities_region(sub_html)
        sub_items, sub_excluded, _more = parse_page(sub_html)
        for item in sub_items:
            item["page"] = sp
        items.extend(sub_items)
        summary["other_lines"] += _other_line_count(sub_html, sub_region)
        for (ab, sec), n in sub_excluded.items():
            summary["abilities"].setdefault(ab, {}).setdefault("excluded", 0)
            summary["abilities"][ab]["excluded"] += n

    counters: dict[tuple[str, str], int] = {}
    agent_token = agent.replace("/", "-")
    for item in items:
        ability, section, text = item["ability"], item["section"], item["text"]
        source_page = item.get("page", page)
        stat = summary["abilities"].setdefault(ability, {})
        stat.setdefault("lines", set())
        stat.setdefault("files", 0)
        stat.setdefault("excluded", 0)
        stat["lines"].add(text)
        for url in item["urls"]:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            key = (ability, section)
            counters[key] = counters.get(key, 0) + 1
            n = counters[key]
            ext = _ext(url)
            fname = f"{agent_token}__{_fileslug(ability)}__{_fileslug(section)}__{n}.{ext}"
            dest = CASTS / fname
            stat["files"] += 1
            if dry_run:
                print(f"   [dry-run] would fetch {fname} <- {url}")
                continue
            if dest.exists() and dest.stat().st_size > 0:
                nbytes = dest.stat().st_size
            else:
                try:
                    nbytes = _download_asset(url, dest)
                    print(f"   {fname} ({nbytes} bytes)")
                except HarvestError as e:
                    print(f"   FAILED {fname}: {e}", file=sys.stderr)
                    stat["files"] -= 1
                    continue
            rows.append({
                "agent": agent, "ability": ability, "section": section,
                "line": text, "source_url": url, "wiki_page": source_page,
                "file": fname, "bytes": nbytes,
                "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            summary["downloaded"] += 1
            summary["bytes"] += nbytes
    return summary


def harvest(agents: list[str] | None = None, dry_run: bool = False) -> list[dict]:
    _lower_priority()
    CASTS.mkdir(parents=True, exist_ok=True)
    rows = load_index()
    seen_urls = {r["source_url"] for r in rows}
    targets = agents or AGENT_ORDER
    summaries = []
    for i, agent in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {agent} ...")
        summary = harvest_agent(agent, rows, seen_urls, dry_run=dry_run)
        summaries.append(summary)
        if summary["error"]:
            print(f"   {summary['error']}", file=sys.stderr)
        if not dry_run:
            save_index(rows)  # persisted after every agent, not only at the end
    return summaries


# ---------------------------------------------------------------- ult-ready


def section_items(html: str, name: str) -> list[dict]:
    """The lines with audio under every heading called `name`, at any level,
    up to the next heading of the same or a higher level. An item is
    {"heading": the heading path, "section", "text", "urls"}."""
    heads = list(ANY_HEAD_RE.finditer(html))
    path: dict[int, str] = {}
    items = []
    for i, h in enumerate(heads):
        level = int(h.group(1))
        title = ar._text(h.group(2)).strip()
        path = {k: v for k, v in path.items() if k < level}
        path[level] = title
        if title.lower() != name.lower():
            continue
        end = next((m.start() for m in heads[i + 1:] if int(m.group(1)) <= level), len(html))
        for b in _li_blocks(html[h.end():end]):
            urls = AUDIO_SRC_RE.findall(b)
            if urls:
                items.append({"heading": " / ".join(path[k] for k in sorted(path)),
                              "section": title, "text": _line_text(b), "urls": urls})
    return items


def ult_status_state(text: str) -> str | None:
    """Which Ultimate Status reply a line is, by its words: `ready`, `almost`
    or `not`; None for a line that says nothing of readiness."""
    t = text.lower().replace("\u2019", "'")
    if "ready" not in t:
        return None
    if "almost" in t:
        return "almost"
    if re.search(r"\bnot\b|n't\b", t):
        return "not"
    return "ready"


def status_tag(url: str) -> str | None:
    """The reply the wiki's file name names (`SkyeUltReady1.mp3` is `ready`)."""
    name = urllib.parse.unquote(url.split("/revision")[0].rsplit("/", 1)[-1]).lower()
    return next((s for tag, s in STATUS_TAGS.items() if tag.lower() in name), None)


def ultimate_names(cast_rows: list[dict]) -> dict[str, str]:
    """{agent: its ultimate}: the ability whose lines the cast index files
    under the ultimate's two heard sections (`reticle.ult_lines.ULT_SECTIONS`)."""
    from reticle.ult_lines import ULT_SECTIONS
    return {r["agent"]: r["ability"] for r in sorted(cast_rows, key=lambda r: r["file"])
            if r.get("section") in ULT_SECTIONS}


def harvest_ult_ready(agents: list[str] | None = None, dry_run: bool = False,
                      dest_dir: Path = ULT_READY) -> list[dict]:
    """Download each agent's ult-ready takes to `dest_dir`; one summary per agent.

    The ready reply under ULT_STATUS_SECTION, each take named
    `<Agent>__<section slug>__<n>.<ext>` with n counting the ready takes in
    page order, seen or not, so a name stays with its take across runs.
    """
    _lower_priority()
    index = dest_dir / "index.json"
    rows = load_index(index)
    seen = {r["source_url"] for r in rows}
    claimed = {r["file"]: r["source_url"] for r in rows}
    ults = ultimate_names(load_index(INDEX))
    targets = agents or AGENT_ORDER
    summaries = []
    for i, agent in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {agent} ...")
        s = {"agent": agent, "page": None, "error": None, "headings": [], "ready": 0,
             "other_replies": 0, "refused": [], "downloaded": 0, "bytes": 0}
        summaries.append(s)
        s["page"] = page = _resolve_quotes_page(agent)
        if page is None:
            s["error"] = "no Quotes page found"
            print(f"   {s['error']}", file=sys.stderr)
            continue
        try:
            html = _api_parse(page)
        except HarvestError as e:
            s["error"] = str(e)
            print(f"   {s['error']}", file=sys.stderr)
            continue
        n = 0
        for item in section_items(html, ULT_STATUS_SECTION):
            if item["heading"] not in s["headings"]:
                s["headings"].append(item["heading"])
            if ult_status_state(item["text"]) != "ready":
                s["other_replies"] += 1
                continue
            for url in item["urls"]:
                tag = status_tag(url)
                if tag not in (None, "ready"):
                    s["refused"].append(f"{url}: the words say ready, the file name says {tag}")
                    continue
                n += 1
                s["ready"] += 1
                fname = (f"{agent.replace('/', '-')}__{_fileslug(ULT_STATUS_SECTION)}"
                         f"__{n}.{_ext(url)}")
                if url in seen:
                    continue
                if fname in claimed:
                    s["refused"].append(f"{url}: {fname} already holds {claimed[fname]}")
                    continue
                dest = dest_dir / fname
                if dry_run:
                    print(f"   [dry-run] would fetch {fname} <- {url}")
                    continue
                if dest.exists() and dest.stat().st_size > 0:
                    nbytes = dest.stat().st_size      # present: kept, never overwritten
                else:
                    try:
                        nbytes = _download_asset(url, dest)
                    except HarvestError as e:
                        s["refused"].append(f"{url}: {e}")
                        continue
                    print(f"   {fname} ({nbytes} bytes)")
                seen.add(url)
                claimed[fname] = url
                rows.append({
                    "agent": agent, "ability": ults.get(agent), "section": item["section"],
                    "line": item["text"], "source_url": url, "wiki_page": page,
                    "file": fname, "bytes": nbytes,
                    "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })
                s["downloaded"] += 1
                s["bytes"] += nbytes
        if not dry_run:
            save_index(rows, index)
    return summaries


def _median(v: list[float]) -> float:
    v = sorted(v)
    m = len(v) // 2
    return float(v[m]) if len(v) % 2 else (v[m - 1] + v[m]) / 2


def ult_ready_counts(rows: list[dict], ult_agents: set[str]) -> dict:
    """The harvest's counts. A line is a distinct text, a file one take;
    `ult_agents` are the agents with an official ult asset, spelled as its
    files spell them (KAY_O)."""
    lines: dict[str, set[str]] = {}
    files: dict[str, int] = {}
    for r in rows:
        a = r["agent"].replace("/", "_")
        lines.setdefault(a, set()).add(r["line"])
        files[a] = files.get(a, 0) + 1
    nl = [len(v) for v in lines.values()] or [0]
    nf = list(files.values()) or [0]
    return {"agents": len(lines), "agents_listed": len(AGENT_ORDER),
            "lines": sum(nl), "files": len(rows), "bytes": sum(r["bytes"] for r in rows),
            "lines_per_agent_min": min(nl), "lines_per_agent_median": _median(nl),
            "lines_per_agent_max": max(nl), "files_per_agent_min": min(nf),
            "files_per_agent_median": _median(nf), "files_per_agent_max": max(nf),
            "agents_with_ult_asset": len(ult_agents),
            "agents_with_ult_asset_covered": len(ult_agents & set(lines))}


def _sha(path: Path) -> str | None:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else None


def report_ult_ready(record: bool = False, summaries: list[dict] | None = None) -> dict:
    """Print the ult-ready index per agent; with `record`, record its counts."""
    rows = load_index(ULT_READY_INDEX)
    ult_agents = {p.stem.rsplit("_ult_", 1)[0] for p in VOICE.glob("*_ult_*.mp3")}
    values = ult_ready_counts(rows, ult_agents)
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["agent"], []).append(r)
    for agent in AGENT_ORDER:
        rs = by.get(agent, [])
        texts = sorted({r["line"] for r in rs})
        print(f"{agent:<10} {len(rs)} takes  {' | '.join(texts) or '--- none ---'}")
    missing = sorted(ult_agents - {a.replace("/", "_") for a in by})
    print(f"\n{values['files']} files, {values['lines']} lines, {values['agents']} agents; "
          f"{values['agents_with_ult_asset_covered']} of {values['agents_with_ult_asset']} "
          f"agents with an ult asset; missing {missing or 'none'}")
    if record:
        from reticle import metrics
        refused = [x for s in summaries or [] for x in s["refused"]]
        metrics.record(
            "voice_line_harvest", part="ult-ready", session="wiki", values=values,
            deps={"section": ULT_STATUS_SECTION,
                  "index_sha256": _sha(ULT_READY_INDEX),
                  "code": metrics.fingerprint(section_items, ult_status_state, status_tag,
                                              harvest_ult_ready, ult_ready_counts)},
            context={"api": API, "index": str(ULT_READY_INDEX), "missing": missing,
                     "refused": refused,
                     "headings": sorted({h for s in summaries or [] for h in s["headings"]})},
            note="ult-ready lines, one reply of the Ultimate Status radio command")
        print("recorded voice_line_harvest/ult-ready@wiki")
    return values


# ---------------------------------------------------------------- report


def report(summaries: list[dict] | None = None) -> None:
    rows = load_index()
    by_agent: dict[str, dict[str, set[str]]] = {}
    for r in rows:
        by_agent.setdefault(r["agent"], {}).setdefault(r["ability"], set()).add(r["line"])

    total_files = len(rows)
    total_bytes = sum(r["bytes"] for r in rows)
    print(f"{total_files} files, {total_bytes} bytes, {len(by_agent)} agents with audio")
    print(f"{CASTS / 'index.json'}")
    print()
    print(f"{'agent':<10} {'abilities':>9} {'min lines':>9} {'median':>7} {'max':>4}")
    counts_examples = []
    for agent in AGENT_ORDER:
        abilities = by_agent.get(agent, {})
        if not abilities:
            print(f"{agent:<10} {'--- no audio ---':>9}")
            continue
        counts = sorted(len(lines) for lines in abilities.values())
        mid = counts[len(counts) // 2] if len(counts) % 2 else \
            (counts[len(counts) // 2 - 1] + counts[len(counts) // 2]) / 2
        print(f"{agent:<10} {len(abilities):>9} {counts[0]:>9} {mid:>7} {counts[-1]:>4}")
        for ability, lines in abilities.items():
            if len(lines) > 1:
                counts_examples.append((agent, ability, sorted(lines)))
    print(f"\n{len(counts_examples)} abilities with more than one distinct cast line")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("harvest", "report", "ult-ready"))
    ap.add_argument("--agents", help="comma-separated subset, wiki-agent spelling")
    ap.add_argument("--dry-run", action="store_true", help="list what would be fetched, fetch nothing")
    ap.add_argument("--record", action="store_true",
                    help="ult-ready: record the counts in the store's notes/metrics.jsonl")
    a = ap.parse_args(argv)

    if a.cmd == "ult-ready":
        agents = [x.strip() for x in a.agents.split(",")] if a.agents else None
        summaries = harvest_ult_ready(agents=agents, dry_run=a.dry_run)
        for s in summaries:
            for x in s["refused"]:
                print(f"   refused {s['agent']}: {x}", file=sys.stderr)
        print()
        report_ult_ready(record=a.record and not a.dry_run and agents is None,
                         summaries=summaries)
        return 0
    if a.cmd == "harvest":
        agents = [x.strip() for x in a.agents.split(",")] if a.agents else None
        harvest(agents=agents, dry_run=a.dry_run)
        print()
        report()
        return 0
    report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
