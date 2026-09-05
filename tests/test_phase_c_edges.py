"""The paths Phase C only reaches when something has already gone wrong.

Every one of these is a `raise` somebody would otherwise have to take on trust.
They are cheap to test and they are the lines that run on the worst day, which is
the argument for testing them rather than the argument against.
"""

import json

import pytest
import yaml

from conftest import load_test_config
from loghog.emit.cases import (
    EmitCase,
    _block_attempt,
    render_cases_yaml,
    render_mapping_scalar,
)
from loghog.emit.promote import promote, render_promoted_case
from loghog.errors import EmitError, HealthError, LabelError, PromoteError
from loghog.label.draft import (
    DRY_RUN_MODEL_ID,
    SYNTHETIC_MARKER,
    Draft,
    DraftOutcome,
    DraftParseError,
    _strip_one_fence,
    parse_draft,
)
from loghog.label.run import LABELS_NAME, _one_model_id, read_labels
from loghog.label.settings import load_label_settings

CRITERIA = ("States the thing.", "Names the item.", "Does not invent a date.")


def case(**overrides) -> EmitCase:
    fields = {
        "case_id": "loghog_w_r_1",
        "record_id": "r-1",
        "window": "w",
        "input_text": "A complaint about a kettle.",
        "output_text": "A summary.",
        "stratum": "error",
        "score": 4,
        "signals": ("error",),
        "criteria": CRITERIA,
        "notes": "n",
        "model_id": "m",
        "dry_run": False,
    }
    fields.update(overrides)
    return EmitCase(**fields)


# --- the fence tolerance ----------------------------------------------------


def test_a_fence_in_another_language_is_left_alone():
    """A ```python block is not a JSON payload with decoration on it."""
    text = "```python\n{}\n```"
    assert _strip_one_fence(text) == text
    with pytest.raises(DraftParseError):
        parse_draft(text)


def test_an_unclosed_fence_is_left_alone():
    text = "```json\n" + json.dumps({"criteria": list(CRITERIA), "notes": "n"})
    assert _strip_one_fence(text) == text


# --- the rendering verifications --------------------------------------------


def test_a_block_attempt_that_does_not_round_trip_returns_none():
    """The `|` style needs a trailing newline; without one it is refused."""
    assert _block_attempt("input", "no trailing newline", "|") is None


@pytest.mark.parametrize(
    "value",
    [
        "  leading spaces on the first line",
        "a\r\nb",
        "two trailing newlines\n\n",
        " ",
    ],
)
def test_a_value_no_block_style_survives_falls_back_to_a_quoted_scalar(value):
    """The fallback is not decoration: these four genuinely need it.

    A literal block whose first line is indented needs an explicit indentation
    indicator; a carriage return is not a YAML line break; and a block cannot
    express "ends with exactly two newlines". Guessing which of those a
    production input contains is how a mining run mangles the one case that
    mattered, so the rendering is parsed back and compared instead.
    """
    rendered = "\n".join(render_mapping_scalar("input", value, 0))
    assert rendered.startswith('input: "')
    assert yaml.safe_load(rendered) == {"input": value}


def test_a_rendering_that_is_not_yaml_at_all_is_refused(monkeypatch):
    monkeypatch.setattr(
        "loghog.emit.cases.render_case", lambda case: ["- id: [unclosed"]
    )
    with pytest.raises(EmitError, match="not valid YAML"):
        render_cases_yaml([case()], window="w", dry_run=False)


def test_a_rendering_that_loses_a_case_is_refused(monkeypatch):
    monkeypatch.setattr("loghog.emit.cases.render_case", lambda case: ["[]"])
    with pytest.raises(EmitError, match="one case per candidate"):
        render_cases_yaml([case()], window="w", dry_run=False)


def test_a_rendering_that_changes_an_id_is_refused(monkeypatch):
    good = case()
    monkeypatch.setattr(
        "loghog.emit.cases.case_notes", lambda case: "n"
    )
    original = __import__("loghog.emit.cases", fromlist=["render_case"]).render_case

    def wrong(case):
        return [line.replace(case.case_id, "loghog_w_other") for line in original(case)]

    monkeypatch.setattr("loghog.emit.cases.render_case", wrong)
    with pytest.raises(EmitError, match="is not"):
        render_cases_yaml([good], window="w", dry_run=False)


