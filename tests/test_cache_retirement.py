"""Crop caches the player deleted (2026-10-09): the retirement row, the
`cache_retired` refusal, `pixel_source`, and what `plan` and `status` say."""
import json
from types import SimpleNamespace

import pytest

from reticle import plan, roi_cache
from reticle.profiles import get_profile
from reticle.status import render as status_render

SID = "abcdef012345"
ROW = {"at": "2026-10-09T20:05:04+00:00", "reason": "player decision 2026-10-09; future "
       "caches key every frame", "roi_cache_version": roi_cache.ROI_CACHE_VERSION,
       "rois": ["hud", "killfeed_panel", "minimap", "scoreboard"], "sessions": [SID]}


def _man(tmp_path, retired: bool) -> dict:
    man = {"session_id": SID, "source_profile": "valorant-16x9", "ingested_at": "2026-10-01",
           "source": {"path": str(tmp_path / "gone.mp4") if retired else __file__,
                      "content_key": "k", "width": 1920, "height": 1080}}
    if retired:
        man["video_retired"] = {"at": "2026-10-05T00:00:00+00:00"}
    return man


def test_the_row_joins_the_retirement_log_and_load_refuses_cache_retired(tmp_path):
    man, prof = _man(tmp_path, False), get_profile("valorant-16x9")
    assert roi_cache.RoiCache.load(tmp_path, man, prof, "minimap") == (None, "no_cache")
    with pytest.raises(ValueError, match="sessions"):
        roi_cache.record_cache_retirement(tmp_path, {**ROW, "sessions": []})
    # The video retirement log is the same file; its rows carry no `kind`.
    log = tmp_path / roi_cache.CACHE_RETIREMENT_LOG
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"session_id": "other", "status": "retired"}) + "\n",
                   encoding="utf-8")
    roi_cache.record_cache_retirement(tmp_path, ROW)
    assert [r["kind"] for r in roi_cache.cache_retirements(tmp_path)] == ["roi_cache"]
    assert roi_cache.cache_retirement(tmp_path, SID)["at"] == ROW["at"]
    assert roi_cache.cache_retirement(tmp_path, "other") is None
    assert roi_cache.RoiCache.load(tmp_path, man, prof, "minimap") == (None, "cache_retired")
    assert roi_cache.RoiCache.load(tmp_path, man, prof, "killfeed") == (None, "cache_retired")
    assert roi_cache.channel_cache(tmp_path, man, prof, "ally_icon") == (None, "cache_retired")


def test_the_retirement_log_is_the_one_retire_writes():
    from reticle import retire
    assert roi_cache.CACHE_RETIREMENT_LOG == retire.RETIREMENT_LOG


def test_pixel_source_names_what_a_reread_can_read(tmp_path):
    assert roi_cache.pixel_source(tmp_path, _man(tmp_path, False))["state"] == "video"
    gone = _man(tmp_path, True)
    got = roi_cache.pixel_source(tmp_path, gone)
    assert got == {"state": "no_pixels", "why": "no pixels: source retired, no crop cache stored"}
    roi_cache.record_cache_retirement(tmp_path, ROW)
    got = roi_cache.pixel_source(tmp_path, gone)
    assert got == {"state": "no_pixels", "why": "no pixels: source and cache retired 2026-10-09"}
    d = roi_cache.cache_dir(tmp_path, "minimap")
    d.mkdir(parents=True)
    (d / f"{SID}.json").write_text("{}", encoding="utf-8")
    assert roi_cache.pixel_source(tmp_path, gone)["state"] == "cache"


def test_a_reader_refusing_an_absent_cache_says_how_or_that_none_can(tmp_path):
    roi_cache.record_cache_retirement(tmp_path, ROW)
    text = roi_cache.absent_text(tmp_path, _man(tmp_path, False), "minimap", "cache_retired")
    assert ("`reticle scan abcdef012345 --only roi_cache --cache-roi minimap --cache-hz 15 "
            "--cache-live`") in text
    text = roi_cache.absent_text(tmp_path, _man(tmp_path, True), "minimap", "cache_retired")
    assert "no pixels: source and cache retired" in text and "reticle scan" not in text


def test_trial_refuses_an_absent_cache_by_name(tmp_path):
    from reticle import trial
    roi_cache.record_cache_retirement(tmp_path, ROW)
    store = SimpleNamespace(root=tmp_path)
    with pytest.raises(SystemExit, match="no pixels: source and cache retired"):
        trial._clove_circle_timeline(store, _man(tmp_path, True), "all", 0.0)


def _decode():
    return [{"stream": "ally_icon", "channel": "ally_icon", "stored": "a", "current": "b",
             "trial": "ally_icon"},
            {"stream": "ping", "channel": "ping", "stored": "a", "current": "b", "trial": None},
            {"stream": "ult_line", "channel": "audio", "stored": "a", "current": "b",
             "trial": None}]


