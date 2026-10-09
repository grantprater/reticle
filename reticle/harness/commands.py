r"""The acceptance harness's subcommands: one parser table, one dispatch.

`reticle acceptance <subcommand>` (`cli.cmd_acceptance`) and the old
`prototypes/question_acceptance.py` both build their parsers here
(`add_parsers`) and run through `dispatch`, which imports the module that
owns each command only when it runs:

* `lane`, `label` -- the enemy lane's emitted tracks against T1d, and the
  replay entity under every find (`run`);
* `ally`, `smoke`, `glyph`, `marks` -- steps 5 to 8, other owners' finds (`run`);
* `replay-score`, `replay-abilities` -- step 9, the replay scorers (`run`);
* `budget` and `budget-feats`, `budget-eye`, `budget-eye-score`,
  `budget-levers`, `budget-sample`, `budget-peek` -- the enemy error budget
  (`run`, `budget`);
* `hook`, `hook-report`, `arms-report` -- QA5r3 over the gated ally pass and
  the stored read-schedule arms (`schedule`);
* `draw-persist`, `draw-smokes` -- T1d's persistence and smoke census (`draw`).

`summary` stays in `cli` beside them: it rescores stored rows on
`reticle.acceptance` alone.
"""
from __future__ import annotations

from pathlib import Path

from .extras import DEV, NEW

#: Every subcommand `dispatch` runs.
COMMANDS = ("label", "lane", "ally", "smoke", "glyph", "marks", "replay-score", "replay-abilities",
            "budget", "budget-feats", "budget-eye", "budget-sample", "budget-levers", "budget-eye-score",
            "budget-peek", "hook", "hook-report", "arms-report", "draw-persist", "draw-smokes")


def add_parsers(sub) -> None:
    """Add every harness subcommand to an argparse subparsers object."""
    p = sub.add_parser("label", help="the replay entity under every find (truth_under)")
    p.add_argument("sessions", nargs="*", default=list(DEV))
    p.add_argument("--tag", required=True)
    p.add_argument("--pings", default="b1")
    p.add_argument("--reality", choices=("off", "on"), default="off")
    p = sub.add_parser("lane", help="the enemy lane's emitted tracks against T1d")
    p.add_argument("sessions", nargs="*", default=list(DEV))
    p.add_argument("--tag", required=True)
    p.add_argument("--pings", default="b1",
                   help="the teardrop_refusals ping reread classing the extras (the tag's score used b1)")
    p.add_argument("--reality", choices=("off", "on", "paired"), default="off",
                   help="the detection_reality arm: off (no glyph verdicts), on, or both paired")
    p.add_argument("--record", action="store_true")
    for step, hlp in (("ally", "step 5: round_entities' teammates"), ("smoke", "step 6: smoke_owner's smokes"),
                      ("glyph", "step 7: the glyph owner's verdicts"), ("marks", "step 8: X and \"?\" marks")):
        p = sub.add_parser(step, help=hlp)
        p.add_argument("sessions", nargs="*", default=list(DEV))
        p.add_argument("--tag", required=step == "marks", default=None)
        p.add_argument("--pings", default="b1")
        p.add_argument("--record", action="store_true")
    p = sub.add_parser("replay-score", help="step 9: replay_truth score, its phantoms against every entity")
    p.add_argument("sessions", nargs="*", default=list(DEV))
    p.add_argument("--geometry", type=Path, default=None,
                   help="a baked geometry npz in place of the session's own (no class-aware block)")
    p.add_argument("--legacy-out", default=None,
                   help="also write the report alone under replay_truth.ANALYSIS with this name")
    p.add_argument("--record", action="store_true", help="the class-aware values")
    p.add_argument("--record-score", action="store_true", help="the replay_truth/score series")
    p = sub.add_parser("replay-abilities", help="step 9: replay_abilities score, its point finds "
                                                 "against every entity")
    p.add_argument("sessions", nargs="*", default=list(DEV))
    p.add_argument("--legacy-out", action="store_true",
                   help="also write the report alone under replay_abilities.ANALYSIS")
    p.add_argument("--record", action="store_true", help="the class-aware values")
    p.add_argument("--record-score", action="store_true", help="the replay_abilities/score series")
    p = sub.add_parser("budget", help="step 9: the enemy error budget, extras from truth_under")
    p.add_argument("sessions", nargs="*", default=list(DEV))
    p.add_argument("--tag", required=True)
    p.add_argument("--record", action="store_true")
    p.add_argument("--rewrite", action="store_true",
                   help="rewrite a stored players-only budget that differs")
    p = sub.add_parser("budget-feats", help="the budget's features per miss and extra")
    p.add_argument("sessions", nargs="+")
    p.add_argument("--tag", required=True)
    p = sub.add_parser("budget-eye", help="the budget's crops for the eye check")
    p.add_argument("--tag", required=True)
    p.add_argument("--n", type=int, default=12)
    p.add_argument("--only", help="SET__CLASS,... to draw (default: every class at or above EYE_SHARE)")
    p.add_argument("--out", default="eye")
    p = sub.add_parser("budget-sample", help="the budget's stratified label sample")
    p.add_argument("--tag", required=True)
    for name in ("budget-levers", "budget-eye-score"):
        p = sub.add_parser(name)
        p.add_argument("--tag", required=True)
        p.add_argument("--record", action="store_true")
    p = sub.add_parser("budget-peek", help="crops of feature rows a filter picks (exploration)")
    p.add_argument("--tag", required=True)
    p.add_argument("--sessions", default=",".join(DEV))
    p.add_argument("--set", default="miss")
    p.add_argument("--expr", default="True", help="a Python filter over the feature row f (exploration)")
    p.add_argument("--n", type=int, default=12)
    p.add_argument("--name", required=True)
    p = sub.add_parser("hook", help="QA5r3: the production ally gate simulated on stored ally_icon "
                                    "rows; V15h, Vhook and Vhook+a per session")
    p.add_argument("sessions", nargs="+", help=f"e.g. {' '.join(DEV + NEW)}")
    p = sub.add_parser("hook-report", help="QA5r3 of the hook arms pooled (dev3, new3, all6), "
                                           "with read share and CPU per session")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("arms-report", help="QA5r2 or QA5r3 of the stored read-schedule arms "
                                           "(prototypes/real_reader_schedule.py run)")
    p.add_argument("--rule", choices=("QA5r2", "QA5r3"), default="QA5r3")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("draw-persist", help="T1d's persistence: icon to '?' swaps less the last sight")
    p.add_argument("sessions", nargs="*", default=list(DEV))
    p = sub.add_parser("draw-smokes", help="T1d's smoke census: modelled smokes and blockers left out")
    p.add_argument("keys", nargs="*", help="replay keys (default: every stored replay layer)")


