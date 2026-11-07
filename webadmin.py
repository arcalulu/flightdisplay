#!/usr/bin/env python3
"""Administration web legere pour flightdisplay (bibliotheque standard uniquement)."""
import base64, collections, configparser, hmac, json, math, os, re, shlex, shutil, socket
import subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import webadmin_mqtt
import webadmin_update

HERE = os.path.dirname(os.path.abspath(__file__))
INI_PATH = os.environ.get("WEBADMIN_INI") or os.path.join(HERE, "config.ini")
# Sections de config.ini gérées par webadmin ; toutes les autres appartiennent au programme d'affichage.
WEB_SECS = ("server", "app", "screen", "build", "mqtt", "update")


class Settings:
    """Reglages de webadmin (sections server, app, screen, build, mqtt, update de config.ini), relus apres chaque modification."""

    def reload(self):
        ini = configparser.ConfigParser(interpolation=None, strict=False)
        ini.read(INI_PATH, encoding="utf-8-sig")
        self.ini = ini

        def gs(sec, key, d=""):
            return ini.get(sec, key, fallback=d).strip()

        def gb(sec, key, d):
            try:
                return ini.getboolean(sec, key, fallback=d)
            except ValueError:
                return d

        try:
            self.PORT = ini.getint("server", "port", fallback=8080)
        except ValueError:
            self.PORT = 8080
        self.HOST = gs("server", "host", "0.0.0.0") or "0.0.0.0"
        self.USER = gs("server", "user", "admin")
        self.PASSWORD = ini.get("server", "password", fallback="")
        self.APP_DIR = os.path.abspath(os.path.expanduser(gs("app", "dir") or HERE))
        self.CONFIG = INI_PATH
        self.RUNTIME = os.path.join(self.APP_DIR, gs("app", "runtime", "cache/runtime.json"))
        self.TYPES_FILE = os.path.join(self.APP_DIR, "types_extra.txt")
        self.SERVICE = gs("app", "service", "flightdisplay")
        self.PYTHON = gs("app", "python") or sys.executable
        self.BUILD_SCRIPT = gs("app", "build_script", "build_map_vector.py")
        self.SUDO = shlex.split(gs("app", "sudo", "sudo -n"))
        self.SYSTEMCTL = gs("app", "systemctl") or (
            "/usr/bin/systemctl" if os.path.exists("/usr/bin/systemctl") else (shutil.which("systemctl") or "systemctl"))
        self.JOURNALCTL = gs("app", "journalctl") or shutil.which("journalctl") or "journalctl"
        self.SCREEN_HELPER = gs("screen", "helper", "/usr/local/bin/flight-screen")
        self.SCREEN_FLAG = gs("screen", "flag", "/run/flight-screen-off")
        self.BUILD_STOP_DISPLAY = gb("build", "stop_display", True)
        self.UPDATE_AUTO = gb("update", "auto_check", True)


S = Settings()
S.reload()
BOUND = (S.HOST, S.PORT)
file_lock = threading.Lock()
rt_lock = threading.Lock()


def path_of(f):
    # Les deux fichiers logiques ("config" et "web") sont le même config.ini.
    return INI_PATH


# ---------------------------------------------------------------- schema
CATS = [
    ("position", "Carte et position", "Programme"),
    ("api", "Flightradar24", "Programme"),
    ("display", "Affichage", "Programme"),
    ("label", "Étiquettes des avions", "Programme"),
    ("panel", "Panneau photo", "Programme"),
    ("ground", "Avions au sol", "Programme"),
    ("alert", "Alerte de proximité", "Programme"),
    ("types", "Types d'avion", "Programme"),
    ("other", "Autres réglages", "Programme"),
    ("server", "Serveur web", "Webadmin"),
    ("paths", "Application et système", "Webadmin"),
    ("update", "Mises à jour", "Webadmin"),
    ("mqtt", "MQTT / Home Assistant", "Intégrations"),
]
CAT_NOTES = {
    "label": "Petits panneaux affichés à côté de chaque avion sur la carte. Réordonnez les éléments avec les flèches, choisissez ceux à afficher, leur taille, gras et italique, et s'ils partagent la ligne de l'élément précédent. Si tout est masqué, aucun panneau n'est affiché. Pris en compte après relance du programme.",
    "position": "Modifier ces valeurs oblige à reconstruire la carte (section Reconstruction de la carte, en bas de cette page).",
    "server": "Le port et l'adresse d'écoute demandent un redémarrage de webadmin. L'identifiant et le mot de passe s'appliquent immédiatement.",
    "paths": "Réglages avancés. Une valeur vide utilise le comportement par défaut.",
    "update": "La mise à jour elle-même se lance depuis l'onglet « Mises à jour ».",
    "mqtt": "Les changements sont appliqués immédiatement : webadmin se reconnecte au serveur MQTT.",
}


def P(cat, file, sec, key, typ, default, label, help="", group="", **kw):
    d = dict(cat=cat, file=file, sec=sec, key=key, type=typ, default=default, label=label, help=help, group=group)
    d["apply"] = kw.pop("apply", "app" if file == "config" else "live")
    d.update(kw)
    return d


def C(*a, **k):
    return P(a[0], "config", *a[1:], **k)


def W(*a, **k):
    return P(a[0], "web", *a[1:], **k)


# Champs des etiquettes d'avion : (id, nom, visible, taille, meme ligne que le precedent). Memes defauts que main.py.
LABEL_FIELDS = [("model", "Modèle de l'avion", True, "medium", False), ("registration", "Immatriculation", False, "medium", True),
                ("callsign", "Indicatif de vol", False, "medium", True), ("airline", "Compagnie", True, "small", False),
                ("route", "Trajet", True, "small", False), ("altitude", "Altitude", True, "small", False),
                ("speed", "Vitesse", True, "small", True)]
LABEL_PARAMS = [C("label", "label", "order", "text", ",".join(f[0] for f in LABEL_FIELDS), "Ordre des éléments",
                  "Ordre d'affichage, de haut en bas.", "Disposition", fields=[f[0] for f in LABEL_FIELDS])]
for _id, _name, _show, _size, _same in LABEL_FIELDS:
    LABEL_PARAMS += [
        C("label", "label", "show_" + _id, "bool", _show, _name, "", "Contenu"),
        C("label", "label", _id + "_size", "choice", _size, _name + " : taille", "", "Style", options=["small", "medium", "large"]),
        C("label", "label", _id + "_bold", "bool", False, _name + " : gras", "", "Style"),
        C("label", "label", _id + "_italic", "bool", False, _name + " : italique", "", "Style"),
        C("label", "label", _id + "_same_line", "bool", _same, _name + " : sur la ligne précédente", "", "Style"),
    ]

