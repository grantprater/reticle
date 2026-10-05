"""The ladder fetcher on synthetic fixtures; nothing here opens a socket.

Every match, PUUID and key below is made up. The v4 shape follows HenrikDev's
published schema (docs.henrikdev.xyz, get-match-details-v4), never a recorded
response.
"""
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import ladder_fetch as lf  # noqa: E402

KEY = "HDEV-test-not-a-key"


def puuid(i):
    return f"00000000-0000-0000-0000-{i:012d}"


def mid(i):
    return f"11111111-0000-0000-0000-{i:012d}"


def who(i, team):
    return {"puuid": puuid(i), "name": f"n{i}", "tag": "t", "team": team}


def match(m, players, tier="Gold 2", queue="competitive",
          started="2026-09-20T12:00:00Z", rounds=2):
    """A v4 match: players `players` (ten ints), first five Red."""
    team = {p: ("Red" if k < 5 else "Blue") for k, p in enumerate(players)}
    tiers = tier if isinstance(tier, list) else [tier] * len(players)
    rs, ks = [], []
    for r in range(rounds):
        rs.append({
            "id": r, "result": "Elimination", "ceremony": "CeremonyDefault",
            "winning_team": "Red",
            "plant": {"round_time_in_ms": 40000, "site": "A",
                      "location": {"x": 1, "y": 2},
                      "player": who(players[0], "Red"),
                      "player_locations": [
                          {"player": who(p, team[p]), "view_radians": 0.5,
                           "location": {"x": p, "y": -p}}
                          for p in players]} if r == 0 else None,
            "defuse": None,
            "stats": [{"player": who(p, team[p]),
                       "economy": {"loadout_value": 3900, "remaining": 100,
                                   "weapon": {"id": "w", "name": "Vandal",
                                              "type": "Weapon"},
                                   "armor": {"id": "a", "name": "Heavy"}},
                       "stats": {"score": 200, "kills": 1},
                       "was_afk": False, "received_penalty": False,
                       "stayed_in_spawn": False} for p in players]})
        for v in players[5:]:
            ks.append({
                "round": r, "time_in_round_in_ms": 10000 + v,
                "time_in_match_in_ms": 100000 * r + v,
                "killer": who(players[0], "Red"),
                "victim": who(v, "Blue"),
                "assistants": [who(players[1], "Red")] if v % 2 else [],
                "weapon": {"id": "w", "name": "Vandal", "type": "Weapon"},
                "secondary_fire_mode": False,
                "location": {"x": v, "y": v},
                "player_locations": [
                    {"player": who(p, team[p]), "view_radians": 1.0,
                     "location": {"x": p, "y": p}} for p in players[:3]]})
    return {"metadata": {"match_id": mid(m), "map": {"id": "m", "name": "Ascent"},
                         "game_version": "v", "game_length_in_ms": 1,
                         "started_at": started, "is_completed": True,
                         "queue": {"id": queue}, "season": {"short": "e11a1"},
                         "region": "na", "cluster": "x"},
            "players": [{"puuid": puuid(p), "name": f"n{p}", "tag": "t",
                         "team_id": team[p], "party_id": f"party{p % 3}",
                         "agent": {"name": "Jett"},
                         "tier": {"id": 13, "name": tiers[k]},
                         "account_level": 50,
                         "stats": {"score": 1, "kills": 1, "deaths": 1,
                                   "assists": 0},
                         "behavior": {"afk_rounds": 0, "rounds_in_spawn": 0}}
                        for k, p in enumerate(players)],
            "teams": [{"team_id": "Red", "won": True,
                       "rounds": {"won": rounds, "lost": 0}},
                      {"team_id": "Blue", "won": False,
                       "rounds": {"won": 0, "lost": rounds}}],
            "rounds": rs, "kills": ks}


def body(ms):
    return json.dumps({"status": 200, "data": ms}).encode()


class Clock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class Opener:
    """Replies from a list in order; records every URL and header set."""

    def __init__(self, replies, clock=None, cost=0.0):
        self.replies, self.calls, self.clock, self.cost = list(replies), [], \
            clock, cost

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        if self.clock:
            self.clock.t += self.cost
        r = self.replies.pop(0)
        return r if isinstance(r, lf.Response) else lf.Response(200, {}, r)


