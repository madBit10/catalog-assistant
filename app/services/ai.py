# Concept: ADAPTER PATTERN. Ollama and Claude have different APIs, but the
# worker sees ONE method: client.describe(clean_jpeg) -> AIResult.
# Switching providers = one setting (AI_PROVIDER), no worker change.
import base64
from io import BytesIO
from typing import Literal, Protocol

import anthropic
import httpx
from PIL import Image
from pydantic import BaseModel, ValidationError

from app.core.config import settings

AI_IMAGE_PX = 1024   # smaller image = fewer tokens + faster; enough detail for a listing


class CatalogListing(BaseModel):
    """Why: the exact JSON we demand from the AI. Both providers are forced into it
    (Concept: STRUCTURED OUTPUT), and Pydantic rejects anything that doesn't fit.
    Example: {"is_product": true, "title": "Navy Cotton Crew-Neck T-Shirt",
              "category": "men", "colours": ["navy"], "tags": ["t-shirt", "cotton"], ...}"""
    is_product: bool
    title: str
    description: str
    category: Literal["women", "men", "kids", "baby", "none"]
    colours: list[str]
    tags: list[str]


class AIResult(BaseModel):
    """What the worker saves: the listing + which model wrote it + what it cost."""
    listing: CatalogListing
    model: str                      # e.g. "ollama/qwen2.5vl:7b", "claude/claude-haiku-5-5"
    input_tokens: int | None = None
    output_tokens: int | None = None


class AIError(Exception):
    """Why: the worker needs ONE question answered: would retrying help?
    Example: AIError("Local AI isn't running", transient=True)   -> item can be retried
             AIError("AI returned an unusable answer", transient=False) -> needs_review"""
    def __init__(self, message: str, transient: bool):
        super().__init__(message)
        self.transient = transient


SYSTEM_PROMPT = """You write product listings for an online CLOTHING store.
You get ONE product photo on a white background. Follow these rules exactly:
- is_product: true ONLY if the photo shows clothing, footwear or a fashion accessory for sale. Otherwise false.
- If is_product is false: category "none", description "", colours [], tags [], and title = a short plain name of what you see.
- category: who it is for: "women", "men", "kids" (about 3-12 years), "baby" (0-2 years).
- title: at most 8 words. No hype words ("amazing", "perfect"). A brand only if clearly printed.
- description: 2-3 factual sentences (item type, visible material, fit, key details).
  Never invent sizes, prices or materials you cannot see.
- colours: 1-3 main colours, simple lowercase names ("navy", "white").
- tags: 3-8 lowercase search keywords."""

USER_PROMPT = "Write the catalog listing for this photo."


def _shrink(clean_jpeg: bytes) -> bytes:
    """Why: the clean image is 2048 px; AI models don't need that much.
    Example: 2048x2048 (~1.5 MB) -> 1024x1024 (~0.2 MB), ~4x fewer image tokens."""
    with Image.open(BytesIO(clean_jpeg)) as img:
        img.thumbnail((AI_IMAGE_PX, AI_IMAGE_PX))
        out = BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=90)
        return out.getvalue()


def tidy(listing: CatalogListing) -> CatalogListing:
    """Why: models break their own rules (our test: is_product=false but category="kids").
    Code enforces the rules the prompt asked for, whatever the model did.
    Example: {is_product: False, category: "kids", tags: ["x"]} -> category "none", tags []
             colours ["Navy", "navy ", "WHITE"] -> ["navy", "white"]"""
    def clean_list(items: list[str], limit: int) -> list[str]:
        seen = []
        for x in items:
            x = x.strip().lower()
            if x and x not in seen:
                seen.append(x)
        return seen[:limit]

    if not listing.is_product:
        return listing.model_copy(update={"category": "none", "description": "", "colours": [], "tags": [],
                                          "title": listing.title.strip()[:200]})
    return listing.model_copy(update={
        "title": listing.title.strip()[:200],     # DB column is String(200)
        "description": listing.description.strip(),
        "colours": clean_list(listing.colours, 3),
        "tags": clean_list(listing.tags, 8),
    })


