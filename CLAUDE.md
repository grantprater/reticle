# Reticle

Vision-based mechanical analysis pipeline for Valorant — measuring the layer of
play the match API structurally cannot see. Python 3.14, four deps, single
process, no ML frameworks.

**Design doc** (the authority on stage numbering and intent):
https://claude.ai/code/artifact/d7c7173f-dc5e-4c1e-9dcc-acded5a486cb
**Store dashboard:**
https://claude.ai/code/artifact/3854df28-3e45-4783-8aee-7e7f062ac461

Section references in docstrings (`SS3`, `SS7`) mean §3, §7 of that doc.

## Picking up

Last worked 2026-08-25. **Fourteen sessions ingested, fourteen with scoreboard
K/D in `checks.KNOWN_KD`, and every one carries its map.** Thirteen are
scorable (`0f08b3dc3777` is the cropped capture and has no killfeed ROI). The
store is at **`hud-0.8.1`** throughout. **Nine of thirteen are exact and the gap is 8 events across 372.** Five of the
eight are Run It Back (see "Scoreboard divergence is a finding" below), one is
the ability-kill read error, and two are new and uninvestigated — see below.
Long tracks are 0. Nothing is half-applied and the tree is clean.

**Ground truth is now corroborated.** Grant read his whole match history on
2026-08-25 and every K/D already transcribed off the end screens agreed, so
`KNOWN_KD` has two independent sources behind it. Two sessions gained ground
truth for the first time and both were fully out-of-sample — never scored, never
used to tune anything: `96aa1ae9b96f` (Haven) came out **exact**, and the brand
new `043bafca271a` (Haven) came out **exact** as well.

**One match has no capture.** The history lists a thirteenth match on 2026-08-24
(Split, 3/13) with no corresponding file. Nothing is wrong with the pipeline;
the recording is simply absent.

**Open: `e37fdeca944f` (Sunset) is −2 deaths.** A brand new capture on a map
never seen before, kills exact. Not yet investigated and not yet known whether
it is a read error or another divergence. It is the first thing to look at.

`hud-0.7.0` — **three band-detection fixes**, all found from five misses Grant
spotted by eye on `9acf02f98283` (4:27, 20:32, 24:35, 31:22, 32:22). Four of the
five were caught in exactly *one* sampled frame, one short of `KF_MIN_OBS`; the
fifth formed no band at all.

