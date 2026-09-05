"""The command line's corners: broken configuration, missing files, no subcommand.

Every one of these paths exists to turn an exception into a sentence somebody
can act on. A traceback is a fact about this program's call stack; an operator
needs a fact about their file.
"""

from conftest import SAMPLES_DIR, write_config
from loghog.cli import main
from loghog.cli_common import EXIT_CANNOT_RUN, render_class_counts
from loghog.window.store import WindowStore

SAMPLE = SAMPLES_DIR / "support_chat.synthetic.jsonl"


def test_class_counts_with_nothing_in_them_say_so():
    assert render_class_counts({}) == ["  (nothing)"]


def test_redact_with_a_broken_configuration_exits_three(tmp_path, capsys):
    assert main(["redact", "--text", "a", "--config", str(tmp_path / "nope.toml")]) == (
        EXIT_CANNOT_RUN
    )


def test_redact_on_a_file_that_is_not_there_exits_three(tmp_path, capsys):
    code = main(
        ["redact", "--input", str(tmp_path / "ghost.txt"), "--config", str(write_config(tmp_path))]
    )
    assert code == EXIT_CANNOT_RUN
    assert "ghost.txt" in capsys.readouterr().err


def test_window_show_with_a_broken_configuration_exits_three(tmp_path):
    assert main(["window", "show", "--window", "d", "--config", str(tmp_path / "n.toml")]) == (
        EXIT_CANNOT_RUN
    )


def test_window_list_with_a_broken_configuration_exits_three(tmp_path):
    assert main(["window", "list", "--config", str(tmp_path / "n.toml")]) == EXIT_CANNOT_RUN


def test_window_list_ignores_a_directory_that_is_not_a_window(tmp_path, capsys):
    config = write_config(tmp_path)
    (tmp_path / "records" / "not-a-window").mkdir(parents=True)
    main(["window", "list", "--config", str(config)])
    assert "no windows" in capsys.readouterr().out.lower()


def test_mappings_list_with_a_broken_configuration_exits_three(tmp_path):
    assert main(["mappings", "list", "--config", str(tmp_path / "n.toml")]) == EXIT_CANNOT_RUN


def test_mappings_list_says_when_a_built_in_is_missing(tmp_path, capsys):
    config = write_config(tmp_path)
    (tmp_path / "mappings" / "prompton_events.toml").unlink()
    main(["mappings", "list", "--config", str(config)])
    assert "missing" in capsys.readouterr().out.lower()


def test_the_window_command_with_no_subcommand_prints_usage(tmp_path, capsys):
    assert main(["window"]) == EXIT_CANNOT_RUN
    assert "usage" in capsys.readouterr().err.lower()


def test_the_mappings_command_with_no_subcommand_prints_usage(tmp_path, capsys):
    assert main(["mappings"]) == EXIT_CANNOT_RUN
    assert "usage" in capsys.readouterr().err.lower()


def test_a_truncation_is_reported_on_the_command_line(tmp_path, capsys):
    config = write_config(tmp_path, [("max_text_chars = 20000", "max_text_chars = 40")])
    main(
        ["ingest", "--input", str(SAMPLE), "--format", "jsonl", "--mapping",
         "openai_chat_jsonl", "--window", "demo", "--config", str(config), "--synthetic"]
    )
    assert "truncated" in capsys.readouterr().out.lower()


def test_the_store_reports_the_window_it_is_looking_at(tmp_path):
    store = WindowStore(tmp_path / "records" / "demo")
    assert store.directory.name == "demo"
    assert store.exists is False
