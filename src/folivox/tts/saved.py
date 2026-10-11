"""Voices created in a provider account for books (designed, localized, cloned) and kept for later books.

Only a small list of ids and names is stored here (``cloud_voices.json`` in the user data dir); the voice itself
lives in the provider's account until the user deletes it. No audio and no keys are stored.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def _path() -> Path:
    from platformdirs import user_data_dir

    return Path(user_data_dir("folivox", appauthor=False)) / "cloud_voices.json"


def _read() -> list[dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def listing(provider: str | None = None) -> list[dict]:
    return [v for v in _read() if not provider or v.get("provider") == provider]


def find(provider: str, wanted: str) -> dict | None:
    """A saved voice by id or (case-insensitive) name."""
    if not wanted:
        return None
    w = wanted.strip().lower()
    return next((v for v in listing(provider) if v["id"] == wanted or v.get("name", "").lower() == w), None)


def add(provider: str, voice_id: str, name: str, mode: str, description: str = "", lang: str = "") -> dict:
    items = [v for v in _read() if not (v.get("provider") == provider and v["id"] == voice_id)]
    entry = {"provider": provider, "id": voice_id, "name": " ".join(name.split())[:60] or "My voice", "mode": mode,
             "description": description[:300], "lang": lang, "created": int(time.time())}
    items.append(entry)
    _write(items)
    return entry


def remove(provider: str, voice_id: str) -> None:
    _write([v for v in _read() if not (v.get("provider") == provider and v["id"] == voice_id)])


def _write(items: list[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def rename(provider: str, voice_id: str, name: str) -> bool:
    items = _read()
    for v in items:
        if v.get("provider") == provider and v["id"] == voice_id:
            v["name"] = " ".join(name.split())[:60] or v["name"]
            _write(items)
            return True
    return False
