# The pipeline as it runs today: a map for a pub/sub design

Status (2026-09-27): superseded. A snapshot of the serial pipeline at `a065949`; its seams and open
questions became the [design](PUBSUB_DESIGN.md)'s model and findings. Its line references into `cli.py`,
`usage.py` and `doctor.py` moved after `a065949`, and "No reader threads ... exist" (section 2) no longer
holds: `reticle/pipeline.py` feeds readers on their own threads.

Source reading at `a065949`; `reticle/` there matches master `3588d11`. I ran only
`reticle.architecture --graph`, `reticle ownership --check` and `reticle capabilities`; no unit
suite, scan or media. This map states what the code does, not how long it takes. Paths are relative
to `reticle/`. Rates are CLI defaults.

## 1. Stage graph

```text
media (manifest points at it; never copied)
 |- ingest: sample_frames 5 Hz -> PrimitiveExtractor -> l1/primitives -> segment -> l2/spans
 |- scan: ONE decode (sample_multi) or the ROI crop cache (run_cached), readers attached by rate:
 |    hud 2 Hz ............ l1/hud               killfeed_portrait 2 Hz .. events/killfeed_{portrait,weapon,name}
 |    minimap 15 Hz* ...... l1/minimap           ping 10 Hz* ............. events/ping (formal events)
 |    roster 2 Hz ......... l1/roster            scoreboard 2 Hz ......... events/scoreboard
 |    lineup 0.1 Hz ....... lineups/<sid>.json   ally_icon 2 Hz* ......... candidates -> decisions -> events/ally_icon
 |    minimap_dark 4 Hz* .. events/minimap_dark  combat_report 1 Hz ...... events/combat_report
 |    roi_cache (opt-in) .. roi_cache/<set>/<version>/<sid>.*          (* = active spans only)
 |- crop cache, no decode: tray -> events/tray_drop -> ability_shapes -> events/ability_shape
 |- seek decode: ability_light, refine --execute, board, overlay, fidelity-check, trial --from video
 '- storage only: rounds -> deaths -> combat-report identity, lifetimes; smokes; reliability;
      belief (unstored); audit; coach; ability-* corpus bundles
```

**Pixel stages.** Src: `video` decodes; `cache` reads stored crops; `seek` decodes windows.

