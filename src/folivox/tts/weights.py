"""Locate or download CosyVoice 3 weights (Apache-2.0, FunAudioLLM/Fun-CosyVoice3-0.5B-2512)."""

from __future__ import annotations

import fnmatch
import json
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from platformdirs import user_data_dir

REPO_ID = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
REQUIRED = ["cosyvoice3.yaml", "llm.pt", "flow.pt", "hift.pt", "campplus.onnx", "speech_tokenizer_v3.onnx",
            "CosyVoice-BlankEN/config.json", "CosyVoice-BlankEN/model.safetensors", "CosyVoice-BlankEN/vocab.json",
            "CosyVoice-BlankEN/merges.txt", "CosyVoice-BlankEN/tokenizer_config.json"]
# Skipped: TensorRT estimator export, batch tokenizer, the RL variant of the LLM (~4.3 GB together).
ALLOW = ["cosyvoice3.yaml", "config.json", "configuration.json", "llm.pt", "flow.pt", "hift.pt", "campplus.onnx",
         "speech_tokenizer_v3.onnx", "CosyVoice-BlankEN/*", "README.md"]
ENV = "FOLIVOX_MODEL_DIR"

# Called as hook(name, downloaded_bytes, total_bytes) while weights are downloaded (total 0 = unknown).
_hook: Callable[[str, int, int], None] | None = None
POLL_SECONDS = 1.0


@contextmanager
def reporting(hook: Callable[[str, int, int], None] | None) -> Iterator[None]:
    """Report download progress to ``hook`` for downloads started inside the block."""
    global _hook
    previous, _hook = _hook, hook
    try:
        yield
    finally:
        _hook = previous


class DownloadMeter:
    """Speed (smoothed over the last ~10 s of samples) and time left from a stream of (bytes done, now)."""

    WINDOW = 10.0

    def __init__(self):
        self.samples: list[tuple[float, int]] = []

    def update(self, done: int, total: int, now: float) -> tuple[float, float | None]:
        """Returns (bytes per second, seconds left or None while unknown)."""
        self.samples.append((now, done))
        while len(self.samples) > 2 and now - self.samples[0][0] > self.WINDOW:
            self.samples.pop(0)
        t0, d0 = self.samples[0]
        speed = (done - d0) / (now - t0) if now > t0 and done >= d0 else 0.0
        eta = (total - done) / speed if speed > 0 and total > done else None
        return speed, eta


def _live_size(p: Path) -> int:
    """Size of a file that may still be written. On Windows ``stat()`` on a growing file returns a stale size (NTFS
    updates it lazily, in bursts), so ask through an open handle, which is exact."""
    try:
        with open(p, "rb") as f:
            return f.seek(0, 2)
    except OSError:
        return p.stat().st_size


def _downloaded(target: Path, patterns: list[str]) -> int:
    """Bytes on disk: finished files matching ``patterns`` plus huggingface_hub's ``.incomplete`` parts."""
    done = 0
    for p in target.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(target).as_posix()
        try:  # a part file renamed to its final name between the walk and the stat must not kill the watcher
            if rel.startswith(".cache/"):
                done += _live_size(p) if rel.endswith(".incomplete") else 0
            elif any(fnmatch.fnmatch(rel, pat) for pat in patterns):
                done += p.stat().st_size
        except OSError:
            continue
    return done


def _total_size(patterns: list[str]) -> int:
    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(REPO_ID, files_metadata=True)
        return sum(f.size or 0 for f in info.siblings if any(fnmatch.fnmatch(f.rfilename, p) for p in patterns))
    except Exception:  # noqa: BLE001 — offline metadata is a nicety; the download itself decides success
        return 0


def _hub_bars_off() -> Callable[[], None]:
    """Silence huggingface_hub's own per-file tqdm bars (parallel bars tear apart on a Windows console and fight
    our single progress line); returns a function that restores them."""
    try:
        from huggingface_hub.utils import are_progress_bars_disabled, disable_progress_bars, enable_progress_bars
    except ImportError:
        return lambda: None
    if are_progress_bars_disabled():
        return lambda: None
    disable_progress_bars()
    return enable_progress_bars


