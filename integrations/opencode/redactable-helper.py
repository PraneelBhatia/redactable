#!/usr/bin/env python3
"""Scrub helper for the opencode Redactable plugin (redactable.js, same directory).

Protocol: reads {"texts": [...], "policy": "..."} on stdin; scrubs every text through ONE
ConversationRedactor (so tokens like [EMAIL_1] stay consistent across the whole conversation)
and prints {"texts": [...scrubbed...], "keymap": {token: original}, "count": n}.

The plugin keeps the keymap and restores originals itself (plain string replace), so this
process is only ever invoked for the deterministic detect+tokenize step on the way out.

Run with a Python that has `redactable` installed:  pip install redactable
"""
import json
import sys

try:
    from redactable.proxy import ConversationRedactor
except Exception as e:  # redactable not importable with this interpreter
    print(json.dumps({"error": f"import failed: {e}"}))
    sys.exit(0)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        print(json.dumps({"error": "bad input"}))
        return
    texts = data.get("texts") or []
    policy = data.get("policy") or "pii-structured"
    r = ConversationRedactor(policy)
    scrubbed = [r.scrub(t) if isinstance(t, str) else t for t in texts]
    print(json.dumps({"texts": scrubbed, "keymap": r.keymap, "count": len(r.keymap)}))


if __name__ == "__main__":
    main()
