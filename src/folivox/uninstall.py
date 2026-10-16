"""What `folivox uninstall` removes: only what Folivox itself created, nothing the user had before."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir


@dataclass
class Item:
    label: str
    path: Path
    size: int


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def data_dir() -> Path:
    return Path(user_data_dir("folivox", appauthor=False))


def plan(everything: bool = False) -> list[Item]:
    """Existing things to remove. Level 1: downloaded models. ``everything`` adds voices, settings and state.

    Never included: a model folder the user pointed to (FOLIVOX_MODEL_DIR), a config file from FOLIVOX_CONFIG,
    books, ``BOOK.folivox`` work folders and audiobooks, uv, ffmpeg.
    """
    from folivox import config
    from folivox.tts import weights

    d = data_dir()
    cands: list[tuple[str, Path]] = [("Voice model (CosyVoice 3)", d / "models"),
                                     ("Fish Audio engines (weights and environments)", d / "engines"),
                                     ("Fish Audio licence texts", d / "licences")]
    for repo in weights.owned_repos():
        cands.append((f"Speech recognition model ({repo})", weights._hf_repo_dir(repo)))
    if everything:
        cands += [("Your voices", d / "voices"), ("Cloud voice list", d / "cloud_voices.json"),
                  ("Studio state and token", d / "ui"), ("Studio token", d / "ui_token")]
        if not os.environ.get("FOLIVOX_CONFIG"):
            cands.append(("Settings", config.config_path()))
    items = []
    for label, path in cands:
        try:
            if path.exists():
                items.append(Item(label, path, _size(path)))
        except OSError:
            continue
    return items


def remove(items: list[Item], everything: bool) -> list[str]:
    """Delete ``items``; returns error messages. Tidies the data folder when nothing is left in it."""
    from folivox.tts import weights

    errors = []
    removed_repos = []
    for it in items:
        try:
            shutil.rmtree(it.path) if it.path.is_dir() else it.path.unlink()
        except OSError as e:
            errors.append(f"{it.path}: {e}")
            continue
        for repo in weights.owned_repos():
            if it.path == weights._hf_repo_dir(repo):
                removed_repos.append(repo)
    f = weights._owned_file()
    try:
        if everything and not errors:
            f.unlink(missing_ok=True)
        elif removed_repos and f.exists():
            left = [r for r in weights.owned_repos() if r not in removed_repos]
            f.write_text(json.dumps({"hf_repos": left}), encoding="utf-8")
        d = data_dir()
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
        c = Path(user_config_dir("folivox", appauthor=False))
        if c.is_dir() and not any(c.iterdir()):
            c.rmdir()
    except OSError:
        pass
    return errors
