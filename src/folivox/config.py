"""User configuration: ``config.toml`` in the user config dir (or ``$FOLIVOX_CONFIG``).

Example::

    [providers]
    tts = "cosyvoice3"
    asr = "auto"
    llm = "ollama"
    voicegen = "qwen3-voicedesign"

    [llm.ollama]
    model = "gemma4:31b-it-qat"

    [llm.openai]                     # any OpenAI-compatible endpoint
    base_url = "https://openrouter.ai/api/v1"
    model = "some/model"
    api_key_env = "OPENROUTER_API_KEY"   # the key itself stays in the environment

    [voicegen.qwen3-voicedesign]
    python = "~/.local/share/tts-bench/qwen3tts/.venv/bin/python"
    model = "~/.local/share/tts-bench/qwen3tts/models/VoiceDesign"

API keys are never read from this file — only from environment variables.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from platformdirs import user_config_dir


def config_path() -> Path:
    env = os.environ.get("FOLIVOX_CONFIG")
    return Path(env).expanduser() if env else Path(user_config_dir("folivox", appauthor=False)) / "config.toml"


@lru_cache(maxsize=1)
def load() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib
    with path.open("rb") as f:
        data = tomllib.load(f)
    _reject_keys(data)
    return data


def _reject_keys(data: dict, where: str = "") -> None:
    for k, v in data.items():
        if isinstance(v, dict):
            _reject_keys(v, f"{where}{k}.")
        elif k.lower() in ("api_key", "key", "token", "secret"):
            raise ValueError(f"{config_path()}: {where}{k} — put API keys in environment variables "
                             f"and reference them with api_key_env")


def section(dotted: str) -> dict:
    """``section("llm.ollama")`` → the ``[llm.ollama]`` table (empty if absent)."""
    node: object = load()
    for part in dotted.split("."):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    return dict(node) if isinstance(node, dict) else {}


def provider(kind: str, cli_value: str | None = None) -> str | None:
    """CLI option > ``FOLIVOX_<KIND>`` env var > ``[providers]`` in config > registry default (None)."""
    return cli_value or os.environ.get(f"FOLIVOX_{kind.upper()}") or load().get("providers", {}).get(kind)


def api_key(env_names: list[str] | str, provider_name: str) -> str:
    names = [env_names] if isinstance(env_names, str) else env_names
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    raise ValueError(f"{provider_name}: set the API key in the environment variable {names[0]} "
                     f"(it is used at your own cost and never stored by Folivox)")
