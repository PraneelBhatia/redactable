"""Tests for the local-LLM contextual detector (Gemma via Ollama / OpenAI-compatible).

The model call is injected (``transport``), so the mapping/locating/parsing logic is tested
without a live server. Like the browser tier, it must tolerate the malformed JSON small
models emit, and it must never trust model-reported offsets — it locates the substring itself.
"""

from redactable.detectors.llm import LlmDetector, extract_entities_json
from redactable.span import EntityType


class TestExtractEntitiesJson:
    def test_recovers_from_stray_brace(self):
        raw = '[{"text":"Sarah Chen","label":"person"} }]'  # the exact failure Gemma-4 produced
        items = extract_entities_json(raw)
        assert {"text": "Sarah Chen", "label": "person"} in items

    def test_handles_label_first_order(self):
        items = extract_entities_json('[{"label":"location","text":"Boston"}]')
        assert items == [{"text": "Boston", "label": "location"}]

    def test_empty_on_garbage(self):
        assert extract_entities_json("I cannot help with that.") == []


class TestLlmDetector:
    def test_maps_labels_and_locates_offsets(self):
        raw = '[{"text":"Sarah Chen","label":"person"},{"text":"Boston","label":"location"}]'
        det = LlmDetector(transport=lambda prompt: raw)
        text = "Dr. Sarah Chen practices in Boston."
        spans = {s.entity_type: s for s in det.detect(text)}
        assert spans[EntityType.PERSON].text == "Sarah Chen"
        assert text[spans[EntityType.PERSON].start : spans[EntityType.PERSON].end] == "Sarah Chen"
        assert EntityType.LOCATION in spans

    def test_tolerates_malformed_json_end_to_end(self):
        det = LlmDetector(transport=lambda p: '[{"text":"Sarah Chen","label":"person"} }]')
        assert any(s.entity_type == EntityType.PERSON for s in det.detect("Sarah Chen here"))

    def test_unknown_label_skipped(self):
        det = LlmDetector(transport=lambda p: '[{"text":"foo","label":"misc"}]')
        assert det.detect("foo bar") == []

    def test_hallucinated_span_not_in_text_is_dropped(self):
        det = LlmDetector(transport=lambda p: '[{"text":"Nowhere City","label":"location"}]')
        assert det.detect("this text has no such place") == []

    def test_provenance_and_softness(self):
        det = LlmDetector(transport=lambda p: '[{"text":"Ann","label":"person"}]')
        span = det.detect("Ann waved")[0]
        assert span.detector == "llm"
        assert span.valid is None  # generative output is never asserted as checksum-valid
        assert 0.0 < span.score < 1.0

    def test_has_a_name(self):
        assert LlmDetector(transport=lambda p: "[]").name == "llm"
