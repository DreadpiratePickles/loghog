"""Model identifiers, and nothing else.

Every model id in this package lives here. No other module names a model, and
neither does `loghog.toml`: configuration names a *reference* — the name of an
environment variable — and this module resolves it. That keeps vendor strings
out of reviewed configuration and gives a deployment one variable to override,
which is the rule projects 1, 2, 8 and 9 in this series all follow for the same
reason: a model id is a fact about the outside world that changes without
warning, and it should change in one reviewable place.

**Phase A calls no model.** Stages 01 and 02 are ingestion and redaction, both
of which are mechanical, and mechanical work is deterministic code. This module
exists before its first call site because the rule it enforces is cheapest to
keep when it is established before the first call site exists rather than after
the fourth.
"""

import os

LABEL_MODEL_ID = "gemini-3.5-flash-lite"
"""The model stage 06 (`06_label`, PLANNED) will draft criteria with.

The cheapest published Gemini text model. Labelling is a short, well-specified
judgement made once per selected record, and a selection worth labelling is
small by construction — if it were not, the earlier stages failed.
"""

LABEL_MODEL_REF = "LOGHOG_LABEL_MODEL_ID"
"""The environment variable that overrides `LABEL_MODEL_ID` for one deployment."""

MODEL_ID_DEFAULTS: dict[str, str] = {
    LABEL_MODEL_REF: LABEL_MODEL_ID,
}
"""Environment variable name -> default model id. The whole vocabulary of
references configuration may use."""


class UnknownModelRefError(ValueError):
    """Configuration names a model reference this module does not define."""


def model_id_for_ref(ref: str) -> str:
    """Resolve a configured `model_ref` to the model id that should be called.

    The environment wins over the default so a run can be pointed at another
    model without a commit.

    Raises:
        UnknownModelRefError: `ref` is not a defined reference. An unrecognised
            reference is never silently resolved to a default: a typo would then
            quietly route a run to the wrong model at the wrong price.
    """
    if ref not in MODEL_ID_DEFAULTS:
        known = ", ".join(sorted(MODEL_ID_DEFAULTS))
        raise UnknownModelRefError(f"unknown model reference {ref!r}; known references: {known}")
    override = os.environ.get(ref, "").strip()
    return override or MODEL_ID_DEFAULTS[ref]
