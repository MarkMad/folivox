"""Locate or download CosyVoice 3 weights (Apache-2.0, FunAudioLLM/Fun-CosyVoice3-0.5B-2512)."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

from folivox.i18n import _

REPO_ID = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
REQUIRED = ["cosyvoice3.yaml", "llm.pt", "flow.pt", "hift.pt", "campplus.onnx", "speech_tokenizer_v3.onnx",
            "CosyVoice-BlankEN/config.json"]
# Skipped: TensorRT estimator export, batch tokenizer, the RL variant of the LLM (~4.3 GB together).
ALLOW = ["cosyvoice3.yaml", "config.json", "configuration.json", "llm.pt", "flow.pt", "hift.pt", "campplus.onnx",
         "speech_tokenizer_v3.onnx", "CosyVoice-BlankEN/*", "README.md"]
ENV = "FOLIVOX_MODEL_DIR"


def default_model_dir() -> Path:
    return Path(user_data_dir("folivox", appauthor=False)) / "models" / "Fun-CosyVoice3-0.5B"


def is_complete(path: Path) -> bool:
    return all((path / f).exists() for f in REQUIRED)


def resolve_model_dir(explicit: str | os.PathLike | None = None, download: bool = True) -> Path:
    for cand in (explicit, os.environ.get(ENV)):
        if cand:
            p = Path(cand).expanduser()
            if not is_complete(p):
                raise FileNotFoundError(_("{path} has no complete set of CosyVoice 3 weights (needed: {files})",
                                          path=p, files=", ".join(REQUIRED)))
            return p
    p = default_model_dir()
    if is_complete(p):
        return p
    if not download:
        raise FileNotFoundError(_("Weights not found in {path}", path=p))
    return download_weights(p)


LLM_FILES = {"base": "llm.pt", "rl": "llm.rl.pt"}


def ensure_llm(model_dir: Path, variant: str) -> str:
    """Return the LLM weights file name for ``variant``, downloading the RL file on demand."""
    name = LLM_FILES[variant]
    if not (model_dir / name).exists():
        from huggingface_hub import hf_hub_download

        print(_("Downloading {name} (~2 GB)…", name=name), flush=True)
        hf_hub_download(REPO_ID, name, local_dir=str(model_dir))
    return name


def download_weights(target: Path) -> Path:
    from huggingface_hub import snapshot_download

    target.mkdir(parents=True, exist_ok=True)
    print(_("Downloading CosyVoice 3 weights (~4.5 GB) from huggingface.co/{repo} to {path}…", repo=REPO_ID,
            path=target), flush=True)
    snapshot_download(REPO_ID, local_dir=str(target), allow_patterns=ALLOW)
    if not is_complete(target):
        raise RuntimeError(_("Weights download incomplete: {path}", path=target))
    return target
