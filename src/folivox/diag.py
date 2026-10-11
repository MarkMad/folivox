"""Diagnostics: a rotating per-user log file and a redacted support bundle (``folivox doctor``).

The log holds versions, platform, engine, options without secrets, timings and tracebacks. It never holds
API keys or book text beyond short snippets. The bundle is a zip the user can attach to a bug report; it is
built locally and never sent anywhere.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from platformdirs import user_log_dir

LOGGER = "folivox"
SNIPPET = 40  # characters of book text allowed in diagnostics
LOG_TAIL_BYTES = 400_000
SECRET_OPTIONS = ("key", "token", "secret", "password")

_PATTERNS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [redacted]"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password|authorization|x-api-key)[\"'\s:=]+)[^\s\"',;}]{6,}"),
     r"\1[redacted]"),
    (re.compile(r"\b(sk|xi|key|pk|gsk|AIza)[-_A-Za-z0-9]{16,}"), "[redacted-key]"),
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "[redacted-hex]"),
]


def log_dir() -> Path:
    return Path(user_log_dir("folivox", appauthor=False))


def log_file() -> Path:
    return log_dir() / "folivox.log"


class _JsonLines(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"t": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
                "level": record.levelname, "msg": record.getMessage()}
        data.update(getattr(record, "fields", {}))
        if record.exc_info:
            data["traceback"] = self.formatException(record.exc_info)
        return redact(json.dumps(data, ensure_ascii=False, default=str))


def setup_logging(path: Path | None = None) -> logging.Logger:
    """Attach the rotating file handler once (1 MB × 5 files). Never raises: logging must not break a render."""
    log = logging.getLogger(LOGGER)
    if any(getattr(h, "_folivox", False) for h in log.handlers) and path is None:
        return log
    log.setLevel(logging.INFO)
    log.propagate = False
    try:
        target = path or log_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(target, maxBytes=1_000_000, backupCount=5, encoding="utf-8",
                                                       delay=True)
        handler.setFormatter(_JsonLines())
        handler._folivox = True  # type: ignore[attr-defined]
        for old in [h for h in log.handlers if getattr(h, "_folivox", False)]:
            log.removeHandler(old)
            old.close()
        log.addHandler(handler)
    except OSError:
        log.addHandler(logging.NullHandler())
    return log


def event(msg: str, level: int = logging.INFO, exc_info=None, **fields) -> None:
    """One structured log line. ``fields`` are redacted on the way out."""
    log = logging.getLogger(LOGGER)
    if not log.handlers:
        setup_logging()
    try:
        log.log(level, msg, exc_info=exc_info, extra={"fields": fields})
    except Exception:  # noqa: BLE001 — never let logging fail the job
        pass


def redact(text: str) -> str:
    """Remove API keys, tokens and the values of key environment variables; shorten the home directory."""
    for name, value in os.environ.items():
        if value and len(value) >= 8 and re.search(r"(?i)key|token|secret|password", name):
            text = text.replace(value, "[redacted]")
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    home = str(Path.home())
    if len(home) > 3:
        text = text.replace(home, "~").replace(home.replace("\\", "\\\\"), "~")
    return text


def options_summary(opts) -> dict:
    """Render options for the log: no secrets, no book text, paths reduced to names."""
    out = {}
    for k, v in vars(opts).items():
        if any(s in k.lower() for s in SECRET_OPTIONS) or k in ("meta", "tts_description", "voice_text"):
            continue
        plain = isinstance(v, (int, float, str, bool, type(None)))
        out[k] = v.name if isinstance(v, Path) else (v if plain else str(v))
    return out


def snippet(text: str, n: int = SNIPPET) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n] + "…"


# ---- the report -------------------------------------------------------------------------------------
PACKAGES = ("folivox", "numpy", "torch", "soundfile", "huggingface_hub", "starlette", "uvicorn", "typer",
            "platformdirs", "onnxruntime", "faster-whisper", "openai-whisper", "transformers")


def _version(name: str) -> str | None:
    from importlib import metadata

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def ffmpeg_info() -> dict:
    from folivox.audio.assemble import FFmpegMissing, ffmpeg

    try:
        exe = ffmpeg()
    except FFmpegMissing as e:
        return {"found": False, "error": str(e)}
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=10).stdout.splitlines()
    except (OSError, subprocess.SubprocessError) as e:
        return {"found": True, "path": exe, "error": str(e)}
    return {"found": True, "path": exe, "version": out[0] if out else ""}


def devices() -> dict:
    try:
        import torch
    except ImportError:
        return {"torch": None}
    return {"cuda": bool(torch.cuda.is_available()), "mps": bool(getattr(torch.backends, "mps", None)
                                                                   and torch.backends.mps.is_available())}


def ram_gb() -> float | None:
    """Physical memory in GB on macOS, Linux and Windows without extra packages."""
    try:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
        import ctypes

        class Mem(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                        ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("ve", ctypes.c_ulonglong)]

        m = Mem()
        m.length = ctypes.sizeof(Mem)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore[attr-defined]
        return m.total / 1e9
    except Exception:  # noqa: BLE001
        return None


def hardware() -> dict:
    """What the machine offers: CPU cores, RAM, GPU (name, memory) and the device Folivox would use."""
    info: dict = {"cpu": platform.processor() or platform.machine(), "cores": os.cpu_count(),
                  "ram_gb": round(ram_gb(), 1) if ram_gb() else None, "gpu": None, "vram_gb": None}
    try:
        import torch

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            info.update(gpu=props.name, vram_gb=round(props.total_memory / 1e9, 1), device="cuda")
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            info.update(gpu="Apple GPU (shared memory)", device="mps")
        else:
            info["device"] = "cpu"
    except ImportError:
        info["device"] = None
    info["advice"] = advice(info)
    return info


def advice(hw: dict) -> list[str]:
    """Plain-language recommendations derived from :func:`hardware`."""
    tips = []
    ram, device = hw.get("ram_gb"), hw.get("device")
    if device is None:
        tips.append("PyTorch is not installed: local voices need `pip install \"folivox[tts]\"` "
                    "(or use an online engine).")
    if ram is not None and ram < 8:
        tips.append(f"Only {ram:.0f} GB of RAM: the local model (about 6 GB) may not fit; use an online engine or "
                    "close other programs. Use `--no-qa` to spare memory.")
    elif ram is not None and ram < 16:
        tips.append("8-16 GB of RAM is enough for the local model, but close heavy programs during a render.")
    if device == "cpu":
        tips.append("No GPU is used: synthesis will be several times slower than real time. A long book takes "
                    "days on a CPU; consider an online engine for it.")
    if device == "cuda" and (hw.get("vram_gb") or 99) < 6:
        tips.append(f"The GPU has {hw['vram_gb']} GB of memory: if loading fails Folivox falls back to the CPU.")
    if hw.get("cores") and hw["cores"] <= 4 and device == "cpu":
        tips.append("Few CPU cores: the speech-recognition check slows a render noticeably; `--no-qa` skips it.")
    return tips


def journal_summary(work_dir: Path) -> dict | None:
    """Counts only: how far a render got. Chapter titles are cut to a snippet, fragment text is never included."""
    db = Path(work_dir) / "journal.sqlite"
    if not db.exists():
        return None
    import sqlite3

    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            done = con.execute("SELECT COUNT(*) FROM chunks WHERE key IN (SELECT key FROM takes)").fetchone()[0]
            chapters = [snippet(t, 30) for (t,) in con.execute("SELECT title FROM chapters ORDER BY idx LIMIT 200")]
            meta = {k: v for k, v in con.execute("SELECT key, value FROM meta")
                    if not k.startswith("chapter_") and k != "book_title"}
            flagged = con.execute("SELECT COUNT(*) FROM takes WHERE score > 0.08").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as e:
        return {"error": f"journal unreadable: {e}"}
    audio_dir = Path(work_dir) / "audio"
    files = sum(1 for _ in audio_dir.glob("*.flac")) if audio_dir.is_dir() else 0
    return {"fragments": chunks, "fragments_done": done, "chapters": len(chapters), "chapter_titles": chapters,
            "audio_files": files, "flagged_takes": flagged, "meta": meta}


def report(work_dir: Path | None = None) -> dict:
    from folivox import config

    selected = {}
    try:
        for kind in ("tts", "asr", "generator", "llm"):
            selected[kind] = config.provider(kind)
    except Exception:  # noqa: BLE001
        pass
    data = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
                     "python": sys.version.split()[0], "implementation": platform.python_implementation(),
                     "filesystem_encoding": sys.getfilesystemencoding(), "stdout_encoding": getattr(sys.stdout,
                                                                                                    "encoding", None)},
        "packages": {n: v for n in PACKAGES if (v := _version(n))},
        "ffmpeg": ffmpeg_info(),
        "devices": devices(),
        "hardware": hardware(),
        "selected_providers": selected,
        "config_file": str(config.config_path()),
        "disk_free_mb": _free_mb(work_dir or Path.home()),
        "log_file": str(log_file()),
    }
    from folivox.tts import weights

    data["model_dir"] = {"path": str(weights.default_model_dir()), "complete": weights.is_complete(
        weights.default_model_dir())}
    if work_dir is not None:
        data["journal"] = journal_summary(work_dir)
    return json.loads(redact(json.dumps(data, ensure_ascii=False, default=str)))


def _free_mb(path: Path) -> int | None:
    try:
        probe = path if path.exists() else path.parent
        return shutil.disk_usage(probe).free // 1_000_000
    except OSError:
        return None


def log_tail(limit: int = LOG_TAIL_BYTES) -> str:
    f = log_file()
    try:
        with open(f, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - limit))
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return redact(raw.split("\n", 1)[-1] if len(raw) >= limit else raw)


def support_bundle(dest: Path, work_dir: Path | None = None) -> Path:
    """Write the redacted zip: report.json, the log tail and a README that says what is (not) inside."""
    dest = Path(dest).expanduser()
    if dest.is_dir():
        dest = dest / time.strftime("folivox-support-%Y%m%d-%H%M%S.zip")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("report.json", json.dumps(report(work_dir), ensure_ascii=False, indent=2))
            z.writestr("folivox.log", log_tail())
            z.writestr("README.txt", README)
        os.replace(part, dest)
    finally:
        part.unlink(missing_ok=True)
    return dest


README = """Folivox support bundle
======================
Made locally by `folivox doctor --bundle`; nothing was sent anywhere. Send it to whoever helps you.

