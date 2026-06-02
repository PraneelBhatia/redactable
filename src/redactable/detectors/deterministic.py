"""The deterministic regex + checksum detector — Redactable's recall-critical core.

Structured identifiers are not a guessing game. Each rule is a precise pattern, and
checksum-bearing types (credit card, IBAN, routing number) are *gated*: a candidate
that fails its checksum is discarded rather than emitted, because flagging a
known-invalid identifier is a false positive. Confidence is always 1.0 — this layer
makes claims it can prove.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from redactable.checksums import aba_routing_valid, iban_valid, luhn_valid
from redactable.span import EntityType, Span

_DIGITS_ONLY = re.compile(r"[^0-9]")


def _digits(text: str) -> str:
    return _DIGITS_ONLY.sub("", text)


@dataclass(frozen=True)
class _Rule:
    entity_type: EntityType
    pattern: re.Pattern[str]
    # Optional checksum gate. Receives the matched text; returns True if it passes.
    # When present, only passing matches are emitted (and marked ``valid=True``).
    validator: Callable[[str], bool] | None = None


# Order matters only for readability; overlap resolution happens in the redactor.
_RULES: tuple[_Rule, ...] = (
    _Rule(
        EntityType.EMAIL,
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    ),
    _Rule(
        EntityType.URL,
        re.compile(r"\bhttps?://[^\s<>\"')]+", re.IGNORECASE),
    ),
    _Rule(
        # North American + E.164-ish phone formats, boundaried so it won't bite into
        # longer digit runs (cards, IBANs).
        EntityType.PHONE,
        re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"),
    ),
    _Rule(
        # SSN with SSA-invalid area/group/serial ranges excluded for precision.
        EntityType.US_SSN,
        re.compile(r"(?<!\d)(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)"),
    ),
    _Rule(
        EntityType.CREDIT_CARD,
        re.compile(r"(?<!\d)\d(?:[ \-]?\d){12,18}(?!\d)"),
        validator=lambda m: luhn_valid(_digits(m)),
    ),
    _Rule(
        # Compact IBAN form (no internal spaces). Spaced/grouped printed IBANs are a
        # later enhancement; matching them generically risks swallowing trailing prose.
        EntityType.IBAN,
        re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}[A-Za-z0-9]{11,30}(?![A-Za-z0-9])"),
        validator=iban_valid,
    ),
    _Rule(
        EntityType.IP_ADDRESS,
        re.compile(
            r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])"
        ),
    ),
    _Rule(
        # Bare 9-digit US routing number, ABA-checksum gated.
        EntityType.US_ROUTING,
        re.compile(r"(?<!\d)\d{9}(?!\d)"),
        validator=aba_routing_valid,
    ),
)


class DeterministicDetector:
    """Detects structured PII via regex, gated by checksums where one exists."""

    name = "deterministic"

    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for rule in _RULES:
            for match in rule.pattern.finditer(text):
                matched = match.group()
                valid: bool | None = None
                if rule.validator is not None:
                    if not rule.validator(matched):
                        continue  # checksum failed -> not this entity
                    valid = True
                spans.append(
                    Span(
                        start=match.start(),
                        end=match.end(),
                        entity_type=rule.entity_type,
                        text=matched,
                        score=1.0,
                        detector=self.name,
                        valid=valid,
                    )
                )
        return spans