| Stage | Entry | Reads | Writes: schema in one line | Stamp and provenance | Src | Command |
|---|---|---|---|---|---|---|
| Ingest | `cli.py:202` `cmd_ingest`; `primitives.py:59` | media at 5 Hz | `manifests/<sid>.json`; `l1/primitives`: frame_idx, t_ms, motion, luma, edge_density, per-ROI luma/std/edge/dhash/dchange | `extractor_version`, schema_version, session_id, content_key, source_profile per row and in metadata | video | `ingest VIDEO` |
| Segment | `segment.py:197`; `cli.py:283` | l1/primitives | `l2/spans`: span_idx, state off/idle/active, t_start/end_ms, duration, n_samples, mean_motion | `segmenter_version`; config JSON in metadata | store | `ingest`, `segment` |
| HUD | `hud_reader.py:67` `HudReader.feed` | scoreline, bottom HUD, killfeed ROIs; `masks/<sid>.kf.npy` | `l1/hud`: clock, scores, hp, shield, ammo, killfeed counts, slot masks, dividers, side masks, `*_reason` | `hud_version` + identity columns | video, cache | `scan`, `hud` |
| Killfeed views | `killfeed.py:1938` | killfeed ROI | three JSONL streams: portrait_observation (key `sid:frame:slot:role`) + second_life_observation; weapon_icon_observation; name_observation | three stamps (`killfeed_{portrait,weapon,name}_version`), `frames_from` | video, cache | `scan` (channel `hud`) |
| Minimap self | `cli.py:499` `_MinimapPass.feed` | minimap ROI; baked geometry | `l1/minimap`: self_x/y, n_allies, ally{i}_x/y, widget_drawn | `minimap_version` | video | `scan`, `minimap` |
| Ping | `ping.py:430`, finish `:447` | minimap ROI; floor | formal `entity_state`/`entity_deleted` pairs | `producer_version` = ping stamp | video | `scan` |
| Roster | `roster.py:321` | roster bars | `l1/roster`: alive_ally/enemy, detail_ally/enemy | `roster_version`, `roster_split_version` | video | `scan` |
| Scoreboard | `scoreboard.py:546` | whole frame | row_observation (key `sid:frame:display_row`): K/D/A, credits + reasons, portrait scores | `scoreboard_version`, `portrait_scorer` | video | `scan` |
| Lineup | `lineup.py:390`, finish `:396` | top bar, tray | `lineups/<sid>.json`: sides, tray votes, player, identity_claims, **agent_identity verdicts**, scores | `version` = lineup stamp | video | `scan` unless `--only`/`--no-lineup` |
| Ally icons | `minimap.py:1195` | minimap ROI; baked map | candidate revision -> decisions -> `ally_icon`: coverage, frame, icon (key `sid:frame:index`) | `ally_icon_version`, `candidate_revision` | video, cache | `scan` |
| Minimap dark | `minimap_dark.py:77` | minimap ROI; lighting reference | frame rows with packed grey_dark and occluded masks | `minimap_dark_version`, `lighting_version`, `geometry_key` | video | `scan` |
| Combat report | `combat_report.py:244` | whole frame | frame rows: header score, row reads | `combat_report_version`, template provenance | video | `scan` |
| ROI cache | `roi_cache.py:196`, finish `:212` | one `CACHE_SETS` entry | PNG blob + index, or FFV1 `.mkv` per rect; JSON record | `roi-cache` stamp, content_key, profile, rects, hz, spans | video | `scan --cache-roi SET` |
| Tray | `tray.py:68,149`; `cli.py:2711` | cached `hud_abilities` crops, hud, rounds, stalls | `tray_drop`: drops, player_cast, refusal reasons | `tray_version`, `step_s` | cache | `tray` |
| Ability shapes | `ability_shapes.py:268`; `cli.py:2761` | tray_drop, lineup verdict, cached minimap, l1/minimap | `ability_shape`: per-cast shape fits | `ability_shape_version`, `tray_version`, `minimap_version` | cache | `ability-shapes` |
| Ability light | `cli.py:2328` | one OpenCV seek per candidate instant | `ability_light`: raw_lit, raw_dark masks | `ability_light_version`, `lighting_version`, `geometry_key` | seek | `ability-light` |

**Storage-only stages.** None opens media.

| Stage | Entry | Reads | Writes | Stamp and provenance | Command |
|---|---|---|---|---|---|
| Rounds | `rounds.py:440`; `cli.py:1788` | l1/hud, second-life rows | `l2/rounds`: bounds, sources, outcome, sides, scores, K/D, plant, map | `round_version`; metadata records hud and killfeed_portrait stamps | `rounds` |
| Deaths | `adjudication/death.py:1772`; `cli.py:2488` | hud, roster, rounds, three killfeed streams, scoreboard, lineup, identity gallery, reliability table | `death`: summary with an `inputs` stamp map, death_verdict per `death_key`; `death_identity`: formal events | `death_adjudication_version` + `inputs` | `deaths` |
| Combat report rounds | `adjudication/combat_report.py:208`; `cli.py:2393` | combat_report, rounds, hud; then lineup, portraits, scoreboard, death | `combat_report_round`, `combat_report_rows`, `combat_report_identity` | own stamps; refuses a stale input | `combat-report` |
| Smokes | `adjudication/smokes.py:164`; `cli.py:2672` | minimap_dark, lighting reference | `smoke` tracks | smoke stamp; refuses stale input | `smokes` |
| Round entities | `round_entities.py:102`; `cli.py:1866` | ally_icon, hud, roster, death, lineup, portrait refs | `round_entity` | two stamps + input file hashes | `lifetimes` |
| Reliability | `adjudication/reliability.py:119`; `cli.py:2630` | every session's current deaths, labels, metrics | `reliability/<version>.json` | inputs: death stamp, sessions | `reliability` |
| Belief | `belief.py:131`; `cli.py:1955` | l1/minimap, rounds, geometry | nothing; prints | `BELIEF_VERSION` | `belief` |
| Audit | `reconciliation.py:27,125,154,379`; `cli.py:2020` | hud, roster, scoreboard | `analysis/reconciliation*.json` | literal audit stamp, table metadata | `audit` |
| Coaching | `coaching.py:379`; `cli.py:2081` | hud, roster, rounds, derived verdicts | `analysis/coaching/` | coach stamp; `artifacts.py` code hashes | `coach` |
| Ability corpus | `adjudication/{ability,phases,gallery,capture}.py`, `ability_timeline.py` | prototype-made candidates, series, casts, labels | `analysis/ability-*/runs/<rev>/` + `current.json` | `revisions.publish_revision` | `ability-*` |

