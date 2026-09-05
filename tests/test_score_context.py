"""The window-level facts a per-record signal cannot know on its own.

An outlier is only an outlier against a distribution, a disagreement needs two
records, and novelty needs a dataset to be novel against. All three live here,
computed once per window, so that scoring a record is a pure function of the
record and this object.

The other half of this module is the honest part: which signals could **not** be
evaluated, and whether that is an absence the operator chose or one the window
imposed. "No disagreements found" and "disagreement cannot be seen in a
deduplicated window" are different facts, and a report that printed 0 for both
would be lying in the more dangerous direction.
"""

import pytest

from conftest import load_test_config, make_record
from loghog.errors import ScoreError
from loghog.score.context import build_context, percentile


def settings(tmp_path):
    return load_test_config(tmp_path).score


def context(tmp_path, records, **overrides):
    fields = {
        "settings": settings(tmp_path),
        "shingle_words": 5,
        "dedupe_enabled": False,
        "output_json_expectation": "none",
        "golden_inputs": None,
    }
    fields.update(overrides)
    return build_context(records, **fields)


# --- percentile -------------------------------------------------------------


def test_the_percentile_is_nearest_rank_and_lands_on_a_real_observation():
    # Not interpolated. An interpolated p95 is a latency no request ever had,
    # and "slower than any of these" is easier to defend than "slower than a
    # number we made up between two of them".
    assert percentile([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], 95) == 100
    assert percentile(list(range(1, 21)), 95) == 19


def test_the_percentile_of_one_value_is_that_value():
    assert percentile([7], 50) == 7


def test_the_percentile_ignores_the_order_it_was_given():
    assert percentile([9, 1, 5], 50) == percentile([1, 5, 9], 50)


def test_the_percentile_of_nothing_is_refused():
    with pytest.raises(ScoreError, match="no values"):
        percentile([], 95)


def test_a_percentile_outside_the_range_is_refused():
    with pytest.raises(ScoreError, match="percentile"):
        percentile([1, 2, 3], 0)


# --- outlier thresholds -----------------------------------------------------


def test_a_window_too_small_for_a_distribution_reports_the_outliers_unevaluated(tmp_path):
    records = [make_record(record_id=f"r-{i}", latency_ms=100 + i) for i in range(3)]
    built = context(tmp_path, records)
    assert built.latency_p95 is None
    unevaluated = {entry.signal for entry in built.not_evaluated}
    assert {"latency_outlier", "length_outlier"} <= unevaluated


def test_a_small_window_is_an_absence_and_not_an_impediment(tmp_path):
    records = [make_record(record_id=f"r-{i}", latency_ms=100 + i) for i in range(3)]
    reasons = {entry.signal: entry for entry in context(tmp_path, records).not_evaluated}
    assert reasons["latency_outlier"].blocking is False


def test_a_big_enough_window_gets_a_latency_threshold(tmp_path):
    records = [make_record(record_id=f"r-{i}", latency_ms=100 + i) for i in range(20)]
    built = context(tmp_path, records)
    assert built.latency_p95 == 118
    assert "latency_outlier" not in {entry.signal for entry in built.not_evaluated}


def test_records_without_a_latency_do_not_count_towards_the_sample(tmp_path):
    records = [make_record(record_id=f"r-{i}") for i in range(20)]
    built = context(tmp_path, records)
    assert built.latency_p95 is None


def test_the_length_thresholds_come_from_the_window_itself(tmp_path):
    records = [
        make_record(record_id=f"r-{i}", input_text="x" * (10 + i), output_text="y" * (5 + i))
        for i in range(20)
    ]
    built = context(tmp_path, records)
    assert built.input_len_p95 == 28
    assert built.output_len_p95 == 23


# --- version disagreement ---------------------------------------------------


def failing(record_id, text, version):
    return make_record(
        record_id=record_id, input_text=text, output_text=None,
        error="ProviderTransientError", prompt_version=version,
    )


def passing(record_id, text, version):
    return make_record(record_id=record_id, input_text=text, prompt_version=version)


def test_two_versions_disagreeing_on_one_input_are_recorded(tmp_path):
    records = [passing("a", "the lamp flickers", "v1"), failing("b", "the lamp flickers", "v2")]
    built = context(tmp_path, records)
    assert set(built.disagreements) == {records[0].input_fingerprint()}


