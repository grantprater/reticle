"""Render one original source frame for the lane B review bundle."""
import argparse
import json
from pathlib import Path

import cv2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    ap.add_argument("t_ms", type=float)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    source = json.loads(args.manifest.read_text())["source"]["path"]
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"source unavailable: {source}")
    cap.set(cv2.CAP_PROP_POS_MSEC, args.t_ms)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"source frame unavailable: {args.t_ms}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), frame):
        raise RuntimeError(f"could not write: {args.output}")


if __name__ == "__main__":
    main()
