"""The four Phase B commands from the command line, exit codes included.

The exit codes are the contract, and Phase B adds one meaning to code 1 and one
to code 2:

    score   1  a signal could not be evaluated because of how the window is built
    select  1  the global cap truncated the shortlist; there was more worth having
    select  2  nothing was chosen, which is not a shortlist

An absence somebody *chose* — no goldens file, a window too small for a
percentile — stays 0, because a code that was 1 on every run would stop meaning
anything.
"""

import json

import pytest

from conftest import SAMPLES_DIR, write_config, write_jsonl
from loghog.cli import main

SAMPLE = SAMPLES_DIR / "support_chat.synthetic.jsonl"

GOLDENS = """
- id: flickering_lamp
  tags: [hardware]
  input: The desk lamp flickers whenever the brightness is above about half.
  criteria:
    - names the flickering
"""


def cli(tmp_path, *args):
    return main([*args, "--config", str(tmp_path / "loghog.toml")])


def ingested(tmp_path, *, window="demo", source=SAMPLE, fmt="jsonl", mapping="openai_chat_jsonl"):
    write_config(tmp_path)
    return cli(
        tmp_path, "ingest", "--input", str(source), "--format", fmt,
        "--mapping", mapping, "--window", window, "--synthetic",
    )


def test_score_from_the_command_line_writes_the_files(tmp_path, capsys):
    ingested(tmp_path)
    code = cli(tmp_path, "score", "--window", "demo")
    assert (tmp_path / "records" / "demo" / "scores.jsonl").is_file()
    assert (tmp_path / "records" / "demo" / "score.md").is_file()
    assert code == 1  # the committed config deduplicates; see the report
    assert "version_disagreement" in capsys.readouterr().out


def test_score_prints_the_banner_of_a_synthetic_window_first(tmp_path, capsys):
    ingested(tmp_path)
    cli(tmp_path, "score", "--window", "demo")
    assert capsys.readouterr().out.splitlines()[0].startswith("SYNTHETIC")


def test_score_without_impediments_exits_zero(tmp_path):
    write_config(tmp_path, [("dedupe = true", "dedupe = false")])
    cli(
        tmp_path, "ingest", "--input", str(SAMPLE), "--format", "jsonl",
        "--mapping", "openai_chat_jsonl", "--window", "demo", "--synthetic",
    )
    assert cli(tmp_path, "score", "--window", "demo") == 0


def test_score_of_a_window_that_does_not_exist_exits_three(tmp_path, capsys):
    write_config(tmp_path)
    assert cli(tmp_path, "score", "--window", "nope") == 3
    assert "loghog ingest" in capsys.readouterr().err


def test_score_with_existing_goldens_uses_project_ones_loader(tmp_path, capsys):
    ingested(tmp_path)
    goldens = tmp_path / "goldens.yaml"
    goldens.write_text(GOLDENS, encoding="utf-8")
    cli(tmp_path, "score", "--window", "demo", "--existing", str(goldens))
    assert "novelty" in capsys.readouterr().out


def test_a_goldens_file_that_will_not_load_is_refused_by_project_ones_error(tmp_path, capsys):
    ingested(tmp_path)
    broken = tmp_path / "broken.yaml"
    broken.write_text("- id: no_criteria\n  tags: []\n  input: hi\n", encoding="utf-8")
    assert cli(tmp_path, "score", "--window", "demo", "--existing", str(broken)) == 3
    assert "broken.yaml" in capsys.readouterr().err


def test_cluster_from_the_command_line(tmp_path, capsys):
    ingested(tmp_path)
    cli(tmp_path, "score", "--window", "demo")
    assert cli(tmp_path, "cluster", "--window", "demo") == 0
    assert (tmp_path / "records" / "demo" / "clusters.json").is_file()
    assert "cluster(s)" in capsys.readouterr().out


