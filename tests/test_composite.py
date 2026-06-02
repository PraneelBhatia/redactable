"""Tests for CompositeDetector — run several engines and pool their spans.

This is what lets the eval harness (which scores one Detector) benchmark a stack like
deterministic + GLiNER, and what powers the CLI's --ner flag.
"""

from redactable.detectors.composite import CompositeDetector
from redactable.span import EntityType, Span


class Stub:
    def __init__(self, name, spans):
        self.name = name
        self._spans = spans

    def detect(self, text):
        return list(self._spans)


def test_pools_spans_from_all_detectors():
    a = Stub("a", [Span(0, 5, EntityType.PERSON, "Alice")])
    b = Stub("b", [Span(6, 13, EntityType.EMAIL, "a@b.com")])
    spans = CompositeDetector([a, b]).detect("Alice a@b.com")
    assert {s.entity_type for s in spans} == {EntityType.PERSON, EntityType.EMAIL}


def test_has_composite_name_and_handles_empty():
    assert CompositeDetector([]).name == "composite"
    assert CompositeDetector([]).detect("x") == []
