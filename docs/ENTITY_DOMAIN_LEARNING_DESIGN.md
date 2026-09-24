# Entity mining and domain learning

Date: 2026-09-23
Status: accepted direction; bounded foundation implementation authorized.

Next pilot handoff: [ENTITY_DOMAIN_LOOP_PILOT.md](ENTITY_DOMAIN_LOOP_PILOT.md).
Launch waits for the user's scan-fix readiness confirmation.

## Purpose

Extend the exemplar loop to extract and identify entities in unlabelled sessions,
and to propose domain knowledge from the same evidence. Accepted knowledge feeds
the owners of later extraction and adjudication decisions. Preserve unknowns,
counterexamples, source evidence, and the dependencies that could make a result
self-confirming.

The user requests an implementation checkpoint before substantial experimentation.
Ongoing ally work belongs to another session and includes uncommitted changes.
Implement the independent foundation first; coordinate before touching those files.

## Existing foundations

- `tools/identity_loop.py` harvests killfeed appearances labelled by independent
  witnesses and asks `adjudication.identity` to resolve subsequent claims.
- `adjudication.identity` owns agent names, side assignment, and dependent claims.
  The current ally path names observations; track association supplies its own keys.
- `track` owns continuation constraints; `minimap_lifecycle` owns origin decisions.
- `adjudication.gallery` separates ability appearance phases and evaluation scope.
- `domain` owns accepted facts, their provenance, subject lookup, and citations.
- `store`, `artifacts`, and `revisions` provide persistence and dependency machinery.
- `acquisition` plans additional evidence; shared passes acquire source observations.

Read the actual implementations before extending them. The current tree can move
while the ally session works. The broader mining rationale lives in
[MINIMAP_MINING_REVIEW.md](MINIMAP_MINING_REVIEW.md), and the existing exemplar
safeguards in [IDENTITY_EXEMPLAR_LOOP.md](IDENTITY_EXEMPLAR_LOOP.md).

## Two outputs from one evidence loop

    source observations -> provisional tracklets -> appearance families
             |                       |                    |
             +---- independent witnesses -> identity claims -> arbiter
             |                                            |
             +---- domain hypotheses <---- eligible evidence
                          |
                   independent checks
                          |
                     review decision
                          |
                    accepted domain fact
                          |
                 versioned owning consumer

An appearance family, a persistent instance, an agent identity, and an ability's
caster are separate questions. Class similarity cannot establish instance identity
or caster attribution. Every agent name still comes from the identity arbiter.

## Entity evidence contract

Persist candidates through existing store conventions, with stable observation
keys, session/source references, observation time, frame/ROI coordinates, coordinate
transform, geometry revision, reader/descriptor versions, extent, descriptors,
readability, and refusal reasons. Retain overlapping proposals and unknowns.
Do not copy raw media or derive static maps from session pixels.

Tracklets reference observations and retain association alternatives and gap
reasons. Families reference distinct tracklets and representative appearances.
Neither requires a semantic name. Repeated frames from one instance count as one
instance of support, with separate round/session support also reported.

Exemplars retain their visual surface, phase, applicable scope, labelling witness,
binding evidence, and transitive dependencies. Retrieved identities cannot seed
independent labels. Exclude the query instance from its own references. Match
unknown families without forcing a nearest semantic name.

The ally extension should bind independent witnesses to conservative tracklets,
harvest clean appearances, and retrieve them for unresolved instances. A death and
an icon disappearance merely propose a binding: require readable surrounding
observations, a unique compatible association, and explicit competing explanations.

## Domain hypothesis contract

Keep hypotheses in versioned store artifacts, separate from accepted `domain/*.toml`.
Use a small typed schema with these fields or equivalent explicit structures:

| Field | Meaning |
|---|---|
| hypothesis_id, revision, schema/producer version | Stable identity and immutable revision |
| claim, kind, subject | Concrete proposed assertion and domain subject |
| scope | Applicable map/profile/phase/game version; unspecified scope is explicit |
| proposed_by | Producer or human source; never a fabricated attribution |
| supporting, contradicting, unresolved | Evidence references with distinct roles |
| evidence dependencies | Observation/artifact revisions, identity verdicts, and rules used |
| prediction, falsifier, evaluation plan | What would support or refute the proposal |
| support units | Distinct instances, rounds, sessions; no frame-count confidence |
| status, decision, decision provenance | Proposed, under_review, accepted, rejected, superseded, withdrawn |
| accepted fact reference/revision | Link to canonical fact after promotion |
| supersedes | Previous hypothesis revision or claim where applicable |

Evidence records must distinguish observation time from analysis/review time.
Unknown values remain null with reasons. A statement of support without resolvable
evidence is incomplete, not proof. Preserve contradictory evidence after acceptance.

