"""The two agent portraits every killfeed entry draws, and the plate under them."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from reticle import appearance, killfeed
from reticle.killfeed import (KILLFEED_PORTRAIT_VERSION, UNIT_SCALE,
                              PORTRAIT_ASPECT, EntryView,
                              KillfeedPortraitReader, _entry_columns,
                              _portrait_edge, portrait_observations)
from reticle.profiles import Roi


def _bgr(h, s, v):
    """One BGR triple from an HSV point, so a fixture cannot drift from the
    detector's own colour windows the way this one first did: hand-picked
    greens fell outside `GREEN_H`, no plate was found at all, and the test
    failed for the fixture's reason rather than the code's."""
    return tuple(int(c) for c in cv2.cvtColor(
        np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0, 0])


GREEN = _bgr(sum(killfeed.GREEN_H) // 2, sum(killfeed.GREEN_S) // 2, 200)
RED = _bgr(4, 200, 200)
WHITE = (245, 245, 245)
#: Neither plate colour, and saturated enough to survive the value floor.
ART_A = _bgr(150, 200, 210)
ART_B = _bgr(30, 210, 200)


def band_frame(h=40, w=200, bh=20):
    """One synthetic entry: portrait, plate with text, plate, portrait.

    Laid out the way the game draws it -- `[portrait][name][icon][name]
    [portrait]` -- so the walk has to step over the text to find the gap.
    """
    frame = np.zeros((h, w, 3), np.uint8)
    y0, y1 = 4, 4 + bh
    pw = int(PORTRAIT_ASPECT * bh)
    # killer portrait: saturated art, deliberately neither plate colour
    frame[y0:y1, 10:10 + pw] = ART_A
    frame[y0:y1, 10 + pw:110] = GREEN          # killer plate
    frame[y0:y1, 60:70] = WHITE                # killer name, drawn ON the plate
    frame[y0:y1, 110:150] = RED                # victim plate
    frame[y0:y1, 120:130] = WHITE              # victim name
    frame[y0:y1, 150:150 + pw] = ART_B           # victim portrait
    return frame, y0, y1, bh, pw


class WalkTests(unittest.TestCase):
    """The walk stops at the portrait; every rule that did not ran off the end."""

    def test_the_walk_steps_over_text_and_stops_at_the_portrait(self):
        frame, y0, y1, bh, pw = band_frame()
        green = np.all(frame == GREEN, axis=2)
        red = np.all(frame == RED, axis=2)
        white = np.all(frame == WHITE, axis=2).astype(np.uint8) * 255
        on = _entry_columns(green[y0:y1], red[y0:y1], white[y0:y1], bh)
        # From inside the killer name, walking left: over the text, over the
        # plate, and stopping where the portrait begins.
        self.assertEqual(_portrait_edge(on, 64, -1, frame.shape[1]), 10 + pw - 1)
        # And right from the victim name to the victim portrait.
        self.assertEqual(_portrait_edge(on, 124, +1, frame.shape[1]), 150)

    def test_white_hair_past_the_name_is_not_text(self):
        """Jett's white hair read as text and the walk crossed her portrait
        (a06f04a0059f 284.5 s); ink that begins past the name end is art."""
        frame, y0, y1, bh, pw = band_frame()
        frame[y0:y0 + 8, 150:150 + pw] = WHITE     # hair across the portrait's top
        green = np.all(frame == GREEN, axis=2)
        red = np.all(frame == RED, axis=2)
        white = np.all(frame == WHITE, axis=2).astype(np.uint8) * 255
        raw = _entry_columns(green[y0:y1], red[y0:y1], white[y0:y1], bh)
        self.assertEqual(_portrait_edge(raw, 130, +1, frame.shape[1]), 150 + pw)   # past her
        own = killfeed.own_ink(white[y0:y1], 129)
        on = _entry_columns(green[y0:y1], red[y0:y1], own, bh)
        self.assertEqual(_portrait_edge(on, 130, +1, frame.shape[1]), 150)

    def test_a_mark_the_name_run_sits_in_stays_furniture(self):
        """A second-life badge's ring encloses the run; its arc past the run
        is the entry's own ink, not the portrait (a06f04a0059f 1576.0 s)."""
        frame, y0, y1, bh, pw = band_frame()
        frame[y0:y1, 118:120] = WHITE              # ring's left arc
        frame[y0:y1, 131:137] = WHITE              # right arc, past the run
        frame[y0:y0 + 2, 118:137] = WHITE          # joined over the top
        green = np.all(frame == GREEN, axis=2)
        red = np.all(frame == RED, axis=2)
        white = np.all(frame == WHITE, axis=2).astype(np.uint8) * 255
        own = killfeed.own_ink(white[y0:y1], 129)
        self.assertTrue((own[:, 131:137] > 0).all())
        on = _entry_columns(green[y0:y1], red[y0:y1], own, bh)
        self.assertEqual(_portrait_edge(on, 130, +1, frame.shape[1]), 150)

    def test_the_victim_name_ends_past_a_word_space_and_merged_letters(self):
        """`name_run` stops at a word space ("Daddy Darkrai") and touching
        letters merge wider than a glyph ("me"); the name ends after both,
        and a lock of hair on the baseline past the plate gap is not text."""
        white = np.zeros((34, 200), np.uint8)
        for x in (10, 17, 24):                      # first word
            white[13:23, x:x + 5] = 255
        for x in (36, 43):                          # second word, 7 px on
            white[13:23, x:x + 5] = 255
        white[15:23, 50:70] = 255                   # "me", merged, 20 px wide
        white[15:23, 85:95] = 255                   # hair on the baseline
        self.assertEqual(killfeed.victim_name_end(white, (10, 28)), 69)

    def test_a_band_with_no_gap_refuses(self):
        frame, y0, y1, bh, _pw = band_frame()
        frame[y0:y1, :] = GREEN                # plate edge to edge, no portrait
        green = np.all(frame == GREEN, axis=2)
        red = np.zeros_like(green)
        white = np.zeros(green.shape, np.uint8)
        on = _entry_columns(green[y0:y1], red[y0:y1], white[y0:y1], bh)
        self.assertIsNone(_portrait_edge(on, 64, -1, frame.shape[1]))


