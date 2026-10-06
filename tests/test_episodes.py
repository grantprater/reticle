"""Episode definitions (docs/EPISODES.md) on a synthetic timeline.

One round on a toy map: one wall, five boxes for super-regions. A1 and D1
duel past the wall's end, D2 trades A1, three attackers execute onto A while
A4 holds B, A2 plants, D3 rotates from B through Mid and retakes A, A5 falls
to his death, and D3 defuses.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("embreex")

from reticle import episodes as ep
from reticle.line_of_sight import Occluders
from reticle.map_regions import Regions

T_END = 90_000.0
DT = 50.0
BLIND = 90.0          # pitch straight up: sees no one on the floor


def wall(x, y0, y1, z0=-1000.0, z1=1000.0):
    a, b, c, d = (x, y0, z0), (x, y1, z0), (x, y1, z1), (x, y0, z1)
    return np.array([[a, b, c], [a, c, d]], np.float32)


def box(x0, x1, y0, y1):
    return np.eye(4), [x0, y0, -1000.0], [x1, y1, 1000.0]


def regions():
    spec = [("Attacker Side", box(-10000, -5000, -10000, 10000)),
            ("A", box(5000, 10000, 5000, 10000)),
            ("B", box(5000, 10000, -10000, -5000)),
            ("Mid", box(5000, 10000, -5000, 5000)),
            ("Defender Side", box(10000, 15000, -10000, 10000))]
    inv = [s[1][0] for s in spec]
    lo = [s[1][1] for s in spec]
    hi = [s[1][2] for s in spec]
    labels = [{"volume": n, "region": n, "super": n, "basis": "inside"} for n, _ in spec]
    return Regions(inv, lo, hi, labels)


def yaw_to(p, q):
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))


def track(segments):
    """segments: list of (t_from, (x, y), yaw, pitch); piecewise constant."""
    t = np.arange(0.0, T_END, DT)
    out = {k: np.zeros(t.size) for k in ("x", "y", "z", "yaw", "pitch")}
    out["t"] = t
    for t0, (x, y), yaw, pitch in segments:
        m = t >= t0
        out["x"][m], out["y"][m], out["z"][m] = x, y, 100.0
        out["yaw"][m], out["pitch"][m] = yaw, pitch
    return out


ATT_SPAWN = (-7000.0, 0.0)
DEF_SPAWN = (12000.0, 0.0)
A_SITE = (7000.0, 7000.0)
B_SITE = (7000.0, -7000.0)
MID = (8000.0, 0.0)
SPAWNS = {"attack": np.array(ATT_SPAWN), "defence": np.array(DEF_SPAWN)}


def timeline():
    a1, d1, d2 = (6000.0, 0.0), (7000.0, 0.0), (7000.0, -3000.0)
    d1_out = (7000.0, 3000.0)
    tracks = {
        "A1": track([(0, ATT_SPAWN, 0, BLIND), (30_000, a1, 0, BLIND),
                     (39_500, a1, yaw_to(a1, d1_out), 0)]),
        "A2": track([(0, ATT_SPAWN, 0, BLIND), (50_000, A_SITE, 0, BLIND)]),
        "A3": track([(0, ATT_SPAWN, 0, BLIND), (50_000, A_SITE, 0, BLIND)]),
        "A4": track([(0, ATT_SPAWN, 0, BLIND), (40_000, B_SITE, 0, BLIND)]),
        "A5": track([(0, ATT_SPAWN, 0, BLIND), (50_000, A_SITE, 0, BLIND)]),
        "D1": track([(0, DEF_SPAWN, 0, BLIND), (30_000, d1, 180, BLIND),
                     (39_000, d1_out, yaw_to(d1_out, a1), 0)]),
        "D2": track([(0, DEF_SPAWN, 0, BLIND), (30_000, d2, 180, BLIND),
                     (42_000, d2, yaw_to(d2, a1), 0)]),
        "D3": track([(0, DEF_SPAWN, 0, BLIND), (30_000, B_SITE, 0, BLIND),
                     (55_000, MID, 0, BLIND), (62_000, A_SITE, 0, BLIND)]),
        "D4": track([(0, DEF_SPAWN, 0, BLIND)]),
        "D5": track([(0, DEF_SPAWN, 0, BLIND)]),
    }
    slots = [ep.Slot(f"A{k}", "red") for k in range(1, 6)] + [ep.Slot(f"D{k}", "blue")
                                                               for k in range(1, 6)]
    E = ep.Event
    events = [
        E("round_start", 0.0, "rs1"), E("buy_end", 30_000.0, "be1"),
        E("damage", 40_000.0, "dm1", actor="A1", target="D1", amount=40.0, wallbang=False),
        E("death", 40_300.0, "k1", actor="A1", target="D1"),
        E("damage", 42_800.0, "dm2", actor="D2", target="A1", amount=140.0, wallbang=False),
        E("death", 43_000.0, "k2", actor="D2", target="A1"),
        E("plant", 60_000.0, "pl1", actor="A2", position=(A_SITE[0], A_SITE[1], 100.0)),
        E("death", 70_000.0, "k3", actor=None, target="A5", cause="fall"),
        E("defuse", 80_000.0, "df1", actor="D3"),
        E("round_end", 80_100.0, "re1"),
        E("round_start", 87_000.0, "rs2"),
        E("match_end", T_END, "end"),
    ]
    return ep.ArrayTimeline("synthetic", "toy", slots, tracks, events)


def derive(tl):
    occ = Occluders("toy", tris=wall(6500.0, -1000.0, 1000.0))
    return ep.derive_episodes(tl, occ=occ, regions=regions(), spawns=SPAWNS)


@pytest.fixture(scope="module")
def derived():
    return derive(timeline())


def kinds(d, kind, rnd=1):
    return [e for e in d.episodes if e["kind"] == kind and e["round"] == rnd]


def test_phases_tile_the_round(derived):
    ph = sorted([e for e in derived.episodes if e["kind"].startswith("phase_") and e["round"] == 1],
                key=lambda e: e["t_start_ms"])
    assert [e["kind"] for e in ph] == ["phase_buy", "phase_live", "phase_post_plant",
                                       "phase_round_over"]
    for a, b in zip(ph, ph[1:]):
        assert a["t_end_ms"] == b["t_start_ms"]
    assert ph[0]["t_start_ms"] == 0.0 and ph[-1]["t_end_ms"] == 87_000.0
    out = ph[2]["outcome"]
    assert out["end_reason"] == "defuse" and out["winner"] == "blue"
    assert out["attack_team"] == "red" and out["end_lag_ms"] == 100.0


def test_attack_team_from_spawn(derived):
    assert derived.header["attack_team"]["1"] == "red"


def test_duel_rests_on_sight_and_acts(derived):
    duels = kinds(derived, "duel")
    first = next(d for d in duels if set(d["participants"].values()) == {"A1", "D1"})
    # D1 steps past the wall's end at 39 s facing A1; A1 turns at 39.5 s.
    assert first["t_start_ms"] == pytest.approx(39_000.0, abs=70.0)
    assert first["t_end_ms"] == 40_300.0
    assert first["first_seer"] == "D1"
    assert first["first_hitter"] == "A1"
    assert first["mutual"] and first["sight_at_kill"]
    assert first["outcome"] == {"result": "killed", "killer": "A1", "victim": "D1"}
    assert first["opening"] is True
    second = next(d for d in duels if set(d["participants"].values()) == {"A1", "D2"})
    assert second["outcome"]["killer"] == "D2" and second["opening"] is False


def test_no_duel_without_an_act(derived):
    pairs = {frozenset(d["participants"].values()) for d in kinds(derived, "duel")}
    assert pairs == {frozenset({"A1", "D1"}), frozenset({"A1", "D2"})}


def test_trade_and_engagement(derived):
    eng = kinds(derived, "engagement")
    assert len(eng) == 1
    assert sorted(eng[0]["participants"]["combatants"]) == ["A1", "D1", "D2"]
    assert eng[0]["outcome"]["kills"] == {"blue": 1, "red": 1}
    assert eng[0]["outcome"]["winner"] == "even"
    tr = kinds(derived, "trade")
    assert len(tr) == 1
    t = tr[0]
    assert t["participants"] == {"traded": "D1", "killer": "A1", "trader": "D2"}
    assert t["outcome"]["lag_ms"] == 2700.0 and t["same_engagement"] is True
    assert t["trader_distance_m"] == pytest.approx(math.hypot(1000, 3000) / 100, abs=0.01)


def test_every_kill_in_one_engagement_or_listed(derived):
    deaths = {"k1", "k2", "k3"}
    in_eng = [k for e in derived.episodes if e["kind"] == "engagement" for k in e["kill_events"]]
    listed = [d["event_id"] for d in derived.unassigned_deaths]
    assert sorted(in_eng + listed) == sorted(deaths)
    assert len(set(in_eng)) == len(in_eng)
    assert derived.unassigned_deaths[0]["reason"] == "no_killer"


def test_execute_lurk_retake_rotation(derived):
    ex = kinds(derived, "execute")
    assert len(ex) == 1
    x = ex[0]
    assert x["t_start_ms"] == pytest.approx(50_000.0, abs=250.0)
    assert x["outcome"]["site"] == "A" and x["outcome"]["result"] == "planted"
    assert sorted(x["participants"]["committed"]) == ["A2", "A3", "A5"]
    assert x["participants"]["elsewhere"] == ["A4"]
    lk = kinds(derived, "lurk")
    assert [lu["participants"]["lurker"] for lu in lk] == ["A4"]
    assert lk[0]["regions"] == ["B"]
    rt = kinds(derived, "retake")
    assert len(rt) == 1 and rt[0]["outcome"]["result"] == "defused"
    assert rt[0]["entry_ms"] == pytest.approx(62_000.0, abs=250.0)
    rot = kinds(derived, "rotation")
    assert [r["participants"]["rotator"] for r in rot] == ["D3"]
    assert rot[0]["outcome"] == {"from_site": "B", "to_site": "A"}
    assert rot[0]["path"] == ["B", "Mid", "A"]


def test_contested_plant_is_no_retake():
    tl = timeline()
    tl.tracks["D4"] = track([(0, DEF_SPAWN, 0, BLIND), (45_000, A_SITE, 0, BLIND)])
    d = derive(tl)
    assert not kinds(d, "retake")
    cp = kinds(d, "contested_plant")
    assert len(cp) == 1 and cp[0]["participants"]["on_site"] == ["D4"]


def test_duel_gap_splits_bouts():
    tl = timeline()
    E = ep.Event
    # Two blind exchanges between A4 and D3, 10 s apart: damage at a distance
    # twice, never a duel, and outside every engagement.
    tl.events += [E("damage", 41_000.0, "x1", actor="A4", target="D3", amount=20.0),
                  E("damage", 51_000.0, "x2", actor="D3", target="A4", amount=20.0)]
    tl.events.sort(key=lambda e: e.t_ms)
    d = derive(tl)
    bouts = [x for x in d.episodes if x["kind"] in ("duel", "remote_damage")
             and set(x["participants"].values()) == {"A4", "D3"}]
    assert [b["kind"] for b in bouts] == ["remote_damage", "remote_damage"]
    assert all(b["outcome"]["result"] == "disengaged" and b["sight"] is False for b in bouts)
    eng = kinds(d, "engagement")
    assert all("A4" not in e["participants"]["combatants"] for e in eng)


def test_killing_hit_logged_after_the_kill_joins_its_duel():
    tl = timeline()
    tl.events.append(ep.Event("damage", 40_310.0, "late", actor="A1", target="D1", amount=99.0))
    tl.events.sort(key=lambda e: e.t_ms)
    d = derive(tl)
    pair = [x for x in kinds(d, "duel") if set(x["participants"].values()) == {"A1", "D1"}]
    assert len(pair) == 1 and "late" in pair[0]["members"]
    assert pair[0]["t_end_ms"] == 40_300.0 and pair[0]["hits"] == 2


def test_frustum():
    d = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0], [1.0, 1.3, 0.0],
                  [1.0, 0.0, 1.0]])
    got = ep.frustum(np.zeros(5), np.zeros(5), d, 103.0)
    # 45 degrees in; 52.4 degrees out of a 51.5 half-angle; 45 up out of 35.3.
    assert got.tolist() == [True, False, True, False, False]
    assert ep.frustum(np.array([90.0]), np.array([0.0]), d[1:2], 103.0).tolist() == [True]
    # Pitch is stored wrapped: 350 is ten degrees down.
    assert ep.frustum(np.array([0.0]), np.array([350.0]), np.array([[1.0, 0, -0.2]]),
                      103.0).tolist() == [True]


def test_runs_merge():
    m = np.array([0, 1, 1, 0, 0, 1, 0, 0, 0, 1], bool)
    assert ep.merged_runs(m, 0) == [(1, 2), (5, 5), (9, 9)]
    assert ep.merged_runs(m, 2) == [(1, 5), (9, 9)]
    assert ep.merged_runs(m, 3) == [(1, 9)]


def test_rows_round_trip(tmp_path, derived):
    p = ep.write_episodes(derived, "synthetic", root=tmp_path)
    assert p.name == "synthetic.jsonl"
    head = ep.read_header("synthetic", root=tmp_path)
    assert head["version"] == ep.EPISODES_VERSION and head["source"] == "truth"
    rows = ep.read_episodes("synthetic", root=tmp_path)
    assert sum(r["row"] == "episode" for r in rows) == len(derived.episodes)
