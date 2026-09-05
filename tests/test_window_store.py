"""Writing a window, and refusing to write one that still carries personal data.

The refusal is the point of the module. `[privacy] redact = true` is a promise,
and a promise kept by a habit somewhere upstream is not a promise. Every record
is re-checked at the moment it is about to become bytes on a disk.
"""

import json
import stat

import pytest

from conftest import make_record
from loghog.errors import ManifestError, UnredactedWriteError, WindowConflictError
from loghog.record import REDACTED_TEXT_FIELDS, JudgeVerdict
from loghog.window.store import (
    ERRORS_NAME,
    MANIFEST_NAME,
    RECORDS_NAME,
    REPORT_NAME,
    WindowStore,
)
from test_window_manifest import make_manifest


def store_at(tmp_path):
    return WindowStore(tmp_path / "records" / "2026-09-05")


def test_the_file_names_are_the_documented_ones():
    assert (RECORDS_NAME, MANIFEST_NAME, ERRORS_NAME, REPORT_NAME) == (
        "records.jsonl",
        "manifest.json",
        "errors.jsonl",
        "ingest.md",
    )


def test_a_new_window_does_not_exist_yet(tmp_path):
    assert store_at(tmp_path).exists is False


def test_writing_records_creates_the_window(tmp_path):
    store = store_at(tmp_path)
    store.append_records([make_record()], redaction_enabled=True)
    assert store.exists is True
    assert store.records_path.is_file()


def test_a_record_is_written_as_one_json_object_per_line(tmp_path):
    store = store_at(tmp_path)
    store.append_records([make_record(record_id="a"), make_record(record_id="b")],
                         redaction_enabled=True)
    lines = store.records_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["record_id"] == "a"


def test_appending_adds_to_what_is_there(tmp_path):
    store = store_at(tmp_path)
    store.append_records([make_record(record_id="a")], redaction_enabled=True)
    store.append_records([make_record(record_id="b", input_text="other")],
                         redaction_enabled=True)
    assert len(store.records_path.read_text(encoding="utf-8").splitlines()) == 2


def test_the_window_directory_is_not_world_readable(tmp_path):
    # It holds production text. That is the whole reason it exists, and the
    # whole reason it is gitignored and 0700.
    store = store_at(tmp_path)
    store.append_records([make_record()], redaction_enabled=True)
    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.records_path.stat().st_mode) == 0o600


# --- the write guard --------------------------------------------------------


def test_a_record_still_carrying_an_email_is_refused(tmp_path):
    store = store_at(tmp_path)
    leaky = make_record(input_text="write to sam@example.com about the lamp")
    with pytest.raises(UnredactedWriteError, match="EMAIL"):
        store.append_records([leaky], redaction_enabled=True)


def test_the_refusal_names_the_record_but_not_the_value(tmp_path):
    store = store_at(tmp_path)
    leaky = make_record(record_id="r-9", input_text="sam@example.com")
    with pytest.raises(UnredactedWriteError) as caught:
        store.append_records([leaky], redaction_enabled=True)
    assert "r-9" in str(caught.value)
    assert "sam@example.com" not in str(caught.value)


def test_the_guard_checks_the_output_as_well_as_the_input(tmp_path):
    store = store_at(tmp_path)
    leaky = make_record(output_text="I have refunded card 4242 4242 4242 4242")
    with pytest.raises(UnredactedWriteError):
        store.append_records([leaky], redaction_enabled=True)


def test_the_guard_checks_the_verdict_criteria_too(tmp_path):
    # A criterion is free text lifted verbatim out of the customer's log —
    # `judged_summaries.toml` maps one — so it is a fifth way production text
    # reaches this file, and the guard has to know about it.
    store = store_at(tmp_path)
    leaky = make_record(
        judge_verdicts=(
            JudgeVerdict(criterion="mentions susan.calvin@example.com", passed=False),
        )
    )
    with pytest.raises(UnredactedWriteError, match="EMAIL"):
        store.append_records([leaky], redaction_enabled=True)


@pytest.mark.parametrize("field_name", REDACTED_TEXT_FIELDS)
def test_the_guard_covers_every_field_the_redactor_covers(tmp_path, field_name):
    # The two tuples must not drift. A sixth text field added to the redactor
    # and forgotten here is exactly how a criterion reached disk unredacted.
    store = store_at(tmp_path)
    # A record carries an output or an error, never both, so setting `error`
    # means clearing the output that `make_record` supplies by default.
    fields = {field_name: "write to sam@example.com"}
    if field_name == "error":
        fields["output_text"] = None
    leaky = make_record(**fields)
    with pytest.raises(UnredactedWriteError, match="EMAIL"):
        store.append_records([leaky], redaction_enabled=True)


def test_the_verdict_refusal_names_the_field_but_not_the_value(tmp_path):
    store = store_at(tmp_path)
    leaky = make_record(
        record_id="r-7",
        judge_verdicts=(
            JudgeVerdict(criterion="quotes card 4242 4242 4242 4242", passed=True),
        ),
    )
    with pytest.raises(UnredactedWriteError) as caught:
        store.append_records([leaky], redaction_enabled=True)
    message = str(caught.value)
    assert "r-7" in message
    assert "judge_verdicts" in message
    assert "4242 4242 4242 4242" not in message


