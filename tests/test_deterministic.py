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


class TestRecallGapsClosed:
    """Regression tests for formats the first cut silently missed (found by review)."""

    def test_compact_ssn_without_dashes(self):
        assert EntityType.US_SSN in types_found("SSN 123456789 on file")
        # the dashed form must still work
        assert EntityType.US_SSN in types_found("dashed 123-45-6789 here")

    def test_compact_ssn_excludes_invalid_areas(self):
        assert EntityType.US_SSN not in types_found("000121234")  # area 000
        assert EntityType.US_SSN not in types_found("900121234")  # area 9xx

    def test_ipv6_addresses_detected(self):
        for ip in [
            "2001:db8::1",
            "fe80::1%eth0",
            "2001:0db8:85a3:0000:0000:8a2e:0370:7334",
            "::ffff:192.0.2.1",
        ]:
            assert EntityType.IP_ADDRESS in types_found(f"host {ip} end"), ip

    def test_ipv6_trailing_period_not_captured(self):
        assert find_one("ping 2001:db8::1.", EntityType.IP_ADDRESS).text == "2001:db8::1"

    def test_mac_and_clock_time_not_mistaken_for_ipv6(self):
        assert EntityType.IP_ADDRESS not in types_found("mac 01:23:45:67:89:ab here")
        assert EntityType.IP_ADDRESS not in types_found("meeting at 12:34:56 today")

    def test_ipv4_still_detected(self):
        assert find_one("from 192.168.0.1 today", EntityType.IP_ADDRESS).text == "192.168.0.1"

    def test_spaced_grouped_iban_detected_without_swallowing_prose(self):
        span = find_one("remit to GB82 WEST 1234 5698 7654 32 by Friday.", EntityType.IBAN)
        assert span.text == "GB82 WEST 1234 5698 7654 32"
        assert span.valid is True

    def test_international_phone_numbers_detected(self):
        assert EntityType.PHONE in types_found("ring +44 7911 123456 now")
        assert EntityType.PHONE in types_found("call +49 30 1234567 please")

    def test_url_trailing_sentence_punctuation_trimmed(self):
        assert find_one("see https://example.com/path. Next", EntityType.URL).text == (
            "https://example.com/path"
        )

    def test_ipv4_at_end_of_sentence_detected(self):
        # Found via the ai4privacy benchmark: an IPv4 ending a sentence was being dropped.
        assert find_one("from 215.114.180.213. As noted", EntityType.IP_ADDRESS).text == (
            "215.114.180.213"
        )
        assert find_one("logged 88.129.163.16.", EntityType.IP_ADDRESS).text == "88.129.163.16"

    def test_ipv4_not_partially_matched_in_five_group(self):
        # A malformed 5-group dotted number must not yield a partial IPv4.
        assert EntityType.IP_ADDRESS not in types_found("build 1.2.3.4.5 here")

    def test_ssn_space_separated_detected(self):
        # ai4privacy includes space-separated US SSNs (e.g. "838 44 5162").
        assert find_one("ssn 838 44 5162 on file", EntityType.US_SSN).text == "838 44 5162"
