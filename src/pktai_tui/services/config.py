from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

CONFIG_DIRNAME = ".pktai"
CONFIG_FILENAME = "pktai.yaml"


def get_config_dir() -> Path:
    home = Path(os.path.expanduser("~"))
    return home / CONFIG_DIRNAME


def get_config_path() -> Path:
    return get_config_dir() / CONFIG_FILENAME


def ensure_initialized() -> None:
    """Ensure ~/.pktai/pktai.yaml exists with reasonable defaults.

    If missing, create a providers template populated with common providers.
    For providers that support the OpenAI models list endpoint, do not include
    static model names (supports_list: true). Others include representative
    static_models values.
    """
    cfg_dir = get_config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = get_config_path()
    if cfg_path.exists():
        return
    data: Dict[str, Any] = {
        "providers": [
            # Perplexity (OpenAI-format, no /v1/models endpoint)
            {
                "alias": "Perplexity",
                "base_url": "https://api.perplexity.ai",
                "api_key": "",
                "supports_list": False,
                "static_models": [
                    "sonar",
                    "sonar-pro",
                    "sonar-reasoning",
                    "sonar-reasoning-pro",
                    "sonar-deep-research",
                ],
            },
            # OpenAI-compatible (auto model listing)
            {
                "alias": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "api_key": "",
                "supports_list": True,
            },
            {
                "alias": "Together",
                "base_url": "https://api.together.xyz/v1",
                "api_key": "",
                "supports_list": True,
            },
            {
                "alias": "Groq",
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": "",
                "supports_list": True,
            },
            {
                "alias": "Fireworks",
                "base_url": "https://api.fireworks.ai/inference/v1",
                "api_key": "",
                "supports_list": True,
            },
            {
                "alias": "OpenRouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "",
                "supports_list": True,
            },
            {
                "alias": "DeepInfra",
                "base_url": "https://api.deepinfra.com/v1/openai",
                "api_key": "",
                "supports_list": True,
            },
            # Local OpenAI-compatible
            {
                "alias": "Ollama",
                "base_url": "http://localhost:11434/v1",
                "api_key": "",
                "supports_list": True,
            },
            {
                "alias": "LM Studio",
                "base_url": "http://localhost:1234/v1",
                "api_key": "",
                "supports_list": True,
            },
            # Non-OpenAI APIs
            {
                "alias": "Anthropic",
                "base_url": "https://api.anthropic.com",
                "api_key": "",
                "supports_list": False,
                "static_models": [
                    "claude-3-5-sonnet-latest",
                    "claude-3-5-haiku-latest",
                ],
            },
            {
                "alias": "Google Gemini",
                "base_url": "https://generativelanguage.googleapis.com",
                "api_key": "",
                "supports_list": False,
                "static_models": [
                    "gemini-1.5-pro",
                    "gemini-1.5-flash",
                ],
            },
            {
                "alias": "Cohere",
                "base_url": "https://api.cohere.com",
                "api_key": "",
                "supports_list": False,
                "static_models": [
                    "command-r-plus",
                    "command-r",
                ],
            },
            # Mistral has OpenAI-compatible endpoints including /v1/models
            {
                "alias": "Mistral",
                "base_url": "https://api.mistral.ai/v1",
                "api_key": "",
                "supports_list": True,
            },
        ]
    }
    with cfg_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def load_config() -> Dict[str, Any]:
    ensure_initialized()
    cfg_path = get_config_path()
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("providers", [])
    return data


def save_config(data: Dict[str, Any]) -> None:
    cfg_path = get_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def list_providers() -> List[Dict[str, Any]]:
    cfg = load_config()
    providers = cfg.get("providers") or []
    if not isinstance(providers, list):
        return []
    out: List[Dict[str, Any]] = []
    for p in providers:
        if isinstance(p, dict) and p.get("alias") and p.get("base_url"):
            out.append(p)
    # Ensure unique aliases by last-win
    uniq: Dict[str, Dict[str, Any]] = {}
    for p in out:
        uniq[str(p["alias"])]=p
    return list(uniq.values())


def upsert_provider(
    *,
    alias: str,
    base_url: str,
    api_key: str = "",
    supports_list: Optional[bool] = None,
    static_models: Optional[List[str]] = None,
) -> None:
    """Create or update a provider entry by alias."""
    alias = alias.strip()
    if not alias:
        return
    cfg = load_config()
    providers: List[Dict[str, Any]] = list(cfg.get("providers") or [])
    entry: Dict[str, Any] = {
        "alias": alias,
        "base_url": base_url,
        "api_key": api_key,
    }
    if supports_list is not None:
        entry["supports_list"] = bool(supports_list)
    if static_models is not None:
        entry["static_models"] = list(static_models)

    updated = False
    for i, p in enumerate(providers):
        if isinstance(p, dict) and str(p.get("alias")) == alias:
            providers[i] = {**p, **entry}
            updated = True
            break
    if not updated:
        providers.append(entry)
    cfg["providers"] = providers
    save_config(cfg)
