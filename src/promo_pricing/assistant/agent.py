"""Tool-calling assistant over the project's results.

Works with any provider exposing the OpenAI chat-completions API with tools:
Mistral, Groq, OpenAI, or a local Ollama server. Configure with environment variables
(or Streamlit secrets):

    LLM_PROVIDER = groq | mistral | openai | ollama      (presets below; groq has a free API tier)
    LLM_API_KEY  = your key (not needed for ollama)
    LLM_MODEL    = optional, overrides the preset model
    LLM_BASE_URL = optional, overrides the preset URL
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from promo_pricing.assistant.tools import TOOL_SCHEMAS, call_tool

PRESETS = {
    "mistral": {"base_url": "https://api.mistral.ai/v1", "model": "mistral-small-latest"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "qwen2.5:7b"},
}

SYSTEM_PROMPT = """You are the analytics assistant of a promotion and pricing study on dunnhumby retail data
(4 categories: frozen pizza, cold cereal, mouthwash, pretzels; 55 products; 77 US stores; Jan 2009 - Jan 2012).

Rules:
1. Every number you give MUST come from a tool result in this conversation. Never use outside knowledge
   or estimates. If no tool provides the answer, say clearly that the analysis does not cover it.
2. For a question about a specific product, call find_products first to get its upc.
3. Shares in tool results are fractions: 0.326 means 32.6 %. Elasticities are plain numbers (-2.68).
4. Margins are assumptions (the data has no costs): say which margin you used.
5. Answer in the user's language, in 2 to 6 short sentences, most important number first.
   End with the source table(s) in brackets, e.g. [source: promo_roi.csv].
6. Do not answer questions unrelated to this study (other products, other companies, general chat):
   politely say it is outside the scope of the analysis."""


@dataclass
class AgentResult:
    answer: str
    tool_calls: list = field(default_factory=list)   # [{"name", "arguments", "result"}]
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None
    provider_error: bool = False   # the provider failed (quota, network): not a mistake of the model


def make_client(provider: str | None = None, api_key: str | None = None, base_url: str | None = None):
    """OpenAI-compatible client for the chosen provider."""
    from openai import OpenAI   # imported here so the rest of the package works without it

    provider = (provider or os.getenv("LLM_PROVIDER", "groq")).lower()
    preset = PRESETS.get(provider, {})
    url = base_url or os.getenv("LLM_BASE_URL") or preset.get("base_url")
    key = api_key or os.getenv("LLM_API_KEY") or ("ollama" if provider == "ollama" else None)
    if not key:
        raise RuntimeError("No API key: set LLM_API_KEY (or use LLM_PROVIDER=ollama for a local model).")
    # retries are handled by Assistant._create (with longer waits suited to free tiers)
    return OpenAI(base_url=url, api_key=key, max_retries=0), os.getenv("LLM_MODEL") or preset.get("model")


def is_rate_limit(exc: Exception) -> bool:
    """True for HTTP 429 'too many requests' errors, whatever the SDK's exception class."""
    return getattr(exc, "status_code", None) == 429 or type(exc).__name__ == "RateLimitError"


def is_provider_failure(exc: Exception) -> bool:
    """Infrastructure failures (quota, authentication, server, network) are not the model's fault.
    A 400 'bad request' - e.g. a tool call that does not match the schema - is counted against the model."""
    status = getattr(exc, "status_code", None)
    if status is not None:
        return status in (401, 403, 429) or status >= 500
    return type(exc).__name__ in {"APIConnectionError", "APITimeoutError", "RateLimitError"}


def retry_after(exc: Exception) -> float | None:
    """Seconds to wait if the provider says so in a Retry-After header."""
    try:
        return float(exc.response.headers.get("retry-after"))
    except Exception:
        return None


class Assistant:
    def __init__(self, client, model: str, max_steps: int = 6, temperature: float = 0.0,
                 max_retries: int = 4, backoff_s: float = 5.0, sleep=time.sleep):
        self.client, self.model, self.max_steps, self.temperature = client, model, max_steps, temperature
        self.max_retries, self.backoff_s, self.sleep = max_retries, backoff_s, sleep
        self.tools = [{"type": "function", "function": s} for s in TOOL_SCHEMAS]

    def _create(self, messages):
        """One model call, waiting and retrying on rate limits (5 s, 10 s, 20 s, 40 s by default)."""
        for attempt in range(self.max_retries + 1):
            try:
                return self.client.chat.completions.create(model=self.model, messages=messages, tools=self.tools,
                                                           tool_choice="auto", temperature=self.temperature)
            except Exception as e:
                if not is_rate_limit(e) or attempt == self.max_retries:
                    raise
                self.sleep(retry_after(e) or self.backoff_s * 2 ** attempt)

    def ask(self, question: str, history: list | None = None) -> AgentResult:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + (history or []) + [{"role": "user", "content": question}]
        result, t0 = AgentResult(answer=""), time.time()
        try:
            for _ in range(self.max_steps):
                resp = self._create(messages)
                if getattr(resp, "usage", None):
                    result.prompt_tokens += resp.usage.prompt_tokens or 0
                    result.completion_tokens += resp.usage.completion_tokens or 0
                msg = resp.choices[0].message
                calls = msg.tool_calls or []
                if not calls:
                    result.answer = (msg.content or "").strip()
                    break
                messages.append({"role": "assistant", "content": msg.content or "",
                                 "tool_calls": [{"id": c.id, "type": "function",
                                                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                                for c in calls]})
                for c in calls:
                    output = call_tool(c.function.name, c.function.arguments)
                    result.tool_calls.append({"name": c.function.name, "arguments": c.function.arguments, "result": output})
                    messages.append({"role": "tool", "tool_call_id": c.id, "name": c.function.name, "content": output})
            else:
                result.answer = "I could not finish the analysis within the allowed number of steps."
        except Exception as e:   # reported, not raised
            result.error = f"{type(e).__name__}: {e}"
            result.provider_error = is_provider_failure(e)
        result.latency_s = time.time() - t0
        return result
