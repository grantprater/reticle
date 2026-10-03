"""The two bars that turn per-frame killfeed bands into adjudicated entries.

Both are stated in SAMPLES as well as milliseconds, and both tests below exist
because the millisecond form alone gave the wrong answer at native rate: a
2500 ms track gap is five samples at 2 Hz and 150 frames at 60, and a
two-observation minimum is one second at 2 Hz and 33 ms at 60.

The shapes here are the ones measured on `c40d950031bb`, scaled down.
"""
import unittest

from reticle.checks import (KF_ENTRY_MIN_LIFE_MS, _count, entry_presence,
                            sample_step_ms, track_entries)


def steps(t0, n, step):
    return [t0 + i * step for i in range(n)]


def feed(times, occupied):
    """One mask column: `occupied` maps a time to the slots holding an entry."""
    return [sum(1 << s for s in occupied.get(t, ())) for t in times]


class SampleStepTests(unittest.TestCase):
    def test_the_step_is_measured_rather_than_declared(self):
        self.assertAlmostEqual(sample_step_ms(steps(0, 20, 500.0)), 500.0)
        self.assertAlmostEqual(sample_step_ms(steps(0, 20, 1000 / 60)), 1000 / 60)

    def test_a_stall_does_not_move_the_step(self):
        t = steps(0, 20, 500.0) + [200_000.0, 200_500.0]
        self.assertAlmostEqual(sample_step_ms(t), 500.0)

    def test_too_few_reads_fall_back_rather_than_divide_by_nothing(self):
        self.assertEqual(sample_step_ms([]), 500.0)
        self.assertEqual(sample_step_ms([0.0, 500.0]), 500.0)


class PersistenceTests(unittest.TestCase):
    """A band that never persists is not an entry, at any rate."""

    def native(self, occupied, seconds=20.0):
        t = steps(0.0, int(seconds * 60), 1000 / 60)
        return t, track_entries(t, feed(t, occupied))

    def test_a_two_frame_band_at_native_rate_is_refused(self):
        # 33 ms of plate colour cleared KF_MIN_OBS on its own, which is how a
        # camera wipe reached the entry count at 60 Hz and not at 2 Hz.
        t = steps(0.0, 600, 1000 / 60)
        occupied = {t[100]: (0,), t[101]: (0,)}
        tracks = track_entries(t, feed(t, occupied))
        self.assertEqual([a["refused"] for a in tracks], ["no_persistence"])
        self.assertEqual([a["counted"] for a in tracks], [False])

    def test_a_flag_is_counted_in_the_slot_the_entry_held_then(self):
        # The entry rises from slot 1 to slot 0; the flag follows it there,
        # and a flag on the slot it left is another entry's.
        t = steps(0.0, 8, 500.0)
        occupied = {ts: ((1,) if ts < 2000.0 else (0,)) for ts in t}
        flag = feed(t, {ts: ((1,) if ts < 2000.0 else (0, 1)) for ts in t})
        tracks = track_entries(t, feed(t, occupied), flags={"same_side": flag})
        self.assertEqual(len(tracks), 1)
        self.assertEqual((tracks[0]["flag_hits"], tracks[0]["n_obs"]), ({"same_side": 8}, 8))
        tracks = track_entries(t, feed(t, occupied))
        self.assertEqual(tracks[0]["flag_hits"], {})

    def test_a_five_second_entry_at_native_rate_is_counted(self):
        t = steps(0.0, 600, 1000 / 60)
        occupied = {ts: (0,) for ts in t if 2000.0 <= ts <= 7000.0}
        tracks = track_entries(t, feed(t, occupied))
        self.assertEqual([a["counted"] for a in tracks], [True])
        self.assertGreater(tracks[0]["span_ms"], KF_ENTRY_MIN_LIFE_MS)

    def test_the_same_entry_is_counted_at_2_hz_from_two_samples(self):
        # The bar is a LIFE, not a span: `span + 2*step` is the longest life a
        # track is consistent with, so a 2 Hz sampler that caught an entry
        # twice is not refused for resolution it never had.
        t = steps(0.0, 40, 500.0)
        occupied = {2000.0: (0,), 2500.0: (0,)}
        tracks = track_entries(t, feed(t, occupied))
        self.assertEqual([a["counted"] for a in tracks], [True])

    def test_a_single_frame_is_refused_at_every_rate(self):
        for step in (1000 / 60, 500.0):
            t = steps(0.0, 40, step)
            tracks = track_entries(t, feed(t, {t[10]: (0,)}))
            self.assertEqual([a["refused"] for a in tracks], ["single_frame"])


