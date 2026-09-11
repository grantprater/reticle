# Reticle — working notes

Where the work stands **today**: the handoff into the next session, and the
defects that are live rather than standing. `CLAUDE.md` carries what stays
true across sessions — the conventions, the domain rules, the mistakes worth
not repeating. This file carries what is true this week, and it is read on
demand rather than loaded into every session.

Read it when picking up unfinished work. Update it in place; let it go stale
rather than let it grow.

Split out of `CLAUDE.md` on 2026-08-27.

## THE KILLFEED DRAWS THE AGENT, AND NOW SOMETHING LOOKS AT IT -- 2026-09-11

**`killfeed.portrait_observations` extracts both portraits from every entry.**
The reference art for all 29 agents was already in the store and already loaded;
this module had only ever used the portraits as landmarks -- the thing at the
ROI edge that is not a name.

**Matched inside the lineup for the side its own plate names, it is exact.**
Against the ability TRAY, which names the player's agent on a different surface
by a different rule and knows nothing about the killfeed:

    within the side's lineup     93 / 93   player-involved observations
    open against all 29 agents   62 / 93

`b7d24102a6f6` is the whole argument: open set it picks Tejo over Skye on 30 of
31, and the ally lineup corrects every one. The portrait is a weak 29-way
classifier and a perfect 5-way one, which is CROSS-REFERENCE BEFORE TUNING
paying out -- gate the channel on what another channel already knows instead of
fitting the detector.

**The geometry took three attempts and each was rendered and looked at.**
Anchoring on the plate runs put the box on the weapon icon. Anchoring on the
largest plate span ran off the entry into the scenery, because warm scenery
reads as the enemy plate's red -- the same thing that used to merge background
into the band above. What works: walk outward from the name to the first
sustained gap in plate-or-text, and take the WIDTH from the official art, which
is 256x128 and therefore two band heights. No constant is fitted to a session.

**The descriptor has one definition now.** `appearance.composition` is the
10x3x3 HSV histogram `scoreboard` had inline; `killfeed` calls the same
function rather than carrying a second copy, and the plate is masked OUT --
unmasked, every ally portrait resembles the ally plate rather than the agent.
Note that `lineup` still uses a DIFFERENT composition from `prototypes`, and the
agent gallery is built with it. The two are not interchangeable and unifying
them would move every measured lineup result at once; `BACKLOG.md` carries it.

**Limits, stated rather than implied.** Truth here is the tray, a reader and not
an external record. The 93 are repeated views of a smaller number of distinct
deaths and this run did not separate them. 37% of victim portraits are clipped
by the killfeed ROI's right edge. And nothing yet names the other nine players:
the reader emits a descriptor and a side and refuses to name, because naming
needs the lineup and a reader that borrowed it would collapse two witnesses into
one.

**Measured after the fact, and it tempers the 93/93: per FRAME the portrait is
not reliable, per ENTRY it is.** The first stability run scored 0 of 0 because it
sampled SPACED frames, so no two observations landed inside one entry. Sampled
consecutively -- 8 bursts of 12 frames on each of 3 sessions, 52 multi-frame
runs:

    within the side's lineup   41/52 runs constant, 545/589 frames with the
                               run's own majority (92.5%)
    open against 29 agents     38/52 runs constant, 531/589 frames (90.2%)

So a fifth of entries would give a different name depending on which frame was
looked at, while nine frames in ten agree with their entry's majority. The 93/93
was player-involved entries only and reads as stronger than the channel is.

**That constrains the adjudicator rather than the reader.** It accumulates over
an entry's lifetime and takes the majority, exactly as `lineup` accumulates
scores across a session instead of an argmax per frame. Recorded as the
`killfeed-portrait` entry's negative boundary, so the next session cannot build
on a single-frame claim without `reticle ownership` saying not to. How much of
the instability is a band still sliding into the stack -- `_trusted_wx` already
records a half-formed band reading a wrong divider for a frame or two -- is not
separated, and accumulating fixes both.

**Next is the owner, not more evidence.** `agent-identity` in `ownership.toml`
is still declared unowned, and its `blocked_by` now says so: what is missing is
the module that holds a named claim per entity, weighs the portrait against the
top bar, the tray and the self icon, and keeps the disagreements. The player has
named the shape of the endstate -- one producer of agent events, with the
ability and ping adjudicators consuming it for `is_alive` rather than
re-deriving it.

## THE MARGIN NOW MEASURES THE ASSIGNMENT -- 2026-09-11

**`lineup.adjudicate` replaces `Lineup.verdict`'s arithmetic, and the
interesting result is the two names it TOOK AWAY.** The margin is now the
optimal assignment's total minus the best total attainable with the slot
forbidden its agent, so the alternative is one the uniqueness constraint
permits. Over 190 slots in 19 sessions, old against new on IDENTICAL score
matrices, refusals went 82 -> 73: eleven named, and two un-named.

**Both losses are `043bafca271a` enemy slots 0 and 4, and they are the fault
worth having found.** Both slots look most like Breach. The old margin scored
Breach against Breach's own runner-up, cleared 0.07 on that, and then printed
the name the assignment gave -- *Raze* for slot 0. A confident name resting on
a different agent's evidence. Under the new rule the two fight each other for
Breach, both collapse to 0.019, and both refuse. `best_guess` carried the same
fault on 12 of 190 slots, reporting an argmax the constraint had already thrown
out; it now reports the assignment's pick.

**What did NOT happen.** On `7010b3d62460`, the only session with a recorded
lineup truth, nothing changed: slots 0 and 3 stay refused at 0.054 and 0.013,
because Chamber and Breach are claimed by no other slot and there was no
constraint to exploit. So the correctness prediction is UNTESTED rather than
passed, none of the eleven newly named slots has a truth to check against, and
nine of the eleven sit within 0.03 of a `MARGIN_MIN` fitted on one lineup of
five slots. The honest claim is that the rule stopped measuring the wrong
quantity, not that coverage is solved.

**The verdict is now pure over a stored observation.** `adjudicate` takes the
(slot, agent) matrix, and the matrix is written beside the verdict -- about 3 KB
a session. Changing this rule cost a seven-minute decode of nineteen sessions
because the observation had been thrown away and only the conclusion kept; the
next change costs nothing. The 19 stored lineups were rebuilt at 300 sampled
frames, 2286 -> 3395 contributing, and backed up first. Complete SIDES, the unit
alive-set differencing needs, went 4 -> 7 of 38. Sessions complete on BOTH sides
remain 0.

**Next, and the player named the shape of it: the other identity channels are
built and unfed.** The gallery already loads three surfaces per agent --
`agent_icon`, `killfeed_portrait`, `minimap_portrait` -- and scores all three
against the TOP BAR only.

    top bar        wired, and the only channel naming agents today
    ability tray   wired, names the player outright, one slot of ten
    minimap self   `Lineup.add_self` exists and HAS NO CALLER anywhere; the
                   self-icon witness the player identity claims to combine is
                   never fed, so the tray and the top bar decide alone
    scoreboard     `scoreboard.portrait_observations` emits descriptors and
                   refuses to name; nothing consumes them
    killfeed       locates both portraits as structural landmarks and never
                   matches them, though the reference art is already loaded

The killfeed is the one to take first. It names agents on BOTH teams, it fires
on every death rather than only at 5v5, and its portrait is the same feature the
matcher already uses. It also carries the state transition the lineup cannot see
-- 56 of the 79 refusals had no named candidate from any witness, and the
witness that would name them is drawn every time someone dies.

## OWNERSHIP IS DECLARED AND CHECKED -- 2026-09-11

**`ownership.toml` says who may DECIDE each question, and `doctor`'s OWNERSHIP
check holds it against the code.** 47 entries, 26 infrastructure modules, every
one of the 64 modules placed exactly once. An owner claims its entry in its own
docstring with an `[owns:<id>]` token, so an entry pointing at a renamed output,
an owner that stopped claiming its contract, a new module nobody classified, a
`defers_to` whose import went away, and a `shipped` owner still reaching
`prototypes/` are ERRORs. Read one with `reticle ownership which agent died`.

**The route that was asked for was a hand-written index, and the registry
replaces it.** Three arguments decided it. A prose restatement of 63 module
boundaries is the tangle `domain/*.toml` exists to replace, and the owners'
docstrings already carry the argument better -- `track.py` has a *What this is
not* section, `minimap.py` says ally identity is future work and not silently
assumed, `minimap_lifecycle.py` says the motion law is `track`'s. An unchecked
declaration is satisfied by declaring everything, which `architecture.toml`
argues in its own header. And the index pass itself, which classified all 63
modules accurately, did not notice the thing a check found immediately.

**What the check found: `reticle/adjudication/` was in no layer at all.**
`architecture.py` globbed `reticle/*.py`, and a glob cannot see a directory, so
four modules sat unplaced and `adjudication.ability` imported `ability_timeline`
-- an eager edge up out of adjudication into entities -- with nothing reporting
it. The blind spot is fixed: modules are placed by dotted name, relative imports
resolve against their own subpackage, and `from reticle import x` is counted,
which it never was. The edge is gone rather than blessed: `ability_timeline` and
`ability_coverage` are pure over stored observations, which is this repo's own
definition of `adjudication`, so they moved down a layer and the `entities`
entries left behind are the command adapters they always were.

**Five questions are declared UNOWNED and print on every run.**
`agent-identity`, `death-victim`, `ability-owner`, `ability-detection`,
`fact-subject`. That is the north star, on screen, with its blocker attached:
`agent-identity` blocks three of the other four, and its own blocker is lineup
COVERAGE rather than perception. Nothing in this change moves that work; it
stops the next session having to rediscover where it lives.

Superseded by this: `PROVISIONAL_INDEXING.md`, whose per-module content is now
the registry, and `docs/IDENTITY_INDEX_DESIGN.md`, which is now
`docs/OWNERSHIP_INDEX.md` and describes what exists. Three boundaries the pass
raised and did not resolve -- `minimap_lifecycle` against `round_lifetimes`,
`reconciliation`'s missing ceiling, and `ability_phases.ally_deaths` living in a
command adapter -- are in `BACKLOG.md` with their triggers. 477 tests pass;
`doctor` reports 13 findings and zero errors.

## PICKING UP -- 2026-09-10, STEP ONE IS BUILT AND LINEUP IS THE BLOCKER

**`prototypes/roster_identity.py` names the living, and running it named its own
blocker.** The alive SET per side per instant, by name. The packing is the
obstacle -- survivors shift left, so slot index is never identity -- and the
ORDER is the solution: survivors keep team order, so the k occupied cells are a
k-SUBSEQUENCE of the side's five known agents, at most ten candidates for a
five-slot bar. That turns a 29-way classification into a 5-choose-k ordered
assignment and reuses `lineup`'s composition matcher and gallery unchanged.
`shrink_events` differences the set to say who left, which is step two's hook.
Fifteen tests cover the assignment and every refusal.

**CORRECTED, same session, by the player: portrait identity and its
multi-channel corroboration are RIGHT and I credited the wrong cause.**
`Lineup.player` combines three witnesses -- the ability TRAY, which names the
agent outright, the TOP BAR, which proposes five candidates, and the SELF ICON,
which ranks among them -- keeps ABSTAINED distinct from DISAGREES, and refuses
to pool scores answering different questions. a06f04a0059f was decided by the
tray at 128/186 votes. `verdict` already applies uniqueness per side with
`track.assign`. Composition matching transfers at 83.5% held out. None of that
is the problem.

**The measured gap, over 79 refused slots in 19 stored lineups:**

    12   pairwise ties `assign` ALREADY BROKE -- the margin is taken from the
         raw per-slot ordering, order[0] against order[1], computed WITHOUT the
         assignment, so a slot is refused where the constraint resolved it
    11   resolvable only by CROSS-SIDE elimination, which is forbidden
    56   neither candidate named anywhere -- these need a second witness

So the fix is not more frames or a looser margin. It is (a) measure the margin
against the best alternative CONSISTENT WITH the assignment, and (b) feed
`add_self` and `add_tray` to all ten slots rather than to the player's own,
which is the only slot they currently constrain.

**A wrong elimination avoided by asking rather than assuming.** Two teams MAY
field the same agent -- [domain:rounds/agent-uniqueness] -- so a ten-slot
assignment across the match would have named those 11 slots wrongly. `assign`
staying per side is already correct.

**The coverage figures stand; the cause does not.** Over the 19 sessions with a
stored lineup, ZERO have both sides complete:

    ally side    3-5 named of 5
    ENEMY side   0-3 named of 5
    33 further sessions have no lineup at all

So a06f04a0059f names 0 of 40 sampled frames and refuses each one --
`roster_incomplete:3/5` ally, `2/5` enemy. Every downstream step assumes a named
roster, and none of them can run on a side with an unnamed slot without
guessing.

**Two bugs the first run exposed, both worth remembering.** It reported a median
margin of 1.000: at five alive there is exactly ONE candidate subset, so the
runner-up scores zero and the most trivial case was reading as the most
confident one. And an unnamed roster slot scores zero against every cell, so
every subset containing it loses and the assignment silently preferred the NAMED
slots -- reporting a named agent alive in a cell whose true occupant lineup had
declined to name. That is exactly the named-wrong-one the plan forbids, so an
incomplete roster now refuses the whole side. `doctor` also caught a third: the
function was called `read_session`, which `lineup.py` already defines, and the
DUPLICATE check made it an ERROR. Renamed rather than blessed.

**NEXT, in this order, and it is verdict logic rather than more perception:**

1. **measure the margin against the ASSIGNMENT**, not the raw top two. Twelve
   refusals are ties already broken. It changes a shipped reader's output, so it
   wants its own run against `checks.KNOWN_KD` -- deliberately not attempted at
   the end of a long session;
2. **extend the two existing witnesses past one slot.** `add_self` and
   `add_tray` constrain only the player's own slot today; 56 refusals have
   neither candidate named anywhere and a second witness is what they need;
3. only then the coverage knobs -- `Lineup.add` accumulating solely from a FULLY
   ALIVE side, which starves a side rarely at five and is checkable from stored
   roster counts with NO decode; and `MARGIN_MIN = 0.07`, provisional and fitted
   on five slots of one session.

Then step two: difference the alive set at each killfeed death time to name the
victim, scoring against the killfeed and `checks.KNOWN_KD` and storing the
disagreements.

450 tests pass; `doctor` has eight findings and zero errors.

## PRIOR -- 2026-09-10, DEATHS WITH IDENTITY IS THE PRIORITY

**The player set the ordering plainly: deaths as events with identity and
location is the point of the whole pipeline, and getting to identity in events
matters more than anything else queued.** The plan is in `BACKLOG.md` under
*DEATHS AS EVENTS WITH IDENTITY AND LOCATION*. Read it before anything else.

**Verified, not assumed: no stored column carries identity on any channel.**
`l1/roster` is COUNTS, and its occupied slots are a contiguous run because
survivors pack, so slot index is never identity and a count can never name a
victim. `l1/hud` carries TEAM masks. `l1/minimap` has positional `ally0..3`
slots over a track identity that already churns. Death times are
scoreboard-verified and ally death location is solid via the X mark; identity is
simply absent.

**The anchor already exists and I had not connected it.** `reticle/lineup.py`
identifies roster and scoreboard portraits by COMPOSITION and writes
`slot -> agent` with scores, margins and explicit refusals on a thin margin, and
most sessions have a stored lineup. It runs once per session. Running its matcher
over the OCCUPIED roster slots per sampled frame gives the SET of agents alive at
t for both teams, and differencing that set at each killfeed death time names the
victim -- two independent sides, so the disagreements are the output worth
storing.

That also repairs the broken link in the question that opened this: *the deadlock
is now dead* is not readable from the killfeed, which gives a team mask, but an
agent leaving the roster's alive set is exactly that fact. And with a victim
named, `xmark_eval`'s standing caveat dissolves -- *closest of several will
always look better than a single detector's true accuracy* is the identity
problem stated from inside the location problem.

**The artifact is an EVENT STREAM CARRYING IDENTITY, and it is now the north
star in `CLAUDE.md`.** The player's own shape for it: at x our ally Breach was at
(u,v); at x+1 at (u+du,v+dv); at x+2 they used their C at (n,m) with orientation
(r,t). Identity is the primary means by which rules of MOVEMENT and EXISTENCE
can be verified -- a position with no identity cannot contradict a speed limit,
a continuity rule, a teleport, or the origin-event invariants. The annotated
match is the CHECK on that stream, not a separate goal. Deaths are the entry
point rather than the goal: identity is sharpest there, because two independent
channels bracket a death.

**Enemy death location is BETTER than I recorded, and the correction is the
player's.** [domain:minimap/enemy-death-mark]: for a GUNFIRE kill both the
enemy's icon and the X are visible around the death, because somebody had to see
the victim to shoot them. The mark is missing only where nobody saw them --
killed by ally utility, or fell off the map -- and those narrow the position
without naming it. My standing note that visibility was unmeasured and absence
meant nothing is corrected in place in `prototypes/CLAUDE.md`.

Separating the causes needs only a BINARY on the killfeed's weapon-icon slot,
gun against ability mark -- far cheaper than the per-ability template bank the
backlog prices for identifying WHICH ability. That slot is already located as
the divider on every entry and never classified. Read the other way it is a
VISION WITNESS: a gunfire entry says a teammate saw the victim at that instant,
which bears directly on the unmeasured persistence window.

**Also recorded: the fact registry has no SUBJECT**, so what was built is a list
rather than the wiki-shaped graph the player asked for. Filing by `kind` groups a
Cypher cam with the audio ring and separates two facts about one device. The
minimal fix is a `subject` from identifiers the pipeline already uses, plus a
`given` field for the conditional facts, which are prose today and therefore
unscorable. Not started, deliberately: a graph over an event log with no identity
has nothing to check itself against.

435 tests pass; `doctor` has eight findings and zero errors.

## PRIOR -- 2026-09-10 latest, the repaint was refuted and a06 explained

**The a06 repaint buys nothing, and it was measured before it cost the player
anything.** Overriding the recorded r=7 to 10, 12, 14 and 16 -- writing to no
label file -- leaves the audit bit-identical at every value: 72.7% base recall,
90.9% union recall, 1.9% precision, the same single miss. **The matching radius
was never what loses a06's icons**, so my "a06's paint is the blocker"
diagnosis was wrong and there is no repaint to do.

**Also corrected: the icons are r=12, not the 20-25 I claimed.** Rendering all
11 painted icons at 5x against reference circles put r=12 on the sonic sensor's
disc edge and r=7 on its inner bullseye, which reconciles with
[domain:minimap/icon-extent-by-family] -- 24 px across IS r=12. The three files
carrying the wrong number are fixed; the superseded claim in the PRIOR below is
marked rather than rewritten.

**What actually limits a06 was already a domain fact nobody had connected to
acquisition.** [domain:minimap/dim-devices-defeat-the-residual]:

    a06's 11 painted icons     n    median contrast   median filled fraction
    acquired                  10          240                  0.46
    missed                     1          173                  0.11

173 is inside the recorded dim mode of 122-175 against the live mode's
231-241. A live sensor is near-black on grey floor, fills solid, dt 6.6-10.0 px;
a dim one is mid-grey on grey floor, its residual is speckle, filling changes
nothing, dt 1.0-3.2 px. `core` recall on a06 caps at 54.5% at the most
permissive floor swept, so no threshold reaches it.

**That is the measured reason the pool keeps `base`** -- previously only an
observation that it helped. `core` needs a substantially filled disc; `base`'s
area-gated centroid survives speckle. And the miss is anticipatable rather than
chaseable: `device_deactivation.py` links dim devices to a preceding ally death
at pooled p=0.002 over 73 devices, both channels already stored.

**The player set two labelling conventions, now in the tool rather than in my
head.** `r` is the ICON DISC ONLY and extent past it is a REGION; a
multi-segment object is one icon PER NODE plus a region for the span. Both are
in `paint_icons.py`'s docstring and its on-launch help overlay -- which is where
two earlier passes failed to find the radius keys at all.

**Next: DIVERSITY, not a06.** a06 is nine sonic sensors and two mesh nodes; d95
is about six Cypher objects on one map with one agent. Painted frames on more
maps and more agents are the mining review's own next step, and the dim state
argues for a retained low-contrast channel that RANKS rather than gates.
Building that on one missed icon would be fitting to n=1.

413 tests pass; `doctor` has seven findings and zero errors.

## PRIOR -- 2026-09-10 late, the area band was fitted on players

**The cap was the other half of the acquisition failure, and independent labels
settled it.** `minimap_dynamic` is a different human pass with a different
proposer; over 831 rows on three scale-1.0 sessions, box extent separates the
families -- a player icon is 13 px across at the median, an ability icon 24, a
region 27. `ICON_AREA_REF`'s cap of 400 reference px is a disc **22.6 px
across**, below the ability median, because it had been fitted where the
evidence was: on players. It is now `(10, 500)`, the knee of the curve, and the
measurement is [domain:minimap/icon-extent-by-family].

Pre-registered and confirmed on every clause:

    d95cfad5693a base recall   77.1% -> 93.8%    precision 7.6% -> 9.1%
    d95 candidates              515  ->  523     fragmented targets 8 -> 3
    a06f04a0059f base recall   72.7% -> 72.7%    (predicted unchanged)
    union recall           100% / 90.9% unchanged on both

Seven of d95's eight `component_too_large` misses sat on components of 205-251
px against a cap of 203. The audited attribution was right, and recovering them
cost 1.6% more candidates -- a claim no threshold tuned on these same frames
could have made. `prototypes/object_proposals.py` held a FORKED copy of the same
constant at (10, 400) and now imports the one definition.

**Domain facts now live in `domain/*.toml` and prose cites them.** Fourteen
seeded facts, every one cited by its consumer, `doctor`'s DOMAIN check making a
dangling citation an ERROR. See the global constraint in `CLAUDE.md` and
`reticle domain --check`.

Two things measured and declined, both in `BACKLOG.md`: a `doctor` check for
forked CONSTANTS fired 17 errors on a clean repo and was reverted, because a
checker that fails on everything gets ignored; and `map_shade.stamp()` hashes
raw bytes, so the LF copy of `wiki_map.py` in the working tree made twelve
current shades report stale all session -- the one-line fix forces a rebuild of
baked geometry, so it waits for a deliberate one.

**Next: the a06 repaint, and it needs the player.** a06's `ability_paint` rows
mark r=7 discs on icons of **r=12**, so the matching radius is smaller than the
icon and `core` scores 45.5% there against 100.0% on d95. Rendering all 11 at 5x
corrected an earlier claim of 20-25 px radius here: r=12 puts the circle on the
sonic sensor's disc edge, and 24 px across is exactly what
[domain:minimap/icon-extent-by-family] measured. So the missed components of
1189-1417 px are the icon (area ~452) welded to adjacent art, not a huge icon. Until then
a06 is a lower bound on acquisition and an upper bound on nothing, d95's
diversity is about six distinct objects on one map with one agent, and no single
channel should be selected. Invoke `labelling-pass` before painting.

395 tests pass; `doctor` has seven findings and zero errors.

## PRIOR -- 2026-09-10, the baked-geometry baseline and two new channels

**The geometry cleanup cost nothing and the proposer now clears its floor.**
Rerunning `proposal_audit.py` with both sessions on baked `(map, profile)`
geometry -- the rerun the mixed-dependency correction demanded -- moved a06 from
254 proposals to 244 and its precision from 3.1% to 3.3%. Every other figure is
identical; d95 is unchanged because it already read baked geometry. The retired
per-session static contributed nothing this measurement could see, so the earlier
numbers were wrong in dependency, not in value.

**Inspecting all 14 misses found one failure shape.** Twelve of 14 sit on a
component too large for the area band that contains exactly one painted icon:
the icon welded through a 1-2 px neck to a viewcone, a trapwire line, a
neighbouring icon, or bright map structure. The area gate was rejecting an icon
for its neighbour's extent. Two things about the mask follow: an icon is a ragged
RING, because its mid-grey interior sits inside the lighting band, and a ring has
no distance-transform core -- peak dt under a matched icon and a missed one are
the same 2-3 px. Fill the enclosed holes and the icon becomes the disc it is.

