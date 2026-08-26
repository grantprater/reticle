"""Assert the refactored detector is bit-identical to the shipped one.

    .\\.venv\\Scripts\\python.exe prototypes\\enemy_equiv_check.py [session] [n]

`enemy_features.py` splits `enemy_detect_eval.detect()` into `propose()` +
`gate()`. Everything downstream is built on that split, so it has to be shown to
change nothing BEFORE anything is built on it -- and shown by running it, not by
reading it.

This is the "re-run the thing and confirm a known number comes back" convention,
in its strongest form: not a summary statistic that could coincide, but the full
box list per frame, compared element by element. A parse check would have said
this file was fine after deleting every function in it.

`enemy_detect_eval.py` reads `sys.argv` and loads a session at import, so it
cannot be imported as a library. Rather than modify the reference -- the one file
that must stay untouched for this comparison to mean anything -- it is executed
with a patched argv and `detect` lifted out of its namespace.
"""
import runpy
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
import enemy_features as ef                                    # noqa: E402

SID = sys.argv[1] if len(sys.argv) > 1 else "9acf02f98283"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 40


def main() -> int:
    # The reference reads its OPERATING POINT from argv -- argv[2] is `THR`, not
    # a frame count. Handing it this script's argv silently ran the reference at
    # thr=40 against the shipped thr=25 and reported 22 mismatches that were
    # entirely this bug. Give it exactly the session and nothing else, so it
    # takes every shipped default.
    saved, sys.argv = sys.argv, [sys.argv[0], SID]
    try:
        ns = runpy.run_path(str(Path(__file__).parent / "enemy_detect_eval.py"),
                            run_name="_reference")
    finally:
        sys.argv = saved
    ref_detect, rows, src, fps = ns["detect"], ns["rows"], ns["src"], ns["fps"]

    # Prefer frames that carry labels -- a detector agreeing on empty sky is not
    # evidence. Sorted so the sample is reproducible rather than dict-ordered.
    marked = [r for r in rows if r.get("marks")]
    plain = [r for r in rows if not r.get("marks")]
    marked.sort(key=lambda r: r["t_ms"])
    plain.sort(key=lambda r: r["t_ms"])
    sample = (marked[:N // 2] + plain[:N - len(marked[:N // 2])])[:N]

    cap = cv2.VideoCapture(str(src["path"]))
    n_frames = n_boxes = 0
    bad = []
    for r in sample:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(r["t_ms"] / 1000.0 * fps)))
        ok, fr = cap.read()
        if not ok:
            continue
        a = ref_detect(fr)
        b = ef.detect(fr, ef.SHIPPED)
        n_frames += 1
        n_boxes += len(a)
        if a != b:
            bad.append((r["t_ms"], a, b))
    cap.release()

    print(f"{SID}: {n_frames} frames, {n_boxes} reference boxes, "
          f"{len(marked)} labelled frames available")
    if bad:
        print(f"MISMATCH in {len(bad)} frames -- the refactor is NOT equivalent")
        for t, a, b in bad[:5]:
            print(f"  t={t}ms\n    ref {a}\n    new {b}")
        return 1
    if n_boxes == 0:
        print("VACUOUS: reference found no boxes at all, so nothing was compared")
        return 1
    print("identical on every frame")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
