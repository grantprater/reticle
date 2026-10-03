# Killfeed queue prior

A plan, proposed 2026-10-02. The killfeed reader parses every band of every
sample from scratch, and `checks.track_entries` links entries afterwards slot
by slot. At bdfdcf009dba 674.0 s an entry with an unread divider took another
entry's misread divider and jumped two slots (patched in `be57714`). This plan
makes the reader follow the stack as a queue: carry its state, predict the
next sample, verify the prediction cheaply, and parse in full only on surprise
or on a fixed audit cadence, as `AGENTS.md` ("Continue the prior; widen the
search only on surprise") and [PRIOR_DRIVEN_READERS.md](PRIOR_DRIVEN_READERS.md)
item 6 ask. It builds nothing.

The queue rests on [domain:killfeed/stack-order], [domain:killfeed/stack-queue],
[domain:killfeed/entry-lifetime], [domain:killfeed/slot-pitch],
[domain:killfeed/round-clear], [domain:killfeed/post-round-kill-persists] and
[domain:killfeed/subpixel-placement]; this document cites them and does not
restate them.

Measurements below come from the stored bands of
`prototypes/killfeed_queue_stats.py` (2 Hz crop cache, no decode) on the eight
acceptance sessions, by a scratch script recorded as run
`killfeed-prior-20261002`. Its instrument tracks entries by appearance and
matches
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#instrument_matched=1179]
of [metric:killfeed_prior/design@eight~killfeed-prior-20261002#riot_kills=1313]
Riot kills, where master's reader matches 1290: its misses are the
instrument's own, so every loss figure below is an upper bound.

## 1. Ownership

`reticle ownership` answers, per question:

- *Did a kill appear, and did it involve the player* (`killfeed-event`, owner
  `killfeed`). **Changes.** The reader gains the follow: state, prediction,
  verification, widening, audit. Its prior comes only from its own earlier
  samples and the domain facts, never from another stream (guard 7 of
  PRIOR_DRIVEN_READERS.md), so a rounds or roster change never restales it.
- *Which band in this sample continues which entry.* No owner exists; the
  walk in `checks.track_entries` answers it today under `hud-invariant`, whose
  question is whether stored HUD reads contradict each other. Add an
  ownership entry `killfeed-entry-follow`, owner `killfeed`, producing a
  per-slot entry id from the reader's verified prediction; `not_for`: counting
  kills, lifecycle bars, onset inference, names.
- *Do the stored HUD reads contradict each other* (`hud-invariant`, owner
  `checks`). **Stays the owner of the persistence bars and counted tracks.**
  Once the reader's entry ids are stored, `track_entries` takes them as its
  linkage where present and keeps its divider-and-slot walk as the prior-free
  comparator; a disagreement is stored, never resolved silently. Sessions
  stamped before the follow keep the walk.
- *Which agent died at this killfeed time* (`death-victim`, owner
  `adjudication.death`). **Unchanged rule.** It still takes the time from the
  feed. An onset inferred from an expiry (section 6) is an alternative it may
  hold beside the observed first sample, declaring `rests_on`
  `domain:killfeed/entry-lifetime` and `domain:killfeed/stack-queue`; it never
  replaces a stored observation time.
- *What the portraits, weapon slot and names look like* (`killfeed-portrait`,
  `killfeed-weapon-descriptor`, `killfeed-name-descriptor`, owner `killfeed`).
  **Change only in which views they read** (section 7), and each row gains
  `entry_id` and `scope`.
- *Which named agent* (`agent-identity`, owner `adjudication.identity`).
  **Unchanged.** Every name still goes through the arbiter. A view the prior
  placed but did not verify yields no descriptor, so no claim; a descriptor is
  never copied from one view to another, so accumulation over an entry's life
  counts only views read.

## 2. State and prediction

**State per entry:** id; first content sample and whether a blank slide-in
plate preceded it; first-seen slot; rest top at sub-pixel; plate extent;
seam column and colours; divider column; victim side; a reference template
(soft whiteness and soft plate colour over the entry's columns, cut at its
first full parse); last verified sample; status (`resting`, `held`,
`sliding`, `occluded`, `overdue`).

**State per stack:** the ordered entries; the time of the last expiry (the
hold); and whether the last sample was a hole (no widget crop, a stall gap, a
round wipe), which empties the state so the next sample parses in full
(guard 6).

**Prediction for the next sample:**

- *Expiry.* An entry is due once its content has shown the lifetime
  [domain:killfeed/entry-lifetime]. Within half a sample of due, present and
  gone are both predicted; later, presence is an `overdue` surprise. The
  reader knows no round state (guard 7), so a post-decision kill that outlives
  its timer [domain:killfeed/post-round-kill-persists] is stored as overdue for
  adjudication to explain, not suppressed.
- *Hold and rise.* After an expiry the entries below are predicted at two
  hypotheses, held and risen by the number of vacated slots
  [domain:killfeed/stack-queue]; the verify picks one. A mid-slide sample
  (rare per the same fact) is covered by searching the verify score over the
  whole interval between the two rests.
- *Place.* Rests from [domain:killfeed/slot-pitch] scaled by `KillfeedScale`;
  the self entry's taller frame [domain:killfeed/self-yellow-frame]. The
  verify fits the top to sub-pixel by a parabola through the score peak
  [domain:killfeed/subpixel-placement]. `killfeed.PITCH` (40) and the measured
  39 px pitch must agree first: step 1 uses the measured pitch.
- *Arrival.* One probe of the first empty slot below the stack, below the hold
  gap if the stack is holding. Several arrivals in one sample fill
  consecutive slots.
- *Round wipe.* [domain:killfeed/round-clear]: all entries vanish together
  under the wipe; they end `cleared`, not expired, and the state resets.

The queue predicts the arrival slot well: of matched arrivals,
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#arrivals_at_queue_slot=1095]
land in the slot below the stack and
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#arrivals_at_hold_gap=27]
below a hold gap
([metric:killfeed_prior/derived@eight~killfeed-prior-20261002#queue_slot_arrival_share=0.952]).
Of the rest
([metric:killfeed_prior/design@eight~killfeed-prior-20261002#arrivals_below=47]
below,
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#arrivals_above=10]
above), two viewed cases (c62c2b06bcfb 1838.5 s, e37fdeca944f 1088.0 s) obey
the queue: the instrument had lost the entries above.

## 3. Verify, parse, surprise

**Verify.** For each predicted entry, correlate its reference template with
the sample's crop, as soft maps, never binarised: normalised cross-correlation
of whiteness (the opaque text, icon and portraits, which the translucent plate
does not tint) plus agreement of the soft plate colour on each side of the
seam, over the entry's columns, with the overlay mask's pixels dropped from
both. Resample with the filters AGENTS.md names; never enlarge. One cut, at
the decision, fitted on audit rows (section 4); until then, step 1 records the
score distribution and cuts nothing.

**What counts as a surprise:**

1. *Missing early:* a predicted entry fails at every hypothesis position
   before its due window.
2. *Extra band:* a plate-coloured band where nothing is predicted, outside the
   probe slot.
3. *Mismatch:* a band at the predicted place that fails the template.
4. *Arrival not at the bottom:* a new band above the lowest predicted entry.
5. *Fall or pass:* an entry below its predicted rest or past another.
6. *Overdue:* an entry present after its due window.
7. *Whole stack gone* without the wipe's signature.

A surprise runs the full parse (today's `analyse_killfeed`) on that sample and
stores a row: the prediction (ids, hypotheses, scores), the parse, and the
kind. The state reseeds from the parse; a parsed band continues an entry only
if that entry's template verifies on it and no order is broken
[domain:killfeed/stack-order]. Surprises are never averaged into a rate that
replaces them. Expected volume: transitions that return a lost entry or move
one down
([metric:killfeed_prior/design@eight~killfeed-prior-20261002#trans_return_or_fall=585]
of [metric:killfeed_prior/design@eight~killfeed-prior-20261002#transitions=34118])
and samples with a band outside any entry track
([metric:killfeed_prior/design@eight~killfeed-prior-20261002#phantom_band_samples=840]),
most on the Shooting Error box, the KILLED BY banner and washes.

## 4. Audit

A full parse runs on samples chosen before reading, by opportunity alone:
every 4th sample whose predicted stack is non-empty and every 20th sample
whose predicted stack is empty, counted per session from its first sample,
plus the first sample after every hole. The parse result is stored apart
(`kind: audit`) beside the follow's answer for the same sample. A
surprise-triggered parse is not an audit sample and never enters the audit
statistics.

Efficacy test, fixed now: disagreement is an audit sample where the parse
holds an entry, position (beyond 1 px) or entry boundary the follow lacked, or
the reverse. The audit stops widening by cadence once at least 2000 non-empty
audit samples across the corpus give a Wilson 95% upper bound under 1%
disagreement; it restarts for a capture height the facts have not covered
(every measured capture is 1080p [domain:killfeed/slot-pitch]).

## 5. Occlusion

Flashes [domain:abilities/phoenix-curveball-blind-screen]
[domain:abilities/skye-guiding-light-blind-screen], the death-cam fade, the
KILLED BY banner and the Shooting Error box hide entries. On the eight
sessions the overlay mask covers rows 136-198 of the crop on 4f207c0c4e39 and
bdfdcf009dba (slots 3 and 4) and nothing elsewhere.

- An entry the follow predicts under occlusion is stored as `predicted`, in a
  mask apart from the observation masks (`kf_predicted_mask`), with
  `rests_on` naming the facts and its last verified sample. It never sets a
  bit of `kf_entry_mask`, never adds to `n_obs` or the persistence bars, never
  enters the killfeed-roster audit, and yields no descriptor.
- An entry that reappears where predicted verifies and continues its id; its
  re-acquisition row declares `scope: prior`.
- A sample unreadable as a whole is stored unread with its reason (`wash`,
  `banner`, `fade`), never as empty. Flash detection itself, which the player
  wants for the minimap too, belongs to its own owner later.

## 6. Reading only the top k slots

Entries per read sample: none on
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#count_0=26138],
one on [metric:killfeed_prior/design@eight~killfeed-prior-20261002#count_1=5521],
two on [metric:killfeed_prior/design@eight~killfeed-prior-20261002#count_2=1882],
three on [metric:killfeed_prior/design@eight~killfeed-prior-20261002#count_3=482],
four or more on
[metric:killfeed_prior/derived@eight~killfeed-prior-20261002#samples_ge4_entries=103]
of [metric:killfeed_prior/design@eight~killfeed-prior-20261002#read_samples=34126].
[metric:killfeed_prior/derived@eight~killfeed-prior-20261002#arrival_slot_ge3=47]
matched entries arrived in slot 3 or lower.

Under the queue every entry reaches slot 0 unless the wipe or an occluder
ends it first, so top-k reading loses onset time, rarely the entry:

| k | never seen | seen late | delay median / p90 / max |
|---|---|---|---|
| 2 | [metric:killfeed_prior/design@eight~killfeed-prior-20261002#top2_lost=22] | [metric:killfeed_prior/design@eight~killfeed-prior-20261002#top2_late=176] | -- |
| 3 | [metric:killfeed_prior/design@eight~killfeed-prior-20261002#top3_lost=6] | [metric:killfeed_prior/design@eight~killfeed-prior-20261002#top3_late=41] | [metric:killfeed_prior/design@eight~killfeed-prior-20261002#top3_delay_median_s=1.5] / [metric:killfeed_prior/design@eight~killfeed-prior-20261002#top3_delay_p90_s=3.5] / [metric:killfeed_prior/design@eight~killfeed-prior-20261002#top3_delay_max_s=4.0] s |
| 4 | [metric:killfeed_prior/design@eight~killfeed-prior-20261002#top4_lost=1] | [metric:killfeed_prior/design@eight~killfeed-prior-20261002#top4_late=10] | -- |
| 6 | 0 | 0 | -- |

Two of the six top-3 losses viewed (c62c2b06bcfb 1838.5 s, 5822b6646448
1103.5 s) do rise into slot 2 or 3 by eye; the instrument's track broke at
the rise. Six is an upper bound.

The inferred onset (last content sample less the lifetime) is as precise as
the observed one where the expiry is clean: MAD
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#onset_exp_mad_ms=125.5]
ms against
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#onset_dir_mad_ms=124.0]
ms against Riot, on
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#onset_clean_n=354]
clean entries. But it fails where top-3 needs it:
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#late3_expiry_unclean=38]
of the
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#late3_n=47]
entries top-3 sees late or never have a round boundary inside their life, so
their expiry is the wipe's or a post-decision hold
[domain:killfeed/post-round-kill-persists], not the timer's. Low arrivals
cluster at round ends and multi-kills, exactly where onset matters for death
order.

Whole-life hiding cannot be measured with this instrument; master's 23
unmatched Riot kills of 1313 bound it.

**Recommendation:** no fixed k. The follow reads the predicted entries plus
one probe slot, so a deep stack costs reading only when entries are there
(four or more on
[metric:killfeed_prior/derived@eight~killfeed-prior-20261002#samples_ge4_entries=103]
samples), and arrivals at any depth keep their observed onset. A cap of 3 is
the player's option if a budget ever forces it; its cost is the table's
k = 3 row.

## 7. Cost

The killfeed portrait reader took
[metric:killfeed_prior/cost@5822b6646448~killfeed-prior-20261002#feed_s_killfeed_portrait=111.54]
s over
[metric:killfeed_prior/cost@5822b6646448~killfeed-prior-20261002#samples=4438]
samples on 5822b6646448: weapon
[metric:killfeed_prior/cost@5822b6646448~killfeed-prior-20261002#step_weapon_s=61.34]
s, portraits
[metric:killfeed_prior/cost@5822b6646448~killfeed-prior-20261002#step_portraits_s=22.34]
s, entries
[metric:killfeed_prior/cost@5822b6646448~killfeed-prior-20261002#step_entries_s=24.54]
s, names
[metric:killfeed_prior/cost@5822b6646448~killfeed-prior-20261002#step_names_s=1.87]
s. The `hud` reader, which parses the same bands again through
`read_killfeed` beside its OCR, took
[metric:scan_usage/hud+killfeed_portrait/cache/serial/cv12@5822b6646448~19aa9411#feed_s_hud=32.98]
s. A timed replay of 601 cached samples (600-900 s) splits the cost by entry
count: an empty sample costs
[metric:killfeed_prior/cost@5822b6646448~killfeed-prior-20261002#ms_portrait_reader_0_entries=5.25]
plus
[metric:killfeed_prior/cost@5822b6646448~killfeed-prior-20261002#ms_read_killfeed_0_entries=3.35]
ms, a one-entry sample
[metric:killfeed_prior/cost@5822b6646448~killfeed-prior-20261002#ms_portrait_reader_1_entry=55.77]
plus
[metric:killfeed_prior/cost@5822b6646448~killfeed-prior-20261002#ms_read_killfeed_1_entry=10.17]
ms. Descriptors dominate
([metric:killfeed_prior/derived@eight~killfeed-prior-20261002#descriptor_share=0.767]
of the portrait reader's time).

Stack stability: of
[metric:killfeed_prior/derived@eight~killfeed-prior-20261002#nonempty_transitions=9070]
transitions with an entry on either side,
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#trans_unchanged=5143]
keep the stack unchanged
([metric:killfeed_prior/derived@eight~killfeed-prior-20261002#unchanged_share_nonempty=0.567]),
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#trans_expiry_or_rise=2096]
only expire or rise, and
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#trans_arrival=1246]
bring an arrival. Counting empty samples,
[metric:killfeed_prior/derived@eight~killfeed-prior-20261002#unchanged_or_empty_share=0.885]
of transitions change nothing. Of
[metric:killfeed_prior/design@eight~killfeed-prior-20261002#entry_views=11167]
entry views,
[metric:killfeed_prior/derived@eight~killfeed-prior-20261002#verified_view_share=0.882]
continue an entry already seen.

Estimated saving per session, from these figures:

- *Band finding by prediction* (descriptors on every view): the empty
  samples' search shrinks to the probe slot, and one parse feeds both the
  `hud` and portrait readers. About 25-35 s of the roughly 145 s the two
  readers spend.
- *Descriptors thinned on verified views* (the player's choice, section 9):
  reading every 4th verified view would save about half the portrait
  reader's time again, about 55 s, at the price of fewer views for the
  portrait vote, which `killfeed-portrait`'s `not_for` says must accumulate.

The gain is consistency first (one entry identity, observed at the reader),
cost second, as PRIOR_DRIVEN_READERS.md ranked it.

## 8. Storage and versions

- `hud` (`HUD_VERSION`): the observation masks keep their meaning; add per
  slot `kf_entry_id`, `kf_scope` (`parsed`, `verified`, `audit`) and the
  separate `kf_predicted_mask`. A bump, rerun from the crop cache with
  `scan --only hud`.
- A new stream `killfeed_follow` with its own `KILLFEED_FOLLOW_VERSION`:
  surprise rows and audit rows, stored apart. `plan.py` lists it beside
  `killfeed_portrait`, `killfeed_weapon` and `killfeed_name` on the `hud`
  cache set, so `plan` names it stale by stamp.
- `killfeed_portrait`, `killfeed_weapon`, `killfeed_name`: bump only if the
  views they read change (thinning) or their rows gain `entry_id`.
- Downstream, from storage: `death` (its recorded inputs name all four
  killfeed streams), then what `plan` names after it: identity claims,
  `combat_report`, round entities, entity events; `rounds`, `reconciliation`,
  `fidelity` and `status` through `track_entries`. No decode.

## 9. Staged steps

1. **Follow beside the parse.** `prototypes/killfeed_queue_prior.py`: a
   reader wrapping `KillfeedPortraitReader` and `read_killfeed` that runs the
   follow and the full parse on every sample from the crop cache, uses the
   follow's bands for descriptors (every view), and writes the
   `killfeed_trial_deaths.py` layout. Records verify-score distributions,
   surprises by kind, and follow-parse agreement; cuts nothing it has not
   fitted.
   *Acceptance:* `prototypes/killfeed_queue_prior.py trial SESSION --out DIR`
   then `prototypes/riot_ground_truth.py SESSION --no-minimap --no-status
   --offline --deaths-from DIR` on the eight sessions; `killfeed_openset.py
   faults` on the 16 crop-fault rows.
   *Evidence:* per session no lost match and no new false death against
   master (totals 1290 of 1313 matched, ability kills 33 of 37, 24 false
   deaths, victim R/W/ref 1266/3/21, all floors); the 16 fault rows unchanged
   or better, each change named; follow and parse agree on 99% of
   non-surprise samples; 30 random surprise rows viewed on crop sheets and
   classed.
2. **Wire the follow** into `killfeed` with `kf_entry_id`, `kf_scope`,
   `kf_predicted_mask` and the `killfeed_follow` stream; register
   `killfeed-entry-follow` in `ownership.toml`.
   *Acceptance:* `reticle trial SESSION --reader killfeed` and step 1's two
   commands on the eight sessions; `reticle usage SESSION`.
   *Evidence:* step 1's floors; killfeed reader time per session at or below
   master's; `verify --tier fast` 7 of 7.
3. **`track_entries` takes the ids.** Linkage from `kf_entry_id` where
   stamped; the walk stays and its disagreements are stored.
   *Acceptance:* `reticle status`, step 1's scorer on the eight sessions.
   *Evidence:* `checks.KNOWN_KD` at least 13 of 17 exact; no lost match; every
   walk-follow disagreement listed with its crop.
4. **Audit to significance** at the cadence of section 4.
   *Acceptance:* a `killfeed_follow` audit summary over the corpus.
   *Evidence:* the Wilson bound of section 4 met, or the disagreements viewed
   and the cause named.
5. **Optional, by the player's choice:** descriptor thinning; a top-k cap;
   the expiry-inferred onset in `adjudication.death`.
   *Acceptance:* step 1's commands plus `reticle usage`.
   *Evidence:* step 1's floors, including victim R/W/ref; time saved quoted
   with its run.

Predictions for step 1 are logged in the store's `notes/predictions.jsonl`
under `killfeed-prior-design-20261002`.

## Open questions

- Is an entry made after the round's decision held past its timer, or does
  the post-round phase merely outlast it? (Open in
  [domain:killfeed/post-round-kill-persists].) The follow stores `overdue`
  either way.
- Does the death-cam fade hide the feed for the whole transition, and do the
  entries keep their timers through it? (043bafca271a 753.0-755.5 s in
  [domain:killfeed/entry-lifetime]'s exceptions.)
- Is the pale beige wash after a blind part of the blind?
  ([domain:abilities/phoenix-curveball-blind-screen] leaves it open.)
