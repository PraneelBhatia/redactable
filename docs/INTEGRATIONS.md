# Integrating Redactable into your coding agent

Three drop-in ways to scrub PII before it reaches an LLM, from "one line" to "fully automatic".

The shared idea: **reversible tokenization**. PII becomes consistent tokens (`[EMAIL_1]`) on
the way out and is restored locally on the way back, so the model never sees real values but
the round-trip stays coherent. (Everything runs on the deterministic engine — no model, no
network — so it's safe in an always-on interceptor.)

## 1. MCP server (the one-line drop-in)

Works with any MCP-aware agent (Claude Code, Cursor, …).

```bash
pip install "redactable[mcp]"
claude mcp add redactable -- redactable-mcp      # Claude Code
```
or in `.mcp.json`:
```json
{ "mcpServers": { "redactable": { "command": "redactable-mcp" } } }
```

Tools exposed:
- `scrub(text, policy="pii-structured", reversible=true)` → `{redacted, entities, session}`
- `restore(text, session)` → originals put back
- `detect(text, policy)` → what PII is present, without changing anything

The agent calls `scrub` before sharing data and `restore` on the reply. *Model-invoked* — great
for "scrub this before I send it"; for guaranteed automatic filtering, use #2 or #3.

## 2. Pre-send hook (a guardrail)

A Claude Code `UserPromptSubmit` hook that warns (or blocks) when a prompt contains PII.
Ship-ready at [`hooks/redactable-userpromptsubmit.py`](../hooks/redactable-userpromptsubmit.py):

```json
"hooks": {
  "UserPromptSubmit": [
    { "hooks": [ { "type": "command",
      "command": "python3 /ABS/PATH/hooks/redactable-userpromptsubmit.py" } ] }
  ]
}
```
Default: non-blocking warning in context. `REDACTABLE_BLOCK=1` blocks submission instead.
A hook can *detect + warn/block* pre-send, but it can't silently rewrite the payload — for that,
use #1 (model calls `scrub`) or #3.

## 3. Local scrub proxy (fully automatic, any agent) — roadmap

The only point every agent shares is its HTTP call to the model. A local OpenAI/Anthropic-
compatible proxy that tokenizes message bodies, forwards to the real API, and reverses the reply
makes redaction automatic and transparent — point the agent at it with one env var
(`ANTHROPIC_BASE_URL` / `--openai-api-base`). Planned as `redactable serve`.

## Own the agent code? Wrap the call directly

```python
from redactable.service import RedactionService
svc = RedactionService()
out = svc.scrub(user_text)                 # out["redacted"], out["session"]
reply = call_llm(out["redacted"])          # model sees [EMAIL_1], never the real value
final = svc.restore(reply, out["session"]) # restore locally
```
