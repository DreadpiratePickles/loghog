"""The four configuration sections Phase B adds, and what each of them refuses.

A weight is an argument about what matters, and a quota is an argument about
what a dataset should be made of. Both belong in a reviewed file rather than in
code, and both are validated hard: a typo in a weight silently reranks every
window, and a typo in a quota silently changes what the dataset measures.

Every test edits the *committed* file rather than inventing one, so a test
cannot keep passing against a section the repository no longer ships.
"""

import re

import pytest

from conftest import COMMITTED_CONFIG, load_test_config
from loghog.config_file import load_config
from loghog.errors import ConfigFileError
from loghog.score.settings import SIGNAL_NAMES


def edited(tmp_path, **lines: str):
    """The committed configuration with whole lines replaced, by key.

    Line-level rather than substring-level because a substring edit inside a
    list would leave the rest of the list dangling and the failure under test
    would become a TOML parse error instead.
    """
    text = COMMITTED_CONFIG.read_text(encoding="utf-8")
    for key, replacement in lines.items():
        pattern = re.compile(rf"^{re.escape(key)} = .*$", re.MULTILINE)
        if not pattern.search(text):
            raise AssertionError(f"no line for {key!r} in the committed loghog.toml")
        text = pattern.sub(replacement, text, count=1)
    path = tmp_path / "loghog.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_committed_configuration_carries_every_phase_b_section(tmp_path):
    config = load_test_config(tmp_path)
    assert config.selected_dir == tmp_path / "selected"
    assert config.drift_dir == tmp_path / "drift"
    assert config.cluster.permutations == 64
    assert config.select.max_candidates > 0
    assert config.drift.novel_cluster_jaccard > 0


def test_every_signal_has_a_weight_in_the_committed_file(tmp_path):
    weights = load_test_config(tmp_path).score.weights
    assert sorted(weights) == sorted(SIGNAL_NAMES)


def test_every_signal_has_a_quota_and_ordinary_traffic_does_too(tmp_path):
    quotas = load_test_config(tmp_path).select.quotas
    assert sorted(quotas) == sorted((*SIGNAL_NAMES, "ordinary"))


def test_a_missing_weight_is_refused_by_name(tmp_path):
    with pytest.raises(ConfigFileError, match="tiny_input"):
        load_config(edited(tmp_path, tiny_input="# removed"))


def test_an_unknown_weight_is_refused_rather_than_ignored(tmp_path):
    # The failure mode of a tolerant loader: `judge_falure = 9` is dropped on
    # the floor and every failed judgement then scores zero.
    with pytest.raises(ConfigFileError, match="judge_falure"):
        load_config(edited(tmp_path, tiny_input="tiny_input = 1\njudge_falure = 9"))


def test_a_negative_weight_is_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="tiny_input"):
        load_config(edited(tmp_path, tiny_input="tiny_input = -1"))


def test_a_float_weight_is_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="integer"):
        load_config(edited(tmp_path, tiny_input="tiny_input = 1.5"))


def test_a_boolean_weight_is_refused_because_true_is_not_one(tmp_path):
    with pytest.raises(ConfigFileError, match="integer"):
        load_config(edited(tmp_path, tiny_input="tiny_input = true"))


def test_weights_that_are_all_zero_are_refused(tmp_path):
    zeroed = {name: f"{name} = 0" for name in SIGNAL_NAMES}
    with pytest.raises(ConfigFileError, match="every weight is zero"):
        load_config(edited(tmp_path, **zeroed))


def test_a_ratio_outside_zero_to_one_is_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="between 0 and 1"):
        load_config(edited(tmp_path, non_ascii_threshold="non_ascii_threshold = 1.5"))


def test_a_ratio_that_is_an_integer_is_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="fraction"):
        load_config(edited(tmp_path, non_ascii_threshold="non_ascii_threshold = 1"))


def test_a_percentile_outside_the_range_is_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="percentile"):
        load_config(edited(tmp_path, outlier_percentile="outlier_percentile = 150"))


def test_an_empty_feedback_vocabulary_is_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="negative_feedback_words"):
        load_config(edited(tmp_path, negative_feedback_words="negative_feedback_words = []"))


def test_a_word_in_both_feedback_vocabularies_is_refused(tmp_path):
    # "up" meaning both would make `feedback_conflict` fire on every record
    # that had any feedback at all.
    with pytest.raises(ConfigFileError, match="both"):
        both = 'positive_feedback_words = ["up", "down"]'
        load_config(edited(tmp_path, positive_feedback_words=both))


def test_bands_that_do_not_divide_the_permutations_are_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="divide"):
        load_config(edited(tmp_path, bands="bands = 7"))


def test_a_jaccard_threshold_outside_zero_to_one_is_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="between 0 and 1"):
        load_config(edited(tmp_path, jaccard_threshold="jaccard_threshold = 2.0"))


def test_max_per_cluster_below_one_is_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="at least 1"):
        load_config(edited(tmp_path, max_per_cluster="max_per_cluster = 0"))


def test_an_unknown_quota_is_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="nonsense"):
        load_config(edited(tmp_path, ordinary="ordinary = 4\nnonsense = 3"))


def test_a_missing_quota_is_refused_because_a_silent_zero_is_a_silent_cap(tmp_path):
    with pytest.raises(ConfigFileError, match="ordinary"):
        load_config(edited(tmp_path, ordinary="# removed"))


def test_an_unknown_key_in_a_phase_b_section_is_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="embeddings"):
        load_config(edited(tmp_path, seed="seed = 1729\nembeddings = true"))


def test_the_new_paths_stay_inside_the_repository(tmp_path):
    with pytest.raises(ConfigFileError, match="outside"):
        load_config(edited(tmp_path, selected_dir='selected_dir = "../selected"'))


def test_a_zero_quota_is_allowed_because_excluding_a_stratum_is_a_real_choice(tmp_path):
    config = load_config(edited(tmp_path, ordinary="ordinary = 0"))
    assert config.select.quotas["ordinary"] == 0
