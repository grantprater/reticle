"""The ability tray: bar counts, fills, drops and their suspicion, and the gate
that decides which drops are the player's casts."""
from __future__ import annotations

import unittest

import numpy as np

from reticle import tray
from reticle.ability_timeline import player_tray_casts

TEAL = (180, 170, 30)


def _frame(fill=(1.0, 1.0, 1.0, 1.0)) -> np.ndarray:
    f = np.zeros((1080, 1920, 3), np.uint8)
    for k, x in enumerate(fill):
        cx = tray.SLOT_X0 + tray.SLOT_DX * k
        w = int(round(2 * tray.BAR_HALF * x))
        f[tray.BAR_Y0:tray.BAR_Y1, cx - tray.BAR_HALF:cx - tray.BAR_HALF + w] = TEAL
    return f


class TrayReadTest(unittest.TestCase):
    def test_counts_follow_the_bar(self):
        full, ok = tray.slot_counts(_frame())
        half, _ = tray.slot_counts(_frame((0.5, 1.0, 1.0, 1.0)))
        self.assertTrue(ok)
        self.assertAlmostEqual(half[0] / full[0], 0.5, delta=0.03)

    def test_a_teal_screen_is_refused(self):
        f = np.zeros((1080, 1920, 3), np.uint8)
        f[1000:1080] = TEAL
        self.assertFalse(tray.slot_counts(f)[1])

    def test_a_drop_and_a_spectator_switch(self):
        rows = [(1.0, 1.0, 1.0, 1.0)] * 3 + [(0.0, 1.0, 1.0, 1.0)] * 3 \
            + [(0.0, 0.0, 0.0, 1.0)] * 3
        counts = np.array([tray.slot_counts(_frame(r))[0] for r in rows], float)
        ts = [1000.0 * (i + 1) for i in range(len(rows))]
        got = tray.drops(ts, counts, np.ones(len(rows), bool))
        self.assertEqual([(d["t_ms"], d["slot"]) for d in got],
                         [(4000.0, "C"), (7000.0, "Q"), (7000.0, "E")])
        self.assertFalse(got[0]["suspect"])
        self.assertTrue(got[1]["cooccur"] and got[2]["cooccur"])

    def _flooded(self, fill):
        # Sova's bow glowing over the tray: the guard rows go teal.
        f = _frame(fill)
        f[tray.GUARD_Y[0][0]:tray.GUARD_Y[0][1], tray.SLOT_X0 - 60:tray.SLOT_X0 + 400] = TEAL
        return f

    def test_a_drop_under_a_flash_is_compared_across_it(self):
        frames = [_frame()] * 3 + [self._flooded((1.0, 1.0, 0.0, 1.0))] \
            + [_frame((1.0, 1.0, 0.0, 1.0))] * 3
        counts, clean = zip(*(tray.slot_counts(f) for f in frames))
        self.assertEqual(clean, (True,) * 3 + (False,) + (True,) * 3)
        ts = [500.0 * (i + 1) for i in range(len(frames))]
        got = tray.drops(ts, np.array(counts, float), np.array(clean, bool))
        self.assertEqual([(d["t_ms"], d["slot"], d["across_gap"]) for d in got],
                         [(2500.0, "E", True)])

    def test_a_long_refusal_is_not_bridged(self):
        frames = [_frame()] * 3 + [self._flooded((1.0, 1.0, 0.0, 1.0))] * 7 \
            + [_frame((1.0, 1.0, 0.0, 1.0))] * 3
        counts, clean = zip(*(tray.slot_counts(f) for f in frames))
        ts = [500.0 * (i + 1) for i in range(len(frames))]
        self.assertEqual(tray.drops(ts, np.array(counts, float), np.array(clean, bool)), [])

    def test_an_undrawn_tray_is_no_reading(self):
        self.assertFalse(tray.drawn(np.zeros(4)))
        self.assertTrue(tray.drawn(np.array([0.0, 0.0, 0.5, 0.0])))

    def test_a_quiet_drop_is_marked_but_marks_no_other(self):
        ev = [(20.0, "Q", 1.25, 0.97, False), (20.0, "E", 1.0, 0.0, False),
              (30.0, "C", 1.0, 0.0, False)]
        self.assertEqual([s for *_x, s in tray.flag_suspect(ev)], [True, True, False])
        got = tray.flag_suspect(ev, quiet=[True, False, False])
        self.assertEqual([s for *_x, s in got], [True, False, False])


