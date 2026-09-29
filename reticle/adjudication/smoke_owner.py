"""Which ally agent cast each minimap smoke: claims through the identity arbiter.

    .\\.venv\\Scripts\\python.exe -m reticle smokes <session>

Owns [owns:smoke-owner].

Reads storage only: the `smoke` tracks `adjudication.smokes` recomputes, the
lineup's identity verdicts (`lineup.load_lineup`, through `ult_cast`'s
`lineup_sides` and `player_agent`), and, where the player's agent is one of the
team's smoke agents, the player's tray casts as `ability_timeline
.player_tray_casts` decides them. It decodes nothing.

Only the player's team's smokes are drawn
[domain:abilities/enemy-smokes-not-on-minimap], so the candidates are the ally
side's smoke agents (`SMOKE_ABILITY`). The player gave three ways to name one
[domain:abilities/smoke-attribution], and each is an identity channel:

* `team_smoke_agent` -- the ally side has one smoke agent.
* `smoke_lifetime` -- the track's lifetime fits one candidate's measured disc
  lifetime (`LIFETIME_S`) and no other candidate's lies within error of it.
  Only a track with both ends observed has a lifetime; a censored track has a
  lower bound, which names a candidate only by excluding every other one
  whose lifetime is shorter.
  A candidate with no measurement has no lifetime rule, so the channel
  abstains while one is in the set [domain:abilities/ability-rules-are-unique].
* `player_tray` -- the player's agent is a candidate and the tray shows the
  player casting its smoke slot inside that agent's cast window
  (`CAST_WINDOW_S`) before the birth; with two candidates and no drop of that
  slot in the window, the smoke is the other's. Only Omen has a window.

Smokes born in the same sample with both onsets observed are one cast from one
agent, and never Omen's or Astra's [domain:abilities/smoke-bulk-confirm]:
each member's candidates lose Omen and Astra, and a member named by its own
evidence names the others on channel `bulk_cast`, declaring `depends_on`.

Every claim that rests on the lineup declares `depends_on` the ally slots'
entity ids, so no channel here counts as an independent witness; a track's
`agent` is the arbiter's verdict and nothing else. A refused track keeps its
reason: `no_lineup`, `ally_side_incomplete`, `no_team_smoke_agent`,
`lifetimes_within_error`, `no_lifetime_for`, `censored_lifetime`,
`lifetime_fits_no_candidate`, `tray_cast_conflict` or `conflicting_claims`.

Enemy smokes show only as missing cone light
[domain:minimap/enemy-smokes-block-cones] and wait on the stored team vision.
"""
from __future__ import annotations

from collections import defaultdict

from ..version import SMOKE_OWNER_VERSION
from .identity import adjudicate_agent_identity, identity_claim, identity_events
from .ult_cast import lineup_sides, player_agent

#: The agents whose kit draws a smoke on the caster's team's minimap, with the
#: tray slot of that smoke. The wiki harvest (`reference/abilities.json`,
#: 2026-09-04) classes these abilities Smoke or Vision Blocker; Astra's Nebula
#: draws a dark disc [domain:abilities/astra-nebula-minimap-disc]. A candidate
#: is excluded by evidence, never by omission, so an agent whose ability may
#: draw no disc (Cyber Cage, Cove) stays in the set and can only cost a name.
SMOKE_ABILITY = {
    "Astra": ("E", "nebula"), "Brimstone": ("E", "sky smoke"),
    "Clove": ("E", "ruse"), "Cypher": ("Q", "cyber cage"),
    "Harbor": ("E", "cove"), "Jett": ("C", "cloudburst"),
    "Miks": ("E", "waveform"), "Omen": ("E", "dark cover"),
    "Viper": ("Q", "poison cloud"),
}
#: Agents that cannot place two smokes in one cast
#: [domain:abilities/smoke-bulk-confirm].
NO_BULK = frozenset({"Omen", "Astra"})

