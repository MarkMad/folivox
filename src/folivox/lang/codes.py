"""ISO 639-1 codes a fragment of a book may be marked with (a model's answer is checked against this list)."""

from __future__ import annotations

ALLOWED = frozenset(
    "ru en de fr es it zh ja ko uk be pl cs sk bg sr hr sl pt nl sv da no fi tr el he ar hi la hu ro lt lv et "
    "id vi th fa ka hy".split())


def valid(code: object) -> str:
    """The normalised code if it is on the allow-list, else ``""``."""
    from folivox.lang import normalize_code

    c = normalize_code(code if isinstance(code, str) else "")
    return c if c in ALLOWED else ""
