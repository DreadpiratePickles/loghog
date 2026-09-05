"""`loghog.toml`: the paths, the privacy switch, and the limits.

Every test loads the *committed* file with substitutions rather than inventing
a configuration in code, so a test cannot keep passing against wording the
repository no longer ships.
"""

import pytest

from conftest import load_test_config, write_config
from loghog.config_file import DEFAULT_CONFIG_NAME, load_config
from loghog.errors import ConfigFileError


def test_the_committed_configuration_loads(tmp_path):
    config = load_test_config(tmp_path)
    assert config.redact is True
    assert config.records_dir.name == "records"
    assert config.mappings_dir.name == "mappings"


def test_the_default_file_name_is_the_one_the_docs_use():
    assert DEFAULT_CONFIG_NAME == "loghog.toml"


def test_paths_resolve_against_the_config_file_not_the_shell(tmp_path):
    config = load_test_config(tmp_path)
    assert config.records_dir == tmp_path / "records"
    assert config.root == tmp_path


def test_redaction_is_on_by_default_in_the_committed_file(tmp_path):
    assert load_test_config(tmp_path).redact is True


def test_redaction_can_be_turned_off_and_the_config_says_so(tmp_path):
    config = load_test_config(tmp_path, [("redact = true", "redact = false")])
    assert config.redact is False


def test_a_missing_file_is_a_typed_error_naming_the_path(tmp_path):
    with pytest.raises(ConfigFileError, match="nope.toml"):
        load_config(tmp_path / "nope.toml")


def test_unparseable_toml_is_a_typed_error(tmp_path):
    path = tmp_path / "loghog.toml"
    path.write_text("[paths\n", encoding="utf-8")
    with pytest.raises(ConfigFileError):
        load_config(path)


def test_an_absolute_path_in_configuration_is_refused(tmp_path):
    # A committed path containing somebody's home directory works on exactly
    # one machine.
    path = write_config(tmp_path, [('records_dir = "records"', 'records_dir = "/tmp/records"')])
    with pytest.raises(ConfigFileError, match="absolute"):
        load_config(path)


def test_a_path_escaping_the_repository_is_refused(tmp_path):
    path = write_config(tmp_path, [('records_dir = "records"', 'records_dir = "../elsewhere"')])
    with pytest.raises(ConfigFileError, match="outside"):
        load_config(path)


def test_a_non_boolean_redact_is_refused(tmp_path):
    path = write_config(tmp_path, [("redact = true", 'redact = "yes"')])
    with pytest.raises(ConfigFileError, match="redact"):
        load_config(path)


def test_an_unknown_top_level_section_is_refused(tmp_path):
    path = write_config(tmp_path, [("[privacy]", "[privicy]")])
    with pytest.raises(ConfigFileError, match="unknown"):
        load_config(path)


def test_an_unknown_key_inside_a_section_is_refused(tmp_path):
    path = write_config(tmp_path, [("redact = true", "redact = true\nredakt = true")])
    with pytest.raises(ConfigFileError, match="redakt"):
        load_config(path)


def test_the_name_allowlist_is_a_tuple_of_strings(tmp_path):
    config = load_test_config(tmp_path)
    assert isinstance(config.name_allowlist, tuple)
    assert all(isinstance(entry, str) for entry in config.name_allowlist)


def test_a_non_string_in_the_allowlist_is_refused(tmp_path):
    path = write_config(tmp_path, [("name_allowlist = [", "name_allowlist = [7,")])
    with pytest.raises(ConfigFileError, match="allowlist"):
        load_config(path)


def test_the_text_limits_are_positive_integers(tmp_path):
    config = load_test_config(tmp_path)
    assert config.max_text_chars > 0


def test_a_zero_text_limit_is_refused(tmp_path):
    path = write_config(tmp_path, [("max_text_chars = 20000", "max_text_chars = 0")])
    with pytest.raises(ConfigFileError, match="max_text_chars"):
        load_config(path)


def test_a_float_text_limit_is_refused(tmp_path):
    path = write_config(tmp_path, [("max_text_chars = 20000", "max_text_chars = 2.5")])
    with pytest.raises(ConfigFileError):
        load_config(path)


def test_dedupe_is_on_in_the_committed_file(tmp_path):
    assert load_test_config(tmp_path).dedupe is True


def test_dedupe_can_be_turned_off(tmp_path):
    config = load_test_config(tmp_path, [("dedupe = true", "dedupe = false")])
    assert config.dedupe is False
