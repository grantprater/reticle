"""Harvest the official ability reference: what each ability IS, looks like, and sounds like.

    .\\.venv\\Scripts\\python.exe prototypes\\ability_reference.py harvest [--no-assets]
    .\\.venv\\Scripts\\python.exe prototypes\\ability_reference.py show <agent>
    .\\.venv\\Scripts\\python.exe prototypes\\ability_reference.py check

Why this exists
---------------
Every ability question this project has stalled on is a question about a
POPULATION it cannot see. The 254 label rows are five ability classes from
three agents; the ranked corpus died because a threshold fitted to them did not
transfer. More clips do not fix that on their own -- what fixes it is knowing,
without labelling anything, what the full space of abilities actually contains.

Riot publishes that space. `valorant-api.com` mirrors the game's own asset
catalogue and the fandom wiki carries a per-ability infobox with the fields
that decide how an ability BEHAVES over time. Both are free, which matters:
the player ruled out a paid VLM labelling pass on 2026-09-04, so the teacher in the
teacher/student plan has to be built out of priors and reference art rather
than out of per-candidate judgement.

Three things it supplies, each aimed at a specific dead end
-----------------------------------------------------------
1. **behaviour, for the acausal lifetime pass.** `Deployment Type`, `Health`,
   `Uses` and `Restock` say whether an ability is a placed deployable that
   persists until destroyed, a projectile that resolves in a second, or an
   instant effect. The acausal teacher tests an object's measured lifetime
   against what its ability is supposed to do, and this is the field that says
   what it is supposed to do;

2. **`minimapPortrait`, 64x64 RGBA, one per agent.** `minimap_portrait_transform.py`
   tried to synthesize minimap templates by cropping the scoreboard bust and
   concluded the premise was FALSE -- three of five agents sat at 0.16-0.24
   resemblance in the best case the parametrisation could produce, and its
   verdict was *"the minimap avatar appears to be its own render -- not the bust
   rescaled"*. That render was untestable then because no surface in the capture
   carries it. It is a download. This is the asset that experiment concluded
   must exist;

3. **ultimate voicelines as matched-filter references.** `audio_probe.py` found
   onset detection dead (null median flux rank 0.99) and said a matched filter
   is needed instead -- and that *"a matched filter needs a reference cut at a
   KNOWN cast time"*. The wiki hosts 64 of them as isolated game-file MP3s,
   320 kbps 48 kHz mono, in ALLY and ENEMY variants. The two variants are not
   redundant: which one fires carries team identity.

The ability icons are the fourth, and the one to be careful about
-----------------------------------------------------------------
`displayIcon` is 128x128 RGBA -- the HUD tray art. It is NOT how the ability
draws on the minimap, and template-matching it against minimap content will
find nothing. Where it belongs is the TRAY, which `ability_hud.py` already
reads geometrically: that module knows slot k fired but takes the ability's
identity from the agent roster. Matching this art against the tray gives
identity from pixels instead, which is the difference between "slot 2 fired"
and "Killjoy cast Turret".

The alpha channel is a free exact mask. Every capture-derived template this
project has built carries whatever was behind it; these do not.

What is VERIFIED here and what is not
--------------------------------------
`check` cross-checks the API's slot ordering (Grenade/Ability1/Ability2/Ultimate)
against the wiki infobox's own `Default Key` field for every ability, so the
C/Q/E/X mapping `ability_hud.py` depends on is measured rather than assumed.

Nothing here has been matched against capture pixels yet. That is deliberate:
the scoreboard-crop failure is the standing warning that a plausible source
asset can simply not resemble the render, and the honest test is
`minimap_portrait.py eval` against the hand-marked icons, with the bar
set in advance by that module's own in-domain figure -- ONE median template per
agent scored 70.4%.

The wiki is community-maintained and lags patches. Costs and charge counts drift
first. Treat every field here as a PRIOR, never as an oracle.
"""

from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

STORE = Path.home() / "reticle-store"
REF = STORE / "reference"
ASSETS = REF / "assets"
TABLE = REF / "abilities.json"

