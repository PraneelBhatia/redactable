"""Tests for deterministic checksum validators.

Vectors are well-known public test values (payment-network test numbers, the
classic Luhn example, published valid routing/IBAN samples). A checksum is the
whole point of "deterministic-first": these must be exactly right, not approximately.
"""

from redactable.checksums import aba_routing_valid, iban_valid, luhn_valid


class TestLuhn:
    def test_known_valid_card_numbers(self):
        assert luhn_valid("4111111111111111")  # Visa test
        assert luhn_valid("5500005555555559")  # MasterCard test
        assert luhn_valid("79927398713")  # classic Luhn textbook example

    def test_known_invalid_card_numbers(self):
        assert not luhn_valid("4111111111111112")
        assert not luhn_valid("79927398714")

    def test_empty_or_nondigit_is_invalid(self):
        assert not luhn_valid("")
        assert not luhn_valid("abcd")

    def test_single_digit_zero_is_valid_but_too_short_handled_by_caller(self):
        # The checksum itself: "0" sums to 0 -> divisible by 10. Length policy is the
        # detector's job, not the checksum's.
        assert luhn_valid("0")


class TestIban:
    def test_known_valid_ibans(self):
        assert iban_valid("GB82WEST12345698765432")
        assert iban_valid("DE89370400440532013000")
        # Whitespace/case tolerance (printed IBANs are grouped in fours).
        assert iban_valid("gb82 west 1234 5698 7654 32")

    def test_known_invalid_ibans(self):
        assert not iban_valid("GB82WEST12345698765433")  # last digit changed
        assert not iban_valid("DE00370400440532013000")  # bad check digits

    def test_malformed_is_invalid(self):
        assert not iban_valid("")
        assert not iban_valid("XX")  # too short, no body


class TestAbaRouting:
    def test_known_valid_routing_numbers(self):
        assert aba_routing_valid("021000021")  # JPMorgan Chase
        assert aba_routing_valid("011401533")  # valid sample

    def test_known_invalid_routing_numbers(self):
        assert not aba_routing_valid("021000022")
        assert not aba_routing_valid("123456789")

    def test_wrong_length_is_invalid(self):
        assert not aba_routing_valid("02100002")  # 8 digits
        assert not aba_routing_valid("0210000210")  # 10 digits
        assert not aba_routing_valid("")
