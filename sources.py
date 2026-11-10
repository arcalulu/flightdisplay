"""Sources de donnees des avions (Flightradar24, serveur tar1090 : solution de wiedehopf, compatible dump1090 / readsb) et fusion de leurs resultats.

Module partage par main.py (programme d'affichage) et webadmin.py (test d'un serveur tar1090).
Chaque source produit des objets Flight normalises (memes champs que ceux de FlightRadar24). Un meme avion est reconnu d'une
source a l'autre par son adresse ICAO 24 bits (« hex »).

Modes de combinaison (section [sources], cle mode) :
  combine  : toutes les sources actives sont cumulees ; un avion vu par plusieurs sources n'apparait qu'une fois
             (cle overlap : freshest = la position la plus recente gagne, priority = la source la mieux classee gagne).
  primary  : seule la source principale (la 1re de la liste qui repond) donne les avions et les positions ; les autres
             ne servent qu'a completer les informations manquantes (immatriculation, type, trajet...).
  failover : une seule source a la fois, la 1re de la liste qui repond ; la suivante ne prend le relais qu'en cas de panne.
"""
import copy
import json
import threading
import time
import urllib.error
import urllib.request

NAMES = ("fr24", "tar1090")
COMPLETE = ("registration", "aircraft_code", "callsign", "origin_airport_iata", "destination_airport_iata", "airline_icao")
UA = {"User-Agent": "flightdisplay"}


