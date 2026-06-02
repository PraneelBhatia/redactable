"""Detectors: pluggable engines that turn text into spans.

The deterministic detector is always available. The encoder-NER detector lives in
``redactable.detectors.ner`` and requires the optional ``[ner]`` extra.
"""

from redactable.detectors.base import Detector
from redactable.detectors.composite import CompositeDetector
from redactable.detectors.deterministic import DeterministicDetector

# GlinerDetector intentionally not imported here — importing it is cheap (the heavy
# gliner dependency loads lazily), but keeping it explicit signals it's the optional tier.

__all__ = ["Detector", "CompositeDetector", "DeterministicDetector"]
