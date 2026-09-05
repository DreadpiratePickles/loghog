"""What counts as personal data, and — just as importantly — what does not.

Every case here is one somebody actually types into a support form. The tricky
ones are deliberate: an email inside a URL, a card number that fails Luhn, an
IP that is really a version string, and a Title Case pair that is a product.
"""

import pytest

from loghog.privacy.detect import (
    ADDRESS,
    CARD,
    EMAIL,
    IBAN,
    IPV4,
    NAME,
    PHONE,
    PII_CLASSES,
    SSN,
    find_spans,
)


def classes_in(text, **kwargs):
    return [span.pii_class for span in find_spans(text, **kwargs)]


def values_of(text, pii_class, **kwargs):
    return [span.value for span in find_spans(text, **kwargs) if span.pii_class == pii_class]


def test_the_class_list_is_the_documented_eight():
    assert set(PII_CLASSES) == {EMAIL, PHONE, CARD, IBAN, SSN, IPV4, ADDRESS, NAME}


def test_a_span_knows_where_it_starts_and_ends():
    text = "write to sam@example.com please"
    (span,) = find_spans(text)
    assert text[span.start : span.end] == span.value == "sam@example.com"


# --- email ------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "sam@example.com",
        "sam.o'brien+tag@sub.example.co.uk",
        "SAM@EXAMPLE.COM",
        "s@e.io",
        "first_last-1@example-corp.com",
    ],
)
def test_ordinary_addresses_are_found(address):
    assert values_of(f"contact {address} today", EMAIL) == [address]


def test_an_email_inside_a_url_is_still_an_email():
    # The single most common way an address survives a naive redactor: it is
    # not surrounded by spaces, so a word-boundary regex walks straight past it.
    text = "see https://app.example.com/users/sam@example.com?ref=1 for the account"
    assert values_of(text, EMAIL) == ["sam@example.com"]


def test_a_mailto_link_is_an_email():
    assert values_of("mailto:sam@example.com", EMAIL) == ["sam@example.com"]


def test_an_email_in_angle_brackets_is_an_email():
    assert values_of("Sam <sam@example.com>", EMAIL) == ["sam@example.com"]


def test_a_trailing_sentence_full_stop_is_not_part_of_the_address():
    assert values_of("mail me at sam@example.com.", EMAIL) == ["sam@example.com"]


def test_an_at_sign_that_is_not_an_address_is_left_alone():
    assert EMAIL not in classes_in("the rate is 5 @ 20 per unit")


def test_a_twitter_style_handle_is_not_an_email():
    assert EMAIL not in classes_in("ping @support about it")


# --- cards ------------------------------------------------------------------


def test_a_luhn_valid_card_is_redacted():
    assert values_of("charged 4242 4242 4242 4242 twice", CARD) == ["4242 4242 4242 4242"]


def test_a_sixteen_digit_number_that_fails_luhn_is_not_a_card():
    # An order reference. Blanking it would destroy the case: "why was order
    # 1234567812345678 charged twice" is the whole question.
    assert CARD not in classes_in("order 1234567812345678 was charged twice")


def test_a_hyphenated_card_is_found_with_its_separators():
    assert values_of("card 4111-1111-1111-1111 declined", CARD) == ["4111-1111-1111-1111"]


@pytest.mark.parametrize(
    "text,found",
    [
        ("card 4242.4242.4242.4242 declined", "4242.4242.4242.4242"),
        ("card 4242_4242_4242_4242 declined", "4242_4242_4242_4242"),
    ],
)
def test_a_dot_or_underscore_separated_card_is_found(text, found):
    # A card pasted out of a spreadsheet column or a filename. Luhn still
    # gates it, so widening the separator class does not widen the net over
    # anything that is not a card.
    assert values_of(text, CARD) == [found]


def test_a_dotted_quad_is_still_an_address_and_not_a_card():
    # The separator class now contains `.`, so the guard against a short dotted
    # run becoming a card is the thirteen-digit minimum, and it is worth a test.
    assert CARD not in classes_in("timing out from 192.168.1.14")


def test_a_fifteen_digit_amex_is_a_card():
    assert values_of("amex 378282246310005", CARD) == ["378282246310005"]


