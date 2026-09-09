"""What BRIDGE may re-attach: near the map is not the same as part of it.

Synthetic, because the point is the CONTRACT. The measured separation over the
twelve baked geometries is in `minimap.floor_mask`'s docstring, and the case
that motivated it is real: Sunset's location-name banner is drawn 9 px above
the map body, so 25 px of bridge dilation swallowed the words `B Market` and
the round pipeline reported them as 57 entity hypotheses.
"""
import unittest

import numpy as np

from reticle.minimap import STABLE_PCT, floor_mask, slab_mask


#: Reference widget size, so `widget_scale` is 1.0 and BRIDGE is its measured
#: 25 px. A narrower synthetic silently shrinks the bridge and tests nothing.
W, H = 465, 485
BODY, ISLAND, GAP = (60, 440), (30, 51), 9


def _map(noisy=False):
    """A grey body, and a second grey block a bridgeable gap above it.

    `GAP` is Sunset's own 9 px. Both blocks pass the slab colour test
    identically, so brightness alone cannot tell them apart -- which is
    exactly the situation the banner creates.
    """
    med = np.zeros((H, W, 3), np.uint8)
    med[BODY[0]:BODY[1], 30:430] = 117            # the map
    med[ISLAND[0]:ISLAND[1], 190:280] = 117       # the banner, GAP px above
    sd = np.full((H, W), 1.0, np.float32)
    if noisy:
        sd[ISLAND[0]:ISLAND[1], 190:280] = 40.0   # text, redrawn per region
    assert BODY[0] - ISLAND[1] == GAP
    return med, sd


class BridgeAdmitsOnlyStableStructure(unittest.TestCase):
    def test_without_sd_the_island_is_bridged_as_before(self):
        med, _ = _map()
        self.assertTrue(slab_mask(med)[40, 235])

    def test_a_stable_island_is_still_bridged(self):
        med, sd = _map(noisy=False)
        self.assertTrue(slab_mask(med, sd=sd)[40, 235])

    def test_an_unstable_island_is_refused(self):
        med, sd = _map(noisy=True)
        self.assertFalse(slab_mask(med, sd=sd)[40, 235])

    def test_refusing_the_island_leaves_the_body_untouched(self):
        med, sd = _map(noisy=True)
        kept, dropped = slab_mask(med), slab_mask(med, sd=sd)
        body = np.zeros(med.shape[:2], bool)
        body[BODY[0]:BODY[1], 30:430] = True
        self.assertTrue((dropped & body == kept & body).all())

    def test_the_ceiling_comes_from_the_body_not_a_constant(self):
        # A body that is itself noisy admits an island of the same noise: the
        # reference is the map, so a dim capture does not lose its own rooms.
        med, sd = _map(noisy=True)
        sd[BODY[0]:BODY[1], 30:430] = 40.0
        self.assertTrue(slab_mask(med, sd=sd)[40, 235])

    def test_the_body_percentile_ignores_its_own_noisiest_pixels(self):
        # STABLE_PCT is a percentile so a handful of churning body pixels --
        # an icon's usual parking spot -- cannot raise the ceiling for
        # everything. One percent of the body at banner noise must not admit
        # the banner.
        med, sd = _map(noisy=True)
        rng = np.random.default_rng(0)
        body = np.zeros(med.shape[:2], bool)
        body[BODY[0]:BODY[1], 30:430] = True
        ys, xs = np.where(body)
        pick = rng.choice(len(ys), len(ys) // 100, replace=False)
        sd[ys[pick], xs[pick]] = 60.0
        self.assertLess(len(pick) / len(ys) * 100, 100 - STABLE_PCT)
        self.assertFalse(slab_mask(med, sd=sd)[40, 235])

    def test_floor_mask_dilation_does_not_resurrect_a_refused_island(self):
        med, sd = _map(noisy=True)
        self.assertFalse(floor_mask(med, sd=sd)[40, 235])


class StabilityIsOptional(unittest.TestCase):
    def test_none_is_no_channel_rather_than_stable(self):
        med, sd = _map(noisy=True)
        self.assertTrue(floor_mask(med, sd=None)[40, 235])
        self.assertFalse(floor_mask(med, sd=sd)[40, 235])


if __name__ == "__main__":
    unittest.main()
