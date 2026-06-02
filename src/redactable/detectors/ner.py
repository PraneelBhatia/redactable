"""Optional encoder-NER detector for contextual PII (names, locations, organizations).

Why an *encoder* NER and not a generative LLM: a token-classification model returns
character offsets and a confidence it cannot fabricate — it can miss a span, but it
cannot hallucinate a fake one or regurgitate training data. That makes it auditable,
which the recall-critical liability story demands. GLiNER is the default because one
small model handles arbitrary labels; the weights are a heavy opt-in (``redactable[ner]``).

The model is injectable so the translation logic is testable without downloading
hundreds of megabytes — and so any other engine exposing ``predict_entities`` can be
dropped in.
"""

from __future__ import annotations

from typing import Any

from redactable.span import EntityType, Span

# Default GLiNER label -> Redactable entity type. GLiNER takes free-form labels, so
# these strings are what we ask the model to find.
DEFAULT_LABEL_MAP: dict[str, EntityType] = {
    "person": EntityType.PERSON,
    "location": EntityType.LOCATION,
    "organization": EntityType.ORG,
}

# A small, CPU-friendly multi-PII GLiNER checkpoint (ONNX-exportable). Overridable.
DEFAULT_MODEL_NAME = "urchade/gliner_multi_pii-v1"


class GlinerDetector:
    """Wraps a GLiNER model behind the Detector contract."""

    name = "gliner"

    def __init__(
        self,
        model: Any | None = None,
        label_map: dict[str, EntityType] | None = None,
        threshold: float = 0.5,
        model_name: str = DEFAULT_MODEL_NAME,
    ) -> None:
        self._model = model
        self._label_map = label_map or dict(DEFAULT_LABEL_MAP)
        self.threshold = threshold
        self.model_name = model_name

    def _ensure_model(self) -> Any:
        if self._model is None:
            try:
                from gliner import GLiNER
            except ImportError as exc:  # pragma: no cover - exercised only without the extra
                raise ImportError(
                    "the GLiNER detector requires the optional NER extra: "
                    "install it with `pip install redactable[ner]`"
                ) from exc
            self._model = GLiNER.from_pretrained(self.model_name)
        return self._model

    def detect(self, text: str) -> list[Span]:
        model = self._ensure_model()
        labels = list(self._label_map.keys())
        spans: list[Span] = []
        for ent in model.predict_entities(text, labels, threshold=self.threshold):
            entity_type = self._label_map.get(ent["label"])
            if entity_type is None:
                continue  # a label we don't map to a PII type
            spans.append(
                Span(
                    start=ent["start"],
                    end=ent["end"],
                    entity_type=entity_type,
                    text=ent["text"],
                    score=float(ent.get("score", 1.0)),
                    detector=self.name,
                )
            )
        return spans
