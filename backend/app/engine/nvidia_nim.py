"""NVIDIA NIM client — OpenAI-compatible API with Anthropic-shaped responses."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
FALLBACK_MODEL = "nvidia/nemotron-3-super-120b-a12b"
MAX_RETRIES = 5


def _block_attr(block: Any, key: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _anthropic_tools_to_openai(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get(
                    "input_schema", {"type": "object", "properties": {}}
                ),
            },
        }
        for tool in tools
    ]


def _anthropic_messages_to_openai(
    messages: list[dict],
    system: str,
) -> list[dict]:
    openai_messages: list[dict] = [{"role": "system", "content": system}]

    for message in messages:
        role = message["role"]
        content = message["content"]

        if role == "user" and isinstance(content, str):
            openai_messages.append({"role": "user", "content": content})
            continue

        if role == "user" and isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_result":
                    openai_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": item["tool_use_id"],
                            "content": item.get("content", ""),
                        }
                    )
            continue

        if role == "assistant" and isinstance(content, list):
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for block in content:
                block_type = _block_attr(block, "type")
                if block_type == "text":
                    text = _block_attr(block, "text", "")
                    if text:
                        text_parts.append(text)
                elif block_type == "tool_use":
                    tool_input = _block_attr(block, "input", {})
                    tool_calls.append(
                        {
                            "id": _block_attr(
                                block, "id", f"call_{uuid.uuid4().hex[:12]}"
                            ),
                            "type": "function",
                            "function": {
                                "name": _block_attr(block, "name", ""),
                                "arguments": json.dumps(tool_input),
                            },
                        }
                    )

            assistant_message: dict[str, Any] = {"role": "assistant"}
            if text_parts:
                assistant_message["content"] = "\n".join(text_parts)
            else:
                assistant_message["content"] = None
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            openai_messages.append(assistant_message)

    return openai_messages


def _openai_response_to_anthropic(data: dict) -> SimpleNamespace:
    choice = data["choices"][0]
    message = choice["message"]
    finish_reason = choice.get("finish_reason", "stop")

    content: list[SimpleNamespace] = []
    text = message.get("content")
    if text:
        content.append(SimpleNamespace(type="text", text=text))

    for tool_call in message.get("tool_calls") or []:
        function = tool_call.get("function", {})
        raw_args = function.get("arguments", "{}")
        try:
            parsed_args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            parsed_args = {"raw": raw_args}
        content.append(
            SimpleNamespace(
                type="tool_use",
                id=tool_call.get("id", f"call_{uuid.uuid4().hex[:12]}"),
                name=function.get("name", ""),
                input=parsed_args,
            )
        )

    stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"
    return SimpleNamespace(
        id=data.get("id"),
        model=data.get("model"),
        content=content,
        stop_reason=stop_reason,
        usage=data.get("usage", {}),
    )


def _resolve_model(model: str, default_model: str) -> str:
    if not model or model.startswith("claude-"):
        return default_model
    return model


def _is_transient(status_code: int) -> bool:
    # The hosted NIM API intermittently answers 404 for models it does serve.
    return status_code == 404 or status_code >= 500


def _models_to_try(primary: str, fallback: str | None) -> list[str]:
    models = [primary]
    if fallback and fallback != primary:
        models.append(fallback)
    return models


@dataclass
class NvidiaNimMessages:
    base_url: str
    api_key: str
    default_model: str = DEFAULT_MODEL
    fallback_model: str | None = FALLBACK_MODEL
    enable_thinking: bool = False
    _client: httpx.AsyncClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=300.0)

    async def create(
        self,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> SimpleNamespace:
        resolved_model = _resolve_model(model, self.default_model)
        openai_tools = _anthropic_tools_to_openai(tools)
        body: dict[str, Any] = {
            "messages": _anthropic_messages_to_openai(messages, system),
            "max_tokens": max_tokens,
            "temperature": 1.0,
            "top_p": 0.95,
        }
        if openai_tools:
            body["tools"] = openai_tools
            body["tool_choice"] = "auto"
            body["chat_template_kwargs"] = {
                "enable_thinking": self.enable_thinking,
                "force_nonempty_content": True,
            }

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        models = _models_to_try(resolved_model, self.fallback_model)
        last_error: Exception | None = None

        for model_index, current_model in enumerate(models):
            body["model"] = current_model
            for attempt in range(MAX_RETRIES):
                response = await self._client.post(url, headers=headers, json=body)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "15"))
                    logger.warning(
                        "NVIDIA NIM rate limited (429) on %s; retrying in %ss (%s/%s)",
                        current_model,
                        retry_after,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                try:
                    response.raise_for_status()
                    if current_model != resolved_model:
                        logger.warning(
                            "NVIDIA NIM request succeeded on fallback model %s "
                            "(primary was %s)",
                            current_model,
                            resolved_model,
                        )
                    return _openai_response_to_anthropic(response.json())
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    transient = _is_transient(response.status_code)
                    if transient and attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    if transient and model_index < len(models) - 1:
                        logger.warning(
                            "NVIDIA NIM model %s failed with HTTP %s after %s "
                            "retries; falling back to %s",
                            current_model,
                            response.status_code,
                            MAX_RETRIES,
                            models[model_index + 1],
                        )
                        break
                    raise

        if last_error:
            raise last_error
        raise RuntimeError("NVIDIA NIM request failed after retries")

    async def close(self) -> None:
        await self._client.aclose()


@dataclass
class NvidiaNimClient:
    """Drop-in replacement for anthropic.AsyncAnthropic using NVIDIA NIM."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    default_model: str = DEFAULT_MODEL
    fallback_model: str | None = FALLBACK_MODEL
    enable_thinking: bool = False
    messages: NvidiaNimMessages = field(init=False)

    def __post_init__(self) -> None:
        self.messages = NvidiaNimMessages(
            base_url=self.base_url,
            api_key=self.api_key,
            default_model=self.default_model,
            fallback_model=self.fallback_model,
            enable_thinking=self.enable_thinking,
        )
