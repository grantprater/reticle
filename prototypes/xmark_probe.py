"""First look: what does the blue ally death X actually look like in pixels?

    .\\.venv\\Scripts\\python.exe prototypes\\xmark_probe.py <session>

Purely exploratory -- no detector yet. Pulls the minimap crop just after every
verified ALLY (non-self) death, upscales it, and dumps it plus raw pixel stats
so the colour/shape signature can be read off real footage before writing any
threshold. Same reasoning as every other minimap module here: measure first.

Ally-teammate deaths are derived, not stored directly. `kf_ally_mask` marks any
entry whose *victim* is on my team (self included); `kf_death_mask` marks only
the *local player's* own death entries. Ally-teammate deaths = ally_mask tracks
whose t_first does not coincide with a player-death track, which is the same
kind of derivation `player_events` does for the player's own kills/deaths, just
not filtered down to self.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle.checks import track_entries                          # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402

STORE = Path.home() / "reticle-store"
COINCIDE_MS = 500.0  # an ally-mask track this close to a self-death is the self-death


def main() -> int:
    sid = sys.argv[1]
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    w, h = int(src["width"]), int(src["height"])
    x0, y0, x1, y1 = next(r for r in prof.rois if r.name == "minimap").pixels(w, h)

    hud = pq.read_table(next((STORE / "l1" / "hud").rglob(f"session={sid}/hud.parquet")))
    t = hud.column("t_ms").to_pylist()
    dividers = hud.column("kf_entry_wx").to_pylist() if "kf_entry_wx" in hud.column_names else None
    death_dividers = hud.column("kf_death_wx").to_pylist() if "kf_death_wx" in hud.column_names else None

    self_deaths = [a for a in track_entries(t, hud.column("kf_death_mask").to_pylist(), death_dividers)
                   if a["counted"]]
    ally_tracks = [a for a in track_entries(t, hud.column("kf_ally_mask").to_pylist(), dividers)
                   if a["counted"]]

    def is_self(a):
        return any(abs(a["t_first"] - s["t_first"]) <= COINCIDE_MS for s in self_deaths)

    teammate_deaths = [a for a in ally_tracks if not is_self(a)]
    print(f"{len(self_deaths)} self deaths, {len(ally_tracks)} ally-mask tracks, "
          f"{len(teammate_deaths)} look like teammate (non-self) deaths")
    for a in teammate_deaths:
        print(f"  t={a['t_first']/1000:7.1f}s  n_obs={a['n_obs']}")

    out_dir = Path.cwd() / f"xmark_{sid}"
    out_dir.mkdir(exist_ok=True)
    cap = cv2.VideoCapture(str(src["path"]))
    fps = float(src["fps"])
    for a in teammate_deaths:
        for dt_s, tag in ((0.5, "p0.5"), (1.5, "p1.5"), (3.0, "p3.0")):
            tm = a["t_first"] + dt_s * 1000.0
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(tm / 1000.0 * fps)))
            ok, fr = cap.read()
            if not ok:
                continue
            crop = fr[y0:y1, x0:x1]
            up = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
            name = f"t{a['t_first']/1000:.0f}_{tag}.png"
            cv2.imwrite(str(out_dir / name), up)
    cap.release()
    print(f"\nwrote crops to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
