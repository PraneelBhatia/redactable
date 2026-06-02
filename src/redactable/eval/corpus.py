"""Labeled corpus loading and the detector→scorer bridge.

Corpus format is JSONL, one example per line::

    {"text": "...", "spans": [{"start": 6, "end": 13, "type": "EMAIL"}], "meta": {...}}

Span offsets are half-open ``[start, end)`` into ``text``. The loader validates bounds
and JSON per line so a broken benchmark fails loudly instead of silently understating
or overstating recall.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field

from redactable.detectors.base import Detector
from redactable.eval.scorer import EvalReport, score
from redactable.span import EntityType, Span


@dataclass(frozen=True)
class Example:
    text: str
    gold: list[Span]
    meta: dict = field(default_factory=dict)


def _coerce_type(raw: str) -> EntityType | str:
    """Use the EntityType enum for known types; keep custom labels as plain strings."""
    try:
        return EntityType(raw)
    except ValueError:
        return raw


def load_corpus(path: str) -> list[Example]:
    """Load and validate a JSONL corpus file."""
    examples: list[Example] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {lineno}: invalid JSON: {exc}") from exc

            text = row["text"]
            spans: list[Span] = []
            for raw_span in row.get("spans", []):
                start, end = raw_span["start"], raw_span["end"]
                if not (0 <= start < end <= len(text)):
                    raise ValueError(
                        f"line {lineno}: span out of bounds for text of length "
                        f"{len(text)}: {raw_span}"
                    )
                spans.append(
                    Span(start, end, _coerce_type(raw_span["type"]), text[start:end])
                )
            examples.append(Example(text=text, gold=spans, meta=row.get("meta", {})))
    return examples


def _restrict(spans: Iterable[Span], scope: set[str] | None) -> list[Span]:
    if scope is None:
        return list(spans)
    return [s for s in spans if str(s.entity_type) in scope]


def evaluate(
    detector: Detector,
    examples: list[Example],
    thresholds: dict[str, float] | None = None,
    scope: set[str] | None = None,
) -> EvalReport:
    """Run ``detector`` over every example and score it against the gold spans.

    Args:
        scope: if given, both gold and predicted spans are restricted to these entity
            types — so the detector is not penalised for finding types the active policy
            does not care about, and out-of-scope gold is not counted as missed.
    """
    pairs = [
        (_restrict(ex.gold, scope), _restrict(detector.detect(ex.text), scope))
        for ex in examples
    ]
    return score(pairs, thresholds=thresholds)
