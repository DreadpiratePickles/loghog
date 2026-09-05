"""`loghog emit` and `loghog promote` — stage 07, and the human gate.

Two commands, and the split between them is the whole design. `emit` writes
*drafts*: a file in project 1's golden-case schema and a review document a
person reads in one sitting. `promote` is the only thing in this repository that
writes into a goldens file, and it refuses without `--reviewed-by` and without
an id typed on the command line.

There is deliberately no `--all`. A switch that promoted everything would be a
switch that made "reviewed by" a lie, and the name in the file is the only thing
that answers "who decided this was correct?" the first time a case fails
somebody's build.
"""

from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from loghog.cli_common import add_config_option, config_from, fail
from loghog.emit.promote import parse_ids, promote
from loghog.emit.run import EXIT_NOTHING, emit_window
from loghog.errors import LoghogError


def add_parsers(subparsers) -> None:
    emit = subparsers.add_parser(
        "emit",
        help="render the labelled shortlist as drafted golden cases plus a review",
        description=(
            "Write candidates-<window>.yaml in project 1's golden-case schema — it "
            "loads with regression_detect.goldens.load_goldens exactly as it stands — "
            "and review-<window>.md, which shows each case, its drafted criteria as "
            "unchecked boxes, and one Accept / Edit / Reject line. Nothing is adopted "
            "here."
        ),
    )
    emit.add_argument("--window", required=True, help="the window whose labels to emit")
    add_config_option(emit)
    emit.set_defaults(handler=run_emit)

    promoter = subparsers.add_parser(
        "promote",
        help="adopt named drafted cases into a goldens file, under a reviewer's name",
        description=(
            "Append the cases you accepted to a goldens file, as text so its comments "
            "survive, and re-load the result with project 1's own loader before "
            "replacing anything. Refuses an unknown id, an id the target already holds, "
            "and a run with no reviewer. There is no switch meaning 'all of them'."
        ),
    )
    promoter.add_argument(
        "--file", required=True, type=Path, help="a candidates file written by `loghog emit`"
    )
    promoter.add_argument(
        "--ids", required=True, help="comma-separated case ids to adopt, in order"
    )
    promoter.add_argument(
        "--into", required=True, type=Path, help="the goldens file to append to"
    )
    promoter.add_argument(
        "--reviewed-by", required=True, help="the person who read these cases and accepted them"
    )
    add_config_option(promoter)
    promoter.set_defaults(handler=run_promote)


def run_emit(args: Namespace) -> int:
    try:
        config = config_from(args)
        outcome = emit_window(config, window=args.window)
    except LoghogError as exc:
        return fail(str(exc))

    lines = [
        f"Window {outcome.window!r}: {outcome.emitted} drafted case(s), "
        f"{outcome.skipped_count} left out for want of criteria."
    ]
    if outcome.dry_run:
        lines.append("  SYNTHETIC — these criteria are placeholders. Do not promote them.")
    if outcome.exit_code == EXIT_NOTHING:
        lines.append(
            "  nothing was emitted, so no candidates file was written. Read "
            f"{outcome.review_path.name} for what failed."
        )
    else:
        lines.append(f"  the dataset is in {outcome.candidates_path.name}")
    lines += [
        f"  the review document is in {outcome.review_path.name}",
        "  nothing is adopted until `loghog promote --ids <id> --reviewed-by <name>`.",
    ]
    print("\n".join(lines))
    return outcome.exit_code


def run_promote(args: Namespace) -> int:
    try:
        config_from(args)
        result = promote(
            candidates_path=args.file,
            case_ids=parse_ids(args.ids),
            into=args.into,
            reviewed_by=args.reviewed_by,
            ts_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except LoghogError as exc:
        return fail(str(exc))

    print(
        f"Promoted {len(result.promoted)} case(s) into {result.into}, reviewed by "
        f"{result.reviewed_by}:\n"
        + "\n".join(f"  {case_id}" for case_id in result.promoted)
        + f"\n  {result.total_cases} case(s) in the file, and it still loads."
    )
    return 0
