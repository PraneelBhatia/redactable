"""Tests for the Redactor orchestrator.

The redactor turns raw text into redacted text + an audit manifest: it runs detectors,
resolves overlaps (a high-confidence checksum-valid span beats a weak guess), drops
out-of-scope types, applies the policy's per-entity action, and records what it did
without ever putting original values in the manifest.
"""

from redactable.policy import Policy
from redactable.redactor import Redactor
from redactable.span import EntityType, Span


class StubDetector:
    name = "stub"

    def __init__(self, spans):
        self._spans = spans

    def detect(self, text):
        return list(self._spans)


def write_policy(tmp_path, body):
    p = tmp_path / "p.yaml"
    p.write_text(body)
    return str(p)


class TestEndToEndWithHipaa:
    def test_masks_email_and_ssn(self):
        r = Redactor.from_policy("hipaa-safe-harbor")
        out = r.redact("Email a@b.com SSN 123-45-6789")
        assert out.text == "Email [EMAIL] SSN [US_SSN]"

    def test_manifest_records_counts_without_leaking_originals(self):
        r = Redactor.from_policy("hipaa-safe-harbor")
        out = r.redact("Email a@b.com SSN 123-45-6789")
        m = out.manifest
        assert m["policy"]["name"] == "hipaa-safe-harbor"
        assert m["entity_counts"] == {"EMAIL": 1, "US_SSN": 1}
        assert m["total_redactions"] == 2
        assert "engine_version" in m and "input_sha256" in m
        # The manifest must not contain the raw PII.
        assert "a@b.com" not in repr(m)
        assert "123-45-6789" not in repr(m)


class TestOverlapResolution:
    def test_higher_confidence_span_wins_overlap(self):
        spans = [
            Span(0, 5, EntityType.PERSON, "Alice", score=0.5, detector="ner"),
            Span(0, 5, EntityType.EMAIL, "Alice", score=1.0, detector="deterministic"),
        ]
        pol = Policy.load("hipaa-safe-harbor")
        r = Redactor(detectors=[StubDetector(spans)], policy=pol)
        out = r.redact("Alice")
        assert out.text == "[EMAIL]"  # the score-1.0 span won
        assert len(out.spans) == 1


class TestScopeAndActions:
    def test_out_of_scope_type_is_left_intact(self, tmp_path):
        body = "name: only-email\nversion: 1\ndefault_action: mask\nentities:\n  EMAIL:\n    action: mask\n"
        pol = Policy.load(write_policy(tmp_path, body))
        # Deterministic detector would also find the URL, but the policy only scopes EMAIL.
        r = Redactor.from_policy(pol)
        out = r.redact("see https://x.io and a@b.com")
        assert "https://x.io" in out.text  # URL untouched (out of scope)
        assert "[EMAIL]" in out.text

    def test_per_entity_actions_mixed(self, tmp_path):
        body = (
            "name: mixed\nversion: 1\ndefault_action: mask\n"
            "entities:\n  PERSON:\n    action: tokenize\n  EMAIL:\n    action: mask\n"
        )
        pol = Policy.load(write_policy(tmp_path, body))
        spans = [
            Span(0, 5, EntityType.PERSON, "Alice"),
            Span(9, 16, EntityType.EMAIL, "a@b.com"),
        ]
        r = Redactor(detectors=[StubDetector(spans)], policy=pol)
        out = r.redact("Alice at a@b.com")
        assert out.text == "[PERSON_1] at [EMAIL]"
        assert out.keymap == {"[PERSON_1]": "Alice"}
