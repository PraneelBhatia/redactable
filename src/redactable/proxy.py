"""`redactable serve` — a local scrub-proxy that sits between a coding agent and the LLM API.

Point any agent at it (`ANTHROPIC_BASE_URL` / `--openai-api-base`). For each request it:
  1. tokenizes PII out of the messages (reversibly: jane@acme.io -> [EMAIL_1]),
  2. injects a small meta-prompt telling the model to keep the placeholders verbatim,
  3. forwards to the real API with your key passed straight through,
  4. restores the originals in the reply (JSON or streamed SSE) — locally.

So the model provider never sees real PII, but the agent (and you) get coherent output. Pure
stdlib — no new dependencies. The redaction core is deterministic (regex+checksums), JSON-safe
for structured PII, so it's safe to leave on in an always-on interceptor.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from redactable.detectors.deterministic import DeterministicDetector
from redactable.overlap import resolve_overlaps
from redactable.policy import Policy
from redactable.tokenization import Tokenizer

META_PROMPT = (
    "Note: some values below have been replaced with redaction placeholders such as "
    "[EMAIL_1], [US_SSN_2], or [PERSON_1]. Treat each as an opaque stand-in for a real value. "
    "Keep every placeholder exactly and verbatim in your response — do not expand, translate, "
    "guess, or invent the underlying value, and reuse the same placeholder when you refer to "
    "the same entity."
)

DEFAULT_UPSTREAM = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
}


# --------------------------------------------------------------------------- transforms

class ConversationRedactor:
    """Per-request redactor: consistent tokens across the whole conversation + a keymap."""

    def __init__(self, policy: str = "pii-structured") -> None:
        self._det = DeterministicDetector()
        self._pol = Policy.load(policy)
        self._tok = Tokenizer(strategy="tokenize")
        self.keymap: dict[str, str] = {}

    def scrub(self, text: str) -> str:
        if not text:
            return text
        spans = resolve_overlaps(
            [s for s in self._det.detect(text) if self._pol.in_scope(str(s.entity_type))]
        )
        result = self._tok.apply(text, spans)
        self.keymap.update(result.keymap)
        return result.text

    def restore(self, text: str) -> str:
        return Tokenizer.reverse(text, self.keymap)


def _scrub_content(content, redactor: ConversationRedactor):
    if isinstance(content, str):
        return redactor.scrub(content)
    if isinstance(content, list):  # content blocks (vision/anthropic)
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                block["text"] = redactor.scrub(block["text"])
    return content


def _append_meta(content):
    if isinstance(content, list):
        content.append({"type": "text", "text": META_PROMPT})
        return content
    return (content or "") + ("\n\n" if content else "") + META_PROMPT


def redact_request(body: dict, fmt: str, redactor: ConversationRedactor) -> dict:
    """Scrub messages + system and inject the placeholder-preservation meta-prompt."""
    messages = body.get("messages", []) or []

    if fmt == "anthropic":
        for m in messages:
            m["content"] = _scrub_content(m.get("content"), redactor)
        system = body.get("system")
        if system is None:
            body["system"] = META_PROMPT
        else:
            body["system"] = _append_meta(_scrub_content(system, redactor))
    else:  # openai-compatible
        system_msg = next((m for m in messages if m.get("role") == "system"), None)
        for m in messages:
            if m.get("role") != "system":
                m["content"] = _scrub_content(m.get("content"), redactor)
        if system_msg is not None:
            system_msg["content"] = _append_meta(_scrub_content(system_msg.get("content"), redactor))
        else:
            messages.insert(0, {"role": "system", "content": META_PROMPT})
        body["messages"] = messages
    return body


def restore_json_response(body: dict, fmt: str, redactor: ConversationRedactor) -> dict:
    """Restore originals into a non-streamed JSON response."""
    if fmt == "anthropic":
        for block in body.get("content", []) or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                block["text"] = redactor.restore(block["text"])
    else:
        for choice in body.get("choices", []) or []:
            msg = choice.get("message") or {}
            if isinstance(msg.get("content"), str):
                msg["content"] = redactor.restore(msg["content"])
    return body


class StreamRestorer:
    """Restores tokens in a streamed (SSE) body, holding back a possible partial token so a
    placeholder split across chunks is never missed. Safe for structured-PII values (no JSON
    metacharacters), which is the default policy."""

    def __init__(self, redactor: ConversationRedactor) -> None:
        self._r = redactor
        self._buf = ""

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        cut = len(self._buf)
        last_open = self._buf.rfind("[")
        if last_open != -1 and "]" not in self._buf[last_open:]:
            cut = last_open  # might be the start of a token still arriving
        out, self._buf = self._buf[:cut], self._buf[cut:]
        return self._r.restore(out)

    def flush(self) -> str:
        out, self._buf = self._buf, ""
        return self._r.restore(out)


# --------------------------------------------------------------------------- server

class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep stdout clean; never log request content
        pass

    def _route(self):
        if "/messages" in self.path:
            return "anthropic", self.server.upstream["anthropic"]
        return "openai", self.server.upstream["openai"]

    def _upstream_headers(self, length: int) -> dict:
        skip = {"host", "content-length", "accept-encoding", "connection"}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in skip}
        headers["Content-Length"] = str(length)
        headers["Accept-Encoding"] = "identity"  # don't let upstream gzip the body
        return headers

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length", 0) or 0))
        fmt, upstream = self._route()
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return self._error(400, "redactable proxy: request body is not JSON")

        redactor = ConversationRedactor(self.server.policy)
        scrubbed = json.dumps(redact_request(body, fmt, redactor)).encode("utf-8")
        req = urllib.request.Request(
            upstream + self.path, data=scrubbed, method="POST", headers=self._upstream_headers(len(scrubbed))
        )
        try:
            resp = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            return self._relay(e.code, e.headers, e.read())
        except urllib.error.URLError as e:
            return self._error(502, f"redactable proxy: upstream unreachable ({e.reason})")

        if body.get("stream"):
            return self._stream(resp, redactor)
        data = resp.read()
        try:
            data = json.dumps(restore_json_response(json.loads(data), fmt, redactor)).encode("utf-8")
        except json.JSONDecodeError:
            pass
        self._relay(resp.status, resp.headers, data)

    def _stream(self, resp, redactor):
        self.send_response(resp.status)
        for k, v in resp.headers.items():
            if k.lower() not in {"content-length", "content-encoding", "transfer-encoding", "connection"}:
                self.send_header(k, v)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        sr = StreamRestorer(redactor)

        def write_chunk(text: str):
            if not text:
                return
            b = text.encode("utf-8")
            self.wfile.write(f"{len(b):X}\r\n".encode() + b + b"\r\n")
            self.wfile.flush()

        while True:
            chunk = resp.read(2048)
            if not chunk:
                break
            write_chunk(sr.feed(chunk.decode("utf-8", "replace")))
        write_chunk(sr.flush())
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _relay(self, status: int, headers, data: bytes):
        self.send_response(status)
        for k, v in headers.items():
            if k.lower() not in {"content-length", "content-encoding", "transfer-encoding", "connection"}:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, message: str):
        data = json.dumps({"error": {"message": message}}).encode("utf-8")
        self._relay(status, {"Content-Type": "application/json"}, data)


def serve(host: str = "127.0.0.1", port: int = 8080, policy: str = "pii-structured",
          anthropic_url: str | None = None, openai_url: str | None = None) -> None:
    httpd = ThreadingHTTPServer((host, port), _ProxyHandler)
    httpd.policy = policy
    httpd.upstream = {
        "anthropic": anthropic_url or DEFAULT_UPSTREAM["anthropic"],
        "openai": openai_url or DEFAULT_UPSTREAM["openai"],
    }
    print(f"redactable serve → http://{host}:{port}  (policy: {policy})")
    print(f"  Anthropic: point ANTHROPIC_BASE_URL at http://{host}:{port}")
    print(f"  OpenAI:    point the base URL at http://{host}:{port}/v1")
    print("  scrubbing PII before it reaches the model; nothing is logged. Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
