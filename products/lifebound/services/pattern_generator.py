"""
pattern_generator.py — Generador fusionado v2+v5
Genera patterns_low.json, patterns_medium.json, patterns_high.json
Correr UNA vez: python services/pattern_generator.py
"""
import json, random, hashlib, logging
from typing import List, Dict
from datetime import datetime
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)

DATA_DIR     = Path(__file__).parent.parent / "data"
CONFIG_FILE  = DATA_DIR / "pattern_config.json"

RANGE_LIMITS = {"LOW":(15,30), "MEDIUM":(31,55), "HIGH":(56,80)}
PAGE_LIMITS  = {
    "LOW":    {"min":5,  "max":10, "max_slot4":2},
    "MEDIUM": {"min":10, "max":16, "max_slot4":999},
    "HIGH":   {"min":16, "max":22, "max_slot4":999},
}
FREQUENCIES = {
    "LOW":    {1:0.35, 2:0.35, 3:0.20, 4:0.10},
    "MEDIUM": {1:0.20, 2:0.30, 3:0.30, 4:0.20},
    "HIGH":   {1:0.05, 2:0.10, 3:0.15, 4:0.70},
}
TEXT_PAGES = [
    {"page":1,"template":"cover_page",    "slots":0,"color":None},
    {"page":2,"template":"cover_letter",  "slots":0,"color":None},
    {"page":3,"template":"identification","slots":0,"color":None},
]

def load_config() -> Dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)

def fix_start(seq):
    if not seq or seq[0] in (1,2): return seq
    for i in range(1,len(seq)):
        if seq[i] in (1,2):
            seq[0],seq[i]=seq[i],seq[0]; return seq
    seq[0]=2; return seq

def fix_no_consecutive_1(seq):
    seq=seq[:]
    for i in range(1,len(seq)):
        if seq[i]==1 and seq[i-1]==1:
            for j in range(i+1,len(seq)):
                if seq[j]!=1: seq[i],seq[j]=seq[j],seq[i]; break
            else: seq[i]=2
    return seq

def fix_no_1_to_4(seq):
    seq=seq[:]
    for i in range(1,len(seq)):
        if seq[i-1]==1 and seq[i]==4:
            for j in range(i+1,len(seq)):
                if seq[j] not in (1,4): seq[i],seq[j]=seq[j],seq[i]; break
            else: seq[i]=3
    return seq

def generate_slot_sequence(photo_count:int, range_type:str) -> List[int]:
    lim      = PAGE_LIMITS[range_type]
    freqs    = FREQUENCIES[range_type]
    ideal    = int(photo_count/2.7)
    target   = max(lim["min"], min(ideal, lim["max"]))
    max_s4   = lim["max_slot4"]
    pool     = []; rem=photo_count; s4=0

    for sz,fr in sorted(freqs.items(),key=lambda x:x[1],reverse=True):
        n = int(target*fr)
        if sz==4: n=min(n,max(0,max_s4-s4))
        n = min(n, rem//sz)
        if n>0:
            pool.extend([sz]*n); rem-=sz*n
            if sz==4: s4+=n

    while rem>0:
        if rem>=4 and s4<max_s4: pool.append(4); s4+=1; rem-=4
        elif rem>=3: pool.append(3); rem-=3
        elif rem>=2: pool.append(2); rem-=2
        else: pool.append(1); rem-=1

    groups=defaultdict(list)
    for s in pool: groups[s].append(s)
    for lst in groups.values(): random.shuffle(lst)
    seq=[]
    for k in sorted(groups): seq.extend(groups[k])
    seq=fix_start(seq)
    seq=fix_no_consecutive_1(seq)
    seq=fix_no_1_to_4(seq)
    return seq

def assign_templates(slot_seq:List[int], config:Dict) -> List[str]:
    counters={1:0,2:0,3:0,4:0}; result=[]
    for sz in slot_seq:
        opts=config["templates"][str(sz)]
        result.append(opts[counters[sz]%len(opts)])
        counters[sz]+=1
    return result

def generate_color_scheme(strategy:str, n:int, config:Dict) -> Dict:
    colors=config["colors"]
    if strategy=="monochrome":
        c=random.choice(colors)
        return {"strategy":"monochrome","base_colors":[c],"page_colors":[c]*n}
    if strategy=="dual":
        c1,c2=random.sample(colors,2)
        return {"strategy":"dual","base_colors":[c1,c2],
                "page_colors":[c1 if i%2==0 else c2 for i in range(n)]}
    if strategy=="gradient":
        g=random.choice(config["gradients"])
        pc=[g[0] if (i/max(n-1,1))<0.33 else g[1] if (i/max(n-1,1))<0.66 else g[2] for i in range(n)]
        return {"strategy":"gradient","base_colors":g,"page_colors":pc}
    if strategy=="palette":
        p=random.choice(config["palettes"])
        return {"strategy":"palette","base_colors":p,
                "page_colors":[random.choice(p) for _ in range(n)]}
    return {"strategy":"random","base_colors":colors,
            "page_colors":[random.choice(colors) for _ in range(n)]}

def make_checksum(slots,templates,colors) -> str:
    data=json.dumps({"s":slots,"t":templates,"c":colors},sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()

def generate_pattern(photo_count:int, range_type:str, strategy:str, config:Dict) -> Dict:
    slots     = generate_slot_sequence(photo_count, range_type)
    templates = assign_templates(slots, config)
    scheme    = generate_color_scheme(strategy, len(slots), config)
    chk       = make_checksum(slots, templates, scheme["page_colors"])
    pages     = []
    for i,(sz,tid) in enumerate(zip(slots,templates)):
        pages.append({"page":i+4,"template":tid,"slots":sz,
                      "color":scheme["page_colors"][i]})
    return {
        "pattern_id":     f"{range_type.lower()}_{photo_count}_{chk[:8]}",
        "range_type":     range_type,
        "photo_count":    photo_count,
        "total_pages":    3+len(pages),
        "photo_pages":    len(pages),
        "slot_sequence":  slots,
        "template_sequence": templates,
        "color_scheme":   scheme,
        "checksum":       chk,
        "sequence":       TEXT_PAGES + pages,
    }

def generate_all(patterns_per_count:int=30):
    config = load_config()
    strategies = config["color_strategies"]
    for range_type,(lo,hi) in RANGE_LIMITS.items():
        all_patterns=[]
        for pc in range(lo,hi+1):
            seen=set(); batch=[]
            attempts=0
            while len(batch)<patterns_per_count and attempts<patterns_per_count*20:
                attempts+=1
                strat=strategies[len(batch)%len(strategies)]
                p=generate_pattern(pc,range_type,strat,config)
                if p["checksum"] not in seen:
                    seen.add(p["checksum"]); batch.append(p)
            all_patterns.extend(batch)
            print(f"  {pc} fotos: {len(batch)} patrones",end="\r")
        out={
            "version":"v2.0","generated_at":datetime.now().isoformat(),
            "range_type":range_type,"total_patterns":len(all_patterns),
            "patterns":all_patterns
        }
        fname=DATA_DIR/f"patterns_{range_type.lower()}.json"
        with open(fname,"w") as f: json.dump(out,f,indent=2)
        print(f"✅ {fname.name}: {len(all_patterns):,} patrones")

if __name__=="__main__":
    print("Generando patrones...")
    generate_all()
    print("Listo.")
