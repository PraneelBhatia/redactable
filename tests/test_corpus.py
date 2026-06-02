"""Tests for the labeled-corpus loader and the evaluate() bridge.

The corpus is the ground truth the whole 'provable recall' claim rests on, so the
loader validates aggressively: span bounds must be real, and malformed rows fail
loudly with a line number rather than silently corrupting a benchmark.
"""

import json

import pytest

from redactable.detectors.deterministic import DeterministicDetector
from redactable.eval.corpus import evaluate, load_corpus
from redactable.span import EntityType


def write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(path)


class TestLoad:
    def test_loads_text_and_gold_spans(self, tmp_path):
        p = write_jsonl(
            tmp_path / "c.jsonl",
            [{"text": "email a@b.com", "spans": [{"start": 6, "end": 13, "type": "EMAIL"}]}],
        )
        examples = load_corpus(p)
        assert len(examples) == 1
        ex = examples[0]
        assert ex.text == "email a@b.com"
        assert len(ex.gold) == 1
        assert ex.gold[0].entity_type == EntityType.EMAIL
        assert ex.gold[0].text == "a@b.com"  # sliced from the source text

    def test_blank_lines_skipped(self, tmp_path):
        p = tmp_path / "c.jsonl"
        p.write_text('{"text": "x", "spans": []}\n\n   \n{"text": "y", "spans": []}\n')
        assert len(load_corpus(str(p))) == 2

    def test_custom_entity_type_preserved_as_string(self, tmp_path):
        p = write_jsonl(
            tmp_path / "c.jsonl",
            [{"text": "MRN 12345", "spans": [{"start": 4, "end": 9, "type": "MRN"}]}],
        )
        ex = load_corpus(p)[0]
        assert str(ex.gold[0].entity_type) == "MRN"


class TestValidation:
    def test_out_of_bounds_span_raises_with_line_number(self, tmp_path):
        p = write_jsonl(
            tmp_path / "c.jsonl",
            [{"text": "short", "spans": [{"start": 0, "end": 99, "type": "EMAIL"}]}],
        )
        with pytest.raises(ValueError, match="line 1"):
            load_corpus(p)

    def test_invalid_json_raises_with_line_number(self, tmp_path):
        p = tmp_path / "c.jsonl"
        p.write_text('{"text": "ok", "spans": []}\n{not json}\n')
        with pytest.raises(ValueError, match="line 2"):
            load_corpus(str(p))

    def test_missing_text_field_raises_with_line_number(self, tmp_path):
        p = tmp_path / "c.jsonl"
        p.write_text('{"spans": []}\n')
        with pytest.raises(ValueError, match="line 1"):
            load_corpus(str(p))

    def test_missing_span_type_raises_with_line_number(self, tmp_path):
        p = write_jsonl(tmp_path / "c.jsonl", [{"text": "hi there", "spans": [{"start": 0, "end": 2}]}])
        with pytest.raises(ValueError, match="line 1"):
            load_corpus(p)


class TestEvaluate:
    def test_evaluate_runs_detector_over_corpus(self, tmp_path):
        p = write_jsonl(
            tmp_path / "c.jsonl",
            [
                {"text": "ping a@b.com", "spans": [{"start": 5, "end": 12, "type": "EMAIL"}]},
                {"text": "see c@d.org", "spans": [{"start": 4, "end": 11, "type": "EMAIL"}]},
            ],
        )
        examples = load_corpus(p)
        report = evaluate(DeterministicDetector(), examples)
        assert report.per_entity["EMAIL"].recall == 1.0

    def test_evaluate_resolves_overlapping_predictions(self, tmp_path):
        # Eval measures what the pipeline REDACTS, so overlapping candidate spans are
        # resolved first: a shorter CREDIT_CARD inside a longer valid IBAN is dropped and
        # must not show up as a spurious false positive.
        from redactable.span import EntityType, Span

        class TwoOverlap:
            name = "x"

            def detect(self, text):
                return [
                    Span(0, 10, EntityType.IBAN, "x" * 10, valid=True),
                    Span(2, 8, EntityType.CREDIT_CARD, "x" * 6, valid=True),
                ]

        p = write_jsonl(
            tmp_path / "c.jsonl",
            [{"text": "x" * 10, "spans": [{"start": 0, "end": 10, "type": "IBAN"}]}],
        )
        report = evaluate(TwoOverlap(), load_corpus(p))
        assert "CREDIT_CARD" not in report.per_entity
        assert report.per_entity["IBAN"].precision == 1.0

    def test_evaluate_restricts_to_scope(self, tmp_path):
        # A URL is present and detected, but scope is EMAIL-only -> URL must not appear.
        p = write_jsonl(
            tmp_path / "c.jsonl",
            [{"text": "go https://x.io now", "spans": []}],
        )
        examples = load_corpus(p)
        report = evaluate(DeterministicDetector(), examples, scope={"EMAIL"})
        assert "URL" not in report.per_entity
