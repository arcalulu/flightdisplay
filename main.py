import configparser, json, math, os, queue, sys, threading, time, hashlib
from array import array
import requests
import i18n

cfg = configparser.ConfigParser(); cfg.read("config.ini")
i18n.set_language(cfg.get("general", "language", fallback="fr"))  # langue du texte affiche a l'ecran
tr = i18n.tr

# Cercles de distance autour de la maison : le premier cercle peut aussi donner la distance d'alerte
RING_FIRST = max(0.1, cfg.getfloat("rings", "first_km", fallback=5))
RING_STEP = max(0.1, cfg.getfloat("rings", "step_km", fallback=5))
RING_N = max(0, min(30, cfg.getint("rings", "count", fallback=4))) if cfg.getboolean("rings", "show", fallback=True) else 0
ALERT_KM = RING_FIRST if (cfg.getboolean("alert", "link_first_ring", fallback=False) and RING_N > 0) else cfg.getfloat("alert", "radius_km", fallback=5)  # sans cercle affiche, la distance du premier cercle ne sert pas
ALERT_ON = ALERT_KM > 0
ALERT_SOUND = cfg.getboolean("alert", "sound", fallback=True)
ALERT_START_SOUND = cfg.getboolean("alert", "sound_on_start", fallback=False)
ALERT_VOL = max(0.0, min(1.0, cfg.getfloat("alert", "volume", fallback=0.6)))
ALERT_PULSE = max(0.5, cfg.getfloat("alert", "pulse_seconds", fallback=3))
ALERT_A_MIN = cfg.getint("alert", "alpha_min", fallback=10)
ALERT_A_MAX = cfg.getint("alert", "alpha_max", fallback=60)
ALERT_SIM = cfg.getboolean("alert", "simulate_on_start", fallback=False)
ALERT_SIM_SEC = cfg.getfloat("alert", "simulate_seconds", fallback=3)
ALERT_ALT_MIN = cfg.getint("alert", "min_altitude_ft", fallback=0)
ALERT_ALT_MAX = cfg.getint("alert", "max_altitude_ft", fallback=0)


def in_alert_alt(alt, was_in):
    lo = ALERT_ALT_MIN * (0.9 if was_in else 1.0)
    if alt < lo:
        return False
    return ALERT_ALT_MAX <= 0 or alt <= ALERT_ALT_MAX * (1.1 if was_in else 1.0)

if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
    os.environ.setdefault("SDL_RENDER_DRIVER", "opengles2")
    if not ALERT_SOUND:
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
if ALERT_SOUND and os.environ.get("SDL_AUDIODRIVER") == "dummy":
    print("ATTENTION : SDL_AUDIODRIVER=dummy, l'alerte sonore sera muette")

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
from FlightRadarAPI import FlightRadar24API
import sources

LAT = cfg.getfloat("position", "latitude"); LON = cfg.getfloat("position", "longitude")
RADIUS_M = cfg.getfloat("position", "radius_km") * 1000

POLL = cfg.getfloat("api", "poll_seconds", fallback=30)
DETAILS_PAUSE = cfg.getfloat("api", "details_pause_seconds", fallback=4)
STALE = cfg.getfloat("api", "stale_seconds", fallback=30)

# Sources des avions : Flightradar24, serveur tar1090 (https://github.com/wiedehopf/tar1090), services en ligne airplanes.live / adsb.lol / adsb.fi
# (voir sources.py pour les modes de combinaison)
SRC_ENABLED = [n for n in sources.NAMES if cfg.getboolean("sources", n + "_enabled", fallback=(n == "fr24"))]
TAR_URL = cfg.get("tar1090", "url", fallback="").strip()
TAR_EVERY = max(0.5, cfg.getfloat("tar1090", "interval_seconds", fallback=2))
if "tar1090" in SRC_ENABLED and not TAR_URL:
    print("ATTENTION : source tar1090 activee sans adresse (section [tar1090], url) : ignoree")
    SRC_ENABLED.remove("tar1090")
ONLINE_EVERY = max(1.0, cfg.getfloat("online", "interval_seconds", fallback=5))  # services en ligne : interrogation toutes les n secondes
if not SRC_ENABLED:
    print("ATTENTION : aucune source de donnees activee : aucun avion ne sera affiche")
ENRICH = cfg.getboolean("sources", "enrich", fallback=True)  # complete les avions hors FlightRadar24 via adsbdb.com
hub = sources.Hub(SRC_ENABLED, sources.parse_order(cfg.get("sources", "order", fallback=""), None),
                  cfg.get("sources", "mode", fallback="combine").strip().lower(), cfg.get("sources", "overlap", fallback="freshest").strip().lower())

FULLSCREEN = cfg.getboolean("display", "fullscreen", fallback=False)
try:  # sur un Raspberry Pi, l'affichage est toujours en plein ecran (le reglage n'est pas propose dans webadmin)
    with open("/proc/device-tree/model", "rb") as _f:
        FULLSCREEN = FULLSCREEN or b"Raspberry Pi" in _f.read()
except OSError:
    pass
FPS = cfg.getint("display", "fps", fallback=10)
ALT_UNIT = cfg.get("display", "altitude_unit", fallback="ft")
SPEED_UNIT = cfg.get("display", "speed_unit", fallback="kmh")
MAX_ALT = cfg.getint("display", "max_altitude_ft", fallback=0)

GROUND_ON = cfg.getboolean("ground", "show_list", fallback=True)
AIRPORT = cfg.get("ground", "airport_iata", fallback="").strip().upper()
G_MIN = cfg.getfloat("ground", "min_speed_kt", fallback=0)
G_MAX = cfg.getint("ground", "max_rows", fallback=8)
LANDED_ALT = cfg.getint("ground", "landed_alt_ft", fallback=2000)
LANDED_KEEP = cfg.getfloat("ground", "landed_keep_minutes", fallback=10) * 60

meta = json.load(open("map_meta.json"))
W, H, MPP = meta["w"], meta["h"], meta["mpp"]
COSL = math.cos(math.radians(LAT))

# Les tailles du config.ini sont exprimees pour un ecran 1080p de reference.
UI = H / 1080.0


def S(v):
    return max(1, int(round(v * UI)))


ICON = cfg.getfloat("display", "icon_scale", fallback=1.25) * UI
# Etiquettes affichees a cote de chaque avion (section [label]) : ordre, visibilite, taille, gras, italique
LABEL_FIELDS = ("model", "registration", "callsign", "airline", "route", "altitude", "speed")
_LBL_DEF = {"model": (True, "medium", False), "registration": (False, "medium", True),
            "callsign": (False, "medium", True), "airline": (True, "small", False),
            "route": (True, "small", False), "altitude": (True, "small", False), "speed": (True, "small", True)}
LBL = {}
for _k, (_show, _size, _same) in _LBL_DEF.items():
    _sz = cfg.get("label", _k + "_size", fallback=_size).strip().lower()
    LBL[_k] = dict(show=cfg.getboolean("label", "show_" + _k, fallback=_show),
                   bold=cfg.getboolean("label", _k + "_bold", fallback=False),
                   italic=cfg.getboolean("label", _k + "_italic", fallback=False),
                   size=_sz if _sz in ("small", "medium", "large") else _size,
                   same=cfg.getboolean("label", _k + "_same_line", fallback=_same))
