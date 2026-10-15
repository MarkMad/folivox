"""Text LLM providers (see :data:`LLMS`): picking voice-sample fragments, later text analysis.

Local: Ollama. Optional: any OpenAI-compatible chat endpoint (OpenAI, OpenRouter, a local
llama.cpp / vLLM server…) with the user's own key.
"""

from __future__ import annotations

import json
import os
import urllib.request

from folivox.providers import Registry


class LLM:
    name = ""

    def complete(self, prompt: str, system: str | None = None, temperature: float = 0.3) -> str:
        raise NotImplementedError

    def complete_json(self, prompt: str, system: str | None = None, temperature: float = 0.2) -> str:
        """Like :meth:`complete`, asking the model for a JSON document where the backend can enforce it."""
        return self.complete(prompt, system, temperature)


# Gemma 4 (multilingual) in the sizes Ollama offers, by the memory a computer has for a model that runs alone
# (book analysis runs before the audio is made, never together with the TTS model). QAT builds, sizes from
# ollama.com/library/gemma4/tags. (minimum total RAM in GB, tag, download GB, note)
GEMMA_TIERS = (
    (48, "gemma4:31b-it-qat", 19, "best understanding of long, complex books"),
    (32, "gemma4:26b-a4b-it-qat", 16, "nearly as good, much faster (4B active parameters)"),
    (0, "gemma4:12b-it-qat", 7.2, "good for most books; the smallest that was reliable (slow below 16 GB of memory)"),
)


def recommend_model(total_ram_gb: float | None) -> str:
    """The largest Gemma 4 that leaves room on a computer with ``total_ram_gb`` (the default when RAM is unknown)."""
    if total_ram_gb is None:
        return "gemma4:12b-it-qat"
    return next(tag for need, tag, _gb, _note in GEMMA_TIERS if total_ram_gb >= need)


def _post(url: str, payload: dict, headers: dict | None = None, timeout: float = 600) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class Ollama(LLM):
    name = "ollama"

    def __init__(self, model: str = "gemma4:31b-it-qat", host: str | None = None, num_ctx: int = 16384):
        self.model = model
        self.num_ctx = num_ctx  # Ollama's own default (4096) silently cuts a long prompt
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        if not self.host.startswith("http"):
            self.host = "http://" + self.host

    def complete(self, prompt, system=None, temperature=0.3):
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        r = _post(f"{self.host}/api/chat", {"model": self.model, "messages": msgs, "stream": False, "think": False,
                                            "options": {"temperature": temperature, "num_ctx": self.num_ctx}})
        return r["message"]["content"].strip()

    def complete_json(self, prompt, system=None, temperature=0.2):
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        r = _post(f"{self.host}/api/chat", {"model": self.model, "messages": msgs, "stream": False, "think": False,
                                            "format": "json",
                                            "options": {"temperature": temperature, "num_ctx": self.num_ctx}})
        return r["message"]["content"].strip()

    def installed(self) -> list[str]:
        """Models already pulled into this Ollama (empty when it is not running)."""
        try:
            req = urllib.request.Request(f"{self.host}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as r:
                return [m["name"] for m in json.loads(r.read()).get("models", [])]
        except (OSError, ValueError):
            return []


class OpenAICompatible(LLM):
    name = "openai"

    def __init__(self, model: str = "gpt-5-mini", base_url: str = "https://api.openai.com/v1",
                 api_key_env: str = "OPENAI_API_KEY"):
        from folivox.config import api_key

        self.model, self.base_url = model, base_url.rstrip("/")
        self.key = api_key(api_key_env, "LLM")

    def complete(self, prompt, system=None, temperature=0.3):
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        r = _post(f"{self.base_url}/chat/completions", {"model": self.model, "messages": msgs},
                  {"Authorization": f"Bearer {self.key}"})
        return r["choices"][0]["message"]["content"].strip()


LLMS: Registry = Registry("llm", default="ollama")
LLMS.register("ollama", Ollama, "Local models via Ollama (default model gemma4:31b-it-qat)", needs="ollama")
LLMS.register("openai", OpenAICompatible, "OpenAI-compatible chat API: OpenAI, OpenRouter, llama.cpp… (your key)",
              local=False, needs="OPENAI_API_KEY")