`proposal-audit-0.3.0` now scores an acquisition POOL. On `d95cfad5693a`:

    channel   recall  precision  candidates   (48 icons, 12 frames)
    base       77.1%      7.6%       515
    neck       97.9%     19.5%       249
    core      100.0%     66.7%        72
    all three 100.0%      6.0%       836

`core` is distance-transform peaks on the hole-filled residual -- 9x the base
channel's precision at perfect recall, 6 candidates per frame against 43, median
centre error 1.207 px. On `a06f04a0059f` it collapses to 45.5% and `base` is the
only channel finding seven of that session's ten, so `mine_icons.propose` takes
the UNION, `POOL = ("base", "neck", "core")`. A union cannot lower recall;
proposals per frame on `c40d950031bb` rise 23.7 -> 44.4, which mining tolerates.
Replacing `base` with `core` is **measured and declined** in writing: six
distinct objects on one map and one agent do not justify dropping the channel the
other session depends on.

One defect nearly buried this. The first `fill_holes` passed `4` positionally to
`cv2.connectedComponents`, where it binds to `labels`, not connectivity; the
background stayed 8-connected, leaked diagonally through every thin ring, and
filled nothing. With `connectivity=4` the core channel went 89.6% -> 100.0% on
d95 and 27.3% -> 45.5% on a06, untuned.

**a06 cannot fairly score this yet, and that is the next task.** It is the
reference `valorant-16x9-bigmap` widget; its missed components run 1189-1417 px
against an area band capping at 400, and the painter marked r=7 discs on icons
of 20-25 px radius, so the matching radius is smaller than the icon.
[CORRECTED 2026-09-10 later: the icons are r=12, not 20-25 -- see the current
PICKING UP section. The claim is left here as what was believed at the time.]
`ICON_AREA_REF = (10, 400)` is wrong for that profile's real icon sizes --
re-measure it against the widget, do not tune it against these labels.

Next, in order: repaint a06 with radii that match its widget and widen the
painted truth to more maps and agents; re-audit; only then choose a single
channel or touch the descriptor. Read
[MINIMAP_MINING_REVIEW.md](docs/MINIMAP_MINING_REVIEW.md) first.

378 tests pass; `doctor` has eight findings and zero errors.

## PRIOR -- 2026-09-10, per-session map state removed and guarded

The invariant is now explicit and enforced: session pixels may measure only
minimap widget dimensions/placement. Production readers and prototypes obtain
base-map pixels, floor, lighting references, and detector backgrounds only from
baked `(map, profile)` geometry. The retired `Store.read_static_map` /
`write_static_map` API and runtime median builders are deleted. Bare-video
prototypes require an explicit geometry key.

`doctor` now fails on retired cache calls, runtime `static_map`/`median_widget`
calls, `.static.npy` paths, or capture-median construction outside two named
exceptions. `minimap_geometry.py` may derive pixels only to build the shared
artifact; `clip_preflight.py` may median a capture only for widget dimensions,
placement, and orientation. Twenty legacy `masks/*.static.npy` files remain
untouched and are reported as ignored; deleting them is a separate destructive
cleanup. Full suite: 367 tests pass.

The proposal-audit figures immediately below are history. The rerun they asked
for is done, and it is reported in the `PICKING UP` section above: the retired
session static changed nothing the measurement could see.

## PRIOR -- 2026-09-10, proposal acquisition audited and below floor

**The revised design's first measurement is complete.**
`prototypes/proposal_audit.py` scores the colour-free residual proposer against
the existing exhaustive, unseeded `ability_paint` frames with one-to-one matches
and explicit miss reasons. It creates no labels and changes no reader. Focused
tests cover assignment and failure attribution.

The predeclared 80% acquisition floor failed on both sessions:

    session          frames/icons  proposals   recall  precision  miss cause
    a06f04a0059f       12 / 11        254       72.7%     3.1%    2 large, 1 small
    d95cfad5693a       12 / 48        515       77.1%     7.6%    8 large, 3 displaced/claimed

All 14 missed icons still overlap lighting-residual support; NONE are
`no_residual_support`. Eight d95 targets and two a06 targets are fragmented.
The residual channel therefore contains evidence in this limited set, but one
area-gated centroid per connected component is not an adequate proposer. The
d95 short demo read baked `ascent__valorant-16x9` geometry, but a06 read a
retired per-session static. Do not compare or extend these figures as a current
baseline.

Next: inspect the missed support, then add a complementary decomposition/centre
proposal over the existing residual mask and re-audit UNION recall. Do not change
the descriptor or clustering yet. Treat precision as candidate volume: 3.1-7.6%
is tolerable only for mining and must remain bounded. Validation diversity is
small (a06: Sonic Sensor/Barrier Mesh; d95: repeated Cypher devices plus self),
so neither session establishes general inventory recall.

## PRIOR -- 2026-09-10, mining critique and revised comparison plan

Read [MINIMAP_MINING_REVIEW.md](docs/MINIMAP_MINING_REVIEW.md) before the next
mining change. It supersedes the interpretation and next-step list below, while
preserving the first-run measurements. Documentation only; no detector changes,
new labels, or new perceptual experiment.

The miner runs, but proposal recall and cluster purity remain unmeasured.
Position spread separates neither classes nor origins: use position for instance
association and appearance across instances for family discovery. The fixed
portrait-interior descriptor omits outer glyph shape, color, and extent. Static
occupancy can erase real persistent entities. Contrast should initially rank
candidates with a retained low-contrast audit channel, not become a hard gate.

Next: freeze evaluation sessions and annotation scope; audit proposal recall and
centering; compare the current miner with full-glyph/tracklet-based deterministic
mining and a fine-tuned YOLO challenger at stated labeling budgets. Learned Stage
02 observations are a proposed architecture expansion, not an implemented change
to the no-model rule. Select by held-out extraction accuracy, coverage, and human
effort, not cluster count. Keep lifecycle inference and independent truth separate.

Review-time diagnostics: `doctor` six findings, zero errors; all 20 stored minimap
datasets stale against `minimap-0.6.0`. Pin producer versions and refresh required
inputs before a future comparison. The review did not rescan them.

## PRIOR -- 2026-09-10 late, first mining run (interpretation superseded)

The measurements below are historical. Claims that the proposer is validated,
that position spread establishes noise or origin, and the contrast/spread-first
next-step sequence are superseded by the review linked above.

**`prototypes/mine_icons.py` is the general instrument the appearance plan
specified and never described.** Propose from the lighting-band residual inside
the slab with NO colour key, subtract what is always foreign, describe with
`minimap_appearance.describe`, leader-cluster on masked NCC, then relate
clusters by rotation. It runs end to end. The proposer holds: 2391 proposals
over 101 frames of `c40d950031bb` at 1 Hz, 23.7 per frame, all describable.

**Three of its four steps are refuted by their own first run**, and
`docs/MINIMAP_APPEARANCE_MATCHING.md` is corrected rather than left standing:

* the static subtraction is INERT -- 14 px, 0.0% of the slab, where the plan
  promised the bulk of the tail;
* clustering on appearance alone FRAGMENTS -- 254 clusters, 67 recurring, the
  large ones with a POSITION SPREAD of 60-84 px, which is a bag of similar
  noise rather than a class;
* the rotation relation has no NULL and fired on 93 pairs. Give it one.

**The finding is that POSITION SPREAD separates them, and it was printed by
accident.** Cluster 11: n=37, spread 6.8 px, contrast 150. Cluster 14: n=30,
32 px, 126. Noise: 60-84 px at contrast 45-70. That is the entity model's
`origin` falling out of the data -- a fixed object recurs in one place, a
player recurs everywhere, speckle recurs nowhere at low contrast.

Do this next, in order:

1. gate proposals on CONTRAST before describing them;
2. cluster on appearance AND recurrence behaviour -- spread and contrast --
   rather than on the descriptor alone;
3. give the rotation test a null, then re-ask whether the spike's two states
   are a discovered pair;
4. only then anchor clusters to the HUD plant and to killfeed deaths for their
   meaning, which is the step that turns a cluster into a thing.

**Do not build another detector per icon family.** That is what this pass
replaces, and a session went into `ability_disc` before the player stopped it.
A class-specific detector is a candidate CHANNEL of the proposer, never the
reader.

### Also this session

**`doctor` has a PROMOTE check.** It reads `notes/predictions.jsonl` and
reports every prototype named there that no `reticle/` module uses. Not wiring
was the silent default: `check_unwired` sees only modules already inside
`reticle/`, and `check_orphan` exempts anything a document names, so writing a
result up was what made it invisible. Declining now costs a `"wire": "no"` and
a `wire_reason`. The rule is in `CLAUDE.md`'s global constraints. Every
prototype it listed carries a decision; the ability line is triaged in
`BACKLOG.md`.

**Wired:** `icons` returns `inner_v`, the interior GREY that `fit_ring` always
computed and this function dropped -- the feature that separates the player
from the spike, where `inner` cannot. `minimap-0.6.0` writes `widget_drawn` and
`belief.absent_instants` reads it, so a refusal is finally distinguishable from
an absent widget; older rows fall back to the ally proxy and a missing column
reads as UNKNOWN, never false.

**Fixed:** `prototypes/minimap_dynamic.py` imported `reticle.geometry as _G`
inside one function while three others referenced it, so the whole ability line
raised `NameError`. It had been dead long enough that nothing noticed.

**Measured and rejected:** a peak-based disc finder. The pre-registered
prediction held -- local maxima are monotonic in the response floor where
thresholded blobs ridge, confirming merging past `AREA_MAX` as the cause -- and
the painted frames killed it anyway: 4.0% and 1.7% precision against the blob
finder's 100% and 32.3%. **Do not choose an operating point on labels that
cannot score precision**; the candidate-anchored sweep made it look like a
modest trade.

**Domain, recorded:** the spike glyph is a rounded equilateral triangle with a
thin black outline, a black dot inside a BLACK CIRCLE, and three dots toward
the corners. That circle is why the ring fit accepts it -- the spike really is
a keyed annulus around a dark interior, so every *fit the ring better* proposal
is dead. It inverts on pickup, base down on the ground and base up carried, in
one frame, unboundedly many times a round. Own-team icons are always visible;
enemy-team entities are drawn only inside team vision, and a reveal shows
PLAYERS ONLY -- not the spike, not abilities -- so for those the gate is
exceptionless. Use the DRAWN light in `lighting.py`, not the raycast.

360 tests pass; `doctor` has six findings and zero errors.

## PRIOR -- 2026-09-10 earlier, the self reader has an accuracy figure at last

**The headline: 87.49% of the self reader's ACCEPTED positions are the player.**
200 labelled fits on `c40d950031bb`, reweighted by stratum: 8.13% are a
different object and 4.38% are two things the widget cannot separate. On the
same session `fidelity-check` reports 0.9917 cross-rate agreement. That is
consistency; this is accuracy; the gap is the standing rule made concrete, and
everything built above the reader inherits it. Score with
`prototypes/self_fit_eval.py [--features]`.

`reticle/belief.py` (`belief-0.2.0`, `reticle belief SESSION`, stored data only)
answers every sampled instant with a `Fix`: observed, interpolated, held or
unresolved, a physical radius, a reason, and `rests_on`. It takes evidence as
arguments -- `voids` from round bounds, `reachable` from the art floor. Nothing
stores or reads a `Fix`. **It is built on contaminated anchors and stamps an
observed fix at 2 px, which is false for one in eight.** Fix the reader first.

Measured and NOT shipped, all in `BACKLOG.md`:

* arc coverage separates the wrong accepts and nothing else does -- the player
  sits at 0.38 [0.28-0.56], every wrong class at 0.28-0.30. A gate at 0.35 cuts
  wrong-object to 1.1% and costs 36% of correct positions;
* gating only where a read ally is near leaks, because 3 of 9 spike cases sit
  in the `clear` stratum: **no channel reads the spike**, so the confuser is
  invisible to the confuser test. See *The bootstrapping floor* in
  `docs/ADJUDICATION_DESIGN.md`;
* the fit flips between the portrait and the CARRIED-SPIKE BADGE 3.2 px to its
  bottom left -- confirmed with no labels, from a bimodal step distribution;
* self fits land on yellow site paint at twice the ally rate. `site_mask`
  already derives the zones from the static map;
* a constant-velocity hold does not beat a stationary one, but the test is
  scored against contaminated reads, so it is not settled.

Untested risk: arc coverage depends on bearing (61-67% of bearings 150-240 deg
against 22-23% at 330-30), so raising the gate biases refusals by facing rather
than losing at random. The facing angle was not kept in the feature cache.

**The plan now covers every icon that can be taken for another**, not the self
icon alone: *The occluder inventory* and *Icon-class order of work* in
[docs/MINIMAP_APPEARANCE_MATCHING.md](docs/MINIMAP_APPEARANCE_MATCHING.md). It
adds the glyph track G1-G5, running G1 before the numbered Step 3, and it opens
on a measurement: **the spike is inside the SELF COLOUR KEY.** By the player's
own labels, a 5 px disc at the accepted fit is 0.117 self-keyed at the ten
spike positions against 0.062 at the 179 player ones -- and that is a lower
bound, since the player is an annulus and the spike is filled.
`prototypes/key_collision.py` measures it off the label sheets with no decode.

**Then the player described the glyph, and it explains the confuser outright.**
It is a rounded equilateral triangle, thin black outline, a black dot at the
centre inside a BLACK CIRCLE, three more dots toward the corners. At this scale
that is a keyed annulus around a dark interior -- what `fit_ring` exists to
find, and what the player's own icon is. Both pass `inner_max`: the player
0.000, the spike 0.156, the gate 0.25. **The spike really is a ring, so every
*fit the ring better* proposal is dead, arc coverage included.** The separators
are the silhouette, the interior VALUE -- `fit_ring` computes `inner_v` and
`icons` throws it away -- and the dot pattern.

**The state discriminator is the flip, and the first two attempts at it both
failed.** The spike is yellow in every state, carried by a teammate included,
so the ally key holds no spike at all; on the ground the base sits at the bottom
with a corner up, and carried it is the same glyph rotated 180 degrees and
slightly smaller, in a one-frame transition, unboundedly many times per round.
That is a per-frame shape test separating a fixed object from a badge on a
player, with no association and no second channel. Three predictions were
pre-registered and all ten labelled instants were sought at native rate.
**None could be scored: `self_mask` does not deliver the glyph as an object** --
1 to 5 keyed components within 8 px, a single component on 2 of 10, largest
8-36 px. The glyph is plainly visible in the raw pixels, so this is a KEY
problem, not a resolution one, and G1 must be built on the glyph's own colour
band or a masked luma fit rather than on `self_mask` components. The second
attempt, a row profile with the corrected geometry, failed on contamination --
base-up on 8 of 10, with exactly 8 keyed pixels in the top row of five separate
cases, which is a window clipping site paint rather than a base. Segment the
glyph before measuring its shape.

**Own-team icons are always visible**, so on the attacking half the spike's
state is fully observable at every instant and a missing icon is a detector
failure. The vision gate below is scoped to the enemy half only.

**Stop asking for prose and mine the inventory instead** -- *Infer the
inventory; do not be told it*, in the plan. Everything above except the game
rules is a property of pixels the capture already holds, and the precedent
already worked on the harder case: `prototypes/minimap_portrait.py` clustered
71 enemy icons on their interiors into 19 pure groups that merged into exactly
the five agents on the roster plus a sixth for question marks, nothing tuned,
and when the agent NAMES were written down wrong no measurement changed. So
G1's step one is a mining pass, and the proposer for it already exists and was
thrown away: `minimap_occlusion.foreign_fraction` computes a per-pixel *is
something drawn here* mask against the map's own lighting band, reduces it to a
scalar and discards the mask. **Measured on four frames inside the slab, at a
10.0 margin: 3.5-5.5% of slab pixels foreign, 11-37 components in the icon
band**, covering the icon clumps and also objects no colour key would find.
The tail is bigger than the real icon count and much of it is furniture, which
is removable because it is STATIC -- accumulate a per-pixel foreign RATE and
subtract what is always there. That tail is acceptable because a miner needs
RECURRENCE rather than per-frame precision: artwork repeats with a consistent
appearance and speckle does not. Then describe and cluster with
`minimap_appearance.describe` and `minimap_portrait`'s clustering, relate the
clusters by rotation and scale, and anchor them to the plant instant and to
killfeed deaths. The spike is the test case: three states, three clusters, two
of them a 180-degree rotation the pass should DISCOVER. What stays a question
for the player is a one-word cluster name or a yes/no on a rule, never a
description.

**Reintroduce the vision gate on enemy-team entities.** An enemy-team entity is
drawn only where our team can see it -- enemy icons and the enemy-side ground
spike alike -- which for enemies is a necessary condition rather than the
correlate it is for allies. The rule is not new: it is already an origin-time
event in the entity model and §11 there calls the collective viewcone the term
four enemy-half invariants are written in. Nothing consumes it. Use the DRAWN
light in `lighting.py`, not the raycast in `cone.py`, whose area over-claims
~3x. New backlog entry above *Reject ally icons that have no light beside them*.

Next, in the order that unblocks the most witnesses:

1. a crude spike reader -- it is the largest confuser and the missing witness.
   G1 in the plan above states the three states, what is already built and
   unwired, and the four predictions to predeclare;
2. photometric vicinity via `prototypes/minimap_occlusion.py`, gating ACCEPTS
   rather than explaining refusals, as the stand-in until 1 lands;
3. the raised gate PLUS the belief layer, measured end to end against these
   same labels: observed accuracy up, observed coverage down, believed coverage
   roughly held. Neither half is worth shipping alone;
4. a `widget_drawn` column in L1, folded into the re-decode that rebuilds the
   18 sessions still on `minimap-0.4.0`.

Also closed this session: minimap appearance matching (Step 2), as a measured
negative -- both the standalone and the joint appearance/geometry paths, and
the overlap story that motivated them, refuted at 1.06x by
`prototypes/minimap_occlusion.py`.

360 tests pass; `doctor` has seven findings and zero errors. The new PROMOTE check listed five measured-but-unwired prototypes and four are now decided in `notes/predictions.jsonl`; the survivor is `ability_disc`, which SHOULD ship and is blocked on two named things. See *`reticle/` has NO ability detector* in `BACKLOG.md`. Labels are in
`<store>/labels/self_fit/`, clips in `<store>/notes/refusal-clips/`, and every
prediction and outcome is in `notes/predictions.jsonl`.

## Prior P3 context -- killfeed persistence and the Step 1 ring fit

The two rules the last handoff asked for landed and both were measured before
and after. `reticle fidelity-check` is the gate; the run is pinned at
`notes/p3-fidelity-20260909-adjudicated.json`. 320 tests pass; `doctor` has six
findings and zero errors.

**1. Persistence went into the adjudicator, and the killfeed gate passes.**
`read_killfeed` still reports what one frame held, because one frame is not
where a camera wipe can be told from an entry. `checks.track_entries` refuses
what never persisted, and `checks.entry_presence` is the entry count of record.
Two bars, both stated in samples as well as milliseconds:

    KF_ENTRY_MIN_LIFE_MS   1500. A track counts when it COULD have been on
                           screen that long -- `span + 2*step` -- so a low rate
                           is not refused for resolution it never had. 614
                           player entries at 2 Hz over seventeen scored
                           sessions allow it; the shortest spans one interval.
    KF_TRACK_GAP_STEPS     40, with the existing 2500 ms cap, whichever is
                           shorter. At 2 Hz the cap binds and nothing moves. At
                           native it has to bind: with 2500 ms alone one track
                           ran 503.5-511.5 s, absorbing seven scattered wipe
                           bands in four slots and then the real entry 1.8 s
                           after them.

Measured on the frozen windows, reader unchanged: confuser false-positive
instants go **11 -> 0 at native, 3 -> 0 at 15 Hz, 3 -> 0 at 10, 6 -> 0 at 5 and
3 -> 0 at 2**; presence recall is unchanged at every tier; and every tier from
native to 2 Hz counts **the same eleven entries**. Scoring the twenty stored
sessions against `checks.KNOWN_KD` is byte-identical.

The classes never came close, so no threshold was fitted anywhere: eleven real
entries span 4733-8017 ms and eleven wipe tracks span 0-667 ms.

**Four false positives survive at every rate, and w1 holds an UNLABELLED
WIPE.** I first read these as an onset-granularity quibble. They are not. The
killfeed ROI at 185567-185717 ms goes to a uniform 190.3 with **zero green and
zero white pixels** and 17115 red, then decays back over ~600 ms:

    t_ms   roi_mean  green    red   white  glyphs
    185533    138.7   4709   6005  496740      29   entry, divider 176
    185567    190.3      0  17115       0       0   flat wash, whole ROI
    186000    167.7      0   9266  311100      17
    186183    147.4   1227   7806  322065      20   same entry, divider 176

The entry either side is the same one -- divider 176, victim run (293,317). So
this is a THIRD camera wipe in this session, sitting inside a **trigger**
window, and the reviewed field's "no entries at 186000/186200/186400" is a
person correctly reporting they cannot see a row through a wash. The frozen
contract calls that stretch clean; it is not. w2's single survivor is the same
shape at 506517 against a reviewed 506620.

**The player's rule fixes both without a threshold, and it is better than the
persistence bar.** A killfeed entry renders in a fixed ORDER -- plate, then
furniture (divider and portraits), then glyphs -- and unrenders in reverse. At
186167 the band arrives with its final divider column and a victim name run
already up, and only the killer run missing, for exactly one frame. So:

    a band that appears WITH FULL CONTENTS in a single frame violates the
    ordering and is a wash;
    a band that loses its contents while keeping its plate AND its divider is
    one entry blinking, not two.

Neither test has a number in it. Build it in `analyse_killfeed`, which already
computes every term.

**2. `pick_self` no longer scores worse at a higher rate.** The gate was
`RUN_PX * scale * (step_ms/1000) * 2` and nothing else -- 1.50 px at 60 Hz,
narrower than the icon fit's own p90, so it refused the player's own icon and
the pick fell through to the largest blob on 9.4% of consecutive steps at 60 Hz
against 1.9% at 2 Hz. It is now floored at `2 * FIT_ERR_PX` (the fit's pair
budget, the same 4 px `minimap_lifecycle` spends) and takes the REAL elapsed
time since the previous position was read, dropping `prev` past `GAP_MS`.
`FIT_ERR_PX` moved to `minimap.py`; `track.FIT_ERR_PX` still resolves.

    minimap self agreement   15 Hz 0.9030 -> 0.9363, 10 Hz 0.9068 -> 0.9438,
                             5 Hz 0.8766 -> 0.8816, 2 Hz unchanged at 0.9085
    reads that moved         native 6.6%, 15 Hz 0.9% -- exactly its ten
                             widget-absent frames -- and none at 10, 5 or 2 Hz

**3. What is left of the minimap failure is the self ring FRAGMENTING, and the
fix is icon MATCHING rather than anything about rates.** On **all 69**
disagreeing frames at 15 Hz and **all 47** at 5 Hz, the reference's own answer
sits in the candidate list the cheaper tier held: two to seven self-coloured
blobs a median 10.3 px apart, which is the ring's own diameter.

`pick_self` was fed by `self_rings` -- connected components of the yellow key,
one CENTROID each -- so every arc of a broken annulus votes as its own icon and
an arc's centroid sits ~r from the true centre. `self_icons`, the ring fit that
has been in `minimap.py` all along and that `overlay.py` already uses, collapses
them: on 10 of 11 sampled disagreeing frames it returns exactly ONE icon.

    182800  key 55 px  3 blobs 20@(267,156) 8@(274,162) 40@(263,167)
                       -> 1 icon (267.0,162.0) r6.0

Measured through the frozen gate, three ways:

    pick_self fed by          15 Hz     10 Hz      5 Hz      2 Hz
    self_rings (shipped)     0.9363    0.9438    0.8816    0.9085
    self_icons               0.9825    0.9949    0.9874    1.0000
    self_icons else blobs    0.9520    0.9349    0.8992    0.9512

