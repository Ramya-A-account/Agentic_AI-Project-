"""
AgentCare LLM Reasoning Layer

This is the piece that turns the pipeline from a purely rule-based
monitoring system into one with an actual reasoning agent in it.

Two callers use this:
  - RecommendationAgent     -> reasons about an incident and writes a
                                specific, context-aware recommendation
  - DailyManagerReportAgent -> reasons about the whole day's data and
                                writes the executive summary

Supports two providers, tried in this priority order based on which
API key is configured in .env:
  1. Groq       (GROQ_API_KEY)      - has a free tier, used by default
  2. Anthropic  (ANTHROPIC_API_KEY) - paid, used if Groq isn't configured

Design principles:
  - Never crash the pipeline. If no API key is set, or the API call
    fails for any reason (network, rate limit, bad response), callers
    fall back to their original deterministic logic. The system should
    degrade gracefully to "rule-based," never to "broken."
  - Every LLM output is tagged with its source ("LLM" or "RULE_BASED")
    wherever it's stored, so the reasoning is auditable — a manager or
    evaluator can always see whether a given recommendation came from
    the model reasoning about the situation, or from a fixed rule.
  - Prompts request structured JSON output and are parsed defensively;
    a malformed response is treated as a failure and falls back too.
"""

import json
import re

from agentcare.config import (
    ANTHROPIC_API_KEY,
    GROQ_API_KEY,
    GROQ_MODEL,
    LLM_ENABLED,
    LLM_MODEL,
    LLM_PROVIDER,
)

_client = None  # lazily constructed; False means "tried and failed, don't retry"
_last_error = None  # the most recent failure reason, surfaced on the dashboard


def _get_client():
    """Lazily construct the provider's client so importing this module
    never fails even if the SDK package or API key isn't present."""
    global _client

    if _client is not None:
        return _client or None

    if not LLM_ENABLED:
        _client = False
        return None

    try:
        if LLM_PROVIDER == "groq":
            from groq import Groq
            _client = Groq(api_key=GROQ_API_KEY)
        elif LLM_PROVIDER == "anthropic":
            import anthropic
            _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        else:
            _client = False
    except Exception as exc:
        print(f"⚠️  LLM reasoning disabled — could not initialize {LLM_PROVIDER} client: {exc}")
        _client = False

    return _client or None


def _extract_json(text_response):
    """Model responses occasionally wrap JSON in prose or code fences.
    Pull out the first {...} block and parse it defensively."""
    match = re.search(r"\{.*\}", text_response, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _call_groq(client, system_prompt, user_prompt, max_tokens):
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content


def _call_anthropic(client, system_prompt, user_prompt, max_tokens):
    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def reason(system_prompt, user_prompt, max_tokens=600):
    """
    Call the configured LLM provider with a system + user prompt,
    expecting a JSON object back. Returns the parsed dict on success,
    or None on any failure (no API key, network error, malformed
    response) so the caller can fall back to deterministic logic.
    """
    global _last_error

    client = _get_client()
    if client is None:
        return None

    try:
        if LLM_PROVIDER == "groq":
            text_response = _call_groq(client, system_prompt, user_prompt, max_tokens)
        else:
            text_response = _call_anthropic(client, system_prompt, user_prompt, max_tokens)
        parsed = _extract_json(text_response)
        if parsed is None:
            _last_error = "Model response wasn't valid JSON"
        else:
            _last_error = None
        return parsed
    except Exception as exc:
        _last_error = str(exc)
        print(f"⚠️  LLM call failed, falling back to rule-based logic: {exc}")
        return None


def is_available():
    return _get_client() is not None


def provider_name():
    return LLM_PROVIDER or "none (rule-based fallback)"


def last_error():
    """The most recent LLM call failure, if any — surfaced on the
    dashboard so a problem (e.g. a deprecated model ID) is visible
    without having to dig through terminal logs."""
    return _last_error
