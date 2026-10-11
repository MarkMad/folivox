"""Download the whole LibriVox catalog (id, title, language, genres, sections, length) into <work>/lv_books.json."""
import collections, json, sys, time, urllib.request
from pathlib import Path

UA = {"User-Agent": "folivox-voice-research/0.1 (open-source audiobook tool; 1 req/s)"}
work = Path(sys.argv[1]); work.mkdir(parents=True, exist_ok=True)
books, off = [], 0
while True:
    u = ("https://librivox.org/api/feed/audiobooks?format=json&limit=500&offset=%d"
         "&fields=id,title,language,genres,num_sections,totaltimesecs,url_librivox" % off)
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
    except Exception as e:
        print("end", off, e); break
    b = d.get("books", []); books += b; print(off, len(b), flush=True)
    if len(b) < 500: break
    off += 500; time.sleep(1)
json.dump(books, open(work / "lv_books.json", "w"), ensure_ascii=False)
print(len(books)); print(collections.Counter(b["language"] for b in books).most_common(25))