**Do not fall back.** The mixture is worse than either pure choice and its worst
disagreement blows out to 71-74 px, because two tiers then differ by WHICH
estimator ran on that frame -- and the two estimators are biased ~r apart by
construction. Either fit or refuse.

**Step 1 landed in `minimap-0.5.0`.** The real reader now supplies fitted
`self_icons`, allows position when bearing is unreadable, requires opaque-slab
support, and never falls back to blob centroids. The rerun in
`reticle-store/notes/appearance-step1-after.json` moves agreement to **0.9917,
0.9885, 0.9849 and 0.9939** at 15/10/5/2 Hz. Eligible coverage is **0.7237 at
native and 0.7101-0.7301 at candidate tiers**: the predicted 27.7% refusal is
real. `fidelity-0.2.0` now prints that denominator so matching refusals cannot
masquerade as a complete PASS. Step 2 must recover coverage with appearance.

### Do this next, in order

Design follow-up: [minimap appearance matching](docs/MINIMAP_APPEARANCE_MATCHING.md)
consolidates the proposed portrait/shape, tinted-region and animation matchers,
with staged implementation and independent evaluation gates. Step 1 is now
measured above. Portraits stay upright while facing geometry rotates; the
prototype's 93.0% is provisional clustering-based evidence, not independent
accuracy. The current P3 ordering below remains in force.

**The theme is that measured work never reached the readers.** Three separate
things below were built, scored and left in place: `self_icons` sits in
`minimap.py` and only `overlay.py` calls it; `prototypes/minimap_portrait.py`
reached 93.0% and nothing in `reticle/` imports it; the ordering evidence
`analyse_killfeed` needs is already computed there. None of this is new
research. `doctor`'s UNWIRED check catches a module in `reticle/` that no CLI
command reaches, and catches none of these -- a prototype named by a doc, or a
second better path inside a module that IS wired, both read as healthy.

1. **Match the icon instead of keying its ring.** The self ring is a **1-2 px
   COLOUR feature** and this capture is 4:2:0, which halves colour, while the
   icon interior is **~11 px of LUMA carried at full resolution** --
   `prototypes/minimap_portrait.py` measured exactly that. We key on the most
   degraded channel in the file and ignore the best preserved one, which is why
   the annulus breaks into arcs at all. Three steps, cheapest first:

   * **DONE, `minimap-0.5.0`:** feed `pick_self` from `self_icons`, with no fallback;
   * close the 27.7% of frames the fit refuses by matching the icon's own
     mined appearance, `minimap_portrait`'s exemplar gallery applied to self;
   * match over ROTATIONS and keep the argmax rather than building rotation
     invariance. Invariance discards the bearing, which this project wants, and
     the bearing argmax is already recorded as following centre jitter -- one
     joint fit for centre and bearing settles both.

   **Mine the exemplars from FORCED CORRESPONDENCES**, not from frames the
   current detector called clean: one detection in frame t-1 and one in frame t
   have no alternative explanation, which needs no tracker and no labels. It is
   how `FIT_ERR_PX` was measured. Anything else scores the detector against
   itself.

   **Normalise the background out first.** `geometry` stores `lo_gray`/`hi_gray`
   per pixel per map and `lighting.py` classifies which state a frame is in, so
   a semi-transparent icon can be matched against a KNOWN two-state background
   rather than unknown live scenery. That is what makes fuzzy matching
   well-posed here at all.

   `nearest exemplar, not a per-agent template` is the load-bearing result to
   carry over: 93.0% against 70.4% for an average, because within-agent
   variation exceeds between-agent distance.

2. **Put the render ORDER in `analyse_killfeed`**, per the rule above. It ends
   the wipe problem in the per-frame column, which is what `capabilities`
   withholds `hud.killfeed_entry_count` for, and it needs no threshold.

3. **Re-review w1 and re-freeze the contract.** `p3_reference_windows.json`
   records 185.6-186.2 s as clean and it holds a wash. A frozen evaluation with
   a mislabelled window is worse than none -- it is where the four surviving
   false positives come from. Either mark the stretch as a confuser or drop
   those instants; do not adjust a tolerance to absorb it.

4. **Cut and review frozen windows on a second session** -- another map, another
   capture. `capabilities` withholds `hud@transition` for want of coverage
   rather than for a defect, so this is what promotes it. Use
   `tools/wipe_scout.py` to pick the confuser windows out of the store instead
   of watching video.

Do not claim adaptive savings from tier selection: the measured saving so far is
the transport's. Do not proceed to P4/P5.

## The first P3 comparison, 2026-09-09 -- superseded above except for the transport

`reticle fidelity-check` compares the shipped readers against reference fidelity
on six frozen, source-reviewed windows (`reticle/frozen/p3_reference_windows.json`,
`c40d950031bb`: two trigger, two audit, two confuser, 79.4 s). `reticle
capabilities` prints what the run licensed. Its killfeed and minimap findings
are answered in the section above; `notes/p3-fidelity-20260909.json` is the gate
as first measured and `notes/p3-fidelity-20260909-after.json` the same windows
after the empty-band refusal.

**The one finding that still stands is the transport, and it is worth keeping.**
The cost was never the frame count. `sample_multi` grabs the file from the start
to the last timestamp requested, so over one 10 s window at 850 s it cost 49.74 s
at 60 Hz and 48.80 s at 2 Hz -- 28.6x fewer frames for 1.9% less time.
`decode.sample_windows` seeks to the window: 2.51 s and 1.10 s. Plans now report
`covered_span_seconds`/`reach_seconds` and `execute_plan` picks the transport. On
the fixed transport the tier finally matters: 60.24 s native against 7.47 s at
2 Hz over the frozen set.

The reading that produced the empty-band refusal is kept because it is the
domain fact, not the fix: the player corrected me twice and both landed. Ability
kills DO carry both portraits and an ability icon -- 13:14 renders
`HungryHamster5 [ability] Me` and reads `death` for 1.6 s straight -- so
`no_icon` was never the ability-kill signature, and `no_divider` never fires at
all in this session.

## PICKING UP -- 2026-09-09, pipeline architecture implementation through P3 foundation

Read [docs/PIPELINE_REVIEW.md](docs/PIPELINE_REVIEW.md) for the current P0-P5
sequence and error taxonomy. Verified handoff: 271 tests pass; `doctor` has six
findings and zero errors; `status` has four stale **minimap L1 datasets**. Those
four are detector tables, not geometry caches. Current official-art geometry is
authoritative and `doctor` reports no stale-geometry error. The old Sunset replay
used for the P2 behavior check merely predates that rebuild; rerender derived
observations before using it for visual/geometric acceptance.

Implementation has started in that order. Commits `0865d94` through `26e4c48`
close the first sampling contract, separate appearance/state, publish immutable
phase and gallery revisions, condition the gallery on appearance, retain bounded
identity histories through overlap, and add an executable acquisition-planning
contract. Bright-only Deadlock
identity reaches 0.6053/0.5833 balanced across the two held-out directions but
does not beat shuffled labels; dim-only is not evaluable at the minimum per-class
coverage. `reticle acquisition-plan SPEC.json` chooses the cheapest declared
temporal tier meeting each request tolerance, distinguishes opportunity from
conflict selection, refuses unsupported/budget-limited requests, and produces a
shared-decode route plan without opening media. `execute_plan` drives registered
readers over those routes and records actual frame coverage.

P3 is a foundation, not accepted adaptive performance. The capability
declaration, the frozen windows and the same-window comparison the next
paragraphs called for all landed later the same day -- read the section above
this one for what they measured. Reduced spatial tiers are deliberately rejected
until separately validated. P0 still needs the cross-channel capability matrix
and broader artifact migration; P2 still needs fresh-geometry visual review plus
independently attributed later evidence. Do not proceed to P4 semantics or P5
coaching as if those gates were complete, and do not claim ability recognition
from these results.

## PICKING UP -- 2026-09-09, the ability line A-F, and what it actually says

Six commands, all stored-data-only: `ability-coverage`, `ability-timeline`,
`ability-entities`, `ability-gallery`, `ability-phases`, `ability-capture`.
251 tests, `doctor` 6 findings 0 errors.

**Milestone D's gate FAILS and that is the result.** Phase-binned temporal shape
does not separate `deadlock:sonic sensor` from `deadlock:barrier mesh` across the
two matches: 0.5749 balanced at permutation p=0.3085 one way, 0.4646 at p=0.6368
the other, below the shuffled median. Per-class recall flips with the direction
of the split, so what it tracks is a session offset.

**Do not quote those figures as a property of temporal shape.** The sensor class
is BIMODAL -- 24 labelled positions at contrast 122-175 against 47 at 231-241,
with a 56-level gap holding nothing -- because a deployed device DIMS when it
deactivates. A single median centroid represents neither mode. Conditioning the
gallery on activation state and re-running is the next real step on D.

### Do this next, in order

1. **Condition the gallery on phase and re-run D.** `ability-phases` already
   segments every traced entity; the gallery does not consume it.
2. **Run `prototypes/label_grouping.py`** -- 1,381 queued questions, Deadlock
   first. `d` toggles DIM, `1`-`5` group (same digit = same entity), `e` = was
   already there. Append-only and resumable; `--redo` revisits.
3. **Per-agent death**, to sharpen the deactivation cross-reference from "an ally
   died" to "the OWNER died". Needs ally-side portrait identification; the
   scoreboard portraits are already mined for both matches.

### What the corpus will not support, and why

Exactly ONE held-out contrast exists. Every ability but Deadlock's pair appears
in a single session, so a leave-one-session-out split has nothing to train on.
Detector appearance features and held-out evaluability are DISJOINT: scalar
features live only in the demo sessions, and the two real matches that support a
split have no candidate file at all. That is structural, not a tuning problem.

The capture queue asks for **8 cards, 120 recorded seconds**, each naming its own
discriminator, beside 749 review items that ask for no recording.

### Load-bearing facts found this session

* label x/y are ROI-RELATIVE, indexing the crop the session's PROFILE defines --
  verified by residual, 98.5 against 6.3 over 114 labels;
* a labelled object can live under two seconds (an Omen smoke IN FLIGHT), so a
  filmstrip must sample the labelled instant, not an even spread;
* a whole-tray simultaneous drop is a transition wipe, not four casts. All twelve
  in the spectator Cypher sessions are artifacts, already flagged suspect;
* a device dims when it deactivates. Dim devices sit closer to a preceding ally
  death than live ones: pooled 17.5s gap, **p=0.002**, n=73;
* an entity TRANSFORMS. `ability-phases` models it; grouping now offers
  `position_persistence` beside onset proximity, and they disagree on 39 of 105
  use claims -- exactly the transforming case.

## PICKING UP -- 2026-09-09, scoreboard credits are observations

`scan` now stores versioned, context-free scoreboard row observations: K/D/A,
credit OCR evidence, local-row highlight, source boxes, and portrait composition.
`audit` adjudicates repeated credit candidates and preserves conflicts. On
`7010b3d62460`, 4,500 observations produced 203 resolved credit states and 512
candidate disagreements. The two inspected source frames recovered all 20 credit
values before the strict confidence gate.

Do not attach identity in `ScoreboardReader`. The architecture is `reader ->
detector -> adjudicator`; display slots can move, and the top roster compacts
after deaths. The next economy step is to make lineup, minimap, and killfeed
portrait channels emit keyed identity claims, then let reconciliation associate
them with scoreboard observations. Automatic ledger derivation waits for that
stable player link.

## PICKING UP -- 2026-09-08 late, geometry comes from the ART now

**Read this first: every measured number in the section below it was taken on
the DERIVED map geometry and none of them reproduce.** The twelve geometries
were rebuilt from the official art at the end of this session, so the round
exports in `~/reticle-store/notes/sunset-round6-*` are all against stale
geometry. Re-render before quoting anything from them.

### The promotion that should have happened weeks ago

`BACKLOG.md`'s "Promote the WIKI MAP into `minimap_geometry`" was settled on
2026-09-06 with the trigger *"the next time a session's geometry is built"*.
That trigger fired on 2026-09-08 -- all twelve were rebuilt -- and was walked
past, and the session then spent hours patching the derived rule's false
positives one at a time. Scored on the same painted referee:

    session                 area   recall    prec     IoU
    Ascent  derived        37.8%   100.0%   78.8%   78.8%
            ART            30.4%    97.2%   95.2%   92.7%
    Lotus   derived        40.1%   100.0%   77.9%   77.9%
            ART            32.8%    99.4%   94.7%   94.2%

`derived & ART` = ART and `derived | ART` = derived, so the derived rule's
extra ~7% of the widget was almost all false positive: the location banner,
the widget rim, the close skirt, the barrier doorways.

**Both halves are done.** `minimap.art_floor` is the mask;
`minimap_geometry.classify_art` is the labels, mapping the six art classes to
the six geometry classes, so `cone.passable_from` no longer reads a
classification derived from gameplay frames. 10 of 12 keys are on ART;
`summit__valorant-16x9` stays derived because its art places at IoU 0.663
against 0.888-0.954 for the rest (`geometry.MIN_ART_FIT`). Every npz records
`label_source`, and every round export records `floor_source`.

**The stamp now covers the art path**, which is what was actually broken: it
fingerprinted `floor_mask` only, so the first art change did not mark anything
stale and nothing recomputed. `art_floor` and `classify_art` are in it now, so
touching either makes all twelve npz stale as a `doctor` ERROR.

**`tools/guard_geometry.py` + `.claude/settings.json`** assert the wiring on
every Write/Edit and at Stop. The player's reason for wanting it is on record
and is fair: a convention in prose did not hold. Verified both ways -- passes
on the tree, exits 2 on a tree with the promotion removed. NOTE: it needs
`/hooks` opened once, or a restart, before the watcher picks it up.

### The barrier cut law, honed by the player, and where it stands

*"The ally portion includes the ally spawn, which is either the top or bottom
of the map depending on attacking/defending (attackers are bottom on these
non-rotating maps). The ally portion is entirely separated from the neutral
portion, which in turn is entirely separated from the enemy portion, which
includes the enemy spawn."*

That is `barriers.territories` and `barriers.chain`: exactly THREE regions in
a PATH, with per-bar attribution of which pair each bar separates. The old
test was `len(regions) >= 2`, which a wrong set passes easily.
`barriers.reachable` excludes the two ~1,170 px pockets Sunset's floor already
has before any bar is painted -- counting those as territories made a correct
nine-bar set read as five.

**Sunset has NINE spawn barriers, not the six that are baked**, and the player
said so outright. Two were missed by the persistence rule (0.75 is above the
knee; 8 are stable across 0.25-0.60) and **one is DIAGONAL at -41.6 degrees**,
missed because the shape filter measured straightness in an axis-aligned
bounding box: axis aspect 1.17, rotated aspect 2.76, right in the range of the
other eight. Use `cv2.minAreaRect` or `barriers.axis_of`, never `w/h`.

**They are NOT baked, deliberately.** The nine do not satisfy the chain law on
the art geometry, and `barriers.seal` says why -- a bar spans its doorway, so
the closure is an extension along the bar's own axis until it meets
impassable ground, needing no growth constant:

    bar 0 (233,186)   WALL@7   OPEN@40   <-- does not span its opening
    bars 1-7                   sealed at both ends within 0-6 px
    bar 8 (150,352)   diagonal, not measured on the right axis

So the flood is not leaking around bars 1/3/7 -- the player's first guess, and
the measurement says they each seal. It is getting through bar 0. Next session:
measure bar 8 on its PCA axis, work out whether bar 0 is a fragment of a longer
bar or not a spawn barrier at all, then bake and re-render. **Do not reach for
a growth constant to make the count come out at three.**

### Everything else from this session, in one place

* **The enemy channel was gating on a FITTED CENTRE.** An arc fits its centre
  at `p + r*n`, so red in the widget's transparent surround places a centre
  3-9 px inside the slab. It is not an ability: the player turned to face
  Sunset's brick architecture and `red_mask` went 613 -> 40,851 px while the
  count ON the slab held at 90 -> 114. `ring_supported` scores the ring's own
  pixels; enemy entities 166 -> 15 over the session, and the two bursts the
  player reported at 0:30 and 0:37 went to zero.
* **The barrier channel gates the enemy channel** while the bars are drawn:
  531 -> 159 observations, 158 after `live_start` unchanged.
* **`Tracker.principal` held a stale track** -- 56 of 774 samples had a self
  icon detected and no box drawn. Sticky and refusing now: 81.0% -> 72.6%
  reported, worst step 312 px -> 13.9 px, nothing over 20.
* **`round-lifetimes-0.5.0`**, appearance is comparative. The old `>= 0.85`
  absolute bar sat above the signal (same ally 0.708 median, different allies
  0.213, and they overlap), so it never fired. Ranked against the alternatives
  it agrees with position-truth on 97.9% of 1,748 unambiguous pairs.
* **The doorway phantoms are the barrier doorways** -- objects with >=30
  observations are 16x enriched within 8 px of one -- and the cause is
  photometric, not geometric: `sd_hi` at those pixels is 8.3-23.6 against a
  whole-slab median of 0.75, because the barrier is drawn there every buy
  phase and the two-state fit merges two states into one. **Not fixed.** The
  clean answer is to fit the reference on live-phase frames only.
* **Still 85 allies for 4.** The comparative appearance gate helps a little
  (85 -> 75 at the shipped margin) and is not the whole answer.
* **The player's conservation idea, not yet built:** N icons enter an overlap,
  N leave, unless a death or round end accounts for one. It needs no new
  architecture -- the temporal model is already there -- what is missing is
  merge/split bookkeeping inside it. It would have caught the self being lost
  under a KAY/O icon at 0:44 and re-emerging as `ability? 308`.

## Superseded -- 2026-09-08 evening, the widget furniture patches

The session's goal was **full-round visual labelling and bounding, clearly
correct**. Four defects were found by measuring the shipped round rather than
by reading code, and all four are fixed, committed and re-rendered. Entity
hypotheses for Sunset R6 fell **1,671 -> 1,551** with no agent, ping or ability
on real map lost, and the two channels that were most visibly wrong -- the
location-name banner and the buy-phase enemies -- are gone entirely.

### The artefact to look at

    ~/reticle-store/notes/sunset-round6-final-20260908

79.0 s, 4740/4740 frames, 0 ms stalled, `lighting-0.3.0`,
`round-lifetimes-0.4.0`, `full-round-0.10.0`. The three earlier directories
from today (`-reconciled-`, `-clean-`, `-gated-`) are the A/B steps and can be
deleted; each isolates one fix.

**The `lighting-0.3.0` gap named in the previous handoff is closed.** The
re-run produced `sunset-round6-lighting03-20260908` with the version stamped in
`provenance.json`, and the entity set was byte-identical at 1,671 -- so the
monotonic lit read changes the cone evidence and not the detections. Re-measured
under it, with unknown pixels no longer counted as dark, **the median
unexplained lit floor is 52.0%, not the 41% recorded under `lighting-0.2.0`**.
The residual got worse when it was measured honestly. `unknown_px` is 64,891
against 4.25 M comparable, so unknown is not what moved it.

### What was wrong, and what the cross-reference was each time