def test_two_versions_agreeing_on_one_input_are_not_a_disagreement(tmp_path):
    records = [passing("a", "the lamp flickers", "v1"), passing("b", "the lamp flickers", "v2")]
    assert context(tmp_path, records).disagreements == {}


def test_one_version_failing_twice_on_one_input_is_not_a_disagreement(tmp_path):
    records = [failing("a", "the lamp flickers", "v1"), passing("b", "the lamp flickers", "v1")]
    # Same version, two outcomes: that is flakiness, which is a real thing and
    # not this signal. Calling it a version disagreement would blame a prompt
    # change that never happened.
    assert context(tmp_path, records).disagreements == {}


def test_records_without_a_prompt_version_are_ignored_by_the_signal(tmp_path):
    records = [
        make_record(record_id="a", input_text="the lamp flickers"),
        failing("b", "the lamp flickers", None),
    ]
    assert context(tmp_path, records).disagreements == {}


def test_the_evidence_names_the_versions_and_never_the_input(tmp_path):
    records = [passing("a", "the lamp flickers", "v1"), failing("b", "the lamp flickers", "v2")]
    evidence = next(iter(context(tmp_path, records).disagreements.values()))
    assert "v1" in evidence and "v2" in evidence
    assert "lamp" not in evidence


def test_a_deduplicated_window_cannot_show_a_disagreement_and_says_so(tmp_path):
    # The finding this signal produced: stage 01 deduplicates on the input, so
    # in a deduplicated window two arms answering one question are already one
    # record. Reporting zero would be a lie; this is an impediment.
    records = [passing("a", "the lamp flickers", "v1")]
    reasons = {
        entry.signal: entry
        for entry in context(tmp_path, records, dedupe_enabled=True).not_evaluated
    }
    assert "version_disagreement" in reasons
    assert reasons["version_disagreement"].blocking is True
    assert "dedupe" in reasons["version_disagreement"].reason


# --- novelty and format -----------------------------------------------------


def test_without_goldens_novelty_is_unavailable_rather_than_zero(tmp_path):
    reasons = {entry.signal: entry for entry in context(tmp_path, [make_record()]).not_evaluated}
    assert reasons["novelty"].blocking is False
    assert "--existing" in reasons["novelty"].reason


def test_with_goldens_novelty_is_evaluated(tmp_path):
    built = context(tmp_path, [make_record()], golden_inputs=["a golden case about a lamp"])
    assert built.golden_shingles is not None
    assert "novelty" not in {entry.signal for entry in built.not_evaluated}


def test_an_empty_goldens_file_is_refused_rather_than_making_everything_novel(tmp_path):
    with pytest.raises(ScoreError, match="no cases"):
        context(tmp_path, [make_record()], golden_inputs=[])


def test_no_mapping_declaring_json_leaves_the_format_signal_unavailable(tmp_path):
    reasons = {entry.signal: entry for entry in context(tmp_path, [make_record()]).not_evaluated}
    assert reasons["format_violation"].blocking is False


def test_sources_that_disagree_about_json_are_an_impediment(tmp_path):
    built = context(tmp_path, [make_record()], output_json_expectation="mixed")
    reasons = {entry.signal: entry for entry in built.not_evaluated}
    assert reasons["format_violation"].blocking is True
    assert built.expect_output_json is False


def test_every_source_declaring_json_switches_the_signal_on(tmp_path):
    built = context(tmp_path, [make_record()], output_json_expectation="all")
    assert built.expect_output_json is True
    assert "format_violation" not in {entry.signal for entry in built.not_evaluated}


def test_an_unknown_expectation_is_refused(tmp_path):
    with pytest.raises(ScoreError, match="expectation"):
        context(tmp_path, [make_record()], output_json_expectation="maybe")


def test_a_context_over_no_records_is_refused(tmp_path):
    with pytest.raises(ScoreError, match="no records"):
        context(tmp_path, [])


def test_the_blocked_flag_summarises_the_impediments(tmp_path):
    assert context(tmp_path, [make_record()]).blocked is False
    assert context(tmp_path, [make_record()], dedupe_enabled=True).blocked is True