class TrackGapTests(unittest.TestCase):
    """The gap that ends a track is bounded by samples as well as by time."""

    def test_scattered_wipe_bands_do_not_chain_into_the_entry_that_follows(self):
        # Measured shape: seven singles across a respawn wipe in four different
        # slots, 1.8 s of nothing, then the real entry. With a 2500 ms gap and
        # nothing else, all of it was ONE track running 8.0 s -- long enough to
        # pass any persistence bar, and claiming the entry started during the
        # wipe.
        t = steps(0.0, 600, 1000 / 60)
        wipe = {t[i]: (s,) for i, s in ((10, 4), (17, 3), (40, 5), (75, 1))}
        entry = {ts: (0,) for ts in t if 3000.0 <= ts <= 8000.0}
        tracks = track_entries(t, feed(t, {**wipe, **entry}))
        counted = [a for a in tracks if a["counted"]]
        self.assertEqual(len(counted), 1)
        self.assertGreaterEqual(counted[0]["t_first"], 3000.0)

    def test_2_hz_keeps_the_millisecond_gap_it_was_validated_on(self):
        # Every stored session was read at 2 Hz and scored against the
        # scoreboard K/D there. At that rate the sample bound is 20 s and the
        # 2500 ms cap binds, so the walk is the one those numbers validated.
        t = steps(0.0, 60, 500.0)
        # The two reads stay within one entry's life, which the weld split
        # would otherwise cut [domain:killfeed/entry-lifetime].
        occupied = {ts: (0,) for ts in t if ts <= 1500.0 or 3500.0 <= ts <= 5000.0}
        tracks = track_entries(t, feed(t, occupied))
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["t_last"], 5000.0)

    def test_a_dropout_inside_one_entry_does_not_split_it(self):
        # A real entry's plate drops out mid-life -- 583 ms of it on
        # c40d950031bb, returning with the same divider column. Splitting there
        # would double-count the kill.
        t = steps(0.0, 900, 1000 / 60)
        occupied = {ts: (0,) for ts in t
                    if 2000.0 <= ts <= 7000.0 and not 4000.0 < ts < 4500.0}
        tracks = track_entries(t, feed(t, occupied))
        self.assertEqual(len(tracks), 1)


class StackOrderTests(unittest.TestCase):
    """A new entry arrives below; the older one holds the top until it expires
    [domain:killfeed/stack-order]."""

    def test_a_newer_entry_arrives_below_and_rises_when_the_top_expires(self):
        # The stored shape at c40d950031bb: entry A (divider 275, enemy victim)
        # holds slot 0; entry B (278, the player's death) arrives in slot 1 at
        # 908.5 s; slot 0 empties at 909.5 s and B reads in slot 0 from 910.0 s.
        # The dividers agree within KF_SIG_TOL, so the victim side is what keeps
        # B off A's track when B rises into the slot A left.
        from reticle.killfeed import divider_of_ys, FIRST_Y, PITCH
        t = steps(905_000.0, 17, 500.0)
        rows = {ts: ([(0, 275)] if ts < 908_500.0 else
                     [(0, 275), (1, 278)] if ts < 909_500.0 else
                     [(1, 278)] if ts < 910_000.0 else [(0, 278)]) for ts in t}
        masks = feed(t, {ts: tuple(s for s, _ in r) for ts, r in rows.items()})
        wx = [divider_of_ys([FIRST_Y + s * PITCH for s, _ in rows[ts]],
                            [w for _, w in rows[ts]]) for ts in t]
        side = lambda ts, want: sum(1 << s for s, w in rows[ts] if (w == 278) == want)
        sides = [(side(ts, True), side(ts, False)) for ts in t]
        tracks = sorted(track_entries(t, masks, wx, sides=sides), key=lambda a: a["t_first"])
        self.assertEqual([(a["t_first"], a["t_last"], a["slot_first"], a["slot"], a["side"])
                          for a in tracks],
                         [(905_000.0, 909_000.0, 0, 0, "enemy"),
                          (908_500.0, t[-1], 1, 0, "ally")])


def stored(rows):
    """Columns from stored HUD rows `(t_ms, mask, wx, ally, enemy, same, ...)`."""
    cols = list(zip(*rows))
    return list(cols[0]), list(cols[1]), list(cols[2]), list(zip(cols[3], cols[4], cols[5]))


