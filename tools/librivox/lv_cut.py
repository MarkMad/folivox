"""lv_cut.py <work> <code> [out_dir]
Whisper segments (language = <code>) -> 8-15 s window between sentence boundaries, wav + txt + СПИСОК.txt."""
import json, re, subprocess, sys
from pathlib import Path
import librosa, mlx_whisper, numpy as np, soundfile as sf
from folivox.qa import canonical

S, code = Path(sys.argv[1]), sys.argv[2]
out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path.home() / f"Desktop/folivox_voices/librivox_{code}"
out.mkdir(parents=True, exist_ok=True)
SENT = r"[.!?…。！？」』»”\"]$"
PROMPT = {"it": "Buongiorno, signor Rossi. Come sta? Molto bene, grazie.", "fr": "Bonjour, monsieur Dupont. Comment allez-vous ? Très bien, merci.",
          "de": "Guten Tag, Herr Müller. Wie geht es Ihnen? Danke, gut.", "es": "Buenos días, señor García. ¿Cómo está usted? Muy bien, gracias.",
          "en": "Good morning, Mr. Smith. How are you? Very well, thank you.", "ko": "안녕하세요. 잘 지내셨어요? 네, 잘 지냈습니다.",
          "ja": "こんにちは。お元気ですか？はい、元気です。", "zh": "你好，先生。你好吗？我很好，谢谢。"}
CJK = code in ("zh", "ja", "ko")  # no spaces / capitals
END = r"[.!?…。！？」』»”\"]\W*$"
if CJK or code == "ko":  # Whisper often punctuates these with commas only: accept clause boundaries (flagged in the list)
    END = r"[.!?…。！？」』»”\",，、]\W*$"
ANN = re.compile(r"librivox|public domain|recording by|chapter|capitulo|capítulo|kapitel|chapitre|capitolo|"
                 r"volunteer|lizenz|gemeinfrei|dominio p|domaine public|pubblico dominio|リブリボックス|リブリヴォックス|"
                 r"录音|朗读|朗読|녹음|리브리복스|lecture|lectura|leitura|gelesen von|lue par|leído por|letto da", re.I)
jobs = json.load(open(S / f"{code}_jobs.json")); rows = []
for j in jobs:
    f = S / f"{code}_raw" / j["file"]
    if not f.exists() or f.stat().st_size < 50000: continue
    wav = S / "tmp.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-ac", "1", "-ar", "24000", str(wav)], check=True)
    a, sr = sf.read(wav, dtype="float32")
    seg = mlx_whisper.transcribe(str(wav), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language=code,
                                 condition_on_previous_text=False, verbose=None, word_timestamps=True,
                                 initial_prompt=PROMPT.get(code))["segments"]
    words = [w for sg in seg for w in sg["words"]]
    def txt(i, k):
        t = "".join(w["word"] for w in words[i:k+1]); return t.strip()
    gap = lambda i: words[i]["start"] - words[i-1]["end"] if i > 0 else 0   # pause before word i
    pick = None
    for mode in (0, 1, 2):  # 0: sentence start+end; 1: start at a pause, sentence end; 2: pauses only
        strict = mode < 2
        for i in range(1, len(words)):
            begins = re.search(SENT, words[i-1]["word"].strip()) if mode == 0 else gap(i) >= 0.3
            if not begins or (mode == 0 and not CJK and not words[i]["word"].strip()[:1].isupper()): continue
            for k in range(i, len(words)):
                d = words[k]["end"] - words[i]["start"]
                if d > 15: break
                nxt = gap(k+1) if k + 1 < len(words) else 0
                if d >= 8 and (re.search(SENT, words[k]["word"].strip()) if strict else nxt >= 0.35):
                    pick = (i, k); break
            if pick: break
        if pick: break
    if not pick: rows.append({**j, "ok": False}); print(j["file"], "no window"); continue
    i, k = pick; t0 = max(0, words[i]["start"] - 0.1); t1 = min(len(a)/sr, words[k]["end"] + 0.15)
    text = txt(i, k)
    seg = [sg for sg in seg if sg["end"] > t0 and sg["start"] < t1]; i = 0; k = len(seg) - 1
    punct = bool(re.search(r"[.!?…。！？,，、]", text))
    clip = a[int(t0*sr):int(t1*sr)]
    if ANN.search(text): rows.append({**j, "ok": False}); print(j["file"], "announcement"); continue
    clip = clip * (0.9 / max(1e-6, np.abs(clip).max()))
    name = f"{re.sub(r'[^A-Za-z0-9]+', '_', j['reader']).strip('_') or 'reader'}_{j['reader_id']}_{j['file'].split('_')[1][0]}"
    sf.write(out / f"{name}.wav", clip, sr, subtype="PCM_16"); (out / f"{name}.txt").write_text(text, encoding="utf-8")
    f0, _, _ = librosa.pyin(librosa.resample(clip, orig_sr=sr, target_sr=16000), fmin=60, fmax=500, sr=16000)
    dur = len(clip) / sr; cps = len(canonical(text, code)) / dur
    kind = "СТИХИ?" if any("poet" in g.lower() for g in j["genres"]) else "проза"
    rows.append({**j, "ok": True, "name": name, "dur": round(dur, 1), "f0": int(np.nanmedian(f0)), "cps": round(cps, 1),
                 "text": text, "punct": punct, "kind": kind,
                 "conf": round(float(np.mean([x["avg_logprob"] for x in seg[i:k+1]])), 2)})
    print(name, round(dur, 1), int(np.nanmedian(f0)), "Hz", round(cps, 1), "cps", kind, text[:60], flush=True)
json.dump(rows, open(S / f"{code}_clips.json", "w"), ensure_ascii=False, indent=1)
ok = [r for r in rows if r["ok"]]
lines = ["имя | чтец | reader_id | книга | жанр | длительность | F0 | зн/с | уверенность Whisper (ближе к 0 лучше) | источник | текст"]
for r in sorted(ok, key=lambda r: r["f0"]):
    lines.append(f"{r['name']} | {r['reader']} | {r['reader_id']} | {r['book']} | {r['kind']} ({', '.join(r['genres'])}) | "
                 f"{r['dur']} с | {r['f0']} Гц | {r['cps']} | {'' if r['punct'] else 'БЕЗ ПУНКТУАЦИИ | '}conf {r['conf']} | {r['book_url']} (секция {r['section']}, {r['mp3']}) | {r['text']}")
(out / "СПИСОК.txt").write_text("\n".join(lines), encoding="utf-8")
print(len(ok), "clips of", len(rows))
