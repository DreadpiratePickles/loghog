"""Exact deduplication on the fingerprint of the normalised, redacted input.

Redacted, and that is a real decision: two tickets identical except for the
customer's name collapse into one record. For an eval dataset that is correct —
they are one case — and it is also the only ordering that lets a window be
deduplicated without keeping the raw text around to compare.
"""

from conftest import make_record
from loghog.window.dedupe import Deduper


def test_the_first_sighting_of_an_input_is_new():
    assert Deduper().is_new(make_record()) is True


def test_the_second_sighting_of_the_same_input_is_not():
    deduper = Deduper()
    deduper.is_new(make_record(record_id="a"))
    assert deduper.is_new(make_record(record_id="b")) is False


def test_a_different_input_is_new_again():
    deduper = Deduper()
    deduper.is_new(make_record())
    assert deduper.is_new(make_record(record_id="b", input_text="something else")) is True


def test_inputs_differing_only_in_case_and_spacing_are_the_same_input():
    deduper = Deduper()
    deduper.is_new(make_record(input_text="My  Lamp Flickers"))
    assert deduper.is_new(make_record(record_id="b", input_text="my lamp flickers")) is False


def test_different_outputs_do_not_make_a_new_case():
    # Deliberate. The dataset is keyed on what was asked, not on what came back;
    # two answers to one question is one eval case with a disagreement in it,
    # and noticing that disagreement is stage 03's job.
    deduper = Deduper()
    deduper.is_new(make_record(output_text="one answer"))
    assert deduper.is_new(make_record(record_id="b", output_text="another answer")) is False


def test_the_dropped_count_is_the_number_suppressed():
    deduper = Deduper()
    for index in range(4):
        deduper.is_new(make_record(record_id=f"r-{index}"))
    assert deduper.dropped == 3
    assert deduper.distinct == 1


def test_fingerprints_already_in_the_window_suppress_a_repeat():
    # The `--append` case: a second file into the same window must not add a
    # case the window already has.
    first = make_record()
    deduper = Deduper(seen=[first.input_fingerprint()])
    assert deduper.is_new(make_record(record_id="b")) is False


def test_a_disabled_deduper_lets_everything_through():
    deduper = Deduper(enabled=False)
    deduper.is_new(make_record())
    assert deduper.is_new(make_record(record_id="b")) is True
    assert deduper.dropped == 0


def test_a_disabled_deduper_still_counts_what_it_saw():
    deduper = Deduper(enabled=False)
    deduper.is_new(make_record())
    assert deduper.distinct == 1