class PlayerCastGateTest(unittest.TestCase):
    def _drop(self, t, slot, forced=False):
        return {"t_ms": t, "slot": slot, "from": 1.0, "to": 0.0, "forced": forced,
                "suspect": forced, "cooccur": False}

    @staticmethod
    def _rounds(*bounds):
        return [{"t_start_ms": a, "t_end_ms": z, "t_close_ms": c} for a, z, c in bounds]

    def test_the_gate(self):
        rounds = self._rounds((0.0, 90000.0, 100000.0))
        phase = lambda t: "buy_phase" if t < 5000 else "round_live"
        drops = [self._drop(3000, "C"), self._drop(20000, "E"), self._drop(49500, "Q"),
                 self._drop(60000, "X"), self._drop(150000, "C")]
        got = {r["t_ms"]: r for r in player_tray_casts(drops, phase, rounds, [50000.0])}
        self.assertEqual(got[3000]["reason"], "phase:buy_phase")
        self.assertTrue(got[20000]["player_cast"])
        self.assertEqual(got[49500]["reason"], "after_player_death")
        self.assertEqual(got[60000]["reason"], "after_player_death")
        self.assertEqual(got[150000]["reason"], "no_round")

    def test_a_death_where_rounds_touch_belongs_to_the_round_it_ends(self):
        rounds = self._rounds((0.0, 60000.0, 60000.0), (60000.0, 150000.0, 150000.0))
        got = player_tray_casts([self._drop(80000, "E")], lambda t: "round_live",
                                rounds, [60000.0, 120000.0])
        self.assertTrue(got[0]["player_cast"])
        self.assertEqual(got[0]["first_player_death_ms"], 120000.0)

    def test_suspicion_is_recomputed_among_the_casts(self):
        # A cast beside a post-death spectator switch is no longer tainted by it.
        rounds = self._rounds((0.0, 100000.0, 100000.0))
        phase = lambda t: "round_live"
        drops = [self._drop(20000, "E"), self._drop(20500, "Q"), self._drop(40000, "C"),
                 self._drop(40800, "Q")]
        got = {r["t_ms"]: r for r in player_tray_casts(drops, phase, rounds, [41000.0])}
        self.assertEqual(got[20000]["reason"], "cooccur_among_casts")
        self.assertTrue(got[40000]["reason"] == "after_player_death")
        drops = [self._drop(38000, "C"), self._drop(40500, "Q")]
        got = {r["t_ms"]: r for r in player_tray_casts(drops, phase, rounds, [41000.0])}
        self.assertTrue(got[38000]["player_cast"])

    def test_a_capture_without_rounds_stores_every_drop_as_no_rounds(self):
        # A demo has no rounds table: nothing is placed in a guessed round,
        # and nothing is discarded.
        drops = [self._drop(3000, "C"), self._drop(20000, "E"), self._drop(20500, "Q")]
        got = player_tray_casts(drops, None, None, [])
        self.assertEqual([r["reason"] for r in got], ["no_rounds"] * 3)
        self.assertFalse(any(r["player_cast"] for r in got))
        self.assertEqual([r["round_ms"] for r in got], [None] * 3)
        # An empty table is a table: its drops fall outside every round.
        got = player_tray_casts(drops, lambda t: "round_live", [], [])
        self.assertEqual({r["reason"] for r in got}, {"no_round"})

    def test_a_fade_beside_a_bridged_bolt_stays_refused(self):
        # 75a55a296d3b 274.1 s: Sova's bow glow lifts the empty C or the half Q
        # bar on one clean sample and fades; the bolt's own drop is bridged
        # across the flash 0.5 s earlier. The fade is no cast, and the bridged
        # drop keeps refusing it as co-occurring.
        rounds = self._rounds((200000.0, 300000.0, 300000.0))
        drops = [dict(self._drop(273567, "E"), across_gap=True),
                 dict(self._drop(274067, "Q"), across_gap=False)]
        got = {r["slot"]: r for r in player_tray_casts(drops, lambda t: "round_live",
                                                       rounds, [])}
        self.assertEqual(got["Q"]["reason"], "cooccur_among_casts")