Review stages decode for themselves and write outside the tables: `overlay` (`cli.py:1534`), `board`
(`cli.py:1351`), `refine --execute` (`cli.py:2896`), `fidelity-check`, and `trial` (`trial.py:137`),
which feeds one reader from `seek_at` or the cache and writes nothing. `acquisition.execute_plan`
(`acquisition.py:313`) is a second pass driver over `sample_windows` or `sample_multi`.

## 2. Execution model today

- **One process, one main thread, one frame at a time.** `cmd_scan` (`cli.py:799`) compares stamps
  to pick stale channels, builds the readers, chooses a source (`roi_cache.cache_for`,
  `roi_cache.py:118`), runs `passes.run` (`passes.py:152`) or `passes.run_cached` (`:185`), then
  publishes each reader's rows in turn (`cli.py:1029-1177`) and appends a usage record.
- **Frame selection.** `decode.sample_multi` (`decode.py:461`) grabs every frame from the file start
  to the last requested span end. It retrieves a frame only when some reader's `t_ms` lies in its
  current span and has reached its `next_t`, and yields `(frozenset(names), Sample)`. Each reader
  keeps `next_t = t_ms + 1000/hz`, reset at each span start. `None` spans mean the whole capture;
  `[]` means no work. `t_ms` is the stream PTS (NVDEC) or `CAP_PROP_POS_MSEC` (OpenCV), so rates
  survive variable frame rate.
- **Dispatch.** `passes.run` feeds each wanting reader synchronously in frozenset order
  (`passes.py:171`), which Python leaves unspecified. It fetches the next frame only after every
  reader returns, and calls each `finish` once after the loop (`:176`). Readers hold their rows in
  Python lists until the pass ends.
- **Decode.** `open_capture` (`decode.py:198`) prefers `_NvdecCapture` (`:40`): PyAV with
  `HWAccel("cuda")`, verified only for H.264 yuv420p limited range. A daemon thread decodes up to
  `_NVDEC_AHEAD` frames ahead; `retrieve()` downloads NV12 and converts it to BGR24 through swscale
  on the main thread. The `cv2.VideoCapture` fallback decodes inside `grab()` on the main thread.
  `RETICLE_DECODE` selects auto, cpu or nvdec. Every seeking caller (`seek_at`, `sample_windows`,
  `refine.iter_windows`, the killfeed mask calibration, `ability_light`) stays on OpenCV.
- **ROI crops.** Each reader slices its own ROI inside `feed`; no stage shares crops.
  `RoiCacheWriter` (`roi_cache.py:161`) rides the pass as a reader and stores lossless crops of one
  `CACHE_SETS` entry (`:45`): PNG blobs for `killfeed` and `hud`, FFV1 through one `ffmpeg`
  subprocess per rect for `minimap`. `RoiCache.samples` (`:286`) pastes crops into a black full
  frame, so readers run unchanged. A pass is cache-fed only when every reader declares `cache_set`,
  matches the cache's rate and fits its spans. Only `HudReader`, `KillfeedPortraitReader` and, when
  its box equals the profile ROI, `AllyIconReader` declare one; an unnarrowed scan adds the lineup
  reader, so only `scan --only ...` skips decode.
