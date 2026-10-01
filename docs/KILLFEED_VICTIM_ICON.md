# Reading the icon beside the victim's name

**Status: proposed design, not implemented (2026-10-01).** Step 3 of the
open-set killfeed icon work; steps 1 and 2 are in
`prototypes/killfeed_openset.py` and `adjudication.weapon`
[owns:killfeed-weapon].

## The question

An entry can carry an icon beside the victim's name as well as in the weapon
slot. Two are recorded: Phoenix's Run It Back badge and the KAY/O down icon
[domain:killfeed/kayo-downed-entry]; both mark a second-life death
[domain:killfeed/entry-types]. Today `killfeed.detect_second_life_badge` fits
a ring beside the victim's name, names no icon, and runs only on entries the
reader calls the player's own deaths (`KillfeedPortraitReader.feed`, verdict
`death`). The player expects it to fire on the KAY/O icon and on much else.
The player's design: read every position where an icon can appear in every
entry, and stop once context has narrowed enough.

## The pixels are already stored

Every pixel the killfeed reader reads lies inside the profile's `killfeed`
ROI, and the badge detector reads the entry's full band across that ROI
(`frame[y0 + view.y0:y0 + view.y1, x0:x1]`). The `killfeed` and `hud` crop
caches store that ROI losslessly at the reader's 2 Hz: 1421-1910 x 81-346 at
1080p on a06f04a0059f, 5822b6646448 and 4f207c0c4e39. The step 2 labeller
renders whole rows from that cache, victim name and portrait included. So a
victim-side reader needs no decode on a cached session: `reticle trial
--reader killfeed --from cache` runs it over stored windows and diffs it
against storage.

Cost: a full trial of the current killfeed reader from the cache over the
occupied windows of a06f04a0059f reads
[metric:killfeed_openset/victim_icon_trial_cost@a06f04a0059f#frames=2034]
frames in [metric:killfeed_openset/victim_icon_trial_cost@a06f04a0059f#seconds=32.8]
s ([metric:killfeed_openset/victim_icon_trial_cost@a06f04a0059f#ms_per_frame=16.1]
ms a frame), identical to storage. A second icon search per entry adds little
to that. The cache serves [metric:killfeed_openset/victim_icon_cache_coverage@corpus#sessions_cached=21]
of the [metric:killfeed_openset/victim_icon_cache_coverage@corpus#sessions=60] ingested sessions; the rest
(e78e75b2d191 among them) need a decode: a `reticle scan --only hud` rescan,
which writes the cache as it goes. Ask the player before starting one.

## Design

1. **Ask first.** Before any reader code, ask the player which icons can
   appear beside the victim's name, and beside the weapon. The step 2
   exemplar rows show a glyph between the weapon and the victim's name on a
   plain kill; what it is is the player's answer, not an inference. Record
   each answer as a `domain/killfeed.toml` fact.
2. **Positions.** The reader stores, per entry and frame, a descriptor
   (the 16x64 grid and aspect, as `killfeed_weapon` stores) for each icon
   position it finds: the weapon slot (stored now), the gap between the
   weapon and the victim's name, and the gap between the victim's name and
   portrait. A new stream, `killfeed_badge`, has its own version stamp; the
   existing streams keep theirs. No name is decided in the reader.
3. **Narrow by context in the owner.** A new adjudication, asked through
   `adjudication.death.entry_type`, names a badge only from the candidates
   the entry's context allows, and says what it `rests_on`:
   - the Run It Back badge only when the victim is Phoenix, alive in the
     round and inside his ultimate;
   - the KAY/O down icon only when the victim is KAY/O inside NULL/cmd;
   - the revive icons only as [domain:killfeed/entry-types] allows them.

   The full set is the surprise path. A fixed hash sample gets the full
   search, stored apart, as `entry_weapon`'s audit does.
4. **Groups and labels.** Unnamed badge descriptors are grouped like the
   weapon slot's (`killfeed_openset.py groups`), and the player names them
   with `label_killfeed_groups.py`, so the labelling path is the one step 2
   built.
5. **Acceptance.** A trial from the cache on the fast sessions shows the
   existing streams unchanged. The badge stream's named entries are then
   scored against the player's labels, and every second-life death the
   death owner stores is scored against a badge read.

## Not settled

- Whether the gap glyphs are fixed art (one exemplar each) or vary.
- Whether an entry can carry more than one icon beside the victim's name.
- Which cached sessions hold a Phoenix in Run It Back or a downed KAY/O is
  unchecked; if none does, a demo capture supplies the first exemplars.
