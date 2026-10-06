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


def _post(url: str, payload: dict, headers: dict | None = None, timeout: float = 600) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class Ollama(LLM):
    name = "ollama"

    def __init__(self, model: str = "gemma4:31b-it-qat", host: str | None = None):
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        if not self.host.startswith("http"):
            self.host = "http://" + self.host

    def complete(self, prompt, system=None, temperature=0.3):
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        r = _post(f"{self.host}/api/chat", {"model": self.model, "messages": msgs, "stream": False, "think": False,
                                            "options": {"temperature": temperature}})
        return r["message"]["content"].strip()


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