Appearance examples belong in galleries. Claims about the game or capture belong
in domain hypotheses. Detector accuracy, failure regimes, and tuning outcomes
belong in metrics/capability records. Classify the proposal before promotion.

## Independence and rule feedback

Record the rules used in acquisition selection, association, identification, and
adjudication. Evidence shaped by the candidate rule, a derived equivalent, or its
dependent verdict cannot independently validate that rule. Traverse dependencies;
checking only a direct self-reference is insufficient. Cycles, missing references,
and stale references produce explicit validation refusals.

Preserve raw observations so competing rules can be tested over the same evidence.
Selection influenced by a rule must be visible even when the raw pixels are valid.
Use separately selected source windows to check coverage and counterexamples.
Domain hypotheses may prioritize review or request acquisition; they do not become
hard production constraints before acceptance.

Acceptance requires a recorded review decision and satisfied evidence checks.
Early implementation uses explicit human review decisions. Later automation needs
a separately validated policy per rule family; a confidence threshold alone does
not authorize automatic domain writes. Approximate tendencies remain soft evidence.

`domain` remains the canonical fact owner. Promotion renders a reviewable fact
proposal compatible with its required `claim`, `kind`, `known`, and `since` fields
and existing provenance rules. A reviewed inference retains its derived provenance;
review does not turn it into a directly observed fact. Do not change accepted facts
as part of the initial foundation demonstration.

Consumers resolve accepted fact revisions through the relevant decision owner.
Record consumed fact revisions in artifact provenance. Withdrawal or correction
marks dependent artifacts stale and produces a rebuild plan; it preserves original
observations and historical verdicts. Recompute pure adjudication from stored data.
Decode only when the missing evidence requires source pixels.

## Review and evaluation

Review reports show the claim, scope, independent support, dependent support,
counterexamples, unresolved cases, refusal reasons, and proposed consumer impact.
Link source windows and show diverse appearances where available. Sample refused
observations and no-proposal windows as well as named entities.

Separate frozen-gallery transfer from adaptation using independent witnesses in
the target session. Split evaluation by session and instance before mining or
tuning. Report extraction misses, identity errors, track swaps/fragmentation,
unknown coverage, counterexample coverage, and review effort. Channel agreement
is a diagnostic, not an accuracy label. Never invent measurements or source review.

Before perceptual experiments, inspect source, log falsifiable predictions in the
store's `notes/predictions.jsonl`, and invoke the required labelling workflow when
labelling. The initial implementation does not need a perceptual experiment.

## Initial implementation slice and checkpoint

Implement a usable stored-data domain-hypothesis foundation:

1. Resolve ownership before introducing decision code; declare new ownership and
   architecture placement without duplicating `domain`, identity, or track rules.
2. Add hypothesis/evidence validation and immutable persistence using existing
   artifact/revision machinery. Keep support, contradiction, and unresolved records.
3. Add a command or standalone tool to import a proposal, validate dependencies,
   and render a readable report plus machine-readable output. Prefer a standalone
   adapter if the ongoing session owns `reticle/cli.py`.
4. Produce a reviewable promotion proposal and a dependency impact report for
   withdrawal/correction. Dry-run the full lifecycle with clearly synthetic test
   data isolated from production evidence. Accepted domain files stay unchanged.
5. Exercise the real command on that fixture and inspect its output. Cover
   transitive circular support, stale/missing evidence, contradiction retention,
   invalid transitions, derived provenance, revision immutability, and invalidation
   in focused tests. Synthetic success validates plumbing, not domain truth.
6. Add an executable task contract and concise working-map route. Preserve the
   concurrent ally handoff; coordinate before editing shared working documents.

Report the implemented behavior, commands/checks run, review artifact location,
limits, and the next bounded integration. Stop at this checkpoint before corpus
rescans, repeated mining experiments, real fact promotion, model integration, or
changes to ongoing ally work. Stage 02 remains deterministic and model-free.

Full extraction generalization, automatic hypothesis generation, actual consumer
wiring, and corpus evaluation follow after this foundation checkpoint. Do not
claim that an isolated registry completes the broader entity/domain loop.

## Implementation handoff

Requested agent: GPT-6 Sol, medium reasoning effort. Read `AGENTS.md`, the working
map, current handoff/backlog/contracts, this design, relevant guide sections, and
the owning module docstrings. Run doctor/status and inspect dirty files first.
Use the repository venv. Preserve all unrelated changes, especially concurrent
ally files and `prototypes/mechanics_eval.py`. Commit only verified owned changes;
never stage the entire working tree. Report before substantial experimentation.