@contextmanager
def _watch_measured(name: str, measure: Callable[[], int], total: int) -> Iterator[None]:
    hook = _hook
    if hook is None:
        yield
        return
    stop = threading.Event()
    hub_bars = _hub_bars_off()

    def poll() -> None:
        last = -1
        while True:
            done = measure()
            if done != last:
                hook(name, done, max(total, done) if total else 0)
                last = done
            if stop.wait(POLL_SECONDS):
                return

    t = threading.Thread(target=poll, daemon=True, name="folivox-download-watch")
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join()
        hub_bars()
        hook(name, total or measure(), total)


@contextmanager
def _watch(name: str, target: Path, patterns: list[str], total: int | None = None) -> Iterator[None]:
    """``total`` is the known size in bytes; without it the size is looked up in the default (CosyVoice) repo."""
    if _hook is None:
        yield
        return
    size = _total_size(patterns) if total is None else total
    with _watch_measured(name, lambda: _downloaded(target, patterns), size):
        yield


def _repo_total(repo_id: str) -> int:
    try:
        from huggingface_hub import HfApi

        return sum(f.size or 0 for f in HfApi().model_info(repo_id, files_metadata=True).siblings)
    except Exception:  # noqa: BLE001 — see _total_size
        return 0


def _cache_bytes(repo_id: str) -> int:
    """Bytes in the huggingface cache folder of ``repo_id`` (finished blobs and ``.incomplete`` parts)."""
    root = _hf_repo_dir(repo_id) / "blobs"
    try:
        return sum(p.stat().st_size for p in root.iterdir() if p.is_file())
    except OSError:
        return 0


def _hf_repo_dir(repo_id: str) -> Path:
    from huggingface_hub import constants

    return Path(constants.HF_HUB_CACHE) / ("models--" + repo_id.replace("/", "--"))


def _owned_file() -> Path:
    return Path(user_data_dir("folivox", appauthor=False)) / "owned.json"


def owned_repos() -> list[str]:
    """huggingface repos in the shared cache that Folivox downloaded itself (so `uninstall` may remove them)."""
    try:
        return list(json.loads(_owned_file().read_text(encoding="utf-8")).get("hf_repos", []))
    except (OSError, ValueError, AttributeError):
        return []


def _claim_repo(repo_id: str) -> None:
    """Remember ``repo_id`` as ours when its cache folder does not exist yet (never claim what the user had)."""
    try:
        if _hf_repo_dir(repo_id).exists():
            return
        repos = owned_repos()
        if repo_id not in repos:
            f = _owned_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"hf_repos": repos + [repo_id]}), encoding="utf-8")
    except OSError:
        pass  # without the note `uninstall` leaves the model alone: the safe direction


@contextmanager
def watch_repo(name: str, repo_id: str | None) -> Iterator[None]:
    """Progress for a download into the shared huggingface cache that we do not drive ourselves (Whisper)."""
    if repo_id:
        _claim_repo(repo_id)
    if _hook is None or not repo_id:
        yield
        return
    with _watch_measured(name, lambda: _cache_bytes(repo_id), _repo_total(repo_id)):
        yield


def default_model_dir() -> Path:
    return Path(user_data_dir("folivox", appauthor=False)) / "models" / "Fun-CosyVoice3-0.5B"


def is_complete(path: Path) -> bool:
    """Every required file exists and is not empty (hf downloads land under their final name only when whole)."""
    try:
        return all((path / f).is_file() and (path / f).stat().st_size > 0 for f in REQUIRED)
    except OSError:
        return False


DOWNLOAD_ATTEMPTS = 4


