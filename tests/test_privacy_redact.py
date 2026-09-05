"""Replacement, stable tokens, and the report that counts what was taken out.

The token is the interesting part. `[EMAIL_1]` in one record and `[EMAIL_1]` in
another must mean the same address, or a later stage cannot tell "the same
customer wrote in twice" from "two customers wrote in once" — and that is the
difference between one eval case and two.
"""

import pytest

from loghog.errors import RedactionError
from loghog.privacy.detect import CARD, EMAIL, IPV4
from loghog.privacy.redact import (
    Redactor,
    contains_hard_pii,
    hard_pii_classes,
    redaction_token,
)


def test_a_token_names_its_class_and_its_index():
    assert redaction_token(EMAIL, 1) == "[EMAIL_1]"
    assert redaction_token(CARD, 12) == "[CARD_12]"


def test_an_index_below_one_is_refused():
    with pytest.raises(RedactionError):
        redaction_token(EMAIL, 0)


def test_an_email_is_replaced_by_a_token():
    assert Redactor().redact("write to sam@example.com") == "write to [EMAIL_1]"


def test_the_surrounding_text_is_untouched():
    redactor = Redactor()
    assert redactor.redact("URGENT: sam@example.com !!") == "URGENT: [EMAIL_1] !!"


def test_the_same_value_gets_the_same_token_twice_in_one_string():
    assert Redactor().redact("sam@example.com cc sam@example.com") == "[EMAIL_1] cc [EMAIL_1]"


def test_the_same_value_gets_the_same_token_across_calls():
    # This is the property the whole design exists for: co-reference survives.
    redactor = Redactor()
    assert redactor.redact("from sam@example.com") == "from [EMAIL_1]"
    assert redactor.redact("also sam@example.com") == "also [EMAIL_1]"


def test_two_different_values_get_different_tokens():
    redactor = Redactor()
    out = redactor.redact("sam@example.com and kim@example.com")
    assert out == "[EMAIL_1] and [EMAIL_2]"


def test_tokens_are_numbered_per_class_not_globally():
    redactor = Redactor()
    out = redactor.redact("sam@example.com from 10.0.0.1")
    assert out == "[EMAIL_1] from [IPV4_1]"


def test_email_matching_is_case_insensitive_for_the_token_but_the_case_is_still_removed():
    # SAM@EXAMPLE.COM and sam@example.com are the same mailbox. Giving them two
    # tokens would silently split one customer in half.
    redactor = Redactor()
    assert redactor.redact("SAM@Example.com then sam@example.com") == "[EMAIL_1] then [EMAIL_1]"


def test_a_card_is_replaced_and_an_order_number_is_not():
    redactor = Redactor()
    out = redactor.redact("order 1234567812345678 paid with 4242 4242 4242 4242")
    assert out == "order 1234567812345678 paid with [CARD_1]"


def test_several_classes_in_one_string_are_all_replaced():
    redactor = Redactor()
    out = redactor.redact("Dr Susan Calvin, sam@example.com, +44 20 7946 0958")
    assert out == "[NAME_1], [EMAIL_1], [PHONE_1]"


def test_none_stays_none():
    assert Redactor().redact(None) is None


def test_empty_text_stays_empty():
    assert Redactor().redact("") == ""


def test_text_with_nothing_personal_comes_back_identical():
    text = "the lamp flickers above half brightness"
    assert Redactor().redact(text) == text


def test_a_string_that_already_contains_a_token_is_not_re_redacted():
    # Re-running ingestion over an already-redacted window must be a no-op, not
    # a second round of numbering.
    redactor = Redactor()
    assert redactor.redact("write to [EMAIL_1]") == "write to [EMAIL_1]"


# --- the report -------------------------------------------------------------


def test_the_report_counts_replacements_by_class():
    redactor = Redactor()
    redactor.redact("sam@example.com and kim@example.com")
    redactor.redact("sam@example.com again, plus 10.0.0.1")
    report = redactor.report()
    assert report.by_class[EMAIL] == 3
    assert report.by_class[IPV4] == 1


def test_the_report_counts_distinct_values_separately_from_replacements():
    redactor = Redactor()
    redactor.redact("sam@example.com sam@example.com kim@example.com")
    report = redactor.report()
    assert report.by_class[EMAIL] == 3
    assert report.distinct_by_class[EMAIL] == 2


