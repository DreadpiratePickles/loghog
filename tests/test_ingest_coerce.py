"""Turning whatever the log said into the type the canonical record insists on.

CSV hands everything over as a string; JSON hands over whatever the producer
felt like. This is the boundary where that stops being true, and it is strict:
a value that cannot be resolved without guessing is a typed error naming the
field, never a default.
"""

import pytest

from loghog.errors import FieldTypeError, MissingFieldError, TimestampError
from loghog.ingest.coerce import (
    coerce_bool,
    coerce_int,
    coerce_text,
    coerce_timestamp,
    coerce_verdicts,
    truncate,
)
from loghog.record import JudgeVerdict

# --- text -------------------------------------------------------------------


def test_a_string_comes_through():
    assert coerce_text("hello", field_name="input_text") == "hello"


def test_a_number_is_not_text_by_default():
    # `input_text = 42` is a mapping pointed at the wrong field, not an input.
    with pytest.raises(FieldTypeError, match="input_text"):
        coerce_text(42, field_name="input_text")


def test_a_number_is_accepted_where_an_identifier_is_expected():
    # Plenty of logs number their rows. `12345` is a perfectly good record id.
    assert coerce_text(12345, field_name="record_id", allow_number=True) == "12345"


def test_a_float_is_never_an_identifier():
    with pytest.raises(FieldTypeError):
        coerce_text(1.5, field_name="record_id", allow_number=True)


def test_a_bool_is_never_text():
    with pytest.raises(FieldTypeError):
        coerce_text(True, field_name="record_id", allow_number=True)


def test_none_is_a_missing_field_not_a_type_error():
    with pytest.raises(MissingFieldError):
        coerce_text(None, field_name="input_text")


# --- truncation -------------------------------------------------------------


def test_short_text_is_not_truncated():
    assert truncate("hello", 10) == ("hello", False)


def test_long_text_is_cut_and_says_so():
    text, was_cut = truncate("abcdefghij", 5)
    assert was_cut is True
    assert text.startswith("abcde")


def test_a_truncated_text_carries_a_visible_marker():
    text, _ = truncate("abcdefghij", 5)
    assert "TRUNCATED" in text


def test_truncation_at_exactly_the_limit_does_nothing():
    assert truncate("abcde", 5) == ("abcde", False)


# --- integers ---------------------------------------------------------------


def test_an_integer_comes_through():
    assert coerce_int(412, field_name="latency_ms") == 412


def test_a_numeric_string_is_parsed_because_csv_has_no_other_type():
    assert coerce_int("412", field_name="latency_ms") == 412


def test_a_whole_float_is_accepted():
    assert coerce_int(412.0, field_name="latency_ms") == 412


def test_a_fractional_float_is_refused_rather_than_rounded():
    # Rounding here would be the tool quietly deciding what a half-millisecond
    # is worth. It is not this layer's decision to make.
    with pytest.raises(FieldTypeError, match="latency_ms"):
        coerce_int(412.5, field_name="latency_ms")


def test_a_bool_is_not_an_integer():
    with pytest.raises(FieldTypeError):
        coerce_int(True, field_name="latency_ms")


def test_a_non_numeric_string_is_refused():
    with pytest.raises(FieldTypeError):
        coerce_int("fast", field_name="latency_ms")


def test_an_empty_string_is_a_missing_number_not_a_zero():
    # A blank CSV cell is an absent value. Reading it as zero would put a
    # thousand free calls in a cost total.
    with pytest.raises(MissingFieldError):
        coerce_int("", field_name="cost_micro_usd")


# --- booleans ---------------------------------------------------------------


@pytest.mark.parametrize("value", [True, "true", "TRUE", "yes", "1", 1])
def test_the_shapes_of_true(value):
    assert coerce_bool(value, field_name="passed") is True


@pytest.mark.parametrize("value", [False, "false", "No", "0", 0])
def test_the_shapes_of_false(value):
    assert coerce_bool(value, field_name="passed") is False


def test_a_word_that_is_neither_is_refused():
    with pytest.raises(FieldTypeError, match="passed"):
        coerce_bool("maybe", field_name="passed")


def test_a_number_that_is_neither_zero_nor_one_is_refused():
    with pytest.raises(FieldTypeError):
        coerce_bool(2, field_name="passed")


# --- timestamps -------------------------------------------------------------


def test_an_iso_timestamp_with_a_z_comes_through():
    assert coerce_timestamp("2026-09-05T10:00:00Z", field_name="ts_utc") == "2026-09-05T10:00:00Z"