**1. The location-name banner was FLOOR.** `floor_mask`'s BRIDGE rule
re-attaches any component within 25 widget px of the map body, and Sunset draws
`B Market` 9 px above it. 57 entity hypotheses over 1,410 observations sat on
the words, as `ability? 307` and `enemy 68`. The channel the brightness test
does not read was already in the npz -- **map structure is what does not
change** -- so a bridged component is now admitted only when its median `sd_lo`
is inside the body's own 95th percentile. Over the twelve baked geometries the
separation is clean: every real component 0.00-0.87 of the body's p95, the two
offenders at 2.90 (Split's widget rim) and 7.46 (the banner). Ascent's 1,362 px
component -- the Boathouse shape this bridge exists for -- is kept, which a
convex-hull rule would have thrown away. Rendered and inspected on three maps.
`floor_mask_eval` unmoved: Ascent 78.8%, Lotus 77.9%, recall 100%.

**2. Two thirds of the enemy channel was impossible.** While the spawn barriers
are drawn nobody has line of sight, so the widget cannot show an enemy. The
barrier channel is observed per frame and now gates the enemy channel: enemy
observations **531 -> 159**, enemy entities **152 -> 73**, and the 158
observations after `live_start` are unchanged, which was the falsifier. The two
channels agree about the boundary without being told -- barriers +1.5s..+29.2s,
`live_start` +29.5s, zero barrier samples after it.

**3. `Tracker.principal` held a track that had stopped being observed.** It
ranked on lifetime `n_obs`, which answers *which track has the best record*
rather than *where is the icon now*, so 56 of 774 drawn samples had a self icon
detected AND tracked with no box drawn. It is now sticky and refuses. Coverage
81.0% -> 72.6%, and that is the right direction: the worst step between
consecutive reported self positions goes 312.2 px -> 13.9 px and the count over
20 px goes 6 -> 0. 38 of its 77 gaps are one sample, which the renderer covers
by holding the last box. Ordering on freshness alone reaches 88.2% and puts the
p95 step at 20.1 px, which is the flip-flop `principal` exists to stop.

**4. The roster conflict named an arbitrary victim.** The flag went to whichever
ally the observation list reached fifth. Ally observations now fill the roster's
slots ranked by the strength of the correspondence claim, so the mark lands on
the weakest one in the frame; the flagged ally is a resolved continuation in 31
samples now against 69 before, with counts unchanged.

Also: the sidecar panel listed the six STATIC barriers for the whole buy phase
and never printed self, ally or enemy, out of 16.4 rows per sample. Fixed, and
the same order now decides which label keeps its baseline in a crowd.

### THE NEXT THREAD: four allies are still 85 hypotheses

Unchanged by any of this, and now the largest wrong number left. The roster
disagrees with the ally count in 58% of drawn samples -- over-count in 136,
under-count in 314 -- and 68 of the 85 ally births happen while a roster slot
was FREE, so the roster gate is not what is holding it back: the tracker loses
an ally and re-acquires it as a new entity.

**Do not expect the light to solve it.** Measured today over the 103 samples
carrying a roster conflict, the flagged ally's `lit_share` ran a median 0.707
against 0.761 for the accepted ones. Light separates a phantom from a real
icon; it does not rank four real icons against five. The residual-light idea in
the previous handoff is still worth trying for a MISSING emitter, but this
measurement says it will not arbitrate an extra one.

### Measured, not shipped: the close skirt inflates the slab

`floor_mask` closes by 5 px before taking its component, and the component is
read off the CLOSED mask -- so the slab carries a ~2 px skirt of pixels that
never passed the colour test. `CLAUDE.md` warns against exactly this (*fit a
shape rather than repairing it with a closing radius*). Intersecting the
component back with the raw mask shrinks the slab by 0.4-5.2% per map and
leaves the 9 px `floor` **unchanged on every one of the twelve**, so it touches
only the support gate and `floor_mask_eval` cannot see it.

It is not shipped because the impact is real and unresolved: of the Sunset R6
observations whose centre sits in the skirt and nowhere else, **10.1% of self
and 21.4% of enemy** would lose support, against 1.0% of ally. `supported()`
tests a single centre pixel, so a hole under an icon costs the whole detection.
Either widen `supported` to the icon's extent first, or measure which of those
57 self observations are real. That order matters.

## Superseded today -- 2026-09-08, identity, barriers, and the cone restored

### THE DECISION WAITING: context-free events, or a concurrent model

The player's framing, and it is not to be settled yet: *"If we think we can
have detectors emit context-free events that can be disambiguated and
aggregated by the orchestrator that's great. If it would make more sense or
even be required to have more of a back and forth concurrent model, awaiting
other detector events then maybe that might make more sense... we can continue
on the road of attempting to emit context-free events, but keep that in mind."*

**What this session's couplings actually looked like.** Every cross-detector
dependency that arose was ONE-DIRECTIONAL and resolvable by ordering, not by
negotiation:

    lit mask      -> bearing            `cone.resolve_lobe`
    roster count  -> ally acquisition   `RoundLifetimes.step`
    roster alive  -> lineup slot        only accumulate a full bar
    barrier set   -> agent icons        `on_bar`
    all cones     -> residual light     an aggregate, so it is the orchestrator's

So a topological order plus context-free emission covers everything built so
far. **The strongest evidence for that road is `on_bar`:** it was the one live
coupling that looked like it needed the barrier channel's per-frame output, and
baking barriers into MAP STATE removed the coupling entirely rather than
formalising it. A dependency that can be hoisted into state stops being a
dependency.

**The test for when the other fork is required** is whether any channel's
output feeds back into a channel it consumes. Today none does. The first place
it plausibly could is exactly what is queued next: use residual light to
hypothesise a missing ally, and that hypothesised ally casts a cone, which
changes the residual that proposed it. That is a fixed point, not an ordering,
and `[[reticle-ensemble-guessing]]`'s leave-one-out validation is already that
shape. **If the ally/light work needs to iterate to convergence, that is the
signal to switch; until then context-free emission is not a compromise.**

**NEXT SESSION: the light cones and the allies.** That is the thread with the
most left in it -- the residual-light crosscheck says a median 41% of lit floor
is explained by no cone we cast, 11.6% of cones land on unlit floor, and four
allies still arrive as 81 entity hypotheses in one round. The two are probably
one problem: a fragmented ally leaves its light behind, so the residual is
where the missing emitter is. Start from `cone_checks` in the round exports.

### THE LAST HOUR, 19:57-20:07 -- and the one thing it did not reach

Written after the fact: this work landed after the section above was written,
and it is **uncommitted**. `git status` shows six modified files and three new
ones; 156 tests pass under `.venv/Scripts/python.exe -m unittest discover -s
tests` (there is no pytest in that venv).

**The patchiness had a decision-boundary cause, and it is fixed.**
`lighting.lit_mask` classified nearest-state in noise units, `|g-hi|/sd_hi <
|g-lo|/sd_lo`. When the two sigmas differ that test has a SECOND crossing above
the lit reference: a pixel brighter than `hi` can be called dark. It is now the
noise-weighted crossing between the states, `(hi*sd_lo + lo*sd_hi)/(sd_lo +
sd_hi)`, with brightness monotonic above it -- identical behaviour between `lo`
and `hi`, no reversal outside. `LIGHTING_VERSION` is `lighting-0.3.0`.

Measured, not assumed: on Sunset R6 offsets +36 and +55 the inspected
central/B-lane patches held **239 and 548** pixels that were above `hi` and
classified dark, **all of them measured-reference pixels, none terrain-filled**
(`sunset-light-patchiness-20260908/above-hi-dark.json`, with the per-stratum
counts in `report.json`; `sd_hi` there runs 0.5-0.6 against `sd_lo` 3.3-6.8,
which is exactly the sigma asymmetry that opens the second crossing). The
morphological open/close then enlarged the resulting holes -- `report.json`
records `open_removed` 4433 of `raw` 10022 at +36 -- so the filters were
amplifying the defect, not creating it.

**This is a CONSISTENCY improvement, not a visual-accuracy claim.** It removes
a reversal that provably existed; it does not establish that the mask now
matches what the map draws. Bright foreground overlays still contaminate the
read, so cone/light agreement stays a crosscheck rather than truth. Neon and
Clove windows were where the reversal was found, and residual patchiness there
has NOT been shown to be gone.

**THE GAP: the shipped full-round output predates the fix.**
`sunset-round6-reconciled-20260908/` is complete (4740 of 4740 frames, 0 stalled
ms, `complete_round_rendered: true`, 1671 entities) but its `provenance.json`
stamps **`lighting-0.2.0`** -- the run started 20:01 and imported the module
before the 20:05 edit. The re-run that was to fix this,

    .\.venv\Scripts\python.exe prototypes\full_round_entities.py a1a995e6b19b \
      --round 6 --out ...\notes\sunset-round6-lighting03-20260908

**never produced its output directory.** That is the first thing to redo, and
until it exists no full-round artefact demonstrates `lighting-0.3.0`. Verify by
grepping the new `provenance.json` for the version stamp, not by eye
`[[verify-visual-claims-by-measurement]]`.

**Three other changes rode along, all narrowing rather than adding.**

* `cone.compare_evidence(mask, lit, known)` partitions a cone into unknown and
  comparable pixels, then comparable into lit and unlit. `resolve_lobe` takes
  an optional `known`: only classified pixels score a lobe, a lobe with no
  comparable pixels cannot win, and a detection with neither lobe comparable is
  returned unchanged. Omitting `known` preserves the old whole-cone behaviour,
  so nothing silently reinterprets. **Unknown is not dark** -- that conflation
  was the quiet way the residual-light number could have been inflated.
* `round_lifetimes` 0.2.0 -> **0.3.0**: `known_kind` treats only an explicit,
  unqualified reader kind as a constraint (`object?` constrains nothing);
  static association now measures against a stored `anchor_observation` rather
  than step to step, so per-step fit noise cannot accumulate into translation;
  and appearance-only links expire on a width-based horizon (`sqrt(2) *
  REF_WIDGET_W / walker.max_px_s`) because appearance is not an independent
  identity witness.
* `prototypes/cone_reconcile.py` is new: samples given round offsets, warms
  trackers one second per window, and writes source/lighting/geometric/
  disagreement panels plus machine-readable counts. It makes no accuracy claim
  and refuses a non-new output directory.

**Emitter recovery is untouched and is still the thread with the most in it.**
The residual/missing-ally fixed point described above is unchanged by any of
this -- except that its inputs are now cleaner in two ways worth re-measuring
before trusting the old numbers: the median 41% unexplained lit floor and the
11.6% of cones on unlit floor were both computed under `lighting-0.2.0` AND
under a whole-cone comparison that counted unknown pixels as dark. **Re-measure
both before hypothesising an emitter from them** `[[seek-independent-
corroborating-channels]]`.



**Both rounds are on disk and both are complete**, which is the deliverable
`docs/FULL_ROUND_LIFETIMES.md` was written for; that document now carries the
results and the exact reproduction commands, so read it before this.

    ~/reticle-store/notes/lotus-round15-20260908    100.5 s, 6030/6030 frames
    ~/reticle-store/notes/sunset-round6-20260908     79.0 s, 4740/4740 frames

Both at 10 Hz detection over 60 Hz video with source audio, 0 ms stalled, each
with `observations.jsonl`, `lifetimes.json`, `coverage.json`, `provenance.json`
and a `review.html` that passes `tests/review_harness.cjs`.

### THE ROSTER BAR PACKS, and that was corrupting the lineup

Found while testing the death witness, and it is the most consequential thing
in this increment. `roster.alive_from_detail` reads the living as *a contiguous
run anchored at the scoreline edge* -- so a dead player is DROPPED and the
survivors shift. Slot 2 is a different agent before and after a death, and
accumulating per fixed index across a match quietly averages several agents
into one cell.

`Lineup.add` now accumulates a side only while that side is FULLY ALIVE, which
is the only state in which an index is an identity, and is the common one --
it holds at the start of every round. `lineup-0.2.0`:

    LOTUS    3/5 named before and after, but every correct margin sharpened
             Sage 0.132 -> 0.144, Phoenix 0.109 -> 0.138, Cypher 0.120 -> 0.138
    SUNSET   2/5 named -> 5/5 NAMED
             Sage 0.082, Clove 0.119, Neon 0.244, Jett 0.178, KAY_O 0.104

Sunset's five corroborate the player from outside the system: he named Neon's
vision cone and an ally KAY/O knife in that round before any of this existed,
and both are on the roster it reads. Lotus's two refusals are unchanged --
Chamber and Brimstone still do not separate from Sova and Raze on colour
composition at portrait size, and they are refused rather than guessed.

### The death witness: mechanism CLEAN, and it answers the wrong question

`l1/hud` carries the player's `hp` and `l1/roster` carries per-slot detail, so
this needed no decode. The signal is unambiguous -- at one Sunset death the
dying slot goes 31.7 -> 3.3 while its neighbours hold at 25 and 37:

    -0.5s  alive=3    3.4   4.4  |31.7|  24.7  38.5
    +0.0s  alive=2    3.3   3.2  | 3.3|  25.7  37.0

**And voting it over 46 Lotus deaths and 36 Sunset deaths names the wrong slot
both times, near-flat.** The reason is the packing above: at a death the bar is
by definition NOT full, so the index that dims is the player's position among
the currently-living, not their canonical slot. The witness is real; it needs
the packing state carried alongside it, which means tracking death order. Not
built, and it should not be used until it is -- a witness that answers a
different question than the one asked is worse than no witness.

### Named in the overlay

`full_round_entities` reads `lineups/<session>.json`: the self icon is drawn as
the agent (`phoenix`, `clove`) and the HUD tray as `phoenix:blaze`,
`clove:not dead yet` -- the same lowercase `agent:ability` form
`labels/ability_categories.json` uses by hand. The panel prints who the player
is and the team as read.

**Ally ICONS are deliberately not named.** Knowing who is on the team is not
knowing which icon is which, and there is no per-icon witness yet, so `ally 3`
stays what it is.

### The viewcone is back in the round pipeline, with two crosschecks

The 2 s diagnostic renders had an observable-area channel and the full-round
ones never did, so both rounds rendered so far carried no cone at all.
`cone.observable` now runs over the tracked bearings each sample; the aggregate
is tinted under the boxes, per-icon masks are kept (the aggregate cannot say
WHICH teammate saw a pixel), and coverage is printed in the panel. Measured over
45 s of Sunset R6, 435 samples:

    observable coverage   median 5.6% of floor, max 12.0%
    emitters with a bearing   median 4 of 4

**First draft of both crosschecks, and neither gates anything yet.**

*Residual light -- lit floor no cone of ours explains.* The widget draws an
ally's cone whether or not this pipeline found that ally, so light outside
every cone we cast is evidence of an emitter we are MISSING, which is the one
signal that speaks to ally fragmentation: a fragmented ally leaves its light
behind. **Median 41% of lit floor is unexplained** (min 7%, max 100%). That is
not 41% missing allies -- the lit mask also carries ability light and widget
shading -- which is exactly why it is recorded and not gated. The largest
unexplained blob is reported as a position HINT with that word in the row: a
cone's apex is at its narrow end and a centroid is not an apex. It is already
behaving like a signal rather than noise -- at t=36 s and t=42 s the same
region near (151, 234) carries a blob growing 783 -> 1000 px.

*Unlit cone -- an icon claiming a view nothing corroborates.* `resolve_lobe`
picks the better of two lobes and never asks whether the winner is any good, so
a phantom icon still gets a bearing. **189 of 1,631 per-emitter cones (11.6%)
land on floor that is under 10% lit.**

### The ability tray is safe now, and it is the strongest identity witness

The failure was never the ultimate slot: the tray crops held ~2,700 bright
pixels per cell on Lotus against ~540 on Sunset, because `g > 170` is an
absolute cut and Lotus's buy phase is a bright sandy courtyard. Adding a
saturation term does not help -- pale sand is bright AND unsaturated.

**The gate that works is structural rather than fitted: a glyph is a symbol
with background around it, so a mask filling most of its cell has stopped being
a glyph.** `GLYPH_FILL` refuses outside 4-45% of the cell. Over spaced frames
in both sessions:

    LOTUS    16 frames, 12 passed the fill gate, 12 voted Phoenix, 0 wrong
    SUNSET   13 frames, 11 passed,               10 voted Clove,   0 wrong

22 of 22 correct, and the frames the gate refuses are refused rather than
guessed. The witness that was confidently wrong at margin 0.136 is now the one
that decides:

    LOTUS    PLAYER Phoenix, ally slot 2   by the tray; top bar AGREES
    SUNSET   PLAYER Clove,   ally slot 1   by the tray; top bar ABSTAINED

**Abstained is not disagreed.** The top bar refusing a slot for want of margin
says nothing against the tray, and collapsing the two into a boolean would
report a conflict where there is only silence -- so `agree` is
`agrees` / `abstained` / `DISAGREES`.

### The player is named by TWO weak witnesses, neither of which is enough

The player listed the witnesses and the point of listing them: *"I realize it's
a tangle of mutually reinforcing factors, but that's kind of the point."*

**Do not redetect the self icon.** It is already `you`/E0001, one entity for a
whole round, and its `composition()` is already stored on every observation for
association -- so the identity witness is free and `Lineup.add_self` takes the
VECTOR, not a crop.

    LOTUS, truth slot 2 / Phoenix
      top bar    slot 2 = Phoenix, margin 0.109      accepted, but says
                                                    nothing about WHO is me
      self icon  Phoenix ranked 2nd of 29, margin 0.045   REFUSED alone
      joined     among the five the top bar proposes, Phoenix wins by 0.098
                 -> slot 2, correct

    SUNSET     -> slot 1, Clove, margin 0.186

**The scores are not pooled.** The top bar answers *who is on the team* and the
self icon answers *which of them is holding the camera*; summing them would let
a confident answer to one paper over silence on the other. `Lineup.player`
keeps both verdicts and an `agree` flag.

Clove is confirmed from two further directions: the buy-phase tray glyphs are
butterflies with a butterfly-and-heart ultimate, which is Clove's iconography
and matches `Pick-me-up / Meddle / Ruse / Not Dead Yet`; and the player is
OVERHEALED in that round, which is Clove's own effect. Lotus's Phoenix is
likewise confirmed by the tray reading Blaze / Hot Hands / Curveball with a
"Run it Back" ult banner.

### The tray glyph is a REAL witness and it is not safe yet

`reference/assets/abilities` holds 118 official glyphs as `<Agent>_<Slot>.png`,
and the tray is the player's own, large and unoccluded. Matching the four
glyphs as binary shapes:

    SUNSET   Clove     IoU 0.860  margin 0.523   CORRECT
    LOTUS    Sage      IoU 0.603  margin 0.136   WRONG (truth Phoenix, not in
                                                 the top five)

**It is not the ultimate slot** -- dropping X changes neither answer. It is the
MASK: the tray crops hold ~2,700 bright pixels per slot on Lotus against ~540
on Sunset, because Lotus's buy phase is a bright sandy scene and `g > 170` is
an absolute cut that floods when the world behind the HUD is bright. The glyph
detector is a brightness threshold, which is the failure class this repo
already pays for repeatedly.

**The margin was healthy and the input was garbage**, and 0.136 would clear the
0.07 gate -- so a confidence number is worthless without a precondition on the
input that produced it. Gate on mask quality (the tray plate is a known dark
region; a top-hat or local contrast would not care what is behind it) BEFORE
this witness is allowed to vote. Not built, and not wired into the overlay.

### Identity rides every scan now: `reticle/lineup.py`

The player's spec, and it is right on all three counts: *"default to getting
roster for identity and wire it in for events. Every scan that's not just
testing one specific thing. Every time. It doesn't even need scoreboard, just
the top bar, and continue checking on different, spaced frames until we have
high enough confidence."*

**The top bar needs no Tab press and is drawn every frame**, so `LineupReader`
joins the shared pass at 0.1 Hz and costs no decode of its own. On by default;
`--only` narrows a scan to one thing and is left alone, `--no-lineup` opts out.
Output is `~/reticle-store/lineups/<session>.json`.

**Composition against OFFICIAL ART -- no session mining, no labels.**
`reference/assets/agents` holds 29 agents x 3 surfaces (`agent_icon`,
`killfeed_portrait`, `minimap_portrait`); the three are independent drawings of
one thing so their intersection scores are summed. A histogram is layout-free,
which is also why the enemy bar being mirrored costs nothing.

**The MARGIN is the confidence, and it separates completely.** Lotus
`7010b3d62460`, 90 spaced frames, ground truth from the buy menu (Phoenix,
Cypher, Chamber, Sage, Brimstone):

    slot 1  Sage      margin 0.132   correct
    slot 2  Phoenix   margin 0.109   correct
    slot 4  Cypher    margin 0.109   correct
    slot 0  --        margin 0.035   REFUSED (best guess Sova; truth Chamber,
                                     which is the runner-up)
    slot 3  --        margin 0.031   REFUSED (best guess Raze; truth Brimstone)

Three named, all three right; two refused, and they are exactly the two that
would have been wrong. `MARGIN_MIN` is PROVISIONAL -- one lineup, five slots --
so every verdict carries its margin and keeps its best guess beside the refusal.

Two constraints do real work: the five slots are five DIFFERENT agents, so the
verdict is an assignment rather than five arg-maxes (`track.assign`, the same
solver the tracker uses on icons); and scores accumulate rather than votes,
because an argmax per frame throws away the closeness that is the only thing
here that knows whether the answer is worth having.

**Sunset corroborates from a direction the reader cannot see.** It names Neon
(0.153) and Jett (0.131) on the ally side, and the player -- watching the same
round before any of this existed -- called out *"neon's vision cone"* and *"the
ally kay/o knife"*. `KAY_O` is the reader's best guess for ally slot 4 at 0.068,
a hair under the cut. The enemy side names nothing at all: every slot is under
the margin, so it says so rather than inventing five agents.

**`agent:ability` is a lookup, not a matcher.** `reference/abilities.json` has
29 agents and every ability's slot key, so a known agent turns the HUD tray
into `phoenix:blaze`, `phoenix:hot hands`, `phoenix:curveball`,
`phoenix:run it back` -- the same lowercase form
`labels/ability_categories.json` already uses by hand. The Lotus tray reads
Blaze / Hot Hands / Curveball and the ult banner reads "Run it Back", so the
TRAY is a second, independent witness to the player's own agent, and it needs
no portrait matching at all. Not yet wired into the overlay's naming.

**What I got wrong before measuring.** I said there was no identity witness and
that `agent:ability` was blocked. Both false: `minimap_portrait` scores 83.5%
held-out / 88.6% leave-one-out over five agents, the 28 `ability-demo` sessions
each carry their agent as a manifest tag, `casts/` holds their C/Q/E/X events,
and the round pipeline was already computing `composition()` per icon and
throwing the matching step away. It was never a capability gap, only wiring.

### ONE support surface, because the mask was a per-call-site accident

The player: *"Shouldn't all the detectors be using slab?"* Yes, and the split
was not a decision anyone made -- it was whatever each call site happened to
pass. Measured over Sunset R6, off-slab rate by what the channel was handed:

    handed the SLAB     discs 0.8%      dynamic 0.2%
    handed the FLOOR    enemy 39.2%     raw pings 16.8%   (846 of 5024)

The floor is the slab dilated by 9 px and the margin is **20% of the floor
area**, so the floor-fed channels leak at about the margin's own size -- which
is what pure artefact looks like. `RoundReader.support` is now the one rule:
SEARCH on the floor so an icon at the map's edge is not clipped, REQUIRE
support on the slab, ANY support rather than a fraction. Refusals are kept per
channel in `off_support` instead of vanishing.

**And fixing barriers recovered 354 real allies, which is the argument for an
orchestrator in one number.** `on_bar` suppresses an agent fit sitting on a
barrier -- reasonable, and with 21 spurious bar positions in the calibration
set it was deleting true detections:

    first 45 s      raw ally fits   suppressed as "on a barrier"   emitted
    before              1875                 627                    1248
    after               1872                 273                    1599

The ally detector did not change at all. A false positive in one channel was
silently destroying true positives in another, and no amount of looking at the
ally channel would have found it.

    channel      before   after         (first 45 s of Sunset R6)
    enemy           783     449    -43%, 324 refusals now counted
    barrier        2625    1668    anchored to 8 baked bars
    ally           1248    1599    +351, recovered from false barriers
    self            335     335    unchanged; it already had support

### The orchestrator: the cross-references exist, nothing OWNS them

The player asked for a unifying layer. The reason he is right is that the
cross-referencing this repo keeps insisting on is already here and is scattered
across four files with no shared shape:

    on_bar()                     a closure inside the prototype's read()
    distance dedupe to agents    the same function, three separate spellings
    MIN_ICON_SEPARATION_PX       inside minimap.icons
    temporal dedupe              inside track.Tracker
    roster capacity              inside RoundLifetimes.step
    stall gating                 the top of read()
    support                      six call sites until today
    simultaneous_enemy_evidence  appended to cross_view and never read

Each is right on its own and none can see the others, which is how a barrier
false positive got to delete an ally for a whole round without leaving a trace.
The shape to move to: channels emit typed CLAIMS rather than observations;
one layer holds the shared surfaces, applies adjudication rules that are DATA
rather than `if` statements, records which rule fired, and keeps every refusal.
`read()` becomes a driver. Not started.

### `barrier 57` was the CALIBRATION speaking, and the cut law is now a check

**The converged anchor set was always right.** `barrier_candidates` accumulates
a per-pixel count over buy phase and keeps components present in >= 75% of
samples -- and by the end of buy it has 8 clean bars on Sunset and 6 on Lotus.
The 57 entities come from EMITTING while that rule still has no power: it
starts at `buy_samples >= 5`, where a blob present in four samples scores 80%.
Clustering Sunset's 57 by position:

    9 positions   180-305 observations each, spanning the whole buy phase
                  boxes 25x8, 8x18, 27x6, 8x28, 28x8 ...   the real bars
   21 positions   1-53 observations, all dead by 2-8 s
                  boxes 2x10, 2x8, 3x8, 2x7 ...            slivers of map art

Six of the nine real bars are already ONE entity for the whole buy phase, so
this was never an association failure. **Measured end to end: `barrier 57`
became `barrier 8`** -- one entity per baked anchor, each observed 274-278
times across the whole 27.7 s buy phase, in a re-render. `reticle/barriers.py` bakes the anchors
as map state keyed like geometry (`<map>__<profile>.json`), the reader emits a
barrier only where a keyed component sits within `ANCHOR_PX` of a baked anchor,
and a round on an unbaked map reports NO barriers and says so -- render once to
calibrate, `python -m reticle.barriers SESSION ROUND_DIR --write`, render again
to observe.

**The player's law is the validator, and it failed a map on its first run.**
Barriers sit over chokepoints and *in aggregate separate the map into ally,
neutral and enemy territory*, so the test is whether painting the set onto
`cone.passable_from` cuts the floor. Growing each bar to its blocking extent
(the team-colour key catches the middle of a bar, not its ends):

    grow px      SUNSET, 8 bars                LOTUS, 6 bars
       0         94% one region                92% one region
       4         46% / 43%                     90% one region
       6         45% / 35% / 7%                89% one region
      12         44% / 33% / 6%                84% one region

**Sunset separates and Lotus does not**, at any growth -- so Lotus is MISSING a
barrier, which is a claim no per-blob score can make and no threshold on this
round could have found. The tool reports the contradiction rather than guessing
which bar is absent.

### The KAY/O hypothesis: CONFIRMED, in a channel I first looked past

The player saw ability casts followed by hallucinations, with the enemy (red)
KAY/O knife producing more than the ally (white) one. First measurement said no
burst at all -- but it counted `object`/`outline`/`ally_outline`, and the
proposed mechanism is the ENEMY colour key. Counting `enemy` detections per
sample, live-phase median 0.2, sd 1.3:

    t=31  enemy KAY/O knife, RED ring     6.2 / sample   +4.5 sd
    t=37  ally  KAY/O knife, white        2.6 / sample   +1.8 sd
    t=43  enemy KAY/O grenade             5.0 / sample   +3.6 sd
    t=44                                  4.7 / sample   +3.4 sd
    everything else in the round          ~0

So the bursts are real, they are large, and **the red/white asymmetry runs
exactly as predicted** -- the enemy-keyed cast produces about 2.4x the ally
one. The enemy grenade spikes too, which is the same three observations the
player flagged as `enemy outline?` with no enemy on screen.

**The ARC half is refuted and the player had already seen why.** If the ring
were producing fits along its circumference the radii would pile at one value;
they spread from 20 to 340 px. His correction: the markers were *"quite a ways
away from the actual ability radius"* and *"all at the map border"*. They are,
and the border is the MAP's, not the crop's -- 0% of either knife burst is
within 12 px of the crop edge, but measured against the opaque slab:

    window                     n    off the slab   within 3 px of the map edge
    t=31 enemy knife          72      50%                56%
    t=37 ally knife           28      25%                43%
    t=43 enemy grenade       101      74%                81%
    all other live samples   124      29%                38%

**So the burst is the map's edge, and one existing rule already rejects it.**
`ally_icons` and `self_icons` take `support=self.slab`; `enemy_rings` was
reading the DILATED floor. Over the whole round that asymmetry is most of the
channel:

    enemy   892 observations   39.2% have no slab support
    ally   1950                 4.2%
    self    627                 1.1%
    object 4908                 0.9%

The enemy ring now takes the same gate -- ANY support, not a fraction -- and
the refusals are kept in `enemy_no_slab` rather than dropped. What is still
unexplained is the TIMING: why a cast is when the border lights up. The player
notes Chamber's ultimate voiceline lands at 0:30 too, and that is a second
candidate this round cannot separate from the knife.

**Also his, and not yet used:** the ally KAY/O reveal writes a HUD item BELOW
the minimap -- dagger icon plus who was revealed, Omen in this case. That is a
named reveal with a named TARGET, in a fixed HUD region, which is a stronger
witness than anything the widget carries. The crop is 465 wide by 485 tall, so
the ROI already extends past the widget; whether that strip is inside it has
not been checked.

### Doors are a static class, and they are NOT vision-gated

Lotus has two mechanical doors and both are in round 15, currently misfiled as
`ability icon?`:

    E0581  C-side door   200 observations, 52.5-73.0 s, max drift 0.3 px
    E0788                 84 observations, 61.6-70.0 s, max drift 11.7 px

E0581 is one contiguous run of 199 continuations at a fixed pixel -- the
tracking is already right, only the class is wrong. The player's mechanics:
**the icon is drawn only while the door is IN USE**, it is accompanied by a
distinctive sound within audio range, and *it does not matter whether an ally
can see the door*. That last part is what makes it valuable: a door is a
GLOBAL event witness, unlike almost everything else on the widget, so it is
evidence about the enemy team that needs no line of sight -- and it has an
audio channel to corroborate against.

### Correction: do not raycast the Sova dart on the minimap

Recorded earlier as "the drawn circle is the bound, not the answer, and
`cone.raycast` over the passable geometry already does the line-of-sight
computation". The player has refused the second half: the dart sticks to walls
and ceilings, **and the minimap does not carry height**, so a 2D raycast from
the dart's ground projection is not the scan. What can be said confidently is
only *where the dart landed* and *which enemies were scanned*; height might be
recovered from lineups, from which enemies were revealed, or by seeing it.
**So the revealed set is the OBSERVABLE and the dart is what it is evidence
about, not the other way round.** KAY/O's knife is the easier case and the
opposite one -- its radius passes through walls, so it needs no ray at all.

### THE PLAYER WATCHED BOTH ROUNDS, and named 21 entities

Recorded as adjudications, not prose:
`~/reticle-store/labels/round-entities/player-review-20260908.jsonl` -- entity
id, the class the detector gave it, the class he gave it, and its video
timestamps. Every id he named resolves and every timestamp matches. This is a
labelling pass he did for free and it is worth more than the renders.

**The CRACK class is real, it is MAP ART, and it is derivable without labels.**
He named cracks -- holes, walls, pillars, corners drawn into the minimap art --
as the thing the object channel keeps finding. The stored geometry median has
every entity removed by construction, so anything a detector finds in IT is
furniture. Run the ability-disc reader on Lotus's median:

    5 dark discs in the entity-free map median
    E0075  0.0 px   E0224  0.5 px   E0079  0.5 px      <- he named all five
    E0280  4.0 px   E0290  4.5 px

All five, and nothing else. E0303 (a shadow off Chamber's pillar) and E0291 (a
lit pillar on C) are correctly absent -- they are dynamic. **So cracks bake per
map exactly as barriers do**, and the median is the source: no player pass, no
threshold. Sunset's median has ZERO discs, so its objects are a different
mechanism entirely.

**Two flagged detections are off the opaque slab and one rule already rejects
them.** `slab_mask` is the gate `minimap.icons` uses for ally/self; the ENEMY,
BARRIER and dynamic-object channels never got it.

    E0136  barrier `spawn barrier?`   0/31 observations on slab   -- a WALL crack
    E0277  enemy   `enemy agent?`     3/12 observations on slab   -- off the map

Do not generalise it further: every Lotus crack sits squarely ON the slab, so
slab support fixes these two and no others. (Measured after claiming otherwise
from a three-point sample.)

**Spawn barriers have a geometric law and it is checkable.** His words: barriers
*"will always be over choke points of various sizes and taken in aggregate will
separate the map into ally, neutral, and enemy territory."* That is a cut of the
passable graph, and `cone.passable_from` already builds that graph -- so a
barrier hypothesis SET can be tested for whether it partitions the map into
three regions, and E0136 (a wall crack, not on a chokepoint) fails a test that
no per-blob threshold could have. Nothing built.

**KAY/O's knife (E) is a reveal source and it is NOT the recon dart.** The red
ring is the enemy's and marks a detection radius that **goes through walls**;
the ally's knife draws the same shape in white. So unlike Sova's dart -- whose
drawn circle bounds a LINE-OF-SIGHT computation -- the knife's revealed set is
the radius itself, and `cone.raycast` is the wrong model for it. Both are
`LEGAL_ORIGINS["enemy"]` reveals.

**A big ring makes fits all along its arc, and that is the burst.** He saw the
enemy knife cast at A produce hallucinations around A and then around B, and
had no hypothesis. This repo already has one: the Haven recon-dart circle did
exactly this (*"a teal ring spanning much of the map produces icon fits on its
arc"*), which is why the bursts land far from the cast. It also predicts the
asymmetry he noticed -- the RED ring shares the enemy key and the white ally
knife does not, so the red one should produce more. Untested, and it is the
cheapest of these to test.

**Most abilities cannot be cast in buy phase.** A short list can; the rest
cannot. So an `ability?` inside buy phase is refutable by the phase alone, the
same rule that made barriers separate cleanly. The exception list has to come
from the wiki, and is not in the repo.

**Also named, not yet modelled:** buy-phase-only ally markers above teammates'
heads cross the world view and produce silhouette hallucinations (0:09 Sunset);
an enemy KAY/O grenade produces first-person `enemy outline?` with no enemy
present (E1155-57, all single-observation); Neon's vision cone in a doorway
produces objects (E1001, E1017); a lit box produces one (E1340); and the B Lobby
HUD element ABOVE the minimap is inside the read region (E0844 at y=16).

### Names are English now, because the ids were hiding the re-births

`round-lifetimes-0.2.0`. Every entity gets a round-scoped name fixed AT BIRTH --
`you`, `ally 1`, `enemy 3`, `barrier 2`, `ping:danger 1`, `ability?`, `?`,
`outline?`, `ally shape?`, `tray C` -- and the overlay draws that instead of
`E0303`. The ordinal is the point: **`ally 7` in a 5v5 is wrong on the face of
the frame**, where a serial number is not, so the name is the fragmentation
test rather than a caption. The class can still move underneath it and
`class_history` keeps that.

`ping:type` cost nothing: `ping.classify` already named every ping and the name
was being dropped into `hypotheses` while the frame read `ping?`.

Still not derivable, so not claimed: the AGENT. There is no identity witness --
`minimap_portrait.composition` is an appearance histogram, not a name -- so
`ally 3` is the honest form and `agent:ability` waits for one.

### What holds for a whole round, and what does not

**The three classes with an independent witness hold; nothing else does.**

    self       one entity for the entire round, on BOTH maps
    barrier    every observation in buy phase, none in live or post-plant
               (1,950 on Lotus, 2,625 on Sunset) -- the phase rule separates
               completely, and this is the payoff of naming the glyph
    spike      Lotus: 239 of 240 observations post-plant, the odd one at the
               boundary. Sunset: ONE observation in a round with no plant, so
               the HUD flag has a 1-in-790 false positive

Against that, 1,228 entity hypotheses for the Lotus round and 1,691 for the
shorter Sunset one. 1,082 of Lotus's are `object?`/`outline?` -- unresolved
classes rather than wrong answers -- and 492 of those are seen exactly once.
Four allies over 100 s arrive as 81 hypotheses.

### THE DEFECT TO FIX FIRST: the motion law goes vacuous at 14.6 s

A long-gap re-acquisition is admitted on APPEARANCE similarity whenever the
motion law does not refuse it. The walker class is 45 px/s and the widget
diagonal is 658 px, so past

    dt = 658 / 45 = 14.6 s

`admits` returns True for every position on the map and a colour histogram at
0.85 is the whole gate. Counting accepted continuations across a gap over a
second:

    lotus R15     7 links,  0 past 14.6 s   longest gap  9.7 s
    sunset R6    64 links, 31 past 14.6 s   longest gap 76.9 s

61 of Sunset's 64 are ENEMIES, which is where it bites: an enemy icon is drawn
only while revealed, so its observations are sparse by nature and the appearance
branch is reached constantly. `E0026` is three observations spanning 77.0 s
across one 76.9 s gap -- an icon at round start and an icon at round end, called
the same enemy. `docs/FULL_ROUND_LIFETIMES.md` forbids exactly this:
*reacquisition must be unique under the motion law or an independent identity
witness*.

**Lotus alone would have said this was fine.** Render the second round.

The bound is DERIVED (`diagonal / max_px_s`), not tuned, so the fix does not
need a threshold search -- it needs a decision about what happens past it:
refuse, or keep the link and say out loud that appearance is carrying it alone.
Measure against both rounds; `python -m reticle.round_lifetimes DIR --out X`
replays the whole adjudication from stored observations in 50 s without
decoding a frame, and reproduces `lifetimes.json` byte for byte.

### Then: the roster gate is limited by the SELF icon, not by the roster

Capacity is `alive_ally - 1` because the roster counts the player, so it needs
an observed self. 18-21% of ally observations get `roster_unknown` for want of
one:

    lotus   2,333 slot_available / 527 roster_unknown / 73 count_conflict
    sunset  1,534 slot_available / 397 roster_unknown / 19 count_conflict

The self icon is absent in 212 of 1005 Lotus samples over 59 runs, the widget
DRAWN in all but 7 of them, and 79% self coverage repeats almost exactly on
Sunset (79.4% vs 78.9%) -- so this is the widget, not the detector. The longest
run (1446.1-1449.3 s) is the source drawing no agent icons at all at round
start; the pixels show it directly. **The cross-reference is available and not
built**: the roster already knows whether the player is alive, which separates
"the widget is not drawing me" from "I am spectating", and `has_self` cannot
tell those apart today.

### Also measured, not fixed

* **the candidate-parent set never expires** for ally/enemy entities with an
  appearance vector. It grows 0 -> 166 over the Lotus round while the set seen
  within the last second stays at 30-50; 61% of the 1.86 M candidate pairs are
  against entities not seen for over a second, and the render decelerates 4x
  from the first block of frames to the last;
* **the review pages are too long to ask for** -- 2,457 and 3,055 candidates,
  three per entity. The 660 `object?` entities would dominate a player pass.
  Sample the population before spending anyone's time on it;
* **`floor_mask_eval reticle.minimap a06f04a0059f` is BROKEN** at the fourth
  decimal (iou 0.7882 -> 0.788) with its `impl` fingerprint unmoved. The run is
  2026-09-07T21:58, which is when geometry was re-keyed per (map, profile) --
  so the likely cause is that the eval's deps do not include the geometry npz
  it reads. That would make it a MISSING DEPENDENCY rather than an unversioned
  edit, and the check is behaving correctly. Not confirmed.

### Housekeeping done this session

`reticle/screen.py` was promoted carrying byte-identical copies of
`hud_mask`, `find_boxes` and `_runs` from `prototypes/enemy_features.py`;
doctor called it, the copies are gone, and `enemy_detect_eval` still returns
TP 42 / FN 4 / FP 60 with `enemy_equiv_check` identical on every frame.
`reticle metrics` no longer raises `KeyError: 'index'`, and no longer announces
an uncorrected regime change. `round_lifetimes.main` no longer assumes widget
scale 1.0. `AGENTS.md` is an untracked byte-identical copy of `CLAUDE.md` --
left alone, but it will drift.

## Superseded today -- 2026-09-08, entity lifetimes and evidence-based teleports

**A teleport is now licensed by CORROBORATION, not by distance.**
`track.Corroboration` + `corroborates_teleport` is the one rule -- the icon AND
the viewcone must have relocated, tied to a predecessor entity by audio or an
observed destination, with source refs -- and `admits(..., evidence=)` admits
any distance above the walk ceiling when it holds. `TELEPORT_PX` survives only
as the no-event fallback and every step it admits now returns
`TELEPORT_ASSUMED` so the assumption is countable. The reviewed ~52 px Lotus
relocation is refused on distance and admitted on evidence, asserted in
`--self-test`; `minimap.filter_track` takes the evidence per span
(`[(t0, t1, class, corroboration), ...]`) and still never interpolates across
a jump. `minimap_lifecycle` no longer keeps its own copy of the rule.

**Lifetime tracking: the self entity is now ONE id where it was thirteen.**
Measured by re-running the real `overlay --minimap-diagnostics` command on the
same two 2 s 60 Hz windows:

    window  metric                  before   after
    ascent  self track keys           13       1     (icon detected in 120/120)
    ascent  ally track keys           43      14
    ascent  quarantined obs           55      51
    lotus   self track keys           10       1
    lotus   ally track keys           11       2
    lotus   relocation rows, 1 event   6       2

Three assumptions were the cause and all three are gone:

* **the association tolerance was integer quantization** (`sqrt(0.5)`), which
  is a floor on the icon fit's centre error rather than a measurement of it.
  `track.FIT_ERR_PX` is 2.0 px, measured from FORCED CORRESPONDENCES -- the
  self icon is detected exactly once in every frame of both windows, so
  consecutive detections are the same entity by construction and no labels are
  needed. Every value from 2.0 to 10.0 holds the self track at one id, so it is
  a plateau and not a fit; the ceiling is icon separation (~20 px);
* **`max_missed=3` expired tracks in FRAMES**, so the real budget was 50 ms at
  60 Hz against the 500 ms `max_gap_ms` says. Two constants for one law. The
  frame count is deleted, not raised;
* **the lifecycle wiped identity whenever the widget was not drawn** -- a
  missing observation treated as a missing entity, in the module that exists
  to catch that. It now suspends, and elapsed time alone expires.

A fourth was the ally half, and it is a RESOLUTION limit rather than a motion
one: the widget draws an icon about `2*R_MIN` across, so two same-role fits
closer than that are two fits of ONE icon and cannot be two entities. The
Ascent ally arrives as a stable r=8 fit of area ~100 and a second r=12-13 fit
of area ~20 about 8 px away, alternating frame to frame, and the tracker was
minting an identity for each. `Tracker.resolve` collapses the same-frame pair
(keeping the higher `cov`, the detector's own goodness measure) and the birth
path defers to an unobserved track inside the limit, which is how the
alternation actually arrives -- one fit at a time. **The measured separation
gap is what licenses it**: over the Ascent window every same-frame ally pair is
either 8.1-9.1 px apart (four, all that same signature) or at least 45 px (77),
with nothing at all between 10 and 45.

Also deduplicated: `track.association_tolerance` is one definition where there
were three, and the lifecycle's continuation ceiling (`RUN_PX*dt + sqrt(2)`,
2.2 px at 60 Hz against the tracker's 4.8) was quarantining observations the
tracker had already associated. `tools/minimap_sequence_summary.py` now replays
the whole chain -- tracker and lifecycle -- at three error terms and reports
forced breaks; the throwaway prototype that did this is deleted.

**Cone availability FALLS on Lotus allies, 92/92 to 76/92, and that is the
point.** `resolved_facing` refuses a bearing whose window is ambiguous, and a
one-sample window has a resultant of 1.0 by construction -- so fragmentation
was bypassing the ambiguity gate rather than passing it. After the merge the
16 refusals are concentrated in one track: the post-teleport destination fits,
which are exactly where the fit is worst. Under-claiming is the rule.

`minimap_diagnostics.light_support` was also not comparable between fits: it
excluded `d <= r`, the fit's OWN radius, so two candidate fits of one icon were
scored on different annuli and the one that fitted a larger circle counted less
of its own dark surroundings. It excludes `R_MAX` now. That artefact was worth
0.13 of adjacent-lit fraction in the direction that would have promoted the
weaker fit.

97 tests, `--self-test` PASS, doctor 2 findings / 0 errors.

### The quarantines: all 51 were the world showing through the widget

**Scored without a labelling pass, because the answer turned out to be
derivable and a review page would have spent player time confirming it.**

`floor_mask` dilates the slab by 9 px so an icon at the map's edge is not
clipped, and that margin lies over the SEE-THROUGH part of the widget. On
Ascent the game world behind it is a green glass wall, which keys as ally
teal -- the ally mask holds 7,855 px at 299.6 s against 153 a second earlier,
and every quarantined blob sits in the margin. Measured over both windows and
both roles, counting detections with at least one keyed pixel on the opaque
slab:

    real (adjudicated eligible)    452 / 452
    the quarantined burst            0 /  51

A total separation, and the rule is *any* support at all rather than a
threshold. `minimap.icons` now takes `support` (the undilated slab, from
`minimap.slab_mask`) and drops a component that never touches it.

    window  metric                  before   after
    ascent  raw ally detections      175     120     (the 55 phantoms, gone)
    ascent  self track keys           13       1
    ascent  ally track keys           43       1
    ascent  quarantined obs           55       0
    ascent  bearings resolved     112+170  120+120
    lotus   everything            unchanged         (no phantoms there)

So the Ascent window is now one self and one ally, each a single entity
continuous across all 120 frames, with a bearing on every observation and no
quarantine at all. **50 of the 55 phantoms were casting viewcones**, which is
why the observable area falls from 8.3% to 5.3% of the floor at 299.8 s: the
channel was claiming area from the void.

The same-frame duplicate rule now lives ONLY in `minimap.icons`, where the
fits are produced. It was already there at 8 px -- under the 8.1-9.1 px the
duplicate pairs actually sit at, which is why every one leaked through -- so
it takes `MIN_ICON_SEPARATION_PX` and keeps the best-covered fit. `Tracker`
keeps the TEMPORAL half, which the detector cannot see because it never sees
two frames.

**A spot-check page is built and waiting, and it is optional.** The claim above
is my own measurement, so `prototypes/quarantine_sample.py` drew the population
a player pass would need to turn it into a scored number -- all 51 quarantined
observations plus 25 position-deduplicated eligible controls, shuffled, so the
page cannot show which is which and a page of pure refusals cannot be answered
"nothing" all the way down. `tools/minimap_sequence_review.py --candidates`
takes that selection; the page is
`~/reticle-store/notes/ascent-quarantine-review.html`, 76 questions, and it
passes `tests/review_harness.cjs`. Answering it would give a
false-refusal rate and a missed-phantom rate rather than a derivation.

**What is still not scored.** Lotus has no quarantines and Ascent now has
none, so there is nothing in these two windows for a player pass to adjudicate.
That is not the same as the channel being right: these are 2 s windows on two
maps, the separation above is measured on the JPEG review previews rather than
the decoded frames (the effect is gross enough that this cannot explain it,
but a promotable figure should be recomputed on source pixels), and the
lifecycle gate has still never been scored against a case where it refuses
something real. The next window to render is one with a MAP GLANCE or a death
in it -- the widget-absent path is now a suspension rather than a wipe and
that change has not met real data.

### The player-supplied Haven windows, and a capture stall the channel could not see

**The player named four windows in `96aa1ae9b96f` (Haven, and the SMALL 331 px
widget -- everything before this was measured at 465 px, scale 1.0):**

    3:43-3:44   the buy menu open
    4:21-4:23   a death
    7:03-7:06   the game frozen -- "may be me alt-tabbed or a recording issue"
    11:46-11:51 a second freeze, POST-PLANT, "there is still fragmented audio"

**The buy menu is the case the suspension path was built for, and it passes.**
The widget is genuinely absent for 2.97 s (222.38-225.35). Elapsed time expires
the anchors at 500 ms, so the return is a censored boundary and not a burst of
births, and everything after it is a continuation. No change was needed.

**A FROZEN CAPTURE was reporting the most confident tracking in the session.**
Every track holds, every position repeats, nothing is refused -- the channel
was describing a world it had stopped observing. `CLAUDE.md` already requires
stale input to stay distinguishable from a real reading; this was the missing
half. `minimap_diagnostics.stale_source` decides it and the frame is treated
exactly like an absent widget, recorded as its own `widget: "stale"` state.

**The player supplied the better witness: THE CLOCK.** *"Clock will work to
detect capture stalls where the clock exists. Post-plant it is harder."* Both
halves are now measured, and both are true:

    window            clock readable   stall found            evidence
    haven 421-428        420/420       421.02-427.42 (6.40s)  clock held AND
                                                              pixels static
    haven 704-713          0/541       706.47-708.65 (2.18s)  pixels only
                                       708.68-712.72 (4.03s)
    haven 259-266        414/420       none                   clock refutes
    ascent 298-300 (control) 36/120    none                   unchanged

Post-plant the round clock is replaced by the spike timer and is unreadable in
every one of the 541 frames, exactly as the player said -- so the pixel delta
stays as the fallback and every row records WHICH witness the answer rests on.
A ticking clock refutes a stall whatever the pixels look like, and that is what
removed 15 single-frame false positives from the death window.

**Both stalls are longer than the windows above, which were CLIPPING them.**
Rescanned at 5 Hz over 390-430 and 695-725:

    stall     video               length   state during it
    first     407.2 - 427.6 s     20.4 s   BUY PHASE, clock stuck at 0:14
    second    706.8 - 712.8 s      6.0 s   post-plant, no clock at all

So a window chosen around a stall has to be wider than the stall or the figure
is a lower bound. Say which it is when quoting one.

**NO TIME IS LOST, and I nearly reported that it was.** The clock resumes at
1:32 of the next round, which looked like a whole round had passed unrecorded.
Looking at the frames settles it: 0:14 is the BUY PHASE timer (the "BUY PHASE"
banner is on screen, knife out, combat report open), so 14 s of buy plus 8 s
into a 1:40 round is ~22 s of real time against ~20.4 s of video. The score is
1-2 on both sides of it, so no round completed. **The picture is stale; the
timeline is not.** The inference that ~45 s had vanished came from assuming
0:14 was a round timer, and the unchanged score was the clue that said
otherwise.

**The self icon is now chosen by the TRACK, not by one frame's coverage.** The
overlay took the highest-`cov` self candidate per frame, before the tracker saw
any of them; in the death window that moved the reported player position
between two points 35-45 px apart seven times in three seconds, on candidates
whose `cov` sat at the 0.25 floor. `track.Tracker.principal` picks the
best-supported track and the rejected candidate is kept rather than deleted.
Impossible self steps 11 -> 4 (death) and 2 -> 0 (frozen); self track keys
3 -> 1 in both. `minimap.pick_self` already did the nearest-to-previous version
of this and the overlay had never called it.

**What the Haven windows expose and did NOT fix, in the order worth attacking:**

* **the detector's own acquisition looks like births.** A window opens, the
  detector finds allies over the next ~0.4 s, and each arrival is an
  `unexplained_appearance` -- the lifecycle's boundary is a single moment while
  acquisition is spread over time. This is most of the 116-154 quarantines in
  the Haven windows. **The roster is the cross-reference** (`ally_icons` scored
  against it is the precedent in `CLAUDE.md`): an appearance is explained when
  a live teammate is unaccounted for. This session has no `l1/roster` table;
  that is the blocker, not the rule;
* **a large team-coloured ability circle keys as ally.** In the death window a
  teal ring spanning much of the map produces icon fits on its arc. `area`,
  `cov`, `inner` and `r` all overlap with real icons, so no detector feature
  separates them -- the entity model's `static`/`settles` classes exist for
  this and nothing produces them;
* **a stationary ally-coloured object** at (78,228) is quarantined for 101
  consecutive observations, before AND after the buy menu. Zero movement over
  1.67 s is not a player;
* **once quarantined, always quarantined**, by design (*a repeated candidate
  cannot corroborate itself*). Correct, but it means a real ally acquired late
  in a window is lost for the whole window. The roster fixes this too;
* `ambiguous_continuation` fired for the first time (8 rows, death window) --
  two parents inside the ceiling. Not yet looked at.

101 tests, `--self-test` PASS, doctor 2 findings / 0 errors. The Ascent control
is unchanged through all of it: 1 self, 1 ally, 0 quarantined.

### `l1/roster` exists now, and it already explains the Haven death window

    reticle scan 96aa1ae9b96f --only roster

3375 rows at 2 Hz over the whole capture, 122 s. **Answered 2892/3375 (85.7%),
5v5 on 1498 (44.4%), and 483 rows (14.3%) defer to the HUD gate** -- that is
COVERAGE, not accuracy; the deferred rows are unanswered, not wrong, and
`reticle audit` resolves them.

**It named the death immediately.** `alive_ally` goes 5 -> 4 at 262.5 s, so the
player's "4:21-4:23 has a death" is an ALLY dying at ~262.2, not the player --
which is why that window never lost its widget and why the ally detections
jump at 262.8.

**What it will do to the quarantines, measured but NOT wired in** (the roster
counts the player, so the expected icon count is `alive_ally - 1`):

    window          quarantined allies while a slot is FREE   while FULLY accounted
    haven-death                  154                                   0
    haven-buy                    110                                   4
    haven-postplant                4                                  26
    haven-frozen                   0                                   0

Both directions are useful and they are different claims. Where a slot is free
the appearance is PERMITTED, which is what kills the "detector acquisition
looks like a birth" false quarantine. Where the roster is fully accounted for
-- 157 of the post-plant frames -- an extra ally detection is a phantom by
count, which is a positive rejection rather than a refusal. **Permission is not
identification**: a free slot licenses one more ally, it does not say which
detection is the ally, and the arc-fragment phantom below sits in a frame with
a free slot too.

Note the roster reader is itself STALE through a capture stall -- it reports
5v5 confidently across all 20.4 s of frozen picture. The stall class touches
every channel and only the minimap channel currently knows about it.

### The three residual errors, looked at

**1. A large team-coloured CIRCLE, and the ally key catches its arc.** It
appears within ~0.7 s of the ally death, centred near B, and persists for
seconds. Only 156 px of the whole widget key as ally at 263.5 s and 22 of them
are far from any icon -- a thin arc fragment -- and the ring fit sits a legal
circle on it at (161,173). **Shape is suggestive and does not separate it:**
component elongation is 7.12 median for quarantined against 2.18 for eligible,
but 31% of REAL icons are also >= 3.0. That is the aspect-ratio trap this repo
already paid for once (*0 of 55 hand-marked icons have aspect >= 2.0* would
have deleted Sage walls and ping ripples). Do not ship an elongation gate.
**Ask the player what the circle is** -- one word names the ability and the
`static` class already exists for it.

**2. A stationary team-coloured CAPSULE** at (78,228), in a corridor, 110
observations from 221.63 to 227.0 with zero pixel movement, spanning the buy
menu. Absent at 221.2 and present after. Also an ability glyph, also unnamed,
same question.

**3. `ambiguous_continuation` is the crowded-cluster case and it is working.**
All 8 rows are one shape: a new track id appears at (115-125, 183-194) with
`alternatives ['ally:1','ally:2']`, in a cluster where four allies sit 12-13 px
apart. The lifecycle refuses to guess which entity it continues, which is
right; the cause upstream is the tracker minting a new id inside the cluster.

**A correction to a worry recorded earlier today.** `MIN_ICON_SEPARATION_PX` is
NOT merging real allies on Haven. With the dedupe disabled there are 257
same-frame ally pairs under the 11.4 px limit and they are 1-3 px apart with
`|dr|` of 0-1 -- the same icon fitted twice, not two teammates. The smallest
SURVIVING separation being exactly 11.4 px is an artefact of the rule, not
evidence that real allies sit there; genuine pairs live in the 11.4-20 px band
(312 of them in the death window alone) and they survive.

### ANSWERED: both glyphs are real objects, and both are structural work

**1. The circle is SOVA'S RECON DART scan radius.** It is not an entity that
moves and it is not an ally -- and it is a REVEAL SOURCE, which is the part
that matters here: `LEGAL_ORIGINS["enemy"]` already lists `reveal`, so an enemy
icon appearing at a dart pulse is an EXPLAINED origin rather than an
unexplained appearance. Three properties decide how it must be modelled:

* **two pulses per dart**, so it is two discrete reveal events, not a window;
* **it reveals only what the pulse can SEE from the dart at that instant** --
  so the revealed set is a line-of-sight computation from the dart's position,
  which `cone.raycast` over the passable/box geometry already does. The drawn
  circle is the bound, not the answer;
* **the dart has variable verticality** -- it sticks to walls and ceilings --
  so the circle on a 2D minimap is a projection of a scan whose origin is off
  the floor plane. **Do not treat the drawn radius as ground coverage.**

**2. The capsule is an ALLY BARRIER (the buy-phase spawn barrier).** Haven
attack has FOUR, of varying widths: left to right, the doorway to C main, the
doorway to mid/doors, the doorway to "true mid", and the widest at the entrance
to A site. That matches what the buy phase shows -- keyed components persisting
across >= 30% of 29 samples from 222-250 s, in one horizontal band, with the
rightmost by far the widest:

    barrier            widget centre    keyed bbox
    C main                 ( 82, 230)      4 x 8
    mid / doors            (138, 233)      6 x 2
    "true mid"             (177, 226)      4 x 4
    A entrance (widest)  (185-209, 231)   ~24 x 4   (two fragments of one bar)

These are anchors, not extents: the ally key catches only part of each bar, so
a barrier detector must measure the bar on its own colour rather than on this.

**Barriers are STATIC MAP FURNITURE, so they belong in the map state**, baked
once per map and side rather than detected per session -- they are in the same
place every round, they are drawn in team colour so they key as ally on every
map, and they exist only during the buy phase. Baked, a keyed blob at a barrier
anchor during the buy phase is explained instead of quarantined. The player has
also already made the point that a barrier is a PHASE LANDMARK -- a known
position appearing at a known phase -- so it can check that the stored geometry
is still aligned, per round, for free. That is his, not a suggestion from here.

**And barriers were not an unknown: `minimap.py` has named them since it was
written.** Lines 734-739 list three confirmed false-positive classes -- "the
teal SPAWN BARRIERS drawn across doorways in buy phase, the blue X marks a
teammate death leaves, and green scenery reaching the key through the
semi-transparent widget" -- and this session rediscovered all three from
pixels: the scenery one became the slab-support rule, the barrier one became a
110-observation quarantine I asked the player to identify, and the death X
marks are the untested third. **The fixes are new; the identifications were
not.** Read the owning module's own recorded failure classes before treating a
detection as unexplained.

### The timestamps these were answered from

Both are in `96aa1ae9b96f` (Haven), bounded by decoding the ally key at the
positions rather than estimated:

* **recon dart circle** -- 262.8 to ~265.5 s (4:22.8-4:25.5), clearest at
  263.5 s; centred near B, radius ~55 widget px, alive ~2.7 s, appearing within
  ~0.7 s of the ally death at 262.2 s;
* **ally barrier** -- first keyed at 221.5 s (3:41.5), gone by 252 s (4:12), so
  it lives the buy phase; widget (82,230), zero pixel movement throughout.

### The stall class propagates through `l1/primitives`, not through an emitter

The player, on the architecture: *"The stall class should propagate to
everything. I'm not entirely sure architecturally how to handle that. If we're
doing it purely sequentially maybe a timestamped event emitter, though there is
almost certainly a better way."*

**There is, and most of it is already built.** A stall is a property of the
SOURCE FRAME, not of any channel, and `l1/primitives` already stores a
whole-frame `motion` column per frame at 5 Hz for all 50 sessions -- computed
once on the shared decode pass, versioned, and recomputable without touching
video, which is the standing rule an emitter would break (an emitted fact
exists only during the run, so a later analysis over stored data cannot see
it).

`motion == 0.0` is the stall signature and it separates cleanly:

    window                       motion median   p90      min
    stall 1 (407-428)               0.0000    0.0000       --
    stall 2 post-plant (706-713)    0.0000    0.0923       --
    death window (259-266)          0.0861    0.1059    0.0100
    100 s of ordinary play          0.0836    0.1416    0.0001
    buy menu open (221-227)         0.0288    0.1687    0.0001

Zero-motion runs come in ~3.6 s pieces separated by one non-zero row -- almost
certainly the encoder's keyframe interval refreshing a frozen picture -- so the
span rule must MERGE runs separated by under a second. With that, the whole
corpus maps in about a second of compute:

    session         stalled   longest      session        stalled   longest
    3694746e4e54      9.2%     71.4 s      bfad2778a372     2.9%     27.8 s
    96aa1ae9b96f      5.1%     26.2 s      59c70f1ef720     2.0%     23.4 s
    587c15b07779      4.3%     31.8 s      bdfdcf009dba     1.4%     16.0 s
    ...                                    a06f04a0059f     0.7%      9.2 s

**12.3 minutes of stalled capture across the corpus**, and in `96aa1ae9b96f`
five multi-second episodes at 6:47, 8:19, 9:44, 11:47 and 18:14 -- the player
knew about two of them. Short ability-demo clips read 4-17% and should be
treated as suspect rather than stalled: a static practice-range scene can
genuinely repeat a thumbnail, and 2 s is a large fraction of a 40 s clip.

**BUILT, 2026-09-08 (`reticle/stalls.py`, `stalls-0.1.0`).** It has the shape
`segment` already has: a derived, versioned span rule over stored primitives,
recomputed on demand, that every consumer JOINS against and each interprets for
itself -- a reader records no observation, a tracker ages without observing, a
metric drops the frames from its denominator. The shared layer states the fact;
it does not decide the response. `for_session` returns None when a session has
no primitives, which is UNKNOWN rather than "no stalls", and the diagnostic
records which of the two it is.

**The minimap-local check it supersedes is DELETED**, not left beside it:
`STALE_DELTA`, `source_delta`, `stale_source` and the round-clock witness are
gone, along with the overlay's per-frame luma compare and clock bookkeeping.
That machinery measured one ROI on the decode path to answer a question a
stored whole-frame column answers for every channel at once. The overlay now
looks the timestamp up in the spans. Verified on the real command over
405-430 s: the stale stretch is 406.8-427.5 s, matching the 407.2-427.6 the
deleted per-frame check measured, at zero per-frame cost.

`doctor` carries a STALL check so the load is visible at every pickup rather
than only inside a render -- 4 sessions over 2%, worst `3694746e4e54` at 9.2%
with a single 71 s stall. Captures under five minutes are skipped: the
ability-demo clips are a static practice range where a motionless scene
genuinely repeats a thumbnail, they all report 4-17%, and left in they were 26
of 36 findings.

**Not yet joined: the other readers.** `hud`, `roster` and `ping` still record
observations during a stall. They read at decode time, so wiring them is a
change to `cmd_scan`'s shared pass rather than to each reader, and it wants
measuring before it ships -- a roster row inside a stall is not wrong about the
picture, only about the world.

### Next session, as it was framed before the rounds were rendered

The player's framing, and it was the right one: **lifecycle tracking makes
sense round start -> round end**, not on 2-7 s windows. Capture stalls are a
missing-data class to work around rather than a defect to fix. DONE -- both
rounds above are rendered, and 21 of the 22 complete rounds across the two
recordings have no stalled capture at all, so the stall constraint never bound.

### Earlier increment

Plan and acceptance gates: `docs/MINIMAP_DETECTION_PLAN.md`. Native 60 Hz,
two-second Ascent/Lotus renders now carry track IDs, observation-gap ages,
adjacent-light evidence and distance-binned cone disagreement in a versioned
JSONL sidecar (`overlay --minimap-diagnostics`). Missing widgets advance the
trackers; elapsed gaps expire them; integer-center quantization has an explicit
association uncertainty. 83 tests pass; doctor remains 2 findings / 0 errors.
Raw-data replay cuts self ID births 25->13 and 21->10 in those windows; this is
less fragmentation, not accuracy. Phantom allies and fit jitter remain visible.
`tools/minimap_sequence_review.py` builds unseeded offline player review pages;
the generated scripts parse, but no browser connection was available for UI QA.
No light-rejection gate or ability attribution was promoted. Start from the
reviewed failures and the plan, not by increasing motion tolerance.

## Previous handoff -- 2026-09-07, the viewcone channel, end to end

`doctor` 2 findings / 0 errors, 76 tests. Five commits today and they are one
thread: the entity channel was reading the wrong things, and every fix came
from a SECOND CHANNEL rather than from tuning the one that was wrong. That
reflex is now a global constraint in `CLAUDE.md` -- read it before touching a
detector.

**What was wrong, in the order it was found.** Geometry was keyed per session,
36 npz holding 5 geometries; it is now `<map>__<profile>`, 11 keys over 50
sessions. `classify` carried an unscaled copy of the site test and labelled ZERO
of two Lotus bomb sites. `two_state_gray` was fitting "the widget was drawn"
instead of "an ally can see this", because blacked-out transition frames went
into the fit -- a third of Lotus read permanently lit. Rays passed through boxes,
which the recorder corrected: sight terminates at walls AND boxes. The bearing's
180-degree lobe was never resolved. And 17-29% of solid floor could never be lit
at all, because the fit demanded each pixel be OBSERVED unlit.

**Where it stands, measured on the two painted maps:**

    always-lit artefact      33.7% -> 0.0-0.4%      (a pixel lit every frame)
    known floor              71-83% -> 99-100%
    bearing flip rate        12.4% -> 4.9%          (independent validator)
    cone precision           15.9% -> 41-45%
    cone over-claim          4.4x -> ~1.5x

The flip rate is the honest number. Precision and recall are scored against the
lit mask, which is a second DETECTOR and not ground truth, and since the bearing
is now chosen using that mask they are partly circular. Say so when quoting them.

### FIRST THING NEXT SESSION: the over-claim number disagrees with the picture

**The recorder, looking at the rendered cones: it does not read as over-claiming
by 50%, if anything it under-claims.** That is a direct contradiction of the
`over-claim ~1.5x` figure quoted above and it is the next thing to settle,
because one of the two is wrong and both are being used to steer the work.

The rendered grids support the objection: per-frame the ratio of raycast area to
lit area was 1.25, 1.49 and 3.6 on Ascent and **0.55**, 1.04 and 1.54 on Lotus.
One of six is under half. So the summary statistic is hiding a wide spread.

Four candidates, cheapest first, and they are not exclusive:

* **the statistic is a median of per-frame ratios**, which is not what an eye
  reads off three chosen frames -- report the distribution, not the median;
* **the grids predate the unlit fill** (`a908fd2` landed after they were drawn),
  and the fill grew `lit` substantially. Re-render before comparing anything;
* **the error is SPATIAL, not uniform.** The raycast is unbounded in range, so
  it claims thin slivers far down corridors -- little visual weight, real pixel
  count -- while missing near-field area around the icon. That would read as
  under-claiming to a viewer and over-claiming to a pixel count at the same
  time, with no contradiction;
* the frames chosen for the grids were selected for enemies and abilities, which
  is not the sample the statistic was computed over.

**The measurement that separates them: decompose precision, recall and the area
ratio BY DISTANCE from the emitter.** If over-claim concentrates past ~60 px
while recall is lost inside 20 px, the third candidate is it -- and that lands
directly on the standing open question of whether the drawn cone has a visible
edge at some range or simply dims out (lit share 51% at 0-20 px falling to 13%
at 100 px, over 407 cones). An unbounded raycast is the wrong model if it ends.

### Then, in priority order

1. **Icon rejection by adjacent light is measured but NOT wired.** An ally lights
   the ground around itself, so an icon with no lit pixels beside it is a spawn
   barrier or a death X -- the two classes `minimap.py` already lists. Rejects
   24.5% of Ascent icons and 15.8% of Lotus's. Rendered and inspected: the
   rejections do land on featureless floor marks while portrait-bearing icons
   are kept. **It has a failure regime** -- in a frame with almost no light,
   every icon rejects -- so it needs a light-budget guard and probably a
   persistence test (a barrier does not move; an ally does) before it gates
   anything.
2. **Guessing the emitters the aggregate lost.** Leave-one-out: hide a detected
   icon and recover its bearing from residual light alone. Median error 39.2 deg
   on Ascent, 48.8 on Lotus, against 90 for a random bearing; 42.2% within 30
   deg against 16.7%; and only 3.0-5.3% opposed. **So it is a good DIRECTION
   estimator and a poor bearing one** -- consistent with `resolve_lobe`, where
   the binary choice works and the continuous estimate does not. Use it to place
   a coarse cone for a track with no detection, not to refine one that has it.
3. Unverified hypotheses from the recorder, each cheap and each worth a look
   before building anything: a white teleport ring near an icon suppressing its
   detection the way the audio ring does; the buy-phase weapon panel drawn OVER
   the minimap ROI (visible on Lotus, and neither of today's two failure modes);
   ability zones such as sonic sensors shading a region that then reads as lit.
4. The mechanical doors still read permanently lit -- 188 px on Ascent, ~360 on
   Lotus -- and are the last known instance of "an object whose resting state is
   the bright one inverts the two-state fit".

### Superseded today, do not re-derive

`--geometry-from`, `--two-state-from`, `tools/rebuild_geometry.py`, doctor's
DONOR check, and the inline plant test in `classify` are all deleted. The
base-shade restriction `NOTES.md` predicted would fix the always-lit artefact
was measured and makes it WORSE (32.8% -> 35.6%); it held only on the session it
was measured on. Fitting an affine on the art's rendered grey to predict the
unlit level also fails, held out, at MAE 8.1-10.4 against a constant's 5.3-9.8 --
the art's terrain CLASS works, its grey value does not.

## Superseded -- 2026-09-07, geometry is keyed per (MAP, PROFILE)

`doctor` is 2 findings / 0 errors, down from 4 / 1. The stale-geometry error --
the blocker every minimap number sat behind, and the one the last two handoffs
inherited -- is closed, and the layout that kept re-creating it is gone. 60
tests pass (50 before). The next thing in the minimap channel is job 2 of the
re-validation, re-reading `l1/minimap`; nothing there is blocked any more.

**The store had 36 geometry npz holding 5 distinct geometries.** Twenty-nine
were one 39-minute Ascent match copied to twenty-eight ability-demo clips by a
`--geometry-from` flag, because a 37s clip built around one deliberate cast
cannot median its own static map without baking the cast in. That number is the
whole argument: geometry is a property of the LEVEL and the widget it is drawn
in, not of the recording.

    store/geometry/<map>__<profile>.npz      11 keys, covering 50 sessions
    store/reference/fits/<map>__<profile>.npz  the art fit, same key, same reason

`reticle/geometry.py` owns the key and every path that used to be built by hand
from a session id. `minimap_geometry.py --all` rebuilds every key from its
reference session -- the longest recording on that key -- in 5m40s, and
re-attaches shade on each write. `--geometry-from` and `--two-state-from` are
deleted, not deprecated: sharing IS the key now, so there is one write path and
nothing to choose wrongly. `tools/rebuild_geometry.py`, written earlier the same
day to order the donations, went with them.

**Three defects the old key could produce and this one cannot.** The copy was
invisible (a donated npz recorded nothing about its donor, so the relation
survived only as a byte-identical `static`). A rebuild looked like 36 decodes
when it was 5, so it was deferred, so the stamp stayed stale. And one map could
hold different answers per session with nothing comparing them -- the two Lotus
recordings disagreed on 0.35% of pixels and their stored lighting references by
24 grey levels, which `prototypes/CLAUDE.md` had already measured as an artefact
of different frame counts in different runs rather than of the recordings.
`doctor`'s DONOR check went too, replaced by COVERAGE: a donor shared across
widget sizes is now unrepresentable, and a check that cannot fail is worse than
no check.

**Verified, not assumed:**

* `floor_mask_eval` reproduces **78.8% / 77.9% IoU at 100% recall** against the
  two paintings -- the number recorded in `reticle/minimap.py:223`, read through
  the new resolver off freshly rebuilt per-key geometry;
* `cone.py --bench` still reports **0 disagreeing pixels**, 2.56 ms/cone;
* `STATUS.md`'s K/D, rounds and plant columns are unchanged; the only movement
  is the `geo` column, `-` to `y` for **18 sessions** that now reach geometry
  because their map has it;
* SITE against derived PLANT holds at **87.5% / 87.4% / 87.9%** on the three
  bigmap keys, against 87.4-87.9% before the rebuild;
* 60 tests, including `tests/test_geometry.py` on the key itself.

### What the new coverage exposed, which is the point of having it

Five keys now exist that never had geometry: abyss, haven, lotus and split at
`valorant-16x9`, and summit. Scoring them against the art immediately found one
outlier:

    ascent__valorant-16x9-bigmap   SITE vs PLANT  87.5%
    split__valorant-16x9-bigmap                   87.9%
    lotus__valorant-16x9-bigmap                   87.4%
    split__valorant-16x9                          85.0%
    ascent__valorant-16x9                         84.4%
    sunset__valorant-16x9                         76.4%
    haven__valorant-16x9                          74.8%
    abyss__valorant-16x9                          72.4%
    lotus__valorant-16x9                          35.4%   <- 732 px derived
                                                             against 1793 art

**`lotus__valorant-16x9` finds 41% of the plant zones it should.** Small-widget
keys score lower across the board (the plant tint test was tuned at bigmap), but
this one is not on that gradient -- it is a different failure. Nothing has been
changed to chase it; it is written into `BACKLOG.md` with what would make it
worth doing. Two summit keys carry no shade at all because `summit.png` has
never been fetched, which is `doctor`'s remaining SHADE finding.

### Three things settled on the way, each of which was an open question

**`2ba870ccbd50` is Ascent on the LARGE widget: the tag was wrong, the ingest
was right.** Measured off its own frames, not its npz -- the npz was a donated
copy and said nothing about the session. Against the stored statics at every
scale from 0.55 to 1.05 the best fit is Ascent at **scale 1.00** (corr
0.686/0.691 against the two Ascent geometries, 0.071 Split, 0.050 Lotus).
Retagged `ability-demo brimstone map:ascent minimap:large`; only what was
measured went in, so `outline:red` and `custom-game` were not invented. This
also corrects `prototypes/CLAUDE.md`, which reasoned about the unexplained
borrowing failure from *a different map and profile* -- it is the same map and
the same profile, so a wrong crop is no longer a candidate explanation.

**`79a706a7ce4c` is Ascent too** (its own static correlates 0.949 with Ascent
and 0.102 with Split), which closed the one npz with no shade. It was also the
one short clip still deriving geometry from its own 44 seconds, and the diff
against the shared version shows why that is not allowed: **its static had
Cypher's placed camera and trapwires baked in as map structure**, and its
classifier put 347 px of "plantable" in the void beside A site. Labels differed
by only 1.14% of pixels, so no aggregate was ever going to show this; a rendered
diff showed it in seconds. Two more untagged Ascent clips (`d95cfad5693a`,
`eb10db50b1fb`) were identified the same way and tagged.

**A rebuild could silently drop the shade.** `map_shade.write_shade` declines
without raising when it cannot place a map, and `reattach_shade` was best-effort
over exceptions only -- so a rebuild dropped shade two npz already had and
`doctor`'s SHADE finding went 1 -> 3 with nothing in the output saying so. The
npz is now checked for shade BEFORE it is overwritten, and losing arrays that
were there prints a line: a different event from never having had them.

### Where the old numbers moved, measured against a pre-change snapshot

Taken while the per-session layout still stood, so it is a real before/after:
27 donated copies moved 0.08pp of border to box edge (they carried an older
build of the donor's labels), one split key 0.12pp, and **the three
`valorant-16x9` sessions moved floor -1.80pp to void +0.93 and hole +0.87.**
`BACKLOG.md` predicted exactly that in advance -- *the lengths in `floor_mask`
now scale with the widget, which moves three small-widget sessions and no large
one* -- and this was the first time that prediction had been run. The direction
is conservative: the mask admits less of the semi-transparent void.

## Superseded -- 2026-09-07, architecture steps A1-A4 landed

`docs/ARCHITECTURE_PLAN.md` is the execution plan; its status table now carries
the evidence. A1 split the eager `CLAUDE.md` (71 lines) from `PROJECT_GUIDE.md`,
which retains the former 1523-line guide verbatim. A2 moved `_HudPass` into
`reticle/hud_reader.py` with a CLI alias. A3 put artifact producers and stale-input
checks on one declaration in `reticle/artifacts.py`. A4 added `tools/task_check.py`
and `docs/tasks.json`: a work packet names its reads, owned files, acceptance
argument arrays and evidence, and the runner appends a result to the external
`notes/development.jsonl`.

Acceptance rerun at pickup, not inherited: 50 tests pass (41 at baseline), all
three contracts pass, `git diff --check` is clean, and the fixed 14s review
`ea445110508b26f12d4e` re-emits its 840 native rows byte-identical -- only the
producer hash moved. `doctor` is unchanged at four findings / one stale-geometry
error, which is the pre-existing blocker rather than a new regression.

A5 is partial: the runner has the fields to compare delegation cost, but no
attempt is logged with a model yet, so no default model is justified. A6 is
untouched and stays gated on real invalidation examples. Next is still the domain
work below -- inspect dense evidence in disputed windows -- not more architecture.

## Bounded dense evidence from the review queue -- 2026-09-07

`reticle refine SESSION --review-id ID` previews selected review intervals;
`--execute` reads them at native rate with the shipped HUD reader. Overlapping
windows merge before decoding. Dense observations, review references, actual
coverage, source identity and reader hashes go to `analysis/refinement/`, never
over L1 or existing coaching events. Stale provenance, missing mask calibration
and exceeded duration/frame limits refuse. No full-capture calibration is hidden
in this command.

Validated on review `ea445110508b26f12d4e`: 14 seconds -> 840 native observations.
The frame-budget failure preserves a previous artifact. 41 tests pass; `doctor`
is down to four existing findings / one stale-geometry error (UNWIRED closed).
Next: inspect dense evidence in disputed windows before defining onset refinement
or promoting the revive mark. This command supplies observations, not adjudication.

### Ordinary controls in the review queue

`reticle coach` now writes `review.jsonl` and a linked `review.md`: one
chronological event per resolved round plus one ordinary eligible-state control
per eligible round. Windows stop at round/source boundaries; controls can overlap
observed events and are NOT verified no-contact examples. The selection rule and
its own stamp live in `reticle/review.py`, separately from inference.

Stored-corpus validation: 342 windows (316 event, 26 control); all 543 event
observations and eligible states preserved. Probability evaluation still abstains.
30 tests pass. No media decode or L1 changes. Next: review these windows for
usefulness; correction history still waits for an actual human disagreement.
`docs/WORKING_MAP.md` routes new tasks to code and checks without repeating results.
The revive promotion decision and minimap revalidation below remain open.

## Revive mark handoff -- 2026-09-07, three sessions reconcile

`prototypes/revive_mark.py` reads the second-life badge (Phoenix Run It Back,
Kayo stabilise) off a killfeed entry. Score the CONTINUITY of a fitted circle,
never its coverage: a headshot crosshair is four bars round a point, which is a
circle sampled at four places, and it beats two real badges on coverage. Longest
unbroken run separates 0.359-0.453 against 0.125-0.219 with nothing between.

`RUN_MIN = 0.29` was fixed on `587c15b07779` and written down before anything
else was scored. Three sessions then reconcile to the scoreboard EXACTLY, with
that gate unchanged and both plate colours covered:

    ff636d173b07  --side death   4 of 24   24 - 4 = 20 = KNOWN_KD deaths
    bfad2778a372  --side kill    1 of 20   20 - 1 = 19 = KNOWN_KD kills

The four death timestamps match marks found by hand off a contact sheet long
before the reader existed. **8 positives, 3 sessions, and the agent is Phoenix
every time** -- Kayo is the remaining gap in the class.

**Scan in the module's own slot, not the frame's maximum.** `entry_marks`
returns every entry on screen and other players' entries carry badges too; an
ally kill at 524.8s on `ff636d173b07` scores 0.453, higher than three of the
four real ones. Frame-maximum finds 5 of 24 and breaks the reconciliation.

### THE DECISION WAITING: promote it into `killfeed.py`?

That means a `HUD_VERSION` bump and re-reading all 18 sessions. The evidence is
now three independent reconciliations rather than one, which is what was missing
when this was last deferred -- but it is still one agent. `CLAUDE.md` has wanted
this since 2026-08-25 and the position on it is settled: **tag the events, do
not drop them**, because a duel lost inside Run It Back is still a duel lost.

### Everything else from this session

Round starts moved to the clock reset (`round-0.2.0`) -- median 28.0s over 275
rounds, where the roster predicted 28.0s from 26. Rounds are no longer
contiguous; the 7.5s gap is the post-round period, and every consumer was
checked empirically (0 events mis-attributed, 504 attributed + 39 unresolved =
543). Audit disagreements 6 -> 4 and 2 -> 0. `STATUS.md` byte-identical.

The roster reader is done: ratio split plus a HUD gate on the empty bar
(`roster-split-0.2.0`), and `l1/roster` stores the detail vectors so a rule
change re-derives instead of re-decoding. All ten unresolved audit windows are
diagnosed and NOT ONE is a roster error -- three are Run It Back, three are
killfeed tracker defects, two are onset straddling a window boundary.

Failed, recorded so they are not retried: `over_long` is not a merge detector;
frozen runs do not localize round boundaries; the killfeed is not systematically
late (median +0.00s over 182 matched drops -- do not widen `ENTRY_ALIGNMENT_MS`);
cross-slot spread does not separate an undrawn roster from a wiped one.

## Minimap handoff -- 2026-09-07, the BASE layer is built

### DONE 2026-09-07: the art's terrain LEVELS are in the geometry npz.

`prototypes/map_shade.py`, additive, **9 of the 11 (map, profile) keys** --
35 of 36 session npz when it was measured, the same coverage under the layout
that replaced them; the two exceptions are the summit keys, whose art has never
been fetched. Six classes rather than a
level table -- FLOOR (a per-map ladder), RAMP, SHADOW, LINE, SITE, VOID -- plus
`shade_step`, `shade_purity` and the fit used. Full argument and every figure in
that module's docstring and in `prototypes/CLAUDE.md` under "THE BASE LAYER IS
BUILT". The three that matter here:

* **51.9% of every always-lit pixel is off the base shade**, and the artefact
  rate climbs monotonically with the rung (8.1% at base, 35.8% at +5) while the
  real cones fall away with it (7.7% sometimes-lit at base, 0.1% at +5);
* **SITE against the derived `PLANT` labels is 87.4-87.9% IoU** on the three
  bigmap keys -- an alignment check the alpha fit cannot give. It held across
  the re-key. The five small-widget keys score 35-85% and are a live defect,
  not a result: see `BACKLOG.md`;
* **two stored fits were stale and worse than the code's own answer**
  (`a06f04a0059f` 79.9% -> 94.6% IoU). Recomputed. `cone_terrain`'s numbers were
  measured through the worse one and **survived unchanged**.

**Licensing: SETTLED, and not as a risk being managed. Corrected 2026-09-07.**
This used to read *"the recorder is content to take level geometry from the wiki
art"*, which turned a POSITION into a tolerated risk. The position is that where
a level's floors, walls, elevations and sites are is DATA about the level rather
than anything expressive, so there is nothing in it for a copyright interest to
attach to. The art is an instrument for measuring that data.

What the code does follows from it and is worth stating plainly, because it is
checkable: the PNGs are fetched into the store, which is outside the repo, and
no PNG has ever been committed here. What this repo produces and ships is
`reference/shade/<map>.npz` -- class indices per pixel -- which is the
measurement, not the render.

### Next within the minimap channel (the cache is revalidated)

**The ANNOTS layer: subtract the audio ring and the icons, then fit bearings to
the residual.** BASE now exists, so this is the next layer down the list in
`prototypes/CLAUDE.md`'s "THE WIDGET IS LAYERS", and it is unblocked rather than
merely next.

    per frame:  fit an affine art-grey -> observed on pixels explained by
                nothing else, using `shade` as the art level
                subtract the KNOWN-geometry annotations -- the audio ring
                (an annulus at 94-95 px round the self icon, drawn only while
                running), the icons, the X marks
                what remains is LIGHT: the union of the team's cones

**Two things the shade work says about how to do it.** The affine should be
fitted on `shade_kind == FLOOR & shade_step == 0` only -- the base shade is 72%
of the usable area and carries 90% of the real cone pixels, so it is both the
biggest and the cleanest population. And `shade_kind == LINE` should be excluded
from every lit test outright: it is 21.4% always-lit and it is not terrain.

**DONE 2026-09-07: every key with art carries shade.** `79a706a7ce4c` measured
as Ascent, tagged, and then dissolved as a question entirely -- it reads
`ascent__valorant-16x9-bigmap` like every other Ascent bigmap session, because
geometry is no longer per session. Only `summit` is uncovered, and the fix is
`wiki_map.py fetch summit` rather than anything about a session.

**The `map_shade.py build --all` follow-up is no longer a follow-up.**
`minimap_geometry.py` re-attaches shade on every write and says so out loud when
a rebuild loses shade that was there. `--all` verifies coverage after it runs
rather than leaving it to whoever remembers.


**The observable area is built, drawn and measured, and the session ended on a
DESIGN CORRECTION that supersedes how it is computed. Read this section's last
part before extending anything.**

**What shipped and is solid:**

* `reticle/cone.py` -- the raycast, promoted out of `minimap_cone`, vectorised
  (2.74 ms/cone against 37.40, exact agreement with the loop on a real map).
  `passable` and `visible` split, fixing a real under-claim bug;
* `fit_ring` promoted to `reticle/minimap.py`, byte-identical
  (`minimap_icon_eval --finder ring`: 86.3% / 48.1% either side), and its
  circle search vectorised 8.7x, again exactly equivalent;
* `minimap.ally_icons` -- a blob becomes an icon by ring coverage, a non-key
  interior AND a facing lobe. Scored against the ROSTER, which is a label-free
  ground truth (`n_icons == alive_ally - 1`): raw ally blobs carry a **+0.99**
  residual, one phantom teammate per frame; promoted icons carry **-0.15**,
  **20 of 24 rounds agreeing, 95% CI [64%, 93%]**;
* `track.Tracker` -- Hungarian identity, motion law as an inadmissible cost,
  plus `resolved_facing`: a windowed circular mean with a RESULTANT gate;
* `overlay.py` draws the minimap channel -- icons, bearings, per-icon cones,
  the aggregate. AMBER is a refused bearing.

**THE THREE FINDINGS, in the order they matter:**

1. **THE WIDGET MUST BE SOLVED AS LAYERS** (`prototypes/cone_terrain.py`, and
   the section of that name in `prototypes/CLAUDE.md`). Terrain shade reads as
   illumination at 3x, the audio ring is baked into the static reference, and
   the derived floor mask agrees with the wiki art's exact alpha at only 75.6%
   IoU. Per-pixel tests for one layer ask a question the pixel cannot answer
   alone. **This is where the next session starts;**
2. **the reconstruction OVER-claims about 3x** against the area the game draws
   (`cone_lit.py`). Recall is high, precision is low. That dwarfs the 13% of
   area the ambiguity gate gives back, which was the wrong thing to optimise;
3. **the raw per-frame bearing FLIPS 180 degrees on 16% of frames**
   (`cone_flip.py`), from a thick annulus whose "reach past r" is uniform, so
   the argmax follows centre jitter. Gated, not solved -- and ally bearings
   turn out BETTER than self (7.2% against 16.1%).

**NEXT, in order:**

1. **the BASE + ANNOTATIONS layer.** Warp the art (the transform is already
   fitted and stored in `reference/fits/`), fit an affine art-grey -> observed
   per frame, and SUBTRACT the known-geometry annotations -- audio ring, icons,
   X marks -- rather than detecting them. The residual is the light. This kills
   the terrain artefact and gives a clean region to fit bearings to;
2. **ally IDENTITY, which is coupled to it** -- icons are one of the subtracted
   layers. 862 tracks over 4266 frames, 27% lasting a single observation, 12
   live tracks for 6 icons in the overlay. This is now the binding constraint,
   not the bearing;
3. re-measure `ally_icons` against the roster afterwards -- the -0.15 residual
   is a COUNT and says nothing about bearings;
4. then the interior-appearance invariant, which is what the area is for.

**OPEN QUESTION FOR THE RECORDER, cheap for them and expensive to derive:** the
drawn cone FADES with distance (lit share 51% at 0-20 px falling smoothly to
13% at 100 px, no cliff, over 407 cones). Does the cone have a visible edge at
some range, or does it just dim out? If it ends, an unbounded raycast is wrong;
if it fades, the lit mask is a conservative floor rather than an outline.
Picking wrong makes the area wrong in opposite directions.

**`CONE_HALF_ANGLE_DEG` is now 51.5 (103 full)**, from a reported fixed FOV of
103 that sits inside this repo's own measured 50-65 band. Provenance is a web
search and the docstring says so; an attempt to confirm it from camera pan
failed on a weapon-model lock in `minimap_self_check._world_grey`.

**Standing asks of the recorder:** unchanged -- more teleport-agent clips for
`TELEPORT_PX`, and the equip-hold-cast protocol.

## The north star for this channel (recorded 2026-09-06)

> a system that can annotate the vods, highlight the abilities, players,
> viewcones, pings, and any other icons as they evolve throughout a match

A visually checkable proof of work, and it outranks any per-detector metric --
recorded in full under "The NORTH STAR for the entity channel" in `CLAUDE.md`.
`reticle/overlay.py` is the vehicle: it exists, it already refuses to hold its
own copy of the logic, and it draws **no minimap entity at all** yet. Extending
it to the minimap channel -- tracks, not per-frame detections, every channel in
one frame -- is the concrete form of this.

## THE ORIGIN-EVENT MODEL is now §10 of the entity doc (2026-09-06)

**An entity's existence interval begins at an ORIGIN EVENT from a closed set:**
round start, ability equip, ability cast, ping, player death, or -- for an
enemy-owned entity -- the moment it left the COLLECTIVE TEAM VIEWCONE.

It is the largest omission the design doc had: §4 said existence is a set of
intervals and never said where one STARTS. The shift is from birth OBSERVED
(first detection, a property of the detector) to birth EXPLAINED (a property of
the world), and it makes a bad frame a missing OBSERVATION rather than a missing
ENTITY -- which is the structural fix for momentary blips, needing no detector
improvement at all.

**Five of the six origins already have readers. The sixth does not, and it is
now the highest-leverage missing piece in the minimap directory:** only the
local player's viewcone is fitted, ally cones are unread, and the enemy half of
the model cannot be built without the collective cone. An enemy entity's origin
is an OBSERVATION event -- a question mark is born when knowledge is lost.

Full argument in `docs/minimap-entity-model.html` §10 and `prototypes/CLAUDE.md`.

## RUNNING IS NEVER SILENT: 0 of 176 windows (2026-09-06)

The corroboration claim -- a player icon moving at running speed should be
making footstep sounds -- measured over all 28 ability-demo clips. Motion class
from the MEDIAN speed over a 1 s window, ability spans excluded:

    class    windows  clips   silent          95% CI
    still        601     28    35.4%   [31.7%, 39.3%]
    walk         995     28     6.3%   [ 5.0%,  8.0%]
    run          176     22     0.0%   [ 0.0%,  2.1%]

**The intervals do not overlap**, so the separation is established rather than
suggestive, and the ordering is monotonic. Running produced sound in every one
of 176 windows across 22 clips.

Two statistics that found NOTHING on a full match, recorded so they are not
retried: broadband RMS (run/still 1.04x) and step-rate cadence at 1.5-4.5 Hz
(0.92x, slightly the wrong way). A match is saturated; the demo clips are where
this question is answerable.

**The earlier PARTIAL result was an aggregate artefact, not a real conflict.**
Classifying on PER-STEP speed let tracker jitter -- which spikes to 80-724 px/s
against `RUN_PX` 45 -- read as running. See the aggregate convention in
`CLAUDE.md`; this was its third instance in one session.

## The audio channel opened, and the tray CONFIRMS it (2026-09-06)

the player recorded `b9558488a607` (Omen, 83 s, Ascent) to a deliberate protocol --
equip, hold the target while stationary, cast, pause, repeat -- and it settled
the question the corpus could not.

**The tray and the audio agree to within one 50 ms bin on 6 casts of 6**
(`prototypes/audio_events.py --align`). Two independent readers, a teal pixel
count in the HUD and an RMS envelope of the audio, sharing no code, no pixels
and no failure mode. That validates the tray reader as much as the audio.

**The second teleport cast has FIVE SECONDS OF DIGITAL SILENCE in front of it**
-- every bin at the 0.0002 noise floor against a cast peak of 21.1. A reference
cut with nothing to be confused with, which is what no amount of filtering
recovers from a clip where the player was running.

**The equip sound is visible**, and it is the claim arriving independently:
two events at 3.65-4.80 s and 13.90-15.05 s, **duration 1.15 s to the bin and
peak 9.2 / 9.4**, one before each of the two teleport casts -- and the player equipped
exactly twice. Other slots are weaker and not claimed; the first E cast has
nothing before it at all, so coverage stays unverified exactly as the player hedged it.

**NEXT on this thread:** cut the references (the ult voicelines already exist,
56 of them, all decoding), then a matched filter, then NMF with a fixed
dictionary for the overlapping case. `prototypes/passes.py`, not another decode.

## Picking up

**2026-09-06, late. A long architecture session. Six plan items, and the
running theme is that two of them were WRONG and the measurements said so.**

Read `BACKLOG.md` first -- it is new, and it holds everything tabled with the
reason and the trigger that would un-defer it.

**What shipped:**

* **`floor_mask` was forked for ten days** and is reconciled (`18b0912`).
  78.8% / 77.9% IoU at 100% recall against the paintings, up from
  57.8% / 74.0%. **A SITE IS FLOOR** -- the correction, mid-fix, and it caught a
  real defect: 9.6% of stored self positions sit inside one;
* **`reticle doctor`** -- the repo's half of `status`. Six structural checks,
  and it found a manifest contradiction nobody was looking for
  (`2ba870ccbd50` tagged small-widget, ingested bigmap);
* **`l1/roster`** -- alive counts are stored, riding the HUD pass for free.
  The audit that validates it now runs off L1 with no decode and reproduces the
  seek path exactly;
* **`metrics` intervals** -- `wilson`/`bootstrap_ci`, on CHANGED only. The plan
  said to soften BROKEN with them, which was backwards;
* **`reticle/track.py`** -- motion as a property of IDENTITY, 18 self-tests,
  Hungarian assignment;
* **the entity model doc gained §6**, republished: the drivers ARE the tracking
  constraints, with the fourteen-row invariant inventory.

**Three measurements that changed the plan rather than confirming it:**

* **overlap is TRANSIENT** (the claim, tested): median 4.75x extent
  variation over a window, 9 of 10 events, 12% of frames a clean look. So
  identity precedes grouping, and the labelling pass must show a WINDOW. The
  grouping pass is therefore NOT next;
* **there is no dash mode** in 102,239 steps -- a smooth decay from the walk
  ceiling, so `track.DASH_PX_S` cannot be validated and the census refuses to
  quote a defect rate resting on it;
* **`filter_track` cannot tell a teleport from a phantom**: 54.7% of the 11,599
  observations it drops sit at teleport distance. Backlogged.

**Item 1 is DONE**: `filter_track(..., motion=None)` takes a `track.CLASSES`
key, the default path is byte-identical on all five sessions (93,553 points),
a teleport is kept and never interpolated across, and seven self-tests cover
it. `jump_census.py --motion` measures what opting in would do:

    observations kept    default   walker   walker_dash   walker_teleport
    pooled 102,765        88.7%    81.9%       95.0%          89.5%
                                  -6,987      +6,508          +835

**That is not what the entry predicted, and it re-aims item 2.** `admits` makes
two changes at once -- it adds the teleport branch and removes the 1.6x slack
the fixed gate always had. Against a strict walker the teleport branch is worth
+7,822; the lost slack costs -6,987 of it. Three of five sessions come out
NEGATIVE. So the old gate's slack was doing a motion class's job badly, for
every agent at once.

**Item 2 is BUILT and MEASURED** (`prototypes/cast_motion.py`), and it found
why the chain underperforms. `filter_track` also takes span-conditional motion
now -- `[(t0_ms, t1_ms, class), ...]` -- which is the mechanism item 2 wanted.
The class map is derived from `ability_reference`'s `functions` field rather
than hand-listed (and `Displacement` had to come out of it: it licensed jumps
for four ultimates that move ENEMIES, not the caster).

**What a teleport actually looks like, measured for the first time** -- largest
step in the 3 s after each teleport cast, agent from the ingest tag:

    yoru GATECRASH 4.6 / 6.3 px    omen Shrouded Step 38.5 / 40.1 px
    veto Crosscut 65.0 / 6.8 px    chamber Rendezvous 323.8 px

**`track.TELEPORT_PX` (200 px) is far too high, and `walker_teleport` refuses
three of the four real teleports it exists to admit** -- "too far to walk, too
near to be a teleport". The default gate refuses them too. Every SHORT teleport
lives in that dead zone, which is also why item 1's session-wide class was only
+835: the teleport branch almost never fires on a real teleport.

**NEXT: `TELEPORT_PX` wants re-measuring, and n=8 on 4 solo clips is not enough
to refit it on** -- fitting a constant to the observations that must pass is
the degenerate-crop mistake. More teleport-agent demo clips are the cheap way
to get n, and cost the player a few minutes each. Also open from the same run: a
two-part teleport (Yoru, Chamber, Waylay) drops on PLACEMENT and jumps on
traversal, so no fixed window catches it in general.

*Superseded framing, kept for the argument:* **item 2, cast events select the class** -- and the numbers above are the
argument for it rather than a per-session agent. *a teleport activated
on the hotbar (or in audio) should be triggering an expected agent teleport.* A
session-wide class gives up the slack everywhere to buy jumps in a few places;
a cast selects the class **on a window**, spending the permissiveness only
where there is evidence for it. `ability_hud.py`, `ability_reference` and
`l1/minimap` all exist; nothing new needs detecting.

The third item, **`fit_ring` on the self key, is DONE**, and so is the
descriptor swap it pointed at. Crossed:

                        --geom bbox        --geom pin
        --desc hist       10/26  38%         9/26  35%
        --desc ncc         0/26   0%         8/26  31%

**Nothing beat 38%, and the interaction is the finding.** Geometry is worth -1
under a histogram and **+8 under NCC** -- the fitted ring was measured with an
instrument (an alignment-blind histogram) that could not detect it, so the
falsification is narrower than it first read. The wash hypothesis is confirmed
on its own terms: `chamber -> sova` at a 98% margin becomes `chamber ->
chamber` under NCC. And the two descriptors are **complementary** -- they agree
on 4 of 26 and their union is **13/26 (50%)**.

Two facts about the self glyph came out of it, neither known before: the key
survives only over the lower half of the rim (22-23% present at the top
bearings, a dropout fixed in SCREEN space), and there is no hole to find (0 in
347 frames), so the portrait cannot be had as a hole in the key.

**So stop choosing a descriptor.** Both discard most of the glyph and they fail
on disjoint agents. `BACKLOG.md`'s analysis-by-synthesis entry now names
`self_agent` as its FIRST INSTANCE -- one entity, 29 hypotheses, no assignment
problem, and a ground-truth label already in the ingest tags. Draw the glyph
agent X would produce, subtract, score the residual against `sd_lo/sd_hi`; the
wash becomes part of the prediction instead of a nuisance to remove, and the
tail becomes evidence instead of a mask. It is the only place the loop can be
proved without also solving the pruning, which is why it is worth taking before
the audio half.

**Note for item 1.** Its `BACKLOG.md` trigger is *an agent is known for a
session*, which was item 3's job, and item 3 did not deliver it. So the motion
class has to come from somewhere else -- the ingest tag on the demo corpus, or
a `--agent` argument -- or item 1 ships the parameter with today's `walker`
default and nothing opts in yet, which is what its own text proposes.

**the direction for the channel, in the words:** *identity-based
identification of entities with their temporal evolution, subject to the
invariants of their specific identity.* That is design doc §6 now.

**2026-09-06. The ability-channel handoff further down is
unchanged and still the plan for that thread.**

**NEXT: the causal, temporal, aggregated entity model.** the goal for the
next session, and every piece it needs now exists in some form. The shape,
from the framing:

* **aggregated** -- one segmentation of the widget per frame, fragments grouped
  into OBJECTS (`prototypes/widget_objects.py`), instead of five detectors
  independently thresholding the same pixels and nothing arbitrating;
* **causal** -- what is on screen is CAUSED by events the pipeline already
  tracks. Two enemies dying in one place leave overlapping X marks the killfeed
  can predict the count of; an ability implies a caster who was alive; charges
  bound how many casts are possible;
* **temporal** -- decide on a WINDOW, not on the sampled frame
  (`reticle/refine.py`), and align channels in time.

**What is ready, and what is not:**

* **DONE: alive counts are STORED.** `l1/roster` at `roster-0.1.0`, written by
  `reticle scan`; the reader rides the HUD's own frames, so it costs no decode.
  `status` reports its staleness. First session `c40d950031bb`: 1945 rows,
  90.2% answered, 0 over-five. `roster_alive.py --stored` now runs the whole
  audit off L1 with no decode and reproduces the seek path EXACTLY (43/48,
  14/16, identical histogram) -- the end-to-end check on the wiring;
* **The cross-channel audit found its first defect, and it is in the ROSTER.**
  Three cross-channel misses and the two failed start-at-five checks on
  `c40d950031bb` have one cause: an undrawn roster reads as `0`, not as unreadable.
  The earlier wording incorrectly called these all five cross-channel misses;
  two `+1` cross-channel discrepancies also exist. 9.6% of stored rows are `(0,0)` and every one is
  outside a round (0:08-1:53 pre-match, 16:06-16:09 after). Round 0's window
  starts in that prologue, so its first three probes are the three `-10`s and
  its two teams are the two `starts at 5` failures. **Not patched on one
  session** -- `DETAIL_FLOOR` exists to resolve the all-dead case, so refusing
  there contradicts its purpose. Fix is a drawn/undrawn test (as
  `minimap.widget_drawn` does) or bounding the reader to rounds. Full note in
  `roster.py`. Direction still holds and must not silently reverse: this
  calibrates the roster; afterwards the killfeed is the audited channel;
* **587c15b07779 now has a roster scan** -- 3730 rows, obtained with
  `scan --only roster` without minimap recomputation. The old 100/113 probe
  result reproduces exactly from storage. The interval-delta audit localizes
  six disagreement windows and one count increase; see the picking-up section;
* **READY: window refinement.** `reticle/refine.py`. On the ping detector it
  takes precision 26% -> 42% at NO recall cost, killing every world, xmark and
  bar false positive (`prototypes/ping_edge_eval.py`);
* **NOT ready: assignment.** Objects are described, not labelled. Mutual
  exclusion and the count constraints need the roster table to exist first;
* **FALSIFIED, do not retry as stated:** grouping does not separate ally from
  ping on any shape feature at any gap. Pings are placed ON teammates, so the
  collision is in SPACE as well as in feature space. And `ally_rings` cannot
  veto a ping -- it fires harder on pings (median 0.9 px) than on allies
  (4.0 px).

**Also landed today, all committed with numbers:**

* `587c15b07779` ingested -- Lotus, 31:04, `valorant-16x9-bigmap`. Killfeed
  19/14; `board` reads 19/13, first divergence 0:15:50. **Not in `KNOWN_KD`
  and must not be added until the player confirms it off the match history** --
  `board` is a third extractor over the same pixels, not an external source;
* **the plant is detected positively off the spike graphic**
  (`prototypes/plant_spike.py`), 210/369 rounds (57%) against the null-clock
  rule's 183 (50%), disagreeing on 11%. `rounds._plant` is UNCHANGED pending
  the labels. The absolute version of that test was wrong (6 of 16
  disagreements misread) and the relative one is 16/16 -- and the two rates
  were nearly identical, so a rate is not evidence a rule is right;
* seven review findings fixed, including `verify` being unable to fail on
  `KNOWN_KD`, and the widget-size scale is now DERIVED (exactly 1.0 on
  everything read so far, so nothing moved).

**The map art is wired into `searchable` and is the biggest available accuracy
win still unclaimed.** `searchable(labels, art=art_mask(sid))` scores 92.3% /
94.0% against the paintings where the label rule scores 65.0% / 67.6%.
Nothing downstream calls it yet -- `dynamic_eval`, `scan_ability_clip` and the
ability corpus all still pass `static=`. Switching them over is the change
that acts on the *misreads of non-minimap content as icons*, because the
art's boundary is exact and undilated where `floor_mask` grows 9 px and closes
every crack narrower than that.

**the architectural note, now a convention in CLAUDE.md: a new reader
joins the PASS.** `ping_scan` was written as a standalone video-path script the
same afternoon `passes.py` was built to prevent exactly that. Fixed, both paths
verified to return 14 pings -- but the lesson is the one to carry: a registry
the newest code does not use is not a registry.

**Four things landed earlier in the session:**

* **the last known read error in stage 02 is CLOSED.** `c40d950031bb` reads
  2/7 against `KNOWN_KD`'s 2/7. Two killfeed defects, found by the exclusion
  census rather than by looking for them: the icon test was a FALLBACK rather
  than a tier, so a portrait suppressed the area test small weapon icons need
  and **pistol kills went unparsed**; and `plate_seam` is a divider that needs
  no icon at all, which is what reads an ability kill. Nothing regressed.
  `e37fdeca944f` is still -2 deaths and is NOT a divider problem;
* **`reticle/census.py` + `prototypes/reader_census.py` exist**, and the audit
  they were built for is the thing to keep running. Decode is 93% of a stage's
  cost, so a census pass over a session is cheap relative to what it finds.
  **`ocr.py` has ~12 unexamined guards of the same shape** and the scoreline's
  transient extra digit on `9acf02f98283` is probably one of them;
* **decode once, feed many.** `decode.sample_multi` + `reticle scan` run both
  stage-02 halves in one pass, 45% saved, frame-for-frame identical. `hud`,
  `minimap` and `scan` all drive the same `_HudPass`/`_MinimapPass`. The
  killfeed overlay mask is cached per session at `<store>/masks/`;
* **the shipped minimap reader now has a widget guard** (`minimap-0.2.0`), and
  the re-validation of the position track is the live piece of work -- see
  below.

**PINGS ARE DONE AS A DETECTOR, and the clip falsified why it was asked for.**
`prototypes/ping_scan.py`. Five glyphs, and **the LIFETIME is the feature**:
7.0 s for standard / need help / watching here / on my way, **10.0 s for
danger**, exact to 0.1 s at a 10 Hz sample. Hue alone gives 15 true and 24
false; the lifetime gate leaves 14 true and 0 false, with a truncated run
reported UNCONFIRMED rather than guessed at. A ping does NOT expand -- full
size in under one frame -- so the entity model needs no fourth extent value.
Details and the two ways a persistence gate can be fooled are in that module.

**What is worth doing next on pings**, in order, none of it started:

1. **ingest the two clips** so the events have a real session id. `ping_scan
   --emit` writes `<store>/events/ping/<session>.jsonl` and nothing has been
   emitted yet, because inventing a session id would put rows in the store
   under a key no manifest backs;
2. **a ping over the VOID is invisible to this** -- off the opaque slab the
   world shows through and hue means nothing. How often that happens is
   UNMEASURED and it is the first thing to check on match footage;
3. **`on_my_way` (hue 32) sits closer to `need_help` (17-22) than any other
   pair**, and both were measured on one map. Those two are what breaks first
   on a different map;
4. `watching_here` has n=1 and `on_my_way` only appears in its own short clip,
   so their lifetimes are ASSUMED from the other three rather than observed.

**THE LIVE PIECE: re-validate the minimap position track at `minimap-0.2.0`.**
the call, 2026-09-05: add the guard, then re-validate; checking the rate on
a second ordinary session first is TABLED.

`cmd_minimap` had no widget guard of any kind. Measured over all 27757 frames
of `a06f04a0059f` at 15 Hz: `drawn()` refuses 5.0% where `usable()` refuses
2.2%, and those frames yield 3605 self and 4178 ally candidates -- 2.6 per
frame, harvested from open scenery. `minimap.widget_drawn` is now called per
frame and a refused frame is stored as a row with NULL positions rather than
dropped, so the hole stays visible to `filter_track`.

`drawn`/`usable` were PROMOTED from `prototypes/minimap_temporal` into
`reticle/minimap.py`; the prototype re-exports them, so there is still exactly
one implementation.

**That moves every stored minimap number**, so `xmark_eval.py` and
`chokepoint_eval.py` both take `--no-guard` to reproduce the figure on record
and are being run both ways on `a06f04a0059f`. **Until those two numbers are
in, the position track's validation status is UNKNOWN, not good** -- the
figures in `prototypes/CLAUDE.md` were measured with the phantom frames in.

**2026-09-05. The ability channel was re-founded on a different question, and
the full argument is a document rather than a handoff:**

**The ability event log** -- `docs/ability-recognition.html`,
https://claude.ai/code/artifact/bffd7660-cd3e-4e6f-ada9-3be6b0dca887
**The minimap entity model** -- `docs/minimap-entity-model.html`,
https://claude.ai/code/artifact/324e1c5f-9240-4b13-8ff1-59adb24a2f06
The first is what the log contains; the second is what an entity IS, with a
driver PER PARAMETER. Read both before picking this up; below is only state.

**What today settled, in one place.**

* **the labelling pass is DONE** -- 5 sessions, 161 records, 58 new positives,
  giving 85 pos / 252 neg over 9 sessions, up from 27 over 4;
* **it falsified the claim it was run to support.** `patch_range` pooled AUC
  **0.86 -> 0.57**, consistent 4 of 9. The break is perfectly confounded with
  capture regime (4 ordinary captures vs 5 `infinite-abilities` demos), so the
  corpus cannot say whether the feature never generalised or the demos are a
  different world. **One ordinary-capture session labelled the new way is the
  one footage ask**, and it is worth more than any number of demo clips;
* **the weighted combiner does not earn its parameters.** Equal-weight z-sum
  matches or beats it in every configuration (0.74 vs 0.69 AUC), and sign
  agreement is 100% across all 8 folds -- so this is not fold noise, the
  features are near-redundant. Label volume was never the blocker;
* **per-session z-scoring is worth more than any weighting** (0.74 vs 0.64).
  The dominant recoverable variance is per-session, not per-object;
* **current honest best**: equal-weight z-sum, per-session z, leave-one-session-
  out -- precision 0.36, recall 0.68, AUC 0.74, against a 0.21 baseline.
  **CORRECTED 2026-09-06: it is NOT established as worse than the 0.49 @ 0.85
  that was on record.** That recall rested on 27 positives, 95% CI
  [0.675, 0.941], against 0.68 on 85 at [0.577, 0.772] -- they overlap, so the
  old figure was too weak to be worse than rather than better. Clearing the
  0.252 class baseline IS established. This sentence asserted a decline for a
  fortnight and the arithmetic never supported it; `metrics.wilson` exists now
  so the next one says so on its own;
* **the cast-anchored detector is built and emitting.**
  `prototypes/ability_cast.py`, joining `ability_hud.py`'s tray drops to the
  reference kit: **24 casts, 27 of 43 agent-named positives explained (63%)**,
  and `--emit` writes events to `<store>/events/ability/`;
* **"slot X never drops" was a defect in the READER.** The ult pips desaturate
  with the bar, so the existing teal mask reads them: slot X goes 909 -> 0 teal
  px between 28.0s and 28.5s against a Hunter's Fury label at 28.2s. Two bugs
  compounded -- `casts()` looped `range(3)`, and `drawn()` refused the frame
  because an all-spent tray reads as "not rendered". Both fixed;
* **a cast buys the EVENT cheaply and NOT the POSITION.** Widening the position
  window never raised the number of correct picks (3, at every width), so
  position is emitted only when the window holds exactly one candidate -- 2 of 2
  exact -- and is null otherwise, with the candidates carried along. Time and
  identity come free from HUD structure; location still needs the weak detector.
  **State this wherever the 63% is quoted.**

**the domain facts from today, none recoverable from pixels.** Detail is in
the module docstrings and the design doc; the heads only:

* **controllable deployables emit vision cones too** -- Owl Drone, Tejo's
  Stealth Drone, Skye's Trailblazer AND Guiding Light, Fade's Prowler, Killjoy's
  turret. Same half-angle is EXPECTED, not known. `self_cone()` cannot see them,
  and `cone_cond` -- now the best single feature, inverted, 7 of 9 consistent --
  is computed against the player's cone only. See `minimap_cone.py`;
* **`radius_ring` is what a DEPLOYED device draws, not placement** (Killjoy,
  Chamber, Veto). The ring is not the device: a candidate on the perimeter sits
  tens of px from its object;
* **held placeables want a `mode` field**, currently leaking into category names
  (`place_color`, `smoke` vs `smoke_deployed`). A preview sits at the player's
  feet, so it contaminates `self_d_med`;
* **deployed smokes are one agent-independent class on purpose** -- Jett's
  Cloudburst and Viper's Poison Cloud are both generic `smoke`, because the
  minimap carries no thrower identity;
* **placement hold time is unbounded** -- only the ~1-2s before the commit
  carries positional information; a long hold is its own signal;
* **`infinite-abilities` is a misleading tag on the five demo sessions** --
  toggled on to charge the ult, then off. `2ba870ccbd50` (Brimstone) genuinely
  had it on. **Viper's Pit is SUSTAINED**, so its bar releases when the pit ENDS
  (drop at 44.0s against labels at 36.9-42.6s);
* **Skye's Regrowth drains only while healing someone**, so `no cast` in a solo
  clip is correct, not a sampling defect.

**The cone tint is real and `blob_colour` structurally cannot see it.** Killjoy's
turret cone is green-tinted; `minimap_dynamic.blob_colour` gates on `s > 90`
before naming any colour and a translucent tint never clears it. Needs its own
low-saturation hue test -- do NOT loosen `COLOUR_SAT`, which is load-bearing.

**NEXT SESSION STARTS HERE: A LABELLING PASS ON OBJECT GROUPING.** the
call, 2026-09-05, closing the session -- *next session we can start on the
labelling pass.*

**Nothing in the label store says WHICH CANDIDATES ARE ONE OBJECT.** Grouping
has been in this pipeline since `ability_corpus` and has never been scored
against anything, so three separate things are currently unfalsifiable and one
pass settles all of them:

* the **extending signature** in `ability_cast.py` -- distance from an origin
  increasing over >=3 fragments. It resolved Viper's Toxic Screen correctly
  (+9.7 deg, 3 fragments) and returned three bolts for Sova's ult, but the rule
  was designed after looking at the Toxic Screen window, so that case is what
  it was fitted to rather than evidence for it;
* the **onset rule** it replaces for extending abilities (300 ms, 60 px);
* the **10 refused positions**, which are refused precisely because nothing can
  say whether several candidates are several objects or fragments of one.

Before building the labeller: **invoke the `labelling-pass` skill**, and render
and review the candidates first -- launching a GUI against unreviewed
candidates has three recorded recurrences and cost the player real clicking time
twice. `review_candidates.py` gates it.

**THE PING CLIP IS RECORDED AND IT FALSIFIED THE REASON FOR ASKING FOR IT.**
`2026-09-05 17-39-40.mp4` (65 s, four types) and `2026-09-05 17-57-24.mp4`
(on-my-mark). on watching it back: *they did not seem to radially
emanate*. Measured at 60 Hz and the player is right --

    7.133 s   nothing
    7.150 s   the diamond is ALREADY AT FULL SIZE

**There is no growth phase at all**, no ring, no arcs, and the glyph then sits
static for its whole life. So **a ping is not a third extent kind** and the
entity model does not need a fourth `extent` value: a ping is
`origin=fixed, bearing=absent, extent=none`, the same parameter shape as a
deployed device, and its identity is carried by GLYPH SHAPE AND COLOUR rather
than by motion. `git show d15418c` is the commit that claimed otherwise.

That also removes the reason to point the object-grouping labeller at pings
first. The pitch was *fragments of one expanding ring are the grouping problem
in its purest form*; a ping is one compact ~8x8 blob, which makes it the
EASIEST class in the store, not the hardest. It is still worth labelling -- as
a clean, cheap, four-class glyph problem with free labels -- just not as the
grouping case.

Where the older claim came from is worth knowing before it is written down
again: *a ping is an expanding ripple whose fragments are thin arcs* came off
the colour-free pass on the SMALL widget. Either the animation differs at that
size, or those arcs were something else. Do not re-assert it without a clip.

Glyphs seen so far, all ~8-10 px, hue is OpenCV:

    cyan diamond      hue ~82    the standard ping
    orange flag       hue ~17-20
    red triangle      hue ~173   danger (last in the order, so this is it)
    yellow stopwatch  hue ~32    on my mark (its own clip)

the order in the spam clip was **standard, need help, watching here,
danger**; three glyphs were isolated from it, so one of the middle two is
still unassigned. The warm Sunset scenery shows through the semi-transparent
widget at hue 10-22 and floods any saturation-based finder, which is why the
middle of that clip is noisy -- **a ping finder cannot be a colour threshold**,
it has to be shape against the opaque slab.

**QUEUED CAPTURE (SUPERSEDED, kept for the reasoning): a PING clip.** *I want to record a ping
minimap session where I just spam ping for a minute or so.* Same shape as the
one-agent-per-clip demo corpus and the same reason it works -- the player knows what the player
did, so the labels are free and exact.

It is worth more than a confounder clip. Pings are named in the endstate
alongside abilities (*labelling of abilities and pings on the minimap*), the
only evidence in the store today is a handful of rows from the colour-free pass
(*a ping is an expanding ripple whose fragments are thin arcs*, aspect ratios
that would have been deleted by a shape filter), and a minute of deliberate
spam gives more instances than the whole corpus has.

Two things it settles that nothing else can:

* **it is a THIRD extent kind.** The entity model has `extending` (outward
  along a bearing, a wall) and `radius` (fixed, a smoke). A ping expands
  RADIALLY -- a growing radius with no bearing at all -- so the model needs a
  fourth value and the ping clip is what measures its rate and lifetime;
* **fragments of one expanding ring are the grouping problem in its purest
  form.** Thin arcs at a shared centre, appearing over successive frames,
  which the onset rule and the bearing rule both handle badly. If the object
  grouping labeller is built first it can be pointed straight at this.

Pre-ingest, per the root checklist: crosshair centred, perf stats text-only,
shooting-error off, minimap fixed/always_same/uncentered, record the widget
size and the outline colour, and run `clip_preflight.py` BEFORE ingesting --
the first take of the last sitting was recorded with side-based orientation and
the whole widget was rotated 180 degrees.

**Then, in order.** (The event log doc's SS7 is the fuller version.)

1. **Label negatives on `a06f04a0059f` (53 positives) and `5822b6646448` (35).**
   Both were labelled POSITIVES-ONLY, so the scorer skips them for having no
   both-class labels, silently -- 88 positives stranded, more than the whole
   usable corpus. No new footage, no decode. Render and review the candidates
   first; that mistake has three recorded recurrences.
2. **One ordinary-capture session labelled the new way**, to break the regime
   confound. Until it exists, do not fit anything across both regimes.
3. **Audit the other readers for silent exclusions.** Every real gain today came
   from finding something discarded without a word -- the both-class check,
   `range(3)`, `drawn()`. `killfeed.py`, `scoreboard.py` and
   `minimap_temporal.usable()` all carry guards of the same shape.
4. **Audio**, now genuinely unblocked: `audio_probe.py` killed onset detection
   and said a matched filter needs a reference cut at a known cast time. The 56
   ultimate voicelines are the cuts and the tray now supplies the times. It is
   also the only channel for OTHER players' casts -- and the framing is why
   that generalises: **audio range is roughly the observable range, and roughly
   what is worth recording**.
5. **A low-saturation tint test, and a deployable cone seed.** New observations
   rather than recombinations of the exhausted bank. Killjoy's turret cone is
   **100 degrees** against the player's measured ~112 -- from the reference
   text, not a measurement, so do not reuse `CONE_HALF_ANGLE_DEG` for it.
6. **A per-ability distance-from-player prior**, to break the position ties this
   module currently refuses. only Omen's smoke and ultimate are truly
   global, so the shipped self track constrains every other ability. Measured
   medians span 21 px (Viper's Pit) to 180 px (Toxic Screen) and the ordering
   matches the families -- but n is 1-3 placements per ability, and the
   reference's `Deployment Type` is a different axis. See `ability_cast.py`.
7. **Represent an ability as ORIGIN + an OPTIONAL DEPLOYMENT VECTOR + a
   TRAJECTORY DRIVER.** the player proposed origin+vector, then withdrew it the same
   hour: objects change state after deployment, and the useful axis is what
   DRIVES the motion -- static, enemy-reactive (Killjoy's Alarmbot and turret),
   player-piloted (the scouts), player-aimed (Cypher's cam), or freeform-at-cast
   (Phoenix's wall). The vector is absent for rotation-invariant smokes: absent
   by construction, which is information, not a failed fit. `icon_facing()`
   already returns the pose half. It also re-justifies `cv2.minAreaRect` --
   deferred as a classifier feature, but the long axis of a grouped region IS
   the deployment vector, and measuring an object whose identity the cast
   already gave you is not classification.
8. **Enemy-reactive motion is an ENEMY DETECTION**, and CLAUDE.md lists opponent
   priors as blocked for want of enemy positions. An Alarmbot that moves is
   moving toward one; a turret that snaps is snapping onto one. Needs no new
   extractor -- the position track applied to an object the cast identified.
   Both are UNTESTABLE on the demo corpus (solo game, no enemies to react to),
   so this needs match footage.

**Do NOT**: add shape features (the bank is near-redundant and cannot be
usefully weighted -- measured); record more demo clips; chase `patch_range`.

**Standing hazards.** Never re-scan `2ba870ccbd50`, `eb10db50b1fb`,
`d95cfad5693a`, `79a706a7ce4c` -- the label store key is unstable. Never seed a
label file. **The tile is not the object**: at the candidate's own pixel 177 of
205 sit on FLOOR.

**`64d0fb783be2` (Vyse) is PULLED and TABLED at the call** -- 65 of 96
candidates in one 10s window, rendering as flat salmon tiles with no object.
Worth revisiting with the tint/illumination work: a coherent lit region produces
exactly that signature.

**Other live threads, not touched.** Detail in `git show HEAD~1:NOTES.md` and in
the module docstrings; heads only, because this section grows by stacking.

* **minimap position (self) is shipped; allies are not.** Next: ally identity
  across frames, then the visibility computation dA/ds, then enemy-icon states.
  Note ally CONES need no identity -- a cone is per-frame, and `ally_rings()`
  already returns the tuple `self_cone()` seeds from -- but the demo corpus is
  SOLO, so ally cones buy nothing there and everything on real-match footage;
* **vision cones:** confirm the half-angle on a second map, and find a case
  where a raycast actually crosses a boxedge pixel. Deployable cones are a
  second cone per clip on a path the player never walks, which is the cheap way
  out of "more footage than one clip supplies".

**Still true and still queued:** `ability_corpus.load_events` takes `min(dists)`
across an event's fragments, re-introducing the Phase 0a failure one level up;
three different `floor` conventions feed `self_rings`; a pulsing region still
gets one event per pulse; teleports break the shipped position track for Veto,
Omen, Chamber and Waylay.

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
