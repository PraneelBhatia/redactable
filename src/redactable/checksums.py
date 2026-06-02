"""Deterministic checksum validators for structured identifiers.

These are the reason Redactable is "deterministic-first": a Luhn or MOD-97 check
gives a provable yes/no that no probabilistic model can match. Each function is a
pure, total function over its input string and never raises on bad input — it
returns ``False`` so detectors can call it freely on candidate matches.
"""

from __future__ import annotations

import string


def luhn_valid(digits: str) -> bool:
    """Validate a number string with the Luhn (mod-10) algorithm.

    Expects digits only (the caller strips spaces/dashes). Used for credit-card
    candidates. Returns ``False`` for empty or non-digit input.
    """
    if not digits or not digits.isdigit():
        return False
    total = 0
    # Double every second digit from the right.
    for index, char in enumerate(reversed(digits)):
        value = ord(char) - 48  # faster than int(char), and we know it's a digit
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def iban_valid(iban: str) -> bool:
    """Validate an IBAN using the ISO 13616 / ISO 7064 MOD-97-10 check.

    Tolerates the conventional printed grouping (spaces) and lowercase. An IBAN is
    valid when, after moving the first four characters to the end and replacing each
    letter with its position value (A=10 .. Z=35), the resulting integer mod 97 == 1.
    """
    compact = iban.replace(" ", "").upper()
    # Basic structural sanity: 2-letter country, 2 check digits, then a body.
    if len(compact) < 5 or len(compact) > 34:
        return False
    if not (compact[:2].isalpha() and compact[2:4].isdigit()):
        return False
    if not all(c in string.ascii_uppercase + string.digits for c in compact):
        return False

    rearranged = compact[4:] + compact[:4]
    # Convert to the numeric string: letters -> two-digit codes.
    converted = []
    for char in rearranged:
        if char.isdigit():
            converted.append(char)
        else:
            converted.append(str(ord(char) - 55))  # 'A' (65) -> 10
    return int("".join(converted)) % 97 == 1


def aba_routing_valid(number: str) -> bool:
    """Validate a US ABA routing number (9 digits) with its weighted mod-10 checksum.

    Checksum: 3·(d1+d4+d7) + 7·(d2+d5+d8) + 1·(d3+d6+d9) ≡ 0 (mod 10).
    """
    if len(number) != 9 or not number.isdigit():
        return False
    weights = (3, 7, 1, 3, 7, 1, 3, 7, 1)
    total = sum(w * (ord(d) - 48) for w, d in zip(weights, number))
    return total % 10 == 0
