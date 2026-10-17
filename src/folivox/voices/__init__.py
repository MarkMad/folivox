"""Voice catalog: voices bundled with Folivox plus the user's own voices.

Bundled voices live in this package (``<id>.flac`` + entry in ``catalog.json``) and must be
redistributable (public domain / CC0 / permissive). User voices live in the user data dir,
``voices/<id>/`` with ``voice.flac``, ``voice.txt`` and ``meta.json``; they never leave the machine.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from platformdirs import user_data_dir

from folivox.i18n import _

PACKAGE_DIR = Path(__file__).parent
DEFAULT_VOICE = "russlib"
TARGET_SR = 24000


@dataclass
class VoiceEntry:
    id: str
    name: str
    gender: str  # "f" | "m"
    lang: str  # ISO 639-1 of the sample; zero-shot cloning works best in the same language
    transcript: str
    source: str = ""
    license: str = ""
    url: str = ""
    bundled: bool = False
    commercial: bool = False  # generated with a commercial cloud API: personal use only, never bundled
    path: Path = field(default=Path(), compare=False)

    def to_meta(self) -> dict:
        d = asdict(self)
        d.pop("path")
        d.pop("bundled")
        return d


def user_voices_dir() -> Path:
    return Path(user_data_dir("folivox", appauthor=False)) / "voices"


def bundled() -> list[VoiceEntry]:
    data = json.loads((PACKAGE_DIR / "catalog.json").read_text(encoding="utf-8"))
    return [VoiceEntry(**v, bundled=True, path=PACKAGE_DIR / f"{v['id']}.flac") for v in data]


def user() -> list[VoiceEntry]:
    out = []
    root = user_voices_dir()
    if root.exists():
        for d in sorted(root.iterdir()):
            meta = d / "meta.json"
            if meta.exists():
                try:
                    v = json.loads(meta.read_text(encoding="utf-8"))
                    v.pop("bundled", None)
                    v.pop("path", None)
                    out.append(VoiceEntry(**v, path=d / "voice.flac"))
                except (OSError, ValueError, TypeError, AttributeError):
                    continue  # one broken or foreign meta.json must not hide every voice
    return out


def all_voices() -> list[VoiceEntry]:
    mine = user()
    ids = {v.id for v in mine}
    return mine + [v for v in bundled() if v.id not in ids]  # a user voice may override a bundled one


def find(voice_id: str) -> VoiceEntry | None:
    return next((v for v in all_voices() if v.id == voice_id), None)


def default_for(lang: str, gender: str | None = None) -> VoiceEntry:
    """Default voice for a book language: the bundled default if it matches, else the first voice
    in that language (bundled before user voices), else the global default (cross-lingual cloning
    works, but the accent of the sample carries over)."""
    candidates = [v for v in bundled() + user() if v.lang == lang and (not gender or v.gender == gender)]
    preferred = [v for v in candidates if v.id == DEFAULT_VOICE]
    if preferred or candidates:
        return (preferred or candidates)[0]
    return find(DEFAULT_VOICE)


_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


def add(voice_id: str, audio: Path, transcript: str, *, name: str = "", gender: str = "", lang: str = "ru",
        source: str = "", license: str = "", url: str = "", overwrite: bool = False,
        commercial: bool = False) -> VoiceEntry:
    """Normalise a sample (mono, 24 kHz, trimmed silence) and store it as a user voice."""
    import numpy as np
    import soundfile as sf

    from folivox.audio import trim_silence

    if not _ID.match(voice_id):
        raise ValueError(_("Voice id: lowercase latin letters, digits, '-' and '_', up to 40 characters"))
    target = user_voices_dir() / voice_id
    if target.exists() and not overwrite:
        raise FileExistsError(_("Voice {id!r} already exists (use --force)", id=voice_id))
    data, sr = sf.read(str(audio), dtype="float32", always_2d=True)
    data = data.mean(axis=1)
    if sr != TARGET_SR:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(sr, TARGET_SR)
        data = resample_poly(data, TARGET_SR // g, sr // g).astype(np.float32)
    data = trim_silence(data, TARGET_SR, threshold_db=-50, margin=0.1)
    peak = float(np.abs(data).max()) if data.size else 0
    if peak > 0:
        data = data * (0.9 / peak)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    sf.write(str(target / "voice.flac"), data, TARGET_SR, subtype="PCM_16")
    entry = VoiceEntry(voice_id, name or voice_id, gender, lang, " ".join(transcript.split()), source, license,
                       url, commercial=commercial, path=target / "voice.flac")
    (target / "voice.txt").write_text(entry.transcript, encoding="utf-8")
    (target / "meta.json").write_text(json.dumps(entry.to_meta(), ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


def remove(voice_id: str) -> None:
    target = user_voices_dir() / voice_id
    if not target.exists():
        raise FileNotFoundError(_("No user voice {id!r}", id=voice_id))
    shutil.rmtree(target)
