import configparser, gzip, hashlib, json, math, os, struct, sys, time
from collections import Counter
import requests
from PIL import Image, ImageDraw, ImageFont
import mapstyle

cfg = configparser.ConfigParser(); cfg.read("config.ini")
KEY = cfg.get("map", "carto_key")
OFFSET = cfg.getint("map", "vector_zoom_offset", fallback=0)
LAT = cfg.getfloat("position", "latitude"); LON = cfg.getfloat("position", "longitude")
RADIUS_M = cfg.getfloat("position", "radius_km") * 1000
W = cfg.getint("display", "width"); H = cfg.getint("display", "height")
STYLE = mapstyle.from_config(cfg)
# Mode apercu (webadmin) : "--preview DOSSIER" + un JSON sur l'entree standard {lat, lon, radius_km, width, height, style, presets}.
# Image reduite, tuiles gardees dans DOSSIER/tiles, un fichier par theme demande plus "current.png".
PREVIEW = "--preview" in sys.argv
if PREVIEW:
    OUT = sys.argv[sys.argv.index("--preview") + 1]
    REQ = json.load(sys.stdin)
    LAT = float(REQ.get("lat", LAT)); LON = float(REQ.get("lon", LON))
    RADIUS_M = float(REQ.get("radius_km", RADIUS_M / 1000)) * 1000
    W0, H0 = int(REQ.get("width", W)), int(REQ.get("height", H))
    W = min(W0, 640); H = max(1, round(W * H0 / W0))
    STYLE = mapstyle.merge(STYLE, REQ.get("style"))
    CREQ = REQ.get("cities") or {}
MPP = 2 * RADIUS_M / H
S, TILE = 2, 512
CITIES = cfg.getboolean("cities", "show", fallback=True)
KINDS = [k.strip() for k in cfg.get("cities", "kinds", fallback="city,town").split(",")]
MAXN = cfg.getint("cities", "max_labels", fallback=25)
FSIZE = cfg.getint("cities", "font_size", fallback=20)
if PREVIEW:
    CITIES = bool(CREQ.get("show", CITIES))
    if isinstance(CREQ.get("kinds"), list): KINDS = [str(k) for k in CREQ["kinds"]]
    MAXN = int(CREQ.get("max_labels", MAXN)); FSIZE = int(CREQ.get("font_size", FSIZE))
    FSIZE = max(9, round(FSIZE * W / W0))
places = []

def varint(b, i):
    r = s = 0
    while True:
        c = b[i]; i += 1
        r |= (c & 0x7F) << s; s += 7
        if c < 0x80: return r, i

def fields(b):
    i, n = 0, len(b)
    while i < n:
        k, i = varint(b, i); f, w = k >> 3, k & 7
        if w == 0: v, i = varint(b, i)
        elif w == 2:
            l, i = varint(b, i); v = b[i:i + l]; i += l
        elif w == 1: v = b[i:i + 8]; i += 8
        elif w == 5: v = b[i:i + 4]; i += 4
        else: raise ValueError("protobuf")
        yield f, w, v

def packed(b):
    out, i = [], 0
    while i < len(b):
        v, i = varint(b, i); out.append(v)
    return out

def zz(v): return (v >> 1) ^ -(v & 1)

def value(b):
    for f, w, v in fields(b):
        if f == 1: return v.decode("utf-8", "replace")
        if f == 2: return struct.unpack("<f", v)[0]
        if f == 3: return struct.unpack("<d", v)[0]
        if f in (4, 5): return v
        if f == 6: return zz(v)
        if f == 7: return bool(v)

def geometry(cmds):
    parts, cur, x, y, i = [], None, 0, 0, 0
    while i < len(cmds):
        c = cmds[i]; i += 1
        cmd, cnt = c & 7, c >> 3
        if cmd in (1, 2):
            for _ in range(cnt):
                x += zz(cmds[i]); y += zz(cmds[i + 1]); i += 2
                if cmd == 1: cur = [(x, y)]; parts.append(cur)
                else: cur.append((x, y))
    return parts

