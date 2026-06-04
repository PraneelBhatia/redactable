"""Tests for the scrub-proxy transform logic (pure; no network).

The proxy tokenizes PII out of an LLM request, injects a meta-prompt telling the model to
keep the placeholders verbatim, forwards upstream, and restores originals in the reply —
including across streamed (SSE) chunk boundaries.
"""

from redactable.proxy import (
    META_PROMPT,
    ConversationRedactor,
    StreamRestorer,
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


class TestStreamRestorer:
    def test_restores_token_split_across_chunks(self):
        r = ConversationRedactor()
        r.scrub("a@b.com")
        sr = StreamRestorer(r)
        parts = [sr.feed("Use [EMA"), sr.feed("IL_1] today"), sr.flush()]
        assert "".join(parts) == "Use a@b.com today"

    def test_preserves_non_token_brackets(self):
        r = ConversationRedactor()
        sr = StreamRestorer(r)
        out = sr.feed("arr[0] and ") + sr.flush()
        assert out == "arr[0] and "
