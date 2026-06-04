"""RedactionService — the reusable core behind every integration (MCP, hook, proxy).

`scrub()` removes PII before text goes to an LLM; by default it is *reversible* (consistent
``[TYPE_n]`` tokens + a session keymap), so a model's reply that references the tokens can be
restored locally with `restore()`. `detect()` reports what's present without changing anything.

All of this runs on the deterministic engine — no model, no network — so it's safe to embed
in an always-on interceptor.
"""

from __future__ import annotations

from uuid import uuid4

from redactable.detectors.deterministic import DeterministicDetector
from redactable.overlap import resolve_overlaps
from redactable.policy import Policy
from redactable.tokenization import Tokenizer


class RedactionService:
    def __init__(self) -> None:
        self._detector = DeterministicDetector()
        self._sessions: dict[str, dict[str, str]] = {}  # session id -> token->original keymap

    def _spans(self, text: str, policy: str):
        pol = Policy.load(policy)
        in_scope = [s for s in self._detector.detect(text) if pol.in_scope(str(s.entity_type))]
        return resolve_overlaps(in_scope)

    @staticmethod
    def _counts(spans) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in spans:
            counts[str(s.entity_type)] = counts.get(str(s.entity_type), 0) + 1
        return dict(sorted(counts.items()))

    def scrub(self, text: str, policy: str = "pii-structured", reversible: bool = True) -> dict:
        """Redact PII. Reversible mode returns a ``session`` to restore originals later."""
        spans = self._spans(text, policy)
        tokenizer = Tokenizer(strategy="tokenize" if reversible else "mask")
        result = tokenizer.apply(text, spans)
        session = None
        if reversible and result.keymap:
            session = uuid4().hex
            self._sessions[session] = result.keymap
        return {"redacted": result.text, "entities": self._counts(spans), "session": session}

    def restore(self, text: str, session: str) -> str:
        """Put original values back into a reversibly-scrubbed text, using its session id."""
        keymap = self._sessions.get(session)
        if keymap is None:
            raise KeyError(f"unknown or expired session: {session}")
        return Tokenizer.reverse(text, keymap)

    def detect(self, text: str, policy: str = "pii-structured") -> dict:
        """Report PII present without modifying the text."""
        spans = self._spans(text, policy)
        return {"found": self._counts(spans), "total": len(spans)}