_ord = [x.strip() for x in cfg.get("label", "order", fallback="").split(",") if x.strip() in LABEL_FIELDS]
LBL_ORDER = list(dict.fromkeys(_ord)) + [k for k in LABEL_FIELDS if k not in _ord]
PANEL_W = S(cfg.getint("panel", "width", fallback=480))
# Attributions exigees par les fournisseurs (OpenStreetMap : ODbL, CARTO : conditions du fond de carte) : ne pas retirer
CREDITS = "\u00a9 OpenStreetMap contributors  \u00b7  \u00a9 CARTO  \u00b7  Flightradar24"
ROTATE = cfg.getfloat("panel", "rotate_seconds", fallback=12)
# Contenu du panneau photo (section [panel_content]) : ordre, visibilite, taille, gras, italique, meme ligne
PANEL_FIELDS = ("model", "registration", "callsign", "airline", "route", "altitude", "speed", "credit")
_PNL_DEF = {"model": (True, "large", True, False), "registration": (True, "large", True, True), "callsign": (False, "large", True, True),
            "airline": (True, "medium", False, False), "route": (True, "medium", False, False),
            "altitude": (True, "medium", False, False), "speed": (True, "medium", False, True), "credit": (True, "small", False, False)}
PNL = {}
for _k, (_show, _size, _bold, _same) in _PNL_DEF.items():
    _sz = cfg.get("panel_content", _k + "_size", fallback=_size).strip().lower()
    _sec, _key = ("panel", "show_credit") if _k == "credit" else ("panel_content", "show_" + _k)  # show_credit existait deja dans [panel]
    PNL[_k] = dict(show=cfg.getboolean(_sec, _key, fallback=_show),
                   bold=cfg.getboolean("panel_content", _k + "_bold", fallback=_bold),
                   italic=cfg.getboolean("panel_content", _k + "_italic", fallback=False),
                   size=_sz if _sz in ("small", "medium", "large") else _size,
                   same=cfg.getboolean("panel_content", _k + "_same_line", fallback=_same))
_pord = [x.strip() for x in cfg.get("panel_content", "order", fallback="").split(",") if x.strip() in PANEL_FIELDS]
PNL_ORDER = list(dict.fromkeys(_pord)) + [k for k in PANEL_FIELDS if k not in _pord]
# Angles ou le panneau photo peut s'afficher, dans l'ordre : haut droite, haut gauche, bas droite, bas gauche
PANEL_CORNERS = [cfg.getboolean("panel", k, fallback=True) for k in
                 ("corner_top_right", "corner_top_left", "corner_bottom_right", "corner_bottom_left")]
PANEL_ALLOWED = [i for i in range(4) if PANEL_CORNERS[i]] or [0, 1, 2, 3]  # tous decoches : aucune restriction
G_W = S(cfg.getint("ground", "width", fallback=780))

if abs(meta["lat"] - LAT) > 1e-4 or abs(meta["lon"] - LON) > 1e-4:
    print("ATTENTION : la carte a ete generee pour d'autres coordonnees que config.ini ->"
          " relancez build_map_vector.py")

CACHE = "cache"; os.makedirs(CACHE, exist_ok=True)
DETAILS_FILE = os.path.join(CACHE, "details.json")
lock = threading.Lock()

RUNTIME_FILE = os.path.join(CACHE, "runtime.json")
# Images par seconde reellement affichees, lues par webadmin. En memoire (/dev/shm) pour ne pas user la carte SD.
FPS_FILE = "/dev/shm/flightdisplay-fps.json" if os.path.isdir("/dev/shm") else os.path.join(CACHE, "fps.json")


SCREEN_FLAG = cfg.get("screen", "flag", fallback="/run/flight-screen-off")  # cree par flight-screen off (veille de l'ecran)
_sl = {"t": 0.0, "v": False}


def screen_asleep():
    """Ecran en veille : le programme continue de tourner (historique, alertes) mais ne dessine plus. Teste au plus 2 fois par seconde."""
    now = time.time()
    if now - _sl["t"] >= 0.5:
        _sl["t"], _sl["v"] = now, os.path.exists(SCREEN_FLAG)
    return _sl["v"]


def fps_publish(fps, aircraft=0, ground=0, zone=0, paused=False):
    """Etat en direct lu par webadmin : images par seconde, avions en vol / au sol / dans la zone d'alerte."""
    try:
        tmp = FPS_FILE + f".{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"fps": round(fps, 1), "t": time.time(), "pid": os.getpid(), "aircraft": aircraft, "ground": ground, "zone": zone, "paused": bool(paused), "sources": hub.health(), "mode": hub.mode, "overlap": hub.overlap}, fh)
        os.replace(tmp, FPS_FILE)
    except OSError:
        pass


# Types d'avion vus au-dessus de la maison (compteur de passages), lus par webadmin (page Types d'avion).
TYPES_SEEN_FILE = os.path.join(CACHE, "types_seen.json")
types_seen = {}
_ts = {"dirty": False, "last": 0.0}
try:
    with open(TYPES_SEEN_FILE, encoding="utf-8") as _fh:
        types_seen = {str(k).upper(): v for k, v in json.load(_fh).items() if isinstance(v, dict)}
except (OSError, ValueError):
    pass


def types_note(code):
    if not code or code == "GRND":
        return
    e = types_seen.setdefault(code.upper(), {"n": 0, "t": 0})
    e["n"] += 1; e["t"] = int(time.time()); _ts["dirty"] = True


def types_detail(code, info):
    """Garde le dernier modele, la derniere immatriculation et la derniere photo vus pour ce type."""
    if not code or code == "GRND":
        return
    e = types_seen.setdefault(code.upper(), {"n": 0, "t": 0})
    for k, v in (("model", info.get("model")), ("reg", info.get("reg"))):
        if v and v != "?" and e.get(k) != v:
            e[k] = v; _ts["dirty"] = True
    p = info.get("photo_path")
    if p and e.get("photo") != os.path.basename(p):
        e["photo"] = os.path.basename(p); _ts["dirty"] = True


def types_flush():
    """Ecrit au plus toutes les 10 minutes (menage la carte SD)."""
    if not _ts["dirty"] or time.time() - _ts["last"] < 600:
        return
    _ts.update(dirty=False, last=time.time())
    try:
        tmp = TYPES_SEEN_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(types_seen, fh)
        os.replace(tmp, TYPES_SEEN_FILE)
    except OSError:
        pass


# Historique des avions vus (page "Avions vus" de webadmin) : un avion par vol, plafonne ; ecrit 30 s apres un nouvel avion
# (les mises a jour du dernier passage attendent le prochain nouvel avion : pas d'ecriture inutile sur la carte SD).
HISTORY_FILE = os.path.join(CACHE, "history.json")
HISTORY_MAX = 1000
history = {}
_hs = {"dirty": False, "last": 0.0}
try:
    with open(HISTORY_FILE, encoding="utf-8") as _fh:
        history = {str(e["id"]): e for e in json.load(_fh) if isinstance(e, dict) and e.get("id")}
except (OSError, ValueError, TypeError, KeyError):
    pass


alerted = {}  # vols qui ont declenche l'alerte (zone d'alerte) : id -> heure ; garde meme si l'avion n'est pas encore dans l'historique


def history_alert(ids):
    """Marque les vols qui viennent d'entrer dans la zone d'alerte (filtre « alerte » de la page Avions vus)."""
    now = int(time.time())
    with lock:
        for k in ids:
            alerted[k] = now
            e = history.get(k)
            if e is not None and not e.get("al"):
                e["al"] = now
                _hs["dirty"] = True
        if len(alerted) > 300:
            for k in sorted(alerted, key=alerted.get)[:len(alerted) - 300]:
                del alerted[k]


