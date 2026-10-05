"""Who assisted each kill, and with which ability, from the stored reads of
the assist panel [domain:killfeed/assist-panel]. Pure over stored rows:
`killfeed_assist` observations, the death stream's verdicts, the lineup and
`killfeed_kits`. Owns [owns:kill-assists].

    .\\.venv\\Scripts\\python.exe -m reticle assists <session>

**Count.** Each death's views (`killfeed_assist.assist_observation`, a few
per entry) vote on how many assisters its panel draws; a view whose search
the ROI cut does not vote. The count is the views' agreement: one value read
by every voting view is `read`; a split vote keeps the majority with its
dissent, and a tie refuses as `count_tie`. Zero is a reading: the kill drew
no panel. Where the ROI cut every view, the assisters each view found before
the cut stand as a lower bound (`count_min`, the least over the views): they
are named and read like the rest, and `present` is True; `count` stays None.

**Agents.** Every assister is an entity, `<death_id>:assist:<k>` with k
counted from the killer's portrait leftwards, and each view's portrait
scores become one `identity_claim` on channel `killfeed_assist`, decided by
`adjudication.identity`'s arbiter, never here. A view names the best
admitted agent (the killer's side, `identity.side_candidates`) when its art
correlation reaches `killfeed_assist.PRESENT_Z` and leads every other
admitted agent and rival by `identity.PORTRAIT_MARGIN_MIN`; else it abstains
with its reason. An assister found only on the reader's surprise path (an
agent outside the side's lineup) abstains as `outside_side`.

**Icons.** An assister drawn with no icon reads `none`
[domain:killfeed/assist-without-icon]. A drawn icon is named from the
pooled scores (mean over the views that read the cell) in three widening
sets, each a fact or a stored decision: first the assister's disabling and
undecided abilities (`killfeed_kits` `assist_icons`, `assist_open`)
[domain:killfeed/disabling-ability-assist-icon]; on surprise, the rest of its
kit; then the panel's generic icons and every other icon, which name nothing
and refuse as `outside_kit` with `drawn` recording what the cell matched
best. The icon rests on the assister's verdict (`depends_on`); an assister
with no verdict is read against the side's kits and says so.

The kill owner (`adjudication.death`) does not yet carry this; each verdict is
keyed by `death_id` for it to join (`assists` in `docs/WORKING_MAP.md`).
"""
from __future__ import annotations

from collections import Counter, defaultdict

from . import killfeed_kits
from .identity import (AGENT_IDENTITY_VERSION, PORTRAIT_MARGIN_MIN, AgentIdentityArbiter,
                       identity_claim, side_candidates)
from ..killfeed_assist import KILLFEED_ASSIST_VERSION, PRESENT_Z

# 0.1.0 (2026-10-04): first adjudication.
# 0.2.0 (2026-10-04): a cut panel keeps its lower bound (`count_min`,
# `present`) and the assisters found before the cut.
# 0.3.0 (2026-10-04): a view's claim evidence carries the portrait's frame
# (`self` for the player's yellow frame) and the art margin it was scored at;
# the stream opens with a summary row of its inputs.
ASSIST_ADJUDICATION_VERSION = "assist-adjudication-0.3.0"

CHANNEL = "killfeed_assist"
#: An icon is named when its pooled score reaches this and leads the next
#: name in the same set by ICON_MARGIN.
ICON_READ = 0.5
ICON_MARGIN = 0.05
NONE_ICON = "none"


def killer_side(verdict: dict) -> str | None:
    """The killer's side for one death verdict: the victim's own on a team
    kill, else the other."""
    side = verdict.get("side")
    if side not in ("ally", "enemy"):
        return None
    if verdict.get("same_side"):
        return side
    return "enemy" if side == "ally" else "ally"


def side_admitted(lineup: dict | None, side: str | None) -> dict:
    """The killer's side as `identity.side_candidates` splits it: who may be
    named and who may only compete."""
    rows = ((lineup or {}).get("sides") or {}).get(side or "", [])
    return side_candidates(rows)


