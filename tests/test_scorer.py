"""Tests for the eval scorer — the heart of 'de-identification you can prove'.

Matching is type-aware relaxed-overlap with greedy 1:1 pairing: a gold entity is
recalled if a predicted span of the *same type* overlaps it. This mirrors how NER
de-identification is evaluated (did we cover the sensitive characters?) rather than
demanding exact byte boundaries.
"""

from redactable.eval.scorer import score
from redactable.span import EntityType, Span


def sp(start, end, t):
    return Span(start, end, t, "x" * (end - start))


class TestPerfectMatch:
    def test_all_recalled_and_precise(self):
        gold = [sp(0, 5, EntityType.PERSON), sp(10, 15, EntityType.EMAIL)]
        pred = [sp(0, 5, EntityType.PERSON), sp(10, 15, EntityType.EMAIL)]
        report = score([(gold, pred)])
        assert report.micro.recall == 1.0
        assert report.micro.precision == 1.0
        assert report.micro.f1 == 1.0


class TestMissedAndSpurious:
    def test_missed_gold_lowers_recall_only(self):
        gold = [sp(0, 5, EntityType.PERSON), sp(10, 15, EntityType.PERSON)]
        pred = [sp(0, 5, EntityType.PERSON)]  # missed the second
        report = score([(gold, pred)])
        person = report.per_entity["PERSON"]
        assert person.tp == 1 and person.fn == 1 and person.fp == 0
        assert person.recall == 0.5
        assert person.precision == 1.0

    def test_spurious_prediction_lowers_precision_only(self):
        gold = [sp(0, 5, EntityType.PERSON)]
        pred = [sp(0, 5, EntityType.PERSON), sp(20, 25, EntityType.PERSON)]  # invented one
        person = score([(gold, pred)]).per_entity["PERSON"]
        assert person.tp == 1 and person.fp == 1 and person.fn == 0
        assert person.recall == 1.0
        assert person.precision == 0.5


class TestMatchingSemantics:
    def test_overlap_counts_as_match(self):
        gold = [sp(2, 10, EntityType.PERSON)]
        pred = [sp(0, 6, EntityType.PERSON)]  # different boundaries, overlaps
        assert score([(gold, pred)]).per_entity["PERSON"].recall == 1.0

    def test_type_mismatch_is_not_a_match(self):
        gold = [sp(0, 5, EntityType.LOCATION)]
        pred = [sp(0, 5, EntityType.PERSON)]  # right place, wrong type
        report = score([(gold, pred)])
        assert report.per_entity["LOCATION"].recall == 0.0  # missed
        assert report.per_entity["PERSON"].precision == 0.0  # spurious

    def test_one_prediction_cannot_cover_two_gold(self):
        # Greedy 1:1: a single big prediction matches only one gold, the other is a miss.
        gold = [sp(0, 4, EntityType.PERSON), sp(5, 9, EntityType.PERSON)]
        pred = [sp(0, 9, EntityType.PERSON)]
        person = score([(gold, pred)]).per_entity["PERSON"]
        assert person.tp == 1 and person.fn == 1


class TestAggregation:
    def test_macro_averages_per_type_recall(self):
        # PERSON recall 1.0, EMAIL recall 0.0 -> macro recall 0.5
        gold = [sp(0, 5, EntityType.PERSON), sp(10, 15, EntityType.EMAIL)]
        pred = [sp(0, 5, EntityType.PERSON)]
        report = score([(gold, pred)])
        assert report.macro.recall == 0.5


class TestRegressionGate:
    def test_gate_fails_when_recall_below_threshold(self):
        gold = [sp(0, 5, EntityType.PERSON), sp(10, 15, EntityType.PERSON)]
        pred = [sp(0, 5, EntityType.PERSON)]  # recall 0.5
        report = score([(gold, pred)], thresholds={"PERSON": 0.9})
        assert report.gate_passed is False
        assert any(f.entity_type == "PERSON" for f in report.gate_failures)

    def test_gate_passes_when_recall_meets_threshold(self):
        gold = [sp(0, 5, EntityType.PERSON)]
        pred = [sp(0, 5, EntityType.PERSON)]  # recall 1.0
        report = score([(gold, pred)], thresholds={"PERSON": 0.9})
        assert report.gate_passed is True
        assert report.gate_failures == []

    def test_no_thresholds_means_no_gate(self):
        report = score([([sp(0, 5, EntityType.PERSON)], [])])
        assert report.gate_passed is None

    def test_gate_skips_thresholded_types_absent_from_corpus(self):
        # EMAIL has gold and is caught; US_SSN is thresholded but the corpus has no SSNs,
        # so recall is unmeasurable and must NOT count as a failure.
        gold = [sp(0, 5, EntityType.EMAIL)]
        pred = [sp(0, 5, EntityType.EMAIL)]
        report = score([(gold, pred)], thresholds={"EMAIL": 0.9, "US_SSN": 0.99})
        assert report.gate_passed is True
        assert report.gate_failures == []
