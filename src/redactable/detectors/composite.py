"""CompositeDetector: run several detectors and pool their spans.

Overlap resolution between engines is the Redactor's job — the composite simply unions
the candidate spans, so the eval harness (which scores a single Detector) can measure a
whole stack (e.g. deterministic + GLiNER) as one engine.
"""

from __future__ import annotations

from collections.abc import Sequence

from redactable.detectors.base import Detector
from redactable.span import Span


class CompositeDetector:
    name = "composite"

    def __init__(self, detectors: Sequence[Detector]) -> None:
        self.detectors = list(detectors)

    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for detector in self.detectors:
            spans.extend(detector.detect(text))
        return spans