def http_json(url, timeout=6):
    """GET d'un JSON (bibliotheque standard : webadmin n'a pas besoin de « requests »). Renvoie (code HTTP, contenu ou None)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 404, None
        raise


class Flight:
    """Avion normalise, quelle que soit la source."""

    def __init__(self, **kw):
        self.id = ""
        self.hex = ""
        self.source = ""
        self.sources = []
        self.latitude = 0.0
        self.longitude = 0.0
        self.ground_speed = 0
        self.heading = 0
        self.altitude = 0
        self.on_ground = False
        self.callsign = ""
        self.registration = ""
        self.aircraft_code = ""
        self.origin_airport_iata = ""
        self.destination_airport_iata = ""
        self.airline_icao = ""
        self.time = 0.0
        self.fr = None  # objet FlightRadar24 d'origine (necessaire pour ses details)
        self.__dict__.update(kw)


def from_fr24(f, ts):
    """Convertit un vol FlightRadar24. ts : heure de la position (secondes Unix)."""
    hx = (getattr(f, "icao_24bit", "") or "").strip().lower()
    return Flight(id=hx or "fr24:" + str(f.id), hex=hx, source="fr24", sources=["fr24"], latitude=f.latitude, longitude=f.longitude,
                  ground_speed=f.ground_speed or 0, heading=f.heading or 0, altitude=f.altitude or 0, on_ground=bool(f.on_ground),
                  callsign=f.callsign or f.registration or "", registration=f.registration or "", aircraft_code=f.aircraft_code or "",
                  origin_airport_iata=f.origin_airport_iata or "", destination_airport_iata=f.destination_airport_iata or "",
                  airline_icao=f.airline_icao or "", time=ts, fr=f)


def fetch_tar1090(url, max_age=30.0, timeout=6):
    """Lit un aircraft.json (tar1090, dump1090-fa, readsb, tar1090). Renvoie (liste de Flight, nombre total d'avions du fichier)."""
    _, d = http_json(url, timeout)
    items = d.get("aircraft") if isinstance(d, dict) else None
    if not isinstance(items, list):
        raise ValueError("fichier aircraft.json inattendu (pas de liste « aircraft »)")
    now = time.time()
    out = []
    for a in items:
        try:
            hx = str(a.get("hex", "")).strip().lower().lstrip("~")
            if not hx or a.get("lat") is None or a.get("lon") is None:
                continue
            if str(a.get("category", "")).upper().startswith("C"):  # vehicules de piste, obstacles
                continue
            age = float(a.get("seen_pos", a.get("seen", 0)) or 0)
            ab = a.get("alt_baro")
            ground = ab == "ground"
            if ground:
                alt = 0
            else:
                alt = ab if isinstance(ab, (int, float)) else (a.get("alt_geom") if isinstance(a.get("alt_geom"), (int, float)) else 0)
            if not ground and age > max_age:
                continue
            hd = a.get("track", a.get("true_heading", 0))
            out.append(Flight(id=hx, hex=hx, source="tar1090", sources=["tar1090"], latitude=float(a["lat"]), longitude=float(a["lon"]),
                              ground_speed=int(round(float(a.get("gs") or 0))), heading=float(hd or 0), altitude=int(alt), on_ground=ground,
                              callsign=str(a.get("flight", "") or "").strip(), registration=str(a.get("r", "") or "").strip(),
                              aircraft_code=str(a.get("t", "") or "").strip().upper(), time=now - age))
        except (TypeError, ValueError):
            continue
    return out, len(items)


def merge(snaps, order, mode, overlap):
    """snaps : {source: [Flight]} (sources valides seulement). Renvoie la liste fusionnee, un Flight par avion."""
    live = [n for n in order if n in snaps]
    if not live:
        return []
    if mode == "failover":
        return list(snaps[live[0]])
    rank = {n: i for i, n in enumerate(live)}
    groups = {}
    for n in live:
        for f in snaps[n]:
            groups.setdefault(f.id, []).append(f)
    main = {f.id for f in snaps[live[0]]} if mode == "primary" else None
    out = []
    for k, cands in groups.items():
        if main is not None and k not in main:
            continue
        cands.sort(key=lambda f: rank[f.source])
        if mode == "combine" and overlap != "priority":
            best = max(cands, key=lambda f: (f.time, -rank[f.source]))
        else:
            best = cands[0]
        if len(cands) == 1:
            out.append(best)
            continue
        m = copy.copy(best)
        m.sources = [f.source for f in cands]
        for attr in COMPLETE:
            if not getattr(m, attr):
                for f in cands:
                    if getattr(f, attr):
                        setattr(m, attr, getattr(f, attr)); break
        for f in cands:
            if f.fr is not None:
                m.fr = f.fr; break
        out.append(m)
    return out


class Hub:
    """Dernier resultat de chaque source + fusion. Les sources publient depuis leur propre thread."""

    def __init__(self, enabled, order, mode, overlap):
        self.enabled = [n for n in order if n in enabled]
        self.order = self.enabled
        self.mode = mode if mode in ("combine", "primary", "failover") else "combine"
        self.overlap = overlap if overlap in ("freshest", "priority") else "freshest"
        self.lock = threading.Lock()
        self.snap = {}  # nom -> dict(t, flights, ok, err, total, ttl)
        self.event = threading.Event()

    def publish(self, name, flights, ttl, total=None):
        with self.lock:
            self.snap[name] = dict(t=time.time(), flights=flights, ok=True, err="", total=len(flights) if total is None else total, ttl=ttl)
        self.event.set()

    def fail(self, name, msg):
        with self.lock:
            s = self.snap.setdefault(name, dict(t=0, flights=[], ok=False, err="", total=0, ttl=0))
            s["ok"], s["err"] = False, str(msg)[:120]
            s["fail_t"] = time.time()

    def valid(self, name, now=None):
        s = self.snap.get(name)
        now = now or time.time()
        return bool(s and s["ok"] and s["t"] and now - s["t"] <= s["ttl"])

    def merged(self):
        now = time.time()
        with self.lock:
            snaps = {n: self.snap[n]["flights"] for n in self.order if n in self.snap and self.valid(n, now)}
            # une source en erreur dont le dernier resultat est encore recent reste utilisable (coupure brève)
            for n in self.order:
                s = self.snap.get(n)
                if n not in snaps and s and s["t"] and now - s["t"] <= s["ttl"] and mode_keeps_stale(self.mode):
                    snaps[n] = s["flights"]
        return merge(snaps, self.order, self.mode, self.overlap)

    def any_ok(self):
        return any(self.valid(n) for n in self.order)

    def health(self):
        now = time.time()
        out = {}
        with self.lock:
            for n in self.order:
                s = self.snap.get(n)
                if not s:
                    out[n] = dict(ok=None, n=0, age=None, err="")
                else:
                    out[n] = dict(ok=self.valid(n, now), n=s["total"], age=round(now - s["t"], 1) if s["t"] else None, err=s["err"])
        return out


def mode_keeps_stale(mode):
    return mode != "failover"  # en secours, une source en erreur est abandonnee tout de suite au profit de la suivante


def parse_order(text, enabled_flags):
    """« fr24,tar1090 » -> liste ordonnee complete (les sources oubliees sont ajoutees a la fin)."""
    seen = []
    for n in [x.strip().lower() for x in (text or "").split(",")]:
        if n in NAMES and n not in seen:
            seen.append(n)
    for n in NAMES:
        if n not in seen:
            seen.append(n)
    return seen


def adsbdb_details(hx, callsign, timeout=8):
    """Complete un avion qui ne vient pas de FlightRadar24 (immatriculation, modele, compagnie, trajet, photo) via adsbdb.com (gratuit, sans cle)."""
    info = {}
    code, d = http_json("https://api.adsbdb.com/v0/aircraft/" + hx, timeout)
    if code == 200 and isinstance(d, dict):
        ac = (d.get("response") or {}).get("aircraft") if isinstance(d.get("response"), dict) else None
        if isinstance(ac, dict):
            man, typ = (ac.get("manufacturer") or "").strip(), (ac.get("type") or "").strip()
            info["model"] = typ if (not man or typ.lower().startswith(man.lower())) else (man + " " + typ).strip()
            info["code"] = (ac.get("icao_type") or "").strip().upper()
            info["reg"] = ac.get("registration") or ""
            info["owner"] = ac.get("registered_owner") or ""
            info["photo_url"] = ac.get("url_photo") or None
    cs = (callsign or "").strip()
    if cs:
        code, d = http_json("https://api.adsbdb.com/v0/callsign/" + cs, timeout)
        if code == 200 and isinstance(d, dict):
            fr = (d.get("response") or {}).get("flightroute") if isinstance(d.get("response"), dict) else None
            if isinstance(fr, dict):
                def city(k):
                    a = fr.get(k) or {}
                    return a.get("municipality") or a.get("name") or a.get("iata_code") or "?"
                info["airline"] = (fr.get("airline") or {}).get("name") or ""
                info["origin"], info["dest"] = city("origin"), city("destination")
                info["oi"] = (fr.get("origin") or {}).get("iata_code") or ""
                info["di"] = (fr.get("destination") or {}).get("iata_code") or ""
    return info