def client(replies, state=None, **pol):
    c = Clock()
    st = state or lf.State(since="2026-01-01")
    op = Opener(replies, c)
    return lf.Client(KEY, st, lf.Politeness(**pol), op, c.sleep, c), op, c, st


class Limits(unittest.TestCase):
    def test_half_the_documented_limit(self):
        p = lf.Politeness()
        self.assertEqual(p.per_min, 15)
        self.assertEqual(p.interval_s, 4.0)
        self.assertEqual(lf.Politeness(fraction=0.9).per_min, 15)  # capped
        self.assertEqual(lf.Politeness(key_tier="enhanced").interval_s,
                         60 / 45)

    def test_limiter_spaces_requests(self):
        c = Clock()
        lim = lf.Limiter(4.0, c.sleep, c)
        for _ in range(3):
            lim.wait()
            c.t += 1.0         # the request takes a second
        self.assertEqual(c.slept, [3.0, 3.0])
        lim.hold(30)
        lim.wait()
        self.assertEqual(c.slept[-1], 30)

    def test_wait_hints(self):
        self.assertEqual(lf.wait_hint_s({"retry-after": "12"}), 12)
        self.assertEqual(lf.wait_hint_s({"X-RateLimit-Reset": "7"}), 7)
        self.assertIsNone(lf.wait_hint_s({}))


class Backoff(unittest.TestCase):
    def test_429_honours_retry_after(self):
        cl, op, c, st = client([lf.Response(429, {"Retry-After": "45"}, b""),
                                body([])])
        _, r = cl.get("/x")
        self.assertEqual(r.status, 200)
        self.assertIn(45, c.slept)
        self.assertEqual(st.requests_total, 2)
        self.assertEqual(st.consecutive_errors, 0)

    def test_5xx_backs_off_exponentially(self):
        cl, op, c, st = client([lf.Response(503, {}, b""),
                                lf.Response(502, {}, b""), body([])],
                               max_consecutive_errors=5)
        cl.get("/x")
        self.assertEqual([s for s in c.slept if s >= 8], [8, 16])

    def test_repeated_errors_stop(self):
        cl, op, c, st = client([lf.Response(500, {}, b"")] * 5)
        with self.assertRaises(lf.Stop):
            cl.get("/x")
        self.assertEqual(len(op.calls), 3)

    def test_network_error_counts_as_failure(self):
        cl, op, c, st = client([lf.Response(0, {}, b"refused")] * 3)
        with self.assertRaises(lf.Stop):
            cl.get("/x")

    def test_caps_stop_before_sending(self):
        st = lf.State(requests_total=5)
        cl, op, c, _ = client([body([])], state=st, total_cap=5)
        with self.assertRaises(lf.Stop):
            cl.get("/x")
        self.assertEqual(op.calls, [])
        st = lf.State(requests_by_day={lf.today(): 3})
        cl, op, c, _ = client([body([])], state=st, daily_cap=3)
        with self.assertRaises(lf.Stop):
            cl.get("/x")
        self.assertEqual(op.calls, [])

    def test_no_key_stops(self):
        with self.assertRaises(lf.Stop):
            lf.Client("", lf.State(), lf.Politeness())

    def test_remaining_zero_holds(self):
        cl, op, c, st = client([lf.Response(200, {"X-RateLimit-Remaining": "0",
                                                  "X-RateLimit-Reset": "50"},
                                            body([])), body([])])
        cl.get("/x")
        cl.get("/y")
        self.assertEqual(c.slept[-1], 50)