#: Per agent, (shortest, longest) minimap disc lifetime in seconds as the
#: smoke tracker reads it, and its source. Miks: the tracks named by the lone
#: team smoke agent on a06f04a0059f with both ends observed,
#: [metric:smokes/lifetime-miks@a06f04a0059f#both_ends=22] of them, read
#: [metric:smokes/lifetime-miks@a06f04a0059f#life_min_s=17.75] to
#: [metric:smokes/lifetime-miks@a06f04a0059f#life_max_s=18.0] s at 4 Hz, the
#: disc's 18.2 s [domain:abilities/miks-smoke-minimap-disc] less the tracker's
#: quantization. Omen and Jett: their own measured minimap discs
#: [domain:abilities/omen-dark-cover] [domain:abilities/jett-cloudburst-duration];
#: no stored `minimap_dark` session holds either, so the tracker has not read
#: them. No other smoke agent has a measurement, and none is inferred.
LIFETIME_S = {
    "Miks": (17.75, 18.0, "tracker"),
    "Omen": (15.0, 15.0, "domain"),
    "Jett": (2.75, 3.0, "domain"),
}
#: Per agent, (earliest, latest) disc birth minus the player's tray drop, in
#: seconds. Omen's disc appears within 3.2 s of the cast
#: [domain:abilities/omen-dark-cover]; no other agent's lag is measured.
CAST_WINDOW_S = {"Omen": (0.0, 3.2)}
#: A tray refusal that says the player could not have cast: the tray shows a
#: spectated kit, or the drop spent no charge. Any other refusal of a smoke-slot
#: drop in the window leaves the cast open.
NOT_A_PLAYER_CAST = ("after_player_death", "after_kit_change", "equip_release")

CHANNELS = ("team_smoke_agent", "smoke_lifetime", "player_tray", "bulk_cast")


def tolerance_s(hz: float | None) -> float:
    """A tracker lifetime's error: onset and end are each quantized to one
    sample period, so two periods."""
    return 2.0 / float(hz or 4.0)


def window(agent: str, tol: float) -> tuple[float, float] | None:
    """The agent's measured lifetime widened by `tol`, or None."""
    got = LIFETIME_S.get(agent)
    return None if got is None else (got[0] - tol, got[1] + tol)


def lifetime_verdict(track: dict, candidates: list[str], tol: float) -> tuple[str | None, str | None, dict]:
    """(agent or None, the reason for None, evidence) from a track's lifetime
    among `candidates`. See the module docstring."""
    life = float(track["life_s"])
    both = track["onset_status"] == "observed" and track["end_status"] == "observed"
    unmeasured = sorted(a for a in candidates if a not in LIFETIME_S)
    ev = {"life_s": life, "both_ends": both, "tol_s": tol,
          "windows": {a: window(a, tol) for a in candidates if a in LIFETIME_S}}
    if not candidates:
        return None, "no_candidate", ev
    if both:
        fits = [a for a in candidates if a in LIFETIME_S
                and window(a, tol)[0] <= life <= window(a, tol)[1]]
    else:
        # A censored track was present at least this long.
        fits = [a for a in candidates if a in LIFETIME_S and life <= window(a, tol)[1]]
    ev["fits"] = fits
    if unmeasured:
        return None, "no_lifetime_for " + " ".join(unmeasured), ev
    if not fits:
        return None, "lifetime_fits_no_candidate", ev
    if len(fits) > 1:
        return None, ("lifetimes_within_error " if both else "censored_lifetime ") + " ".join(fits), ev
    if not both and len(candidates) == 1:
        # A lower bound that excludes nobody is no lifetime evidence.
        return None, "censored_lifetime " + fits[0], ev
    a = fits[0]
    lo, hi = window(a, tol)
    near = sorted(b for b in candidates if b != a
                  and window(b, tol)[0] <= hi and lo <= window(b, tol)[1])
    if near:
        return None, "lifetimes_within_error " + " ".join([a] + near), ev
    return a, None, ev


def cast_groups(tracks: list[dict]) -> dict[int, list[int]]:
    """Per track, the tracks born in its sample with both onsets observed
    (itself included); a track with a censored onset is alone."""
    by_birth = defaultdict(list)
    for t in tracks:
        if t["onset_status"] == "observed":
            by_birth[t["first_ms"]].append(t["track"])
    return {t["track"]: (by_birth[t["first_ms"]] if t["onset_status"] == "observed"
                         else [t["track"]]) for t in tracks}


