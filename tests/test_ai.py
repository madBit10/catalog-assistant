"""The AI layer on its own: tidy() rules, OllamaClient and ClaudeClient error handling.
Ollama is faked with httpx.MockTransport; Claude with a fake SDK client. No network, no cost."""
import json
from io import BytesIO
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from PIL import Image

from app.services.ai import AIError, CatalogListing, ClaudeClient, OllamaClient, tidy


def clean_jpeg():
    buf = BytesIO()
    Image.new("RGB", (2048, 2048), "white").save(buf, "JPEG")
    return buf.getvalue()


GOOD = {"is_product": True, "title": "  Navy Cotton T-Shirt ", "description": "A navy tee.",
        "category": "men", "colours": ["Navy", "navy ", "WHITE"], "tags": ["T-Shirt", "cotton", "t-shirt"]}


# ---------- tidy(): code enforces the prompt's rules ----------

def test_tidy_fixes_contradiction_when_not_a_product():
    # Real case from Ollama: is_product=false but category="kids"
    out = tidy(CatalogListing(**{**GOOD, "is_product": False, "category": "kids"}))
    assert (out.category, out.colours, out.tags, out.description) == ("none", [], [], "")


def test_tidy_cleans_lists_and_title():
    out = tidy(CatalogListing(**GOOD))
    assert out.title == "Navy Cotton T-Shirt"            # spaces trimmed
    assert out.colours == ["navy", "white"]              # lowercased, duplicates removed
    assert out.tags == ["t-shirt", "cotton"]


def test_tidy_cuts_overlong_title_to_db_limit():
    out = tidy(CatalogListing(**{**GOOD, "title": "x" * 500}))
    assert len(out.title) == 200                         # items.title is String(200)


# ---------- OllamaClient (fake HTTP server) ----------

def ollama_with(handler):
    """Why: run OllamaClient against a fake server we control.
    Concept: httpx.MockTransport answers requests in-process, no network."""
    return OllamaClient("http://ollama.test", "qwen2.5vl:7b", http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_ollama_good_answer_is_parsed_and_tidied():
    def handler(request):
        body = json.loads(request.content)
        assert body["format"]["properties"]["category"]["enum"] == ["women", "men", "kids", "baby", "none"]
        assert len(body["messages"][1]["images"]) == 1              # the photo was sent
        return httpx.Response(200, json={"message": {"content": json.dumps(GOOD)},
                                         "prompt_eval_count": 1500, "eval_count": 80})
    result = ollama_with(handler).describe(clean_jpeg())
    assert result.listing.colours == ["navy", "white"]
    assert (result.model, result.input_tokens, result.output_tokens) == ("ollama/qwen2.5vl:7b", 1500, 80)


def test_ollama_not_running_is_transient():
    def handler(request):
        raise httpx.ConnectError("connection refused")
    with pytest.raises(AIError) as err:
        ollama_with(handler).describe(clean_jpeg())
    assert err.value.transient and "isn't reachable" in str(err.value)


def test_ollama_garbage_answer_is_permanent():
    handler = lambda request: httpx.Response(200, json={"message": {"content": "Sorry, I can't do JSON"}})
    with pytest.raises(AIError) as err:
        ollama_with(handler).describe(clean_jpeg())
    assert not err.value.transient


def test_ollama_model_not_downloaded_is_permanent():
    handler = lambda request: httpx.Response(404, json={"error": "model not found"})
    with pytest.raises(AIError) as err:
        ollama_with(handler).describe(clean_jpeg())
    assert not err.value.transient


# ---------- ClaudeClient (fake SDK client) ----------

REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


class FakeClaudeSDK:
    """Why: stands in for anthropic.Anthropic. Its messages.parse returns or raises what we choose."""
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
        self.messages = SimpleNamespace(parse=self.parse)

    def parse(self, **kwargs):
        self.kwargs = kwargs                              # lets tests inspect what was sent
        if self.error:
            raise self.error
        return self.result


def claude_with(sdk):
    return ClaudeClient("sk-test", "claude-haiku-5-5", max_retries=0, client=sdk)


def test_claude_good_answer():
    reply = SimpleNamespace(stop_reason="end_turn", parsed_output=CatalogListing(**GOOD),
                            usage=SimpleNamespace(input_tokens=1200, output_tokens=90))
    sdk = FakeClaudeSDK(result=reply)
    result = claude_with(sdk).describe(clean_jpeg())
    assert result.model == "claude/claude-haiku-5-5" and result.listing.tags == ["t-shirt", "cotton"]
    assert sdk.kwargs["output_format"] is CatalogListing          # structured output requested
    assert sdk.kwargs["messages"][0]["content"][0]["type"] == "image"


def test_claude_rate_limit_is_transient():
    sdk = FakeClaudeSDK(error=anthropic.RateLimitError("slow down", response=httpx.Response(429, request=REQ), body=None))
    with pytest.raises(AIError) as err:
        claude_with(sdk).describe(clean_jpeg())
    assert err.value.transient


def test_claude_wrong_api_key_is_permanent():
    sdk = FakeClaudeSDK(error=anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=REQ), body=None))
    with pytest.raises(AIError) as err:
        claude_with(sdk).describe(clean_jpeg())
    assert not err.value.transient and "401" in str(err.value)


def test_claude_refusal_is_permanent():
    reply = SimpleNamespace(stop_reason="refusal", parsed_output=None, usage=None)
    with pytest.raises(AIError) as err:
        claude_with(FakeClaudeSDK(result=reply)).describe(clean_jpeg())
    assert not err.value.transient
