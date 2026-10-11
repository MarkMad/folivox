"""lv_dl.py <work> <Language> <code> <max_readers>
Per reader (most sections first) picks 2 sections from different books and downloads ~45 s from the
middle with an HTTP Range request (mp3 is 64 kbps: byte offset = seconds * 8000)."""
import collections, concurrent.futures as cf, json, subprocess, sys, time
from pathlib import Path

work, lang, code, nmax = Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4])
ALL = json.load(open(work / f"sec_{lang}.json"))
nread = collections.Counter(x["mp3"] for x in ALL)  # sections with several readers: speaker is ambiguous
VERSE = ("poet", "epic", "verse", "ballad", "poem", "sonnet", "lyric", "rime", "canti", "divin", "furioso", "gedicht", "poesi", "poés")
def verse(x): return any(v in (" ".join(x["genres"]) + " " + x["title"]).lower() for v in VERSE)
sec = [x for x in ALL if nread[x["mp3"]] == 1 and (code in ("ja", "zh", "ko") or not verse(x)) and x["playtime"] >= int(sys.argv[5] if len(sys.argv) > 5 else 120)]
by = collections.defaultdict(list)
for x in sec: by[x["reader_id"]].append(x)
readers = sorted(by, key=lambda r: -len(by[r]))[:nmax]
out = work / f"{code}_raw"; out.mkdir(exist_ok=True)
jobs = []
for rid in readers:
    v = by[rid]; seen, pick = set(), []
    for x in sorted(v, key=lambda x: -x["playtime"]):
        if x["book"] in seen: continue
        seen.add(x["book"]); pick.append(x)
        if len(pick) == 2: break
    for x in sorted(v, key=lambda x: -x["playtime"]):  # few books: fill up from other sections
        if len(pick) >= 2: break
        if x not in pick: pick.append(x)
    for k, x in enumerate(pick):
        jobs.append((rid, k, x, max(20, min(120, x["playtime"] // 2 - 13)), len(v)))
def dl(j):
    rid, k, x, start, _ = j; f = out / f"{rid}_{k}.mp3"
    if f.exists() and f.stat().st_size > 50000: return f.name, True
    time.sleep(0.5)
    r = subprocess.run(["curl", "-sL", "--max-time", "90", "-r", f"{start*8000}-{(start+45)*8000}", "-A",
                        "folivox-voice-research/0.1", "-o", str(f), "-w", "%{http_code}", x["mp3"]],
                       capture_output=True, text=True)
    return f.name, r.stdout == "206"
with cf.ThreadPoolExecutor(3) as ex: res = list(ex.map(dl, jobs))
json.dump([{"file": f"{r}_{k}.mp3", "reader_id": r, "reader": x["reader"], "book": x["title"], "book_url": x["url"],
            "src": x["src"], "genres": x["genres"], "section": x["sec"], "start": s, "mp3": x["mp3"], "n_sections": n}
           for r, k, x, s, n in jobs], open(work / f"{code}_jobs.json", "w"), ensure_ascii=False)
print(len(jobs), "jobs; ok:", sum(ok for _, ok in res)); print([n for n, ok in res if not ok])
