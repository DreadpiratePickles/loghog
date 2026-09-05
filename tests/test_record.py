"""The canonical record, and the invariants that make a window worth mining.

Every source format collapses to this one shape. If the shape is loose, every
later stage has to re-check the same things, and a log line that lied gets to
lie all the way into a golden case.
"""

import dataclasses

import pytest

from loghog.errors import FieldTypeError, MissingFieldError, RecordError, TimestampError
from loghog.record import (
    TIMESTAMP_FORMAT,
    JudgeVerdict,
    Record,
    input_fingerprint,
    normalise_for_dedupe,
    record_from_json_dict,
)

OK_FIELDS = {
    "record_id": "req-001",
    "ts_utc": "2026-09-05T10:00:00Z",
    "input_text": "My lamp flickers above half brightness.",
    "output_text": "Customer reports a flickering lamp.",
}


def make_record(**overrides) -> Record:
    fields = dict(OK_FIELDS)
    fields.update(overrides)
    return Record(**fields)


def test_the_timestamp_format_is_utc_with_a_z_and_no_offset():
    assert TIMESTAMP_FORMAT == "%Y-%m-%dT%H:%M:%SZ"


def test_a_minimal_successful_record_is_valid():
    record = make_record()
    assert record.record_id == "req-001"
    assert record.error is None
    assert record.judge_verdicts == ()


def test_a_record_is_frozen_because_it_already_happened():
    record = make_record()
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.record_id = "changed"


# --- identity ---------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "   ", "\n"])
def test_an_empty_record_id_is_refused(bad):
    with pytest.raises(MissingFieldError):
        make_record(record_id=bad)


def test_a_record_id_containing_a_newline_is_refused():
    # Records are one JSON object per line. An id with a newline in it is an id
    # that cannot survive the file it is written to.
    with pytest.raises(FieldTypeError):
        make_record(record_id="req\n001")


def test_a_non_string_record_id_is_refused():
    with pytest.raises(FieldTypeError):
        make_record(record_id=17)


# --- timestamps -------------------------------------------------------------


def test_a_timestamp_that_is_not_the_canonical_format_is_refused():
    with pytest.raises(TimestampError):
        make_record(ts_utc="2026-09-05 10:00:00")


def test_a_timestamp_carrying_an_offset_is_refused_at_the_record_boundary():
    # Offsets are resolved during coercion, not here. By the time a Record
    # exists the instant is already UTC, and a second representation of "the
    # same moment" is a second thing to keep in step.
    with pytest.raises(TimestampError):
        make_record(ts_utc="2026-09-05T10:00:00+02:00")


def test_an_impossible_date_is_refused():
    with pytest.raises(TimestampError):
        make_record(ts_utc="2026-02-30T10:00:00Z")


# --- the ok / failed split --------------------------------------------------


def test_a_failed_record_carries_an_error_and_no_output():
    record = make_record(output_text=None, error="ProviderTransientError")
    assert record.failed is True
    assert record.output_text is None


def test_a_record_with_neither_an_output_nor_an_error_is_refused():
    # This is the empty-success bug the rulebook names outright: a failed read
    # must not become a successful no-op.
    with pytest.raises(RecordError, match="neither"):
        make_record(output_text=None)


def test_a_record_with_both_an_output_and_an_error_is_refused():
    with pytest.raises(RecordError, match="both"):
        make_record(error="Timeout")


def test_an_empty_output_string_is_not_a_success():
    with pytest.raises(RecordError):
        make_record(output_text="   ")


def test_an_empty_error_string_is_not_a_failure():
    with pytest.raises(RecordError):
        make_record(output_text=None, error="   ")


def test_a_successful_record_reports_failed_false():
    assert make_record().failed is False


# --- the input --------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "    ", "\t\n"])
def test_an_empty_input_is_refused(bad):
    # A record with no input is not an eval case; it is a row that will be
    # dropped by every later stage after being counted by all of them.
    with pytest.raises(MissingFieldError):
        make_record(input_text=bad)


# --- numbers ----------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["latency_ms", "input_tokens", "output_tokens", "cost_micro_usd"]
)
def test_a_negative_number_is_refused(field):
    with pytest.raises(FieldTypeError):
        make_record(**{field: -1})


@pytest.mark.parametrize(
    "field", ["latency_ms", "input_tokens", "output_tokens", "cost_micro_usd"]
)
def test_a_float_is_refused_even_when_it_is_whole(field):
    # Money is integer micro-USD and a token count is a count. A float here is
    # a unit error waiting to be summed a million times.
    with pytest.raises(FieldTypeError):
        make_record(**{field: 1.0})


@pytest.mark.parametrize(
    "field", ["latency_ms", "input_tokens", "output_tokens", "cost_micro_usd"]
)
def test_a_bool_is_refused_because_python_says_true_is_one(field):
    with pytest.raises(FieldTypeError):
        make_record(**{field: True})


def test_zero_is_a_legitimate_number():
    record = make_record(latency_ms=0, input_tokens=0, output_tokens=0, cost_micro_usd=0)
    assert record.cost_micro_usd == 0