def player_smoke_casts(drop_rows: list[dict], rounds: list[dict], **gate) -> list[dict]:
    """The drops of the player's smoke slot among a session's stored
    `tray_drop` rows, each with the `player_cast` and `reason` that
    `ability_timeline.player_tray_casts` gives it. Every slot's drops go in,
    because the owner's co-occurrence test reads them all. `gate` carries the
    owner's other inputs, the player's `agent` among them, as
    `ability_timeline.stored_gate_inputs` reads them."""
    from ..ability_timeline import player_tray_casts
    from .ult_cast import DROP_FIELDS
    slot = SMOKE_ABILITY[gate["agent"]][0]
    drops = [{k: r[k] for k in DROP_FIELDS if k in r} for r in drop_rows
             if r.get("kind") == "drop"]
    return [r for r in player_tray_casts(drops, rounds=rounds, **gate) if r["slot"] == slot]


def tray_verdict(birth_ms: float, player: str, others: list[str],
                 casts: list[dict] | None, tray_reason: str | None) -> tuple[str | None, str | None, dict]:
    """(agent or None, the reason for None, evidence) from the player's tray
    around a birth. `casts` are the owner's verdicts on the session's drops."""
    if casts is None:
        return None, tray_reason or "no_tray_drops", {}
    win = CAST_WINDOW_S.get(player)
    if win is None:
        return None, f"no_cast_window_for {player}", {}
    slot = SMOKE_ABILITY[player][0]
    near = [c for c in casts if c["slot"] == slot
            and win[0] <= (birth_ms - float(c["t_ms"])) / 1000.0 <= win[1]]
    own = [c for c in near if c["player_cast"]]
    ev = {"slot": slot, "window_s": list(win),
          "drops": [{"t_ms": c["t_ms"], "player_cast": c["player_cast"], "reason": c.get("reason")}
                    for c in near]}
    if own:
        return player, None, ev
    open_ = [c for c in near if not any(str(c.get("reason") or "").startswith(r)
                                        for r in NOT_A_PLAYER_CAST)]
    if open_:
        return None, "tray_drop_refused " + str(open_[0].get("reason")), ev
    if len(others) == 1:
        return others[0], None, {**ev, "rule": "no_player_cast_in_window"}
    return None, "no_player_cast_and_" + str(len(others)) + "_other_candidates", ev


