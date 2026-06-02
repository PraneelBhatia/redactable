"""Tests for the optional encoder-NER detector (GLiNER).

GLiNER itself (and its weights) are a heavy optional dependency, so the detector takes
an injectable model: these tests exercise the label-mapping, scoring, and span-building
logic with a fake, and the real model is validated by the same tiny contract. The point
of an *encoder* NER (vs a generative LLM) is that it returns offsets + scores it can't
hallucinate — so the detector's job is faithful translation, which is what we test.
"""

import importlib.util

import pytest

from redactable.detectors.ner import GlinerDetector
from redactable.span import EntityType


class FakeModel:
    """Stands in for a loaded GLiNER model."""

    def __init__(self, entities):
        self._entities = entities

    def predict_entities(self, text, labels, threshold=0.5):
        return [e for e in self._entities if e["score"] >= threshold]


class TestMapping:
    def test_maps_gliner_labels_to_entity_types(self):
        fake = FakeModel(
            [
                {"start": 5, "end": 15, "text": "Alice Chen", "label": "person", "score": 0.9},
                {"start": 19, "end": 25, "text": "Boston", "label": "location", "score": 0.8},
            ]
        )
        det = GlinerDetector(model=fake, threshold=0.0)
        spans = det.detect("call Alice Chen in Boston")
        by_type = {s.entity_type: s for s in spans}
        assert EntityType.PERSON in by_type
        assert EntityType.LOCATION in by_type
        assert by_type[EntityType.PERSON].text == "Alice Chen"

    def test_unknown_label_is_skipped(self):
        fake = FakeModel([{"start": 0, "end": 3, "text": "foo", "label": "misc", "score": 0.9}])
        det = GlinerDetector(model=fake, threshold=0.0)
        assert det.detect("foo bar") == []

    def test_score_and_provenance_carried(self):
        fake = FakeModel([{"start": 0, "end": 5, "text": "Alice", "label": "person", "score": 0.77}])
        span = GlinerDetector(model=fake, threshold=0.0).detect("Alice")[0]
        assert span.detector == "gliner"
        assert abs(span.score - 0.77) < 1e-9
        assert span.entity_type == EntityType.PERSON


class TestDependencyHandling:
    def test_clear_error_when_extra_missing(self):
        if importlib.util.find_spec("gliner") is not None:
            pytest.skip("gliner is installed; the missing-extra path can't be exercised here")
        with pytest.raises(ImportError, match=r"redactable\[ner\]"):
            GlinerDetector().detect("anything")
