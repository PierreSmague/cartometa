"""Spike: source file per (country, family), verdict per tag, compact data for the examples page."""
import json, glob, sys, collections, os, base64, re
KEEP = ("car_year", "copyright", "antenna", "bl", "blur", "exposed", "snow", "smallcam")
G_DROP, G_KEEP, CAPT = 0.10, 0.20, 0.35
out_dir, dates_path, dest = sys.argv[1], sys.argv[2], sys.argv[3]
dates = json.load(open(dates_path, encoding="utf-8"))
files = [json.load(open(f, encoding="utf-8")) for f in sorted(glob.glob(out_dir + "/*.json"))]
CARY = re.compile(r"^.+?\s+(20\d{2}|\d{2})(\s*\((A|NA|A\s*\+\s*NA)\))?$")
cands = collections.defaultdict(list)
for d in files:
    for c in d["countries"]:
        share = c["points"] / d["points"]
        primary = share >= 0.50
        if not primary and c["points"] < 1000: continue
        cands[c["country"]].append(dict(primary=primary, date=dates.get(d["file"], ""), file=d["file"], c=c, pts=c["points"]))

def verdict(r):
    if r["n"] < 30: return "écarté", "moins de 30 points"
    kids = [k for k in r["children"] if CARY.match(k)]
    if r["family"] not in ("copyright", "car_year") and kids and r["covered"] >= 0.95:
        return "écarté", "couvert par des tags plus fins"
    if r["zones"] == 0: return "écarté", "aucune zone de 30 points"
    if r["capture"] < CAPT: return "écarté", "points surtout isolés"
    if r["G10"] < G_DROP: return "écarté", "non discriminant"
    if r["G10"] < G_KEEP: return "arbitrage", "discriminance limite"
    return "retenu", ""

def pack(states):
    b = bytearray((len(states) + 3) // 4)
    for i, v in enumerate(states): b[i >> 2] |= v << ((i & 3) * 2)
    return base64.b64encode(bytes(b)).decode()

grids, rows = {}, []
for cc, lst in sorted(cands.items()):
    prim = sorted((x for x in lst if x["primary"]), key=lambda x: (x["date"], x["pts"]), reverse=True)
    multi = sorted((x for x in lst if not x["primary"]), key=lambda x: x["pts"], reverse=True)
    pool = prim + (multi if not prim else [])
    for fam in KEEP:
        for rank, src in enumerate(pool):
            c = src["c"]
            if not any(r["family"] == fam and r["n"] >= 30 for r in c["rows"]): continue
            gkey = f"{cc}|{src['file']}"
            g = c["grid"]
            if gkey not in grids:
                grids[gkey] = dict(cc=cc, file=src["file"].split("/")[-1], date=src["date"][:10], pts=c["points"], W=g["W"], H=g["H"],
                                   s=round(g["s"], 1), R=round(0.10 * g["D"]), link=round(g["link"], 1), cov=g["cov"],
                                   primary=src["primary"], latest=(rank == 0))
            covpos = {f: i for i, f in enumerate(g["cov"])}
            for r in c["rows"]:
                if r["family"] != fam: continue
                v, why = verdict(r)
                m = None
                if r["zones"]:
                    st = [0] * len(g["cov"])
                    pr = r.get("pr") or []
                    for i, pv in enumerate(pr):
                        if pv <= 12: st[i] = 2
                    for f in r["fcells"]: st[covpos[f]] = 1
                    m = pack(st)
                rep = r.get("rep") or {}
                rows.append(dict(g=gkey, cc=cc, t=r["tag"], fam=fam, n=r["n"], sh=round(r["share"], 4), z=r["zones"],
                                 cap=round(r["capture"], 3), A=round(r["A"], 3),
                                 g3=None if r.get("G3") is None else round(r["G3"], 3),
                                 g10=None if r.get("G10") is None else round(r["G10"], 3),
                                 v=v, why=why, m=m, pano=rep.get("pano"), lat=rep.get("lat"), lng=rep.get("lng"), hd=rep.get("heading")))
            break
json.dump(dict(grids=grids, rows=rows), open(dest, "w"), ensure_ascii=False, separators=(",", ":"))
C = collections.Counter
print("countries:", len(cands), "| rows:", len(rows), "| data bytes:", os.path.getsize(dest))
print("verdicts:", C((r["v"], r["why"]) for r in rows).most_common())
print("by family (non écarté):", C((r["fam"], r["v"]) for r in rows if r["v"] != "écarté").most_common())
load = C(r["cc"] for r in rows if r["v"] == "retenu"); arb = C(r["cc"] for r in rows if r["v"] == "arbitrage")
print("per country retenu+arbitrage:", ", ".join(f"{k}:{load[k]}+{arb[k]}" for k in sorted(set(load) | set(arb))))
print("sources:"); 
for k, g in grids.items(): print("  ", g["cc"], g["file"], g["date"], "primary" if g["primary"] else "MULTI", "" if g["latest"] else "(older file, for a family the latest lacks)", sorted({r["fam"] for r in rows if r["g"] == k}))
if "-v" in sys.argv:
    for why in ("discriminance limite", "non discriminant", "couvert par des tags plus fins"):
        print("\n" + why.upper())
        for r in sorted((r for r in rows if r["why"] == why), key=lambda r: (r["cc"], -r["n"])):
            print(f"  {r['cc']} {r['t'][:30]:30s} n={r['n']:6d} share={r['sh']:4.0%} A={r['A']:4.0%} capt={r['cap']:4.0%} G3={(r['g3'] or 0):4.0%} G10={(r['g10'] or 0):4.0%}")
    print("\nPOINTS SURTOUT ISOLÉS:", C(r["cc"] for r in rows if r["why"] == "points surtout isolés").most_common())
    import statistics
    caps = [r["cap"] for r in rows if r["z"]]
    print("capture quantiles among zoned:", [round(q, 2) for q in statistics.quantiles(caps, n=10)])