class RiseIntoVacatedSlotTests(unittest.TestCase):
    """An entry rises only into a slot its occupant vacated
    [domain:killfeed/stack-order]: a risen detection belongs to the track from
    below that read last sample, not to the expired track above it."""

    # 043bafca271a (C:/Users/grant/Videos/2026-08-25 13-59-44.mp4), stored
    # hud rows 1499.0-1513.0 s: t, kf_entry_mask, kf_entry_wx, kf_ally_mask,
    # kf_enemy_mask, kf_same_side_mask. Entry A (divider 237, ally victim) reads
    # in slot 0 until 1505.0 s. The player's death B (243, ally victim) arrives
    # in slot 2 at 1506.5 s, reads in slot 1 at 1507.0 s and in slot 0 from
    # 1507.5 s to 1511.0 s; the crop cache shows it rising 2, 1, 0 as the two
    # entries above it expire. The nearest-slot walk gave B's slot-0 reads to
    # A, whose track then ran 1500.5-1511.0 s and B's 1506.5-1507.0 s.
    ROWS_043B = [
        (1499000.0, 0, 0, 0, 0, 0), (1499500.0, 0, 0, 0, 0, 0), (1500000.0, 0, 0, 0, 0, 0),
        (1500500.0, 1, 237, 1, 0, 0), (1501000.0, 1, 237, 1, 0, 0),
        (1501500.0, 1, 237, 1, 0, 0), (1502000.0, 7, 39437549, 3, 4, 0),
        (1502500.0, 7, 39437549, 3, 4, 0), (1503000.0, 7, 39437549, 3, 4, 0),
        (1503500.0, 7, 39437549, 3, 4, 0), (1504000.0, 7, 39437549, 3, 4, 0),
        (1504500.0, 7, 39437549, 3, 4, 0), (1505000.0, 7, 39437549, 3, 4, 0),
        (1505500.0, 6, 39437312, 2, 4, 0), (1506000.0, 3, 77026, 1, 2, 0),
        (1506500.0, 7, 63778018, 5, 2, 0), (1507000.0, 34, 124416, 2, 0, 0),
        (1507500.0, 1, 243, 1, 0, 0), (1508000.0, 1, 243, 1, 0, 0),
        (1508500.0, 1, 243, 1, 0, 0), (1509000.0, 1, 243, 1, 0, 0),
        (1509500.0, 1, 243, 1, 0, 0), (1510000.0, 1, 243, 1, 0, 0),
        (1510500.0, 1, 243, 1, 0, 0), (1511000.0, 1, 243, 1, 0, 0),
        (1511500.0, 0, 0, 0, 0, 0), (1512000.0, 0, 0, 0, 0, 0), (1512500.0, 0, 0, 0, 0, 0),
        (1513000.0, 0, 0, 0, 0, 0)]

    def test_the_players_death_at_043bafca271a_keeps_its_risen_reads(self):
        t, masks, wx, sides = stored(self.ROWS_043B)
        tracks = [a for a in track_entries(t, masks, wx, sides=sides) if a["counted"]]
        got = {a["t_first"]: a for a in tracks}
        self.assertEqual((got[1500500.0]["t_last"], got[1500500.0]["sig"]), (1505000.0, 237))
        b = got[1506500.0]
        self.assertEqual((b["t_last"], b["slot_first"], b["slot"], b["side"]),
                         (1511000.0, 2, 0, "ally"))
        # The walk says which rule took each read: the rise into slot 0 is the
        # stack's, the reads that follow are the nearest slot's.
        self.assertEqual([r for _, _, r in b["assigned"]],
                         ["new", "nearest", "stack_rise"] + ["nearest"] * 7)

    # b3b9defb6fd7 (C:/Users/grant/Videos/2026-08-23 18-24-15.mp4), stored hud
    # rows 1627.0-1641.0 s: t, kf_entry_mask, kf_entry_wx, kf_ally_mask,
    # kf_enemy_mask, kf_same_side_mask, kf_kill_mask, kf_kill_wx. A genuine
    # double: the player kills TurtPlatAccount at 1632.0 s (27:12) and Waylay at
    # 1634.0 s (27:14); the crop cache shows both entries on screen at once.
    # The kill attribution drops out of slot 0 at 1634.0 s and of both slots
    # at 1635.0 s, which is what made "prefer the most recently seen track"
    # shatter it.
    ROWS_B3B9 = [
        (1627000.0, 0, 0, 0, 0, 0, 0, 0), (1627500.0, 0, 0, 0, 0, 0, 0, 0),
        (1628000.0, 0, 0, 0, 0, 0, 0, 0), (1628500.0, 0, 0, 0, 0, 0, 0, 0),
        (1629000.0, 1, 295, 1, 0, 0, 0, 0), (1629500.0, 1, 295, 1, 0, 0, 0, 0),
        (1630000.0, 1, 295, 1, 0, 0, 0, 0), (1630500.0, 1, 295, 1, 0, 0, 0, 0),
        (1631000.0, 1, 295, 1, 0, 0, 0, 0), (1631500.0, 0, 0, 0, 0, 0, 0, 0),
        (1632000.0, 3, 82215, 1, 2, 0, 2, 81920), (1632500.0, 3, 82727, 1, 2, 0, 2, 82432),
        (1633000.0, 6, 81084928, 4, 2, 0, 2, 82432),
        (1633500.0, 7, 81085223, 5, 2, 0, 2, 82432),
        (1634000.0, 7, 58878625, 2, 5, 0, 4, 58720256),
        (1634500.0, 7, 58878625, 2, 5, 0, 5, 58720417),
        (1635000.0, 7, 158208, 2, 5, 0, 0, 0),
        (1635500.0, 7, 58878625, 2, 5, 0, 5, 58720417),
        (1636000.0, 7, 58878625, 2, 5, 0, 5, 58720417),
        (1636500.0, 7, 58878625, 2, 5, 0, 5, 58720417),
        (1637000.0, 6, 58878464, 2, 4, 0, 4, 58720256),
        (1637500.0, 7, 81117493, 5, 2, 0, 2, 114688),
        (1638000.0, 6, 81117184, 4, 2, 0, 2, 114688),
        (1638500.0, 3, 158432, 2, 1, 0, 1, 224), (1639000.0, 2, 158208, 2, 0, 0, 0, 0),
        (1639500.0, 0, 0, 0, 0, 0, 0, 0), (1640000.0, 0, 0, 0, 0, 0, 0, 0),
        (1640500.0, 0, 0, 0, 0, 0, 0, 0), (1641000.0, 0, 0, 0, 0, 0, 0, 0)]

    def test_the_b3b9defb6fd7_double_stays_two_kills(self):
        # The later kill reads in slot 2 while the earlier one still reads in
        # slot 0, so it has not risen, and the stack rule leaves the earlier
        # kill its own track across the dropout.
        rows = self.ROWS_B3B9
        t = [r[0] for r in rows]
        tracks = [a for a in track_entries(t, [r[6] for r in rows], [r[7] for r in rows])
                  if a["counted"]]
        self.assertEqual([(a["t_first"], a["t_last"]) for a in tracks],
                         [(1632000.0, 1636500.0), (1634000.0, 1638500.0)])
        self.assertEqual(_count(t, [r[6] for r in rows], [r[7] for r in rows]), 2)

    def test_the_b3b9defb6fd7_entries_keep_their_tracks(self):
        t, masks, wx, sides = stored(self.ROWS_B3B9)
        tracks = [a for a in track_entries(t, masks, wx, sides=sides) if a["counted"]]
        self.assertEqual([(a["t_first"], a["t_last"], a["slot_first"], a["slot"])
                          for a in tracks],
                         [(1629000.0, 1633500.0, 0, 0), (1632000.0, 1636500.0, 1, 0),
                          (1633000.0, 1637500.0, 2, 0), (1634000.0, 1638500.0, 2, 0),
                          (1637500.0, 1639000.0, 2, 1)])
        self.assertFalse(any(r == "stack_rise" for a in tracks for _, _, r in a["assigned"]))

    # bdfdcf009dba (C:/Users/grant/Videos/2026-08-23 19-25-23.mp4), stored hud
    # rows 1942.5-1956.5 s, columns as above. Evan -> duckyrelicc (divider
    # 195) holds slot 0 until 1948.0 s; Dcmonster002 -> macaroni (198) arrives
    # below it at 1948.0 s and rises to slot 0 at 1949.0 s; Dcmonster002 ->
    # doritorine (195) arrives at 1950.0 s. Every victim is an enemy and the
    # dividers agree, so the nearest slot ran Evan's entry 1943.5-1954.5 s.
    ROWS_BDFD = [
        (1942500.0, 0, 0, 0, 0, 0), (1943000.0, 0, 0, 0, 0, 0), (1943500.0, 1, 195, 0, 1, 0),
        (1944000.0, 1, 195, 0, 1, 0), (1944500.0, 1, 195, 0, 1, 0), (1945000.0, 0, 0, 0, 0, 0),
        (1945500.0, 1, 195, 0, 1, 0), (1946000.0, 1, 195, 0, 1, 0), (1946500.0, 1, 195, 0, 1, 0),
        (1947000.0, 1, 195, 0, 1, 0), (1947500.0, 1, 195, 0, 1, 0),
        (1948000.0, 3, 101571, 0, 3, 0), (1948500.0, 2, 101376, 0, 2, 0),
        (1949000.0, 1, 198, 0, 1, 0), (1949500.0, 1, 199, 0, 1, 0),
        (1950000.0, 3, 100039, 0, 3, 0), (1950500.0, 7, 59082438, 0, 7, 0),
        (1951000.0, 7, 59082438, 0, 7, 0), (1951500.0, 7, 59082438, 0, 7, 0),
        (1952000.0, 7, 59082439, 0, 7, 0), (1952500.0, 7, 59082438, 0, 7, 0),
        (1953000.0, 6, 59082240, 0, 6, 0), (1953500.0, 3, 115395, 0, 3, 0),
        (1954000.0, 3, 115395, 0, 3, 0), (1954500.0, 3, 114883, 0, 3, 0),
        (1955000.0, 2, 115200, 0, 2, 0), (1955500.0, 0, 0, 0, 0, 0), (1956000.0, 0, 0, 0, 0, 0),
        (1956500.0, 0, 0, 0, 0, 0)]

    def test_the_track_whose_slot_was_taken_ends_there(self):
        # When macaroni's entry rises into slot 0, Evan's expired track ends;
        # left open, it would take the risen entry's next read at 1949.5 s.
        t, masks, wx, sides = stored(self.ROWS_BDFD)
        tracks = [a for a in track_entries(t, masks, wx, sides=sides) if a["counted"]]
        self.assertEqual(tracks[0].get("ended_by"), "stack_rise")
        self.assertEqual([(a["t_first"], a["t_last"], a["slot_first"], a["slot"])
                          for a in tracks],
                         [(1943500.0, 1948000.0, 0, 0), (1948000.0, 1952500.0, 1, 0),
                          (1950000.0, 1954500.0, 1, 0), (1950500.0, 1955000.0, 2, 1)])

    def test_two_entries_that_rise_together_keep_their_order(self):
        # 9acf02f98283 (C:/Users/grant/Videos/2026-08-24 11-55-34.mp4) 1226.0-
        # 1237.0 s: Sakiko -> Me (slot 1) and twilightfangrl -> Reyna (slot 2)
        # arrive at 1231.5 s under an expiring entry, dividers 276-278, all
        # ally victims, and both rise one slot at 1232.0 s. The upper entry's
        # slot then holds the lower one, which is no sign the upper one stayed.
        rows = [(1226000.0, 1, 254, 1, 0, 0), (1226500.0, 5, 72876286, 5, 0, 0),
                (1227000.0, 5, 72876286, 5, 0, 0), (1227500.0, 5, 72876286, 5, 0, 0),
                (1228000.0, 5, 72876286, 5, 0, 0), (1228500.0, 5, 72876286, 5, 0, 0),
                (1229000.0, 4, 72876032, 4, 0, 0), (1229500.0, 2, 142336, 2, 0, 0),
                (1230000.0, 2, 142336, 2, 0, 0), (1230500.0, 1, 278, 1, 0, 0),
                (1231000.0, 1, 278, 1, 0, 0), (1231500.0, 6, 72755200, 6, 0, 0)] + [
                (ts, 3, 142100, 3, 0, 0) for ts in steps(1_232_000.0, 9, 500.0)] + [
                (1236500.0, 0, 0, 0, 0, 0), (1237000.0, 0, 0, 0, 0, 0)]
        t, masks, wx, sides = stored(rows)
        tracks = [a for a in track_entries(t, masks, wx, sides=sides) if a["counted"]]
        self.assertEqual([(a["t_first"], a["t_last"], a["slot_first"], a["slot"])
                          for a in tracks if a["t_first"] >= 1226500.0],
                         [(1226500.0, 1231000.0, 2, 0), (1231500.0, 1236000.0, 1, 0),
                          (1231500.0, 1236000.0, 2, 1)])

    def test_a_misread_divider_does_not_become_an_entry(self):
        # 223d636bf8d2 (C:/Users/grant/Videos/2026-08-23 20-09-01.mp4) 755.0-
        # 761.5 s: Koop -> vxCrucifiedxv (divider 181) reads 151 at 758.5 s
        # and no divider at 759.0 s; the crop cache shows one entry. The
        # unread divider fits both tracks in slot 0, and the entry's own track
        # must take it, or the misread becomes a counted entry.
        rows = [(755000.0, 1, 221, 1, 0, 0), (755500.0, 1, 221, 1, 0, 0),
                (756000.0, 3, 93405, 1, 2, 0), (756500.0, 3, 93405, 1, 2, 0),
                (757000.0, 3, 93405, 1, 2, 0), (757500.0, 2, 93184, 0, 2, 0),
                (758000.0, 1, 182, 0, 1, 0), (758500.0, 1, 151, 0, 1, 0),
                (759000.0, 1, 0, 0, 1, 0), (759500.0, 1, 182, 0, 1, 0),
                (760000.0, 1, 181, 0, 1, 0), (760500.0, 1, 181, 0, 1, 0),
                (761000.0, 2, 122368, 2, 0, 0), (761500.0, 1, 239, 1, 0, 0)]
        t, masks, wx, sides = stored(rows)
        tracks = [a for a in track_entries(t, masks, wx, sides=sides) if a["counted"]]
        self.assertEqual([(a["t_first"], a["t_last"]) for a in tracks if 756000.0 <= a["t_first"] <= 760500.0],
                         [(756000.0, 760500.0)])

    def test_a_dropout_above_does_not_hand_its_slot_to_the_entry_below(self):
        # A misses one sample while B, below it, reads; A returns in slot 0 and
        # B still reads in slot 1, so B has not risen and A keeps its track.
        t = steps(0.0, 12, 500.0)
        occupied = {ts: ((0, 1) if ts != 2000.0 else (1,)) for ts in t}
        tracks = track_entries(t, feed(t, occupied), [0] * len(t))
        self.assertEqual([(a["t_first"], a["t_last"], a["slot_first"]) for a in tracks],
                         [(0.0, t[-1], 0), (0.0, t[-1], 1)])

    def test_an_unread_entry_does_not_jump_past_the_entry_above_it(self):
        # bdfdcf009dba (C:/Users/grant/Videos/2026-08-23 19-25-23.mp4) 668.5-
        # 677.5 s, hud-0.17.0 rows read from the crop cache. macaroni -> Clove
        # (an ability kill, divider 337, ally victim) holds slot 1 and Evan ->
        # TunaNoCrust holds slot 3 under the Shooting Error overlay, divider
        # and side unread. At 674.0 s the entry above expires and macaroni's
        # divider reads 365, its plate seam. The unread track fit that read
        # vacuously and took it past Me -> Waylay (slot 2, divider 225), then
        # took macaroni's 337 back at 674.5 s by the stack rule: two entries
        # split into four tracks, two of them false deaths.
        rows = [(668500.0, 1, 0, 0, 1, 0), (669000.0, 5, 53739725, 0, 5, 0),
                (669500.0, 5, 53739725, 0, 5, 0), (670000.0, 4, 53739520, 0, 4, 0),
                (670500.0, 6, 88447488, 4, 2, 0), (671000.0, 3, 172749, 2, 1, 0),
                (671500.0, 7, 58893005, 2, 5, 0), (672000.0, 15, 58893005, 2, 5, 0),
                (672500.0, 15, 59155149, 2, 5, 0), (673000.0, 15, 58893005, 2, 5, 0),
                (673500.0, 15, 58893005, 2, 5, 0), (674000.0, 14, 59169280, 2, 4, 0),
                (674500.0, 7, 48087889, 1, 6, 0), (675000.0, 6, 48087552, 0, 6, 0),
                (675500.0, 3, 93921, 0, 3, 0), (676000.0, 3, 93921, 0, 3, 0),
                (676500.0, 2, 93696, 0, 2, 0), (677000.0, 0, 0, 0, 0, 0),
                (677500.0, 0, 0, 0, 0, 0)]
        t, masks, wx, sides = stored(rows)
        tracks = track_entries(t, masks, wx, sides=sides)
        self.assertEqual([(a["t_first"], a["t_last"], a["slot_first"], a["sig"])
                          for a in tracks if a["counted"] and a["t_first"] >= 669000.0],
                         [(669000.0, 673500.0, 2, 205), (670500.0, 674500.0, 2, 337),
                          (671500.0, 676000.0, 2, 225), (672000.0, 676500.0, 3, 183)])
        # The seam read is a track of its own, refused as one frame.
        self.assertIn((674000.0, 365, "single_frame"),
                      [(a["t_first"], a["sig"], a["refused"]) for a in tracks])

    def test_an_entry_that_arrived_after_the_last_read_orders_nothing(self):
        # bdfdcf009dba 872.5-880.5 s, hud-0.17.0 rows. Evan -> duckyrelicc
        # (divider 195) reads in slot 2 at 875.0 s as the two entries above it
        # expire, goes unread at 875.5 s while TunaNoCrust -> Evan (264)
        # arrives BELOW it in slot 1, and reads in slot 0 from 876.0 s. The
        # newcomer was never seen above it, so it does not block the rise.
        rows = [(872500.0, 3, 115920, 2, 1, 0), (873000.0, 3, 115920, 2, 1, 0),
                (873500.0, 3, 115920, 2, 1, 0), (874000.0, 3, 115920, 2, 1, 0),
                (874500.0, 3, 115920, 2, 1, 0), (875000.0, 4, 51118080, 0, 4, 0),
                (875500.0, 2, 135168, 2, 0, 0)] + [
                (ts, 3, 135363, 2, 1, 0) for ts in steps(876_000.0, 8, 500.0)] + [
                (880000.0, 2, 135168, 2, 0, 0), (880500.0, 0, 0, 0, 0, 0)]
        t, masks, wx, sides = stored(rows)
        tracks = [a for a in track_entries(t, masks, wx, sides=sides) if a["counted"]]
        self.assertEqual([(a["t_first"], a["t_last"], a["slot_first"], a["sig"])
                          for a in tracks if a["t_first"] >= 875000.0],
                         [(875000.0, 879500.0, 2, 195), (875500.0, 880000.0, 1, 264)])

    def test_a_ringed_revive_holds_one_divider_and_one_track(self):
        # bdfdcf009dba (C:/Users/grant/Videos/2026-08-23 19-25-23.mp4) 682.0-
        # 689.0 s, hud-0.18.0 rows read from the crop cache. Evan
        # [Resurrection] Clove arrives in slot 1 at 684.5 s and rises to slot
        # 0 at 687.0 s. At hud-0.17.0 its divider read 327, then 317, 317,
        # 328, 347, 347 in slot 0 -- one ring piece or another -- and the walk
        # counted three tracks. The divider is now the whole ring, 317.
        rows = [(682000.0, 1, 198, 0, 1, 0), (682500.0, 1, 198, 0, 1, 0),
                (683000.0, 1, 198, 0, 1, 0), (683500.0, 1, 198, 0, 1, 0),
                (684000.0, 1, 198, 0, 1, 0), (684500.0, 3, 162502, 2, 1, 2),
                (685000.0, 3, 198, 2, 1, 2), (685500.0, 3, 198, 2, 1, 2),
                (686000.0, 3, 198, 2, 1, 2), (686500.0, 2, 0, 2, 0, 2)] + [
                (ts, 1, 317, 1, 0, 1) for ts in steps(687_000.0, 5, 500.0)] + [
                (689500.0, 0, 0, 0, 0, 0), (690000.0, 0, 0, 0, 0, 0)]
        t, masks, wx, sides = stored(rows)
        same = [r[5] for r in rows]
        tracks = [a for a in track_entries(t, masks, wx, flags={"same_side": same}, sides=sides)
                  if a["counted"]]
        self.assertEqual([(a["t_first"], a["t_last"], a["slot_first"], a["sig"]) for a in tracks],
                         [(682000.0, 686000.0, 0, 198), (684500.0, 689000.0, 1, 317)])


