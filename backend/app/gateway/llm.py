"""LLM gateway: one endpoint in front of several providers, with PII masking, audit and spans.

Provider choice: AGENTHUB_LLM_PROVIDER if set, otherwise the first provider with a key
(Anthropic → Google Gemini → Groq → OpenAI). With no key at all it runs in **scripted** mode:
the caller supplies a deterministic `scripted_response`, so demos work offline and cost nothing.
Gemini, Groq and Ollama are reached through their OpenAI-compatible endpoints."""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import anthropic
import openai
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.auth.deps import Principal
from app.config import Settings, get_settings
from app.gateway import pii
from app.models import AuditEvent, Decision
from app.tracing.spans import record_span

logger = logging.getLogger("agenthub.llm")


@dataclass(frozen=True)
class Provider:
    name: str
    model: str
    api_key: str | None = None
    base_url: str | None = None


DEFAULT_MODELS = {
    "anthropic": "claude-haiku-5-5",
    "google": "gemini-2.5-flash",
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.2",
}
BASE_URLS = {
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
}


def resolve_provider(settings: Settings) -> Provider:
    keys = {
        "anthropic": settings.anthropic_api_key,
        "google": settings.google_api_key,
        "groq": settings.groq_api_key,
        "openai": settings.openai_api_key,
    }
    name = settings.llm_provider or next((n for n, k in keys.items() if k), "scripted")
    if name == "scripted":
        return Provider("scripted", "scripted")
    model = settings.llm_model or DEFAULT_MODELS.get(name, "")
    if name == "ollama":
        return Provider("ollama", model, api_key="ollama", base_url=settings.ollama_url)
    return Provider(name, model, api_key=keys.get(name), base_url=BASE_URLS.get(name))


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    system: str | None = None
    agent: str | None = None  # which agent is asking (for audit/trace labels)
    max_tokens: int = Field(default=800, le=4000)
    # Returned verbatim in scripted mode (no provider configured, or the provider failed).
    scripted_response: str | None = None


class ChatOut(BaseModel):
    text: str
    provider: str
    model: str
    mode: Literal["live", "scripted"]
    input_tokens: int
    output_tokens: int
    pii_masked: dict[str, int]
    latency_ms: int
    span_id: str | None = None
    fallback_reason: str | None = None


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def _call_provider(p: Provider, body: ChatIn, messages: list[dict], system: str | None):
    timeout = get_settings().llm_timeout_seconds
    if p.name == "anthropic":
        client = anthropic.AsyncAnthropic(api_key=p.api_key, timeout=timeout, max_retries=1)
        extra = {"system": system} if system else {}
        resp = await client.messages.create(
            model=p.model,
            max_tokens=body.max_tokens,
            messages=messages,
            output_config={"effort": "low"},  # short agent steps don't need deep reasoning
            **extra,
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("Model declined the request")
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, resp.usage.input_tokens, resp.usage.output_tokens

    client = openai.AsyncOpenAI(api_key=p.api_key, base_url=p.base_url, timeout=timeout, max_retries=1)
    chat = ([{"role": "system", "content": system}] if system else []) + messages
    resp = await client.chat.completions.create(model=p.model, messages=chat, max_tokens=body.max_tokens)
    usage = resp.usage
    return (
        resp.choices[0].message.content or "",
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
    )


async def chat(
    *,
    session: Session,
    principal: Principal,
    body: ChatIn,
    run_id: str | None = None,
    parent_span_id: str | None = None,
) -> ChatOut:
    settings = get_settings()
    provider = resolve_provider(settings)
    started, t0 = datetime.now(UTC), time.perf_counter()

    # Mask PII before anything leaves for a third-party model.
    counts: dict[str, int] = {}
    system, messages = body.system, [m.model_dump() for m in body.messages]
    if settings.llm_mask_pii:
        masked, counts = await asyncio.to_thread(pii.mask, {"system": system, "messages": messages})
        system, messages = masked["system"], masked["messages"]

    fallback_reason = None
    prompt_text = (system or "") + "".join(m["content"] for m in messages)
    if provider.name != "scripted":
        try:
            text, tokens_in, tokens_out = await _call_provider(provider, body, messages, system)
            mode = "live"
        except (anthropic.APIError, openai.APIError, RuntimeError, TimeoutError) as e:
            fallback_reason = f"{provider.name} failed: {type(e).__name__}"
            logger.warning("LLM provider failed, using scripted response: %s", e)
            provider = Provider("scripted", "scripted")
    if provider.name == "scripted":
        text = body.scripted_response or "(scripted mode: no LLM provider is configured)"
        tokens_in, tokens_out, mode = _estimate_tokens(prompt_text), _estimate_tokens(text), "scripted"

    latency = int((time.perf_counter() - t0) * 1000)
    span = record_span(
        session,
        name=f"llm:{body.agent or principal.name}",
        kind="llm",
        start=started,
        run_id=run_id,
        parent_id=parent_span_id,
        attrs={
            "provider": provider.name,
            "model": provider.model,
            "mode": mode,
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "pii_masked": counts,
            "fallback_reason": fallback_reason,
        },
    )
    session.add(
        AuditEvent(
            principal=principal.name,
            role=principal.role.value,
            kind="llm",
            server=provider.name,
            tool=provider.model,
            decision=Decision.allowed,
            reason=fallback_reason or f"{mode} completion",
            pii_masked=sum(counts.values()),
            latency_ms=latency,
            run_id=run_id,
            detail={"agent": body.agent, "input_tokens": tokens_in, "output_tokens": tokens_out},
        )
    )
    session.commit()
    return ChatOut(
        text=text,
        provider=provider.name,
        model=provider.model,
        mode=mode,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        pii_masked=counts,
        latency_ms=latency,
        span_id=span.id,
        fallback_reason=fallback_reason,
    )