def test_a_long_digit_run_inside_a_longer_one_is_not_split_into_a_card():
    # A 24-digit machine id happens to contain a Luhn-valid 16-digit window.
    # Matching it would redact the middle of an identifier and leave the ends.
    assert CARD not in classes_in("node 424242424242424212345678")


# --- iban -------------------------------------------------------------------


@pytest.mark.parametrize(
    "iban",
    ["GB33BUKB20201555555555", "DE89370400440532013000", "FR7630006000011234567890189"],
)
def test_iban_shaped_strings_are_found(iban):
    assert values_of(f"refund to {iban} please", IBAN) == [iban]


def test_an_iban_with_spaces_is_found():
    assert values_of("to DE89 3704 0044 0532 0130 00 thanks", IBAN) == [
        "DE89 3704 0044 0532 0130 00"
    ]


def test_two_letters_and_a_short_number_is_not_an_iban():
    assert IBAN not in classes_in("model GB33 is discontinued")


# --- ssn --------------------------------------------------------------------


def test_a_dashed_ssn_is_found():
    assert values_of("ssn 123-45-6789 on file", SSN) == ["123-45-6789"]


def test_a_spaced_ssn_is_found():
    assert values_of("ssn 123 45 6789 on file", SSN) == ["123 45 6789"]


def test_a_phone_number_is_not_mistaken_for_an_ssn():
    assert SSN not in classes_in("call 020 7946 0958")


def test_a_date_is_not_an_ssn():
    assert SSN not in classes_in("shipped 2026-09-05")


# --- phone ------------------------------------------------------------------


@pytest.mark.parametrize(
    "number",
    [
        "+44 20 7946 0958",
        "+1 (555) 010-9999",
        "020 7946 0958",
        "555-010-9999",
        "+49 30 901820",
    ],
)
def test_phone_numbers_in_the_shapes_people_type_are_found(number):
    assert values_of(f"call me on {number} tomorrow", PHONE) == [number]


def test_a_short_number_is_not_a_phone_number():
    assert PHONE not in classes_in("i ordered 3 of them")


def test_a_price_is_not_a_phone_number():
    assert PHONE not in classes_in("it cost 124.50 in total")


def test_an_order_reference_of_six_digits_is_not_a_phone_number():
    assert PHONE not in classes_in("order 401820 is late")


def test_an_invoice_number_of_two_groups_is_not_a_phone_number():
    # `9911-2233` is in the sample CSV, and an earlier, looser pattern took it.
    # Every real number in this test set carries a country code, a
    # parenthesised area code, or three groups, so requiring one of the three
    # costs nothing and removes a whole class of false positive.
    assert PHONE not in classes_in("for invoice 9911-2233 please")


def test_a_parenthesised_area_code_is_enough_without_a_country_code():
    assert values_of("call (555) 010-9999 today", PHONE) == ["(555) 010-9999"]


def test_a_date_is_not_a_phone_number():
    # 2026-09-05 is three groups of digits separated by hyphens, which is the
    # exact shape of a North American number. Dates are excluded by name.
    assert PHONE not in classes_in("shipped on 2026-09-05 by courier")


def test_a_number_with_too_few_digits_to_dial_is_not_a_phone_number():
    assert PHONE not in classes_in("rooms 12-34 are closed")


# --- ipv4 -------------------------------------------------------------------


def test_an_ip_address_is_found():
    assert values_of("from 192.168.1.14 last night", IPV4) == ["192.168.1.14"]


def test_a_number_above_255_in_an_octet_is_not_an_ip():
    assert IPV4 not in classes_in("build 999.1.1.1 failed")


def test_a_four_part_version_string_that_is_a_valid_ip_is_still_redacted():
    # Deliberate: 1.2.3.4 is indistinguishable from an address without context,
    # and a redactor that guesses wrong in this direction leaks nothing.
    assert values_of("upgraded to 1.2.3.4", IPV4) == ["1.2.3.4"]


def test_an_ip_at_the_end_of_a_sentence_is_still_found():
    # The full stop is not a fifth octet. A trailing-dot guard that refuses one
    # refuses every address anybody wrote in prose, which is most of them.
    assert values_of("timing out from 192.168.1.14. Is that blocked?", IPV4) == ["192.168.1.14"]


