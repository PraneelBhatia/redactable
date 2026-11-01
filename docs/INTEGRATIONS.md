# Integrating Redactable into a client

Reversible tokenization replaces detected identifiers with consistent placeholders and
restores them locally using a keymap. Detection is limited to the enabled detector and
policy. It does not establish that arbitrary text contains no remaining PII.

## MCP server

```bash
pip install "redactable[mcp]"
claude mcp add redactable -- redactable-mcp
```

Or in `.mcp.json`:

```json
{ "mcpServers": { "redactable": { "command": "redactable-mcp" } } }
```

Tools: `scrub(text, policy="pii-structured", reversible=true)`, `restore(text, session)`,
and `detect(text, policy)`. The agent must choose to call them before sharing data; adding an
MCP server does not automatically filter all model traffic.

## Pre-send guardrail

[`hooks/redactable-userpromptsubmit.py`](../hooks/redactable-userpromptsubmit.py) checks a
Claude Code user prompt. Default behavior is a non-blocking warning; `REDACTABLE_BLOCK=1`
blocks detected identifiers. It does not rewrite the payload or cover every message,
attachment or tool result.

```json
"hooks": {
  "UserPromptSubmit": [
    { "hooks": [ { "type": "command",
      "command": "python3 /ABS/PATH/hooks/redactable-userpromptsubmit.py" } ] }
  ]
}
```

## Local proxy for non-streaming text

```bash
redactable serve
export OPENAI_BASE_URL=http://localhost:8080/v1
# Or, for an Anthropic Messages client:
export ANTHROPIC_BASE_URL=http://localhost:8080
```

The proxy accepts text-only OpenAI Chat Completions and Anthropic Messages. It scrubs every
message and Anthropic's top-level system text, injects a placeholder-preservation prompt,
forwards the transformed JSON, and restores placeholders in JSON replies. API credentials
are passed to the configured upstream; request content is not logged by the proxy.

Streaming, tools, attachments, metadata, unknown fields, query strings, Responses/Codex,
Google and other endpoints return errors **before any upstream request**. Streaming was
disabled because raw byte replacement did not handle JSON delta boundaries or UTF-8 safely.
Literal placeholder syntax is rejected to avoid re-identification collisions. Only supported
deterministic entity types can be selected; this proxy does not load contextual models.

This is a compatibility restriction: many coding agents require tools or streaming and
cannot use this version of the proxy. OAuth clients that ignore the base URL bypass it
entirely. The proxy cannot detect or block traffic it never receives. In-harness adapters,
including [`integrations/opencode/`](../integrations/opencode/), require separate verification.

The exact schema, header boundary and a synthetic mock-upstream verification are in
[`AGENT-SETUP.md`](AGENT-SETUP.md). Flags: `--policy --host --port --anthropic-url --openai-url`.

## Wrap a call in your own application

```python
from redactable.service import RedactionService
svc = RedactionService()
out = svc.scrub(user_text)
reply = call_llm(out["redacted"])
final = svc.restore(reply, out["session"])
```

Review and test all fields your application sends. This example transforms `user_text` only.
