"""Generate ``corpus/seed.jsonl`` with auto-computed span offsets.

Run: ``python corpus/build_seed.py``

Each example is ``(text, [(substring, TYPE), ...])`` and offsets are located
automatically (first unused occurrence), so the labeled corpus can never drift out of
sync with its text. All data here is synthetic — no real individuals — and the
structured identifiers are deliberately checksum-valid so the deterministic engine can
prove it catches them.
"""

from __future__ import annotations

import json
import pathlib

EXAMPLES: list[tuple[str, list[tuple[str, str]]]] = [
    ("Email the lab report to dana.lee@example.com before noon.", [("dana.lee@example.com", "EMAIL")]),
    ("Call the clinic at (212) 555-0188 or fax 312-555-0177.",
     [("(212) 555-0188", "PHONE"), ("312-555-0177", "PHONE")]),
    ("Patient SSN is 123-45-6789; verify before billing.", [("123-45-6789", "US_SSN")]),
    ("Charge card 4111 1111 1111 1111 for the copay.", [("4111 1111 1111 1111", "CREDIT_CARD")]),
    ("Wire the balance to IBAN DE89370400440532013000 by end of day.",
     [("DE89370400440532013000", "IBAN")]),
    ("Server logged a request from 192.168.10.45 during the incident.",
     [("192.168.10.45", "IP_ADDRESS")]),
    ("Routing number 021000021 is printed on the deposit slip.", [("021000021", "US_ROUTING")]),
    ("Results are posted at https://patient-portal.example.org/login overnight.",
     [("https://patient-portal.example.org/login", "URL")]),
    ("Dr. Sarah Chen reviewed the chart this morning.", [("Sarah Chen", "PERSON")]),
    ("The patient was transferred to Boston for the procedure.", [("Boston", "LOCATION")]),
    ("Records were forwarded to Mercy General Hospital last week.",
     [("Mercy General Hospital", "ORG")]),
    ("Reach roberto.alvarez@example.net or call +1 415 555 0143 anytime.",
     [("roberto.alvarez@example.net", "EMAIL"), ("+1 415 555 0143", "PHONE")]),
    ("Nurse Priya Patel updated the medication list at noon.", [("Priya Patel", "PERSON")]),
    ("The sample shipped through Chicago and then Denver before arrival.",
     [("Chicago", "LOCATION"), ("Denver", "LOCATION")]),
    ("Billing email admin@hospital.example, card 5500 0055 5555 5559 on file.",
     [("admin@hospital.example", "EMAIL"), ("5500 0055 5555 5559", "CREDIT_CARD")]),
    ("Forward the intake form to intake@clinic.example.org for processing.",
     [("intake@clinic.example.org", "EMAIL")]),
]


def locate(text: str, items: list[tuple[str, str]]) -> list[dict]:
    spans = []
    cursor: dict[str, int] = {}
    for substring, etype in items:
        start = text.find(substring, cursor.get(substring, 0))
        if start < 0:
            raise SystemExit(f"substring {substring!r} not found in {text!r}")
        end = start + len(substring)
        cursor[substring] = end
        spans.append({"start": start, "end": end, "type": etype})
    spans.sort(key=lambda s: s["start"])
    return spans


def main() -> None:
    out = pathlib.Path(__file__).parent / "seed.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for text, items in EXAMPLES:
            fh.write(json.dumps({"text": text, "spans": locate(text, items)}) + "\n")
    print(f"wrote {len(EXAMPLES)} examples to {out}")


if __name__ == "__main__":
    main()
