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

**NEXT SESSION: get Grant's agent labels, then take the icon work to Lotus and
Split.** Portrait identification is BUILT and measured -- `minimap_portrait.py`,
93.0% leave-one-out over five agents, detail under "Portrait identification"
below. Two things gate what comes next and both are cheap:

* **71 of the 107 agent labels are still `claude-provisional`.** Grant ran the
  labeller on 2026-08-26 and it presented only 36 icons, because seeding the
  file with provisional rows made every seeded icon look already-done. Fixed --
  provenance now decides, not presence -- but the fix does not relabel anything:
  **`label_icon_agent.py a06f04a0059f --names ... --redo` still needs a pass**,
  and until it has had one the 93.0% is my clustering scored against itself;
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

* **label Cypher cams specifically.** `LOBE_MIN_FRAC` was added to stop a cam
  passing the motion filter, and the cam case is still UNTESTED -- nothing in the
  label set says which `other_red` marks are cams. A cam is a perfect circle, so
  it is likely a strong ring-fit candidate on coverage alone.
* **`a06f04a0059f` is +2 kills / +3 deaths** against Grant's 19/19, the widest
  gap in the set, uninvestigated. Run It Back would explain deaths running high,
  which is the direction seen, but no agent has been checked.

### State, 2026-08-26

**Screen enemy detector: unchanged and still the shipped numbers.** 91.3% /
41.2% on Ascent, 76.2% / 42.5% on Lotus (`prototypes/enemy_detect_eval.py`,
which stays the reference oracle). `enemy_features.py` splits it into
`propose()` + `gate()`, proven bit-identical frame by frame.

**CLOSED: lowering `AREA` with persistence as the net does not work**, and
neither does track-level back-fill. At the shipped floor the track rule reaches
*exactly* shipped recall with much worse precision, so back-fill recovers zero
enemies there; 120 -> 8 buys 2 enemies on Ascent and 4 on Lotus for 43-55% more
false positives. **The shape gates, not the size floor, are doing the work.**
A blob-level fitted score gives a high-precision point the AND-chain has no
equivalent for (50.0% / 85.2% cross-map) but does not beat shipped+persistence
in the useful region. Detail in `enemy_teacher.py`, `enemy_teacher_sweep.py`.

