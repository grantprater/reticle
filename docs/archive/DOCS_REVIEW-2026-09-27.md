# Documentation review, 2026-09-27

## 1. Scope and method

Two read-only audits of the checkout at `befce8a` read every live document,
`ownership.toml`, `domain/*.toml`, `docs/tasks.json` and the module docstrings
the guide restates: one mapped duplication and contradiction, the other mapped
unimplemented, unused and dangling material. This pass re-located each cited
passage by grep on master at `e518f8e`, checked each claim against the code,
the git history, the `experiment/bootstrap-*` branches or the private notes
before editing, and verified the result with a relative-link checker,
`reticle doctor` and the unit suite. Nobody read the ~90,000 archive words or
the five `docs/*.html` pages linearly, and the audits' helper agents, not the
auditor, read the plan and findings documents in full.

## 2. Findings

### Duplication

The five largest clusters, with the audit's estimate of repeated words and the
home chosen for each:

| Cluster | Repeated words | Canonical home |
|---|---:|---|
| PROJECT_GUIDE sections restating the `glance`, `metrics`, `judgement` and `doctor` docstrings | ~2,300 | the module docstrings |
| Minimap, adjudication and ability designs: the mining protocol twice, acceptance gates five times, the evidence contract, the vision gate | ~2,300 | `domain/minimap.toml` for rules; MINIMAP_MINING_REVIEW for mining; the appearance plan's evaluation contract for gates |
| Repository-declaration and ownership arguments, told in nine places | ~1,900 | each declaration and its module docstring |
| Plan documents: the pipeline spine, the three times, the learning pass, the experiment protocol, win-probability evaluation | ~1,900 | PIPELINE_REVIEW for gates; `architecture.toml` and the working map for the spine |
| Global working rules | ~1,600 | AGENTS.md, "Global constraints" |

### Unimplemented and unused

Of 41 documents and declarations audited, 12 were current, 10 partly built, 5
superseded, 8 dated findings, 4 unbuilt on master, one a file of closed task
contracts and one set untracked generated output.

- **Orphans** (nothing live linked them): `docs/USAGE.md`,
  `DEATH_KILLERS.md`, `FULL_ROUND_LIFETIMES.md` and
  `MINIMAP_CANDIDATE_CONTRACT.md`; doctor also names 29 prototypes nothing
  cites.
- **Plans entirely done:** the architecture plan (A1-A4 finished 2026-09-07; A5
  and A6 never resumed) and the minimap detection plan (its follow-ups shipped;
  the `Tracker.resolve` it names was deleted on 2026-09-08).
- **Plans unbuilt on master:** EXPERIMENT_PROGRAM, the graph solver of
  ADJUDICATION_DESIGN (its eight modules and `reticle adjudicate`), and the
  bootstrap plan with its pilot.
- **The bootstrap experiment ran unmerged.** Lane A (`experiment/bootstrap-a`,
  627b830), lane B (`experiment/bootstrap-b`, a5fae3d) and the integration
  (`experiment/bootstrap-integration`, bd9d903 and 5c0a093) all ran on
  2026-09-24. The integration's `handoff.md` and `result.json` close it: the
  learner changed no name on the development or transfer slice, so the
  player's answer scored production, not the learner; `tools/bootstrap_compare.py`
  is the reusable piece. Both plan documents still said "prepared, not
  launched".
- **The contract mechanism went dormant.** All twelve contracts in
  `docs/tasks.json` covered closed or standing work, none was written after
  2026-09-23, and no open BACKLOG item had one.

### Dangling references

The ten most misleading, and what they now say:

1. AGENTS, the working map and `prototypes/CLAUDE.md` sent a session to "the
   selected task's contract" that no open task had. They now route NOTES, then
   the BACKLOG task, then the owning docstring and the guide.
2. The guide said `prototypes/CLAUDE.md` holds the detector state and "the
   single least replaceable thing in this repo". That file is a 7-line stub;
   the guide now points at the prototypes archive and the docstrings.
3. The guide listed the combat report as not built. `reticle/combat_report.py`
   stores each frame's panel read and `adjudication.combat_report` adjudicates
   it.
