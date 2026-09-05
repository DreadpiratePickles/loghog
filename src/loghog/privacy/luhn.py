"""The Luhn checksum: the difference between a card number and sixteen digits.

An order reference, a session id, a serial number and an invoice number are all
long runs of digits, and a redactor that blanks every one of them destroys the
thing an eval case is *about* — "why was order 1234567812345678 charged twice"
is the question, and a `[CARD_1]` in the middle of it is a case nobody can use.

Luhn costs one pass over the digits and is what every payment form on the
internet uses to catch a typo before it reaches an acquirer. It is not proof
that a number is a live account; it is proof that it is card-*shaped*, which is
the right question for a redactor.
"""

MIN_CARD_DIGITS = 13
"""Below this no issuer allocates. Twelve digits is almost always an order id."""

MAX_CARD_DIGITS = 19
"""ISO/IEC 7812's maximum. Above it, whatever it is, it is not a PAN."""

CARD_SEPARATORS = " -._"
"""The characters that may sit between the groups of a card number.

Space and hyphen are how a person types one. Dot and underscore are how a card
arrives out of a spreadsheet column or a filename, and a redactor that misses
`4242.4242.4242.4242` misses a real paste. The detector builds its separator
character class from this string, so the pattern and the checksum cannot come
to disagree about what a separator is.
"""


def digits_only(text: str) -> str:
    """The digits of `text`, with every separator dropped."""
    return "".join(character for character in text if character.isdigit())


def luhn_ok(text: str) -> bool:
    """Whether `text` is a card-shaped number with a valid Luhn checksum.

    Separators (`CARD_SEPARATORS`) are ignored because that is how people type a
    card and how a spreadsheet exports one. Any other non-digit character makes
    it not a number at all — a run containing letters is an identifier, not a
    PAN.
    """
    if not isinstance(text, str):
        return False
    stripped = text
    for separator in CARD_SEPARATORS:
        stripped = stripped.replace(separator, "")
    if not stripped or not stripped.isdigit():
        return False
    if not MIN_CARD_DIGITS <= len(stripped) <= MAX_CARD_DIGITS:
        return False
    total = 0
    # Right to left: every second digit is doubled, and a double over nine has
    # its digits summed — which is the same as subtracting nine.
    for position, character in enumerate(reversed(stripped)):
        digit = int(character)
        if position % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
