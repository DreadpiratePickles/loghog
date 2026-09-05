"""The whole of stage 01 and stage 02, end to end, over the committed sample.

The sample log is the one in `samples/`, not a fixture invented here — thirteen
lines with two broken ones, a duplicate, an allowlisted product that must
survive redaction and an order reference that must survive it too. If the
sample changes, these numbers change with it, and that is the point.
"""

import json

import pytest

from conftest import SAMPLES_DIR, load_test_config, write_jsonl, write_lines
from loghog.errors import (
    ManifestError,
    MappingError,
    UnredactedWriteError,
    WindowConflictError,
)
from loghog.ingest.run import EXIT_NOTHING, EXIT_OK, EXIT_PARTIAL, ingest
from loghog.window.store import WindowStore

SAMPLE = SAMPLES_DIR / "support_chat.synthetic.jsonl"
SAMPLE_CSV = SAMPLES_DIR / "support_tickets.synthetic.csv"
CSV_MAPPING = SAMPLES_DIR / "support_csv.toml"


def run(tmp_path, *, substitutions=(), **overrides):
    config = load_test_config(tmp_path, substitutions)
    kwargs = {
        "input_path": SAMPLE,
        "source_format": "jsonl",
        "mapping_reference": "openai_chat_jsonl",
        "window": "demo",
        "synthetic": True,
    }
    kwargs.update(overrides)
    return config, ingest(config, **kwargs)


def records_of(outcome):
    store = WindowStore(outcome.directory)
    return [
        json.loads(line)
        for line in store.records_path.read_text(encoding="utf-8").splitlines()
    ]


# --- the happy path ---------------------------------------------------------


def test_the_sample_produces_records(tmp_path):
    _, outcome = run(tmp_path)
    assert outcome.manifest.counts.records_written > 0
    assert len(records_of(outcome)) == outcome.manifest.counts.records_written


def test_every_line_of_the_sample_is_accounted_for(tmp_path):
    _, outcome = run(tmp_path)
    counts = outcome.manifest.counts
    assert counts.lines_read == counts.rows + counts.blank_lines + counts.unparsed
    assert counts.rows == counts.records_written + counts.duplicates_dropped + counts.invalid


def test_the_two_kinds_of_bad_line_are_counted_separately(tmp_path):
    # The sample has one line that is not JSON at all and one that reads
    # perfectly and is not a record. They are different problems.
    _, outcome = run(tmp_path)
    assert outcome.manifest.counts.unparsed == 1
    assert outcome.manifest.counts.invalid == 1


def test_the_two_deliberately_broken_lines_are_rejected_and_named(tmp_path):
    _, outcome = run(tmp_path)
    assert outcome.manifest.counts.rejected == 2
    assert len(outcome.failures) == 2
    assert all(failure.error_type for failure in outcome.failures)


def test_a_run_with_rejected_lines_does_not_exit_zero(tmp_path):
    # A partial success that returns 0 is the failure this tool exists to
    # prevent: nobody reads the report of a command that succeeded.
    _, outcome = run(tmp_path)
    assert outcome.exit_code == EXIT_PARTIAL


def test_the_duplicate_complaint_is_deduplicated(tmp_path):
    _, outcome = run(tmp_path)
    assert outcome.manifest.counts.duplicates_dropped == 1


def test_deduplication_can_be_turned_off(tmp_path):
    _, outcome = run(tmp_path, substitutions=[("dedupe = true", "dedupe = false")])
    assert outcome.manifest.counts.duplicates_dropped == 0


def test_the_window_lands_where_the_configuration_says(tmp_path):
    config, outcome = run(tmp_path)
    assert outcome.directory == config.records_dir / "demo"


def test_an_explicit_output_directory_wins(tmp_path):
    elsewhere = tmp_path / "somewhere"
    _, outcome = run(tmp_path, out_dir=elsewhere)
    assert outcome.directory == elsewhere


def test_all_four_files_are_written(tmp_path):
    _, outcome = run(tmp_path)
    store = WindowStore(outcome.directory)
    for path in (store.records_path, store.manifest_path, store.errors_path, store.report_path):
        assert path.is_file(), path


# --- redaction --------------------------------------------------------------


def test_no_email_survives_into_the_records(tmp_path):
    _, outcome = run(tmp_path)
    blob = WindowStore(outcome.directory).records_path.read_text(encoding="utf-8")
    assert "susan.calvin@example.com" not in blob
    assert "[EMAIL_1]" in blob