def _derived():
    return [{"stream": "self_icon", "how": "cache", "command": f"reticle self-icon {SID}",
             "stored": "a", "current": "b", "inputs_moved": []},
            {"stream": "death", "how": "storage", "command": f"reticle deaths {SID}",
             "stored": "a", "current": "b", "inputs_moved": []}]


def _render(sid, d, dv, r=(), rebuild=(), unbuilt=()):
    return plan.render({sid: {"decode": d, "derived": dv, "absent": [], "waived": [],
                              "declined": [], "unchecked": [], "held": [], "unrecorded": [],
                              "widget": None, "placement": {}, "caches": [],
                              "source_retired": list(r), "rebuild": list(rebuild),
                              "retired_caches": list(unbuilt)}})


def test_plan_proposes_no_reread_of_a_session_with_no_pixels(tmp_path):
    roi_cache.record_cache_retirement(tmp_path, ROW)
    gone = _man(tmp_path, True)
    pixels = roi_cache.pixel_source(tmp_path, gone)
    feeds = lambda ch: (None, "cache_retired")
    d, dv, w, c, r = plan.source_retired(SID, gone, _decode(), _derived(), None, [], feeds,
                                         pixels=pixels)
    assert [s["stream"] for s in d] == ["ult_line"] and [x["stream"] for x in dv] == ["death"]
    assert {x["stream"] for x in r} == {"ally_icon", "ping", "self_icon"}
    assert {x["reason"] for x in r} == {"no_pixels"}
    text = _render(SID, d, dv, r)
    assert "--from cache" not in text and "trial" not in text
    assert ("retired  reticle scan <sid> --only ally_icon   (ally_icon: no pixels: source and "
            "cache retired 2026-10-09; never proposed)") in text


def test_plan_rebuilds_the_cache_before_cache_fed_work_on_a_session_with_video(tmp_path):
    roi_cache.record_cache_retirement(tmp_path, ROW)
    man, store = _man(tmp_path, False), SimpleNamespace(root=tmp_path)
    d, dv = _decode(), _derived()
    rebuild = plan.cache_rebuild(store, man, d, dv)
    assert [(b["set"], b["reason"], b["feeds"]) for b in rebuild] == [
        ("minimap", "cache_retired", ["ally_icon", "self_icon"])]
    assert d[0]["rebuild"] == "minimap" and "rebuild" not in d[1]
    unbuilt = plan.retired_caches(store, man, {b["set"] for b in rebuild})
    assert [c["set"] for c in unbuilt] == ["hud", "killfeed_panel", "scoreboard"]
    text = _render(SID, d, dv, rebuild=rebuild, unbuilt=unbuilt).splitlines()
    first = next(i for i, ln in enumerate(text) if "--cache-roi minimap" in ln)
    trial_at = next(i for i, ln in enumerate(text) if "reticle trial" in ln)
    assert first < trial_at and text[first].startswith("decode   ")
    assert "after its crop cache rebuild above" in text[trial_at]
    assert not any("where one exists" in ln for ln in text)
    assert any(ln.startswith("absent   reticle scan <sid> --only roi_cache --cache-roi hud")
               for ln in text)


def test_every_cache_reading_derived_stream_names_its_sets():
    streams = [s["stream"] for s in plan.derived_streams() if s.get("how") == "cache"]
    streams += [s for s, how in plan._CACHE_READERS.items() if how == "cache"]
    for s in streams:
        assert set(plan.cache_stream_sets(s)) <= set(roi_cache.CACHE_SETS), s


def test_the_gated_ally_arms_are_declared():
    for s in ("ally_icon_gated", "ally_icon_gated2", "ally_icon_gated3_audit",
              "ally_icon_gated_audit"):
        assert plan.arm_reason(s), s
    assert plan.arm_reason("ally_icon") is None and plan.arm_reason("ally_icon_audit") is None


def test_status_names_a_session_with_no_pixels_beside_its_retired_video():
    why = "no pixels: source and cache retired 2026-10-09"
    base = {"map": "ascent", "minutes": 34.0, "n_rounds": None, "won": None, "lost": None,
            "planted": None, "kills": None, "deaths": None, "kd_basis": None,
            "kd_reason": None, "known": None, "verdict": None, "geometry": True,
            "cohort": None, "labels": {}, "hud": True, "video": "retired"}
    data = {"sessions": [{**base, "sid": "aaa", "pixels": {"state": "no_pixels", "why": why}},
                         {**base, "sid": "bbb", "pixels": {"state": "cache", "why": "x"}}],
            "hud_version": "h", "minimap_version": "m", "ping_version": "p",
            "round_outcome_version": "r", "roster_version": "o", "stored": {}}
    out = status_render(data)
    assert "Video retired, audio kept (source_retired: no decode): aaa, bbb" in out
    assert f"  No pixels: source and cache retired 2026-10-09; stored rows only, no reread: aaa" \
        in out
