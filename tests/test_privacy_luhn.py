"""Luhn: the difference between a card number and sixteen digits.

An order reference, a session id and a serial number are all long runs of
digits, and a redactor that blanks every one of them destroys the very thing an
eval case is about. Luhn is a cheap, deterministic filter that keeps them.
"""

import pytest

from loghog.privacy.luhn import luhn_ok

# The vendors' own published test numbers. They are not real accounts and never
# were; every payment stack in the world ships them in its documentation.
VALID = [
    "4242424242424242",  # Visa test number
    "5555555555554444",  # Mastercard test number
    "378282246310005",  # Amex test number, 15 digits
    "6011111111111117",  # Discover test number
    "4111111111111111",
]


@pytest.mark.parametrize("number", VALID)
def test_the_published_test_numbers_pass(number):
    assert luhn_ok(number) is True


@pytest.mark.parametrize("number", VALID)
def test_changing_one_digit_breaks_the_checksum(number):
    # Luhn's whole purpose: a single-digit typo is caught.
    head, last = number[:-1], number[-1]
    wrong = head + str((int(last) + 1) % 10)
    assert luhn_ok(wrong) is False


def test_a_plausible_looking_sixteen_digit_number_that_is_not_a_card_fails():
    assert luhn_ok("1234567812345678") is False


def test_separators_are_ignored_because_people_type_cards_in_groups():
    assert luhn_ok("4242 4242 4242 4242") is True
    assert luhn_ok("4242-4242-4242-4242") is True


def test_a_string_with_no_digits_is_not_a_card():
    assert luhn_ok("") is False
    assert luhn_ok("----") is False


def test_a_run_too_short_or_too_long_to_be_a_card_is_rejected():
    # Twelve digits is below every issuer's minimum; twenty is above the ISO
    # maximum. Both are far more likely to be an order id.
    assert luhn_ok("000000000000") is False
    assert luhn_ok("4" + "0" * 19) is False


def test_letters_make_it_not_a_number():
    assert luhn_ok("4242abcd42424242") is False
