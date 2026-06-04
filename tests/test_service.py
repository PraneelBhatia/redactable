"""Tests for RedactionService — the shared core behind the MCP server, hook, and proxy.

It scrubs text (reversibly by default, so an LLM round-trip stays coherent) and restores
originals from a session keymap. This is the logic the integrations wrap; keeping it here
means the thin MCP/hook layers need no tests of their own.
"""

import pytest

from redactable.service import RedactionService


class TestScrubRestore:
    def test_reversible_round_trip(self):
        svc = RedactionService()
        out = svc.scrub("SSN 123-45-6789, email a@b.com", policy="pii-structured")
        assert "[US_SSN_1]" in out["redacted"]
        assert "[EMAIL_1]" in out["redacted"]
        assert "123-45-6789" not in out["redacted"]
        assert out["session"]
        # the model's reply might reference the tokens; restore brings the originals back
        restored = svc.restore("Use [EMAIL_1] for [US_SSN_1].", out["session"])
        assert restored == "Use a@b.com for 123-45-6789."

    def test_entities_summary(self):
        svc = RedactionService()
        out = svc.scrub("cards 4111 1111 1111 1111 and email x@y.io")
        assert out["entities"] == {"CREDIT_CARD": 1, "EMAIL": 1}

    def test_mask_mode_has_no_session(self):
        svc = RedactionService()
        out = svc.scrub("email a@b.com", reversible=False)
        assert out["redacted"] == "email [EMAIL]"
        assert out["session"] is None

    def test_restore_unknown_session_raises(self):
        with pytest.raises(KeyError):
            RedactionService().restore("anything", "nope")

    def test_clean_text_round_trips_unchanged(self):
        svc = RedactionService()
        out = svc.scrub("just some ordinary text")
        assert out["redacted"] == "just some ordinary text"
        assert out["entities"] == {}


class TestDetectPreview:
    def test_detect_reports_without_modifying(self):
        svc = RedactionService()
        res = svc.detect("ssn 123-45-6789 ip 10.0.0.1")
        assert res["total"] == 2
        assert res["found"]["US_SSN"] == 1
        assert res["found"]["IP_ADDRESS"] == 1
