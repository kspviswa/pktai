from __future__ import annotations

import os
from typing import Optional, List, Dict, Any

from openai import AsyncOpenAI


class LLMService:
    """Thin abstraction over an OpenAI-compatible chat completion endpoint.

    Defaults target to a local Ollama server, but works with any OpenAI-compatible URL.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.2,
        client: Optional[AsyncOpenAI] = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self._client = client or AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)

    @classmethod
    def from_env(cls) -> "LLMService":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        # Ollama ignores the key but OpenAI client requires something present
        api_key = os.getenv("OPENAI_API_KEY", "ollama")
        model = os.getenv("OLLAMA_MODEL", "qwen3:latest")
        # Allow override; default aligns with current UI expectations
        try:
            temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
        except ValueError:
            temperature = 0.2
        return cls(base_url=base_url, api_key=api_key, model=model, temperature=temperature)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send messages and return assistant content (non-streaming).

        Returns a user-friendly placeholder if no content is produced.
        """
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
        }
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)

        resp = await self._client.chat.completions.create(**payload)
        content = resp.choices[0].message.content if resp.choices else None
        return content or "(no response)"

    async def list_models(self) -> List[str]:
        """List available model IDs from the OpenAI-compatible server (e.g., Ollama)."""
        models = await self._client.models.list()
        # OpenAI client returns an object with .data, each having .id
        ids: List[str] = []
        for m in getattr(models, "data", []) or []:
            mid = getattr(m, "id", None)
            if isinstance(mid, str):
                ids.append(mid)
        return ids
