"""Core data model: the entity taxonomy and the detected-span value object.

A ``Span`` is the universal currency of Redactable: every detector emits spans,
the eval harness scores spans against gold spans, and the redactor transforms
spans. Keeping it small, immutable, and validated keeps the rest of the system honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EntityType(StrEnum):
    """The kinds of PII/PHI Redactable can detect.

    A ``StrEnum`` so a member *is* its string value — ergonomic in YAML policies,
    JSON corpora, and audit manifests where we round-trip through plain strings.
    Policy packs may reference additional custom types as bare strings; this enum
    covers the built-in detectors.
    """

    # --- Structured identifiers (deterministic: regex + checksum) ---
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    US_SSN = "US_SSN"
    CREDIT_CARD = "CREDIT_CARD"
    IBAN = "IBAN"
    IP_ADDRESS = "IP_ADDRESS"
    US_ROUTING = "US_ROUTING"
    URL = "URL"
    DATE = "DATE"

    # --- Contextual identifiers (encoder NER) ---
    PERSON = "PERSON"
    LOCATION = "LOCATION"
    ORG = "ORG"


@dataclass(frozen=True, slots=True)
class Span:
    """A single detected entity over a source text, as a half-open ``[start, end)`` range.

    Attributes:
        start: Inclusive start offset (0-based) into the source text.
        end: Exclusive end offset; ``end > start`` is required.
        entity_type: What kind of entity this is.
        text: The exact substring covered, ``source[start:end]``.
        score: Detector confidence in ``[0.0, 1.0]``. Deterministic detectors use 1.0.
        detector: Name of the detector that produced this span (provenance for audit).
        valid: Checksum result where applicable — ``True``/``False`` for validated
            identifiers (e.g. Luhn-checked cards), ``None`` when not applicable.
    """

    start: int
    end: int
    entity_type: EntityType
    text: str
    score: float = 1.0
    detector: str = ""
    valid: bool | None = field(default=None)

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"span start must be >= 0, got {self.start}")
        if self.end <= self.start:
            raise ValueError(
                f"span end ({self.end}) must be greater than start ({self.start})"
            )
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(f"span score must be in [0.0, 1.0], got {self.score}")

    @property
    def length(self) -> int:
        """Number of characters covered."""
        return self.end - self.start

    def overlaps(self, other: Span) -> bool:
        """True if this span shares at least one character position with ``other``.

        Half-open semantics: adjacent spans (``a.end == b.start``) do not overlap.
        """
        return self.start < other.end and other.start < self.end

    def contains(self, other: Span) -> bool:
        """True if ``other`` lies entirely within this span."""
        return self.start <= other.start and other.end <= self.end