class Crawl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "v4"

    def tearDown(self):
        self.tmp.cleanup()

    def test_crawl_stores_and_resumes(self):
        st = lf.State(since="2026-01-01")
        lf.add_frontier(st, [{"puuid": puuid(1), "kind": "owner"}])
        m1 = match(1, list(range(1, 11)))
        m2 = match(2, [1] + list(range(11, 20)))
        old = match(3, list(range(1, 11)), started="2025-01-01T00:00:00Z")
        unr = match(4, list(range(1, 11)), queue="unrated")
        cap = match(5, list(range(1, 11)))
        cl, op, c, _ = client([body([m1, m2, old, unr, cap])], state=st)
        pol = lf.Politeness(max_matches=50)
        r = lf.crawl(cl, st, self.out, pol, known={mid(5)}, owners_only=True)
        self.assertEqual(r["new"], 2)
        self.assertEqual(r["duplicate"], 1)       # the captured match
        self.assertEqual(r["out_of_scope"], 2)    # old and unrated
        url, hdr = op.calls[0]
        self.assertIn("mode=competitive", url)
        self.assertIn("size=10", url)
        self.assertEqual(hdr["Authorization"], KEY)
        # raw stored gzip with a manifest row; the key appears nowhere
        man = lf.read_manifest(self.out)
        self.assertEqual(len(man), 1)
        raw = (self.out / "raw" / man[0]["file"]).read_bytes()
        self.assertEqual(len(gzip.decompress(raw)), man[0]["bytes"])
        for p in self.out.rglob("*"):
            if p.is_file():
                self.assertNotIn(KEY.encode(), p.read_bytes())
        # resume: the state round-trips; the owner is never listed again
        st.save(self.out / "state.json")
        st2 = lf.State.load(self.out / "state.json")
        self.assertEqual(set(st2.matches), {mid(1), mid(2)})
        nxt = lf.choose_next(st2)
        self.assertNotEqual(nxt["puuid"], puuid(1))
        # a reply repeating stored matches stores none twice
        c2 = lf.register(st2, [m1, m2], "snowball", set())
        self.assertEqual(c2["duplicate"], 2)
        # parse reads the first copy of each stored match
        ms = lf.stored_matches(self.out, st2)
        self.assertEqual(sorted(m["metadata"]["match_id"] for m in ms),
                         [mid(1), mid(2)])

    def test_match_cap(self):
        st = lf.State(since="2026-01-01")
        lf.add_frontier(st, [{"puuid": puuid(1), "kind": "owner"}])
        cl, op, c, _ = client([body([match(1, list(range(1, 11)))])] * 3,
                              state=st)
        lf.crawl(cl, st, self.out, lf.Politeness(max_matches=1), set())
        self.assertEqual(len(op.calls), 1)
        self.assertIn("size=1", op.calls[0][0])

    def test_raw_never_overwritten(self):
        st = lf.State()
        r = lf.Response(200, {}, body([]))
        a = lf.save_raw(self.out, st, "list", "/x", r, "t", [])
        st.seq -= 1                    # a stale state would reuse the name
        with self.assertRaises(FileExistsError):
            lf.save_raw(self.out, st, "list", "/x", r, "t", [])
        self.assertTrue((self.out / "raw" / a["file"]).exists())


class Strata(unittest.TestCase):
    def test_stratum_and_median(self):
        self.assertEqual(lf.stratum("Ascendant 3"), "Ascendant")
        self.assertIsNone(lf.stratum("Unrated"))
        self.assertEqual(lf.match_stratum(["Gold 1", "Gold 3", "Silver 2",
                                           "Platinum 1", None]), "Gold")

    def test_choose_next_fills_the_largest_deficit(self):
        st = lf.State(target_matches=100)
        st.matches = {f"m{i}": {"stratum": "Gold"} for i in range(20)}
        lf.add_frontier(st, [
            {"puuid": "a", "stratum": "Gold"},
            {"puuid": "b", "stratum": "Silver"},
            {"puuid": "c", "stratum": "Radiant"}])
        # Gold is over quota and every other stratum empty, so the
        # first candidate in a starved stratum goes next; Gold waits.
        self.assertEqual(lf.choose_next(st)["puuid"], "b")


