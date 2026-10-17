"""Install, check and remove the optional native runtime: audio.cpp (Apache-2.0, C++/GGML) and its GGUF weights.

The runtime is a pinned release of https://github.com/0xShug0/audio.cpp: a prebuilt ``audiocpp_server`` for the
computer's platform and backend (Metal, CUDA, Vulkan) plus the CosyVoice 3 GGUF weights from Hugging Face.
Everything is listed in ``native_catalog.json`` with sizes and sha256, nothing is downloaded without the caller
asking first (see :func:`plan`), and archives are unpacked only into Folivox's own data folder.

Expert override: ``FOLIVOX_NATIVE_SERVER`` (path of your own ``audiocpp_server`` build) and
``FOLIVOX_NATIVE_MODEL`` (path of a cosyvoice3 GGUF) are used instead of the installed files.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from platformdirs import user_data_dir

CATALOG_FILE = Path(__file__).with_name("native_catalog.json")
READY = "ready.json"
SERVER_ENV, MODEL_ENV, DIR_ENV = "FOLIVOX_NATIVE_SERVER", "FOLIVOX_NATIVE_MODEL", "FOLIVOX_NATIVE_DIR"
SERVER_NAME = "audiocpp_server.exe" if os.name == "nt" else "audiocpp_server"
SKIP_TOP = {"src", "tools", "docs", "Notebooks", "examples"}  # source and helper scripts inside release archives
WEIGHT_CHOICES = ("q8_0", "f32")
Progress = Callable[[str, int, int], None]


class NativeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Binary:
    id: str
    platform: str
    backend: str
    status: str  # verified | untested
    note: str
    assets: tuple[Asset, ...]

    @property
    def size(self) -> int:
        return sum(a.size for a in self.assets)


@dataclass(frozen=True)
class WeightFile:
    key: str
    repo: str
    revision: str
    path: str
    size: int
    sha256: str


@dataclass
class Catalog:
    release: str
    download_base: str
    auto_ok: list[str]
    binaries: list[Binary]
    weights: dict[str, WeightFile] = field(default_factory=dict)  # by key (q8_0, f32)
    licence: dict = field(default_factory=dict)
    measurements: list[dict] = field(default_factory=list)  # our own runs, see runtime.advice
    sources: dict = field(default_factory=dict)  # where everything comes from and how to build it
    recheck: dict = field(default_factory=dict)

@lru_cache(maxsize=1)
def load() -> Catalog:
    raw = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    bins = [Binary(b["id"], b["platform"], b["backend"], b["status"], b.get("note", ""),
                   tuple(Asset(**a) for a in b["assets"])) for b in raw["binaries"]]
    w = raw["weights"]["cosyvoice3"]
    files = {k: WeightFile(k, w["repo"], w["revision"], f["path"], f["size"], f["sha256"])
             for k, f in w["files"].items()}
    return Catalog(raw["release"], raw["download_base"], raw.get("auto_ok", []), bins, files, raw.get("licence", {}),
                   raw.get("measurements", []), raw.get("sources", {}), raw.get("recheck", {}))


def sources() -> dict:
    return load().sources


def own_server_for(family: str | None) -> Path | None:
    """A server you built yourself or that Folivox built from a pinned fork, for the families a release lacks."""
    if family != "fish_drama3":
        return None
    env = os.environ.get(SERVER_ENV)
    if env and Path(env).expanduser().is_file():
        return Path(env).expanduser()
    from folivox.tts import native_build

    return native_build.own_server("drama3")


# ---- where things live ---------------------------------------------------------------------------------

def root() -> Path:
    env = os.environ.get(DIR_ENV)
    return Path(env).expanduser() if env else Path(user_data_dir("folivox", appauthor=False)) / "native"


def bin_dir(b: Binary) -> Path:
    return root() / "bin" / f"{load().release}-{b.id}"


def weights_dir() -> Path:
    return root() / "models"


def weights_path(key: str) -> Path:
    return weights_dir() / load().weights[key].path


def log_file() -> Path:
    return root() / "logs" / "audiocpp_server.log"


def platform_tag() -> str:
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64" if machine in ("amd64", "x86_64") else machine
    return f"{sys.platform}-{arch}"


# ---- which build fits this computer ----------------------------------------------------------------------

def nvidia_info() -> tuple[int, float] | None:
    """(driver major version, compute capability) of the first NVIDIA GPU, or None."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=driver_version,compute_cap", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=15)  # noqa: S603, S607
        if r.returncode != 0 or not r.stdout.strip():
            return None
        driver, _, cap = r.stdout.splitlines()[0].partition(",")
        return int(driver.strip().split(".")[0]), float(cap.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def candidates(tag: str | None = None) -> list[Binary]:
    tag = tag or platform_tag()
    return [b for b in load().binaries if b.platform == tag]


def pick_binary(backend: str = "auto", tag: str | None = None, nvidia=nvidia_info) -> Binary | None:
    """The build for this computer: Metal on Apple Silicon, CUDA on a modern NVIDIA GPU, else Vulkan."""
    cands = candidates(tag)
    if backend not in ("", "auto"):
        named = [b for b in cands if backend in (b.id, b.backend)]
        return named[0] if named else None
    if not cands:
        return None
    by_backend = {b.backend: [] for b in cands}
    for b in cands:
        by_backend[b.backend].append(b)
    if "metal" in by_backend:
        return by_backend["metal"][0]
    gpu = nvidia() if "cuda" in by_backend else None
    if gpu and gpu[1] >= 7.5:
        new = [b for b in by_backend["cuda"] if "13" in b.id]
        old = [b for b in by_backend["cuda"] if "12" in b.id]
        return (new if gpu[0] >= 580 else old or new)[0]
    return by_backend["vulkan"][0] if "vulkan" in by_backend else None


# ---- state ----------------------------------------------------------------------------------------------

def find_server(directory: Path) -> Path | None:
    for p in sorted(directory.rglob(SERVER_NAME)):
        if p.is_file():
            return p
    return None


def installed_binary(backend: str = "auto") -> tuple[Binary, Path] | None:
    """The installed build (it must have been verified at install time) and its server executable."""
    cands = [pick_binary(backend)] if backend not in ("", "auto") else candidates()
    for b in cands:
        if b is None:
            continue
        d = bin_dir(b)
        try:
            if json.loads((d / READY).read_text(encoding="utf-8")).get("release") != load().release:
                continue
        except (OSError, ValueError):
            continue
        if (srv := find_server(d)) is not None:
            return b, srv
    return None


def server_path(backend: str = "auto") -> Path | None:
    env = os.environ.get(SERVER_ENV)
    if env:
        p = Path(env).expanduser()
        return p if p.is_file() else None
    found = installed_binary(backend)
    return found[1] if found else None


def server_backend(backend: str = "auto") -> str:
    """Backend name passed to the server (metal, cuda, vulkan, cpu)."""
    if backend not in ("", "auto"):
        return {"cuda12.4": "cuda", "cuda13.3": "cuda"}.get(backend, backend)
    found = installed_binary()
    if found:
        return found[0].backend
    return "metal" if platform_tag() == "darwin-arm64" else "cpu"


def model_path(key: str = "q8_0") -> Path | None:
    env = os.environ.get(MODEL_ENV)
    if env:
        p = Path(env).expanduser()
        return p if p.is_file() else None
    p = weights_path(key)
    try:
        return p if p.is_file() and p.stat().st_size == load().weights[key].size else None
    except OSError:
        return None


def _older_release_installed() -> bool:
    try:
        return any((d / READY).is_file() for d in (root() / "bin").iterdir() if d.is_dir())
    except OSError:
        return False


@dataclass
class Status:
    platform: str
    binary: Binary | None  # the build that fits this computer (None = no prebuilt build for it)
    server: Path | None
    weights: dict[str, bool]
    auto: bool  # `--runtime auto` would use it
    problem: str = ""

    @property
    def ready(self) -> bool:
        return self.server is not None and any(self.weights.values())


def status(weights_key: str | None = None) -> Status:
    cat = load()
    tag = platform_tag()
    b = pick_binary(tag=tag)
    srv = server_path()
    have = {k: model_path(k) is not None for k in cat.weights}
    problem = ""
    if srv is None and os.environ.get(SERVER_ENV) is None and _older_release_installed():
        problem = "an older native engine release is installed: run `folivox runtime install` to update it"
    elif srv is None:
        problem = "the native engine is not installed" if (b or os.environ.get(SERVER_ENV)) else \
            f"there is no prebuilt native engine for {tag}"
    elif not any(have.values()):
        problem = "the native model is not downloaded"
    elif weights_key and not have.get(weights_key):
        problem = f"the {weights_key} model file is not downloaded"
    ok = srv is not None and (have.get(weights_key) if weights_key else any(have.values()))
    return Status(tag, b, srv, have, bool(ok and tag in cat.auto_ok), problem)


# ---- download and verify ----------------------------------------------------------------------------------

def sha256_file(path: Path, hook: Callable[[int], None] | None = None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(8 << 20):
            h.update(chunk)
            if hook:
                hook(len(chunk))
    return h.hexdigest()


@dataclass
class Plan:
    binary: Binary | None  # None = keep the installed engine, download only the model
    weights: WeightFile | None
    todo_bytes: int
    lines: list[str]


def plan(weights: str | None = "q8_0", backend: str = "auto") -> Plan:
    """What an install would download now (items already installed are left out). Asks nothing, downloads nothing.
    ``weights=None`` plans the engine only (the Fish models bring their own GGUF files)."""
    if weights is not None and weights not in WEIGHT_CHOICES:
        raise NativeError(f"weights must be one of {', '.join(WEIGHT_CHOICES)}")
    lines, total = [], 0
    b = None
    if os.environ.get(SERVER_ENV):
        pass  # the user brought their own build
    else:
        want = pick_binary(backend)
        if want is None:
            raise NativeError(f"There is no prebuilt native engine for {platform_tag()}"
                              f"{f' with the {backend} backend' if backend != 'auto' else ''}. "
                              f"{PYTORCH_HINT}")
        if installed_binary(backend) is None:
            b = want
            total += b.size
            lines.append(f"engine audio.cpp {load().release} ({b.backend}): {b.size / 1e6:.0f} MB from GitHub")
    w = None
    if weights is not None and model_path(weights) is None:
        w = load().weights[weights]
        total += w.size
        lines.append(f"CosyVoice 3 model ({weights}): {w.size / 1e9:.1f} GB from huggingface.co/{w.repo}")
    return Plan(b, w, total, lines)


PYTORCH_HINT = "The default PyTorch runtime keeps working (`--runtime pytorch`)."


def _download(url: str, dest: Path, a: Asset, progress: Progress | None, attempts: int = 3) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    err: Exception | None = None
    for attempt in range(attempts):
        part = dest.with_name(dest.name + ".part")
        h = hashlib.sha256()
        try:
            with urllib.request.urlopen(url, timeout=60) as r, part.open("wb") as out:  # noqa: S310 (pinned https URL)
                done = 0
                while chunk := r.read(1 << 20):
                    out.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(a.name, done, a.size)
            if h.hexdigest() != a.sha256:
                part.unlink(missing_ok=True)
                raise NativeError(f"{a.name} does not match the checksum pinned in Folivox and was deleted. "
                                  "Run the install again; if it keeps failing, the release changed.")
            part.replace(dest)
            return
        except NativeError:
            raise
        except OSError as e:
            err = e
            time.sleep(min(2 ** attempt * 3, 20))
    raise NativeError(f"Downloading {a.name} failed: {err}. Check the network and run again.") from err


def _inside(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _skip(name: str) -> bool:
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    return bool(parts) and parts[0] in SKIP_TOP


def safe_extract(archive: Path, dest: Path) -> None:
    """Unpack a release archive into ``dest``, refusing paths and links that escape it."""
    dest.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if _skip(info.filename):
                    continue
                if not _inside(dest, dest / info.filename):
                    raise NativeError(f"{archive.name} contains an unsafe path ({info.filename}); nothing was unpacked")
                z.extract(info, dest)
        return
    with tarfile.open(archive) as t:
        for m in t.getmembers():
            if _skip(m.name):
                continue
            if not _inside(dest, dest / m.name) or m.isdev() or m.isfifo():
                raise NativeError(f"{archive.name} contains an unsafe entry ({m.name}); nothing was unpacked")
            if (m.issym() or m.islnk()) and not _inside(dest, (dest / m.name).parent / m.linkname):
                raise NativeError(f"{archive.name} contains a link that leaves its folder ({m.name})")
            t.extract(m, dest, **({"filter": "tar"} if sys.version_info >= (3, 12) else {}))


def install(p: Plan, progress: Progress | None = None, log: Callable[[str], None] = print,
            fetch: Callable[[str, Path, Asset, Progress | None], None] | None = None) -> None:
    """Download and verify what ``p`` lists. Safe to run again: finished parts are kept."""
    fetch = fetch or _download
    if p.binary is not None:
        b = p.binary
        d = bin_dir(b)
        tmp = root() / "downloads" / b.id
        if d.exists():
            shutil.rmtree(d)
        for a in b.assets:
            log(f"Downloading {a.name} ({a.size / 1e6:.0f} MB)…")
            archive = tmp / a.name
            fetch(load().download_base + a.name, archive, a, progress)
            safe_extract(archive, d)
        srv = find_server(d)
        if srv is None:
            shutil.rmtree(d, ignore_errors=True)
            raise NativeError(f"{SERVER_NAME} was not found in the downloaded engine; nothing was installed")
        if os.name != "nt":
            for f in d.rglob("*"):
                if f.is_file() and (f.name.startswith("audiocpp_") or f.suffix in (".so", ".dylib")):
                    f.chmod(f.stat().st_mode | 0o111)
        ver = version_text(srv)
        if b.backend not in ver:
            shutil.rmtree(d, ignore_errors=True)
            raise NativeError(f"The downloaded engine does not report the {b.backend} backend ({ver.strip()[:200]}). "
                              "Your system may lack the needed GPU driver; nothing was installed.")
        (d / READY).write_text(json.dumps({"release": load().release, "installed": time.time()}), encoding="utf-8")
        shutil.rmtree(tmp, ignore_errors=True)
        log(f"Native engine ready: {ver.splitlines()[0] if ver else srv}")
    if p.weights is not None:
        install_weights(p.weights, progress, log)


def version_text(server: Path) -> str:
    try:
        r = subprocess.run([str(server), "--version"], capture_output=True, text=True, timeout=60,  # noqa: S603
                           cwd=str(server.parent))
        return (r.stdout + r.stderr)
    except (OSError, subprocess.SubprocessError) as e:
        return f"cannot run: {e}"


def install_weights(w: WeightFile, progress: Progress | None, log: Callable[[str], None]) -> None:
    from folivox.tts import weights

    d = weights_dir()
    d.mkdir(parents=True, exist_ok=True)
    from huggingface_hub import snapshot_download

    log(f"Downloading the CosyVoice 3 model ({w.size / 1e9:.1f} GB) from huggingface.co/{w.repo} "
        f"at revision {w.revision[:8]}…")
    with weights.reporting(progress), weights._watch_measured(
            w.path, lambda: weights._downloaded(d, [w.path]), w.size):
        weights.with_retries(lambda: snapshot_download(w.repo, revision=w.revision, local_dir=str(d),
                                                       allow_patterns=[w.path]), w.path)
    f = d / w.path
    log("Checking the checksum…")
    if f.stat().st_size != w.size or sha256_file(f) != w.sha256:
        f.unlink(missing_ok=True)
        raise NativeError(f"{w.path} does not match the checksum pinned in Folivox and was removed. "
                          "Run the install again; if it keeps failing, the repository changed.")
    log("Model ready.")


def remove(engine: bool = True, models: bool = True) -> int:
    """Delete the installed engine and/or model files. Returns bytes freed. Files the user brought are untouched."""
    freed = 0
    for sub in (["bin", "downloads", "own", "build"] if engine else []) + (["models"] if models else []):
        d = root() / sub
        if d.exists():
            freed += sum(f.stat().st_size for f in d.rglob("*") if f.is_file() and not f.is_symlink())
            shutil.rmtree(d, ignore_errors=True)
    if engine and models:
        shutil.rmtree(root() / "refs", ignore_errors=True)
    return freed


def disk_problem(need: int, where: Path | None = None) -> str | None:
    where = where or root()
    probe = where
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if free < need * 1.15:
        return f"Not enough disk space: {need / 1e9:.1f} GB needed, {free / 1e9:.1f} GB free on {probe}"
    return None


def ensure_engine(backend: str = "auto", progress: Progress | None = None,
                  log: Callable[[str], None] = print) -> Path:
    """The ``audiocpp_server`` executable, downloading the pinned release first when it is missing."""
    srv = server_path(backend)
    if srv is not None:
        return srv
    p = plan(None, backend)
    problem = disk_problem(p.todo_bytes)
    if problem:
        raise NativeError(problem)
    install(p, progress, log)
    srv = server_path(backend)
    if srv is None:
        raise NativeError("The native engine could not be installed")
    return srv
