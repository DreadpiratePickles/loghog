"""What a signal needs to know about the window it is scoring a record inside.

Three of the thirteen signals are not properties of a record at all. An outlier
is only an outlier against a distribution; a version disagreement needs two
records; novelty needs a dataset to be novel against. All three are computed
once, here, so that scoring one record stays a pure function of the record and
this object — which is what makes the whole stage reproducible.

The second half of this module is the honest part. Some signals cannot be
evaluated at all for a given window, and there are two very different reasons:

- **an absence the operator chose** — no goldens file was passed, so nothing can
  be called novel;
- **an impediment the window imposes** — it was deduplicated on the input, so
  two prompt versions answering one question are already one record and no
  disagreement can be seen.

The first is fine and exits 0. The second is a partial success and exits 1,
because "no disagreements" and "disagreement is invisible here" are different
facts and printing 0 for both is a lie in the dangerous direction.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from loghog.cluster.shingles import shingles
from loghog.errors import ScoreError
from loghog.record import Record
from loghog.score.settings import ScoreSettings

JSON_EXPECTATIONS = ("all", "none", "mixed")
"""What the window's sources say about whether outputs should parse as JSON.

`all` — every source's mapping declares it. `none` — no source does. `mixed` —
they disagree, and since a record does not carry which source it came from,
guessing would apply one producer's contract to another producer's output.
"""


@dataclass(frozen=True)
class NotEvaluated:
    """One signal that produced no answer, and whether that is a problem."""

    signal: str
    reason: str
    blocking: bool


@dataclass(frozen=True)
class ScoreContext:
    """Every window-level fact the thirteen signals draw on."""

    settings: ScoreSettings
    records_scored: int
    latency_p95: int | None
    input_len_p95: int | None
    output_len_p95: int | None
    disagreements: dict[str, str]
    golden_shingles: tuple[frozenset[str], ...] | None
    shingle_words: int
    expect_output_json: bool
    not_evaluated: tuple[NotEvaluated, ...]

    @property
    def blocked(self) -> bool:
        """Whether any signal was silenced by the window rather than by choice."""
        return any(entry.blocking for entry in self.not_evaluated)


def percentile(values: Sequence[int], percent: int) -> int:
    """The nearest-rank percentile: an observation, never an interpolation.

    Interpolating gives a p95 latency no request ever had. "Slower than any of
    these" is a sentence somebody can defend; "slower than a number we made up
    between two of them" is not.

    Raises:
        ScoreError: no values, or a percentile outside 1-99.
    """
    if not values:
        raise ScoreError("a percentile over no values is not a number")
    if isinstance(percent, bool) or not isinstance(percent, int) or not 1 <= percent <= 99:
        raise ScoreError(f"percentile must be between 1 and 99, got {percent!r}")
    ordered = sorted(values)
    rank = math.ceil(percent / 100 * len(ordered))
    return ordered[max(rank, 1) - 1]


def build_context(
    records: Sequence[Record],
    *,
    settings: ScoreSettings,
    shingle_words: int,
    dedupe_enabled: bool,
    output_json_expectation: str,
    golden_inputs: Sequence[str] | None = None,
) -> ScoreContext:
    """Compute the window-level facts once.

    Raises:
        ScoreError: no records, an unknown expectation, or a goldens file that
            loaded and holds no cases — which would make every record novel and
            quietly turn a suppression rule into a no-op.
    """
    if not records:
        raise ScoreError("there are no records to score")
    if output_json_expectation not in JSON_EXPECTATIONS:
        raise ScoreError(
            f"unknown output-json expectation {output_json_expectation!r}; "
            f"known: {', '.join(JSON_EXPECTATIONS)}"
        )

    unevaluated: list[NotEvaluated] = []
    latency = _threshold(
        [r.latency_ms for r in records if r.latency_ms is not None],
        settings=settings,
        signal="latency_outlier",
        what="carry a latency",
        unevaluated=unevaluated,
    )
    lengths = _threshold(
        [len(r.input_text) for r in records],
        settings=settings,
        signal="length_outlier",
        what="are in this window",
        unevaluated=unevaluated,
    )
    answered = [len(r.output_text) for r in records if r.output_text is not None]
    outputs = (
        percentile(answered, settings.outlier_percentile)
        if len(answered) >= settings.min_outlier_sample
        else None
    )

    disagreements = _disagreements(records)
    if dedupe_enabled:
        disagreements = {}
        unevaluated.append(
            NotEvaluated(
                signal="version_disagreement",
                reason=(
                    "this window was ingested with dedupe on, and deduplication is on the "
                    "input — so two prompt versions answering one question are already one "
                    "record. Re-ingest with [dedupe] dedupe = false to see disagreements."
                ),
                blocking=True,
            )
        )

    golden_shingles = None
    if golden_inputs is None:
        unevaluated.append(
            NotEvaluated(
                signal="novelty",
                reason="no goldens file was given; pass --existing <goldens.yaml> to compare.",
                blocking=False,
            )
        )
    else:
        if not golden_inputs:
            raise ScoreError(
                "the goldens file loaded and holds no cases. Every record would be novel, "
                "which is a suppression rule that silently does nothing."
            )
        golden_shingles = tuple(
            shingles(text, size=shingle_words) for text in golden_inputs
        )

    expect_json = output_json_expectation == "all"
    if output_json_expectation == "none":
        unevaluated.append(
            NotEvaluated(
                signal="format_violation",
                reason=(
                    "no mapping in this window declares [expect] output_json, so nothing "
                    "here claims its output should parse."
                ),
                blocking=False,
            )
        )
    elif output_json_expectation == "mixed":
        unevaluated.append(
            NotEvaluated(
                signal="format_violation",
                reason=(
                    "the sources in this window disagree about [expect] output_json, and a "
                    "record does not carry which source it came from. Split the window."
                ),
                blocking=True,
            )
        )

    return ScoreContext(
        settings=settings,
        records_scored=len(records),
        latency_p95=latency,
        input_len_p95=lengths,
        output_len_p95=outputs,
        disagreements=disagreements,
        golden_shingles=golden_shingles,
        shingle_words=shingle_words,
        expect_output_json=expect_json,
        not_evaluated=tuple(unevaluated),
    )


def _threshold(
    values: list[int],
    *,
    settings: ScoreSettings,
    signal: str,
    what: str,
    unevaluated: list[NotEvaluated],
) -> int | None:
    """A percentile, or a recorded absence when the sample is too small.

    A p95 over four observations is the largest of four, which is not a
    distribution — it is the word "maximum" wearing a percentile's hat.
    """
    if len(values) < settings.min_outlier_sample:
        unevaluated.append(
            NotEvaluated(
                signal=signal,
                reason=(
                    f"only {len(values)} record(s) {what}; a p{settings.outlier_percentile} "
                    f"needs at least {settings.min_outlier_sample} to be a distribution."
                ),
                blocking=False,
            )
        )
        return None
    return percentile(values, settings.outlier_percentile)


def _outcome(record: Record) -> str:
    """"failed" or "passed", as the disagreement signal understands it."""
    if record.failed or any(not verdict.passed for verdict in record.judge_verdicts):
        return "failed"
    return "passed"


def _disagreements(records: Sequence[Record]) -> dict[str, str]:
    """Input fingerprints where two prompt versions reached different outcomes.

    Keyed on the fingerprint rather than on the text, so nothing here holds a
    copy of what a customer wrote — and the evidence names the versions and the
    outcomes only, for the same reason.
    """
    by_input: dict[str, dict[str, set[str]]] = {}
    for record in records:
        if record.prompt_version is None:
            continue
        versions = by_input.setdefault(record.input_fingerprint(), {})
        versions.setdefault(record.prompt_version, set()).add(_outcome(record))

    found: dict[str, str] = {}
    for fingerprint, versions in by_input.items():
        if len(versions) < 2:
            continue
        outcomes = {version: sorted(seen) for version, seen in versions.items()}
        distinct = {tuple(seen) for seen in outcomes.values()}
        if len(distinct) < 2:
            continue
        described = ", ".join(
            f"{version} ({'/'.join(seen)})" for version, seen in sorted(outcomes.items())
        )
        found[fingerprint] = f"one input, two outcomes across prompt versions: {described}"
    return found