class Parse(unittest.TestCase):
    def tables(self, ms, owners=(), captured=()):
        return lf.parse_matches(ms, b"0" * 16, set(owners), set(captured))

    def test_tables(self):
        tiers = ["Gold 1"] * 5 + ["Platinum 2"] * 5
        ms = [match(1, list(range(1, 11)), tier=tiers),
              match(2, list(range(11, 21)), rounds=3)]
        t = self.tables(ms, owners={puuid(1)}, captured={mid(2)})
        self.assertEqual(t["matches"].num_rows, 2)
        self.assertEqual(t["players"].num_rows, 20)
        self.assertEqual(t["rounds"].num_rows, 5)
        self.assertEqual(t["economy"].num_rows, 50)
        self.assertEqual(t["kills"].num_rows, 25)
        kill_pos = [e for e in t["positions"]["event"].to_pylist()
                    if e == "kill"]
        self.assertEqual(len(kill_pos), 75)
        self.assertEqual(t["positions"]["event"].to_pylist().count("plant"),
                         20)
        m = t["matches"].to_pylist()
        self.assertEqual([x["winning_team"] for x in m], ["Red", "Red"])
        self.assertEqual([x["rounds"] for x in m], [2, 3])
        self.assertEqual(m[0]["stratum"], "Gold")      # lower median
        self.assertEqual([x["has_owner"] for x in m], [True, False])
        self.assertTrue(m[1]["captured"] and m[1]["holdout"])
        self.assertEqual(sum(t["players"]["is_owner"].to_pylist()), 1)
        a = t["kills"]["assistants"].to_pylist()
        self.assertEqual(sum(len(x) for x in a), 10)    # odd victims
        self.assertEqual(len({x for xs in a for x in xs}), 2)
        # pseudonyms: no PUUID, name or party id survives in any table
        for name, tab in t.items():
            text = json.dumps(tab.to_pylist(), default=str)
            self.assertNotIn(puuid(1), text, name)
            self.assertNotIn('"n1"', text, name)
            self.assertNotIn("party1", text, name)
        # stable: the same salt names a player alike across tables
        killer = t["kills"]["killer"][0].as_py()
        self.assertIn(killer, t["players"]["player"].to_pylist())

    def test_riot_record_transcodes(self):
        subj = [puuid(i) for i in range(1, 11)]
        rec = {"match": {
            "matchInfo": {"matchId": mid(9), "mapId": "/Game/Maps/X",
                          "gameStartMillis": 1_700_000_000_000,
                          "gameLengthMillis": 1, "queueID": "competitive",
                          "isCompleted": True, "seasonId": "s",
                          "gamePodId": "pod"},
            "players": [{"subject": s, "teamId": "Red" if i < 5 else "Blue",
                         "characterId": "c", "competitiveTier": 12,
                         "partyId": "p", "stats": {"kills": 1}}
                        for i, s in enumerate(subj)],
            "teams": [{"teamId": "Red", "won": True, "roundsWon": 1,
                       "roundsPlayed": 1},
                      {"teamId": "Blue", "won": False, "roundsWon": 0,
                       "roundsPlayed": 1}],
            "roundResults": [{
                "roundNum": 0, "roundResultCode": "Elimination",
                "winningTeam": "Red", "bombPlanter": subj[0],
                "plantRoundTime": 30000, "plantSite": "B",
                "plantLocation": {"x": 1, "y": 1},
                "plantPlayerLocations": [{"subject": subj[0],
                                          "viewRadians": 0.1,
                                          "location": {"x": 1, "y": 1}}],
                "playerEconomies": [{"subject": s, "loadoutValue": 800,
                                     "weapon": "", "armor": "",
                                     "remaining": 0, "spent": 800}
                                    for s in subj]}],
            "kills": [{"round": 0, "gameTime": 5000, "roundTime": 3000,
                       "killer": subj[0], "victim": subj[5],
                       "assistants": [subj[1]],
                       "victimLocation": {"x": 2, "y": 2},
                       "finishingDamage": {"damageType": "Weapon",
                                           "damageItem": "w"},
                       "playerLocations": [
                           {"subject": s, "viewRadians": 0.2,
                            "location": {"x": 0, "y": 0}}
                           for s in subj[:9]]}]}}
        t = self.tables([lf.riot_to_v4(rec)])
        self.assertEqual(t["kills"].num_rows, 1)
        self.assertEqual(t["kills"]["weapon_type"][0].as_py(), "Weapon")
        self.assertEqual(t["economy"]["spent"].to_pylist(), [800] * 10)
        self.assertEqual(t["positions"].num_rows, 10)
        self.assertEqual(t["rounds"]["plant_site"][0].as_py(), "B")


if __name__ == "__main__":
    unittest.main()
