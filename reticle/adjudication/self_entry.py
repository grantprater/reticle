"""Which killfeed entry roles are the local player's own, and the K/D they give.

A team fields each agent once, so on the player's side of the feed one
portrait names one player: an entry role whose plate is the player's side
(ally) and whose portrait shows the player's bound agent is the player's
own. The side colour separates a mirror match, where the enemy fields the
same agent. That is the primary witness, and it reads no text.

Valorant usually prints the local player's name as "Me" (`killfeed`'s
attribution, the `kf_player_kill` / `kf_player_death` flags the death
adjudication carries per entry). A capture can instead print the player's
account name [domain:killfeed/own-name-me-or-account]: 4f207c0c4e39 and
the held-out cea8ecbc94ab did, and their killfeed read no "Me" at all. "Me" is therefore a second witness, consulted
when the portrait refuses, and only on a capture that prints it: a capture
on which no entry role reads "Me" (`me_printed` false) gives the absence of
"Me" no weight, and the witness abstains as `capture_prints_no_me`.

A third witness is the role's name cluster (`adjudication.killfeed_names`
through the death adjudication): roles printing one name on one side, named
by the identity arbiter. It pools portrait views of the other roles of that
name, so it `rests_on` the portrait channel and is consulted only after both
witnesses above abstain. On a "Me" capture the player's roles stay out of the
clusters and this witness abstains.

The rule, per role:

* portrait witness: `True` when the role's side is ally and its per-entry
  portrait verdict (the death adjudication's `killfeed_portrait` claim,
  before a name cluster replaces it) is the bound agent by
  `agent_names.same_agent`; `False` when it names another agent or the side
  is enemy; `None` with the portrait's reason when it refused, the side is
  unread, or the player has no bound agent (`identity.player_identity`).
* the verdict is the first witness, in that order, that is not `None`;
  `basis` names it. When every witness abstains the verdict is `None` and
  `reason` joins their reasons.
* every witness that disagrees with the verdict is stored in
  `disagreements`; agreement is consistency, not accuracy.

K/D: a kill is an entry of type `kill` whose killer role is the player and
whose victim is on the other side (a team kill is no kill), and a death is
an entry of type `kill` whose victim role is the player. A second-life entry
(Run It Back, a downed KAY/O) counts neither: the scoreboard credits neither
the death nor the kill (the rule `checks.KNOWN_DIVERGENCE` records); a revive
is no kill or death [domain:killfeed/entry-types]. A role whose verdict is `None` on a countable entry is
`unread`, never counted as the player's or not.

Pure over stored rows: the `death` stream and the lineup's player binding.
It never reads pixels, and the rounds' stored killfeed counts stay beside it.

A consumer's K/D (`session_kd`, per round `round_kd`): the adjudication's
answer where its inputs are current. Where it refuses -- no death stream, or
one at an older stamp -- the "Me" witness answers alone through the HUD
reader's own "Me" tracks (`checks.player_events`, the rounds' killfeed
counts), but only on a capture whose killfeed read "Me" at all; on a capture
that printed none the K/D is unread, `None` with both reasons, never 0/0.
`basis` names which answered: `self_entry` or `me`.

Owns [owns:self-entry].
"""

from __future__ import annotations

from collections import Counter

from ..agent_names import same_agent
from .death import DEATH_ADJUDICATION_VERSION
from .identity import player_identity

#: 0.1.0 (2026-10-06): the bound agent on the player's side decides; "Me"
#: where the portrait refuses, on a capture that prints "Me"; the name cluster
#: last.
SELF_ENTRY_VERSION = "self-entry-0.1.0"

ROLES = ("killer", "victim")
WITNESSES = ("side_portrait", "me", "name_cluster")
PORTRAIT_CHANNEL = "killfeed_portrait"
NAME_CHANNEL = "killfeed_name_cluster"


def _claim(verdict: dict, role: str, channel: str) -> dict | None:
    key = "killer_identity" if role == "killer" else "identity"
    ident = (verdict.get("metadata") or {}).get(key) or {}
    return next((c for c in ident.get("claims") or [] if c.get("channel") == channel), None)


def role_side(verdict: dict, role: str) -> str | None:
    """The plate side of a role: the victim's is the verdict's `side`; the
    killer's is the same on a one-colour entry (`same_side`), else the other."""
    side, same = verdict.get("side"), verdict.get("same_side")
    if side not in ("ally", "enemy"):
        return None
    if role == "victim":
        return side
    if same is None:
        return None
    return side if same else ("enemy" if side == "ally" else "ally")


def portrait_agent(verdict: dict, role: str) -> tuple[str | None, str | None]:
    """The role's per-entry portrait verdict and, when None, its reason. A
    name cluster's replacement keeps the per-entry answer in the claim's
    evidence (`per_entry_agent`); this reads that, not the cluster's."""
    c = _claim(verdict, role, PORTRAIT_CHANNEL)
    if c is None:
        return None, "no_portrait_claim"
    agent = c.get("agent") or (c.get("evidence") or {}).get("per_entry_agent")
    return agent, None if agent else (c.get("reason") or "portrait_refused")


