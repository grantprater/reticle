"""The ping owner's danger run: the pulse flash may drop frames (ping-0.2.0)."""
from __future__ import annotations

import unittest

from reticle import ping

HZ = 10.0
DANGER_HUE = 170
STANDARD_HUE = 82


def _run(hue: int, t0: float, t1: float, *, flash_every: float | None = None,
         flash_s: float = 0.3, x: int = 50, y: int = 50) -> tuple[ping.Grouper, list[float]]:
    """Sightings of one fixed mark at 10 Hz over [t0, t1]; with `flash_every`,
    the mark is unseen for `flash_s` at that period, as the danger pulse
    whitens the triangle. The observed timestamps run 1 s either side."""
    g = ping.Grouper(HZ)
    ts = [round(t0 - 1.0 + k / HZ, 3) for k in range(int((t1 - t0 + 2.0) * HZ) + 1)]
    for t in ts:
        if not t0 <= t <= t1:
            continue
        if flash_every is not None and ((t - t0) % flash_every) < flash_s:
            continue
        g.add(t, x, y, hue)
    return g, ts


class DangerPulseTests(unittest.TestCase):
    def test_a_flashing_danger_ping_is_one_confirmed_run(self):
        # The 9acf02f98283 shape: unseen 0.3 s every 0.68 s over a 9.6 s life.
        g, ts = _run(DANGER_HUE, 100.0, 109.6, flash_every=0.68)
        conf, unconf, rej = ping.resolve(g, ts, HZ)
        self.assertEqual([r[0] for r in conf], ["danger"])
        self.assertEqual(len(g.groups), 1)

    def test_the_flash_on_both_ends_is_credited(self):
        # The first flash hides 100.0-100.3 s, so red is seen for 8.6 s, as at
        # 676.6-685.1 s on 9acf02f98283: the hidden ends are credited.
        g, ts = _run(DANGER_HUE, 100.0, 108.9, flash_every=0.68)
        conf, _, _ = ping.resolve(g, ts, HZ)
        self.assertEqual(len(conf), 1)

    def test_a_short_danger_run_is_still_refused(self):
        g, ts = _run(DANGER_HUE, 100.0, 106.0, flash_every=0.68)
        conf, _, rej = ping.resolve(g, ts, HZ)
        self.assertEqual(conf, [])
        self.assertEqual(len(rej), 1)

    def test_a_long_danger_run_is_refused(self):
        # A red bar drawn for 27 s stays refused by its span.
        g, ts = _run(DANGER_HUE, 100.0, 127.0, flash_every=0.68)
        conf, _, rej = ping.resolve(g, ts, HZ)
        self.assertEqual(conf, [])
        self.assertEqual(len(rej), 1)

    def test_a_sparse_danger_run_is_refused_on_cover(self):
        # Seen under half its span: a flicker joined by the pulse gap.
        g, ts = _run(DANGER_HUE, 100.0, 110.0, flash_every=0.5, flash_s=0.4)
        conf, _, rej = ping.resolve(g, ts, HZ)
        self.assertEqual(conf, [])

    def test_other_kinds_keep_the_contiguous_run(self):
        # The same gaps split a standard ping into short runs, none confirmed.
        g, ts = _run(STANDARD_HUE, 100.0, 107.0, flash_every=0.68)
        conf, _, _ = ping.resolve(g, ts, HZ)
        self.assertEqual(conf, [])
        self.assertGreater(len(g.groups), 1)

    def test_an_unbroken_standard_ping_still_confirms(self):
        g, ts = _run(STANDARD_HUE, 100.0, 107.0)
        conf, _, _ = ping.resolve(g, ts, HZ)
        self.assertEqual([r[0] for r in conf], ["standard"])

    def test_the_pulse_gap_stays_under_the_period_and_far_below_the_life(self):
        self.assertLess(ping.DANGER_GAP_S, 0.68)
        self.assertLess(2 * ping.DANGER_FLASH_S, ping.LIFE_TOL_S)


if __name__ == "__main__":
    unittest.main()
