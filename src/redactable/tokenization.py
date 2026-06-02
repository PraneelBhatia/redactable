"""Transformation strategies: how a detected span becomes redacted output.

- ``mask``: replace with a bare ``[TYPE]`` label. Irreversible, simplest.
- ``tokenize``: replace with a consistent ``[TYPE_n]`` placeholder. The same original
  value always maps to the same token (so de-identified data stays joinable), and a
  keymap records ``token -> original`` for authorized re-identification.
- ``hash``: replace with ``[TYPE_<hash>]``, a salted digest. Consistent pseudonymization
  with no stored secret — same value yields the same token, but it is not reversible.

The redactor is expected to pass overlap-resolved spans; we still defensively sort and
drop overlaps so the transformer never corrupts output.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from redactable.span import Span

_STRATEGIES = ("mask", "tokenize", "hash")


@dataclass(repr=False)
class RedactionResult:
    """The output of applying a tokenizer: redacted text plus a (possibly empty) keymap."""

    text: str
    keymap: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        # The keymap re-identifies people; never expose its originals via repr.
        return f"RedactionResult(text_len={len(self.text)}, keymap=<{len(self.keymap)} entries redacted>)"


class Tokenizer:
    """Applies a transformation strategy to detected spans over a text."""

    def __init__(
        self,
        strategy: str = "tokenize",
        salt: bytes = b"",
        action_resolver: Callable[[Span], str] | None = None,
    ) -> None:
        if strategy not in _STRATEGIES:
            raise ValueError(f"unknown strategy {strategy!r}; choose one of {_STRATEGIES}")
        self.strategy = strategy
        self.salt = salt
        # Optional per-span strategy override (used by the redactor to honour a policy's
        # per-entity actions). When None, every span uses ``strategy``.
        self._action_resolver = action_resolver
        # Per-type running counter and a (type, original) -> token cache, so identical
        # values reuse the same token across an entire apply() (and across calls if the
        # same Tokenizer instance is reused — enabling cross-document joinability).
        self._counters: dict[str, int] = {}
        self._tokens: dict[tuple[str, str, str], str] = {}

    def _effective(self, span: Span) -> str:
        strat = self._action_resolver(span) if self._action_resolver else self.strategy
        if strat not in _STRATEGIES:
            raise ValueError(f"policy action {strat!r} is not one of {_STRATEGIES}")
        return strat

    def _token_for(self, span: Span, effective: str) -> str:
        etype = str(span.entity_type)
        if effective == "mask":
            return f"[{etype}]"

        # Key includes the effective strategy so hash/tokenize can't cross-contaminate
        # if the same instance is reused with a changed strategy.
        key = (etype, span.text, effective)
        if key in self._tokens:
            return self._tokens[key]

        if effective == "hash":
            digest = hashlib.sha256(self.salt + span.text.encode("utf-8")).hexdigest()[:10]
            token = f"[{etype}_{digest}]"
        else:  # tokenize
            self._counters[etype] = self._counters.get(etype, 0) + 1
            token = f"[{etype}_{self._counters[etype]}]"

        self._tokens[key] = token
        return token

    def apply(self, text: str, spans: list[Span]) -> RedactionResult:
        """Replace each span in ``text`` with its token, returning text + keymap."""
        ordered = sorted(spans, key=lambda s: (s.start, -s.length))
        out: list[str] = []
        keymap: dict[str, str] = {}
        cursor = 0
        for span in ordered:
            if span.start < cursor:
                continue  # overlaps an already-emitted span; skip
            effective = self._effective(span)
            token = self._token_for(span, effective)
            out.append(text[cursor : span.start])
            out.append(token)
            if effective == "tokenize":
                keymap[token] = span.text
            cursor = span.end
        out.append(text[cursor:])
        return RedactionResult(text="".join(out), keymap=keymap)

    @staticmethod
    def reverse(text: str, keymap: dict[str, str]) -> str:
        """Restore original values from a tokenized text using its keymap.

        Single-pass simultaneous substitution: each token is replaced exactly once, so a
        restored value can never be re-consumed by a later token's substitution (which a
        naive sequential ``str.replace`` loop would do). Longer tokens are tried first to
        avoid one token being a prefix of another.
        """
        if not keymap:
            return text
        pattern = re.compile("|".join(re.escape(k) for k in sorted(keymap, key=len, reverse=True)))
        return pattern.sub(lambda m: keymap[m.group(0)], text)
