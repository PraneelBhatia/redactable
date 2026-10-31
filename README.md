<h1 align="center">Redactable</h1>

<p align="center">
  <b>Deterministic-first PII/PHI de-identification you can <i>prove</i>.</b><br>
  Benchmarked recall · versioned jurisdiction policies · reversible tokenization · reproducible audit trail.
</p>

<p align="center">
  <code>pip install redactable</code> &nbsp;·&nbsp; Apache-2.0 &nbsp;·&nbsp; runs anywhere your data already lives
</p>

---

> **De-identification is a *proof* problem, not a model problem.**
> A team that ships data across a trust boundary — to a vendor, a cloud LLM, or a shared
> training corpus — cannot adopt a redactor they can't **measure, version, or audit**.
> Redactable makes accuracy a number you can put in CI.

## Why another redaction tool?

Most PII tools are a pile of regexes or a thin wrapper around an LLM, and neither tells you
*how much they miss*. Redactable is built around three convictions the alternatives get wrong:

1. **Deterministic-first.** Structured identifiers (credit cards, IBANs, SSNs) are caught by
   **regex + checksum** — a Luhn or MOD-97 check is provably correct, reproducible, and
   auditable. A probabilistic LLM can't beat a checksum and only adds non-determinism and
   hallucination risk to the one category where a miss is a breach.
2. **The model is a commodity; the *eval* is the product.** Contextual PII (names, locations)
   is handled by an **encoder NER** (GLiNER) — non-autoregressive, so it can't hallucinate or
   regurgitate — and *every* engine (ours, Presidio, a cloud API) is scored on the same labeled
   corpus. If recall drops, your build fails.
3. **Versioned and auditable.** Declarative **policy packs** select the entity types currently
   mapped in the library. **Reversible tokenization** lets transformed data
   stays joinable, and a reproducible **audit manifest** of exactly what was redacted, by which
   policy version, by which engine version, when.

## Quick start

```bash
pip install redactable

# De-identify a file and write a reproducible audit manifest alongside it
redactable redact notes.txt --policy hipaa-safe-harbor --out notes.redacted.txt --audit notes.audit.json

# Add contextual entities (names, locations) with the optional encoder NER
pip install "redactable[ner]"
redactable redact notes.txt --policy hipaa-safe-harbor --ner --out notes.redacted.txt

# Measure full-span recall against a labeled corpus; fail on misses or missing support
redactable eval --corpus corpus/seed.jsonl --policy pii-structured --gate
```

The gate uses **type-aware full-span containment**, with one prediction per gold entity.
A prediction must cover every character of a gold span to receive credit; exact-boundary
and relaxed-overlap scores are separate diagnostics in `--json`. Every thresholded type
needs at least one gold example. Missing support fails the gate, including an empty corpus.
Reports list unmeasured and ungated types. A passing gate measures only the supplied labels,
examples and thresholds; it does not establish that arbitrary text is free of PII.

```python
from redactable import Redactor

# The deterministic core (no model, no download) catches structured identifiers:
r = Redactor.from_policy("hipaa-safe-harbor")
out = r.redact("Email jane@acme.io or call (212) 555-0188; card 4111 1111 1111 1111.")
print(out.text)
# Email [EMAIL] or call [PHONE]; card [CREDIT_CARD].

# Names/locations need the optional encoder NER — add it explicitly:
#   from redactable.detectors.ner import GlinerDetector
#   r = Redactor.from_policy("hipaa-safe-harbor",
#                            detectors=[*r.detectors, GlinerDetector()])
```

Use the reusable GitHub Action to gate PRs:

```yaml
# .github/workflows/pii-gate.yml
- uses: redactable/redactable@v0
  with:
    corpus: corpus/seed.jsonl
    policy: pii-structured   # deterministic types only — passes with no model
```

## Names & places, in any runtime

Structured identifiers use regex patterns and checksum validation. **Contextual** PII (names, places, orgs) has no
checksum, so it needs a model — and the engine swaps in whichever model fits the runtime,
behind one `Detector` interface. **GLiNER (a small CPU encoder) is the default contextual
engine; Gemma is the last-resort fallback** for when you have a GPU and want max recall.

