# Reticle — working notes

Where the work stands **today**: the handoff into the next session, and the
defects that are live rather than standing. `CLAUDE.md` carries what stays
true across sessions — the conventions, the domain rules, the mistakes worth
not repeating. This file carries what is true this week, and it is read on
demand rather than loaded into every session.

Read it when picking up unfinished work. Update it in place; let it go stale
rather than let it grow.

Split out of `CLAUDE.md` on 2026-08-27.

## Picking up

**SUPERSEDED THE SAME DAY, evening of 2026-08-27: the match-derived ability fit
below (held-out F1, "more Ascent fit data") is no longer the active plan.**
Grant's call, later the same day: record short CONTROLLED clips, one agent per
clip, using every ability on purpose, instead of mining full matches and hoping
the right agents show up. Two new tools support it:

    prototypes\scan_ability_clip.py <session>     # dense per-clip scan -> candidates
    prototypes\label_ability.py <session>         # name/correct them (freeform, MRU categories)

`label_ability.py` also still serves the older match-derived `kind: ability`
rows (`--source dynamic`) -- both paths coexist, `--source auto` picks
whichever candidate file exists. Full worked example: `2ba870ccbd50`, a
37s Brimstone ability demo, ingested and iterated through several rounds of
false-positive hunting that turned into the detector work below.

**The colour-free detector itself changed, in `minimap_dynamic.detect()`, and
now benefits every caller** (`label_dynamic.py`, `scan_ability_clip.py`):

1. **Two-state lighting reference.** A geometry pixel has exactly two
   legitimate resting colours -- unlit and viewcone-lit (Grant's model,
   confirmed against real footage: 81-91% of samples at one interior
   border/box-edge point cluster at a single value, most of the rest at one
   adjacent second value). `minimap_geometry.two_state_gray` learns both per
   pixel; `detect(..., static_gray2=hi_gray)` counts a pixel dynamic only when
   it falls OUTSIDE the interval the two references span, not merely far from
   the nearer one -- the earlier "far from nearest" version still flagged
   viewcone-transition midpoints as dynamic. Fixes the border/box-edge false
   positives that four earlier downstream filters (aspect, bbox line-overlap,
   mask line-overlap, host span) all failed to separate cleanly.
2. **Saturation trigger.** Several abilities TINT the widget rather than
   fully overwrite it -- Brimstone's ult orange, Skye's heal a green area,
   Breach's ult a reddish bar -- and can coincidentally match the resting
   grayscale luminance exactly (measured: Orbital Strike's marker at gray=114
   against an unlit reference of 117). `sat > COLOUR_SAT` is now an
   independent OR, reusing the constant `blob_colour` already had.
3. **`minimap_geometry.py --two-state-from OTHER` / `--geometry-from OTHER`.**
   A short demo clip's own frames can contaminate its own reference -- a 2.4s
   ability in a 37s clip is ~9% of the sampling window, not the rare minority
   a full match gives you. Source the lighting reference (or the whole
   geometry: floor plan, holes, bomb sites too) from a full match on the same
   map/profile instead. **Still open:** wholesale `--geometry-from` borrowing
   fixed the contamination but introduced a NEW problem on `2ba870ccbd50` --
   large, long-duration false positives from a pixel-value mismatch between
   the two recordings (brightness/gamma/encoding drift, not yet root-caused).
   That session's own geometry needs another pass before its candidates are
   trustworthy; don't trust `--geometry-from` blindly until this is understood.

**Two bugs fixed in shared geometry code** (`minimap_icons.floor_mask`,
`minimap_geometry.classify`), both found by Grant reading the rendered
geometry sheet by eye, same evening:

* **`floor_mask` was discarding real rooms cut off by one narrow doorway.**
  It keeps only the SINGLE largest connected component (to drop HUD/scenery),
  and Ascent's Boathouse -- plain floor by every pixel statistic -- formed its
  own small island because the doorway to the main slab didn't survive the
  5px close. Now also recovers any component within `BRIDGE=25` px of the
  main slab; validated by eye against the 5 closest unclaimed components
  (Boathouse plus 4 real nooks, all confirmed on the map; the next-nearest
  jumps to 31px and is a 5px speck).