def test_the_email_inside_a_url_is_the_one_that_was_caught(tmp_path):
    _, outcome = run(tmp_path)
    blob = WindowStore(outcome.directory).records_path.read_text(encoding="utf-8")
    assert "app.example.com/users/[EMAIL_1]" in blob


def test_the_card_is_redacted_and_the_order_reference_is_not(tmp_path):
    _, outcome = run(tmp_path)
    blob = WindowStore(outcome.directory).records_path.read_text(encoding="utf-8")
    assert "4242 4242 4242 4242" not in blob
    assert "[CARD_1]" in blob
    assert "1234567812345678" in blob


def test_the_allowlisted_product_survives(tmp_path):
    _, outcome = run(tmp_path)
    blob = WindowStore(outcome.directory).records_path.read_text(encoding="utf-8")
    assert "Dr Pepper" in blob


def test_the_redaction_report_counts_by_class(tmp_path):
    _, outcome = run(tmp_path)
    by_class = outcome.manifest.redaction["by_class"]
    assert by_class["EMAIL"] >= 1
    assert by_class["CARD"] >= 1
    assert by_class["SSN"] >= 1


def test_the_manifest_says_redaction_was_on(tmp_path):
    _, outcome = run(tmp_path)
    assert outcome.manifest.redaction["enabled"] is True


def test_turning_redaction_off_without_the_flag_refuses_before_anything_is_written(tmp_path):
    with pytest.raises(UnredactedWriteError):
        run(tmp_path, substitutions=[("redact = true", "redact = false")])
    assert not (tmp_path / "records").exists()


def test_turning_redaction_off_with_the_flag_writes_the_text_as_it_came(tmp_path):
    _, outcome = run(
        tmp_path,
        substitutions=[("redact = true", "redact = false")],
        allow_unredacted=True,
    )
    blob = WindowStore(outcome.directory).records_path.read_text(encoding="utf-8")
    assert "susan.calvin@example.com" in blob
    assert outcome.manifest.redaction["enabled"] is False


# --- windows ----------------------------------------------------------------


def test_running_twice_into_one_window_is_refused(tmp_path):
    config, _ = run(tmp_path)
    with pytest.raises(WindowConflictError, match="--append"):
        ingest(
            config,
            input_path=SAMPLE,
            source_format="jsonl",
            mapping_reference="openai_chat_jsonl",
            window="demo",
        )


def test_appending_a_second_file_adds_to_the_window(tmp_path):
    config, first = run(tmp_path)
    second = ingest(
        config,
        input_path=SAMPLE_CSV,
        source_format="csv",
        mapping_reference=str(CSV_MAPPING),
        window="demo",
        append=True,
        synthetic=True,
    )
    assert len(second.manifest.sources) == 2
    assert second.manifest.counts.records_written > first.manifest.counts.records_written


def test_appending_the_same_file_twice_is_refused(tmp_path):
    config, _ = run(tmp_path)
    with pytest.raises(ManifestError, match="already"):
        ingest(
            config,
            input_path=SAMPLE,
            source_format="jsonl",
            mapping_reference="openai_chat_jsonl",
            window="demo",
            append=True,
        )


def test_the_manifest_records_the_source_hash_and_the_mapping_hash(tmp_path):
    _, outcome = run(tmp_path)
    (source,) = outcome.manifest.sources
    assert len(source.sha256) == 64
    assert len(source.mapping_sha256) == 64
    assert source.mapping == "openai_chat_jsonl"


def test_the_recorded_source_path_is_relative(tmp_path):
    _, outcome = run(tmp_path)
    (source,) = outcome.manifest.sources
    assert not source.path.startswith("/")


# --- csv --------------------------------------------------------------------


def test_the_csv_sample_ingests_cleanly(tmp_path):
    _, outcome = run(
        tmp_path,
        input_path=SAMPLE_CSV,
        source_format="csv",
        mapping_reference=str(CSV_MAPPING),
    )
    assert outcome.exit_code == EXIT_OK
    assert outcome.manifest.counts.records_written == 5


def test_an_empty_csv_cell_does_not_fail_the_row(tmp_path):
    _, outcome = run(
        tmp_path,
        input_path=SAMPLE_CSV,
        source_format="csv",
        mapping_reference=str(CSV_MAPPING),
    )
    ratings = [record["feedback"] for record in records_of(outcome)]
    assert None in ratings and "up" in ratings


# --- refusals ---------------------------------------------------------------


