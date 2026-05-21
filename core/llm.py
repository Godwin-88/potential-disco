"""
core/llm.py — Shared LLM client

Single entry point for all LLM calls across the retrieval pipeline.
Supports openai_compatible (Groq, OpenRouter, LocalAI), anthropic, gemini.
Temperature and max_tokens are first-class parameters so callers like the
self-consistency module can vary temperature per call.
"""
from __future__ import annotations
import logging
from config import get_settings

logger = logging.getLogger(__name__)


def call_llm(
    user: str,
    system: str = "",
    max_tokens: int = 1500,
    temperature: float = 0.0,
    json_mode: bool = False,
) -> str:
    """
    Call the configured LLM backend and return the response text.

    Args:
        user:        The user-turn message.
        system:      Optional system prompt.
        max_tokens:  Maximum tokens in the completion.
        temperature: Sampling temperature (0 = deterministic).
        json_mode:   If True, instruct the model to return valid JSON only.
    """
    s = get_settings()
    backend = s.llm_backend.lower()

    if json_mode and system:
        system = system + "\n\nRESPOND WITH VALID JSON ONLY — no markdown, no preamble."
    elif json_mode:
        system = "Respond with valid JSON only — no markdown, no preamble."

    if backend in ("openai", "openai_compatible"):
        return _call_openai_compatible(user, system, max_tokens, temperature, s, json_mode)
    elif backend == "anthropic":
        return _call_anthropic(user, system, max_tokens, s)
    elif backend == "gemini":
        return _call_gemini(user, system, max_tokens, s)
    else:
        raise ValueError(f"Unknown llm_backend: {s.llm_backend!r}")


# ── Backend implementations ───────────────────────────────────────────────────

def _call_openai_compatible(
    user: str, system: str, max_tokens: int, temperature: float, s, json_mode: bool
) -> str:
    import httpx, json as _json

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    payload: dict = {
        "model":       s.openai_compatible_model,
        "messages":    messages,
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        # Groq and most OpenAI-compatible providers support this
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {s.openai_compatible_api_key}",
        "Content-Type":  "application/json",
    }
    response = httpx.post(
        f"{s.openai_compatible_base_url.rstrip('/')}/chat/completions",
        headers=headers,
        json=payload,
        timeout=90.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _call_anthropic(user: str, system: str, max_tokens: int, s) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=s.anthropic_api_key)
    kwargs: dict = dict(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": user}],
    )
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    return msg.content[0].text


def _call_gemini(user: str, system: str, max_tokens: int, s) -> str:
    import google.generativeai as genai
    genai.configure(api_key=s.gemini_api_key)
    model = genai.GenerativeModel(
        model_name="gemini-1.5-pro",
        system_instruction=system or None,
        generation_config={"max_output_tokens": max_tokens},
    )
    return model.generate_content(user).text