Inside: report.json (versions, platform, ffmpeg, selected engines, progress counters of the render) and
folivox.log (the last part of the log: events, timings, errors).

Left out on purpose: API keys and tokens (also cut from the log), the book text (at most a 40-character
snippet appears in messages), audio, and your voice recordings. Home folder paths are shown as ~.
Look through the files before you share them.
"""


def render_report_text(data: dict) -> str:
    """Human-readable form of :func:`report` for the terminal."""
    lines = []
    p = data["platform"]
    lines.append(f"System:   {p['system']} {p['release']} ({p['machine']}), Python {p['python']}")
    lines.append("Packages: " + ", ".join(f"{k} {v}" for k, v in data["packages"].items()))
    ff = data["ffmpeg"]
    lines.append("ffmpeg:   " + (ff.get("version") or ff.get("path") or "NOT FOUND — " + ff.get("error", "")))
    hw = data["hardware"]
    lines.append(f"Hardware: {hw['cores']} cores, {hw['ram_gb']} GB RAM, GPU: {hw['gpu'] or 'none'}"
                 f"{' ' + str(hw['vram_gb']) + ' GB' if hw['vram_gb'] else ''} → device {hw['device']}")
    lines += [f"  ! {t}" for t in hw["advice"]]
    lines.append(f"Engines:  {data['selected_providers']}")
    m = data["model_dir"]
    lines.append(f"Model:    {m['path']} ({'complete' if m['complete'] else 'not downloaded or incomplete'})")
    lines.append(f"Disk:     {data['disk_free_mb']} MB free")
    lines.append(f"Log:      {data['log_file']}")
    if data.get("journal"):
        j = data["journal"]
        lines.append(f"Journal:  {j.get('fragments_done')}/{j.get('fragments')} fragments done" if "fragments" in j
                     else f"Journal:  {j}")
    return "\n".join(lines)
