import json, subprocess, re, sys
from pathlib import Path
import numpy as np, soundfile as sf, librosa, mlx_whisper
from folivox.qa import canonical
S=Path(sys.argv[1]); raw=S/"ru_raw"; out=Path.home()/"Desktop/folivox_voices/librivox_ru"; out.mkdir(parents=True,exist_ok=True)
jobs=json.load(open(S/"ru_jobs.json")); rows=[]
for j in jobs:
    f=raw/j["file"]
    if not f.exists() or f.stat().st_size<50000: continue
    wav=S/"tmp.wav"
    subprocess.run(["ffmpeg","-v","error","-y","-i",str(f),"-ac","1","-ar","24000",str(wav)],check=True)
    a,sr=sf.read(wav,dtype="float32")
    r=mlx_whisper.transcribe(a if False else str(wav),path_or_hf_repo="mlx-community/whisper-large-v3-turbo",language="ru",condition_on_previous_text=False,verbose=None)
    seg=r["segments"]; pick=None
    for i in range(1,len(seg)):
        if not re.search(r"[.!?…»]\W*$",seg[i-1]["text"].strip()): continue
        if not seg[i]["text"].strip()[:1].isupper(): continue
        for k in range(i,len(seg)):
            d=seg[k]["end"]-seg[i]["start"]
            if d>15: break
            if d>=8 and re.search(r"[.!?…]\W*$",seg[k]["text"].strip()):
                pick=(i,k); break
        if pick: break
    if not pick: rows.append({**j,"ok":False}); print(j["file"],"no window"); continue
    i,k=pick; t0=max(0,seg[i]["start"]-0.1); t1=min(len(a)/sr,seg[k]["end"]+0.15)
    clip=a[int(t0*sr):int(t1*sr)]; text=" ".join(s["text"].strip() for s in seg[i:k+1])
    clip=clip*(0.9/max(1e-6,np.abs(clip).max()))
    name=f"{re.sub(r'[^A-Za-z0-9]+','_',j['reader']).strip('_') or 'reader'}_{j['reader_id']}_{j['file'].split('_')[1][0]}"
    sf.write(out/f"{name}.wav",clip,sr,subtype="PCM_16"); (out/f"{name}.txt").write_text(text,encoding="utf-8")
    f0,_,_=librosa.pyin(librosa.resample(clip,orig_sr=sr,target_sr=16000),fmin=60,fmax=500,sr=16000)
    dur=len(clip)/sr; cps=len(canonical(text))/dur
    rows.append({**j,"ok":True,"name":name,"dur":round(dur,1),"f0":int(np.nanmedian(f0)),"cps":round(cps,1),"text":text})
    print(name,round(dur,1),int(np.nanmedian(f0)),"Hz",round(cps,1),"cps",text[:70],flush=True)
json.dump(rows,open(S/"ru_clips.json","w"),ensure_ascii=False,indent=1)
