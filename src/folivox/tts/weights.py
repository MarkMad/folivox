"""Locate or download CosyVoice 3 weights (Apache-2.0, FunAudioLLM/Fun-CosyVoice3-0.5B-2512)."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

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
                raise FileNotFoundError(f"В {p} нет полного набора весов CosyVoice 3 (нужны: {', '.join(REQUIRED)})")
            return p
    p = default_model_dir()
    if is_complete(p):
        return p
    if not download:
        raise FileNotFoundError(f"Веса не найдены в {p}")
    return download_weights(p)


def download_weights(target: Path) -> Path:
    from huggingface_hub import snapshot_download

    target.mkdir(parents=True, exist_ok=True)
    print(f"Скачиваю веса CosyVoice 3 (~4.5 ГБ) из huggingface.co/{REPO_ID} в {target} …", flush=True)
    snapshot_download(REPO_ID, local_dir=str(target), allow_patterns=ALLOW)
    if not is_complete(target):
        raise RuntimeError(f"Загрузка весов не завершена: {target}")
    return target
