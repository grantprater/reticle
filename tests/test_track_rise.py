"""Entries rise alike: an entry never rises further than one above it
[domain:killfeed/stack-order] (`checks.track_entries`, `outrises`).

223d636bf8d2 1203.5-1210.5 s at 2 Hz: an entry under the Shooting Error
overlay reads in slot 4 with no divider and no side; a Not Dead Yet banner
the walk never saw in slot 3 first reads at 1208.0 s in slot 2, while the
entry above rose one slot.
"""
import unittest

from reticle.checks import track_entries
from reticle.killfeed import WX_BITS

ALLY, ENEMY = 1, 2
# t (s) -> {slot: (divider or 0 for unread, side or 0 for unread)}
READS = {
    1203.5: {0: (187, ENEMY), 1: (243, ALLY)},
    1204.0: {0: (187, ENEMY), 1: (243, ALLY), 2: (217, ENEMY)},
    1206.0: {0: (187, ENEMY), 1: (243, ALLY), 2: (217, ENEMY), 4: (0, 0)},
    1206.5: {0: (187, ENEMY), 1: (243, ALLY), 2: (217, ENEMY), 4: (0, 0)},
    1207.0: {0: (187, ENEMY), 1: (243, ALLY), 2: (217, ENEMY), 4: (0, 0)},
    1207.5: {1: (243, ALLY), 2: (217, ENEMY)},
    1208.0: {0: (243, ALLY), 1: (217, ENEMY), 2: (265, ENEMY)},
    1208.5: {1: (217, ENEMY), 2: (265, ENEMY)},
    1209.0: {1: (265, ENEMY), 2: (239, ALLY)},
    1209.5: {1: (239, ALLY), 2: (253, ALLY)},
    1210.0: {0: (239, ALLY), 1: (253, ALLY)},
    1210.5: {0: (239, ALLY), 1: (253, ALLY)},
}


def columns():
    t = [1203500.0 + 500.0 * i for i in range(15)]
    mask, wx, sides = [], [], []
    for x in t:
        # 1204.5-1205.5 hold what 1204.0 held
        s = READS.get(x / 1000.0, READS[1204.0])
        mask.append(sum(1 << k for k in s))
        wx.append(sum(w << (WX_BITS * k) for k, (w, _) in s.items()) or None)
        sides.append((sum(1 << k for k, (_, d) in s.items() if d == ALLY),
                      sum(1 << k for k, (_, d) in s.items() if d == ENEMY), 0))
    return t, mask, wx, sides


class RiseTests(unittest.TestCase):
    def test_an_unread_entry_never_outrises_the_entry_above(self):
        t, mask, wx, sides = columns()
        got = [a for a in track_entries(t, mask, wx, sides=sides) if a["counted"]]
        hidden = next(a for a in got if a["t_first"] == 1206000.0)
        self.assertEqual(hidden["slot_first"], 4)
        reads = [(t_ / 1000.0, s_) for t_, s_, _ in hidden["assigned"]]
        self.assertNotIn((1208.0, 2), reads)
        self.assertIn((1209.0, 2), reads)
        self.assertEqual(hidden["side"], "ally")
        banner = next(a for a in got if a["t_first"] == 1208000.0)
        self.assertEqual(banner["sig"], 265)


if __name__ == "__main__":
    unittest.main()