def history_note(f, info):
    """Ajoute (ou complete) l'avion dans l'historique. Appele avec le verrou."""
    now = int(time.time())
    e = history.get(f.id) or {"id": f.id, "t": now}
    if f.id in alerted and not e.get("al"):
        e["al"] = alerted[f.id]
    e["src"] = sorted(set(e.get("src") or ()) | set(f.sources or ()))  # sources qui ont vu l'avion (page Avions vus)
    if f.mlat:
        e["mlat"] = 1  # position deja calculee par MLAT au moins une fois
    if f.mil:
        e["mil"] = 1  # signale militaire par une source (indicateur dbFlags)
    e.update(l=now, cs=f.callsign or "", reg=info.get("reg") or "", code=f.aircraft_code or "", model=info.get("model") or "",
             airline=info.get("airline") or "", frm=info.get("origin") or "", to=info.get("dest") or "",
             fi=f.origin_airport_iata or "", ti=f.destination_airport_iata or "",
             photo=os.path.basename(info["photo_path"]) if info.get("photo_path") else e.get("photo", ""),
             url=info.get("photo_url") or e.get("url", ""), credit=info.get("credit") or e.get("credit", ""))
    history[f.id] = e
    if len(history) > HISTORY_MAX:
        for k in sorted(history, key=lambda k: history[k].get("t", 0))[:len(history) - HISTORY_MAX]:
            del history[k]
    _hs["dirty"] = True


def history_flush():
    if not _hs["dirty"] or time.time() - _hs["last"] < 30:
        return
    _hs.update(dirty=False, last=time.time())
    try:
        tmp = HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(sorted(history.values(), key=lambda e: e.get("t", 0)), fh)
        os.replace(tmp, HISTORY_FILE)
    except OSError:
        pass


rt = {"muted": False, "volume": ALERT_VOL, "seq": 0, "mtime": 0, "checked": 0.0}


def rt_refresh(first=False):
    now = time.time()
    if not first and now - rt["checked"] < 0.5:
        return
    rt["checked"] = now
    try:
        mt = os.stat(RUNTIME_FILE).st_mtime_ns
    except OSError:
        return
    if mt == rt["mtime"]:
        return
    rt["mtime"] = mt
    try:
        with open(RUNTIME_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        rt["muted"] = bool(d.get("muted", False))
        v = d.get("volume")
        rt["volume"] = max(0.0, min(1.0, float(v))) if isinstance(v, (int, float)) else ALERT_VOL
        seq = int(d.get("test_seq", 0))
    except Exception:
        return
    if first:
        rt["seq"] = seq
    elif seq != rt["seq"]:
        rt["seq"] = seq
        play_alert()

rt_refresh(True)

def toggle_mute():
    d = {}
    try:
        with open(RUNTIME_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        pass
    rt["muted"] = not rt["muted"]
    d["muted"] = rt["muted"]
    try:
        tmp = RUNTIME_FILE + f".{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        os.replace(tmp, RUNTIME_FILE)
        rt["mtime"] = os.stat(RUNTIME_FILE).st_mtime_ns
    except Exception:
        pass


def make_mute_icon(size):
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    k = size / 26.0
    c = (205, 210, 218)
    body = [(3, 10), (8, 10), (15, 4), (15, 22), (8, 16), (3, 16)]
    pygame.draw.polygon(surf, c, [(x * k, y * k) for x, y in body])
    pygame.draw.lines(surf, c, False, [(18 * k, 9 * k), (20.5 * k, 13 * k), (18 * k, 17 * k)], max(1, int(2 * k)))
    a, b = (4 * k, 3 * k), (23 * k, 23 * k)
    pygame.draw.line(surf, (10, 14, 20), a, b, max(3, int(5 * k)))
    pygame.draw.line(surf, (255, 70, 70), a, b, max(2, int(3 * k)))
    return surf

def make_chime(rate=22050):
    notes = [(659, 0.20), (880, 0.20), (1175, 0.50)]
    out = array("h")
    for f, dur in notes:
        n = int(rate * dur)
        for i in range(n):
            env = min(1.0, i / (0.008 * rate)) * (1.0 - i / n) ** 1.6
            v = math.sin(2 * math.pi * f * i / rate) + 0.3 * math.sin(4 * math.pi * f * i / rate)
            out.append(int(32767 * 0.5 * env * v / 1.3))
    return out.tobytes()


CHIME = make_chime() if ALERT_SOUND else b""
_snd_busy = [False]


def play_alert():
    if not ALERT_SOUND or rt["muted"] or _snd_busy[0]:
        return
    _snd_busy[0] = True

    def run():
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=2048, allowedchanges=0)
            snd = pygame.mixer.Sound(buffer=CHIME)
            snd.set_volume(rt["volume"])
            ch = snd.play()
            t0 = time.time()
            rt_refresh(True)
            while ch is not None and ch.get_busy() and time.time() - t0 < 5:
                time.sleep(0.05)
            time.sleep(0.3)
        except Exception as e:
            print("son indisponible :", type(e).__name__, str(e)[:120])
        finally:
            try: pygame.mixer.quit()
            except Exception: pass
            _snd_busy[0] = False

    threading.Thread(target=run, daemon=True).start()


def load_details():
    try:
        with open(DETAILS_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        lim = time.time() - 3 * 3600
        return {k: v for k, v in d.items() if v.get("t", 0) > lim}
    except Exception:
        return {}


states = {}
details = load_details()
last_save = [0]
queued = set(); q = queue.Queue()
status = {"msg": "", "t": 0, "high": 0, "err": False}
cool = {"until": 0}
api = FlightRadar24API()


def save_details():
    with lock:
        snap = dict(details)
    try:
        tmp = DETAILS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snap, fh)
        os.replace(tmp, DETAILS_FILE)
    except Exception:
        pass


def to_xy(la, lo):
    dx = (lo - LON) * 111320 * COSL
    dy = (la - LAT) * 110574
    return W / 2 + dx / MPP, H / 2 - dy / MPP


def dist_km(la, lo):
    return math.hypot((lo - LON) * 111.32 * COSL, (la - LAT) * 110.574)


def predict(s, now):
    d = s["speed"] * 0.514444 * max(0, min(now - s["t"], STALE))
    h = math.radians(s["heading"])
    return (s["lat"] + d * math.cos(h) / 110574,
            s["lon"] + d * math.sin(h) / (111320 * COSL))


def fmt_alt(ft):
    if ALT_UNIT == "m":
        return f"{round(ft * 0.3048 / 10) * 10} m"
    return f"{round(ft / 100) * 100:,}".replace(",", " ") + " ft"


def fmt_speed(kt):
    if SPEED_UNIT == "kt":
        return f"{round(kt)} kt"
    return f"{round(kt * 1.852)} km/h"

def label_lines(s, d):
    """Etiquette d'un avion : liste de lignes, chaque ligne = liste de (texte, champ). Vide : pas d'etiquette."""
    reg = (d["reg"] if d else "") or s.get("reg") or ""
    vals = dict(registration=reg, callsign=s["callsign"] or "", altitude=fmt_alt(s["alt"]), speed=fmt_speed(s["speed"]))
    if d:
        vals.update(model=d["model"], airline=d["airline"], route=route(d["origin"], d["dest"]))
    else:  # details pas encore charges : seul le code du type est connu
        vals.update(model=s["code"] or "")
    lines = []
    for k in LBL_ORDER:
        c, v = LBL[k], vals.get(k) or ""
        if not c["show"] or not v:
            continue
        if c["same"] and lines:
            lines[-1].append((v, k))
        else:
            lines.append([(v, k)])
    return lines


def fit_line(pieces, maxw):
    """Garde une ligne (liste de (texte, police, couleur)) dans maxw pixels : le texte qui depasse est coupe et termine par « … »."""
    out, used = [], 0
    for txt, fnt, col in pieces:
        w = fnt.size(txt)[0]
        if used + w <= maxw:
            out.append((txt, fnt, col))
            used += w
            continue
        ell, room = "\u2026", maxw - used
        if room > fnt.size(ell)[0]:
            lo, hi = 0, len(txt)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fnt.size(txt[:mid].rstrip() + ell)[0] <= room:
                    lo = mid
                else:
                    hi = mid - 1
            if lo > 0:
                out.append((txt[:lo].rstrip() + ell, fnt, col))
        break
    return out


def panel_lines(s, d):
    """Texte du panneau photo : liste de lignes, chaque ligne = liste de (texte, champ) (section [panel_content])."""
    reg = (d["reg"] if d else "") or s.get("reg") or ""
    vals = dict(registration=reg, callsign=s["callsign"] or "", altitude=tr("Altitude {0}", fmt_alt(s["alt"])),
                speed=tr("Vitesse {0}", fmt_speed(s["speed"])))
    if d:
        vals.update(model=d["model"], airline=d["airline"], route=route(d["origin"], d["dest"]),
                    credit=(tr("Photo personnelle") if d.get("perso") else "\u00a9 %s / JetPhotos" % str(d["credit"])[:44]) if d.get("credit") else "")
    else:  # details pas encore charges
        vals.update(model=s["code"] or "")
    lines = []
    for k in PNL_ORDER:
        c, v = PNL[k], vals.get(k) or ""
        if not c["show"] or not v:
            continue
        if c["same"] and lines:
            lines[-1].append((v, k))
        else:
            lines.append([(v, k)])
    return lines


def route(o, t):
    o = "" if o in (None, "?") else o
    t = "" if t in (None, "?") else t
    if not o and not t:
        return ""
    return f"{o or '?'}  \u2192  {t or '?'}"

def ground_row(s, d):
    o = d["origin"] if d else (s["o_iata"] or "")
    t = d["dest"] if d else (s["d_iata"] or "")
    o = "" if o == "?" else o
    t = "" if t == "?" else t
    if AIRPORT and s["d_iata"] == AIRPORT:
        where = tr("de {0}", o) if o else ""
    elif AIRPORT and s["o_iata"] == AIRPORT:
        where = tr("vers {0}", t) if t else ""
    else:
        where = route(o, t)
    model = d["model"] if d else (s["code"] or "")
    airline = d["airline"] if d else ""
    return (s["callsign"] or "?", airline, model, where)


def parse_details(f, d):
    ac = d.get("aircraft") or {}
    ap = d.get("airport") or {}

    def city(k, fallback):
        a = ap.get(k) or {}
        c = ((a.get("position") or {}).get("region") or {}).get("city")
        return c or a.get("name") or fallback or "?"

    imgs = ac.get("images") or {}
    lst = imgs.get("large") or imgs.get("medium") or []
    photo = lst[0] if lst else {}
    return {
        "model": (ac.get("model") or {}).get("text") or f.aircraft_code or "?",
        "airline": (d.get("airline") or {}).get("name") or f.airline_icao or "",
        "origin": city("origin", f.origin_airport_iata),
        "dest": city("destination", f.destination_airport_iata),
        "reg": ac.get("registration") or f.registration or "",
        "photo_url": photo.get("src"), "credit": photo.get("copyright", ""),
        "photo_path": None,
    }


def download_photo(url):
    path = os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + ".jpg")
    if not os.path.exists(path):
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        with open(path, "wb") as fh:
            fh.write(r.content)
    return path


