"""Tests for the CLI surface: `redactable redact` and `redactable eval`.

``main(argv)`` returns an exit code so behaviour is testable without spawning a
process. Documented codes: 0 ok, 1 runtime error, 3 eval-gate failure.
"""

import importlib.util
import json

import pytest

from redactable.cli import main


def write_corpus(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(path)


class TestRedact:
    def test_redacts_file_to_out(self, tmp_path):
        inp = tmp_path / "in.txt"
        inp.write_text("Email a@b.com SSN 123-45-6789")
        out = tmp_path / "out.txt"
        rc = main(["redact", str(inp), "--policy", "hipaa-safe-harbor", "--out", str(out)])
        assert rc == 0
        assert out.read_text() == "Email [EMAIL] SSN [US_SSN]"

    def test_writes_audit_manifest(self, tmp_path):
        inp = tmp_path / "in.txt"
        inp.write_text("contact a@b.com")
        out = tmp_path / "out.txt"
        audit = tmp_path / "audit.json"
        rc = main(
            [
                "redact", str(inp), "--policy", "hipaa-safe-harbor",
                "--out", str(out), "--audit", str(audit),
            ]
        )
        assert rc == 0
        manifest = json.loads(audit.read_text())
        assert manifest["entity_counts"] == {"EMAIL": 1}
        assert manifest["policy"]["name"] == "hipaa-safe-harbor"

    def test_unknown_policy_returns_1(self, tmp_path):
        inp = tmp_path / "in.txt"
        inp.write_text("hi")
        rc = main(["redact", str(inp), "--policy", "does-not-exist"])
        assert rc == 1


class TestEval:
    def test_prints_per_entity_metrics(self, tmp_path, capsys):
        corpus = write_corpus(
            tmp_path / "c.jsonl",
            [{"text": "ping a@b.com", "spans": [{"start": 5, "end": 12, "type": "EMAIL"}]}],
        )
        rc = main(["eval", "--corpus", corpus, "--policy", "hipaa-safe-harbor"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "EMAIL" in out
        assert "recall" in out.lower()

    def test_gate_passes_when_recall_met(self, tmp_path):
        corpus = write_corpus(
            tmp_path / "c.jsonl",
            [{"text": "ping a@b.com", "spans": [{"start": 5, "end": 12, "type": "EMAIL"}]}],
        )
        rc = main(["eval", "--corpus", corpus, "--policy", "hipaa-safe-harbor", "--gate"])
        assert rc == 0

    def test_gate_fails_on_missed_in_scope_entity(self, tmp_path):
        # PERSON is in scope with a 0.85 threshold; the deterministic engine can't find
        # names, so recall is 0 and the gate must fail with exit code 3.
        corpus = write_corpus(
            tmp_path / "c.jsonl",
            [{"text": "call Alice Smith", "spans": [{"start": 5, "end": 16, "type": "PERSON"}]}],
        )
        rc = main(["eval", "--corpus", corpus, "--policy", "hipaa-safe-harbor", "--gate"])
        assert rc == 3

    def test_ner_flag_without_extra_errors_cleanly(self, tmp_path, capsys):
        if importlib.util.find_spec("gliner") is not None:
            pytest.skip("gliner installed; the missing-extra error path can't be exercised")
        corpus = write_corpus(
            tmp_path / "c.jsonl",
            [{"text": "ping a@b.com", "spans": [{"start": 5, "end": 12, "type": "EMAIL"}]}],
        )
        rc = main(["eval", "--corpus", corpus, "--policy", "hipaa-safe-harbor", "--ner"])
        assert rc == 1
        assert "redactable[ner]" in capsys.readouterr().err
