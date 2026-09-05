"""`loghog label` — stage 06, the one command in this package that leaves the machine.

Everything else here reads files and writes files. This one spends money and
somebody else's quota, so it says what it is about to do before it does it: how
many calls, to which model, at what spacing, and roughly how long that will take.
A command that could not tell you its cost before it ran is a command nobody
points at production twice.

`--dry-run` substitutes project 1's `FakeProvider` behaviour — a fixed
placeholder list — makes no network call at all, and paces at zero, because
there is no quota to spread a burst across when nothing is called. Every line it
writes says `SYNTHETIC` first.

The provider is built here and nowhere else. `label_window` takes a drafter, so
the stage itself never learns what a provider is and the tests never need one.
"""

from argparse import Namespace

from regression_detect.providers.base import ProviderError
from regression_detect.providers.gemini import gemini_provider_from_env

from loghog.cli_common import add_config_option, config_from, fail
from loghog.config import model_id_for_ref
from loghog.errors import LoghogError
from loghog.label.draft import Drafter, provider_drafter, synthetic_drafter
from loghog.label.report import SYNTHETIC_BANNER
from loghog.label.run import LABEL_REPORT_NAME, LABELS_NAME, label_window


def add_parsers(subparsers) -> None:
    label = subparsers.add_parser(
        "label",
        help="draft checkable criteria for every selected candidate, one call each",
        description=(
            "One bounded model call per shortlisted record, drafting three to five "
            "plain-English criteria with at least one negative one. Writes "
            f"{LABELS_NAME} and {LABEL_REPORT_NAME} beside the shortlist. Nothing here "
            "adopts anything: `loghog emit` renders drafts and `loghog promote` is the "
            "only command that puts a case in a goldens file."
        ),
    )
    label.add_argument("--window", required=True, help="the window whose shortlist to label")
    label.add_argument(
        "--dry-run",
        action="store_true",
        help="call nothing; write fixed [SYNTHETIC] placeholders and say so on every line",
    )
    label.add_argument(
        "--min-interval-ms",
        type=int,
        default=None,
        help="override [label] min_interval_ms for this run (ignored under --dry-run)",
    )
    add_config_option(label)
    label.set_defaults(handler=run_label)


def run_label(args: Namespace) -> int:
    try:
        config = config_from(args)
        drafter, model_id = _drafter(config, dry_run=args.dry_run)
    except (LoghogError, ProviderError) as exc:
        return fail(str(exc))

    try:
        outcome = label_window(
            config,
            window=args.window,
            drafter=drafter,
            dry_run=args.dry_run,
            min_interval_ms=args.min_interval_ms,
        )
    except LoghogError as exc:
        return fail(str(exc))
    except ValueError as exc:
        # Project 1's pacing validator, which is a `ValueError` rather than one
        # of ours. Surfacing it as a refusal keeps `--min-interval-ms -5` a
        # one-line message instead of a traceback about somebody else's module.
        return fail(f"min_interval_ms: {exc}")

    lines: list[str] = []
    if outcome.dry_run:
        lines.append(SYNTHETIC_BANNER)
    lines += [
        f"Window {outcome.window!r}: {outcome.calls} call(s) to {model_id}, one per "
        f"candidate — {outcome.drafted} drafted, {outcome.failed} failed.",
    ]
    for name, count in sorted(outcome.by_error.items()):
        lines.append(f"  {name}  {count}")
    if outcome.failed:
        lines.append(
            "  a candidate with no draft is kept out of the emitted dataset entirely"
        )
    lines += [
        f"  criteria in {LABELS_NAME}, the accounting in {LABEL_REPORT_NAME}",
        f"  nothing has been adopted. Run `loghog emit --window {outcome.window}` next.",
    ]
    print("\n".join(lines))
    return outcome.exit_code


def _drafter(config, *, dry_run: bool) -> tuple[Drafter, str]:
    """The drafter, and the name of what will answer.

    Raises:
        ProviderConfigError: no API key, from project 1's seam, with a message
            that never contains one.
        UnknownModelRefError: `[label] model_ref` names a reference this build
            does not define — though the configuration loader has already
            refused that, so reaching it here means the two disagree.
    """
    if dry_run:
        return synthetic_drafter(), "nothing (dry run)"
    model_id = model_id_for_ref(config.label.model_ref)
    return provider_drafter(gemini_provider_from_env(model_id)), model_id
