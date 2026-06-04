#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: warn (or block) when a prompt contains PII.

Register in ~/.claude/settings.json (or .claude/settings.json):

  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command",
        "command": "python3 /ABS/PATH/hooks/redactable-userpromptsubmit.py" } ] }
    ]
  }

By default it adds a non-blocking warning to context. Set REDACTABLE_BLOCK=1 to instead
block submission when PII is detected. Requires `pip install redactable`.

Note: a hook is a *guardrail* — it detects and warns/blocks pre-send. For automatic,
transparent scrubbing of the outgoing payload, use the MCP `scrub` tool or a local proxy.
"""

import json
import os
import sys

try:
    from redactable.service import RedactionService
except Exception:
    sys.exit(0)  # redactable not installed → no-op

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

prompt = data.get("prompt", "") or ""
result = RedactionService().detect(prompt)
if not result["total"]:
    sys.exit(0)

summary = ", ".join(f"{k}×{v}" for k, v in result["found"].items())

if os.environ.get("REDACTABLE_BLOCK") == "1":
    print(json.dumps({
        "decision": "block",
        "reason": (
            f"Redactable: this prompt contains PII ({summary}). "
            "Remove it (or unset REDACTABLE_BLOCK) before sending to the model."
        ),
    }))
else:
    print(f"⚠ Redactable: this prompt appears to contain PII ({summary}) — "
          "consider removing it before it goes to the model.")

sys.exit(0)
