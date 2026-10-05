"""`reticle retire` and the audio-source owner on a small synthetic capture.

The capture is made by ffmpeg from lavfi sources (a 64x64 test pattern and a
stereo AAC sine), so no store media is read; the tests skip without ffmpeg.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from reticle import audio_source as asrc
from reticle import plan, retire
from reticle.store import Store

SID = "feedfacecafe"


def _ffmpeg():
    try:
        from reticle.roi_cache import ffmpeg_path
        return ffmpeg_path()
    except SystemExit:
        return None


FF = _ffmpeg()
needs_ffmpeg = pytest.mark.skipif(FF is None, reason="no ffmpeg")


def _capture(path: Path, seconds: float = 3.0) -> Path:
    subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=64x64:rate=10:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:d={seconds}",
                    "-ac", "2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "96k", "-shortest", "-y", str(path)],
                   check=True, capture_output=True)
    return path


def _store(tmp_path: Path, video: Path, duration_ms: float = 3000.0) -> Store:
    store = Store(tmp_path / "store")
    man = {"schema_version": 1, "session_id": SID, "source_profile": "valorant-16x9",
           "ingested_at": "2026-10-05T00:00:00+00:00",
           "source": {"path": str(video), "filename": video.name, "size_bytes": video.stat().st_size,
                      "content_key": SID + "0" * 20, "session_id": SID, "width": 64,
                      "height": 64, "fps": 10.0, "frame_count": 30, "duration_ms": duration_ms}}
    store.manifest_path(SID).parent.mkdir(parents=True, exist_ok=True)
    store.manifest_path(SID).write_text(json.dumps(man), encoding="utf-8")
    return store


@needs_ffmpeg
def test_stream_copy_keeps_codec_timing_and_every_packet(tmp_path):
    video = _capture(tmp_path / "cap.mp4")
    meta = retire.extract_audio(video, tmp_path / "out" / f"{SID}.m4a")
    vmeta = retire.stream_meta(video)
    assert meta["codec"] == "aac" and meta["sample_rate"] == 48000 and meta["channels"] == 2
    for k in ("start_pts", "time_base", "duration_pts", "extradata_sha256"):
        assert meta[k] == vmeta[k], k
    assert meta["sha256"] == retire.sha256_file(tmp_path / "out" / f"{SID}.m4a")
    assert not (tmp_path / "out" / f"{SID}.m4a.part").exists()
    pk = retire.compare_lines(retire.framemd5(video), retire.framemd5(tmp_path / "out" / f"{SID}.m4a"))
    assert pk["compared"] > 100 and pk["differ"] == 0


@needs_ffmpeg
def test_alignment_refuses_a_truncated_file(tmp_path):
    video = _capture(tmp_path / "cap.mp4")
    short = tmp_path / "short.m4a"
    subprocess.run([FF, "-v", "error", "-i", str(video), "-map", "0:a:0", "-t", "2", "-c:a", "copy",
                    "-y", str(short)], check=True, capture_output=True)
    store = _store(tmp_path, video)
    man = store.read_manifest(SID)
    pk = retire.compare_lines(retire.framemd5(video), retire.framemd5(short))
    al = retire.check_alignment(man, retire.stream_meta(video), retire.stream_meta(short), {}, pk)
    assert not al["ok"]
    assert not al["duration"]["ok"] and not al["manifest_end"]["ok"] and not al["packets"]["ok"]
    full = tmp_path / "full.m4a"
    retire.extract_audio(video, full)
    pk = retire.compare_lines(retire.framemd5(video), retire.framemd5(full))
    assert retire.check_alignment(man, retire.stream_meta(video), retire.stream_meta(full), {}, pk)["ok"]


def _meta(start_s=0.0, duration_s=3.0):
    return {"codec": "aac", "profile": "LC", "sample_rate": 48000, "channels": 2,
            "layout": "stereo", "time_base": "1/48000", "extradata_sha256": "x",
            "start_s": start_s, "duration_s": duration_s, "video_start_s": 0.0}


def test_alignment_refuses_a_shifted_start_and_a_cache_outside_the_audio():
    man = {"source": {"fps": 10.0, "duration_ms": 3000.0}}
    pk = {"compared": 10, "differ": 0}
    caches = {"hud": {"rows": 3, "t_min_ms": 0.0, "t_max_ms": 2900.0, "grid_residual_ms": 0.0}}
    assert retire.check_alignment(man, _meta(), _meta(), caches, dict(pk))["ok"]
    shifted = retire.check_alignment(man, _meta(), _meta(start_s=0.5), caches, dict(pk))
    assert not shifted["ok"] and not shifted["start"]["ok"]
    assert shifted["start"]["diff_ms"] == pytest.approx(500.0)
    late = {"hud": {"rows": 3, "t_min_ms": 0.0, "t_max_ms": 3500.0, "grid_residual_ms": 0.0}}
    al = retire.check_alignment(man, _meta(), _meta(), late, dict(pk))
    assert not al["ok"] and not al["caches"]["hud"]["ok"]
    off = {"hud": {"rows": 3, "t_min_ms": 0.0, "t_max_ms": 2900.0, "grid_residual_ms": 3.0}}
    assert not retire.check_alignment(man, _meta(), _meta(), off, dict(pk))["ok"]


@needs_ffmpeg
def test_preconditions_refuse_by_name_and_commit_writes_nothing(tmp_path, monkeypatch):
    from reticle import dev_sample
    video = _capture(tmp_path / "cap.mp4")
    store = _store(tmp_path, video)
    root = store.root
    monkeypatch.setattr(retire, "plan_steps", lambda store, sid: ([
        {"step": "scan --only ping", "stream": "ping", "why": "scan decodes the capture"}], []))
    (root / "external" / "replays").mkdir(parents=True)
    (root / "external" / "replays" / "manifest.json").write_text(json.dumps(
        {"files": [{"file": "r.vrf", "capture_session": SID}]}), encoding="utf-8")
    labels = root / "labels" / "probe_set"
    labels.mkdir(parents=True)
    (labels / "index.json").write_text(json.dumps({"sessions": {SID: {}}}), encoding="utf-8")
    (labels / "ask.json").write_text(json.dumps({"items": [
        {"key": f"{SID}|1.0", "session": SID}, {"key": f"{SID}|2.0", "session": SID}]}),
        encoding="utf-8")
    (root / "labels" / "probe_set.jsonl").write_text(
        json.dumps({"key": f"{SID}|1.0", "session": SID, "answer": "x"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(dev_sample, "MATCHES", dev_sample.MATCHES + (SID,))
    monkeypatch.setattr(dev_sample, "HELD_OUT_WINDOWS", ((SID, 1.0, 2.0, "test"),))
    got = retire.preconditions(store, store.read_manifest(SID))
    reasons = [r["reason"] for r in got["refusals"]]
    assert reasons == ["plan_needs_video", "kept_replay", "dev_sample", "held_out_window",
                       "pending_labels"]
    pend = got["refusals"][-1]["detail"][0]
    assert pend["set"] == "probe_set" and pend["unanswered"] == 1
    assert got["labels"] == {"checked": ["probe_set"], "unchecked": []}
    before = store.manifest_path(SID).read_bytes()
    row = retire.retire(store, SID, commit=True)
    assert row["status"] == "refused" and row["reasons"] == reasons
    assert store.manifest_path(SID).read_bytes() == before
    assert not (root / "audio").exists() and not (root / retire.RETIREMENT_LOG).exists()


@needs_ffmpeg
def test_commit_marks_the_manifest_and_the_owner_then_names_the_retained_file(tmp_path, monkeypatch):
    video = _capture(tmp_path / "cap.mp4")
    store = _store(tmp_path, video)
    monkeypatch.setattr(retire, "plan_steps", lambda store, sid: ([], []))
    monkeypatch.setattr(retire, "reader_checks", lambda *a, **k: {"ok": True})
    man = store.read_manifest(SID)
    assert asrc.audio_source(man, store.root) == {"path": str(video), "kind": "video",
                                                  "reason": None}
    row = retire.retire(store, SID, commit=True, force_reason="test")
    assert row["status"] == "retired", row
    assert row["delete_command"] == f"Remove-Item -LiteralPath '{video}'"
    assert video.is_file()                       # retire never deletes
    man = store.read_manifest(SID)
    rec = man["video_retired"]
    final = asrc.retained_audio_path(store.root, SID)
    assert final.is_file() and rec["audio"]["sha256"] == retire.sha256_file(final)
    assert rec["audio"]["path"] == (asrc.RETAINED_AUDIO_DIR / final.name).as_posix()
    assert rec["audio"]["video_start_s"] == row["video_audio"]["video_start_s"] is not None
    assert asrc.video_state(man) == "retired_present"
    assert asrc.audio_source(man, store.root)["kind"] == "video"
    log = (store.root / retire.RETIREMENT_LOG).read_bytes()
    assert log.endswith(b"\r\n") and json.loads(log)["status"] == "retired"
    assert (store.root / rec["manifest_before"]).is_file()
    video.unlink()                               # the player deletes the capture
    assert asrc.video_state(man) == "retired"
    assert asrc.audio_source(man, store.root) == {"path": str(final), "kind": "retained_audio",
                                                  "reason": None}
    # A second commit refuses: the video is gone and the session retired.
    assert retire.retire(store, SID, commit=True, force_reason="again")["status"] == "refused"
    from reticle.doctor import ERROR, check_source
    assert check_source(store.root) == []
    # Every run compares the size; only --verbose reads the sha256.
    good = final.read_bytes()
    final.write_bytes(good[:-1] + b"\0")
    assert check_source(store.root) == []
    assert [sev for sev, _ in check_source(store.root, verbose=True)] == [ERROR]
    final.write_bytes(good[:-1])
    assert [sev for sev, _ in check_source(store.root)] == [ERROR]


def test_audio_source_reasons(tmp_path):
    man = {"session_id": SID, "source": {"path": str(tmp_path / "gone.mp4")}}
    assert asrc.audio_source(man, tmp_path) == {"path": None, "kind": None,
                                                "reason": "source_media_moved"}
    assert asrc.video_state(man) == "missing"
    rel = (asrc.RETAINED_AUDIO_DIR / f"{SID}.m4a").as_posix()
    man["video_retired"] = {"audio": {"path": rel, "bytes": 4}}
    assert asrc.audio_source(man, tmp_path)["reason"] == "retained_audio_missing"
    p = tmp_path / rel
    p.parent.mkdir(parents=True)
    p.write_bytes(b"abc")
    assert asrc.audio_source(man, tmp_path)["reason"] == "retained_audio_size_mismatch"
    p.write_bytes(b"abcd")
    assert asrc.audio_source(man, tmp_path)["kind"] == "retained_audio"


def test_plan_keeps_cache_fed_rereads_and_retires_what_needs_the_video(tmp_path):
    decode = [{"stream": "hud", "channel": "hud", "stored": "a", "current": "b", "trial": "hud"},
              {"stream": "ping", "channel": "ping", "stored": "a", "current": "b", "trial": None},
              {"stream": "ult_line", "channel": "audio", "stored": "a", "current": "b",
               "trial": None}]
    derived = [{"stream": "ability_light", "how": "decode", "command": f"reticle ability-light {SID}",
                "stored": "a", "current": "b", "inputs_moved": []},
               {"stream": "death", "how": "storage", "command": f"reticle deaths {SID}",
                "stored": "a", "current": "b", "inputs_moved": []}]
    caches = [{"set": "killfeed_panel", "reason": "missing", "witness": "killfeed_portrait",
               "command": f"reticle scan {SID} --only roi_cache --cache-roi killfeed_panel"}]
    feeds = lambda ch: ("hud", "the hud cache holds its ROIs") if ch == "hud" else (
        None, f"a {ch} reader reads outside any cached ROI set")
    present = {"session_id": SID, "source": {"path": __file__}}
    assert plan.source_retired(SID, present, decode, derived, None, caches, feeds)[4] == []
    gone = {"session_id": SID, "source": {"path": str(tmp_path / "gone.mp4")},
            "video_retired": {"at": "2026-10-05"}}
    d, dv, w, c, r = plan.source_retired(SID, gone, decode, derived,
                                         {"cache": {"command": "x", "reason": "stale_rects"}},
                                         caches, feeds)
    assert [(s["stream"], s.get("from_cache")) for s in d] == [("hud", "hud"), ("ult_line", None)]
    assert [s["stream"] for s in dv] == ["death"]
    assert w is None and c == []
    assert {x["stream"] for x in r} == {"ping", "ability_light", "roi_cache:minimap",
                                        "roi_cache:killfeed_panel"}
    assert all(x["reason"] == "source_retired" for x in r)
    text = plan.render({SID: {"decode": d, "derived": dv, "absent": [], "waived": [],
                              "declined": [], "unchecked": [], "held": [], "unrecorded": [],
                              "widget": w, "placement": {}, "caches": c, "source_retired": r}})
    assert "accept reticle scan <sid> --only hud --from cache" in text
    assert "retired  reticle scan <sid> --only ping" in text and "source_retired" in text
    assert "accept reticle ult-lines" in text


def test_channel_cache_names_no_set_for_a_channel_whose_readers_decode(tmp_path):
    from reticle.profiles import get_profile
    from reticle.roi_cache import SCAN_CHANNEL_SETS, channel_cache
    man = {"session_id": SID, "source_profile": "valorant-16x9",
           "source": {"path": "x", "content_key": "k", "width": 1920, "height": 1080}}
    prof = get_profile("valorant-16x9")
    assert channel_cache(tmp_path, man, prof, "scoreboard")[0] is None
    assert channel_cache(tmp_path, man, prof, "hud") == (None, "no_cache")
    assert set(SCAN_CHANNEL_SETS) == {"hud", "roster", "minimap", "ally_icon", "minimap_dark"}


def test_the_roster_declares_the_set_scan_channel_sets_names_for_it():
    from reticle.profiles import get_profile
    from reticle.roi_cache import SCAN_CHANNEL_SETS
    from reticle.roster import RosterReader
    r = RosterReader(get_profile("valorant-16x9"), (1920, 1080))
    assert (r.cache_set,) == SCAN_CHANNEL_SETS["roster"]


def _retired_store(tmp_path):
    store = Store(tmp_path / "store")
    man = {"session_id": "s", "ingested_at": "2026-09-07", "source_profile": "valorant-16x9",
           "source": {"path": str(tmp_path / "gone.mp4"), "filename": "gone.mp4",
                      "content_key": "k", "width": 1920, "height": 1080, "fps": 60,
                      "duration_ms": 1000},
           "video_retired": {"at": "2026-10-05T00:00:00+00:00"}}
    store.manifest_path("s").parent.mkdir(parents=True)
    store.manifest_path("s").write_text(json.dumps(man), encoding="utf-8")
    return store


def test_scan_on_a_retired_session_reads_the_crop_cache(tmp_path, monkeypatch):
    """The video is gone: the pass reads the crop cache, and refuses by name
    where no cache feeds it or a flag needs the video."""
    import contextlib
    import io
    from types import SimpleNamespace
    from reticle import cli, roi_cache
    store = _retired_store(tmp_path)
    monkeypatch.setattr("reticle.usage.code_revision", lambda root=None: {"sha": "0", "dirty": False})
    monkeypatch.setattr(cli, "_HudPass", lambda *a, **k: (_ for _ in ()).throw(AssertionError("hud")))
    asked = []

    def choose(root, manifest, profile, readers, mode, live_rounds):
        asked.append(mode)
        return SimpleNamespace(record={"version": "roi-cache-test", "roi": "hud"}), "hud cache", []

    def one_pass(ctx, readers, cache, progress, usage, *rest):
        assert cache is not None and [r.name for r in readers] == ["roster"]
        readers[0].rows = [dict(frame_idx=0, t_ms=0, alive_ally=5, alive_enemy=5,
                                detail_ally=[30.0] * 5, detail_enemy=[30.0] * 5)]
        return 1, None

    monkeypatch.setattr(roi_cache, "choose_source", choose)
    monkeypatch.setattr(cli, "_scan_pass", one_pass)
    monkeypatch.setattr(cli, "passes_run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("decoded a retired capture")))
    args = cli.build_parser().parse_args(["--store", str(store.root), "scan", "s", "--only", "roster"])
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert cli.cmd_scan(args) == 0
    assert asked == ["cache"] and "retired" in out.getvalue()
    assert store.has_roster("s", "2026-09-07")
    monkeypatch.setattr(roi_cache, "choose_source", lambda *a: (None, "no_cache", []))
    args = cli.build_parser().parse_args(["--store", str(store.root), "scan", "s", "--only",
                                          "roster", "--force"])
    with pytest.raises(SystemExit, match="source_retired_no_cache"), \
            contextlib.redirect_stdout(io.StringIO()):
        cli.cmd_scan(args)
    for flags in (["--from", "video"], ["--cache-roi", "hud"]):
        args = cli.build_parser().parse_args(["--store", str(store.root), "scan", "s",
                                              "--only", "roster", "--force"] + flags)
        with pytest.raises(SystemExit, match="source_retired"):
            cli.cmd_scan(args)


def test_commands_that_need_the_video_say_source_retired(tmp_path):
    from reticle import cli
    store = _retired_store(tmp_path)
    with pytest.raises(SystemExit, match="source_retired"):
        cli._capture_or_exit(store.read_manifest("s"))
    man = store.read_manifest("s")
    del man["video_retired"]
    with pytest.raises(SystemExit, match="source media has moved"):
        cli._capture_or_exit(man)


def test_label_coverage_names_the_sets_the_rule_cannot_read(tmp_path):
    labels = tmp_path / "labels"
    (labels / "indexed").mkdir(parents=True)
    (labels / "indexed" / "index.json").write_text("{}", encoding="utf-8")
    (labels / "loose").mkdir()
    (labels / "loose" / "items.jsonl").write_text(json.dumps({"key": f"{SID}|3.0"}) + "\n",
                                                  encoding="utf-8")
    (labels / "crops").mkdir()
    (labels / "crops" / f"{SID}_12.png").write_bytes(b"\x89PNG")
    (labels / "other").mkdir()
    (labels / "other" / "items.jsonl").write_text("{}\n", encoding="utf-8")
    got = retire.label_coverage(tmp_path, SID)
    assert got["checked"] == ["indexed"]
    assert [(u["set"], u["files"]) for u in got["unchecked"]] == [("crops", 1), ("loose", 1)]
