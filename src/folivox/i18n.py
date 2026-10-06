"""Minimal i18n for CLI messages: English in the code, translations in ``folivox/locales/<lang>.py``.

The UI language is ``$FOLIVOX_UI_LANG``, else the system locale (``LC_ALL`` / ``LC_MESSAGES`` /
``LANG``, the macOS preferred language, the Windows locale); English when there is no catalog.
"""

from __future__ import annotations

import importlib
import locale
import os
import subprocess
import sys
from functools import cache, lru_cache


@lru_cache(maxsize=1)
def ui_lang() -> str:
    for var in ("FOLIVOX_UI_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v and v not in ("C", "POSIX", "C.UTF-8"):
            return v[:2].lower()
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True,
                                 timeout=2).stdout
            first = out.strip("() \n").split(",")[0].strip().strip('"')
            if first:
                return first[:2].lower()
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        loc = locale.getlocale()[0] or ""
    except ValueError:
        loc = ""
    if loc.lower().startswith("russian"):
        return "ru"
    return loc[:2].lower() or "en"


@cache
def catalog(lang: str) -> dict[str, str]:
    if lang == "en":
        return {}
    try:
        return importlib.import_module(f"folivox.locales.{lang}").MESSAGES
    except ImportError:
        return {}


def _(message: str, **kwargs) -> str:
    text = catalog(ui_lang()).get(message, message)
    return text.format(**kwargs) if kwargs else text


def plural(n: int, one: str, many: str) -> str:
    """English-style plural; translations handle their own forms through the catalog."""
    return one if n == 1 else many