- **GPU and CPU.** The GPU runs NVDEC and, when cupy finds a device, the scoreboard's portrait
  correlation (`scoreboard.py:419`, `RETICLE_SCOREBOARD`). Everything else runs in numpy and OpenCV
  on the CPU. `passes._feed` (`passes.py:221`) sets OpenCV's process-wide thread count to one around
  readers that declare `cv_threads = 1` (`_MinimapPass`, `DarkRegionReader`).
- **Concurrency, complete list.** The NVDEC decode thread, the `ffmpeg` encoders and OpenCV's
  internal pool. No reader threads, process pools, async code or cross-frame batching exist.
- **Reader state between frames.** Order-dependent: `_MinimapPass` (last self position,
  `pick_self`), `PingReader` (the `Grouper`; resolves at `finish`), `RoiCacheWriter` (offsets,
  pipes), `PrimitiveExtractor` (previous thumbnail and dhashes). Order-free accumulation:
  `LineupReader` (score sums, tray votes). Pure per frame: `HudReader`, `KillfeedPortraitReader`,
  `RosterReader`, `ScoreboardReader`, `AllyIconReader`, `DarkRegionReader`, `CombatReportReader`.
- **Repeated work.** `HudReader` (via `read_killfeed`, `killfeed.py:2085`) and
  `KillfeedPortraitReader` (`killfeed.py:1942`) both run `analyse_killfeed` on the same 2 Hz frame.
  Four minimap readers each test `widget_drawn` (`cli.py:516`, `minimap.py:1199`,
  `minimap_dark.py:84`, `ping.py:435`).
- **Usage accounting** (`usage.py:41`). `timed_frames` (`:59`) times each `next()` on the frame
  iterator: the grabs since the last yield, the retrieve and conversion, and under NVDEC the queue
  wait; from the cache, crop decode and paste. That total is "source" time. `feed` times each reader
  call; `finish_ns` sums each finish; `pass_other_ns` is the remainder of the pass. `setup_ns`
  covers reader construction, including geometry loads and any killfeed mask calibration (40 OpenCV
  seeks, `passes.py:96`). `publish_ns` covers the writes, the ally-icon candidate adjudication and a
  second `finish` of the lineup and ping readers. All are wall-clock; only `scan` records.
- **Shared machine.** Two heavy jobs run here now: a minimap rescan on NVDEC and an audio agent on
  the GPU. Any baseline taken meanwhile competes with them for NVDEC, the GPU and the CPU, so its
  timings bound the cost from above. The audio gate (`docs/AUDIO_GATE.md`) is a prototype marked
  `wire: no`; `reticle/` does not import it, so it gates no pass today.

## 3. Storage

- **Layout** under `~/reticle-store` (`store.py:35`) or `--store`: `manifests/<sid>.json` (source
  path, content_key, size, fps, duration, tags); `l1/{primitives,hud,minimap,roster}/date=<ingest
  date>/session=<sid>/*.parquet`; `l2/{spans,rounds}/...` likewise; `events/<kind>/<sid>.jsonl`;
  `candidates/<producer>/<sid>/<rev>.json`; `decisions/.../<rev>__<rule>.json`;
  `lineups/<sid>.json`; `reliability/<version>.json`; `masks/<sid>.kf.npy` (unstamped);
  `geometry/<map>__<profile>.npz` (baked); `roi_cache/<set>/<version>/`;
  `analysis/<artifact>/runs/<rev>/` + `current.json`; `notes/{usage,metrics,predictions}.jsonl`.
- **Formats.** Parquet with zstd, stamps both in a column and in schema metadata. JSONL whose first
  row is a coverage or summary head carrying `<kind>_version`; formal events carry
  `producer_version` and `events_version`.
- **Staleness.** `plan.stale` (`plan.py:82`) compares each reader stream's stored stamp (parquet
  metadata, or the first JSONL row via `events_version`, `store.py:702`) with the code's. Of derived
  streams it knows only rounds and deaths, whose recorded input stamps let it predict what a rescan
  moves. Others check for themselves: smokes and combat-report rounds refuse a stale input, round
  entities hash input files, tray and shapes check `tray_version`. `scan` skips a channel at the
  current stamp unless `--force`. A code change that keeps its stamp is invisible to all of this.
