# Reticle — ingestion

Stages 00–02 of the pipeline in the design doc: fingerprint a capture, decode it
into L1 primitives, gate it into spans, read the scoreline off the HUD, and
write the whole thing to a Parquet event store you can query with DuckDB.

Stage 02 is partial. The scoreline extractor (round clock, both team scores) is
built; ammo, HP, credits, killfeed template matching and minimap position
tracking are not. Nothing above that exists — no event proposal, no VLM.

## Setup

```
cd C:\Users\grant\reticle
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run everything as `.\.venv\Scripts\python.exe -m reticle <command>`.

## Try it without a VOD

```
python -m reticle synth --out .\fixtures\synthetic_capture
python -m reticle --store .\teststore ingest .\fixtures\synthetic_capture.mp4
python -m reticle --store .\teststore inspect --spans 10
```

`synth` renders a clip that carries the *signal structure* the segmenter keys
on — a busy top-left panel, high-contrast corner chrome, a scene that moves or
holds. It exists to prove the plumbing, not to stand in for Valorant. Do not
calibrate thresholds against it.

## With a real VOD

**1 — Check the ROI boxes.** `valorant-16x9` was measured against real
1920x1080 footage on 2026-08-23. Re-check after any HUD restyle, resolution
change, or HUD layout-setting change.

```
python -m reticle probe "D:\vods\match.mp4" --n 8
```

That writes annotated frames. Open them. If `minimap` isn't on the minimap,
edit the fractions in `profiles.py` and run it again. Everything downstream is
wrong until this is right.

Two things worth checking on a new capture before anything else:

* **Is the frame cropped?** The crosshair must sit at the centre of the frame
  (960, 540 at 1080p). If it sits elsewhere, OBS is compositing a larger render
  onto a smaller canvas at 1:1 and part of the HUD is not in the file at all.
  Fix the OBS scaling; `valorant-16x9-crop75` exists only to salvage captures
  already recorded that way.
* **What minimap settings were used?** Rotation, per-side orientation and
  "keep player centered" all change what the minimap ROI contains, and only
  fixed + always_same + uncentered gives a constant minimap -> world transform.
  `probe` prints the profile's assumption; override per capture with
  `ingest --minimap-mode "fixed/per_side/uncentered"`, recorded in the manifest.

**2 — Ingest.**

```
python -m reticle ingest "D:\vods\match.mp4"
```

Decodes at 5 Hz by default and writes L1 + spans. Re-running the same file is a
cache hit — pass `--force` to re-decode. Use `--max-frames 2000` for a quick
look at a long capture before committing to a full pass.

**3 — Calibrate the thresholds.**

```
python -m reticle segment --all --show-signals
```

This recomputes spans **from stored L1 without touching the video** — the point
of the L0/L1 split in §7. It's milliseconds, so you can sweep thresholds freely:

```
python -m reticle segment --minimap-dchange 4 --active-motion 0.02
```

`--show-signals` prints percentiles for each column the classifier thresholds
on. You're looking for a bimodal split; put the threshold in the valley.

**4 — Read the HUD (stage 02).**

```
python -m reticle hud
python -m reticle verify
```

`hud` re-opens the source the manifest points at and reads the top-centre
scoreline off each sampled frame, writing L1 HUD reads. It needs pixels, so
unlike `segment` it cannot recompute from stored L1 — it is the one stage that
forces a re-decode.

Nothing here is a model. The HUD is structured data rendered as pixels, so it is
parsed against templated regions: threshold, connected components, filter by
glyph geometry, normalise to a fixed grid, nearest labelled template. Fields the
extractor cannot read stay **null** rather than being guessed, and every value is
range-checked before it is returned — a clock of 7:41 is a misread, not a fact.

`verify` checks the result against domain invariants — the clock tracks real
time, scores never fall, resets coincide with a score change. No labels are
needed for any of that, and a violation localises the extraction fault in time.

**Digit templates.** These are mined from your own footage rather than a font
file, because what matters is how this build renders at this resolution:

```
python -m reticle glyphs "D:\vods\match.mp4"          # writes a montage
python -m reticle glyphs "D:\vods\match.mp4" --label "0131..."
```

Open the montage, read the clusters left to right, and pass one character per
cluster. The result is committed as a small `.npz` keyed by profile name.
Templates ship for `valorant-16x9` only — `valorant-16x9-crop75` stores a
2560x1440 render at 1:1, so its glyphs are a third larger and both the templates
and the geometry constants in `ocr.py` would need re-deriving.

**5 — Check the result against reality.**

```
python -m reticle frames --every 30
```

Dumps frames named with the label the baseline assigned. Skim them. The ones
labelled wrong are your first correction set, and that's what a trained stage-01
classifier eventually gets fitted on.

## Querying

```
python -m reticle sql                          # list views and columns
python -m reticle sql "SELECT state, round(sum(duration_ms)/1000,1) secs
                       FROM spans GROUP BY state"
```

Views `primitives` (L1) and `spans` (L2) over the whole store.

## What the segmenter actually claims

The design doc calls for a small *trained* classifier over buy / in-round /
post-round / menu / spectate. There's no labelled data yet, so this ships a
rule-based baseline making a deliberately coarser claim:

| state | meaning |
|---|---|
| `off` | no HUD — loading, agent select, alt-tabbed |
| `idle` | HUD present, scene static — death cam, mid-match menu, AFK |
| `active` | HUD present, scene moving |

It keys on three signals: sustained perceptual change in the minimap ROI (a
live minimap redraws constantly), edge density in the bottom-corner HUD ROIs,
and whole-frame motion. All three are thresholded, smoothed with a rolling
median, and short spans get absorbed into their neighbours.

On the synthetic fixture it recovers the script exactly. On Valorant it is
unverified.

## Store layout

```
<store>/manifests/<session>.json                               L0 pointer
<store>/l1/primitives/date=<d>/session=<s>/primitives.parquet   L1
<store>/l2/spans/date=<d>/session=<s>/spans.parquet             L2
```

Default store is `~/reticle-store`; override with `--store`.

Conventions from §7 that are actually enforced:

- **Raw media is never copied.** The manifest points at where the file lives.
  Move the file and `frames` will tell you it's gone.
- **Wide and denormalised** — identity and version columns sit inline on every
  row rather than in a join table.
- **Versioned** — every row carries `extractor_version`, `schema_version`,
  `source_profile`, `session_id`, `content_key`. Bump `EXTRACTOR_VERSION` in
  `version.py` and the next ingest re-decodes; bump `SEGMENTER_VERSION` and only
  spans recompute.
- **Idempotent** — sessions are keyed by a sampled content digest, so identity
  survives a rename and a re-run costs nothing.

## Known gaps

- ROI fractions are guesses until `probe` says otherwise.
- Segmentation is a baseline, not the trained classifier the doc specifies.
- `content_key` is a sampled digest (size + head/mid/tail), not a full hash. It
  identifies files; it does not detect corruption.
- 16:9 only. Other aspect ratios need their own profile.
- Single-file, single-process. No queue, no parallelism — at a few games that
  isn't the bottleneck; decode is.

## Cost check

The doc's stage-01 rule is that the expensive layer should see well under 1% of
frames. `inspect` prints the funnel with your capture's real numbers so you can
see what fraction of a match actually survives gating before anything expensive
would run.