def fr24_loop():
    """Source Flightradar24 : interroge l'API et publie le resultat dans le hub."""
    bounds = api.get_bounds_by_point(LAT, LON, W * MPP / 2 + 2000)
    fails = 0
    rate = False
    interval = POLL
    warned = False
    while True:
        wait = cool["until"] - time.time()
        if wait > 0:
            time.sleep(min(wait, 5)); continue
        try:
            flights = api.get_flights(bounds=bounds)
            now = time.time()
            tss = [getattr(f, "time", 0) or 0 for f in flights]
            ref = max(tss) if tss else now
            use_ts = abs(now - ref) < 120
            if not use_ts and not warned:
                print("ATTENTION : horloge du systeme decalee par rapport a FR24 (NTP ?)")
                warned = True
            conv = [sources.from_fr24(f, (getattr(f, "time", 0) or now) if use_ts else now) for f in flights if f.aircraft_code != "GRND"]
            hub.publish("fr24", conv, ttl=max(90, interval * 3))
            fails = 0
            rate = False
            interval = max(POLL, interval * 0.98)
        except Exception as e:
            fails += 1
            rate = "429" in str(e)
            print(time.strftime("%H:%M:%S"), "erreur get_flights :", type(e).__name__, str(e)[:200])
            if rate:
                interval = min(interval * 1.5, 120)
                cool["until"] = time.time() + 60
                print("intervalle porte a", round(interval), "s")
            hub.fail("fr24", str(e))
        time.sleep(interval if (not fails or rate) else min(interval * 2 ** fails, 300))


def tar_loop():
    """Source tar1090 (solution de wiedehopf, compatible dump1090 / readsb) : lit aircraft.json."""
    fails = 0
    while True:
        try:
            fl, total = sources.fetch_tar1090(TAR_URL, STALE)
            hub.publish("tar1090", fl, ttl=max(15, TAR_EVERY * 5), total=total)
            if fails:
                print(time.strftime("%H:%M:%S"), "tar1090 : connexion retablie")
            fails = 0
        except Exception as e:
            fails += 1
            if fails in (1, 10, 100):
                print(time.strftime("%H:%M:%S"), "erreur tar1090 :", type(e).__name__, str(e)[:200])
            hub.fail("tar1090", "%s: %s" % (type(e).__name__, e))
        time.sleep(TAR_EVERY if not fails else min(TAR_EVERY * 2 ** min(fails, 6), 60))


def online_loop(name):
    """Source en ligne (airplanes.live, adsb.lol, adsb.fi) : tous les avions autour de la position, au format ADSBexchange v2."""
    label = sources.LABELS[name]
    nm = min(sources.MAX_NM, math.ceil(math.hypot(W, H) * MPP / 2 / 1852 + 1))  # cercle qui couvre tout l'ecran
    url = sources.online_url(name, LAT, LON, nm)
    fails = 0
    while True:
        try:
            fl, total = sources.fetch_aircraft(url, name, STALE)
            hub.publish(name, fl, ttl=max(20, ONLINE_EVERY * 4), total=total)
            if fails:
                print(time.strftime("%H:%M:%S"), label, ": connexion retablie")
            fails = 0
        except Exception as e:
            fails += 1
            if fails in (1, 10, 100):
                print(time.strftime("%H:%M:%S"), "erreur", label, ":", type(e).__name__, str(e)[:200])
            hub.fail(name, "%s: %s" % (type(e).__name__, e))
        time.sleep(ONLINE_EVERY if not fails else min(ONLINE_EVERY * 2 ** min(fails, 5), 120))


adsb_wait = {}  # avion -> heure avant laquelle on ne redemande pas ses informations (echec de adsbdb.com)


