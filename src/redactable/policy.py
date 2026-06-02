"""Policy packs: declarative, versioned, per-jurisdiction de-identification rules.

A pack answers three questions for a run: which entity types are *in scope*, what
*transformation* each gets, and what *recall thresholds* the eval gate enforces.
Packs are plain YAML so they are forkable and reviewable — the maintained set of
expert-tuned packs is part of the product's moat, but the format is fully open.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources

import yaml


@dataclass(frozen=True)
class Policy:
    name: str
    version: int
    jurisdiction: str
    description: str
    default_action: str
    entities: dict[str, str]  # entity type -> action
    thresholds: dict[str, float]  # entity type -> minimum recall for the CI gate

    @classmethod
    def load(cls, name_or_path: str) -> Policy:
        """Load a pack by bundled name (e.g. ``"hipaa-safe-harbor"``) or by file path."""
        if os.path.sep in name_or_path or name_or_path.endswith((".yaml", ".yml")):
            if not os.path.exists(name_or_path):
                raise FileNotFoundError(f"policy pack not found: {name_or_path}")
            with open(name_or_path, encoding="utf-8") as fh:
                return cls._from_dict(yaml.safe_load(fh))

        try:
            text = (
                resources.files("redactable.policies")
                .joinpath(f"{name_or_path}.yaml")
                .read_text(encoding="utf-8")
            )
        except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
            raise FileNotFoundError(f"no bundled policy pack named {name_or_path!r}") from exc
        return cls._from_dict(yaml.safe_load(text))

    @classmethod
    def _from_dict(cls, data: dict) -> Policy:
        raw_entities = data.get("entities") or {}
        entities = {
            etype: (spec.get("action") if isinstance(spec, dict) else spec)
            for etype, spec in raw_entities.items()
        }
        return cls(
            name=data["name"],
            version=int(data.get("version", 1)),
            jurisdiction=data.get("jurisdiction", ""),
            description=data.get("description", ""),
            default_action=data.get("default_action", "tokenize"),
            entities=entities,
            thresholds={k: float(v) for k, v in (data.get("thresholds") or {}).items()},
        )

    def action_for(self, entity_type: str) -> str:
        """The transformation for ``entity_type`` (its declared action, or the default)."""
        return self.entities.get(str(entity_type), self.default_action)

    def in_scope(self, entity_type: str) -> bool:
        """Whether the policy declares (cares about) this entity type."""
        return str(entity_type) in self.entities
