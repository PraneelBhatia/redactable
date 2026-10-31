"""Scoring engine: turn (gold, predicted) spans into per-entity precision/recall/F1.

The gate uses type-aware full-span containment: touching part of a sensitive value
does not establish its removal. Exact-boundary and relaxed-overlap scores are
separate diagnostics. All three use maximum one-to-one matching.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from redactable.span import Span


@dataclass(frozen=True)
class EntityScore:
    """Confusion counts and derived metrics for a single entity type (or aggregate)."""

    entity_type: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def support(self) -> int:
        """Number of gold entities (tp + fn)."""
        return self.tp + self.fn

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass(frozen=True)
class GateFailure:
    entity_type: str
    recall: float | None
    threshold: float
    reason: str = "below_threshold"


@dataclass
class EvalReport:
    per_entity: dict[str, EntityScore]
    micro: EntityScore
    macro: EntityScore
    gate_passed: bool | None = None
    gate_failures: list[GateFailure] = field(default_factory=list)
    matching: str = "full_span"
    unmeasured_types: list[str] = field(default_factory=list)
    ungated_types: list[str] = field(default_factory=list)
    diagnostics: dict[str, dict[str, EntityScore]] = field(default_factory=dict)


def _match_type(golds: list[Span], preds: list[Span], mode: str) -> tuple[int, int, int]:
    """Maximum 1:1 matching, independent of span order. Returns (tp, fp, fn)."""
    def matches(gold: Span, pred: Span) -> bool:
        if mode == "exact":
            return gold.start == pred.start and gold.end == pred.end
        if mode == "relaxed_overlap":
            return gold.overlaps(pred)
        return pred.contains(gold)

    owners: dict[int, int] = {}

    def assign(g: int, seen: set[int]) -> bool:
        for p, pred in enumerate(preds):
            if p in seen or not matches(golds[g], pred):
                continue
            seen.add(p)
            if p not in owners or assign(owners[p], seen):
                owners[p] = g
                return True
        return False

    tp = sum(assign(g, set()) for g in range(len(golds)))
    fn = len(golds) - tp
    fp = len(preds) - tp
    return tp, fp, fn


def score(
    pairs: list[tuple[list[Span], list[Span]]],
    thresholds: dict[str, float] | None = None,
    expected_types: set[str] | None = None,
) -> EvalReport:
    """Score predictions against gold across a corpus.

    Args:
        pairs: one ``(gold_spans, predicted_spans)`` tuple per example/document.
        thresholds: optional ``{entity_type: min_recall}``. When provided, the report's
            missing gold support fails the gate with reason ``missing_support``.
        expected_types: policy scope to include in the coverage report, even when absent.
    """
    for threshold in (thresholds or {}).values():
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("recall thresholds must be finite numbers between 0 and 1")
    required = set(expected_types or ()) | set(thresholds or ())
    all_counts = {
        mode: {t: [0, 0, 0] for t in required}
        for mode in ("full_span", "exact", "relaxed_overlap")
    }

    for gold_spans, pred_spans in pairs:
        types = {str(s.entity_type) for s in gold_spans} | {str(s.entity_type) for s in pred_spans}
        for t in types:
            golds = [s for s in gold_spans if str(s.entity_type) == t]
            preds = [s for s in pred_spans if str(s.entity_type) == t]
            for mode, counts in all_counts.items():
                tp, fp, fn = _match_type(golds, preds, mode)
                bucket = counts.setdefault(t, [0, 0, 0])
                bucket[0] += tp
                bucket[1] += fp
                bucket[2] += fn

    counts = all_counts["full_span"]
    per_entity = {
        t: EntityScore(entity_type=t, tp=c[0], fp=c[1], fn=c[2]) for t, c in sorted(counts.items())
    }

    total_tp = sum(c[0] for c in counts.values())
    total_fp = sum(c[1] for c in counts.values())
    total_fn = sum(c[2] for c in counts.values())
    micro = EntityScore("micro", total_tp, total_fp, total_fn)

    # Macro = unweighted mean of per-type metrics (every entity type counts equally).
    # F1 is the mean of per-type F1s — NOT the harmonic mean of the mean P and mean R,
    # which inflates the score when precision and recall are asymmetric across types.
    n = len(per_entity) or 1
    macro_p = sum(s.precision for s in per_entity.values()) / n
    macro_r = sum(s.recall for s in per_entity.values()) / n
    macro_f1 = sum(s.f1 for s in per_entity.values()) / n
    macro = _MacroScore(precision=macro_p, recall=macro_r, f1=macro_f1)

    report = EvalReport(
        per_entity=per_entity, micro=micro, macro=macro,
        unmeasured_types=sorted(t for t in required if per_entity[t].support == 0),
        ungated_types=sorted(set(per_entity) - set(thresholds or ())),
        diagnostics={
            mode: {t: EntityScore(t, *c) for t, c in sorted(buckets.items())}
            for mode, buckets in all_counts.items() if mode != "full_span"
        },
    )

    if thresholds:
        failures = [
            GateFailure(
                t, per_entity[t].recall if per_entity[t].support else None, thr,
                "below_threshold" if per_entity[t].support else "missing_support",
            )
            for t, thr in thresholds.items()
            if per_entity[t].support == 0 or per_entity[t].recall < thr
        ]
        report.gate_failures = failures
        report.gate_passed = not failures

    return report


@dataclass(frozen=True)
class _MacroScore:
    """Macro aggregate: every field is the unweighted mean of the per-type metric."""

    precision: float
    recall: float
    f1: float = 0.0
    entity_type: str = "macro"
