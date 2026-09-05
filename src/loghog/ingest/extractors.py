"""Named extractors, from a fixed registry.

A mapping file names an extractor; it never supplies one. Nothing in this
package will `eval` a string out of a configuration file — a mapping is a file
somebody edits in a hurry, often with a vendor's documentation open beside it,
and the blast radius of a typo in one should be a typed error listing the four
names that exist rather than arbitrary code execution.

Every extractor takes the value the path resolved to and returns either a value
or `MISSING`. None of them raises: a shape the extractor does not recognise is
an absent value, and it is the record layer that decides whether absent is
fatal for that particular field.
"""

from collections.abc import Callable
from typing import Any

from loghog.errors import MappingError
from loghog.ingest.paths import MISSING

TEXT_PART_TYPE = "text"
"""The `type` of a content part that carries text in the multimodal chat shape."""


def _identity(value: Any) -> Any:
    return value


def _join_text(value: Any) -> Any:
    """A list of strings as one block; a plain string unchanged."""
    if value is MISSING:
        return MISSING
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return MISSING
    parts = [entry for entry in value if isinstance(entry, str)]
    return "\n".join(parts) if parts else MISSING


def _message_content(message: Any) -> Any:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # The multimodal shape: content is a list of typed parts. Only the text
        # parts are an input; an image URL is not something a golden case can
        # be written about here.
        texts = [
            part.get("text")
            for part in content
            if isinstance(part, dict)
            and part.get("type") == TEXT_PART_TYPE
            and isinstance(part.get("text"), str)
        ]
        return "\n".join(texts) if texts else MISSING
    return MISSING


def _last_message_with_role(value: Any, role: str) -> Any:
    if value is MISSING or not isinstance(value, list):
        return MISSING
    for message in reversed(value):
        if isinstance(message, dict) and message.get("role") == role:
            return _message_content(message)
    return MISSING


def _last_user_message(value: Any) -> Any:
    return _last_message_with_role(value, "user")


def _assistant_message(value: Any) -> Any:
    return _last_message_with_role(value, "assistant")


EXTRACTORS: dict[str, Callable[[Any], Any]] = {
    "identity": _identity,
    "openai_last_user_message": _last_user_message,
    "openai_assistant_message": _assistant_message,
    "join_text": _join_text,
}

EXTRACTOR_NAMES: tuple[str, ...] = tuple(sorted(EXTRACTORS))

DEFAULT_EXTRACTOR = "identity"


def extractor_for(name: str) -> Callable[[Any], Any]:
    """Look up an extractor by name.

    Raises:
        MappingError: no extractor by that name, with the four that exist named
            in the message.
    """
    extractor = EXTRACTORS.get(name)
    if extractor is None:
        known = ", ".join(EXTRACTOR_NAMES)
        raise MappingError(f"unknown extractor {name!r}; known extractors: {known}")
    return extractor
