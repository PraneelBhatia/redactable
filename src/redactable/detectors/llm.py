"""Contextual PII via a *local* generative LLM (e.g. Gemma through Ollama).

This is the non-browser sibling of ``web/gemma.js``: when you want Gemma (or any model)
to find names/places/orgs from the CLI, a server, or CI, you point this detector at a
local OpenAI-compatible endpoint — Ollama (``ollama run gemma3``), LM Studio, llama.cpp's
server, vLLM, etc. No heavy Python dependency and the text stays on your machine.

Design notes carried over from the browser tier:
  * Small models emit *malformed* JSON constantly, so parsing tolerates a stray brace /
    trailing comma / code fence (regex fallback).
  * Model-reported offsets are never trusted — we locate the returned substring in the
    source text ourselves, and drop anything the model invented that isn't actually there.

For a CLI/server the *encoder* NER (``GlinerDetector``) is usually the better contextual
engine — auditable and non-hallucinating. This LLM path exists for parity with the browser
and for users who already run a local Gemma.
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable

from redactable.span import EntityType, Span

_LABELS = {"person": EntityType.PERSON, "location": EntityType.LOCATION, "organization": EntityType.ORG}

_OBJ_TEXT_FIRST = re.compile(r'\{\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"label"\s*:\s*"([^"]*)"\s*\}')
_OBJ_LABEL_FIRST = re.compile(r'\{\s*"label"\s*:\s*"([^"]*)"\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}')

_PROMPT = (
    "Extract every person name, physical location, and organization from the TEXT.\n"
    'Respond ONLY with a JSON array of objects like {"text":"...","label":"person|location|organization"}.\n'
    "Use the exact substring as it appears. No commentary.\n\nTEXT:\n"
)


def extract_entities_json(raw: str) -> list[dict]:
    """Recover ``{text,label}`` objects from possibly-malformed model output."""
    start, end = raw.find("["), raw.rfind("]")
    if start != -1 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass  # fall through to regex recovery
    objects = [{"text": m.group(1), "label": m.group(2)} for m in _OBJ_TEXT_FIRST.finditer(raw)]
    objects += [{"text": m.group(2), "label": m.group(1)} for m in _OBJ_LABEL_FIRST.finditer(raw)]
    return objects


class LlmDetector:
    """Detects contextual PII by prompting a local OpenAI-compatible LLM endpoint."""

    name = "llm"

    def __init__(
        self,
        model: str = "gemma3",
        base_url: str = "http://localhost:11434/v1",
        api_key: str | None = None,
        timeout: float = 120.0,
        transport: Callable[[str], str] | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._transport = transport or self._http_transport

    def _http_transport(self, prompt: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "stream": False,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.load(resp)
        return data["choices"][0]["message"]["content"]

    def detect(self, text: str) -> list[Span]:
        raw = self._transport(_PROMPT + text)
        spans: list[Span] = []
        cursor: dict[str, int] = {}
        for item in extract_entities_json(raw):
            value = item.get("text")
            entity_type = _LABELS.get(str(item.get("label", "")).lower())
            if not value or entity_type is None:
                continue
            idx = text.find(value, cursor.get(value, 0))
            if idx == -1:
                continue  # model invented a span not present in the text -> drop it
            cursor[value] = idx + len(value)
            spans.append(
                Span(idx, idx + len(value), entity_type, value, score=0.6, detector=self.name)
            )
        return spans
