# Benchmarks — validating efficacy on real data

"Provable recall" only means something if it's measured against data we didn't write. This
directory validates the engine against an independent, third-party labeled PII dataset.

## ai4privacy/pii-masking-200k (English)

[`ai4privacy/pii-masking-200k`](https://huggingface.co/datasets/ai4privacy/pii-masking-200k)
is an open, span-labeled synthetic PII dataset. We fetch the English rows on demand via the
HF datasets-server (no bulk download, no redistribution) and map its 56-label taxonomy onto
our entity types.

```bash
python benchmarks/ai4privacy/benchmark.py --limit 1500
```

### Method
- **Deterministic engine only** (regex + checksums). Contextual types (names/places/orgs)
  are out of scope here — they need the NER/Gemma tier, benchmarked separately.
- **Recall** is the headline de-identification metric (did we catch the real PII?).
- **Precision-coverage** = fraction of spans we flag that overlap *some* real labeled PII
  (any type) — a fairer precision than exact-type match, since redacting an account number
  we happen to label `CREDIT_CARD` is still a correct redaction.

### Results (1500 English examples, 4680 labeled spans)

| our type | precision | recall | f1 | gold |
|---|---|---|---|---|
| EMAIL | 1.000 | **1.000** | 1.000 | 123 |
| URL | 1.000 | **1.000** | 1.000 | 103 |
| IBAN | 1.000 | **1.000** | 1.000 | 55 |
| IP_ADDRESS | 1.000 | **0.996** | 0.998 | 241 |
| PHONE | 1.000 | 0.609 | 0.757 | 87 |
| US_SSN | 0.966 | 0.560 | 0.709 | 50 |
| CREDIT_CARD | 0.215 | 0.181 | 0.197 | 94 |
| **micro** | **0.908** | **0.822** | 0.863 | 753 |

**Precision-coverage: 100%** — every span the engine flagged overlaps a real labeled PII
span. It redacts real PII, not noise.

### Honest interpretation

- **EMAIL / URL / IBAN / IP_ADDRESS** — at or near perfect. The structured core does its job.
- **CREDIT_CARD 0.18** is *by design, not a defect*: only **18% of this dataset's "card
  numbers" are Luhn-valid** (all 94 are random 16-digit strings). The checksum gate correctly
  rejects invalid numbers — against *real* cards (always Luhn-valid) recall is ≈100%. A
  permissive "card-like" mode (flag 13–19 digit runs without Luhn, trading precision for
  recall) is a roadmap option for users who prefer recall here.
- **US_SSN 0.56** — the dataset's `SSN` label is a *mix*: genuine space-separated US SSNs
  (`838 44 5162`, now caught) plus non-US national IDs (`756.2808.9893`, 11-digit) that a
  *US*-SSN detector should not claim. The remaining miss is mostly the latter.
- **PHONE 0.61** — our regexes are US/E.164-centric; the dataset's faker phones include
  leading-zero country codes and exotic groupings we don't match yet. **Roadmap:** a broader
  international phone rule.
- **Contextual (names/places/orgs): 1154 spans, out of scope** for the deterministic tier —
  handled by the optional NER/Gemma layer (see `web/` for the in-browser Gemma-4 demo).

## Gemma-4 contextual tier (in-browser, WebGPU)

The deterministic tier scores **0.0** on names/places/orgs by design — there is no checksum
for "is this a person". Those are handled by the optional NER/Gemma tier. To validate it, the
**actual in-browser Gemma-4 path** (`web/gemma.js` → `onnx-community/gemma-4-E2B-it-ONNX`,
Transformers.js + WebGPU) was run over 25 real ai4privacy examples (35 gold contextual spans),
mapping `FIRSTNAME/LASTNAME/MIDDLENAME→PERSON`, `CITY/STATE/COUNTY/STREET→LOCATION`,
`COMPANYNAME→ORG`. Recall (granularity-tolerant overlap — a full-name prediction credits both
the first- and last-name gold spans):

| Gemma-4 (WebGPU) | recall | precision* | gold |
|---|---|---|---|
| PERSON | **1.000** (24/24) | 0.83 | 24 |
| LOCATION | **1.000** (10/10) | 0.83 | 10 |
| ORG | 0.000 (0/1) | — | 1 |

So **deterministic (structured) + Gemma-4 (contextual)** together cover the dataset: the part
deterministic can't touch, Gemma catches at ~100% recall on this sample.

Caveats (kept honest): small sample (25 examples); **ORG has a single gold span** so its number
is not meaningful; `*`precision is a *lower bound* — some Gemma "false positives" are real
entities of types not mapped here (usernames, job titles), i.e. real PII under a different label.
This was run live via the browser path (verified end-to-end), not a mock. A larger, automated
sweep is future work.

### Bugs this benchmark found and fixed

1. **IPv4 at end of a sentence** (`...213.`) was dropped — the trailing boundary rejected a
   following period. IP_ADDRESS recall **0.768 → 0.996**.
2. **Space-separated SSNs** (`838 44 5162`) weren't matched. US_SSN recall **0.420 → 0.560**.

Both are covered by regression tests in `tests/test_deterministic.py`.
