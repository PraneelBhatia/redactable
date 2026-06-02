"""The Redactor: orchestrates detectors, policy, and transformation into a result.

Pipeline: run every detector → keep only policy-in-scope spans → resolve overlaps
(a checksum-valid span beats a higher score beats a longer span) → apply the policy's
per-entity action → emit redacted text, the resolved spans, an optional re-identification
keymap, and an audit manifest that records *what* was redacted but never the originals.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from redactable import __version__
from redactable.detectors.base import Detector
from redactable.detectors.deterministic import DeterministicDetector
from redactable.overlap import resolve_overlaps
from redactable.policy import Policy
from redactable.span import Span
from redactable.tokenization import Tokenizer


@dataclass(repr=False)
class RedactionOutcome:
    text: str
    spans: list[Span]
    keymap: dict[str, str]
    manifest: dict

    def __repr__(self) -> str:
        # Never expose raw PII (in spans) or re-identification originals (in keymap).
        return (
            f"RedactionOutcome(redactions={len(self.spans)}, "
            f"types={self.manifest.get('entity_counts', {})}, "
            f"keymap=<{len(self.keymap)} entries redacted>)"
        )


class Redactor:
    def __init__(self, detectors: Sequence[Detector], policy: Policy, salt: bytes = b"") -> None:
        self.detectors = list(detectors)
        self.policy = policy
        self.salt = salt

    @classmethod
    def from_policy(
        cls,
        policy: Policy | str,
        detectors: Sequence[Detector] | None = None,
        salt: bytes = b"",
    ) -> Redactor:
        """Build a redactor from a Policy (or a bundled name/path), defaulting to the
        deterministic detector when none is supplied."""
        pol = policy if isinstance(policy, Policy) else Policy.load(policy)
        return cls(detectors or [DeterministicDetector()], pol, salt)

    def _collect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for detector in self.detectors:
            try:
                spans.extend(detector.detect(text))
            except Exception:  # noqa: BLE001 — a failing optional detector must not break the core
                continue
        return spans

    def redact(self, text: str) -> RedactionOutcome:
        in_scope = [s for s in self._collect(text) if self.policy.in_scope(str(s.entity_type))]
        spans = resolve_overlaps(in_scope)

        tokenizer = Tokenizer(
            salt=self.salt,
            action_resolver=lambda s: self.policy.action_for(str(s.entity_type)),
        )
        result = tokenizer.apply(text, spans)

        counts: dict[str, int] = {}
        for span in spans:
            counts[str(span.entity_type)] = counts.get(str(span.entity_type), 0) + 1

        manifest = {
            "engine": "redactable",
            "engine_version": __version__,
            "policy": {"name": self.policy.name, "version": self.policy.version},
            "detectors": [d.name for d in self.detectors],
            # Hash of the REDACTED output, not the raw input: a hash of the original would
            # be an invertible record of PII for short/predictable inputs.
            "output_sha256": hashlib.sha256(result.text.encode("utf-8")).hexdigest(),
            "entity_counts": dict(sorted(counts.items())),
            "total_redactions": len(spans),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return RedactionOutcome(
            text=result.text, spans=spans, keymap=result.keymap, manifest=manifest
        )
