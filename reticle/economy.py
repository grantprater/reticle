"""Pure, versioned Valorant credit accounting.

This module consumes adjudicated facts; it does not read video or turn a weapon
observation into a purchase.  Balances are intervals because missing purchases,
plants, survival and kill attribution must remain unknown rather than becoming
zero.  A later credit reader can anchor an interval without erasing the residual
between the observation and the prior ledger.

Owns [owns:credit-ledger].
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from .version import ECONOMY_VERSION


@dataclass(frozen=True, order=True)
class CreditRange:
    minimum: int
    maximum: int

    def __post_init__(self):
        if self.minimum < 0 or self.maximum < self.minimum:
            raise ValueError("credit range must satisfy 0 <= minimum <= maximum")

    @classmethod
    def exact(cls, value: int) -> "CreditRange":
        return cls(value, value)

    def add_capped(self, amount: "CreditRange", cap: int) -> "CreditRange":
        return CreditRange(min(cap, self.minimum + amount.minimum),
                           min(cap, self.maximum + amount.maximum))

    def spend(self, amount: "CreditRange") -> "CreditRange":
        if amount.minimum > self.maximum:
            raise ValueError("minimum spend exceeds possible balance")
        if amount.maximum > self.maximum:
            raise ValueError("maximum spend exceeds possible balance")
        # Balance and spend may be correlated.  These are conservative bounds,
        # not a claim that every value inside the interval is feasible.
        return CreditRange(max(0, self.minimum - amount.maximum),
                           self.maximum - amount.minimum)

    @property
    def value(self) -> int | None:
        return self.minimum if self.minimum == self.maximum else None


@dataclass(frozen=True)
class EconomyRules:
    starting_credits: int = 800
    credit_cap: int = 9000
    win_reward: int = 3000
    loss_rewards: tuple[int, ...] = (1900, 2400, 2900)
    survival_reward: int = 1000
    kill_reward: int = 200
    plant_reward: int = 300
    version: str = ECONOMY_VERSION

    def loss_reward(self, streak_including_round: int) -> int:
        if streak_including_round < 1:
            raise ValueError("loss streak must include at least the current loss")
        return self.loss_rewards[min(streak_including_round, len(self.loss_rewards)) - 1]


@dataclass(frozen=True)
class RoundEconomyInput:
    round_no: int
    winner: str
    attacking_team: str
    planted: bool | None
    spike_detonated: bool | None
    # Every player must be present. An uncertain count is an explicit (min, max).
    kills: Mapping[str, int | tuple[int, int]]
    # Every player on the losing team must be present. None means unread.
    survived: Mapping[str, bool | None]
    settlement_t_ms: float | None = None
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EconomyTransaction:
    sequence: int
    round_no: int | None
    t_ms: float | None
    player_id: str
    team_id: str
    kind: str
    amount: CreditRange
    balance_before: CreditRange | None
    balance_after: CreditRange
    reason: str
    source_ids: tuple[str, ...]
    economy_version: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BalanceReconciliation:
    player_id: str
    observed: int
    predicted: CreditRange | None
    residual: tuple[int, int] | None
    status: str
    transaction_sequence: int


def survival_penalty(side: str, survived: bool | None,
                     planted: bool | None, spike_detonated: bool | None) -> bool | None:
    """Whether a losing player receives 1000 instead of the loss-streak award.

    ``side`` is the player's side for this round. Unknown source facts propagate.
    This function does not decide whether the team lost; callers apply it only to
    losing players.
    """
    if side not in ("attack", "defence"):
        raise ValueError("side must be 'attack' or 'defence'")
    if survived is False:
        return False
    if survived is None:
        return None
    if side == "attack":
        return None if planted is None else not planted
    return None if spike_detonated is None else spike_detonated


def _count_range(value: int | tuple[int, int] | list[int]) -> CreditRange:
    if isinstance(value, int):
        return CreditRange.exact(value)
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise TypeError("count must be an int or a (minimum, maximum) tuple")
    return CreditRange(*value)


class EconomyTracker:
    """A match-scoped ledger over stable player identities.

    Construction does not assume the capture began at match start. Call
    ``reset_period`` at a known reset, or ``observe_balance`` for every player,
    before settling a round.
    """

    def __init__(self, teams: Mapping[str, tuple[str, ...] | list[str]],
                 rules: EconomyRules | None = None):
        self.rules = rules or EconomyRules()
        if len(teams) != 2:
            raise ValueError("economy requires exactly two teams")
        self.teams = {team: tuple(players) for team, players in teams.items()}
        if any(not players for players in self.teams.values()):
            raise ValueError("each team must contain at least one player")
        all_players = [p for players in self.teams.values() for p in players]
        if len(all_players) != len(set(all_players)):
            raise ValueError("player identities must be unique across teams")
        self.player_team = {p: team for team, players in self.teams.items() for p in players}
        self.balances: dict[str, CreditRange | None] = {p: None for p in all_players}
        self.loss_streaks = {team: 0 for team in self.teams}
        self.transactions: list[EconomyTransaction] = []
        self.last_settled_round: int | None = None

    def _append(self, player_id: str, kind: str, amount: CreditRange,
                before: CreditRange | None, after: CreditRange, reason: str,
                round_no: int | None, t_ms: float | None,
                source_ids: tuple[str, ...]) -> EconomyTransaction:
        tx = EconomyTransaction(len(self.transactions), round_no, t_ms, player_id,
                                self.player_team[player_id], kind, amount, before,
                                after, reason, source_ids, self.rules.version)
        self.transactions.append(tx)
        self.balances[player_id] = after
        return tx

    def reset_period(self, round_no: int, reason: str,
                     credits: int | None = None, t_ms: float | None = None,
                     source_ids: tuple[str, ...] = ()) -> None:
        """Apply a known match-start, halftime, overtime or observed reset."""
        if reason not in ("match_start", "halftime", "overtime", "observed_reset"):
            raise ValueError("unsupported reset reason")
        value = self.rules.starting_credits if credits is None else credits
        if not 0 <= value <= self.rules.credit_cap:
            raise ValueError("reset credits outside ruleset bounds")
        for player, before in self.balances.items():
            after = CreditRange.exact(value)
            # A reset assigns a balance; ``amount`` records that assigned value,
            # rather than pretending a reset that discards credits is income.
            self._append(player, "reset", CreditRange.exact(value), before, after, reason,
                         round_no, t_ms, source_ids)
        self.loss_streaks = {team: 0 for team in self.teams}
        self.last_settled_round = round_no - 1

    def observe_balance(self, player_id: str, credits: int, *, round_no: int | None,
                        t_ms: float | None = None,
                        source_ids: tuple[str, ...] = ()) -> BalanceReconciliation:
        self._require_player(player_id)
        if not 0 <= credits <= self.rules.credit_cap:
            raise ValueError("observed credits outside ruleset bounds")
        before = self.balances[player_id]
        status = ("initial_anchor" if before is None else
                  "consistent" if before.minimum <= credits <= before.maximum else
                  "conflict")
        residual = None if before is None else (credits - before.maximum,
                                                credits - before.minimum)
        tx = self._append(player_id, "balance_observation", CreditRange.exact(0),
                          before, CreditRange.exact(credits), status, round_no,
                          t_ms, source_ids)
        return BalanceReconciliation(player_id, credits, before, residual,
                                     status, tx.sequence)

    def record_spending(self, player_id: str, amount: int | tuple[int, int], *,
                        round_no: int, t_ms: float | None = None,
                        reason: str = "purchase_or_transfer",
                        source_ids: tuple[str, ...] = ()) -> EconomyTransaction:
        self._require_player(player_id)
        before = self._balance(player_id)
        spend = _count_range(amount)
        after = before.spend(spend)
        return self._append(player_id, "spend", spend, before, after, reason,
                            round_no, t_ms, source_ids)

    def settle_round(self, row: RoundEconomyInput) -> list[EconomyTransaction]:
        if row.round_no < 1:
            raise ValueError("round number must be positive")
        if row.winner not in self.teams or row.attacking_team not in self.teams:
            raise ValueError("winner and attacking team must identify tracked teams")
        if row.spike_detonated is True and row.planted is False:
            raise ValueError("spike detonation contradicts planted=False")
        if self.last_settled_round is not None and row.round_no != self.last_settled_round + 1:
            raise ValueError("rounds must be settled consecutively; reset or anchor the gap")
        missing_balances = [p for p, balance in self.balances.items() if balance is None]
        if missing_balances:
            raise ValueError("partial capture needs a balance anchor for every player: " +
                             ", ".join(missing_balances))
        if set(row.kills) != set(self.player_team):
            raise ValueError("kills must explicitly cover every player")
        loser = next(team for team in self.teams if team != row.winner)
        if set(row.survived) != set(self.teams[loser]):
            raise ValueError("survived must explicitly cover every losing player")

        start = len(self.transactions)
        sources = tuple(row.source_ids)

        # These rewards occur during play and can hit the cap before settlement.
        for player in self.player_team:
            counts = _count_range(row.kills[player])
            reward = CreditRange(counts.minimum * self.rules.kill_reward,
                                 counts.maximum * self.rules.kill_reward)
            self._credit(player, "kill_reward", reward, "credited_kills",
                         row.round_no, row.settlement_t_ms, sources)

        plant_known = True if row.spike_detonated is True else row.planted
        if plant_known is not False:
            reward = (CreditRange.exact(self.rules.plant_reward) if plant_known is True
                      else CreditRange(0, self.rules.plant_reward))
            for player in self.teams[row.attacking_team]:
                self._credit(player, "plant_reward", reward,
                             "spike_planted" if plant_known is True else "plant_unknown",
                             row.round_no, row.settlement_t_ms, sources)

        losing_streak = self.loss_streaks[loser] + 1
        loss_reward = self.rules.loss_reward(losing_streak)
        for team, players in self.teams.items():
            for player in players:
                if team == row.winner:
                    amount = CreditRange.exact(self.rules.win_reward)
                    kind, reason = "round_win_reward", "round_won"
                else:
                    side = "attack" if team == row.attacking_team else "defence"
                    penalty = survival_penalty(side, row.survived[player],
                                               plant_known, row.spike_detonated)
                    if penalty is True:
                        amount = CreditRange.exact(self.rules.survival_reward)
                        kind, reason = "survival_reward", "qualifying_survived_loss"
                    elif penalty is False:
                        amount = CreditRange.exact(loss_reward)
                        kind, reason = "round_loss_reward", f"loss_streak_{losing_streak}"
                    else:
                        amount = CreditRange(min(self.rules.survival_reward, loss_reward),
                                             max(self.rules.survival_reward, loss_reward))
                        kind, reason = "round_loss_reward", "survival_eligibility_unknown"
                self._credit(player, kind, amount, reason, row.round_no,
                             row.settlement_t_ms, sources)

        self.loss_streaks[row.winner] = 0
        self.loss_streaks[loser] = losing_streak
        self.last_settled_round = row.round_no
        return self.transactions[start:]

    def snapshot(self) -> dict:
        return {
            "economy_version": self.rules.version,
            "last_settled_round": self.last_settled_round,
            "loss_streaks": dict(self.loss_streaks),
            "players": {
                player: {
                    "team_id": self.player_team[player],
                    "credits_min": balance.minimum if balance else None,
                    "credits_max": balance.maximum if balance else None,
                    "credits": balance.value if balance else None,
                    "reason": None if balance else "uninitialized_partial_capture",
                }
                for player, balance in self.balances.items()
            },
        }

    def _require_player(self, player_id: str) -> None:
        if player_id not in self.player_team:
            raise ValueError(f"unknown player {player_id!r}")

    def _balance(self, player_id: str) -> CreditRange:
        balance = self.balances[player_id]
        if balance is None:
            raise ValueError(f"player {player_id!r} has no starting balance anchor")
        return balance

    def _credit(self, player: str, kind: str, amount: CreditRange, reason: str,
                round_no: int, t_ms: float | None,
                source_ids: tuple[str, ...]) -> EconomyTransaction:
        before = self._balance(player)
        after = before.add_capped(amount, self.rules.credit_cap)
        return self._append(player, kind, amount, before, after, reason,
                            round_no, t_ms, source_ids)


def run_document(document: Mapping) -> dict:
    """Run an explicit fact document through the ledger.

    This is the temporary human/reconciler adapter until Reticle observes stable
    ten-player balances. Operations stay explicit so omitted evidence cannot read
    as zero. The returned document is JSON-serializable.
    """
    tracker = EconomyTracker(document["teams"])
    reconciliations = []
    for operation in document.get("operations", []):
        kind = operation.get("kind")
        sources = tuple(operation.get("source_ids", ()))
        if kind == "reset":
            tracker.reset_period(operation["round_no"], operation["reason"],
                                 operation.get("credits"), operation.get("t_ms"), sources)
        elif kind == "spend":
            tracker.record_spending(operation["player_id"], operation["amount"],
                                    round_no=operation["round_no"],
                                    t_ms=operation.get("t_ms"),
                                    reason=operation.get("reason", "purchase_or_transfer"),
                                    source_ids=sources)
        elif kind == "balance_observation":
            result = tracker.observe_balance(operation["player_id"], operation["credits"],
                                             round_no=operation.get("round_no"),
                                             t_ms=operation.get("t_ms"),
                                             source_ids=sources)
            reconciliations.append(asdict(result))
        elif kind == "round":
            tracker.settle_round(RoundEconomyInput(
                round_no=operation["round_no"], winner=operation["winner"],
                attacking_team=operation["attacking_team"],
                planted=operation.get("planted"),
                spike_detonated=operation.get("spike_detonated"),
                kills=operation["kills"], survived=operation["survived"],
                settlement_t_ms=operation.get("settlement_t_ms"),
                source_ids=sources))
        else:
            raise ValueError(f"unknown economy operation kind {kind!r}")
    return {
        "economy_version": tracker.rules.version,
        "transactions": [transaction.as_dict() for transaction in tracker.transactions],
        "reconciliations": reconciliations,
        "snapshot": tracker.snapshot(),
    }