def poll_loop():
    """Fusionne les sources (hub) et met a jour les avions affiches, a chaque nouveau resultat."""
    while True:
        hub.event.wait(5); hub.event.clear()
        now = time.time()
        if not SRC_ENABLED:  # aucune source cochee : aucun avion
            with lock:
                states.clear()
            status.update(msg=tr("aucune source activée"), t=now, err=True)
            continue
        if not hub.any_ok():
            h = hub.health()
            msg = next((v["err"] for v in h.values() if v.get("err")), "") or "aucune source ne repond"
            status.update(msg=tr("erreur réseau : {0}", msg[:60]), t=now, err=True)
            continue
        try:
            flights = hub.merged()
            seen = set(); high = 0
            with lock:
                for f in flights:
                    if f.aircraft_code == "GRND":
                        continue
                    px_, py_ = to_xy(f.latitude, f.longitude)
                    if not (-80 < px_ < W + 80 and -80 < py_ < H + 80):
                        continue
                    if MAX_ALT and not f.on_ground and (f.altitude or 0) > MAX_ALT:
                        high += 1
                        continue
                    ts = f.time or now
                    if not f.on_ground and now - ts > STALE:
                        continue
                    old = states.get(f.id)
                    if old is None:
                        types_note(f.aircraft_code)
                    seen.add(f.id)
                    if f.id in history:
                        history[f.id]["l"] = int(now)  # dernier passage (ecrit avec le prochain enregistrement)
                        if f.mlat and not history[f.id].get("mlat"):
                            history[f.id]["mlat"] = 1; _hs["dirty"] = True
                        if not set(f.sources) <= set(history[f.id].get("src") or ()):
                            history[f.id]["src"] = sorted(set(history[f.id].get("src") or ()) | set(f.sources)); _hs["dirty"] = True
                    elif f.id in details:  # details deja en memoire (redemarrage, cache de 3 h) : l'avion entre quand meme dans l'historique
                        history_note(f, details[f.id])
                    if not (old and ts <= old["t"]):
                        trail = old["trail"] if old else []
                        trail.append((f.latitude, f.longitude)); trail[:] = trail[-25:]
                        states[f.id] = dict(lat=f.latitude, lon=f.longitude, speed=f.ground_speed or 0,
                                            heading=f.heading or 0, alt=f.altitude or 0, t=ts,
                                            trail=trail, callsign=f.callsign or f.registration or "",
                                            code=f.aircraft_code or (old["code"] if old else ""), ground=bool(f.on_ground), reg=f.registration or "",
                                            o_iata=f.origin_airport_iata, d_iata=f.destination_airport_iata)
                    if f.id in details and personal_photo(f, details[f.id]):  # photo personnelle ajoutee ou retiree depuis webadmin
                        if f.id in history:
                            history[f.id]["photo"] = os.path.basename(details[f.id]["photo_path"] or ""); _hs["dirty"] = True
                    states[f.id]["mlat"] = bool(f.mlat)  # position MLAT : petit M a cote de l'icone
                    states[f.id]["mil"] = bool(f.mil)  # signale militaire par une source : icone militaire
                    if f.mil and f.id in history and not history[f.id].get("mil"):
                        history[f.id]["mil"] = 1; _hs["dirty"] = True
                    states[f.id]["src"] = tuple(f.sources)  # sources qui voient l'avion en ce moment (couleur de l'icone)
                    if (f.id not in details and f.id not in queued and now >= adsb_wait.get(f.id, 0)
                            and (f.fr is not None or ENRICH)
                            and not (f.on_ground and (f.ground_speed or 0) < G_MIN)):
                        queued.add(f.id); q.put(f)
                types_flush()
                history_flush()
                for k in list(states):
                    s = states[k]
                    if s.get("landed"):
                        if now - s["landed"] > LANDED_KEEP:
                            del states[k]
                        continue
                    if k in seen and (s["ground"] or now - s["t"] <= STALE):
                        continue
                    if (not s["ground"] and s["alt"] < LANDED_ALT
                            and (not AIRPORT or s["d_iata"] == AIRPORT)):
                        s.update(ground=True, speed=0, landed=now)
                    else:
                        del states[k]
                for k in list(details):
                    if k not in states and now - details[k].get("t", now) > 3600:
                        del details[k]
                for k in [k for k, v in adsb_wait.items() if v < now]:
                    del adsb_wait[k]
            status.update(msg="", t=now, high=high, err=False)
        except Exception as e:
            print(time.strftime("%H:%M:%S"), "erreur fusion des sources :", type(e).__name__, str(e)[:200])


def details_loop():
    while True:
        f = q.get()
        retry = False
        wait = cool["until"] - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            if f.fr is not None:
                info = parse_details(f.fr, api.get_flight_details(f.fr))
            else:  # avion vu seulement par une source locale : immatriculation, modele, compagnie, trajet via adsbdb.com
                x = sources.adsbdb_details(f.hex or f.id, f.callsign)
                info = {"model": x.get("model") or f.aircraft_code or "?", "airline": x.get("airline") or x.get("owner") or "",
                        "origin": x.get("origin") or "?", "dest": x.get("dest") or "?", "reg": x.get("reg") or f.registration or "",
                        "photo_url": x.get("photo_url"), "credit": "", "photo_path": None, "code": x.get("code") or ""}
                if not f.aircraft_code and info["code"]:
                    f.aircraft_code = info["code"]
                if not f.origin_airport_iata and x.get("oi"):
                    f.origin_airport_iata = x["oi"]
                if not f.destination_airport_iata and x.get("di"):
                    f.destination_airport_iata = x["di"]
            if not personal_photo(f, info) and info["photo_url"]:
                try: info["photo_path"] = download_photo(info["photo_url"])
                except Exception: pass
            info["t"] = time.time()
            with lock:
                details[f.id] = info
                st_ = states.get(f.id)
                if st_ is not None:  # un avion sans type connu prend celui des details
                    if not st_.get("code") and f.aircraft_code:
                        st_["code"] = f.aircraft_code
                        types_note(f.aircraft_code)
                    if not st_.get("reg") and info.get("reg"):
                        st_["reg"] = info["reg"]
                    if not st_.get("o_iata") and f.origin_airport_iata:
                        st_["o_iata"] = f.origin_airport_iata
                    if not st_.get("d_iata") and f.destination_airport_iata:
                        st_["d_iata"] = f.destination_airport_iata
                types_detail(f.aircraft_code, info)
                history_note(f, info)
            if time.time() - last_save[0] > 60:
                last_save[0] = time.time()
                save_details()
        except Exception as e:
            print(time.strftime("%H:%M:%S"), "erreur details :", type(e).__name__, str(e)[:200])
            if f.fr is None:
                adsb_wait[f.id] = time.time() + 120
                time.sleep(5)
            elif "429" in str(e):
                cool["until"] = time.time() + 120
                retry = True
                q.put(f)
            else:
                time.sleep(5)
        finally:
            if not retry:
                with lock:
                    queued.discard(f.id)
        time.sleep(DETAILS_PAUSE)


_redl = {}  # url de photo -> heure de la derniere tentative de retelechargement


def personal_photo(f, d):
    """Photo personnelle (dossier photos_perso, ajoutee depuis webadmin) : elle remplace celle de JetPhotos. d = details de l'avion.
    Renvoie True si la photo du panneau a change."""
    pp = perso_find(".", f.hex, d.get("reg") or f.registration)
    if pp:
        if d.get("photo_path") == pp:
            return False
        d.update(photo_path=pp, credit="Photo personnelle", perso=True)
        return True
    if d.get("perso"):  # la photo personnelle a ete retiree : retour a la photo d'origine
        d.update(photo_path=None, credit="", perso=False)
        redownload_photo(d)
        return True
    return False


def redownload_photo(d):
    """La photo en cache a ete effacee (webadmin, Stockage) : on la retelecharge discretement."""
    url = d.get("photo_url")
    if not url or time.time() - _redl.get(url, 0) < 600:
        return
    _redl[url] = time.time()

    def work():
        try:
            d["photo_path"] = download_photo(url)
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()


def clean_cache(days=3):
    lim = time.time() - days * 86400
    for n in os.listdir(CACHE):
        if n.endswith(".json") or n.endswith(".tmp"):
            continue
        p = os.path.join(CACHE, n)
        try:
            if os.path.getmtime(p) < lim:
                os.remove(p)
        except Exception:
            pass


