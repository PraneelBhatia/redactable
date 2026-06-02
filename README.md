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
3. **Provable, not promised.** Versioned **jurisdiction policy packs** (HIPAA Safe Harbor's 18
   identifiers, GDPR special categories), **reversible tokenization** so de-identified data
   stays joinable, and a reproducible **audit manifest** of exactly what was redacted, by which
   policy version, by which engine version, when.

## Quick start

```bash
pip install redactable

# De-identify a file under the HIPAA Safe Harbor policy, emit an audit manifest
redactable redact notes.txt --policy hipaa-safe-harbor --out notes.redacted.txt --audit

# Prove your engine's recall against a labeled corpus — exits non-zero on regression (CI gate)
redactable eval --corpus corpus/seed.jsonl --policy hipaa-safe-harbor --gate
```

```python
from redactable import Redactor

r = Redactor.from_policy("hipaa-safe-harbor")
result = r.redact("Contact Jane Doe at jane@acme.io or 555-0142; card 4111 1111 1111 1111.")
print(result.text)
# Contact [PERSON_1] at [EMAIL_1] or [PHONE_1]; card [CREDIT_CARD_1].
```

## What's in the box (v0.1)

- **Deterministic detectors** — email, phone, US SSN, credit card (Luhn), IBAN (MOD-97),
  IPv4/IPv6, US routing (ABA), URL, and more. Confidence is `1.0`/`0.0`, not a guess.
- **Encoder-NER detector** *(optional `pip install redactable[ner]`)* — PERSON / LOCATION / ORG
  via GLiNER + ONNX, with a CPU fallback. No mandatory GPU, no multi-GB download for the core.
- **Eval harness** — per-entity precision / recall / F1 over a labeled corpus, with a
  configurable **regression gate** for CI.
- **Reversible tokenization** — consistent `[TYPE_n]` placeholders, joinable across a document,
  re-identifiable under a local keymap.
- **Policy packs** — declarative, versioned YAML. Ships HIPAA Safe Harbor.
- **CLI + Python library + GitHub Action.**

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
