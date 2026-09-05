"""The manifest: where a window came from, and what happened on the way in.

A window with no manifest is a pile of JSON somebody has to take on trust. The
manifest is what makes it evidence: which files, at which hashes, read under
which mapping, how many lines were rejected and for what, and exactly how much
personal data came out.
"""

import pytest

from loghog.errors import ManifestError
from loghog.window.manifest import (
    MANIFEST_SCHEMA_VERSION,
    IngestCounts,
    Manifest,
    SourceEntry,
    manifest_from_json_dict,
)


def make_source(**overrides) -> SourceEntry:
    fields = {
        "path": "samples/support_chat.synthetic.jsonl",
        "source_format": "jsonl",
        "mapping": "openai_chat_jsonl",
        "mapping_sha256": "a" * 64,
        "sha256": "b" * 64,
        "bytes": 2048,
        "ingested_utc": "2026-09-05T10:00:00Z",
        "redactions": 12,
    }
    fields.update(overrides)
    return SourceEntry(**fields)


def make_counts(**overrides) -> IngestCounts:
    fields = {
        "lines_read": 12,
        "blank_lines": 1,
        "rows": 9,
        "unparsed": 2,
        "invalid": 2,
        "records_written": 6,
        "duplicates_dropped": 1,
        "truncated": 0,
    }
    fields.update(overrides)
    return IngestCounts(**fields)


def make_manifest(**overrides) -> Manifest:
    fields = {
        "window": "2026-09-05",
        "created_utc": "2026-09-05T10:00:00Z",
        "updated_utc": "2026-09-05T10:00:00Z",
        "synthetic": False,
        "sources": (make_source(),),
        "counts": make_counts(),
        "redaction": {"enabled": True, "by_class": {"EMAIL": 12}, "total": 12},
        "errors_by_type": {"MissingFieldError": 2},
        "dedupe_enabled": True,
    }
    fields.update(overrides)
    return Manifest(**fields)


def test_a_manifest_round_trips_through_json():
    manifest = make_manifest()
    assert manifest_from_json_dict(manifest.to_json_dict()) == manifest


def test_the_manifest_declares_its_schema_version():
    assert make_manifest().to_json_dict()["schema_version"] == MANIFEST_SCHEMA_VERSION


def test_a_manifest_from_a_future_schema_is_refused():
    payload = make_manifest().to_json_dict()
    payload["schema_version"] = MANIFEST_SCHEMA_VERSION + 1
    with pytest.raises(ManifestError, match="schema_version"):
        manifest_from_json_dict(payload)


def test_a_manifest_records_the_tool_version_that_wrote_it():
    from loghog import __version__

    assert make_manifest().to_json_dict()["loghog_version"] == __version__


def test_a_manifest_missing_a_key_is_refused():
    payload = make_manifest().to_json_dict()
    del payload["counts"]
    with pytest.raises(ManifestError, match="counts"):
        manifest_from_json_dict(payload)


def test_a_manifest_that_is_not_an_object_is_refused():
    with pytest.raises(ManifestError):
        manifest_from_json_dict([1, 2])


def test_the_counts_have_to_add_up():
    # Every line is a row, a blank or a rejection. If that arithmetic does not
    # hold, a line went missing and the report is a lie.
    with pytest.raises(ManifestError, match="add up"):
        make_manifest(counts=make_counts(lines_read=99))


def test_more_records_than_rows_is_refused():
    with pytest.raises(ManifestError, match="rows"):
        make_manifest(counts=make_counts(records_written=99))


def test_a_stored_rejected_total_is_ignored_rather_than_trusted():
    payload = make_manifest().to_json_dict()
    payload["counts"]["rejected"] = 999
    assert manifest_from_json_dict(payload).counts.rejected == 4


def test_a_negative_count_is_refused():
    with pytest.raises(ManifestError):
        make_counts(invalid=-1)


def test_the_rows_have_to_add_up_too():
    # Every row is a record, a duplicate, or an invalid row.
    with pytest.raises(ManifestError, match="rows do not add up"):
        make_manifest(counts=make_counts(records_written=5))


