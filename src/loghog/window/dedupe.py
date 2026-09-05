"""Exact deduplication on the fingerprint of the normalised, redacted input.

Three choices worth naming.

*Exact*, not near. Two log lines whose inputs differ by a word are two records
here. Clustering near-duplicates is a real and useful thing to do and it is
stage 04's job, where it can be done with a threshold somebody argued about
rather than silently at the door.

*The input*, not the whole row. The dataset is keyed on what was asked, not on
what came back; two answers to one question is one eval case with a
disagreement in it, and noticing that disagreement is a later stage's job.

*Redacted*, not raw. Two tickets identical except for the customer's name
collapse into one record. For an eval dataset that is correct — they are one
case — and it is the only ordering that lets a window be deduplicated without
keeping the raw text around to compare against.
"""

from collections.abc import Iterable

from loghog.record import Record


class Deduper:
    """Remembers which inputs a window has already seen."""

    def __init__(self, *, enabled: bool = True, seen: Iterable[str] = ()) -> None:
        self._enabled = bool(enabled)
        # Seeded from the window on disk when appending, so that a second file
        # into the same window cannot add a case the window already has.
        self._seen: set[str] = set(seen)
        self._dropped = 0

    def is_new(self, record: Record) -> bool:
        """Whether this record's input has not been seen, recording it either way."""
        fingerprint = record.input_fingerprint()
        already = fingerprint in self._seen
        self._seen.add(fingerprint)
        if already and self._enabled:
            self._dropped += 1
            return False
        return True

    @property
    def dropped(self) -> int:
        """How many records were suppressed as duplicates."""
        return self._dropped

    @property
    def distinct(self) -> int:
        """How many distinct inputs the window holds."""
        return len(self._seen)