class TraySpansTest(unittest.TestCase):
    class _Cache:
        def __init__(self, spans, t_ms):
            self.record, self.t_ms = {"spans": spans}, np.asarray(t_ms, float)

    def test_a_whole_capture_cache_is_one_span(self):
        from reticle.cli import _tray_spans
        self.assertEqual(_tray_spans(self._Cache(None, [500.0, 0.0, 65000.0])),
                         [[0.0, 65000.0]])
        self.assertEqual(_tray_spans(self._Cache([[1.0, 2.0], [5.0, 9.0]], [1.0])),
                         [[1.0, 2.0], [5.0, 9.0]])
        self.assertEqual(_tray_spans(self._Cache(None, [])), [])


class StripCropTest(unittest.TestCase):
    """`slot_counts` crops the strip before converting; the whole-frame read
    it replaced must give the same counts and verdict."""

    @staticmethod
    def _whole_frame(frame):
        import cv2
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
        teal = ((h > tray.TEAL_H[0]) & (h < tray.TEAL_H[1])
                & (s > tray.TEAL_S_MIN) & (v > tray.TEAL_V_MIN))
        out, bleed = [], 0.0
        for k in range(4):
            cx = tray.SLOT_X0 + tray.SLOT_DX * k
            sl = slice(cx - tray.BAR_HALF, cx + tray.BAR_HALF)
            out.append(int(teal[tray.BAR_Y0:tray.BAR_Y1, sl].sum()))
            bar = teal[tray.BAR_Y0:tray.BAR_Y1, sl].mean()
            g = max(teal[a:b, sl].mean() for a, b in tray.GUARD_Y)
            if bar > 0.05:
                bleed = max(bleed, g / bar)
        return out, bleed <= tray.GUARD_MAX_RATIO

    def test_crop_reads_as_the_whole_frame(self):
        rng = np.random.default_rng(20261002)
        frames = [_frame(), _frame((0.5, 0.0, 1.0, 0.3))]
        for _ in range(6):
            f = _frame(tuple(rng.random(4)))
            noise = rng.integers(0, 256, f.shape, dtype=np.uint8)
            frames.append(np.where(rng.random(f.shape[:2])[..., None] < 0.3, noise, f))
        flood = _frame()
        flood[tray.GUARD_Y[0][0]:tray.GUARD_Y[1][1], :] = TEAL
        frames.append(flood)
        for f in frames:
            self.assertEqual(tray.slot_counts(f), self._whole_frame(f))

    def test_strip_covers_bars_and_guards(self):
        self.assertEqual(tray.STRIP_Y, (1008, 1076))
        self.assertEqual(tray.STRIP_X, (751, 1166))


#: Pixel colours read off stored crops (BGR): the teal bar, a returned charge's
#: gold, the empty bar's grey and a cyan screen streak over a bar.
SEG_BGR = {"teal": (178, 255, 106), "gold": (181, 225, 245), "empty": (146, 151, 151),
           "streak": (170, 165, 100), "flash": (60, 60, 230)}


