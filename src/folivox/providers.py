"""Pluggable backends.

Every stage that depends on a model (speech synthesis, ASR for QA, reference-voice generation,
text LLM) goes through a :class:`Registry`. Implementations register a *factory* under a short
name; the factory is imported lazily so optional heavy dependencies are only needed when used.

Third-party packages can add providers through the ``folivox.providers`` entry-point group::

    [project.entry-points."folivox.providers"]
    my-tts = "my_pkg.folivox_plugin:register"   # register() calls folivox.tts.ENGINES.register(...)
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class ProviderError(RuntimeError):
    """A provider is unknown, not installed or misconfigured."""


@dataclass
class Provider:
    name: str
    target: str  # "module:attr" of the factory, imported on first use
    description: str = ""
    local: bool = True  # False → sends data to a remote API (needs the user's own key)
    needs: str = ""  # install hint / required env var


class Registry(Generic[T]):
    def __init__(self, kind: str, default: str):
        self.kind, self.default = kind, default
        self._items: dict[str, Provider] = {}

    def register(self, name: str, target: str | Callable[..., T], description: str = "", *, local: bool = True,
                 needs: str = "") -> None:
        if callable(target):
            fn = target
            target = f"{fn.__module__}:{fn.__qualname__}"
        self._items[name] = Provider(name, target, description, local, needs)

    def names(self) -> list[str]:
        _load_plugins()
        return list(self._items)

    def providers(self) -> list[Provider]:
        _load_plugins()
        return list(self._items.values())

    def get(self, name: str | None) -> Provider:
        _load_plugins()
        name = name or self.default
        if name not in self._items:
            raise ProviderError(f"Unknown {self.kind} provider {name!r}; available: {', '.join(self._items)}")
        return self._items[name]

    def create(self, name: str | None = None, **kwargs: Any) -> T:
        """Instantiate a provider. ``kwargs`` come from the CLI and the ``[<kind>.<name>]`` config section."""
        from folivox.config import section

        p = self.get(name)
        module, _, attr = p.target.partition(":")
        factory = importlib.import_module(module)
        for part in attr.split("."):
            factory = getattr(factory, part)
        options = {**section(f"{self.kind}.{p.name}"), **{k: v for k, v in kwargs.items() if v is not None}}
        return factory(**options)


_plugins_loaded = False


def _load_plugins() -> None:
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    from importlib.metadata import entry_points

    for ep in entry_points(group="folivox.providers"):
        try:
            ep.load()()
        except Exception as e:  # noqa: BLE001 — a broken plugin must not break the CLI
            import warnings

            warnings.warn(f"folivox plugin {ep.name!r} failed to load: {e}", stacklevel=2)
