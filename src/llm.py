"""Minimal, provider-agnostic chat client.

Uses the OpenAI-compatible /chat/completions endpoint, which is supported by
OpenAI, DeepSeek, Moonshot, Qwen (DashScope compatible mode), OpenRouter,
Ollama and most self-hosted gateways. Switching provider is a matter of
changing LLM_BASE_URL and LLM_MODEL - no code change.
"""

import json
import os
import re

import requests

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT = 45

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class LLMError(RuntimeError):
    """Raised when the provider call fails or returns unusable output."""


def _config():
    base_url = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    return base_url, api_key, model


def is_configured():
    _, api_key, _ = _config()
    return bool(api_key)


def _proxies():
    """Read the proxy from the environment instead of hardcoding it.

    An explicit LLM_PROXY wins. Otherwise requests already honours
    HTTP_PROXY / HTTPS_PROXY, so returning None is the right default.
    """
    proxy = os.environ.get("LLM_PROXY")
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _strip_fences(text):
    return _FENCE_RE.sub("", text.strip())


def _extract_json(text):
    """Parse JSON out of a model reply, tolerating fences and stray prose."""
    cleaned = _strip_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise LLMError("Model did not return valid JSON")


def _message_content(payload):
    """Pull the assistant text out of a chat-completions response.

    Never index blindly: providers differ, and reasoning models can return
    extra fields. Fail with a readable error instead of an IndexError.
    """
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMError("Response contained no choices")

    message = choices[0].get("message") or {}
    content = message.get("content")

    # Some gateways return content as a list of blocks.
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") in (None, "text")
        ]
        content = "".join(parts)

    if not isinstance(content, str) or not content.strip():
        raise LLMError("Response contained no message content")

    return content


def complete_json(system_prompt, user_prompt, temperature=0.2):
    """Send one prompt pair and return the parsed JSON object."""
    base_url, api_key, model = _config()
    if not api_key:
        raise LLMError("No API key. Set LLM_API_KEY, or run with DEMO_MODE=1.")

    body = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def _post(payload_body):
        try:
            return requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload_body,
                proxies=_proxies(),
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise LLMError(f"Could not reach {base_url}: {exc}") from exc

    response = _post(body)

    # Not every provider accepts response_format. If that is what it rejected,
    # retry once without it - the prompt already demands raw JSON.
    if response.status_code == 400 and "response_format" in response.text:
        fallback = {k: v for k, v in body.items() if k != "response_format"}
        response = _post(fallback)

    if not response.ok:
        detail = response.text[:400]
        raise LLMError(f"Provider returned {response.status_code}: {detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise LLMError("Provider returned a non-JSON body") from exc

    return _extract_json(_message_content(payload))
