# Redactable — Design Spec

**Date:** 2026-06-02
**Status:** Approved (autonomous mode — decision validated by adversarial red-team, not human gate)
**License:** Apache-2.0

## One-liner

Open-source, **deterministic-first** PII/PHI de-identification you can *prove*: benchmarked
recall, versioned jurisdiction policy packs, reversible tokenization, and a reproducible
audit trail — shipped as a CLI, Python library, and CI gate that runs anywhere your data
already lives.

## How we got here (decision provenance)

Three research/validation workflows drove this design:

1. **Market scout** — ranked four domains; picked Web Accessibility, ranked Data Privacy
   runner-up, demoting it *only* for the "data-residency paradox" (regulated buyers won't
   send PHI to a cloud API → free self-host → no revenue).
2. **Browser-model feasibility** — rated Data Privacy the #1 browser-first fit (5/5),
   because privacy *is* the point; rated accessibility 3/5 (in-browser vision is the weakest leg).
3. **Adversarial red-team** — stress-tested the resulting "browser-first local PII redaction
   powered by Gemma" thesis and returned **REFINE** with these load-bearing corrections:
   - **"Local is the moat" is false** — Chrome 148 ships Gemini Nano as a free browser
     primitive; local inference is a commodity.
   - **A generative LLM is the *wrong tool* for the recall-critical core** — it cannot beat a
     Luhn/MOD-97 checksum on structured identifiers, is non-deterministic and unauditable,
     and general small models miss 30–66% of PII on real clinical text (liability magnet).
   - **The consumer "scrub before you paste" extension is a free-clone graveyard** — Microsoft
     Purview bundles it as an E5 checkbox.
   - **What survives:** the *domain* (de-identification) and the insight that **de-id is a
     PROOF problem, not a model problem.** Teams cannot adopt a redactor they cannot measure,
     version, or audit.

The model layer is treated as **interchangeable commodity**. The moat is the eval harness +
jurisdiction policy packs + reversible tokenization + reproducible audit artifact.

### Where open-source models still live (honoring the "default to open models / Gemma" intent)

Open models are kept exactly where a model *adds* value and *out* of the recall-critical path:
- **GLiNER** (open, ONNX) — encoder NER for contextual PII (names/locations). Non-autoregressive,
  auditable, CPU-capable. This is the open-model workhorse.
- **Gemma 3 270M** (optional) — a fine-tuned, human-gated *disambiguation* pass on genuinely
  ambiguous spans ("the patient in Room 11"). Never the sole detector.
- **Gemma browser "Deep Scan"** (later) — an opt-in WASM/WebGPU deployment target, not the flagship.

## Architecture

Deterministic-first, LLM-last pipeline. Each detector is a plugin behind one interface, so the
eval harness can score *any* engine (ours, Presidio, GLiNER, cloud APIs) on the same corpus.

```
                 ┌─────────────────────────────────────────────┐
   input text ──▶│  Redactor (orchestrator)                     │
                 │   1. run detectors → spans                   │
                 │   2. resolve overlaps (priority + score)     │
                 │   3. apply policy pack (per-type action)     │
                 │   4. transform (mask / tokenize / hash)      │
                 │   5. emit redacted text + audit manifest     │
                 └───────┬───────────────────────┬─────────────┘
                         │                        │
            ┌────────────▼──────────┐   ┌─────────▼───────────────┐
            │ DeterministicDetector │   │ (optional) NerDetector  │
            │  regex + checksum      │   │  GLiNER via ONNX        │
            │  EMAIL, PHONE, SSN,    │   │  PERSON, LOCATION, ORG  │
            │  CREDIT_CARD(Luhn),    │   │  CPU/WASM fallback      │
            │  IBAN(MOD-97), IP, ... │   └─────────────────────────┘
            └────────────────────────┘

   eval corpus (labeled spans) ──▶ Scorer ──▶ per-entity precision/recall/F1
                                              + regression gate (exit non-zero)
```

### Components / units (each independently testable)

| Module | Responsibility | Depends on |
|---|---|---|
| `span.py` | `EntityType` registry, `Span` value object | stdlib |
| `checksums.py` | Luhn, MOD-97 (IBAN), ABA routing — pure functions | stdlib |
| `detectors/base.py` | `Detector` protocol: `detect(text) -> list[Span]` | span |
| `detectors/deterministic.py` | regex + checksum detectors (the recall-critical core) | span, checksums |
| `detectors/ner.py` | optional GLiNER encoder NER (extra dependency) | span |
| `eval/corpus.py` | load/validate labeled fixtures (JSONL of text + gold spans) | span |
| `eval/scorer.py` | match predicted vs gold; precision/recall/F1; regression gate | span, corpus |
| `tokenization.py` | mask / consistent reversible tokenize / hash strategies | span |
| `policy.py` | load versioned policy packs (YAML): in-scope types + per-type action + recall thresholds | span |
| `redactor.py` | orchestrate detectors → resolve overlaps → apply policy → transform → audit manifest | all above |
| `cli.py` | `redactable redact` / `redactable eval` | redactor, scorer, policy |

