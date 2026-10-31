"""Full-span gates, exact/relaxed diagnostics, and explicit corpus coverage."""

import pytest

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
    @pytest.mark.parametrize("start,end", [(2, 3), (2, 9), (3, 10), (0, 6)])
    def test_partial_overlap_does_not_pass_gate(self, start, end):
        gold = [sp(2, 10, EntityType.PERSON)]
        pred = [sp(start, end, EntityType.PERSON)]
        report = score([(gold, pred)], thresholds={"PERSON": 1.0})
        assert report.per_entity["PERSON"].recall == 0.0
        assert report.gate_passed is False
        assert report.diagnostics["relaxed_overlap"]["PERSON"].recall == 1.0

    def test_complete_larger_span_is_not_an_exact_match(self):
        report = score([([sp(2, 10, EntityType.PERSON)], [sp(0, 12, EntityType.PERSON)])])
        assert report.micro.recall == 1.0
        assert report.diagnostics["exact"]["PERSON"].recall == 0.0

    @pytest.mark.parametrize("second_start", [5, 6])
    def test_split_spans_do_not_receive_full_entity_credit(self, second_start):
        report = score([([sp(0, 10, EntityType.PERSON)],
                         [sp(0, 5, EntityType.PERSON), sp(second_start, 10, EntityType.PERSON)])])
        assert report.micro.recall == 0.0

    def test_maximum_matching_does_not_depend_on_greedy_order(self):
        gold = [sp(0, 5, EntityType.PERSON), sp(6, 10, EntityType.PERSON)]
        pred = [sp(0, 10, EntityType.PERSON), sp(0, 5, EntityType.PERSON)]
        assert score([(gold, pred)]).micro.recall == 1.0

    def test_duplicate_prediction_is_a_false_positive(self):
        s = sp(0, 5, EntityType.PERSON)
        assert score([([s], [s, s])]).micro.fp == 1

    def test_repeated_values_are_matched_by_position(self):
        gold = [sp(0, 5, EntityType.PERSON), sp(6, 11, EntityType.PERSON)]
        assert score([(gold, [gold[0]])]).micro.recall == 0.5

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

    def test_macro_f1_is_mean_of_per_type_f1_not_harmonic_of_means(self):
        # EMAIL: P=1.0 R=0.5 F1=0.667 ; PHONE: P=0.5 R=1.0 F1=0.667 -> macro F1 = 0.667
        # (the buggy harmonic-of-means would give 0.75).
        gold = [sp(0, 5, EntityType.EMAIL), sp(10, 15, EntityType.EMAIL), sp(20, 25, EntityType.PHONE)]
        pred = [sp(0, 5, EntityType.EMAIL), sp(20, 25, EntityType.PHONE), sp(30, 35, EntityType.PHONE)]
        report = score([(gold, pred)])
        assert abs(report.macro.f1 - 2 / 3) < 1e-6


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

    def test_gate_fails_for_thresholded_types_absent_from_corpus(self):
        gold = [sp(0, 5, EntityType.EMAIL)]
        pred = [sp(0, 5, EntityType.EMAIL)]
        report = score([(gold, pred)], thresholds={"EMAIL": 0.9, "US_SSN": 0.99})
        assert report.gate_passed is False
        assert report.unmeasured_types == ["US_SSN"]
        assert report.gate_failures[0].reason == "missing_support"
        assert report.gate_failures[0].recall is None

    @pytest.mark.parametrize("pairs", [[], [([], [])], [([], [sp(0, 5, EntityType.EMAIL)])]])
    def test_empty_or_negative_only_corpus_cannot_pass(self, pairs):
        report = score(pairs, thresholds={"EMAIL": 0.0})
        assert report.gate_passed is False
        assert report.gate_failures[0].reason == "missing_support"

    @pytest.mark.parametrize("threshold", [float("nan"), float("inf"), -0.1, 1.1])
    def test_invalid_threshold_rejected(self, threshold):
        with pytest.raises(ValueError, match="thresholds"):
            score([], thresholds={"EMAIL": threshold})

    def test_policy_coverage_reports_ungated_and_unmeasured_types(self):
        report = score([], thresholds={"EMAIL": 0.9}, expected_types={"EMAIL", "DATE"})
        assert report.unmeasured_types == ["DATE", "EMAIL"]
        assert report.ungated_types == ["DATE"]