class ObservationTests(unittest.TestCase):
    def observe(self, frame, y0, y1, ally=True):
        h, w = frame.shape[:2]
        view = EntryView(0, y0, y1, 80, 100, killer_run=(60, 70),
                         victim_run=(120, 130), victim_ally=ally)
        return portrait_observations(frame, Roi("kf", 0.0, 0.0, 1.0, 1.0), w, h,
                                     views=[view], scale=UNIT_SCALE)

    def test_both_portraits_are_found_and_neither_is_named(self):
        frame, y0, y1, _bh, _pw = band_frame()
        got = self.observe(frame, y0, y1)
        self.assertEqual([o["role"] for o in got], ["killer", "victim"])
        for o in got:
            self.assertNotIn("agent", o)
            self.assertGreater(len(o["composition"]), 0)
            self.assertEqual(o["reason"], "")

    def test_the_killer_and_the_victim_are_on_opposite_sides(self):
        frame, y0, y1, _bh, _pw = band_frame()
        killer, victim = self.observe(frame, y0, y1, ally=True)
        self.assertTrue(victim["ally"])
        self.assertFalse(killer["ally"])
        killer, victim = self.observe(frame, y0, y1, ally=False)
        self.assertFalse(victim["ally"])
        self.assertTrue(killer["ally"])

    def test_an_undecidable_plate_leaves_the_side_unknown(self):
        frame, y0, y1, _bh, _pw = band_frame()
        for o in self.observe(frame, y0, y1, ally=None):
            self.assertIsNone(o["ally"])

    def test_the_plate_is_masked_out_of_the_descriptor(self):
        """Unmasked, every ally portrait would look like the ally plate."""
        frame, y0, y1, _bh, pw = band_frame()
        killer, _victim = self.observe(frame, y0, y1)
        art = frame[y0:y1, 10:10 + pw]
        self.assertGreater(appearance.agrees(killer["composition"],
                                             appearance.hsv_composition(art)), 0.95)
        plate = np.full_like(art, GREEN, dtype=np.uint8)
        self.assertLess(appearance.agrees(killer["composition"],
                                          appearance.hsv_composition(plate)), 0.05)

    def test_two_different_portraits_do_not_agree(self):
        frame, y0, y1, _bh, _pw = band_frame()
        killer, victim = self.observe(frame, y0, y1)
        self.assertLess(appearance.agrees(killer["composition"],
                                          victim["composition"]), 0.2)

    def test_a_portrait_cut_by_the_ROI_edge_reports_how_much(self):
        """The victim's portrait sits at the entry's right end and gets cut."""
        half = int(PORTRAIT_ASPECT * 20) // 2
        frame, y0, y1, _bh, pw = band_frame(w=150 + half)
        got = self.observe(frame, y0, y1)
        victim = next(o for o in got if o["role"] == "victim")
        self.assertGreater(victim["clipped"], 0.4)
        self.assertEqual(next(o for o in got if o["role"] == "killer")
                         ["clipped"], 0.0)

    def test_an_entry_with_no_name_runs_yields_nothing(self):
        frame, y0, y1, _bh, _pw = band_frame()
        h, w = frame.shape[:2]
        view = EntryView(0, y0, y1, verdict="unparsed")
        self.assertEqual(portrait_observations(frame, Roi("kf", 0.0, 0.0, 1.0, 1.0),
                                               w, h, views=[view], scale=UNIT_SCALE), [])


