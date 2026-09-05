"""The derived artefacts: replaced rather than appended, and refused rather than skipped.

Two rules, and both are the opposite of what `store` does for records.

**Replaced, not appended.** Records are evidence and nothing rewrites them.
Scores and clusters are *derived*, and re-scoring a window with different
weights must leave a file describing that window rather than two files stapled
together.

**Refused, not skipped.** A scores file with one unreadable line is not a
ranking over nine records; it is a ranking over a window nobody can name. Half
an answer to a question about coverage is worse than no answer, because it looks
like an answer.
"""

import json

import pytest

from conftest import load_test_config, make_record
from conftest import write_jsonl as fixture_jsonl
from loghog.errors import ScoreError, SelectionError
from loghog.window.artifacts import (
    read_clusters,
    read_jsonl,
    read_scores,
    read_signals,
    write_json,
    write_jsonl,
    write_text,
)
from loghog.window.store import WindowStore


def store_at(tmp_path) -> WindowStore:
    return WindowStore(tmp_path / "records" / "w")


def test_writing_a_json_document_creates_the_directory_at_0700(tmp_path):
    store = store_at(tmp_path)
    write_json(store.clusters_path, {"clusters": []})
    assert store.directory.stat().st_mode & 0o777 == 0o700
    assert store.clusters_path.stat().st_mode & 0o777 == 0o600


def test_writing_a_json_document_leaves_no_temporary_behind(tmp_path):
    store = store_at(tmp_path)
    write_json(store.clusters_path, {"clusters": []})
    assert sorted(path.name for path in store.directory.iterdir()) == ["clusters.json"]


def test_writing_jsonl_replaces_rather_than_appends(tmp_path):
    store = store_at(tmp_path)
    write_jsonl(store.scores_path, [{"a": 1}, {"a": 2}])
    write_jsonl(store.scores_path, [{"a": 3}])
    assert store.scores_path.read_text(encoding="utf-8") == '{"a": 3}\n'


def test_writing_no_rows_leaves_an_empty_file_rather_than_a_blank_line(tmp_path):
    store = store_at(tmp_path)
    write_jsonl(store.scores_path, [])
    assert store.scores_path.read_text(encoding="utf-8") == ""


def test_writing_text_replaces_an_earlier_report(tmp_path):
    store = store_at(tmp_path)
    write_text(store.score_report_path, "first")
    write_text(store.score_report_path, "second")
    assert store.score_report_path.read_text(encoding="utf-8") == "second"


def test_reading_a_file_that_is_not_there_is_refused_by_name(tmp_path):
    with pytest.raises(ScoreError, match="scores file"):
        read_jsonl(tmp_path / "nope.jsonl", what="scores file")


def test_a_blank_line_in_a_jsonl_file_is_skipped(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('{"a": 1}\n\n{"a": 2}\n', encoding="utf-8")
    assert read_jsonl(path, what="rows") == [{"a": 1}, {"a": 2}]


def test_an_unreadable_line_names_its_number(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('{"a": 1}\nnot json\n', encoding="utf-8")
    with pytest.raises(ScoreError, match="line 2"):
        read_jsonl(path, what="rows")


def test_a_line_that_is_not_an_object_is_refused(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(ScoreError, match="not a JSON object"):
        read_jsonl(path, what="rows")


def test_reading_scores_from_an_unscored_window_names_the_command(tmp_path):
    with pytest.raises(ScoreError, match="loghog score"):
        read_scores(store_at(tmp_path))


def test_a_score_that_is_not_an_integer_is_refused(tmp_path):
    store = store_at(tmp_path)
    write_jsonl(store.scores_path, [{"record_id": "a", "score": "high", "signals": []}])
    with pytest.raises(ScoreError, match="not a score"):
        read_scores(store)


def test_a_boolean_score_is_refused_because_true_is_not_one(tmp_path):
    store = store_at(tmp_path)
    write_jsonl(store.scores_path, [{"record_id": "a", "score": True, "signals": []}])
    with pytest.raises(ScoreError, match="not a score"):
        read_scores(store)


def test_signals_read_back_in_the_order_they_were_written(tmp_path):
    store = store_at(tmp_path)
    write_jsonl(
        store.scores_path,
        [
            {
                "record_id": "a",
                "score": 9,
                "signals": [{"name": "error", "weight": 4}, {"name": "tiny_input", "weight": 1}],
            }
        ],
    )
    assert read_signals(store) == {"a": ("error", "tiny_input")}


def test_a_score_row_with_no_signals_list_is_refused(tmp_path):
    store = store_at(tmp_path)
    write_jsonl(store.scores_path, [{"record_id": "a", "score": 1}])
    with pytest.raises(ScoreError, match="no signals list"):
        read_signals(store)


def test_reading_clusters_from_an_unclustered_window_names_the_command(tmp_path):
    with pytest.raises(SelectionError, match="loghog cluster"):
        read_clusters(store_at(tmp_path))


def test_an_unreadable_clusters_document_is_refused(tmp_path):
    store = store_at(tmp_path)
    write_text(store.clusters_path, "{not json")
    with pytest.raises(SelectionError, match="not readable JSON"):
        read_clusters(store)


def test_a_clusters_document_without_clusters_is_refused(tmp_path):
    store = store_at(tmp_path)
    write_json(store.clusters_path, {"window": "w"})
    with pytest.raises(SelectionError, match="not a clusters document"):
        read_clusters(store)


def test_the_store_reads_no_records_from_a_window_that_has_none(tmp_path):
    assert store_at(tmp_path).read_records() == []


def test_a_written_record_reads_back_as_the_record_it_was(tmp_path):
    store = store_at(tmp_path)
    store.append_records([make_record()], redaction_enabled=True)
    assert [record.record_id for record in store.read_records()] == ["req-001"]


def test_a_corrupt_record_line_stops_the_read_rather_than_being_skipped(tmp_path):
    store = store_at(tmp_path)
    store.append_records([make_record()], redaction_enabled=True)
    with store.records_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"record_id": "broken"}) + "\n")
    with pytest.raises(Exception, match="missing key"):
        store.read_records()


def test_the_committed_configuration_is_what_these_helpers_run_under(tmp_path):
    # A guard on the fixture rather than on the code: every test above uses the
    # real window layout, and this is what says so out loud.
    config = load_test_config(tmp_path)
    assert config.records_dir.name == "records"
    assert fixture_jsonl(tmp_path / "x.jsonl", [{"a": 1}]).is_file()
