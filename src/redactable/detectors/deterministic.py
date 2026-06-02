"""The deterministic regex + checksum detector — Redactable's recall-critical core.

Structured identifiers are not a guessing game. Each rule is a precise pattern, and
checksum-bearing types (credit card, IBAN, routing number) are *gated*: a candidate
that fails its checksum is discarded rather than emitted, because flagging a
known-invalid identifier is a false positive. Confidence is always 1.0 — this layer
makes claims it can prove.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass

from redactable.checksums import aba_routing_valid, iban_valid, luhn_valid
from redactable.span import EntityType, Span

_DIGITS_ONLY = re.compile(r"[^0-9]")


def _digits(text: str) -> str:
    return _DIGITS_ONLY.sub("", text)


def _ipv6_valid(candidate: str) -> bool:
    """True if ``candidate`` (optionally with a ``%zone`` suffix) is a real IPv6 address."""
    core = candidate.split("%", 1)[0]
    try:
        ipaddress.IPv6Address(core)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class _Rule:
    entity_type: EntityType
    pattern: re.Pattern[str]
    # Optional checksum/format gate. Receives the (trimmed) matched text; returns True if
    # it passes. When present, only passing matches are emitted (and marked ``valid=True``).
    validator: Callable[[str], bool] | None = None
    # Trailing characters to strip from a match (e.g. sentence punctuation), with the span
    # end adjusted accordingly. Applied before the validator runs.
    trim_trailing: str = ""


# Order matters only for readability; overlap resolution happens in the redactor.
_RULES: tuple[_Rule, ...] = (
    _Rule(
        EntityType.EMAIL,
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    ),
    _Rule(
        EntityType.URL,
        re.compile(r"\bhttps?://[^\s<>\"')]+", re.IGNORECASE),
        trim_trailing=".,;:!?]}",  # don't swallow sentence punctuation into the URL
    ),
    _Rule(
        # North American phone formats, boundaried so it won't bite into longer digit
        # runs (cards, IBANs).
        EntityType.PHONE,
        re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"),
    ),
    _Rule(
        # International E.164-style numbers (country code != 1, which the NANP rule owns).
        EntityType.PHONE,
        re.compile(r"(?<!\d)\+(?!1\b)[1-9]\d{0,3}(?:[\s.\-]?\d){6,14}(?!\d)"),
    ),
    _Rule(
        # SSN, dashed or compact, with SSA-invalid area/group/serial ranges excluded.
        EntityType.US_SSN,
        re.compile(
            r"(?<!\d)(?!000|666|9\d\d)\d{3}"
            r"(?:-(?!00)\d{2}-(?!0000)\d{4}|(?!00)\d{2}(?!0000)\d{4})(?!\d)"
        ),
    ),
    _Rule(
        EntityType.CREDIT_CARD,
        re.compile(r"(?<!\d)\d(?:[ \-]?\d){12,18}(?!\d)"),
        validator=lambda m: luhn_valid(_digits(m)),
    ),
    _Rule(
        # Compact IBAN form (no internal spaces); the checksum gates precision.
        EntityType.IBAN,
        re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}[A-Za-z0-9]{11,30}(?![A-Za-z0-9])"),
        validator=iban_valid,
    ),
    _Rule(
        # Grouped/printed IBAN: blocks of four separated by single spaces, with a tight
        # 1-4 char tail so trailing prose isn't swallowed. The checksum still gates it.
        EntityType.IBAN,
        re.compile(
            r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}(?: [A-Za-z0-9]{4}){2,7}(?: [A-Za-z0-9]{1,4})?"
            r"(?![A-Za-z0-9])"
        ),
        validator=iban_valid,
    ),
    _Rule(
        EntityType.IP_ADDRESS,
        re.compile(
            r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])"
        ),
    ),
    _Rule(
        # IPv6 (compressed, full, IPv4-mapped, and %zone forms). A permissive candidate
        # gated by the stdlib parser, so MAC addresses and clock times are rejected.
        EntityType.IP_ADDRESS,
        re.compile(
            r"(?<![\w%.:])(?=[0-9A-Fa-f.]*:[0-9A-Fa-f.]*:)[0-9A-Fa-f:.]+(?:%[0-9A-Za-z._-]+)?"
        ),
        validator=_ipv6_valid,
        trim_trailing=".",
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
                start, end = match.start(), match.end()
                if rule.trim_trailing:
                    trimmed = matched.rstrip(rule.trim_trailing)
                    if not trimmed:
                        continue
                    end -= len(matched) - len(trimmed)
                    matched = trimmed
                valid: bool | None = None
                if rule.validator is not None:
                    if not rule.validator(matched):
                        continue  # checksum/format failed -> not this entity
                    valid = True
                spans.append(
                    Span(
                        start=start,
                        end=end,
                        entity_type=rule.entity_type,
                        text=matched,
                        score=1.0,
                        detector=self.name,
                        valid=valid,
                    )
                )
        return spans
