"""The match-fetch kit on fixture responses; nothing here touches a network.

The fixtures copy the shapes of the local client's token reply, the PD
match-history page and the game log's lines; every ID is made up.
"""
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import riot_match_fetch as mf  # noqa: E402

PUUID = "11111111-2222-3333-4444-555555555555"
OTHER = "99999999-8888-7777-6666-555555555555"
CAPTURED = "aaaaaaaa-0000-0000-0000-000000000001"
NEW = [f"bbbbbbbb-0000-0000-0000-00000000000{i}" for i in range(1, 4)]
LOCK = "Riot Client:1234:51234:s3cr3t:https"
LOG = """\
[2026.10.02-19.00.00:000][  0]LogInit: Build: ++Ares-Core+release-13.06
[2026.10.02-19.00.01:000][  0]LogShooter: CI server version: release-13.06-shipping-18-5590001
[2026.10.02-19.00.02:000][  0]LogPlatform: GET https://pd.na.a.pvp.net/store/v1/wallet
[2026.10.02-19.00.03:000][  0]LogPlatform: GET https://glz-na-1.na.a.pvp.net/session
"""


def history_page(start, ids, total):
    return {"Subject": PUUID, "BeginIndex": start,
            "EndIndex": start + len(ids), "Total": total,
            "History": [{"MatchID": m, "GameStartTime": t,
                         "QueueID": "competitive"} for m, t in ids]}


class FakeServer:
    """Answers the URLs the kit asks for; records every request."""

    def __init__(self, puuid=PUUID, details_status=None, n429=0):
        self.puuid = puuid
        self.calls = []
        self.details_status = details_status or {}
        self.n429 = n429
        # four matches, newest first as Riot lists them; one already captured
        allm = [(NEW[2], 1790500000000), (CAPTURED, 1790400000000),
                (NEW[1], 1790300000000), (NEW[0], 1790200000000)]
        self.pages = {0: history_page(0, allm[:2], 4),
                      2: history_page(2, allm[2:], 4)}

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        hdr = {"Date": "Sun, 04 Oct 2026 20:00:00 GMT",
               "Content-Type": "application/json", "Set-Cookie": "x=y"}
        if url.startswith("https://127.0.0.1:51234/entitlements/v1/token"):
            return mf.Response(200, hdr, json.dumps({
                "accessToken": "ACCESS", "token": "ENTITLE",
                "subject": self.puuid, "entitlements": []}).encode())
        assert url.startswith("https://pd.na.a.pvp.net/"), url
        if self.n429:
            self.n429 -= 1
            return mf.Response(429, {"Retry-After": "7"}, b"")
        if "/match-history/v1/history/" in url:
            start = int(url.split("startIndex=")[1].split("&")[0])
            return mf.Response(200, hdr,
                               json.dumps(self.pages[start]).encode())
        mid = url.rsplit("/", 1)[1]
        status = self.details_status.get(mid, 200)
        body = (b'{"matchInfo": {"matchId": "%s"},  "kills": []}'
                % mid.encode()) if status == 200 else b""
        return mf.Response(status, hdr, body)


class Env:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = root / "store"
        (self.store / "external" / "riot").mkdir(parents=True)
        (self.store / "external" / "riot" / f"{CAPTURED}.json").write_text(
            '{"probe": {}, "match": {}}')
        (root / "lockfile").write_text(LOCK)
        (root / "ShooterGame.log").write_text(LOG)
        self.root = root
        self.out = self.store / "external" / mf.OUT_NAME
        self.slept = []

    def args(self, **kw):
        a = dict(account="A", check=False, dry_run=False, limit=None,
                 interval=2.5, shard=None, store=str(self.store),
                 lockfile=str(self.root / "lockfile"),
                 game_log=str(self.root / "ShooterGame.log"))
        a.update(kw)
        return Namespace(**a)

    def run(self, server, **kw):
        return mf.run_fetch(self.args(**kw), opener=server,
                      sleep=self.slept.append, clock=lambda: 0.0)


class ParseTest(unittest.TestCase):
    def test_lockfile(self):
        d = mf.read_lockfile(LOCK + "\n")
        self.assertEqual((d["port"], d["password"]), (51234, "s3cr3t"))
        with self.assertRaises(mf.FetchStop):
            mf.read_lockfile("garbage")

    def test_game_log(self):
        d = mf.read_game_log(LOG)
        self.assertEqual(d["client_version"],
                         "release-13.06-shipping-18-5590001")
        self.assertEqual(d["shards"], ["na"])
        self.assertEqual(mf.choose_shard(["eu", "na"], "na"), "na")
        with self.assertRaises(mf.FetchStop):
            mf.choose_shard(["eu", "na"], None)

    def test_hosts(self):
        self.assertTrue(mf._allowed("https://pd.na.a.pvp.net/x", "na"))
        self.assertTrue(mf._allowed("https://127.0.0.1:1/x", None))
        self.assertFalse(mf._allowed("https://evil.example/x", "na"))
        self.assertFalse(mf._allowed("http://pd.na.a.pvp.net/x", "na"))


