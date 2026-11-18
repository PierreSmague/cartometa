"""Spike: per (file, country, tag) zone analysis of carmeta JSONs.

For each tag: zones of >= 30 points where the tag is locally present, and the
share of the country's coverage that lies farther than R from any such zone
("eliminated share"). Throwaway analysis code, not product code.
"""
import json, math, os, re, sys, zipfile, collections
import numpy as np
import shapely
from shapely.geometry import shape, MultiPoint
from shapely.strtree import STRtree

KM_LAT, KM_LON = 110.574, 111.320
MIN_ZONE_PTS = 30
TAU = float(os.environ.get("TAU", "0.10"))      # min local share for presence
RHO = float(os.environ.get("RHO", "0.06"))      # R = RHO * D
MIN_COUNTRY_PTS = 300

KOPPEN = re.compile(r"^(Af|Am|Aw|As|BW[hk]|BS[hk]|C[sfw][abc]|D[sfw][abcd]|ET|EF)$")
WEATHER = {"clear", "some clouds", "overcast"}
LAENDER = {"bayern", "niedersachsen", "nordrhein-westfalen", "baden-württemberg", "brandenburg",
           "mecklenburg-vorpommern", "rheinland-pfalz", "sachsen-anhalt", "sachsen", "schleswig-holstein",
           "thüringen", "hessen", "berlin", "saarland", "hamburg", "bremen"}
CAR_YEAR = re.compile(r"^(?P<desc>.+?)\s+(?P<year>20\d{2}|\d{2})(?:\s*\((?P<ant>A|NA|A\s*\+\s*NA)\))?$")


def family(tag, iso):
    t = tag.strip()
    low = t.lower()
    if re.search(r"[─—═]{3,}", t): return "sep"
    if re.fullmatch(r"©\s?\d{4}", t): return "copyright"
    if re.fullmatch(r"(19|20)\d{2}", t): return "year"
    if re.fullmatch(r"([1-9]|1[0-2])", t): return "month"
    if re.fullmatch(r"\d\d-\d\d", t): return "yearmonth"
    if low in WEATHER: return "weather"
    if KOPPEN.match(t): return "koppen"
    if re.fullmatch(r"P\d|Part \d", t): return "parts"
    if low in ("bl", "no bl", "brakelight"): return "bl" if not low.startswith("no ") else "neg"
    if re.fullmatch(r"[A-Z]{2}", t) and t in iso: return "country"
    if low in LAENDER: return "admin"
    if low in ("gen 4", "normal gen 4"): return "camera_gen"
    if low == "smallcam": return "smallcam"
    if low == "antenna": return "antenna"
    if low in ("no antenna", "no front blur", "no snow"): return "neg"
    if low in ("front blur", "new blur"): return "blur"
    if low in ("exposed", "exposed back"): return "exposed"
    if low == "snow": return "snow"
    if CAR_YEAR.match(t): return "car_year"
    if low in ("black", "white", "grey", "gray", "blue", "red"): return "color"
    return "unknown"


def load(path):
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = [n for n in z.namelist() if not n.startswith("__MACOSX")][0]
            return json.loads(z.read(name).decode("utf-8"))
    return json.load(open(path, encoding="utf-8"))


