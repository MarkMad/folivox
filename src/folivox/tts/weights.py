"""Locate or download CosyVoice 3 weights (Apache-2.0, FunAudioLLM/Fun-CosyVoice3-0.5B-2512)."""

from __future__ import annotations

import fnmatch
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from platformdirs import user_data_dir

REPO_ID = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
REQUIRED = ["cosyvoice3.yaml", "llm.pt", "flow.pt", "hift.pt", "campplus.onnx", "speech_tokenizer_v3.onnx",
            "CosyVoice-BlankEN/config.json"]
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


def _downloaded(target: Path, patterns: list[str]) -> int:
    """Bytes on disk: finished files matching ``patterns`` plus huggingface_hub's ``.incomplete`` parts."""
    done = 0
    for p in target.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(target).as_posix()
        if rel.startswith(".cache/"):
            done += p.stat().st_size if rel.endswith(".incomplete") else 0
        elif any(fnmatch.fnmatch(rel, pat) for pat in patterns):
            done += p.stat().st_size
    return done


def _total_size(patterns: list[str]) -> int:
    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(REPO_ID, files_metadata=True)
        return sum(f.size or 0 for f in info.siblings if any(fnmatch.fnmatch(f.rfilename, p) for p in patterns))
    except Exception:  # noqa: BLE001 — offline metadata is a nicety; the download itself decides success
        return 0


@contextmanager
def _watch(name: str, target: Path, patterns: list[str]) -> Iterator[None]:
    hook = _hook
    if hook is None:
        yield
        return
    stop = threading.Event()
    total = _total_size(patterns)

    def poll() -> None:
        last = -1
        while True:
            done = _downloaded(target, patterns)
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
        hook(name, total or _downloaded(target, patterns), total)


def default_model_dir() -> Path:
    return Path(user_data_dir("folivox", appauthor=False)) / "models" / "Fun-CosyVoice3-0.5B"


def is_complete(path: Path) -> bool:
    return all((path / f).exists() for f in REQUIRED)


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


def needs_download(explicit: str | os.PathLike | None = None, llm: str = "rl") -> bool:
    """True when starting the engine would download weights (so the UI can say so up front)."""
    if explicit or os.environ.get(ENV):
        return False  # a user-provided folder is never downloaded into (an incomplete one is an error)
    p = default_model_dir()
    return not is_complete(p) or not (p / LLM_FILES.get(llm, "llm.pt")).exists()


def ensure_llm(model_dir: Path, variant: str) -> str:
    """Return the LLM weights file name for ``variant``, downloading the RL file on demand."""
    name = LLM_FILES[variant]
    if not (model_dir / name).exists():
        from huggingface_hub import hf_hub_download

        print(f"Downloading {name} (~2 GB)…", flush=True)
        with _watch(name, model_dir, [name]):
            hf_hub_download(REPO_ID, name, local_dir=str(model_dir))
    return name


def download_weights(target: Path) -> Path:
    from huggingface_hub import snapshot_download

    target.mkdir(parents=True, exist_ok=True)
    print(f"Downloading CosyVoice 3 weights (~4.5 GB) from huggingface.co/{REPO_ID} to {target}…", flush=True)
    with _watch("CosyVoice 3 weights", target, ALLOW):
        snapshot_download(REPO_ID, local_dir=str(target), allow_patterns=ALLOW)
    if not is_complete(target):
        raise RuntimeError(f"Weights download incomplete: {target}")
    return target