def _player_witness(agent, side, bound, reason):
    if bound is None:
        return {"value": None, "agent": agent, "reason": reason}
    if side is None:
        return {"value": None, "agent": agent, "reason": "side_unread"}
    if agent is None:
        return {"value": None, "agent": None, "reason": reason}
    return {"value": bool(side == "ally" and same_agent(agent, bound)), "agent": agent,
            "reason": None}


def me_printed(verdicts: list[dict]) -> bool:
    """Whether this capture prints "Me": some entry role read it."""
    return any(v.get("kf_player_kill") or v.get("kf_player_death") for v in verdicts)


def role_verdict(verdict: dict, role: str, player: dict, printed: bool) -> dict:
    """One role's witnesses and verdict (module docstring)."""
    bound = player.get("agent")
    side = role_side(verdict, role)
    unbound = None if bound else f"player_unbound:{player.get('status')}"
    agent, why = portrait_agent(verdict, role)
    portrait = _player_witness(agent, side, bound, unbound or why)
    flag = bool(verdict.get("kf_player_kill" if role == "killer" else "kf_player_death"))
    me = ({"value": flag, "reason": None} if printed or flag
          else {"value": None, "reason": "capture_prints_no_me"})
    nc = _claim(verdict, role, NAME_CHANNEL)
    name = _player_witness(nc.get("agent") if nc else None, side, bound,
                           unbound or ((nc or {}).get("reason") or "no_name_cluster"))
    name["rests_on"] = PORTRAIT_CHANNEL
    witnesses = {"side_portrait": portrait, "me": me, "name_cluster": name}
    basis = next((w for w in WITNESSES if witnesses[w]["value"] is not None), None)
    value = witnesses[basis]["value"] if basis else None
    return {"role": role, "side": side, "is_player": value, "basis": basis,
            "reason": None if basis else "; ".join(
                f"{w}:{witnesses[w]['reason']}" for w in WITNESSES),
            "witnesses": witnesses,
            "disagreements": [w for w in WITNESSES if witnesses[w]["value"] is not None
                              and witnesses[w]["value"] != value]}


def entry_counts(verdict: dict, roles: dict) -> dict:
    """Whether the entry is the player's kill or death, None where unread."""
    etype = (verdict.get("entry_type") or {}).get("type") or "kill"
    countable = etype == "kill" and not verdict.get("is_second_life") and not verdict.get("is_revive")
    if not countable:
        return {"countable": False, "kill": False, "death": False,
                "why": "second_life" if verdict.get("is_second_life") else etype}
    killer, victim = roles["killer"], roles["victim"]
    cross = verdict.get("same_side") is False
    kill = (killer["is_player"] and cross) if killer["is_player"] is not None else None
    if killer["is_player"] is True and not cross:
        kill = False
    return {"countable": True, "kill": kill, "death": victim["is_player"], "why": None}


def adjudicate(death_rows: list[dict], player: dict, session_id: str) -> list[dict]:
    """The `self_entry` stream: a summary, one row per entry, one per round."""
    verdicts = [r for r in death_rows if r.get("kind") == "death_verdict"]
    printed = me_printed(verdicts)
    common = {"session_id": session_id, "source": "self_entry",
              "self_entry_version": SELF_ENTRY_VERSION}
    entries, rounds = [], {}
    basis, agree, refused = Counter(), Counter(), Counter()
    for v in sorted(verdicts, key=lambda r: (r.get("t_ms") or 0, r.get("death_id") or "")):
        roles = {role: role_verdict(v, role, player, printed) for role in ROLES}
        counts = entry_counts(v, roles)
        for r in roles.values():
            basis[r["basis"] or "none"] += 1
            p, m = r["witnesses"]["side_portrait"]["value"], r["witnesses"]["me"]["value"]
            if p is not None and m is not None:
                agree["agree" if p == m else f"disagree:portrait_{p}_me_{m}"] += 1
            if p is None:
                refused[r["witnesses"]["side_portrait"]["reason"]] += 1
        rn = v.get("round_no")
        rr = rounds.setdefault(rn, {"round_no": rn, "kills": 0, "deaths": 0,
                                    "unread_kills": 0, "unread_deaths": 0})
        if counts["countable"]:
            for k, field in (("kill", "kills"), ("death", "deaths")):
                if counts[k] is None:
                    rr["unread_" + field] += 1
                elif counts[k]:
                    rr[field] += 1
        entries.append({**common, "kind": "entry", "death_id": v.get("death_id"),
                        "round_no": rn, "t_ms": v.get("t_ms"), "slot": v.get("slot"),
                        "entry_type": (v.get("entry_type") or {}).get("type"),
                        "is_second_life": v.get("is_second_life"), "counts": counts,
                        "roles": roles})
    per_round = [{**common, "kind": "round", **rounds[k]}
                 for k in sorted(rounds, key=lambda x: (x is None, x))]
    head = {**common, "kind": "summary",
            "player": {k: player.get(k) for k in ("agent", "status", "reason", "slot",
                                                   "player_agent_version")},
            "me_printed": printed, "entries": len(entries),
            "basis": dict(basis), "portrait_vs_me": dict(agree),
            "portrait_refusals": dict(refused),
            "kills": sum(r["kills"] for r in per_round),
            "deaths": sum(r["deaths"] for r in per_round),
            "unread_kills": sum(r["unread_kills"] for r in per_round),
            "unread_deaths": sum(r["unread_deaths"] for r in per_round),
            "inputs": {"death": next((r.get("death_adjudication_version") for r in death_rows
                                      if r.get("kind") == "summary"), None),
                       "player_agent": player.get("player_agent_version")}}
    return [head] + entries + per_round