def adjudicate(session_id: str, smoke_rows: list[dict], lineup: dict | None, *,
               hz: float | None = None, tray_casts: list[dict] | None = None,
               tray_reason: str | None = "tray_not_read") -> dict:
    """The session's stored rows, claims, verdicts and formal identity events.

    `tray_casts` are `ability_timeline.player_tray_casts` rows over the
    session's stored drops, or None with `tray_reason`."""
    head = next((r for r in smoke_rows if r.get("kind") == "coverage"), {}) or {}
    tracks = [r for r in smoke_rows if r.get("kind") == "track"]
    sides = lineup_sides(lineup, session_id)
    player = player_agent(lineup, session_id)
    tol = tolerance_s(hz)
    groups = cast_groups(tracks)
    eid = {t["track"]: f"{session_id}:smoke:{int(round(t['first_ms']))}:{t['track']}"
           for t in tracks}
    ally = sides["ally"] if sides else None
    team = sorted(a for a in (ally["named"] if ally else []) if a in SMOKE_ABILITY)
    slots = ally["slots"] if ally else []
    player_slot = next((s for s in slots if lineup and s.endswith(
        f":slot:{(lineup.get('player') or {}).get('slot')}")), None)

    claims, meta = [], {}
    for t in tracks:
        e = eid[t["track"]]
        base = dict(observed_at_ms=t["first_ms"], source_version=SMOKE_OWNER_VERSION)
        group = groups[t["track"]]
        cands = [a for a in team if not (len(group) > 1 and a in NO_BULK)]
        meta[e] = {"track": t, "group": group, "candidates": cands}
        if ally is None:
            claims.append(identity_claim(e, None, channel="team_smoke_agent",
                                         reason="no_lineup", **base))
            continue
        if not ally["complete"]:
            claims.append(identity_claim(
                e, None, channel="team_smoke_agent", depends_on=slots, **base,
                reason=f"ally_side_incomplete {ally['refused']}_unresolved"))
            continue
        if not cands:
            claims.append(identity_claim(
                e, None, channel="team_smoke_agent", depends_on=slots, **base,
                reason="no_team_smoke_agent" if not team else "bulk_excludes " + " ".join(team),
                evidence={"team": team, "group": group}))
            continue
        claims.append(identity_claim(
            e, cands[0] if len(cands) == 1 else None, channel="team_smoke_agent",
            depends_on=slots, **base,
            reason=None if len(cands) == 1 else "team_smoke_agents " + " ".join(cands),
            evidence={"team": team, "candidates": cands, "group": group}))
        agent, why, ev = lifetime_verdict(t, cands, tol)
        claims.append(identity_claim(e, agent, channel="smoke_lifetime", reason=why,
                                     depends_on=slots, evidence=ev, **base))
        if player in cands:
            agent, why, ev = tray_verdict(t["first_ms"], player,
                                          [a for a in cands if a != player],
                                          tray_casts, tray_reason)
            claims.append(identity_claim(e, agent, channel="player_tray", reason=why,
                                         depends_on=[player_slot] if player_slot else slots,
                                         evidence=ev, **base))

    # One cast, one agent: a member its own evidence names names the others.
    first = {v["entity_id"]: v for v in adjudicate_agent_identity(claims)}
    for e, m in meta.items():
        if len(m["group"]) < 2:
            continue
        mates = [eid[k] for k in m["group"] if eid[k] != e]
        named = sorted({first[x]["agent"] for x in mates if first[x]["status"] == "resolved"})
        if len(named) == 1:
            claims.append(identity_claim(
                e, named[0], channel="bulk_cast", observed_at_ms=m["track"]["first_ms"],
                source_version=SMOKE_OWNER_VERSION,
                depends_on=[x for x in mates if first[x]["agent"] == named[0]],
                evidence={"group": m["group"]}))

    verdicts = {v["entity_id"]: v for v in adjudicate_agent_identity(claims)}
    common = {"session_id": session_id, "smoke_owner_version": SMOKE_OWNER_VERSION,
              "smoke_version": head.get("smoke_version")}
    rows, events = [], []
    for e, m in meta.items():
        t, v = m["track"], verdicts[e]
        by = v["by_channel"]
        reason = None
        if v["status"] == "disagreement":
            reason = "tray_cast_conflict" if "player_tray" in v["channels"] else "conflicting_claims"
        elif v["status"] != "resolved":
            reason = next((by[ch]["reason"] for ch in ("smoke_lifetime", "player_tray")
                           if ch in by and by[ch]["reason"]), None) or by.get(
                "team_smoke_agent", {}).get("reason") or v["reason"]
        rows.append({**common, "kind": "smoke_owner", "entity_id": e, "track": t["track"],
                     "first_ms": t["first_ms"], "last_ms": t["last_ms"], "life_s": t["life_s"],
                     "onset_status": t["onset_status"], "end_status": t["end_status"],
                     "cx": t["cx"], "cy": t["cy"],
                     "agent": v["agent"] if v["status"] == "resolved" else None,
                     "identity_status": v["status"], "reason": reason,
                     "rules": v["channels"], "candidates": m["candidates"],
                     "cast_group": [eid[k] for k in m["group"]],
                     "by_channel": {ch: {"agent": r["agent"], "reason": r["reason"]}
                                    for ch, r in by.items()},
                     "evidence": {c["channel"]: c["evidence"] for c in v["claims"]
                                  if c["evidence"]},
                     "depends_on": v["depends_on"]})
        events += identity_events([v], session_id, t["first_ms"])
    named = [r for r in rows if r["agent"]]
    refused = defaultdict(int)
    for r in rows:
        if not r["agent"]:
            refused[str(r["reason"]).split(" ")[0]] += 1
    cover = {**common, "kind": "coverage", "lineup": ally is not None,
             "team_smoke_agents": team, "player_agent": player, "tolerance_s": tol,
             "tray": {"read": tray_casts is not None, "reason": tray_reason},
             "tracks": len(rows), "named": len(named),
             "by_agent": {a: sum(r["agent"] == a for r in named)
                          for a in sorted({r["agent"] for r in named})},
             "by_rule": {ch: sum(ch in r["rules"] for r in named) for ch in CHANNELS},
             "refused": dict(sorted(refused.items()))}
    return {"rows": [cover] + rows, "events": events, "claims": claims}
