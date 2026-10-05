r"""Replay Riot's match records through the credit ledger.

    .\.venv\Scripts\python.exe prototypes\riot_economy.py [--record] [--json OUT.json]

Each Riot round result carries every player's `remaining` and `spent`
credits after the buy phase, so `remaining + spent` is that player's wallet
when the round opened. This script drives `reticle.economy.EconomyTracker`,
the owner of the credit rules (ownership `credit-ledger`), unchanged over the 22
stored records (`external/riot/*.json` in the store):

* at match start, the halftime round and every overtime round it applies the
  owner's `reset_period` and compares the reset with Riot's wallets;
* every other played round it anchors each player at Riot's `remaining` after
  the buy phase, settles the round from Riot's kills, plant and result, and
  compares the predicted wallets with the next round's.

A team-round is reproduced when the team's predicted wallet total equals
Riot's. Totals are the unit because a drop or a sale moves credits between
teammates: `remaining + spent` reaches 11,850 for one player, past the 9,000
cap, so it is no single player's wallet, while the team's total balances.
Per-player agreement is reported beside it.

`ALTERNATIVES` changes one rule at a time; a rule is load-bearing when the
change loses team-rounds.

The inputs it builds, and nothing else: a kill pays its killer when the victim
is on the other team (a spike death names the victim as its own killer);
`survived` is a losing player Riot's kills never name as victim; `planted` is
any plant, post-round included; `spike_detonated` is a `Detonate` result.
Surrendered rounds carry no economy and end the comparison.

`--record` appends one `riot_economy` metrics row. Riot's records are an
external witness: this never feeds a production reader.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
if sys.platform == "win32" and __name__ == "__main__":
    import ctypes
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                            0x4000)  # Below Normal
from collections import Counter
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reticle.economy import EconomyRules, EconomyTracker, RoundEconomyInput  # noqa: E402
from reticle.rounds import side_in_round  # noqa: E402

STORE = Path.home() / "reticle-store"
HALF = 12          # rounds per half before overtime, 0-indexed boundary
OVERTIME = 24      # the first overtime round, 0-indexed
PLAYED = ("Elimination", "Defuse", "Detonate", "")   # "" is "Round timer expired"


def load_records(store_root: Path = STORE) -> list[tuple[str, dict]]:
    """(session id, match) for every stored Riot record, by session id."""
    out = []
    for p in sorted((Path(store_root) / "external" / "riot").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append((d["probe"]["session_id"], d["match"]))
    return sorted(out, key=lambda x: x[0])


def _teams(m: dict) -> dict[str, tuple[str, ...]]:
    teams: dict[str, list[str]] = {}
    for p in m["players"]:
        if not p.get("isObserver"):
            teams.setdefault(p["teamId"], []).append(p["subject"])
    return {t: tuple(sorted(ps)) for t, ps in teams.items()}


def _attackers(m: dict, teams: dict) -> dict[int, str]:
    """The attacking team per round, from any round's winner and role.

    The side rule is the rounds owner's (`rounds.side_in_round`, by match
    round counted from 1 [domain:rounds/side-by-round]); Riot's `roundNum`
    counts from 0. The first round naming its winner's role fixes the team
    that started on attack."""
    names = sorted(teams)

    def other(t):
        return next(x for x in names if x != t)

    def starts_on_attack(n: int) -> bool:
        return side_in_round(n + 1, "attack")[0] == "attack"

    first = None
    for r in m["roundResults"]:
        role, win = r.get("winningTeamRole"), r.get("winningTeam")
        if role in ("Attacker", "Defender") and win in teams:
            att = win if role == "Attacker" else other(win)
            first = att if starts_on_attack(r["roundNum"]) else other(att)
            break
    return {r["roundNum"]: first if starts_on_attack(r["roundNum"]) else other(first)
            for r in m["roundResults"]}


def _wallets(r: dict) -> dict[str, int]:
    return {e["subject"]: int(e["remaining"]) + int(e["spent"])
            for e in (r.get("playerEconomies") or [])}


def _period(n: int) -> str:
    if n == 0:
        return "match_start"
    if n == HALF:
        return "halftime"
    if n >= OVERTIME:
        return "overtime"
    return "regular"


def round_input(m: dict, r: dict, teams: dict, attacker: str) -> RoundEconomyInput:
    n = r["roundNum"]
    team_of = {p: t for t, ps in teams.items() for p in ps}
    kills = {p: 0 for p in team_of}
    victims = set()
    for k in m["kills"]:
        if k["round"] != n:
            continue
        victims.add(k["victim"])
        killer = k.get("killer")
        if killer in team_of and team_of[killer] != team_of.get(k["victim"]):
            kills[killer] += 1
    winner = r["winningTeam"]
    loser = next(t for t in teams if t != winner)
    planted = bool(r.get("bombPlanter")) or (r.get("plantRoundTime") or 0) > 0
    return RoundEconomyInput(
        round_no=n + 1, winner=winner, attacking_team=attacker,
        planted=planted, spike_detonated=r["roundResultCode"] == "Detonate",
        kills=kills, survived={p: p not in victims for p in teams[loser]},
        source_ids=(f"riot-round:{n}",))


def post_round_plant(m: dict, r: dict) -> bool:
    """A plant after the attackers eliminated every defender."""
    if not ((r.get("plantRoundTime") or 0) > 0 and r["roundResultCode"] == "Elimination"
            and r.get("winningTeamRole") == "Attacker"):
        return False
    last = max((k["roundTime"] for k in m["kills"] if k["round"] == r["roundNum"]), default=0)
    return r["plantRoundTime"] > last


def replay(sid: str, m: dict, rules: EconomyRules | None = None) -> list[dict]:
    """One row per team-round: Riot's wallet total and the ledger's."""
    rules = rules or EconomyRules()
    teams = _teams(m)
    att = _attackers(m, teams)
    rounds = sorted(m["roundResults"], key=lambda r: r["roundNum"])
    tracker = EconomyTracker(teams, rules)
    rows: list[dict] = []
    prev = prev_r = None
    for r in rounds:
        n = r["roundNum"]
        if r["roundResultCode"] not in PLAYED:
            break
        wallets = _wallets(r)
        period = _period(n)
        txs = []
        if period != "regular":
            tracker.reset_period(n + 1, period)
        elif prev is None:
            break
        else:
            txs = tracker.settle_round(prev)
        predicted = {p: tracker.balances[p] for p in wallets}
        for team, players in teams.items():
            obs = sum(wallets[p] for p in players)
            lo = sum(predicted[p].minimum for p in players)
            hi = sum(predicted[p].maximum for p in players)
            kinds = Counter(f"{t.kind}:{t.reason}" for t in txs if t.team_id == team)
            rows.append({
                "session": sid, "round": n, "team": team, "period": period,
                "observed": obs, "predicted_min": lo, "predicted_max": hi,
                "ok": lo == obs == hi,
                "players_ok": sum(predicted[p].minimum == wallets[p] == predicted[p].maximum
                                  for p in players),
                "players": len(players),
                "max_remaining": max(int(e["remaining"]) for e in r["playerEconomies"]
                                     if e["subject"] in players),
                "capped": sum(t.balance_before.maximum + t.amount.maximum
                              > rules.credit_cap for t in txs if t.team_id == team),
                "settled_code": prev_r["roundResultCode"] if prev_r and txs else None,
                "settled_winner": prev.winner == team if prev and txs else None,
                "settled_attacker": prev.attacking_team == team if prev and txs else None,
                "kinds": dict(kinds),
                # AFK in the round this row settles, not the round it opens.
                "afk_settled": [p for p in players if txs and any(
                    ps["subject"] == p and ps.get("wasAfk") for ps in prev_r["playerStats"])],
                # Riot's wallet less the ledger's, per player (exact predictions only).
                "residuals": {p: wallets[p] - predicted[p].minimum for p in players
                              if predicted[p].value is not None},
            })
        # Anchor at Riot's `remaining` after the buy phase; settle next turn.
        for e in r["playerEconomies"]:
            tracker.observe_balance(e["subject"], int(e["remaining"]), round_no=n + 1)
        prev, prev_r = round_input(m, r, teams, att[n]), r
    return rows


#: One rule changed at a time; a rule is load-bearing when its change loses
#: team-rounds the owner's rules reproduce.
ALTERNATIVES = {
    "plant_200": {"plant_reward": 200},
    "overtime_800": {"overtime_credits": 800},
    "no_cap": {"credit_cap": 10 ** 6},
    "flat_loss_1900": {"loss_rewards": (1900,)},
    "survival_1900": {"survival_reward": 1900},
    "kill_150": {"kill_reward": 150},
}


def alternative_rules(name: str) -> EconomyRules:
    return replace(EconomyRules(), **ALTERNATIVES[name])


def rule_counts(records) -> dict:
    """Facts the reproduced rounds carry: plants, survivals, defuses, the cap."""
    c = Counter()
    for sid, m in records:
        teams = _teams(m)
        for r in m["roundResults"]:
            if r["roundResultCode"] not in PLAYED:
                continue
            c["rounds_played"] += 1
            if (r.get("plantRoundTime") or 0) > 0 or r.get("bombPlanter"):
                c["plant_rounds"] += 1
                c["post_round_plants"] += post_round_plant(m, r)
            c["defuse_rounds"] += r["roundResultCode"] == "Defuse"
            c["detonate_rounds"] += r["roundResultCode"] == "Detonate"
            c["afk_player_rounds"] += sum(bool(ps.get("wasAfk")) for ps in r["playerStats"])
        c["kills"] += len(m["kills"])
        c["spike_kills"] += sum(k["finishingDamage"]["damageType"] == "Bomb" for k in m["kills"])
        c["matches"] += 1
        c[f"{m['matchInfo']['queueID']}_matches"] += 1
        c["players_afk_rounds"] += sum(1 for p in m["players"]
                                       if (p.get("behaviorFactors") or {}).get("afkRounds"))
        # An abandon would show as a second participation period or fewer
        # rounds played than the match's other players.
        played = max(p["stats"]["roundsPlayed"] for p in m["players"])
        c["players_multi_period"] += sum(len(p.get("participationPeriods") or []) != 1
                                         for p in m["players"])
        c["players_short_rounds"] += sum(p["stats"]["roundsPlayed"] < played
                                         for p in m["players"])
        del teams
    return dict(c)


def summarise(rows: list[dict]) -> dict:
    out = {}
    for period in ("match_start", "halftime", "overtime", "regular"):
        sel = [r for r in rows if r["period"] == period]
        out[f"{period}_n"] = len(sel)
        out[f"{period}_ok"] = sum(r["ok"] for r in sel)
        out[f"{period}_players_n"] = sum(r["players"] for r in sel)
        out[f"{period}_players_ok"] = sum(r["players_ok"] for r in sel)
    out["max_remaining"] = max(r["max_remaining"] for r in rows)
    ok = [r for r in rows if r["ok"] and r["period"] == "regular"]
    kinds = Counter()
    for r in ok:
        kinds.update(r["kinds"])
    for key, field in (("loss_streak_1", "round_loss_reward:loss_streak_1"),
                       ("loss_streak_2", "round_loss_reward:loss_streak_2"),
                       ("loss_streak_3", "round_loss_reward:loss_streak_3"),
                       ("survival", "survival_reward:qualifying_survived_loss"),
                       ("plant", "plant_reward:spike_planted")):
        out[f"ok_{key}_payments"] = kinds[field]
    out["ok_capped_payments"] = sum(r["capped"] for r in ok)
    out["ok_defuse_winner_rows"] = sum(1 for r in ok if r["settled_code"] == "Defuse"
                                       and r["settled_winner"])
    # The first round after halftime: a team that lost rounds 12 and 13 (1-based)
    # is paid the first loss step only if halftime resets the streak.
    out["ok_post_halftime_rows"] = sum(1 for r in ok if r["round"] == HALF + 1)
    afk = [r for r in rows if r["afk_settled"]]
    out["afk_rows"] = len(afk)
    out["afk_rows_ok"] = sum(r["ok"] for r in afk)
    # The AFK player's own residual (the reward withheld) and each teammate's.
    own = [r["residuals"][p] for r in afk for p in r["afk_settled"]]
    mates = [v for r in afk for p, v in r["residuals"].items() if p not in r["afk_settled"]]
    out["afk_own_residual_min"] = min(own, default=None)
    out["afk_own_residual_max"] = max(own, default=None)
    out["afk_teammate_residual_min"] = min(mates, default=None)
    out["afk_teammate_residual_max"] = max(mates, default=None)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--record", action="store_true", help="append a riot_economy metrics row")
    ap.add_argument("--json", help="write every team-round row here")
    a = ap.parse_args(argv)
    records = load_records(Path(a.store))
    rows = [row for sid, m in records for row in replay(sid, m)]
    s = summarise(rows)
    alt = {}
    for name in ALTERNATIVES:
        rules = alternative_rules(name)
        alt_rows = [row for sid, m in records for row in replay(sid, m, rules)]
        alt_s = summarise(alt_rows)
        alt[f"{name}_regular_ok"] = alt_s["regular_ok"]
        alt[f"{name}_overtime_ok"] = alt_s["overtime_ok"]
    counts = rule_counts(records)
    misses = [r for r in rows if not r["ok"]]
    print(json.dumps({"summary": s, "alternatives": alt, "counts": counts,
                      "misses": misses}, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    if a.record:
        from reticle import metrics
        from reticle.version import ECONOMY_VERSION
        metrics.record("riot_economy", part="team_rounds",
                       values={**s, **alt, **counts, "misses": len(misses)},
                       deps={"economy_version": ECONOMY_VERSION,
                             "replay": metrics.fingerprint(replay, round_input, _attackers)},
                       context={"records": len(records)},
                       note="Riot wallets (remaining+spent) against EconomyTracker anchored at remaining")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
