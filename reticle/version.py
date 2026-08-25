"""Version stamps written into every stored row.

Per the design doc (SS7): every row carries the versions that produced it, so
rows can be attributed to a definition and selectively recomputed later.

Bump EXTRACTOR_VERSION when the meaning of any primitive column changes --
that invalidates cached L1 and forces a re-decode. Bump SEGMENTER_VERSION for
changes to span logic only; that recomputes from stored L1 without touching
video.
"""

SCHEMA_VERSION = 1
EXTRACTOR_VERSION = "l1-0.1.0"
SEGMENTER_VERSION = "seg-0.2.0"
# Stage 02 deterministic HUD extraction. Bump when glyph segmentation, the
# template set, or field parsing changes -- that invalidates stored HUD reads
# and forces a re-decode, since this stage needs pixels.
HUD_VERSION = "hud-0.8.1"
