# Bootstrap integration source question

The old lane adapter names Phoenix as killer on the entry keyed
`death:a06f04a0059f:412000:0:killer`. That key is absent from the production
death stream. Production has `death:a06f04a0059f:412000:1` and already names
Phoenix as killer. The
[source frame](../../../../bootstrap-b/.experiment-store/bootstrap-b/source-412000.jpg)
shows adjacent killfeed rows at the query instant. Their distinct event count
and association to the stored entry need a controlled check. The earlier lane
frame is a review prompt, not a source label.

Ask the player: **At 06:52 in `a06f04a0059f`, are the visible `Me` killfeed rows
distinct kills? Which row first appeared at 409000 ms, and which at 412000 ms?**
Answers: **distinct (mark each row)**, **one event repeated (mark it)**,
or **cannot tell**. Show the source frame without the learned verdict first;
ring each proposed row in the review tool. Record the answer, source
coordinates, reviewer and source revision under the repository's `labelling-pass`
contract before running source accuracy comparison. Keep a no-proposal control
and the prior lane's seeded random event in the same review pass.

No answer has been entered. The learner's source accuracy is unknown. The
`a1a995e6b19b` session was seen during production acceptance, so it is only
learner held out; use fresh source for a later generalization test.

The stored combat report identity stream has `conflicting_claims` cases where
`scoreboard_kd` and `killfeed_portrait` disagree. `death_verdict` often inherits
the killfeed name and supplies no independent vote. A bounded next experiment
should inspect one report portrait cluster with a scoreboard bound of one, for
example `combat_report:223d636bf8d2:portrait:2`, against its source panel and
Tab opening, then test the row-to-entry association. Do not tune either reader
until that association has source evidence.