* plate density was measured across the whole ROI, so **narrow entries** ("Me
  (Bandit) exile") fell under `PLATE_ROW_FRAC` where the glyphs are tallest and
  the run shattered below `MIN_BAND_H`. Now measured inside the row's own entry;
* **warm scenery** reads as the enemy plate's red and merged into the entry
  above until the run passed `MAX_BAND_H` and was discarded whole. Rows now have
  to show both plate colours — the band's own test, one step earlier. Because
  new entries arrive at the top of the stack, this always cost the newest event;
* the divider test asked for **ink** either side, not glyphs, so bright sky in
  the band won it on size and flipped a kill to a death. Now glyphs.

`hud-0.8.1` — **a divider is only recorded when it can be trusted.** While an
entry slides into the stack its band is half-formed for a frame or two and the
split can land far left with no killer name beyond it; at `ff636d173b07` 10:18
that read 151 and 150 before settling at 253, and the tracker took the move as a
different entry and counted one death twice. The divider is now recorded only
when there is a name on both sides of it — the same test that chose it — and an
unrecorded one (stored as 0) falls back to slot and time. This was the divider
mechanism's own first defect, found while trying to verify the Phoenix deaths.

`hud-0.8.0` — **the tracker now sees each entry's divider column**. An entry's
weapon-icon divider sits at a fixed column for its whole life (the feed is
right-aligned, so the victim's name width sets it) and moves by at most 3 px,
while two different entries in one slot are tens of pixels apart. Storing it
(`kf_entry_wx` / `kf_kill_wx` / `kf_death_wx`, packed nine bits per slot) and
refusing to extend a track whose divider moved more than `KF_SIG_TOL` removed
every long track in the set. `223d636bf8d2` went exact; `ff636d173b07`'s kills
went from −3 to exact. **This supersedes the `kf_entry_mask` stack-shift plan** —
the divider does the same job more directly, and `kf_entry_mask` is still unused.

**Settled: every remaining divergence is Run It Back.** All six events between
the killfeed and `checks.KNOWN_KD` are now accounted for — one read error and
five entries that are read correctly and simply not counted:

* `ff636d173b07` +4 deaths. All 24 tracked deaths read correctly, and exactly
  four carry the **Phoenix ult mark** — 13:21, 20:00, 29:13, 38:20. 24 − 4 = 20,
  the recorded figure. Grant's own deaths inside his ult.
* `bfad2778a372` +1 kill, the same rule from the other side: a kill on an
  *enemy* Phoenix inside Run It Back. 19/15 confirmed off the end screen.

Both causes are **visible in the killfeed itself**, which is what makes reading
the mark worth doing: one detector reconciles both sessions exactly.

**Grant's call (2026-08-25): keep these events, do not drop them to match the
board.** A duel lost inside Run It Back is still a duel that was lost, and §4's
metrics are about duels. So the mark becomes a *category* on the entry — an
event that happened and that the scoreboard does not count — rather than a
filter. Stage 05 subtracts them when reconciling totals; stage 06 decides per
metric whether to include them. Same treatment as wallbangs.

**In flight: minimap position tracking** (`prototypes/minimap_position.py`,
not wired into the pipeline). Measured on `9acf02f98283`: 86% of frames yield a
position, 92% coverage after filtering, 1.5% of steps physically implausible.
Ally rings detect too. The static map falls out as a per-pixel median and is
also the occlusion grid the geometry work needs. Read the rejected-approaches
list at the foot of that file before trying anything clever — five variants
failed there and the failures share one cause: **the widget is semi-transparent
over the void, so anything content-based drowns in the world moving behind it.**
Masking to the opaque floor slab is what fixed it.

Next steps, in order: promote it to `reticle/minimap.py` with L1 columns; settle
the sample rate (everything downstream is a *speed* measurement, so 2 Hz cannot
work — 15-20 Hz for the minimap, likely a separate pass from the 2 Hz HUD read);
then the visibility computation.

**Peek exposure as the design doc defines it is out of reach**, and that is a
design-doc correction rather than a missing feature. It needs enemy positions,
and enemies are not on the minimap at all — only red X last-known marks. If the
product must run on a player's own OBS capture (Grant is sceptical that building
commercially on the replay system is viable), no amount of extractor work
recovers it. See "How peeking actually works" below for what replaces it.

The four candidates for what comes next, with the case for each:

1. **Reconcile the scoreboard against the killfeed** (§3 stage 05). The board
   outranks killfeed inference and is already readable, so for any session where
   it is open the totals could simply be taken from it, with the killfeed
   supplying timing within the round. This makes the remaining attribution gap
   stop mattering for totals without fixing it.
2. **Record whether an entry carries a revive mark.** This is now the best-
   evidenced next step: it is the only divergence in the set with a *visible
   cause in the killfeed itself*, and reading it would reconcile `bfad2778a372`
   exactly. The marks all sit in one place — right of the weapon icon, where a
   headshot crosshair goes — and are all circular badges, so *detecting* one
   needs no icon list; telling the four apart does, but four is a bounded set
   that changes only when Riot ships a new revive ult. Worth capturing as a
   field on the entry either way: a kill undone is its own coachable category,
   the same argument as wallbangs.
3. **Minimap position tracking** — the last big stage-02 extractor, and the
   gating dependency for the doc's peek-exposure metric.
4. **Keep grinding killfeed recall.** Diminishing: four causes found, two fixed,
   the rest cost a re-ingest or need a new primitive.

If a new capture reads badly, count thin tracks first (see below) — it is the
fastest signal for whether the problem is detection or counting.

## Running

Always via the venv interpreter — there is no console script:

```
.\.venv\Scripts\python.exe -m reticle <command>
```

Default store is `~/reticle-store` (outside this repo); override with `--store`.
`fixtures/`, `teststore/`, `probe_*/`, `frames_*/` are gitignored scratch.

## Pipeline status

Stage numbers are the design doc's §3 stages, not release versions.

| Stage | What | Status |
|---|---|---|
| 00 Ingest | fingerprint → profile, manifest, no media copied | **done** (`probe`, `ingest`) |
| 01 Gate/segment | frame state → bounded play spans | **rule-based baseline** — `off`/`idle`/`active`, not the doc's trained buy/in-round/post-round/menu/spectate classifier. No labelled data yet. |
| 02 Deterministic extractors | HUD, killfeed, minimap, main-view | **partial** — see below |
| 03 Event proposal | fuse stage-02 into typed candidates | not started |
| 04 VLM adjudication | ambiguous band only | not started |
| 05 Reconcile | source priority + label-free invariants | invariants only (`checks.py`, `verify`). The scoreboard is now readable and outranks killfeed inference, but nothing reconciles the two yet. |
| 06 Metrics | pure versioned functions | not started |
| 07 Narrate/query | not started |
| 08 Correction loop | not started |

### Stage 02 detail

Built and populating in the store: round clock, both team scores, HP, shield,
ammo (mag + reserve), killfeed **entry count**, and killfeed **player
attribution** (kill/death, with the stack positions needed to count entries).

Built but not stored: the **Tab scoreboard** (`scoreboard.py`) — all ten rows'
K/D/A and which row is the local player's. `reticle board` reads it live off the
video; nothing writes it to L1 yet, which is the obvious next step if it starts
getting used for more than checking.

Not built: **credits**, **minimap position tracking**, **main-view detection**,
**combat report**.

Minimap position tracking is the gating dependency for the doc's peek-exposure
metric and for movement state generally; §2 calls the homography trivial, and
`MinimapMode.has_static_homography` records per session whether a single
constant transform exists — true for every capture from 2026-08-23 evening on.

The **combat report** (the post-death panel, right of centre) is the richest
unread surface in the game: per enemy it shows outgoing damage, incoming damage,
the hit breakdown, and kill / killed-you flags. That is engagement-level data
the killfeed cannot give. Two things to settle before building it: the panel's
height and vertical position vary with the number of enemy rows, so it needs
detection rather than a fixed ROI; and the banner name changes between deaths
(`Chef`, then `Harbinger` on one session), which may mean it follows the
spectated player rather than the local one.

## Checking against the game's own numbers

Two commands exist for this, and they are the only checks that compare against
something outside the pipeline rather than a domain invariant.

```
reticle kd    <session>          running K/D per round, from the killfeed
reticle board <session>          read every Tab scoreboard and score us against it
```

`board` is the stronger of the two: it reads all ten rows of the scoreboard and
identifies the local player's row by the yellow outline the game draws round it
(no name reading — see `scoreboard.py`). Per opening it prints the board's K/D
beside ours, so the first divergent row names a window of a minute or two rather
than a whole match. On `96aa1ae9b96f` it agreed exactly across 21 consecutive
openings before the first miss.

Ask Grant to open the scoreboard once a round when recording; it costs him
nothing and it is worth more than any invariant.

## Wallbangs are a finding, not just a parsing problem

The wallbang arrow is currently something to see past when reading a name, but
§4 already excludes wallbang duels from the aim metrics ("no visual contact") —
and an exclusion rate is itself diagnostic. A kill or death through a surface is
its own coachable category: prediction, recon and map knowledge rather than aim.
The icon is detectable, so capture it as a field on the entry when the icon list
lands, rather than only stepping over it.

## How peeking actually works, and what to measure instead

Grant's domain knowledge, 2026-08-25. None of this is recoverable from the code
and the metric below makes no sense without it.

**Peek style is dictated by angle advantage, which is geometry.** If you are
*further* from the corner than the enemy, you see them first, so the correct play
is slow — slice the pie, take the angle in increments. If you are tight against
the corner you have angle *dis*advantage, you will be seen first, and the correct
play is a wide swing: cross the exposed band fast and get full information at
once. Jump peeks and the rest are situational variants.

The computable form of that is a derivative. Let A(p) be the set of positions
with line of sight to p — the visibility footprint, a raster visibility
computation on the floorplan the median map already gives us. Then

    dA/ds  =  how much new territory can see you, per unit of your own movement

is exactly angle advantage. Far from the corner it is small: each step exposes a
sliver, so slicing works. Tight to the corner it is large: no increment is small
enough to be safe, so committing is right. **It needs no enemy positions and no
conditioning** — it is a property of where you are standing.

That gives two failure modes, and the second is the one worth telling a player:

  * dA/ds small, moving fast   — threw away an advantage the position gave you
  * dA/ds large, moving slow   — slow-rolling into an angle you were always
                                 going to lose

**Counting exposed angles is the other half, and it is conditional.** Grant:
wide-swinging when you reasonably expect one enemy is not a bad play, so a raw
count is not a verdict. Worse, peeking is driven by *priors* — where enemies
commonly are, which shifts with rank and a lot with map geometry. The
naive-but-honest treatment is statistical: record features per peek, learn the
empirical rate, report tendencies rather than judgements ("you wide-swing into
4+ angles with 3 enemies alive 18% of the time and win 22% of those").

Most conditioning variables are already in L1 or one step away: **enemies alive**
decrements from the killfeed, **teammates** from the killfeed plus the minimap's
ally rings, **time in round** from the clock, **region** from the callout label
above the minimap. The outcome — did a duel follow, was it won — is the killfeed
again. This is where the "engagements without a kill" question below stops being
academic: duels that produced no killfeed entry are disproportionately the ones
that went badly, so omitting them flatters every number.

Order of attack: build dA/ds first because it is unconditional, and leave the
angle count as a statistical layer on top.

Standing limits, none cheap to fix: **no elevation** (the floorplan is a
silhouette, so a bridge and the floor under it are one region), **no cover
objects**, **jump peeks are invisible** (vertical motion is not on the minimap,
so a jump peek reads as a fast peek), and dA/ds aggregates every occluding edge
in play rather than naming the one you mishandled.

## Sampling densely where it matters, without poisoning the sample

Open, 2026-08-25. Peek work needs 15-20 Hz and the whole capture does not
deserve it, so some form of proportional sampling is wanted. Two passes is the
shape the design doc already implies -- §3's cost rule ("if the expensive layer
ever sees more than ~1% of frames, stage 01 is wrong") is about the VLM band,
but the principle is the same: a cheap pass decides where the expensive pass
looks.

**The trap is gating on outcome.** Sampling densely where shots were fired, or
where a killfeed entry landed, seems obvious and is wrong for the same reason
already recorded under "engagements without a kill": a peek that exposed five
angles and met nobody is not a non-event, it is the control group. Gate on
contact and the model only ever sees peeks that drew a duel, which flatters
every number and cannot be corrected after the fact.

**Gate on opportunity instead.** dA/ds is a property of the *map*, not of the
round -- so it can be precomputed once per map as a scalar field over the
floorplan, and "is the player near a cell where exposure changes fast" is then a
lookup rather than an inference. That gates on geometry the player was moving
through, entirely independent of whether anything happened, which is exactly the
independence the statistical layer needs.

That also settles the hard-code-versus-infer question for this case: the field
is *derived* from the floorplan rather than hand-authored, but it is *static*,
so it costs nothing at query time. Nothing about round phase needs hard-coding
-- "start of round is high value" is a proxy for "everyone is alive and moving
into position", and the geometry gate captures the part that matters without
assuming it.

Practical note: seeking is expensive in H.264 and contiguous decoding is cheap,
so the second pass should decode *ranges*, not scattered frames. Windows, not
samples.

## Scoreboard divergence is a finding, not an error

The killfeed and the scoreboard answer different questions, and where they
disagree the killfeed is often the one worth keeping. A death inside Phoenix's
Run It Back never reaches the scoreboard, and a Kayo ult down may not either —
but both are duels that were lost, and §4's metrics are about duels, not about
the end-of-match tally. Grant's position (2026-08-25): **perfectly matching the
scoreboard is not the goal.**

So `checks.KNOWN_KD` measures two different things at once and they must not be
conflated:

- a **read error** — the extractor got the pixels wrong. A missed entry, or an
  entry attributed to the wrong side. This is the number that should go to zero.
- a **definitional divergence** — the extractor read the entry correctly and the
  game simply does not count it. This should be *labelled*, not eliminated.

At `hud-0.8.1` the 6-event gap is one read error (`c40d950031bb` 13:14, the
ability kill) and five Run It Back events, all verified. Quote the read-error
count as the quality number.

Verifying them is what found the `hud-0.8.1` defect along the way: the one
divergence `board` could see on `ff636d173b07` was a real double-count, not a
Phoenix death. That session has only 5 openings in 45 minutes, all before 12:03,
so `board` could say nothing about the rest — the sharpest argument yet for
asking Grant to open Tab once a round. 79 openings pinned a miss to a single
round on `223d636bf8d2`.

This raises the value of recording a revive mark rather than lowering it: the
point is not to drop those events to match the board, it is to tag them so
stage 06 can include or exclude them per metric. A kill undone by a Sage revive
is also its own coachable category, the same argument as wallbangs above.

## Open design question: engagements without a kill

The killfeed only fires when someone dies, so keying stage 03 on it alone would
measure a biased subset. Counted from the store, shots fired outnumber killfeed
events **2.6 to 1** (400 shot bursts against 153 attributed entries across the
six sessions, and that is a floor — 2 Hz sampling collapses any burst shorter
than half a second into one sample). Damage taken outnumbers them 3.7 to 1.

The bias has a direction: a duel where the player fired and nobody died is
disproportionately a duel they *lost* or flubbed. Measuring only duels that
ended in a kill would flatter every one of the doc's three metrics — that is a
validity problem, not just missing coverage.

The signals are already in L1 and need no new extractor:

- **`ammo_mag` falling between samples is a shot fired** (already noted in
  `store.py`). Bursts of it bound an engagement.
- **`hp` + `shield` falling is damage taken**, which catches engagements the
  player never shot in.
- The killfeed stays what §2 calls the bootstrap: it is the *labelled* subset,
  the anchor that says a duel definitely happened and who won it.

So the answer is almost certainly no, do not ignore them — but nothing depends
on this until stage 03 defines what an engagement is, and the sample rate
probably has to rise for shot-level timing to mean anything.

## Debugging what the extractors see

`reticle overlay` renders the detections onto the capture as a video. It reads
no stored HUD and writes no L1 — every annotation comes from calling the real
extractor on that frame, so it cannot disagree with what `hud` would record.
Keep it that way: a debug view with its own copy of the logic is worse than none.

```
reticle overlay <session> --from 7:35 --seconds 25            # a window
reticle overlay <session> --from 2:40 --to 4:40 --entries-only  # only frames with a killfeed entry
```

Per killfeed entry it draws the band, the weapon-icon divider, the two name runs
with their pixel widths, and both match scores against the threshold. Colour is
the language: green kill, red death, grey not-the-player, **amber** an overlay
covers the name so attribution was refused, **magenta** unparsed. Amber and
magenta are the ones to chase; so is grey on an entry that visibly reads `Me`.
The calibrated overlay mask is drawn too, so you can see what it ate.

Text is rasterised before `--scale` is applied, so use `--scale 1.0` when
reading values and a smaller scale only for skimming.

**To audit a whole session's entries at once, build a contact sheet**: crop the
band for every tracked event into one tall image, one row per entry, labelled
with its timestamp. Twenty-four rows fit in a single glance, which is how the
four Phoenix marks on `ff636d173b07` were found and counted. Far cheaper than
scrubbing an overlay video, and it is the right tool whenever the question is
"which of these entries carries X" rather than "what happened at time T".

## Open defects

- **One known read error across 289 events** at `hud-0.8.1` — the ability kill
  below. The raw gap against `checks.KNOWN_KD` is 6 events, from 24 at
  `hud-0.6.0`, and all five of the others are verified Run It Back events; see "Scoreboard divergence is a finding" above before
  quoting the 6. `killfeed.py` has the per-session table.
- **The one real miss left is an ability kill.** `c40d950031bb` 13:14,
  `HungryHamster5 ⊗ Me`, killed by Raze. There is no weapon icon, and the
  ability mark fragments under the white-text cut into pieces too small to be a
  divider candidate, so the band goes *unparsed* and the death is lost. Reading
  it needs a divider that does not depend on the icon — the boundary between the
  two plate colours is the candidate, and it needs no list of icons. A prototype
  landed the split correctly on 6 of 8 test bands; the estimator needs to be
  edge detection on the plate chevron rather than a brute-force search.
- **A single-frame detection is discarded** (`KF_MIN_OBS = 2`), which is right —
  but it means any detection fault that thins a track to one frame costs a whole
  event rather than degrading it. Four of the five misses Grant found by hand on
  `9acf02f98283` were exactly that; the fifth formed no band at all. When hunting
  a miss, read `kf_entries` either side of it before looking at attribution: a
  lone frame is the tell.
- **Absolute brightness is the known soft spot.** `TEXT_V_MIN` (200) and
  `PLATE_V_MIN` (140) are absolute levels, tuned across captures that all share
  one set of video settings, and nothing has tested whether they survive a
  different one. No fix since `hud-0.6.0` has added another — the warm-scenery
  fault had a working fix that just raised `PLATE_V_MIN` to 160 and it was
  dropped for a structural test instead. The ability icon above fragments
  precisely because of `TEXT_V_MIN`.
- **No list of killfeed icons is needed, and none was used.** Valorant draws
  marks between the weapon and the victim name (headshot, wallbang) and in the
  weapon slot itself (abilities). Rather than enumerate them — which would never
  finish, since each patch can add more — `killfeed.py` keys on what a *name*
  is: several glyphs rather than one solid shape, with names on both sides of
  the divider. That handles unseen icons for free.
- **Two sessions are not clean comparisons, and both for the same reason: the
  killfeed and the scoreboard genuinely disagree.** `ff636d173b07` is a Phoenix
  game, `bfad2778a372` has an enemy Phoenix, and both are now fully explained by
  the same rule — see "Settled" above. Do not tune the extractor against either.

  The rule, from Grant: **Sage and Clove revive after a real death and that
  death counts; Phoenix and Kayo grant the second life before the fact — Run It
  Back ends in a self-kill or a real kill and then returns him, Kayo can be
  downed and either finished or picked back up — and those never counted.** It
  applies to the kill side as well as the death side.
- **Thin tracks are the leading indicator.** An entry seen in <=4 of a possible
  ~12 sampled frames is either barely caught or about to be split in two. If a
  new capture reads badly, count these first — 7 of 290 across the set now. A
  count *above* ~12 used to mean the opposite, two entries merged into one; the
  divider ended that and there are now none anywhere, so one appearing again is
  a signal that something upstream broke.
- **Fixed at `hud-0.8.0`: the entry tracker could not tell a merge from a
  split.** Matching by nearest slot merged consecutive entries reusing a vacated
  slot; matching by most-recently-seen shattered genuine doubles and scored
  worse. Slot plus time never contained the answer. Each entry's divider column
  does — see `killfeed.divider_of_ys`. It rules a match *out* only: two entries
  with the same killer, victim and weapon render at the same column, so equal
  dividers prove nothing.
- **An overlay can delete a killfeed entry outright.** The occlusion mask blanks
  pixels, so a row behind the shooting-error box may not reach `PLATE_ROW_FRAC`
  and the band never forms — the entry is not reported occluded, it is simply
  absent. The row profile is now measured over *visible* pixels only, which
  recovers the partly-covered bands (`223d636bf8d2` went from 14 to 30 frames
  correctly reported as unattributed), but a row almost entirely behind the box
  is unrecoverable. That is a capture fix, not a code one.
- **Scoreline OCR drops a transient extra digit.** On `9acf02f98283` the score
  reads `1 → 11 → 1` and `9 → 19 → 9` within half a second, i.e. a spurious
  leading `1`, and `verify` flags 8 violations there. Single-sample, reverts
  immediately, and unrelated to the killfeed. Clock read rate on that session is
  also low (39.7%). Worth a look when next in `ocr.py`.
- **`README.md` is stale.** It says HP, ammo and the killfeed are unbuilt; they
  are built, and it still describes stage 02 as scoreline-only. Fix it when next
  touching that area.
- **Health is not a death signal.** `hp` going unreadable was used as an
  independent death estimate and it is not one — it also goes unreadable in buy
  phase, while scoped, and while spectating. On `b3b9defb6fd7` it produced 20
  "deaths" of which most were a *teammate* dying. Don't reach for it again.

## Before ingesting any new capture

1. **Check the crosshair position.** It must sit at frame centre — (960, 540) at
   1080p. (1280, 720) means OBS is compositing a larger render onto a smaller
   canvas at 1:1 and part of the HUD is *not in the file*. Fix it in OBS.
   `valorant-16x9-crop75` exists only to salvage already-recorded captures
   (`0f08b3dc3777` is one).
2. **Set Valorant's performance stats to text-only**, not graph or both. The
   graph column covers the lower half of the killfeed ROI and cuts usable entry
   slots from six to three — losing exactly the multikills worth measuring.
3. **Turn the shooting-error readout off**, or move it out of the top-right. It
   lands at killfeed-ROI x 337-461, y 136-198, covering 59% of the victim name
   box in stack slot 3 and 26% in slot 4 — precisely where a death is read.
   Entries under it are counted as `kf_unattributed` rather than guessed, so it
   costs lost deaths, not wrong ones.
4. **Run `probe` and look at the frames.** ROI fractions are guesses until you
   have. Everything downstream is wrong until they are right.
5. **Record the minimap settings.** Only fixed + always_same + uncentered gives
   a constant minimap→world transform. Pass
   `ingest --minimap-mode "fixed/always_same/uncentered"`; it lands in the
   manifest.
6. **Label the map.** Grant is labelling maps for future captures. Geometry
   should be shared between sessions on the same map rather than re-derived per
   session, and nothing currently knows which map a capture is.
7. **Check whether the minimap has an opacity setting.** Unresolved. The widget
   being semi-transparent over the void is the single largest difficulty in
   minimap extraction; if it can be made opaque most of that goes away for
   future recordings. Same class of fix as the shooting-error readout above.

## Conventions that are load-bearing

- **Never guess a value.** A field the extractor cannot read stays `null`.
  Everything is range-checked before return — a clock of 7:41 is a misread, not
  a fact. This is what makes `checks.py` meaningful.
- **No model in stage 02.** The HUD is structured data rendered as pixels:
  threshold → connected components → geometry filter → normalise → nearest
  template. Digit templates are *mined from Grant's own footage* (`glyphs`),
  not from a font file, and committed as `.npz` keyed by profile.
- **Version stamps drive recompute.** Bump `EXTRACTOR_VERSION` → re-decode;
  `SEGMENTER_VERSION` → spans recompute from stored L1 in milliseconds;
  `HUD_VERSION` → re-read (needs pixels, so it re-decodes).
- **`segment` must never open the video.** Recomputing spans from stored L1 is
  the whole point of the L0/L1 split, and it is what makes threshold sweeps
  free. `hud` is the one stage that legitimately re-decodes.
- **Raw media is never copied.** Manifests point at where the file lives.
- **Deaths per round is not a usable invariant** — Sage resurrect and Clove
  self-revive both let a player die twice in a round.
- Cost rule from §3: if the expensive layer ever sees more than ~1% of frames,
  stage 01 is wrong. Fix gating before buying compute.