API_AGENTS = "https://valorant-api.com/v1/agents?isPlayableCharacter=true"
WIKI_ABILITIES = "https://valorant.fandom.com/wiki/Abilities"
WIKI_PAGE = "https://valorant.fandom.com/wiki/{}"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# valorant-api slot name -> the key the ability is bound to. Cross-checked
# against the wiki's own `Default Key` field by `check`; never trust it silently.
SLOT_KEY = {"Grenade": "C", "Ability1": "Q", "Ability2": "E", "Ultimate": "X", "Passive": None}

# Infobox fields worth keeping. `Deployment Type` and `Health` are the two the
# acausal lifetime pass actually consumes; the rest are context.
KEEP = (
    "Ability Type", "Function", "Uses", "Restock", "Default Key", "Deployment Type",
    "Health", "Weapon Reequip Speed", "Susceptible to full damage and effects?",
    "Affects allies/self?", "Cost", "Duration", "Cooldown", "Radius", "Range",
)


class HarvestError(RuntimeError):
    """A source did not answer. Raised at the cause so the caller can say which."""


def _get(url: str, tries: int = 4, pause: float = 2.0) -> bytes:
    """Fetch with a browser UA, retrying past Cloudflare's interstitial.

    Fandom serves a challenge to bursts. It is a 200 with a `Just a moment...`
    body, so the status code alone does not detect it.
    """
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            if b"Just a moment" in body[:2000] and b"challenges.cloudflare" in body[:4000]:
                last = "cloudflare challenge"
                time.sleep(pause * (i + 1))
                continue
            return body
        except Exception as e:  # noqa: BLE001 - reported, not swallowed
            last = repr(e)
            time.sleep(pause * (i + 1))
    raise HarvestError(f"{url}: {last}")