def decode(b):
    layers = {}
    for f, w, v in fields(b):
        if f != 3: continue
        name, keys, vals, feats, extent = "", [], [], [], 4096
        for f2, w2, v2 in fields(v):
            if f2 == 1: name = v2.decode()
            elif f2 == 2: feats.append(v2)
            elif f2 == 3: keys.append(v2.decode())
            elif f2 == 4: vals.append(value(v2))
            elif f2 == 5: extent = v2
        out = []
        for fb in feats:
            tags, gt, geo = [], 0, []
            for f3, w3, v3 in fields(fb):
                if f3 == 2: tags = packed(v3)
                elif f3 == 3: gt = v3
                elif f3 == 4: geo = packed(v3)
            props = {keys[tags[j]]: vals[tags[j + 1]] for j in range(0, len(tags) - 1, 2)}
            out.append((gt, props, geometry(geo)))
        layers[name] = (extent, out)
    return layers

cosl = math.cos(math.radians(LAT))
print("Connexion a CARTO...", flush=True)
tj = requests.get(f"https://tiles.basemaps.cartocdn.com/vector/carto.streets/v2/tiles.json?key={KEY}", timeout=30)
tj.raise_for_status(); tj = tj.json()
tmpl = tj["tiles"][0].replace("{s}", "a")
if "key=" not in tmpl:
    tmpl += ("&" if "?" in tmpl else "?") + f"key={KEY}"
Z = max(0, math.ceil(math.log2(156543.03 * cosl / (TILE / 256) / MPP))) + OFFSET
Z = min(Z, int(tj.get("maxzoom", 14)))
n = 2 ** Z
res = 156543.03 * cosl / (n * TILE / 256)

def world_px(la, lo):
    x = (lo + 180) / 360 * n * TILE
    s = math.sin(math.radians(la))
    return x, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n * TILE

