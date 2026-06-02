"""Scoring engine: turn (gold, predicted) spans into per-entity precision/recall/F1.

This is the asset competitors can't clone in a weekend: a reproducible number for
how much PII a given engine actually catches, per entity type, with a gate that
fails CI on regression. Matching is *type-aware relaxed overlap* with greedy 1:1
pairing — the standard way de-identification recall is measured.
"""

from __future__ import annotations

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
    recall: float
    threshold: float


@dataclass
class EvalReport:
    per_entity: dict[str, EntityScore]
    micro: EntityScore
    macro: EntityScore
    gate_passed: bool | None = None
    gate_failures: list[GateFailure] = field(default_factory=list)


def _match_type(golds: list[Span], preds: list[Span]) -> tuple[int, int, int]:
    """Greedy 1:1 overlap matching within one entity type. Returns (tp, fp, fn)."""
    matched_preds: set[int] = set()
    tp = 0
    for gold in golds:
        for i, pred in enumerate(preds):
            if i in matched_preds:
                continue
            if gold.overlaps(pred):
                matched_preds.add(i)
                tp += 1
                break
    fn = len(golds) - tp
    fp = len(preds) - len(matched_preds)
    return tp, fp, fn


def score(
    pairs: list[tuple[list[Span], list[Span]]],
    thresholds: dict[str, float] | None = None,
) -> EvalReport:
    """Score predictions against gold across a corpus.

    Args:
        pairs: one ``(gold_spans, predicted_spans)`` tuple per example/document.
        thresholds: optional ``{entity_type: min_recall}``. When provided, the report's
            ``gate_passed`` is set and any entity below its threshold is a ``GateFailure``.
    """
    counts: dict[str, list[int]] = {}  # type -> [tp, fp, fn]

    for gold_spans, pred_spans in pairs:
        types = {str(s.entity_type) for s in gold_spans} | {str(s.entity_type) for s in pred_spans}
        for t in types:
            golds = [s for s in gold_spans if str(s.entity_type) == t]
            preds = [s for s in pred_spans if str(s.entity_type) == t]
            tp, fp, fn = _match_type(golds, preds)
            bucket = counts.setdefault(t, [0, 0, 0])
            bucket[0] += tp
            bucket[1] += fp
            bucket[2] += fn

    per_entity = {
        t: EntityScore(entity_type=t, tp=c[0], fp=c[1], fn=c[2]) for t, c in sorted(counts.items())
    }

    total_tp = sum(c[0] for c in counts.values())
    total_fp = sum(c[1] for c in counts.values())
    total_fn = sum(c[2] for c in counts.values())
    micro = EntityScore("micro", total_tp, total_fp, total_fn)

    # Macro = unweighted mean of per-type metrics (every entity type counts equally).
    n = len(per_entity) or 1
    macro_p = sum(s.precision for s in per_entity.values()) / n
    macro_r = sum(s.recall for s in per_entity.values()) / n
    # Store macro as a pseudo-EntityScore is lossy for f1; expose a tiny wrapper instead.
    macro = _MacroScore(precision=macro_p, recall=macro_r)

    report = EvalReport(per_entity=per_entity, micro=micro, macro=macro)

    if thresholds:
        # Only gate types the corpus can actually measure (support > 0). A threshold on
        # an entity type with no gold examples is unmeasurable, not a failure.
        failures = [
            GateFailure(t, per_entity[t].recall, thr)
            for t, thr in thresholds.items()
            if t in per_entity and per_entity[t].support > 0 and per_entity[t].recall < thr
        ]
        report.gate_failures = failures
        report.gate_passed = not failures

    return report


@dataclass(frozen=True)
class _MacroScore:
    """Macro aggregate: precision/recall are means of per-type metrics, not pooled counts."""

    precision: float
    recall: float
    entity_type: str = "macro"

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0
