"""The committed examples: every one says what it is on its own first line.

These files are the evidence in the README and the thing a reader looks at
before they trust anything else here. Every number in them came from an invented
log, and a copy of one of them that lost its banner is a copy somebody quotes as
a measurement.

The candidates file gets a second check, and it is the load-bearing one: it must
load with `regression_detect.goldens.load_goldens`. If it stops loading, the
claim this whole repository makes about its output is false, and it is false in
the committed artefact rather than only in a test fixture.
"""

import pytest
from regression_detect.goldens import load_goldens

from conftest import REPO_ROOT

EXAMPLES = REPO_ROOT / "docs" / "examples"

MARKDOWN = (
    "lifecycle.synthetic.md",
    "selection.synthetic.md",
    "label.synthetic.md",
    "review.synthetic.md",
    "health.synthetic.md",
    "drift.synthetic.md",
)
YAML = ("candidates.synthetic.yaml", "goldens.handwritten.yaml")


@pytest.mark.parametrize("name", MARKDOWN)
def test_every_markdown_example_says_synthetic_on_its_first_line(name):
    first = (EXAMPLES / name).read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("SYNTHETIC"), f"{name} does not lead with its banner"


@pytest.mark.parametrize("name", YAML)
def test_every_yaml_example_says_synthetic_in_its_first_comment(name):
    first = (EXAMPLES / name).read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("# SYNTHETIC"), f"{name} does not lead with its banner"


@pytest.mark.parametrize("name", YAML)
def test_every_yaml_example_loads_with_project_ones_own_loader(name):
    cases = load_goldens(EXAMPLES / name)
    assert cases
    assert all(case.criteria for case in cases)


def test_the_mined_example_is_tagged_loghog_and_the_handwritten_one_is_not():
    mined = load_goldens(EXAMPLES / "candidates.synthetic.yaml")
    assert all(case.tags[0] == "loghog" for case in mined)
    handwritten = load_goldens(EXAMPLES / "goldens.handwritten.yaml")
    assert all("loghog" not in case.tags for case in handwritten)


def test_the_lifecycle_records_the_refusal_rather_than_a_promotion():
    """The one command in the transcript that is supposed to fail."""
    text = (EXAMPLES / "lifecycle.synthetic.md").read_text(encoding="utf-8")
    assert "loghog promote" in text
    assert "[SYNTHETIC] marker" in text
    assert "[exit 3]" in text


def test_the_lifecycle_says_there_is_no_live_run_and_why():
    text = (EXAMPLES / "lifecycle.synthetic.md").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY is not set" in text
    assert "no number in" in text


def test_no_example_leaks_a_planted_value():
    """The demo logs plant eight classes of personal data. None reaches here."""
    from test_demo_logs import PLANTED  # the list lives beside the logs it describes

    for name in (*MARKDOWN, *YAML):
        text = (EXAMPLES / name).read_text(encoding="utf-8")
        for value in PLANTED:
            assert value not in text, f"{name} carries {value!r}"
