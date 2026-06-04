"""Benchmark the CONTEXTUAL tier (names/places/orgs) on ai4privacy — head-to-head ready.

Scores a contextual detector (GLiNER by default, or a local LLM) with the SAME sample,
mapping, and granularity-tolerant overlap recall used for the in-browser Gemma-4 run, so the
numbers are directly comparable.

Run:  python benchmarks/ai4privacy/benchmark_contextual.py --engine gliner --sample web/bench_sample.json
"""

from __future__ import annotations

import argparse
import json
import time

MAP = {
    "FIRSTNAME": "PERSON", "LASTNAME": "PERSON", "MIDDLENAME": "PERSON",
    "CITY": "LOCATION", "STATE": "LOCATION", "COUNTY": "LOCATION", "STREET": "LOCATION",
    "COMPANYNAME": "ORG",
}
TYPES = ["PERSON", "LOCATION", "ORG"]


def load_sample(path: str) -> list[dict]:
    return json.load(open(path))


def build_detector(engine: str):
    if engine == "gliner":
        from redactable.detectors.ner import GlinerDetector

        return GlinerDetector()
    if engine == "llm":
        from redactable.detectors.llm import LlmDetector

        return LlmDetector()
    raise SystemExit(f"unknown engine {engine!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="gliner", choices=["gliner", "llm"])
    ap.add_argument("--sample", default="web/bench_sample.json")
    args = ap.parse_args()

    sample = load_sample(args.sample)
    det = build_detector(args.engine)

    acc = {t: {"tp": 0, "fp": 0, "fn": 0} for t in TYPES}
    t0 = time.time()
    for ex in sample:
        text = ex["source_text"]
        gold = [
            {"start": m["start"], "end": m["end"], "type": MAP[m["label"]]}
            for m in ex.get("privacy_mask", [])
            if m["label"] in MAP
        ]
        pred = [s for s in det.detect(text) if str(s.entity_type) in TYPES]
        # granularity-tolerant overlap: gold recalled if any same-type prediction overlaps
        for g in gold:
            hit = any(str(p.entity_type) == g["type"] and p.start < g["end"] and g["start"] < p.end for p in pred)
            acc[g["type"]]["tp" if hit else "fn"] += 1
        for p in pred:
            hit = any(g["type"] == str(p.entity_type) and p.start < g["end"] and g["start"] < p.end for g in gold)
            if not hit:
                acc[str(p.entity_type)]["fp"] += 1
    elapsed = time.time() - t0

    print(f"# Contextual tier: {args.engine}  ({len(sample)} examples, {elapsed:.1f}s, "
          f"{elapsed / max(1, len(sample)) * 1000:.0f} ms/example)\n")
    print(f"{'type':<10}{'precision':>10}{'recall':>9}{'gold':>7}")
    print("-" * 36)
    for t in TYPES:
        a = acc[t]
        prec = a["tp"] / (a["tp"] + a["fp"]) if (a["tp"] + a["fp"]) else 0.0
        rec = a["tp"] / (a["tp"] + a["fn"]) if (a["tp"] + a["fn"]) else 0.0
        print(f"{t:<10}{prec:>10.3f}{rec:>9.3f}{a['tp'] + a['fn']:>7}")


if __name__ == "__main__":
    main()
