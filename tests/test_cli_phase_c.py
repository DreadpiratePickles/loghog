"""The four Phase C commands from a shell, exit codes included.

    label   1  some candidate's draft could not be read
    label   2  none of them could
    emit    1  a labelled candidate had no criteria and was left out
    emit    2  there was nothing to emit
    health  0  always, when a report was written — see the note below

`health` has no unhealthy exit code on purpose. The threshold at which a dataset
becomes unhealthy is a decision this stage does not make, and putting one in an
exit code would make it — quietly, in a constant, for everybody.
"""

import json

import pytest

from conftest import SAMPLES_DIR, write_config
from loghog.cli import main

SAMPLE = SAMPLES_DIR / "support_chat.synthetic.jsonl"

GOLDENS = """\
- id: flickering_lamp
  tags: [hardware]
  input: The desk lamp flickers whenever the brightness is above about half.
  criteria:
    - names the flickering
"""


def cli(tmp_path, *args):
    return main([*args, "--config", str(tmp_path / "loghog.toml")])


def shortlisted(tmp_path):
    """A window ingested from the committed sample, scored, clustered, selected."""
    write_config(tmp_path)
    cli(
        tmp_path, "ingest", "--input", str(SAMPLE), "--format", "jsonl",
        "--mapping", "openai_chat_jsonl", "--window", "demo", "--synthetic",
    )
    cli(tmp_path, "score", "--window", "demo")
    cli(tmp_path, "cluster", "--window", "demo")
    cli(tmp_path, "select", "--window", "demo")


def labelled(tmp_path):
    shortlisted(tmp_path)
    return cli(tmp_path, "label", "--window", "demo", "--dry-run")


# --- label ------------------------------------------------------------------


def test_a_dry_run_labels_every_candidate_and_says_synthetic_first(tmp_path, capsys):
    shortlisted(tmp_path)
    assert cli(tmp_path, "label", "--window", "demo", "--dry-run") == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("SYNTHETIC")
    assert "call(s)" in out
    labels = tmp_path / "selected" / "demo" / "labels.jsonl"
    rows = [json.loads(line) for line in labels.read_text().splitlines() if line]
    assert rows and all(row["dry_run"] for row in rows)
    assert all(row["criteria"] for row in rows)


