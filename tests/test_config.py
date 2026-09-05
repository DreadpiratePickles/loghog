"""Model identifiers live in exactly one module, and nowhere else.

Phase A calls no model. The module exists anyway, and is tested anyway, because
the rule it enforces — one place names a model — is cheapest to keep when it is
established before the first call site exists rather than after the fourth.
"""

from pathlib import Path

import pytest

from loghog import config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_label_model_is_the_cheap_one_this_workspace_uses():
    assert config.LABEL_MODEL_ID == "gemini-3.5-flash-lite"


def test_every_reference_resolves_to_a_default():
    for ref, default in config.MODEL_ID_DEFAULTS.items():
        assert isinstance(ref, str) and ref.isupper()
        assert isinstance(default, str) and default


def test_a_reference_resolves_to_its_default_when_the_environment_is_silent(monkeypatch):
    monkeypatch.delenv(config.LABEL_MODEL_REF, raising=False)
    assert config.model_id_for_ref(config.LABEL_MODEL_REF) == config.LABEL_MODEL_ID


def test_the_environment_wins_so_a_run_can_be_pointed_elsewhere(monkeypatch):
    monkeypatch.setenv(config.LABEL_MODEL_REF, "some-other-model")
    assert config.model_id_for_ref(config.LABEL_MODEL_REF) == "some-other-model"


def test_a_blank_environment_value_is_not_a_model_id(monkeypatch):
    monkeypatch.setenv(config.LABEL_MODEL_REF, "   ")
    assert config.model_id_for_ref(config.LABEL_MODEL_REF) == config.LABEL_MODEL_ID


def test_an_unknown_reference_is_refused_rather_than_defaulted():
    # A typo in configuration must not quietly route a run to the wrong model.
    with pytest.raises(config.UnknownModelRefError, match="unknown model reference"):
        config.model_id_for_ref("LOGHOG_TYPO_MODEL_ID")


def test_the_error_lists_the_references_that_do_exist():
    with pytest.raises(config.UnknownModelRefError, match=config.LABEL_MODEL_REF):
        config.model_id_for_ref("NOPE")


def test_no_other_source_file_names_a_model():
    # The rule, checked mechanically rather than by habit. Scanned over the
    # source, the scripts, the mappings and the configuration file — the four
    # places a vendor string could plausibly be pasted — and deliberately not
    # over the tests or the docs, which quote the id on purpose.
    scanned = [
        path
        for directory in ("src", "scripts", "mappings")
        for path in sorted((REPO_ROOT / directory).rglob("*"))
        if path.is_file() and path.suffix in {".py", ".toml"}
    ] + [REPO_ROOT / "loghog.toml"]
    assert len(scanned) > 5, "the scan found almost nothing; the paths are wrong"
    named = [
        str(path.relative_to(REPO_ROOT))
        for path in scanned
        if "gemini-" in path.read_text(encoding="utf-8")
    ]
    assert named == ["src/loghog/config.py"], f"a model id escaped config.py: {named}"
