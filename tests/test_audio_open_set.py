import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))

import audio_open_set as A  # noqa: E402


def row(flac, abilities, phases, persp=None, states=()):
    return {"flac": flac, "abilities": abilities, "phases": phases,
            "media_name_perspective": persp, "states": [list(s) for s in states]}


class CandidateFileTests(unittest.TestCase):
    def test_keeps_only_single_ability_files_of_the_agent(self):
        rows = [row("a", ["Sova:Q:Shock Bolt"], ["cast"]),
                row("b", ["Sova:Q:Shock Bolt", "Sova:E:Recon Bolt"], ["equip"]),
                row("c", [], []),
                row("d", ["Skye:Q:Trailblazer"], ["cast"]),
                row("e", ["Sova:Q:Shock Bolt"], ["refused"])]
        self.assertEqual([f["flac"] for f in A.kit_files(rows, "Sova")], ["a"])

    def test_perspective_prefers_the_media_name(self):
        self.assertEqual(A.perspective(row("x", [], [], "3P", [("Q", "o", "s", "cast", "e", "1P")])), "3P")
        self.assertEqual(A.perspective(row("x", [], [], None, [("Q", "o", "s", "cast", "e", "1P?")])), "1P")
        self.assertEqual(A.perspective(row("x", [], [], None, [("Q", "o", "s", "cast", "e", "3P-ally")])), "3P")
        self.assertEqual(A.perspective(row("x", [], [], None, [("Q", "o", "s", "c", "e", "1P"),
                                                               ("Q", "o", "s", "c", "e", "3P")])), "any")

    def test_a_file_takes_its_earliest_phase(self):
        self.assertEqual(A.file_phase(["impact", "cast"]), ("cast", 2, True))
        self.assertEqual(A.file_phase(["loop"]), ("loop", 6, False))
        self.assertEqual(A.file_phase(["none"]), ("none", None, False))


class SplitTests(unittest.TestCase):
    def test_even_positions_dev(self):
        self.assertEqual(A.split_demos(["c", "a", "b"]), {"dev": ["a", "c"], "held": ["b"]})


class QuantileTests(unittest.TestCase):
    def test_histogram_quantiles_match_numpy(self):
        rng = np.random.default_rng(0)
        r = np.clip(rng.normal(0.1, 0.1, 200000), -1, 1)
        h = np.bincount(A.hist_index(r), minlength=A.HIST_BINS)[None]
        q = A.hist_quantiles(h)[0]
        self.assertAlmostEqual(q[0], np.quantile(r, 0.5), delta=2.0 / A.HIST_BINS)
        self.assertAlmostEqual(q[1], np.quantile(r, 0.999), delta=2.0 / A.HIST_BINS)

    def test_empty_row_is_nan(self):
        self.assertTrue(np.isnan(A.hist_quantiles(np.zeros((1, A.HIST_BINS)))).all())


class PeakTests(unittest.TestCase):
    def test_local_maxima_at_or_above_level_one_per_gap(self):
        V = np.zeros((1, 400), np.float32)
        V[0, 100], V[0, 120], V[0, 300] = 2.0, 1.5, 1.0
        f, k = A.peaks(V, np.ones_like(V, bool), 0.9, gap=50)
        self.assertEqual(list(k), [100, 300])

    def test_invalid_frames_never_peak(self):
        V = np.zeros((1, 200), np.float32)
        V[0, 50] = 3.0
        valid = np.ones_like(V, bool)
        valid[0, 50] = False
        self.assertEqual(len(A.peaks(V, valid, 0.9)[1]), 0)

    def test_a_plateau_keeps_its_first_frame(self):
        V = np.zeros((1, 200), np.float32)
        V[0, 60:63] = 2.0
        self.assertEqual(list(A.peaks(V, np.ones_like(V, bool), 0.9)[1]), [60])


FILES = [{"slot": "Q", "phase": "equip", "rank": 0, "opens": True, "perspective": "1P"},
         {"slot": "Q", "phase": "cast", "rank": 2, "opens": True, "perspective": "1P"},
         {"slot": "Q", "phase": "impact", "rank": 4, "opens": False, "perspective": "3P"},
         {"slot": "E", "phase": "loop", "rank": 6, "opens": False, "perspective": "any"},
         {"slot": "E", "phase": "none", "rank": None, "opens": False, "perspective": "any"}]