def _halves(cols) -> np.ndarray:
    """A frame whose eight bar halves are painted `cols` (slot-major, left first)."""
    f = np.zeros((1080, 1920, 3), np.uint8)
    for k in range(4):
        cx = tray.SLOT_X0 + tray.SLOT_DX * k
        for side, (a, b) in enumerate(((cx - 32, cx), (cx + 1, cx + 33))):
            f[1038:1052, a:b] = SEG_BGR[cols[2 * k + side]]
    return f


class SegmentTest(unittest.TestCase):
    def test_each_half_takes_its_class(self):
        cols = ["teal", "gold", "empty", "empty", "gold", "gold", "teal", "teal"]
        got = tray.segment_classes(tray.segment_scores(_halves(cols)))
        self.assertEqual(got, [cols[0:2], cols[2:4], cols[4:6], cols[6:8]])

    def test_a_streak_is_unreadable(self):
        cols = ["streak", "streak", "teal", "teal", "empty", "empty", "teal", "teal"]
        got = tray.segment_classes(tray.segment_scores(_halves(cols)))
        self.assertEqual(got[0], ["unreadable", "unreadable"])

    def test_gold_under_bright_scenery_is_not_gold(self):
        """The empty bar is translucent: a bright flash behind it reads gold."""
        cols = ["teal", "teal", "teal", "teal", "gold", "gold", "teal", "teal"]
        f = _halves(cols)
        f[tray.SEG_GUARD_Y[0]:tray.SEG_GUARD_Y[1]] = (235, 250, 255)
        got = tray.segment_classes(tray.segment_scores(f))
        self.assertEqual(got[2], ["unreadable", "unreadable"])
        self.assertEqual(got[1], ["teal", "teal"])

    def test_runs_keep_the_classes_and_break_at_separators(self):
        a = tray.segment_scores(_halves(["teal"] * 8))
        b = tray.segment_scores(_halves(["teal"] * 4 + ["gold", "gold"] + ["teal"] * 2))
        scores = np.stack([a, a, b, np.zeros_like(a), b])
        rows = tray.segment_runs([0, 500, 1000, 1010, 2000], scores, [1, 1, 1, 0, 1])
        e = [(r["t_first_ms"], r["t_last_ms"], r["halves"]) for r in rows if r["slot"] == "E"]
        self.assertEqual(e, [(0.0, 500.0, ["teal", "teal"]), (1000.0, 1000.0, ["gold", "gold"]),
                             (2000.0, 2000.0, ["gold", "gold"])])
        self.assertEqual(sum(r["samples"] for r in rows), 4 * 4)

    def test_classes_over_many_samples_match_one_at_a_time(self):
        a = tray.segment_scores(_halves(["teal", "gold", "empty", "empty"] * 2))
        b = tray.segment_scores(_halves(["streak"] * 2 + ["teal"] * 6))
        many = np.stack([a, b, np.zeros_like(a)])
        self.assertEqual(tray.segment_classes(many), [tray.segment_classes(x) for x in many])


def _drop_frame(cols, teal_x=1.0) -> np.ndarray:
    """A frame of bar halves `cols` with the ult bar lit to `teal_x`, so the
    teal fill sees the tray where `teal_x` is high."""
    f = _halves(cols)
    cx = tray.SLOT_X0 + tray.SLOT_DX * 3
    if teal_x:
        f[tray.BAR_Y0:tray.BAR_Y1, cx - tray.BAR_HALF:cx + tray.BAR_HALF] = SEG_BGR["teal"]
    return f


def _read(frames):
    counts, clean = zip(*(tray.slot_counts(f) for f in frames))
    scores = np.stack([tray.segment_scores(f) for f in frames])
    return np.array(counts, float), np.array(clean, bool), scores