# --- optional strings -------------------------------------------------------


@pytest.mark.parametrize("field", ["prompt_version", "arm", "feedback", "error"])
def test_an_optional_string_present_but_empty_is_refused(field):
    overrides = {field: "  "}
    if field == "error":
        overrides["output_text"] = None
    with pytest.raises(RecordError):
        make_record(**overrides)


@pytest.mark.parametrize("field", ["prompt_version", "arm", "feedback"])
def test_an_optional_string_may_be_absent(field):
    assert getattr(make_record(**{field: None}), field) is None


# --- judge verdicts ---------------------------------------------------------


def test_a_verdict_carries_a_criterion_and_a_strict_bool():
    verdict = JudgeVerdict(criterion="names the product", passed=True)
    assert verdict.to_json_dict() == {"criterion": "names the product", "passed": True}


def test_a_verdict_whose_passed_is_not_a_bool_is_refused():
    # 1 and "true" both mean "passed" to a careless reader and neither is a
    # verdict. A judge either said yes or it did not.
    with pytest.raises(FieldTypeError):
        JudgeVerdict(criterion="c", passed=1)


def test_a_verdict_with_an_empty_criterion_is_refused():
    with pytest.raises(MissingFieldError):
        JudgeVerdict(criterion="  ", passed=False)


def test_two_verdicts_on_the_same_criterion_are_refused():
    verdicts = (
        JudgeVerdict(criterion="c", passed=True),
        JudgeVerdict(criterion="c", passed=False),
    )
    with pytest.raises(RecordError, match="twice"):
        make_record(judge_verdicts=verdicts)


def test_verdicts_must_be_verdicts_not_dicts():
    with pytest.raises(FieldTypeError):
        make_record(judge_verdicts=({"criterion": "c", "passed": True},))


def test_verdicts_are_a_tuple_so_a_record_cannot_grow_one_later():
    record = make_record(judge_verdicts=(JudgeVerdict(criterion="c", passed=True),))
    assert isinstance(record.judge_verdicts, tuple)


# --- json round trip --------------------------------------------------------


def test_a_record_round_trips_through_json():
    record = make_record(
        prompt_version="1.1.0",
        arm="candidate",
        latency_ms=412,
        input_tokens=120,
        output_tokens=40,
        cost_micro_usd=136,
        feedback="up",
        judge_verdicts=(JudgeVerdict(criterion="c", passed=False),),
    )
    assert record_from_json_dict(record.to_json_dict()) == record


def test_the_json_form_has_exactly_the_canonical_keys():
    assert set(make_record().to_json_dict()) == {
        "record_id",
        "ts_utc",
        "input_text",
        "output_text",
        "prompt_version",
        "arm",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "cost_micro_usd",
        "error",
        "feedback",
        "judge_verdicts",
    }


def test_the_json_keys_are_sorted_so_a_diff_of_two_windows_is_readable():
    keys = list(make_record().to_json_dict())
    assert keys == sorted(keys)


def test_reading_back_a_record_with_an_unknown_key_is_refused():
    payload = make_record().to_json_dict()
    payload["cost_usd"] = 0.13
    with pytest.raises(RecordError, match="unknown"):
        record_from_json_dict(payload)


def test_reading_back_a_record_with_a_missing_key_is_refused():
    payload = make_record().to_json_dict()
    del payload["ts_utc"]
    with pytest.raises(RecordError, match="missing"):
        record_from_json_dict(payload)


def test_reading_back_something_that_is_not_an_object_is_refused():
    with pytest.raises(RecordError):
        record_from_json_dict(["not", "an", "object"])


def test_reading_back_a_verdict_that_is_not_an_object_is_refused():
    payload = make_record().to_json_dict()
    payload["judge_verdicts"] = ["nope"]
    with pytest.raises(RecordError):
        record_from_json_dict(payload)


def test_reading_back_verdicts_that_are_not_a_list_is_refused():
    payload = make_record().to_json_dict()
    payload["judge_verdicts"] = {"criterion": "c", "passed": True}
    with pytest.raises(RecordError):
        record_from_json_dict(payload)


# --- the dedupe fingerprint -------------------------------------------------


def test_normalisation_lowercases_and_collapses_whitespace():
    assert normalise_for_dedupe("  My   Lamp\n\tFLICKERS ") == "my lamp flickers"


def test_two_inputs_differing_only_in_whitespace_and_case_share_a_fingerprint():
    assert input_fingerprint("Hello  There") == input_fingerprint("hello there")


def test_the_fingerprint_is_a_sha256_hex_digest():
    digest = input_fingerprint("anything")
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_different_inputs_get_different_fingerprints():
    assert input_fingerprint("a lamp") != input_fingerprint("a desk")


def test_the_fingerprint_of_a_record_is_the_fingerprint_of_its_input():
    record = make_record()
    assert record.input_fingerprint() == input_fingerprint(OK_FIELDS["input_text"])
