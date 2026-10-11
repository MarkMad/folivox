"""lv_readers.py <work> <Language> <max_books> [--poetry]
Per book (extended=1): sections with reader, playtime and mp3 url -> <work>/sec_<Language>.json.
Books are filtered by the BOOK's language; poetry/drama/multi-voice genres are skipped unless --poetry.
If there are more candidate books than max_books, a seeded random sample is taken."""
import collections, json, random, sys, time, urllib.request
from pathlib import Path

UA = {"User-Agent": "folivox-voice-research/0.1 (open-source audiobook tool; 1 req/s)"}
work, lang, cap = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
poetry = "--poetry" in sys.argv
SKIP = ("poetry", "poem", "drama", "play", "dramatic", "multi", "song", "sermon", "religion", "bible")
def ok(b):
    if b["language"] != lang or int(b["num_sections"] or 0) < 2: return False
    g = " ".join(x["name"].lower() for x in b.get("genres") or [])
    return poetry or not any(s in g for s in SKIP)
books = [b for b in json.load(open(work / "lv_books.json")) if ok(b)]
random.Random(1).shuffle(books); books = books[:cap]
print(len(books), "books", flush=True)
sec = []
for b in books:
    u = f"https://librivox.org/api/feed/audiobooks?format=json&extended=1&id={b['id']}"
    try: d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))["books"][0]
    except Exception as e: print("skip", b["id"], e); time.sleep(1); continue
    genres = [x["name"] for x in b.get("genres") or []]
    for s in d["sections"]:
        for r in s["readers"]:
            sec.append({"book": b["id"], "title": d["title"], "lang": d["language"], "url": d["url_librivox"],
                        "src": d["url_text_source"], "genres": genres, "reader_id": r["reader_id"],
                        "reader": r["display_name"], "sec": s["section_number"],
                        "playtime": int(s["playtime"] or 0), "mp3": s["listen_url"]})
    time.sleep(1)
json.dump(sec, open(work / f"sec_{lang}.json", "w"), ensure_ascii=False)
print(lang, "readers:", len({s["reader_id"] for s in sec}), "sections:", len(sec))
