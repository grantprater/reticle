"""`track.assign` on scipy against the Hungarian it replaced.

The reference keeps the old implementation verbatim, here only: both must
reach the same total cost and leave as many rows unmatched on every matrix;
which rows and columns may differ only where optima tie."""
from __future__ import annotations

import random
import unittest

from reticle.track import assign

INF = float("inf")


def _hungarian_reference(cost: list[list[float]], forbidden: float = float("inf")) -> list[int]:
    """The hand-written Hungarian `track.assign` was until 2026-10-02."""
    if not cost or not cost[0]:
        return [-1] * len(cost)
    n_r, n_c = len(cost), len(cost[0])
    n = max(n_r, n_c)
    big = 1e12
    # Square, padded with zeros so unmatched rows are free rather than forced.
    a = [[0.0] * n for _ in range(n)]
    for i in range(n_r):
        for j in range(n_c):
            c = cost[i][j]
            a[i][j] = big if (c is None or c >= forbidden or c != c) else float(c)

    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        # Unused columns stay ascending, so the scan meets them in the order
        # a pass over every column does; a used column's update touches only
        # its own entries, so the order of `done` changes no value.
        free = list(range(1, n + 1))
        done = []
        while True:
            done.append(j0)
            i0, delta, j1 = p[j0], INF, 0
            row, ui = a[i0 - 1], u[i0]
            for j in free:
                cur = row[j - 1] - ui - v[j]
                m = minv[j]
                if cur < m:
                    minv[j] = m = cur
                    way[j] = j0
                if m < delta:
                    delta, j1 = m, j
            for j in done:
                u[p[j]] += delta
                v[j] -= delta
            for j in free:
                minv[j] -= delta
            j0 = j1
            free.remove(j0)
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0], j0 = p[j1], j1

    out = [-1] * n_r
    for j in range(1, n + 1):
        i = p[j] - 1
        if 0 <= i < n_r and j - 1 < n_c and a[i][j - 1] < big:
            out[i] = j - 1
    return out


def _total(cost, picks):
    return sum(cost[i][j] for i, j in enumerate(picks) if j >= 0)


def _matrix(rng, n_r, n_c, p_forbid, ties):
    vals = [0.0, 1.0, 2.0] if ties else None
    return [[INF if rng.random() < p_forbid else
             (rng.choice(vals) if vals else rng.uniform(-5.0, 5.0))
             for _ in range(n_c)] for _ in range(n_r)]


class AssignTest(unittest.TestCase):
    def test_matches_the_reference_cost_on_random_matrices(self):
        rng = random.Random(20261002)
        differ = n = 0
        for _ in range(3000):
            n_r, n_c = rng.randint(1, 8), rng.randint(1, 30)
            if rng.random() < 0.3:
                n_c = n_r
            cost = _matrix(rng, n_r, n_c, rng.choice([0.0, 0.1, 0.5, 0.9]),
                           ties=rng.random() < 0.4)
            new, ref = assign(cost), _hungarian_reference(cost)
            self.assertEqual(sum(j < 0 for j in new), sum(j < 0 for j in ref), cost)
            self.assertAlmostEqual(_total(cost, new), _total(cost, ref), places=9)
            self.assertEqual(len(set(j for j in new if j >= 0)),
                             sum(j >= 0 for j in new))
            n += 1
            differ += new != ref
        # Differences are ties only (equal totals above); report the rate.
        print(f"assign: {differ} of {n} random matrices pick other columns at equal cost")

    def test_forbidden_pairs_are_never_taken(self):
        self.assertEqual(assign([[INF, 5.0], [5.0, INF]]), [1, 0])
        self.assertEqual(assign([[INF, INF], [1.0, 2.0]]), [-1, 0])
        self.assertEqual(assign([[INF, INF]]), [-1])
        self.assertEqual(assign([[None, 1.0], [float("nan"), 2.0]]), [1, -1])

    def test_a_finite_forbidden_threshold(self):
        self.assertEqual(assign([[3.0, 1.0], [1.0, 9.0]], forbidden=5.0), [1, 0])
        self.assertEqual(assign([[9.0, 9.0]], forbidden=5.0), [-1])

    def test_empty_input(self):
        self.assertEqual(assign([]), [])
        self.assertEqual(assign([[], []]), [-1, -1])

    def test_rectangular_both_ways(self):
        self.assertEqual(assign([[3.0, 1.0, 9.0]]), [1])
        self.assertEqual(assign([[3.0], [1.0], [9.0]]), [-1, 0, -1])

    def test_beats_greedy_on_the_crossing_case(self):
        self.assertEqual(assign([[1.0, 2.0], [1.0, 100.0]]), [1, 0])


if __name__ == "__main__":
    unittest.main()
