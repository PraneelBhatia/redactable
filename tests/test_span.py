"""Tests for the core data model: EntityType and Span."""

import pytest

from redactable.span import EntityType, Span


class TestEntityType:
    def test_core_structured_types_exist(self):
        # Structured identifiers handled deterministically.
        for name in ["EMAIL", "PHONE", "US_SSN", "CREDIT_CARD", "IBAN", "IP_ADDRESS"]:
            assert hasattr(EntityType, name)

    def test_core_contextual_types_exist(self):
        # Contextual identifiers handled by NER.
        for name in ["PERSON", "LOCATION", "ORG"]:
            assert hasattr(EntityType, name)

    def test_entity_type_is_its_string_value(self):
        # StrEnum: comparing to the bare string works (ergonomic in policies/JSON).
        assert EntityType.EMAIL == "EMAIL"
        assert str(EntityType.PERSON) == "PERSON"

    def test_from_string_roundtrip(self):
        assert EntityType("EMAIL") is EntityType.EMAIL


class TestSpan:
    def test_construction_and_fields(self):
        s = Span(start=8, end=15, entity_type=EntityType.EMAIL, text="a@b.com")
        assert s.start == 8
        assert s.end == 15
        assert s.entity_type == EntityType.EMAIL
        assert s.text == "a@b.com"
        # Sensible defaults.
        assert s.score == 1.0
        assert s.detector == ""
        assert s.valid is None

    def test_length(self):
        assert Span(0, 5, EntityType.PERSON, "Alice").length == 5

    def test_rejects_non_positive_length(self):
        with pytest.raises(ValueError):
            Span(5, 5, EntityType.EMAIL, "")
        with pytest.raises(ValueError):
            Span(7, 3, EntityType.EMAIL, "x")

    def test_rejects_negative_start(self):
        with pytest.raises(ValueError):
            Span(-1, 3, EntityType.EMAIL, "x")

    def test_rejects_score_out_of_range(self):
        with pytest.raises(ValueError):
            Span(0, 1, EntityType.EMAIL, "x", score=1.5)
        with pytest.raises(ValueError):
            Span(0, 1, EntityType.EMAIL, "x", score=-0.1)

    def test_is_frozen(self):
        s = Span(0, 1, EntityType.EMAIL, "x")
        with pytest.raises(Exception):
            s.start = 9  # type: ignore[misc]

    def test_overlaps_is_symmetric_and_half_open(self):
        a = Span(0, 5, EntityType.PERSON, "Alice")
        b = Span(3, 8, EntityType.PERSON, "iceXX")
        c = Span(5, 9, EntityType.EMAIL, "abcd")  # touches a at 5 but half-open => no overlap
        assert a.overlaps(b) and b.overlaps(a)
        assert not a.overlaps(c)
        assert not c.overlaps(a)

    def test_contains_other(self):
        outer = Span(0, 10, EntityType.PERSON, "0123456789")
        inner = Span(2, 5, EntityType.PERSON, "234")
        assert outer.contains(inner)
        assert not inner.contains(outer)
