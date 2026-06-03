"""Validate the Redactable deterministic engine against a real third-party PII dataset.

Dataset: ai4privacy/pii-masking-200k (English subset), fetched on demand via the Hugging
Face datasets-server (no bulk download, no redistribution of the data).

This measures the honest question: of the real emails / SSNs / cards / IBANs / IPs / phones
a third party labeled, how many does our *deterministic* engine catch? Contextual types
(names, places, orgs) are reported as out-of-scope here — they need the optional NER/Gemma
tier, which is benchmarked separately.

Run:  python benchmarks/ai4privacy/benchmark.py --limit 2000 [--cache path.json]
"""

from __future__ import annotations

import argparse
import collections
import json
import urllib.request

from redactable.detectors.deterministic import DeterministicDetector
from redactable.eval.scorer import score
from redactable.overlap import resolve_overlaps
from redactable.span import EntityType, Span

DATASET = "ai4privacy/pii-masking-200k"
ROWS_URL = (
    "https://datasets-server.huggingface.co/rows"
    f"?dataset={DATASET}&config=default&split=train&offset={{off}}&length=100"
)

# ai4privacy label -> our entity type. STRUCTURED types are what the deterministic engine
# claims to handle; CONTEXTUAL types need the NER tier (shown for completeness, not scored
# against the deterministic engine).
STRUCTURED = {
    "EMAIL": "EMAIL",
    "URL": "URL",
    "PHONENUMBER": "PHONE",
    "SSN": "US_SSN",
    "CREDITCARDNUMBER": "CREDIT_CARD",
    "IBAN": "IBAN",
    "IPV4": "IP_ADDRESS",
    "IPV6": "IP_ADDRESS",
    "IP": "IP_ADDRESS",
}
CONTEXTUAL = {
    "FIRSTNAME": "PERSON", "LASTNAME": "PERSON", "MIDDLENAME": "PERSON",
    "CITY": "LOCATION", "STATE": "LOCATION", "COUNTY": "LOCATION", "STREET": "LOCATION",
    "COMPANYNAME": "ORG",
}


def fetch_english(limit: int) -> list[dict]:
    rows: list[dict] = []
    off = 0
    while len(rows) < limit:
        with urllib.request.urlopen(ROWS_URL.format(off=off), timeout=60) as r:
            page = json.load(r).get("rows", [])
        if not page:
            break
        rows += [x["row"] for x in page]
        off += 100
    return [r for r in rows if r.get("language") == "en"][:limit]


def build_pairs(examples: list[dict]):
    pairs = []  # (gold_structured_spans, predicted_spans)
    pred_total = 0
    pred_hit_any_pii = 0  # predictions overlapping ANY labeled PII (any type) — fair precision
    det = DeterministicDetector()
    for ex in examples:
        text = ex["source_text"]
        all_pii = [(m["start"], m["end"]) for m in ex.get("privacy_mask", [])]
        gold = [
            Span(m["start"], m["end"], EntityType(STRUCTURED[m["label"]]), text[m["start"]:m["end"]])
            for m in ex.get("privacy_mask", [])
            if m["label"] in STRUCTURED
        ]
        pred = resolve_overlaps(det.detect(text))
        pairs.append((gold, pred))
        for p in pred:
            pred_total += 1
            if any(p.start < e and s < p.end for (s, e) in all_pii):
                pred_hit_any_pii += 1
    coverage = pred_hit_any_pii / pred_total if pred_total else 0.0
    return pairs, pred_total, coverage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--cache", help="path to a pre-fetched English-rows JSON list")
    args = ap.parse_args()

    if args.cache:
        examples = json.load(open(args.cache))[: args.limit]
    else:
        examples = fetch_english(args.limit)

    label_counts = collections.Counter(
        m["label"] for ex in examples for m in ex.get("privacy_mask", [])
    )
    pairs, pred_total, coverage = build_pairs(examples)
    report = score(pairs)

    print(f"# Redactable vs {DATASET} (English)\n")
    print(f"examples: {len(examples)}   labeled spans: {sum(label_counts.values())}\n")
    print("Deterministic engine — recall on STRUCTURED PII it targets:\n")
    print(f"{'our type':<14}{'precision':>10}{'recall':>9}{'f1':>8}{'gold':>7}")
    print("-" * 48)
    targeted = sorted({v for v in STRUCTURED.values()})
    for t in targeted:
        s = report.per_entity.get(t)
        if s:
            print(f"{t:<14}{s.precision:>10.3f}{s.recall:>9.3f}{s.f1:>8.3f}{s.support:>7}")
    print("-" * 48)
    m = report.micro
    print(f"{'micro':<14}{m.precision:>10.3f}{m.recall:>9.3f}{m.f1:>8.3f}{m.support:>7}")
    print(
        f"\nPrecision-coverage: {coverage:.1%} of the {pred_total} spans we flagged overlap a "
        f"real labeled PII span (any type) — i.e. we redact real PII, not noise."
    )
    contextual_total = sum(label_counts[k] for k in CONTEXTUAL)
    print(
        f"\nOut of scope for the deterministic tier: {contextual_total} contextual spans "
        f"(names/places/orgs) — these need the NER/Gemma tier."
    )


if __name__ == "__main__":
    main()