4. The guide said the minimap reader has no widget guard. `widget_drawn` has
   guarded it since `minimap-0.2.0`.
5. README, the guide and the working map said HUD work must re-decode.
   `scan --only hud` rereads the crop cache; only `--from video` and the
   standalone `hud` command decode.
6. The bootstrap plan, its pilot and the working map called both "prepared".
   Both ran and closed on 2026-09-24.
7. OWNERSHIP_INDEX and the guide named `death-victim` and three other
   questions unowned. `ownership.toml` leaves only `ability-owner` unowned.
8. ADJUDICATION_DESIGN cited `minimap.resolve_track`, which moved to
   `belief.resolve` at `belief-0.2.0`.
9. The guide cited `~/reticle-notes/QUOTES.md`, folded into `DOMAIN.md` on
   2026-09-07.
10. The appearance plan cited a "standing constraint in `../CLAUDE.md`" found
    in no file; it lives in the archived backlog entry *Reject ally icons that
    have no light beside them*. The guide likewise cited a section, "4:2:0
    chroma subsampling costs a fifth of the detector", that exists nowhere; it
    now cites the chroma domain fact.

### Contradictions between live documents

- **Decoding:** covered in item 5 above; the working map contradicted itself.
- **The queue:** AGENTS pointed at contracts, BACKLOG ordered work without
  them, and README called IMPLEMENTATION_PLAN the roadmap.
- **Built or not:** the guide, OWNERSHIP_INDEX and ADJUDICATION_DESIGN denied
  the combat report, ally identity, the widget guard, the `widget_drawn`
  column and self identity, all of which exist.
- **The vision gate:** the appearance plan called it exceptionless;
  `domain/minimap.toml` records a reveal exception and a trailing persistence.
- **The killfeed:** the guide said it fires only on deaths; the domain records
  revive entries.
- **STATUS.md:** it showed `hud-0.12.0` against `hud-0.15.0` in code, and
  PIPELINE_REVIEW repeated the stale stamp.
- **Doctor's own description:** the guide counted "seven checks" (the code
  runs 17) and said DOMAIN reports every restatement (it sees only declared
  phrases).
- **Status lines** of the behaviour, adjudication, learning and economy
  designs denied work that ships; the guide called `2ba870ccbd50` undecided
  after the prototypes archive decided it.
- **Rule drift:** the copies of the session-pixel rule disagree on
  orientation; `prototypes/CLAUDE.md` kept fewer unknown states than AGENTS;
  README's minimap-mode example named a setting its own text rules out.
- **Counts that drifted:** geometry keys (11 against 12), dependencies (four
  against five), modules (63 against 65 and 88), stale tables, and the
  minimap version quoted in the appearance plan.
- **Split queues:** NOTES and BACKLOG carry the same open items, and
  ADJUDICATION_DESIGN kept finished steps open.
- **Tensions:** the guide's "main goal" of win probability against AGENTS'
  annotated-match north star; `side` in the win-probability state against the
  plans that forbid inferring it; ammo drops as shots against the rule that a
  dead player spectates.

### The dead checks

- **HANDOFF** counted `## Active: <id>` headings, which BACKLOG stopped using,
  so the three-active-task limit and the "active task has no contract" warning
  never fired, and anchors were stripped before the `reads` check, so five dead
  anchors passed. With `docs/tasks.json` archived, the check now stops at
  "missing handoff file: docs\tasks.json" before it measures NOTES or BACKLOG;
  the NOTES and BACKLOG size limits go unchecked until the parallel change to
  `check_handoff` lands.
- **DOMAIN** reports a restatement only when a fact declares `phrases`, and
  only 18 of the 137 facts on master do; it matches exact substrings without
  normalising whitespace, excuses a whole file after one citation, and scans
  only `.py` and `.md`. This pass found one more gap: its citation pattern
  `[a-z0-9-]` rejects the underscore in `combat_report`, so every
  `[domain:combat_report/...]` token goes unvalidated and uncounted, and doctor
  lists those facts as cited by nothing while five files cite them.