class Countries:
    def __init__(self, ne_path):
        data = json.load(open(ne_path, encoding="utf-8"))
        self.codes, self.geoms = [], []
        for f in data["features"]:
            p = f["properties"]
            code = p.get("ISO_A2_EH") or p.get("ISO_A2")
            if not code or code == "-99": continue
            g = shape(f["geometry"])
            if not g.is_valid: g = g.buffer(0)
            shapely.prepare(g)
            self.codes.append(code.upper()); self.geoms.append(g)
        self.bounds = np.array([g.bounds for g in self.geoms])
        self.tree = STRtree(self.geoms)
        self.iso = set(self.codes)

    def assign(self, lat, lng):
        out = np.full(len(lat), -1, dtype=np.int32)
        x0, y0, x1, y1 = lng.min(), lat.min(), lng.max(), lat.max()
        b = self.bounds
        cand = np.nonzero((b[:, 0] <= x1) & (b[:, 2] >= x0) & (b[:, 1] <= y1) & (b[:, 3] >= y0))[0]
        for ci in cand:
            todo = np.nonzero(out < 0)[0]
            if not len(todo): break
            bx0, by0, bx1, by1 = b[ci]
            sub = todo[(lng[todo] >= bx0) & (lng[todo] <= bx1) & (lat[todo] >= by0) & (lat[todo] <= by1)]
            if not len(sub): continue
            inside = shapely.contains_xy(self.geoms[ci], lng[sub], lat[sub])
            out[sub[inside]] = ci
        left = np.nonzero(out < 0)[0]
        if len(left):
            pts = shapely.points(lng[left], lat[left])
            near = self.tree.query_nearest(pts, max_distance=0.09)
            seen = set()
            for i, j in zip(near[0], near[1]):
                if i not in seen:
                    seen.add(i); out[left[i]] = j
        return out


def box3(a):
    p = np.pad(a, 1)
    H, W = a.shape
    return sum(p[1 + dy:1 + dy + H, 1 + dx:1 + dx + W] for dy in (-1, 0, 1) for dx in (-1, 0, 1))


def disc_sum(a, r):
    H, W = a.shape
    k = int(math.floor(r))
    if k <= 0: return a.copy()
    p = np.pad(a, k)
    out = np.zeros_like(a)
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            if dx * dx + dy * dy <= r * r:
                out += p[k + dy:k + dy + H, k + dx:k + dx + W]
    return out


def dilate_disc(mask, r):
    H, W = mask.shape
    k = int(math.floor(r))
    if k <= 0: return mask.copy()
    p = np.pad(mask, k)
    out = np.zeros_like(mask)
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            if dx * dx + dy * dy <= r * r:
                out |= p[k + dy:k + dy + H, k + dx:k + dx + W]
    return out


LINK_K = float(os.environ.get("LINK_K", "3"))
NB = [dy * 1000003 + dx for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)]
OFFS = [(dy, dx) for dy in range(-2, 3) for dx in range(-2, 3) if (dy, dx) != (0, 0)]


def components(mask):
    """Connected components of True cells, a one-cell gap is bridged."""
    cells = set(zip(*(a.tolist() for a in np.nonzero(mask))))
    comps = []
    while cells:
        start = cells.pop()
        comp, stack = [start], [start]
        while stack:
            y, x = stack.pop()
            for dy, dx in OFFS:
                c = (y + dy, x + dx)
                if c in cells:
                    cells.remove(c); comp.append(c); stack.append(c)
        comps.append(comp)
    return comps


