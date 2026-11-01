"""`redactable serve` — a local scrub-proxy that sits between a coding agent and the LLM API.

Point a compatible text client at it. For each supported request it:
  1. tokenizes PII out of the messages (reversibly: jane@acme.io -> [EMAIL_1]),
  2. injects a small meta-prompt telling the model to keep the placeholders verbatim,
  3. forwards to the real API with your key passed straight through,
  4. restores the originals in the JSON reply — locally.

Only non-streaming text requests on the documented endpoints are supported. Unknown
schemas are rejected before forwarding. Detection is limited to the policy's structured
types; this is not a network interceptor or a guarantee that all PII is removed.
"""

from __future__ import annotations

import json
import math
import re
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

ROUTES = {
    "/messages": "anthropic",
    "/v1/messages": "anthropic",
    "/chat/completions": "openai",
    "/v1/chat/completions": "openai",
}
MAX_REQUEST_BYTES = 8 * 1024 * 1024
_PLACEHOLDER = re.compile(r"\[[A-Z_]+_[0-9]+\]")


class UnsupportedRequest(ValueError):
    """A request cannot be safely transformed under the supported text-only schema."""


def _validate_text(content) -> None:
    if isinstance(content, str):
        if _PLACEHOLDER.search(content):
            raise UnsupportedRequest("literal redaction placeholders are unsupported")
        return
    if isinstance(content, list) and content:
        for block in content:
            if (not isinstance(block, dict) or set(block) != {"type", "text"}
                    or block["type"] != "text" or not isinstance(block["text"], str)):
                raise UnsupportedRequest("only plain text content blocks are supported")
            _validate_text(block["text"])
        return
    raise UnsupportedRequest("content must be a string or nonempty list of text blocks")


def _validate_request(body, fmt: str) -> None:
    if fmt not in {"openai", "anthropic"}:
        raise UnsupportedRequest("unsupported API format")
    if not isinstance(body, dict):
        raise UnsupportedRequest("request must be a JSON object")
    numeric = {"temperature", "top_p", "max_tokens"}
    if fmt == "openai":
        numeric |= {"max_completion_tokens", "frequency_penalty", "presence_penalty", "seed", "n"}
    else:
        numeric |= {"top_k"}
    allowed = {"model", "messages", "stream"} | numeric
    if fmt == "anthropic":
        allowed.add("system")
    if set(body) - allowed:
        raise UnsupportedRequest("unsupported request fields (tools and metadata are unsupported)")
    if "stream" in body and body["stream"] is not False:
        raise UnsupportedRequest("streaming is unsupported; set stream to false")
    if "model" in body and (not isinstance(body["model"], str)
                            or not re.fullmatch(r"[A-Za-z0-9_./:-]+", body["model"])):
        raise UnsupportedRequest("model must be an API model identifier")
    for key in numeric & set(body):
        value = body[key]
        if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
            raise UnsupportedRequest("inference parameters must be finite numbers")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise UnsupportedRequest("messages must be a nonempty list")
    roles = {"user", "assistant"}
    if fmt == "openai":
        roles |= {"system", "developer"}
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or not isinstance(message["role"], str) or message["role"] not in roles):
            raise UnsupportedRequest("unsupported message fields or role")
        _validate_text(message["content"])
    if "system" in body:
        _validate_text(body["system"])


def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise UnsupportedRequest("duplicate JSON fields are unsupported")
        result[key] = value
    return result


# --------------------------------------------------------------------------- transforms

class ConversationRedactor:
    """Per-request redactor: consistent tokens across the whole conversation + a keymap."""

    def __init__(self, policy: str = "pii-structured") -> None:
        self._det = DeterministicDetector()
        self._pol = Policy.load(policy)
        if not self._pol.entities or set(self._pol.entities) - self._det.supported_types:
            raise ValueError("proxy policies must declare only supported deterministic entity types")
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
    if isinstance(content, list):  # validated text blocks
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
    _validate_request(body, fmt)
    messages = body["messages"]

    if fmt == "anthropic":
        for m in messages:
            m["content"] = _scrub_content(m.get("content"), redactor)
        system = body.get("system")
        if system is None:
            body["system"] = META_PROMPT
        else:
            body["system"] = _append_meta(_scrub_content(system, redactor))
    else:  # validated OpenAI chat-completions schema
        system_msg = next((m for m in messages if m.get("role") == "system"), None)
        for m in messages:
            m["content"] = _scrub_content(m["content"], redactor)
        if system_msg is not None:
            system_msg["content"] = _append_meta(system_msg["content"])
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