class HalfDropTest(unittest.TestCase):
    EMPTY3 = ["empty"] * 6

    SEEN = {"witnessed": True, "by": ["icon"]}

    def test_spending_a_gold_charge_is_a_drop_once_witnessed(self):
        # E holds a returned (gold) charge and spends it: the teal fill never
        # moves, the halves do, and the drop waits on a witness.
        frames = [_drop_frame(["empty"] * 4 + ["gold", "gold"] + ["teal", "teal"])] * 3 \
            + [_drop_frame(self.EMPTY3 + ["teal", "teal"])] * 3
        counts, clean, scores = _read(frames)
        ts = [500.0 * (i + 1) for i in range(len(frames))]
        icons = np.ones(len(frames), bool)
        self.assertEqual(tray.drops(ts, counts, clean), [])
        cands = tray.gold_candidates(ts, counts, clean, scores, icons)
        self.assertEqual([(c["t_ms"], c["slot"], c["t_before_ms"], c["t_gold_ms"]) for c in cands],
                         [(2000.0, "E", 1500.0, 1500.0)])
        self.assertEqual(tray.drops(ts, counts, clean, scores, icons), [])
        self.assertEqual(tray.drops(ts, counts, clean, scores, icons,
                                    {(2000.0, "E"): {"witnessed": False}}), [])
        got = tray.drops(ts, counts, clean, scores, icons, {(2000.0, "E"): self.SEEN})
        self.assertEqual([(d["t_ms"], d["slot"], d["by"], d["spent_halves"]) for d in got],
                         [(2000.0, "E", ["halves"], ["gold", "gold"])])
        self.assertEqual(got[0]["halves_from"], ["gold", "gold"])
        self.assertEqual(got[0]["witness"], self.SEEN)
        self.assertFalse(got[0]["forced"])

    def test_an_unwitnessed_gold_drop_marks_no_other_drop(self):
        # C's teal fill falls one sample after E's gold goes empty.
        a = ["teal", "teal", "empty", "empty", "gold", "gold"]
        b = ["teal", "teal", "empty", "empty", "empty", "empty"]
        c = ["empty", "empty", "empty", "empty", "empty", "empty"]
        frames = [_drop_frame(a + ["teal", "teal"])] * 2 + [_drop_frame(b + ["teal", "teal"])] \
            + [_drop_frame(c + ["teal", "teal"])] * 2
        counts, clean, scores = _read(frames)
        ts = [500.0 * (i + 1) for i in range(len(frames))]
        icons = np.ones(len(frames), bool)
        alone = tray.drops(ts, counts, clean, scores, icons)
        self.assertEqual([(d["slot"], d["cooccur"]) for d in alone], [("C", False)])
        both = tray.drops(ts, counts, clean, scores, icons, {(1500.0, "E"): self.SEEN})
        self.assertEqual([(d["slot"], d["cooccur"]) for d in both], [("E", True), ("C", True)])

    def test_an_all_spent_tray_is_drawn_where_its_icons_read(self):
        # C, Q and E empty and the ult dark: no teal anywhere.
        frames = [_drop_frame(self.EMPTY3 + ["empty", "empty"], teal_x=0)] * 2
        counts, clean, scores = _read(frames)
        f = tray.fills(counts, clean)
        h = tray.segment_index(scores)
        self.assertFalse(tray.drawn_mask(f).any())
        self.assertTrue(tray.halves_readable(h).all())
        self.assertFalse(tray.drawn_mask(f, h).any())          # halves alone: no
        self.assertTrue(tray.drawn_mask(f, h, [True, True]).all())
        self.assertFalse(tray.drawn_mask(f, h, [False, False]).any())
        self.assertTrue(tray.drawn(f[0], h[0], True))

    def test_a_gold_half_is_held_across_a_streak(self):
        # A flash hides E on the sample before the spend; the gold half
        # compares as it last read.
        gold = ["empty"] * 4 + ["gold", "gold"] + ["teal", "teal"]
        streak = ["empty"] * 4 + ["flash", "flash"] + ["teal", "teal"]
        frames = [_drop_frame(gold)] * 2 + [_drop_frame(streak)] \
            + [_drop_frame(self.EMPTY3 + ["teal", "teal"])] * 2
        counts, clean, scores = _read(frames)
        ts = [500.0 * (i + 1) for i in range(len(frames))]
        icons = np.ones(len(frames), bool)
        cands = tray.gold_candidates(ts, counts, clean, scores, icons)
        # The gold last read before the streak: its sample is the witness's.
        self.assertEqual([(c["t_ms"], c["t_before_ms"], c["t_gold_ms"]) for c in cands],
                         [(2000.0, 1500.0, 1000.0)])
        got = tray.drops(ts, counts, clean, scores, icons, {(2000.0, "E"): self.SEEN})
        self.assertEqual([(d["t_ms"], d["slot"], d["halves_from"]) for d in got],
                         [(2000.0, "E", ["gold", "gold"])])

    def test_a_gold_run_counts_readable_samples_before_the_drop(self):
        # Phoenix's Curveball: cream beside teal, a streak over the cream on
        # one sample, then the cream half empties with the teal one left.
        cream = ["empty"] * 4 + ["teal", "gold"] + ["teal", "teal"]
        streak = ["empty"] * 4 + ["teal", "flash"] + ["teal", "teal"]
        spent = ["empty"] * 4 + ["teal", "empty"] + ["teal", "teal"]
        frames = [_drop_frame(cream)] * 2 + [_drop_frame(streak)] + [_drop_frame(cream)]             + [_drop_frame(spent)] * 2
        counts, clean, scores = _read(frames)
        ts = [500.0 * (i + 1) for i in range(len(frames))]
        icons = np.ones(len(frames), bool)
        cands = tray.gold_candidates(ts, counts, clean, scores, icons)
        self.assertEqual([(c["t_ms"], c["t_gold_ms"], c["gold_run"]) for c in cands],
                         [(2500.0, 2000.0, 3)])
        w = tray.gold_witness(cands[0], [], {})
        self.assertEqual((w["witnessed"], w["by"], w["gold_run"]), (True, ["persisted"], 3))

    def test_a_one_sample_gold_reading_is_no_run(self):
        # c62c2b06bcfb 216.5 s: an orange weapon behind the spent bar reads
        # gold for one sample.
        empty = self.EMPTY3 + ["teal", "teal"]
        flash = ["empty"] * 4 + ["gold", "empty"] + ["teal", "teal"]
        frames = [_drop_frame(empty)] * 2 + [_drop_frame(flash)] + [_drop_frame(empty)] * 2
        counts, clean, scores = _read(frames)
        ts = [500.0 * (i + 1) for i in range(len(frames))]
        cands = tray.gold_candidates(ts, counts, clean, scores, np.ones(len(frames), bool))
        self.assertEqual([(c["t_ms"], c["gold_run"]) for c in cands], [(2000.0, 1)])
        w = tray.gold_witness(cands[0], [], {})
        self.assertEqual((w["witnessed"], w["by"]), (False, []))

    def test_gold_runs_stop_at_another_class_an_undrawn_sample_or_a_gap(self):
        G, T, E = (tray.SEG_CLASSES.index(c) for c in ("gold", "teal", "empty"))
        U = len(tray.SEG_CLASSES)                                  # unreadable
        col = [G, G, T, G, U, G, G, G, G, G]
        h = np.full((len(col), 4, 2), E)
        h[:, 2, 1] = col
        ts = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 9.0, 9.5]
        good = np.ones(len(col), bool)
        dr = good.copy()
        dr[6] = good[6] = False                                   # undrawn
        runs = tray._gold_runs(ts, h, good, dr)[:, 2, 1].tolist()
        # teal ends a run; the unreadable sample is skipped; the undrawn one
        # ends it; a 5 s gap starts a new one.
        self.assertEqual(runs, [1, 2, 0, 1, 0, 2, 0, 1, 1, 2])

    def test_the_drops_without_halves_are_the_teal_drops(self):
        rows = [(1.0, 1.0, 1.0, 1.0)] * 3 + [(0.0, 1.0, 1.0, 1.0)] * 3
        frames = [_frame(r) for r in rows]
        counts, clean, scores = _read(frames)
        ts = [1000.0 * (i + 1) for i in range(len(rows))]
        plain = tray.drops(ts, counts, clean)
        with_halves = tray.drops(ts, counts, clean, scores, np.ones(len(rows), bool))
        self.assertEqual([(d["t_ms"], d["slot"]) for d in plain], [(4000.0, "C")])
        self.assertEqual([{k: d[k] for k in plain[0]} for d in with_halves], plain)
        self.assertEqual(with_halves[0]["by"], ["fill"])



