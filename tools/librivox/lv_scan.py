import json, time, urllib.request, collections
books=[]; off=0
while True:
    u=f"https://librivox.org/api/feed/audiobooks?format=json&limit=500&offset={off}&fields=id,title,language,num_sections,totaltimesecs,url_librivox"
    try: d=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"folivox-voice-research/0.1 (open-source audiobook tool; 1 req/s)"}),timeout=60))
    except Exception as e: print("end",off,e); break
    b=d.get("books",[]); books+=b; print(off,len(b),flush=True)
    if len(b)<500: break
    off+=500; time.sleep(1)
json.dump(books,open("lv_books.json","w"),ensure_ascii=False)
c=collections.Counter(b["language"] for b in books)
print(len(books)); print(c.most_common(25))