def test_an_offset_is_resolved_to_utc():
    assert coerce_timestamp("2026-09-05T12:00:00+02:00", field_name="ts_utc") == (
        "2026-09-05T10:00:00Z"
    )


def test_sub_second_precision_is_dropped_not_rounded():
    assert coerce_timestamp("2026-09-05T10:00:00.999Z", field_name="ts_utc") == (
        "2026-09-05T10:00:00Z"
    )


def test_epoch_seconds_are_understood():
    assert coerce_timestamp(1_788_000_000, field_name="ts_utc") == "2026-08-29T10:40:00Z"


def test_epoch_milliseconds_are_understood():
    assert coerce_timestamp(1_788_000_000_000, field_name="ts_utc") == "2026-08-29T10:40:00Z"


def test_an_epoch_as_a_string_is_understood():
    assert coerce_timestamp("1788000000", field_name="ts_utc") == "2026-08-29T10:40:00Z"


def test_a_naive_timestamp_is_refused_by_default():
    # The silent assumption this rule exists to prevent: a log written in
    # Berlin, read in London, and off by an hour for the rest of its life.
    with pytest.raises(TimestampError, match="naive_is_utc"):
        coerce_timestamp("2026-09-05T10:00:00", field_name="ts_utc")


def test_a_naive_timestamp_is_accepted_when_the_mapping_says_it_is_utc():
    assert coerce_timestamp(
        "2026-09-05T10:00:00", field_name="ts_utc", naive_is_utc=True
    ) == "2026-09-05T10:00:00Z"


def test_a_space_separated_timestamp_is_understood():
    assert coerce_timestamp(
        "2026-09-05 10:00:00", field_name="ts_utc", naive_is_utc=True
    ) == "2026-09-05T10:00:00Z"


def test_nonsense_is_a_timestamp_error_naming_the_value():
    with pytest.raises(TimestampError, match="yesterday"):
        coerce_timestamp("yesterday", field_name="ts_utc")


def test_a_bool_is_not_a_timestamp():
    with pytest.raises(TimestampError):
        coerce_timestamp(True, field_name="ts_utc")


def test_none_is_a_missing_timestamp():
    with pytest.raises(MissingFieldError):
        coerce_timestamp(None, field_name="ts_utc")


def test_a_negative_epoch_is_refused():
    with pytest.raises(TimestampError):
        coerce_timestamp(-1, field_name="ts_utc")


# --- verdicts ---------------------------------------------------------------


def test_a_list_of_objects_becomes_verdicts():
    verdicts = coerce_verdicts(
        [{"criterion": "names the product", "passed": True}],
        field_name="judge_verdicts",
        criterion_key="criterion",
        passed_key="passed",
    )
    assert verdicts == (JudgeVerdict(criterion="names the product", passed=True),)


def test_the_key_names_come_from_the_mapping():
    verdicts = coerce_verdicts(
        [{"check": "is short", "ok": "false"}],
        field_name="judge_verdicts",
        criterion_key="check",
        passed_key="ok",
    )
    assert verdicts == (JudgeVerdict(criterion="is short", passed=False),)


def test_a_criterion_to_boolean_mapping_is_accepted():
    # The other shape logs use: one object, criteria as keys.
    verdicts = coerce_verdicts(
        {"is short": True, "names the product": False},
        field_name="judge_verdicts",
        criterion_key="criterion",
        passed_key="passed",
    )
    assert verdicts == (
        JudgeVerdict(criterion="is short", passed=True),
        JudgeVerdict(criterion="names the product", passed=False),
    )


def test_an_empty_list_is_no_verdicts_rather_than_an_error():
    assert coerce_verdicts([], field_name="v", criterion_key="c", passed_key="p") == ()


def test_a_verdict_missing_its_criterion_is_refused():
    with pytest.raises(MissingFieldError):
        coerce_verdicts(
            [{"passed": True}], field_name="v", criterion_key="criterion", passed_key="passed"
        )


def test_a_verdict_whose_passed_is_nonsense_is_refused():
    with pytest.raises(FieldTypeError):
        coerce_verdicts(
            [{"criterion": "c", "passed": "sort of"}],
            field_name="v",
            criterion_key="criterion",
            passed_key="passed",
        )


def test_something_that_is_neither_a_list_nor_an_object_is_refused():
    with pytest.raises(FieldTypeError):
        coerce_verdicts("passed", field_name="v", criterion_key="c", passed_key="p")