class PlateSideTests(unittest.TestCase):
    """One entry's victim never changes team: a flipped plate is a new entry."""

    # The shape at 59c70f1ef720 slot 0: an enemy-victim entry 1619.5-1624.0 s,
    # one empty sample, then an ally-victim entry 1625.0-1629.0 s, dividers
    # 250 and 253, within KF_SIG_TOL and within the track gap.
    def shape(self):
        t = steps(1_619_500.0, 20, 500.0)
        first = [ts for ts in t if ts <= 1_624_000.0]
        second = [ts for ts in t if ts >= 1_625_000.0]
        masks = feed(t, {ts: (0,) for ts in first + second})
        wx = [250 if ts in first else 253 if ts in second else 0 for ts in t]
        return t, masks, wx, first, second

    def test_a_flip_across_a_missed_sample_starts_a_new_track(self):
        t, masks, wx, first, second = self.shape()
        sides = [(0, 1) if ts in first else (1, 0) if ts in second else (0, 0) for ts in t]
        tracks = track_entries(t, masks, wx, sides=sides)
        self.assertEqual([(a["t_first"], a["t_last"], a["side"]) for a in tracks],
                         [(first[0], first[-1], "enemy"), (second[0], second[-1], "ally")])
        self.assertEqual([a["counted"] for a in tracks], [True, True])

    # Without a side flip the walk joins the two entries across the missed
    # sample; the joined track outlives one entry, so the weld split cuts it
    # back at that gap [domain:killfeed/entry-lifetime].
    def test_without_sides_the_walk_joins_and_the_lifetime_cuts(self):
        t, masks, wx, first, second = self.shape()
        tracks = track_entries(t, masks, wx)
        self.assertEqual([(a["t_first"], a["t_last"]) for a in tracks],
                         [(first[0], first[-1]), (second[0], second[-1])])
        self.assertEqual(tracks[0]["weld"]["cuts"], [(second[0], "gap")])
        self.assertNotIn("side", tracks[0])

    def test_a_stable_side_does_not_split(self):
        t, masks, wx, first, second = self.shape()
        sides = [(0, 1) if ts in first + second else (0, 0) for ts in t]
        tracks = track_entries(t, masks, wx, sides=sides)
        self.assertEqual([(a["t_first"], a["t_last"], a["side"]) for a in tracks],
                         [(first[0], first[-1], "enemy"), (second[0], second[-1], "enemy")])
        self.assertEqual(tracks[0]["weld"]["cuts"], [(second[0], "gap")])

    def test_an_unread_side_rules_nothing_out(self):
        # A sample whose plate went unread (neither bit) keeps the track; the
        # piece the weld split cuts off it read no side.
        t, masks, wx, first, second = self.shape()
        sides = [(0, 1) if ts in first else (0, 0) for ts in t]
        tracks = track_entries(t, masks, wx, sides=sides)
        self.assertEqual([(a["t_first"], a["t_last"], a["side"]) for a in tracks],
                         [(first[0], first[-1], "enemy"), (second[0], second[-1], None)])
        self.assertEqual(tracks[0]["weld"]["cuts"], [(second[0], "gap")])

    def test_a_one_colour_banner_does_not_split_on_its_flicker(self):
        # bdfdcf009dba 1884-1886 s: a revive's plate reads ally with the
        # same-side flag, then enemy, then ally again, divider 328 throughout.
        t = steps(0.0, 12, 500.0)
        on = t[1:10]
        masks = feed(t, {ts: (0,) for ts in on})
        wx = [328 if ts in on else 0 for ts in t]
        flicker = [(1, 0, 1), (1, 0, 1), (0, 1, 0), (1, 0, 1), (0, 1, 0),
                   (1, 0, 1), (0, 1, 0), (1, 0, 1), (1, 0, 1)]
        sides = [flicker[on.index(ts)] if ts in on else (0, 0, 0) for ts in t]
        tracks = track_entries(t, masks, wx, sides=sides)
        self.assertEqual([(a["t_first"], a["t_last"]) for a in tracks], [(on[0], on[-1])])
        # Without the same-side mask the flicker sheds a track at each flip.
        tracks = track_entries(t, masks, wx, sides=[p[:2] for p in sides])
        self.assertGreater(len(tracks), 1)