def _text(frag: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", frag))).strip()


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


# ---------------------------------------------------------------- sources


def fetch_agents() -> list[dict]:
    return json.loads(_get(API_AGENTS))["data"]


def _rows(table: str) -> tuple[list[str], list[list[str]]]:
    heads = [_text(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
    out = []
    for tr in re.findall(r"<tr.*?</tr>", table, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if cells:
            out.append(cells)
    return heads, out


def fetch_index(page: bytes) -> dict[str, dict]:
    """Ability name -> {agent, wiki_page, cost, charges, functions} from the three index tables.

    The Agent cell is rowspanned over an agent's abilities, so a row that is one
    cell short of the header count belongs to the agent above it.
    """
    h = page.decode("utf-8", "replace")
    tables = re.findall(r"<table.*?</table>", h, re.S)
    index: dict[str, dict] = {}
    for ti, kind in ((0, "Basic"), (1, "Signature"), (2, "Ultimate")):
        heads, rows = _rows(tables[ti])
        ncol = len(heads)
        agent = None
        for cells in rows:
            if len(cells) == ncol:
                agent, data = _text(cells[0]), cells[1:]
            elif len(cells) == ncol - 1:
                data = cells
            else:
                continue
            if not agent or not data:
                continue
            link = re.search(r'<a href="/wiki/([^"#]+)"', data[0])
            name = _text(data[0])
            if not name:
                continue
            index[name.lower()] = {
                "agent": agent,
                "wiki_page": _html.unescape(link.group(1)) if link else None,
                "table_kind": kind,
                "cost": _text(data[1]) if len(data) > 1 else None,
                "charges": _text(data[2]) if len(data) > 2 else None,
                "functions": _text(data[-1]) or None,
            }
    return index


def fetch_voicelines(page: bytes) -> dict[str, dict]:
    """Agent -> {ally: {url, line}, enemy: {url, line}} from the ultimate-cast table."""
    h = page.decode("utf-8", "replace")
    tables = re.findall(r"<table.*?</table>", h, re.S)
    _, rows = _rows(tables[3])
    out: dict[str, dict] = {}
    for cells in rows:
        if len(cells) < 5:
            continue
        agent = _text(cells[0])
        if not agent:
            continue
        rec = {}
        for side, ai, ti in (("ally", 1, 2), ("enemy", 3, 4)):
            m = re.search(r'(?:data-src|src)="(https://static\.wikia[^"]+\.mp3[^"]*)"', cells[ai])
            line = _text(cells[ti]).strip('"')
            if m:
                rec[side] = {"url": m.group(1), "line": line or None}
        if rec:
            out[agent] = rec
    return out


def fetch_infobox(wiki_page: str) -> dict[str, str]:
    """The portable-infobox label/value pairs from one ability page."""
    h = _get(WIKI_PAGE.format(wiki_page)).decode("utf-8", "replace")
    box = re.search(r"<aside[^>]*portable-infobox.*?</aside>", h, re.S)
    if not box:
        return {}
    out = {}
    pat = r'<h3 class="pi-data-label[^"]*">(.*?)</h3>\s*<div class="pi-data-value[^"]*">(.*?)</div>'
    for m in re.finditer(pat, box.group(0), re.S):
        lab, val = _text(m.group(1)), _text(m.group(2))
        if lab and val:
            out[lab] = val
    return out


# ---------------------------------------------------------------- assets


def _download(url: str, path: Path) -> bool:
    if path.exists() and path.stat().st_size > 0:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(_get(url, tries=3))
        return True
    except HarvestError as e:
        print(f"   asset FAILED {path.name}: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------- harvest


def harvest(with_assets: bool = True, pause: float = 0.6) -> dict:
    REF.mkdir(parents=True, exist_ok=True)
    print("fetching valorant-api agent catalogue ...")
    agents = fetch_agents()
    print(f"   {len(agents)} playable agents")

    print("fetching wiki ability index ...")
    page = _get(WIKI_ABILITIES)
    index = fetch_index(page)
    voice = fetch_voicelines(page)
    print(f"   {len(index)} abilities indexed, {len(voice)} agents with ultimate voicelines")

    out = {"source": {"api": API_AGENTS, "wiki": WIKI_ABILITIES},
           "harvested": time.strftime("%Y-%m-%d"), "agents": {}}

    total = sum(len(a["abilities"]) for a in agents)
    seen = 0
    for a in agents:
        an = a["displayName"]
        rec: dict = {
            "uuid": a["uuid"],
            "role": (a.get("role") or {}).get("displayName"),
            "description": a.get("description"),
            "abilities": [],
            "voicelines": voice.get(an, {}),
        }
        for asset, key in (("minimapPortrait", "minimap_portrait"),
                           ("killfeedPortrait", "killfeed_portrait"),
                           ("displayIcon", "agent_icon")):
            url = a.get(asset)
            if not url:
                continue
            p = ASSETS / "agents" / f"{_slug(an)}_{key}.png"
            ok = _download(url, p) if with_assets else False
            rec[key] = {"url": url, "file": str(p.relative_to(REF)) if ok else None}

        for b in a["abilities"]:
            seen += 1
            name = (b.get("displayName") or "").strip()
            slot = b.get("slot")
            idx = index.get(name.lower(), {})
            info: dict[str, str] = {}
            if idx.get("wiki_page"):
                print(f"   [{seen}/{total}] {an} {slot}: {name}")
                try:
                    info = fetch_infobox(idx["wiki_page"])
                except HarvestError as e:
                    print(f"      infobox FAILED: {e}", file=sys.stderr)
                time.sleep(pause)
            ab: dict = {
                "name": name,
                "slot": slot,
                "key": SLOT_KEY.get(slot),
                "description": b.get("description"),
                "wiki_page": idx.get("wiki_page"),
                "table_kind": idx.get("table_kind"),
                "cost": idx.get("cost"),
                "charges": idx.get("charges"),
                "functions": idx.get("functions"),
                "infobox": {k: v for k, v in info.items() if k in KEEP},
            }
            if b.get("displayIcon"):
                p = ASSETS / "abilities" / f"{_slug(an)}_{slot}.png"
                ok = _download(b["displayIcon"], p) if with_assets else False
                ab["icon"] = {"url": b["displayIcon"], "file": str(p.relative_to(REF)) if ok else None}
            rec["abilities"].append(ab)

        if with_assets:
            for side, v in rec["voicelines"].items():
                p = ASSETS / "voicelines" / f"{_slug(an)}_ult_{side}.mp3"
                v["file"] = str(p.relative_to(REF)) if _download(v["url"], p) else None

        out["agents"][an] = rec

    TABLE.parent.mkdir(parents=True, exist_ok=True)
    TABLE.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {TABLE}")
    return out


def load() -> dict:
    if not TABLE.exists():
        raise HarvestError(f"{TABLE} missing -- run `ability_reference.py harvest` first")
    return json.loads(TABLE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- reporting


def check(ref: dict) -> int:
    """Cross-check the API slot order against the wiki's own Default Key.

    Returns the number of disagreements. `ability_hud.py` reads slot k = C/Q/E/X
    off a fitted pitch and takes identity from the roster; this is what says the
    ordering it assumes is the ordering the game uses.
    """
    agree = disagree = unknown = 0
    for an, rec in sorted(ref["agents"].items()):
        for ab in rec["abilities"]:
            want = ab.get("key")
            got = ab.get("infobox", {}).get("Default Key")
            if want is None or not got:
                unknown += 1
                continue
            m = re.match(r"\s*([A-Z0-9]+)\s*\(PC\)", got)
            if not m:
                unknown += 1
                continue
            if m.group(1) == want:
                agree += 1
            else:
                disagree += 1
                print(f"  MISMATCH {an} {ab['slot']} {ab['name']}: api->{want} wiki->{m.group(1)}")
    print(f"\nslot->key mapping: {agree} agree, {disagree} disagree, {unknown} not stated")
    return disagree


def summarise(ref: dict) -> None:
    ags = ref["agents"]
    nab = sum(len(a["abilities"]) for a in ags.values())
    icons = sum(1 for a in ags.values() for b in a["abilities"] if (b.get("icon") or {}).get("file"))
    mm = sum(1 for a in ags.values() if (a.get("minimap_portrait") or {}).get("file"))
    vo = sum(len(a.get("voicelines", {})) for a in ags.values())
    boxes = sum(1 for a in ags.values() for b in a["abilities"] if b.get("infobox"))
    print(f"agents {len(ags)}   abilities {nab}   with infobox {boxes}")
    print(f"assets: {icons} ability icons, {mm} minimap portraits, {vo} ultimate voicelines")

    dep: dict[str, int] = {}
    for a in ags.values():
        for b in a["abilities"]:
            d = b.get("infobox", {}).get("Deployment Type")
            if d:
                dep[d] = dep.get(d, 0) + 1
    print("\nDeployment Type -- the field the acausal lifetime pass consumes:")
    for k, v in sorted(dep.items(), key=lambda kv: -kv[1]):
        print(f"   {v:>3}  {k}")

    hp = [(a_n, b["name"], b["infobox"]["Health"])
          for a_n, a in ags.items() for b in a["abilities"] if b.get("infobox", {}).get("Health")]
    print(f"\ndestructible deployables with stated Health: {len(hp)}")
    for a_n, n, v in hp[:15]:
        print(f"   {a_n:<10} {n:<24} {v}")


def show(ref: dict, agent: str) -> None:
    key = next((k for k in ref["agents"] if k.lower() == agent.lower()), None)
    if not key:
        print(f"no such agent: {agent}. have: {', '.join(sorted(ref['agents']))}")
        return
    rec = ref["agents"][key]
    print(f"{key}  ({rec.get('role')})")
    for side, v in rec.get("voicelines", {}).items():
        print(f"   ult voiceline ({side}): \"{v.get('line')}\"  -> {v.get('file')}")
    for b in rec["abilities"]:
        print(f"\n  [{b.get('key') or '-'}] {b['name']}  ({b.get('table_kind') or b['slot']})")
        for k in ("cost", "charges", "functions"):
            if b.get(k):
                print(f"       {k:<12} {b[k]}")
        for k, v in b.get("infobox", {}).items():
            print(f"       {k:<12} {v}"[:140])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("harvest", "show", "check", "summary"))
    ap.add_argument("agent", nargs="?")
    ap.add_argument("--no-assets", action="store_true", help="table only, skip icon/audio downloads")
    ap.add_argument("--pause", type=float, default=0.6, help="seconds between wiki page fetches")
    a = ap.parse_args(argv)

    if a.cmd == "harvest":
        ref = harvest(with_assets=not a.no_assets, pause=a.pause)
        print()
        summarise(ref)
        return 0

    ref = load()
    if a.cmd == "show":
        if not a.agent:
            print("show needs an agent name")
            return 2
        show(ref, a.agent)
    elif a.cmd == "check":
        return 1 if check(ref) else 0
    else:
        summarise(ref)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
