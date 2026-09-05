"""Every report a synthetic window produces says so on its own first line.

The rule is stated in `CONTEXT.md` and kept by `ingest.md`, `score.md` and
`cluster.md`. It was **not** kept by `selection.md`, by either drift report or
by the health report, and that is the failure this file exists to stop
recurring: a report whose banner is missing is a report somebody quotes as a
measurement, and every number in these came from an invented log.

The health and drift reports each read two facts rather than one, and both are
covered here: a comparison is synthetic when *either* window is, because a real
window compared against an invented one is not a measurement of anything.
"""

import json

import pytest

from conftest import SAMPLES_DIR, load_test_config
from loghog.cluster.window import cluster_window
from loghog.drift.run import drift_report
from loghog.health.run import health_report
from loghog.ingest.report import SYNTHETIC_BANNER
from loghog.ingest.run import ingest
from loghog.score.run import score_window
from loghog.select.run import select_candidates

SAMPLE = SAMPLES_DIR / "support_chat.synthetic.jsonl"

GOLDENS = """\
- id: flickering_lamp
  tags: [hardware]
  input: The desk lamp flickers whenever the brightness is above about half.
  criteria:
    - names the flickering
"""

SUBJECTS = (
    "The delivery driver left my parcel in the recycling bin without ringing.",
    "My replacement kettle arrived with the lid already cracked across the hinge.",
    "The mobile app signs me out every time I rotate the phone to landscape.",
    "I was charged twice for one subscription renewal in the same minute.",
)


def window(tmp_path, config, name, *, synthetic, offset=0):
    rows = [
        {
            "id": f"{name}-{index:03d}",
            "created": 1_788_000_000 + offset + index,
            "messages": [
                {"role": "user", "content": SUBJECTS[(index + offset) % len(SUBJECTS)]},
                {"role": "assistant", "content": f"A summary, number {index}."},
            ],
        }
        for index in range(4)
    ]
    source = tmp_path / f"{name}.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    ingest(
        config,
        input_path=source,
        source_format="jsonl",
        mapping_reference="openai_chat_jsonl",
        window=name,
        synthetic=synthetic,
    )
    score_window(config, window=name)
    cluster_window(config, window=name)
    return config


def test_a_synthetic_window_puts_the_banner_first_in_selection_md(tmp_path):
    config = load_test_config(tmp_path)
    window(tmp_path, config, "w", synthetic=True)
    outcome = select_candidates(config, window="w")
    report = (outcome.directory / "selection.md").read_text(encoding="utf-8")
    assert report.splitlines()[0] == SYNTHETIC_BANNER


def test_a_real_window_does_not_claim_to_be_synthetic_in_selection_md(tmp_path):
    config = load_test_config(tmp_path)
    window(tmp_path, config, "w", synthetic=False)
    outcome = select_candidates(config, window="w")
    report = (outcome.directory / "selection.md").read_text(encoding="utf-8")
    assert "SYNTHETIC" not in report


def test_a_synthetic_window_puts_the_banner_first_in_the_health_report(tmp_path):
    config = load_test_config(tmp_path)
    window(tmp_path, config, "w", synthetic=True)
    goldens = tmp_path / "cases.yaml"
    goldens.write_text(GOLDENS, encoding="utf-8")
    outcome = health_report(config, window="w", goldens_path=goldens)
    assert outcome.synthetic
    assert outcome.markdown_path.read_text(encoding="utf-8").splitlines()[0] == SYNTHETIC_BANNER
    assert json.loads(outcome.json_path.read_text(encoding="utf-8"))["synthetic"] is True


def test_a_real_window_health_report_carries_no_banner(tmp_path):
    config = load_test_config(tmp_path)
    window(tmp_path, config, "w", synthetic=False)
    goldens = tmp_path / "cases.yaml"
    goldens.write_text(GOLDENS, encoding="utf-8")
    outcome = health_report(config, window="w", goldens_path=goldens)
    assert not outcome.synthetic
    assert "SYNTHETIC" not in outcome.markdown_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("earlier_synthetic", "later_synthetic"),
    [(True, True), (True, False), (False, True)],
)
def test_a_drift_report_is_synthetic_when_either_window_is(
    tmp_path, earlier_synthetic, later_synthetic
):
    """A real window compared against an invented one is not a measurement."""
    config = load_test_config(tmp_path)
    window(tmp_path, config, "a", synthetic=earlier_synthetic)
    window(tmp_path, config, "b", synthetic=later_synthetic, offset=1)
    outcome = drift_report(config, earlier="a", later="b")
    assert outcome.synthetic
    assert outcome.markdown_path.read_text(encoding="utf-8").splitlines()[0] == SYNTHETIC_BANNER
    assert json.loads(outcome.json_path.read_text(encoding="utf-8"))["synthetic"] is True


def test_a_drift_report_between_two_real_windows_carries_no_banner(tmp_path):
    config = load_test_config(tmp_path)
    window(tmp_path, config, "a", synthetic=False)
    window(tmp_path, config, "b", synthetic=False, offset=1)
    outcome = drift_report(config, earlier="a", later="b")
    assert not outcome.synthetic
    assert "SYNTHETIC" not in outcome.markdown_path.read_text(encoding="utf-8")


def test_the_committed_sample_lifecycle_banners_every_report(tmp_path):
    """End to end over the repository's own sample, which is invented."""
    config = load_test_config(tmp_path)
    ingest(
        config,
        input_path=SAMPLE,
        source_format="jsonl",
        mapping_reference="openai_chat_jsonl",
        window="demo",
        synthetic=True,
    )
    score_window(config, window="demo")
    cluster_window(config, window="demo")
    select_candidates(config, window="demo")
    goldens = tmp_path / "cases.yaml"
    goldens.write_text(GOLDENS, encoding="utf-8")
    health_report(config, window="demo", goldens_path=goldens)
    for path in (
        config.records_dir / "demo" / "ingest.md",
        config.records_dir / "demo" / "score.md",
        config.records_dir / "demo" / "cluster.md",
        config.selected_dir / "demo" / "selection.md",
        config.health_dir / "demo.md",
    ):
        assert path.read_text(encoding="utf-8").splitlines()[0] == SYNTHETIC_BANNER, path