- **ORPHAN** skips BACKLOG, the archive, `tools/`, `tests/`,
  `reticle/adjudication/`, `.claude/skills/` and the prediction ledger, so it
  calls tested and skill-cited prototypes orphans.

## 3. What this pass changed

"Live" means root `*.md`, `docs/*.md` outside the archive and
`prototypes/CLAUDE.md`.

| File | Change | Live words removed | Reason |
|---|---|---:|---|
| `PROJECT_GUIDE.md` | edited | 1,662 | Four docstring restatements cut to what the modules lack (1,532); ROSTER_FINDINGS figures and the command block replaced by pointers; about 30 stale claims corrected; ten domain facts cited; the ownership index's seven meanings of *identity* carried in |
| `docs/MINIMAP_APPEARANCE_MATCHING.md` | edited | 1,189 | Superseded mining proposal moved to the archive; vision gate, reveal answer, death-mark colour and chroma now cite domain facts |
| `docs/WORKING_MAP.md` | edited | 292 | Rule sections replaced by a pointer to AGENTS; start-here no longer routes through contracts; pilot, ownership and detection rows state outcomes; decoding contradiction fixed; candidate contract routed |
| `docs/MINIMAP_MINING_REVIEW.md` | edited | 39 | Acceptance paragraph points at the evaluation contract |
| `prototypes/CLAUDE.md` | edited | 14 | Contract pointer removed; rules replaced by a cited pointer to AGENTS |
| `AGENTS.md` | edited | -74 | Contract pointer removed; one bullet carries the working map's rules on shared passes, restamping, pure adjudication, late answers and review windows; three domain facts cited |
| `README.md` | edited | -46 | Stored as LF with its `cd` line repaired (a separate commit); five-line quickstart; USAGE notes folded in; rule, checklist and store restatements replaced by pointers; three contradicted claims fixed |
| `docs/ADJUDICATION_DESIGN.md` | edited | -100 | Status line of what is built; `belief.resolve`; finished steps marked; shared gates pointed out |
| Nine further design and findings docs | edited | -119 | Status lines and claims corrected (learning, behaviour, economy, implementation plan, pipeline review, roster findings, ability design, experiment program, pub/sub baseline) |
| `docs/ARCHITECTURE_PLAN.md` | archived, dated 2026-09-09 | 1,109 | Done; outcome line added |
| `docs/MINIMAP_DETECTION_PLAN.md` | archived, 2026-09-09 | 1,980 | Done; outcome line added |
| `docs/BOOTSTRAP_PARALLEL_RUN.md` | archived, 2026-09-24 | 1,641 | Ran and closed; status line names the branches and outcome |
| `docs/ENTITY_DOMAIN_LOOP_PILOT.md` | archived, 2026-09-24 | 1,249 | Ran as lane B; status line added |
| `docs/OWNERSHIP_INDEX.md` | archived, 2026-09-11 | 864 | Hand-written and drifted; `reticle ownership` replaces it |
| `docs/FULL_ROUND_LIFETIMES.md` | archived, 2026-09-08 | 2,163 | Orphaned findings |
| `docs/DEATH_SCOREBOARD_BINDING.md` | archived, 2026-09-23 | 1,460 | Findings read only by closed contracts |
| `docs/DEATH_ROUND4_REFUSALS.md` | archived, 2026-09-23 | 812 | Findings read only by closed contracts |
| `docs/DEATH_KILLERS.md` | archived, 2026-09-23 | 323 | Orphaned findings |
| `STATUS.md` | removed; ignored in `.gitignore` | 1,545 | Stale snapshot nothing read; `reticle status` prints it live |
| `docs/USAGE.md` | removed | 217 | Orphan; folded into README |
| `docs/tasks.json` | archived as `tasks-through-2026-09-23.json` | (not markdown) | Twelve closed contracts |
| `docs/archive/MINIMAP_MINING_PROPOSAL-2026-09-10.md` | new archive file | (archive) | The appearance plan's superseded mining section |
| `docs/archive/BACKLOG-through-2026-09-23.md` | links repointed | 0 | Eight links now reach the archived findings and contracts |