```bash
# Default: GLiNER — an encoder NER (auditable, CPU, fast, can't hallucinate)
pip install "redactable[ner]"
redactable redact notes.txt --policy hipaa-safe-harbor --ner

# Last resort (max recall, needs a GPU/server): Gemma via any OpenAI-compatible endpoint,
# e.g. Ollama — `ollama run gemma3` — text never leaves your machine
redactable redact notes.txt --policy hipaa-safe-harbor --llm --llm-model gemma3

# In the browser: Gemma-4 on WebGPU (see web/) — the GPU "last resort" tier, runs in the tab
```

Same policies, same eval harness, same audit trail — only the contextual `Detector` changes.
A missing or failing configured detector aborts redaction; partially protected output is
not returned. Install and verify optional models explicitly before using them.

## Drop it into your coding agent

Scrub PII before it reaches the model — via the familiar mechanisms:

```bash
# MCP server — one-line add for any MCP-aware agent (Claude Code, Cursor, …)
pip install "redactable[mcp]"
claude mcp add redactable -- redactable-mcp
```

```bash
# For clients using supported, non-streaming text requests through a local proxy:
redactable serve
export ANTHROPIC_BASE_URL=http://localhost:8080      # Claude Code; or --openai-api-base for others
```

The MCP server exposes `scrub` / `restore` / `detect` tools. The proxy tokenizes detected
structured identifiers in supported message text and restores them in JSON replies.
It accepts text-only OpenAI Chat Completions and Anthropic Messages; streaming, tools,
attachments, metadata and unknown endpoints or fields are rejected before forwarding.
Changing the proxy policy cannot enable contextual detection. Also ships a Claude Code
**pre-send hook** (`hooks/redactable-userpromptsubmit.py`) and a git **pre-commit** hook. Full
guide: [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).

> **Running inside a coding agent?** Verify the actual client route and request schema.
> OAuth or hosted clients may bypass localhost entirely, and agents that require tools or
> streaming are currently unsupported by this proxy. Setup and a synthetic verification
> test: [`docs/AGENT-SETUP.md`](docs/AGENT-SETUP.md).

## What's in the box (v0.1)

- **Deterministic detectors** — email, phone, US SSN, credit card (Luhn), IBAN (MOD-97),
  IPv4/IPv6, US routing (ABA), URL, and more. Confidence is `1.0`/`0.0`, not a guess.
- **Encoder-NER detector** *(optional `pip install redactable[ner]`)* — PERSON / LOCATION / ORG
  via GLiNER. The deterministic core has **zero heavy dependencies**; the `[ner]` extra pulls
  PyTorch + transformers transitively (a large, CPU-capable download), so it stays opt-in.
- **Eval harness** — per-entity precision / recall / F1 over a labeled corpus, with a
  configurable **full-span regression gate** for CI and explicit coverage reporting.
- **Reversible tokenization** — consistent `[TYPE_n]` placeholders, joinable across a document,
  re-identifiable under a local keymap.
- **Policy packs** — declarative, versioned YAML. Ships `hipaa-safe-harbor` (a partial mapping
  of identifier categories, not complete Safe Harbor implementation) and `pii-structured`
  (deterministic types only). A policy declaration does not add detector coverage.
- **CLI + Python library + reusable GitHub Action.**

## Validated on real data

Historical results against the third-party synthetic
[`ai4privacy/pii-masking-200k`](https://huggingface.co/datasets/ai4privacy/pii-masking-200k)
dataset (1,500 English examples) used relaxed-overlap matching. These numbers have **not**
been rerun with the current full-span scorer and do not measure complete removal:

| EMAIL | URL | IBAN | IP_ADDRESS | PHONE | US_SSN | CREDIT_CARD |
|---|---|---|---|---|---|---|
| 1.000 | 1.000 | 1.000 | 0.996 | 0.609 | 0.560 | 0.181* |

The historical overlap precision-coverage was 100%; overlap alone does not prove full
redaction or correct classification. `*`Only 18% of the dataset's synthetic cards are
Luhn-valid. Detection still depends on format and policy, and contextual entities require
optional detectors. Methodology and limitations: [`benchmarks/`](benchmarks/).

## What this is *not*

Redactable does not claim legal compliance and never silently auto-redacts high-stakes PHI as a
fact. It is **assisted de-identification with measured recall** — a high-recall, flag-and-prove
tool whose output you can audit. Compliance is a process; this gives you the evidence for it.

## Project status

Early (`0.1.0`, alpha). The deterministic core + eval harness are the foundation; the roadmap
(hosted pipeline, maintained policy packs, signed attestation, warehouse/log connectors, an
optional browser build) is tracked in [`docs/`](docs/).

## License

Apache-2.0. See [LICENSE](LICENSE).
