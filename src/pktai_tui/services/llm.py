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
        # Prefer generic envs; fall back to legacy OLLAMA_* for backward compatibility
        base_url = (
            os.getenv("LLM_BASE_URL")
            or os.getenv("OLLAMA_BASE_URL")
            or "http://localhost:11434/v1"
        )
        # Many OpenAI-compatible servers require a key; Ollama ignores it
        api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "ollama"
        model = os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL")
        # Allow override; default aligns with current UI expectations
        try:
            temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
        except ValueError:
            temperature = 0.2
        return cls(base_url=base_url, api_key=api_key, model=model, temperature=temperature)

    @classmethod
    def from_config(
        cls,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: Optional[float] = None,
    ) -> "LLMService":
        """Construct from explicit configuration, with sensible defaults.

        If temperature is None, uses 0.2.
        """
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=0.2 if temperature is None else float(temperature),
        )

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

    async def ping(self) -> tuple[bool, list[str] | None, str | None]:
        """Quick connectivity check returning (ok, models, error_message).

        Used by UI to show a green/red status light and to refresh model choices.
        """
        # 1) Try listing models if supported
        try:
            ids = await self.list_models()
        except Exception:
            ids = None

        if isinstance(ids, list):
            # If we have a non-empty list, prefer the first model and succeed
            if ids:
                try:
                    self.model = ids[0]
                except Exception:
                    pass
                return True, ids, None
            # If listing worked but returned empty, fall through to chat-based check

        # 2) Fallback: attempt a tiny chat completion as connectivity test.
        # Requires that a model is set (e.g., provided by user for Custom providers).
        try:
            # Keep the payload minimal to avoid cost/latency.
            _ = await self.chat(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=8,
            )
            # If we got here without raising, consider connectivity OK.
            return True, ids if isinstance(ids, list) and ids else None, None
        except Exception as e:
            return False, None, str(e)