def test_a_format_that_contradicts_the_mapping_is_refused(tmp_path):
    with pytest.raises(MappingError, match="csv"):
        run(tmp_path, source_format="csv")


def test_a_mapping_that_needs_a_sidecar_and_has_none_is_refused(tmp_path):
    with pytest.raises(MappingError, match="sidecar"):
        run(tmp_path, mapping_reference="regress_rollout_events")


def test_a_file_where_nothing_survives_writes_nothing_and_exits_two(tmp_path):
    path = write_lines(tmp_path / "junk.jsonl", "not json\nalso not json\n")
    _, outcome = run(tmp_path, input_path=path)
    assert outcome.exit_code == EXIT_NOTHING
    assert outcome.manifest is None
    assert not (tmp_path / "records" / "demo" / "records.jsonl").exists()


def test_a_file_where_nothing_survives_still_reports_why(tmp_path):
    path = write_lines(tmp_path / "junk.jsonl", "not json\n")
    _, outcome = run(tmp_path, input_path=path)
    assert len(outcome.failures) == 1


# --- the sidecar path -------------------------------------------------------


def test_a_rollout_event_log_ingests_when_its_traffic_file_is_supplied(tmp_path):
    import hashlib

    text = "The Lumen desk lamp flickers above half brightness."
    traffic = write_jsonl(tmp_path / "traffic.jsonl", [{"request_id": "tk-1", "text": text}])
    events = write_jsonl(
        tmp_path / "events.jsonl",
        [
            {
                "request_id": "tk-1",
                "unit_id": "cust-1",
                "ts_utc": "2026-09-04T12:00:00Z",
                "flag": "summarizer-1.1",
                "step_index": 2,
                "exposure_percent": 25,
                "arm": "candidate",
                "prompt_label": "1.1.0",
                "prompt_sha256": "a" * 64,
                "model_id": "a-model",
                "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "status": "ok",
                "output_text": "A flickering lamp.",
                "latency_ms": 412,
                "input_tokens": 120,
                "output_tokens": 40,
                "cost_micro_usd": 136,
                "currency": "USD",
                "error_type": None,
                "feedback": None,
            }
        ],
    )
    _, outcome = run(
        tmp_path,
        input_path=events,
        mapping_reference="regress_rollout_events",
        sidecar_path=traffic,
    )
    assert outcome.exit_code == EXIT_OK
    (record,) = records_of(outcome)
    assert record["input_text"] == text
    assert record["arm"] == "candidate"
    assert record["prompt_version"] == "1.1.0"


# --- the report -------------------------------------------------------------


def test_a_synthetic_run_says_so_on_the_first_line(tmp_path):
    _, outcome = run(tmp_path)
    report = WindowStore(outcome.directory).report_path.read_text(encoding="utf-8")
    assert report.splitlines()[0].startswith("SYNTHETIC")


def test_a_non_synthetic_run_does_not_claim_to_be_one(tmp_path):
    _, outcome = run(tmp_path, synthetic=False)
    report = WindowStore(outcome.directory).report_path.read_text(encoding="utf-8")
    assert not report.splitlines()[0].startswith("SYNTHETIC")


def test_an_unredacted_run_says_so_on_a_banner_line(tmp_path):
    _, outcome = run(
        tmp_path,
        substitutions=[("redact = true", "redact = false")],
        allow_unredacted=True,
        synthetic=False,
    )
    report = WindowStore(outcome.directory).report_path.read_text(encoding="utf-8")
    assert report.splitlines()[0].startswith("UNREDACTED")


def test_the_report_names_the_error_types_and_their_counts(tmp_path):
    _, outcome = run(tmp_path)
    report = WindowStore(outcome.directory).report_path.read_text(encoding="utf-8")
    assert "LineParseError" in report
    assert "RecordError" in report


def test_the_report_never_quotes_a_record(tmp_path):
    _, outcome = run(tmp_path)
    report = WindowStore(outcome.directory).report_path.read_text(encoding="utf-8")
    assert "Lumen" not in report
    assert "[EMAIL_1]" not in report


def test_the_report_carries_the_source_hash(tmp_path):
    _, outcome = run(tmp_path)
    report = WindowStore(outcome.directory).report_path.read_text(encoding="utf-8")
    assert outcome.manifest.sources[0].sha256[:12] in report


def test_a_truncated_field_is_counted(tmp_path):
    _, outcome = run(tmp_path, substitutions=[("max_text_chars = 20000", "max_text_chars = 40")])
    assert outcome.manifest.counts.truncated > 0