def test_a_refused_write_leaves_nothing_behind(tmp_path):
    # All or nothing: a half-written window is worse than no window, because
    # its manifest would describe records that are not there.
    store = store_at(tmp_path)
    with pytest.raises(UnredactedWriteError):
        store.append_records(
            [make_record(record_id="a"), make_record(record_id="b", input_text="sam@example.com")],
            redaction_enabled=True,
        )
    assert not store.records_path.exists()


def test_with_redaction_off_the_guard_needs_an_explicit_override(tmp_path):
    store = store_at(tmp_path)
    with pytest.raises(UnredactedWriteError, match="allow-unredacted"):
        store.append_records(
            [make_record(input_text="sam@example.com")], redaction_enabled=False
        )


def test_with_redaction_off_and_the_override_the_text_is_written_as_it_came(tmp_path):
    store = store_at(tmp_path)
    store.append_records(
        [make_record(input_text="sam@example.com")],
        redaction_enabled=False,
        allow_unredacted=True,
    )
    assert "sam@example.com" in store.records_path.read_text(encoding="utf-8")


def test_the_override_does_not_apply_when_redaction_is_on(tmp_path):
    # Belt and braces: with redaction on, a leaky record means the redactor
    # failed, and no command-line flag should let that through.
    store = store_at(tmp_path)
    with pytest.raises(UnredactedWriteError):
        store.append_records(
            [make_record(input_text="sam@example.com")],
            redaction_enabled=True,
            allow_unredacted=True,
        )


# --- reading back -----------------------------------------------------------


def test_the_fingerprints_of_an_existing_window_can_be_read_back(tmp_path):
    store = store_at(tmp_path)
    record = make_record()
    store.append_records([record], redaction_enabled=True)
    assert store.existing_fingerprints() == {record.input_fingerprint()}


def test_the_fingerprints_of_a_window_that_does_not_exist_are_empty(tmp_path):
    assert store_at(tmp_path).existing_fingerprints() == set()


def test_a_corrupt_record_line_stops_the_read_rather_than_being_skipped(tmp_path):
    store = store_at(tmp_path)
    store.append_records([make_record()], redaction_enabled=True)
    store.records_path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        store.existing_fingerprints()


# --- the manifest -----------------------------------------------------------


def test_a_manifest_round_trips_through_the_store(tmp_path):
    store = store_at(tmp_path)
    manifest = make_manifest()
    store.write_manifest(manifest)
    assert store.read_manifest() == manifest


def test_reading_a_manifest_that_is_not_there_is_a_manifest_error(tmp_path):
    with pytest.raises(ManifestError, match="manifest"):
        store_at(tmp_path).read_manifest()


def test_a_manifest_of_broken_json_is_a_manifest_error(tmp_path):
    store = store_at(tmp_path)
    store.write_manifest(make_manifest())
    store.manifest_path.write_text("{", encoding="utf-8")
    with pytest.raises(ManifestError):
        store.read_manifest()


def test_the_manifest_is_written_atomically(tmp_path):
    # Written to a neighbour and renamed, so an interrupted run leaves either
    # the old manifest or the new one and never half of either.
    store = store_at(tmp_path)
    store.write_manifest(make_manifest())
    assert list(store.directory.glob("*.tmp")) == []


def test_a_window_that_already_exists_refuses_a_fresh_run(tmp_path):
    store = store_at(tmp_path)
    store.write_manifest(make_manifest())
    with pytest.raises(WindowConflictError, match="--append"):
        store.check_writable(append=False)


def test_a_window_that_already_exists_accepts_an_append(tmp_path):
    store = store_at(tmp_path)
    store.write_manifest(make_manifest())
    store.check_writable(append=True)


def test_appending_to_a_window_that_does_not_exist_is_refused(tmp_path):
    with pytest.raises(WindowConflictError, match="does not exist"):
        store_at(tmp_path).check_writable(append=True)


# --- the other two files ----------------------------------------------------


def test_the_error_report_is_one_json_object_per_rejected_line(tmp_path):
    from loghog.errors import LineFailure

    store = store_at(tmp_path)
    store.append_errors([LineFailure(line_no=3, error_type="MissingFieldError", detail="no ts")])
    payload = json.loads(store.errors_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload == {"detail": "no ts", "error_type": "MissingFieldError", "line_no": 3}


def test_an_empty_error_report_is_still_created_so_its_absence_means_something(tmp_path):
    store = store_at(tmp_path)
    store.append_errors([])
    assert store.errors_path.is_file()
    assert store.errors_path.read_text(encoding="utf-8") == ""


def test_the_human_report_is_written_where_the_docs_say(tmp_path):
    store = store_at(tmp_path)
    store.write_report("# a report\n")
    assert store.report_path.name == REPORT_NAME
    assert store.report_path.read_text(encoding="utf-8") == "# a report\n"
