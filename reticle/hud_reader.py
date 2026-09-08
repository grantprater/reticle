"""Shared stage 02 HUD reader for hud, scan, and refinement flows.

The reader lives here so every decode path uses the same scoreline, bottom-HUD,
and killfeed extraction and writes identical rows.  Killfeed calibration is a
per-session constant: it is measured once and cached, while cached reads avoid
opening the source video.  This module only relocates that reader; detector and
version behavior remain unchanged.
"""

from __future__ import annotations

from pathlib import Path

from .killfeed import KillfeedRead, killfeed_roi, overlay_mask, read_killfeed
from .ocr import Templates, crop_gray, read_bottom_hud, read_scoreline, scoreline_roi


class HudReader:
    """Stage 02 HUD, fed one decoded frame at a time."""

    def __init__(self, store, manifest, profile, args):
        import cv2

        self.src = manifest["source"]
        self.profile = profile
        self.w, self.h = int(self.src["width"]), int(self.src["height"])
        self.templates = Templates.load(profile.name)
        self.roi = scoreline_roi(profile)
        self.kf_roi = killfeed_roi(profile)
        self.min_conf = args.min_confidence
        self.min_margin = args.min_margin
        self.rows: list[dict] = []
        self.name = "hud"
        self.hz = args.hz
        self.spans = None

        self.kf_mask = None
        if self.kf_roi is not None:
            self.kf_mask = store.read_kf_mask(manifest["session_id"])
            if self.kf_mask is None:
                cap = cv2.VideoCapture(str(Path(self.src["path"])))
                cal = []
                try:
                    step = max(1, int((self.src["duration_ms"] or 0) / 40))
                    for ms in range(0, int(self.src["duration_ms"] or 0), step):
                        cap.set(cv2.CAP_PROP_POS_MSEC, ms)
                        ok, fr = cap.read()
                        if ok:
                            cal.append(fr)
                finally:
                    cap.release()
                if cal:
                    self.kf_mask = overlay_mask(cal, self.kf_roi, self.w, self.h)
                    store.write_kf_mask(manifest["session_id"], self.kf_mask)
                    print(f"killfeed   overlay mask from {len(cal)} frames, "
                          f"{(~self.kf_mask).mean() * 100:.1f}% of the ROI masked out")
            else:
                print(f"killfeed   overlay mask cached, "
                      f"{(~self.kf_mask).mean() * 100:.1f}% of the ROI masked out")

    def feed(self, smp) -> None:
        w, h = self.w, self.h
        r = read_scoreline(crop_gray(smp.frame, self.roi, w, h), self.templates,
                           self.min_conf, self.min_margin)
        b = read_bottom_hud(smp.frame, self.profile, self.templates, w, h,
                            self.min_conf, self.min_margin)
        kf = (read_killfeed(smp.frame, self.kf_roi, w, h, self.kf_mask,
                            self.profile.name)
              if self.kf_roi is not None else KillfeedRead(0, (), False, False))
        self.rows.append({
            "frame_idx": smp.frame_idx, "t_ms": smp.t_ms,
            "clock_ms": r.clock_ms, "score_left": r.score_left,
            "score_right": r.score_right, "hp": b.hp, "shield": b.shield,
            "ammo_mag": b.ammo_mag, "ammo_reserve": b.ammo_reserve,
            "kf_entries": kf.entries, "kf_player_kill": kf.player_kill,
            "kf_player_death": kf.player_death, "kf_entry_mask": kf.entry_mask,
            "kf_kill_mask": kf.kill_mask, "kf_death_mask": kf.death_mask,
            "kf_unattributed": kf.unattributed, "kf_unparsed": kf.unparsed,
            "kf_unparsed_reason": kf.unparsed_reason, "clock_reason": r.clock_reason,
            "score_left_reason": r.score_left_reason, "score_right_reason": r.score_right_reason,
            "kf_ally_mask": kf.ally_mask, "kf_enemy_mask": kf.enemy_mask,
            "kf_entry_wx": kf.entry_dividers, "kf_kill_wx": kf.kill_dividers,
            "kf_death_wx": kf.death_dividers, "confidence": r.confidence,
            "bottom_confidence": b.confidence, "n_glyphs": r.n_glyphs,
        })