def analyse_country(code, idx, lat, lng, combo_of, combos, tagnames, pts, iso):
    lat_c, lng_c = lat[idx], lng[idx].copy()
    if lng_c.max() - lng_c.min() > 300:  # antimeridian
        lng_c[lng_c < 0] += 360
    lat0 = float(lat_c.mean())
    kx = KM_LON * math.cos(math.radians(lat0))
    x, y = lng_c * kx, lat_c * KM_LAT
    hull = MultiPoint(np.column_stack([x, y])[:: max(1, len(x) // 20000)]).convex_hull
    D = math.sqrt(max(hull.area, 1.0))
    s = min(25.0, max(1.5, D / 60))
    R = RHO * D
    x0, y0 = x.min(), y.min()
    ix, iy = ((x - x0) // s).astype(np.int64), ((y - y0) // s).astype(np.int64)
    W, H = int(ix.max()) + 1, int(iy.max()) + 1
    flat = iy * W + ix
    tot = np.bincount(flat, minlength=H * W).reshape(H, W).astype(np.float64)
    cov = tot > 0
    ncov = int(cov.sum())
    N = len(idx)
    # sampling spacing: median nearest-neighbour distance on a sample
    rng = np.random.default_rng(0)
    smp = rng.choice(N, size=min(300, N), replace=False)
    nn = []
    for a0 in range(0, len(smp), 10):
        ch = smp[a0:a0 + 10]
        d2 = (x[None, :] - x[ch, None]) ** 2 + (y[None, :] - y[ch, None]) ** 2
        d2[np.arange(len(ch)), ch] = np.inf
        nn.extend(np.sqrt(d2.min(axis=1)).tolist())
    delta = float(np.median(nn))
    link = max(LINK_K * delta, 1.0)
    totR = {gk: disc_sum(tot, rho * D / s) for gk, rho in (("G3", 0.03), ("G6", 0.06), ("G10", 0.10))}

    # tag membership through combos
    cid = combo_of[idx]
    ucid, inv = np.unique(cid, return_inverse=True)
    tag_combos = collections.defaultdict(list)   # tag id -> local combo indexes
    for k, c in enumerate(ucid):
        for t in combos[c]:
            tag_combos[t].append(k)
    ccount = np.bincount(inv, minlength=len(ucid))
    ntag = {t: int(ccount[ks].sum()) for t, ks in tag_combos.items()}

    rows = []
    for t, ks in sorted(tag_combos.items(), key=lambda kv: -ntag[kv[0]]):
        name = tagnames[t]
        fam = family(name, iso)
        n = ntag[t]
        row = dict(tag=name, family=fam, n=n, share=n / N)
        if fam == "sep":
            continue
        # granularity: finer tags implying this one
        kset = set(ks)
        children, covered = [], np.zeros(len(ucid), dtype=bool)
        for u, us in tag_combos.items():
            if u == t or ntag[u] >= n or ntag[u] < 5: continue
            fu = family(tagnames[u], iso)
            if fu == "sep": continue
            inter = sum(int(ccount[k]) for k in us if k in kset)
            if inter >= 0.98 * ntag[u]:
                children.append(tagnames[u])
                covered[[k for k in us if k in kset]] = True
        row["children"] = children
        row["covered"] = float(ccount[covered].sum() / n) if children else 0.0
        if n < MIN_ZONE_PTS:
            row.update(zones=0, capture=0.0, A=0.0, G3=None, G6=None, G10=None, fcells=[])
            rows.append(row); continue
        member = np.isin(inv, ks)
        mi = np.nonzero(member)[0]
        # zones: chains of >= 30 points, linked through a hash grid of size LINK
        kxc = np.floor(x[mi] / link).astype(np.int64); kyc = np.floor(y[mi] / link).astype(np.int64)
        key = (kyc - kyc.min()) * 1000003 + (kxc - kxc.min())
        ukey, kinv, kcnt = np.unique(key, return_inverse=True, return_counts=True)
        cellpos = {int(k): i for i, k in enumerate(ukey)}
        label = np.full(len(ukey), -1, dtype=np.int64)
        comp_pts = []
        for start in range(len(ukey)):
            if label[start] >= 0: continue
            lab = len(comp_pts); label[start] = lab; stack = [start]; total = 0
            while stack:
                i = stack.pop(); total += int(kcnt[i]); k = int(ukey[i])
                for dk in NB:
                    j = cellpos.get(k + dk)
                    if j is not None and label[j] < 0:
                        label[j] = lab; stack.append(j)
            comp_pts.append(total)
        comp_pts = np.array(comp_pts)
        good = comp_pts >= MIN_ZONE_PTS
        inzone = good[label[kinv]]
        zi = mi[inzone]
        row["zones"] = int(good.sum())
        row["zone_pts"] = sorted((int(v) for v in comp_pts[good]), reverse=True)[:8]
        row["capture"] = float(inzone.sum() / n)
        cnt = np.bincount(flat[zi], minlength=H * W).reshape(H, W).astype(np.float64)
        F = cnt > 0
        row["A"] = float(F.sum() / ncov)
        if row["zones"]:
            for gk, rho in (("G3", 0.03), ("G6", 0.06), ("G10", 0.10)):
                r = rho * D / s
                tR = totR[gk]
                known = cov & (tR >= MIN_ZONE_PTS)
                pR = np.where(known, disc_sum(cnt, r) / np.where(tR > 0, tR, 1), 0.0)
                tsum = pR[known].sum()
                kl = 0.0
                if tsum > 0:
                    q = pR[known] / tsum
                    nz = q > 0
                    kl = float((q[nz] * np.log2(q[nz] * known.sum())).sum())
                row[gk] = 1 - 2 ** (-kl)
                if gk == "G10":
                    mx = pR[cov].max() if cov.any() else 0
                    row["pr"] = (np.round(255 * pR[cov] / mx).astype(int).tolist() if mx > 0 else [])
            row["fcells"] = np.nonzero(F.ravel())[0].tolist()
            big = int(np.argmax(np.where(good, comp_pts, -1)))
            bi = mi[label[kinv] == big]
            cxm, cym = x[bi].mean(), y[bi].mean()
            p = pts[int(idx[bi[int(np.argmin((x[bi] - cxm) ** 2 + (y[bi] - cym) ** 2))]])]
            row["rep"] = dict(lat=round(p["lat"], 5), lng=round(p["lng"], 5), pano=p.get("panoId"),
                              heading=round(p.get("heading") or 0, 1))
        else:
            row.update(G3=None, G6=None, G10=None, fcells=[])
        rows.append(row)
    grid = dict(delta=delta, link=link, lat0=lat0, kx=kx, x0=float(x0), y0=float(y0), s=s, W=W, H=H, D=D, R=R,
                cov=np.nonzero(cov.ravel())[0].tolist())
    return dict(country=code, points=N, cells=ncov, grid=grid, rows=rows)


def main():
    ne, out_dir = sys.argv[1], sys.argv[2]
    countries = Countries(ne)
    summary = []
    for path in sys.argv[3:]:
        rel = os.path.relpath(path, os.environ.get("ROOT", "/"))
        try:
            d = load(path)
        except Exception as e:
            print("ERR", rel, repr(e)); continue
        pts = [p for p in d["customCoordinates"] if p.get("lat") is not None and abs(p["lat"]) < 84]
        lat = np.array([p["lat"] for p in pts]); lng = np.array([p["lng"] for p in pts])
        tagid, tagnames, comboid, combos = {}, [], {}, []
        combo_of = np.zeros(len(pts), dtype=np.int32)
        for i, p in enumerate(pts):
            tags = (p.get("extra") or {}).get("tags") or []
            key = tuple(sorted(tagid.setdefault(str(t), len(tagid)) for t in tags))
            if key not in comboid:
                comboid[key] = len(combos); combos.append(key)
            combo_of[i] = comboid[key]
        tagnames = [None] * len(tagid)
        for t, i in tagid.items(): tagnames[i] = t
        cidx = countries.assign(lat, lng)
        order = (d.get("extra") or {}).get("tags") or {}
        res = dict(file=rel, name=d.get("name"), points=len(pts), unplaced=int((cidx < 0).sum()),
                   order={t: m.get("order") for t, m in order.items()},
                   color={t: m.get("color") for t, m in order.items() if m.get("color")}, countries=[], skipped={})
        for ci in np.unique(cidx[cidx >= 0]):
            idx = np.nonzero(cidx == ci)[0]
            code = countries.codes[ci]
            if len(idx) < MIN_COUNTRY_PTS:
                res["skipped"][code] = int(len(idx)); continue
            res["countries"].append(analyse_country(code, idx, lat, lng, combo_of, combos, tagnames, pts, countries.iso))
        fn = re.sub(r"[^A-Za-z0-9]+", "_", rel)[:80] + ".json"
        json.dump(res, open(os.path.join(out_dir, fn), "w"), ensure_ascii=False)
        print(f"{rel}: {len(pts)} pts, unplaced {res['unplaced']}, countries "
              + ", ".join(f"{c['country']}:{c['points']}" for c in res["countries"]) + f" skipped {res['skipped']}", flush=True)


if __name__ == "__main__":
    main()