def test_cluster_before_score_exits_three_naming_the_command(tmp_path, capsys):
    ingested(tmp_path)
    assert cli(tmp_path, "cluster", "--window", "demo") == 3
    assert "loghog score" in capsys.readouterr().err


def test_select_from_the_command_line_writes_the_shortlist(tmp_path, capsys):
    _prepare(tmp_path)
    code = cli(tmp_path, "select", "--window", "demo")
    path = tmp_path / "selected" / "demo" / "candidates.jsonl"
    assert path.is_file()
    assert (tmp_path / "selected" / "demo" / "selection.md").is_file()
    assert code == 0
    assert "candidate(s)" in capsys.readouterr().out


def test_select_with_a_cap_of_one_truncates_and_exits_one(tmp_path, capsys):
    _prepare(tmp_path)
    assert cli(tmp_path, "select", "--window", "demo", "--max-candidates", "1") == 1
    out = capsys.readouterr().out
    assert "max_candidates" in out


def test_select_before_cluster_exits_three(tmp_path, capsys):
    ingested(tmp_path)
    cli(tmp_path, "score", "--window", "demo")
    assert cli(tmp_path, "select", "--window", "demo") == 3
    assert "loghog cluster" in capsys.readouterr().err


def test_select_names_each_cap_on_the_terminal_not_only_in_the_file(tmp_path, capsys):
    _prepare(tmp_path)
    cli(tmp_path, "select", "--window", "demo", "--max-candidates", "2")
    out = capsys.readouterr().out
    assert "dropped" in out


def test_drift_from_the_command_line(tmp_path, capsys):
    _prepare(tmp_path)
    _prepare_second(tmp_path)
    assert cli(tmp_path, "drift", "--from", "demo", "--to", "later") == 0
    payload = json.loads((tmp_path / "drift" / "demo-vs-later.json").read_text(encoding="utf-8"))
    assert payload["earlier"] == "demo"
    assert "new cluster" in capsys.readouterr().out


def test_drift_against_an_unscored_window_exits_three(tmp_path, capsys):
    _prepare(tmp_path)
    write_jsonl(tmp_path / "later.jsonl", _rows())
    cli(
        tmp_path, "ingest", "--input", str(tmp_path / "later.jsonl"), "--format", "jsonl",
        "--mapping", "openai_chat_jsonl", "--window", "later",
    )
    assert cli(tmp_path, "drift", "--from", "demo", "--to", "later") == 3
    assert "loghog score" in capsys.readouterr().err


def test_drift_of_a_window_with_itself_exits_three(tmp_path, capsys):
    _prepare(tmp_path)
    assert cli(tmp_path, "drift", "--from", "demo", "--to", "demo") == 3
    assert "itself" in capsys.readouterr().err


def test_the_help_lists_the_four_new_commands(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for command in ("score", "cluster", "select", "drift"):
        assert command in out


def _prepare(tmp_path):
    ingested(tmp_path)
    cli(tmp_path, "score", "--window", "demo")
    cli(tmp_path, "cluster", "--window", "demo")


def _prepare_second(tmp_path):
    write_jsonl(tmp_path / "later.jsonl", _rows())
    cli(
        tmp_path, "ingest", "--input", str(tmp_path / "later.jsonl"), "--format", "jsonl",
        "--mapping", "openai_chat_jsonl", "--window", "later",
    )
    cli(tmp_path, "score", "--window", "later")
    cli(tmp_path, "cluster", "--window", "later")


def _rows():
    texts = [
        "The subscription renewed although i cancelled it last month entirely",
        "The tracking page has said out for delivery since last Wednesday",
        "The promised discount code is rejected at the checkout every time",
    ]
    return [
        {
            "id": f"later-{index}",
            "created": 1_788_100_000 + index,
            "messages": [
                {"role": "user", "content": text},
                {"role": "assistant", "content": f"A summary of: {text}"},
            ],
            "latency_ms": 300,
        }
        for index, text in enumerate(texts)
    ]
