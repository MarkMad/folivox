"""Compatibility shim: the CLI is English only, so ``_()`` just formats the message.

New code should use plain f-strings. This module stays only until ``folivox/voices`` stops importing it.
"""

from __future__ import annotations


def _(message: str, **kwargs) -> str:
    return message.format(**kwargs) if kwargs else message
