"""The command line: exit codes, refusals, and what gets printed.

The exit codes are the contract. A run that rejected two thousand lines and
returned 0 is worse than one that crashed, because nobody reads the report of a
command that succeeded.
"""

import json

import pytest

from conftest import SAMPLES_DIR, write_config, write_lines
from loghog.cli import EXIT_CANNOT_RUN, main
from loghog.ingest.run import EXIT_NOTHING, EXIT_OK, EXIT_PARTIAL

SAMPLE = SAMPLES_DIR / "support_chat.synthetic.jsonl"
SAMPLE_CSV = SAMPLES_DIR / "support_tickets.synthetic.csv"
CSV_MAPPING = SAMPLES_DIR / "support_csv.toml"


def ingest_args(tmp_path, *extra, source=SAMPLE, mapping="openai_chat_jsonl", fmt="jsonl"):
    return [
        "ingest",
        "--input",
        str(source),
        "--format",
        fmt,
        "--mapping",
        mapping,
        "--window",
        "demo",
        "--config",
        str(write_config(tmp_path)),
        *extra,
    ]


def test_no_arguments_prints_usage_and_does_not_crash(capsys):
    assert main([]) == EXIT_CANNOT_RUN
    assert "usage" in capsys.readouterr().out.lower()


def test_an_unknown_command_is_refused(capsys):
    with pytest.raises(SystemExit):
        main(["frobnicate"])


# --- ingest -----------------------------------------------------------------


def test_ingesting_the_sample_exits_one_because_two_lines_are_broken(tmp_path, capsys):
    assert main(ingest_args(tmp_path, "--synthetic")) == EXIT_PARTIAL
    out = capsys.readouterr().out
    assert "record(s) written" in out.lower()


def test_the_clean_csv_sample_exits_zero(tmp_path):
    code = main(
        ingest_args(tmp_path, source=SAMPLE_CSV, mapping=str(CSV_MAPPING), fmt="csv")
    )
    assert code == EXIT_OK


def test_the_output_names_the_window_directory(tmp_path, capsys):
    main(ingest_args(tmp_path, "--synthetic"))
    assert str(tmp_path / "records" / "demo") in capsys.readouterr().out


def test_the_output_reports_the_redaction_counts(tmp_path, capsys):
    main(ingest_args(tmp_path, "--synthetic"))
    out = capsys.readouterr().out
    assert "EMAIL" in out and "CARD" in out


def test_the_output_never_quotes_a_record(tmp_path, capsys):
    main(ingest_args(tmp_path, "--synthetic"))
    assert "Lumen" not in capsys.readouterr().out


def test_a_synthetic_run_says_so_on_its_first_line_of_output(tmp_path, capsys):
    main(ingest_args(tmp_path, "--synthetic"))
    assert capsys.readouterr().out.splitlines()[0].startswith("SYNTHETIC")


def test_a_file_of_junk_exits_two(tmp_path, capsys):
    junk = write_lines(tmp_path / "junk.jsonl", "not json\n")
    assert main(ingest_args(tmp_path, source=junk)) == EXIT_NOTHING
    assert "nothing was written" in capsys.readouterr().out.lower()


def test_a_missing_input_file_exits_three(tmp_path, capsys):
    code = main(ingest_args(tmp_path, source=tmp_path / "ghost.jsonl"))
    assert code == EXIT_CANNOT_RUN
    assert "ghost.jsonl" in capsys.readouterr().err


def test_a_missing_configuration_exits_three(tmp_path, capsys):
    code = main(
        [
            "ingest",
            "--input",
            str(SAMPLE),
            "--format",
            "jsonl",
            "--mapping",
            "openai_chat_jsonl",
            "--config",
            str(tmp_path / "nope.toml"),
        ]
    )
    assert code == EXIT_CANNOT_RUN
    assert "nope.toml" in capsys.readouterr().err


def test_an_unknown_mapping_exits_three_and_lists_the_built_ins(tmp_path, capsys):
    code = main(ingest_args(tmp_path, mapping="nope"))
    assert code == EXIT_CANNOT_RUN
    assert "openai_chat_jsonl" in capsys.readouterr().err


def test_a_second_run_into_one_window_exits_three(tmp_path, capsys):
    main(ingest_args(tmp_path, "--synthetic"))
    capsys.readouterr()
    assert main(ingest_args(tmp_path, "--synthetic")) == EXIT_CANNOT_RUN
    assert "--append" in capsys.readouterr().err


def test_appending_works_from_the_command_line(tmp_path, capsys):
    main(ingest_args(tmp_path, "--synthetic"))
    code = main(
        ingest_args(
            tmp_path,
            "--append",
            "--synthetic",
            source=SAMPLE_CSV,
            mapping=str(CSV_MAPPING),
            fmt="csv",
        )
    )
    assert code == EXIT_OK
    manifest = json.loads((tmp_path / "records" / "demo" / "manifest.json").read_text())
    assert len(manifest["sources"]) == 2


