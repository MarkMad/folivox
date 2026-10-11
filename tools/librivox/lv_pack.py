"""lv_pack.py <work> <code> [per_gender]
Select the best candidates from <work>/<code>_clips.json (prose, no duplicate texts, best Whisper confidence,
<=2 clips per reader, balanced low/high F0), write them with a СПИСОК.txt into ~/Desktop/folivox_voices/librivox_<code>/
and zip. The full set stays in <work>/all_<code>/."""
import json, shutil, sys
from pathlib import Path

work, code = Path(sys.argv[1]), sys.argv[2]
per = int(sys.argv[3]) if len(sys.argv) > 3 else 12
src = Path.home() / f"Desktop/folivox_voices/librivox_{code}"
dst = Path.home() / "Desktop/folivox_voices"
rows = [r for r in json.load(open(work / f"{code}_clips.json")) if r["ok"]]
cjk = code in ("ja", "zh", "ko")
seen, good = set(), []
for r in sorted(rows, key=lambda r: -r["conf"]):
    key = r["text"][:40]
    if key in seen: continue
    if (r["kind"] != "проза" and not cjk) or r["conf"] < (-0.9 if cjk else -0.45) or not r["punct"]: continue
    if not 4 <= r["cps"] <= 22 and not cjk: continue
    seen.add(key); good.append(r)
by = {}
for r in good: by.setdefault(r["reader_id"], []).append(r)
readers = sorted(by.values(), key=lambda v: -v[0]["conf"])
def gender(f0): return "м?" if f0 < 165 else "ж?"
pickr, cnt = [], {"м?": 0, "ж?": 0}
for v in readers:
    g = gender(sorted(x["f0"] for x in v)[len(v)//2])
    if cnt[g] < per: cnt[g] += 1; pickr.append((g, v[:2]))
final = Path(work / f"final_{code}"); shutil.rmtree(final, ignore_errors=True); final.mkdir()
lines = ["имя | пол по F0 (оценка) | чтец | reader_id | книга | жанр | длительность | F0 | зн/с | уверенность Whisper (ближе к 0 лучше) | источник | текст"]
for g, v in sorted(pickr, key=lambda t: (t[0], t[1][0]["f0"])):
    for r in v:
        for ext in ("wav", "txt"): shutil.copy(src / f"{r['name']}.{ext}", final / f"{r['name']}.{ext}")
        lines.append(f"{r['name']} | {g} | {r['reader']} | {r['reader_id']} | {r['book']} | {r['kind']} ({', '.join(r['genres'])}) | "
                     f"{r['dur']} с | {r['f0']} Гц | {r['cps']} | {r['conf']} | {r['book_url']} (секция {r['section']}, {r['mp3']}) | {r['text']}")
(final / "СПИСОК.txt").write_text("\n".join(lines), encoding="utf-8")
shutil.rmtree(work / f"all_{code}", ignore_errors=True); shutil.move(str(src), str(work / f"all_{code}"))
shutil.move(str(final), str(src))
shutil.make_archive(str(dst / f"librivox_{code}"), "zip", dst, f"librivox_{code}")
print(code, "readers", len(pickr), "(м?", cnt["м?"], "ж?", cnt["ж?"], ") clips", len(lines) - 1, "of", len(rows))