def test_a_rendering_that_loses_a_criterion_is_refused(monkeypatch):
    original = __import__("loghog.emit.cases", fromlist=["render_sequence_item"])

    def fewer(value, indent):
        return f"{' ' * indent}- changed"

    monkeypatch.setattr(original, "render_sequence_item", fewer)
    with pytest.raises(EmitError, match="criteria did not survive"):
        render_cases_yaml([case()], window="w", dry_run=False)


# --- promotion --------------------------------------------------------------


def test_a_promotion_that_would_change_the_case_count_writes_nothing(tmp_path, monkeypatch):
    candidates = tmp_path / "c.yaml"
    candidates.write_text(render_cases_yaml([case()], window="w", dry_run=False))
    target = tmp_path / "g.yaml"
    monkeypatch.setattr(
        "loghog.emit.promote.render_promoted_case",
        lambda case, reviewed_by, ts_utc: render_promoted_case(
            case, reviewed_by=reviewed_by, ts_utc=ts_utc
        )
        + ["", "- id: an_extra_case", "  tags: []", "  input: x", "  criteria: [y]"],
    )
    with pytest.raises(PromoteError, match="where 1 were expected"):
        promote(
            candidates_path=candidates,
            case_ids=["loghog_w_r_1"],
            into=target,
            reviewed_by="Bobby",
            ts_utc="2026-09-05T00:00:00Z",
        )
    assert not target.exists()


def test_a_write_that_fails_leaves_no_temporary_behind(tmp_path, monkeypatch):
    candidates = tmp_path / "c.yaml"
    candidates.write_text(render_cases_yaml([case()], window="w", dry_run=False))
    target = tmp_path / "g.yaml"

    def explode(temporary, mode):
        raise OSError("disk full")

    monkeypatch.setattr("loghog.emit.promote.os.chmod", explode)
    with pytest.raises(OSError):
        promote(
            candidates_path=candidates,
            case_ids=["loghog_w_r_1"],
            into=target,
            reviewed_by="Bobby",
            ts_utc="2026-09-05T00:00:00Z",
        )
    assert not target.exists()
    assert not list(tmp_path.glob(".g.yaml.*"))


# --- labels read back -------------------------------------------------------


def test_a_labels_row_that_is_not_a_label_is_refused(tmp_path):
    directory = tmp_path / "selected" / "w"
    directory.mkdir(parents=True)
    (directory / LABELS_NAME).write_text('{"record_id": "r-1"}\n', encoding="utf-8")
    with pytest.raises(LabelError, match="not a label"):
        read_labels(directory)


def test_a_run_that_changed_model_halfway_says_so_rather_than_picking_one():
    assert _one_model_id(["a", "a"]) == "a"
    assert _one_model_id(["a", "b"]) == "mixed (a, b)"
    assert _one_model_id([]) == "none"


def test_a_draft_outcome_from_the_synthetic_drafter_names_the_dry_run_model():
    outcome = DraftOutcome(
        draft=Draft(criteria=CRITERIA, notes=SYNTHETIC_MARKER),
        error_type=None,
        model_id=DRY_RUN_MODEL_ID,
    )
    assert "dry run" in outcome.model_id


# --- configuration ----------------------------------------------------------


def test_a_non_string_model_ref_is_refused():
    from loghog.errors import ConfigFileError

    with pytest.raises(ConfigFileError, match="model reference"):
        load_label_settings({"model_ref": 3, "min_interval_ms": 0, "max_calls": 1})


def test_a_health_threshold_that_is_an_integer_is_refused():
    from loghog.errors import ConfigFileError
    from loghog.health.settings import load_health_settings

    with pytest.raises(ConfigFileError):
        load_health_settings({"neighbour_jaccard": 1, "max_recommendations": 5})


# --- health -----------------------------------------------------------------


def test_health_over_a_window_with_no_records_is_refused(tmp_path):
    config = load_test_config(tmp_path)
    directory = config.records_dir / "w"
    directory.mkdir(parents=True)
    (directory / "records.jsonl").write_text("", encoding="utf-8")
    goldens = tmp_path / "g.yaml"
    goldens.write_text(
        "- id: a\n  tags: []\n  input: x\n  criteria: [y]\n", encoding="utf-8"
    )
    with pytest.raises(HealthError, match="no records"):
        health_of(config, goldens)


def health_of(config, goldens):
    from loghog.health.run import health_report

    return health_report(config, window="w", goldens_path=goldens)