class GoldWitnessTest(unittest.TestCase):
    """`tray.gold_witness` on the three judged drops' shapes."""
    CAND = {"t_ms": 10000.0, "slot": "E", "t_before_ms": 9500.0, "t_gold_ms": 9500.0}

    @staticmethod
    def _reads(*pairs):
        return [{"t_ms": t, "slot": "E", "numeral": n, "value_s": None if not n else float(n)}
                for t, n in pairs]

    @staticmethod
    def _icon(gold, *after):
        out = {9500.0: [None, None, gold, None]}
        out.update({10000.0 + 500.0 * i: [None, None, v, None] for i, v in enumerate(after)})
        return out

    def test_a_countdown_that_keeps_counting_and_a_dim_icon_refuse(self):
        # c62c2b06bcfb 216.5 s: an orange weapon over the spent bar.
        w = tray.gold_witness(self.CAND, self._reads((9000.0, "27"), (9500.0, "26"),
                                                     (10000.0, "25")), self._icon(109.0, 120.0))
        self.assertFalse(w["witnessed"])
        self.assertEqual((w["countdown"], w["icon"]), ("continued", "dim_on_gold"))

    def test_no_numeral_and_a_dim_icon_refuse(self):
        # a1a995e6b19b 1298.0 s: a yellow wall behind Clove's spent Meddle.
        w = tray.gold_witness(self.CAND, self._reads((10500.0, "")), self._icon(136.0, 136.0))
        self.assertFalse(w["witnessed"])
        self.assertEqual((w["countdown"], w["icon"]), ("no_numeral_after", "dim_on_gold"))

    def test_a_countdown_restarting_witnesses(self):
        # e37fdeca944f 426.6 s: 0.2, then 49, with a teal charge left.
        w = tray.gold_witness(self.CAND, self._reads((9000.0, "0.2"), (9500.0, ""),
                                                     (10500.0, "49")), self._icon(254.0, 254.0))
        self.assertTrue(w["witnessed"])
        self.assertEqual((w["by"], w["numeral_before"], w["numeral_after"]),
                         (["countdown"], "0.2", "49"))
        self.assertEqual(w["icon"], "stayed_lit")

    def test_a_countdown_appearing_witnesses_unless_a_read_refused(self):
        reads = self._reads((10000.0, "50"))
        self.assertEqual(tray.gold_witness(self.CAND, reads, {})["countdown"], "appeared")
        refused = [{"t_ms": 9500.0, "slot": "E", "numeral": None, "value_s": None}] + reads
        w = tray.gold_witness(self.CAND, refused, {})
        self.assertEqual((w["countdown"], w["icon"], w["witnessed"]),
                         ("unread_before", "unread", False))

    def test_an_icon_lit_on_gold_that_dims_witnesses(self):
        w = tray.gold_witness(self.CAND, [], self._icon(251.0, 240.0, 191.0, 107.0))
        self.assertEqual((w["by"], w["icon_on_gold"], w["icon_least_after"]),
                         (["icon"], 251.0, 107.0))
        late = tray.gold_witness(self.CAND, [], self._icon(251.0, 240.0, 240.0, 240.0, 240.0, 107.0))
        self.assertEqual((late["icon"], late["witnessed"]), ("stayed_lit", False))


if __name__ == "__main__":
    unittest.main()
