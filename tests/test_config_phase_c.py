"""`[label]` and `[health]`, and the two paths Phase C adds.

The one rule worth a test of its own: `[label] model_ref` names a *reference*
that `loghog.config.MODEL_ID_DEFAULTS` defines, never a model id. A vendor
string in a reviewed configuration file is exactly what `config.py` exists to
prevent, and a typo in a reference must be refused when the file is read rather
than discovered when the first call is priced.
"""

import pytest

from conftest import load_test_config, write_config
from loghog.config import LABEL_MODEL_ID, LABEL_MODEL_REF, model_id_for_ref
from loghog.config_file import load_config
from loghog.errors import ConfigFileError
from loghog.health.settings import load_health_settings
from loghog.label.settings import load_label_settings


def test_committed_config_carries_the_phase_c_sections(tmp_path):
    config = load_test_config(tmp_path)
    assert config.label.model_ref == LABEL_MODEL_REF
    assert config.label.min_interval_ms >= 0
    assert config.label.max_calls >= 1
    assert 0.0 < config.health.neighbour_jaccard < 1.0
    assert config.health.max_recommendations >= 1


def test_the_paths_resolve_inside_the_repository(tmp_path):
    config = load_test_config(tmp_path)
    root = config.root
    assert config.goldens_dir.parent == root
    assert config.health_dir.parent == root


def test_the_committed_config_names_no_model_id(tmp_path):
    """The reference is resolved by config.py; the file itself names no model.

    `GEMINI_API_KEY` appears in a comment and is not a counterexample: it is the
    name of a secret, not the name of a model. What must not appear is the model
    id itself, because that is the string a deployment would then have two
    places to change.
    """
    config = load_test_config(tmp_path)
    raw = config.path.read_text(encoding="utf-8")
    assert LABEL_MODEL_ID not in raw
    assert config.label.model_ref in raw
    assert model_id_for_ref(config.label.model_ref) == LABEL_MODEL_ID


def test_an_unknown_model_reference_is_refused_when_the_file_is_read(tmp_path):
    path = write_config(
        tmp_path, [('model_ref = "LOGHOG_LABEL_MODEL_ID"', 'model_ref = "LOGHOG_TYPO"')]
    )
    with pytest.raises(ConfigFileError) as excinfo:
        load_config(path)
    assert "LOGHOG_TYPO" in str(excinfo.value)
    assert "LOGHOG_LABEL_MODEL_ID" in str(excinfo.value)


def test_a_model_id_in_the_configuration_is_refused(tmp_path):
    """The failure this rule exists to prevent, spelled out."""
    path = write_config(
        tmp_path,
        [('model_ref = "LOGHOG_LABEL_MODEL_ID"', 'model_ref = "gemini-3.5-flash-lite"')],
    )
    with pytest.raises(ConfigFileError):
        load_config(path)


@pytest.mark.parametrize(
    "table",
    [
        {"min_interval_ms": 0, "max_calls": 1},
        {"model_ref": "LOGHOG_LABEL_MODEL_ID", "max_calls": 1},
        {"model_ref": "LOGHOG_LABEL_MODEL_ID", "min_interval_ms": 0},
    ],
)
def test_every_label_key_is_required(table):
    with pytest.raises(ConfigFileError):
        load_label_settings(table)


def test_a_negative_interval_is_refused():
    with pytest.raises(ConfigFileError):
        load_label_settings(
            {"model_ref": LABEL_MODEL_REF, "min_interval_ms": -1, "max_calls": 5}
        )


def test_a_zero_call_budget_is_refused():
    """Zero calls is not a budget, it is a stage that cannot run."""
    with pytest.raises(ConfigFileError):
        load_label_settings(
            {"model_ref": LABEL_MODEL_REF, "min_interval_ms": 0, "max_calls": 0}
        )


def test_an_unknown_label_key_is_refused():
    with pytest.raises(ConfigFileError):
        load_label_settings(
            {
                "model_ref": LABEL_MODEL_REF,
                "min_interval_ms": 0,
                "max_calls": 1,
                "temperature": 0.7,
            }
        )


def test_health_keys_are_validated():
    with pytest.raises(ConfigFileError):
        load_health_settings({"neighbour_jaccard": 0.6})
    with pytest.raises(ConfigFileError):
        load_health_settings({"neighbour_jaccard": 1.0, "max_recommendations": 5})
    with pytest.raises(ConfigFileError):
        load_health_settings({"neighbour_jaccard": 0.6, "max_recommendations": 0})
    settings = load_health_settings({"neighbour_jaccard": 0.6, "max_recommendations": 5})
    assert settings.neighbour_jaccard == 0.6