class RunTest(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.tmp.cleanup()

    def test_check_contacts_nothing(self):
        s = FakeServer()
        self.assertEqual(self.env.run(s, check=True), 0)
        self.assertEqual(s.calls, [])
        self.assertFalse(self.env.out.exists())

    def test_dry_run_writes_nothing(self):
        s = FakeServer()
        self.assertEqual(self.env.run(s, dry_run=True), 0)
        self.assertFalse(any("match-details" in u for u, _ in s.calls))
        self.assertFalse(self.env.out.exists())

    def test_fetch_saves_raw_and_provenance(self):
        s = FakeServer()
        self.env.run(s)
        details = [u for u, _ in s.calls if "match-details" in u]
        # oldest first, the captured match skipped
        self.assertEqual([u.rsplit("/", 1)[1] for u in details],
                         [NEW[0], NEW[1], NEW[2]])
        raw = self.env.out / "raw" / f"{NEW[0]}.json"
        self.assertEqual(raw.read_bytes(),
                         b'{"matchInfo": {"matchId": "%s"},  "kills": []}'
                         % NEW[0].encode())   # byte for byte, spacing kept
        prov = json.loads((self.env.out / "provenance" /
                           f"{NEW[0]}.json").read_text())
        self.assertEqual(prov["account_label"], "A")
        self.assertEqual(prov["response_date"],
                         "Sun, 04 Oct 2026 20:00:00 GMT")
        self.assertNotIn("Set-Cookie", prov["response_headers"])
        self.assertNotIn("ACCESS", json.dumps(prov))
        self.assertNotIn("ENTITLE", json.dumps(prov))
        self.assertEqual(len(list((self.env.out / "history").glob("*"))), 4)
        # headers the PD probe needed
        _, h = details[0], s.calls[-1][1]
        self.assertEqual(h["X-Riot-ClientVersion"],
                         "release-13.06-shipping-18-5590001")
        self.assertTrue(h["User-Agent"].startswith("reticle-"))
        # rate: every PD request after the first waited the interval
        self.assertEqual(self.env.slept, [2.5] * 4)
        log = (self.env.out / "fetch_log.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(s)["outcome"] for s in log],
                         ["saved"] * 3)

    def test_resume_fetches_nothing_twice(self):
        self.env.run(FakeServer(), limit=1)
        s = FakeServer()
        self.env.run(s)
        details = [u.rsplit("/", 1)[1] for u, _ in s.calls
                   if "match-details" in u]
        self.assertEqual(details, [NEW[1], NEW[2]])

    def test_never_overwrites(self):
        p = self.env.root / "x.json"
        mf.write_new(p, b"1")
        with self.assertRaises(FileExistsError):
            mf.write_new(p, b"2")
        self.assertEqual(p.read_bytes(), b"1")
        self.assertFalse((self.env.root / "x.json.part").exists())

    def test_label_bound_to_one_account(self):
        self.env.run(FakeServer(), limit=1)
        with self.assertRaises(mf.FetchStop):
            self.env.run(FakeServer(puuid=OTHER))           # label A reused
        with self.assertRaises(mf.FetchStop):
            self.env.run(FakeServer(), account="B")          # same account

    def test_404_logged_and_skipped(self):
        s = FakeServer(details_status={NEW[1]: 404})
        self.env.run(s)
        self.assertFalse((self.env.out / "raw" / f"{NEW[1]}.json").exists())
        self.assertTrue((self.env.out / "raw" / f"{NEW[2]}.json").exists())

    def test_403_stops(self):
        s = FakeServer(details_status={NEW[0]: 403})
        with self.assertRaises(mf.FetchStop):
            self.env.run(s)
        self.assertFalse((self.env.out / "raw").exists())

    def test_429_waits_retry_after(self):
        s = FakeServer(n429=1)
        self.env.run(s)
        self.assertIn(7.0, self.env.slept)
        with self.assertRaises(mf.FetchStop):
            other = Env()
            try:
                other.run(FakeServer(n429=10))
            finally:
                other.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
