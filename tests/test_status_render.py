"""`status.render`: the plant column counts unread rounds beside read ones,
and an unread K/D shows as unread with its reason, never 0/0."""
import unittest

from reticle.status import render


def _session(sid, **kw):
    s = {"sid": sid, "map": "ascent", "minutes": 34.0, "n_rounds": 23, "won": 13, "lost": 10,
         "planted": 4, "plant_unread": 19, "kills": 15, "deaths": 16, "kd_basis": "self_entry",
         "kd_reason": None, "kd_unread": (1, 1), "known": None, "verdict": None,
         "geometry": True, "cohort": None, "labels": {}, "hud": True, "video": "present"}
    s.update(kw)
    return s


def _data(*sessions):
    return {"sessions": list(sessions), "hud_version": "h", "minimap_version": "m",
            "ping_version": "p", "round_outcome_version": "r", "roster_version": "o",
            "stored": {}}


class StatusRenderTests(unittest.TestCase):
    def test_the_plant_column_names_the_unread_rounds(self):
        out = render(_data(_session("cadaadeb2d8b")))
        row = next(ln for ln in out.splitlines() if ln.startswith("cadaadeb2d8b"))
        self.assertIn("4/23 (19 unread)", row)
        self.assertIn("15/16", row)
        self.assertIn("self_entry (1/1 unread)", row)

    def test_an_unread_kd_is_unread_with_its_reason(self):
        why = "self_entry:no death verdicts; me:capture_prints_no_me"
        out = render(_data(_session("4f207c0c4e39", kills=None, deaths=None, kd_basis=None,
                                    kd_reason=why, kd_unread=None, plant_unread=0)))
        row = next(ln for ln in out.splitlines() if ln.startswith("4f207c0c4e39"))
        self.assertIn("unread", row)
        self.assertNotIn("0/0", row)
        self.assertIn(f"K/D unread for 4f207c0c4e39: {why}", out)


if __name__ == "__main__":
    unittest.main()