- **Replacement.** Parquet goes straight onto the final path (`pq.write_table`); JSONL streams are
  rewritten whole with `open(path, "w")` (`store.py:663`); lineups and reliability use `write_text`.
  None is atomic, no table carries a run id, and a scan publishes streams one after another, so a
  failure mid-publish leaves mixed versions. Atomic and immutable: candidate and decision revisions
  (content-addressed, temp file then `os.replace`), analysis revisions (`revisions.py`, an atomic
  `current.json` pointer), and ROI cache files (`.part` then replace; the JSON record goes last and
  gates loading). Append-only: `usage.jsonl`, `metrics.jsonl`.
- **`usage.jsonl` record** (`scan-usage-1`, `usage.py:84`): run_id, recorded_at, kind `vod_scan`,
  status, session_id, content_key, profile, source (`video` or `cache:<version>`), bucket_upper_ns,
  setup_ns, pass_ns, publish_ns, source_calls {count, total_ns, max_ns, buckets}, readers {name:
  {hz, spans (count or null), feed {count, total_ns, max_ns, buckets}, finish_ns}}, pass_other_ns.

## 4. Seams for pub/sub

**A. Decoded frame or ROI tile -> reader.**
- Message: session_id, content_key, profile, frame_idx, t_ms, source (`video` or `cache:<version>`),
  the wanting readers, and the BGR frame or lossless crops with their rects. (session, frame_idx,
  t_ms) identifies a frame; decode is deterministic per content_key and transport.
- Ordering: per session; strictly increasing `t_ms` for stateful readers. Pure readers may run out
  of order if the writer sorts rows by key.
- The producer chooses frames, and the frames define a reader's output: `cache_for` refuses a rate
  mismatch, and phases reset at span starts. A subscriber that thins a faster topic must reproduce
  `next_t` exactly.
- Constraints: raw media is never copied, so a durable full-frame topic breaks the rule; a tile
  topic is the `roi_cache` case (fixed profile ROI, lossless, keyed by session, set and version).
  SESSION PIXELS DO NOT DEFINE THE MAP: no consumer may aggregate tiles into a map value; those come
  from `geometry` (`SessionContext.map_reference`, `passes.py:127`), and `doctor` SESSION_STATIC
  rejects a median over stacked frames. New readers join a shared pass. The scoreboard, combat
  report and lineup read the whole frame and need a declared ROI set before they can take tiles.

**B. Reader read -> L1 table.**
- Message: an observation row keyed by (session, stream, frame_idx or `observation_key`) with
  `t_ms`, the stream's stamp and reason fields; then an end-of-stream message carrying the coverage
  head (frames offered, refusals by reason, `frames_from`), which exists only after `finish`.
- Ordering and state: per (session, stream); the writer buffers to end of stream because tables are
  rewritten whole. The ally-icon writer also runs candidate -> decision -> accepted replay before it
  publishes. Row keys expose redelivery; the file write is not atomic.
- Constraints: `t_ms` is observation time, never processing time; one stamp per stream; a lost
  message becomes a refusal row with a reason, except where absence is the signal (`PingReader`
  omits widget-absent frames on purpose); never silently overwrite evidence.

**C. L1 -> adjudication.**
- Message: "stream X of session S is published at stamp V", not rows. Adjudicators read whole
  streams from storage.
- Ordering: per session, by dependency: rounds before deaths; deaths before combat-report identity
  and round entities; tray before shapes; minimap_dark before smokes. Reliability reads every
  session's deaths and feeds deaths back (`cli.py:2532`), a cycle across runs.
- State and idempotence: each records its input stamps and is pure over stored inputs, apart from
  that cycle. Deaths iterate to convergence and name clusters span the session, so row-level
  streaming does not apply.
- Constraints: adjudication reads L1, never frames (tray and shapes read cached crops, a middle
  case). Ask the owner (`reticle ownership`); every agent name comes from `adjudication.identity`; a
  claim resting on another verdict declares `depends_on`; source evidence precedes promotion.