def test_rejected_is_derived_from_the_two_kinds_of_bad_line():
    assert make_counts().rejected == 4


def test_a_source_with_a_short_hash_is_refused():
    with pytest.raises(ManifestError, match="sha256"):
        make_source(sha256="abc")


def test_a_source_path_that_is_absolute_is_refused():
    # A manifest is committed evidence in spirit even when it is not committed
    # in fact. Somebody's home directory in it helps nobody.
    with pytest.raises(ManifestError, match="absolute"):
        make_source(path="/Users/somebody/logs/a.jsonl")


def test_a_window_with_no_sources_is_refused():
    with pytest.raises(ManifestError, match="source"):
        make_manifest(sources=())


# --- merging on append ------------------------------------------------------


def test_appending_adds_the_new_source():
    merged = make_manifest().merge(
        sources=(make_source(path="second.jsonl"),),
        counts=make_counts(),
        redaction={"enabled": True, "by_class": {"EMAIL": 3}, "total": 3},
        errors_by_type={"MissingFieldError": 1},
        updated_utc="2026-09-05T11:00:00Z",
    )
    assert [source.path for source in merged.sources] == [
        "samples/support_chat.synthetic.jsonl",
        "second.jsonl",
    ]


def test_appending_sums_the_counts():
    merged = make_manifest().merge(
        sources=(make_source(path="second.jsonl"),),
        counts=make_counts(),
        redaction={"enabled": True, "by_class": {}, "total": 0},
        errors_by_type={},
        updated_utc="2026-09-05T11:00:00Z",
    )
    assert merged.counts.records_written == 12
    assert merged.counts.lines_read == 24


def test_appending_sums_the_redaction_classes():
    merged = make_manifest().merge(
        sources=(make_source(path="second.jsonl"),),
        counts=make_counts(),
        redaction={"enabled": True, "by_class": {"EMAIL": 3, "CARD": 1}, "total": 4},
        errors_by_type={},
        updated_utc="2026-09-05T11:00:00Z",
    )
    assert merged.redaction["by_class"] == {"CARD": 1, "EMAIL": 15}
    assert merged.redaction["total"] == 16


def test_appending_an_unredacted_run_makes_the_whole_window_unredacted():
    # The honest reading: a window is only fully redacted if every run into it
    # was. Anything else lets one debugging session quietly launder a flag.
    merged = make_manifest().merge(
        sources=(make_source(path="second.jsonl"),),
        counts=make_counts(),
        redaction={"enabled": False, "by_class": {}, "total": 0},
        errors_by_type={},
        updated_utc="2026-09-05T11:00:00Z",
    )
    assert merged.redaction["enabled"] is False


def test_appending_keeps_the_original_creation_time():
    merged = make_manifest().merge(
        sources=(make_source(path="second.jsonl"),),
        counts=make_counts(),
        redaction={"enabled": True, "by_class": {}, "total": 0},
        errors_by_type={},
        updated_utc="2026-09-05T11:00:00Z",
    )
    assert merged.created_utc == "2026-09-05T10:00:00Z"
    assert merged.updated_utc == "2026-09-05T11:00:00Z"


def test_appending_the_same_source_twice_is_refused():
    # Same path, same hash: the file has already been ingested into this window,
    # and doing it again would double every count for no new records.
    with pytest.raises(ManifestError, match="already"):
        make_manifest().merge(
            sources=(make_source(),),
            counts=make_counts(),
            redaction={"enabled": True, "by_class": {}, "total": 0},
            errors_by_type={},
            updated_utc="2026-09-05T11:00:00Z",
        )


def test_the_same_path_with_different_bytes_may_be_appended():
    # A log file that has grown since the last run is a legitimate second read.
    merged = make_manifest().merge(
        sources=(make_source(sha256="c" * 64),),
        counts=make_counts(),
        redaction={"enabled": True, "by_class": {}, "total": 0},
        errors_by_type={},
        updated_utc="2026-09-05T11:00:00Z",
    )
    assert len(merged.sources) == 2