def view_claim(row: dict, entity_id: str, admitted: dict, observed_at_ms: float) -> dict:
    """One view's identity claim on one assister."""
    zs = row.get("art_zncc") or {}
    ev = {"k": row["k"], "x": row.get("x"), "y": row.get("y"), "art_zncc": zs,
          "art_candidates": row.get("art_candidates"), "widened": row.get("widened"),
          "frame": row.get("frame"), "art_margin": row.get("art_margin"),
          "named_candidates": admitted["named"], "rivals": admitted["rivals"],
          "blind": admitted["blind"]}
    kw = dict(channel=CHANNEL, observed_at_ms=observed_at_ms,
              source_version=KILLFEED_ASSIST_VERSION, evidence=ev)
    if row.get("art_candidates") == "all":
        return identity_claim(entity_id, None, reason="outside_side", **kw)
    if admitted["blind"]:
        return identity_claim(entity_id, None, reason="blind_slot", **kw)
    ranked = sorted(zs.items(), key=lambda kv: -kv[1])
    if not ranked:
        return identity_claim(entity_id, None, reason="no_scores", **kw)
    top, z1 = ranked[0]
    z2 = ranked[1][1] if len(ranked) > 1 else -1.0
    if top not in admitted["named"]:
        return identity_claim(entity_id, None, reason=f"rival_leads:{top}", **kw)
    if z1 < PRESENT_Z:
        return identity_claim(entity_id, None, reason="weak", **kw)
    if z1 - z2 < PORTRAIT_MARGIN_MIN:
        return identity_claim(entity_id, None, reason=f"margin {z1 - z2:.3f}", **kw)
    return identity_claim(entity_id, top, **kw)


def pool_count(views: list[dict]) -> dict:
    """The count the views agree on, with their votes."""
    votes = Counter(v["count"] for v in views if v.get("count") is not None)
    refused = Counter(v.get("reason") or "unread" for v in views if v.get("count") is None)
    if not votes:
        # the ROI cut every view: the assisters found before the cut are a
        # lower bound the views agree on (the least any view found)
        mins = [v.get("count_min") or 0 for v in views if v.get("reason") == "cut_by_roi"]
        low = min(mins) if mins else 0
        return {"count": None, "count_status": "refused", "count_votes": {},
                "count_reason": (refused.most_common(1)[0][0] if refused else "no_views"),
                "count_min": low, "present": True if low > 0 else None}
    ranked = votes.most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return {"count": None, "count_status": "refused", "count_reason": "count_tie",
                "count_votes": {str(k): n for k, n in ranked}, "count_min": 0,
                "present": True if all(k > 0 for k, _n in ranked) else None}
    n = ranked[0][0]
    return {"count": n, "count_status": "read" if len(ranked) == 1 else "majority",
            "count_votes": {str(k): c for k, c in ranked}, "count_reason": None,
            "count_min": n, "present": n > 0}


def _kit_sets(agent: str, kits: dict) -> tuple[list[str], list[str]]:
    """(assist set, rest of kit) as icon names `<Agent>/<ability>`."""
    assist = set(kits["assist_icons"].get(agent, [])) | set(kits["assist_open"].get(agent, []))
    whole = [a["name"] for a in kits["abilities"]
             if a["agent"] == agent and a["damage"].get("status") != "passive"]
    norm = lambda s: " ".join(s.split()).casefold()
    first = [f"{agent}/{n}" for n in whole if norm(n) in {norm(x) for x in assist}]
    rest = [f"{agent}/{n}" for n in whole if f"{agent}/{n}" not in first]
    return first, rest


def _match(scores: dict, names: list[str]) -> dict:
    """Scores restricted to `names`, compared casefolded and space-collapsed
    (the reference spells "Nebula  / Dissipate", the game "Nebula / Dissipate")."""
    norm = lambda s: " ".join(s.split()).casefold()
    want = {norm(n): n for n in names}
    return {want[norm(k)]: v for k, v in scores.items() if norm(k) in want}


def decide_icon(scores: dict, agent: str | None, side_agents: list[str], kits: dict) -> dict:
    """Name a drawn icon from pooled `scores` {icon name: score} in widening
    sets; see the module docstring."""
    agents = [agent] if agent else list(side_agents)
    first, rest = [], []
    for a in agents:
        f, r = _kit_sets(a, kits)
        first += f
        rest += r
    sets = [("assist_decision", first), ("kit", rest)]
    out = {"icon_candidates": "assister_kit" if agent else "side_kits"}
    for label, names in sets:
        sub = _match(scores, names)
        if not sub:
            continue
        ranked = sorted(sub.items(), key=lambda kv: -kv[1])
        s1 = ranked[0][1]
        s2 = ranked[1][1] if len(ranked) > 1 else 0.0
        if s1 >= ICON_READ and s1 - s2 >= ICON_MARGIN:
            name = ranked[0][0]
            return {**out, "icon": name.split("/", 1)[1], "icon_agent": name.split("/", 1)[0],
                    "icon_set": label, "icon_status": "read", "icon_score": round(s1, 4),
                    "icon_margin": round(s1 - s2, 4), "icon_reason": None}
        if s1 >= ICON_READ:
            return {**out, "icon": None, "icon_set": label, "icon_status": "refused",
                    "icon_reason": f"margin {s1 - s2:.3f}", "icon_score": round(s1, 4)}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    drawn = ranked[0] if ranked else (None, None)
    return {**out, "icon": None, "icon_set": "open", "icon_status": "refused",
            "icon_reason": "outside_kit" if drawn[1] is not None and drawn[1] >= ICON_READ
            else "weak", "drawn": drawn[0], "drawn_score": drawn[1]}