def test_a_dry_run_never_asks_for_a_key(tmp_path, monkeypatch):
    """Asserted by removing the variable a live run would need."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    shortlisted(tmp_path)
    assert cli(tmp_path, "label", "--window", "demo", "--dry-run") == 0


def test_an_unselected_window_names_the_command_that_fixes_it(tmp_path, capsys):
    write_config(tmp_path)
    assert cli(tmp_path, "label", "--window", "nope", "--dry-run") == 3
    assert "loghog select" in capsys.readouterr().err


def test_a_live_run_without_a_key_is_refused_and_never_prints_one(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setattr(
        "loghog.cli_label.gemini_provider_from_env",
        _raise_config_error,
    )
    shortlisted(tmp_path)
    assert cli(tmp_path, "label", "--window", "demo") == 3
    err = capsys.readouterr().err
    assert "GEMINI_API_KEY" in err
    assert "Traceback" not in err


def _raise_config_error(model_id):
    from regression_detect.providers.base import ProviderConfigError

    raise ProviderConfigError(
        "GEMINI_API_KEY is not set. Create a .env file in the repository root."
    )


def test_the_interval_can_be_overridden_on_the_command_line(tmp_path, capsys):
    shortlisted(tmp_path)
    assert cli(tmp_path, "label", "--window", "demo", "--dry-run", "--min-interval-ms", "0") == 0


def test_a_negative_interval_is_refused(tmp_path, capsys):
    shortlisted(tmp_path)
    assert cli(tmp_path, "label", "--window", "demo", "--dry-run", "--min-interval-ms", "-5") == 3
    assert "min_interval_ms" in capsys.readouterr().err


# --- emit -------------------------------------------------------------------


def test_emit_writes_a_loadable_dataset_and_a_review(tmp_path, capsys):
    labelled(tmp_path)
    assert cli(tmp_path, "emit", "--window", "demo") == 0
    out = capsys.readouterr().out
    assert "candidates-demo.yaml" in out
    assert "review-demo.md" in out
    from regression_detect.goldens import load_goldens

    cases = load_goldens(tmp_path / "goldens" / "candidates-demo.yaml")
    assert cases
    assert all(case.tags[0] == "loghog" for case in cases)


def test_emit_before_label_names_the_command_that_fixes_it(tmp_path, capsys):
    shortlisted(tmp_path)
    assert cli(tmp_path, "emit", "--window", "demo") == 3
    assert "loghog label" in capsys.readouterr().err


# --- promote ----------------------------------------------------------------


def reviewed_candidates(tmp_path):
    """A candidates file whose criteria are not dry-run placeholders.

    `label --dry-run` cannot produce one, and that is the point: `promote`
    refuses the marker. So this stands in for the file a live labelling run
    would have written.
    """
    from loghog.emit.cases import EmitCase, render_cases_yaml

    case = EmitCase(
        case_id="loghog_demo_chat_001",
        record_id="chat-001",
        window="demo",
        input_text="The desk lamp flickers whenever the brightness is above half.",
        output_text="Customer reports a flickering desk lamp.",
        stratum="negative_feedback",
        score=4,
        signals=("negative_feedback",),
        criteria=(
            "States that the lamp flickers.",
            "Names the brightness threshold the customer gave.",
            "Does not invent a model number.",
        ),
        notes="Catches summaries that drop the threshold.",
        model_id="a-model",
        dry_run=False,
    )
    path = tmp_path / "reviewed.yaml"
    path.write_text(render_cases_yaml([case], window="demo", dry_run=False), encoding="utf-8")
    return path


def test_promote_appends_one_named_case_under_a_reviewer(tmp_path, capsys):
    from regression_detect.goldens import load_goldens

    write_config(tmp_path)
    candidates = reviewed_candidates(tmp_path)
    target = tmp_path / "cases.yaml"
    target.write_text(GOLDENS, encoding="utf-8")
    code = cli(
        tmp_path, "promote", "--file", str(candidates), "--ids", "loghog_demo_chat_001",
        "--into", str(target), "--reviewed-by", "Bobby",
    )
    assert code == 0
    ids = [case.id for case in load_goldens(target)]
    assert ids == ["flickering_lamp", "loghog_demo_chat_001"]
    assert "Bobby" in capsys.readouterr().out


def test_promote_refuses_a_dry_run_placeholder_from_a_shell(tmp_path, capsys):
    """The file says "do not promote them", and the tool means it."""
    from regression_detect.goldens import load_goldens

    labelled(tmp_path)
    cli(tmp_path, "emit", "--window", "demo")
    candidates = tmp_path / "goldens" / "candidates-demo.yaml"
    first = load_goldens(candidates)[0].id
    target = tmp_path / "cases.yaml"
    target.write_text(GOLDENS, encoding="utf-8")
    before = target.read_text(encoding="utf-8")
    code = cli(
        tmp_path, "promote", "--file", str(candidates), "--ids", first,
        "--into", str(target), "--reviewed-by", "Bobby",
    )
    assert code == 3
    assert "[SYNTHETIC]" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == before


def test_promote_refuses_without_a_reviewer(tmp_path):
    write_config(tmp_path)
    candidates = reviewed_candidates(tmp_path)
    target = tmp_path / "cases.yaml"
    target.write_text(GOLDENS, encoding="utf-8")
    with pytest.raises(SystemExit):
        cli(
            tmp_path, "promote", "--file", str(candidates), "--ids", "anything",
            "--into", str(target),
        )


def test_promote_refuses_an_unknown_id_and_writes_nothing(tmp_path, capsys):
    write_config(tmp_path)
    candidates = reviewed_candidates(tmp_path)
    target = tmp_path / "cases.yaml"
    target.write_text(GOLDENS, encoding="utf-8")
    before = target.read_text(encoding="utf-8")
    code = cli(
        tmp_path, "promote", "--file", str(candidates), "--ids", "not_a_case",
        "--into", str(target), "--reviewed-by", "Bobby",
    )
    assert code == 3
    assert target.read_text(encoding="utf-8") == before
    assert "not_a_case" in capsys.readouterr().err


def test_promote_refuses_a_case_the_target_already_holds(tmp_path, capsys):
    write_config(tmp_path)
    candidates = reviewed_candidates(tmp_path)
    target = tmp_path / "cases.yaml"
    target.write_text(GOLDENS, encoding="utf-8")
    common = (
        "promote", "--file", str(candidates), "--ids", "loghog_demo_chat_001",
        "--into", str(target), "--reviewed-by", "Bobby",
    )
    assert cli(tmp_path, *common) == 0
    assert cli(tmp_path, *common) == 3
    assert "stable for ever" in capsys.readouterr().err


# --- health -----------------------------------------------------------------


def test_health_writes_both_files_and_reports_coverage(tmp_path, capsys):
    shortlisted(tmp_path)
    goldens = tmp_path / "cases.yaml"
    goldens.write_text(GOLDENS, encoding="utf-8")
    assert cli(tmp_path, "health", "--window", "demo", "--goldens", str(goldens)) == 0
    out = capsys.readouterr().out
    assert "coverage" in out.lower()
    assert (tmp_path / "health" / "demo.md").is_file()
    payload = json.loads((tmp_path / "health" / "demo.json").read_text())
    assert payload["window"] == "demo"


def test_health_on_a_goldens_file_that_will_not_load_is_refused(tmp_path, capsys):
    shortlisted(tmp_path)
    broken = tmp_path / "broken.yaml"
    broken.write_text("not: a list\n", encoding="utf-8")
    assert cli(tmp_path, "health", "--window", "demo", "--goldens", str(broken)) == 3
    assert "golden dataset" in capsys.readouterr().err.lower()


def test_health_before_cluster_names_the_command_that_fixes_it(tmp_path, capsys):
    write_config(tmp_path)
    cli(
        tmp_path, "ingest", "--input", str(SAMPLE), "--format", "jsonl",
        "--mapping", "openai_chat_jsonl", "--window", "demo", "--synthetic",
    )
    goldens = tmp_path / "cases.yaml"
    goldens.write_text(GOLDENS, encoding="utf-8")
    assert cli(tmp_path, "health", "--window", "demo", "--goldens", str(goldens)) == 3
    assert "loghog" in capsys.readouterr().err


# --- the help ---------------------------------------------------------------


def test_every_phase_c_command_is_in_the_help(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for command in ("label", "emit", "promote", "health"):
        assert command in out