def adjudicate_session(store, session_id: str) -> list[dict]:
    """`adjudicate` over a session's stored `death` stream and the player
    binding `identity.player_identity` reads from its lineup. Refuses a death
    stream that is missing or not at DEATH_ADJUDICATION_VERSION."""
    from ..lineup import load_lineup
    deaths = store.read_events("death", session_id)
    if not any(r.get("kind") == "death_verdict" for r in deaths):
        raise ValueError(f"{session_id}: no death verdicts")
    got = next((r.get("death_adjudication_version") for r in deaths
                if r.get("kind") == "summary"), None)
    if got != DEATH_ADJUDICATION_VERSION:
        raise ValueError(f"{session_id}: death stream at {got}, current is "
                         f"{DEATH_ADJUDICATION_VERSION}")
    player = player_identity(load_lineup(session_id, store.root), session_id)
    return adjudicate(deaths, player, session_id)


#: Which witness answered a consumer's K/D (`session_kd`).
KD_BASES = ("self_entry", "me")


def session_kd(store, session_id: str, me: dict | None = None) -> dict:
    """The player's session K/D for a consumer (module docstring): `status`
    (`ok` or `refused`), `basis`, `kills`, `deaths`, `unread_kills`,
    `unread_deaths`, `reason` (the refusal, kept beside a "Me" answer) and
    `entries` (this adjudication's entry rows, empty unless `basis` is
    `self_entry`). `me` is the HUD's "Me" count, `{"kills", "deaths"}`, or
    None where the caller has no HUD."""
    try:
        rows = adjudicate_session(store, session_id)
    except ValueError as e:
        why = str(e).removeprefix(f"{session_id}: ")
        unread = {"unread_kills": None, "unread_deaths": None, "entries": []}
        if me is None:
            return {"status": "refused", "basis": None, "kills": None, "deaths": None,
                    "reason": f"self_entry:{why}; me:no_hud", **unread}
        if not (me["kills"] or me["deaths"]):
            return {"status": "refused", "basis": None, "kills": None, "deaths": None,
                    "reason": f"self_entry:{why}; me:capture_prints_no_me", **unread}
        return {"status": "ok", "basis": "me", "kills": me["kills"], "deaths": me["deaths"],
                "reason": f"self_entry:{why}", **unread}
    head = rows[0]
    return {"status": "ok", "basis": "self_entry", "kills": head["kills"],
            "deaths": head["deaths"], "unread_kills": head["unread_kills"],
            "unread_deaths": head["unread_deaths"], "reason": None,
            "entries": [r for r in rows if r["kind"] == "entry"]}


def round_kd(kd: dict, rounds: list[dict]) -> dict[int, dict]:
    """`session_kd`'s answer per round of `rounds` (`build_rounds` rows):
    round_no -> `kills`, `deaths`, `unread_kills`, `unread_deaths`, `basis`,
    `reason`. A `self_entry` entry joins the round the rounds owner places its
    time in (`rounds.round_containing`); one outside every round counts only
    in the session total. A `me` answer is the round's own killfeed count."""
    from ..rounds import round_containing
    out = {r["round_no"]: {"kills": None, "deaths": None, "unread_kills": None,
                           "unread_deaths": None, "basis": kd["basis"], "reason": kd["reason"]}
           for r in rounds}
    if kd["basis"] == "me":
        for r in rounds:
            out[r["round_no"]].update(kills=r["player_kills"], deaths=r["player_deaths"])
    elif kd["basis"] == "self_entry":
        for v in out.values():
            v.update(kills=0, deaths=0, unread_kills=0, unread_deaths=0)
        for e in kd["entries"]:
            c = e["counts"]
            r = round_containing(e["t_ms"], rounds) if c["countable"] else None
            if r is None:
                continue
            v = out[r["round_no"]]
            for k, field in (("kill", "kills"), ("death", "deaths")):
                if c[k] is None:
                    v["unread_" + field] += 1
                elif c[k]:
                    v[field] += 1
    return out
