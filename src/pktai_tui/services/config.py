from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

CONFIG_DIRNAME = ".pktai"
CONFIG_FILENAME = ".pktai.yaml"


def get_config_dir() -> Path:
    home = Path(os.path.expanduser("~"))
    return home / CONFIG_DIRNAME


def get_config_path() -> Path:
    return get_config_dir() / CONFIG_FILENAME


def ensure_initialized() -> None:
    """Ensure ~/.pktai/.pktai.yaml exists with reasonable defaults.

    Adds a Perplexity provider with static model list by default if file is missing.
    """
    cfg_dir = get_config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = get_config_path()
    if cfg_path.exists():
        return
    data: Dict[str, Any] = {
        "providers": [
            {
                "alias": "Perplexity",
                "base_url": "https://api.perplexity.ai",
                "api_key": "",  # user will fill
                "supports_list": False,
                "static_models": [
                    "sonar",
                    "sonar-pro",
                    "sonar-reasoning",
                    "sonar-reasoning-pro",
                    "sonar-deep-research",
                ],
            }
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