class CompositionTests(unittest.TestCase):
    def test_a_crop_with_too_few_pixels_describes_nothing(self):
        self.assertEqual(appearance.hsv_composition(
            np.zeros((3, 3, 3), np.uint8)).size, 0)
        self.assertEqual(appearance.agrees(np.zeros(0), np.zeros(0)), 0.0)

    def test_a_composition_sums_to_one(self):
        art = np.random.RandomState(0).randint(0, 255, (20, 40, 3), dtype=np.uint8)
        self.assertAlmostEqual(float(appearance.hsv_composition(art).sum()), 1.0, 5)

    def test_the_mask_is_what_is_described(self):
        art = np.zeros((20, 40, 3), np.uint8)
        art[:, :20] = (0, 0, 255)
        art[:, 20:] = (0, 255, 0)
        mask = np.zeros((20, 40), bool)
        mask[:, :20] = True
        self.assertGreater(appearance.agrees(
            appearance.hsv_composition(art, mask),
            appearance.hsv_composition(art[:, :20])), 0.99)


class EntryAnchorCarryTests(unittest.TestCase):
    """An entry's confident killer placement is carried to its later views."""

    def test_the_anchor_found_on_one_view_is_the_next_views_first_prior(self):
        frame, y0, y1, _bh, _pw = band_frame()
        h, w = frame.shape[:2]
        view = EntryView(0, y0, y1, 80, 100, killer_run=(60, 70),
                         victim_run=(120, 130), victim_ally=True)
        seen = []

        def fake_art_view(crop, role, x0, y0_, ally, s, art_dir, candidates=None,
                          plate_x0=None, entry_x0=None):
            seen.append((role, plate_x0, entry_x0))
            if role != "killer":
                return {"art_zncc": {"A": 0.9}, "art_search": "prior",
                        "art_anchor": "right_edge", "art_x0": 150}
            return {"art_zncc": {"A": 0.9}, "art_search": "prior", "art_x0": 10,
                    "art_anchor": "entry_anchor" if entry_x0 is not None else "plate_left",
                    "art_candidates_widened": None}

        anchors = killfeed.EntryAnchors()
        with patch("reticle.killfeed.art_view", fake_art_view), \
             patch("reticle.killfeed.plate_left_edge", return_value=(10.3, 9.0)):
            rows = []
            for t in (0.0, 500.0):
                anchors.frame(t)
                rows.append(portrait_observations(
                    frame, Roi("kf", 0.0, 0.0, 1.0, 1.0), w, h, views=[view],
                    scale=UNIT_SCALE, art_dir="unused", anchors=anchors))
        killers = [x for x in seen if x[0] == "killer"]
        self.assertEqual(killers[0][2], None)
        self.assertAlmostEqual(killers[1][2], 10.3)
        first, second = rows[0][0], rows[1][0]
        self.assertEqual(first["entry"], second["entry"])
        self.assertNotIn("entry_anchor", first)
        self.assertEqual(second["rests_on"][0]["prior"], "entry_anchor")
        self.assertEqual(second["rests_on"][0]["source"], "plate_left")
        # the name-start box is the cross-check; its disagreement is stored
        self.assertIn("surprise", second["anchor_check"])


