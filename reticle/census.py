"""A named tally of what each reader threw away, and why.

Every guard in this pipeline is a `continue` or a `return None` that discards a
frame, a band or a candidate. Each one is there for a measured reason, and the
module docstrings argue for them at length -- but *none of them says how often
it fires*, so a guard that is correct on the case it was written for and
catastrophic on a session nobody re-read looks exactly like a guard that never
fires at all.

Three of the four real gains of 2026-09-05 were found by noticing something
discarded without a word: the both-class label check, `casts()` looping
`range(3)`, and `drawn()` refusing an all-spent tray. In each case the code was
doing what it said and the *rate* was the finding. This module exists so the
rate is a thing you can look at rather than a thing you have to suspect.

Deliberately NOT a log. A log of a hundred thousand drops is not readable and
nobody reads it; a count per named reason is four lines and it is comparable
across sessions, which is what turns "this guard fires" into "this guard fires
eleven times more often here than anywhere else". Where a case needs to be
*seen* rather than counted, `keep` retains the first few examples' locations so
a probe can go back to those frames -- the location, never the pixels.

Off by default and threaded through as an argument rather than a global,
because a reader that behaves differently when observed is not the reader.
Passing `None` is the shipped path and costs one `is not None` per guard.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Census:
    """Counts of discards by reason, for one reader over one scan."""

    name: str = ""
    #: How many examples of each reason to retain a locator for.
    keep: int = 8
    counts: Counter = field(default_factory=Counter)
    #: reason -> up to `keep` locators, whatever the caller finds useful
    examples: dict[str, list] = field(default_factory=dict)
    #: Units offered to the reader at all, so a rate has a denominator. A count
    #: without one is unreadable: 40 dropped bands is nothing across a session
    #: and everything inside one round.
    seen: Counter = field(default_factory=Counter)

    def saw(self, unit: str = "unit", n: int = 1) -> None:
        self.seen[unit] += n

    def drop(self, reason: str, where=None) -> None:
        self.counts[reason] += 1
        if where is not None:
            ex = self.examples.setdefault(reason, [])
            if len(ex) < self.keep:
                ex.append(where)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def table(self, unit: str = "unit") -> str:
        """One block per reason, ordered by how much it takes."""
        den = self.seen.get(unit, 0)
        head = f"{self.name or 'census'}: {self.total} dropped of {den} {unit}"
        if den:
            head += f" ({self.total / den * 100:.1f}%)"
        lines = [head]
        for reason, n in self.counts.most_common():
            pct = f"{n / den * 100:5.1f}%" if den else "     -"
            lines.append(f"  {pct}  {n:6d}  {reason}")
            for e in self.examples.get(reason, [])[:3]:
                lines.append(f"                  e.g. {e}")
        if not self.counts:
            lines.append("  (nothing dropped)")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "seen": dict(self.seen),
            "counts": dict(self.counts),
            "examples": {k: list(v) for k, v in self.examples.items()},
        }
