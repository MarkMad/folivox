"""User configuration: ``config.toml`` in the user config dir (or ``$FOLIVOX_CONFIG``).

Example::

    [providers]
    tts = "cosyvoice3"
    asr = "auto"
    llm = "ollama"
    voicegen = "qwen3-voicedesign"

    [runtime]                        # optional native C++ runtime (audio.cpp): auto | pytorch | native
    inference = "auto"

    [llm.ollama]
    model = "gemma4:31b-it-qat"

    [llm.openai]                     # any OpenAI-compatible endpoint
    base_url = "https://openrouter.ai/api/v1"
    model = "some/model"
    api_key_env = "OPENROUTER_API_KEY"   # the key itself stays in the environment

    [voicegen.qwen3-voicedesign]
    python = "~/.local/share/tts-bench/qwen3tts/.venv/bin/python"
    model = "~/.local/share/tts-bench/qwen3tts/models/VoiceDesign"

API keys are never read from this file — only from environment variables or the OS keychain.
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
        try:
            data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"{path}: not valid TOML ({e})") from e
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
    return cli_value or os.environ.get(f"FOLIVOX_{kind.upper()}") or section("providers").get(kind)


RUNTIMES = ("auto", "pytorch", "native")


def runtime(cli_value: str | None = None) -> str:
    """Inference runtime: CLI option > ``FOLIVOX_RUNTIME`` > ``[runtime] inference`` in config > ``auto``."""
    value = (cli_value or os.environ.get("FOLIVOX_RUNTIME") or section("runtime").get("inference")
             or "auto")
    value = str(value).strip().lower()
    if value not in RUNTIMES:
        raise ValueError(f"Unknown inference runtime {value!r}; choose one of {', '.join(RUNTIMES)}")
    return value


def save_runtime(value: str) -> None:
    """Write ``[runtime] inference`` to config.toml (a ``.bak`` copy is kept: comments are lost on rewrite)."""
    import shutil

    import tomli_w

    if value not in RUNTIMES:
        raise ValueError(f"Unknown inference runtime {value!r}; choose one of {', '.join(RUNTIMES)}")
    path = config_path()
    data = dict(load())
    old = data.get("runtime")
    data["runtime"] = {**(old if isinstance(old, dict) else {}), "inference": value}
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.write_text(tomli_w.dumps(data), encoding="utf-8")
    load.cache_clear()


def native_options() -> dict:
    """``[runtime.native]``: ``backend`` (auto|metal|cuda|vulkan), ``weights`` (q8_0|f32), ``weight_type``."""
    return {"backend": "auto", "weights": "q8_0", "weight_type": "f16", **section("runtime.native")}


KEYCHAIN_SERVICE = "folivox"


def keychain_get(name: str) -> str | None:
    """A key saved in the OS keychain (optional ``keyring`` package; the web UI stores keys there)."""
    try:
        import keyring

        return keyring.get_password(KEYCHAIN_SERVICE, name) or None
    except Exception:  # noqa: BLE001 — no keyring installed or no backend: fall back to the environment only
        return None


def keychain_set(name: str, value: str) -> None:
    import keyring

    keyring.set_password(KEYCHAIN_SERVICE, name, value)


def keychain_delete(name: str) -> None:
    import keyring

    try:
        keyring.delete_password(KEYCHAIN_SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass


def api_key(env_names: list[str] | str, provider_name: str) -> str:
    """Environment variable first, then the OS keychain. Never the config file."""
    names = [env_names] if isinstance(env_names, str) else env_names
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    for n in names:
        if value := keychain_get(n):
            return value
    raise ValueError(f"{provider_name}: set the API key in the environment variable {names[0]} or save it in the "
                     f"web interface (`folivox ui`); it is used at your own cost and never stored in a file")


def output_dir() -> Path:
    """Where the studio puts finished audiobooks unless told otherwise: ``FOLIVOX_OUTPUT_DIR`` or ``~/Audiobooks``."""
    return Path(os.environ.get("FOLIVOX_OUTPUT_DIR") or Path.home() / "Audiobooks").expanduser()
