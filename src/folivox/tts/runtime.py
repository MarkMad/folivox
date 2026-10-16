"""Which inference runtime reads the book: PyTorch (default) or the native C++ one (audio.cpp).

One general switch (``--runtime``, ``FOLIVOX_RUNTIME``, ``[runtime] inference`` in config.toml, the studio's Advanced
settings). Only engines that have a native implementation (CosyVoice 3) are affected; the others ignore it.
``auto`` picks native only on platforms where the Folivox catalog records it as checked (``auto_ok``) and only when it
is installed; everything else stays on PyTorch. Light module: no torch import.
"""

from __future__ import annotations

from folivox import config

NATIVE_ENGINES = ("cosyvoice3",)


def resolve(engine: str, requested: str | None = None) -> str:
    """``"native"`` or ``"pytorch"`` for ``engine`` given the requested mode (CLI value or None → config)."""
    mode = config.runtime(requested)
    if engine not in NATIVE_ENGINES or mode == "pytorch":
        return "pytorch"
    if mode == "native":
        return "native"
    from folivox.tts import native_setup

    return "native" if native_setup.status(config.native_options()["weights"]).auto else "pytorch"


def supports_native(engine: str) -> bool:
    return engine in NATIVE_ENGINES


def require_ready() -> None:
    """Raise a clear error when the native runtime was asked for but is not installed."""
    from folivox.providers import ProviderError
    from folivox.tts import native_setup

    st = native_setup.status(config.native_options()["weights"])
    if st.server is None or st.problem and "downloaded" in st.problem:
        raise ProviderError(f"The native runtime was requested but {st.problem}. Install it with "
                            "`folivox runtime install`, or use `--runtime pytorch`.")


def take_settings(speed: float) -> str:
    """Identity of takes made natively: the engine release, the weights file and the precision."""
    from folivox.tts import native, native_setup

    opts = config.native_options()
    return (f"cv3-native-1|{native_setup.load().release}|{native.settings_tag(opts['weights'], opts['weight_type'])}"
            f"|speed={speed}")