- Leak: `LineupReader.finish` (`lineup.py:396`) calls the identity arbiter inside the scan. The
  lineup file stores `scores`, so the verdict could move downstream.

**D. Adjudication -> event.**
- Message: `events.Event` (`events.py:172`): event_id `sid:kind:t_ms:ordinal`, session_id, entity_id
  `owner:key`, observation `t_ms`, event_kind, source_channel, producer_version, evidence_refs,
  payload. Identity travels as `identity_claim` dicts (`adjudication/identity.py:118`) into
  `adjudicate_agent_identity` (`:1481`): resolved, disagreement or abstained.
- Idempotence and order: event_id and `death_key` (`death.py:496`) are deterministic, so consumers
  can upsert by key in any order; `write_events` validates every stream that holds `event_kind`
  rows.
- Constraints: an identity event built outside the arbiter is an OWNERSHIP ERROR; the owner that
  binds a witness supplies the entity key.

## 5. Tests and checks

- The suite runs with `python -m unittest discover -s tests -q`. I did not run it (forbidden while
  the two heavy jobs run), so its duration is unknown. Decode tests mock `cv2.VideoCapture`
  (`test_decode`, `test_refine`, `test_fidelity`, `test_hud_reader`). `test_decode_nvdec` encodes a
  short clip with `ffmpeg` and decodes it on NVDEC, skipping without either; `test_scoreboard_gpu`
  skips without cupy. `test_ability_glyph` and `test_weapon_attribution` read the real store; the
  rest build temporary ones. Pass-level tests: `test_passes_threads`, `test_usage`, `test_trial`,
  `test_plan`, `test_acquisition`.
- `doctor` (`doctor.py:971`) fails only on an ERROR. A new module must pass LAYER (placed in
  `architecture.toml`; imports its layer or lower, or a blessed `[[exception]]`; never
  `prototypes/`), OWNERSHIP (an entry whose owner docstring carries the owns token, or a line in
  `[infrastructure]`), UNWIRED and UNCALLED (reached from a `cmd_*`; `uncalled_debt.toml` only
  shrinks), DUPLICATE, SESSION_STATIC, QUOTED, DOMAIN, PROMOTE and HANDOFF.
- Placement: a transport that decides nothing belongs in the `orchestration` layer ("shared decode
  passes, which dispatch to readers and own no reading") and in `[infrastructure]`; any new decision
  needs an ownership entry.
- This session: `architecture --graph` printed the layering; `ownership --check` found no errors and
  one warning (nothing owns `ability-owner`); `capabilities` declares one validated reader property
  and withholds the rest.

## 6. Open questions

1. The `cmd_scan` docstring says spans come from the HUD table the scan writes, but `segment` reads
   ingest's `l1/primitives` (`cli.py:816`, `segment.py:197`). Is the docstring stale?
2. `CACHE_SETS["hud"]` holds the roster ROIs, yet `RosterReader` declares no `cache_set`
   (`roi_cache.py:49`, `roster.py:307`). Intended?
3. Can reader order within a frame matter? A grep found no reader writing into the shared frame,
   which proves nothing (`passes.py:171`).
4. The lineup and ping readers finish twice (`passes.py:176`, `cli.py:1090`, `cli.py:1155`).
   `passes.py` calls finish idempotent; I did not confirm that `Lineup.verdict` (`lineup.py:351`) is
   pure.
5. What order settles the reliability-deaths cycle across a corpus (`cli.py:2532`,
   `adjudication/reliability.py:178`)?
6. `lifetimes` rebuilds rounds from the HUD without the second-life split instead of reading
   `l2/rounds` (`cli.py:1915`). Deliberate?
7. Should smokes, combat-report rounds, round entities, tray drops and shapes join `plan.stale`
   (`plan.py:82`)?
8. `usage.jsonl` cannot split NVDEC queue wait from main-thread conversion (`usage.py:59`), and no
   other command records usage. How much of source time is conversion?
9. An unnarrowed scan adds the lineup reader, which has no `cache_set`, so a cache-fed pass needs
   `--only` (`cli.py:839`, `roi_cache.py:130`). Intended?