### Data model

- `EntityType` — string-backed registry (EMAIL, PHONE, US_SSN, CREDIT_CARD, IBAN, IP_ADDRESS,
  US_ROUTING, URL, DATE, PERSON, LOCATION, ORG, …); extensible by policy packs.
- `Span(start, end, entity_type, text, score, detector, valid)` — half-open `[start, end)`,
  `score` in `[0,1]`, `valid` set by checksum where applicable (`True`/`False`/`None`).
- Gold corpus row: `{ "text": str, "spans": [ {start, end, type} ], "meta": {...} }` (JSONL).

### Overlap resolution

When detectors disagree on overlapping spans: prefer (1) checksum-`valid` deterministic spans,
then (2) higher `score`, then (3) longer span. Deterministic high-confidence wins over NER guesses.

### Tokenization strategies

- `mask` — replace with `[TYPE]` (irreversible, simplest).
- `tokenize` — consistent placeholder `[TYPE_n]` stable within a document; a local **keymap**
  (token → original) is persisted so authorized re-identification is possible. Joinability:
  same original value → same token across the corpus when a shared keymap is used.
- `hash` — salted hash (pseudonymization; deterministic, non-reversible without rainbow risk → salted).
- *(later)* `format-preserving` — keep shape (e.g., `***-**-1234`).

### Policy packs (the maintained-corpus moat)

Declarative, versioned YAML. v0.1 ships **HIPAA Safe Harbor (18 identifiers)**. A policy
declares: `version`, in-scope `entities`, the `action` per entity, and `thresholds`
(min recall per entity type) that the eval gate enforces.

### Eval harness + regression gate (build this FIRST)

`redactable eval` runs a detector engine over a labeled corpus and prints per-entity
precision / recall / F1 and a micro/macro summary. With `--gate`, it exits non-zero if any
in-scope entity's recall falls below the policy threshold — so accuracy regressions fail CI.
This makes correctness **provable from commit #1** and forces every later component (encoder
NER, optional LLM) to justify itself against a number.

### Audit manifest (reproducibility)

Every redaction run can emit a manifest: input hash, engine version, detector versions, policy
pack + version, per-type counts, timestamp, and (for tokenize) the keymap reference. This is the
artifact closed SaaS / consumer extensions cannot produce, and the basis of the paid attestation tier.

## Error handling

- Detectors must never crash the pipeline: a failing optional detector is logged and skipped
  (deterministic core still runs). Missing optional deps (`ner`) raise a clear, actionable error
  only when that detector is explicitly requested.
- Corpus loader validates span bounds (`0 <= start < end <= len(text)`) and rejects malformed rows
  with row numbers.
- CLI returns documented exit codes: `0` ok, `1` runtime error, `2` usage error, `3` eval-gate failure.

## Testing strategy (TDD)

Test-first, in build order: checksums → scorer → deterministic detectors (scored against the seed
corpus) → tokenization → policy loading → redactor orchestration → CLI. Property-ish tests for
checksums (known-valid/known-invalid vectors). The seed corpus doubles as both fixture and the
first proof the deterministic engine works.

## MVP scope (v0.1)

Python library + CLI, Apache-2.0, **no browser, no Gemma, no cloud**:
1. Deterministic regex + checksum detectors for ~10 structured PII types.
2. One encoder-NER detector (GLiNER via ONNX) for PERSON/LOCATION/ORG — *optional extra*, CPU fallback.
3. Consistent reversible tokenization with a local keymap.
4. One jurisdiction policy pack: HIPAA Safe Harbor 18 identifiers (declarative YAML).
5. `redactable eval`: per-entity precision/recall + non-zero exit on recall regression.
6. `redactable redact`: de-identify a file/stdin, emit redacted text + audit manifest.
7. A GitHub Action wrapper of the eval/redact command.

## Out of scope (deferred)

Browser/WASM build, Gemma deep-scan, hosted pipeline, warehouse/log connectors, RBAC/SSO,
signed attestation service, image/PDF PII. These are the monetization roadmap, not v0.1.

## Business model (open-core)

- **Free OSS core (Apache-2.0):** the engine, deterministic detectors, eval harness, tokenization,
  open policy packs, CLI, GitHub Action. Distribution channel + credibility.
- **Paid:** hosted/self-hosted pipeline (throughput, lineage, scheduled re-eval), *maintained*
  jurisdiction policy packs kept current with regulation, signed reproducible compliance-evidence
  exports/attestation, team governance, premium warehouse/log connectors, a private fine-tuned
  domain model (e.g. clinical).
- **Buyer:** data-platform / ML-platform / data-engineering teams who de-identify programmatically
  and continuously; bottom-up OSS adoption, no procurement/BAA gate for the wedge.