def test_the_window_defaults_to_todays_utc_date(tmp_path, capsys):
    args = [arg for arg in ingest_args(tmp_path, "--synthetic") if arg not in ("--window", "demo")]
    assert main(args) == EXIT_PARTIAL
    windows = [path.name for path in (tmp_path / "records").iterdir()]
    assert len(windows) == 1
    assert windows[0].count("-") == 2


def test_the_default_config_is_looked_for_beside_the_working_directory(tmp_path, monkeypatch):
    write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    code = main(
        ["ingest", "--input", str(SAMPLE), "--format", "jsonl",
         "--mapping", "openai_chat_jsonl", "--window", "demo", "--synthetic"]
    )
    assert code == EXIT_PARTIAL


def test_redaction_off_without_the_flag_exits_three(tmp_path, capsys):
    config = write_config(tmp_path, [("redact = true", "redact = false")])
    code = main(
        ["ingest", "--input", str(SAMPLE), "--format", "jsonl",
         "--mapping", "openai_chat_jsonl", "--window", "demo", "--config", str(config)]
    )
    assert code == EXIT_CANNOT_RUN
    assert "allow-unredacted" in capsys.readouterr().err


def test_the_sidecar_option_is_wired_through(tmp_path, capsys):
    code = main(ingest_args(tmp_path, mapping="regress_rollout_events"))
    assert code == EXIT_CANNOT_RUN
    assert "--sidecar" in capsys.readouterr().err


# --- redact -----------------------------------------------------------------


def test_redact_prints_the_redacted_text(tmp_path, capsys):
    code = main(["redact", "--text", "write to sam@example.com", "--config",
                 str(write_config(tmp_path))])
    assert code == EXIT_OK
    assert "[EMAIL_1]" in capsys.readouterr().out


def test_redact_reports_what_it_found(tmp_path, capsys):
    main(["redact", "--text", "sam@example.com and 10.0.0.1", "--config",
          str(write_config(tmp_path))])
    out = capsys.readouterr().out
    assert "EMAIL" in out and "IPV4" in out


def test_redact_honours_the_configured_allowlist(tmp_path, capsys):
    main(["redact", "--text", "we stock Dr Pepper", "--config", str(write_config(tmp_path))])
    assert "Dr Pepper" in capsys.readouterr().out


def test_redact_reads_a_file(tmp_path, capsys):
    path = write_lines(tmp_path / "note.txt", "call +44 20 7946 0958\n")
    main(["redact", "--input", str(path), "--config", str(write_config(tmp_path))])
    assert "[PHONE_1]" in capsys.readouterr().out


def test_redact_needs_one_of_text_or_input(tmp_path, capsys):
    assert main(["redact", "--config", str(write_config(tmp_path))]) == EXIT_CANNOT_RUN
    assert "--text" in capsys.readouterr().err


def test_redact_says_when_it_found_nothing(tmp_path, capsys):
    main(["redact", "--text", "the lamp flickers", "--config", str(write_config(tmp_path))])
    assert "nothing" in capsys.readouterr().out.lower()


# --- window show ------------------------------------------------------------


def test_window_show_prints_the_manifest_summary(tmp_path, capsys):
    main(ingest_args(tmp_path, "--synthetic"))
    capsys.readouterr()
    code = main(["window", "show", "--window", "demo", "--config", str(write_config(tmp_path))])
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "demo" in out
    assert "record(s) written" in out.lower()


def test_window_show_on_a_window_that_is_not_there_exits_three(tmp_path, capsys):
    code = main(["window", "show", "--window", "ghost", "--config", str(write_config(tmp_path))])
    assert code == EXIT_CANNOT_RUN


def test_window_show_flags_a_synthetic_window_on_its_first_line(tmp_path, capsys):
    main(ingest_args(tmp_path, "--synthetic"))
    capsys.readouterr()
    main(["window", "show", "--window", "demo", "--config", str(write_config(tmp_path))])
    assert capsys.readouterr().out.splitlines()[0].startswith("SYNTHETIC")


def test_window_list_names_every_window(tmp_path, capsys):
    main(ingest_args(tmp_path, "--synthetic"))
    capsys.readouterr()
    assert main(["window", "list", "--config", str(write_config(tmp_path))]) == EXIT_OK
    assert "demo" in capsys.readouterr().out


def test_window_list_with_no_windows_says_so(tmp_path, capsys):
    assert main(["window", "list", "--config", str(write_config(tmp_path))]) == EXIT_OK
    assert "no windows" in capsys.readouterr().out.lower()


# --- mappings ---------------------------------------------------------------


def test_mappings_list_names_the_three_built_ins(tmp_path, capsys):
    assert main(["mappings", "list", "--config", str(write_config(tmp_path))]) == EXIT_OK
    out = capsys.readouterr().out
    for name in ("openai_chat_jsonl", "prompton_events", "regress_rollout_events"):
        assert name in out


def test_mappings_list_shows_each_description(tmp_path, capsys):
    main(["mappings", "list", "--config", str(write_config(tmp_path))])
    assert "sidecar" in capsys.readouterr().out.lower()
