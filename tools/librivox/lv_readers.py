import json, sys, time, urllib.request, collections
UA={"User-Agent":"folivox-voice-research/0.1 (open-source audiobook tool; 1 req/s)"}
langs=sys.argv[1].split(","); out=sys.argv[2]
books=[b for b in json.load(open("lv_books.json")) if b["language"] in langs]
print(len(books),"books",flush=True)
sec=[]
for i,b in enumerate(books):
    u=f"https://librivox.org/api/feed/audiobooks?format=json&extended=1&id={b['id']}"
    try: d=json.load(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=60))["books"][0]
    except Exception as e: print("skip",b["id"],e); continue
    for s in d["sections"]:
        for r in s["readers"]:
            sec.append({"book":b["id"],"title":d["title"],"lang":d["language"],"url":d["url_librivox"],"src":d["url_text_source"],
                        "reader_id":r["reader_id"],"reader":r["display_name"],"sec":s["section_number"],"playtime":int(s["playtime"] or 0),
                        "mp3":s["listen_url"],"sec_lang":s["language"]})
    time.sleep(1)
json.dump(sec,open(out,"w"),ensure_ascii=False)
by=collections.defaultdict(list)
for s in sec: by[(s["lang"],s["reader_id"],s["reader"])].append(s["playtime"])
for l in langs:
    rs=[(k,v) for k,v in by.items() if k[0]==l]
    print(l,"readers:",len(rs),"sections:",sum(len(v) for _,v in rs))
