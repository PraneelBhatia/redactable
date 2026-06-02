"""Overlap resolution shared by the redactor and the eval harness.

When multiple detectors (or multiple rules) emit spans that overlap the same text, the
pipeline keeps the most trustworthy one. Resolving in *both* the redactor and the eval
means the benchmark measures what actually gets redacted — not raw, double-counted
candidate spans.

Preference order: a checksum-valid span beats a span with no checksum, which beats one
whose checksum failed; ties break by higher score, then longer span, then earlier start.
"""

from __future__ import annotations

from redactable.span import Span

# Lower sorts first: checksum-valid (True) > no-checksum (None) > checksum-failed (False).
_VALID_RANK = {True: 0, None: 1, False: 2}


def resolve_overlaps(spans: list[Span]) -> list[Span]:
    """Return a non-overlapping subset of ``spans``, keeping the highest-preference ones."""
    ranked = sorted(
        spans,
        key=lambda s: (_VALID_RANK.get(s.valid, 1), -s.score, -s.length, s.start),
    )
    chosen: list[Span] = []
    for span in ranked:
        if not any(span.overlaps(c) for c in chosen):
            chosen.append(span)
    return sorted(chosen, key=lambda s: s.start)
