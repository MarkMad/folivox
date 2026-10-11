import json, subprocess, collections, concurrent.futures as cf
from pathlib import Path
sec=[x for x in json.load(open("lv_sec_a.json")) if x["lang"]=="Russian" and x["playtime"]>=60]
by=collections.defaultdict(list)
for x in sec: by[x["reader_id"]].append(x)
jobs=[]
for rid,v in by.items():
    v.sort(key=lambda x:x["playtime"]); seen=set(); pick=[]
    for x in v:
        if x["book"] in seen: continue
        seen.add(x["book"]); pick.append(x)
        if len(pick)==2: break
    for k,x in enumerate(pick):
        start=max(15,min(40,x["playtime"]-30)); jobs.append((rid,k,x,start))
out=Path("ru_raw"); out.mkdir(exist_ok=True)
def dl(j):
    rid,k,x,start=j; f=out/f"{rid}_{k}.mp3"
    if f.exists() and f.stat().st_size>50000: return f.name,True
    r=subprocess.run(["curl","-sL","--max-time","90","-r",f"{start*8000}-{(start+26)*8000}","-A","folivox-voice-research/0.1","-o",str(f),"-w","%{http_code}",x["mp3"]],capture_output=True,text=True)
    return f.name,r.stdout=="206"
with cf.ThreadPoolExecutor(3) as ex: res=list(ex.map(dl,jobs))
json.dump([{"file":f"{r}_{k}.mp3","reader_id":r,"reader":x["reader"],"book":x["title"],"book_url":x["url"],"src":x["src"],"section":x["sec"],"start":s,"mp3":x["mp3"]} for r,k,x,s in jobs],open("ru_jobs.json","w"),ensure_ascii=False)
print(len(jobs),"jobs; ok:",sum(ok for _,ok in res)); print([n for n,ok in res if not ok])
