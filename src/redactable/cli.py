"""Command-line interface: ``redactable redact`` and ``redactable eval``.

``main(argv)`` returns an exit code (0 ok, 1 runtime error, 2 usage, 3 gate failure)
so it is unit-testable; ``run()`` is the console-script entry point that wires it to
``sys.exit``.
"""

from __future__ import annotations

import argparse
import json
import sys

from redactable.detectors.base import Detector
from redactable.detectors.composite import CompositeDetector
from redactable.detectors.deterministic import DeterministicDetector
from redactable.eval.corpus import evaluate, load_corpus
from redactable.eval.scorer import EvalReport
from redactable.policy import Policy
from redactable.redactor import Redactor


def _build_detectors(
    use_ner: bool = False,
    use_llm: bool = False,
    llm_model: str = "gemma3",
    llm_url: str = "http://localhost:11434/v1",
) -> list[Detector]:
    """Deterministic core, plus optional contextual tiers when requested.

    --ner adds the GLiNER encoder (recommended: auditable, CPU, non-hallucinating).
    --llm adds a local generative LLM (e.g. Gemma via Ollama) for parity with the browser.
    """
    detectors: list[Detector] = [DeterministicDetector()]
    if use_ner:
        from redactable.detectors.ner import GlinerDetector

        detectors.append(GlinerDetector())
    if use_llm:
        from redactable.detectors.llm import LlmDetector

        detectors.append(LlmDetector(model=llm_model, base_url=llm_url))
    return detectors

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_GATE_FAILED = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="redactable",
        description="Deterministic-first PII/PHI de-identification you can prove.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("redact", help="de-identify text from a file or stdin")
    pr.add_argument("input", nargs="?", default="-", help="input file, or '-' for stdin")
    pr.add_argument("--policy", required=True, help="bundled policy name or path to a YAML pack")
    pr.add_argument("--out", help="write redacted text here (default: stdout)")
    pr.add_argument("--audit", help="write the audit manifest (JSON) here")
    pr.add_argument("--keymap", help="write the re-identification keymap (JSON) here")
    pr.add_argument(
        "--ner", action="store_true", help="also run the GLiNER encoder NER (needs the [ner] extra)"
    )
    pr.add_argument(
        "--llm", action="store_true", help="also run a local LLM (e.g. Gemma via Ollama) for names/places"
    )
    pr.add_argument("--llm-model", default="gemma3", help="LLM model name (default: gemma3)")
    pr.add_argument(
        "--llm-url", default="http://localhost:11434/v1", help="OpenAI-compatible base URL"
    )

    pe = sub.add_parser("eval", help="score a detector against a labeled corpus")
    pe.add_argument("--corpus", required=True, help="JSONL corpus of labeled examples")
    pe.add_argument("--policy", required=True, help="policy whose scope + thresholds to use")
    pe.add_argument("--gate", action="store_true", help="exit non-zero if recall regresses")
    pe.add_argument("--json", action="store_true", dest="as_json", help="emit a JSON report")
    pe.add_argument(
        "--ner", action="store_true", help="benchmark deterministic + GLiNER (needs the [ner] extra)"
    )
    pe.add_argument(
        "--llm", action="store_true", help="benchmark with a local LLM (e.g. Gemma via Ollama)"
    )
    pe.add_argument("--llm-model", default="gemma3", help="LLM model name (default: gemma3)")
    pe.add_argument(
        "--llm-url", default="http://localhost:11434/v1", help="OpenAI-compatible base URL"
    )

    ps = sub.add_parser(
        "serve", help="run a local scrub-proxy between your agent and the LLM API"
    )
    ps.add_argument("--host", default="127.0.0.1")
    ps.add_argument("--port", type=int, default=8080)
    ps.add_argument("--policy", default="pii-structured", help="policy whose PII types to scrub")
    ps.add_argument("--anthropic-url", default=None, help="override upstream Anthropic base URL")
    ps.add_argument("--openai-url", default=None, help="override upstream OpenAI base URL")
    return parser