class EntryPresenceTests(unittest.TestCase):
    """The count of record: what persisted, not what one frame held."""

    def test_a_wipe_contributes_nothing_and_an_entry_covers_its_whole_life(self):
        t = steps(0.0, 600, 1000 / 60)
        wipe = {t[300]: (0, 1, 2), t[301]: (0, 1, 2)}
        entry = {ts: (0,) for ts in t if 1000.0 <= ts <= 6000.0}
        rows = entry_presence(t, feed(t, {**wipe, **entry}))
        at = {r["t_ms"]: r["entries"] for r in rows}
        self.assertEqual(at[t[300]], 1)      # the entry, and not three more
        self.assertEqual(at[t[10]], 0)
        self.assertEqual(at[3000.0], 1)

    def test_a_frame_the_entry_dropped_out_of_still_carries_it(self):
        t = steps(0.0, 900, 1000 / 60)
        occupied = {ts: (0,) for ts in t
                    if 2000.0 <= ts <= 7000.0 and not 4000.0 < ts < 4500.0}
        rows = entry_presence(t, feed(t, occupied))
        at = {r["t_ms"]: r["entries"] for r in rows}
        self.assertEqual(at[t[0]], 0)
        self.assertTrue(all(v == 1 for ts, v in at.items() if 4000.0 < ts < 4500.0))


