"""Detectors: pluggable engines that turn text into spans.

The deterministic detector is always available. The encoder-NER detector lives in
``redactable.detectors.ner`` and requires the optional ``[ner]`` extra.
"""

from redactable.detectors.base import Detector
from redactable.detectors.deterministic import DeterministicDetector

__all__ = ["Detector", "DeterministicDetector"]