* **Box-edge classification had no line-closing step**, unlike `floor_mask`,
  so a real 1-2px wall is exactly as prone to fragmenting from ordinary pixel
  noise as an artefact is (measured: real corner fragments and a small floor
  decal's antialiased rim showed the SAME size and aspect-ratio statistics).
  Fixed the same way `floor_mask` does: close the white-line mask first
  (`LINE_CLOSE=5`), filter by area AFTER closing (`LINE_MIN_AREA=20`). Real
  walls reassemble into one connected network (3 of 4 previously-isolated
  corners merged into a single 3512px component); the decal and an
  ally-roster HUD-bleed cluster at x>=434 stayed small and got dropped.
  54 -> 24 box-edge components on `a06f04a0059f`, tiny (<=12px) ones 37 -> 4.
  Grant's read on the result: better, though some remaining "box edge" pixels
  are legitimately walls/map edges rather than small boxes -- that's expected
  (the class name covers any interior line), not a new defect.

**NEXT SESSION:**
1. Root-cause the `--geometry-from` pixel-mismatch false positives on
   `2ba870ccbd50` before trusting wholesale geometry borrowing again.
2. `5822b6646448` and `c62c2b06bcfb`'s geometry predates ALL of tonight's
   fixes (only `a06f04a0059f` was rebuilt, twice, while verifying) --
   rebuild both before running `label_dynamic.py` on them again.
3. Record a second controlled ability-demo clip (different agent) and run it
   through `scan_ability_clip.py` + `label_ability.py` end to end, now that
   the detector fixes are in place.
4. Audio, raised by Grant as a confirmation/primary signal for abilities with
   no minimap footprint at all: matched-filtering against a clean per-ability
   reference clip is the cheap approach (no ML needed, these are fixed
   deterministic SFX) -- `av` is the one new dependency, everything else is
   plain numpy. Deferred until a demo clip supplies clean isolated reference
   audio per ability; not started.

*Below this point, the ability-class-splitting narrative and its "NEXT
SESSION: more Ascent fit data" are the superseded plan -- kept for the
embedded domain facts (Ascent roster, Miks's kit, ultimate orbs having no
icon) which are still true, not as a live instruction.*

373 answered rows on `5822b6646448`, all from Grant, uniform-in-time sampling
(the two-pool sampler is built but nothing has used it yet):

    nothing 151   ability 64   player 46   area 34   unsure 69   other 5   spike 1

**The `ability` class did not need splitting first**, which was the blocker
written here this morning. On Ascent it was 53 rows at 9 positions with 33 of
them one Deadlock Sonic Sensor; on Lotus it is **64 rows at 35 positions, top-2
holding 11%, worst spot 4**. The sampler fix did that, and it is why the fit is
worth running now rather than after a class split.

Then, in order and all cheap:

* **the 5 `other` rows are Lotus doors** -- split them out by position, no
  questions needed, since a rotating door is a fixed map structure;
* **the cam test finally works.** Lotus has a Cypher, a cam glyph is colour-free
  so it is in THIS channel and not the red mask, and `minimap_ring_fit`'s
  `LOBE_MIN_FRAC` has never met a real one. `prototypes/CLAUDE.md` says a cam
  rotates but never translates and has no lobe -- all three are now testable;
* **69 `unsure` rows are the death-screen cost**, 18.5% of the pass. Fixed by
  `minimap_temporal.drawn()` after row 4; a re-run would not pay them again.

**Known-bad and unmeasured:** the Omen smoke that translates while deploying is
the only counterexample to the translation invariant, and the narrowed version
-- *translates then stops forever = smoke; keeps moving = player* -- has never
been measured. `motion()` says so.

    nothing 148   ability 53   player 25   area 20   ping 4   other 1

The channel was blocked because nothing in the store said which colour-free
blobs were real. It is not blocked any more, and the first cut of the answer is
better than expected. Two features separate an ability glyph from a viewcone
corner-clip, and **neither is currently recorded by the detector**:

* **host span** -- the span of the RAW difference region a blob belongs to,
  before the top-hat fragments it. Grant, on candidate 149: *part of the vision
  cone barely clipping a corner and producing something that vaguely could look
  like an icon.* Median 24 px under a glyph against 127 under a `nothing`;
* **top-hat peak** at the blob, median 132 against 63.

On live play only (30 s or more into an active span, see the buy-phase note
below), against 35 glyphs and 55 artefacts:

    no filter                    100% recall   39% precision vs artefacts
    host span <= 40               77%          96%
    host span <= 40, tophat >=110 31%         100%

    .\.venv\Scripts\python.exe prototypes\dynamic_eval.py a06f04a0059f

reproduces every number in this section, and `--mask` reproduces the IoU
figures. Start there rather than rebuilding feature extraction.

Read that as promising, not settled. n is 35 positives, the thresholds are
picked on the same rows they are scored on, and it is one session on one map.
**The next step is a second labelled session** -- Lotus or Split, which also
serves the older open question about the cold identification path -- fitted on
one and scored on the other. If it holds, this channel is a glyph detector at
an operating point the red ring-finder cannot reach, rather than the weaker
enemy detector it was measured as.

**Also first live test of "predict before you look"** (in the conventions).
Tomorrow is the first session where it applies prospectively rather than
retrospectively, and the Lotus pass is a good case: predict the class
distribution and the stream size BEFORE running `label_dynamic`, at whatever
resolution holds at 0.7, and score it. If the log ends the session with more
`couldn't-tell` than `wrong`, the technique is already decaying.

Three things found while labelling, all Grant's, all recorded below:

* **`active` contains the buy phase**, so 38% of the questions were about an
  empty minimap. Fix the sampling, and consider a phase detector -- the spawn
  barrier is the easiest signal in this document;
* **the size gate is fitted to icons**, so smokes, walls and ultimates are cut
  outright. `8 area` and `9 barrier` are now separate classes;
* ~~a few barriers labelled `nothing` before `9` existed~~ **fixed.** Sweeping
  all 148 `nothing` rows for strong green or red within 12 px gave 16 hits;
  Grant identified exactly two as barriers, both ally green, and corrected rows
  supersede them by the last-write-wins convention. No number moved. Of the
  other fourteen he said: *most of the rest of those are "problem areas" of the
  map I noticed before with high misfire rates* -- so a colour sweep finds the
  high-traffic zones, which is what the viewcone story predicts, since a cone
  is where the coloured things are.

*Previous handoff, resolved 2026-08-26:* portrait identification is built and
measured. Two things gated it and both are now done:

* ~~71 of the 107 agent labels are provisional~~ **DONE 2026-08-26: all 107
  icons are Grant's.** On hand labels, leave-one-out: **88.6% over the five
  agents** (`?` excluded), 84.8% for agents with `?` sitting in the gallery,
  78.6% recall on `?` itself, 83.2% over all six classes. The **roster alive
  check is now 79/79 = 100%** against a 67% chance rate -- every identification
  names an agent the roster shows alive, and that check finally means something
  because the labels are no longer mine. My provisional labels turned out to
  agree with Grant's on 69/71 (97.2%), so the earlier 93.0% was circular rather
  than wrong; the honest five-way number is 88.6%, and the gap is mostly the
  eight hard icons Grant added that my clustering had dropped -- blurry ones,
  and a Jett mostly covered by Grant's own icon in a close-range duel.
  Superseded caveat, kept because the mechanism was the point:
* **~~71 of the 107 agent labels are `claude-provisional`~~.** Grant ran the
  labeller on 2026-08-26 and it presented only 36 icons, because seeding the
  file with provisional rows made every seeded icon look already-done. Fixed --
  provenance now decides, not presence -- but the fix does not relabel anything:
  **`label_icon_agent.py a06f04a0059f --names ... --redo` still needs a pass**,
  and until it has had one the 93.0% is my clustering scored against itself;
* **I named two of the five agents wrong, and no automatic check caught it.**
  Grant, reading the labeller's own key: what I called `sage` is **Skye** and
  what I called `yoru` is **Iso**. The a06f04a0059f enemy lineup is
  **Skye, Iso, Jett, Omen, Killjoy**. Nothing measured changes -- the classes
  were consistent throughout, so every accuracy, the clustering and the abstain
  curve all stand; only the strings were wrong. But it exposes a real limit of
  the roster alive check: it verifies which CLUSTER belongs to which ROSTER
  SLOT, and the slot's name came from the same `--names` list I got wrong, so
  the whole thing was self-consistently mislabelled. I wrote that naming
  therefore needs a human, and **that was wrong, discovered ten minutes later
  on the pixels**: the Tab scoreboard prints the AGENT NAME as a second, grey
  line under each player name -- Omen / Jett / Killjoy / Skye / Iso down the
  enemy block, and "Me / Phoenix" on Grant's own row. So a capture names its own
  agents, and it needs no alphabet: agent names are a CLOSED SET of about
  twenty-five strings, so twenty-five mined word bitmaps matched whole will do
  it, which is exactly the trick `killfeed.py` already uses for "Me". Until that
  is built, treat agent names as an unverified layer over verified classes;
* **the question mark needs its own mechanism, not a tuned threshold.** With
  `?` added as a sixth class the mixed set reads 85.0% overall, 87.3% over the
  five agents alone, and **13 of the 16 misses involve a `?`, in both
  directions**. Two explanations were measured and both failed: red inside the
  interior does not separate them (median 0.08 vs 0.09) and neither does the
  sampling radius (flat, 82.2-86.0% from FRAC 0.55 to 0.94). What does show is
  that a minority of `?` interiors are nearly featureless -- raw contrast p10
  5.9 against 31.1 for agents -- and NCC normalises a flat patch up to full
  weight and then correlates noise. A `?` is a fixed GLYPH, so it belongs with
  the digit templates: matched by shape, decided BEFORE the 5-way portrait
  match;
* **it is one session with one lineup.** `5822b6646448` (Lotus) and
  `c62c2b06bcfb` (Split) are ingested, on the same enlarged widget, with
  different agents. The project's history says a new map is where these break,
  and neither has minimap labels yet.

Two smaller threads left open, both cheap:

* **label Cypher cams specifically -- MOVED TO LOTUS, and to the other
  channel.** Two corrections on 2026-08-27, in order. First: `a06f04a0059f` has
  **no Cypher** (Grant confirmed), so the cam case was never runnable there, and
  two `glance` sheets over 30 of its 144 `other_red` marks duly found zero cams
  (19 death marks, 3 warning pings, 4 occluded, 8/8 controls). Second, and the
  reason those sheets were the wrong instrument anyway: **a cam glyph is black
  and white, so it lives in the COLOUR-FREE channel, not the red mask.** Looking
  for cams in `other_red` could not have worked whoever was on the roster.
  `5822b6646448` (Lotus) **does** have a Cypher, and it is the session already
  queued for the labelling pass -- so the cam question and the ability pass are
  the same errand now.
  The premise that needs re-examining is the one in `minimap_ring_fit`:
  `LOBE_MIN_FRAC` was added to stop *a cam* passing the motion filter, which
  assumes cams reach the red mask at all. Check that against Lotus before
  trusting the constant.
  Reproduce: `prototypes\glance_cams.py a06f04a0059f --seed 3` and `--seed 91`.

* **The Ascent roster, read off the Tab scoreboard TEXT, is definitive.**
  Frame 111702 (31.0 min), `rosters/a06f04a0059f.scoreboard.npz` records the
  index; seek to it and the grey second line under each player name reads:

      allies    Reyna | Me/Phoenix | WhaleKicker/Deadlock | Seacow/Breach | tin/Miks
      enemies   Deebo/Omen | Truewarrior/Jett | vanshrana/Killjoy | Lil2Foot/Skye | chxck/Iso

  **No Cypher.** This is the mechanism this file already predicted would work --
  agent names are a closed set printed as text -- and it settles in one look what
  two rounds of portrait-reading could not. **Read the names, never the
  portraits.** Portraits got `sage` for Skye and `yoru` for Iso in an earlier
  session, and cost two exchanges again on 2026-08-27.

* **So the object at (137,170) is NOT a Cypher cam, whatever it resembles.**
  Grant, on the 10x comparison sheet: *top row is all cypher cams, so is bottom
  right*, and *the reason 06 reads as a different glyph is probably because it's
  a different rotation* -- which collapses my "three distinct glyphs" claim to
  ONE glyph under rotation. But two of those panels are Ascent, and Ascent has no
  Cypher, so either that glyph is not exclusively a cam or the Lotus reading
  generalised. **Open, and it is the blocker on the class list.** The ally with
  placeable devices on Ascent is Deadlock (Sonic Sensor, Barrier Mesh); `Miks` is
  an agent whose kit is not in my knowledge at all, which is worth stating
  plainly rather than guessing around.
  Also from Grant, same pass: **04 is a DEADLOCK wall** (Barrier Mesh) --
  *that light blue going off; there are four of them but they can get destroyed
  or be up against a wall and very small* -- so it is a MULTI-SEGMENT object with
  a variable segment count, which no size gate fitted to icons will survive. And **05 is a viewcone through
  a doorway**, on Ascent at (264,128), which kills that as a candidate object.

* **Ultimate orbs have NO minimap icon.** Grant checked in a custom game,
  2026-08-27: *I don't believe ult orbs have a minimap icon. They didn't in the
  custom game I just opened to test. I think they used to though. They are
  generally in the "no man's zone" area of the map, between the barriers.* This
  kills the hypothesis outright -- an orb was the obvious reading of "two fixed
  positions per map" and it is simply wrong. **A five-minute custom game settles
  what the pixels cannot**, and it is the cheapest instrument in this project.

* **The Ascent object is HALF-SCOPED, which rules out a map fixture.** Over 250
  frames, same gate:

      (136, 168)  n=79   t=  30..1252s   then absent for the last 18 minutes
      (264, 128)  n= 9   t=  77..1043s   same, stops early
      (224, 216)  n= 2   t=1681..2289s   appears only late

  Two positions carry the first half and a different one carries the second.
  That is the **side swap**, so the object is a placed device whose position is a
  per-half placement habit -- not furniture, and not a habit that survives
  halftime, let alone another session. On the Ascent ally roster the candidate is
  **Deadlock's Sonic Sensor** (WhaleKicker), a placed device that persists until
  destroyed. Miks is the other candidate but his deployable is THROWN, which
  fits 2 px repeatability across twenty minutes poorly.
  **Miks's kit, from Grant** (not in my knowledge, so recorded here): smokes, a
  teammate buff (movement speed and fire rate), a cone ult, and a deployable
  toggleable before throwing between healing and stunning.

* **Rounds were never missing -- `reticle rounds` had simply never been run on
  the three enlarged-minimap sessions.** `rounds.py` derives bounds from the
  scoreline climbing by one, recomputed from stored L1 without opening the
  video. Ascent 24 rounds 13-11, Lotus 23, Split 21 21-rounds 13-8, all now
  persisted. My earlier claim that no `l2/rounds` parquet existed was a
  truncated `find | head`; the round table is 349 rounds over 17 sessions.
  (`active` spans still are not rounds -- 29 spans against 24 rounds on Ascent,
  several of them 12-26s fragments -- but nothing on the endstate path needs
  them to be, because the scoreline gives rounds directly.)

* **`PLAYER_SIDE = "left"` is structural now, and it recovered 43 rounds.**
  `infer_player_side` decided the player's side from kill differential and
  ABSTAINED on three sessions, leaving `won` NULL for all 43 of their rounds --
  including all 23 of Lotus, the session queued for labelling. Three independent
  lines settle it instead:

      direct        the top HUD band is COLOURED BY TEAM -- green ally bar left,
                    red enemy bar right. Confirmed by eye on 5822b6646448
                    (bigmap profile, 11-12) and c40d950031bb (16x9 profile, 7-1)
      statistical   the old inference resolves LEFT on 14 sessions, RIGHT on 0
      structural    the roster bars are green-left / red-right, same order

  **The scoreline ROI already contained the answer and nothing was reading it.**
  Rounds with a known outcome went 306 -> 349, and every one of the 14 sessions
  that previously resolved kept an identical W-L, so the change is non-
  destructive. The inference is kept as a CHECK: `reticle rounds` prints `~` where
  it abstains and `!` where it actively disagrees, and a `!` is worth opening the
  capture for. None currently disagree.

* **All three abstaining sessions are TRUNCATED captures**, which is one
  explanation rather than three: 5822b6646448 ends 12 s after its last read at
  11-12, c40d950031bb at 7-1, 75a55a296d3b at 10-2. `infer_player_side` abstains
  exactly on short or lopsided partial matches, as its own docstring predicted.
  **This resolves Lotus's K/D gap**: our 12/20 against Grant's end-of-match 13/21
  is one kill and one death in the unrecorded tail, not two read errors. Check
  capture completeness before quoting a K/D delta as a defect.

* **DONE: the plant, at ~88% either way, from stored L1 alone.** The spike
  graphic sits exactly where the round timer's digits are, so a planted round has
  **no clock to read** -- and `clock_ms is None` is already in L1. The rule needs
  no new ROI and no video re-read:

      a plant is the run of unreadable clock that REACHES the round's end,
      when it is at least as long as a defuse takes.

  **The tail is the discriminator, not the length.** Over 349 rounds the
  trailing-run histogram is 200 rounds at 0-4 s (end-of-round animation), a
  sparse 5-19 s band, then a broad 20-45 s plateau that stops exactly at the
  spike's 45 s fuse. The floor is a GAME RULE rather than a fitted number: **a
  defuse takes 7 s**, so no post-plant is shorter. My first guess of 20 s cost
  2 of 5 plants on `223d636bf8d2`, both real, at 18.5 s and 16.0 s -- fast
  defuses missed by seconds.

      old clock-jump rule       6 plants / 262 rounds
      new rule, 20 s floor    114 plants / 349 rounds (33%), per-session 11-62%
      new rule,  7 s floor    170 plants / 349 rounds (49%), per-session 35-57%

  Validated against pixels three times with `prototypes/plant_probe.py`, all
  sheets VALID:

      9acf02f98283   tuning   recall 100%  precision 88%
      223d636bf8d2   surprise recall  60%  precision 100%   -> found the 20s bug
      e37fdeca944f   HELD OUT recall  88%  precision  88%

  **The controls are free and non-circular**: a READABLE clock proves the graphic
  is absent, because they occupy the same pixels, and that truth comes from
  `ocr.py` -- a different extractor written long before this question -- not from
  my eye and not from the rule under test.

* **Two limits on the plant, both stated in `rounds.py`.** The **boundary is only
  good to +/-5 s**, since an OCR drop can start the run before the plant: enough
  to SPLIT a round into phases, not to time one, so **do not cut a clip on
  `plant_t_ms`**. And the honest way to sharpen it is **audio**, which this
  pipeline has never touched. Grant, 2026-08-27: *the spike beeping speeds up at
  standard intervals, so that's the main way players tell how much time is left
  in postplant.* That is not a cheaper plant flag, it is a **post-plant clock** --
  for the one window where the pixels have no digits by construction.

* **A probe that copies the rule is not a probe.** `plant_probe.py` first
  duplicated `PLANT_MIN_MS` and the run scan, so it was validating a rule that no
  longer matched the shipping one the moment the constant moved. It imports
  `rounds._plant` now. Any future probe does the same: **import the thing under
  test, never restate it.**

* **A rotation-variant glyph breaks template matching.** If the cam icon rotates
  to show facing, then `minimap_portrait`'s NCC gallery approach cannot identify
  it without a rotation bank or a rotation-invariant feature. Nothing in this
  repo has assumed a rotating glyph before.

* **Positional persistence is a real signal, but NOT static-versus-deployed.**
  Same detector, same gate (area 200-420, aspect <= 1.25), 200 frames each:

      ascent  91 disc-like   66 of 91 at TWO positions, spanning 1222s and 966s
      lotus   90 disc-like   24 of 90 at the top two, every cluster 30-90s long

  I read that as map-static furniture versus deployed utility. **That reading was
  wrong**: Ascent has no map object there, so what holds one pixel for twenty
  minutes is a player re-placing a device in a favourite spot every round. The
  measurement stands and the feature is still free and label-free -- it just
  measures a PLACEMENT HABIT, not an object class, and a feature fitted to one
  player's habit will not transfer to another session.

* **STILL THE ONE THAT CHANGES THE NEXT STEP: the `ability` class is mostly one
  object.** 33 of Grant's 53 `ability` rows sit within 6 px of (137,170), from
  t=30s to t=1252s; another 12 sit at (96,180). **44 of 53 (83%) are two fixed
  positions.** The rotation point makes this worse, not better: if those are all
  one glyph, the 77% recall / 96% precision operating point is measuring a single
  object type at two spots in one match. **Split the class before fitting**, and
  get the identities first -- the fit is not worth running until the class list
  is real.
* **`a06f04a0059f` is +2 kills / +3 deaths** against Grant's 19/19, the widest
  gap in the set, uninvestigated. Run It Back would explain deaths running high,
  which is the direction seen, but no agent has been checked.

## Live defects

Bugs with an owner and an end. The standing hazards — the ones that are properties
of the problem rather than tickets — stay in `CLAUDE.md` under "Open defects".

- **One known read error, plus two unexplained**, across 372 events at
  `hud-0.8.1`. The raw gap against `checks.KNOWN_KD` is 8 events, from 24 at
  `hud-0.6.0`: five are verified Run It Back, one is the ability kill below, and
  two are `e37fdeca944f`'s missing deaths, which nobody has looked at yet. See
  "Scoreboard divergence is a finding" in `CLAUDE.md` before quoting the 8.
  `killfeed.py` has the per-session table.
- **The one real miss left is an ability kill.** `c40d950031bb` 13:14,
  `HungryHamster5 ⊗ Me`, killed by Raze. There is no weapon icon, and the
  ability mark fragments under the white-text cut into pieces too small to be a
  divider candidate, so the band goes *unparsed* and the death is lost. Reading
  it needs a divider that does not depend on the icon — the boundary between the
  two plate colours is the candidate, and it needs no list of icons. A prototype
  landed the split correctly on 6 of 8 test bands; the estimator needs to be
  edge detection on the plate chevron rather than a brute-force search.
- **Scoreline OCR drops a transient extra digit.** On `9acf02f98283` the score
  reads `1 → 11 → 1` and `9 → 19 → 9` within half a second, i.e. a spurious
  leading `1`, and `verify` flags 8 violations there. Single-sample, reverts
  immediately, and unrelated to the killfeed. Clock read rate on that session is
  also low (39.7%). Worth a look when next in `ocr.py`.
- **`README.md` is stale.** It says HP, ammo and the killfeed are unbuilt; they
  are built, and it still describes stage 02 as scoreline-only. Fix it when next
  touching that area.