def _format_report(report: EvalReport) -> str:
    header = f"{'entity':<14}{'precision':>11}{'recall':>9}{'f1':>8}{'support':>9}"
    rule = "-" * len(header)
    lines = [header, rule]
    for etype, s in sorted(report.per_entity.items()):
        lines.append(f"{etype:<14}{s.precision:>11.3f}{s.recall:>9.3f}{s.f1:>8.3f}{s.support:>9}")
    lines.append(rule)
    m = report.micro
    lines.append(f"{'micro':<14}{m.precision:>11.3f}{m.recall:>9.3f}{m.f1:>8.3f}{m.support:>9}")
    lines.append(
        f"{'macro':<14}{report.macro.precision:>11.3f}{report.macro.recall:>9.3f}"
        f"{report.macro.f1:>8.3f}"
    )
    return "\n".join(lines)


def _report_to_dict(report: EvalReport) -> dict:
    return {
        "per_entity": {
            t: {
                "precision": round(s.precision, 4),
                "recall": round(s.recall, 4),
                "f1": round(s.f1, 4),
                "support": s.support,
                "tp": s.tp,
                "fp": s.fp,
                "fn": s.fn,
            }
            for t, s in sorted(report.per_entity.items())
        },
        "micro": {
            "precision": round(report.micro.precision, 4),
            "recall": round(report.micro.recall, 4),
            "f1": round(report.micro.f1, 4),
        },
        "gate_passed": report.gate_passed,
        "gate_failures": [
            {"entity_type": f.entity_type, "recall": round(f.recall, 4), "threshold": f.threshold}
            for f in report.gate_failures
        ],
    }


def _cmd_redact(args: argparse.Namespace) -> int:
    if args.input == "-":
        text = sys.stdin.read()
    else:
        with open(args.input, encoding="utf-8") as fh:
            text = fh.read()

    detectors = _build_detectors(args.ner, args.llm, args.llm_model, args.llm_url)
    redactor = Redactor.from_policy(args.policy, detectors=detectors)
    outcome = redactor.redact(text)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(outcome.text)
    else:
        sys.stdout.write(outcome.text)

    if args.audit:
        with open(args.audit, "w", encoding="utf-8") as fh:
            json.dump(outcome.manifest, fh, indent=2)

    if args.keymap and outcome.keymap:
        with open(args.keymap, "w", encoding="utf-8") as fh:
            json.dump(outcome.keymap, fh, indent=2)

    print(
        f"redacted {outcome.manifest['total_redactions']} entit"
        f"{'y' if outcome.manifest['total_redactions'] == 1 else 'ies'} "
        f"under policy '{outcome.manifest['policy']['name']}'",
        file=sys.stderr,
    )
    return EXIT_OK


def _cmd_eval(args: argparse.Namespace) -> int:
    policy = Policy.load(args.policy)
    examples = load_corpus(args.corpus)
    scope = set(policy.entities) or None
    detectors = _build_detectors(args.ner, args.llm, args.llm_model, args.llm_url)
    engine: Detector = CompositeDetector(detectors) if len(detectors) > 1 else detectors[0]
    report = evaluate(engine, examples, thresholds=policy.thresholds, scope=scope)

    if args.as_json:
        print(json.dumps(_report_to_dict(report), indent=2))
    else:
        print(_format_report(report))

    if args.gate and report.gate_passed is False:
        for failure in report.gate_failures:
            print(
                f"GATE FAILED: {failure.entity_type} recall {failure.recall:.3f} "
                f"< threshold {failure.threshold:.3f}",
                file=sys.stderr,
            )
        return EXIT_GATE_FAILED
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "redact":
            return _cmd_redact(args)
        if args.command == "eval":
            return _cmd_eval(args)
        if args.command == "serve":
            from redactable.proxy import serve

            serve(args.host, args.port, args.policy, args.anthropic_url, args.openai_url)
            return EXIT_OK
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 — surface any failure as a clean error code
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def run() -> None:
    """Console-script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    run()
