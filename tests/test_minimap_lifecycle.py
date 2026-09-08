import unittest

from reticle.minimap_lifecycle import Lifecycle, matching_events


def obs(tid=1, x=10, role="ally", lit=10):
    return {"track_id": tid, "role": role, "x": x, "y": 10,
            "position_state": "observed", "light_support": {"known": 100, "lit": lit}}


def frame(t, observations, drawn=True):
    return {"t_ms": t, "widget": "drawn" if drawn else "not_drawn",
            "observations": observations, "light_budget": {"known": 1000, "lit": 200}}


def teleport(**extra):
    event = {"id": "teleport-1", "kind": "teleport", "role": "ally",
             "t_start_ms": 50, "t_end_ms": 150, "available_t_ms": 100,
             "x": 200, "y": 10, "radius_px": 3, "legal": True,
             "predecessor": "ally:1", "channels": ["icon", "viewcone", "audio"],
             "evidence_refs": ["icon:100", "cone:100", "audio:95"]}
    return dict(event, **extra)


class LifecycleTests(unittest.TestCase):
    def test_initial_window_is_censored_not_birth(self):
        row = Lifecycle().step(frame(0, [obs(lit=0)]))[0]
        self.assertTrue(row["eligible"])
        self.assertEqual(row["state"], "left_censored")
        self.assertIsNone(row["origin_interval_ms"])

    def test_new_dark_nonping_quarantined_without_destroying_raw(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs()]))
        raw = obs(2, 200, lit=0)
        result = lifecycle.step(frame(100, [raw]))[0]
        self.assertFalse(result["eligible"])
        self.assertEqual(result["state"], "unlit_unexplained_appearance")
        self.assertNotIn("eligible", raw)
        # Repeated detections do not independently establish an origin.
        self.assertFalse(lifecycle.step(frame(200, [raw]))[0]["eligible"])

    def test_existing_entity_can_persist_in_darkness(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs()]))
        row = lifecycle.step(frame(100, [obs(x=12, lit=0)]))[0]
        self.assertTrue(row["eligible"])
        self.assertEqual(row["state"], "continuation")
        self.assertIsNotNone(row["conflict"])

    def test_confirmed_ping_can_start_in_darkness(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, []))
        event = teleport(kind="ping", role="ping", predecessor=None, channels=["ping"])
        row = lifecycle.step(frame(100, [obs(2, 200, "ping", 0)]), [event])[0]
        self.assertTrue(row["eligible"])
        self.assertIsNone(row["conflict"])

    def test_teleport_relocates_existing_entity(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs()]))
        row = lifecycle.step(frame(100, [obs(2, 200)]), [teleport()])[0]
        self.assertEqual(row["entity_id"], "ally:1")
        self.assertEqual(row["state"], "relocation")
        self.assertIsNone(row["origin_interval_ms"])

    def test_audio_alone_or_future_or_distant_cast_cannot_license_jump(self):
        for event in [teleport(channels=["audio"]), teleport(available_t_ms=101),
                      teleport(x=300), teleport(legal=None), teleport(predecessor="ally:99")]:
            lifecycle = Lifecycle()
            lifecycle.step(frame(0, [obs()]))
            self.assertFalse(lifecycle.step(frame(100, [obs(2, 200)]), [event])[0]["eligible"])

    def test_verified_origin_in_darkness_flags_lighting(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, []))
        cast = teleport(kind="cast", role="ability", predecessor=None)
        row = lifecycle.step(frame(100, [obs(2, 200, "ability", 0)]), [cast])[0]
        self.assertTrue(row["eligible"])
        self.assertEqual(row["conflict"], "origin_vs_lighting")

    def test_blackout_does_not_prove_new_birth(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs()]))
        lifecycle.step(frame(100, [], False))
        row = lifecycle.step(frame(200, [obs(2, 200)]))[0]
        self.assertEqual(row["state"], "left_censored")

    def test_no_light_budget_is_unknown_not_unlit(self):
        f = frame(0, [obs(lit=0)])
        f["light_budget"]["lit"] = 0
        self.assertEqual(Lifecycle().step(f)[0]["light_state"], "unknown")


if __name__ == "__main__":
    unittest.main()