def adjudicate_death(verdict: dict, views: list[dict], lineup: dict | None,
                     kits: dict) -> tuple[dict, list[dict]]:
    """One death's `assist_verdict` row and the identity claims it published."""
    did = verdict["death_id"]
    side = killer_side(verdict)
    admitted = side_admitted(lineup, side)
    row = {"kind": "assist_verdict", "assist_adjudication_version": ASSIST_ADJUDICATION_VERSION,
           "death_id": did, "t_ms": verdict.get("t_ms"), "round_no": verdict.get("round_no"),
           "killer": verdict.get("killer"), "victim": verdict.get("victim"),
           "killer_side": side, "views": len(views),
           "rests_on": {"death_adjudication_version": verdict.get("death_adjudication_version"),
                        "killfeed_assist_version": KILLFEED_ASSIST_VERSION}}
    row.update(pool_count(views))
    claims, assisters = [], []
    n = row["count"] if row["count"] is not None else row.get("count_min") or 0
    exact = row["count"] is not None
    for k in range(n):
        eid = f"{did}:assist:{k}"
        arb = AgentIdentityArbiter()
        mine = [(v, a) for v in views
                if (v.get("count") == n if exact else (v.get("count_min") or 0) >= n)
                for a in v.get("assisters", []) if a["k"] == k]
        for v, a in mine:
            arb.add(view_claim(a, eid, admitted, v["t_ms"]))
        verdicts = arb.verdict()
        ident = verdicts[0] if verdicts else {"entity_id": eid, "agent": None,
                                               "status": "no_claims"}
        claims.extend(arb.claims)
        agent = ident.get("agent") if ident.get("status") == "resolved" else None
        icon_views = [a for _v, a in mine if a.get("icon")]
        has_icon = Counter(bool(a.get("icon")) for _v, a in mine)
        ast = {"k": k, "entity_id": eid, "agent": agent, "identity": ident,
               "icon_drawn_votes": {str(b): c for b, c in has_icon.items()}}
        if not mine:
            ast.update(icon=None, icon_status="refused", icon_reason="no_views")
        elif has_icon[True] < has_icon[False]:
            ast.update(icon=NONE_ICON, icon_status="read", icon_reason=None)
        elif has_icon[True] == has_icon[False]:
            ast.update(icon=None, icon_status="refused", icon_reason="icon_presence_tie")
        else:
            pooled = defaultdict(list)
            for a in icon_views:
                for name, sc in (a.get("icon_scores") or {}).items():
                    pooled[name].append(sc)
            # an icon a view did not keep in its top scores counts as 0 there
            scores = {k_: sum(v_) / len(icon_views) for k_, v_ in pooled.items()}
            ast.update(decide_icon(scores, agent, admitted["named"], kits))
            ast["icon_scores"] = dict(sorted(((k_, round(v_, 4)) for k_, v_ in scores.items()),
                                             key=lambda kv: -kv[1])[:8])
            if agent:
                ast["rests_on"] = [{"identity": eid}]
        assisters.append(ast)
    row["assisters"] = assisters
    return row, claims


def adjudicate_session(verdicts: list[dict], observations: list[dict], lineup: dict | None,
                       kits: dict | None = None) -> list[dict]:
    """Every death verdict's assist row, in death order, each with its claims."""
    kits = kits or killfeed_kits.load()
    by = defaultdict(list)
    for o in observations:
        if o.get("kind") == "assist_observation":
            by[o.get("death_id")].append(o)
    out = []
    for v in sorted(verdicts, key=lambda r: (r.get("t_ms") or 0, r.get("slot") or 0)):
        if v.get("kind") != "death_verdict":
            continue
        row, claims = adjudicate_death(v, by.get(v["death_id"], []), lineup, kits)
        row["claims"] = claims
        out.append(row)
    return out


def summary(rows: list[dict]) -> dict:
    """Counts over one session's assist rows."""
    c = Counter()
    for r in rows:
        if r.get("kind") != "assist_verdict":
            continue
        c[f"count_{r['count'] if r['count'] is not None else 'refused'}"] += 1
        for a in r["assisters"]:
            c["assisters"] += 1
            c["named" if a["agent"] else "unnamed"] += 1
            c[f"icon_{a.get('icon_status')}"] += 1
            if a.get("icon") == NONE_ICON:
                c["icon_none"] += 1
    return dict(c)
