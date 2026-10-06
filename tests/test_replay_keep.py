"""The replay hook: matching a replay to a capture by recording time, keeping,
linking, and what `plan` names, on synthetic headers and a throwaway store."""
import datetime as dt
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from reticle import replay_keep as rk

SID = "sess00000000"
CAPTURE = r"C:\Videos\2026-10-05 18-13-01.mp4"
CAP_START = dt.datetime(2026, 10, 5, 18, 13, 1).timestamp() * 1000.0   # local, as the name
CAP_LEN = 1_700_000.0


def _ticks(epoch_ms: float) -> int:
    return int(round(epoch_ms * 10_000)) + rk._EPOCH_TICKS


def header(length_ms: int, recorded_ms: float | None, version: int = 7,
           name: str = "replay") -> bytes:
    """A replay info header in the layout `read_info` reads."""
    b = struct.pack("<II", rk.VRF_MAGIC, version)
    if version >= 7:
        b += struct.pack("<i", 1) + bytes(range(16)) + struct.pack("<i", 7)
    s = (name + "\0").encode("utf-16-le")
    b += struct.pack("<iIIi", length_ms, 0xABCD, 4091853, -(len(s) // 2)) + s
    b += struct.pack("<I", 0)
    if version >= 1:
        b += struct.pack("<q", _ticks(recorded_ms))
    return b + b"\0" * 64


def write_vrf(d: Path, name: str, length_ms: int, recorded_ms: float | None, **kw) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.vrf"
    p.write_bytes(header(length_ms, recorded_ms, **kw) + name.encode())
    return p


def manifest(path=CAPTURE, duration=CAP_LEN):
    return {"session_id": SID, "source": {"path": path, "duration_ms": duration}}


class HeaderTest(unittest.TestCase):
    def test_reads_length_and_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_vrf(Path(d), "a", 1_784_521, CAP_START - 86_000)
            info = rk.read_info(p)
            self.assertEqual(info["length_ms"], 1_784_521)
            self.assertAlmostEqual(info["recorded_ms"], CAP_START - 86_000, delta=1)

    def test_refuses_another_magic(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.vrf"
            p.write_bytes(b"\x7f\xe2\xa2\x1c" + b"\0" * 64)
            self.assertTrue(rk.read_info(p)["refused"].startswith("not_a_replay"))

    def test_a_header_without_timestamp_dates_by_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_vrf(Path(d), "a", 600_000, None, version=0)
            os.utime(p, (CAP_START / 1000 + 900, CAP_START / 1000 + 900))
            s = rk.replay_span(p)
            self.assertEqual(s["basis"], "mtime")
            self.assertAlmostEqual(s["end_ms"], CAP_START + 900_000, delta=1)
            self.assertAlmostEqual(s["start_ms"], CAP_START + 300_000, delta=1)


class OverlapTest(unittest.TestCase):
    def spans(self, **kw):
        return {n: {"start_ms": a, "end_ms": b} for n, (a, b) in kw.items()}

    def test_one_zero_and_two(self):
        s = self.spans(before=(0, 100), during=(150, 400), after=(500, 900))
        self.assertEqual(rk.overlapping(200, 300, s), ["during"])
        self.assertEqual(rk.overlapping(410, 490, s), [])
        self.assertEqual(rk.overlapping(50, 600, s), ["after", "before", "during"])

    def test_touching_is_no_overlap(self):
        self.assertEqual(rk.overlapping(100, 150, self.spans(a=(0, 100), b=(150, 300))), [])


class FindReplayTest(unittest.TestCase):
    """Candidates come from the Demos folder and the store's kept replays."""

    def setUp(self):
        rk._SPANS.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "store"
        self.demos = Path(self.tmp.name) / "Demos"
        (self.root / "external" / "replays").mkdir(parents=True)
        self.demos.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_the_one_overlapping_replay(self):
        write_vrf(self.demos, "earlier", 1_800_000, CAP_START - 4 * 3_600_000)
        write_vrf(self.demos, "match", 1_784_521, CAP_START - 86_000)
        r = rk.find_replay(manifest(), self.root, self.demos)
        self.assertEqual(r["file"], "match.vrf")
        self.assertEqual(r["span"]["basis"], "header")
        self.assertAlmostEqual(r["overlap_ms"], 1_784_521 - 86_000, delta=1)

    def test_refuses_zero_candidates(self):
        write_vrf(self.demos, "earlier", 1_800_000, CAP_START - 4 * 3_600_000)
        r = rk.find_replay(manifest(), self.root, self.demos)
        self.assertTrue(r["refused"].startswith("no_replay_overlaps_capture"))

    def test_refuses_two_candidates(self):
        write_vrf(self.demos, "one", 1_000_000, CAP_START - 500_000)
        write_vrf(self.root / "external" / "replays", "two", 1_000_000, CAP_START + 900_000)
        r = rk.find_replay(manifest(), self.root, self.demos)
        self.assertEqual(r["refused"], "several_replays_overlap_capture:one.vrf,two.vrf")

    def test_the_mtime_of_a_late_download_does_not_matter(self):
        p = write_vrf(self.demos, "match", 1_784_521, CAP_START - 86_000)
        late = CAP_START / 1000 + 8 * 3600
        os.utime(p, (late, late))
        self.assertEqual(rk.find_replay(manifest(), self.root, self.demos)["file"], "match.vrf")

    def test_refuses_a_capture_name_without_a_stamp(self):
        r = rk.find_replay(manifest(path=r"C:\x\clip.mp4"), self.root, self.demos)
        self.assertTrue(r["refused"].startswith("capture_name_has_no_stamp"))


class KeepLinkTest(unittest.TestCase):
    def test_keep_copies_once_and_refuses_a_differing_copy(self):
        with tempfile.TemporaryDirectory() as d:
            root, demos = Path(d) / "store", Path(d) / "Demos"
            src = write_vrf(demos, "m", 1000, CAP_START)
            self.assertEqual(rk.keep(src, root)["kept"], "copied")
            kept = root / "external" / "replays" / "m.vrf"
            self.assertEqual(kept.read_bytes(), src.read_bytes())
            self.assertEqual(rk.keep(src, root)["kept"], "already_kept")
            kept.write_bytes(b"other")
            self.assertTrue(rk.keep(src, root)["refused"].startswith("kept_copy_differs"))

    def test_link_entry(self):
        span = {"length_ms": 1234, "recorded_ms": CAP_START}
        man = {"files": [{"file": "m.vrf", "capture_session": None, "length_ms": None,
                          "recorded_utc": None}]}
        r = rk.link_entry(man, "m.vrf", SID, CAPTURE, span=span)
        self.assertTrue(r["changed"])
        e = r["manifest"]["files"][0]
        self.assertEqual((e["capture_session"], e["length_ms"]), (SID, 1234))
        self.assertEqual(e["capture_path"], CAPTURE.replace("\\", "/"))
        self.assertIsNone(man["files"][0]["capture_session"])       # input untouched
        self.assertFalse(rk.link_entry(r["manifest"], "m.vrf", SID, CAPTURE, span=span)["changed"])
        self.assertEqual(rk.link_entry(r["manifest"], "m.vrf", "other", CAPTURE)["refused"],
                         f"replay_names_session:{SID}")
        self.assertEqual(rk.link_entry(r["manifest"], "n.vrf", SID, CAPTURE)["refused"],
                         "session_names_another_replay:m.vrf")
        new = rk.link_entry({"files": []}, "n.vrf", SID, CAPTURE, size=5, sha256="ab")
        self.assertEqual(new["manifest"]["files"][0]["sha256"], "ab")

    def test_link_writes_a_backup_first(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rd = root / "external" / "replays"
            rd.mkdir(parents=True)
            body = json.dumps({"files": [{"file": "m.vrf", "capture_session": None}]})
            (rd / "manifest.json").write_text(body)
            self.assertEqual(rk.link_manifest("m.vrf", SID, CAPTURE, root)["linked"], "written")
            self.assertEqual((rd / "manifest.json.bak").read_text(), body)
            self.assertEqual(json.loads((rd / "manifest.json").read_text())["files"][0]
                             ["capture_session"], SID)
            self.assertEqual(rk.link_manifest("m.vrf", SID, CAPTURE, root)["linked"], "already_linked")


class RunTest(unittest.TestCase):
    """The hook over a throwaway store, stopping where its inputs end."""

    def test_steps_and_missing_steps(self):
        rk._SPANS.clear()
        with tempfile.TemporaryDirectory() as d:
            root, demos = Path(d) / "store", Path(d) / "Demos"
            (root / "manifests").mkdir(parents=True)
            (root / "manifests" / f"{SID}.json").write_text(json.dumps(manifest()))
            write_vrf(demos, "match", 1_784_521, CAP_START - 86_000)
            self.assertEqual([m["step"] for m in rk.missing_steps(SID, manifest(), root, demos)],
                             ["keep"])
            # A parse already on disk stands in for vrfkit.
            px = rk.parsed_dir("match", root) / "export"
            px.mkdir(parents=True)
            (px / "actors.parquet").write_bytes(b"")
            rows = rk.run(SID, root, demos)
            got = {r["step"]: next(k for k in ("done", "already", "refused") if k in r)
                   for r in rows}
            self.assertEqual(got, {"find": "done", "keep": "done", "link": "done",
                                   "parse": "already", "wrap": "refused",
                                   "replay_layer": "refused"})
            self.assertEqual(rows[4]["refused"], rk.FETCH_NEEDED)
            self.assertTrue(rows[5]["refused"].startswith("no_stored_deaths"))
            miss = rk.missing_steps(SID, manifest(), root, demos)
            self.assertEqual([(m["step"], m["how"]) for m in miss], [("wrap", "player")])
            again = rk.run(SID, root, demos)
            self.assertEqual([next(k for k in ("done", "already", "refused") if k in r)
                              for r in again][:4], ["already"] * 4)


if __name__ == "__main__":
    unittest.main()