def test_the_report_totals_across_classes():
    redactor = Redactor()
    redactor.redact("sam@example.com from 10.0.0.1")
    assert redactor.report().total == 2


def test_the_report_counts_the_texts_it_changed():
    redactor = Redactor()
    redactor.redact("nothing here")
    redactor.redact("sam@example.com")
    redactor.redact(None)
    report = redactor.report()
    assert report.texts_seen == 2
    assert report.texts_changed == 1


def test_the_report_never_contains_the_value_that_was_removed():
    # A redaction report that quotes what it redacted is a second copy of the
    # data, in a file people paste into tickets.
    redactor = Redactor()
    redactor.redact("sam@example.com and 4242 4242 4242 4242")
    blob = repr(redactor.report().to_json_dict())
    assert "sam@example.com" not in blob
    assert "4242" not in blob


def test_the_report_json_has_a_stable_shape():
    payload = Redactor().report().to_json_dict()
    assert set(payload) == {
        "enabled",
        "by_class",
        "distinct_by_class",
        "total",
        "texts_seen",
        "texts_changed",
    }


def test_a_class_that_never_fired_is_absent_rather_than_zero():
    redactor = Redactor()
    redactor.redact("sam@example.com")
    assert set(redactor.report().by_class) == {EMAIL}


# --- the allowlist ----------------------------------------------------------


def test_an_allowlisted_name_survives_redaction():
    redactor = Redactor(name_allowlist=("Dr Pepper",))
    assert redactor.redact("we stock Dr Pepper") == "we stock Dr Pepper"


def test_the_allowlist_does_not_leak_into_other_classes():
    redactor = Redactor(name_allowlist=("sam@example.com",))
    assert redactor.redact("sam@example.com") == "[EMAIL_1]"


def test_an_allowlist_entry_that_is_not_a_string_is_refused():
    with pytest.raises(RedactionError):
        Redactor(name_allowlist=(7,))


# --- the write guard --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "sam@example.com",
        "4242 4242 4242 4242",
        "123-45-6789",
        "192.168.1.14",
        "GB33BUKB20201555555555",
    ],
)
def test_the_hard_check_sees_the_classes_a_regex_can_be_sure_about(text):
    assert contains_hard_pii(text) is True


@pytest.mark.parametrize("text", ["Dr Susan Calvin", "221B Baker Street", "just a lamp", ""])
def test_the_hard_check_ignores_the_heuristic_classes(text):
    # NAME and ADDRESS are judgement calls. Refusing a write on a heuristic
    # would make the guard fire on "10 Downing St" in a product description and
    # stop an honest ingest for no reason.
    assert contains_hard_pii(text) is False


def test_the_hard_check_passes_redacted_text():
    assert contains_hard_pii(Redactor().redact("sam@example.com")) is False


def test_the_hard_check_tolerates_none():
    assert contains_hard_pii(None) is False


def test_the_hard_check_names_the_classes_it_found():
    # The guard needs the class list for its refusal message, and the boolean
    # is that list emptied. One implementation, or the two drift.
    assert hard_pii_classes("sam@example.com from 192.168.1.14") == ("EMAIL", "IPV4")


def test_the_class_list_is_empty_for_clean_text():
    assert hard_pii_classes("just a lamp") == ()


def test_the_class_list_tolerates_none():
    assert hard_pii_classes(None) == ()


def test_the_boolean_is_the_class_list_emptied():
    for text in ["sam@example.com", "just a lamp", "Dr Susan Calvin", "", None]:
        assert contains_hard_pii(text) is bool(hard_pii_classes(text))


@pytest.mark.parametrize("text", ["4242.4242.4242.4242", "4242_4242_4242_4242"])
def test_a_dot_or_underscore_separated_card_is_hard_pii(text):
    # Somebody pasted a card out of a spreadsheet. Luhn still gates it, so the
    # wider separator class costs nothing an order reference would pay.
    assert contains_hard_pii(text) is True


# --- disabled ---------------------------------------------------------------


def test_a_disabled_redactor_returns_the_text_unchanged():
    redactor = Redactor(enabled=False)
    assert redactor.redact("sam@example.com") == "sam@example.com"


def test_a_disabled_redactor_says_so_in_its_report():
    assert Redactor(enabled=False).report().enabled is False
    assert Redactor().report().enabled is True


def test_a_disabled_redactor_counts_nothing():
    redactor = Redactor(enabled=False)
    redactor.redact("sam@example.com")
    assert redactor.report().total == 0
