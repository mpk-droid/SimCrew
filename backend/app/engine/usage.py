"""Token usage metering for model clients."""

from __future__ import annotations

from typing import Any


def _field(usage: Any, key: str) -> int:
    value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
    return int(value or 0)


def usage_tokens(usage: Any) -> tuple[int, int]:
    """Return (input_tokens, output_tokens) from an Anthropic or OpenAI usage."""
    if not usage:
        return 0, 0
    input_tokens = (
        _field(usage, "input_tokens")
        + _field(usage, "cache_read_input_tokens")
        + _field(usage, "cache_creation_input_tokens")
    ) or _field(usage, "prompt_tokens")
    output_tokens = _field(usage, "output_tokens") or _field(usage, "completion_tokens")
    return input_tokens, output_tokens


class MeteredClient:
    """Wraps a model client and totals token usage across messages.create calls."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.models: set[str] = set()

    @property
    def messages(self) -> MeteredClient:
        return self

    async def create(self, **kwargs: Any) -> Any:
        response = await self._client.messages.create(**kwargs)
        input_tokens, output_tokens = usage_tokens(getattr(response, "usage", None))
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        model = getattr(response, "model", None) or kwargs.get("model")
        if model:
            self.models.add(model)
        return response

    def snapshot(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "models": sorted(self.models),
        }

    async def close(self) -> None:
        if hasattr(self._client, "close"):
            await self._client.close()