**Screen detector regression on the new capture, unfixed.** On
`2026-08-26 09-56-37.mp4` the aggregate rate is normal (0.42 det/frame against
Ascent's 0.40) but the STRONG detections are dominated by purple Ascent foliage
and a **magenta weapon skin** at a fixed screen position (36 of 125 in
x 1360-1840, y 320-480). Both follow from widening the hue band to 130. Two
things to act on: a **weapon skin is a per-session property like the outline
colour**, and the weapon mask's `y > 0.66h` bound is too low for a raised gun
model. The summary statistic hid this completely; a contact sheet took one
glance.

**Minimap: the line is reopened and the finder works.** Full arc today, all
against Grant's 164 hand labels on `a06f04a0059f`, pre-kill pool:

    seal test (hole in the blob)          0.0% recall
    ring fit, per frame                80.8% / 54.6%    uniform P 19.4%
    + persistence len>=3               76.7% / 70.0%    uniform P 19.2%
    + motion (disp>=3 or rot>=15)      72.6% / 74.6%    uniform P 29.4%

The seal test died because **the ring is a teardrop, not an annulus** (Grant):
7.3 px thick at the triangle and **1.1-2.0 px over most of the rest**. Closure
is topological, needs every pixel of that thin arc, and one break loses it --
which is exactly what half-resolution chroma does. Fitting the circle that best
covers the arc needs no closing kernel (the thing that merged adjacent icons in
every earlier attempt) and degrades gracefully. `inner_red` is required
alongside coverage, or solid red things win; the radius must NOT float, or the
fit collapses to the smallest circle through a surviving fragment.

Persistence and motion attack **different** classes -- flicker and static
decoys -- which is why both earn their place. Every cut point is fitted to ONE
session; the project's history says a new map is where these break.

**The premise HOLDS**, in the strong ring-and-triangle form: Grant labelled with
the screen beside the minimap and reports no frame with an enemy present and no
icon. A "58%, so not a proof gate" figure I published was **wrong** -- the pool
sampled 300-1400 ms before the killfeed entry, which lags the kill, so most of
that window held no enemy yet. I treated "a kill happened 1.4 s later" as "an
enemy is present now" without checking it.

**Portrait identification works, and the interior is a far stronger signal than
the ring.** `prototypes/minimap_portrait.py`, `prototypes/label_icon_agent.py`.
Leave-one-out over 71 hand-marked enemy icons on `a06f04a0059f`, five agents:

    nearest exemplar (1-NN)              93.0%
    3-NN                                 84.5%
    one median template per agent        70.4%
    roster art as the template, flipped  74.6%   (crop fitted on the test set)
    roster art as the template, as-is    63.4%   (crop fitted on the test set)

and it abstains usefully -- answering 94.4% of icons at 97.0% correct, 69.0% at
98.0%, 52.1% at 100%, on the margin between the best-matching agent and the
runner-up AGENT (not the runner-up exemplar; two views of the same player
first and second is the confident case).

Four things worth carrying forward:

* **nearest exemplar, not a per-agent template.** A single template scores
  70.4% because the same agent's icons do not correlate well with *each other*:
  the facing triangle sweeps across the interior, the map floor bleeds in at the
  rim, and the local player's icon draws over the top at close range. Averaging
  over that is a blur that matches nobody. Free clustering of the 71 icons gave
  **19 groups, every one visually pure**, merging by eye into exactly the five
  agents the roster shows plus a sixth clean group for the question marks --
  those extra groups are the appearance modes, and holding them is the job;
* **it survives 4:2:0 where the ring nearly does not.** The ring is a 1-2 px
  *colour* feature and colour is what subsampling halves; the portrait is an
  ~11 px *luma* structure. Same file, same frames, opposite outcome;
* **the descriptor is scale-free** -- a disc of 0.55x the fitted ring radius on
  an 11x11 grid, red masked out, per-channel NCC. Every grid size from 11 to 17
  scored within 1.5 points, which says the information is in the pixels the icon
  actually has;
* **the failures are background, not confusion.** All five misses are icons
  sitting over warm scenery or heavily covered by the triangle, and no agent
  pair is systematically confused (five distinct one-off confusions). Masking
  the interior better is the next lever, ahead of any change to the matcher.

**The roster names the gallery; it is not the template source.** Mining the
five enemy portraits is automatic (`minimap_portrait.py mine` finds a frame
where all five are alive by requiring the *weakest* of the five slots to be
detailed, and cuts them at the measured grid). Two jobs it does well and one it
does not:

* it turns five clusters of *players* into five *agents*, needing one frame;
* it says who is ALIVE per frame, which is an external check on identification
  with no hand labels behind it -- 70 of 71 provisional labels name an agent the
  roster shows alive at that instant, against a 77% chance rate. Over all 120
  namings of the five clusters the labelling ranks first at 98.6%, but the
  runner-up is 97.2%, one observation behind: **corroboration, not proof**;
* it is a poor template source, and the reason is Grant's (below): the enemy
  side of the roster draws its art MIRRORED. Even flipped back it tops out at
  74.6% with the crop fitted to the answers. But Grant also says the minimap
  icon is a **circular crop of the same art at a consistent size and scale**,
  which means a fixed transform exists and I swept the wrong family. Fitting it
  against an unmirrored surface -- the Tab scoreboard, which `scoreboard.py`
  already locates -- would mean **a gallery mined once per agent transfers to
  every session**, and a new capture needs no labelling at all. That is worth
  more than the 18 points.

Roster geometry, measured at 1920x1080: enemy slot k at
x = 1175 + 65.75k, y 30..70, 40 px square, slot 0 nearest the scoreline.
Survivors PACK toward the scoreline keeping team order, so slot index is not
identity -- the sequence is.

### Grant's domain notes on the minimap -- not recoverable from the pixels

* **A Cypher cam ROTATES**, and it is the **only other moving icon** on the
  widget. Perfect circle, never translates, rotation shown by the camera glyph
  turning INSIDE the ring -- **no lobe**. This corrected "a placed ability never
  turns", which was load-bearing in `motion()`. Consequence: **translation**
  holds against everything including the cam; **rotation does not reject a cam
  at all**, since rotation is read from the lobe and a cam has none.
  `minimap_ring_fit.LOBE_MIN_FRAC` floors that so a perfect circle cannot report
  a confident bearing from noise. **Still UNTESTED against a real cam** -- no
  label says which `other_red` marks are cams.
* **The triangle is the most important part of the teardrop** -- 7.3 px against
  1-2 px for the rest of the ring, so it is both the most robust part and the
  part carrying identity. A cam has a ring and no triangle.
* **The interior portrait is the same art as the KILLFEED portrait and the top
  roster portrait.** Route to identification, and it works -- see "Portrait
  identification works" above. Two corrections Grant made once it was measured:
  **the ENEMY SIDE of the roster draws the art mirrored**, so the two teams face
  each other, while **the Tab scoreboard and the minimap hold every agent in one
  orientation, always**; and **the minimap icon is a circular CROP of that art,
  not the whole bust, at a consistent size and scale**. The first explains why
  flipping the roster art gained 11 points of matching accuracy; the second says
  a fixed crop-and-scale transform exists to be fitted, which is what a
  cross-session gallery needs.
* **Omen's ultimate turns the minimap a fuzzy black for a few seconds** and is
  the ONLY ability in the game that does so; Omen also teleports globally, so
  position continuity breaks across it. Detected and abstained on rather than
  tuned through -- `minimap_temporal.USABLE_MIN = 70`, sitting in an empty gap
  (floor brightness 121 median / 131 p95 normally, 0-30 affected, p01 39).
  Round-transition fades trip it too. A frame that is unreadable must produce
  NO answer, not a confident empty one.
* **The local player's icon draws ON TOP of an enemy's** when they overlap.
  Deprioritised on Grant's call: only at extreme short range, where the screen
  detector has a large unambiguous blob anyway. It IS in the agent-label set --
  Grant flagged one Jett icon mostly covered by his own in a close-range duel --
  so identification sees the case even though detection was allowed to skip it.
* **An ally Breach ultimate draws a big RED BAR across the minimap**, and it
  occludes icons: Grant hit one covering the top of a question-mark icon while
  labelling. This is the sharpest counterexample yet to the assumption the whole
  minimap line rests on -- **red does not mean enemy**. Every red confounder
  catalogued so far (X marks, Reyna blinds, Cypher cams, pings) is small and
  roughly icon-sized, which is why area and ring-fit gates have been enough; a
  bar is large, is drawn by YOUR OWN TEAM, and lands on top of real icons rather
  than beside them. Consequences to check, none of them measured yet: it may
  survive `floor_mask`, it is the wrong shape for `fit_ring` but could still
  supply a stray arc, and for the portrait descriptor it is occlusion the red
  mask happens to remove for free. Not in any label set as its own class.

**Profile: `valorant-16x9-bigmap`.** The enlarged widget spans px 15..480 x
15..500 against the old 15..346 x 22..351, so the shipped `minimap` ROI missed
most of it. Overrides that one ROI and nothing else; borrows
`valorant-16x9`'s mined templates via `Profile.template_profile`. Its bounding
box clips the ally roster (starts x=434), so the corner x 434..480, y 15..90
holds roster HUD as well as minimap -- accepted, but anything reading this ROI
as a change signal should know it also changes when a teammate dies.

**Capture side: 4:2:0 costs a fifth of the screen detector and most of the
minimap.** Measured on a lossless round against its own subsampled twin, so only
chroma resolution moves: 65.6% of rim pixels survive, top-hat at the rim falls
43.8 -> 27.6 against a threshold of 25, detections fall 103 -> 80. On the
minimap the enemy ring seals in lossless (hole_frac 0.69) and not at 4:2:0
(0.00-0.09). Grant's call: stay on 4:2:0 and prove it there, which the ring fit
now does. `prototypes/chroma_test.py`, and item 12 of the pre-ingest checklist.


**Also unresolved and worth an eye:** some corpses carry a red outline and some
do not, and no explanation survived testing. The obvious one -- the outline fades
with age -- is unsupported but the test is underpowered, because the killfeed
timestamps deaths without locating them and so cannot age an individual body.

Last worked 2026-08-26. **Seventeen sessions ingested, seventeen with
scoreboard K/D in `checks.KNOWN_KD`, and every one carries its map.** Sixteen
are scorable (`0f08b3dc3777` is the cropped capture and has no killfeed ROI).
The store is at **`hud-0.8.1`** throughout. **Nine of thirteen are exact and the gap is 8 events across 372.** Five of the
eight are Run It Back (see "Scoreboard divergence is a finding" below), one is
the ability-kill read error, and two are new and uninvestigated — see below.
Long tracks are 0. Nothing is half-applied and the tree is clean.

**`5822b6646448` (Lotus, 13/21) is EXACT with no invariant violations**, and it
is fully out-of-sample: recorded 2026-08-26 after the widget change, ingested
and scored the same day, nothing tuned against it. It is the second capture on
the enlarged minimap and the first on a map that widget has not seen, which is
the test the icon work most needs. `c62c2b06bcfb` (Split, 13/15) is **kills exact, deaths -1**,
with 5 invariant violations and both open. The violations look like one cause,
not five: the scoreline reads a two-digit score as one digit twice
(0:06:51 12 -> 2, 0:31:43 12 -> 1) and recovers within 3.5s each time, so the
two decreases and the two illegal sum steps are the same event counted from
both sides. The 4.5s clock jump at 0:00:03 is pre-match. Neither the -1 death
nor the dropped digit has been investigated; a Split lineup has not been seen
at this widget size before. Both were confirmed `valorant-16x9-bigmap` before ingest by
measuring the floor slab — it reaches x 452 / 458 against the old widget's 346.

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
and the minimap shows an enemy only while somebody on your team can see them --
a teammate holding an angle, or a recon reveal -- plus red X marks for last-known
positions. That is *what your team knows*, not ground truth, and for decision
analysis it is the right basis: you cannot be faulted for an enemy nobody had
seen, but you can be for peeking into one a teammate was looking at. It does
mean full exposure-to-any-enemy is out of reach from a self-capture. If the
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

## What this is for (decided 2026-08-25)

**Main goal: statistical relationships, via win probability.** Not "does X
correlate with winning" over named facts -- that design is arithmetically
doomed. A round yields *one bit* of outcome, so 262 rounds is 262 bits, and
conditioning splits it to nothing; at 242 scored rounds nothing separates from
baseline except the tautological survive/die pair, and adding facts makes it
worse rather than better because each one is another chance to find noise.

Instead: estimate P(win | round state) and value every event by how much it
moved that probability. State is small -- `(alive_us, alive_them, phase,
coarse_time, side, score_diff)`. The reasons this wins:

* a round passes through eight to ten states, so 262 rounds give ~2000
  state-transition observations rather than 242 outcomes;
* WPA is continuous, so effects resolve with far less data than a win/loss bit;
* conditioning is automatic. "Win% on first blood" stops being its own question
  and becomes the average WPA of the first kill, already conditioned on state.
  A 5v1 peek and a 5v5 peek are never averaged together, which is exactly
  Grant's objection to counting exposed angles;
* it handles the post-plant rule change natively, because phase is in the state.

**Co-equal goal: film retrieval.** The largest |WPA| events *are* the list of
moments that decided a session, so this falls out for free -- and it is the
delivery mechanism for everything else. Nobody changes behaviour from a
coefficient table; people change behaviour after watching themselves throw a
4v2. Highest value per unit of effort in the whole project.

**Standing constraint: metrics must stay versioned and stable**, so the
longitudinal question ("am I improving, on what axis, over months") stays open.
The version stamps already in the store are what protect this and are easy to
break casually.

**Deferred, not dropped: mechanical coaching.** Aim, peeks, positioning --
prescriptive rather than diagnostic, and it needs a different architecture: high
sample rate, engagement-level detail, minimap geometry. It continues on its own
track. It is *not* subsumed by the statistical goal, because statistics describe
the policy Grant already plays and can never say what a different policy would
have produced. That counterfactual gap is the ceiling of the main goal.

**Blocked, for now: opponent and meta priors.** Needs enemy positions, which no
capture of one's own screen contains.

**A goal in its own right: data quality.** With no labelled data and one
customer, a number that cannot be trusted is worse than no number, and this
session produced several corrections to confident claims. Cross-checks are a
feature, not scaffolding.

Fact tables follow from this: the **engagement** is the fact and the **round**
is a dimension, because there are five to ten times more engagements and each
carries richer covariates.

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

## The top HUD says more than it looks like

Measured 2026-08-25 off `9acf02f98283`, and it collapses three open problems.

**Alive counts are directly readable.** The roster bars draw a portrait only for
a player who is *alive* -- it disappears on death -- so counting portraits gives
both teams' alive counts as a per-frame state. No integration of killfeed
events, no error accumulation. `hud_roster` already covered the friendly side;
`hud_roster_enemy` now covers the other, measured at px ~1167..1467.

**That is also a continuous audit of the killfeed.** The roster is state and the
killfeed is events, so a running killfeed total should always agree with the
roster count. Where they diverge, an entry was missed -- and unlike the
scoreboard, which gives ~50 checks a match at best and 5 at worst, this checks
every sampled frame. It is the densest validity signal available and it costs
one new ROI.

**Allies are on the left, enemies on the right.** The roster bars are green-left
and red-right, which independently confirms what `rounds.infer_player_side`
derived statistically from eleven sessions. Two unrelated methods, same answer.

**The spike icon sits in the scoreline ROI.** When the spike is planted the
round timer is replaced by a red spike graphic, centre-screen, for the whole 45
seconds -- inside a region already being cropped. That is the persistent
indicator `rounds.py` wants instead of the one-sample clock discontinuity it
currently uses, and it needs no new ROI at all.

It probably also explains a standing oddity. Clock read rates sit at 33-60% and
`9acf02f98283` is 39.7%; planted rounds have no clock to read, because the spike
graphic is where the digits would be. Some unknown share of "unreadable" frames
are not misreads at all -- they are frames with nothing to read.

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

- **One known read error, plus two unexplained**, across 372 events at
  `hud-0.8.1`. The raw gap against `checks.KNOWN_KD` is 8 events, from 24 at
  `hud-0.6.0`: five are verified Run It Back, one is the ability kill below, and
  two are `e37fdeca944f`'s missing deaths, which nobody has looked at yet. See
  "Scoreboard divergence is a finding" above before quoting the 8.
  `killfeed.py` has the per-session table.
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
- **A dead player spectates, so the main view is not theirs.** Found while
  checking ally rendering: `9acf02f98283` 24:50 shows the combat report, "SWITCH
  PLAYER", and a teammate's first-person model. Nothing currently detects this
  -- `spans` knows off/idle/active and not spectating -- and every main-view
  metric is wrong on those frames, because the camera, the crosshair and the
  hands all belong to somebody else. Aim, crosshair placement and enemy
  detection all have to exclude them. The combat report panel is a usable
  marker, and so is the killfeed: the player is dead from their death entry
  until the round ends.
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
7. **Keep the enemy highlight on, and record its colour** as an `outline:<c>`
   tag at ingest. Valorant outlines enemy models in a colour the player picks --
   red on every capture so far, but yellow and at least one other exist -- so it
   is a per-session property like the minimap mode, and nothing should hardcode
   it. Turning it off entirely would put enemy detection back into
   model-recognition territory.

   **Allies are rendered through walls in buy phase**, as a solid teal
   silhouette -- clearly visible at `9acf02f98283` 9:09. Sampling forty live
   frames found no ally silhouettes, and every green blob there had a mundane
   cause: foliage, and the spectated player's own teal gloves. So the rule is
   not "any outline is an enemy" but **"any outline in the session's enemy
   colour is an enemy"**, which is why that colour is tagged. It also means the
   enemy outline should never be set to green, or the two stop being separable.

   The outline is what makes this tractable. A saturated-red mask over the main
   view returns a few hundred pixels in a 2-megapixel frame -- enormously
   specific -- and the blobs come out human-shaped: 16x44 at aspect 2.75 on a
   standing enemy at 9acf02f98283 4:23.

   Four things carry it, and only the first is a target: a **visible enemy**, a
   **revealed** one outlined through geometry by Sova or Fade (not shootable, so
   it must stay out of aim statistics, but it is a direct measurement of what the
   player knew), a **deployable**, and a **corpse** -- bodies stay outlined, and
   a corpse is the dangerous one because it sits exactly where a real enemy just
   was, so counting it as target acquisition would look reasonable and inflate
   every aim number.
8. **Confirm the minimap is fixed, not rotating, and not side-swapping.**
   Grant sets it that way deliberately -- Valorant's defaults both rotate the map
   with the player and mirror it between attack and defence. It is the setting
   that makes map geometry shareable between sessions and bearings comparable
   across rounds, and a capture recorded with defaults breaks that **silently**:
   position extraction still returns answers, they are just rotated or mirrored.
   Same class of per-session setting as the enemy outline colour above.
9. **Record whether the weapon is left- or right-handed.** Toggleable, and it
   mirrors the view model across the vertical axis. The enemy detector masks the
   player's own weapon by region -- the one place persistence provably fails --
   so the wrong handedness breaks it in both directions at once and silently:
   the mask covers empty screen on one side, costing recall on enemies peeking
   there, while the weapon sits unmasked on the other, costing precision.
10. **Record the minimap size.** Grant is enlarging it from 2026-08-26. Icon
    extraction is resolution-bound, not algorithm-bound: at the original size an
    icon is a ~12 px ring around a portrait, the ring does not survive
    thresholding intact, and every approach tried topped out at 77-79% of frames
    that provably contain a visible enemy. A larger widget should move all of it.
    Record the size per session -- geometry and icon thresholds both scale with it.
12. **Record in 4:4:4 if the encoder allows it, and record which was used.**
    Measured 2026-08-26 (see "4:2:0 chroma subsampling costs a fifth of the
    detector" above): 4:2:0 alone destroys 34% of enemy-rim pixels and 22% of
    detections, on identical frames. The enemy rim is 1-4 px of pure chroma, so
    half-resolution chroma averages it away before the file exists — and no
    algorithm recovers what was never written. This is the same class of
    capture-side constraint as the minimap size, and the same lesson: the
    binding limit is what reached the file.

    Lossless is *not* the recommendation — 5.7 GB per round is ~226 GB for a
    match. NVENC HEVC (and AV1 on newer cards) supports 4:4:4 at ordinary
    bitrates; that is the setting worth changing. Keep the lossless round as a
    reference capture, because a controlled A/B needs an undegraded source and
    it is the only one that exists.

13. **Check whether the minimap has an opacity setting.** Unresolved. The widget
   being semi-transparent over the void is the single largest difficulty in
   minimap extraction; if it can be made opaque most of that goes away for
   future recordings. Same class of fix as the shooting-error readout above.

## Conventions that are load-bearing

- **Never test an absolute level against this HUD.** It is composited over
  live scenery, so any absolute threshold eventually measures the world instead
  of the widget. This is not a series of unrelated bugs, it is one property of
  the game, and it has now produced: the killfeed row profile merging warm walls
  into a band; the minimap's void defeating background differencing, a
  persistence mask and every colour statistic; the roster bar's white health
  pips vanishing against a white wall; washed-out killfeed entries; and the
  victim's plate reading as enemy everywhere because scenery past the entry's
  right edge is warm. Every fix has had the same shape — **measure inside the
  structure, require coverage, compare relatively.** Density within the row's
  own entry, not across the ROI. Slot texture against neighbouring slots, not a
  threshold. A plate column that spans the band's height, not one that is merely
  the right colour. Reach for that shape first; it has never once been wrong.

  **But relative does not mean instead of absolute.** Structure answers "is this
  a thin rim against its surroundings"; level answers "is this the colour we are
  looking for". They are different questions and neither substitutes for the
  other -- the plate test above needs coverage *and* colour, and it is right to.
  Reading this convention as "replace absolute with relative" produced an enemy
  detector that fired confidently on a grey line beside a cyan panel, because a
  top-hat is a local peak finder and every image has local peaks. Adding a
  permissive absolute floor back underneath it nearly doubled precision. The
  floor's job is only to reject things that are not the colour at all; it must
  never be the test that decides what counts as red *enough*, which is the
  mistake that started the whole sequence.

- **The enemy outline is red *through magenta*, not red.** Measured at 47 hand
  labels on 9acf02f98283: the rim sits at OpenCV hue 171-179 and 0-1, 88% of rim
  pixels inside `(h < 10 | h > 170)`. But every miss that failed on colour sat at
  hue **132-160** with *zero* pixels in that band -- while still carrying `a*`
  173-207 and saturation 243-255. They are not faint, they are the wrong hue.
  The cause is tinting: **anything that colours the model shifts the rim toward
  magenta while leaving `a*` high** -- smoke the enemy is standing in, and Reyna's
  ult, which renders the model purple. Widening the band's lower edge from 170 to
  130 took recall from 69.6% to 91.3% for under two points of precision.

  The direction matters as much as the width. Orange scenery -- a confirmed false
  positive on a building at 38:03 -- lives just *above* hue 10, so the band must
  grow downward into magenta and stay tight on the orange side. Widening
  symmetrically, which is the reflex, buys the false positives and not the misses.
  Outline colour is also a **player-toggleable setting** (yellow exists, and at
  least one more), so this band is right for these captures, not universal; it is
  a per-profile value the moment a capture uses a different setting.
- **An ablation is only valid for the configuration it ran in.** Dropping each
  gate in turn showed the saturation and `a*` floors to be completely inert --
  removing either changed one false positive out of a hundred. The obvious
  conclusion, that they were dead weight, was wrong. They were inert only because
  the *hue* gate upstream was already rejecting everything they would have caught.
  Widening that band made both live again, worth 20 false positives between them.
  Deleting them on the ablation's evidence would have given back a fifth of the
  precision the widening was for. Re-measure a gate after changing anything
  upstream of it; "contributes nothing" is a statement about a configuration, not
  about a gate.
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
- **Commit whenever a result is verified. Standing authorisation -- no need to
  ask.** The bar is "a measurement reproduces" or "a section is written", not
  "the task is finished". A session that reached 93.5%/35.0% then carried 500
  insertions of verified work in the working tree while running destructive
  edits against it; a patch that split the file on a section marker discarded
  every function in it, and the work survived only because it could be
  reconstructed from earlier in the same conversation. Small commits also make
  `git show HEAD:path` a real recovery tool -- it has already restored notes
  deleted by a careless rewrite once.
- **A parse check is not a verification.** `ast.parse` reported "parses clean"
  on the gutted file above, because a module containing only a docstring is
  valid Python. Syntax checks cannot see missing behaviour. After any structural
  edit, re-run the thing and confirm a **known number** comes back -- for the
  detector that is TP 43 / FN 3 / FP 80. That check is only meaningful because
  the number was measured before the edit, so measure first, then edit.
- **Keep "Picking up" current, and keep it SHORT. Standing instruction from
  Grant (2026-08-26): do this unprompted.** It is the first thing read next
  session and it decays fastest, so a stale one actively misleads. Detail does
  NOT belong there -- it belongs in the prototype docstring next to the code it
  describes, and in the commit message, both of which are searchable and neither
  of which goes stale silently. One session left it at 560 lines and it had to
  be cut by two thirds.

  **On the trigger, honestly: there is no context-usage readout available.**
  Grant asked for "around 94% of the session limit"; that cannot be implemented
  literally, because nothing exposes a percentage to work from. Guessing at one
  would be worse than not having it. Use what IS observable instead:

  * **rewrite it when a result changes what the next session should do first.**
    This is the real trigger and it is not an end-of-session activity at all --
    a finding that closes a line or opens one should update "Picking up" as part
    of recording it, in the same commit;
  * refresh it when several verified results have landed without one;
  * refresh it when Grant signals winding down, or asks for a handoff.

  The durable protection is the convention above it -- commit whenever a result
  is verified -- because that survives a session ending abruptly, which no
  end-of-session ritual can. Treat the handoff as a summary of commits already
  made, never as the only place a finding is written down.