class ReaderTests(unittest.TestCase):
    def test_reader_persists_raw_observations_with_stable_keys(self):
        profile = SimpleNamespace(name="valorant-16x9")
        sample = SimpleNamespace(frame=np.zeros((20, 20, 3), np.uint8),
                                 frame_idx=12, t_ms=1500.0)
        observation = {"slot": 1, "role": "victim", "ally": False,
                       "composition": [0.5, 0.5], "reason": ""}
        with patch("reticle.killfeed.killfeed_roi", return_value=Roi("kf", 0, 0, 1, 1)), \
             patch("reticle.killfeed.analyse_killfeed", return_value=[]), \
             patch("reticle.killfeed.portrait_observations",
                   return_value=[observation]):
            reader = KillfeedPortraitReader(profile, (1920, 1080), hz=2.0)
            reader.feed(sample)
        events = reader.events("session-1")
        self.assertEqual(events[0]["kind"], "coverage")
        self.assertEqual(events[0]["killfeed_portrait_version"],
                         KILLFEED_PORTRAIT_VERSION)
        self.assertEqual(events[1]["observation_key"],
                         "session-1:12:1:victim")
        self.assertNotIn("agent", events[1])

    def test_coverage_counts_the_refusals_and_names_them(self):
        profile = SimpleNamespace(name="valorant-16x9")
        sample = SimpleNamespace(frame=np.zeros((20, 20, 3), np.uint8),
                                 frame_idx=3, t_ms=500.0)
        described = {"slot": 0, "role": "killer", "ally": True,
                     "composition": [0.123456789, 0.876543211], "reason": ""}
        refused = {"slot": 1, "role": "victim",
                   "reason": "no gap past the name"}
        with patch("reticle.killfeed.killfeed_roi", return_value=Roi("kf", 0, 0, 1, 1)), \
             patch("reticle.killfeed.analyse_killfeed", return_value=[]), \
             patch("reticle.killfeed.portrait_observations",
                   return_value=[described, refused]):
            reader = KillfeedPortraitReader(profile, (1920, 1080), hz=2.0)
            reader.feed(sample)
        coverage = reader.events("session-1")[0]
        self.assertEqual(coverage["observations"], 2)
        self.assertEqual(coverage["described"], 1)
        self.assertEqual(coverage["refused"], 1)
        self.assertEqual(coverage["refused_reasons"],
                         {"no gap past the name": 1})

    def test_the_stored_descriptor_is_rounded(self):
        profile = SimpleNamespace(name="valorant-16x9")
        sample = SimpleNamespace(frame=np.zeros((20, 20, 3), np.uint8),
                                 frame_idx=3, t_ms=500.0)
        observation = {"slot": 0, "role": "killer", "ally": True,
                       "composition": [0.123456789, 0.876543211], "reason": ""}
        with patch("reticle.killfeed.killfeed_roi", return_value=Roi("kf", 0, 0, 1, 1)), \
             patch("reticle.killfeed.analyse_killfeed", return_value=[]), \
             patch("reticle.killfeed.portrait_observations",
                   return_value=[observation]):
            reader = KillfeedPortraitReader(profile, (1920, 1080), hz=2.0)
            reader.feed(sample)
        stored = reader.events("session-1")[1]["composition"]
        self.assertEqual(stored, [0.12346, 0.87654])
        # The reader's own rows keep full precision; only the file rounds.
        self.assertEqual(reader.rows[0]["composition"][0], 0.123456789)


if __name__ == "__main__":
    unittest.main()