class AIClient(Protocol):
    """Concept: PROTOCOL = "anything with this method counts" (duck typing, with type hints).
    OllamaClient, ClaudeClient and the tests' FakeAI all fit without inheriting anything."""
    def describe(self, clean_jpeg: bytes) -> AIResult: ...


class OllamaClient:
    """Why: free, local AI. Talks to the Ollama server on this Mac over HTTP.
    Example: describe(bottle_jpeg) -> AIResult(listing=..., model="ollama/qwen2.5vl:7b",
                                               input_tokens=1399, output_tokens=29)"""
    def __init__(self, url: str, model: str, http: httpx.Client | None = None):
        self.url, self.model = url, model
        self.http = http or httpx.Client(timeout=180)   # local models can take a while

    def describe(self, clean_jpeg: bytes) -> AIResult:
        image_b64 = base64.b64encode(_shrink(clean_jpeg)).decode()
        try:
            r = self.http.post(f"{self.url}/api/chat", json={
                "model": self.model,
                "stream": False,                          # one complete answer, not word by word
                "format": CatalogListing.model_json_schema(),   # forces this JSON shape
                "options": {"temperature": 0},            # Concept: temperature 0 = most predictable answer
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": USER_PROMPT, "images": [image_b64]},
                ],
            })
        except httpx.TransportError:                      # server not running / timed out
            raise AIError("The local AI (Ollama) isn't reachable. Is it running?", transient=True)
        if r.status_code != 200:
            raise AIError(f"Ollama error {r.status_code}", transient=r.status_code >= 500)
        try:
            listing = CatalogListing.model_validate_json(r.json()["message"]["content"])
        except (ValidationError, KeyError, ValueError):
            raise AIError("The AI returned an answer we couldn't use.", transient=False)
        return AIResult(listing=tidy(listing), model=f"ollama/{self.model}",
                        input_tokens=r.json().get("prompt_eval_count"),
                        output_tokens=r.json().get("eval_count"))


class ClaudeClient:
    """Why: paid, stronger AI for the evaluation and demo.
    Example: describe(bottle_jpeg) -> AIResult(..., model="claude/claude-haiku-5-5")"""
    def __init__(self, api_key: str, model: str, max_retries: int, client: anthropic.Anthropic | None = None):
        self.model = model
        # The SDK itself retries 429/5xx/timeouts with exponential backoff
        self.client = client or anthropic.Anthropic(api_key=api_key, max_retries=max_retries)

    def describe(self, clean_jpeg: bytes) -> AIResult:
        image_b64 = base64.b64encode(_shrink(clean_jpeg)).decode()
        try:
            resp = self.client.messages.parse(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                    {"type": "text", "text": USER_PROMPT},
                ]}],
                output_format=CatalogListing,             # SDK turns the model into a JSON schema
            )
        # Concept: TRANSIENT vs PERMANENT. These mean "busy / network": retry later
        except (anthropic.RateLimitError, anthropic.OverloadedError, anthropic.InternalServerError,
                anthropic.APIConnectionError, anthropic.APITimeoutError):
            raise AIError("The AI service is busy right now. Click Retry in a minute.", transient=True)
        except anthropic.APIStatusError as e:             # 400 bad request, 401 wrong key...: retrying won't help
            raise AIError(f"AI request rejected ({e.status_code}).", transient=False)
        except ValidationError:
            raise AIError("The AI returned an answer we couldn't use.", transient=False)

        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            raise AIError("The AI declined to describe this photo.", transient=False)
        return AIResult(listing=tidy(resp.parsed_output), model=f"claude/{self.model}",
                        input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)


def get_ai_client() -> AIClient:
    """Why: the ONE place that reads AI_PROVIDER. The worker calls this and never
    knows which provider it got.
    Example: AI_PROVIDER=ollama -> OllamaClient; AI_PROVIDER=claude -> ClaudeClient"""
    if settings.ai_provider == "claude":
        return ClaudeClient(settings.anthropic_api_key, settings.claude_model, settings.claude_max_retries)
    return OllamaClient(settings.ollama_url, settings.ollama_model)
