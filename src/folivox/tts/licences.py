"""Fish Audio licences: what the user must accept before an engine is installed or used.

Folivox never ships Fish weights or code. The user downloads them from Hugging Face after accepting the
licence that governs the build. The acceptance is stored in ``config.toml`` (``[consent.<licence id>]``) with
the licence version and the sha256 of the text that was shown; when either changes, the question is asked again.
The full text is fetched on demand from the pinned official file and checked against the catalog hash, so what
the user reads is exactly what the vendor published.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import shutil
import urllib.request
from pathlib import Path

from platformdirs import user_data_dir

from folivox import config
from folivox.tts.builds import Build, Licence, load

# The short version shown next to the full text. (id, text) pairs: the web studio translates by id.
POINTS: dict[str, list[tuple[str, str]]] = {
    "fish-research": [
        ("research_only", "The weights are free for research and personal, non-commercial use only."),
        ("no_selling", "Do NOT sell, rent or monetise audiobooks made with this engine (also not on a "
                       "platform, a subscription or with ads): that needs a separate commercial licence from "
                       "Fish Audio."),
        ("voices", "Clone only your own voice, a synthetic voice, or the voice of someone who agreed. Imitating a "
                   "real person without consent is forbidden."),
        ("no_training", "The output must not be used to train other speech or foundation models."),
        ("attribution", "Say \"Built with Fish Audio\" wherever you show or distribute the result."),
    ],
    "fish-community": [
        ("commercial", "Free for research and personal use. Commercial use (selling your audiobooks) is allowed "
                       "only while your total yearly revenue, with affiliates, stays below USD 500,000; above that "
                       "you need a licence from Fish Audio."),
        ("no_hosting", "You may not offer the engine to others as a service (an API, a website that reads text "
                       "for strangers)."),
        ("voices", "Clone only your own voice, a synthetic voice, or the voice of someone who agreed. Imitating a "
                   "real person without consent ends your licence."),
        ("no_training", "The output must not be used to train other speech or foundation models."),
        ("attribution", "Say \"Built with Fish Audio\" wherever you show or distribute the result."),
    ],
}
ATTRIBUTION = "Built with Fish Audio"
DISCLAIMER = "This is a summary, not legal advice; the full licence text is what binds you."


class LicenceError(RuntimeError):
    pass


class LicenceNotAccepted(LicenceError):
    def __init__(self, licence: Licence):
        self.licence = licence
        super().__init__(f"{licence.name} (version {licence.version}) has not been accepted. Read it and accept it "
                         f"with `folivox engines accept {licence.id}`, or in the studio under Settings → Engines.")


def accepted() -> dict[str, dict]:
    """Acceptance records from ``config.toml``: ``{licence id: {version, sha256, accepted_at}}``."""
    return {k: dict(v) for k, v in config.section("consent").items() if isinstance(v, dict)}


def is_accepted(lic: Licence, records: dict[str, dict] | None = None) -> bool:
    rec = (accepted() if records is None else records).get(lic.id)
    return bool(rec) and rec.get("version") == lic.version and rec.get("sha256") == lic.text_sha256


def require(build: Build) -> None:
    lic = load().licences[build.licence]
    if not is_accepted(lic):
        raise LicenceNotAccepted(lic)


def accept(licence_id: str) -> dict:
    """Record that the user accepted the current version of a licence (only call after showing it)."""
    import tomli_w

    lic = load().licences.get(licence_id)
    if lic is None:
        raise LicenceError(f"Unknown licence {licence_id!r}")
    record = {"version": lic.version, "sha256": lic.text_sha256,
              "accepted_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    path = config.config_path()
    data = dict(config.load())
    consent = dict(data.get("consent", {}))
    consent[lic.id] = record
    data["consent"] = consent
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))  # comments are lost on rewrite
    path.write_text(tomli_w.dumps(data), encoding="utf-8")
    config.load.cache_clear()
    return record


def revoke(licence_id: str) -> None:
    import tomli_w

    path = config.config_path()
    data = dict(config.load())
    consent = dict(data.get("consent", {}))
    if consent.pop(licence_id, None) is None:
        return
    data["consent"] = consent
    path.write_text(tomli_w.dumps(data), encoding="utf-8")
    config.load.cache_clear()


def _cache_file(lic: Licence) -> Path:
    return Path(user_data_dir("folivox", appauthor=False)) / "licences" / f"{lic.id}-{lic.text_sha256[:12]}.txt"


def fetch_text(lic: Licence, opener=urllib.request.urlopen) -> str:
    """The full licence text, from the cache or from the vendor's pinned file; refuses text that does not match
    the hash in the catalog (the vendor changed the licence: Folivox needs a catalog update first)."""
    cache = _cache_file(lic)
    if cache.is_file():
        return cache.read_text(encoding="utf-8")
    req = urllib.request.Request(lic.text_url, headers={"User-Agent": "folivox"})
    try:
        with opener(req, timeout=30) as r:
            raw = r.read()
    except OSError as e:
        raise LicenceError(f"Could not download the licence text ({e}). Read it at {lic.page} and try again") from e
    if hashlib.sha256(raw).hexdigest() != lic.text_sha256:
        raise LicenceError(f"The licence text at {lic.text_url} does not match the version Folivox knows. Read it "
                           f"at {lic.page}; update Folivox before installing")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(raw)
    return raw.decode("utf-8")


def summary(licence_id: str) -> dict:
    lic = load().licences[licence_id]
    return {"id": lic.id, "name": lic.name, "version": lic.version, "commercial": lic.commercial, "page": lic.page,
            "points": [{"id": i, "text": t} for i, t in POINTS[lic.id]], "attribution": ATTRIBUTION,
            "accepted": is_accepted(lic), "disclaimer": DISCLAIMER}


def prompt_accept(licence_id: str, ask=input, show=print, assume_yes: bool = False) -> bool:
    """Console flow: show the points, offer the full text, ask. Returns True when accepted (and recorded)."""
    lic = load().licences[licence_id]
    if is_accepted(lic):
        return True
    show(f"\n{lic.name}, version {lic.version}")
    for _i, text in POINTS[lic.id]:
        show(f"  - {text}")
    show(f"  ({DISCLAIMER})")
    if assume_yes:
        accept(lic.id)
        return True
    while True:
        answer = ask("Type 'read' to see the full text, 'yes' to accept, anything else to decline: ").strip().lower()
        if answer == "read":
            try:
                show(fetch_text(lic))
            except LicenceError as e:
                show(str(e))
            continue
        if answer in ("yes", "y"):
            accept(lic.id)
            return True
        return False