from aircraft_types import SHAPES, BUILTIN, read_extra, perso_find, is_ulm
CATEGORY = dict(BUILTIN)
CATEGORY.update(read_extra("types_extra.txt"))
_unknown = set()


def category(code):
    cat = CATEGORY.get((code or "").upper())
    if cat is None:
        if code and code not in _unknown:
            _unknown.add(code); print("type inconnu (icone par defaut) :", code)
        return "narrow"
    return cat


def cfg_color(key, default, sec="display"):
    """Couleur #rrggbb d'une section de config.ini (reglee dans webadmin) ou la valeur par defaut."""
    v = cfg.get(sec, key, fallback="").strip()
    if len(v) == 7 and v[0] == "#":
        try:
            return tuple(int(v[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            pass
    return default


# avion affiche dans le panneau photo, autres avions dont le type est connu, avions de type inconnu
PLANE_PANEL = cfg_color("plane_color_panel", (255, 70, 70))
PLANE_KNOWN = cfg_color("plane_color_known", (255, 210, 80))
PLANE_UNKNOWN = cfg_color("plane_color_unknown", (255, 170, 90))
# couleur des avions selon la source qui les voit (option, voir sources.py) : Flightradar24 seul, tar1090 seul, plusieurs sources
COLOR_BY_SRC = cfg.getboolean("display", "color_by_source", fallback=False)
SRC_COLORS = {"fr24": cfg_color("plane_color_fr24", (255, 210, 80)), "tar1090": cfg_color("plane_color_tar1090", (90, 200, 255)),
              "airplaneslive": cfg_color("plane_color_airplaneslive", (255, 140, 60)), "adsblol": cfg_color("plane_color_adsblol", (255, 120, 190)),
              "adsbfi": cfg_color("plane_color_adsbfi", (180, 150, 255)), "multi": cfg_color("plane_color_multi", (120, 230, 140))}
COLOR_MIL = cfg.getboolean("display", "color_military", fallback=True)  # avions militaires : couleur propre
MIL_COLOR = cfg_color("plane_color_military", (143, 209, 90))
RING_COL = cfg_color("color", (45, 55, 70), "rings")
RING_W = max(1, min(8, cfg.getint("rings", "width", fallback=1)))
RING_LABELS = cfg.getboolean("rings", "show_labels", fallback=False)
RING_TXT = tuple(min(255, (c + 255) // 2) for c in RING_COL)  # texte plus clair que le trait, lisible sur la carte
print("cercles de distance : %d de %g km, ecart %g km, distances affichees : %s" % (RING_N, RING_FIRST, RING_STEP, "oui" if RING_LABELS else "non"))
TRAIL_PANEL = tuple((c + g) // 2 for c, g in zip(PLANE_PANEL, (85, 90, 90)))


def plane_color(s):
    """Couleur d'un avion (hors avion du panneau) : selon sa source si l'option est active, sinon selon que son type est connu."""
    if COLOR_MIL and (s.get("mil") or (not is_ulm(s.get("reg")) and CATEGORY.get((s.get("code") or "").upper()) == "mil")):
        return MIL_COLOR
    if COLOR_BY_SRC:
        src = s.get("src") or ()
        if len(src) >= 2:
            return SRC_COLORS["multi"]
        if src and src[0] in SRC_COLORS:
            return SRC_COLORS[src[0]]
    return PLANE_KNOWN if (is_ulm(s.get("reg")) or s.get("mil") or known_type(s["code"])) else PLANE_UNKNOWN


def known_type(code):
    """False si le type est absent de la liste des types (icone par defaut) : l'avion est alors dessine en orange clair."""
    return not code or code.upper() in CATEGORY


def draw_plane(surf, color, x, y, heading, code, reg="", mil=False):
    cat = "ulm" if is_ulm(reg) else category(code)  # immatriculation F-J... : toujours un ULM, quel que soit le type annonce
    if mil and cat not in ("ulm", "heli"):
        cat = "mil"  # avion signale militaire par une source (les helicopteres gardent leur forme)
    t = math.radians(heading); c, s = math.cos(t), math.sin(t)
    pts = [(x + (px * c - py * s) * ICON, y + (px * s + py * c) * ICON)
           for px, py in SHAPES[cat]]
    pygame.draw.polygon(surf, color, pts)
    if cat == "heli":
        pygame.draw.circle(surf, color, (int(x), int(y)), max(S(6), int(9 * ICON)), 1)


def main():
    T0 = time.time()
    if "fr24" in SRC_ENABLED:
        threading.Thread(target=fr24_loop, daemon=True).start()
    if "tar1090" in SRC_ENABLED:
        threading.Thread(target=tar_loop, daemon=True).start()
    for n in sources.ONLINE:
        if n in SRC_ENABLED:
            threading.Thread(target=online_loop, args=(n,), daemon=True).start()
    threading.Thread(target=poll_loop, daemon=True).start()
    threading.Thread(target=details_loop, daemon=True).start()
    if not cfg.getboolean("storage", "auto_clean", fallback=False):  # sinon webadmin nettoie selon le quota
        clean_cache()
    pygame.display.init()
    pygame.font.init()
    flags = (pygame.FULLSCREEN | pygame.SCALED) if FULLSCREEN else (pygame.SCALED | pygame.RESIZABLE)
    screen = pygame.display.set_mode((W, H), flags)
    pygame.display.set_caption("Flight display")
    pygame.mouse.set_visible(False)
    bg = pygame.image.load("background.png").convert()
    names = "dejavusans,arial,freesans"
    fp = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    fpb = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    def mk(size, bold=False):
        p = fpb if bold else fp
        if os.path.exists(p):
            return pygame.font.Font(p, size)
        return pygame.font.SysFont(names, size, bold=bold)

    f_big, f_mid, f_small = mk(S(26), True), mk(S(22)), mk(max(10, S(17)))
    f_mlat = mk(max(10, S(15)), True)  # lettre M des positions MLAT
    clock = pygame.time.Clock()
    label_cache, photo_cache, box_cache, smooth = {}, {}, {}, {}
    fps_n, fps_t0 = 0, time.time()
    cur_key, cur_t, corner = None, 0, 0
    RED = (255, 70, 70)
    lw = max(1, S(2))
    mute_icon = make_mute_icon(S(24))

    ar = max(2, int(ALERT_KM * 1000 / MPP)) if ALERT_ON else 2
    LEVELS = 12
    overlays = []
    if ALERT_ON:
        for i in range(LEVELS):
            surf = pygame.Surface((2 * ar, 2 * ar), pygame.SRCALPHA)
            a = int(ALERT_A_MIN + (ALERT_A_MAX - ALERT_A_MIN) * i / (LEVELS - 1))
            pygame.draw.circle(surf, (255, 40, 40, a), (ar, ar), ar)
            overlays.append(surf)
    zone_ids = set()

    SIZES = {"small": max(10, S(17)), "medium": S(22), "large": S(26)}
    WHITE, GREY = (255, 255, 255), (190, 200, 210)
    font_cache = {}

    def font_for(k):
        c = LBL[k]
        key = (c["size"], c["bold"], c["italic"])
        if key not in font_cache:
            f = mk(SIZES[c["size"]], c["bold"])
            f.set_italic(c["italic"])
            font_cache[key] = f
        return font_cache[key]

    pfont_cache = {}
    PCOL = {"model": (255, 255, 255), "registration": (255, 255, 255), "callsign": (255, 255, 255), "airline": (220, 225, 230),
            "route": (220, 225, 230), "altitude": (255, 150, 150), "speed": (255, 150, 150), "credit": (140, 150, 160)}

    def pfont_for(k):
        c = PNL[k]
        key = (c["size"], c["bold"], c["italic"])
        if key not in pfont_cache:
            f = mk(SIZES[c["size"]], c["bold"])
            f.set_italic(c["italic"])
            pfont_cache[key] = f
        return pfont_cache[key]

    def panel_pieces(ln):
        out = []
        for i, (txt, k) in enumerate(ln):
            if i:
                out.append(("  \u00b7  ", pfont_for(ln[i - 1][1]), (220, 225, 230)))
            out.append((txt, pfont_for(k), PCOL[k]))
        return out

    def label_surface(lines, hl=False):
        key = (tuple(tuple(l) for l in lines), hl)
        if key not in label_cache:
            if len(label_cache) > 300: label_cache.clear()
            rows = []
            for line in lines:
                parts, prev = [], None
                for txt, k in line:
                    if prev:
                        parts.append(font_for(prev).render("  \u00b7  ", True, GREY))
                    parts.append(font_for(k).render(txt, True, WHITE if k in ("model", "registration", "callsign") else GREY))
                    prev = k
                rows.append((parts, max(p.get_height() for p in parts), sum(p.get_width() for p in parts)))
            w = max(r[2] for r in rows) + S(14)
            h = sum(r[1] for r in rows) + S(10)
            surf = pygame.Surface((w, h), pygame.SRCALPHA)
            surf.fill((70, 14, 14, 190) if hl else (10, 14, 20, 170))
            y = S(5)
            for parts, rh, _ in rows:
                x = S(7)
                for p in parts:
                    surf.blit(p, (x, y + rh - p.get_height())); x += p.get_width()
                y += rh
            label_cache[key] = surf
        return label_cache[key]

    def get_photo(path):
        if path not in photo_cache:
            if len(photo_cache) > 20: photo_cache.clear()
            try:
                img = pygame.image.load(path).convert()
                h = int(PANEL_W * img.get_height() / img.get_width())
                photo_cache[path] = pygame.transform.smoothscale(img, (PANEL_W, h))
            except Exception:
                photo_cache[path] = None
        return photo_cache[path]

    def placeholder(text):
        key = ("ph", text)
        if key not in photo_cache:
            surf = pygame.Surface((PANEL_W, int(PANEL_W * 0.6)))
            surf.fill((28, 34, 42))
            t = f_mid.render(text, True, (140, 150, 160))
            surf.blit(t, t.get_rect(center=surf.get_rect().center))
            photo_cache[key] = surf
        return photo_cache[key]

    def panel_box(size):
        if size not in box_cache:
            b = pygame.Surface(size, pygame.SRCALPHA)
            b.fill((10, 14, 20, 215))
            box_cache[size] = b
        return box_cache[size]

    def ground_surface(rows, total):
        key = ("g", tuple(rows), total)
        if key not in label_cache:
            title = f_small.render(tr("AU SOL ({0})", total), True, (140, 150, 160))
            rh = f_mid.get_height() + S(4)
            h = title.get_height() + rh * len(rows) + S(18)
            surf = pygame.Surface((G_W, h), pygame.SRCALPHA)
            surf.fill((10, 14, 20, 200))
            pygame.draw.rect(surf, (60, 70, 85), surf.get_rect(), 1)
            surf.blit(title, (S(10), S(6)))
            y = title.get_height() + S(12)
            for cs, airline, model, where in rows:
                surf.blit(f_mid.render(cs[:9], True, (255, 255, 255)), (S(10), y))
                surf.blit(f_mid.render(airline[:18], True, (220, 225, 230)), (S(125), y))
                surf.blit(f_small.render(model[:20], True, (170, 180, 190)), (S(345), y + S(3)))
                surf.blit(f_mid.render(where[:20], True, (255, 210, 120)), (S(520), y))
                y += rh
            label_cache[key] = surf
        return label_cache[key]

    sim_until = 0
    if ALERT_ON and ALERT_SIM:
        sim_until = time.time() + ALERT_SIM_SEC
    if (ALERT_ON and ALERT_SIM) or ALERT_START_SOUND:
        play_alert()

    first = True
    running = True
    paused_pub = 0.0
    display_up = True
    while running:
        for e in (pygame.event.get() if display_up else ()):
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                running = False
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_m:
                toggle_mute()
        rt_refresh()
        now = time.time()
        if screen_asleep():
            # Ecran en veille : plus de dessin ni de rafraichissement (processeur, temperature). Le programme ferme aussi
            # l'affichage : tant qu'il le garde, la sortie video ne peut pas etre coupee. Le suivi continue :
            # l'historique se remplit (threads de fond) et les alertes sont marquees, sans son.
            if display_up:
                pygame.display.quit(); display_up = False
                print('ecran en veille : affichage ferme, suivi des avions maintenu', flush=True)
            with lock:
                air_now = [(k, dict(s)) for k, s in states.items() if not s["ground"]]
            zone_now = set()
            if ALERT_ON:
                for k, s in air_now:
                    dk = dist_km(s["lat"], s["lon"]); was = k in zone_ids
                    if (dk < ALERT_KM or (was and dk < ALERT_KM * 1.1)) and in_alert_alt(s["alt"], was):
                        zone_now.add(k)
                if zone_now - zone_ids:
                    history_alert(zone_now - zone_ids)
            zone_ids = zone_now
            if now - paused_pub >= 2.0:
                fps_publish(0, len(air_now), 0, len(zone_ids), paused=True); paused_pub = now
            fps_n, fps_t0 = 0, now
            clock.tick(2)
            continue
        paused_pub = 0.0
        if not display_up:  # reveil de l'ecran : l'affichage est rouvert
            try:
                pygame.display.init()
                screen = pygame.display.set_mode((W, H), flags)
                pygame.display.set_caption("Flight display")
                pygame.mouse.set_visible(False)
                display_up = True
                fps_n, fps_t0 = 0, time.time()
                print('ecran rallume : affichage rouvert', flush=True)
            except Exception as ex:
                print("impossible de rouvrir l'affichage :", ex, "-> redemarrage du programme", flush=True)
                os._exit(1)  # systemd relance le programme, qui demarre ecran allume
        if len(smooth) > 300: smooth.clear()
        screen.blit(bg, (0, 0))
        hx, hy = to_xy(LAT, LON)
        alert_visible = ALERT_ON and (bool(zone_ids) or now < sim_until)
        if alert_visible:
            p = (1 - math.cos(2 * math.pi * now / ALERT_PULSE)) / 2
            screen.blit(overlays[int(p * (LEVELS - 1) + 0.5)], (int(hx) - ar, int(hy) - ar))
        for i in range(RING_N):
            km = RING_FIRST + i * RING_STEP
            if km * 1000 > RADIUS_M:
                break
            rr = int(km * 1000 / MPP)
            pygame.draw.circle(screen, RING_COL, (int(hx), int(hy)), rr, RING_W)
            if RING_LABELS:
                tx = f_small.render("%g km" % round(km, 2), True, RING_TXT)
                ty = int(hy) - rr - tx.get_height() - 2
                if ty >= 0:  # au sommet du cercle ; sinon (cercle qui touche le haut de l'ecran) sur le cote droit
                    screen.blit(tx, (int(hx) - tx.get_width() // 2, ty))
                elif int(hx) + rr + 4 + tx.get_width() < W:
                    screen.blit(tx, (int(hx) + rr + 4, int(hy) - tx.get_height() // 2))
        if alert_visible:
            pygame.draw.circle(screen, RED, (int(hx), int(hy)), ar, lw)
        pygame.draw.circle(screen, (255, 200, 60), (int(hx), int(hy)), S(5))

        with lock:
            items = [(k, dict(s), details.get(k)) for k, s in states.items()]
        items.sort(key=lambda it: dist_km(it[1]["lat"], it[1]["lon"]))

        air = [it for it in items if not it[1]["ground"]]
        gnd = [it for it in items if it[1]["ground"] and it[1]["speed"] >= G_MIN]
        gnd.sort(key=lambda it: -it[1]["speed"])

        vis = []
        for k, s, d in air:
            la, lo = predict(s, now)
            pd = smooth.get(k)
            if pd is None or abs(pd[0] - la) > 0.05 or abs(pd[1] - lo) > 0.05:
                pd = (la, lo)
            else:
                pd = (pd[0] + (la - pd[0]) * 0.25, pd[1] + (lo - pd[1]) * 0.25)
            smooth[k] = pd
            x, y = to_xy(*pd)
            if -S(50) < x < W + S(50) and -S(50) < y < H + S(50):
                vis.append((k, s, d, x, y))

        dist_of = {}
        zone_now = set()
        if ALERT_ON:
            for k, s, d, x, y in vis:
                dk = math.hypot(x - hx, y - hy) * MPP / 1000.0
                dist_of[k] = dk
                was = k in zone_ids
                if (dk < ALERT_KM or (was and dk < ALERT_KM * 1.1)) and in_alert_alt(s["alt"], was):
                    zone_now.add(k)
            if zone_now - zone_ids:
                history_alert(zone_now - zone_ids)
                play_alert()
        zone_ids = zone_now

        placed = []
        ground_surf = ground_rect = None
        if GROUND_ON and gnd:
            rows = [ground_row(s, d) for _, s, d in gnd[:G_MAX]]
            ground_surf = ground_surface(rows, len(gnd))
            ground_rect = ground_surf.get_rect(bottomright=(W - S(30), H - S(40)))
            placed.append(ground_rect)

        zone_keys = [v[0] for v in vis if v[0] in zone_ids]
        if zone_keys:
            keys = zone_keys
        else:
            keys = [v[0] for v in vis if v[2] and v[2].get("photo_path")]
        if not keys:
            cur_key = None
        elif cur_key not in keys:
            cur_key, cur_t = keys[0], now
        elif len(keys) > 1 and now - cur_t > ROTATE:
            cur_key = keys[(keys.index(cur_key) + 1) % len(keys)]; cur_t = now

        panel = None
        if cur_key:
            _, s, d, _, _ = next(v for v in vis if v[0] == cur_key)
            ph = None
            if d and d.get("photo_path"):
                ph = get_photo(d["photo_path"])
                if ph is None:
                    d["photo_path"] = None
                    redownload_photo(d)
            if ph is None:
                ph = placeholder(tr("Photo indisponible") if d else tr("Chargement des détails..."))
            lines = [panel_pieces(ln) for ln in panel_lines(s, d)]
            if cur_key in zone_ids:
                lines.insert(0, [(tr("ALERTE  \u00b7  à {0} km de la maison", f"{dist_of.get(cur_key, 0):.1f}"), f_small, (255, 110, 110))])
            lines = [fit_line(ln, PANEL_W) for ln in lines]  # jamais plus large que le panneau
            lines = [(ln, max(f.get_height() for _, f, _ in ln)) for ln in lines if ln]
            text_h = sum(h + 2 for _, h in lines)
            M = S(30)
            pw, phh = PANEL_W + S(20), ph.get_height() + text_h + S(26)
            rects = [pygame.Rect(W - pw - M, M, pw, phh), pygame.Rect(M, M, pw, phh),
                     pygame.Rect(W - pw - M, H - phh - S(40), pw, phh), pygame.Rect(M, H - phh - S(40), pw, phh)]
            scores = [sum(1 for v in vis if r.inflate(S(90), S(90)).collidepoint(v[3], v[4])) for r in rects]
            if ground_rect:
                scores[2] = 999
            if corner not in PANEL_ALLOWED:
                corner = PANEL_ALLOWED[0]
            if scores[corner] > 0:
                corner = min(PANEL_ALLOWED, key=lambda i: (scores[i], i != corner))
            panel = (rects[corner], ph, lines)
            placed.append(rects[corner])

        for k, s, d, x, y in vis:
            hl = panel is not None and k == cur_key
            if len(s["trail"]) > 1:
                pts = [to_xy(*p) for p in s["trail"]] + [(x, y)]
                pygame.draw.lines(screen, TRAIL_PANEL if hl else (90, 130, 170), False, pts, lw)
            pc = PLANE_PANEL if hl else plane_color(s)
            draw_plane(screen, pc, x, y, s["heading"], s["code"], s.get("reg"), s.get("mil"))
            if s.get("mlat"):
                mt = f_mlat.render("M", True, pc)
                screen.blit(mt, (x - S(12) - mt.get_width(), y - S(12) - mt.get_height()))
            txt = label_lines(s, d)
            if not txt:
                continue
            ls = label_surface(txt, hl)
            w, h = ls.get_size()
            dx, up, dn = S(22), S(6), S(10)
            cands = [(x + dx, y - h - up), (x + dx, y + dn), (x - w - dx, y - h - up), (x - w - dx, y + dn)]
            pos = cands[0]
            for c in cands:
                r = pygame.Rect(c[0], c[1], w, h)
                if r.collidelist(placed) == -1 and screen.get_rect().contains(r):
                    pos = c; break
            placed.append(pygame.Rect(pos[0], pos[1], w, h))
            screen.blit(ls, pos)

        if panel:
            rect, ph, lines = panel
            screen.blit(panel_box(rect.size), rect.topleft)
            pygame.draw.rect(screen, RED, rect, lw)
            screen.blit(ph, (rect.x + S(10), rect.y + S(10)))
            ty = rect.y + S(10) + ph.get_height() + S(6)
            for pieces, lh in lines:
                x = rect.x + S(10)
                for txt, fnt, col in pieces:
                    r = fnt.render(txt, True, col)
                    screen.blit(r, (x, ty + lh - r.get_height()))
                    x += r.get_width()
                ty += lh + 2

        if ground_surf:
            screen.blit(ground_surf, ground_rect.topleft)

        age = now - status["t"]
        on_screen = sum(1 for v in vis if 0 <= v[3] <= W and 0 <= v[4] <= H)
        parts = [tr("{0} avion(s) en vol", on_screen)]
        if MAX_ALT:
            parts.append(tr("{0} au-dessus de {1}", status.get("high", 0), fmt_alt(MAX_ALT)))
        if gnd:
            parts.append(tr("{0} au sol", len(gnd)))
        msg = "  \u00b7  ".join(parts)
        if age > POLL * 4 and status["t"]:
            msg += "  " + tr("(données anciennes)")
        if status["err"]:
            msg += "  |  " + status["msg"]
        tx = S(12)
        if rt["muted"]:
            screen.blit(mute_icon, (S(12), H - S(30)))
            tx += S(32)
        cr = f_small.render(CREDITS, True, (140, 150, 160))
        cx = W - cr.get_width() - S(12)
        st = f_small.render(f"{msg}", True, (110, 120, 130))
        screen.blit(st, (tx, H - S(24)), area=pygame.Rect(0, 0, max(0, min(st.get_width(), cx - tx - S(16))), st.get_height()))
        screen.blit(cr, (cx, H - S(24)))
        pygame.display.flip()
        fps_n += 1
        t_fps = time.time()
        if t_fps - fps_t0 >= 2.0:
            fps_publish(fps_n / (t_fps - fps_t0), on_screen, len(gnd), len(zone_keys)); fps_n, fps_t0 = 0, t_fps
        if first:
            print("premiere image apres", round(time.time() - T0, 1), "s"); first = False
        clock.tick(FPS)
    save_details()
    pygame.quit()


if __name__ == "__main__":
    main()
