"""Redactable — deterministic-first PII/PHI de-identification you can prove."""

__version__ = "0.1.0"


def __getattr__(name: str):
    # Lazy re-exports keep ``import redactable`` cheap and avoid import cycles
    # (redactor imports this module for __version__).
    if name == "Redactor":
        from redactable.redactor import Redactor

        return Redactor
    if name == "Policy":
        from redactable.policy import Policy

        return Policy
    if name in ("EntityType", "Span"):
        from redactable import span

        return getattr(span, name)
    if name == "DeterministicDetector":
        from redactable.detectors.deterministic import DeterministicDetector

        return DeterministicDetector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Redactor", "Policy", "EntityType", "Span", "DeterministicDetector", "__version__"]