def events(dets, files=FILES, family="max", rule=A.RULE):
    """`group_events` over (file index, frame, value) tuples of one session."""
    ft = A.file_table({"x": files}, ["x"])
    f = np.array([d[0] for d in dets], np.int64)
    k = np.array([d[1] for d in dets], np.int64)
    v = np.array([d[2] for d in dets], np.float64)
    E = A.group_events(np.zeros(len(f), np.int64), ft["slot"][f], k, ft["rank"][f],
                       ft["opens"][f], ft["phase"][f], v, family, rule=rule, tie=f)
    return [{"slot": A.SLOTS[s], "frame": int(t), "state": "cast" if c else "equip",
             "best_phase": ft["phase_names"][ft["phase"][f[b]]], "n": int(n)}
            for s, t, c, b, n in zip(E["slot"], E["frame"], E["cast"], E["best"], E["n"])]


def reference_events(dets, files, family):
    """The module docstring's rule, one detection at a time."""
    def rank(fi):
        return A.UNRANKED if files[fi]["rank"] is None else files[fi]["rank"]
    out = []
    for slot in A.SLOTS:
        ds = sorted((d for d in dets if files[d[0]]["slot"] == slot), key=lambda d: (d[1], d[0]))
        chains = []
        for d in ds:
            if chains and d[1] - chains[-1][-1][1] <= A.JOIN_S * 100:
                chains[-1].append(d)
            else:
                chains.append([d])
        cr = [min(rank(d[0]) for d in c) for c in chains]
        parent = list(range(len(chains)))
        for i, c in enumerate(chains):
            for j in range(i - 1, -1, -1):
                if (cr[i] < A.UNRANKED and cr[j] <= A.OPENING_RANK and cr[j] < cr[i]
                        and c[0][1] - chains[j][0][1] <= A.LIFE_S * 100):
                    parent[i] = j
                    break
        root = list(parent)
        for i in range(len(root)):
            while root[root[i]] != root[i]:
                root[i] = root[root[i]]
        groups = {}
        for i, c in enumerate(chains):
            groups.setdefault(root[i], []).extend(c)
        for g in groups.values():
            later = [d[1] for d in g if rank(d[0]) >= A.OPENING_RANK]
            phases = {files[d[0]]["phase"] for d in g}
            if family == "cast" and not any(files[d[0]]["opens"] for d in g):
                continue
            if family == "agree" and len(phases) < 2:
                continue
            out.append((slot, min(later) if later else min(d[1] for d in g), bool(later)))
    return sorted(out, key=lambda e: (e[1], e[0]))


class EventTests(unittest.TestCase):
    def test_phases_in_order_group_into_one_event(self):
        ev = events([(0, 100, 1.0), (1, 150, 2.0), (2, 900, 1.5)])
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["frame"], ev[0]["state"]), (150, "cast"))
        self.assertEqual(ev[0]["best_phase"], "cast")
        old = events([(0, 100, 1.0), (1, 150, 2.0)], rule="audio-open-set-0.1.0")
        self.assertEqual(old[0]["frame"], 100)

    def test_equip_alone_is_an_equip_state_event(self):
        ev = events([(0, 100, 3.0)])
        self.assertEqual((ev[0]["state"], ev[0]["frame"]), ("equip", 100))

    def test_a_cast_long_after_equip_joins_it_and_takes_the_cast_time(self):
        ev = events([(0, 100, 3.0), (1, 700, 2.0)])
        self.assertEqual([(e["state"], e["frame"]) for e in ev], [("cast", 700)])

    def test_a_repeated_cast_phase_opens_a_new_event(self):
        ev = events([(1, 100, 2.0), (1, 600, 2.0)])
        self.assertEqual([e["frame"] for e in ev], [100, 600])

    def test_a_late_phase_past_life_opens_a_new_event(self):
        ev = events([(1, 100, 2.0), (2, 100 + int(A.LIFE_S * 100) + 300, 2.0)])
        self.assertEqual(len(ev), 2)

    def test_an_unphased_chain_never_attaches(self):
        files = FILES[:4] + [dict(FILES[4], slot="Q")]
        self.assertEqual(len(events([(1, 100, 2.0), (4, 900, 2.0)], files)), 2)
        self.assertEqual(len(events([(1, 100, 2.0), (4, 150, 2.0)], files)), 1)   # one chain

    def test_cast_family_needs_an_opening_detection(self):
        self.assertEqual(events([(3, 100, 5.0)], family="cast"), [])
        self.assertEqual(len(events([(3, 100, 5.0)])), 1)

    def test_agree_family_needs_two_phases(self):
        self.assertEqual(events([(1, 100, 5.0)], family="agree"), [])
        self.assertEqual(len(events([(1, 100, 5.0), (2, 300, 1.0)], family="agree")), 1)

    def test_abilities_group_apart(self):
        ev = events([(1, 100, 2.0), (3, 120, 2.0)])
        self.assertEqual(sorted(e["slot"] for e in ev), ["E", "Q"])

    def test_groups_never_join(self):
        ft = A.file_table({"x": FILES}, ["x"])
        i = np.array([0, 1])
        E = A.group_events(np.array([0, 1]), ft["slot"][i], np.array([100, 150]), ft["rank"][i],
                           ft["opens"][i], ft["phase"][i], np.ones(2), "max")
        self.assertEqual(list(E["key"]), [0, 1])

    def test_vectorised_rule_equals_the_reference_on_random_detections(self):
        rng = np.random.default_rng(1)
        for trial in range(300):
            n = int(rng.integers(0, 40))
            dets = sorted({(int(rng.integers(0, len(FILES))), int(rng.integers(0, 6000)),
                            float(rng.random())) for _ in range(n)})
            for fam in A.FAMILIES:
                got = sorted(((e["slot"], e["frame"], e["state"] == "cast")
                              for e in events(dets, family=fam)), key=lambda e: (e[1], e[0]))
                self.assertEqual(got, reference_events(dets, FILES, fam), (trial, fam, dets))


