"""Checks before a render with a Fish engine: licence, installed build, voice policy, free memory."""

from __future__ import annotations

from pathlib import Path

from folivox import config
from folivox.providers import ProviderError
from folivox.tts import builds, fish_setup, licences

BUNDLED_VOICES_NOTE = (
    "The voices bundled with Folivox are recordings of real LibriVox readers. The Fish licences forbid generating "
    "speech that imitates an identifiable person without their consent, so these voices are not offered to Fish "
    "engines. Use your own recording, a voice you generated (`folivox voices design`), or a voice of someone who "
    "agreed. To allow the bundled ones anyway on your own responsibility, set allow_bundled_voices = true in the "
    "[fish] section of config.toml.")


def is_bundled_voice(path: Path | None) -> bool:
    from folivox.voices import PACKAGE_DIR

    return path is not None and Path(path).expanduser().resolve().parent == PACKAGE_DIR.resolve()


def bundled_voices_allowed() -> bool:
    return bool(config.section("fish").get("allow_bundled_voices", False))


def check(opts, events) -> builds.Build:
    """Raise a clear error when the engine cannot be used; report warnings through ``events``."""
    try:
        from folivox.tts import runtime

        build = builds.build_for(opts.tts, opts.tts_build, runtime=runtime.resolve(opts.tts, opts.runtime or None))
    except builds.CatalogError as e:
        raise ProviderError(str(e)) from None
    licences.require(build)
    if not fish_setup.is_ready(build):
        raise FileNotFoundError(f"{build.title} is not installed. It downloads {build.size_gb:.1f} GB from "
                                f"Hugging Face: run  folivox engines install {build.id}  (or use the studio, "
                                "Settings → Engines)")
    if is_bundled_voice(opts.voice_wav) and not bundled_voices_allowed():
        raise ProviderError(BUNDLED_VOICES_NOTE)
    hw = builds.detect_hardware()
    why = builds.memory_gate(build, hw)
    if why:
        raise ProviderError(why)
    f = builds.fit(build, hw)
    if f.level == "no":
        raise ProviderError(f.message)
    if f.level == "tight":
        events.warning(f.message)
    if build.status != "verified":
        events.warning(f"{build.title} has not been tested by the Folivox project yet; the result may be poor.")
    note = builds.speed_note(build)
    if note and hw.platform_tag == "darwin-arm64":
        events.warning(note)
    lic = builds.load().licences[build.licence]
    if not lic.commercial:
        events.warning(f"{lic.name}: audiobooks made with {build.title} are for personal and research use only. "
                       "Selling them or earning money with them is not allowed.")
    events.warning(f"{licences.ATTRIBUTION}: say so wherever you share the result.")
    if opts.speed != 1.0:
        events.warning("Reading speed is not applied by Fish engines; their own pace is used")
    return build