PARAMS = [
    C("position", "position", "latitude", "float", "", "Latitude", "Degrés décimaux (ex. 44.8378).", "Maison", min=-90, max=90, needs_map=True),
    C("position", "position", "longitude", "float", "", "Longitude", "Degrés décimaux (ex. -0.5792).", "Maison", min=-180, max=180, needs_map=True),
    C("position", "position", "radius_km", "float", 20, "Rayon de la carte (km)", "Distance couverte par la carte.", "Carte", min=1, max=200, needs_map=True),
    C("position", "map", "carto_key", "secret", "", "Clé API CARTO", "Nécessaire pour construire la carte (lue par build_map_vector.py).", "Fond de carte", needs_map=True),
    
    C("api", "api", "poll_seconds", "float", 30, "Intervalle de requête (s)", "Trop bas : risque d'erreur 429.", "Fréquence", min=5, max=600),
    C("api", "api", "details_pause_seconds", "float", 4, "Pause entre les détails (s)", "Délai entre deux requêtes de détails d'avion.", "Fréquence", min=0, max=60),
    C("api", "api", "stale_seconds", "float", 30, "Durée de validité d'une position (s)", "Au-delà, l'avion est retiré de la carte.", "Validité des données", min=5, max=600),
    C("display", "display", "fullscreen", "bool", False, "Plein écran", "", "Écran"),
    C("display", "display", "fps", "int", 10, "Images par seconde", "Une valeur basse ménage le Pi Zero.", "Écran", min=1, max=60),
    C("display", "display", "altitude_unit", "choice", "ft", "Unité d'altitude", "", "Unités", options=["ft", "m"]),
    C("display", "display", "speed_unit", "choice", "kmh", "Unité de vitesse", "", "Unités", options=["kmh", "kt"]),
    C("display", "display", "max_altitude_ft", "int", 0, "Altitude maximale suivie (ft)", "0 = pas de limite. Les avions plus hauts sont ignorés.", "Filtre et icônes", min=0, max=100000),
    C("display", "display", "icon_scale", "float", 1.25, "Taille des icônes", "", "Filtre et icônes", min=0.3, max=5),
    C("position", "display", "width", "int", 1920, "Largeur de la carte (px)", "Taille de l'image de fond. Demande de reconstruire la carte.", "Taille de la carte", min=320, max=7680, needs_map=True),
    C("position", "display", "height", "int", 1080, "Hauteur de la carte (px)", "Taille de l'image de fond. Demande de reconstruire la carte.", "Taille de la carte", min=240, max=4320, needs_map=True),
    *LABEL_PARAMS,
    C("panel", "panel", "width", "int", 480, "Largeur (px, base 1080p)", "", "Fiche photo", min=200, max=1200),
    C("panel", "panel", "rotate_seconds", "float", 12, "Rotation entre avions (s)", "", "Fiche photo", min=3, max=120),
    C("panel", "panel", "corner_top_left", "bool", True, "Haut gauche", "Décochez un angle pour que le panneau n'y soit jamais affiché, même si un avion passe derrière les autres angles. Si tout est décoché, aucune restriction.", "Angles autorisés"),
    C("panel", "panel", "corner_top_right", "bool", True, "Haut droite", "", "Angles autorisés"),
    C("panel", "panel", "corner_bottom_left", "bool", True, "Bas gauche", "", "Angles autorisés"),
    C("panel", "panel", "corner_bottom_right", "bool", True, "Bas droite", "La liste des avions au sol occupe déjà cet angle quand elle est affichée.", "Angles autorisés"),
    C("ground", "ground", "show_list", "bool", True, "Afficher la liste", "", "Liste"),
    C("ground", "ground", "max_rows", "int", 8, "Lignes maximum", "", "Liste", min=1, max=30),
    C("ground", "ground", "width", "int", 780, "Largeur de la liste (px, base 1080p)", "", "Liste", min=300, max=1800),
    C("ground", "ground", "airport_iata", "text", "", "Aéroport (code IATA)", "Ex. BOD. Sert à afficher « de ... » et « vers ... ».", "Filtres", upper=True),
    C("ground", "ground", "min_speed_kt", "float", 0, "Vitesse minimale (kt)", "Masque les avions quasi immobiles.", "Filtres", min=0, max=200),
    C("ground", "ground", "landed_alt_ft", "int", 2000, "Altitude d'atterrissage (ft)", "Un avion qui disparaît sous cette altitude est considéré comme posé.", "Atterrissage", min=0, max=10000),
    C("ground", "ground", "landed_keep_minutes", "float", 10, "Durée d'affichage après atterrissage (min)", "", "Atterrissage", min=0, max=240),
    C("alert", "alert", "radius_km", "float", 5, "Rayon d'alerte (km)", "0 désactive toute l'alerte.", "Zone", min=0, max=50),
    C("alert", "alert", "sound", "bool", True, "Son", "Interrupteur général. La coupure temporaire se fait dans Pilotage.", "Son"),
    C("alert", "alert", "volume", "float", 0.6, "Volume par défaut", "Valeur de départ. Le curseur de Pilotage la remplace en direct.", "Son", min=0, max=1, ui="slider", step=0.05),

    C("alert", "alert", "pulse_seconds", "float", 3, "Durée d'un clignotement (s)", "", "Teinte rouge", min=0.5, max=30),
    C("alert", "alert", "alpha_min", "int", 10, "Intensité minimale (0-255)", "", "Teinte rouge", min=0, max=255, ui="slider", step=5),
    C("alert", "alert", "alpha_max", "int", 60, "Intensité maximale (0-255)", "", "Teinte rouge", min=0, max=255, ui="slider", step=5),
    C("alert", "alert", "min_altitude_ft", "int", 0, "Altitude minimale (ft)", "Les avions plus bas ne déclenchent pas l'alerte.", "Plage d'altitude", min=0, max=100000),
    C("alert", "alert", "max_altitude_ft", "int", 0, "Altitude maximale (ft)", "0 = pas de limite haute.", "Plage d'altitude", min=0, max=100000),

    C("alert", "alert", "sound_on_start", "bool", False, "Son au lancement du programme", "Joue le carillon une fois au démarrage, indépendamment des autres options de cette section.", "Au démarrage"),
    C("alert", "alert", "simulate_on_start", "bool", False, "Simuler une alerte au démarrage", "Teinte rouge et carillon pendant quelques secondes, même si « Son au lancement » est décoché.", "Au démarrage"),
    C("alert", "alert", "simulate_seconds", "float", 3, "Durée de la simulation (s)", "", "Au démarrage", min=1, max=30),

    W("server", "server", "host", "text", "0.0.0.0", "Adresse d'écoute", "0.0.0.0 = tout le réseau, 127.0.0.1 = le Pi seul.", "Réseau", apply="web"),
    W("server", "server", "port", "int", 8080, "Port", "", "Réseau", apply="web", min=1, max=65535),
    W("server", "server", "user", "text", "admin", "Identifiant", "", "Accès"),
    W("server", "server", "password", "secret", "", "Mot de passe", "Vide : aucune protection. Le mot de passe circule en clair sur le réseau local.", "Accès"),
    W("paths", "app", "dir", "text", "", "Dossier de l'application", "Vide : dossier de webadmin.py.", "Application"),
    W("paths", "app", "config", "text", "config.ini", "Fichier de réglages", "", "Application"),
    W("paths", "app", "runtime", "text", "cache/runtime.json", "Fichier d'état du son", "Partagé avec le programme d'affichage.", "Application"),
    W("paths", "app", "service", "text", "flightdisplay", "Service d'affichage", "Nom du service systemd.", "Application"),
    W("paths", "app", "python", "text", "", "Python pour la carte", "Interpréteur du venv, utilisé pour build_map_vector.py.", "Carte"),
    W("paths", "app", "build_script", "text", "build_map_vector.py", "Script de la carte", "", "Carte"),
    W("paths", "build", "stop_display", "bool", True, "Arrêter l'affichage pendant la construction", "Valeur par défaut de l'onglet Carte.", "Carte"),
    W("paths", "app", "sudo", "text", "sudo -n", "Préfixe sudo", "", "Système"),
    W("paths", "app", "systemctl", "text", "", "Chemin de systemctl", "Doit correspondre au fichier sudoers.", "Système"),
    W("paths", "app", "journalctl", "text", "", "Chemin de journalctl", "", "Système"),
    W("paths", "screen", "helper", "text", "/usr/local/bin/flight-screen", "Script de veille de l'écran", "", "Écran"),
    W("paths", "screen", "flag", "text", "/run/flight-screen-off", "Fichier témoin de la veille", "", "Écran"),
    W("update", "update", "auto_check", "bool", True, "Vérifier automatiquement", "Interroge GitHub toutes les 12 heures pour signaler une nouvelle version. Rien n'est installé sans votre accord.", "Vérification", apply="live"),
    W("mqtt", "mqtt", "enabled", "bool", False, "Activer MQTT", "Publie l'état et accepte les commandes de Home Assistant.", "Connexion", apply="mqtt"),
    W("mqtt", "mqtt", "host", "text", "", "Serveur", "Adresse du serveur MQTT.", "Connexion", apply="mqtt"),
    W("mqtt", "mqtt", "port", "int", 1883, "Port", "", "Connexion", apply="mqtt", min=1, max=65535),
    W("mqtt", "mqtt", "user", "text", "", "Identifiant", "", "Connexion", apply="mqtt"),
    W("mqtt", "mqtt", "password", "secret", "", "Mot de passe", "", "Connexion", apply="mqtt"),
    W("mqtt", "mqtt", "tls", "bool", False, "Chiffrement TLS", "Certificat vérifié avec les autorités du système.", "Connexion", apply="mqtt"),
    W("mqtt", "mqtt", "base_topic", "text", "flightdisplay", "Préfixe des sujets", "", "Sujets et découverte", apply="mqtt"),
    W("mqtt", "mqtt", "discovery_prefix", "text", "homeassistant", "Préfixe de découverte", "", "Sujets et découverte", apply="mqtt"),
    W("mqtt", "mqtt", "device_name", "text", "Flight display", "Nom de l'appareil", "", "Sujets et découverte", apply="mqtt"),
    W("mqtt", "mqtt", "interval", "float", 30, "Republication complète (s)", "Les changements sont publiés dans les 5 secondes.", "Sujets et découverte", apply="mqtt", min=5, max=3600),
]
SPEC = {(p["file"], p["sec"], p["key"]): p for p in PARAMS}
SEC_RE = re.compile(r"^\[([^\]]+)\]$")
KEY_RE = re.compile(r"^(\s*)([^\s#;=:][^=:]*?)\s*[=:]\s*(.*)$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
TYPE_CATS = ["narrow", "wide", "quad", "regional", "turbo", "light", "bizjet", "heli"]


def read_lines(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read().splitlines()
    except FileNotFoundError:
        return []


def parse(lines):
    vals, secs, sec = {}, {}, None
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s[0] in "#;":
            continue
        m = SEC_RE.match(s)
        if m:
            sec = m.group(1)
            secs.setdefault(sec, {"hdr": i, "last": i})
            continue
        m = KEY_RE.match(line)
        if m and sec is not None:
            vals[(sec, m.group(2).lower())] = dict(line=i, indent=m.group(1), orig=m.group(2), value=m.group(3).strip())
            secs[sec]["last"] = i
    return vals, secs


def fmt_default(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def get_settings():
    state = {f: parse(read_lines(path_of(f)))[0] for f in ("config", "web")}
    cats = {cid: dict(id=cid, title=t, menu=m, groups=collections.OrderedDict(), note=CAT_NOTES.get(cid, ""))
            for cid, t, m in CATS}
    for p in PARAMS:
        cur = state[p["file"]].get((p["sec"], p["key"]))
        raw = cur["value"] if cur else fmt_default(p["default"])
        out = dict(id=f'{p["file"]}:{p["sec"]}.{p["key"]}', cat=p["cat"], key=p["key"], type=p["type"], label=p["label"],
                   help=p["help"], options=p.get("options"), needs_map=bool(p.get("needs_map")), apply=p["apply"],
                   present=cur is not None, min=p.get("min"), max=p.get("max"), step=p.get("step"), ui=p.get("ui"),
                   secret=p["type"] == "secret", set=bool(cur and cur["value"]), value="" if p["type"] == "secret" else raw)
        cats[p["cat"]]["groups"].setdefault(p["group"], []).append(out)
        cats[p["cat"]]["file"] = p["file"]
    for f, vals in state.items():
        for (sec, key), cur in vals.items():
            if (sec in WEB_SECS) != (f == "web"):
                continue
            if (f, sec, key) not in SPEC:
                label = f'[{sec}] {cur["orig"]}'
                cats["other"]["groups"].setdefault("Hors schéma (config.ini)", []).append(
                    dict(id=f"{f}:{sec}.{key}", cat="other", key=key, type="text", label=label, help="", options=None,
                         needs_map=False, apply="app" if f == "config" else "live", present=True, min=None, max=None,
                         step=None, ui=None, secret=False, set=True, value=cur["value"]))
    cats["types"].update(kind="types", groups=[], file=None)
    cats["label"]["kind"] = "labels"
    menu = []
    for gname in ("Programme", "Webadmin", "Intégrations"):
        items = []
        for cid, title, m in CATS:
            c = cats[cid]
            if m == gname and (cid == "types" or c["groups"]):
                items.append(dict(id=cid, title=title))
        if items:
            menu.append(dict(group=gname, items=items))
    for c in cats.values():
        if c.get("kind") != "types":
            c["groups"] = [dict(name=n, params=ps) for n, ps in c["groups"].items()]
    return dict(label_fields=[dict(id=f[0], name=f[1]) for f in LABEL_FIELDS], menu=menu, cats={k: v for k, v in cats.items() if v.get("kind") == "types" or v["groups"]},
                has_backup={f: os.path.exists(path_of(f) + ".bak") for f in ("config", "web")})


def norm_value(p, v):
    v = str(v)
    if "\n" in v or "\r" in v:
        raise ValueError("valeur invalide")
    t = p["type"]
    if t == "secret":
        return v
    v = v.strip()
    if t == "bool":
        if v.lower() not in ("true", "false"):
            raise ValueError("doit être true ou false")
        return v.lower()
    if t in ("int", "float"):
        try:
            n = int(v) if t == "int" else float(v)
        except ValueError:
            raise ValueError("nombre entier attendu" if t == "int" else "nombre attendu")
        if isinstance(n, float) and not math.isfinite(n):
            raise ValueError("nombre invalide")
        if p.get("min") is not None and n < p["min"]:
            raise ValueError("minimum " + str(p["min"]))
        if p.get("max") is not None and n > p["max"]:
            raise ValueError("maximum " + str(p["max"]))
        return str(n) if t == "int" else v
    if t == "choice":
        if v not in p["options"]:
            raise ValueError("choix possibles : " + ", ".join(p["options"]))
        return v
    if p["file"] == "config" and "%" in v:
        raise ValueError("le caractère % n'est pas autorisé dans config.ini")
    if p.get("fields"):  # liste ordonnee d'identifiants : on la complete avec les champs manquants
        items = [x.strip() for x in v.split(",") if x.strip()]
        if any(x not in p["fields"] for x in items) or len(set(items)) != len(items):
            raise ValueError("liste d'éléments invalide")
        return ",".join(items + [x for x in p["fields"] if x not in items])
    return v.upper() if p.get("upper") else v


def plan(f, changes):
    vals, secs = parse(read_lines(path_of(f)))
    todo, errors = [], []
    for ident, raw in changes.items():
        sec, _, key = ident.partition(".")
        if not NAME_RE.match(sec) or not key or not NAME_RE.match(key):
            errors.append(ident + " : nom invalide"); continue
        spec = SPEC.get((f, sec, key.lower()))
        if (sec in WEB_SECS) != (f == "web"):
            errors.append(ident + " : réglage inconnu"); continue
        if spec is None and (sec, key.lower()) not in vals:
            errors.append(ident + " : réglage inconnu"); continue
        p = spec or dict(type="text", label=key, file=f)
        try:
            v = norm_value(p, raw)
        except ValueError as e:
            errors.append(p["label"] + " : " + str(e)); continue
        cur = vals.get((sec, key.lower()))
        if cur is not None and cur["value"] == v:
            continue
        if cur is None and spec is not None and spec["type"] != "secret" and fmt_default(spec["default"]) == v:
            continue
        if cur is None and spec is not None and spec["type"] == "secret" and v == "":
            continue
        todo.append((sec, key, v))
    return todo, errors


def write_changes(items):
    """items : liste de (fichier logique, section, clé, valeur). Une seule écriture et une seule sauvegarde."""
    path = INI_PATH
    lines = read_lines(path)
    changed = []
    for f, sec, key, v in items:
        vals, secs = parse(lines)
        cur = vals.get((sec, key.lower()))
        if cur:
            lines[cur["line"]] = f'{cur["indent"]}{cur["orig"]} = {v}'
        elif sec in secs:
            lines.insert(secs[sec]["last"] + 1, f"{key} = {v}")
        else:
            if lines and lines[-1].strip():
                lines.append("")
            lines += [f"[{sec}]", f"{key} = {v}"]
        changed.append(f"{f}:{sec}.{key}")
    if changed:
        if os.path.exists(path):
            shutil.copy2(path, path + ".bak")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    return changed


def apply_settings(changes):
    by = {"config": {}, "web": {}}
    for ident, v in changes.items():
        f, _, rest = ident.partition(":")
        if f not in by:
            raise ValueError(ident + " : fichier inconnu")
        by[f][rest] = v
    with file_lock:
        plans, errors = {}, []
        for f, ch in by.items():
            todo, errs = plan(f, ch)
            plans[f] = todo
            errors += errs
        if errors:
            raise ValueError(" ; ".join(errors))
        changed = write_changes([(f, sec, key, v) for f, todo in plans.items() for (sec, key, v) in todo])
    res = dict(changed=changed, restart_app=any(c.startswith("config:") for c in changed), restart_web=False,
               needs_map=any(SPEC.get((c.split(":")[0], c.split(":")[1].split(".")[0], c.split(".", 1)[1].lower()), {}).get("needs_map")
                             for c in changed))
    if any(c.startswith("web:") for c in changed):
        S.reload()
        res["restart_web"] = (S.HOST, S.PORT) != BOUND
        if any(c.startswith("web:mqtt.") for c in changed):
            MQTT.restart(S.ini)
    res["port"] = S.PORT
    return res


def restore_backup(f):
    if f not in ("config", "web"):
        raise ValueError("fichier inconnu")
    with file_lock:
        path = path_of(f)
        bak = path + ".bak"
        if not os.path.exists(bak):
            raise ValueError("aucune sauvegarde")
        tmp = path + ".swap"
        if os.path.exists(path):
            shutil.copy2(path, tmp)
        shutil.copy2(bak, path)
        if os.path.exists(tmp):
            os.replace(tmp, bak)
    S.reload()
    MQTT.restart(S.ini)


# ---------------------------------------------------------------- types d'avion
def unknown_types(known):
    found = []
    for code in re.findall(r"type inconnu \(icone par defaut\) : (\S+)", journal(2000)):
        if code.upper() not in known and code not in found:
            found.append(code)
    return found


def read_types():
    try:
        with open(S.TYPES_FILE, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def write_types(text):
    known = set()
    for n, line in enumerate(text.splitlines(), 1):
        body = line.split("#")[0].split()
        if not body:
            continue
        if len(body) != 2:
            raise ValueError(f"ligne {n} : attendu « CODE catégorie »")
        if not re.fullmatch(r"[A-Za-z0-9]{2,6}", body[0]):
            raise ValueError(f"ligne {n} : code de type invalide")
        if body[1] not in TYPE_CATS:
            raise ValueError(f"ligne {n} : catégorie inconnue (" + ", ".join(TYPE_CATS) + ")")
        known.add(body[0].upper())
    path = S.TYPES_FILE
    with file_lock:
        if os.path.exists(path):
            shutil.copy2(path, path + ".bak")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n" if text.strip() else "")
        os.replace(tmp, path)


# ---------------------------------------------------------------- son
def runtime_read():
    try:
        with open(S.RUNTIME, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def sound_state():
    d = runtime_read()
    vals, _ = parse(read_lines(S.CONFIG))
    try:
        cfg_vol = float(vals[("alert", "volume")]["value"])
    except Exception:
        cfg_vol = 0.6
    v = d.get("volume")
    vol = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else cfg_vol
    enabled = vals.get(("alert", "sound"), {}).get("value", "true").lower() != "false"
    return dict(muted=bool(d.get("muted", False)), volume=round(max(0.0, min(1.0, vol)), 2), sound_enabled=enabled)


FPS_FILE = "/dev/shm/flightdisplay-fps.json" if os.path.isdir("/dev/shm") else os.path.join(S.APP_DIR, "cache", "fps.json")


def fps_info():
    """Images par seconde reellement affichees (publiees par main.py), None si le programme ne tourne pas."""
    try:
        with open(FPS_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        if time.time() - float(d["t"]) > 8:
            return None
        return round(float(d["fps"]), 1)
    except Exception:
        return None


def fps_target():
    try:
        return int(parse(read_lines(S.CONFIG))[0][("display", "fps")]["value"])
    except Exception:
        return 10


def sound_update(body):
    with rt_lock:
        d = runtime_read()
        if "muted" in body:
            d["muted"] = bool(body["muted"])
        if "volume" in body:
            try:
                v = float(body["volume"])
            except (TypeError, ValueError):
                raise ValueError("volume invalide")
            if not math.isfinite(v):
                raise ValueError("volume invalide")
            d["volume"] = round(max(0.0, min(1.0, v)), 2)
        if body.get("test"):
            if d.get("muted"):
                raise ValueError("le son est coupé")
            d["test_seq"] = int(d.get("test_seq", 0)) + 1
        os.makedirs(os.path.dirname(S.RUNTIME), exist_ok=True)
        tmp = S.RUNTIME + f".{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        os.replace(tmp, S.RUNTIME)


# ---------------------------------------------------------------- systeme
def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except FileNotFoundError as e:
        return False, "commande introuvable : " + str(e.filename)
    except subprocess.TimeoutExpired:
        return False, "délai dépassé"


def svc_state():
    ok, out = run([S.SYSTEMCTL, "is-active", S.SERVICE], 5)
    return out.splitlines()[0] if out else "inconnu"


def screen_off():
    return os.path.exists(S.SCREEN_FLAG) and svc_state() != "active"


def screen_cmd(act):
    return run(S.SUDO + [S.SCREEN_HELPER, act], 40)


cpu = {"pct": None}


def cpu_sampler():
    def read():
        with open("/proc/stat") as f:
            v = list(map(int, f.readline().split()[1:]))
        return sum(v[:8]), v[3] + (v[4] if len(v) > 4 else 0)
    prev = read()
    while True:
        time.sleep(2)
        cur = read()
        dt, di = cur[0] - prev[0], cur[1] - prev[1]
        if dt > 0:
            cpu["pct"] = round(100.0 * (dt - di) / dt, 1)
        prev = cur

def sysinfo():
    info = dict(host=socket.gethostname(), temp=None, load=list(os.getloadavg()) if hasattr(os, "getloadavg") else [0, 0, 0],
                uptime=0, mem_total=None, mem_avail=None)
    try:
        info["temp"] = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000.0
    except Exception:
        pass
    try:
        info["uptime"] = float(open("/proc/uptime").read().split()[0])
    except Exception:
        pass
    try:
        m = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
        info["mem_total"], info["mem_avail"] = m["MemTotal"], m["MemAvailable"]
    except Exception:
        pass
    return info


build = dict(running=False, rc=None, lines=collections.deque(maxlen=3000), proc=None, cancel=False)
build_lock = threading.Lock()


def build_worker(stop_display):
    b = build
    log = lambda m: b["lines"].append(m)
    stopped, rc = False, -1
    try:
        if stop_display and svc_state() == "active":
            log("Arrêt de l'affichage pendant la construction...")
            stopped, out = run(S.SUDO + [S.SYSTEMCTL, "stop", S.SERVICE])
            log(out or ("ok" if stopped else "échec de l'arrêt"))
        log("$ " + os.path.basename(S.PYTHON) + " -u " + S.BUILD_SCRIPT)
        p = subprocess.Popen([S.PYTHON, "-u", S.BUILD_SCRIPT], cwd=S.APP_DIR, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1, errors="replace")
        b["proc"] = p
        for line in p.stdout:
            log(line.rstrip())
        rc = p.wait()
        if b["cancel"]:
            log("Construction annulée.")
    except Exception as e:
        log("Erreur : " + str(e))
    finally:
        b["rc"] = rc
        try:
            if not screen_off() and (stopped or rc == 0):
                log("Relance de l'affichage...")
                ok, out = run(S.SUDO + [S.SYSTEMCTL, "restart", S.SERVICE])
                log(out or ("ok" if ok else "échec du redémarrage"))
        finally:
            b["proc"] = None
            b["running"] = False


def start_build(stop_display):
    if not os.path.exists(os.path.join(S.APP_DIR, S.BUILD_SCRIPT)):
        raise ValueError(S.BUILD_SCRIPT + " introuvable dans " + S.APP_DIR)
    if UPD.running():
        raise ValueError("une mise à jour du logiciel est en cours")
    with build_lock:
        if build["running"]:
            raise ValueError("une construction est déjà en cours")
        build.update(running=True, rc=None, cancel=False)
        build["lines"].clear()
    threading.Thread(target=build_worker, args=(stop_display,), daemon=True).start()


def cancel_build():
    p = build.get("proc")
    if not build["running"] or p is None:
        raise ValueError("aucune construction en cours")
    build["cancel"] = True
    p.terminate()


def journal(lines):
    ok, out = run([S.JOURNALCTL, "-u", S.SERVICE, "-n", str(lines), "--no-pager", "-o", "short-iso", "-q"], 15)
    if not ok and not out:
        out = "journal indisponible"
    return out


def self_restart():
    try:
        MQTT.stop()
    except Exception:
        pass
    os.execv(sys.executable, [sys.executable] + sys.argv)


UPD = webadmin_update.Updater(S, svc_state, screen_off, lambda: build["running"], self_restart)
MQTT = webadmin_mqtt.Bridge(dict(sysinfo=sysinfo, sound_state=sound_state, sound_update=sound_update,
                                 screen_off=screen_off, screen=screen_cmd))


class Handler(BaseHTTPRequestHandler):
    server_version = "FlightAdmin"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if not S.PASSWORD:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                u, _, p = base64.b64decode(h[6:]).decode("utf-8").partition(":")
                if hmac.compare_digest(u.encode(), S.USER.encode()) & hmac.compare_digest(p.encode(), S.PASSWORD.encode()):
                    return True
            except Exception:
                pass
            time.sleep(1)
        body = "Authentification requise".encode()
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Flight display", charset="UTF-8"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def do_GET(self):
        if not self.authorized():
            return
        u = urlparse(self.path)
        try:
            if u.path == "/":
                data = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/api/status":
                s = sysinfo()
                s.update(service=svc_state(), screen_off=screen_off(), build_running=build["running"], auth=bool(S.PASSWORD))
                s.update(sound_state())
                s["mqtt"] = MQTT.status
                s["update_available"] = UPD.available()
                s["update_running"] = UPD.running()
                s["cpu"] = cpu["pct"]
                s["fps"] = fps_info() if s["service"] == "active" else None
                s["fps_target"] = fps_target()
                self.send_json(s)
            elif u.path == "/api/settings":
                self.send_json(get_settings())
            elif u.path == "/api/types":
                text = read_types()
                known = {l.split("#")[0].split()[0].upper() for l in text.splitlines() if l.split("#")[0].split()}
                self.send_json(dict(text=text, categories=TYPE_CATS, unknown=unknown_types(known)))
            elif u.path == "/api/logs":
                n = int(parse_qs(u.query).get("lines", ["300"])[0])
                self.send_json({"text": journal(max(10, min(n, 2000)))})
            elif u.path == "/api/update":
                self.send_json(UPD.state())
            elif u.path == "/api/build":
                self.send_json(dict(running=build["running"], rc=build["rc"], default_stop=S.BUILD_STOP_DISPLAY,
                                    text="\n".join(list(build["lines"])[-400:])))
            else:
                self.send_json({"error": "introuvable"}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def do_POST(self):
        if not self.authorized():
            return
        if self.headers.get("X-Admin") != "1":
            return self.send_json({"error": "requête refusée"}, 403)
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > 65536:
                return self.send_json({"error": "requête trop grande"}, 413)
            body = json.loads(self.rfile.read(n) or b"{}")
            path = urlparse(self.path).path
            act = str(body.get("action", ""))
            if path == "/api/settings":
                return self.send_json(dict(ok=True, **apply_settings(body.get("changes") or {})))
            if path == "/api/settings/restore":
                restore_backup(str(body.get("file", "")))
                return self.send_json(dict(ok=True))
            if path == "/api/types":
                write_types(str(body.get("text", "")))
                return self.send_json(dict(ok=True))
            if path == "/api/sound":
                sound_update(body)
                return self.send_json(dict(ok=True, **sound_state()))
            if path == "/api/service":
                if act not in ("start", "stop", "restart"):
                    raise ValueError("action invalide")
                ok, out = run(S.SUDO + [S.SYSTEMCTL, act, S.SERVICE])
                if not ok:
                    return self.send_json({"error": out or "échec"}, 500)
                return self.send_json(dict(ok=True, message={"start": "Programme démarré", "stop": "Programme arrêté",
                                                              "restart": "Programme relancé"}[act]))
            if path == "/api/screen":
                if act not in ("on", "off"):
                    raise ValueError("action invalide")
                ok, out = screen_cmd(act)
                if not ok:
                    return self.send_json({"error": out or "échec"}, 500)
                return self.send_json(dict(ok=True, message="Écran en veille" if act == "off" else "Écran rallumé"))
            if path == "/api/power":
                if act not in ("reboot", "poweroff"):
                    raise ValueError("action invalide")
                threading.Timer(1.0, lambda: run(S.SUDO + [S.SYSTEMCTL, act])).start()
                return self.send_json(dict(ok=True, message="Redémarrage en cours..." if act == "reboot"
                                           else "Extinction en cours..."))
            if path == "/api/build":
                start_build(bool(body.get("stop_display")))
                return self.send_json(dict(ok=True))
            if path == "/api/build/cancel":
                cancel_build()
                return self.send_json(dict(ok=True))
            if path == "/api/update/check":
                UPD.check()
                return self.send_json(UPD.state())
            if path == "/api/update/start":
                UPD.start()
                return self.send_json(dict(ok=True))
            if path == "/api/mqtt/reconnect":
                MQTT.restart(S.ini)
                return self.send_json(dict(ok=True))
            if path == "/api/webadmin/restart":
                threading.Timer(1.0, self_restart).start()
                return self.send_json(dict(ok=True, message="Redémarrage de webadmin..."))
            self.send_json({"error": "introuvable"}, 404)
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)
        except Exception as e:
            self.send_json({"error": type(e).__name__ + " : " + str(e)}, 500)


PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0b0f14">
<title>Flight display - administration</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23ffd250' d='M12 2l2 7 8 4v2l-8-2v5l2 2v2l-4-1-4 1v-2l2-2v-5l-8 2v-2l8-4z'/%3E%3C/svg%3E">
<style>
:root{--bg:#0b0f14;--card:#141b24;--card2:#1a2330;--line:#243040;--txt:#e6edf3;--mut:#8b98a8;--acc:#ffd250;--ok:#34c759;--bad:#f85149;--warn:#d29922}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--txt);font:16px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{position:sticky;top:0;z-index:7;background:var(--bg);padding:calc(10px + env(safe-area-inset-top)) 14px 10px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:10px}
header h1{margin:0;font-size:18px}
.chips{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end}
.chip{font-size:12px;padding:3px 9px;border-radius:99px;background:var(--card);border:1px solid var(--line);color:var(--mut)}
.chip.ok{color:var(--ok);border-color:#1f4d2b}.chip.bad{color:var(--bad);border-color:#5c1f1c}.chip.warn{color:var(--warn);border-color:#5a4410}
main{max-width:1100px;margin:0 auto;padding:12px 12px calc(150px + env(safe-area-inset-bottom))}
.tab{display:none}.tab.on{display:block}
nav{position:fixed;left:0;right:0;bottom:0;display:flex;background:#0e141bf2;backdrop-filter:blur(8px);border-top:1px solid var(--line);padding-bottom:env(safe-area-inset-bottom);z-index:8}
nav button{flex:1;background:none;border:0;color:var(--mut);padding:12px 0 10px;font-size:13px}
nav button.on{color:var(--acc)}
h2.t{font-size:13px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em;margin:18px 4px 6px;font-weight:600}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:6px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 13px}
.tile small{display:block;color:var(--mut);font-size:12px;margin-bottom:2px}
.tile b{font-size:20px;font-weight:600}
.tile.ok b{color:var(--ok)}.tile.bad b{color:var(--bad)}.tile.warn b{color:var(--warn)}
.tile i{display:block;font-style:normal;color:var(--mut);font-size:12px;margin-top:1px}
.tile:last-child:nth-child(odd){grid-column:1/-1}
.list{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin:0 0 12px}
.li{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 14px;border-top:1px solid var(--line);min-height:54px}
.li:first-child{border-top:0}
.lt{min-width:0;flex:1}.lt b{display:block;font-weight:500;font-size:16px}.lt small{display:block;color:var(--mut);font-size:12px;margin-top:1px}
.li.stack{display:block}.li.stack .lt{margin-bottom:8px}
.li .btns{display:flex;gap:8px;width:100%}.li .btns button{flex:1}
.tg{position:relative;display:inline-block;width:51px;height:31px;flex:none}
.tg input{opacity:0;width:0;height:0;position:absolute}
.tg span{position:absolute;inset:0;background:#39424f;border-radius:99px;transition:.2s;cursor:pointer}
.tg span::after{content:"";position:absolute;top:2px;left:2px;width:27px;height:27px;border-radius:50%;background:#fff;box-shadow:0 1px 3px #0006;transition:.2s}
.tg input:checked+span{background:var(--ok)}.tg input:checked+span::after{left:22px}
.tg input:disabled+span{opacity:.5}
.tg.chg span{box-shadow:0 0 0 2px var(--acc)}
.seg{display:inline-flex;background:#0e141b;border:1px solid var(--line);border-radius:9px;padding:2px;flex:none}
.seg button{border:0;background:none;color:var(--mut);padding:6px 14px;border-radius:7px;font-size:14px}
.seg button.on{background:#2c3a4d;color:var(--txt)}
.seg.chg{border-color:var(--acc)}
input[type=text],input[type=password],select,textarea{width:100%;padding:10px 12px;border-radius:9px;border:1px solid var(--line);background:#0e141b;color:var(--txt);font-size:16px;font-family:inherit}
textarea{font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;min-height:220px;resize:vertical}
input.chg,select.chg{border-color:var(--acc)}
input[type=range]{width:100%;height:30px;accent-color:var(--acc);margin:0}
.sl{display:flex;align-items:center;gap:10px;width:min(280px,55%)}.sl span{min-width:44px;text-align:right;font-variant-numeric:tabular-nums;color:var(--mut);font-size:14px}
.li.full{display:block}.li.full .lt{margin-bottom:7px}
.li .flag{color:var(--warn);font-size:11px;margin-left:6px}
.pw{display:flex;gap:8px}.pw button{flex:none}
button.b{width:100%;padding:12px;border-radius:10px;border:1px solid var(--line);background:#1b2431;color:var(--txt);font-size:16px}
button.b.p{background:var(--acc);color:#1a1400;border-color:var(--acc);font-weight:600}
button.b.d{background:#3a1613;border-color:#6b2420;color:#ffb4ae}
button.b.s{width:auto;padding:8px 14px;font-size:14px}
button.b:disabled{opacity:.45}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pb{height:10px;border-radius:99px;background:#0e141b;border:1px solid var(--line);overflow:hidden;margin:4px 0 12px}
.pb i{display:block;height:100%;width:0;background:var(--acc);transition:width .4s}
.pb.ok i{background:var(--ok)}.pb.bad i{background:var(--bad)}
.stp{display:flex;align-items:center;gap:10px;padding:9px 14px;border-top:1px solid var(--line);font-size:15px}
.stp:first-child{border-top:0}
.stp .ic{width:22px;text-align:center;flex:none;color:var(--mut)}
.stp.running .ic{color:var(--acc)}.stp.done .ic{color:var(--ok)}.stp.error .ic{color:var(--bad)}
.stp.running{color:var(--txt)}.stp.pending,.stp.skipped{color:var(--mut)}
.stp small{color:var(--mut);font-size:12px;margin-left:auto;text-align:right}
@keyframes spin{to{transform:rotate(360deg)}}
.stp.running .ic{display:inline-block;animation:spin 1s linear infinite}
.cm{display:flex;gap:10px;padding:8px 14px;border-top:1px solid var(--line);font-size:14px}
.cm:first-child{border-top:0}.cm code{white-space:nowrap;color:var(--mut);font:12px ui-monospace,Menlo,Consolas,monospace;flex:none;padding-top:2px}.cm span:nth-child(2){flex:1;min-width:0}.cm .chip{flex:none;align-self:flex-start}
.lprev{display:inline-block;background:#0a0e14;border:1px solid var(--line);border-radius:6px;padding:6px 10px;margin:4px 4px 10px;line-height:1.3}
.lrow{padding:10px 14px;border-top:1px solid var(--line)}.lrow:first-child{border-top:0}
.lrow .top{display:flex;align-items:center;gap:8px}.lrow .top b{flex:1;font-weight:500}
.lrow .opt{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;align-items:center}.lrow.off .opt{opacity:.45}
.lrow button.b.s{padding:6px 12px}.lrow button.b.s.on{background:var(--acc);color:#1a1400;border-color:var(--acc)}
.dotn{position:relative}.dotn.dot::after{content:"";position:absolute;top:8px;right:calc(50% - 38px);width:8px;height:8px;border-radius:50%;background:var(--acc)}
.set{display:block}
.menu{display:flex;gap:6px;overflow-x:auto;padding-bottom:10px;margin:0 -4px 6px;scrollbar-width:none}
.menu::-webkit-scrollbar{display:none}
.menu .mg{display:none}
.menu button{flex:none;border:1px solid var(--line);background:var(--card);color:var(--txt);padding:8px 14px;border-radius:99px;font-size:14px;position:relative}
.menu button.on{background:var(--acc);color:#1a1400;border-color:var(--acc)}
.menu button.dot::after{content:"";position:absolute;top:5px;right:6px;width:7px;height:7px;border-radius:50%;background:var(--acc)}
.menu button.on.dot::after{background:#1a1400}
.catt{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:2px 4px 4px}
.catt h3{margin:0;font-size:20px}
p.note{color:var(--mut);font-size:13px;margin:0 4px 10px}
pre{margin:0;padding:10px;background:#080b10;border:1px solid var(--line);border-radius:10px;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-word;max-height:58vh;overflow:auto}
pre .e{color:#ff8a84}pre .w{color:#e3b341}pre .m{color:var(--mut)}
.bar{position:fixed;left:0;right:0;bottom:calc(52px + env(safe-area-inset-bottom));padding:8px 12px;background:#0e141bf2;backdrop-filter:blur(8px);border-top:1px solid var(--line);z-index:7;display:none}
.bar.on{display:block}.bar .in{max-width:1100px;margin:0 auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap}.bar .in span{flex:1 1 100%;font-size:13px;color:var(--mut)}.bar .in button{flex:1}
.hint{background:#2a2108;border:1px solid #5a4410;color:#f0d78c;padding:10px 12px;border-radius:10px;margin-bottom:12px;display:none;font-size:14px}
.hint .btns{display:flex;gap:8px;margin-top:8px}.hint .btns button{flex:1}
.tools{display:flex;gap:8px;margin-bottom:8px;align-items:center}.tools>*{flex:1}
.tools select,.tools input[type=text]{padding:9px 10px;font-size:14px}
.cols{display:block}
.tcol{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.tcol button{border:1px solid var(--line);background:var(--card2);color:var(--txt);border-radius:99px;padding:5px 12px;font:13px ui-monospace,Menlo,Consolas,monospace}
#toast{position:fixed;left:50%;top:calc(70px + env(safe-area-inset-top));transform:translateX(-50%);background:#1f2937;border:1px solid var(--line);padding:10px 16px;border-radius:10px;z-index:20;display:none;max-width:90vw;font-size:14px}
#toast.bad{border-color:var(--bad);color:#ffb4ae}
@media(min-width:860px){
.tiles{grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);grid-template-columns:none}
.tile b{font-size:18px;overflow-wrap:anywhere}
  .cols{display:grid;grid-template-columns:1fr 1fr;gap:0 16px;align-items:start}
  nav{position:static;max-width:1100px;margin:0 auto;border:0;background:none;backdrop-filter:none;justify-content:flex-start;gap:6px;padding:10px 12px 0}
  nav button{flex:none;padding:8px 18px;border-radius:99px;font-size:15px}
  nav button.on{background:var(--card2)}
  main{padding-bottom:110px}
  .set{display:grid;grid-template-columns:230px 1fr;gap:22px;align-items:start}
  .menu{flex-direction:column;overflow:visible;position:sticky;top:76px;margin:0;gap:2px;padding:0}
  .menu .mg{display:block;color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin:14px 10px 4px}
  .menu .mg:first-child{margin-top:0}
  .menu button{border:0;background:none;text-align:left;padding:9px 12px;border-radius:9px;font-size:15px;width:100%}
  .menu button:hover{background:var(--card)}
  .menu button.on{background:var(--card2);color:var(--acc)}
  .menu button.dot::after{top:14px;right:12px}
  .menu button.on.dot::after{background:var(--acc)}
  .bar{bottom:14px;left:50%;right:auto;transform:translateX(-50%);width:min(760px,94vw);border:1px solid var(--line);border-radius:14px}
}
</style>
</head>
<body>
<header><h1>Flight display</h1><div class="chips" id="chips"></div></header>
<nav id="nav">
  <button data-t="home" class="on" onclick="go('home')">Pilotage</button>
  <button data-t="cfg" onclick="go('cfg')">Réglages</button>
  <button data-t="upd" class="dotn" id="navUpd" onclick="go('upd')">Mises à jour</button>
  <button data-t="log" onclick="go('log')">Logs</button>
</nav>
<main>
<section class="tab on" id="t-home">
  <div class="tiles" id="tiles"></div>
  <div class="cols">
    <div>
      <h2 class="t">Commandes</h2>
      <div class="list" id="ctl"></div>
    </div>
    <div>
      <h2 class="t">Écran</h2>
      <div class="list" id="ctlScreen"></div>
      <h2 class="t">Raspberry Pi</h2>
      <div class="list">
        <div class="li stack"><div class="lt"><b>Alimentation</b><small>Après une extinction, il faut débrancher puis rebrancher l'alimentation.</small></div>
          <div class="btns"><button class="b d" onclick="power('reboot')">Redémarrer</button><button class="b d" onclick="power('poweroff')">Éteindre</button></div></div>
      </div>
    </div>
  </div>
</section>

<section class="tab" id="t-cfg">
  <div class="hint" id="mapHint">La position ou le rayon de la carte a changé : la carte doit être reconstruite.<div class="btns"><button class="b p s" onclick="gotoMap()">Aller à la reconstruction</button></div></div>
  <div class="hint" id="pending"><span id="pendTxt"></span><div class="btns" id="pendBtns"></div></div>
  <div class="set">
    <div class="menu" id="menu"></div>
    <div id="catbox"></div>
  </div>
</section>

<div id="mapHolder" style="display:none"><div id="mapBuild">
  <div class="list">
    <div class="li stack"><div class="lt"><b>Reconstruire la carte</b><small>Lance build_map_vector.py avec la position et le rayon de config.ini. L'affichage est relancé à la fin pour charger la nouvelle carte.</small></div></div>
    <div class="li"><div class="lt"><b>Arrêter l'affichage pendant la construction</b><small>Libère la mémoire du Pi Zero.</small></div><label class="tg"><input type="checkbox" id="stopDisp"><span></span></label></div>
    <div class="li stack"><div class="btns"><button class="b p" id="buildBtn" onclick="startBuild()">Reconstruire la carte</button><button class="b d" id="cancelBtn" onclick="cancelBuild()" style="display:none">Annuler</button></div></div>
  </div>
  <div class="chips" style="margin:0 0 8px;justify-content:flex-start"><span class="chip" id="buildState">inactif</span></div>
  <pre id="buildOut">Aucune construction lancée.</pre>
</div></div>

<section class="tab" id="t-upd">
  <div class="hint" id="updWarn"></div>
  <div class="tiles" id="updTiles"></div>
  <div class="list" id="updAct"></div>
  <div id="updProg" style="display:none">
    <h2 class="t" id="updProgT">Progression</h2>
    <div class="pb" id="updBar"><i></i></div>
    <div class="list" id="updSteps"></div>
    <pre id="updOut"></pre>
  </div>
  <div id="updNew" style="display:none">
    <h2 class="t">Historique des versions</h2>
    <div class="list" id="updCommits"></div>
  </div>
</section>

<section class="tab" id="t-log">
  <div class="tools">
    <select id="logN" onchange="loadLogs()"><option>100</option><option selected>300</option><option>1000</option></select>
    <input type="text" id="logF" placeholder="filtrer" oninput="renderLogs()">
  </div>
  <div class="list"><div class="li"><div class="lt"><b>Actualisation automatique</b><small>Toutes les 3 secondes</small></div><label class="tg"><input type="checkbox" id="logAuto" checked><span></span></label></div></div>
  <pre id="logOut">Chargement...</pre>
</section>
</main>

<div class="bar" id="saveBar"><div class="in"><span id="barTxt"></span>
  <button class="b p" onclick="saveSettings(false)">Enregistrer</button>
  <button class="b" onclick="saveSettings(true)">Enregistrer et appliquer</button>
  <button class="b" style="flex:none;width:auto" onclick="discardEdits()">Annuler</button>
</div></div>
<div id="toast"></div>

<script>
let SET = null, edits = {}, curCat = null, cur = 'home', logText = '', lastSt = null, volDrag = false, volTimer = null;
let pend = {app: false, web: false}, TYPES = null, rows = {}, UPD = null, updWasRunning = false, updBusy = false, updAuto = false;
const $ = s => document.querySelector(s);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined) e.textContent = txt; return e; };

async function api(path, body) {
  const opt = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Admin': '1'}, body: JSON.stringify(body)};
  const r = await fetch(path, opt);
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(data.error || ('Erreur HTTP ' + r.status));
  return data;
}
let toastT = null;
function toast(msg, bad) {
  const t = $('#toast');
  t.textContent = msg; t.className = bad ? 'bad' : ''; t.style.display = 'block';
  clearTimeout(toastT); toastT = setTimeout(() => t.style.display = 'none', bad ? 6000 : 3000);
}
function toggle(checked, onchange) {
  const l = el('label', 'tg'), i = document.createElement('input'); i.type = 'checkbox'; i.checked = checked;
  l.append(i, el('span')); i.addEventListener('change', () => onchange(i.checked, i, l)); return {label: l, input: i};
}
function go(tab) {
  cur = tab;
  document.querySelectorAll('.tab').forEach(e => e.classList.toggle('on', e.id === 't-' + tab));
  document.querySelectorAll('nav button').forEach(e => e.classList.toggle('on', e.dataset.t === tab));
  updateBar();
  if (tab === 'log') loadLogs();
  if (tab === 'cfg') pollBuild();
  if (tab === 'home') pollStatus();
  if (tab === 'upd') pollUpd();
  window.scrollTo(0, 0);
}

/* ---------- Pilotage ---------- */
function li(title, sub, cls) {
  const r = el('div', 'li' + (cls ? ' ' + cls : '')), t = el('div', 'lt'), s = el('small', null, sub || '');
  t.append(el('b', null, title), s); r.append(t); return {r, sub: s};
}
function buildHome() {
  const box = $('#ctl'); box.innerHTML = ''; rows = {};
  const p = li('Programme Flight Display', ''); const tp = toggle(false, onProg); p.r.append(tp.label); rows.prog = {...p, t: tp}; box.append(p.r);
  const s = li('Écran', ''); const ts = toggle(true, onScreen); s.r.append(ts.label); rows.screen = {...s, t: ts}; const scr = $('#ctlScreen'); scr.innerHTML = ''; scr.append(s.r);
  const n = li('Son des alertes', ''); const tn = toggle(true, onSound); n.r.append(tn.label); rows.sound = {...n, t: tn}; box.append(n.r);
  const v = li('Volume', '', 'full'); const w = el('div', 'sl'); w.style.width = '100%';
  const vol = document.createElement('input'); vol.type = 'range'; vol.min = 0; vol.max = 100; vol.step = 5; vol.value = 60; const vl = el('span', null, '60 %');
  const tb = el('button', 'b s', 'Tester le son'); tb.style.flex = 'none';
  w.append(vol, vl, tb); v.r.append(w); rows.vol = {vol, vl}; rows.test = tb; box.append(v.r);
  vol.addEventListener('input', () => {
    volDrag = true; vl.textContent = vol.value + ' %';
    if (!volTimer) volTimer = setTimeout(async () => { volTimer = null; try { await api('/api/sound', {volume: vol.value / 100}); } catch (e) { toast(e.message, true); } }, 200);
  });
  vol.addEventListener('change', async () => { try { await api('/api/sound', {volume: vol.value / 100}); } catch (e) { toast(e.message, true); } volDrag = false; pollStatus(); });
  tb.onclick = async () => { try { await api('/api/sound', {test: true}); toast('Son de test envoyé'); } catch (e) { toast(e.message, true); } };
}
async function busy(inp, fn) {
  inp.disabled = true;
  try { await fn(); } catch (e) { toast(e.message, true); } finally { inp.disabled = false; setTimeout(pollStatus, 1200); }
}
function onProg(on, inp) {
  if (!on && !confirm("Arrêter le programme Flight Display ?")) { inp.checked = true; return; }
  busy(inp, async () => {
    const r = on ? (lastSt && lastSt.screen_off ? await api('/api/screen', {action: 'on'}) : await api('/api/service', {action: 'start'})) : await api('/api/service', {action: 'stop'});
    toast(r.message);
  });
}
function onScreen(on, inp) {
  if (!on && !confirm("Mettre l'écran en veille ? L'affichage sera arrêté.")) { inp.checked = true; return; }
  busy(inp, async () => { const r = await api('/api/screen', {action: on ? 'on' : 'off'}); toast(r.message); });
}
function onSound(on, inp) {
  busy(inp, async () => { await api('/api/sound', {muted: !on}); toast(on ? 'Son réactivé' : 'Son coupé'); });
}
async function svc(action) {
  try { const r = await api('/api/service', {action}); toast(r.message); setTimeout(pollStatus, 1500); } catch (e) { toast(e.message, true); }
}
async function power(action) {
  const t = action === 'reboot' ? 'Redémarrer le Raspberry Pi ?' : "Éteindre le Raspberry Pi ? Il faudra le rebrancher pour le rallumer.";
  if (!confirm(t)) return;
  try { const r = await api('/api/power', {action}); toast(r.message); } catch (e) { toast(e.message, true); }
}
function chip(text, cls) { return el('span', 'chip ' + (cls || ''), text); }
function tile(label, value, cls, sub) {
  const d = el('div', 'tile ' + (cls || '')); d.append(el('small', null, label), el('b', null, value));
  if (sub) d.append(el('i', null, sub)); return d;
}
function fmtUp(s) { const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? d + ' j ' + h + ' h' : (h ? h + ' h ' + m + ' min' : m + ' min'); }
async function pollStatus() {
  try {
    const s = await api('/api/status'); lastSt = s;
    const c = $('#chips'); c.innerHTML = '';
    if (s.muted) c.append(chip('son coupé', 'warn'));
    if (s.build_running) c.append(chip('carte en construction', 'warn'));
    if (s.update_running) c.append(chip('mise à jour en cours', 'warn')); else if (s.update_available) c.append(chip('mise à jour disponible', 'ok'));
    $('#navUpd').classList.toggle('dot', !!s.update_available && !s.update_running);


    const aw = $('#authWarn'); if (aw) aw.style.display = s.auth ? 'none' : 'block';
    const t = $('#tiles'); t.innerHTML = '';
    t.append(tile('Programme', s.service === 'active' ? 'actif' : s.service, s.service === 'active' ? 'ok' : 'bad', s.fps !== null && s.fps !== undefined ? s.fps.toFixed(1) + ' / ' + s.fps_target + ' fps' : ''));
    t.append(tile('Écran', s.screen_off ? 'en veille' : 'allumé', s.screen_off ? 'warn' : ''));
    t.append(tile('Température', s.temp !== null ? s.temp.toFixed(0) + ' °C' : '-', s.temp > 75 ? 'bad' : (s.temp > 65 ? 'warn' : '')));
    t.append(tile('Utilisation CPU', s.cpu !== null ? Math.round(s.cpu) + ' %' : '-', s.cpu > 95 ? 'bad' : (s.cpu > 85 ? 'warn' : ''), 'charge moyenne : ' + s.load[0].toFixed(2) + ' / ' + s.load[1].toFixed(2)));
    if (s.mem_total) {
      const used = Math.round((s.mem_total - s.mem_avail) / 1024), tot = Math.round(s.mem_total / 1024), pct = Math.round(used * 100 / tot);
      t.append(tile('Mémoire', pct + ' %', pct > 90 ? 'bad' : (pct > 80 ? 'warn' : ''), used + ' / ' + tot + ' Mo'));
    } else t.append(tile('Mémoire', '-'));
    t.append(tile('Allumé depuis', fmtUp(s.uptime), '', s.host));
    const ml = {connecte: ['connecté', 'ok'], deconnecte: ['déconnecté', 'bad'], off: ['désactivé', ''], 'paho manquant': ['paho manquant', 'bad'], 'host manquant': ['serveur manquant', 'warn']};
    const mq = ml[s.mqtt] || [String(s.mqtt).startsWith('refuse') ? 'refusé' : s.mqtt, 'bad'];
    t.append(tile('MQTT', mq[0], mq[1]));
    if (rows.prog) {
      const run = s.service === 'active';
      if (!rows.prog.t.input.disabled) rows.prog.t.input.checked = run;
      rows.prog.sub.textContent = run ? 'En fonctionnement' : (s.screen_off ? 'Arrêté (écran en veille)' : 'Arrêté');
      if (!rows.screen.t.input.disabled) rows.screen.t.input.checked = !s.screen_off;
      rows.screen.sub.textContent = s.screen_off ? 'En veille : le programme est arrêté' : 'Allumé';
      if (!rows.sound.t.input.disabled) rows.sound.t.input.checked = !s.muted && s.sound_enabled;
      rows.sound.t.input.disabled = !s.sound_enabled;
      rows.sound.sub.textContent = !s.sound_enabled ? 'Désactivé dans config.ini (alert, sound)' : (s.muted ? "Coupé : icône de haut-parleur barré à l'écran" : 'Carillon à chaque avion entrant dans la zone');
      rows.test.disabled = s.muted || !s.sound_enabled;
      if (!volDrag) { rows.vol.vol.value = Math.round(s.volume * 100); rows.vol.vl.textContent = Math.round(s.volume * 100) + ' %'; }
    }
  } catch (e) {}
}

/* ---------- Réglages ---------- */
function allParams() { const o = []; if (SET) for (const c of Object.values(SET.cats)) for (const g of c.groups || []) for (const p of g.params) o.push(p); return o; }
function pval(p) { return p.id in edits ? edits[p.id] : p.value; }
function setEdit(p, v, clear) {
  if (p.secret) { if (clear) edits[p.id] = ''; else if (v) edits[p.id] = v; else delete edits[p.id]; }
  else if (v === p.value) delete edits[p.id]; else edits[p.id] = v;
  updateBar(); markMenu();
}
function applyNeeds() {
  const n = {app: false, web: false};
  for (const p of allParams()) if (p.id in edits) { if (p.apply === 'app') n.app = true; if (p.apply === 'web') n.web = true; }
  return n;
}
function updateBar() {
  const n = Object.keys(edits).length, b = $('#saveBar');
  b.classList.toggle('on', cur === 'cfg' && n > 0);
  if (n) {
    const a = applyNeeds(), parts = [];
    if (a.app) parts.push('relance du programme'); if (a.web) parts.push('redémarrage de webadmin');
    $('#barTxt').textContent = n + ' modification' + (n > 1 ? 's' : '') + (parts.length ? ' · à appliquer : ' + parts.join(' et ') : ' · prise en compte immédiate');
  }
}
function markMenu() {
  const dirty = new Set(); for (const p of allParams()) if (p.id in edits) dirty.add(p.cat);
  document.querySelectorAll('#menu button').forEach(b => b.classList.toggle('dot', dirty.has(b.dataset.c)));
}
function renderMenu() {
  const m = $('#menu'); m.innerHTML = '';
  for (const g of SET.menu) {
    m.append(el('div', 'mg', g.group));
    for (const it of g.items) { const b = el('button', it.id === curCat ? 'on' : '', it.title); b.dataset.c = it.id; b.onclick = () => { curCat = it.id; renderMenu(); renderCat(); }; m.append(b); }
  }
  markMenu();
}
function control(p) {
  const v = pval(p), wrap = el('div');
  if (p.type === 'bool') {
    const t = toggle(String(v) === 'true', on => setEdit(p, on ? 'true' : 'false'));
    t.label.classList.toggle('chg', p.id in edits); t.input.addEventListener('change', () => t.label.classList.toggle('chg', p.id in edits));
    return {c: t.label, inline: true};
  }
  if (p.type === 'choice' && p.options.length <= 3) {
    const s = el('div', 'seg' + (p.id in edits ? ' chg' : ''));
    for (const o of p.options) { const b = el('button', String(v) === o ? 'on' : '', o); b.onclick = () => { setEdit(p, o); s.classList.toggle('chg', p.id in edits); s.querySelectorAll('button').forEach(x => x.classList.toggle('on', x.textContent === o)); }; s.append(b); }
    return {c: s, inline: true};
  }
  if (p.type === 'choice') {
    const s = document.createElement('select'); for (const o of p.options) { const op = el('option', null, o); op.value = o; s.append(op); }
    s.value = v; s.className = p.id in edits ? 'chg' : ''; s.onchange = () => { setEdit(p, s.value); s.classList.toggle('chg', p.id in edits); }; return {c: s, inline: false};
  }
  if (p.ui === 'slider') {
    const w = el('div', 'sl'), r = document.createElement('input'); r.type = 'range'; r.min = p.min; r.max = p.max; r.step = p.step || 1; r.value = v;
    const l = el('span', null, String(v)); r.oninput = () => { l.textContent = r.value; setEdit(p, String(r.value)); }; w.append(r, l); return {c: w, inline: true};
  }
  if (p.secret) {
    const w = el('div', 'pw'), i = document.createElement('input'); i.type = 'password'; i.autocomplete = 'new-password';
    const cleared = edits[p.id] === '';
    i.placeholder = cleared ? 'sera effacé' : (p.set ? '•••••••• (défini, saisir pour changer)' : 'non défini');
    i.value = (p.id in edits && !cleared) ? edits[p.id] : ''; i.oninput = () => { setEdit(p, i.value); i.classList.toggle('chg', p.id in edits); };
    w.append(i);
    if (p.set) { const b = el('button', 'b s', cleared ? 'Garder' : 'Effacer'); b.onclick = () => { if (cleared) { delete edits[p.id]; updateBar(); markMenu(); } else setEdit(p, '', true); renderCat(); }; w.append(b); }
    return {c: w, inline: false};
  }
  const i = document.createElement('input'); i.type = 'text'; i.value = v; i.className = p.id in edits ? 'chg' : '';
  i.inputMode = p.type === 'int' ? 'numeric' : (p.type === 'float' ? 'decimal' : 'text');
  i.autocomplete = 'off'; i.autocapitalize = 'off'; i.spellcheck = false;
  i.oninput = () => { setEdit(p, p.type === 'float' ? i.value.trim().replace(',', '.') : i.value.trim()); i.classList.toggle('chg', p.id in edits); };
  return {c: i, inline: false};
}
function gotoMap() { go('cfg'); curCat = 'position'; renderMenu(); renderCat(); }
function renderCat() {
  const mb = $('#mapBuild'), holder = $('#mapHolder');
  if (mb && holder && mb.parentNode !== holder) holder.appendChild(mb);
  renderCatBase();
  if (curCat === 'position' && mb) { const box = $('#catbox'); box.appendChild(el('h2', 't', 'Reconstruction de la carte')); box.appendChild(mb); pollBuild(); }
}
function renderCatBase() {
  const box = $('#catbox'); box.innerHTML = '';
  const cat = SET.cats[curCat]; if (!cat) return;
  const head = el('div', 'catt'); head.append(el('h3', null, cat.title)); box.append(head);
  if (cat.kind === 'types') return renderTypes(box);
  if (cat.kind === 'labels') { if (cat.note) box.append(el('p', 'note', cat.note)); return renderLabels(box); }
  if (cat.id === 'mqtt') {
    const st = lastSt ? lastSt.mqtt : 'off', h = el('div', 'tools'); const c = chip('État : ' + (st === 'off' ? 'désactivé' : st), st === 'connecte' ? 'ok' : (st === 'off' ? '' : 'bad')); c.style.flex = 'none';
    const b = el('button', 'b s', 'Reconnecter / republier'); b.style.flex = 'none'; b.onclick = async () => { try { await api('/api/mqtt/reconnect', {}); toast('Reconnexion demandée'); setTimeout(pollStatus, 2000); } catch (e) { toast(e.message, true); } };
    h.append(c, b); box.append(h);
  }
  if (cat.note) box.append(el('p', 'note', cat.note));
  if (cat.id === 'server') { const w = el('div', 'hint', "Aucun mot de passe n'est défini : toute personne du réseau local peut piloter le Raspberry Pi. Définissez-en un ci-dessous."); w.id = 'authWarn'; w.style.display = (lastSt && !lastSt.auth) ? 'block' : 'none'; box.append(w); }  
  for (const g of cat.groups) {
    if (g.name) box.append(el('h2', 't', g.name));
    const list = el('div', 'list');
    for (const p of g.params) {
      const ctl = control(p), row = el('div', 'li' + (ctl.inline ? '' : ' full')), t = el('div', 'lt'), b = el('b', null, p.label);
      if (p.needs_map) b.append(el('span', 'flag', 'recalcule la carte'));
      t.append(b); const hp = (p.help || '') + (p.present ? '' : (p.help ? ' ' : '') + '(absent du fichier : valeur par défaut)');
      if (hp) t.append(el('small', null, hp));
      row.append(t, ctl.c); list.append(row);
    }
    box.append(list);
  }
  if (cat.file) {
    const r = el('button', 'b s', 'Revenir à la version précédente de ' + 'config.ini');
    r.onclick = async () => { if (!confirm('Remplacer le fichier par sa version précédente ?')) return; try { await api('/api/settings/restore', {file: cat.file}); toast('Version précédente restaurée'); await loadSettings(); } catch (e) { toast(e.message, true); } };
    if (cat.file === 'web' && SET.has_backup[cat.file]) box.append(r);
  }
}
async function loadSettings() {
  SET = await api('/api/settings'); edits = {};
  if (!curCat || !SET.cats[curCat]) curCat = SET.menu[0].items[0].id;
  renderMenu(); renderCat(); updateBar();
}
function showPending() {
  const box = $('#pending'), btns = $('#pendBtns'); btns.innerHTML = '';
  if (!pend.app && !pend.web) { box.style.display = 'none'; return; }
  box.style.display = 'block';
  const parts = []; if (pend.app) parts.push('relancer le programme'); if (pend.web) parts.push('redémarrer webadmin');
  $('#pendTxt').textContent = 'Enregistré. Pour appliquer : ' + parts.join(' et ') + '.';
  if (pend.app) { const b = el('button', 'b p s', 'Relancer le programme'); b.onclick = async () => { await svc('restart'); pend.app = false; showPending(); }; btns.append(b); }
  if (pend.web) { const b = el('button', 'b p s', 'Redémarrer webadmin'); b.onclick = () => restartWeb(pend.port); btns.append(b); }
}
async function saveSettings(apply) {
  try {
    const r = await api('/api/settings', {changes: edits});
    await loadSettings();
    pollStatus();
    toast(r.changed.length + ' réglage(s) enregistré(s)');
    if (r.needs_map) $('#mapHint').style.display = 'block';
    pend.port = r.port;
    if (apply) {
      if (r.restart_app) await svc('restart');
      if (r.restart_web) { pend = {app: false, web: false}; showPending(); await restartWeb(r.port); return; }
      pend = {app: false, web: false};
    } else { pend.app = pend.app || r.restart_app; pend.web = pend.web || r.restart_web; }
    showPending();
  } catch (e) { toast(e.message, true); }
}
function discardEdits() { edits = {}; renderCat(); markMenu(); updateBar(); }
async function restartWeb(port) {
  if (!confirm('Redémarrer webadmin ? La page sera indisponible quelques secondes.')) return;
  try { await api('/api/webadmin/restart', {}); } catch (e) { toast(e.message, true); return; }
  toast('Redémarrage de webadmin...');
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 1000));
    try { await fetch('/api/status', {cache: 'no-store'}).then(r => { if (!r.ok && r.status !== 401) throw 0; }); break; } catch (e) {}
  }
  if (port && String(port) !== location.port && location.port) location.href = location.protocol + '//' + location.hostname + ':' + port + '/';
  else location.reload();
}

/* ---------- Types d'avion ---------- */
async function renderTypes(box) {
  box.append(el('p', 'note', "Associe un code de type d'avion (ICAO) à une forme d'icône. Une ligne par règle : le code, puis la catégorie. Les lignes commençant par # sont des commentaires. Pris en compte après relance du programme."));
  let T; try { T = await api('/api/types'); } catch (e) { box.append(el('p', 'note', e.message)); return; }
  TYPES = T;
  const ta = document.createElement('textarea'); ta.value = T.text; ta.spellcheck = false; ta.placeholder = 'WT9 light\nB350 turbo   # exemple';
  const unk = el('div', 'tcol'); const addrow = el('div', 'tools');
  const code = document.createElement('input'); code.type = 'text'; code.placeholder = 'Code (ex. WT9)'; code.style.textTransform = 'uppercase';
  const sel = document.createElement('select'); for (const c of T.categories) { const o = el('option', null, c); o.value = c; sel.append(o); }
  const add = el('button', 'b s', 'Ajouter'); add.style.flex = 'none';
  add.onclick = () => { const c = code.value.trim().toUpperCase(); if (!c) return; ta.value = (ta.value.trim() ? ta.value.replace(/\s+$/, '') + '\n' : '') + c + ' ' + sel.value + '\n'; code.value = ''; };
  addrow.append(code, sel, add);
  if (T.unknown.length) {
    box.append(el('h2', 't', 'Types inconnus détectés dans les logs'));
    for (const u of T.unknown) { const b = el('button', null, u); b.onclick = () => { code.value = u; }; unk.append(b); }
    box.append(unk);
  }
  box.append(el('h2', 't', 'Ajouter une règle'), addrow, el('h2', 't', 'Fichier types_extra.txt'), ta);
  const bt = el('div', 'grid'); bt.style.marginTop = '10px';
  const save = el('button', 'b p', 'Enregistrer'), save2 = el('button', 'b', 'Enregistrer et relancer');
  const doSave = async relaunch => { try { await api('/api/types', {text: ta.value}); toast('Types enregistrés'); if (relaunch) await svc('restart'); else { pend.app = true; showPending(); } } catch (e) { toast(e.message, true); } };
  save.onclick = () => doSave(false); save2.onclick = () => doSave(true); bt.append(save, save2); box.append(bt);
}

/* ---------- Étiquettes des avions ---------- */
const LBL_SAMPLE = {model: 'Airbus A320', registration: 'F-GKXA', callsign: 'AFR1234', airline: 'Air France', route: 'Paris  →  Nice', altitude: '3 000 ft', speed: '450 km/h'};
const LBL_PX = {small: 13, medium: 17, large: 21}, LBL_SIZES = [['small', 'Petit'], ['medium', 'Moyen'], ['large', 'Grand']];
function lp(key) { return allParams().find(p => p.id === 'config:label.' + key); }
function lval(key) { const p = lp(key); return p ? pval(p) : ''; }
function lset(key, v) { const p = lp(key); if (p) setEdit(p, String(v)); }
function labelOrder() {
  const names = SET.label_fields.map(f => f.id);
  let o = String(lval('order')).split(',').map(x => x.trim()).filter(x => names.includes(x));
  o = o.filter((x, i) => o.indexOf(x) === i);
  for (const n of names) if (!o.includes(n)) o.push(n);
  return o;
}
function renderLabels(box) {
  const names = Object.fromEntries(SET.label_fields.map(f => [f.id, f.name]));
  const prev = el('div', 'lprev'), list = el('div', 'list');
  box.append(el('h2', 't', 'Aperçu'), prev, el('h2', 't', 'Contenu, ordre et style'), list);
  const on = k => lval(k) === 'true';
  function preview() {
    prev.innerHTML = '';
    const lines = [];
    for (const k of labelOrder()) {
      if (!on('show_' + k)) continue;
      if (on(k + '_same_line') && lines.length) lines[lines.length - 1].push(k); else lines.push([k]);
    }
    if (!lines.length) { prev.append(el('span', 'chip', 'aucune étiquette')); return; }
    for (const ln of lines) {
      const d = el('div'); d.style.whiteSpace = 'nowrap';
      ln.forEach((k, i) => {
        if (i) { const s = el('span', null, '  ·  '); s.style.color = '#bec8d2'; s.style.fontSize = LBL_PX[lval(ln[i - 1] + '_size')] + 'px'; d.append(s); }
        const s = el('span', null, LBL_SAMPLE[k]);
        s.style.fontSize = LBL_PX[lval(k + '_size')] + 'px'; s.style.fontWeight = on(k + '_bold') ? '700' : '400';
        s.style.fontStyle = on(k + '_italic') ? 'italic' : 'normal'; s.style.color = ['model', 'registration', 'callsign'].includes(k) ? '#fff' : '#bec8d2';
        d.append(s);
      });
      prev.append(d);
    }
  }
  function tbtn(label, active, fn, title) {
    const b = el('button', 'b s' + (active ? ' on' : ''), label); if (title) b.title = title; b.onclick = fn; return b;
  }
  function draw() {
    list.innerHTML = '';
    const order = labelOrder();
    order.forEach((k, i) => {
      const row = el('div', 'lrow' + (on('show_' + k) ? '' : ' off')), top = el('div', 'top');
      const up = tbtn('▲', false, () => { if (i > 0) { [order[i - 1], order[i]] = [order[i], order[i - 1]]; lset('order', order.join(',')); draw(); } });
      const dn = tbtn('▼', false, () => { if (i < order.length - 1) { [order[i + 1], order[i]] = [order[i], order[i + 1]]; lset('order', order.join(',')); draw(); } });
      up.disabled = i === 0; dn.disabled = i === order.length - 1;
      const tg = toggle(on('show_' + k), v => { lset('show_' + k, v ? 'true' : 'false'); draw(); });
      top.append(el('b', null, names[k]), up, dn, tg.label);
      const opt = el('div', 'opt');
      const sz = el('div', 'seg');
      for (const [v, t] of LBL_SIZES) { const b = el('button', lval(k + '_size') === v ? 'on' : '', t); b.onclick = () => { lset(k + '_size', v); draw(); }; sz.append(b); }
      opt.append(sz,
        tbtn('G', on(k + '_bold'), () => { lset(k + '_bold', on(k + '_bold') ? 'false' : 'true'); draw(); }, 'Gras'),
        tbtn('I', on(k + '_italic'), () => { lset(k + '_italic', on(k + '_italic') ? 'false' : 'true'); draw(); }, 'Italique'),
        tbtn('Même ligne', on(k + '_same_line'), () => { lset(k + '_same_line', on(k + '_same_line') ? 'false' : 'true'); draw(); }, "Afficher sur la même ligne que l'élément précédent"));
      row.append(top, opt); list.append(row);
    });
    preview();
  }
  draw();
}

/* ---------- Mises à jour ---------- */
function ago(ts) { const d = Math.max(0, Math.round(Date.now() / 1000 - ts)); return d < 90 ? "à l'instant" : (d < 5400 ? 'il y a ' + Math.round(d / 60) + ' min' : (d < 129600 ? 'il y a ' + Math.round(d / 3600) + ' h' : 'il y a ' + Math.round(d / 86400) + ' j')); }
function fmtEl(s) { return s >= 60 ? Math.floor(s / 60) + ' min ' + (s % 60) + ' s' : s + ' s'; }
async function pollUpd() {
  try {
    const u = await api('/api/update'); UPD = u;
    const busy = u.running || u.restarting;
    if (updWasRunning && !busy && u.ok === true && u.to_label) { updWasRunning = false; renderUpd(); setTimeout(() => { location.hash = '#upd'; location.reload(); }, 2500); return; }
    updWasRunning = busy;
    renderUpd();
    if (!u.check && !busy && !updAuto && !updBusy) { updAuto = true; checkUpd(); }
  } catch (e) {
    if (updWasRunning) { UPD = Object.assign({}, UPD, {restarting: true, running: false}); renderUpd(true); }
  }
}
async function checkUpd() {
  updBusy = true; renderUpd();
  try { UPD = await api('/api/update/check', {}); } catch (e) { toast(e.message, true); }
  updBusy = false; renderUpd(); pollStatus();
}
async function startUpd() {
  try { await api('/api/update/start', {}); updWasRunning = true; await pollUpd(); } catch (e) { toast(e.message, true); }
}
function renderUpd(lost) {
  if (!UPD) return;
  const u = UPD, c = u.check, busy = u.running || u.restarting;
  const tiles = $('#updTiles'); tiles.innerHTML = '';
  const cur = u.current || (c && c.ok ? c.current : null);
  tiles.append(tile('Version installée', cur ? cur.label : '-', '', cur ? cur.date + ' · ' + cur.subject : ''));
  if (c && c.ok) {
    const lat = c.latest;
    tiles.append(tile('Dernière version', lat.label, c.behind ? 'ok' : '', lat.date + ' · ' + lat.subject));
    tiles.append(tile('État', c.behind ? c.behind + ' nouveauté' + (c.behind > 1 ? 's' : '') : 'à jour', c.behind ? 'ok' : '', 'vérifié ' + ago(c.checked_at)));
  } else if (c && !c.ok) tiles.append(tile('État', 'vérification impossible', 'bad'));
  else tiles.append(tile('État', 'non vérifié', ''));
  const warn = $('#updWarn'), w = [];
  if (c && !c.ok) w.push(c.error);
  if (c && c.ok) {
    if (c.dirty.length) w.push('Des fichiers du logiciel ont été modifiés localement (' + c.dirty.slice(0, 5).join(', ') + ') : la mise à jour est bloquée pour ne rien écraser.');
    if (c.ahead) w.push('Cette installation contient ' + c.ahead + ' commit(s) local(aux) absent(s) de GitHub' + (c.behind ? ' : mise à jour impossible sans conflit.' : '.'));
    if (c.behind && c.installer_changed) w.push("Le programme d'installation (install.sh) a changé dans cette version. Webadmin ne met pas à jour les composants système : si une nouvelle fonction ne marche pas, relancez l'installeur.");
  }
  if (u.ok === false && u.error && !busy) w.push('Dernière tentative en échec : ' + u.error);
  warn.style.display = w.length ? 'block' : 'none'; warn.textContent = w.join('\n'); warn.style.whiteSpace = 'pre-line';
  const act = $('#updAct'); act.innerHTML = '';
  const r = el('div', 'li stack'), b = el('div', 'btns');
  const bc = el('button', 'b' + (c && c.ok && c.behind ? '' : ' p'), updBusy ? 'Vérification...' : 'Vérifier les mises à jour'); bc.disabled = updBusy || busy; bc.onclick = checkUpd;
  b.append(bc);
  if (c && c.ok && c.behind) { const bu = el('button', 'b p', 'Mettre à jour'); bu.disabled = busy || updBusy || !c.can_update; bu.onclick = startUpd; b.append(bu); }
  const t = el('div', 'lt'); t.append(el('b', null, 'Mises à jour du logiciel'), el('small', null, 'Télécharge la dernière version depuis GitHub (dépôt arcalulu/flightdisplay). Vos réglages (config.ini) sont conservés.'));
  r.append(t, b); act.append(r);
  const prog = $('#updProg'), show = busy || u.started;
  prog.style.display = show ? 'block' : 'none';
  if (show) {
    $('#updProgT').textContent = busy ? 'Mise à jour en cours' : (u.ok ? 'Dernière mise à jour' : 'Dernière tentative');
    const pb = $('#updBar'); pb.className = 'pb' + (!busy && u.ok === true ? ' ok' : (!busy && u.ok === false ? ' bad' : ''));
    pb.firstElementChild.style.width = (busy || u.ok !== null ? u.pct : 0) + '%';
    const sb = $('#updSteps'); sb.innerHTML = '';
    const icon = {pending: '○', running: '◐', done: '✓', skipped: '–', error: '✕'};
    for (const s of u.steps) {
      const d = el('div', 'stp ' + s.status); d.append(el('span', 'ic', icon[s.status] || '○'), el('span', null, s.label));
      const info = s.status === 'running' && s.elapsed > 2 ? fmtEl(s.elapsed) : s.detail; if (info) d.append(el('small', null, info));
      sb.append(d);
    }
    if (lost || u.restarting) { const d = el('div', 'stp running'); d.append(el('span', 'ic', '◐'), el('span', null, 'Webadmin redémarre, la page va se recharger...')); sb.append(d); }
    if (!busy && u.done_msg) { const d = el('div', 'stp done'); d.append(el('span', 'ic', '✓'), el('span', null, u.done_msg)); sb.append(d); }
    const o = $('#updOut'), atEnd = o.scrollTop + o.clientHeight >= o.scrollHeight - 30;
    o.textContent = u.lines.join('\n') + (u.live ? '\n' + u.live : ''); if (atEnd) o.scrollTop = o.scrollHeight;
  }
  const nw = $('#updNew'), cl = $('#updCommits'); cl.innerHTML = '';
  if (u.history && u.history.length && !busy) {
    nw.style.display = 'block';
    for (const m of u.history) {
      const d = el('div', 'cm'), t = el('span', null, m.subject);
      d.append(el('code', null, 'n°' + m.num + ' · ' + m.short + ' · ' + m.date), t);
      if (m.tag) d.append(el('span', 'chip', m.tag));
      if (m.new) d.append(el('span', 'chip ok', 'nouveau'));
      cl.append(d);
    }
  } else nw.style.display = 'none';
}

/* ---------- Logs et carte ---------- */
function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function renderLogs() {
  const f = $('#logF').value.toLowerCase(), out = $('#logOut');
  const atEnd = out.scrollTop + out.clientHeight >= out.scrollHeight - 30;
  const html = logText.split('\n').filter(l => !f || l.toLowerCase().includes(f)).map(l => {
    const c = /traceback|error|erreur|exception|failed/i.test(l) ? 'e' : (/attention|warn|inconnu|ancien/i.test(l) ? 'w' : '');
    return c ? '<span class="' + c + '">' + esc(l) + '</span>' : esc(l);
  }).join('\n');
  out.innerHTML = html || '<span class="m">(vide)</span>';
  if (atEnd) out.scrollTop = out.scrollHeight;
}
async function loadLogs(force) {
  try { const r = await api('/api/logs?lines=' + $('#logN').value); logText = r.text; renderLogs(); } catch (e) { if (force) toast(e.message, true); }
}
async function startBuild() {
  if (!confirm('Lancer la reconstruction de la carte ?')) return;
  try { await api('/api/build', {stop_display: $('#stopDisp').checked}); $('#mapHint').style.display = 'none'; pollBuild(); } catch (e) { toast(e.message, true); }
}
async function cancelBuild() { try { await api('/api/build/cancel', {}); toast('Annulation demandée'); } catch (e) { toast(e.message, true); } }
async function pollBuild() {
  try {
    const r = await api('/api/build'), st = $('#buildState');
    st.textContent = r.running ? 'en cours...' : (r.rc === null ? 'inactif' : (r.rc === 0 ? 'terminé avec succès' : 'terminé avec erreur (code ' + r.rc + ')'));
    st.className = 'chip ' + (r.running ? 'warn' : (r.rc === null ? '' : (r.rc === 0 ? 'ok' : 'bad')));
    $('#buildBtn').disabled = r.running; $('#cancelBtn').style.display = r.running ? 'block' : 'none';
    if (r.text) { const o = $('#buildOut'), atEnd = o.scrollTop + o.clientHeight >= o.scrollHeight - 30; o.textContent = r.text; if (atEnd) o.scrollTop = o.scrollHeight; }
    if (r.default_stop !== undefined && !pollBuild.init) { $('#stopDisp').checked = r.default_stop; pollBuild.init = true; }
  } catch (e) {}
}

buildHome();
setInterval(pollStatus, 4000);
setInterval(() => { if (cur === 'log' && $('#logAuto').checked) loadLogs(); }, 3000);
setInterval(() => { if (cur === 'cfg' && curCat === 'position') pollBuild(); }, 2000);
setInterval(() => { if (cur === 'upd' || updWasRunning) pollUpd(); }, 1500);
pollStatus(); pollBuild();
loadSettings().catch(e => toast(e.message, true));
if (location.hash === '#upd') { history.replaceState(null, '', location.pathname); go('upd'); }
</script>
</body>
</html>
"""


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    if not S.PASSWORD:
        print("ATTENTION : aucun mot de passe défini dans config.ini (section [server])", flush=True)
    threading.Thread(target=cpu_sampler, daemon=True).start()
    threading.Thread(target=UPD.auto_loop, daemon=True).start()
    MQTT.configure(S.ini)
    MQTT.start()
    print(f"Administration sur http://{S.HOST}:{S.PORT}  (app : {S.APP_DIR})", flush=True)
    Server((S.HOST, S.PORT), Handler).serve_forever()