Totals: live words fell from 121,263 to 105,043, a cut of 16,220. Broken
relative links fell from 47 on master (8 machine-local `teststore/` links and
39 root-relative links inside archived handoffs) to 39; the pass added none.

## 4. What this pass left

- **Code documentation.** The audit counts 26 code and HTML citations of
  `prototypes/CLAUDE.md` for detector state: seven in `reticle/`, sixteen
  prototypes, four `docs/*.html` pages, besides `domain/minimap.toml`. Also
  left: the `check_manifest` docstring still calls `2ba870ccbd50` undecided;
  `doctor.py` advertises a `--verbose` flag the CLI rejects; `status.py` and
  `cli.py` say status intent stays "in CLAUDE.md"; `tools/task_check.py`
  defaults to `docs/tasks.json`. None of these files was in this pass's remit.
- **Documents the handoff still names.** `ALLY_MINIMAP_IDENTITY.md` stays
  until BACKLOG stops linking it, though ROUND_ENTITIES supersedes it.
  BACKLOG's opening line still names `docs/tasks.json`.
- **A live contract kept live.** `MINIMAP_CANDIDATE_CONTRACT.md` describes the
  implemented `candidate_evidence.py` contract, and neither docstring carries
  its descriptor rules, so the working map now routes to it instead of the
  archive holding it.
- **Design dedupe not placed.** The evidence contract told five ways, the
  "Step 0 freeze" told three ways, the plan-doc spine and learning-pass copies,
  the execution records inside IMPLEMENTATION_PLAN, PIPELINE_REVIEW and the
  appearance plan's Step 2 section, and the declaration arguments repeated in
  code docstrings. Each copy carries some subject-specific detail, so a merge
  needs an owner's judgement rather than a pointer.
- **Two figure pairs unreconciled.** Ability lighting reads 0 of 31 in BACKLOG
  and 34 of 34 in the ability design; enemy-portrait accuracy reads 83.5%
  held-out in the entity-model page and 93.0% leave-one-out in the guide, the
  appearance plan and BACKLOG. Each pair may measure different things.
- **Game facts with no domain table:** the credit economy (starting credits,
  win and loss bonuses), the spike graphic replacing the round timer for the
  planted 45 s, the performance-stats graph halving the killfeed's slots, and
  Valorant's default minimap rotation and side mirroring. BACKLOG also restates
  the smoke-attribution rule beside its own citation.
- **The HTML pages** still require the raycast cone where the domain names the
  drawn light, and treat a missing teleport sound as certain.
- **NOTES** still carries open items that belong in BACKLOG.

## 5. Decisions for the player

- **EXPERIMENT_PROGRAM:** implement, supersede or retire it. It now opens with
  "proposed; no module or command implements it".
- **Verbatim quotes in PROJECT_GUIDE.md,** which AGENTS says stay private: the
  endstate (287-292), the north star (298-299), shooting error (348-350), the
  clips pass (360-361), streaming (367-369), the scoreboard position (562), the
  novelty question (914-916), the stake remark (937-938), "this has already
  happened" (1056-1057), the pass rule (1082-1085), the bomb-sites question
  (1206-1207) and the context-limit request (1364); line 143 attributes a
  history rewrite. Keep, move to `~/reticle-notes/`, or paraphrase.
- **Task contracts:** bring them back (contracts for the open BACKLOG items, or
  `## Active:` headings again) or retire `tools/task_check.py` and the
  contract half of HANDOFF.
- **Session pixels and orientation:** AGENTS lets a capture set the widget's
  dimensions and placement; the domain fact adds orientation, and AGENTS' own
  exception grants `clip_preflight` orientation. Which wording is the rule?
- **The ally identity acceptance** failed its contract (2 wrong of 40 against
  at most 1) and records no status: record the failure or the waiver.
- **The candidate contract:** keep it as a document or fold it into the
  `candidate_evidence.py` docstring.
- **The 29 orphan prototypes:** wire, decline in the ledger, or delete.

## 6. The construct

Another agent is adding a documentation register and a doctor DOCS check on
branch `docs-register-20260927`. That branch holds their design; this report
does not restate it.