def dispatch(a, cmd: str) -> int:
    """Run the parsed subcommand `cmd` (an entry of `COMMANDS`)."""
    from . import extras as tr

    a.cmd = cmd
    tr._idle()
    if cmd in ("hook", "hook-report", "arms-report"):
        from . import schedule as rrs
        for s in getattr(a, "sessions", None) or []:
            rrs.refuse(s)
        if cmd == "hook":
            return rrs.run_hook(a.sessions)
        if cmd == "hook-report":
            return rrs.report_hook(a.record)
        return rrs.report_qa5r2(a.record, a.rule)
    if cmd in ("draw-persist", "draw-smokes"):
        from . import draw as tdr
        from .match import replay_matches
        if cmd == "draw-persist":
            for s in a.sessions:
                tdr.refuse(s)
            return tdr.run_persist(a.sessions or list(DEV))
        return tdr.run_smokes(a.keys or replay_matches())
    from . import run
    if cmd == "replay-score":
        return run.run_replay_score(a.sessions or list(DEV), a.geometry, a.legacy_out, a.record, a.record_score)
    if cmd == "replay-abilities":
        return run.run_replay_abilities(a.sessions or list(DEV), a.legacy_out, a.record, a.record_score)
    if cmd == "budget":
        return run.run_budget(a.tag, a.sessions or list(DEV), a.record, a.rewrite)
    if cmd.startswith("budget-"):
        return run.run_budget_tool(a)
    if cmd in run.STEP_FUNCS:
        return run.run_step(cmd, a.sessions or list(DEV), a.tag, a.pings, a.record)
    if cmd == "label":
        return run.run_label(a.sessions or list(DEV), a.tag, a.pings, a.reality)
    return run.run_lane(a.sessions or list(DEV), a.tag, a.pings, a.record, a.reality)
