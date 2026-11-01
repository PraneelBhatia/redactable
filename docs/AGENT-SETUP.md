# Set up the text-only Redactable proxy

The local proxy removes **detected structured identifiers** from supported message text,
passes API credentials to the configured upstream, and restores placeholders in JSON replies.
It does not guarantee that arbitrary content is free of PII. Verify routing and detection
using synthetic data before relying on it.

## Supported contract

| Input | Behavior |
|---|---|
| POST `/v1/chat/completions` or `/chat/completions` | OpenAI text Chat Completions |
| POST `/v1/messages` or `/messages` | Anthropic text Messages |
| Message content | Strings or nonempty lists of `{type: "text", text: "..."}` blocks |
| OpenAI roles | `system`, `developer`, `user`, `assistant`; every message is scrubbed |
| Anthropic roles and system | `user`, `assistant`; top-level `system` is scrubbed too |
| Streaming | Rejected; omit `stream` or set it to `false` |
| Tools, tool results, schemas, images, files, attachments, metadata, extra fields | Rejected before forwarding |
| Responses/Codex, Google, embeddings, unknown endpoints, query strings | Rejected before forwarding |
| Literal `[TYPE_123]`-style tokens in input text | Rejected to avoid restoration ambiguity |
| Chunked/compressed bodies, duplicate JSON keys, malformed messages | Rejected before forwarding |
| Request headers | Only `Authorization`, `x-api-key`, `anthropic-version` are forwarded; JSON framing is regenerated |
| OAuth or any traffic not routed through localhost | Outside proxy control; cannot be intercepted or blocked here |

Optional top-level fields: `model` (an API model identifier), finite numeric `temperature`,
`top_p`, `max_tokens`; OpenAI also accepts numeric `max_completion_tokens`,
`frequency_penalty`, `presence_penalty`, `seed`, `n`; Anthropic also accepts numeric `top_k`.
Other fields are unsupported. Requests have an 8 MiB size limit.

The proxy uses the deterministic detector. Policies must be nonempty subsets of its supported
types: EMAIL, PHONE, US_SSN, CREDIT_CARD, IBAN, IP_ADDRESS, US_ROUTING, URL. Selecting a policy
with PERSON, LOCATION, ORG, DATE or custom types fails at startup. Changing `--policy` cannot
enable NER. The proxy always uses reversible tokenization for its selected types, independent
of a policy's library transformation actions.

**Compatibility change:** earlier versions silently forwarded unknown schemas and attempted
raw SSE replacement. Those paths are now rejected. A placeholder can split across JSON delta
events, and byte chunks can split UTF-8; the old algorithm did not handle those reliably.
Streaming restoration is disabled until an event-aware implementation is tested.

## Start and configure a client

```bash
pip install redactable
redactable serve                         # http://127.0.0.1:8080
```

For an OpenAI Chat Completions client that honors this setting:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8080/v1
```

For an Anthropic Messages client that honors it:

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8080
```

Disable streaming and use text-only requests. Coding agents commonly require tool calls or
streaming and therefore may be incompatible. These settings alone do not prove that a client
uses the proxy. No current agent product or OAuth flow is claimed as end-to-end verified.
An OAuth subscription client can use a different backend and ignore these settings entirely.
For such clients, review an in-harness integration separately; the
[`opencode adapter`](../integrations/opencode/) and
[`pre-send hook`](../hooks/redactable-userpromptsubmit.py) have their own limited scope.

Flags: `--host --port --policy --openai-url --anthropic-url`.
Credentials, model identifiers and inference options are protocol fields, not text to be
redacted. Do not put sensitive user data in them. Custom headers are dropped. This proxy is
not an OS network firewall, and it cannot cover hosted clients that never contact it.

## Verify with synthetic data

Use a mock upstream, never real user records. In terminal 1:

```bash
python3 - <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        print("SYNTHETIC UPSTREAM RECEIVED:", body.decode())
        data = b'{"choices":[{"message":{"content":"ok"}}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
HTTPServer(("127.0.0.1", 9999), H).serve_forever()
PY
```

In terminal 2:

```bash
redactable serve --openai-url http://127.0.0.1:9999
```

In terminal 3:

```bash
curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H 'authorization: Bearer test' -H 'content-type: application/json' \
  -d '{"model":"x","stream":false,"messages":[{"role":"user","content":"synthetic ssn 123-45-6789, email me@example.com"}]}'

# Must return 422, with no new request at the mock upstream:
curl -s http://127.0.0.1:8080/v1/responses \
  -H 'content-type: application/json' -d '{"input":"synthetic me@example.com"}'
```

The supported request should contain `[US_SSN_1]` and `[EMAIL_1]` at the mock, with none of
the corresponding original characters left. This verifies only these synthetic examples.
Repeat with the actual client's payload shape and all relevant policy types. Do not mistake
a restored local reply for proof of outbound filtering.
