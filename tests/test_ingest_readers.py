"""Reading a file line by line, and never losing one silently.

Every line of the source ends up in exactly one of three buckets — a row, a
blank, or a failure — and the counts of the three add up to the number of lines
in the file. That is the property the whole per-line error report rests on.
"""

import pytest

from conftest import write_jsonl, write_lines
from loghog.errors import SourceFormatError
from loghog.ingest.readers import SOURCE_FORMATS, read_source, source_sha256


def read(path, source_format="jsonl"):
    return list(read_source(path, source_format))


def test_the_supported_formats_are_the_documented_two():
    assert SOURCE_FORMATS == ("jsonl", "csv")


def test_an_unsupported_format_is_refused_before_the_file_is_opened(tmp_path):
    with pytest.raises(SourceFormatError, match="parquet"):
        read(tmp_path / "nothing.parquet", "parquet")


def test_a_missing_file_is_a_source_error_naming_the_path(tmp_path):
    with pytest.raises(SourceFormatError, match="ghost.jsonl"):
        read(tmp_path / "ghost.jsonl")


# --- jsonl ------------------------------------------------------------------


def test_every_object_becomes_a_row(tmp_path):
    path = write_jsonl(tmp_path / "log.jsonl", [{"a": 1}, {"a": 2}])
    lines = read(path)
    assert [line.payload for line in lines] == [{"a": 1}, {"a": 2}]


def test_line_numbers_start_at_one(tmp_path):
    path = write_jsonl(tmp_path / "log.jsonl", [{"a": 1}, {"a": 2}])
    assert [line.line_no for line in read(path)] == [1, 2]


def test_a_blank_line_is_counted_as_blank_not_as_a_failure(tmp_path):
    path = write_lines(tmp_path / "log.jsonl", '{"a": 1}\n\n{"a": 2}\n')
    lines = read(path)
    assert [line.blank for line in lines] == [False, True, False]
    assert all(line.failure is None for line in lines)


def test_a_line_of_broken_json_is_a_failure_and_the_run_continues(tmp_path):
    path = write_lines(tmp_path / "log.jsonl", '{"a": 1}\n{not json}\n{"a": 3}\n')
    lines = read(path)
    assert lines[1].failure is not None
    assert lines[1].failure.line_no == 2
    assert lines[2].payload == {"a": 3}


def test_a_json_line_that_is_not_an_object_is_a_failure(tmp_path):
    # A bare list or number is valid JSON and is not a log record.
    path = write_lines(tmp_path / "log.jsonl", "[1, 2, 3]\n")
    assert read(path)[0].failure.error_type == "LineParseError"


def test_the_failure_detail_does_not_quote_the_line(tmp_path):
    # A per-line error report is a file people paste into tickets. Quoting the
    # line would put the customer's text in it.
    path = write_lines(tmp_path / "log.jsonl", '{"email": "sam@example.com"\n')
    assert "sam@example.com" not in read(path)[0].failure.detail


def test_every_line_is_accounted_for(tmp_path):
    path = write_lines(tmp_path / "log.jsonl", '{"a": 1}\n\nbroken\n{"a": 2}\n')
    lines = read(path)
    assert len(lines) == 4
    rows = [line for line in lines if line.payload is not None]
    blanks = [line for line in lines if line.blank]
    failures = [line for line in lines if line.failure is not None]
    assert len(rows) + len(blanks) + len(failures) == 4


def test_a_file_with_no_trailing_newline_still_yields_its_last_line(tmp_path):
    path = write_lines(tmp_path / "log.jsonl", '{"a": 1}\n{"a": 2}')
    assert len(read(path)) == 2


def test_a_utf8_bom_does_not_break_the_first_line(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('﻿{"a": 1}\n', encoding="utf-8")
    assert read(path)[0].payload == {"a": 1}


def test_an_empty_file_yields_nothing_rather_than_failing(tmp_path):
    assert read(write_lines(tmp_path / "log.jsonl", "")) == []


# --- csv --------------------------------------------------------------------


def test_a_csv_becomes_rows_keyed_by_header(tmp_path):
    path = write_lines(tmp_path / "log.csv", "id,prompt\n1,hello\n2,there\n")
    lines = read(path, "csv")
    assert [line.payload for line in lines] == [
        {"id": "1", "prompt": "hello"},
        {"id": "2", "prompt": "there"},
    ]


def test_a_csv_with_no_header_at_all_is_refused(tmp_path):
    with pytest.raises(SourceFormatError, match="header"):
        read(write_lines(tmp_path / "log.csv", ""), "csv")


def test_a_csv_row_with_more_cells_than_the_header_is_a_failure(tmp_path):
    path = write_lines(tmp_path / "log.csv", "id,prompt\n1,hello,extra\n")
    assert read(path, "csv")[0].failure is not None


def test_a_csv_row_with_fewer_cells_leaves_the_rest_absent(tmp_path):
    path = write_lines(tmp_path / "log.csv", "id,prompt,arm\n1,hello\n")
    assert read(path, "csv")[0].payload["arm"] is None


def test_a_quoted_newline_inside_a_cell_stays_in_the_cell(tmp_path):
    path = write_lines(tmp_path / "log.csv", 'id,prompt\n1,"two\nlines"\n')
    lines = read(path, "csv")
    assert len(lines) == 1
    assert lines[0].payload["prompt"] == "two\nlines"


def test_a_csv_with_a_duplicate_header_column_is_refused(tmp_path):
    # DictReader silently keeps the last one, which would drop a column without
    # saying so.
    with pytest.raises(SourceFormatError, match="duplicate"):
        read(write_lines(tmp_path / "log.csv", "id,id\n1,2\n"), "csv")


def test_a_csv_with_a_blank_header_cell_is_refused(tmp_path):
    with pytest.raises(SourceFormatError, match="blank"):
        read(write_lines(tmp_path / "log.csv", "id,,arm\n1,2,3\n"), "csv")


# --- hashing ----------------------------------------------------------------


def test_the_source_hash_is_a_sha256_of_the_bytes(tmp_path):
    path = write_lines(tmp_path / "log.jsonl", '{"a": 1}\n')
    digest = source_sha256(path)
    assert len(digest) == 64
    assert digest == source_sha256(path)


def test_two_different_files_hash_differently(tmp_path):
    one = write_lines(tmp_path / "a.jsonl", '{"a": 1}\n')
    two = write_lines(tmp_path / "b.jsonl", '{"a": 2}\n')
    assert source_sha256(one) != source_sha256(two)
