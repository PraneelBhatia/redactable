# Set up Redactable in any coding agent (agent-followable runbook)

**Goal:** make sure no real PII leaves the machine, regardless of which agent harness you
run — Claude Code, aider, Cursor, Continue, Cline, a custom SDK script, anything.

**Why this works for *any* harness:** every harness, however different, ends in the same place —
an HTTPS call to a model API. Plugins and hooks live *inside* one harness and don't transfer.
The **scrub-proxy** lives on that shared wire, so one setup covers them all: it tokenizes PII
out of each request (`jane@acme.io` → `[EMAIL_1]`), tells the model to keep placeholders
verbatim, forwards to the real API with your key passed straight through, and restores the
originals in the reply. The provider never sees real PII; the agent stays coherent.

> This is a runbook an agent can execute top-to-bottom. Human-friendly version of the same
> material: [`INTEGRATIONS.md`](INTEGRATIONS.md) §3.

---

## Step 1 — Install and start the proxy

```bash
pip install redactable
redactable serve            # listens on http://127.0.0.1:8080 (OpenAI- + Anthropic-compatible)
```

Leave it running (or run it as a background service — see Step 5). Flags:
`--host --port --policy --openai-url --anthropic-url`.

## Step 2 — Point your harness at it

Set the harness's model base URL to the proxy. Pick your row — the rest is identical:

| Harness | One-time setup |
|---|---|
| **Claude Code** | `export ANTHROPIC_BASE_URL=http://127.0.0.1:8080` |
| **aider** | `aider --openai-api-base http://127.0.0.1:8080/v1` (or `export OPENAI_API_BASE=…`) |
| **Cursor / Continue / Cline** | In settings, set the OpenAI base URL / "override base URL" to `http://127.0.0.1:8080/v1` |
| **OpenAI SDK app** (any language) | `export OPENAI_BASE_URL=http://127.0.0.1:8080/v1` |
| **Anthropic SDK app** | `export ANTHROPIC_BASE_URL=http://127.0.0.1:8080` |
| **Anything else** | Find its "base URL" / "API endpoint" setting → `http://127.0.0.1:8080` (Anthropic) or `http://127.0.0.1:8080/v1` (OpenAI) |

**Cover every API-key CLI at once** — set the env vars globally instead of per-harness:

```bash
# ~/.zshrc (or ~/.bashrc)
export OPENAI_BASE_URL=http://127.0.0.1:8080/v1
export OPENAI_API_BASE=http://127.0.0.1:8080/v1      # some tools use this name
export ANTHROPIC_BASE_URL=http://127.0.0.1:8080
```

Now any tool that respects those variables routes through the proxy with zero per-tool config.

## Step 3 — Verify it actually scrubs (don't trust, prove)

Because the proxy restores the reply, a protected session *looks* identical to an unprotected
one. The only honest proof is to inspect what the proxy forwards. Stand up a 10-line echo
"upstream", point the proxy at it, and look at what it received:

```bash
# terminal 1: a mock upstream that just echoes the request body it got
python3 - <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        print("UPSTREAM RECEIVED:", body.decode("utf-8", "replace"))
        self.send_response(200); self.send_header("content-type","application/json"); self.end_headers()
        self.wfile.write(b'{"choices":[{"message":{"role":"assistant","content":"ok"}}]}')
HTTPServer(("127.0.0.1", 9999), H).serve_forever()
PY
```

```bash
# terminal 2: run the proxy pointed at the mock, then send a request with PII through it
redactable serve --openai-url http://127.0.0.1:9999 &
curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H 'authorization: Bearer test' -H 'content-type: application/json' \
  -d '{"model":"x","messages":[{"role":"user","content":"my ssn is 123-45-6789, email me@x.com"}]}' >/dev/null
```

**Pass =** terminal 1 prints `[US_SSN_1]` and `[EMAIL_1]` — never the real SSN or email. That is
proof the model side only ever sees placeholders.

## Step 4 — Know the boundaries (important)

The proxy is universal, but it is not magic. Two honest limits:

1. **OAuth-authenticated harnesses bypass it.** A harness logged in with a subscription account
   (e.g. **opencode**'s ChatGPT login, Claude Pro/Max) talks to a different backend with a
   different request shape, so pointing a base URL at the proxy won't catch it — and the proxy
   doesn't yet parse that shape. For those, use an **in-harness adapter** instead:
   - **opencode** → bundled plugin: [`integrations/opencode/`](../integrations/opencode/) (copy
     both files into `~/.config/opencode/plugin/`). Same tokenize-out / restore-in behavior,
     implemented with opencode's plugin hooks.
   - **Claude Code** → use an **API key** (so the base-URL proxy applies), or the pre-send
     guardrail hook ([`hooks/redactable-userpromptsubmit.py`](../hooks/redactable-userpromptsubmit.py)).
2. **Request shapes covered today:** OpenAI `chat/completions` and Anthropic `messages`. Other
   shapes (OpenAI Responses/Codex, Google) pass through **unscrubbed** until added — they fail
   open, not closed, so don't assume coverage you haven't verified with Step 3.

Also: **GUI/hosted agents** (web ChatGPT, Claude desktop) can't be pointed at localhost — out of
scope by nature. And detection is the deterministic engine by default (`pii-structured`: emails,
phones, SSNs, cards, IBANs, …); names/free-text need a contextual policy (`--policy`).

## Step 5 — (optional) Make it always-on

So you never forget to start it, run the proxy as a background service.

**macOS (launchd):**
```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.redactable.proxy.plist <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.redactable.proxy</string>
  <key>ProgramArguments</key><array>
    <string>$(command -v redactable)</string><string>serve</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
PLIST
launchctl load ~/Library/LaunchAgents/com.redactable.proxy.plist
```

**Linux (systemd user unit):** `~/.config/systemd/user/redactable.service` running
`ExecStart=%h/.local/bin/redactable serve`, then `systemctl --user enable --now redactable`.

---

### TL;DR for an agent

```bash
pip install redactable && redactable serve &           # 1. universal interceptor up
export OPENAI_BASE_URL=http://127.0.0.1:8080/v1         # 2. point your harness at it
export ANTHROPIC_BASE_URL=http://127.0.0.1:8080         #    (use the row for your harness)
# 3. verify with the echo-upstream test above before trusting it
# 4. OAuth harness (opencode/Claude sub)? use integrations/opencode/ or an API key instead
```
