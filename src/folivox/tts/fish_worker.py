"""Fish Audio worker: runs inside the engine's own Python environment (mlx-audio installed there), not in
Folivox's. Standalone: it must not import folivox, and Folivox never imports Fish code.

Protocol: one JSON object per line on stdin, one JSON reply per line on the real stdout (everything the
libraries print goes to stderr).

    {"cmd": "load", "model_dir": dir, "kind": "s2" | "drama3", "warmup": {"wav", "text"} | null}
        → {"ok": true, "sample_rate": 44100, "load_s": .., "warm_s": ..}
    {"cmd": "synth", "id": n, "text": str, "refs": [{"wav": path, "text": str}], "seed": int, "out": "x.npy"}
        → {"ok": true, "id": n, "out": "x.npy", "audio_s": .., "seconds": .., "peak_gb": ..}
    {"cmd": "quit"}

Several ``refs`` are for multi-speaker text: the transcript of reference *i* starts with ``<|speaker:i|>``.
Any failure replies {"ok": false, "error": "..."}; the process stays alive for the next request.
"""

import json
import os
import sys
import time
import traceback


def main() -> None:
    proto = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)  # stray prints from libraries must not corrupt the protocol channel
    sys.stdout = sys.stderr

    def reply(obj: dict) -> None:
        proto.write(json.dumps(obj, ensure_ascii=False) + "\n")
        proto.flush()

    import mlx.core as mx
    import numpy as np
    from mlx_audio.tts.utils import load_model

    state: dict = {}

    def generate(text: str, refs: list[dict], seed: int):
        model, kind = state["model"], state["kind"]
        try:
            mx.random.seed(int(seed))
        except Exception:  # noqa: BLE001
            pass
        if kind == "drama3":  # takes file paths; speaker tags live in the transcripts
            audio = [r["wav"] for r in refs]
            texts = [r["text"] for r in refs]
            kwargs = {"ref_audio": audio if len(audio) > 1 else audio[0],
                      "ref_text": texts if len(texts) > 1 else texts[0]}
        else:  # S2 Pro: one reference, loaded at the model's sample rate
            from mlx_audio.utils import load_audio

            kwargs = {"ref_audio": load_audio(refs[0]["wav"], sample_rate=model.sample_rate),
                      "ref_text": refs[0]["text"]}
        parts = [np.array(r.audio, dtype=np.float32).reshape(-1) for r in model.generate(text=text, **kwargs)]
        return np.concatenate(parts) if parts else np.zeros(0, np.float32)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            cmd = req["cmd"]
            if cmd == "quit":
                return
            if cmd == "load":
                t0 = time.time()
                state["model"] = load_model(req["model_dir"])
                state["kind"] = req["kind"]
                load_s = time.time() - t0
                warm_s = 0.0
                if req.get("warmup"):  # the first call compiles kernels (80-90 s for Drama 3): pay it here
                    t1 = time.time()
                    w = req["warmup"]
                    generate("Hello there.", [{"wav": w["wav"], "text": w["text"]}], 0)
                    warm_s = time.time() - t1
                reply({"ok": True, "sample_rate": int(state["model"].sample_rate), "load_s": load_s,
                       "warm_s": warm_s})
            elif cmd == "synth":
                t0 = time.time()
                audio = generate(req["text"], req["refs"], req.get("seed", 0))
                np.save(req["out"], audio)
                reply({"ok": True, "id": req.get("id"), "out": req["out"],
                       "audio_s": len(audio) / state["model"].sample_rate, "seconds": time.time() - t0,
                       "peak_gb": mx.get_peak_memory() / 1e9})
            else:
                reply({"ok": False, "error": f"unknown command {cmd!r}"})
        except Exception as e:  # noqa: BLE001 — report and keep serving
            traceback.print_exc()
            reply({"ok": False, "error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
