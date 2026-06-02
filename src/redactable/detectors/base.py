"""The detector interface every engine implements.

A ``Detector`` is the seam that makes the eval harness honest: because *any* engine
(our deterministic detector, GLiNER, Presidio, a cloud API) satisfies the same tiny
contract, the scorer can benchmark them all on one corpus and you can swap engines
without touching the redactor.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from redactable.span import Span


@runtime_checkable
class Detector(Protocol):
    """Turns source text into a list of detected spans."""

    @property
    def name(self) -> str:
        """Short, stable identifier used for span provenance and audit manifests."""
        ...

    def detect(self, text: str) -> list[Span]:
        """Return all entity spans found in ``text``. Must not raise on ordinary input."""
        ...