def test_a_five_part_dotted_number_is_not_an_ip():
    assert IPV4 not in classes_in("build 192.168.1.14.15 failed")


def test_a_three_part_version_is_not_an_ip():
    assert IPV4 not in classes_in("version 3.12.1 of python")


# --- address ----------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "221B Baker Street",
        "10 Downing St",
        "1600 Pennsylvania Avenue",
        "42 Acacia Road",
        "7 Rue Lafayette",
    ],
)
def test_a_number_followed_by_a_street_word_is_an_address(address):
    assert values_of(f"deliver to {address} before noon", ADDRESS) == [address]


def test_a_quantity_followed_by_a_noun_is_not_an_address():
    assert ADDRESS not in classes_in("i ordered 3 lamps and 2 shades")


def test_a_street_word_with_no_number_is_not_an_address():
    assert ADDRESS not in classes_in("the Baker Street shop is closed")


# --- names ------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["Dr Susan Calvin", "Mr Ford Prefect", "Ms Ada Lovelace", "Prof. Alan Turing"],
)
def test_an_honorific_followed_by_title_case_words_is_a_name(name):
    assert values_of(f"spoke to {name} yesterday", NAME) == [name]


def test_a_single_title_case_word_after_an_honorific_is_a_name():
    assert values_of("assigned to Dr Calvin", NAME) == ["Dr Calvin"]


def test_a_title_case_pair_with_no_honorific_is_left_alone():
    # The heuristic is deliberately narrow. Without the honorific, "Lumen Desk"
    # and "Susan Calvin" are the same string to a regex, and the product name
    # is the part of the ticket an eval case needs.
    assert NAME not in classes_in("the Lumen Desk lamp flickers")


def test_the_allowlist_suppresses_a_known_non_person():
    assert NAME not in classes_in("we stock Dr Pepper", name_allowlist=("Dr Pepper",))


def test_the_allowlist_is_case_insensitive():
    assert NAME not in classes_in("we stock DR PEPPER", name_allowlist=("Dr Pepper",))


def test_the_allowlist_does_not_suppress_a_different_name():
    assert values_of(
        "spoke to Dr Calvin", NAME, name_allowlist=("Dr Pepper",)
    ) == ["Dr Calvin"]


def test_a_capitalised_word_after_the_name_is_swallowed_and_that_is_the_safe_direction():
    # "Called" is a verb at the start of a clause and the heuristic cannot know
    # that; without a dictionary, "Calvin Called" and "Susan Calvin" are the
    # same shape. It over-redacts, which loses a word of context, rather than
    # under-redacting, which loses a surname. See docs/design.md.
    assert values_of("Dr Calvin Called back", NAME) == ["Dr Calvin Called"]


def test_the_name_never_runs_past_a_lowercase_word():
    assert values_of("Dr Calvin called back", NAME) == ["Dr Calvin"]


# --- overlaps ---------------------------------------------------------------


def test_spans_come_back_in_document_order():
    text = "sam@example.com from 10.0.0.1"
    starts = [span.start for span in find_spans(text)]
    assert starts == sorted(starts)


def test_no_two_spans_overlap():
    text = "card 4242 4242 4242 4242 and phone +44 20 7946 0958 and sam@example.com"
    spans = find_spans(text)
    for earlier, later in zip(spans, spans[1:], strict=False):
        assert earlier.end <= later.start


def test_the_card_wins_over_the_phone_number_when_they_overlap():
    # "4242 4242 4242 4242" is both a Luhn-valid card and a plausible run of
    # spaced digits. Whichever class wins, the digits must be redacted exactly
    # once, and the more specific class is the more useful label.
    assert classes_in("paid with 4242 4242 4242 4242") == [CARD]


def test_an_email_wins_over_a_name_inside_it():
    assert classes_in("Dr Susan Calvin <dr.calvin@example.com>") == [NAME, EMAIL]


def test_empty_and_none_text_produce_no_spans():
    assert find_spans("") == ()


def test_text_that_is_entirely_ordinary_produces_no_spans():
    assert find_spans("the lamp flickers above half brightness") == ()
