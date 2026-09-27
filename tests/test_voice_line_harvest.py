"""The voice-line harvester's parsing and file rules on a synthetic page: no network, no store."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import voice_line_harvest as vh  # noqa: E402

CDN = "https://static.wikia.nocookie.net/valorant/images/0/00"


def _head(level: int, title: str) -> str:
    anchor = title.replace(" ", "_")
    return (f'<h{level}><span class="mw-headline" id="{anchor}">{title}</span>'
            f'<span class="mw-editsection">[edit]</span></h{level}>\n')


def _li(text: str, *files: str) -> str:
    audio = "".join(f'<span class="audio-button"><audio src="{CDN}/{f}/revision/latest?cb=1" '
                    f'controls=""></audio></span>' for f in files)
    return f'<li>{audio} "{text}"</li>\n'


def _page(ready_files=("SkyeUltReady1.mp3", "SkyeUltReady2.mp3")) -> str:
    """A quotes page shaped as the wiki's: Abilities, then the radio replies."""
    return (_head(2, "Abilities") + _head(3, "Seekers") + _head(4, "Ally Cast")
            + "<ul>" + _li("Seekers, find them!", "SkyeUltAllyCast.mp3") + "</ul>"
            + _head(2, "Radio Commands") + _head(3, "Menu and Wheel Index")
            + _head(4, "Thanks") + "<ul>" + _li("Thanks!", "SkyeThanks1.mp3") + "</ul>"
            + _head(4, "Ultimate Status") + "<ul>"
            + _li("My ult's not ready.", "SkyeUltDown1.mp3", "SkyeUltDown2.mp3")
            + _li("My ult's almost ready.", "SkyeUltAlmost1.mp3", "SkyeUltAlmost2.mp3")
            + _li("My ult's ready.", *ready_files) + "</ul>"
            + _head(4, "Yes") + "<ul>" + _li("Yes.", "SkyeYes1.mp3") + "</ul>"
            + _head(2, "Pings") + "<ul>" + _li("Ult ready here.", "SkyePing1.mp3") + "</ul>")


class SectionTests(unittest.TestCase):

    def test_section_items_reads_one_heading_at_any_level(self):
        items = vh.section_items(_page(), "Ultimate Status")
        self.assertEqual([i["text"] for i in items],
                         ['"My ult\'s not ready."', '"My ult\'s almost ready."', '"My ult\'s ready."'])
        self.assertEqual({i["heading"] for i in items},
                         {"Radio Commands / Menu and Wheel Index / Ultimate Status"})
        self.assertEqual(len(items[2]["urls"]), 2)

    def test_a_section_holds_its_subheadings_and_stops_at_its_level(self):
        items = vh.section_items(_page(), "Menu and Wheel Index")
        texts = [i["text"] for i in items]
        self.assertIn('"Thanks!"', texts)
        self.assertIn('"Yes."', texts)
        self.assertNotIn('"Ult ready here."', texts)      # under the next h2

    def test_the_cast_parser_never_reads_the_radio_replies(self):
        items, _excluded, _sub = vh.parse_page(_page())
        self.assertEqual({i["section"] for i in items}, {"Ally Cast"})


class ReplyTests(unittest.TestCase):

    #: Every phrasing the 29 pages used on 2026-09-27, by reply.
    READY = ("My ult's ready.", "My ult is ready.", "My ultimate's ready.",
             "My ultimate is ready.", "Ultimate ready.", "Thrash is ready.")
    ALMOST = ("My ult's almost ready.", "Ult's almost ready.", "My ult is almost ready.",
              "My ultimate's almost ready.", "My ultimate is almost ready.",
              " Thrash is almost ready.")
    NOT = ("My ult's not ready.", "My ult's not ready yet.", "My ult is not ready.",
           "My ult isn't ready.", "My ultimate isn't ready.", "My ultimate's not ready.",
           "My ultimate is not ready.", "She's not ready.", "My ult’s not ready.")

    def test_each_reply_is_named_by_its_words(self):
        for state, texts in (("ready", self.READY), ("almost", self.ALMOST), ("not", self.NOT)):
            for t in texts:
                self.assertEqual(vh.ult_status_state(f'"{t}"'), state, t)
        self.assertIsNone(vh.ult_status_state('"Thanks!"'))

    def test_the_file_name_tag_names_the_reply(self):
        self.assertEqual(vh.status_tag(f"{CDN}/SkyeUltReady1.mp3/revision/latest?cb=1"), "ready")
        self.assertEqual(vh.status_tag(f"{CDN}/KAYOUltAlmost2.mp3/revision/latest"), "almost")
        self.assertEqual(vh.status_tag(f"{CDN}/GekkoUltDown1.mp3"), "not")
        self.assertIsNone(vh.status_tag(f"{CDN}/SkyeThanks1.mp3"))


class HarvestTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.dest = self.tmp / "ult_ready"
        casts = self.tmp / "casts"
        casts.mkdir()
        (casts / "index.json").write_text(json.dumps([
            {"agent": "Skye", "ability": "Seekers", "section": "Ally Cast", "line": "x",
             "source_url": "u", "wiki_page": "Skye/Quotes",
             "file": "Skye__seekers__ally-cast__1.mp3", "bytes": 1, "fetched": "t"}]),
            encoding="utf-8")
        self.fetched = []
        self.html = _page()

        def download(url, dest):
            self.fetched.append(url)
            body = f"take {url}".encode()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            return len(body)

        self.patches = [mock.patch.object(vh, "INDEX", casts / "index.json"),
                        mock.patch.object(vh, "_lower_priority", lambda: None),
                        mock.patch.object(vh, "_resolve_quotes_page", lambda a: f"{a}/Quotes"),
                        mock.patch.object(vh, "_api_parse", lambda title: self.html),
                        mock.patch.object(vh, "_download_asset", download)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _run(self):
        with mock.patch("builtins.print"):
            return vh.harvest_ult_ready(["Skye"], dest_dir=self.dest)

    def _index(self):
        return json.loads((self.dest / "index.json").read_text(encoding="utf-8"))

    def test_only_the_ready_takes_are_fetched_and_named_by_order(self):
        s = self._run()[0]
        self.assertEqual(sorted(p.name for p in self.dest.glob("*.mp3")),
                         ["Skye__ultimate-status__1.mp3", "Skye__ultimate-status__2.mp3"])
        self.assertEqual(len(self.fetched), 2)
        self.assertEqual(s["other_replies"], 2)
        rows = self._index()
        self.assertEqual(set(rows[0]), {"agent", "ability", "section", "line", "source_url",
                                        "wiki_page", "file", "bytes", "fetched"})
        self.assertEqual({r["ability"] for r in rows}, {"Seekers"})
        self.assertEqual({r["section"] for r in rows}, {"Ultimate Status"})

    def test_a_second_run_fetches_nothing(self):
        self._run()
        self.fetched.clear()
        self._run()
        self.assertEqual(self.fetched, [])
        self.assertEqual(len(self._index()), 2)

    def test_a_file_already_present_is_kept_not_overwritten(self):
        self.dest.mkdir()
        (self.dest / "Skye__ultimate-status__1.mp3").write_bytes(b"already here")
        self._run()
        self.assertEqual((self.dest / "Skye__ultimate-status__1.mp3").read_bytes(), b"already here")
        self.assertEqual(len(self.fetched), 1)
        self.assertEqual(len(self._index()), 2)

    def test_a_take_whose_file_name_disagrees_is_refused(self):
        self.html = _page(("SkyeUltReady1.mp3", "SkyeUltDown9.mp3"))
        s = self._run()[0]
        self.assertEqual(len(self._index()), 1)
        self.assertEqual(len(s["refused"]), 1)
        self.assertIn("file name says not", s["refused"][0])

    def test_a_file_holding_another_take_refuses_the_new_one(self):
        self._run()
        self.html = _page(("SkyeUltReady7.mp3", "SkyeUltReady2.mp3"))
        s = self._run()[0]
        self.assertEqual(len(s["refused"]), 1)
        self.assertIn("already holds", s["refused"][0])
        self.assertEqual(len(self._index()), 2)


class CountTests(unittest.TestCase):

    def test_counts_split_lines_from_takes(self):
        rows = [{"agent": "KAY/O", "line": "a", "bytes": 3}, {"agent": "KAY/O", "line": "a", "bytes": 3},
                {"agent": "Skye", "line": "b", "bytes": 4}]
        v = vh.ult_ready_counts(rows, {"KAY_O", "Skye", "Sova"})
        self.assertEqual((v["agents"], v["lines"], v["files"], v["bytes"]), (2, 2, 3, 10))
        self.assertEqual((v["files_per_agent_min"], v["files_per_agent_median"],
                          v["files_per_agent_max"]), (1, 1.5, 2))
        self.assertEqual((v["agents_with_ult_asset"], v["agents_with_ult_asset_covered"]), (3, 2))


if __name__ == "__main__":
    unittest.main()