# --------------------------------------------------------------------------- server

class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep stdout clean; never log request content
        pass

    def _route(self):
        fmt = ROUTES.get(self.path)
        if fmt is None:
            raise UnsupportedRequest("unsupported endpoint or query string")
        return fmt, self.server.upstream[fmt]

    def _upstream_headers(self, length: int) -> dict:
        allowed = {"authorization", "x-api-key", "anthropic-version"}
        headers = {k: v for k, v in self.headers.items() if k.lower() in allowed}
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(length)
        headers["Accept-Encoding"] = "identity"  # don't let upstream gzip the body
        return headers

    def do_POST(self):
        try:
            fmt, upstream = self._route()
            if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding"):
                raise UnsupportedRequest("encoded or chunked request bodies are unsupported")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isdigit():
                return self._error(400, "redactable proxy: one valid Content-Length is required")
            length = int(lengths[0])
            if length > MAX_REQUEST_BYTES:
                return self._error(413, "redactable proxy: request exceeds size limit")
            raw = self.rfile.read(length)
            body = json.loads(raw, object_pairs_hook=_unique_object)
            redactor = ConversationRedactor(self.server.policy)
            scrubbed = json.dumps(redact_request(body, fmt, redactor), allow_nan=False).encode("utf-8")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._error(400, "redactable proxy: request body is not valid JSON")
        except UnsupportedRequest as exc:
            return self._error(422, f"redactable proxy: {exc}")
        except ValueError:
            return self._error(500, "redactable proxy: invalid proxy policy")
        req = urllib.request.Request(
            upstream + self.path, data=scrubbed, method="POST", headers=self._upstream_headers(len(scrubbed))
        )
        try:
            resp = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as e:
            return self._relay(e.code, e.headers, e.read())
        except urllib.error.URLError:
            return self._error(502, "redactable proxy: upstream unreachable")

        with resp:
            if "text/event-stream" in resp.headers.get("Content-Type", "").lower():
                return self._error(502, "redactable proxy: unexpected upstream streaming response")
            data = resp.read()
        try:
            parsed = json.loads(data)
            if not isinstance(parsed, dict):
                return self._error(502, "redactable proxy: upstream response must be a JSON object")
            data = json.dumps(restore_json_response(parsed, fmt, redactor)).encode("utf-8")
        except (ValueError, TypeError, AttributeError):
            return self._error(502, "redactable proxy: invalid upstream JSON response")
        self._relay(resp.status, resp.headers, data)

    def _relay(self, status: int, headers, data: bytes):
        self.send_response(status)
        for k, v in headers.items():
            if k.lower() not in {"content-length", "content-encoding", "transfer-encoding", "connection"}:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, message: str):
        self.close_connection = True  # rejected bodies may not have been consumed
        data = json.dumps({"error": {"message": message}}).encode("utf-8")
        self._relay(status, {"Content-Type": "application/json"}, data)


def serve(host: str = "127.0.0.1", port: int = 8080, policy: str = "pii-structured",
          anthropic_url: str | None = None, openai_url: str | None = None) -> None:
    ConversationRedactor(policy)  # validate policy before accepting any traffic
    httpd = ThreadingHTTPServer((host, port), _ProxyHandler)
    httpd.policy = policy
    httpd.upstream = {
        "anthropic": anthropic_url or DEFAULT_UPSTREAM["anthropic"],
        "openai": openai_url or DEFAULT_UPSTREAM["openai"],
    }
    print(f"redactable serve → http://{host}:{port}  (policy: {policy})")
    print(f"  Anthropic: point ANTHROPIC_BASE_URL at http://{host}:{port}")
    print(f"  OpenAI:    point the base URL at http://{host}:{port}/v1")
    print("  text-only, non-streaming requests; unsupported schemas are rejected.")
    print("  detects structured PII only; verify routing and coverage. Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