def with_retries(fn, what: str, attempts: int = DOWNLOAD_ATTEMPTS, sleep=None):
    """Run a (resumable) download, retrying network failures with growing pauses; huggingface_hub continues
    from its ``.incomplete`` part files, so each attempt picks up where the previous one stopped."""
    import time

    sleep = sleep or time.sleep
    try:  # permanent hub answers (wrong repo/file/revision, gated): retrying only wastes time
        from huggingface_hub.errors import (
            EntryNotFoundError,
            GatedRepoError,
            RepositoryNotFoundError,
            RevisionNotFoundError,
        )
        permanent: tuple[type[BaseException], ...] = (RepositoryNotFoundError, EntryNotFoundError, GatedRepoError,
                                                      RevisionNotFoundError)
    except ImportError:
        permanent = ()
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except (KeyboardInterrupt, FileNotFoundError, PermissionError):
            raise
        except permanent:
            raise
        except OSError as e:
            if getattr(e, "errno", None) == 28:  # ENOSPC
                raise RuntimeError(f"No space left on the disk while downloading {what}. Free some space and "
                                   "run again: the download continues where it stopped") from e
            err = e
        except Exception as e:  # noqa: BLE001 — hub errors: connection, timeout, 5xx
            err = e
        if attempt == attempts:
            raise RuntimeError(f"Downloading {what} failed after {attempts} attempts: {err}. Check the network and "
                               "run again: the download continues where it stopped") from err
        sleep(min(5 * 2 ** (attempt - 1), 60))


def resolve_model_dir(explicit: str | os.PathLike | None = None, download: bool = True) -> Path:
    for cand in (explicit, os.environ.get(ENV)):
        if cand:
            p = Path(cand).expanduser()
            if not is_complete(p):
                raise FileNotFoundError(f"{p} has no complete set of CosyVoice 3 weights "
                                        f"(needed: {', '.join(REQUIRED)})")
            return p
    p = default_model_dir()
    if is_complete(p):
        return p
    if not download:
        raise FileNotFoundError(f"Weights not found in {p}")
    return download_weights(p)


LLM_FILES = {"base": "llm.pt", "rl": "llm.rl.pt"}


def _has(f: Path) -> bool:
    try:
        return f.is_file() and f.stat().st_size > 0
    except OSError:
        return False


def needs_download(explicit: str | os.PathLike | None = None, llm: str = "rl") -> bool:
    """True when starting the engine would download weights (so the UI can say so up front)."""
    name = LLM_FILES.get(llm, "llm.pt")
    own = default_model_dir()
    for cand in (explicit, os.environ.get(ENV)):
        if cand:
            # a user-provided folder is never downloaded into (an incomplete one is an error); a missing
            # LLM file comes from Folivox's own model folder instead, see ensure_llm
            p = Path(cand).expanduser()
            return is_complete(p) and not _has(p / name) and not _has(own / name)
    return not is_complete(own) or not _has(own / name)


def ensure_llm(model_dir: Path, variant: str) -> str:
    """Return the LLM weights file for ``variant``, relative to ``model_dir``, downloading the RL file on demand.

    Folivox downloads only into its own model folder: when a user-managed ``model_dir`` lacks the file, the copy
    in ``default_model_dir()`` is used (and downloaded there if needed) and returned as a path relative to
    ``model_dir``, because CosyVoice3 joins the two as ``f"{model_dir}/{llm_file}"``."""
    name = LLM_FILES[variant]
    if _has(model_dir / name):
        return name
    own = default_model_dir()
    if not _has(own / name):
        from huggingface_hub import hf_hub_download

        own.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {name} (~2 GB) to {own}…", flush=True)
        with _watch(name, own, [name]):
            with_retries(lambda: hf_hub_download(REPO_ID, name, local_dir=str(own)), name)
    try:
        if own.resolve() == model_dir.resolve():
            return name
        return os.path.relpath(own.resolve() / name, model_dir.resolve())
    except ValueError:  # Windows: different drives have no relative path
        raise FileNotFoundError(f"{model_dir} has no {name} and Folivox's copy in {own} is on another drive. "
                                f"Copy {own / name} into {model_dir}, or use the base model (llm=base)") from None


def download_weights(target: Path) -> Path:
    from huggingface_hub import snapshot_download

    target.mkdir(parents=True, exist_ok=True)
    print(f"Downloading CosyVoice 3 weights (~4.5 GB) from huggingface.co/{REPO_ID} to {target}…", flush=True)
    with _watch("CosyVoice 3 weights", target, ALLOW):
        with_retries(lambda: snapshot_download(REPO_ID, local_dir=str(target), allow_patterns=ALLOW),
                     "the CosyVoice 3 weights")
    if not is_complete(target):
        raise RuntimeError(f"Weights download incomplete: {target}")
    return target