cx, cy = world_px(LAT, LON)
cw, ch = W * MPP / res, H * MPP / res
x0, y0 = cx - cw / 2, cy - ch / 2
tx0, tx1 = int(x0 // TILE), int((x0 + cw) // TILE)
ty0, ty1 = int(y0 // TILE), int((y0 + ch) // TILE)

sess = requests.Session(); sess.headers["User-Agent"] = "flight-display-perso/0.1"
def get_tile(tx, ty):
    url = tmpl.replace("{z}", str(Z)).replace("{x}", str(tx % n)).replace("{y}", str(ty))
    cache = None
    if PREVIEW:  # les tuiles sont gardees : un nouvel apercu ne les retelecharge pas
        os.makedirs(os.path.join(OUT, "tiles"), exist_ok=True)
        cache = os.path.join(OUT, "tiles", hashlib.md5(url.split("key=")[0].encode()).hexdigest() + ".pbf")
        if os.path.exists(cache):
            with open(cache, "rb") as fh:
                return decode(fh.read()) if os.path.getsize(cache) else {}
    r = sess.get(url, timeout=30)
    if r.status_code == 404:
        if cache: open(cache, "wb").close()
        return {}
    r.raise_for_status()
    d = r.content
    if d[:2] == b"\x1f\x8b": d = gzip.decompress(d)
    if cache:
        with open(cache, "wb") as fh: fh.write(d)
    return decode(d)

if "--inspect" in sys.argv:
    L = get_tile(int(cx // TILE), int(cy // TILE))
    print("zoom", Z, "| gabarit URL :", tmpl)
    for name, (ext, feats) in L.items():
        c = Counter((p.get("kind") or p.get("pmap:kind"), p.get("kind_detail") or p.get("pmap:kind_detail"), gt) for gt, p, g in feats)
        print(f"\n[{name}] {len(feats)} objets, clés : {list(feats[0][1].keys())[:8] if feats else '-'}")
        for k, v in c.most_common(12): print("   ", k, v)
    raise SystemExit

def area(r): return sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r))) / 2

# Seules les categories cochees sont lues (les themes de l'apercu se dessinent a partir des memes objets).
KEEP = mapstyle.wanted(STYLE)
draw_list = {k: [] for k in mapstyle._ENABLE}
NT, done = (tx1 - tx0 + 1) * (ty1 - ty0 + 1), 0
print(f"Zoom {Z} : {NT} tuile(s) a lire, categories : {', '.join(sorted(KEEP)) or 'aucune'}", flush=True)
for tx in range(tx0, tx1 + 1):
    for ty in range(ty0, ty1 + 1):
        t_start = time.time()
        tile_layers = get_tile(tx, ty)
        done += 1
        print(f"Tuile {done}/{NT} recue en {time.time() - t_start:.1f} s, lecture...", flush=True)
        for name, (ext, feats) in tile_layers.items():
            def conv(r):
                return [((tx * TILE + px / ext * TILE - x0) / cw * W * S,
                         (ty * TILE + py / ext * TILE - y0) / ch * H * S) for px, py in r]
            for gt, p, parts in feats:
                kind = p.get("kind") or p.get("pmap:kind")
                kd = p.get("kind_detail") or p.get("pmap:kind_detail")
                if name == "places" and gt == 1 and CITIES and parts:
                    nm = p.get("name:fr") or p.get("name")
                    cat = kd or kind
                    if nm and cat in KINDS:
                        try: pop = float(p.get("population") or 0)
                        except Exception: pop = 0
                        px_, py_ = conv(parts[0])[0]
                        places.append((cat, -pop, str(nm), px_, py_))
                    continue
                target = mapstyle.classify(name, gt, kind, kd)
                if target is None or target not in KEEP: continue
                if gt == 3:
                    rings = [r for r in parts if len(r) >= 3]
                    pos = [area(r) > 0 for r in rings]
                    if rings and not any(pos): pos = [True if a else a for a in pos]; pos = [area(r) < 0 for r in rings]
                    draw_list[target].append([(conv(r), ex) for r, ex in zip(rings, pos)])
                else:
                    for line in parts:
                        if len(line) >= 2: draw_list[target].append([(conv(line), True)])

def load_font(size):
    for f in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try: return ImageFont.truetype(f, size)
        except Exception: pass
    return ImageFont.load_default()

def draw_labels(img, col):
    if not (CITIES and places): return 0
    d = ImageDraw.Draw(img)
    font = load_font(FSIZE * S)
    order = {"city": 0, "town": 1, "village": 2}
    seen, taken, count = set(), [], 0
    for cat, negpop, nm, px_, py_ in sorted(places, key=lambda t: (order.get(t[0], 3), t[1])):
        if count >= MAXN: break
        if nm in seen: continue
        if not (40 * S < px_ < (W - 40) * S and 40 * S < py_ < (H - 50) * S): continue
        l, t, r, b = d.textbbox((px_ + 9 * S, py_), nm, font=font, anchor="lm")
        rect = (l - 10 * S, t - 5 * S, r + 10 * S, b + 5 * S)
        if any(not (rect[2] < o[0] or rect[0] > o[2] or rect[3] < o[1] or rect[1] > o[3]) for o in taken):
            continue
        d.ellipse((px_ - 3 * S, py_ - 3 * S, px_ + 3 * S, py_ + 3 * S), fill=col)
        d.text((px_ + 9 * S, py_), nm, font=font, fill=col, anchor="lm")
        taken.append(rect); seen.add(nm); count += 1
    return count

def make(style):
    img, pal = mapstyle.render(draw_list, style, (W, H), S)
    return img, draw_labels(img, pal["label"])

if PREVIEW:
    os.makedirs(OUT, exist_ok=True)
    jobs = [("current", STYLE)] + [("preset_" + k, dict(STYLE, preset=k, colors={})) for k in REQ.get("presets", []) if k in mapstyle.PRESETS]
    for name, st in jobs:
        print("Dessin : " + name, flush=True)
        img, cnt = make(st)
        img.resize((W, H), Image.LANCZOS).save(os.path.join(OUT, name + ".png"), optimize=True)
    try:
        prev = json.load(open(os.path.join(OUT, "preview.json")))
    except (OSError, ValueError):
        prev = {}
    geo = {"lat": LAT, "lon": LON, "radius_km": RADIUS_M / 1000, "width": W0, "height": H0}
    thumbs = [n + ".png" for n, _ in jobs if n.startswith("preset_")]
    json.dump({"geo": geo, "w": W, "h": H, "zoom": Z, "files": ["current.png"],
               "thumbs_geo": geo if thumbs else prev.get("thumbs_geo"), "thumb_files": thumbs if thumbs else prev.get("thumb_files", [])},
              open(os.path.join(OUT, "preview.json"), "w"))
    print("OK apercu, zoom", Z, {k: len(v) for k, v in draw_list.items() if v})
    raise SystemExit

img, cnt = make(STYLE)
print(cnt, "noms de lieux dessinés")
img.resize((W, H), Image.LANCZOS).save("background.png", optimize=True)
json.dump({"lat": LAT, "lon": LON, "mpp": MPP, "w": W, "h": H, "zoom": Z}, open("map_meta.json", "w"))
print("OK, zoom", Z, {k: len(v) for k, v in draw_list.items() if v})