def slots(*s):
    return np.array([A.SLOTS.index(x) for x in s], np.int64)


class MatchTests(unittest.TestCase):
    def test_nearest_same_slot_inside_window_each_once(self):
        ei, ci, _dt = A.match(slots("Q", "Q", "E"), [1000, 1050, 1000], slots("Q", "E"),
                              [1040, 2000])
        self.assertEqual(list(zip(ei.tolist(), ci.tolist())), [(1, 0)])

    def test_assignment_takes_the_most_pairs(self):
        # Nearest-first would pair event 1 with cast 0 and leave cast 1 alone.
        ei, ci, _dt = A.match(slots("Q", "Q"), [1000, 1200], slots("Q", "Q"), [1150, 1450])
        self.assertEqual(sorted(zip(ei.tolist(), ci.tolist())), [(0, 0), (1, 1)])

    def test_empty_sides(self):
        self.assertEqual(len(A.match(slots(), [], slots("Q"), [10])[0]), 0)

    def test_castfree_excludes_the_span_around_each_time(self):
        m = A.castfree_mask(3000, np.ones(3000, bool), [10.0])
        self.assertTrue(m[600] and not m[800] and not m[1900] and m[2100])

    def test_castfree_equals_a_loop(self):
        rng = np.random.default_rng(2)
        live = rng.random(5000) > 0.2
        ts = rng.uniform(-5, 60, 8)
        want = live.copy()
        for t in ts:
            a, b = max(int((t - 3.0) * 100), 0), min(int((t + 10.0) * 100), 5000)
            if b > a:
                want[a:b] = False
        self.assertTrue(np.array_equal(A.castfree_mask(5000, live, ts), want))


class TruthRuleTests(unittest.TestCase):
    def test_menu_and_shared_instant_drops_are_left_out(self):
        casts = [{"t_ms": 1000.0, "slot": "Q"}, {"t_ms": 5000.0, "slot": "C"},
                 {"t_ms": 9000.0, "slot": "E"}]
        drops = [{"t_ms": 1000.0, "slot": "Q", "reason": "no_rounds"},
                 {"t_ms": 5000.0, "slot": "C", "reason": "menu_open"},
                 {"t_ms": 9000.0, "slot": "E", "reason": "no_rounds"},
                 {"t_ms": 9020.0, "slot": "X", "reason": "no_rounds"}]
        self.assertEqual(list(A.demo_truth_rule(casts, drops)), [True, False, False])

    def test_a_drop_of_the_same_slot_or_far_away_keeps_the_cast(self):
        casts = [{"t_ms": 1000.0, "slot": "Q"}]
        drops = [{"t_ms": 1000.0, "slot": "Q"}, {"t_ms": 1500.0, "slot": "E"}]
        self.assertEqual(list(A.demo_truth_rule(casts, drops)), [True])


class GuardTests(unittest.TestCase):
    def test_an_existing_directory_or_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = A.new_dir(Path(d) / "run")
            with self.assertRaises(SystemExit):
                A.new_dir(p)
            A.new_file(p / "r.json", "{}")
            with self.assertRaises(FileExistsError):
                A.new_file(p / "r.json", "{}")

    def test_detections_of_another_parameter_set_are_refused(self):
        A.check_params({"params": "p-1"}, "p-1")
        with self.assertRaises(SystemExit):
            A.check_params({"params": "p-0"}, "p-1")


if __name__ == "__main__":
    unittest.main()
