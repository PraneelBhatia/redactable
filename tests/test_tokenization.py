"""Tests for the transformation layer: mask / tokenize / hash.

Tokenization is what keeps de-identified data *useful*: the same original value maps
to the same placeholder (joinable), and under a keymap it is reversible (re-identifiable
by authorized parties). Masking is the irreversible simple case; hashing is consistent
pseudonymization.
"""

from redactable.span import EntityType, Span
from redactable.tokenization import Tokenizer


def person(start, end, text):
    return Span(start, end, EntityType.PERSON, text)


class TestMask:
    def test_replaces_with_bare_type_label(self):
        text = "Hi Alice, meet Bob"
        spans = [person(3, 8, "Alice"), person(15, 18, "Bob")]
        result = Tokenizer(strategy="mask").apply(text, spans)
        assert result.text == "Hi [PERSON], meet [PERSON]"
        assert result.keymap == {}


class TestTokenize:
    def test_consistent_placeholders_same_value_same_token(self):
        text = "Alice called Alice"
        spans = [person(0, 5, "Alice"), person(13, 18, "Alice")]
        result = Tokenizer(strategy="tokenize").apply(text, spans)
        assert result.text == "[PERSON_1] called [PERSON_1]"
        assert result.keymap == {"[PERSON_1]": "Alice"}

    def test_distinct_values_increment_per_type(self):
        text = "Alice emailed a@b.com and Bob"
        spans = [
            person(0, 5, "Alice"),
            Span(14, 21, EntityType.EMAIL, "a@b.com"),
            person(26, 29, "Bob"),
        ]
        result = Tokenizer(strategy="tokenize").apply(text, spans)
        assert result.text == "[PERSON_1] emailed [EMAIL_1] and [PERSON_2]"

    def test_reverse_restores_original(self):
        text = "Contact Alice or Bob"
        spans = [person(8, 13, "Alice"), person(17, 20, "Bob")]
        tok = Tokenizer(strategy="tokenize")
        result = tok.apply(text, spans)
        assert tok.reverse(result.text, result.keymap) == text


class TestHash:
    def test_same_value_hashes_consistently_different_values_differ(self):
        text = "Alice and Alice and Carol"
        spans = [person(0, 5, "Alice"), person(10, 15, "Alice"), person(20, 25, "Carol")]
        result = Tokenizer(strategy="hash", salt=b"pepper").apply(text, spans)
        tokens = result.text.split(" and ")
        assert tokens[0] == tokens[1]  # Alice == Alice
        assert tokens[0] != tokens[2]  # Alice != Carol
        assert tokens[0].startswith("[PERSON_") and tokens[0].endswith("]")


class TestOffsetsAndOrdering:
    def test_handles_unsorted_spans_and_length_changes(self):
        # Spans given out of order; replacements differ in length from originals.
        text = "x Alice y Bob z"
        spans = [person(10, 13, "Bob"), person(2, 7, "Alice")]
        result = Tokenizer(strategy="mask").apply(text, spans)
        assert result.text == "x [PERSON] y [PERSON] z"

    def test_overlapping_spans_keep_first_and_skip_overlap(self):
        text = "Alice"
        spans = [person(0, 5, "Alice"), person(0, 3, "Ali")]  # overlap
        result = Tokenizer(strategy="mask").apply(text, spans)
        assert result.text == "[PERSON]"


class TestReverseRobustness:
    def test_reverse_does_not_re_consume_a_restored_value(self):
        # A restored original containing another token literal must survive intact.
        keymap = {"[URL_1]": "http://x.io/[EMAIL_1]", "[EMAIL_1]": "a@b.com"}
        text = "See [URL_1] and mail [EMAIL_1]"
        assert Tokenizer.reverse(text, keymap) == "See http://x.io/[EMAIL_1] and mail a@b.com"

    def test_reverse_is_order_independent(self):
        keymap = {"[PERSON_2]": "[PERSON_1]", "[PERSON_1]": "Alice"}
        assert Tokenizer.reverse("[PERSON_2] met [PERSON_1]", keymap) == "[PERSON_1] met Alice"


class TestStrategyCacheIsolation:
    def test_same_value_under_different_strategy_is_not_cross_contaminated(self):
        tok = Tokenizer(strategy="tokenize")
        span = person(0, 5, "Alice")
        first = tok.apply("Alice", [span]).text
        tok.strategy = "hash"
        second = tok.apply("Alice", [span]).text
        assert first == "[PERSON_1]"
        assert second != "[PERSON_1]"  # the hash strategy must not reuse the tokenize token
        assert second.startswith("[PERSON_")


class TestReprSafety:
    def test_result_repr_hides_keymap_originals(self):
        result = Tokenizer(strategy="tokenize").apply("Alice", [person(0, 5, "Alice")])
        assert "Alice" not in repr(result)