class WeldSplitTests(unittest.TestCase):
    """A counted track that outlives one entry [domain:killfeed/entry-lifetime]
    is two entries in one slot, cut where the evidence puts it."""

    def walk(self, t0, rows):
        """`rows` maps each 2 Hz sample from `t0` to `[(slot, divider)]`, every
        victim plate enemy."""
        from reticle.killfeed import divider_of_ys, FIRST_Y, PITCH
        t = steps(t0, len(rows), 500.0)
        masks = [sum(1 << s for s, _ in r) for r in rows]
        wx = [divider_of_ys([FIRST_Y + s * PITCH for s, _ in r], [w for _, w in r]) if r else 0
              for r in rows]
        sides = [(0, m, 0) for m in masks]
        return [(a["t_first"], a["t_last"], a["counted"], a.get("weld"))
                for a in track_entries(t, masks, wx, sides=sides)]

    def test_a_slot_gap_after_a_full_life_splits_the_track(self):
        # The stored shape at 043bafca271a: divider 234 reads 820.0-824.5 s, the
        # slot misses 825.0 and 825.5 s, and 236 reads 826.0-830.5 s. The
        # dividers agree within KF_SIG_TOL and the sides match, so the walk
        # held one 10.5 s track and Riot's second death went unmatched.
        rows = [[(0, 234)]] * 10 + [[]] * 2 + [[(0, 236)]] * 10
        got = self.walk(820_000.0, rows)
        weld = {"t_first": 820_000.0, "cuts": [(826_000.0, "gap")]}
        self.assertEqual(got, [(820_000.0, 824_500.0, True, weld),
                               (826_000.0, 830_500.0, True, weld)])

    def test_a_phantom_read_before_a_gap_is_cut_off_the_entry(self):
        # 59c70f1ef720 953.0 s: one read, a two-sample gap, then the entry.
        rows = [[(0, 211)]] + [[]] * 2 + [[(0, 211)]] * 10
        got = self.walk(0.0, rows)
        self.assertEqual([(a, b, c) for a, b, c, _ in got],
                         [(0.0, 0.0, False), (1_500.0, 6_000.0, True)])

    def test_a_cut_off_piece_with_no_divider_is_refused(self):
        # 96aa1ae9b96f 948.5-955.5 s: the entry reads 206 px for ten samples,
        # then the slot reads only unread dividers after a gap.
        rows = [[(0, 206)]] * 10 + [[]] + [[(0, 0)]] * 3
        t = steps(0.0, len(rows), 500.0)
        masks = [sum(1 << s for s, _ in r) for r in rows]
        from reticle.killfeed import divider_of_ys, FIRST_Y, PITCH
        wx = [divider_of_ys([FIRST_Y + s * PITCH for s, w in r if w], [w for _, w in r if w])
              if any(w for _, w in r) else 0 for r in rows]
        got = track_entries(t, masks, wx)
        self.assertEqual([(a["t_first"], a["refused"]) for a in got],
                         [(0.0, None), (5_500.0, "weld_fragment")])

    def test_a_cut_off_full_life_with_no_divider_stays_an_entry(self):
        # e37fdeca944f 499.5-504.0 s: an entry whose divider never read.
        rows = [[(0, 226)]] * 10 + [[]] + [[(0, 0)]] * 10
        t = steps(0.0, len(rows), 500.0)
        masks = [sum(1 << s for s, _ in r) for r in rows]
        from reticle.killfeed import divider_of_ys, FIRST_Y, PITCH
        wx = [divider_of_ys([FIRST_Y + s * PITCH for s, w in r if w], [w for _, w in r if w])
              if any(w for _, w in r) else 0 for r in rows]
        got = track_entries(t, masks, wx)
        self.assertEqual([(a["t_first"], a["refused"]) for a in got],
                         [(0.0, None), (5_500.0, None)])

    def test_a_dropout_inside_one_life_keeps_the_track_whole(self):
        rows = [[(0, 234)]] * 4 + [[]] + [[(0, 234)]] * 5
        self.assertEqual(self.walk(0.0, rows), [(0.0, 4_500.0, True, None)])

    def test_two_lives_back_to_back_split_where_the_divider_steps(self):
        # 9acf02f98283: 246 px reads 1656.0-1660.5 s, then 243 px with no gap.
        rows = [[(0, 246)]] * 10 + [[(0, 243)]] * 10
        got = self.walk(1_656_000.0, rows)
        self.assertEqual([(a, b) for a, b, _, _ in got],
                         [(1_656_000.0, 1_660_500.0), (1_661_000.0, 1_665_500.0)])
        self.assertEqual(got[0][3]["cuts"], [(1_661_000.0, "divider")])

    def test_two_lives_with_one_divider_split_one_life_in(self):
        rows = [[(0, 210)]] * 20
        got = self.walk(0.0, rows)
        self.assertEqual([(a, b) for a, b, _, _ in got], [(0.0, 4_500.0), (5_000.0, 9_500.0)])
        self.assertEqual(got[0][3]["cuts"], [(5_000.0, "life")])

    def test_a_held_entry_that_is_not_two_lives_stays_whole(self):
        # c62c2b06bcfb 1915.5-1922.5 s: 15 samples, held until the round wipe
        # [domain:killfeed/post-round-kill-persists].
        rows = [[(0, 250)]] * 15
        self.assertEqual(self.walk(0.0, rows), [(0.0, 7_000.0, True, None)])


if __name__ == "__main__":
    unittest.main()
