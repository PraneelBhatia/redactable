"""Text transformations and real HTTP handler parsing with a mocked upstream; no network."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import Mock

import pytest

from redactable.proxy import (
    META_PROMPT,
    ConversationRedactor,
    UnsupportedRequest,
    _ProxyHandler,
    redact_request,
    restore_json_response,
)


class TestConversationRedactor:
    def test_consistent_tokens_and_restore(self):
        r = ConversationRedactor()
        assert r.scrub("email a@b.com") == "email [EMAIL_1]"
        assert r.scrub("again a@b.com now") == "again [EMAIL_1] now"  # same value → same token
        assert r.restore("send to [EMAIL_1]") == "send to a@b.com"


class TestMetaPrompt:
    def test_meta_prompt_mentions_placeholders_and_verbatim(self):
        assert "[EMAIL_1]" in META_PROMPT or "placeholder" in META_PROMPT.lower()
        assert "verbatim" in META_PROMPT.lower() or "exactly" in META_PROMPT.lower()


class TestRedactRequestOpenAI:
    def test_scrubs_content_and_injects_system(self):
        body = {"model": "x", "messages": [{"role": "user", "content": "ssn 123-45-6789"}]}
        out = redact_request(body, "openai", ConversationRedactor())
        assert out["messages"][-1]["content"] == "ssn [US_SSN_1]"
        sys_msgs = [m for m in out["messages"] if m["role"] == "system"]
        assert sys_msgs and META_PROMPT in sys_msgs[0]["content"]

    def test_appends_to_existing_system(self):
        body = {"messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "card 4111 1111 1111 1111"},
        ]}
        out = redact_request(body, "openai", ConversationRedactor())
        assert out["messages"][0]["role"] == "system"
        assert "You are helpful." in out["messages"][0]["content"]
        assert META_PROMPT in out["messages"][0]["content"]
        assert out["messages"][1]["content"] == "card [CREDIT_CARD_1]"

    def test_scrubs_every_system_and_developer_message(self):
        body = {"messages": [{"role": role, "content": "a@b.com"}
                             for role in ("system", "system", "developer", "user")]}
        out = redact_request(body, "openai", ConversationRedactor())
        assert "a@b.com" not in json.dumps(out)
        assert all("[EMAIL_1]" in m["content"] for m in out["messages"])


class TestRedactRequestAnthropic:
    def test_scrubs_top_level_system_and_block_content(self):
        body = {
            "system": "Be terse.",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "email a@b.com"}]},
            ],
        }
        out = redact_request(body, "anthropic", ConversationRedactor())
        assert "Be terse." in out["system"] and META_PROMPT in out["system"]
        assert out["messages"][0]["content"][0]["text"] == "email [EMAIL_1]"

    def test_string_content_and_no_system(self):
        body = {"messages": [{"role": "user", "content": "ip 10.0.0.1"}]}
        out = redact_request(body, "anthropic", ConversationRedactor())
        assert out["messages"][0]["content"] == "ip [IP_ADDRESS_1]"
        assert out["system"].strip() == META_PROMPT.strip() or META_PROMPT in out["system"]


class TestRestoreResponse:
    def test_openai_response_restored(self):
        r = ConversationRedactor()
        r.scrub("a@b.com")  # establishes [EMAIL_1] -> a@b.com
        body = {"choices": [{"message": {"role": "assistant", "content": "reply to [EMAIL_1]"}}]}
        out = restore_json_response(body, "openai", r)
        assert out["choices"][0]["message"]["content"] == "reply to a@b.com"

    def test_anthropic_response_restored(self):
        r = ConversationRedactor()
        r.scrub("a@b.com")
        body = {"content": [{"type": "text", "text": "mail [EMAIL_1]"}]}
        out = restore_json_response(body, "anthropic", r)
        assert out["content"][0]["text"] == "mail a@b.com"


class _Socket:
    def __init__(self, raw):
        self.input = io.BytesIO(raw)
        self.output = bytearray()

    def makefile(self, *args):
        return self.input

    def sendall(self, data):
        self.output.extend(data)


class _Response(io.BytesIO):
    status = 200
    headers: ClassVar = {"Content-Type": "application/json"}


@pytest.fixture
def proxy(monkeypatch):
    upstream = Mock(return_value=_Response(b'{"choices": []}'))
    monkeypatch.setattr("redactable.proxy.urllib.request.urlopen", upstream)

    def request(body, path="/v1/chat/completions", headers=None, policy="pii-structured"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        fields = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
        fields.update(headers or {})
        head = f"POST {path} HTTP/1.1\r\nHost: localhost\r\n"
        head += "".join(f"{k}: {v}\r\n" for k, v in fields.items())
        sock = _Socket(head.encode() + b"\r\n" + raw)
        server = SimpleNamespace(policy=policy, upstream={"openai": "https://mock.invalid",
                                                       "anthropic": "https://mock.invalid"})
        _ProxyHandler(sock, ("127.0.0.1", 1234), server)
        response_head, data = bytes(sock.output).split(b"\r\n\r\n", 1)
        status = int(response_head.split(b" ")[1])
        return status, json.loads(data)

    return request, upstream


def text_request(**extra):
    return {"messages": [{"role": "user", "content": "email canary@example.com"}], **extra}


@pytest.mark.parametrize("body", [
    [], None, {}, {"messages": []}, {"messages": "canary@example.com"},
    {"input": "canary@example.com"}, {"contents": [{"parts": [{"text": "canary@example.com"}]}]},
    text_request(metadata={"email": "canary@example.com"}),
    text_request(tools=[{"description": "canary@example.com"}]),
    text_request(stream=True), text_request(stream="false"),
    text_request(temperature=float("nan")),
    {"messages": [{"role": "user", "content": {"text": "canary@example.com"}}]},
    {"messages": [None]}, {"messages": [{"role": [], "content": "canary@example.com"}]},
    {"messages": [{"role": "tool", "content": "canary@example.com"}]},
    {"messages": [{"role": "assistant", "content": None,
                   "tool_calls": [{"function": {"arguments": "canary@example.com"}}]}]},
    {"messages": [{"role": "user", "content": [
        {"type": "tool_result", "content": "canary@example.com"}]}]},
    {"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "canary@example.com"}}]}]},
    {"messages": [{"role": "user", "content": [
        {"type": "text", "text": "hello", "extra": "canary@example.com"}]}]},
    text_request(messages=[{"role": "user", "content": "literal [EMAIL_1] canary@example.com"}]),
])
@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/messages"])
def test_unsupported_body_never_reaches_upstream(proxy, body, capsys, path):
    request, upstream = proxy
    status, response = request(body, path)
    assert status == 422
    upstream.assert_not_called()
    assert "canary@example.com" not in json.dumps(response)
    assert "canary@example.com" not in str(capsys.readouterr())


@pytest.mark.parametrize("path", ["/v1/responses", "/v1/embeddings", "/v1beta/models/x:generateContent",
                                  "/anything/messages/else", "/v1/chat/completions?email=canary@example.com"])
def test_unsupported_route_never_reaches_upstream(proxy, path):
    request, upstream = proxy
    assert request(text_request(), path)[0] == 422
    upstream.assert_not_called()


@pytest.mark.parametrize("raw", [b"{invalid", b"\xff", b'{"messages":[],"messages":[]}'])
def test_invalid_json_never_reaches_upstream(proxy, raw):
    request, upstream = proxy
    assert request(raw)[0] in {400, 422}
    upstream.assert_not_called()


@pytest.mark.parametrize("headers,status", [({"Content-Length": "bad"}, 400),
                                          ({"Content-Length": "999999999"}, 413),
                                          ({"Content-Encoding": "gzip"}, 422),
                                          ({"Transfer-Encoding": "chunked"}, 422)])
def test_unsupported_framing_never_reaches_upstream(proxy, headers, status):
    request, upstream = proxy
    assert request(text_request(), headers=headers)[0] == status
    upstream.assert_not_called()


def test_contextual_policy_is_rejected(proxy):
    request, upstream = proxy
    assert request(text_request(), policy="hipaa-safe-harbor")[0] == 500
    upstream.assert_not_called()
    with pytest.raises(ValueError, match="deterministic"):
        ConversationRedactor("hipaa-safe-harbor")


@pytest.mark.parametrize("path,field", [("/v1/chat/completions", "choices"),
                                       ("/chat/completions", "choices"),
                                       ("/v1/messages", "content"), ("/messages", "content")])
def test_supported_http_flow_scrubs_then_restores(proxy, path, field):
    request, upstream = proxy
    response = ({"choices": [{"message": {"content": "héllo [EMAIL_1]"}}]} if field == "choices"
                else {"content": [{"type": "text", "text": "héllo [EMAIL_1]"}]})
    upstream.return_value = _Response(json.dumps(response, ensure_ascii=False).encode())
    status, result = request(text_request(stream=False), path,
                             headers={"Authorization": "Bearer test", "X-Custom": "canary@example.com"})
    assert status == 200
    assert "héllo canary@example.com" in json.dumps(result, ensure_ascii=False)
    sent = upstream.call_args.args[0]
    assert b"canary@example.com" not in sent.data
    assert b"[EMAIL_1]" in sent.data
    assert json.loads(sent.data)["messages"][-1]["content"] == "email [EMAIL_1]"
    assert sent.get_header("Authorization") == "Bearer test"
    assert sent.get_header("X-custom") is None


def test_json_escaping_and_concurrent_keymaps(proxy):
    request, upstream = proxy

    def echo(req, **kwargs):
        content = json.loads(req.data)["messages"][-1]["content"]
        return _Response(json.dumps({"choices": [{"message": {"content": content}}]}).encode())

    upstream.side_effect = echo
    values = ["https://example.org/a\\b", "a@example.com", "b@example.com"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda value: request(text_request(messages=[
            {"role": "user", "content": value}])), values))
    assert [r[1]["choices"][0]["message"]["content"] for r in results] == values


def test_unknown_format_rejected():
    with pytest.raises(UnsupportedRequest):
        redact_request(text_request(), "unknown", ConversationRedactor())


@pytest.mark.parametrize("system", [None, {}, [], [{"type": "image", "source": "canary@example.com"}]])
def test_malformed_anthropic_system_never_reaches_upstream(proxy, system):
    request, upstream = proxy
    assert request(text_request(system=system), "/v1/messages")[0] == 422
    upstream.assert_not_called()


def test_text_blocks_and_anthropic_system_are_scrubbed(proxy):
    request, upstream = proxy
    body = text_request(system=[{"type": "text", "text": "canary@example.com"}],
                        messages=[{"role": "user", "content": [
                            {"type": "text", "text": "canary@example.com"}]}])
    assert request(body, "/v1/messages")[0] == 200
    sent = json.loads(upstream.call_args.args[0].data)
    assert sent["system"][0]["text"] == "[EMAIL_1]"
    assert sent["messages"][0]["content"][0]["text"] == "[EMAIL_1]"


@pytest.mark.parametrize("raw", [b"bad JSON", b"[]", b'{"choices": [1]}', b"\xff"])
def test_invalid_upstream_response_is_a_clean_error(proxy, raw):
    request, upstream = proxy
    upstream.return_value = _Response(raw)
    assert request(text_request())[0] == 502


def test_unexpected_sse_is_rejected_without_reading_events(proxy):
    request, upstream = proxy
    response = Mock()
    response.headers = {"Content-Type": "text/event-stream"}
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    upstream.return_value = response
    assert request(text_request())[0] == 502
    response.read.assert_not_called()
