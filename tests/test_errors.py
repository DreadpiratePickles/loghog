"""The error hierarchy is the contract: a caller catches a category, not a string.

Every failure this package can produce is a `LoghogError`, and every one of them
sits under exactly one of the six categories a caller might want to treat
differently — bad configuration, a bad record, a bad source line, a refusal to
write unredacted text, a broken window on disk, and a window that read fine and
does not yet hold what a later stage needs.
"""

import inspect

import pytest

from loghog import errors


def test_every_public_error_descends_from_the_root():
    exported = [
        value
        for name, value in vars(errors).items()
        if inspect.isclass(value) and issubclass(value, BaseException) and not name.startswith("_")
    ]
    assert exported, "the module exports no errors at all"
    for error in exported:
        assert issubclass(error, errors.LoghogError), f"{error.__name__} is outside the hierarchy"


@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (errors.ConfigFileError, errors.ConfigError),
        (errors.MappingError, errors.ConfigError),
        (errors.MissingFieldError, errors.RecordError),
        (errors.FieldTypeError, errors.RecordError),
        (errors.TimestampError, errors.RecordError),
        (errors.SourceFormatError, errors.SourceError),
        (errors.UnredactedWriteError, errors.RedactionError),
        (errors.ManifestError, errors.WindowError),
        (errors.WindowConflictError, errors.WindowError),
        (errors.ScoreError, errors.AnalysisError),
        (errors.ClusterError, errors.AnalysisError),
        (errors.SelectionError, errors.AnalysisError),
        (errors.DriftError, errors.AnalysisError),
    ],
)
def test_the_categories_are_the_ones_a_caller_would_branch_on(child, parent):
    assert issubclass(child, parent)


def test_the_six_categories_are_siblings_and_not_each_other():
    categories = [
        errors.ConfigError,
        errors.RecordError,
        errors.SourceError,
        errors.RedactionError,
        errors.WindowError,
        errors.AnalysisError,
    ]
    for one in categories:
        for other in categories:
            if one is not other:
                assert not issubclass(one, other), f"{one.__name__} is under {other.__name__}"


def test_a_record_error_is_not_a_source_error():
    # The distinction is load bearing: a bad line is counted and the run
    # continues, a bad configuration stops the run. Collapsing the two would
    # make a typo in a mapping look like sixty thousand bad log lines.
    assert not issubclass(errors.RecordError, errors.SourceError)
    assert not issubclass(errors.SourceError, errors.RecordError)


def test_a_line_failure_names_its_line_its_type_and_a_detail():
    failure = errors.LineFailure(line_no=42, error_type="MissingFieldError", detail="no ts_utc")
    assert failure.line_no == 42
    assert failure.error_type == "MissingFieldError"
    assert failure.to_json_dict() == {
        "line_no": 42,
        "error_type": "MissingFieldError",
        "detail": "no ts_utc",
    }


def test_a_line_failure_refuses_a_line_number_below_one():
    with pytest.raises(errors.SourceError):
        errors.LineFailure(line_no=0, error_type="x", detail="y")


def test_a_line_failure_refuses_an_empty_error_type():
    # "something went wrong on line 12" is not a report anybody can act on.
    with pytest.raises(errors.SourceError):
        errors.LineFailure(line_no=1, error_type="  ", detail="y")


def test_line_failure_from_an_exception_takes_the_class_name_as_the_type():
    failure = errors.LineFailure.from_exception(7, errors.MissingFieldError("ts_utc is absent"))
    assert failure.error_type == "MissingFieldError"
    assert failure.detail == "ts_utc is absent"
    assert failure.line_no == 7
