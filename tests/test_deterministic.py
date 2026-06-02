"""Tests for the deterministic regex+checksum detector.

The contract: exact offsets, confidence 1.0, and checksum-bearing types
(card/IBAN/routing) are *gated* — a candidate that fails its checksum is NOT
emitted, because emitting a known-invalid identifier is a false positive.
"""

from redactable.detectors.deterministic import DeterministicDetector
from redactable.span import EntityType


def types_found(text):
    det = DeterministicDetector()
    return {s.entity_type for s in det.detect(text)}


def find_one(text, entity_type):
    det = DeterministicDetector()
    matches = [s for s in det.detect(text) if s.entity_type == entity_type]
    assert len(matches) == 1, f"expected exactly one {entity_type}, got {matches}"
    return matches[0]


class TestEmail:
    def test_detects_email_with_exact_offsets(self):
        text = "ping me at jane.doe@acme.io ok"
        span = find_one(text, EntityType.EMAIL)
        assert span.text == "jane.doe@acme.io"
        assert text[span.start : span.end] == "jane.doe@acme.io"
        assert span.score == 1.0
        assert span.detector == "deterministic"


class TestPhone:
    def test_detects_us_phone_formats(self):
        assert find_one("call (212) 555-0188 now", EntityType.PHONE).text == "(212) 555-0188"
        assert find_one("ph: 212-555-0188.", EntityType.PHONE).text == "212-555-0188"
        assert find_one("+1 212 555 0188", EntityType.PHONE).text == "+1 212 555 0188"


class TestSsn:
    def test_detects_valid_ssn(self):
        span = find_one("SSN 123-45-6789 on file", EntityType.US_SSN)
        assert span.text == "123-45-6789"

    def test_excludes_invalid_ssn_area_numbers(self):
        # 000, 666, and 900-999 are never valid SSN area numbers.
        assert EntityType.US_SSN not in types_found("000-12-3456")
        assert EntityType.US_SSN not in types_found("666-12-3456")
        assert EntityType.US_SSN not in types_found("900-12-3456")


class TestCreditCard:
    def test_luhn_valid_card_is_detected_and_marked_valid(self):
        span = find_one("card 4111 1111 1111 1111 exp", EntityType.CREDIT_CARD)
        assert span.text == "4111 1111 1111 1111"
        assert span.valid is True

    def test_luhn_invalid_card_is_not_emitted(self):
        # 16 digits that fail Luhn must not be flagged as a card (false positive).
        assert EntityType.CREDIT_CARD not in types_found("num 4111 1111 1111 1112 end")


class TestIban:
    def test_valid_iban_detected_and_marked_valid(self):
        span = find_one("IBAN GB82WEST12345698765432 please", EntityType.IBAN)
        assert span.text == "GB82WEST12345698765432"
        assert span.valid is True

    def test_invalid_iban_not_emitted(self):
        assert EntityType.IBAN not in types_found("IBAN GB82WEST12345698765433 please")


class TestIpAddress:
    def test_valid_ipv4_detected(self):
        assert find_one("from 192.168.0.1 today", EntityType.IP_ADDRESS).text == "192.168.0.1"

    def test_octets_over_255_rejected(self):
        assert EntityType.IP_ADDRESS not in types_found("addr 999.1.1.1 nope")


class TestUrl:
    def test_detects_http_url(self):
        assert find_one("see https://example.com/x?y=1 here", EntityType.URL).text == (
            "https://example.com/x?y=1"
        )


class TestMixedAndProvenance:
    def test_multiple_entities_in_one_text(self):
        text = "Email a@b.com or call 212-555-0188; SSN 123-45-6789."
        found = types_found(text)
        assert {EntityType.EMAIL, EntityType.PHONE, EntityType.US_SSN} <= found

    def test_no_false_positive_on_plain_prose(self):
        det = DeterministicDetector()
        assert det.detect("The quick brown fox jumps over the lazy dog.") == []

    def test_detector_has_a_name(self):
        assert DeterministicDetector().name == "deterministic"
