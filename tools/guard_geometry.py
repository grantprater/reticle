r"""Refuse to let the ART-derived map geometry be quietly replaced again.

    .\.venv\Scripts\python.exe tools\guard_geometry.py            # check now
    ... | .\.venv\Scripts\python.exe tools\guard_geometry.py --hook

**Why this exists, in the player's words:** *"how do I set up a hook to stop
you from ever intentionally destroying that portion of the code again? I simply
do not trust you to act as you say."* Fair. `BACKLOG.md` recorded the promotion
-- geometry from the official art, photometry from the capture -- on
2026-09-06 with the trigger *"the next time a session's geometry is built"*.
On 2026-09-08 all twelve geometries were rebuilt and the trigger was walked
past; the derived rule stayed in the pipeline and the afternoon went on
patching its false positives one at a time (the location banner, the widget
rim, the close skirt, the barrier doorways) while the exact answer sat unused
in the same npz.

A convention in prose did not hold. This is the same rule as code that runs
whether or not anybody remembers it, which is the standard every other
load-bearing rule in this repo is held to.

**What it asserts** -- each line is a thing that was true and could stop being:

1.  `minimap.art_floor` and `geometry.footprint` exist. They are the promotion.
2.  The round pipeline RESOLVES its floor and slab from the art, and records
    `floor_source` in provenance. A silent fallback is the failure mode.
3.  Geometry is keyed per (map, profile). No npz in the store may be named
    after a session -- that regression has been paid for once already, and the
    player has raised it more than once since.
4.  Every baked geometry whose art places well enough carries `shade_kind`,
    so `footprint` returns a mask rather than `None`.

It does NOT assert that the art is better -- `prototypes/floor_mask_eval.py`
is the referee for that, and it is where the 92.7% / 94.2% against 78.8% /
77.9% is scored. This only asserts the wiring is still there.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = Path.home() / "reticle-store"


#: Editing any of these can break the promotion, so the hook re-checks after
#: one is touched. Everything else is left alone: a guard that fires on every
#: edit in the repo is a guard that gets turned off.
GUARDED = ("reticle/minimap.py", "reticle/geometry.py",
           "prototypes/full_round_entities.py", "prototypes/map_shade.py",
           "prototypes/wiki_map.py", "prototypes/minimap_geometry.py")


def failures() -> list[str]:
    bad = []
    minimap = (ROOT / "reticle/minimap.py").read_text(encoding="utf-8")
    geometry = (ROOT / "reticle/geometry.py").read_text(encoding="utf-8")
    rounds = (ROOT / "prototypes/full_round_entities.py").read_text(encoding="utf-8")

    if not re.search(r"^def art_floor\(", minimap, re.M):
        bad.append("reticle/minimap.py has no `art_floor` -- the art footprint "
                   "is how the map's geometry is read. See BACKLOG.md, "
                   "'Promote the WIKI MAP into minimap_geometry'.")
    if not re.search(r"^def footprint\(", geometry, re.M):
        bad.append("reticle/geometry.py has no `footprint` -- that is the only "
                   "accessor that reaches the art from a session id.")
    if "art_floor(" not in rounds:
        bad.append("prototypes/full_round_entities.py no longer calls "
                   "`art_floor`: the round pipeline has gone back to deriving "
                   "the map from gameplay frames.")
    if "floor_source" not in rounds:
        bad.append("prototypes/full_round_entities.py no longer records "
                   "`floor_source` in provenance, so a fallback to the derived "
                   "rule would be silent. That is the failure mode this "
                   "guards; it is not optional.")

    geo_dir = STORE / "geometry"
    if geo_dir.is_dir():
        session_like = [p.name for p in geo_dir.glob("*.npz")
                        if "__" not in p.stem]
        if session_like:
            bad.append("geometry is keyed per (map, profile) and these are not: "
                       + ", ".join(sorted(session_like)[:6]))
        try:
            import numpy as np
            for p in sorted(geo_dir.glob("*.npz")):
                with np.load(p, allow_pickle=False) as z:
                    fit = (float(z["shade_fit"][4])
                           if "shade_fit" in z.files else 0.0)
                    if fit >= 0.80 and "shade_kind" not in z.files:
                        bad.append(f"{p.stem} places at IoU {fit:.3f} but "
                                   f"carries no `shade_kind` -- run "
                                   f"prototypes/map_shade.py build --all")
        except ImportError:                                # pragma: no cover
            pass
    return bad


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--hook" in argv:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except Exception:                                  # noqa: BLE001
            payload = {}
        edited = str((payload.get("tool_input") or {}).get("file_path", "")
                     or (payload.get("tool_response") or {}).get("filePath", ""))
        touched = edited.replace("\\", "/")
        if not any(touched.endswith(g) for g in GUARDED):
            return 0

    bad = failures()
    if not bad:
        if "--hook" not in argv:
            print("art-derived geometry: wiring intact")
        return 0
    print("GEOMETRY GUARD FAILED -- the art-derived map path is the settled "
          "design (BACKLOG.md, 2026-09-06). Restore it before continuing:",
          file=sys.stderr)
    for b in bad:
        print(f"  * {b}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
