#!/usr/bin/env python3
"""Administration web legere pour flightdisplay (bibliotheque standard uniquement)."""
import base64, collections, configparser, gzip, hashlib, hmac, json, math, os, re, shlex, shutil, socket
import urllib.request
import email.utils
import struct, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import i18n
import mapstyle
import sources
import webadmin_mqtt
import webadmin_update
from i18n import tr

HERE = os.path.dirname(os.path.abspath(__file__))
BOOT_ID = str(int(time.time()))
INI_PATH = os.environ.get("WEBADMIN_INI") or os.path.join(HERE, "config.ini")
# Sections de config.ini gérées par webadmin ; toutes les autres appartiennent au programme d'affichage.
WEB_SECS = ("server", "app", "screen", "build", "mqtt", "update", "schedule", "storage")


SLOT_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")
SCHED_DAYS = [("mon", "Lundi"), ("tue", "Mardi"), ("wed", "Mercredi"), ("thu", "Jeudi"), ("fri", "Vendredi"),
              ("sat", "Samedi"), ("sun", "Dimanche")]


def parse_slots(v):
    """« 07:00-09:30,18:00-24:00 » -> [(420, 570), (1080, 1440)] (minutes depuis minuit), fusionnees et triees."""
    out = []
    for part in str(v).split(","):
        part = part.strip()
        if not part:
            continue
        m = SLOT_RE.match(part)
        if not m:
            raise ValueError("plage horaire invalide")
        a, b = int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))
        if int(m.group(2)) > 59 or int(m.group(4)) > 59 or a >= b or b > 1440:
            raise ValueError("plage horaire invalide")
        out.append((a, b))
    out.sort()
    merged = []
    for a, b in out:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def normalize_slots(v):
    return ",".join("%02d:%02d-%02d:%02d" % (a // 60, a % 60, b // 60, b % 60) for a, b in parse_slots(v))


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
        self.UPDATE_AUTO_INSTALL = gb("update", "auto_install", False)
        try:
            self.UPDATE_HOURS = max(1, min(48, ini.getint("update", "check_hours", fallback=12)))
        except ValueError:
            self.UPDATE_HOURS = 12
        self.UPDATE_CHANNEL = "latest" if gs("update", "channel", "stable").lower() in ("latest", "dev", "main") else "stable"
        self.LANG = i18n.set_language(gs("general", "language", "fr"))
        self.SCHEDULE_ENABLED = gb("schedule", "enabled", False)
        self.CLEAN_AUTO = gb("storage", "auto_clean", False)
        try:
            self.CLEAN_MAX_MB = max(20, min(100000, ini.getint("storage", "cache_max_mb", fallback=200)))
        except ValueError:
            self.CLEAN_MAX_MB = 200
        try:
            self.STORAGE_WARN = max(50, min(99, ini.getint("storage", "warn_percent", fallback=90)))
        except ValueError:
            self.STORAGE_WARN = 90
        week = [False] * 10080  # une case par minute de la semaine (lundi 00:00 = 0)
        for i, (k, _) in enumerate(SCHED_DAYS):
            try:
                for a, b in parse_slots(gs("schedule", k, "")):
                    for m in range(a, b):
                        week[i * 1440 + m] = True
            except ValueError:
                pass
        self.SCHEDULE_MAP = week


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
    ("language", "Langue", "Général"),
    ("position", "Carte et position", "Programme"),
    ("mapstyle", "Style de la carte", "Programme"),
    ("sources", "Sources des avions", "Programme"),
    ("api", "Flightradar24", "Programme"),
    ("tar1090", "tar1090", "Programme"),
    ("online", "Services ADS-B en ligne", "Programme"),
    ("display", "Affichage", "Programme"),
    ("label", "Étiquettes des avions", "Programme"),
    ("panel", "Panneau photo", "Programme"),
    ("ground", "Avions au sol", "Programme"),
    ("alert", "Alerte de proximité", "Programme"),
    ("types", "Types d'avion", "Programme"),
    ("history", "Historique des avions", "Programme"),
    ("other", "Autres réglages", "Programme"),
    ("server", "Serveur web", "Webadmin"),
    ("paths", "Application et système", "Webadmin"),
    ("update", "Mises à jour", "Webadmin"),
    ("schedule", "Planning de l'écran", "Webadmin"),
    ("storage", "Stockage et photos", "Webadmin"),
    ("backup", "Sauvegarde", "Webadmin"),
    ("mqtt", "MQTT / Home Assistant", "Intégrations"),
]
HELP_HIST = "Au moins 1, sans limite haute. Par défaut 1000 (500 sur un Raspberry Pi Zero). Plus l'historique est long, plus la page « Avions vus » est lente à charger (surtout sur un Raspberry Pi), plus le fichier est gros (environ 360 Ko pour 1000 avions, relu et réécrit par le programme) et plus la carte SD est sollicitée. Les avions les plus anciens sont supprimés quand la limite est dépassée."
HELP_HIST_ZERO = "Au moins 1, sans limite haute. Valeur conseillée et par défaut sur ce Raspberry Pi Zero : 500. Au-delà, la page « Avions vus » devient très lente à charger (chaque avion de plus allonge la page), le fichier d'historique grossit (environ 360 Ko pour 1000 avions, relu et réécrit par le programme) et la carte SD est plus sollicitée. Les avions les plus anciens sont supprimés quand la limite est dépassée."
CAT_NOTES = {
    "language": "Langue de webadmin (immédiat) et du texte affiché à l'écran par le programme (le programme d'affichage est relancé à l'enregistrement). Pour ajouter une langue, déposez un fichier dans le dossier lang (voir la documentation).",
    "label": "Petits panneaux affichés à côté de chaque avion sur la carte. Réordonnez les éléments avec les flèches, choisissez ceux à afficher, leur taille, gras et italique, et s'ils partagent la ligne de l'élément précédent. Si tout est masqué, aucun panneau n'est affiché.",
    "position": "Modifier ces valeurs oblige à reconstruire la carte (section Reconstruction de la carte, en bas de cette page).",
    "sources": "D'où viennent les avions affichés. Cochez une ou plusieurs sources, classez-les par priorité et choisissez comment combiner leurs résultats. Un même avion reconnu par plusieurs sources n'est jamais affiché deux fois. Les changements demandent de relancer le programme.",
    "api": "Flightradar24 fournit les positions mondiales par Internet, ainsi que l'immatriculation, le modèle, la compagnie, le trajet et la photo de chaque avion. Les positions sont rafraîchies toutes les 30 s environ ; un intervalle trop court provoque des erreurs 429. Cette source s'active et se classe dans « Sources des avions ».",
    "tar1090": "Serveur tar1090 (https://github.com/wiedehopf/tar1090) de votre réseau, alimenté par une antenne ADS-B et lu par son fichier aircraft.json. Positions quasi instantanées, sans quota ni Internet. Il ne voit que les avions captés par l'antenne et ne donne ni modèle, ni compagnie, ni trajet : ils sont alors demandés à adsbdb.com (option « Compléter les avions captés seulement par l'antenne », dans « Sources des avions »). Cette source s'active et se classe dans « Sources des avions ».",
    "online": "airplanes.live, adsb.lol et adsb.fi sont des services communautaires gratuits, sans clé, qui diffusent les avions captés par des milliers d'antennes ADS-B, positions MLAT comprises. Le programme leur demande les avions dans un cercle autour de votre position qui couvre tout l'écran. Ils ne donnent ni modèle précis, ni compagnie, ni trajet : ils sont alors demandés à adsbdb.com (option « Compléter les avions absents de Flightradar24 », dans « Sources des avions »). Usage non commercial ; airplanes.live demande au plus une requête par seconde. Ces sources s'activent et se classent dans « Sources des avions ».",
    "mapstyle": "Personnalisez le fond de carte : thème, éléments affichés, couleurs et noms de lieux. Choisir un thème affiche tout de suite une carte d'exemple (indicatif) ; « Mettre à jour l'aperçu » donne le rendu fidèle de votre zone, avec vos couleurs et vos éléments. Il faut ensuite enregistrer puis reconstruire la carte pour que l'écran l'utilise.",
    "history": "Nombre d'avions gardés dans la page « Avions vus » : au-delà, les plus anciens sont supprimés. Un historique plus long ralentit la page et pèse sur la carte SD : la valeur par défaut est de 1000 avions, et de 500 sur un Raspberry Pi Zero, mais vous pouvez choisir la valeur que vous voulez. Le changement demande de relancer le programme.",
    "server": "Le port et l'adresse d'écoute demandent un redémarrage de webadmin. L'identifiant et le mot de passe s'appliquent immédiatement.",
    "paths": "Réglages avancés. Une valeur vide utilise le comportement par défaut.",
    "backup": "Exporte la configuration du Raspberry Pi dans un fichier, et la restaure (par exemple sur une nouvelle carte SD après une panne).",
    "storage": "Espace disque du Raspberry Pi et photos de JetPhotos conservées dans le cache. Sans nettoyage automatique, le programme supprime lui-même les photos de plus de 3 jours à son démarrage ; avec le nettoyage automatique, seules les plus anciennes sont supprimées quand le quota est dépassé. Une photo effacée est retéléchargée quand elle est de nouveau nécessaire.",
    "schedule": "Allume et éteint l'écran tout seul selon un calendrier hebdomadaire : faites glisser sur le calendrier pour tracer les plages d'allumage. Appliqué immédiatement.",
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


# Champs d'un bloc de texte personnalisable : (id, nom, visible, taille, meme ligne que le precedent, gras). Memes defauts que main.py.
LABEL_FIELDS = [("model", "Modèle de l'avion", True, "medium", False, False), ("registration", "Immatriculation", False, "medium", True, False),
                ("callsign", "Indicatif de vol", False, "medium", True, False), ("airline", "Compagnie", True, "small", False, False),
                ("route", "Trajet", True, "small", False, False), ("altitude", "Altitude", True, "small", False, False),
                ("speed", "Vitesse", True, "small", True, False)]
PANEL_FIELDS = [("model", "Modèle de l'avion", True, "large", False, True), ("registration", "Immatriculation", True, "large", True, True),
                ("callsign", "Indicatif de vol", False, "large", True, True), ("airline", "Compagnie", True, "medium", False, False),
                ("route", "Trajet", True, "medium", False, False), ("altitude", "Altitude", True, "medium", False, False),
                ("speed", "Vitesse", True, "medium", True, False), ("credit", "Crédit du photographe", True, "small", False, False)]
FIELD_HINTS = {"credit": "Le crédit est déjà visible à l'intérieur de l'image : cette ligne le répète sous la photo."}
# la visibilite du credit existait deja sous [panel] show_credit
PANEL_SHOW_KEYS = {"credit": ("panel", "show_credit")}


PANEL_NOTE = "Texte affiché sous la photo dans le panneau : réordonnez les éléments avec les flèches, choisissez ceux à afficher, leur taille, gras et italique, et s'ils partagent la ligne de l'élément précédent. La ligne d'alerte de proximité n'est pas modifiable."


def field_params(cat, sec, fields, show_keys=None):
    ids = [f[0] for f in fields]
    out = [C(cat, sec, "order", "text", ",".join(ids), "Ordre des éléments", "Ordre d'affichage, de haut en bas.", "Disposition", fields=ids, editor=True)]
    for _id, _name, _show, _size, _same, _bold in fields:
        ssec, skey = (show_keys or {}).get(_id, (sec, "show_" + _id))
        out += [
            C(cat, ssec, skey, "bool", _show, _name, "", "Contenu", editor=True),
            C(cat, sec, _id + "_size", "choice", _size, _name + " : taille", "", "Style", options=["small", "medium", "large"], editor=True),
            C(cat, sec, _id + "_bold", "bool", _bold, _name + " : gras", "", "Style", editor=True),
            C(cat, sec, _id + "_italic", "bool", False, _name + " : italique", "", "Style", editor=True),
            C(cat, sec, _id + "_same_line", "bool", _same, _name + " : sur la ligne précédente", "", "Style", editor=True),
        ]
    return out


def field_editor(sec, fields, mode, show_keys=None):
    """Description de l'editeur de contenu envoyee a l'interface (textes traduits)."""
    pid = lambda s_, k: "config:%s.%s" % (s_, k)
    out = []
    for f in fields:
        ssec, skey = (show_keys or {}).get(f[0], (sec, "show_" + f[0]))
        out.append(dict(id=f[0], name=tr(f[1]), hint=tr(FIELD_HINTS.get(f[0], "")) if mode == "panel" else "",
                        ids=dict(show=pid(ssec, skey), size=pid(sec, f[0] + "_size"), bold=pid(sec, f[0] + "_bold"),
                                 italic=pid(sec, f[0] + "_italic"), same=pid(sec, f[0] + "_same_line"))))
    return dict(mode=mode, order=pid(sec, "order"), fields=out)


LABEL_PARAMS = field_params("label", "label", LABEL_FIELDS)
PANEL_PARAMS = field_params("panel", "panel_content", PANEL_FIELDS, PANEL_SHOW_KEYS)

LANGS = i18n.languages()

PARAMS = [
    C("language", "general", "language", "choice", "fr", "Langue", "", "Langue", options=[l["code"] for l in LANGS],
      labels={l["code"]: l["name"] for l in LANGS}),
    C("position", "rings", "show", "bool", True, "Afficher les cercles de distance", "Cercles centrés sur votre position, tracés par le programme (pas besoin de reconstruire la carte).", "Cercles de distance"),
    C("position", "rings", "count", "int", 4, "Nombre de cercles", "Seuls les cercles contenus dans la hauteur de la carte sont tracés.", "Cercles de distance", min=0, max=30),
    C("position", "rings", "first_km", "float", 5, "Distance du premier cercle (km)", "Peut aussi servir de distance d'alerte (Alerte de proximité).", "Cercles de distance", min=0.1, max=200),
    C("position", "rings", "step_km", "float", 5, "Écartement entre les cercles (km)", "", "Cercles de distance", min=0.1, max=200),
    C("position", "rings", "width", "int", 1, "Épaisseur (px)", "", "Cercles de distance", min=1, max=8),
    C("position", "rings", "color", "color", "#2d3746", "Couleur", "", "Cercles de distance"),
    C("position", "rings", "show_labels", "bool", False, "Afficher la distance sur chaque cercle", "Petit texte « 5 km » au sommet du cercle.", "Cercles de distance"),
    C("position", "position", "latitude", "float", "", "Latitude", "Degrés décimaux (ex. 44.8378).", "Coordonnées GPS", min=-90, max=90, needs_map=True),
    C("position", "position", "longitude", "float", "", "Longitude", "Degrés décimaux (ex. -0.5792).", "Coordonnées GPS", min=-180, max=180, needs_map=True),
    C("position", "position", "radius_km", "float", 20, "Rayon de la carte (km)", "Distance couverte par la carte.", "Carte", min=1, max=200, needs_map=True),
    C("position", "map", "carto_key", "secret", "", "Clé API CARTO", "Nécessaire pour construire la carte (lue par build_map_vector.py).", "Fond de carte", needs_map=True),
    
    C("sources", "sources", "fr24_enabled", "bool", True, "Utiliser Flightradar24", "", "Sources"),
    C("sources", "sources", "tar1090_enabled", "bool", False, "Utiliser tar1090", "", "Sources"),
    C("sources", "sources", "airplaneslive_enabled", "bool", False, "Utiliser airplanes.live", "", "Sources"),
    C("sources", "sources", "adsblol_enabled", "bool", False, "Utiliser adsb.lol", "", "Sources"),
    C("sources", "sources", "adsbfi_enabled", "bool", False, "Utiliser adsb.fi", "", "Sources"),
    C("sources", "sources", "order", "text", "fr24,tar1090,airplaneslive,adsblol,adsbfi", "Ordre de priorité", "", "Sources"),
    C("sources", "sources", "mode", "choice", "combine", "Mode de combinaison", "", "Combinaison", options=["combine", "primary", "failover"]),
    C("sources", "sources", "overlap", "choice", "freshest", "Avion vu par plusieurs sources", "", "Combinaison", options=["freshest", "priority"]),
    C("sources", "sources", "enrich", "bool", True, "Compléter les avions absents de Flightradar24", "Un avion absent de Flightradar24 n'a que sa position : l'immatriculation, le modèle, la compagnie, le trajet et une photo sont alors demandés à adsbdb.com (service gratuit, sans clé). Il en va de même pour un avion que Flightradar24 connaît mais pour lequel il ne donne pas de photo. L'adresse ICAO et l'indicatif de l'avion sont envoyés à ce service. Décochez pour rester entièrement local : l'avion s'affiche alors sans détails.", "Compléments"),
    C("sources", "display", "color_by_source", "bool", False, "Colorer les avions selon leur source", "Les icônes prennent une couleur selon la ou les sources qui voient l'avion (l'avion du panneau photo reste dans sa couleur habituelle).", "Couleurs"),
    C("sources", "display", "plane_color_fr24", "color", "#ffd250", "Vus par Flightradar24 seulement", "", "Couleurs"),
    C("sources", "display", "plane_color_tar1090", "color", "#5ac8ff", "Vus par tar1090 seulement", "", "Couleurs"),
    C("sources", "display", "plane_color_airplaneslive", "color", "#ff8c3c", "Vus par airplanes.live seulement", "", "Couleurs"),
    C("sources", "display", "plane_color_adsblol", "color", "#ff78be", "Vus par adsb.lol seulement", "", "Couleurs"),
    C("sources", "display", "plane_color_adsbfi", "color", "#b496ff", "Vus par adsb.fi seulement", "", "Couleurs"),
    C("sources", "display", "plane_color_multi", "color", "#78e68c", "Vus par plusieurs sources", "", "Couleurs"),
    C("sources", "display", "color_military", "bool", True, "Colorer les avions militaires", "Les avions militaires (signalés par une source, ou de type militaire) prennent leur propre couleur, quelle que soit leur source (l'avion du panneau photo reste dans sa couleur habituelle).", "Couleurs"),
    C("sources", "display", "plane_color_military", "color", "#8fd15a", "Avions militaires", "", "Couleurs"),
    C("tar1090", "tar1090", "url", "text", "", "Adresse du fichier aircraft.json", "Pour tar1090 : http://adresse/tar1090/data/aircraft.json. Les installations dump1090-fa ou readsb seules fonctionnent aussi (http://adresse/dump1090-fa/data/aircraft.json).", "Connexion"),
    C("history", "history", "max_aircraft", "int", 1000, "Nombre d'avions gardés", HELP_HIST, "Historique", min=1),
    C("tar1090", "tar1090", "interval_seconds", "float", 2, "Intervalle de lecture (s)", "", "Connexion", min=0.5, max=60),
    C("online", "online", "interval_seconds", "float", 5, "Intervalle de lecture (s)", "Commun aux trois services. Ne descendez pas sous 1 s : ils limitent le nombre de requêtes.", "Connexion", min=1, max=60),
    C("api", "api", "poll_seconds", "float", 30, "Intervalle de requête (s)", "Trop bas : risque d'erreur 429.", "Fréquence", min=5, max=600),
    C("api", "api", "details_pause_seconds", "float", 4, "Pause entre les détails (s)", "Délai entre deux requêtes de détails d'avion.", "Fréquence", min=0, max=60),
    C("api", "api", "stale_seconds", "float", 30, "Durée de validité d'une position (s)", "Au-delà, l'avion est retiré de la carte.", "Validité des données", min=5, max=600),
    C("display", "display", "fullscreen", "bool", False, "Plein écran", "", "Écran"),
    C("display", "display", "fps", "int", 10, "Images par seconde", "Une valeur basse ménage le Pi Zero.", "Écran", min=1, max=60),
    C("display", "display", "altitude_unit", "choice", "ft", "Unité d'altitude", "", "Unités", options=["ft", "m"]),
    C("display", "display", "speed_unit", "choice", "kmh", "Unité de vitesse", "", "Unités", options=["kmh", "kt"]),
    C("display", "display", "max_altitude_ft", "int", 0, "Altitude maximale suivie (ft)", "0 = pas de limite. Les avions plus hauts sont ignorés.", "Filtre et icônes", min=0, max=100000),
    C("display", "display", "icon_scale", "float", 1.25, "Taille des icônes", "", "Filtre et icônes", min=0.3, max=5),
    C("display", "display", "plane_color_panel", "color", "#ff4646", "Avion affiché dans le panneau", "L'avion dont la photo est montrée dans le panneau.", "Couleurs des avions"),
    C("display", "display", "plane_color_known", "color", "#ffd250", "Autres avions", "Avions dont le type d'avion est connu.", "Couleurs des avions"),
    C("display", "display", "plane_color_unknown", "color", "#ffaa5a", "Avions de type inconnu", "Types absents de la liste (voir Types d'avion).", "Couleurs des avions"),
    C("position", "display", "width", "int", 1920, "Largeur de la carte (px)", "Taille de l'image de fond. Demande de reconstruire la carte.", "Taille de la carte", min=320, max=7680, needs_map=True),
    C("position", "display", "height", "int", 1080, "Hauteur de la carte (px)", "Taille de l'image de fond. Demande de reconstruire la carte.", "Taille de la carte", min=240, max=4320, needs_map=True),
    *LABEL_PARAMS,
    *PANEL_PARAMS,
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
    C("alert", "alert", "radius_km", "float", 5, "Rayon d'alerte (km)", "0 désactive toute l'alerte. Ignoré quand la distance du premier cercle est utilisée (option ci-dessous, proposée seulement s'il y a au moins un cercle affiché).", "Zone", min=0, max=50),
    C("alert", "alert", "link_first_ring", "bool", False, "Utiliser la distance du premier cercle", "Le rayon d'alerte prend la distance du premier cercle (Carte et position, Cercles de distance). Désactivez pour fixer une autre distance.", "Zone"),
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
    W("update", "update", "channel", "choice", "stable", "Canal de mise à jour", "Stable : seulement les versions publiées (v1.2.0…), plus sûr. Développement : chaque nouveau commit, y compris ceux qui ne sont pas encore publiés.", "Version", apply="live",
      options=["stable", "latest"], labels={"stable": "Stable", "latest": "Développement"}),
    W("update", "update", "auto_check", "bool", True, "Vérifier automatiquement", "Interroge GitHub régulièrement pour signaler une nouvelle version. Sans l'option d'installation automatique ci-dessous, rien n'est installé sans votre accord.", "Vérification", apply="live"),
    W("update", "update", "check_hours", "int", 12, "Intervalle de vérification (heures)", "Délai entre deux interrogations de GitHub, de 1 à 48 heures.", "Vérification", apply="live", min=1, max=48, ui="slider", step=1, unit="h"),
    W("update", "update", "auto_install", "bool", False, "Installer automatiquement les mises à jour", "Dès qu'une nouvelle version est détectée, elle est installée sans intervention (avec retour automatique à la version précédente en cas d'échec). Le programme d'affichage est relancé brièvement si la mise à jour le concerne. Nécessite la vérification automatique.", "Installation", apply="live"),
    W("schedule", "schedule", "enabled", "bool", False, "Activer le planning", "Hors des plages d'allumage, l'écran est éteint.", "Planning", apply="live"),
    *[W("schedule", "schedule", k, "text", "", name, "Plages d'allumage, au format 07:00-09:30,18:00-24:00.", "Plages", apply="live", slots=True) for k, name in SCHED_DAYS],
    W("storage", "storage", "auto_clean", "bool", False, "Nettoyer automatiquement le cache des photos", "Quand les photos dépassent le quota ci-dessous, les plus anciennes sont supprimées jusqu'à revenir à 80 % du quota ; les plus récentes sont gardées. Chaque nettoyage est inscrit dans le journal de cette page. Activé, le programme ne supprime plus les photos de plus de 3 jours à son démarrage.", "Nettoyage automatique", apply="live"),
    W("storage", "storage", "cache_max_mb", "int", 200, "Quota du cache des photos (Mo)", "Volume maximal accepté pour les photos en cache. Le nettoyage ne se déclenche qu'au-delà de cette valeur.", "Nettoyage automatique", apply="live", min=20, max=100000),
    W("storage", "storage", "warn_percent", "int", 90, "Seuil d'alerte du disque (%)", "Une alerte s'affiche dans webadmin quand l'utilisation du disque atteint ce pourcentage (alerte orange 10 points avant).", "Surveillance", apply="live", min=50, max=99),
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


def _style_params():
    out = [C("mapstyle", "mapstyle", "preset", "choice", mapstyle.DEFAULT_PRESET, "Thème", "", "Thème", needs_map=True,
             options=list(mapstyle.PRESETS), labels={k: v["label"] for k, v in mapstyle.PRESETS.items()})]
    for k, (d, label) in mapstyle.LAYERS.items():
        if k == "forest":  # cle historique
            out.append(C("mapstyle", "map", "forest", "bool", d, label, "", "Éléments", needs_map=True))
        else:
            out.append(C("mapstyle", "mapstyle", "show_" + k, "bool", d, label, "", "Éléments", needs_map=True))
    out.append(C("mapstyle", "mapstyle", "road_width", "float", 1.0, "Épaisseur des routes", "", "Éléments", needs_map=True, min=0.3, max=4))
    for k in mapstyle.COLOR_KEYS:
        out.append(C("mapstyle", "mapstyle", "color_" + k, "color", "", mapstyle.COLOR_LABELS[k], "Vide : couleur du thème.", "Couleurs", needs_map=True))
    out += [C("mapstyle", "cities", "show", "bool", True, "Afficher les noms de lieux", "", "Noms de lieux", needs_map=True),
            C("mapstyle", "cities", "kinds", "text", "city,town", "Types de lieux", "", "Noms de lieux", needs_map=True),
            C("mapstyle", "cities", "max_labels", "int", 25, "Nombre maximum de noms", "", "Noms de lieux", needs_map=True, min=0, max=200),
            C("mapstyle", "cities", "font_size", "int", 20, "Taille du texte", "", "Noms de lieux", needs_map=True, min=8, max=60)]
    return out


PARAMS += _style_params()
SPEC = {(p["file"], p["sec"], p["key"]): p for p in PARAMS}
SEC_RE = re.compile(r"^\[([^\]]+)\]$")
KEY_RE = re.compile(r"^(\s*)([^\s#;=:][^=:]*?)\s*[=:]\s*(.*)$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
import aircraft_types
TYPE_CATS = list(aircraft_types.ORDER)
TYPE_LABELS = {"narrow": "Monocouloir", "wide": "Gros-porteur", "quad": "Quadriréacteur", "regional": "Jet régional",
               "turbo": "Turbopropulseur", "light": "Avion léger", "ulm": "Ultra léger motorisé (ULM)", "mil": "Militaire","bizjet": "Jet d'affaires", "heli": "Hélicoptère"}


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
    cats = {cid: dict(id=cid, title=tr(t), menu=m, groups=collections.OrderedDict(), note=tr(CAT_NOTES.get(cid, "")))
            for cid, t, m in CATS}
    for p in PARAMS:
        if p["key"] == "fullscreen" and is_pi():
            continue  # sur un Raspberry Pi, l'affichage est toujours en plein ecran
        if p["key"] == "max_aircraft" and is_zero():  # Pi Zero : plafond de l'historique
            p = dict(p, default=aircraft_types.HISTORY_ZERO_DEFAULT, help=HELP_HIST_ZERO)
        cur = state[p["file"]].get((p["sec"], p["key"]))
        raw = cur["value"] if cur else fmt_default(p["default"])
        out = dict(id=f'{p["file"]}:{p["sec"]}.{p["key"]}', cat=p["cat"], key=p["key"], type=p["type"], label=tr(p["label"]),
                   help=tr(p["help"]), options=p.get("options"), labels=p.get("labels"), needs_map=bool(p.get("needs_map")), apply=p["apply"],
                   default=fmt_default(p["default"]), present=cur is not None, min=p.get("min"), max=p.get("max"), step=p.get("step"), ui=p.get("ui"), unit=p.get("unit"),
                   editor=bool(p.get("editor")), secret=p["type"] == "secret", set=bool(cur and cur["value"]), value="" if p["type"] == "secret" else raw)
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
    cats["backup"].update(kind="backup", groups=[], file=None)
    cats["label"].update(kind="fields", editor=field_editor("label", LABEL_FIELDS, "label"))
    cats["panel"].update(kind="fields", editor=dict(field_editor("panel_content", PANEL_FIELDS, "panel", PANEL_SHOW_KEYS), note=tr(PANEL_NOTE)))
    cats["mapstyle"].update(kind="mapstyle", presets={k: dict(label=tr(v["label"]), colors=v["colors"]) for k, v in mapstyle.PRESETS.items()},
                            color_labels={k: tr(v) for k, v in mapstyle.COLOR_LABELS.items()}, color_keys=mapstyle.COLOR_KEYS,
                            layers=[dict(id=k, label=tr(v[1])) for k, v in mapstyle.LAYERS.items()], city_kinds=mapstyle.CITY_KINDS)
    cats["schedule"]["kind"] = "schedule"
    cats["sources"]["kind"] = "sources"
    cats["storage"]["kind"] = "storage"
    menu = []
    for gname in ("Général", "Programme", "Webadmin", "Intégrations"):
        items = []
        for cid, title, m in CATS:
            c = cats[cid]
            if m == gname and cid not in ("api", "tar1090", "online") and (cid in ("types", "backup") or c["groups"]):
                items.append(dict(id=cid, title=title))
        if items:
            menu.append(dict(group=tr(gname), items=items))
    for c in cats.values():
        if c.get("kind") not in ("types", "backup"):
            c["groups"] = [dict(name=tr(n), params=ps) for n, ps in c["groups"].items()]
    return dict(menu=menu, cats={k: v for k, v in cats.items() if v.get("kind") in ("types", "backup") or v["groups"]}, screen=_screen_info())


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
    if t == "color":
        if v and not mapstyle.color_ok(v):
            raise ValueError("couleur attendue, au format #rrggbb")
        return v.lower()
    if t == "choice":
        if v not in p["options"]:
            raise ValueError("choix possibles : " + ", ".join(p["options"]))
        return v
    if p["file"] == "config" and "%" in v:
        raise ValueError("le caractère % n'est pas autorisé dans config.ini")
    if p.get("slots"):
        return normalize_slots(v)
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
    if any(c.startswith("web:schedule.") for c in changed):
        SCHED["align"] = True
    if "config:general.language" in changed:
        S.reload()
        res["reload_ui"] = True
    res["port"] = S.PORT
    return res


# ---------------------------------------------------------------- sauvegarde et restauration
BACKUP_SECRETS = (("map", "carto_key"), ("server", "password"), ("mqtt", "password"))
BACKUP_MAX = 1024 * 1024
BACKUP_FILES = {"config.ini", "types_extra.txt", "runtime.json", "manifest.json", "map_meta.json", "background.png"}
BACKUP_MAP = ("map_meta.json", "background.png")  # carte deja construite : evite de la reconstruire (long sur un Pi Zero)
BACKUP_PNG_MAX = 8 * 1024 * 1024


def _read_text(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read()
    except OSError:
        return ""


def blank_secrets(text):
    sec, out = None, []
    for line in text.split("\n"):
        m = SEC_RE.match(line.strip())
        if m:
            sec = m.group(1)
        else:
            k = KEY_RE.match(line)
            if k and sec and (sec, k.group(2).lower()) in BACKUP_SECRETS:
                line = f"{k.group(1)}{k.group(2)} ="
        out.append(line)
    return "\n".join(out)


def build_backup(secrets):
    import io, zipfile
    buf = io.BytesIO()
    cfg = _read_text(INI_PATH)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("config.ini", cfg if secrets else blank_secrets(cfg))
        types = _read_text(S.TYPES_FILE)
        if types:
            z.writestr("types_extra.txt", types)
        rt = runtime_read()
        if rt:
            z.writestr("runtime.json", json.dumps({k: rt[k] for k in ("muted", "volume") if k in rt}))
        for name in BACKUP_MAP:
            try:
                with open(os.path.join(S.APP_DIR, name), "rb") as fh:
                    data = fh.read(BACKUP_PNG_MAX + 1)
            except OSError:
                continue
            if len(data) <= (BACKUP_PNG_MAX if name.endswith(".png") else BACKUP_MAX):
                z.writestr(name, data, compress_type=zipfile.ZIP_STORED if name.endswith(".png") else zipfile.ZIP_DEFLATED)
        cur = UPD.state().get("current") or {}
        z.writestr("manifest.json", json.dumps(dict(app="flightdisplay", version=cur.get("label", ""), host=socket.gethostname(),
                                                    created=time.strftime("%Y-%m-%dT%H:%M:%S%z"), secrets=bool(secrets))))
    return buf.getvalue()


def backup_filename():
    host = re.sub(r"[^A-Za-z0-9_.-]+", "-", socket.gethostname()) or "pi"
    return "flightdisplay-backup-%s-%s.zip" % (host, time.strftime("%Y%m%d-%H%M"))


def _set_in_text(text, sec, key, value):
    lines = text.split("\n")
    vals, secs = parse(lines)
    cur = vals.get((sec, key.lower()))
    if cur:
        lines[cur["line"]] = f'{cur["indent"]}{cur["orig"]} = {value}'
    elif sec in secs:
        lines.insert(secs[sec]["last"] + 1, f"{key} = {value}")
    else:
        lines += ["", f"[{sec}]", f"{key} = {value}"]
    return "\n".join(lines)


def restore_from_backup(blob):
    """Restaure une sauvegarde (zip) : config.ini, types_extra.txt, etat du son, carte."""
    import io, zipfile
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except (zipfile.BadZipFile, ValueError):
        raise ValueError("fichier de sauvegarde invalide")
    names = set(z.namelist())
    if "config.ini" not in names or not names <= BACKUP_FILES or any(i.file_size > (BACKUP_PNG_MAX if i.filename.endswith(".png") else BACKUP_MAX) for i in z.infolist()):
        raise ValueError("fichier de sauvegarde invalide")
    try:
        manifest = json.loads(z.read("manifest.json")) if "manifest.json" in names else {}
        if not isinstance(manifest, dict) or manifest.get("app", "flightdisplay") != "flightdisplay":
            raise ValueError
        cfg = z.read("config.ini").decode("utf-8-sig")
        configparser.ConfigParser(interpolation=None, strict=False).read_string(cfg)
        types = z.read("types_extra.txt").decode("utf-8-sig") if "types_extra.txt" in names else None
        rt = json.loads(z.read("runtime.json")) if "runtime.json" in names else None
        if rt is not None and not isinstance(rt, dict):
            raise ValueError
        meta = png = None
        if "map_meta.json" in names or "background.png" in names:  # la carte va avec son fichier de description, ou pas du tout
            meta = json.loads(z.read("map_meta.json"))
            png = z.read("background.png")
            if not isinstance(meta, dict) or not all(isinstance(meta.get(k), (int, float)) for k in ("lat", "lon", "mpp", "w", "h")):
                raise ValueError
            if png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR" or struct.unpack(">II", png[16:24]) != (int(meta["w"]), int(meta["h"])):
                raise ValueError
    except (ValueError, KeyError, UnicodeDecodeError, configparser.Error):
        raise ValueError("fichier de sauvegarde invalide")
    if types is not None:
        check_types(types)
    if manifest.get("secrets") is False:  # sauvegarde sans secrets : on garde ceux de cette installation
        cur, _ = parse(read_lines(INI_PATH))
        for sec, key in BACKUP_SECRETS:
            old = cur.get((sec, key))
            if old and old["value"]:
                cfg = _set_in_text(cfg, sec, key, old["value"])
    lang_before = S.LANG
    done = ["config.ini"]
    with file_lock:
        tmp = INI_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(cfg.rstrip("\n") + "\n")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, INI_PATH)
    if types is not None:
        write_types(types)
        done.append("types_extra.txt")
    if rt:
        sound_update({k: rt[k] for k in ("muted", "volume") if k in rt})
        done.append("runtime.json")
    if png is not None:
        for name, data in (("background.png", png), ("map_meta.json", json.dumps(meta).encode())):  # image d'abord : le programme lit les deux au demarrage
            tmp = os.path.join(S.APP_DIR, name + ".tmp")
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, os.path.join(S.APP_DIR, name))
            done.append(name)
    S.reload()
    MQTT.restart(S.ini)
    SCHED["align"] = True
    return dict(restored=done, restart_app=True, restart_web=(S.HOST, S.PORT) != BOUND, port=S.PORT, lang_changed=S.LANG != lang_before)


# ---------------------------------------------------------------- types d'avion
IGNORED_FILE = "types_ignored.txt"


def ignored_types():
    """Codes de type écartés de la liste « À classer » (données erronées : 0000, ZZZZ...), un par ligne dans types_ignored.txt."""
    try:
        with open(os.path.join(S.APP_DIR, IGNORED_FILE), encoding="utf-8") as fh:
            return sorted({l.strip().upper() for l in fh if re.fullmatch(r"[A-Za-z0-9]{2,6}", l.strip())})
    except OSError:
        return []


def ignored_save(code, restore=False):
    code = str(code or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,6}", code):
        raise ValueError("code de type invalide")
    cur = set(ignored_types())
    if restore:
        cur.discard(code)
    else:
        cur.add(code)
    path = os.path.join(S.APP_DIR, IGNORED_FILE)
    with file_lock:
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write("\n".join(sorted(cur)) + ("\n" if cur else ""))
        os.replace(path + ".tmp", path)


def unknown_types(known):
    found = []
    skip = set(ignored_types())
    for code in re.findall(r"type inconnu \(icone par defaut\) : (\S+)", journal(2000)):
        if code.upper() not in known and code.upper() not in skip and code not in found:
            found.append(code)
    return found


_desig = {"t": 0.0, "map": {}}
DESIG_URL = "https://en.wikipedia.org/w/api.php?action=parse&page=List_of_aircraft_type_designators&prop=text&format=json&formatversion=2"


def designators():
    """Table code ICAO -> nom du modele (liste publique de Wikipedia), gardee 24 h en memoire."""
    if _desig["map"] and time.time() - _desig["t"] < 86400:
        return _desig["map"]
    import urllib.request
    req = urllib.request.Request(DESIG_URL, headers={"User-Agent": "FlightDisplay/1.0 (webadmin)"})
    with urllib.request.urlopen(req, timeout=10) as r:
        html = json.load(r)["parse"]["text"]
    out = {}
    for code, name in re.findall(r"<tr>\s*<td>([A-Z0-9]{2,4})</td>\s*<td>[^<]*</td>\s*<td>(.*?)</td>", html, re.S):
        name = re.sub(r"<[^>]+>", "", name).strip()
        if name and code not in out:
            out[code] = name
    _desig.update(t=time.time(), map=out)
    return out


_icao = {"t": 0.0, "map": {}}
ICAO_URL = "https://doc8643.icao.int/external/aircrafttypes"


def icao_types():
    """Base officielle OACI des types d'avion (doc 8643) : {code: [fiches]}, gardee 24 h en memoire."""
    if _icao["map"] and time.time() - _icao["t"] < 86400:
        return _icao["map"]
    import urllib.request
    req = urllib.request.Request(ICAO_URL, data=b"", headers={"User-Agent": "FlightDisplay/1.0 (webadmin)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = json.load(r)
    out = {}
    for x in raw:
        try:
            out.setdefault(str(x["Designator"]).upper(), []).append(
                (str(x.get("ManufacturerCode") or ""), str(x.get("ModelFullName") or ""), str(x.get("AircraftDescription") or ""),
                 str(x.get("WTC") or ""), int(x["EngineCount"]) if str(x.get("EngineCount")).isdigit() else 1, str(x.get("EngineType") or "")))
        except (KeyError, ValueError):
            pass
    del raw
    _icao.update(t=time.time(), map=out)
    return out


def suggest_type(code):
    """Categorie probable : base OACI (fiable), sinon nom du modele vu ou liste Wikipedia (mots-cles)."""
    code = code.upper()
    failed = 0
    try:
        recs = icao_types().get(code)
        if recs:
            cat, model = aircraft_types.classify_icao(recs)
            return dict(code=code, model=model, suggest=cat, source="icao")
    except Exception:
        failed += 1
    model = next((e["model"] for e in seen_types() if e["code"] == code and e["model"]), "")
    if not model:
        try:
            model = designators().get(code, "")
        except Exception:
            failed += 1
    if failed == 2 and not model:
        raise OSError("hors ligne")
    return dict(code=code, model=model, suggest=aircraft_types.suggest(model) if model else None, source="web")


def seen_photo_file(code):
    """Nom du fichier de la derniere photo vue pour ce type (valide, present dans le cache) ou leve une erreur."""
    with open(os.path.join(S.APP_DIR, "cache", "types_seen.json"), encoding="utf-8") as fh:
        ph = str(json.load(fh)[code].get("photo") or "")
    if not re.fullmatch(r"[0-9a-f]{32}\.jpg", ph) or not os.path.exists(os.path.join(S.APP_DIR, "cache", ph)):
        raise OSError(ph)
    return ph


def seen_types():
    """Types vus au-dessus de la maison (compteur tenu par main.py), du plus frequent au plus rare."""
    try:
        with open(os.path.join(S.APP_DIR, "cache", "types_seen.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        out, skip = [], set(ignored_types())
        for k, v in d.items():
            if not isinstance(v, dict) or str(k).upper() in skip:
                continue
            ph = str(v.get("photo") or "")
            ok = bool(re.fullmatch(r"[0-9a-f]{32}\.jpg", ph)) and os.path.exists(os.path.join(S.APP_DIR, "cache", ph))
            model = str(v.get("model") or "")[:80]
            out.append(dict(code=str(k).upper(), n=int(v.get("n", 0)), t=int(v.get("t", 0)), model=model, reg=str(v.get("reg") or "")[:12],
                            photo=ok, suggest=aircraft_types.suggest(model)))
    except (OSError, ValueError):
        return []
    return sorted(out, key=lambda e: (-e["n"], e["code"]))


def read_types():
    try:
        with open(S.TYPES_FILE, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def check_types(text):
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


def write_types(text):
    check_types(text)
    path = S.TYPES_FILE
    with file_lock:
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


def live_info():
    """Etat en direct publie par main.py (None si le programme ne tourne pas) : fps, avions en vol, au sol, dans la zone d'alerte."""
    try:
        with open(FPS_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        if time.time() - float(d["t"]) > 8:
            return None
        return dict(fps=float(d["fps"]), aircraft=int(d.get("aircraft", 0)), ground=int(d.get("ground", 0)), zone=int(d.get("zone", 0)), paused=bool(d.get("paused")), sources=d.get("sources"))
    except Exception:
        return None


def fps_target():
    try:
        return int(parse(read_lines(S.CONFIG))[0][("display", "fps")]["value"])
    except Exception:
        return 10


def disk_info():
    """Occupation du disque qui contient l'application (meme calcul que df)."""
    try:
        u = shutil.disk_usage(S.APP_DIR)
    except OSError:
        return None
    base = u.used + u.free
    pct = round(100.0 * u.used / base, 1) if base else 0.0
    level = "critical" if pct >= S.STORAGE_WARN else ("warn" if pct >= S.STORAGE_WARN - 10 else "ok")
    return dict(total=u.total, used=u.used, free=u.free, pct=pct, level=level, warn=S.STORAGE_WARN)


PHOTO_EXT = (".jpg", ".jpeg")


def cache_stats():
    d = os.path.join(S.APP_DIR, "cache")
    photos = dict(count=0, bytes=0, oldest=None)
    other = 0
    try:
        for e in os.scandir(d):
            if not e.is_file():
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            if e.name.lower().endswith(PHOTO_EXT):
                photos["count"] += 1
                photos["bytes"] += st.st_size
                photos["oldest"] = st.st_mtime if photos["oldest"] is None else min(photos["oldest"], st.st_mtime)
            else:
                other += st.st_size
    except OSError:
        pass
    return dict(photos=photos, other=other, now=time.time())


_hl = {"v": None}  # (signature du fichier, liste, index par identifiant) : le fichier n'est relu que s'il a change


def _history_list():
    """Historique des avions (cache/history.json, ecrit par main.py). Garde en memoire tant que le fichier ne change pas :
    chaque photo de la page Avions vus le consultait, et le relire (1 000 avions) a chaque photo ralentissait beaucoup un Pi Zero."""
    p = os.path.join(S.APP_DIR, "cache", "history.json")
    try:
        st = os.stat(p)
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        return []
    v = _hl["v"]
    if v and v[0] == sig:
        return v[1]
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return []
    L = [e for e in d if isinstance(e, dict) and e.get("id")] if isinstance(d, list) else []
    _hl["v"] = (sig, L, {str(e["id"]): e for e in L})
    return L


def _history_entry(fid):
    _history_list()
    v = _hl["v"]
    return v[2].get(str(fid)) if v else None


_BRANDS = sorted(["Airbus Helicopters", "Airbus", "Boeing", "ATR", "Embraer", "Bombardier", "De Havilland Canada", "De Havilland", "Dassault", "Cessna",
                  "Pilatus", "Cirrus", "Beechcraft", "Beech", "Piper", "Diamond", "Gulfstream", "Learjet", "Fokker", "McDonnell Douglas", "Saab",
                  "Dornier", "Sukhoi", "Tupolev", "Ilyushin", "Antonov", "Mitsubishi", "Textron", "Robin", "Socata", "Daher", "Mooney", "Eurocopter",
                  "Leonardo", "Agusta", "AgustaWestland", "Bell", "Sikorsky", "Robinson", "Hawker", "Britten-Norman", "Comac", "Lockheed", "Canadair",
                  "Aerospatiale", "Aérospatiale", "British Aerospace", "BAe", "Avro", "Short", "Honda", "Quest", "Tecnam", "Extra", "Grob", "Zlin"],
                 key=lambda b: -len(b))


def split_model(model, code):
    """(constructeur, famille) : « Airbus A320-251N » -> (Airbus, A320) ; « Boeing 737-8AS » -> (Boeing, 737) ; « ATR 72-600 » -> (ATR, 72)."""
    m = (model or "").strip()
    if not m or m == "?":
        return "Inconnu", (code or "?")
    brand, rest = None, ""
    for b in _BRANDS:
        if m.lower() == b.lower() or m.lower().startswith(b.lower() + " "):
            brand, rest = b, m[len(b):].strip()
            break
    if brand is None:
        p = m.split(" ", 1)
        brand, rest = p[0], (p[1] if len(p) > 1 else "")
    words = rest.split()
    if not words:
        return brand, (code or brand)
    tok = words[0]
    parts = tok.split("-")
    pre = parts[0]
    if "-" in tok and any(c.isdigit() for c in pre):
        fam = pre                      # A320-251N, 737-8AS, 72-600 : on garde ce qui est avant le tiret
    elif len(parts) >= 3:
        fam = parts[0] + "-" + parts[1]  # DHC-8-402 -> DHC-8
    elif tok.isalpha() and len(words) > 1 and words[1][0].isdigit():
        fam = tok + " " + words[1].split("-")[0]   # ERJ 190-100 -> ERJ 190
    else:
        fam = tok                      # PC-12, Falcon, 172...
    fam = re.sub(r"(?i)(neo|ceo)$", "", fam) or fam   # A320neo -> A320
    return brand, fam


def history_data():
    """Avions vus (ecrits par main.py) : les plus recents d'abord, avec compteurs par immatriculation et statistiques."""
    L = sorted(_history_list(), key=lambda e: -e.get("t", 0))
    regs = collections.Counter()  # passages par immatriculation (un avion revu apres 2 h compte pour un nouveau passage)
    for e in L:
        if e.get("reg"):
            regs[aircraft_types.norm_reg(e["reg"])] += len(e.get("ps") or ()) or 1
    codes = collections.Counter(e.get("code") for e in L)
    label = lambda e: (e.get("model") if e.get("model") and e.get("model") != "?" else e.get("code")) or "?"
    types = collections.Counter(label(e) for e in L)
    airl = collections.Counter(re.sub(r"\s*\(.*$", "", e["airline"]).strip() for e in L if e.get("airline"))
    now = time.time()
    model_of = {}
    for e in L:
        if e.get("reg") and e["reg"] not in model_of:
            model_of[e["reg"]] = label(e)
    entries = []
    mine = perso_listing()
    xcat = dict(aircraft_types.BUILTIN); xcat.update(aircraft_types.read_extra(S.TYPES_FILE))  # type ICAO -> categorie (liste intégrée + types_extra.txt)
    manual = aircraft_types.read_manual(manual_path())
    try:
        lim = aircraft_types.history_limit(S.ini.get("history", "max_aircraft", fallback=""), pi_model())
    except configparser.Error:
        lim = aircraft_types.history_default(pi_model())
    for e in L[:lim]:
        mn = manual.get(str(e["id"]).lower()) or {}
        mcat, mcode, mmodel, mreg = mn.get("cat", ""), mn.get("code", ""), mn.get("model", ""), mn.get("reg", "")
        reg = mreg or aircraft_types.norm_reg(e.get("reg"), e.get("cs"))  # FHURY (indicatif) -> F-HURY ; l'immatriculation saisie à la main prime
        e = dict(e, code=mcode or e.get("code", ""), model=mmodel or e.get("model", ""), reg=reg)  # classement manuel : prime sur les données des sources
        ulm = mcat == "ulm" or (not mcat and aircraft_types.is_ulm(reg))
        br, fa = split_model(e.get("model"), e.get("code"))
        if ulm:  # immatriculation F-J : toujours rangé dans les ULM (filtre Constructeur), le constructeur d'origine passe dans la famille
            fa = (fa if br == "Inconnu" else (br + " " + fa).strip()) or "?"
            br = "ULM"
        mil = mcat == "mil" or (not mcat and not ulm and (bool(e.get("mil")) or xcat.get((e.get("code") or "").upper()) == "mil"))
        tc = not mcat and not ulm and not mil and (not e.get("code") or e.get("model") in ("", "?", None))  # type absent ou inconnu : à classer
        cat = mcat or ("ulm" if ulm else ("mil" if mil else xcat.get((e.get("code") or "").upper(), "")))  # categorie d'icone ('' : type inconnu)
        if mil:  # militaire (signale par une source, ou type militaire) : rangé sous « Militaire » dans le filtre Constructeur
            fa = (fa if br == "Inconnu" else (br + " " + fa).strip()) or "?"
            br = "Militaire"
        entries.append(dict(br=br, fa=fa, al=int(e.get("al") or 0), id=str(e["id"]), t=int(e.get("t", 0)), l=int(e.get("l", e.get("t", 0))), cs=e.get("cs", ""), reg=reg,
                            code=e.get("code", ""), model=e.get("model", ""), airline=e.get("airline", ""), frm=e.get("frm", ""), to=e.get("to", ""),
                            fi=e.get("fi", ""), ti=e.get("ti", ""), photo=bool(e.get("photo") or e.get("url")) or bool(perso_entry(e, mine)), credit=e.get("credit", ""), mp=perso_entry(e, mine), ulm=ulm, mil=mil, tc=tc, cat=cat, mc=mcat, mcode=mcode, mmodel=mmodel, mreg=mreg,
                            n=regs.get(e.get("reg"), 1) if e.get("reg") else 1, ps=[[int(p[0]), int(p[1]), int(p[2]) if len(p) > 2 else 0] for p in (e.get("ps") or ()) if isinstance(p, list) and len(p) >= 2][-20:], rare=codes.get(e.get("code"), 0) == 1,
                            src=[x for x in (e.get("src") or []) if x in sources.NAMES], ml=bool(e.get("mlat"))))
    stats = dict(total=len(L), regs=len(regs), airlines=len(airl), types=len(codes), today=sum(1 for e in L if now - e.get("t", 0) < 86400),
                 first=int(L[-1].get("t", 0)) if L else 0, top_airlines=airl.most_common(5), top_types=types.most_common(5),
                 regulars=[(r, model_of.get(r, "?"), n) for r, n in regs.most_common(5) if n > 1])
    return dict(entries=entries, stats=stats, now=now, cats=[[c, tr(TYPE_LABELS[c])] for c in TYPE_CATS],
                shapes={c: [[round(x, 2), round(y, 2)] for x, y in aircraft_types.SHAPES[c]] for c in TYPE_CATS})


def manual_path():
    return os.path.join(S.APP_DIR, aircraft_types.MANUAL_FILE)


def manual_save(fid, cat, code, model, reg=""):
    """Classement manuel d'un avion (icone, type ICAO, modele) : aircraft_manual.json, lu par main.py. Tout vide = on retire le classement."""
    fid = str(fid).lower()
    cat = cat if cat in TYPE_CATS else ""
    code = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())[:6]
    model = " ".join(str(model or "").split())[:80]
    reg = aircraft_types.norm_reg(re.sub(r"[^A-Za-z0-9-]", "", str(reg or ""))[:12])
    with file_lock:
        try:
            with open(manual_path(), encoding="utf-8") as fh:
                d = json.load(fh)
            d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            d = {}
        if cat or code or model or reg:
            d[fid] = {"cat": cat, "code": code, "model": model, "reg": reg}
        else:
            d.pop(fid, None)
        tmp = manual_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, manual_path())


def aircraft_lookup(fid):
    """Cherche le type, le modèle et l'immatriculation d'un avion de l'historique sur adsbdb.com, hexdb.io puis la base tar1090-db (gratuits, sans clé) : par adresse ICAO,
    puis par immatriculation (adsbdb seulement). Appelé par la fiche d'un avion à classer (l'adresse ICAO ou l'immatriculation sont alors envoyées
    à ces services)."""
    e = _history_entry(fid)
    if not e:
        raise ValueError("avion inconnu")
    reg = aircraft_types.norm_reg(e.get("reg"), e.get("cs"))
    cs = (e.get("cs") or "").strip().upper()
    hx = fid.lower() if re.fullmatch(r"[0-9a-fA-F]{6}", fid) else ""
    tries = []  # (service, fonction)
    if hx:
        tries += [("adsbdb.com", lambda: sources.adsbdb_details(hx, "")), ("hexdb.io", lambda: sources.hexdb_details(hx)),
                  ("tar1090-db", lambda: sources.tar1090db_lookup(hx, os.path.join(S.APP_DIR, "cache")))]
    if reg:
        tries.append(("adsbdb.com", lambda: sources.adsbdb_details(urllib.parse.quote(reg, safe="-"), "")))
    elif re.fullmatch(r"[A-Z0-9-]{4,7}", cs) and not re.fullmatch(r"[A-Z]{3}[0-9]{1,4}[A-Z]{0,2}", cs):
        tries.append(("adsbdb.com", lambda: sources.adsbdb_details(urllib.parse.quote(cs, safe="-"), "")))  # indicatif qui ressemble à une immatriculation
    if not tries:
        return dict(found=False, reg=reg)
    errors = 0
    for name, fn in tries:
        try:
            x = fn()
        except Exception:
            errors += 1
            continue
        if x.get("model") or x.get("code"):
            xcat = dict(aircraft_types.BUILTIN); xcat.update(aircraft_types.read_extra(S.TYPES_FILE))
            code = x.get("code") or ""
            cat = xcat.get(code) or aircraft_types.suggest(x.get("model"))
            if x.get("mil"):
                cat = "mil"  # la base de tar1090 le signale militaire
            if aircraft_types.is_ulm(x.get("reg") or reg):
                cat = "ulm"
            return dict(found=True, model=x.get("model") or "", code=code, reg=aircraft_types.norm_reg(x.get("reg") or reg), owner=x.get("owner") or "", cat=cat or "", source=name)
    if errors == len(tries):
        raise OSError("hors ligne")
    return dict(found=False, reg=reg)


HIST_DEL = "history_deleted.json"  # identifiants a retirer de l'historique : main.py les lit et les retire de sa memoire (sinon il reecrirait l'avion)


def history_delete(ids):
    """Retire des avions de l'historique (page Avions vus, onglet A classer) et oublie leur classement manuel."""
    ids = {str(i) for i in ids if re.fullmatch(r"[A-Za-z0-9:]{1,40}", str(i))}
    if not ids:
        raise ValueError("avion inconnu")
    base = os.path.join(S.APP_DIR, "cache")
    with file_lock:
        L = [e for e in _history_list() if str(e.get("id")) not in ids]
        tmp = os.path.join(base, "history.json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(L, fh)
        os.replace(tmp, os.path.join(base, "history.json"))
        try:
            with open(os.path.join(base, HIST_DEL), encoding="utf-8") as fh:
                old = json.load(fh)
        except (OSError, ValueError):
            old = []
        with open(os.path.join(base, HIST_DEL), "w", encoding="utf-8") as fh:
            json.dump(sorted(set(str(x) for x in (old if isinstance(old, list) else [])) | ids), fh)
    for i in ids:
        manual_save(i, "", "", "")


def perso_dir():
    return os.path.join(S.APP_DIR, aircraft_types.PERSO_DIR)


def perso_listing():
    """{nom de fichier: date de modification} des photos personnelles."""
    try:
        return {n: int(os.path.getmtime(os.path.join(perso_dir(), n))) for n in os.listdir(perso_dir()) if n.endswith(".jpg")}
    except OSError:
        return {}


def perso_entry(e, listing=None):
    """Date de modification de la photo personnelle d'une entree de l'historique (0 si elle n'en a pas)."""
    listing = perso_listing() if listing is None else listing
    for n in aircraft_types.perso_names(str(e.get("id", "")), e.get("reg")):
        if n in listing:
            return listing[n]
    return 0


def _eff_reg(e):
    """Immatriculation d'une entree de l'historique : celle saisie a la main (classement manuel) si elle existe, sinon celle des sources."""
    mn = aircraft_types.read_manual(manual_path()).get(str(e.get("id", "")).lower()) or {}
    return mn.get("reg") or e.get("reg")


def perso_save(fid, data_b64, remove=False):
    """Enregistre (ou retire) la photo personnelle de l'avion fid de l'historique."""
    e = _history_entry(fid)
    if not e:
        raise ValueError("avion inconnu")
    names = aircraft_types.perso_names(fid, _eff_reg(e))
    if not names:
        raise ValueError("cet avion n'a ni adresse ICAO ni immatriculation : photo impossible")
    if remove:
        for n in names:
            try:
                os.remove(os.path.join(perso_dir(), n))
            except OSError:
                pass
        return
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except Exception:
        raise ValueError("image invalide")
    if len(raw) > 3 * 1024 * 1024 or raw[:3] != b"\xff\xd8\xff":
        raise ValueError("image invalide : un JPEG de 3 Mo au plus est attendu")
    os.makedirs(perso_dir(), exist_ok=True)
    tmp = os.path.join(perso_dir(), names[0] + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(raw)
    os.replace(tmp, os.path.join(perso_dir(), names[0]))


def history_photo(fid):
    """Photo d'un avion de l'historique : celle du cache, sinon retelechargee depuis son adresse (apres un nettoyage du cache)."""
    e = _history_entry(fid)
    if not e:
        return None
    cache = os.path.join(S.APP_DIR, "cache")
    for n in aircraft_types.perso_names(fid, _eff_reg(e)):  # photo personnelle : prioritaire
        try:
            with open(os.path.join(perso_dir(), n), "rb") as fh:
                return fh.read()
        except OSError:
            pass
    name = str(e.get("photo") or "")
    if re.fullmatch(r"[0-9a-f]{32}\.jpg", name):
        try:
            with open(os.path.join(cache, name), "rb") as fh:
                return fh.read()
        except OSError:
            pass
    url = str(e.get("url") or "")
    if not url.startswith("https://"):
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15) as r:
            data = r.read(4000001)
    except Exception:
        return None
    if len(data) > 4000000 or data[:3] != b"\xff\xd8\xff":
        return None
    try:
        with open(os.path.join(cache, hashlib.md5(url.encode()).hexdigest() + ".jpg"), "wb") as fh:
            fh.write(data)
    except OSError:
        pass
    return data


def storage_info():
    return dict(disk=disk_info(), cache=cache_stats(),
                clean=dict(auto=S.CLEAN_AUTO, quota=S.CLEAN_MAX_MB * 1024 * 1024, log=list(reversed(clean_log_read()[-30:]))))


CLEAN_LOG_MAX = 100
clean_lock = threading.Lock()


def _clean_log_path():
    return os.path.join(S.APP_DIR, "cache", "cleanup.json")  # .json : le programme ne le supprime pas avec les vieux fichiers


def clean_log_read():
    try:
        with open(_clean_log_path(), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def clean_log_add(entry):
    """Inscrit un nettoyage dans le journal (fichier du cache) et dans le journal du service."""
    with clean_lock:
        d = clean_log_read()[-(CLEAN_LOG_MAX - 1):] + [entry]
        try:
            os.makedirs(os.path.dirname(_clean_log_path()), exist_ok=True)
            tmp = _clean_log_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(d, fh)
            os.replace(tmp, _clean_log_path())
        except OSError:
            pass
    print("nettoyage du cache (%s) : %d photo(s) supprimee(s), %d octets liberes, cache %d -> %d octets, quota %d"
          % (entry.get("kind"), entry.get("count", 0), entry.get("bytes", 0), entry.get("before", 0), entry.get("after", 0), entry.get("quota", 0)), flush=True)


def clear_photo_cache():
    d = os.path.join(S.APP_DIR, "cache")
    n = b = 0
    try:
        for e in os.scandir(d):
            if e.is_file() and e.name.lower().endswith(PHOTO_EXT):
                try:
                    size = e.stat().st_size
                    os.remove(e.path)
                    n, b = n + 1, b + size
                except OSError:
                    pass
    except OSError:
        pass
    if n:
        clean_log_add(dict(t=time.time(), kind="manual", count=n, bytes=b, before=b, after=0, quota=0))
    return n, b


def auto_clean_cache():
    """Au-dela du quota, supprime les photos les plus anciennes jusqu'a 80 % du quota (les plus recentes sont gardees)."""
    if not S.CLEAN_AUTO:
        return None
    quota = S.CLEAN_MAX_MB * 1024 * 1024
    files, total = [], 0
    try:
        for e in os.scandir(os.path.join(S.APP_DIR, "cache")):
            if e.is_file() and e.name.lower().endswith(PHOTO_EXT):
                try:
                    st = e.stat()
                except OSError:
                    continue
                files.append((st.st_mtime, st.st_size, e.path))
                total += st.st_size
    except OSError:
        return None
    if total <= quota:
        return None
    target, n, b = int(quota * 0.8), 0, 0
    for _, size, path in sorted(files):
        if total - b <= target:
            break
        try:
            os.remove(path)
            n, b = n + 1, b + size
        except OSError:
            pass
    entry = dict(t=time.time(), kind="auto", count=n, bytes=b, before=total, after=total - b, quota=quota)
    clean_log_add(entry)
    return entry


def cache_loop():
    time.sleep(60)
    while True:
        try:
            auto_clean_cache()
        except Exception:
            pass
        time.sleep(86400)  # une verification par jour suffit


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
    """Ecran en veille (le programme d'affichage continue de tourner, sans dessiner)."""
    return os.path.exists(S.SCREEN_FLAG)


_helper_ver = {"t": 0.0, "v": None}


def screen_helper_version():
    """Version du script de veille (installe par install.sh) : 2 = le programme continue de tourner pendant la veille ; autre = ancien script."""
    if time.time() - _helper_ver["t"] > 300:
        _helper_ver["t"] = time.time()
        try:
            r = subprocess.run([S.SCREEN_HELPER, "version"], capture_output=True, text=True, timeout=5)
            _helper_ver["v"] = int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else 1
        except (OSError, subprocess.SubprocessError, ValueError):
            _helper_ver["v"] = None
    return _helper_ver["v"]


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

_pi_model = []


def is_zero():
    return "zero" in pi_model().lower()


def pi_model():
    if not _pi_model:
        name = ""
        for f in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
            try:
                with open(f, "rb") as fh:
                    name = fh.read().replace(b"\0", b"").decode("utf-8", "replace").strip()
                break
            except OSError:
                continue
        _pi_model.append(name)
    return _pi_model[0]


_screen_last = []


def screen_resolution():
    """Plus grande resolution annoncee par l'ecran branche (modes DRM du noyau) ; None hors Raspberry Pi."""
    best = None
    try:
        for d in sorted(os.listdir("/sys/class/drm")):
            base = os.path.join("/sys/class/drm", d)
            try:
                with open(os.path.join(base, "status")) as fh:
                    if fh.read().strip() != "connected":
                        continue
                with open(os.path.join(base, "modes")) as fh:
                    modes = fh.read().split()
            except OSError:
                continue
            for m in modes:
                mm = re.fullmatch(r"(\d{3,5})x(\d{3,5})", m)
                if mm:
                    w, h = int(mm.group(1)), int(mm.group(2))
                    if best is None or w * h > best[0] * best[1]:
                        best = (w, h)
    except OSError:
        pass
    if best:
        _screen_last[:] = [best]
    elif _screen_last:
        best = _screen_last[0]  # ecran en veille : on garde la derniere valeur connue
    return dict(width=best[0], height=best[1]) if best else None


def _screen_info():
    r = screen_resolution()
    if r:
        r["zero"] = "zero" in pi_model().lower()
    return r


def is_pi():
    return "raspberry pi" in pi_model().lower()


def temp_limits():
    """Limites thermiques du SoC d'apres la documentation Raspberry Pi : le micrologiciel ralentit les coeurs Arm des 80 °C
    (60 °C sur les Pi 3 B+ / 3 A+ / CM3+, limite douce par defaut) et plafonne le SoC a 85 °C sur tous les modeles."""
    model = pi_model()
    soft = 60 if re.search(r"(Pi 3 Model [AB] Plus|Compute Module 3 Plus)", model) else 80
    return dict(model=model, soft=soft, hard=85)


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
            if stopped or rc == 0:
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


mapprev = dict(running=False, error="", started=0.0, proc=None, cancel=False, lines=collections.deque(maxlen=200))
mapprev_lock = threading.Lock()


def mapprev_dir():
    return os.path.join(S.APP_DIR, "cache", "mapprev")


def mapprev_state():
    """Etat du dernier apercu : les images presentes sur le disque (elles survivent a un redemarrage) et le travail en cours."""
    info, t = {}, 0.0
    try:
        p = os.path.join(mapprev_dir(), "preview.json")
        with open(p, encoding="utf-8") as fh:
            info = json.load(fh)
        t = os.path.getmtime(p)
    except (OSError, ValueError):
        pass
    files = [f for f in info.get("files", []) if os.path.exists(os.path.join(mapprev_dir(), f))]
    thumbs = [f for f in info.get("thumb_files", []) if os.path.exists(os.path.join(mapprev_dir(), f))]
    with mapprev_lock:
        m = mapprev
        return dict(running=m["running"], error=tr(m["error"]) if m["error"] else "", files=files, thumb_files=thumbs, geo=info.get("geo"),
                    thumbs_geo=info.get("thumbs_geo") if thumbs else None, t=t,
                    elapsed=int(time.time() - m["started"]) if m["running"] else 0, lines=list(m["lines"])[-60:])


def _mapprev_worker(req):
    d = mapprev_dir()
    err = ""
    log = mapprev["lines"].append
    try:
        os.makedirs(d, exist_ok=True)
        tiles = os.path.join(d, "tiles")
        if os.path.isdir(tiles) and len(os.listdir(tiles)) > 300:  # le cache de tuiles ne doit pas grossir sans limite
            shutil.rmtree(tiles, ignore_errors=True)
        p = subprocess.Popen([S.PYTHON, "-u", S.BUILD_SCRIPT, "--preview", d], cwd=S.APP_DIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1, errors="replace")
        mapprev["proc"] = p
        p.stdin.write(json.dumps(req))
        p.stdin.close()
        watchdog = threading.Timer(900, p.kill)  # filet de securite : un aperçu ne doit jamais rester bloque
        watchdog.start()
        try:
            for line in p.stdout:
                log(line.rstrip())
            rc = p.wait()
        finally:
            watchdog.cancel()
        if mapprev["cancel"]:
            err = "Aperçu annulé."
        elif rc != 0:
            last = [l for l in list(mapprev["lines"])[-6:] if l.strip()][-3:]
            err = "L'aperçu n'a pas pu être généré : " + " / ".join(last)[-300:]
    except Exception as e:
        err = "L'aperçu n'a pas pu être généré : " + str(e)
    with mapprev_lock:
        mapprev.update(running=False, error=err, proc=None)


def cancel_mapprev():
    p = mapprev.get("proc")
    if not mapprev["running"] or p is None:
        raise ValueError("aucun aperçu en cours")
    mapprev["cancel"] = True
    p.terminate()


def start_mapprev(body):
    def num(k, lo, hi, cast=float):
        try:
            v = cast(body.get(k))
        except (TypeError, ValueError):
            raise ValueError("valeur invalide : " + k)
        if not (lo <= v <= hi) or (cast is float and not math.isfinite(v)):
            raise ValueError("valeur invalide : " + k)
        return v
    req = dict(lat=num("lat", -90, 90), lon=num("lon", -180, 180), radius_km=num("radius_km", 1, 200), width=num("width", 320, 7680, int),
               height=num("height", 240, 4320, int))
    style = body.get("style") if isinstance(body.get("style"), dict) else {}
    req["style"] = {k: style[k] for k in ("preset", "colors", "show", "road_width") if k in style}
    c = body.get("cities") if isinstance(body.get("cities"), dict) else {}
    req["cities"] = dict(show=bool(c.get("show", True)), kinds=[k for k in (c.get("kinds") or []) if k in mapstyle.CITY_KINDS],
                         max_labels=max(0, min(200, int(c.get("max_labels", 25)))), font_size=max(8, min(60, int(c.get("font_size", 20)))))
    req["presets"] = [k for k in (body.get("presets") or []) if k in mapstyle.PRESETS]
    if not os.path.exists(os.path.join(S.APP_DIR, S.BUILD_SCRIPT)):
        raise ValueError(S.BUILD_SCRIPT + " introuvable dans " + S.APP_DIR)
    if build["running"] or UPD.running():
        raise ValueError("une construction de la carte ou une mise à jour est en cours")
    if not parse(read_lines(INI_PATH))[0].get(("map", "carto_key"), {}).get("value"):
        raise ValueError("La clé API CARTO n'est pas renseignée (Carte et position, Fond de carte) : l'aperçu en a besoin.")
    with mapprev_lock:
        if mapprev["running"]:
            raise ValueError("un aperçu est déjà en cours de génération")
        mapprev.update(running=True, error="", started=time.time(), cancel=False)
        mapprev["lines"].clear()
    threading.Thread(target=_mapprev_worker, args=(req,), daemon=True).start()


def journal(lines):
    ok, out = run([S.JOURNALCTL, "-u", S.SERVICE, "-n", str(lines), "--no-pager", "-o", "short-iso", "-q"], 15)
    if not ok and not out:
        out = tr("journal indisponible")
    return out


def self_restart():
    try:
        MQTT.stop()
    except Exception:
        pass
    os.execv(sys.executable, [sys.executable] + sys.argv)


SCHED = dict(last=None, align=False, error="", action=None)


def sched_wanted(lt=None):
    """True si le planning veut l'ecran allume a l'instant donne."""
    lt = lt or time.localtime()
    return S.SCHEDULE_MAP[lt.tm_wday * 1440 + lt.tm_hour * 60 + lt.tm_min]


def sched_status():
    if not S.SCHEDULE_ENABLED:
        return dict(enabled=False)
    t = time.time()
    lt = time.localtime(t)
    pos = lt.tm_wday * 1440 + lt.tm_hour * 60 + lt.tm_min
    wanted = S.SCHEDULE_MAP[pos]
    nxt = None
    for add in range(1, 10081):
        if S.SCHEDULE_MAP[(pos + add) % 10080] != wanted:
            nxt = add
            break
    return dict(enabled=True, wanted=wanted, next_to=(not wanted) if nxt else None,
                next_epoch=(t - lt.tm_sec + nxt * 60) if nxt else None, error=tr(SCHED["error"]) if SCHED["error"] else "",
                action=SCHED["action"])


def sched_apply(want):
    if build["running"] or UPD.running():
        return False  # on reessaie au prochain passage
    ok, out = screen_cmd("on" if want else "off")
    if ok:
        SCHED["error"] = ""
        SCHED["action"] = dict(to=bool(want), epoch=time.time())
    else:
        detail = ((out or "?").splitlines() or ["?"])[0][:120]
        SCHED["error"] = ("échec du réveil de l'écran : {0}" if want else "échec de la mise en veille de l'écran : {0}").replace("{0}", detail)
    return True


def sched_tick():
    if not S.SCHEDULE_ENABLED:
        SCHED["last"] = None
        return
    want = sched_wanted()
    if SCHED["align"]:  # planning venant d'etre enregistre : on aligne l'ecran tout de suite
        if want != (not screen_off()) and not sched_apply(want):
            return
        SCHED["align"], SCHED["last"] = False, want
    elif SCHED["last"] is None:  # demarrage de webadmin : on ne force rien
        SCHED["last"] = want
    elif want != SCHED["last"] and sched_apply(want):  # l'action ne se declenche qu'aux heures programmees
        SCHED["last"] = want


def sched_loop():
    while True:
        try:
            sched_tick()
        except Exception as e:
            SCHED["error"] = "planning : {0}".replace("{0}", str(e))
        time.sleep(15)


def now_info():
    t = time.time()
    lt = time.localtime(t)
    return dict(epoch=t, offset=(lt.tm_gmtoff or 0) // 60, tz=lt.tm_zone or "")


UPD = webadmin_update.Updater(S, svc_state, screen_off, lambda: build["running"], self_restart)
MQTT = webadmin_mqtt.Bridge(dict(sysinfo=sysinfo, sound_state=sound_state, sound_update=sound_update,
                                 screen_off=screen_off, screen=screen_cmd, live=live_info, disk=disk_info,
                                 cpu=lambda: cpu["pct"], service_active=lambda: svc_state() == "active"))


_page_cache = {}


def page_bytes():
    """(page, page compressee) : construites une fois par langue, puis gardees en memoire."""
    tab = i18n.js_table()
    key = (S.LANG, tab.get("lang"), len(tab.get("strings") or ()))
    v = _page_cache.get("v")
    if not v or v[0] != key:
        data = PAGE.replace("__I18N__", json.dumps(tab, ensure_ascii=False).replace("</", "<\\/")).replace('<html lang="fr">', '<html lang="%s">' % S.LANG).encode("utf-8")
        v = _page_cache["v"] = (key, data, gzip.compress(data, 9))
    return v[1], v[2]


class Handler(BaseHTTPRequestHandler):
    server_version = "FlightAdmin"

    def log_message(self, fmt, *args):
        pass

    def accepts_gzip(self):
        return "gzip" in (self.headers.get("Accept-Encoding") or "").lower()

    def send_json(self, obj, code=200):
        if isinstance(obj, dict):
            for k in ("error", "message"):
                if isinstance(obj.get(k), str):
                    obj[k] = tr(obj[k])
        data = json.dumps(obj).encode()
        gz = len(data) > 4096 and self.accepts_gzip()  # grosses reponses (historique) : compressees, bien plus rapides sur le Wi-Fi d'un Pi Zero
        if gz:
            data = gzip.compress(data, 3)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if gz:
            self.send_header("Content-Encoding", "gzip")
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
        body = tr("Authentification requise").encode()
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
                data, gzdata = page_bytes()  # page toute prete et compressee, gardee en memoire (200 Ko : lente a envoyer sur le Wi-Fi d'un Pi Zero)
                gz = self.accepts_gzip()
                data = gzdata if gz else data
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                if gz:
                    self.send_header("Content-Encoding", "gzip")
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
                s["update_can"] = UPD.can_update()
                s["update_running"] = UPD.running()
                s["cpu"] = cpu["pct"]
                s["now"] = now_info()
                s["temp_limits"] = temp_limits()
                s["disk"] = disk_info()
                s["schedule"] = sched_status()
                s["fps"] = fps_info() if s["service"] == "active" else None
                s["fps_target"] = fps_target()
                s["boot"] = BOOT_ID
                lv = live_info()
                s["paused"] = bool(lv and lv.get("paused"))
                s["helper_old"] = screen_helper_version() is not None and screen_helper_version() < 2
                s["sources"] = lv.get("sources") if lv else None
                self.send_json(s)
            elif u.path == "/api/settings":
                self.send_json(get_settings())
            elif u.path == "/api/types":
                text = read_types()
                extra = aircraft_types.read_extra(S.TYPES_FILE)
                known = set(aircraft_types.BUILTIN) | set(extra)
                shapes = {c: [[round(x, 2), round(y, 2)] for x, y in aircraft_types.SHAPES[c]] for c in TYPE_CATS}
                self.send_json(dict(text=text, categories=TYPE_CATS, labels={c: tr(TYPE_LABELS[c]) for c in TYPE_CATS}, shapes=shapes,
                                    builtin=aircraft_types.BUILTIN, extra=extra, seen=seen_types(), unknown=unknown_types(known), ignored=ignored_types()))
            elif u.path == "/api/types/suggest":
                code = parse_qs(u.query).get("code", [""])[0]
                if not re.fullmatch(r"[A-Za-z0-9]{2,6}", code):
                    return self.send_json({"error": "code de type invalide"}, 400)
                try:
                    self.send_json(suggest_type(code))
                except Exception:
                    self.send_json({"error": "Recherche impossible (pas d'accès à internet ?)"}, 502)
            elif u.path == "/api/aircraft/lookup":
                fid = parse_qs(u.query).get("id", [""])[0]
                if not re.fullmatch(r"[A-Za-z0-9:]{1,40}", fid):
                    return self.send_json({"error": "avion inconnu"}, 400)
                try:
                    self.send_json(aircraft_lookup(fid))
                except ValueError as ex:
                    self.send_json({"error": str(ex)}, 404)
                except Exception:
                    self.send_json({"error": "Recherche impossible (pas d'accès à internet ?)"}, 502)
            elif u.path == "/api/types/photo":
                code = parse_qs(u.query).get("code", [""])[0].upper()
                try:
                    with open(os.path.join(S.APP_DIR, "cache", seen_photo_file(code)), "rb") as fh:
                        data = fh.read()
                except Exception:
                    return self.send_json({"error": "photo introuvable"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=300")
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/api/mapstyle/preview":
                self.send_json(mapprev_state())
            elif u.path == "/api/mapstyle/current":
                try:
                    p = os.path.join(S.APP_DIR, "background.png")
                    with open(p, "rb") as fh:
                        data = fh.read()
                    mt = os.path.getmtime(p)
                except OSError:
                    return self.send_json({"error": "aucune carte"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Last-Modified", email.utils.formatdate(mt, usegmt=True))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/api/mapstyle/theme":
                tid = parse_qs(u.query).get("id", [""])[0]
                if tid not in mapstyle.PRESETS:
                    return self.send_json({"error": "thème inconnu"}, 404)
                try:
                    with open(os.path.join(S.APP_DIR, "defaults", "themes", tid + ".png"), "rb") as fh:
                        data = fh.read()
                except OSError:
                    return self.send_json({"error": "image introuvable"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/api/mapstyle/img":
                name = parse_qs(u.query).get("name", [""])[0]
                if not re.fullmatch(r"(current|preset_[a-z]+)\.png", name):
                    return self.send_json({"error": "image introuvable"}, 404)
                try:
                    with open(os.path.join(mapprev_dir(), name), "rb") as fh:
                        data = fh.read()
                except OSError:
                    return self.send_json({"error": "image introuvable"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/api/logs":
                n = int(parse_qs(u.query).get("lines", ["300"])[0])
                self.send_json({"text": journal(max(10, min(n, 2000)))})
            elif u.path == "/api/backup":
                secrets = parse_qs(u.query).get("secrets", ["0"])[0] == "1"
                if secrets and self.headers.get("X-Admin") != "1":
                    return self.send_json({"error": "requête refusée"}, 403)
                data = build_backup(secrets)
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % backup_filename())
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/api/history":
                self.send_json(history_data())
            elif u.path == "/api/history/photo":
                fid = parse_qs(u.query).get("id", [""])[0]
                data = history_photo(fid) if re.fullmatch(r"[A-Za-z0-9]{1,32}", fid) else None
                if data is None:
                    return self.send_json({"error": "photo introuvable"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/api/storage":
                self.send_json(storage_info())
            elif u.path == "/api/update":
                self.send_json(UPD.state())
            elif u.path == "/api/build":
                self.send_json(dict(running=build["running"], rc=build["rc"], default_stop=S.BUILD_STOP_DISPLAY,
                                    text="\n".join(tr(l) for l in list(build["lines"])[-400:])))
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
            path = urlparse(self.path).path
            if n > (14 * 1024 * 1024 if path == "/api/backup/restore" else (5 * 1024 * 1024 if path == "/api/myphoto" else 65536)):
                return self.send_json({"error": "requête trop grande"}, 413)
            body = json.loads(self.rfile.read(n) or b"{}")
            act = str(body.get("action", ""))
            if path == "/api/settings":
                res = apply_settings(body.get("changes") or {})
                if any(str(k).startswith("web:storage.") for k in res.get("changed", [])):
                    threading.Thread(target=auto_clean_cache, daemon=True).start()  # nettoyage tout de suite si le quota est deja depasse
                return self.send_json(dict(ok=True, **res))
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
            if path == "/api/mapstyle/preview":
                start_mapprev(body)
                return self.send_json(dict(ok=True))
            if path == "/api/mapstyle/cancel":
                cancel_mapprev()
                return self.send_json(dict(ok=True))
            if path == "/api/build/cancel":
                cancel_build()
                return self.send_json(dict(ok=True))
            if path == "/api/backup/restore":
                try:
                    blob = base64.b64decode(str(body.get("data", "")), validate=True)
                except Exception:
                    raise ValueError("fichier de sauvegarde invalide")
                return self.send_json(dict(ok=True, **restore_from_backup(blob)))
            if path == "/api/storage/clear":
                n, b = clear_photo_cache()
                return self.send_json(dict(ok=True, count=n, bytes=b))
            if path == "/api/update/check":
                UPD.check()
                return self.send_json(UPD.state())
            if path == "/api/update/rollback":
                UPD.rollback(body.get("hash"))
                return self.send_json(dict(ok=True))
            if path == "/api/update/start":
                UPD.start()
                return self.send_json(dict(ok=True))
            if path == "/api/sources/test":
                url = str(body.get("url", "")).strip()
                if body.get("source") in sources.ONLINE:  # service en ligne : l'adresse est construite avec la position de la carte
                    try:
                        km = float(body.get("radius_km") or 20)
                        url = sources.online_url(body["source"], float(body["lat"]), float(body["lon"]), km * 1.5 / 1.852)
                    except (KeyError, TypeError, ValueError):
                        raise ValueError("position invalide : renseignez la latitude et la longitude dans « Carte et position »")
                if not re.match(r"^https?://[^\s]+$", url):
                    raise ValueError("adresse invalide : elle doit commencer par http:// ou https://")
                try:
                    code_, d = sources.http_json(url, 6)
                except Exception as e:
                    raise ValueError(str(e)[:160])
                if code_ == 404:
                    raise ValueError("page introuvable (404) : vérifiez le chemin du fichier")
                items = (d.get("aircraft") if "aircraft" in d else d.get("ac")) if isinstance(d, dict) else None
                if not isinstance(items, list):
                    raise ValueError("ce n'est pas un fichier aircraft.json (pas de liste « aircraft » ni « ac »)")
                return self.send_json(dict(ok=True, total=len(items), positions=sum(1 for a in items if a.get("lat") is not None and a.get("lon") is not None),
                                           has_db=any(a.get("r") or a.get("t") for a in items)))
            if path == "/api/history/delete":
                ids = body.get("ids")
                if not isinstance(ids, list) or len(ids) > 500:
                    raise ValueError("liste d'avions invalide")
                history_delete(ids)
                return self.send_json(dict(ok=True))
            if path == "/api/types/ignore":
                ignored_save(body.get("code", ""), bool(body.get("restore")))
                return self.send_json(dict(ok=True))
            if path == "/api/aircraft/manual":
                fid = str(body.get("id", ""))
                if not re.fullmatch(r"[A-Za-z0-9:]{1,40}", fid):
                    raise ValueError("avion inconnu")
                manual_save(fid, str(body.get("cat", "")), body.get("code", ""), body.get("model", ""), body.get("reg", ""))
                return self.send_json(dict(ok=True))
            if path == "/api/myphoto":
                fid = str(body.get("id", ""))
                if not re.fullmatch(r"[A-Za-z0-9:]{1,40}", fid):
                    raise ValueError("avion inconnu")
                perso_save(fid, body.get("data", ""), bool(body.get("remove")))
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
#offline{position:fixed;left:0;right:0;bottom:0;top:56px;background:var(--bg);z-index:40;display:none;align-items:center;justify-content:center;text-align:center;padding:20px}
#offline .offbox{max-width:420px}#offline h2{margin:14px 0 6px;font-size:20px}#offline p{margin:0 0 6px;color:var(--mut);font-size:14px}#offline .offs{color:var(--txt);font-size:15px;margin-top:10px}
.offring{width:132px;height:132px}.offring circle{fill:none;stroke-width:8}.offring .offbg{stroke:#243040}.offring .offfg{stroke:var(--acc);stroke-linecap:round;stroke-dasharray:326.7;stroke-dashoffset:0;transition:stroke-dashoffset 1s linear}.offring text{fill:var(--txt);font-size:34px;font-weight:600}
.offring.try .offfg{animation:offspin 1.1s linear infinite;stroke-dasharray:90 237;transition:none}@keyframes offspin{to{stroke-dashoffset:-326.7}}
.srcs{display:flex;flex-direction:column;gap:10px;margin:6px 0 14px}.src{border:1px solid var(--line);border-radius:12px;background:#0e141b;padding:12px 14px}.src.off{opacity:.65}
.src .sh{display:flex;align-items:center;gap:10px}.src .st{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px}.src .rk{flex:none;width:26px;height:26px;border-radius:50%;background:#1b2431;border:1px solid var(--line);display:grid;place-items:center;font-size:13px;font-weight:600}
.src .sd{margin:8px 0;color:var(--mut);font-size:13px}.sft{display:flex;gap:8px;flex-wrap:wrap}
.sst{font-size:12px;color:var(--mut)}.sst.ok{color:#7ad49a}.sst.bad{color:#ff8a80}
.sf{display:flex;flex-direction:column;gap:4px;margin:8px 0}.sf label{font-size:12px;color:var(--mut)}.sres{margin-top:8px;font-size:13px;color:var(--mut)}.sres.ok{color:#7ad49a}.sres.bad{color:#ff8a80}
.opts{display:flex;flex-direction:column;gap:8px;margin:6px 0 14px}.opt{display:block;width:100%;text-align:left;border:1px solid var(--line);border-radius:10px;background:#0e141b;color:var(--txt);padding:10px 12px;cursor:pointer;font:inherit}.opt:hover{border-color:#3a4a60}.opt.on{border-color:var(--acc);background:#13202e}
.opt b{display:block;font-size:14px}.opt small{display:block;margin-top:3px;color:var(--mut);font-size:12.5px;line-height:1.4}.opts.chg .opt.on{box-shadow:0 0 0 1px var(--acc)}
.srcmode.dim{opacity:.5}.srcul{margin:6px 0 14px;padding-left:20px;color:var(--mut);font-size:13px;line-height:1.5}.srcul b{color:var(--txt)}
.srctab{width:100%;border-collapse:collapse;font-size:12.5px;margin:6px 0 14px}.srctab th{color:var(--mut);font-weight:600;text-align:left;padding:6px;border-bottom:1px solid var(--line)}.srctab td{padding:6px;border-bottom:1px solid #1b2431;vertical-align:top}.srctab tr.cur td{background:#13202e}
.hfbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 10px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 12px}.hfbar .hsp{flex:1}.hfbar small{color:var(--mut)}
.hfl{flex:0 0 100%;display:flex;align-items:center;gap:7px;font-size:12px;font-weight:600;color:var(--acc);text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}.hfl svg{width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.hmw{position:relative}.hchip{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);background:#1b2431;color:var(--txt);border-radius:10px;padding:8px 14px;font-size:14px;cursor:pointer;white-space:nowrap}
.hchip:hover{border-color:#3a4c63}.hchip.on{background:#13202e;border-color:var(--acc)}.hchip.al.on{background:#4a1a17;border-color:#8a2f29;color:#ffb4ae}.hchip.clr{background:none;color:var(--mut)}
.hchip em{font-style:normal;background:var(--acc);color:#1a1400;border-radius:99px;padding:0 7px;font-size:11.5px;font-weight:700}
.hpop{position:absolute;z-index:30;top:calc(100% + 6px);left:0;width:280px;max-width:calc(100vw - 32px);background:#0e141b;border:1px solid #3b5d8c;border-radius:12px;padding:8px;box-shadow:0 12px 34px #000a}
.hpop input{width:100%;margin-bottom:6px;padding:7px 10px;font-size:14px;border-radius:8px;border:1px solid var(--line);background:#0b1017;color:var(--txt)}
.hpl{max-height:320px;overflow:auto;display:flex;flex-direction:column;gap:1px}
.hpi2{display:flex;align-items:center;gap:9px;width:100%;text-align:left;border:0;background:none;color:var(--mut);padding:6px 8px;border-radius:7px;font-size:14px;cursor:pointer}
.hpi2:hover{background:#172539}.hpi2.on{background:#172539;color:var(--txt)}.hpi2.sub{padding-left:30px;font-size:13px}.hpi2 span.t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.hpi2 b{font-weight:400;opacity:.7;font-size:12px}
.hpi2 svg{flex:none;color:#9db4cf}.hbox{width:16px;height:16px;border:1.5px solid #4a6285;border-radius:4px;flex:none;display:grid;place-items:center}.hpi2.on .hbox{background:#5aa2ff;border-color:#5aa2ff}.hpi2.on .hbox:after{content:"✓";color:#06101c;font-size:11px;font-weight:700;line-height:1}
.hrad{width:16px;height:16px;border:1.5px solid #4a6285;border-radius:50%;flex:none}.hpi2.on .hrad{border-color:#5aa2ff;background:radial-gradient(#5aa2ff 40%,transparent 45%)}
.hact{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}.hact:empty{display:none}
.htok{display:inline-flex;align-items:center;gap:6px;background:#1d2d45;border:1px solid #33507a;color:#cfe0f7;border-radius:8px;padding:3px 6px 3px 10px;font-size:13px}.htok button{border:0;background:none;color:#9db4cf;cursor:pointer;padding:0 3px;font-size:13px}.htok button:hover{color:#fff}
.hmode button{padding:6px 10px;display:inline-flex}.hmode svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.hmain{flex:1;min-width:0}
.hpager{display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin:12px 0}.hpager .hpi{color:var(--mut);font-size:13px;margin-right:8px}.hpager .hpe{color:var(--mut);padding:0 4px}
.hpg{min-width:34px;height:34px;padding:0 8px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--txt);font-size:14px;cursor:pointer}.hpg:hover:not(:disabled){border-color:#3a4c63}.hpg.on{background:#2c3a4d;border-color:var(--acc);font-weight:600}.hpg:disabled{opacity:.35;cursor:default}
.hrows{display:flex;flex-direction:column;gap:6px}
.hrow{display:grid;grid-template-columns:64px minmax(0,1.15fr) minmax(0,1.6fr) 92px 74px 150px;align-items:center;gap:10px;width:100%;text-align:left;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:6px 10px 6px 6px;color:var(--txt);cursor:pointer}
.hrow:hover{border-color:#3a4c63}.hrow .hrt{position:relative;width:64px;height:42px;border-radius:8px;overflow:hidden;background:#0e141b;display:flex;align-items:center;justify-content:center;color:#3f5269;font-size:20px}.hrow .hrt img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.hrow b{display:block;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.hrow small{display:block;color:var(--mut);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.hrow code{font:12px ui-monospace,Consolas,monospace}.hrow .hbadges{position:static;justify-content:flex-end;align-content:center;gap:3px}.hrow .hbadge{font-size:10px;padding:1px 6px}.hrow .hroutel b{white-space:normal;line-height:1.25}
@media(max-width:820px){.hrow{grid-template-columns:64px minmax(0,1fr) 92px}.hrow>:nth-child(3),.hrow>:nth-child(4){display:none}}
.hbadge.mlat{background:#16303a;border-color:#2f7186;color:#8fd8ee}.hbadge.multi{background:#2a1d44;border-color:#5b3f96;color:#c9b2f5}.hbadge.alert{background:#4a1a17;border-color:#8a2f29;color:#ffb4ae}.hbadge.cnt{background:#243040;border-color:#3a4a5f;color:#c4cfdc}
.hbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:4px 0 12px}.hbar input[type=search]{flex:1 1 200px;min-width:0;padding:9px 12px;font-size:14px;border-radius:9px;border:1px solid var(--line);background:#0e141b;color:var(--txt)}
.hgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:10px}
.hcard{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;cursor:pointer;text-align:left;color:var(--txt);padding:0;display:flex;flex-direction:column;transition:transform .12s,border-color .12s}
.hcard:hover{transform:translateY(-2px);border-color:#3a4c63}
.hph{position:relative;aspect-ratio:16/10;background:#0e141b;display:flex;align-items:center;justify-content:center;font-size:44px;color:#3f5269;overflow:hidden}
.hph img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block}
.hbadges{position:absolute;left:6px;top:6px;display:flex;gap:4px;flex-wrap:wrap;z-index:1}
.hbadge{font-size:11px;padding:2px 7px;border-radius:99px;background:#0b0f14d9;border:1px solid var(--line);color:var(--txt)}
.hbadge.new{background:#14391f;border-color:#1f6b3a;color:#7ee2a0}.hbadge.rare{background:#3a2e0a;border-color:#7a5f10;color:var(--acc)}.hbadge.reg{background:#1b2c44;border-color:#2f5385;color:#9ec3f5}
.hbody{padding:9px 11px 11px}.hbody b{display:block;font-size:15px;line-height:1.25}.hbody .ha{font-size:12px;color:var(--mut);margin-top:2px}
.hroute{display:flex;align-items:center;flex-wrap:wrap;gap:2px 6px;margin-top:7px;font-size:13px}.hroute span{min-width:0;overflow-wrap:anywhere}.hroute i{font-style:normal;color:var(--acc);flex:none}
.hmeta{display:flex;justify-content:space-between;gap:6px;margin-top:7px;font-size:11px;color:var(--mut)}.hmeta code{font:11px ui-monospace,Consolas,monospace;color:var(--txt)}
.hover{position:fixed;inset:0;background:#05080cd9;z-index:30;display:flex;align-items:center;justify-content:center;padding:12px}
.hsheet{background:var(--card);border:1px solid var(--line);border-radius:16px;max-width:560px;width:100%;max-height:94vh;overflow:auto}.hsheet .hph{font-size:60px}
.hsc{padding:14px 16px 16px}.hsc h3{margin:0;font-size:20px}.hsc .ha{color:var(--mut);margin-top:2px}.hcr{font-size:11px;color:var(--mut);margin-top:6px}
.hdl{display:grid;grid-template-columns:auto 1fr;gap:6px 14px;margin:12px 0;font-size:14px}.hdl dt{color:var(--mut)}.hdl dd{margin:0;min-width:0;overflow-wrap:anywhere}
.hnav{display:flex;gap:8px;flex-wrap:wrap}
.htabs{display:flex;border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-top:4px}
.htabs button{flex:1;background:none;border:0;border-radius:0;padding:10px 4px;color:var(--mut);font:inherit;font-size:13px;cursor:pointer}
.htabs button.on{color:var(--acc);box-shadow:inset 0 -2px var(--acc)}.hdot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--acc);margin-left:6px;vertical-align:middle}
.htp{padding:12px 16px 16px}.cblk .cact{margin:8px 0}
.hcls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:12px 0}.hcls small{flex:1 0 100%;color:var(--mut)}.hcls .hnote{min-height:1em}
.cls2{display:grid;grid-template-columns:minmax(150px,230px) minmax(0,1fr);gap:12px;align-items:start}@media(max-width:700px){.cls2{grid-template-columns:minmax(0,1fr)}}
.cli{display:flex;justify-content:space-between;gap:8px;width:100%;text-align:left;background:none;border:0;border-top:1px solid var(--line);color:var(--txt);padding:10px 8px;cursor:pointer;font:inherit}.cli:first-child{border-top:0}
.cli small{color:var(--mut)}.cli.on{background:var(--card2);border-radius:8px}
.cpn h3{margin:0 0 6px;font-size:17px}.ckv{display:grid;grid-template-columns:130px minmax(0,1fr);gap:3px 10px;font-size:13px;margin:8px 0}.ckv i{font-style:normal;color:var(--mut)}.ckv .q{color:var(--mut);opacity:.6}
.csg{background:rgba(52,199,89,.1);border:1px solid rgba(52,199,89,.35);color:#7ee2a0;border-radius:8px;padding:8px 10px;font-size:13px;margin:10px 0}.csg.none{background:var(--card2);border-color:var(--line);color:var(--mut)}
.cact{display:flex;gap:8px;flex-wrap:wrap}.cact .dg{border-color:rgba(248,81,73,.5);color:#ff8a84}.cact .p,.hcls .p{border-color:rgba(255,210,80,.5);color:var(--acc)}
.clnk{display:flex;gap:14px;flex-wrap:wrap;margin-top:12px}.lk{background:none;border:0;color:var(--mut);padding:0;font:inherit;font-size:12px;cursor:pointer;text-decoration:underline}.hcls select,.hcls input{background:var(--card2);color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:7px 9px;min-width:0;flex:1 1 150px}
.hx{position:absolute;top:8px;right:8px;z-index:2;width:30px;height:30px;padding:0;border-radius:50%;border:1px solid var(--line);background:#0b0f14d9;color:var(--txt);font-size:14px;cursor:pointer}
.hbt{display:inline-flex;align-items:center;justify-content:center;width:28px;height:24px;margin-left:8px;padding:0;vertical-align:middle;border-radius:7px;border:1px solid var(--line);background:#1b2431;color:var(--txt);cursor:pointer}.hbt:hover,.hbt.on{border-color:var(--acc)}
.hht{margin:2px 0 14px;overflow:auto;background:#0e141b;border:1px solid var(--line);border-radius:10px;padding:6px 8px}.hht h5{margin:2px 0 6px;font-size:12px;color:var(--mut);font-weight:600}
.htab{width:100%;border-collapse:collapse;font-size:12px}.htab th{color:var(--mut);font-weight:600;text-align:left;padding:4px 6px;border-bottom:1px solid var(--line);white-space:nowrap}.htab td{padding:5px 6px;border-bottom:1px solid #1b2431;vertical-align:top}.htab tr:last-child td{border-bottom:0}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:6px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 13px}
.tile small{display:block;color:var(--mut);font-size:12px;margin-bottom:2px}
.tile b{font-size:20px;font-weight:600}
.tile.ok b{color:var(--ok)}.tile.bad b{color:var(--bad)}.tile.warn b{color:var(--warn)}
.tile i{white-space:pre-line;display:block;font-style:normal;color:var(--mut);font-size:12px;margin-top:1px}
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
.cm:first-child{border-top:0}.cm code{white-space:nowrap;color:var(--mut);font:12px ui-monospace,Menlo,Consolas,monospace;flex:none;padding-top:2px}.cm span:nth-child(2){flex:1;min-width:0}.cm .chip{flex:none;align-self:flex-start}.cm .b{flex:none;align-self:flex-start;padding:3px 10px;font-size:12px}
.lprev.sticky{z-index:4}
.lprev{display:inline-block;background:#0a0e14;border:1px solid var(--line);border-radius:6px;padding:6px 10px;margin:4px 4px 10px;line-height:1.3}
.lrow{padding:10px 14px;border-top:1px solid var(--line)}.lrow:first-child{border-top:0}
.lrow .top{display:flex;align-items:center;gap:8px}.lrow .top b{flex:1;font-weight:500}
.lrow .opt{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;align-items:center}.lrow.off .opt{opacity:.45}
.lrow button.b.s{padding:6px 12px}.lrow button.b.s.on{background:var(--acc);color:#1a1400;border-color:var(--acc)}
.vh{display:flex;align-items:center;gap:8px;padding:11px 14px;margin-top:10px;background:var(--card2);border:1px solid var(--line);border-radius:10px 10px 0 0;cursor:pointer;user-select:none}
.vh.shut{border-radius:10px}.vh b{font-weight:600}.vh small{margin-left:auto;color:var(--mut);font-size:12px;text-align:right}
.vh .chev{color:var(--mut);transition:transform .15s}.vh.shut .chev{transform:rotate(-90deg)}
.vb{background:var(--card);border:1px solid var(--line);border-top:0;border-radius:0 0 10px 10px;overflow:hidden}
.hr{display:flex;align-items:center;gap:10px;justify-content:flex-end;min-width:0}
.crl{font-size:12px;color:var(--mut);white-space:nowrap}
.cl{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:6px}.cl a{color:var(--acc);font-size:14px}
.cal{border:1px solid var(--line);border-radius:12px;background:var(--card);overflow:hidden;user-select:none;-webkit-user-select:none}
.calh,.calb{display:grid;grid-template-columns:40px repeat(7,minmax(0,1fr))}
.calh{background:var(--card2);border-bottom:1px solid var(--line)}
.calday{position:relative;text-align:center;padding:9px 0 8px;font-size:13px;color:var(--txt);border-left:1px solid var(--line)}
.calday.today{color:var(--acc);font-weight:600}
.calcp{position:absolute;right:1px;top:1px;border:0;background:none;color:var(--mut);font-size:12px;padding:2px 3px;cursor:pointer;line-height:1}
.calhr{font-size:10px;color:var(--mut);text-align:right;padding-right:5px;box-sizing:border-box;position:relative;top:-6px}
.calcol{position:relative;border-left:1px solid var(--line);background-image:repeating-linear-gradient(to bottom,#2a3646 0,#2a3646 1px,transparent 1px,transparent 40px),repeating-linear-gradient(to bottom,transparent 0,transparent 20px,#1c2531 20px,#1c2531 21px,transparent 21px,transparent 40px)}
.blk span{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:13px;font-size:10px}
.blk{position:absolute;left:2px;right:2px;background:#2563b0;border:1px solid #5b9cf0;border-radius:6px;color:#fff;font-size:11px;line-height:1.2;overflow:hidden;touch-action:none;cursor:grab;box-sizing:border-box;padding:2px 4px}
.blk.ghost{opacity:.55;pointer-events:none}.blk.drag{opacity:.85;z-index:6;cursor:grabbing;box-shadow:0 2px 10px #0008}
.rh{position:absolute;left:0;right:0;height:9px;cursor:ns-resize;touch-action:none}.rh.t{top:0}.rh.b{bottom:0}
.bx{position:absolute;right:1px;top:1px;border:0;background:#0004;color:#fff;border-radius:4px;font-size:10px;line-height:1;padding:2px 4px;cursor:pointer}
.nowl{position:absolute;left:0;right:0;height:0;border-top:2px solid var(--bad);z-index:5;pointer-events:none}
.nowl::before{content:"";position:absolute;left:-4px;top:-5px;width:8px;height:8px;border-radius:50%;background:var(--bad)}
.sbar{position:relative;height:22px;border-radius:99px;background:#0e141b;border:1px solid var(--line);overflow:hidden;margin:6px 0 4px}
.sbar i{position:absolute;top:0;bottom:0;left:0}
.sbar .su{background:var(--ok)}.sbar.warn .su{background:var(--warn)}.sbar.critical .su{background:var(--bad)}
.sbar .sp{background:#5b9cf0;z-index:1}
.sbar .sw{width:2px;background:#fff;opacity:.85;z-index:2}
.sleg{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--mut);margin-bottom:6px}
.sleg span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px;background:var(--ok)}
.sleg .l-p::before{background:#5b9cf0}.sleg .l-w::before{background:#fff;width:3px;border-radius:0}
.sleg.warn .l-u::before{background:var(--warn)}.sleg.critical .l-u::before{background:var(--bad)}
.tile.ring{display:flex;align-items:center;gap:12px}
.tile.ring.bad{border-color:#6b2420}.tile.ring.warn{border-color:#5a4410}
.ring svg{flex:none}.ring .rb{stroke:#0e141b}.ring .rg{stroke:var(--ok);transition:stroke-dasharray .5s}
.ring.warn .rg{stroke:var(--warn)}.ring.bad .rg{stroke:var(--bad)}
.ring text{fill:var(--txt);font-size:12px;font-weight:600}
.ring .ri{min-width:0}.ring .ri i{font-size:13px;color:var(--txt);margin-top:3px}.ring.bad .ri i{color:#ffb4ae}
.ucard{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:10px}
.ucard.bad{border-color:#6b2420}
.urow{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.uver{font-size:22px;font-weight:600}.uver.new{color:var(--ok)}.uarr{color:var(--mut);margin:0 8px;font-size:18px}
.usub{font-size:12px;color:var(--mut);margin-top:4px}
.ubtns{display:flex;gap:8px}
.ucm{display:inline-flex;flex-direction:column;align-items:flex-start;gap:2px}.ucm small{font-size:10px;line-height:1;color:var(--mut);margin-left:7px;letter-spacing:.03em}.ucm .chip{font-family:ui-monospace,Consolas,monospace;font-size:11px;padding:2px 8px}
.ulab{margin:0 0 2px}.uvr{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.ubig{font-size:28px;font-weight:600;line-height:1.1}
.ustat{font-size:14px;margin-top:8px;display:flex;gap:7px;align-items:baseline}.ustat.new{color:var(--ok)}.ustat.bad{color:#ffb4ae}
.uside{display:flex;flex-direction:column;align-items:flex-end;gap:6px}
.ulink{background:none;border:0;color:var(--mut);font-size:12px;padding:2px;cursor:pointer;text-decoration:underline}
.umeta{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;margin-top:12px;padding-top:10px;border-top:1px solid var(--line);font-size:12px;color:var(--mut)}.umeta .ulink{margin-left:auto}
@media(max-width:520px){.uside{width:100%;align-items:stretch}.uside .ulink{align-self:center}}
.urun{display:flex;align-items:center;gap:18px}.urun svg{flex:none}.urinfo{min-width:0;flex:1}
.urbg{fill:none;stroke:#243040;stroke-width:8}.urfg{fill:none;stroke:var(--acc);stroke-width:8;stroke-linecap:round;transition:stroke-dasharray .5s}
.urun text{fill:var(--txt);font-size:16px;font-weight:600}
.urvs{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.urvs .chip{font-family:ui-monospace,Consolas,monospace;font-size:11px}.urvs .uarr{margin:0;font-size:14px}
.urstep{font-size:17px;font-weight:600;margin-top:8px}
@media(max-width:420px){.urun{gap:12px}.urun svg{width:68px;height:68px}}
.runstep{font-size:14px;margin-top:10px}.runstep.err{color:#ffb4ae}
.utog{color:var(--mut);font-size:12px;margin-top:10px;cursor:pointer;user-select:none}
.utog .chev{display:inline-block;transition:transform .15s;margin-right:6px}.utog .chev.shut{transform:rotate(-90deg)}
.ulast{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 14px;display:flex;align-items:center;flex-wrap:wrap;gap:10px;cursor:pointer;margin-bottom:10px;font-size:14px;user-select:none}
.ulast.bad{border-color:#6b2420}.ulast .ic{color:var(--ok)}.ulast.bad .ic{color:var(--bad)}.ulast .more{margin-left:auto;color:var(--mut);font-size:12px;white-space:nowrap}
.chip.upd{display:inline-flex;align-items:center;cursor:pointer}
.chip .uico{display:inline-flex;align-items:center;max-width:0;overflow:hidden;opacity:0;margin:0;padding:0;border:0;background:var(--ok);color:#06210f;border-radius:99px;font-size:12px;line-height:1;height:18px;cursor:pointer;transition:max-width .2s,opacity .2s,margin .2s,padding .2s}
.chip.upd:hover .uico,.chip.upd:focus-within .uico{max-width:28px;opacity:1;margin-left:7px;padding:0 6px}
@media(hover:none){.chip .uico{max-width:28px;opacity:1;margin-left:7px;padding:0 6px}}
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
.bar.on{display:block}.bar .in{max-width:1100px;margin:0 auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap}.bar .in span{flex:1 1 100%;font-size:12px;color:var(--mut)}.bar .in #barTxt{font-size:14px;font-weight:600;color:var(--txt)}.bar .in button{flex:1}
.hint{background:#2a2108;border:1px solid #5a4410;color:#f0d78c;padding:10px 12px;border-radius:10px;margin-bottom:12px;display:none;font-size:14px}
.hint .btns{display:flex;gap:8px;margin-top:8px}.hint .btns button{flex:1}
.tools{display:flex;gap:8px;margin-bottom:8px;align-items:center}.tools>*{flex:1}
.mpbig{height:380px;border-radius:12px;border:1px solid var(--line);margin:10px 0;overflow:hidden;background:#0e141b}
.mpbig .leaflet-tile-pane{filter:invert(1) hue-rotate(180deg) brightness(.8) saturate(.55)}
.mpbig.leaflet-container,.mpprev.leaflet-container{background:#161d24}  /* Safari iOS laisse voir le fond entre les tuiles pendant le zoom : un fond sombre au lieu du gris clair de Leaflet */
.sl.mprad{width:100%;max-width:640px}.mprad{margin:8px 0}.mprad b{flex:none;margin-right:10px;min-width:84px;font-weight:500}.mprad input{flex:1}
.mpcnt{display:flex;align-items:center;gap:6px}.mpcnt button{width:34px;height:34px;padding:0;border-radius:8px;border:1px solid var(--line);background:#1b2431;color:var(--txt);font-size:18px;line-height:1}.mpcnt span{min-width:30px;text-align:center;font-variant-numeric:tabular-nums}
.mppv{width:100%;max-width:640px;border-radius:10px;border:1px solid var(--line);overflow:hidden;background:#0e141b;margin:8px 0}
.mpprev{width:100%;height:100%}.mpprev .leaflet-tile-pane{filter:invert(1) hue-rotate(180deg) brightness(.72) saturate(.5)}
.mpring span{display:block;text-align:center;font:11px/14px inherit;color:#e6edf3;text-shadow:0 0 3px #000,0 0 3px #000}
.mppin i{display:block;width:22px;height:22px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);background:#ffd250;border:2px solid #111;box-sizing:border-box}
.leaflet-container{font:12px/1.4 inherit}
.msprev{width:100%;max-width:760px;aspect-ratio:16/9;border-radius:10px;border:1px solid var(--line);overflow:hidden;background:#0e141b;margin:8px 0}
.msimg{width:100%;height:100%;display:block;object-fit:cover}
.msthemes{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:8px 0}
.mscard{display:flex;flex-direction:column;gap:6px;text-align:left;border:1px solid var(--line);background:var(--card2);color:var(--txt);border-radius:12px;padding:8px;cursor:pointer;font-size:13px}
.mscard.on{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)}
.msth{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:8px;display:block}
.msw{display:flex;gap:3px}.msw i{flex:1;height:8px;border-radius:3px;display:block}
.kinds{display:flex;gap:6px;flex-wrap:wrap}.kinds .tcode{padding:5px 12px;font:13px inherit}
.mscolors{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin:8px 0 12px}
.mscol{display:flex;align-items:center;gap:8px;font-size:13px}.mscol input[type=color]{width:34px;height:28px;padding:0;border:1px solid var(--line);border-radius:6px;background:none;flex:none}.mscol span{flex:1}
.mscol .b{padding:2px 8px;flex:none}
.note.err{color:var(--bad)}
.mslogbox{margin:6px 0}.mslogbox summary{cursor:pointer;color:var(--mut);font-size:13px}.mslog{max-height:200px;overflow:auto;font:12px ui-monospace,Menlo,Consolas,monospace;background:#0b1118;border:1px solid var(--line);border-radius:8px;padding:8px;white-space:pre-wrap;margin:6px 0}
.colpick{display:flex;align-items:center;gap:8px}.colpick input[type=color]{width:44px;height:32px;padding:0;border:1px solid var(--line);border-radius:6px;background:none}.colpick .b{padding:2px 8px}
.tools.v{flex-direction:column;align-items:stretch;margin-top:8px}
.tools select,.tools input[type=text]{padding:9px 10px;font-size:14px}
.cols{display:block}
.tools input[type=search]{padding:9px 10px;font-size:14px;width:100%;border-radius:9px;border:1px solid var(--line);background:#0e141b;color:var(--txt)}
.tlist{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 4px}
.tcode{border:1px solid var(--line);background:var(--card2);color:var(--txt);border-radius:8px;padding:3px 8px;font:12px ui-monospace,Menlo,Consolas,monospace;cursor:pointer}
.tcode.seen{background:rgba(52,199,89,.18);border-color:var(--ok)}.tcode.mod{border-color:var(--acc)}.tcode.on{background:var(--acc);color:#111}
.tcard{border:1px solid var(--line);background:var(--card);border-radius:12px;margin:8px 0;padding:0 12px}
.tcard summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.tcard summary::-webkit-details-marker{display:none}
.tcard summary small{color:var(--mut);margin-left:auto}.tcard[open]>summary{border-bottom:1px solid var(--line)}.tcard .tlist{margin-bottom:10px}
.tcard svg,.tcl svg,.tcat svg{color:var(--txt);flex:none}
.tcl{padding:10px 0;border-top:.5px solid var(--line)}.tcl:first-child{border-top:0}
.tvh{display:flex;align-items:center;gap:12px;cursor:pointer;flex-wrap:wrap}.tvh .lt{flex:1;min-width:160px}.tacts{display:flex;gap:6px;flex-wrap:wrap}
.tsug.none{background:var(--card2);color:var(--mut)}
.tsug{display:inline-block;margin-top:4px;background:rgba(210,153,34,.18);color:var(--warn);border-radius:8px;padding:2px 8px;font-size:12px}
.tdet{margin:10px 0 4px}.tdtop{display:flex;gap:14px;flex-wrap:wrap}.tdtx{flex:1;min-width:220px}.tdt{font-weight:600;font-size:16px}
.tph{width:200px;max-width:100%;height:130px;object-fit:cover;border-radius:8px;border:1px solid var(--line);flex:none}
.tcats{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:8px;margin:8px 0}
.tcat{display:flex;flex-direction:column;align-items:center;gap:4px;border:1px solid var(--line);background:var(--card2);color:var(--txt);border-radius:10px;padding:8px 4px;font-size:12px;cursor:pointer}
.tcat.on{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)}
.tpick{margin-bottom:12px}
.tcol{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.tcol button{border:1px solid var(--line);background:var(--card2);color:var(--txt);border-radius:99px;padding:5px 12px;font:13px ui-monospace,Menlo,Consolas,monospace}
#toast{position:fixed;left:50%;top:calc(70px + env(safe-area-inset-top));transform:translateX(-50%);background:#1f2937;border:1px solid var(--line);padding:10px 16px;border-radius:10px;z-index:20;display:none;max-width:90vw;font-size:14px}
#toast.bad{border-color:var(--bad);color:#ffb4ae}
@media(min-width:860px){
.tiles{grid-template-columns:repeat(4,minmax(0,1fr))}
.tile b{font-size:18px;overflow-wrap:anywhere}
  .cols{display:grid;grid-template-columns:1fr 1fr;gap:0 16px;align-items:start}
  nav{position:static;max-width:1100px;margin:0 auto;border:0;background:none;backdrop-filter:none;justify-content:flex-start;gap:6px;padding:10px 12px 0}
  nav button{flex:none;padding:8px 18px;border-radius:99px;font-size:15px}
  nav button.on{background:var(--card2)}
  main{padding-bottom:110px}
  .set{display:grid;grid-template-columns:230px 1fr;gap:22px;align-items:start}
  .lprev.sticky{position:sticky;top:62px;box-shadow:0 6px 14px #000a}
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
<header><h1>Flight display</h1><div class="hr"><div class="chips" id="chips"></div><a href="#" class="crl" onclick="go('credits');return false">Crédits</a></div></header>
<nav id="nav">
  <button data-t="home" class="on" onclick="go('home')">Pilotage</button>
  <button data-t="hist" onclick="go('hist')">Avions vus</button>
  <button data-t="cfg" onclick="go('cfg')">Réglages</button>
  <button data-t="upd" id="navUpd" onclick="go('upd')">Mises à jour</button>
  <button data-t="log" onclick="go('log')">Logs</button>
</nav>
<main>
<section class="tab on" id="t-home">
  <div class="hint" id="helperWarn">Le script de veille de l'écran est ancien : la veille arrête encore le programme d'affichage. Relancez l'installeur en conservant la configuration (cd ~/flightdisplay &amp;&amp; bash install.sh) pour que le programme continue de tourner pendant la veille.</div>
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

<section class="tab" id="t-hist"></section>

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
    <div class="li"><div class="lt"><b>Arrêter l'affichage pendant la construction</b><small>Libère la mémoire du Pi Zero.</small></div><label class="tg"><input type="checkbox" id="stopDisp"><span></span></label></div>
    <div class="li stack"><div class="btns"><button class="b p" id="buildBtn" onclick="startBuild()">Reconstruire la carte</button><button class="b d" id="cancelBtn" onclick="cancelBuild()" style="display:none">Annuler</button></div></div>
  </div>
  <div class="chips" style="margin:0 0 8px;justify-content:flex-start"><span class="chip" id="buildState">inactif</span></div>
  <pre id="buildOut">Aucune construction lancée.</pre>
</div></div>

<section class="tab" id="t-upd">
  <div class="hint" id="updWarn"></div>
  <div class="ucard" id="updSummary"></div>
  <div class="ucard" id="updRun" style="display:none">
    <div class="urun">
      <svg width="84" height="84" viewBox="0 0 84 84" role="img" aria-label="Progression"><circle class="urbg" cx="42" cy="42" r="34"/><circle class="urfg" id="runArc" cx="42" cy="42" r="34" transform="rotate(-90 42 42)" stroke-dasharray="0 214"/><text id="runPct" x="42" y="47" text-anchor="middle"></text></svg>
      <div class="urinfo">
        <div class="urvs" id="runVer"></div>
        <div class="urstep" id="runT"></div>
        <div class="usub" id="runStep"></div>
        <div class="utog" id="logTog"></div>
      </div>
    </div>
  </div>
  <div class="ulast" id="lastRow" style="display:none"></div>
  <div class="list" id="updSteps" style="display:none"></div>
  <pre id="updOut" style="display:none"></pre>
  <div id="updNew" style="display:none">
    <h2 class="t">Historique des versions</h2>
    <div class="list" id="updCommits" style="background:none;border:0"></div>
  </div>
</section>

<section class="tab" id="t-credits">
  <div class="catt"><h3>Crédits et licences</h3></div>
  <p class="note">Flight display s'appuie sur des données, des services et des bibliothèques de tiers.</p>
  <div class="list">
    <div class="li stack"><div class="lt"><b>Cartes</b><small>Fond de carte vectoriel, affiché en permanence en bas à droite de l'écran.</small>
      <div class="cl"><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a><a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">© CARTO</a></div></div></div>
    <div class="li stack"><div class="lt"><b>Données de vol</b><small>Flightradar24, via la bibliothèque non officielle FlightRadarAPI. Usage personnel et non commercial uniquement.</small>
      <div class="cl"><a href="https://www.flightradar24.com/terms-of-service" target="_blank" rel="noopener noreferrer">Flightradar24</a><a href="https://github.com/JeanExtreme002/FlightRadarAPI" target="_blank" rel="noopener noreferrer">FlightRadarAPI</a></div></div></div>
    <div class="li stack"><div class="lt"><b>Photos</b><small>© leurs auteurs, via JetPhotos. Le crédit du photographe est visible dans l'image.</small>
      <div class="cl"><a href="https://www.jetphotos.com" target="_blank" rel="noopener noreferrer">JetPhotos</a></div></div></div>
    <div class="li stack"><div class="lt"><b>Bibliothèques</b><small>pygame (LGPL), requests (Apache 2.0), Pillow (MIT-CMU), paho-mqtt (EPL 2.0 ou BSD 3-Clause), polices DejaVu. Dans webadmin : Leaflet (BSD 2-Clause), pour la carte de choix de la position.</small></div></div>
  </div>
  <div class="grid" style="margin-top:12px">
    <a style="text-align:center;text-decoration:none;display:block;padding:12px;border-radius:10px;border:1px solid var(--line);background:#1b2431;color:var(--txt);font-size:16px" href="https://github.com/arcalulu/flightdisplay/blob/main/CREDITS.md" target="_blank" rel="noopener noreferrer">Conditions et licences en détail</a>
    <button class="b" onclick="go('home')">Retour</button>
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

<div class="bar" id="saveBar"><div class="in"><span id="barTxt"></span><span id="barHelp"></span>
  <button class="b p" id="barSave" onclick="saveSettings()">Enregistrer</button>
  <button class="b" style="flex:none;width:auto" onclick="discardEdits()">Annuler</button>
</div></div>
<div id="offline"><div class="offbox">
  <svg class="offring" id="offRing" viewBox="0 0 120 120" role="img" aria-label="Compte à rebours"><circle class="offbg" cx="60" cy="60" r="52"/><circle class="offfg" id="offArc" cx="60" cy="60" r="52" transform="rotate(-90 60 60)"/><text id="offNum" x="60" y="71" text-anchor="middle"></text></svg>
  <h2>Raspberry Pi injoignable</h2>
  <p>Redémarrage du Pi ou coupure du réseau ? La page se reconnecte toute seule et revient là où vous étiez.</p>
  <p class="offs" id="offS"></p>
</div></div>
<div id="toast"></div>

<script>
/* ---------- Traductions ----------
   Le français est la langue source : les textes sont les clés. Une clé peut contenir {0}, {1}... (modèle). */
const I18N = __I18N__;
const TL_ON = I18N.lang !== 'fr' && Object.keys(I18N.strings).length > 0, TPL = [], tcache = new Map();
const hasKey = k => Object.prototype.hasOwnProperty.call(I18N.strings, k);
for (const k in I18N.strings) if (/\{\d+\}/.test(k)) {
  const parts = k.split(/\{(\d+)\}/);
  TPL.push([new RegExp('^' + parts.map((p, i) => i % 2 ? '([\\s\\S]+?)' : p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('') + '$'), parts.filter((_, i) => i % 2).map(Number), I18N.strings[k]]);
}
function tl(s) {
  if (!TL_ON || typeof s !== 'string' || !s) return s;
  if (tcache.has(s)) return tcache.get(s);
  let r = s;
  if (hasKey(s)) r = I18N.strings[s];
  else {
    for (const [rx, idx, v] of TPL) {
      const m = rx.exec(s);
      if (m) { const a = {}; idx.forEach((n, i) => { a[n] = tl(m[i + 1]); }); r = v.replace(/\{(\d+)\}/g, (x, n) => n in a ? a[n] : x); break; }
    }
    if (r === s && s.includes(' ; ')) r = s.split(' ; ').map(tl).join(' ; ');
  }
  if (tcache.size > 3000) tcache.clear();
  tcache.set(s, r); return r;
}
function _t(s, ...a) {
  if (!a.length) return tl(s);
  return (TL_ON && hasKey(s) ? I18N.strings[s] : s).replace(/\{(\d+)\}/g, (x, n) => a[+n] !== undefined ? a[+n] : x);
}
function trAttrs(n) { for (const a of ['placeholder', 'title']) { const v = n.getAttribute && n.getAttribute(a); if (v) { const r = tl(v); if (r !== v) n.setAttribute(a, r); } } }
function trNode(n) {
  if (n.nodeType === 3) { const v = n.nodeValue, m = v.trim(); if (m && m.length < 400) { const r = tl(m); if (r !== m) n.nodeValue = v.replace(m, () => r); } return; }
  if (n.nodeType !== 1) return;
  trAttrs(n);
  if (n.tagName === 'SCRIPT' || n.tagName === 'STYLE' || n.tagName === 'TEXTAREA') return;
  for (let c = n.firstChild; c; c = c.nextSibling) trNode(c);
}
if (TL_ON) {
  const _confirm = window.confirm.bind(window); window.confirm = m => _confirm(tl(m));
  new MutationObserver(ms => { for (const m of ms) { if (m.type === 'childList') m.addedNodes.forEach(trNode); else if (m.type === 'characterData') trNode(m.target); else trAttrs(m.target); } })
    .observe(document.documentElement, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'title']});
  trNode(document.body); document.title = tl(document.title);
}

let lastStAt = 0, SET = null, edits = {}, curCat = null, cur = 'home', logText = '', lastSt = null, volDrag = false, volTimer = null;
let TYPES_DIRTY = false, TYPES_TEXT = '';
let pend = {app: false, web: false}, TYPES = null, rows = {}, UPD = null, updWasRunning = false, updBusy = false, updAuto = false, updTick = 0, histShut = {};
const $ = s => document.querySelector(s);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined) e.textContent = txt; return e; };

/* ---------- Mode hors ligne : le Pi ne répond plus (redémarrage, réseau) ---------- */
let netFails = 0, offline = false, offTimer = null, offLeft = 10, offBusy = false, bootId = null, webRestarting = false;
const OFF_EVERY = 10, OFF_LEN = 326.7;
function netFail() {
  netFails++;
  if (netFails >= 2 && !offline && !webRestarting && !updWasRunning && !(UPD && (UPD.running || UPD.restarting))) goOffline();
}
function goOffline() {
  offline = true; offLeft = OFF_EVERY; offBusy = false;
  const o = $('#offline'), h = document.querySelector('header');
  o.style.top = (h ? h.offsetHeight : 56) + 'px'; o.style.display = 'flex';
  $('#chips').style.visibility = 'hidden';
  offDraw(); clearInterval(offTimer); offTimer = setInterval(offTick, 1000);
}
function offDraw() {
  $('#offRing').classList.toggle('try', offBusy);
  $('#offArc').style.strokeDashoffset = offBusy ? '' : String(OFF_LEN * (1 - offLeft / OFF_EVERY));
  $('#offNum').textContent = offBusy ? '' : String(offLeft);
  $('#offS').textContent = offBusy ? tl('Tentative de connexion…') : _t('Nouvelle tentative dans {0} s', offLeft);
}
async function offTick() {
  if (offBusy) return;
  offLeft--;
  if (offLeft > 0) { offDraw(); return; }
  offBusy = true; offDraw();
  try {
    const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), 6000);
    const r = await fetch('/api/status', {cache: 'no-store', signal: ctl.signal}); clearTimeout(t);
    if (!r.ok && r.status !== 401) throw 0;
    const d = await r.json().catch(() => ({}));
    comeBack(d.boot);
  } catch (e) { offBusy = false; offLeft = OFF_EVERY; offDraw(); }
}
function comeBack(boot) {  // la connexion est revenue : on retrouve la page où l'on était
  clearInterval(offTimer); offline = false; netFails = 0; offBusy = false;
  $('#offline').style.display = 'none'; $('#chips').style.visibility = '';
  if (boot && bootId && boot !== bootId) {  // webadmin a redémarré (nouvelle version possible) : rechargement, même onglet et même catégorie
    try { sessionStorage.setItem('fdRestore', JSON.stringify({tab: cur, cat: curCat})); } catch (e) {}
    location.reload(); return;
  }
  pollStatus();
  if (cur === 'hist') loadHist(); else if (cur === 'upd') pollUpd(); else if (cur === 'log') loadLogs();
  else if (cur === 'cfg' && !Object.keys(edits).length) loadSettings().catch(() => {});
}
async function api(path, body) {
  const opt = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Admin': '1'}, body: JSON.stringify(body)};
  let r;
  try { r = await fetch(path, opt); } catch (e) { netFail(); throw new Error(tl('Connexion perdue')); }
  netFails = 0;
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
  if (tab === 'hist') loadHist();
  if (tab === 'home') pollStatus();
  if (tab === 'upd') { updTick = 0; pollUpd(); }
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
  const sc = li('Planning de l\'écran', ''); const eb = el('button', 'b s', 'Modifier'); eb.onclick = () => { go('cfg'); curCat = 'schedule'; renderMenu(); renderCat(); }; sc.r.append(eb); sc.r.style.display = 'none'; rows.sched = sc; scr.append(sc.r);
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
  busy(inp, async () => {
    const r = await api('/api/service', {action: on ? 'start' : 'stop'});
    toast(r.message);
  });
}
function onScreen(on, inp) {
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
function fmtUp(s) { const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? _t('{0} j {1} h', d, h) : (h ? h + ' h ' + m + ' min' : m + ' min'); }
function ringTile(label, pct, cls, text, detail, tip) {
  const NS = 'http://www.w3.org/2000/svg', C = 2 * Math.PI * 22, d = el('div', 'tile ring ' + (cls || ''));
  const svg = document.createElementNS(NS, 'svg'); svg.setAttribute('width', '54'); svg.setAttribute('height', '54'); svg.setAttribute('viewBox', '0 0 54 54');
  const circle = (c, dash) => { const e = document.createElementNS(NS, 'circle'); for (const [k, v] of Object.entries({cx: 27, cy: 27, r: 22, fill: 'none', 'stroke-width': 6})) e.setAttribute(k, v); e.setAttribute('class', c); if (dash !== undefined) { e.setAttribute('stroke-linecap', dash > 0.5 ? 'round' : 'butt'); e.setAttribute('stroke-dasharray', dash + ' ' + C); e.setAttribute('transform', 'rotate(-90 27 27)'); } return e; };
  const tx = document.createElementNS(NS, 'text'); tx.setAttribute('x', 27); tx.setAttribute('y', 31); tx.setAttribute('text-anchor', 'middle'); tx.textContent = text;
  svg.append(circle('rb'), circle('rg', Math.max(0, Math.min(100, pct || 0)) / 100 * C), tx);
  const info = el('div', 'ri'); info.append(el('small', null, label)); if (detail) info.append(el('i', null, detail));
  if (tip) d.title = tip;
  d.append(svg, info); return d;
}
async function pollStatus() {
  try {
    const s = await api('/api/status'); lastSt = s; bootId = s.boot || bootId;
    if (cur === 'cfg' && curCat === 'sources' && SET) paintSrc();
    const c = el('div');
    if (s.muted) c.append(chip('son coupé', 'warn'));
    if (s.build_running) c.append(chip('carte en construction', 'warn'));
    if (s.update_running) c.append(chip(UPD && UPD.running && UPD.pct ? _t('mise à jour en cours · {0} %', UPD.pct) : 'mise à jour en cours', 'warn'));
    else if (s.update_available) {
      const ch = chip('mise à jour disponible', 'ok'); ch.classList.add('upd'); ch.title = 'Voir les mises à jour'; ch.onclick = () => go('upd');
      if (s.update_can) { const b = el('button', 'uico'); b.innerHTML = '<svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true"><path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" stroke="currentColor" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'; b.title = 'Mettre à jour maintenant'; b.onclick = e => { e.stopPropagation(); quickUpdate(); }; ch.append(b); }
      c.append(ch);
    }
    if (s.disk && s.disk.level !== 'ok') { const ch = chip(_t('disque rempli à {0} %', fmtPct(s.disk.pct)), s.disk.level === 'critical' ? 'bad' : 'warn'); ch.style.cursor = 'pointer'; ch.onclick = () => { go('cfg'); curCat = 'storage'; renderMenu(); renderCat(); }; c.append(ch); }
    { const box = $('#chips'); if (box.dataset.h !== c.innerHTML) { box.dataset.h = c.innerHTML; box.replaceChildren(...c.childNodes); } }

    const aw = $('#authWarn'); if (aw) aw.style.display = s.auth ? 'none' : 'block';
    $('#helperWarn').style.display = s.helper_old ? 'block' : 'none';
    lastStAt = performance.now();
    const t = $('#tiles'); t.innerHTML = '';
    t.append(tile('Programme', s.service === 'active' ? 'actif' : s.service, s.service === 'active' ? 'ok' : 'bad', s.paused ? tl('image en pause (écran en veille)') : (s.fps !== null && s.fps !== undefined ? s.fps.toFixed(1) + ' / ' + s.fps_target + ' fps' : '')));
    t.append(tile('Écran', s.screen_off ? 'en veille' : 'allumé', s.screen_off ? 'warn' : ''));
    const ml = {connecte: ['connecté', 'ok'], deconnecte: ['déconnecté', 'bad'], off: ['désactivé', ''], 'paho manquant': ['paho manquant', 'bad'], 'host manquant': ['serveur manquant', 'warn']};
    const mq = ml[s.mqtt] || [String(s.mqtt).startsWith('refuse') ? 'refusé' : s.mqtt, 'bad'];
    t.append(tile('MQTT', mq[0], mq[1]));
    { const c = tile('Temps', '--:--:--', '', ''); c.querySelector('b').id = 'clk'; const i = el('i'); i.id = 'clkd'; const u = el('i', null, _t('Allumé depuis {0}', fmtUp(s.uptime)) + (s.host ? ' · ' + s.host : '')); c.append(i, u); t.append(c); tickClock(); }
    {
      const L = s.temp_limits || {soft: 80, hard: 85, model: ''}, tp = s.temp, tcls = tp === null ? '' : (tp >= L.soft ? 'bad' : (tp >= L.soft - 10 ? 'warn' : ''));
      t.append(ringTile('Température', tp === null ? 0 : tp / L.hard * 100, tcls, tp === null ? '-' : Math.round(tp) + ' °C', _t('Ralentit dès {0} °C', L.soft),
        (L.model ? L.model + ' : ' : '') + _t('ralentissement dès {0} °C, limite {1} °C', L.soft, L.hard)));
      t.append(ringTile('Utilisation CPU', s.cpu || 0, s.cpu > 95 ? 'bad' : (s.cpu > 85 ? 'warn' : ''), s.cpu !== null ? Math.round(s.cpu) + ' %' : '-', _t('Charge : {0} / {1}', s.load[0].toFixed(2), s.load[1].toFixed(2))));
      let mp = 0, mt = '-', mcls = '', md = '';
      if (s.mem_total) {
        const used = Math.round((s.mem_total - s.mem_avail) / 1024), tot = Math.round(s.mem_total / 1024);
        mp = Math.round(used * 100 / tot); mt = mp + ' %'; mcls = mp > 90 ? 'bad' : (mp > 80 ? 'warn' : ''); md = _t('{0} / {1} Mo', used, tot);
      }
      t.append(ringTile('Mémoire', mp, mcls, mt, md));
      if (s.disk) t.append(ringTile('Disque', s.disk.pct, s.disk.level === 'critical' ? 'bad' : (s.disk.level === 'warn' ? 'warn' : ''), Math.round(s.disk.pct) + ' %', _t('Libre : {0}', fmtBytes(s.disk.free)),
        _t('Disque : {0} libres sur {1} ({2} %)', fmtBytes(s.disk.free), fmtBytes(s.disk.total), fmtPct(s.disk.pct))));
    }
    if (rows.prog) {
      const run = s.service === 'active';
      if (!rows.prog.t.input.disabled) rows.prog.t.input.checked = run;
      rows.prog.sub.textContent = run ? (s.paused ? tl("En fonctionnement, image en pause : l'écran est en veille") : tl('En fonctionnement')) : tl('Arrêté');
      if (!rows.screen.t.input.disabled) rows.screen.t.input.checked = !s.screen_off;
      rows.screen.sub.textContent = s.screen_off ? (s.helper_old ? tl("En veille. Le script de veille est ancien : relancez l'installeur pour que le programme continue de tourner") : tl('En veille : le programme continue de suivre les avions sans rafraîchir l\'image')) : tl('Allumé');
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
  updateBar(); markMenu(); ringVis(); linkSync();
}
function applyNeeds() {
  const n = {app: false, web: false};
  for (const p of allParams()) if (p.id in edits) { if (p.apply === 'app') n.app = true; if (p.apply === 'web') n.web = true; }
  return n;
}
function updateBar() {
  const n = Object.keys(edits).length + (TYPES_DIRTY ? 1 : 0), b = $('#saveBar');
  b.classList.toggle('on', cur === 'cfg' && n > 0);
  if (n) {
    const a = applyNeeds(); if (TYPES_DIRTY) a.app = true;
    $('#barTxt').textContent = _t(n > 1 ? '{0} modifications' : '{0} modification', n);
    $('#barSave').textContent = tl(a.app && a.web ? 'Enregistrer et relancer le programme et webadmin' : (a.app ? 'Enregistrer et relancer le programme' : (a.web ? 'Enregistrer et redémarrer webadmin' : 'Enregistrer')));
    $('#barHelp').textContent = tl(a.app && a.web ? "L'enregistrement relance le programme d'affichage et webadmin pour appliquer ces valeurs." : (a.app ? "L'enregistrement relance le programme d'affichage pour appliquer ces valeurs (quelques secondes sans image à l'écran)." : (a.web ? "L'enregistrement redémarre webadmin pour appliquer ces valeurs (la page sera indisponible quelques secondes)." : "Appliqué dès l'enregistrement.")));
  }
}
function markMenu() {
  const dirty = new Set(); for (const p of allParams()) if (p.id in edits) dirty.add(SRC_PAGES.includes(p.cat) ? 'sources' : p.cat);
  if (TYPES_DIRTY) dirty.add('types');
  document.querySelectorAll('#menu button').forEach(b => b.classList.toggle('dot', dirty.has(b.dataset.c)));
}
function renderMenu() {
  const m = $('#menu'); m.innerHTML = '';
  for (const g of SET.menu) {
    m.append(el('div', 'mg', g.group));
    for (const it of g.items) { const b = el('button', (it.id === curCat || (it.id === 'sources' && SRC_PAGES.includes(curCat))) ? 'on' : '', it.title); b.dataset.c = it.id; b.onclick = () => { curCat = it.id; renderMenu(); renderCat(); }; m.append(b); }
  }
  markMenu();
}
const PLANE_PTS = '0,-13 1.4,-9.9 1.8,-6.8 1.8,-1 12,5 12,7.2 1.8,5 1.8,9 5,11.5 5,13.7 0.9,11.2 0,13 -0.9,11.2 -5,13.7 -5,11.5 -1.8,9 -1.8,5 -12,7.2 -12,5 -1.8,-1 -1.8,-6.8 -1.4,-9.9';
function control(p) {
  const v = pval(p), wrap = el('div');
  if (p.type === 'bool') {
    const t = toggle(String(v) === 'true', on => setEdit(p, on ? 'true' : 'false')); t.input.dataset.pid = p.id;
    t.label.classList.toggle('chg', p.id in edits); t.input.addEventListener('change', () => t.label.classList.toggle('chg', p.id in edits));
    return {c: t.label, inline: true};
  }
  if (p.type === 'choice' && p.options.length <= 3) {
    const s = el('div', 'seg' + (p.id in edits ? ' chg' : ''));
    for (const o of p.options) { const b = el('button', String(v) === o ? 'on' : '', (p.labels && p.labels[o]) || o); b.dataset.v = o; b.onclick = () => { setEdit(p, o); s.classList.toggle('chg', p.id in edits); s.querySelectorAll('button').forEach(x => x.classList.toggle('on', x.dataset.v === o)); }; s.append(b); }
    return {c: s, inline: true};
  }
  if (p.type === 'choice') {
    const s = document.createElement('select'); for (const o of p.options) { const op = el('option', null, (p.labels && p.labels[o]) || o); op.value = o; s.append(op); }
    s.value = v; s.className = p.id in edits ? 'chg' : ''; s.onchange = () => { setEdit(p, s.value); s.classList.toggle('chg', p.id in edits); }; return {c: s, inline: false};
  }
  if (p.type === 'color') {
    const w = el('div', 'colpick'), i = document.createElement('input'), pv = document.createElementNS('http://www.w3.org/2000/svg', 'svg'), rs = el('button', 'b s', '↺');
    const ok = x => /^#[0-9a-f]{6}$/i.test(x || '');
    i.type = 'color'; i.value = ok(v) ? v : p.default; i.dataset.pid = p.id;
    pv.setAttribute('viewBox', '-16 -16 32 32'); pv.setAttribute('width', 30); pv.setAttribute('height', 30);
    const ring = p.id === 'config:rings.color', pg = document.createElementNS('http://www.w3.org/2000/svg', ring ? 'circle' : 'polygon');
    if (ring) { pg.setAttribute('r', 11); pg.setAttribute('fill', 'none'); pg.setAttribute('stroke-width', 2.5); } else pg.setAttribute('points', PLANE_PTS);
    pv.append(pg);
    const paint = () => { pg.setAttribute(ring ? 'stroke' : 'fill', i.value); rs.style.visibility = i.value.toLowerCase() === String(p.default).toLowerCase() ? 'hidden' : 'visible'; };
    i.oninput = () => { setEdit(p, i.value.toLowerCase()); paint(); }; rs.title = 'Couleur par défaut'; rs.onclick = () => { i.value = p.default; setEdit(p, p.default); paint(); };
    paint(); w.append(pv, i, rs); return {c: w, inline: true};
  }
  if (p.ui === 'slider') {
    const w = el('div', 'sl'), r = document.createElement('input'); r.type = 'range'; r.min = p.min; r.max = p.max; r.step = p.step || 1; r.value = v;
    const u = p.unit ? ' ' + p.unit : '', l = el('span', null, String(v) + u); r.oninput = () => { l.textContent = r.value + u; setEdit(p, String(r.value)); }; w.append(r, l); return {c: w, inline: true};
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
  i.autocomplete = 'off'; i.autocapitalize = 'off'; i.spellcheck = false; i.dataset.pid = p.id;
  i.oninput = () => { setEdit(p, p.type === 'float' ? i.value.trim().replace(',', '.') : i.value.trim()); i.classList.toggle('chg', p.id in edits); };
  return {c: i, inline: false};
}
function gotoMap() { go('cfg'); curCat = 'position'; renderMenu(); renderCat(); }
function renderCat() {
  const mb = $('#mapBuild'), holder = $('#mapHolder');
  if (mb && holder && mb.parentNode !== holder) holder.appendChild(mb);
  renderCatBase();
  if ((curCat === 'position' || curCat === 'mapstyle') && mb) { const box = $('#catbox'); box.appendChild(el('h2', 't', 'Reconstruction de la carte')); box.appendChild(mb); pollBuild(); }
}
function renderGroups(box, cat) {
  for (const g of cat.groups) {
    const ps = g.params.filter(p => !p.editor);
    if (!ps.length) continue;
    if (g.name) box.append(el('h2', 't', g.name));
    const list = el('div', 'list');
    for (const p of ps) {
      const ctl = control(p), row = el('div', 'li' + (ctl.inline ? '' : ' full')), t = el('div', 'lt'), b = el('b', null, p.label);
      if (p.needs_map) b.append(el('span', 'flag', 'recalcule la carte'));
      t.append(b); const hp = (p.help || '') + (p.present ? '' : (p.help ? ' ' : '') + _t('(absent du fichier : valeur par défaut)'));
      if (hp) t.append(el('small', null, hp));
      row.dataset.row = p.id; row.append(t, ctl.c); list.append(row);
    }
    box.append(list);
    const pw = g.params.find(p => p.id === 'config:display.width'), ph = g.params.find(p => p.id === 'config:display.height');
    if (pw && ph && SET.screen) {  // résolution maximale de l'écran branché : un bouton la reporte dans la taille de la carte
      const sr = el('div', 'li'), st = el('div', 'lt'), bt = el('button', 'b s', 'Utiliser pour la carte');
      st.append(el('b', null, _t("Résolution maximale de l'écran : {0} × {1}", SET.screen.width, SET.screen.height)), el('small', null, tl('Détectée sur la sortie vidéo du Pi. Changer la taille demande de reconstruire la carte.') + (SET.screen.zero ? ' ' + tl("Sur un Raspberry Pi Zero, la reconstruction d'une grande carte peut être lente (plusieurs minutes).") : '')));
      bt.onclick = () => {
        for (const [p, v] of [[pw, SET.screen.width], [ph, SET.screen.height]]) {
          const i = document.querySelector('[data-row="' + p.id + '"] input'); if (!i) continue;
          i.value = String(v); i.dispatchEvent(new Event('input', {bubbles: true}));
        }
      };
      sr.append(st, bt); list.append(sr);
    }
  }
}
// Cercles de distance : les réglages n'apparaissent que s'ils servent (cercles affichés, au moins 1 cercle, au moins 2 pour l'écartement)
// Alerte : « Utiliser la distance du premier cercle » n'a de sens que s'il y a au moins un cercle affiché. Sinon l'option est décochée et masquée.
function linkSync() {
  const ps = allParams(), lp = ps.find(p => p.id === 'config:alert.link_first_ring'), sh = ps.find(p => p.id === 'config:rings.show'), ct = ps.find(p => p.id === 'config:rings.count');
  if (!lp || !sh || !ct) return;
  const on = String(pval(sh)) === 'true' && (parseInt(pval(ct)) || 0) >= 1;
  if (!on && String(pval(lp)) === 'true') setEdit(lp, 'false');  // setEdit rappelle linkSync : la 2e passe ne fait plus rien
  const r = document.querySelector('[data-row="config:alert.link_first_ring"]');
  if (r) { r.style.display = on ? '' : 'none'; const t = r.querySelector('input[type=checkbox]'); if (t) t.checked = String(pval(lp)) === 'true'; }
}
function ringVis() {
  if (curCat === 'storage') {  // le quota n'a de sens que si le nettoyage automatique est activé
    const ac = allParams().find(p => p.id === 'web:storage.auto_clean'), r = document.querySelector('[data-row="web:storage.cache_max_mb"]');
    if (ac && r) r.style.display = String(pval(ac)) === 'true' ? '' : 'none';
    return;
  }
  if (curCat !== 'position') return;
  const g = k => allParams().find(p => p.id === 'config:rings.' + k);
  if (!g('show') || !g('count')) return;
  const on = String(pval(g('show'))) === 'true', n = parseInt(pval(g('count'))) || 0;
  const vis = {count: on, first_km: on && n >= 1, step_km: on && n >= 2, width: on && n >= 1, color: on && n >= 1, show_labels: on && n >= 1};
  for (const k in vis) { const r = document.querySelector('[data-row="config:rings.' + k + '"]'); if (r) r.style.display = vis[k] ? '' : 'none'; }
}
let fieldTab = {};
function renderCatBase() {
  const box = $('#catbox'); box.innerHTML = ''; box.oninput = null; mapPickDestroy(); msAlive = false;
  const cat = SET.cats[curCat]; if (!cat) return;
  const head = el('div', 'catt'); head.append(el('h3', null, cat.title)); box.append(head);
  if (cat.kind === 'types') return renderTypes(box);
  if (cat.kind === 'backup') { if (cat.note) box.append(el('p', 'note', cat.note)); return renderBackup(box); }
  if (cat.kind === 'mapstyle') { if (cat.note) box.append(el('p', 'note', cat.note)); return renderMapStyle(box, cat); }
  if (cat.kind === 'sources') return renderSources(box, cat);
  if (cat.kind === 'storage') renderStorage(box);
  if (cat.kind === 'schedule') { if (cat.note) box.append(el('p', 'note', cat.note)); return renderSchedule(box); }
  if (cat.kind === 'fields') {
    const extra = cat.groups.some(g => g.params.some(p => !p.editor));
    if (!extra) { if (cat.note) box.append(el('p', 'note', cat.note)); return renderFields(box, cat); }
    const tab = fieldTab[cat.id] || 'content', tabs = el('div', 'seg'); tabs.style.margin = '4px 0 12px';
    for (const [v, t] of [['content', 'Contenu du texte'], ['size', 'Taille et angles']]) { const b = el('button', tab === v ? 'on' : '', t); b.onclick = () => { fieldTab[cat.id] = v; renderCat(); }; tabs.append(b); }
    box.append(tabs);
    if (tab === 'content') { if (cat.editor.note) box.append(el('p', 'note', cat.editor.note)); return renderFields(box, cat); }
    renderGroups(box, cat); return;
  }
  if (SRC_PAGES.includes(cat.id)) {  // pages de source : accessibles seulement depuis « Sources des avions »
    const bk = el('button', 'b s', '← Sources des avions'); bk.style.marginBottom = '12px'; bk.onclick = () => { curCat = 'sources'; renderMenu(); renderCat(); window.scrollTo(0, 0); };
    box.append(bk);
  }
  if (cat.id === 'mqtt') {
    const st = lastSt ? lastSt.mqtt : 'off', h = el('div', 'tools'); const c = chip('État : ' + (st === 'off' ? 'désactivé' : st), st === 'connecte' ? 'ok' : (st === 'off' ? '' : 'bad')); c.style.flex = 'none';
    const b = el('button', 'b s', 'Reconnecter / republier'); b.style.flex = 'none'; b.onclick = async () => { try { await api('/api/mqtt/reconnect', {}); toast('Reconnexion demandée'); setTimeout(pollStatus, 2000); } catch (e) { toast(e.message, true); } };
    h.append(c, b); box.append(h);
  }
  if (cat.note) box.append(el('p', 'note', cat.note));
  if (cat.id === 'server') { const w = el('div', 'hint', "Aucun mot de passe n'est défini : toute personne du réseau local peut piloter le Raspberry Pi. Définissez-en un ci-dessous."); w.id = 'authWarn'; w.style.display = (lastSt && !lastSt.auth) ? 'block' : 'none'; box.append(w); }  
  if (cat.id === 'position') renderMapPicker(box);
  renderGroups(box, cat);
  if (cat.id === 'position' || cat.id === 'storage') ringVis();
  if (cat.id === 'alert') linkSync();
  if (cat.id === 'online') {
    const res = el('div', 'sres'), bx = el('div', 'sft'); bx.style.margin = '12px 0 6px';
    for (const n of ONLINE) {
      const tb = el('button', 'b s', _t('Tester {0}', SRC_NAMES[n]));
      tb.onclick = async () => {
        res.className = 'sres'; res.textContent = tl('Test en cours…');
        try {
          const r = await api('/api/sources/test', {source: n, lat: pval(gp('position.latitude')), lon: pval(gp('position.longitude')), radius_km: pval(gp('position.radius_km'))});
          res.className = 'sres ok';
          res.textContent = SRC_NAMES[n] + ' : ' + _t('Connexion réussie : {0} avions dans le fichier, {1} avec une position.', r.total, r.positions);
        } catch (e) { res.className = 'sres bad'; res.textContent = SRC_NAMES[n] + ' : ' + _t('Échec : {0}', e.message); }
      };
      bx.append(tb);
    }
    box.append(bx, res);
  }
  if (cat.id === 'tar1090') {
    const up_ = allParams().find(p => p.id === 'config:tar1090.url'), i1 = document.querySelector('[data-row="' + up_.id + '"] input');
    if (i1) i1.placeholder = 'http://adresse/tar1090/data/aircraft.json';
    const tb = el('button', 'b s', 'Tester la connexion'), res = el('div', 'sres');
    tb.onclick = async () => {
      res.className = 'sres'; res.textContent = tl('Test en cours…');
      try {
        const r = await api('/api/sources/test', {url: pval(up_)});
        res.className = 'sres ok';
        res.textContent = _t('Connexion réussie : {0} avions dans le fichier, {1} avec une position.', r.total, r.positions) + ' ' + tl(r.has_db ? "Le fichier donne déjà l'immatriculation et le type de certains avions." : "Le fichier ne donne ni immatriculation ni type : ils seront cherchés sur adsbdb.com.");
      } catch (e) { res.className = 'sres bad'; res.textContent = _t('Échec : {0}', e.message); }
    };
    box.append(tb, res);
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
  $('#pendTxt').textContent = _t('Enregistré, mais pas encore pris en compte. Il reste à : {0}.', parts.map(tl).join(_t(' et ')));
  if (pend.app) { const b = el('button', 'b p s', 'Relancer le programme'); b.onclick = async () => { await svc('restart'); pend.app = false; showPending(); }; btns.append(b); }
  if (pend.web) { const b = el('button', 'b p s', 'Redémarrer webadmin'); b.onclick = () => restartWeb(pend.port); btns.append(b); }
}
const S_PORT = () => location.port ? +location.port : undefined;
async function saveSettings() {
  try {
    let r = {changed: [], restart_app: false, restart_web: false, port: S_PORT()};
    if (TYPES_DIRTY) { await api('/api/types', {text: TYPES_TEXT}); TYPES_DIRTY = false; r.restart_app = true; }
    if (Object.keys(edits).length) { const x = await api('/api/settings', {changes: edits}); r = Object.assign(x, {restart_app: x.restart_app || r.restart_app}); }
    await loadSettings();
    pollStatus();
    toast(r.changed.length ? r.changed.length + ' réglage(s) enregistré(s)' : 'Types d\'avion enregistrés');
    if (r.needs_map) $('#mapHint').style.display = 'block';
    pend = {app: false, web: false};
    if (r.reload_ui) setTimeout(() => location.reload(), 1500);
    if (r.restart_app) await svc('restart');
    showPending();
    if (r.restart_web) await restartWeb(r.port, true);
  } catch (e) { toast(e.message, true); }
}
function discardEdits() { edits = {}; TYPES_DIRTY = false; renderCat(); markMenu(); updateBar(); }
async function restartWeb(port, noAsk) {
  if (!noAsk && !confirm('Redémarrer webadmin ? La page sera indisponible quelques secondes.')) return;
  webRestarting = true;
  try { await api('/api/webadmin/restart', {}); } catch (e) { webRestarting = false; toast(e.message, true); return; }
  toast('Redémarrage de webadmin...');
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 1000));
    try { await fetch('/api/status', {cache: 'no-store'}).then(r => { if (!r.ok && r.status !== 401) throw 0; }); break; } catch (e) {}
  }
  if (port && String(port) !== location.port && location.port) location.href = location.protocol + '//' + location.hostname + ':' + port + '/';
  else location.reload();
}

/* ---------- Sources des avions ---------- */
const SRC_NAMES = {fr24: 'Flightradar24', tar1090: 'tar1090', airplaneslive: 'airplanes.live', adsblol: 'adsb.lol', adsbfi: 'adsb.fi'};
const SRC_PAGES = ['api', 'tar1090', 'online'];  // pages de réglages des sources (hors menu, depuis « Sources des avions »)
const SRC_PAGE = {fr24: 'api', tar1090: 'tar1090', airplaneslive: 'online', adsblol: 'online', adsbfi: 'online'};
const ONLINE = ['airplaneslive', 'adsblol', 'adsbfi'];
const SRC_DESC = {
  fr24: "Positions mondiales par Internet, avec détails et photo de chaque avion.",
  tar1090: "Votre antenne ADS-B locale : positions quasi instantanées, sans Internet.",
  airplaneslive: "Service communautaire gratuit : les avions captés par des milliers d'antennes, MLAT compris.",
  adsblol: "Service communautaire gratuit : les avions captés par des milliers d'antennes, MLAT compris.",
  adsbfi: "Service communautaire gratuit : les avions captés par des milliers d'antennes, MLAT compris."
};
const gp = id => allParams().find(p => p.id === 'config:' + id);
function srcOrder() {
  const o = String(pval(gp('sources.order')) || '').split(',').map(x => x.trim().toLowerCase()).filter((x, i, a) => SRC_NAMES[x] && a.indexOf(x) === i);
  for (const n of Object.keys(SRC_NAMES)) if (!o.includes(n)) o.push(n);
  return o;
}
function srcOn(n) { const p = gp('sources.' + n + '_enabled'); return !!p && String(pval(p)) === 'true'; }
function paintSrc() {
  document.querySelectorAll('.sst').forEach(e => {
    const n = e.dataset.src; let t = '', c = 'sst';
    if (srcOn(n)) {
      const h = lastSt && lastSt.sources && lastSt.sources[n];
      if (!h || h.ok === null || h.ok === undefined && !h.err) t = tl('En attente de données');
      else if (h.ok) { t = _t('{0} avions · reçu il y a {1} s', h.n, Math.round(h.age || 0)); c += ' ok'; }
      else { t = _t('Pas de réponse : {0}', h.err || ''); c += ' bad'; }
    } else t = tl('Désactivée');
    if (e.textContent !== t) e.textContent = t;
    e.className = c;
  });
}
function srcOpts(p, opts) {
  const w = el('div', 'opts' + (p.id in edits ? ' chg' : ''));
  for (const [v, t, d] of opts) {
    const b = el('button', 'opt' + (String(pval(p)) === v ? ' on' : '')); b.append(el('b', null, t), el('small', null, d));
    b.onclick = () => { setEdit(p, v); renderCat(); }; w.append(b);
  }
  return w;
}
function renderSources(box, cat) {
  if (cat.note) box.append(el('p', 'note', cat.note));
  const order = srcOrder(), onN = order.filter(srcOn).length;
  if (!onN) box.append(el('div', 'hint', 'Aucune source cochée : Flightradar24 sera utilisé.'));
  box.append(el('h2', 't', 'Sources classées par priorité'));
  const wrap = el('div', 'srcs');
  order.forEach((n, i) => {
    const on = srcOn(n), card = el('div', 'src' + (on ? '' : ' off')), hd = el('div', 'sh');
    const rk = el('span', 'rk', String(i + 1)); rk.title = _t('Priorité {0}', i + 1);
    const tt = el('div', 'st'), sst = el('span', 'sst'); sst.dataset.src = n; tt.append(el('b', null, SRC_NAMES[n]), sst);
    hd.append(rk, tt, control(gp('sources.' + n + '_enabled')).c); card.append(hd, el('p', 'sd', SRC_DESC[n]));
    const ft = el('div', 'sft'), cfgb = el('button', 'b s', n === 'tar1090' ? 'Réglages de tar1090' : (n === 'fr24' ? 'Réglages de Flightradar24' : 'Réglages des services en ligne'));
    cfgb.onclick = () => { curCat = SRC_PAGE[n]; renderMenu(); renderCat(); window.scrollTo(0, 0); };
    ft.append(cfgb);
    if (i > 0) {  // un seul bouton : passer devant la source du dessus
      const up = el('button', 'b s', _t('↑ Passer en n°{0}', i)); up.title = tl('Donne à cette source la priorité sur celle du dessus');
      up.onclick = () => { const o = order.slice(); [o[i - 1], o[i]] = [o[i], o[i - 1]]; setEdit(gp('sources.order'), o.join(',')); renderCat(); };
      ft.append(up);
    }
    card.append(ft);
    wrap.append(card);
  });
  box.append(wrap);
  const ep = gp('sources.enrich'), ec = control(ep), l1 = el('div', 'list'), r1 = el('div', 'li'), t1 = el('div', 'lt');
  t1.append(el('b', null, ep.label), el('small', null, ep.help)); r1.append(t1, ec.c); l1.append(r1); box.append(l1);

  const sec = el('div', 'srcmode' + (onN >= 2 ? '' : ' dim'));
  sec.append(el('h2', 't', 'Comment combiner les sources'));
  if (onN < 2) sec.append(el('p', 'note', "Une seule source est active : les options de combinaison ci-dessous ne s'appliquent pas tant qu'une deuxième n'est pas cochée."));
  const mp = gp('sources.mode'), op = gp('sources.overlap'), mode = String(pval(mp)), ov = String(pval(op));
  sec.append(srcOpts(mp, [
    ['combine', 'Cumuler', "Tous les avions de toutes les sources sont affichés, chacun une seule fois. Le plus complet : un avion capté par une seule source apparaît quand même."],
    ['primary', 'Source principale et compléments', "Seule la source n°1 décide quels avions sont affichés et où. Les autres ne servent qu'à compléter les informations manquantes (immatriculation, type, trajet). Si la source n°1 ne répond plus, la suivante devient principale."],
    ['failover', 'Secours', "Une seule source à la fois : la n°1. Si elle ne répond plus, la n°2 prend le relais, et la n°1 reprend dès qu'elle revient. Le plus simple : aucune donnée n'est mélangée."]]));
  if (mode === 'combine') {
    sec.append(el('h2', 't', 'Si un avion est vu par plusieurs sources'));
    sec.append(srcOpts(op, [
      ['freshest', 'La position la plus récente', "Pour chaque avion, on garde la position, la vitesse et le cap de la source dont le dernier message est le plus récent. Recommandé : l'antenne locale, lue toutes les 2 s, l'emporte presque toujours sur Flightradar24 (30 s) et l'avion se déplace plus fluidement."],
      ['priority', 'La source la mieux classée', "L'avion garde les valeurs de la source classée la plus haut dans la liste, même si une autre est plus récente. À choisir si vous faites plus confiance à une source pour les positions ; l'autre n'apporte alors que les avions que la première ne voit pas."]]));
  }
  sec.append(el('h2', 't', 'Ce que fait toujours Flight display'));
  const ul = el('ul', 'srcul');
  for (const t of ["Un même avion est reconnu d'une source à l'autre par son adresse ICAO (le code hexadécimal de son transpondeur) : il n'est jamais compté ni affiché deux fois (carte, alerte, historique, MQTT).",
    "Position, vitesse, altitude et cap viennent toujours d'une seule source par avion : elles ne sont jamais mélangées ni moyennées.",
    "Les informations manquantes sont complétées par les autres sources (immatriculation, type, indicatif, trajet), quel que soit le mode.",
    "Une source qui ne répond plus est ignorée au bout de quelques secondes (elle reste signalée ici) ; les autres continuent."]) ul.append(el('li', null, t));
  sec.append(ul);
  sec.append(el('h2', 't', 'Exemple : que devient un avion selon le mode ?'));
  const tb = document.createElement('table'), hr = document.createElement('tr'); tb.className = 'srctab';
  for (const h of ['Mode', "Avion vu par les deux sources (n°1 : position d'il y a 8 s, n°2 : il y a 1 s)", 'Avion vu par la source n°2 seulement']) hr.append(el('th', null, h));
  tb.append(hr);
  for (const [m, o, a, b, c] of [['combine', 'freshest', 'Cumuler, position la plus récente', 'Position de la source n°2 (la plus récente)', 'Affiché'],
      ['combine', 'priority', 'Cumuler, source la mieux classée', 'Position de la source n°1', 'Affiché'],
      ['primary', '', 'Source principale et compléments', 'Position de la source n°1', 'Ignoré'],
      ['failover', '', 'Secours', 'Position de la source n°1', "Ignoré (tant que la source n°1 répond)"]]) {
    const r = document.createElement('tr'); if (m === mode && (!o || o === ov)) r.className = 'cur';
    r.append(el('td', null, a), el('td', null, b), el('td', null, c)); tb.append(r);
  }
  sec.append(tb);
  sec.append(el('h2', 't', 'Couleur des icônes'));
  const cl = el('div', 'list'), tp = gp('display.color_by_source'), cols = ['plane_color_fr24', 'plane_color_tar1090', 'plane_color_airplaneslive', 'plane_color_adsblol', 'plane_color_adsbfi', 'plane_color_multi'].map(k => gp('display.' + k));
  const mk = (p, id) => { const c = control(p), r = el('div', 'li'), t = el('div', 'lt'); t.append(el('b', null, p.label)); if (p.help) t.append(el('small', null, p.help)); r.dataset.row = id; r.append(t, c.c); return r; };
  cl.append(mk(tp, 'tg'));
  for (const p of cols) cl.append(mk(p, p.id));
  const milp = gp('display.color_military'), milc = gp('display.plane_color_military');
  cl.append(mk(milp, 'mg'), mk(milc, milc.id));
  sec.append(cl); box.append(sec);
  const tg = cl.querySelector('[data-row="tg"] input[type=checkbox]'), milg = cl.querySelector('[data-row="mg"] input[type=checkbox]');
  const vis = () => { cols.forEach(p => { const r = cl.querySelector('[data-row="' + p.id + '"]'); if (r) r.style.display = String(pval(tp)) === 'true' ? '' : 'none'; });
    const r = cl.querySelector('[data-row="' + milc.id + '"]'); if (r) r.style.display = String(pval(milp)) === 'true' ? '' : 'none'; };
  if (tg) tg.addEventListener('change', vis); if (milg) milg.addEventListener('change', vis); vis();
  paintSrc();
}

/* ---------- Types d'avion ---------- */
function planeSvg(T, cat, size) {
  const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '-20 -20 40 40'); svg.setAttribute('width', size); svg.setAttribute('height', size); svg.setAttribute('class', 'pl');
  const pg = document.createElementNS(NS, 'polygon'); pg.setAttribute('points', (T.shapes[cat] || T.shapes.narrow).map(p => p.join(',')).join(' ')); pg.setAttribute('fill', 'currentColor'); svg.append(pg);
  if (cat === 'heli') { const c = document.createElementNS(NS, 'circle'); c.setAttribute('r', 9); c.setAttribute('fill', 'none'); c.setAttribute('stroke', 'currentColor'); c.setAttribute('stroke-width', 1); svg.append(c); }
  return svg;
}
async function renderTypes(box) {
  box.append(el('p', 'note', "Chaque type d'avion (code ICAO) est associé à une forme d'icône. Touchez un type pour voir sa fiche et changer son icône. Les changements s'enregistrent avec le bouton en bas de page."));
  let T; try { T = await api('/api/types'); } catch (e) { box.append(el('p', 'note', e.message)); return; }
  TYPES = T;
  const extra = Object.assign({}, T.extra), builtin = T.builtin, info = {};
  const textOf = o => Object.keys(o).sort().map(k => k + ' ' + o[k]).join('\n'), origText = textOf(T.extra);
  if (TYPES_DIRTY) { for (const k of Object.keys(extra)) delete extra[k]; for (const l of TYPES_TEXT.split('\n')) { const p = l.trim().split(/\s+/); if (p.length === 2) extra[p[0]] = p[1]; } }
  for (const e of T.seen) info[e.code] = e;
  let sel = null, query = '', editing = null;
  const sug = {}, busy = new Set();
  const opened = new Set();
  const catOf = c => extra[c] || builtin[c] || 'narrow';
  const known = c => !!(extra[c] || builtin[c]);
  const todo = el('div'), cats = el('div'), catList = el('div'), bt = el('div', 'grid'); bt.style.marginTop = '10px';
  const find = document.createElement('input'); find.type = 'search'; find.placeholder = 'Rechercher un code (ex. A320)'; find.style.textTransform = 'uppercase';
  const bar = el('div', 'tools'); bar.append(find);
  const persist = () => { const t = textOf(extra); TYPES_DIRTY = t !== origText; TYPES_TEXT = t; updateBar(); markMenu(); };
  const web = code => { const i = info[code]; window.open('https://www.google.com/search?q=' + encodeURIComponent('ICAO aircraft type ' + code + (i && i.model ? ' ' + i.model : '')), '_blank', 'noopener'); };
  const choose = (code, c) => { if (builtin[code] === c) delete extra[code]; else extra[code] = c; editing = null; draw(); persist(); };
  const ask = async (code, quiet) => {
    busy.add(code); draw();
    try { sug[code] = await api('/api/types/suggest?code=' + encodeURIComponent(code)); }
    catch (e) { sug[code] = {error: true}; if (!quiet) toast(e.message, true); }
    busy.delete(code); draw();
  };
  const unknownCodes = () => { const l = T.seen.filter(e => !known(e.code)).map(e => e.code); for (const u of T.unknown) { const c = u.toUpperCase(); if (!known(c) && !l.includes(c)) l.push(c); } return l; };
  const detail = code => {
    const i = info[code] || {}, w = el('div', 'tdet'), top = el('div', 'tdtop');
    if (i.photo) { const im = document.createElement('img'); im.className = 'tph'; im.alt = code; im.loading = 'lazy'; im.src = '/api/types/photo?code=' + encodeURIComponent(code); im.onerror = () => im.remove(); top.append(im); }
    const tx = el('div', 'tdtx');
    tx.append(el('div', 'tdt', code + (i.model ? ' · ' + i.model : '')));
    const bits = [];
    if (i.n) bits.push(_t('Vu {0} fois', i.n));
    if (i.t) bits.push(_t('dernier passage {0}', new Date(i.t * 1000).toLocaleString()));
    if (i.reg) bits.push(_t('immat. {0}', i.reg));
    tx.append(el('div', 'note', bits.length ? bits.join(' · ') : "Pas encore vu au-dessus de chez vous"));
    const cur = catOf(code);
    if (editing === code) {
      const row = el('div', 'tcats');
      for (const c of T.categories) {
        const b = el('button', 'tcat' + (c === cur && known(code) ? ' on' : '')); b.append(planeSvg(T, c, 36), el('span', null, T.labels[c])); b.onclick = () => choose(code, c); row.append(b);
      }
      tx.append(row);
    }
    const act = el('div', 'tools v'), ed = el('button', 'b s' + (editing === code ? ' on' : ''), 'Modifier le type'); ed.onclick = () => { editing = editing === code ? null : code; draw(); }; act.append(ed);
    const ws = el('button', 'b s', 'Fiche sur internet ↗'); ws.onclick = () => web(code); act.append(ws);
    if (extra[code]) { const r = el('button', 'b s', builtin[code] ? "Rétablir l'icône d'origine" : 'Supprimer ce type'); r.onclick = () => { delete extra[code]; if (!builtin[code]) sel = null; draw(); persist(); }; act.append(r); }
    tx.append(act); top.append(tx); w.append(top); return w;
  };
  const toggleSel = code => { sel = sel === code ? null : code; editing = null; draw(); };
  let inTodo = new Set();
  function todoList() {
    todo.replaceChildren(); inTodo = new Set();
    const list = [];
    for (const e of T.seen) if (!known(e.code)) list.push(e);
    for (const u of T.unknown) { const c = u.toUpperCase(); if (!known(c) && !list.some(e => e.code === c)) list.push({code: c, n: 0, t: 0, model: '', suggest: null}); }
    if (!list.length && !(T.ignored || []).length) return;
    if (list.length) todo.append(el('h2', 't', 'À classer (types détectés mais inconnus)'));
    const box = el('div', 'card');
    for (const e of list) {
      inTodo.add(e.code);
      const r = el('div', 'tcl'), head = el('div', 'tvh'), t1 = el('div', 'lt');
      t1.append(el('b', null, e.code), el('small', null, [e.model, e.n ? _t('{0} passage(s)', e.n) : ''].filter(Boolean).join(' · ') || 'Modèle inconnu'));
      const sg = sug[e.code] || null;
      if (busy.has(e.code)) t1.append(el('span', 'tsug none', 'Recherche…'));
      else if (sg && sg.suggest) t1.append(el('span', 'tsug', _t('Suggestion : {0}', T.labels[sg.suggest]) + (sg.model ? ' · ' + (sg.source === 'icao' ? _t('base OACI : {0}', sg.model) : _t("d'après {0}", sg.model)) : '')));
      else if (sg && sg.error) t1.append(el('span', 'tsug none', "Recherche impossible (pas d'accès à internet ?)"));
      else if (sg) t1.append(el('span', 'tsug none', sg.model ? _t('Aucune suggestion pour {0}', sg.model) : 'Type introuvable dans la base OACI'));
      head.append(planeSvg(T, catOf(e.code), 34), t1); head.onclick = () => toggleSel(e.code);
      const acts = el('div', 'tacts');
      if (sg && sg.suggest) { const ok = el('button', 'b s', 'Accepter'); ok.onclick = ev => { ev.stopPropagation(); choose(e.code, sg.suggest); }; acts.append(ok); }
      else { const qs = el('button', 'b s', 'Suggérer'); qs.onclick = ev => { ev.stopPropagation(); if (!busy.has(e.code)) ask(e.code); }; acts.append(qs); }
      const ws = el('button', 'b s', 'Chercher sur internet ↗'); ws.onclick = ev => { ev.stopPropagation(); web(e.code); }; acts.append(ws);
      const ig = el('button', 'b s dg', 'Ignorer'); ig.title = tl("Donnée erronée : ce code n'apparaîtra plus dans cette liste");
      ig.onclick = async ev => { ev.stopPropagation(); try { await api('/api/types/ignore', {code: e.code}); T.ignored = (T.ignored || []).concat([e.code]); T.seen = T.seen.filter(x => x.code !== e.code); T.unknown = T.unknown.filter(x => x.toUpperCase() !== e.code); if (sel === e.code) sel = null; toast('Type ignoré'); draw(); } catch (er) { toast(er.message, true); } };
      acts.append(ig);
      head.append(acts); r.append(head);
      if (e.code === sel) r.append(detail(e.code));
      box.append(r);
    }
    if (list.length) todo.append(box);
    if ((T.ignored || []).length) {  // codes écartés : on peut les rétablir
      const ig = el('p', 'note', tl('Types ignorés :') + ' ');
      for (const c of T.ignored) { const b = el('button', 'lk', c + ' ↺'); b.title = tl('Rétablir'); b.onclick = async () => { try { await api('/api/types/ignore', {code: c, restore: true}); toast('Type rétabli'); const f = await api('/api/types'); T.seen = f.seen; T.unknown = f.unknown; T.ignored = f.ignored; draw(); } catch (er) { toast(er.message, true); } }; ig.append(b, document.createTextNode(' ')); }
      todo.append(ig);
    }
  }
  function catCards() {
    catList.replaceChildren();
    const all = new Set([...Object.keys(builtin), ...Object.keys(extra)]);
    if (query && /^[A-Z0-9]{2,6}$/.test(query) && !all.has(query)) {
      const a = el('button', 'b s', _t('Ajouter le type {0}', query)); a.onclick = () => { extra[query] = 'narrow'; sel = query; find.value = ''; query = ''; draw(); persist(); }; catList.append(a);
    }
    for (const c of T.categories) {
      const codes = [...all].filter(k => catOf(k) === c && (!query || k.includes(query))).sort();
      if (query && !codes.length) continue;
      const d = document.createElement('details'); d.className = 'tcard'; d.open = !!query || opened.has(c) || (sel && codes.includes(sel));
      d.ontoggle = () => { if (query) return; if (d.open) opened.add(c); else opened.delete(c); };
      const sm = document.createElement('summary'); sm.append(planeSvg(T, c, 34), el('b', null, T.labels[c]), el('small', null, _t('{0} types', codes.length))); d.append(sm);
      const row = el('div', 'tlist');
      for (const k of codes) { const sn = info[k] && info[k].n, b = el('button', 'tcode' + (sn ? ' seen' : '') + (k === sel ? ' on' : '') + (extra[k] ? ' mod' : ''), k); if (sn) b.title = _t('Vu {0} fois', sn); b.onclick = () => toggleSel(k); row.append(b); }
      d.append(row);
      if (sel && codes.includes(sel) && !inTodo.has(sel)) d.append(detail(sel));
      catList.append(d);
    }
  }
  function draw() { todoList(); catCards(); }
  find.oninput = () => { query = find.value.trim().toUpperCase(); catCards(); };
  cats.append(el('h2', 't', 'Types par catégorie'), el('p', 'note', 'En vert : types déjà vus au-dessus de chez vous (survolez pour le nombre de passages).'), bar, catList);
  box.append(todo, cats); draw();
  (async () => { for (const c of unknownCodes()) if (!sug[c]) await ask(c, true); })();
}

/* ---------- Carte : choix de la position, du rayon et aperçu de la zone affichée ---------- */
const LEAFLET = {
  js: ['https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js', 'sha512-puJW3E/qXDqYp9IfhAI54BJEaWIfloJ7JWs7OeD5i6ruC9JZL1gERT1wjtwXFlh7CjE7ZJ+/vcRZRkIYIb6p4g=='],
  css: ['https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css', 'sha512-h9FcoyWjHcOcmEVkxOfTLnmZFWIH0iZhZT1H2TbOq55xssQGEJHEaIm+PgoUaZbRvQTNTluNOEfb1ZRy6D3BOw==']
};
let leafletP = null, mapPick = null;
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (leafletP) return leafletP;
  leafletP = new Promise((ok, ko) => {
    const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = LEAFLET.css[0]; css.integrity = LEAFLET.css[1]; css.crossOrigin = 'anonymous'; document.head.append(css);
    const sc = document.createElement('script'); sc.src = LEAFLET.js[0]; sc.integrity = LEAFLET.js[1]; sc.crossOrigin = 'anonymous';
    sc.onload = () => ok(); sc.onerror = () => { leafletP = null; ko(new Error('leaflet')); }; document.head.append(sc);
  });
  return leafletP;
}
function mapPickDestroy() {
  if (!mapPick) return;
  for (const m of [mapPick.big, mapPick.pv]) { try { if (m) m.remove(); } catch (e) {} }
  mapPick = null;
}
function gcd(a, b) { return b ? gcd(b, a % b) : a; }
function renderMapPicker(box) {
  const P = k => allParams().find(p => p.id.endsWith(':' + k));
  const pLat = P('position.latitude'), pLon = P('position.longitude'), pRad = P('position.radius_km'), pW = P('display.width'), pH = P('display.height');
  if (!pLat || !pLon || !pRad || !pW || !pH) return;
  const num = (p, d) => { const v = parseFloat(String(pval(p)).replace(',', '.')); return isFinite(v) ? v : d; };
  box.append(el('h2', 't', 'Position et zone affichée'));
  box.append(el('p', 'note', "Cliquez sur la carte ou faites glisser le repère pour placer votre position. Le rectangle jaune est la zone que le programme affichera ; les cercles gris sont les cercles de distance. Les valeurs sont écrites dans les champs plus bas ; il faut ensuite enregistrer puis reconstruire la carte."));
  const sr = el('div', 'tools'), q = document.createElement('input'); q.type = 'text'; q.placeholder = 'Rechercher une adresse ou un lieu'; q.autocomplete = 'off';
  const go = el('button', 'b s', 'Chercher'); go.style.flex = 'none'; sr.append(q, go); box.append(sr);
  const res = el('p', 'note'); res.style.display = 'none'; box.append(res);
  const big = el('div', 'mpbig'); box.append(big);
  const info = el('p', 'note'); box.append(info);
  const rw = el('div', 'sl mprad'), rl = el('b', null, 'Taille de la zone'), rr = document.createElement('input'), rv = el('span');
  rr.type = 'range'; rr.min = 1; rr.max = 200; rr.step = 1; rr.value = Math.max(1, Math.min(200, Math.round(num(pRad, 20)))); rw.append(rl, rr, rv); box.append(rw);
  // cercles de distance : nombre, 1er cercle, ecartement (visibles seulement si les cercles sont affiches)
  const cw = el('div', 'sl mprad'), cl = el('b', null, 'Cercles'), cnt = el('div', 'mpcnt'), cm = el('button', null, '−'), cv = el('span'), cp = el('button', null, '+');
  cm.type = cp.type = 'button'; cm.title = tl('Moins de cercles'); cp.title = tl('Plus de cercles'); cnt.append(cm, cv, cp); cw.append(cl, cnt);
  const fw = el('div', 'sl mprad'), fl = el('b', null, '1er cercle'), fr = document.createElement('input'), fv = el('span');
  fr.type = 'range'; fr.min = 0.5; fr.step = 0.5; fw.append(fl, fr, fv);
  const ew = el('div', 'sl mprad'), el_ = el('b', null, 'Écartement'), er = document.createElement('input'), ev = el('span');
  er.type = 'range'; er.min = 0.5; er.step = 0.5; ew.append(el_, er, ev);
  box.append(cw, fw, ew);
  box.append(el('h2', 't', "Aperçu sur l'écran"));
  const pvw = el('div', 'mppv'), pv = el('div', 'mpprev'); pvw.append(pv); box.append(pvw);
  box.append(el('p', 'note', "Cet aperçu montre la même zone que la carte reconstruite, avec le fond OpenStreetMap assombri. Le fond réellement affiché sera celui de CARTO (routes, eau, pistes et noms de lieux), construit à la reconstruction."));
  const st = mapPick = {big: null, pv: null, alive: true};
  const syncInput = p => { const i = document.querySelector('[data-pid="' + p.id.replace(/"/g, '\\"') + '"]'); if (i) { i.value = pval(p); i.classList.toggle('chg', p.id in edits); } };
  const bounds = () => {
    const lat = num(pLat, NaN), lon = num(pLon, NaN), R = num(pRad, 20), W = num(pW, 1920), H = num(pH, 1080);
    if (!isFinite(lat) || !isFinite(lon) || H <= 0 || W <= 0) return null;
    const c = L.CRS.EPSG3857, pt = c.project(L.latLng(lat, lon)), k = 1 / Math.cos(lat * Math.PI / 180), hh = R * 1000 * k, hw = hh * W / H;
    return {lat, lon, R, W, H, b: L.latLngBounds(c.unproject(L.point(pt.x - hw, pt.y - hh)), c.unproject(L.point(pt.x + hw, pt.y + hh)))};
  };
  const RP = k => allParams().find(p => p.id === 'config:' + k);
  function drawRings(ll, R) {
    st.rings.clearLayers(); st.ringsPv.clearLayers();
    const on = String(pval(RP('rings.show'))) === 'true', n = parseInt(pval(RP('rings.count'))) || 0, f = parseFloat(pval(RP('rings.first_km'))) || 5, stp = parseFloat(pval(RP('rings.step_km'))) || 5;
    const w = parseInt(pval(RP('rings.width'))) || 1, col = pval(RP('rings.color')) || '#2d3746', lab = String(pval(RP('rings.show_labels'))) === 'true';
    if (on) for (let i = 0; i < n; i++) {
      const km = f + i * stp; if (km > R) break;
      for (const [grp, color, wt] of [[st.rings, '#8aa0bd', 1], [st.ringsPv, col, w]]) {
        L.circle(ll, {radius: km * 1000, color, weight: wt, fill: false, interactive: false}).addTo(grp);
        if (lab && grp === st.rings) L.marker(L.latLng(ll.lat + km / 110.574, ll.lng), {interactive: false, icon: L.divIcon({className: 'mpring', html: '<span>' + (Math.round(km * 100) / 100) + ' km</span>', iconSize: [50, 14], iconAnchor: [25, 14]})}).addTo(grp);
      }
    }
  }
  function refresh(fit) {
    if (!st.alive || !st.big) return;
    const g = bounds(), W = num(pW, 1920), H = num(pH, 1080), R = num(pRad, 20);
    rv.textContent = Math.round(R * 10) / 10 + ' km';
    const rp = RP('rings.show');
    if (rp) {
      const on = String(pval(rp)) === 'true', f0 = num(RP('rings.first_km'), 5), n0 = parseInt(pval(RP('rings.count'))) || 0;
      cw.style.display = on ? '' : 'none'; fw.style.display = on && n0 >= 1 ? '' : 'none'; ew.style.display = on && n0 >= 2 ? '' : 'none';
      const s0 = num(RP('rings.step_km'), 5);
      fr.max = er.max = Math.max(1, Math.round(R)); fr.value = Math.max(0.5, Math.min(+fr.max, f0)); fv.textContent = Math.round(f0 * 10) / 10 + ' km'; cv.textContent = n0;
      er.value = Math.max(0.5, Math.min(+er.max, s0)); ev.textContent = Math.round(s0 * 10) / 10 + ' km';
    }
    if (W > 0 && H > 0) { pvw.style.aspectRatio = W + ' / ' + H; const d = gcd(Math.round(W), Math.round(H)) || 1; var ratio = Math.round(W / d) + ':' + Math.round(H / d); }
    if (!g) { info.textContent = _t('Choisissez une position sur la carte.'); return; }
    const kmW = 2 * g.R * g.W / g.H, kmH = 2 * g.R;
    info.textContent = _t('Zone affichée : {0} km × {1} km (ratio {2}, {3} m par pixel).', (Math.round(kmW * 10) / 10).toLocaleString(), (Math.round(kmH * 10) / 10).toLocaleString(), ratio || '?', (Math.round(2 * g.R * 1000 / g.H * 10) / 10).toLocaleString());
    const ll = L.latLng(g.lat, g.lon);
    st.mk.setLatLng(ll); st.rect.setBounds(g.b);
    for (const l of [st.mk, st.rect]) if (!st.big.hasLayer(l)) l.addTo(st.big);
    st.home.setLatLng(ll); if (!st.pv.hasLayer(st.home)) st.home.addTo(st.pv);
    st.pv.invalidateSize({animate: false}); st.pv.fitBounds(g.b, {animate: false, padding: [0, 0]});
    if (fit) st.big.fitBounds(g.b, {animate: false, padding: [20, 20]});
    drawRings(ll, g.R);  // après les cadrages : Leaflet refuse de tracer un cercle sur une carte sans vue
  }
  function setPos(lat, lon, fit) {
    setEdit(pLat, String(Math.round(lat * 100000) / 100000)); setEdit(pLon, String(Math.round(((lon + 540) % 360 - 180) * 100000) / 100000));
    syncInput(pLat); syncInput(pLon); refresh(fit);
  }
  rr.oninput = () => { setEdit(pRad, String(rr.value)); syncInput(pRad); refresh(false); };
  fr.oninput = () => { const p = RP('rings.first_km'); setEdit(p, String(fr.value)); syncInput(p); refresh(false); };
  er.oninput = () => { const p = RP('rings.step_km'); setEdit(p, String(er.value)); syncInput(p); refresh(false); };
  const stepCount = d => { const p = RP('rings.count'), n = Math.max(0, Math.min(30, (parseInt(pval(p)) || 0) + d)); setEdit(p, String(n)); syncInput(p); refresh(false); };
  cm.onclick = () => stepCount(-1); cp.onclick = () => stepCount(1);
  rr.onchange = () => refresh(true);
  box.oninput = box.onchange = ev => { const t = ev.target; if (t && t.dataset && t.dataset.pid) { if (!st.alive) return; refresh(false); const sl = Math.round(num(pRad, 20)); if (String(sl) !== rr.value && sl >= 1 && sl <= 200) rr.value = sl; } };
  const search = async () => {
    const t = q.value.trim(); if (!t) return;
    res.style.display = 'block'; res.textContent = _t('Recherche…');
    try {
      const r = await fetch('https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' + encodeURIComponent(t));
      const d = await r.json();
      if (!d.length) { res.textContent = _t('Aucun résultat'); return; }
      res.textContent = d[0].display_name; setPos(parseFloat(d[0].lat), parseFloat(d[0].lon), true);
    } catch (e) { res.textContent = _t("Recherche impossible (pas d'accès à internet ?)"); }
  };
  go.onclick = search; q.onkeydown = ev => { if (ev.key === 'Enter') { ev.preventDefault(); search(); } };
  loadLeaflet().then(() => {
    if (!box.contains(big)) return;
    const tiles = () => L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'});
    st.big = L.map(big, {zoomControl: true, worldCopyJump: true}); tiles().addTo(st.big);
    st.pv = L.map(pv, {zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false, boxZoom: false, keyboard: false, touchZoom: false, zoomSnap: 0, attributionControl: true});
    tiles().addTo(st.pv); st.pv.attributionControl.setPrefix('');
    st.mk = L.marker([0, 0], {draggable: true, icon: L.divIcon({className: 'mppin', html: '<i></i>', iconSize: [22, 22], iconAnchor: [11, 11]})});
    st.rect = L.rectangle([[0, 0], [1, 1]], {color: '#ffd250', weight: 3, fillColor: '#ffd250', fillOpacity: 0.08, interactive: false});
    st.home = L.circleMarker([0, 0], {radius: 5, color: '#ffc83c', fillColor: '#ffc83c', fillOpacity: 1, weight: 1, interactive: false});
    st.rings = L.layerGroup().addTo(st.big); st.ringsPv = L.layerGroup().addTo(st.pv);
    st.mk.on('dragend', () => { const l = st.mk.getLatLng(); setPos(l.lat, l.lng, false); });
    st.big.on('click', ev => setPos(ev.latlng.lat, ev.latlng.lng, false));
    st.big.setView([46.6, 2.4], 5);
    refresh(true);
    setTimeout(() => { if (st.alive) { st.big.invalidateSize(); refresh(true); } }, 150);
  }).catch(e => { console.error(e); big.className = 'note'; big.textContent = _t("La carte n'a pas pu être chargée (accès à internet nécessaire depuis ce navigateur). Vous pouvez toujours saisir les valeurs dans les champs ci-dessous."); pvw.remove(); });
}

/* ---------- Style de la carte : thème, éléments, couleurs, noms de lieux, aperçu réel ---------- */
let msAlive = false;
function renderMapStyle(box, cat) {
  msAlive = true;
  const P = (sec, key) => allParams().find(p => p.id === 'config:' + sec + '.' + key);
  const V = (sec, key) => pval(P(sec, key));
  const layerParam = id => id === 'forest' ? P('map', 'forest') : P('mapstyle', 'show_' + id);
  const presets = cat.presets, colorKeys = cat.color_keys;
  const chg = (p, el_) => { if (el_) el_.classList.toggle('chg', p.id in edits); };
  const styleNow = () => {
    const show = {}; for (const l of cat.layers) show[l.id] = String(pval(layerParam(l.id))) === 'true';
    const colors = {}; for (const k of colorKeys) { const v = V('mapstyle', 'color_' + k); if (v) colors[k] = v; }
    return {preset: V('mapstyle', 'preset'), show, colors, road_width: parseFloat(V('mapstyle', 'road_width')) || 1};
  };
  const citiesNow = () => ({show: String(V('cities', 'show')) === 'true', kinds: String(V('cities', 'kinds')).split(',').map(x => x.trim()).filter(Boolean), max_labels: parseInt(V('cities', 'max_labels')) || 0, font_size: parseInt(V('cities', 'font_size')) || 20});
  const geo = () => ({lat: parseFloat(V('position', 'latitude')), lon: parseFloat(V('position', 'longitude')), radius_km: parseFloat(V('position', 'radius_km')), width: parseInt(V('display', 'width')), height: parseInt(V('display', 'height'))});

  /* aperçu : indicatif et instantané (carte d'exemple fournie par thème), ou fidèle à la demande (rendu serveur) */
  box.append(el('h2', 't', 'Aperçu'));
  const pvw = el('div', 'msprev'), img = document.createElement('img'); img.alt = ''; img.className = 'msimg'; pvw.append(img);
  const msg = el('p', 'note'), again = el('button', 'b s', "Mettre à jour l'aperçu"), stop = el('button', 'b s', 'Annuler'); again.style.marginTop = '4px'; stop.style.display = 'none';
  const lg = document.createElement('details'), lgs = document.createElement('summary'), log = document.createElement('pre'); lg.className = 'mslogbox'; lgs.textContent = _t('Suivi en direct'); log.className = 'mslog'; lg.append(lgs, log);
  const cur = el('button', 'b s', 'Voir la carte actuelle'); cur.style.marginTop = '4px';
  const bar = el('div', 'tools'); bar.append(again, cur, stop);
  box.append(pvw, msg, bar, lg);
  box.append(el('p', 'note', "L'aperçu fidèle est dessiné par le même programme que la vraie carte, pour la zone et le ratio de la page Carte et position, avec tous vos réglages (modifications non enregistrées comprises). Il ne modifie pas la vraie carte : une fois l'aperçu validé, enregistrez puis reconstruisez la carte (section « Reconstruction de la carte », en bas de cette page)."));

  /* thèmes */
  box.append(el('h2', 't', 'Thème'));
  const grid = el('div', 'msthemes'), cards = {};
  for (const [id, pr] of Object.entries(presets)) {
    const c = el('button', 'mscard'), th = document.createElement('img'); th.alt = ''; th.className = 'msth';
    th.style.background = pr.colors.land;
    const sw = el('div', 'msw'); for (const k of ['water', 'forest', 'aero', 'road_high', 'runway', 'label']) { const i = el('i'); i.style.background = pr.colors[k]; sw.append(i); }
    c.append(th, el('span', null, pr.label), sw);
    c.onclick = () => {
      setEdit(P('mapstyle', 'preset'), id);
      for (const k of colorKeys) if (V('mapstyle', 'color_' + k)) setEdit(P('mapstyle', 'color_' + k), '');
      syncAll(); showStatic();
    };
    cards[id] = {c, th}; grid.append(c);
  }
  box.append(grid);

  /* éléments */
  box.append(el('h2', 't', 'Éléments affichés'));
  const lst = el('div', 'list'), tgs = {};
  for (const l of cat.layers) {
    const p = layerParam(l.id), row = el('div', 'li'), t = el('div', 'lt'); t.append(el('b', null, l.label));
    const tg = toggle(String(pval(p)) === 'true', on => { setEdit(p, on ? 'true' : 'false'); chg(p, tg.label); markStale(); });
    chg(p, tg.label); tgs[l.id] = tg; row.append(t, tg.label); lst.append(row);
  }
  box.append(lst);
  const rwp = P('mapstyle', 'road_width'), rrow = el('div', 'li'), rt = el('div', 'lt'), rwc = el('div', 'sl'), rw = document.createElement('input'), rwl = el('span');
  rt.append(el('b', null, 'Épaisseur des routes'));
  rw.type = 'range'; rw.min = 0.5; rw.max = 3; rw.step = 0.1; rw.value = V('mapstyle', 'road_width'); rwl.textContent = '× ' + rw.value;
  rw.oninput = () => { rwl.textContent = '× ' + rw.value; setEdit(rwp, String(rw.value)); chg(rwp, rwc); markStale(); };
  rwc.append(rw, rwl); rrow.append(rt, rwc); lst.append(rrow);

  /* noms de lieux */
  box.append(el('h2', 't', 'Noms de lieux'));
  const cl = el('div', 'list'), cshow = P('cities', 'show'), ck = P('cities', 'kinds'), cmax = P('cities', 'max_labels'), cfs = P('cities', 'font_size');
  const r1 = el('div', 'li'), t1 = el('div', 'lt'); t1.append(el('b', null, 'Afficher les noms de lieux'));
  const tgc = toggle(String(pval(cshow)) === 'true', on => { setEdit(cshow, on ? 'true' : 'false'); chg(cshow, tgc.label); markStale(); }); r1.append(t1, tgc.label); cl.append(r1);
  const r2 = el('div', 'li full'), t2 = el('div', 'lt'); t2.append(el('b', null, 'Types de lieux'));
  const seg = el('div', 'kinds'), kindLabel = {city: 'Villes', town: 'Petites villes', village: 'Villages'};
  const setKinds = () => { const k = cat.city_kinds.filter(x => seg.querySelector('[data-k="' + x + '"]').classList.contains('on')); setEdit(ck, k.join(',')); markStale(); };
  const nowKinds = String(pval(ck)).split(',').map(x => x.trim());
  for (const k of cat.city_kinds) { const b = el('button', 'tcode' + (nowKinds.includes(k) ? ' on' : ''), kindLabel[k] || k); b.dataset.k = k; b.onclick = () => { b.classList.toggle('on'); setKinds(); }; seg.append(b); }
  r2.append(t2, seg); cl.append(r2);
  const slider = (p, label, min, max, step, fmt) => {
    const row = el('div', 'li'), t = el('div', 'lt'), c = el('div', 'sl'), r = document.createElement('input'), l = el('span');
    t.append(el('b', null, label)); r.type = 'range'; r.min = min; r.max = max; r.step = step; r.value = pval(p); l.textContent = fmt(r.value);
    r.oninput = () => { l.textContent = fmt(r.value); setEdit(p, String(r.value)); chg(p, c); markStale(); };
    c.append(r, l); row.append(t, c); return row;
  };
  cl.append(slider(cmax, 'Nombre maximum de noms', 0, 100, 1, v => v), slider(cfs, 'Taille du texte', 10, 40, 1, v => v + ' px'));
  box.append(cl);

  /* couleurs */
  const det = document.createElement('details'); det.className = 'tcard';
  const sm = document.createElement('summary'); sm.append(el('b', null, 'Couleurs personnalisées'), el('small', null, 'optionnel')); det.append(sm);
  det.append(el('p', 'note', "Par défaut, les couleurs du thème choisi. Une couleur modifiée ici remplace celle du thème ; choisir un autre thème les remet à zéro."));
  const cg = el('div', 'mscolors'), cin = {};
  for (const k of colorKeys) {
    const p = P('mapstyle', 'color_' + k), w = el('label', 'mscol'), i = document.createElement('input'), rs = el('button', 'b s', '↺');
    i.type = 'color'; rs.title = 'Couleur du thème'; rs.style.display = 'none';
    i.oninput = () => { setEdit(p, i.value); sync(k); markStale(); };
    rs.onclick = ev => { ev.preventDefault(); setEdit(p, ''); sync(k); markStale(); };
    w.append(i, el('span', null, cat.color_labels[k]), rs); cin[k] = {i, rs}; cg.append(w);
  }
  det.append(cg); box.append(det);
  function sync(k) { const v = V('mapstyle', 'color_' + k); cin[k].i.value = v || presets[V('mapstyle', 'preset')].colors[k]; cin[k].rs.style.display = v ? '' : 'none'; }
  function syncAll() { for (const k of colorKeys) sync(k); for (const id in cards) cards[id].c.classList.toggle('on', id === V('mapstyle', 'preset')); }
  syncAll();
  box.append(el('p', 'note', "Les noms de lieux, les routes et les autres éléments proviennent du fond vectoriel CARTO. Avec un fond clair, les avions jaunes ressortent moins : préférez un thème sombre pour un écran lisible de loin."));

  /* aperçu indicatif : une carte d'exemple fournie par thème (générée avec CARTO sur la zone d'origine) ; les vignettes sont ces mêmes images et ne changent jamais */
  let busy = false, mode = 'static';
  const themeSrc = id => '/api/mapstyle/theme?id=' + encodeURIComponent(id);
  for (const id in cards) cards[id].th.src = themeSrc(id);
  function showStatic() {
    mode = 'static'; msg.classList.remove('err'); again.classList.add('p');
    img.src = themeSrc(V('mapstyle', 'preset'));
    msg.textContent = _t("Aperçu indicatif : carte d'exemple (zone d'origine) du thème choisi. « Mettre à jour l'aperçu » affiche le rendu fidèle de votre zone, avec tous vos réglages.");
  }
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  function markStale() { if (busy) return; msg.classList.remove('err'); msg.textContent = _t("Les réglages ont changé : l'aperçu affiché n'est plus à jour."); again.classList.add('p'); }
  const showLog = st => { log.textContent = st.lines.join('\n'); log.scrollTop = log.scrollHeight; };
  async function refresh() {
    if (!msAlive || !box.isConnected || busy) return;
    busy = true; again.classList.remove('p');
    const g = geo();
    msg.classList.remove('err'); again.disabled = true; stop.style.display = ''; lg.open = true;
    if (isFinite(g.width) && isFinite(g.height) && g.height > 0) pvw.style.aspectRatio = g.width + ' / ' + g.height;
    try {
      let st = await api('/api/mapstyle/preview');
      if (!st.running) await api('/api/mapstyle/preview', Object.assign({}, g, {style: styleNow(), cities: citiesNow(), presets: []}));
      for (;;) {
        await sleep(1000); if (!msAlive) return;
        st = await api('/api/mapstyle/preview'); showLog(st);
        msg.textContent = _t("Génération de l'aperçu… {0} s", st.elapsed);
        if (!st.running) break;
      }
      if (st.error) throw new Error(st.error);
      if (st.files.includes('current.png')) img.src = '/api/mapstyle/img?name=current.png&t=' + Math.round(st.t);
      mode = 'real'; msg.textContent = tl("Aperçu fidèle de votre zone et de vos réglages. La vraie carte n'est pas modifiée : enregistrez puis reconstruisez-la pour l'utiliser."); lg.open = false;
    } catch (e) { msg.textContent = e.message; msg.classList.add('err'); }
    busy = false; again.disabled = false; stop.style.display = 'none';
  }
  cur.onclick = async () => {  // la carte réellement utilisée par le programme d'affichage (background.png)
    if (busy) return;
    msg.classList.remove('err');
    try {
      const r = await fetch('/api/mapstyle/current', {cache: 'no-store'});
      if (!r.ok) { msg.textContent = tl("Aucune carte n'a encore été construite."); msg.classList.add('err'); return; }
      const lm = r.headers.get('Last-Modified'), blob = await r.blob();
      img.src = URL.createObjectURL(blob); mode = 'current'; again.classList.remove('p');
      msg.textContent = _t('Carte actuellement utilisée par le programme (construite {0}).', lm ? new Date(lm).toLocaleString() : '?');
    } catch (e) { msg.textContent = e.message; msg.classList.add('err'); }
  };
  stop.onclick = async () => { try { await api('/api/mapstyle/cancel', {}); } catch (e) { toast(e.message, true); } };
  again.onclick = () => refresh();
  { const g = geo(); if (isFinite(g.width) && isFinite(g.height) && g.height > 0) pvw.style.aspectRatio = g.width + ' / ' + g.height; }
  showStatic();
  (async () => { try { const st = await api('/api/mapstyle/preview'); if (st.running) refresh(); } catch (e) {} })();
}

/* ---------- Sauvegarde et restauration ---------- */
function renderBackup(box) {
  box.append(el('h2', 't', 'Exporter la configuration'));
  const l1 = el('div', 'list'), r1 = el('div', 'li'), t1 = el('div', 'lt');
  t1.append(el('b', null, 'Inclure les mots de passe et la clé CARTO'), el('small', null, "Nécessaire pour tout retrouver après une panne. Le fichier contient alors des secrets : ne le partagez pas et gardez-le en lieu sûr."));
  const tg = toggle(true, () => {}); r1.append(t1, tg.label); l1.append(r1);
  const r2 = el('div', 'li stack'), dl = el('button', 'b p', 'Télécharger la sauvegarde');
  dl.onclick = async () => {
    try {
      const r = await fetch('/api/backup?secrets=' + (tg.input.checked ? 1 : 0), {headers: {'X-Admin': '1'}});
      if (!r.ok) throw new Error(((await r.json().catch(() => ({}))).error) || ('Erreur HTTP ' + r.status));
      const m = /filename="([^"]+)"/.exec(r.headers.get('Content-Disposition') || ''), a = document.createElement('a');
      a.href = URL.createObjectURL(await r.blob()); a.download = m ? m[1] : 'flightdisplay-backup.zip'; document.body.append(a); a.click(); a.remove();
      toast('Sauvegarde téléchargée');
    } catch (e) { toast(e.message, true); }
  };
  r2.append(dl); l1.append(r2); box.append(l1);
  box.append(el('p', 'note', 'La sauvegarde contient config.ini (réglages, avec ou sans les secrets), la liste des types d\'avion, l\'état du son et la carte déjà construite (background.png et map_meta.json). Les photos ne sont pas incluses.'));
  box.append(el('h2', 't', 'Restaurer une sauvegarde'));
  const l2 = el('div', 'list'), r3 = el('div', 'li stack'), t3 = el('div', 'lt');
  t3.append(el('b', null, 'Choisir un fichier de sauvegarde'), el('small', null, "Remplace la configuration actuelle. Une sauvegarde sans secrets garde ceux de cette installation."));
  const fi = document.createElement('input'); fi.type = 'file'; fi.accept = '.zip'; fi.style.marginTop = '8px'; t3.append(fi);
  const r4 = el('div', 'li stack'), rb = el('button', 'b d', 'Restaurer'); rb.disabled = true;
  fi.onchange = () => { rb.disabled = !fi.files.length; };
  rb.onclick = async () => {
    const f = fi.files[0]; if (!f) return;
    if (!confirm(_t('Restaurer la configuration depuis « {0} » ? Les réglages actuels seront remplacés.', f.name))) return;
    try {
      const bytes = new Uint8Array(await f.arrayBuffer()); let bin = ''; for (let i = 0; i < bytes.length; i += 8192) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
      const r = await api('/api/backup/restore', {data: btoa(bin)});
      toast('Configuration restaurée'); fi.value = ''; rb.disabled = true;
      if (r.lang_changed) { setTimeout(() => location.reload(), 1200); return; }
      await loadSettings(); pend = {app: true, web: !!r.restart_web, port: r.port}; showPending();
    } catch (e) { toast(e.message, true); }
  };
  r3.append(t3); r4.append(rb); l2.append(r3, r4); box.append(l2);
}

/* ---------- Stockage et photos ---------- */
async function renderStorage(box) {
  const wrap = el('div'); box.append(wrap);
  async function load() {
    let d; try { d = await api('/api/storage'); } catch (e) { wrap.textContent = e.message; return; }
    if (!wrap.isConnected) return;
    wrap.innerHTML = '';
    const k = d.disk, ph = d.cache.photos;
    if (k) {
      const photoPct = ph.bytes / k.total * 100, photoOfUsed = k.used ? ph.bytes / k.used * 100 : 0;
      wrap.append(el('h2', 't', 'Disque'));
      const card = el('div', 'list'), row = el('div', 'li stack'), lt = el('div', 'lt');
      lt.append(el('b', null, _t('{0} % utilisés', fmtPct(k.pct))), el('small', null, _t('{0} utilisés sur {1} ({2} libres)', fmtBytes(k.used), fmtBytes(k.total), fmtBytes(k.free))));
      const bar = el('div', 'sbar ' + k.level), su = el('i', 'su'), sp = el('i', 'sp'), sw = el('i', 'sw');
      su.style.width = k.pct + '%'; sp.style.width = Math.max(photoPct, ph.bytes ? 0.4 : 0) + '%'; sw.style.left = k.warn + '%';
      bar.append(su, sp, sw);
      const leg = el('div', 'sleg ' + k.level);
      leg.append(el('span', 'l-u', 'Espace utilisé'), el('span', 'l-p', 'Photos en cache'), el('span', 'l-w', _t('Seuil d\'alerte : {0} %', k.warn)));
      lt.append(bar, leg); row.append(lt); card.append(row);
      if (k.level !== 'ok') {
        const w = el('div', 'li stack'); w.style.borderLeft = '3px solid var(--' + (k.level === 'critical' ? 'bad' : 'warn') + ')';
        const wt = el('div', 'lt'); wt.append(el('b', null, k.level === 'critical' ? _t('Disque presque plein') : _t('Le disque se remplit')), el('small', null, k.level === 'critical' ? 'Libérez de l\'espace : videz le cache des photos ci-dessous, puis supprimez les fichiers inutiles (journaux, anciennes sauvegardes).' : 'Pensez à vider le cache des photos ou à libérer de l\'espace avant que le disque ne soit plein.'));
        w.append(wt); card.append(w);
      }
      wrap.append(card);
      wrap.append(el('h2', 't', 'Photos JetPhotos en cache'));
      const c2 = el('div', 'list');
      const line = (title, sub) => { const r = el('div', 'li'), t = el('div', 'lt'); t.append(el('b', null, title)); if (sub) t.append(el('small', null, sub)); r.append(t); return r; };
      c2.append(line(_t('{0} photo(s)', ph.count), ph.oldest ? _t('La plus ancienne date d\'il y a {0}', fmtIn(d.cache.now - ph.oldest)) : 'Aucune photo en cache'));
      c2.append(line(_t('Volume des photos : {0}', fmtBytes(ph.bytes)), _t('{0} % du disque, {1} % de l\'espace utilisé', fmtPct(photoPct), fmtPct(photoOfUsed))));
      c2.append(line(_t('Autres fichiers du cache : {0}', fmtBytes(d.cache.other)), 'Détails des avions, état du son, mise à jour.'));
      const br = el('div', 'li stack'), bb = el('button', 'b d', 'Vider le cache des photos'); bb.disabled = !ph.count;
      bb.onclick = async () => {
        if (!confirm(_t('Supprimer les {0} photo(s) en cache ({1}) ? Elles seront retéléchargées au besoin.', ph.count, fmtBytes(ph.bytes)))) return;
        try { const r = await api('/api/storage/clear', {}); toast(_t('{0} photo(s) supprimée(s) ({1} libérés)', r.count, fmtBytes(r.bytes))); pollStatus(); load(); } catch (e) { toast(e.message, true); }
      };
      const cl = d.clean;
      c2.append(line(cl.auto ? _t('Nettoyage automatique activé : quota de {0}', fmtBytes(cl.quota)) : 'Nettoyage automatique désactivé',
        cl.auto ? _t("Au-delà du quota, les photos les plus anciennes sont supprimées jusqu'à {0} ; les plus récentes sont gardées.", fmtBytes(cl.quota * 0.8))
                : "Activez-le dans les réglages ci-dessous : le cache reste alors sous un quota, sans intervention."));
      br.append(bb); c2.append(br); wrap.append(c2);
      wrap.append(el('h2', 't', 'Journal du nettoyage'));
      const jl = el('div', 'list');
      if (!cl.log.length) jl.append(line('Aucun nettoyage pour le moment', 'Les nettoyages automatiques et manuels des photos sont inscrits ici.'));
      for (const e of cl.log) {
        const when = new Date(e.t * 1000).toLocaleString();
        jl.append(line(e.kind === 'auto'
          ? _t('Nettoyage automatique : {0} photo(s) supprimée(s) ({1} libérés)', e.count, fmtBytes(e.bytes))
          : _t('Cache vidé à la main : {0} photo(s) supprimée(s) ({1} libérés)', e.count, fmtBytes(e.bytes)),
          e.kind === 'auto' ? _t('{0} · cache de {1} ramené à {2} (quota {3})', when, fmtBytes(e.before), fmtBytes(e.after), fmtBytes(e.quota)) : when));
      }
      wrap.append(jl);
    }
  }
  await load();
  const iv = setInterval(() => { if (!wrap.isConnected) clearInterval(iv); else if (cur === 'cfg' && curCat === 'storage') load(); }, 10000);
}

/* ---------- Avions vus : l'historique, en cartes ou en liste, avec filtres et pages ---------- */
const HV = (() => { try { return JSON.parse(localStorage.getItem('histView') || '{}'); } catch (e) { return {}; } })();
let HIST = null, histQ = '', histPeriod = HV.period || 'all', histSort = HV.sort || 'recent', histMode = HV.mode || 'cards', histPer = HV.per || 24;
let fType = new Set(), fAir = new Set(), fBrand = new Set(), fFam = new Set(), fSrc = new Set(), histAlert = false, histTc = false, histOpen = '', histMq = '', histPage = 1;
const histSave = () => { try { localStorage.setItem('histView', JSON.stringify({period: histPeriod, sort: histSort, mode: histMode, per: histPer})); } catch (e) {} };
async function loadHist() {
  try { HIST = await api('/api/history'); } catch (e) { toast(e.message, true); return; }
  buildHist(); drawHist(); drawCls();
}
let histTab = 'hist';
let clsId = '', clsSt = {edit: false};
const clsLook = {};  // adresse -> résultat de la recherche (adsbdb.com, hexdb.io, tar1090-db) ou erreur
function classifyBlock(e, st, redraw, done) {
  // Bloc de classement d'un avion, partagé par l'onglet « À classer » et la fiche d'un avion : suggestion cherchée toute seule, « Appliquer »,
  // formulaire (catégorie, type ICAO, modèle) et suppression de l'avion. st.edit : formulaire affiché ; redraw : redessine ; done : après une action.
  const box = el('div', 'cblk'), L = clsLook[e.id];
  const catName = k => { const m = HIST.cats.find(x => x[0] === k); return m ? m[1] : ''; };
  const sg = el('div', 'csg');
  if (L === undefined) {
    sg.textContent = tl('Recherche…'); clsLook[e.id] = null;
    api('/api/aircraft/lookup?id=' + encodeURIComponent(e.id)).then(r => { clsLook[e.id] = r; }).catch(er => { clsLook[e.id] = {error: er.message}; }).then(() => { if (box.isConnected) redraw(); });
  } else if (L === null) sg.textContent = tl('Recherche…');
  else if (L.error) { sg.textContent = L.error; sg.className = 'csg none'; }
  else if (!L.found) { sg.textContent = tl('Aucune suggestion trouvée : classez-le à la main, ou supprimez-le.'); sg.className = 'csg none'; }
  else sg.textContent = _t('Trouvé sur {0} : {1}', L.source, [L.model, L.code, catName(L.cat)].filter(Boolean).join(' · '));
  box.append(sg);
  const found = !!(L && L.found), act = el('div', 'cact');
  const run = async (body, msg) => { body = Object.assign({reg: e.mreg || ''}, body); await run0(body, msg); };
  const run0 = async (body, msg) => { try { await api('/api/aircraft/manual', Object.assign({id: e.id}, body)); toast(msg); await done(); } catch (er) { toast(er.message, true); } };
  if (found) {
    const ap = el('button', 'b s p', 'Appliquer la suggestion');
    ap.onclick = () => run({cat: L.cat || '', code: L.code || '', model: L.model || ''}, 'Classement enregistré'); act.append(ap);
    const ed = el('button', 'b s', st.edit ? 'Masquer le formulaire' : 'Modifier à la main'); ed.onclick = () => { st.edit = !st.edit; redraw(); }; act.append(ed);
  }
  const hasMan = !!(e.mc || e.mcode || e.mmodel || e.mreg);
  if (hasMan) { const rs = el('button', 'b s', 'Retirer le classement'); rs.onclick = () => run({cat: '', code: '', model: '', reg: ''}, 'Classement retiré'); act.append(rs); }
  const del = el('button', 'b s dg', 'Supprimer cet avion');
  del.onclick = async () => { if (!confirm(tl("Supprimer cet avion de l'historique ? S'il repasse, il réapparaîtra."))) return; try { await api('/api/history/delete', {ids: [e.id]}); toast('Avion supprimé'); await done(); } catch (er) { toast(er.message, true); } };
  act.append(del);
  box.append(act);
  if (st.edit || (L !== undefined && L !== null && !found) || hasMan) {  // pas de suggestion (ou classement déjà fait) : le formulaire est directement là
    const fm = el('div', 'hcls'), sl = document.createElement('select'); sl.append(new Option(tl('Catégorie automatique'), ''));
    for (const [k, l] of HIST.cats) sl.append(new Option(l, k));
    const cd = document.createElement('input'); cd.placeholder = tl('Type ICAO (ex. C172)'); cd.maxLength = 6;
    const md = document.createElement('input'); md.placeholder = tl('Modèle (ex. Cessna 172)'); md.maxLength = 80;
    const rg = document.createElement('input'); rg.placeholder = tl('Immatriculation (ex. F-HURY)'); rg.maxLength = 12; rg.value = e.mreg || '';
    if (hasMan) { sl.value = e.mc || ''; cd.value = e.mcode || ''; md.value = e.mmodel || ''; }
    else if (found) { sl.value = L.cat || ''; cd.value = L.code || ''; md.value = L.model || ''; if (!e.reg && L.reg) rg.value = L.reg; }
    const sv = el('button', 'b s p', 'Enregistrer le classement');
    sv.onclick = () => { if (!sl.value && !cd.value.trim() && !md.value.trim() && !rg.value.trim()) { toast('Choisissez une catégorie, un type, un modèle ou une immatriculation', true); return; } run({cat: sl.value, code: cd.value, model: md.value, reg: rg.value}, 'Classement enregistré'); };
    fm.append(sl, cd, md, rg, sv); box.append(fm);
  }
  return box;
}
function exLinks(e) {  // liens vers d'autres sites, discrets
  const ln = el('div', 'clnk'), add = (t, u) => { const b = el('button', 'lk', t); b.onclick = () => window.open(u, '_blank', 'noopener'); ln.append(b); };
  if (e.reg) { add('Photos sur JetPhotos ↗', 'https://www.jetphotos.com/registration/' + encodeURIComponent(e.reg)); add('Historique Flightradar24 ↗', 'https://www.flightradar24.com/data/aircraft/' + encodeURIComponent(e.reg.toLowerCase())); }
  add('Chercher sur internet ↗', 'https://www.google.com/search?q=' + encodeURIComponent((e.reg || e.cs || e.id) + ' aircraft'));
  return ln;
}
function drawCls() {  // onglet « À classer » : liste à gauche, fiche de l'avion choisi à droite (suggestion cherchée toute seule)
  const c = $('#hCls'); if (!c) return; c.replaceChildren();
  const list = HIST.entries.filter(e => e.tc), tb = $('#hTabCls'); if (tb) tb.textContent = _t('À classer ({0})', list.length);
  if (!list.length) { c.append(el('p', 'note', 'Aucun avion à classer.')); return; }
  if (!list.some(e => e.id === clsId)) { clsId = list[0].id; clsSt.edit = false; }
  const e = list.find(x => x.id === clsId);
  const lay = el('div', 'cls2'), lc = el('div', 'card'), pn = el('div', 'card cpn');
  for (const x of list.slice(0, 300)) {
    const r = el('button', 'cli' + (x.id === clsId ? ' on' : '')); r.append(el('b', null, x.reg || x.cs || x.id), el('small', null, ago(x.l || x.t)));
    r.onclick = () => { clsId = x.id; clsSt.edit = false; drawCls(); }; lc.append(r);
  }
  const q = () => el('span', 'q', '?'), kv = el('div', 'ckv'), row = (k, v) => { kv.append(el('i', null, k)); const s = el('span'); if (v) s.textContent = v; else s.append(q()); kv.append(s); };
  pn.append(el('h3', null, e.reg || e.cs || e.id));
  row('Immatriculation', e.reg); row('Indicatif', e.cs); row('Adresse ICAO', /^[0-9a-f]{6}$/.test(e.id) ? e.id : ''); row('Type ICAO', e.code);
  row('Modèle', e.model && e.model !== '?' ? e.model : ''); row('Compagnie', e.airline); row('Passages', _t('{0} · dernier {1}', e.n, ago(e.l || e.t)));
  pn.append(kv, classifyBlock(e, clsSt, drawCls, async () => { clsSt.edit = false; await loadHist(); }), exLinks(e));
  lay.append(lc, pn); c.append(lay);
}
function setHistTab(v) {
  histTab = v;
  for (const [id, k] of [['hTabHist', 'hist'], ['hTabCls', 'cls']]) { const b = $('#' + id); if (b) b.classList.toggle('on', k === v); }
  const a = $('#hView'), b = $('#hCls'); if (a) a.style.display = v === 'hist' ? '' : 'none'; if (b) b.style.display = v === 'cls' ? '' : 'none';
}
function buildHist() {
  const box = $('#t-hist'); if (box.dataset.ready) return; box.dataset.ready = '1';
  const bar = el('div', 'hbar'), q = document.createElement('input'); q.type = 'search'; q.autocomplete = 'off'; q.placeholder = tl('Rechercher un avion, une compagnie, une ville…');
  q.oninput = () => { histQ = q.value; histPage = 1; drawHist(); };
  const per = document.createElement('select'); per.style.width = 'auto'; per.title = tl('Avions par page');
  for (const n of [12, 24, 48, 96, 200]) { const o = el('option', null, _t('{0} par page', n)); o.value = n; per.append(o); }
  per.value = histPer; per.onchange = () => { histPer = +per.value; histSave(); histPage = 1; drawHist(); };
  const mode = el('div', 'seg hmode'), ICO = {cards: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5"/></svg>', list: '<svg viewBox="0 0 24 24"><path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r=".8"/><circle cx="3.5" cy="12" r=".8"/><circle cx="3.5" cy="18" r=".8"/></svg>'};
  for (const [v, tt] of [['cards', 'Cartes'], ['list', 'Liste']]) {
    const b = el('button', histMode === v ? 'on' : ''); b.innerHTML = ICO[v]; b.title = tl(tt); b.setAttribute('aria-label', tl(tt)); b.dataset.v = v;
    b.onclick = () => { histMode = v; histSave(); mode.querySelectorAll('button').forEach(x => x.classList.toggle('on', x.dataset.v === v)); histPage = 1; drawHist(); }; mode.append(b);
  }
  bar.append(q, mode, per);
  const main = el('div', 'hmain'), filt = el('div', 'hfbar'), act = el('div', 'hact');
  filt.id = 'hFilt'; act.id = 'hAct';
  const p1 = el('div', 'hpager'); p1.id = 'hPg1';
  const res = el('div'); res.id = 'hRes';
  const p2 = el('div', 'hpager'); p2.id = 'hPg2';
  const empty = el('p', 'note'); empty.id = 'hEmpty';
  main.append(filt, act, p1, res, p2, empty);
  const hv = el('div'); hv.id = 'hView'; hv.append(bar, main);
  const tabs = el('div', 'seg'), t1 = el('button', 'on', 'Historique'), t2 = el('button', '', 'À classer'), cv = el('div'); cv.id = 'hCls'; cv.style.display = 'none';
  t1.id = 'hTabHist'; t2.id = 'hTabCls'; t1.onclick = () => setHistTab('hist'); t2.onclick = () => setHistTab('cls'); tabs.append(t1, t2); tabs.style.marginBottom = '12px';
  box.append(tabs, hv, cv);
  document.addEventListener('keydown', ev => {
    const o = document.querySelector('.hover'); if (!o) return;
    if (ev.key === 'Escape') o.remove();
    else if (ev.key === 'ArrowLeft' && o._nav) o._nav(-1);
    else if (ev.key === 'ArrowRight' && o._nav) o._nav(1);
  });
  document.addEventListener('click', ev => { if (histOpen && !(ev.target.closest && ev.target.closest('.hmw'))) { histOpen = ''; if (HIST) drawFilters(histPick().length); } });
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && histOpen) { histOpen = ''; if (HIST) drawFilters(histPick().length); } });
  setInterval(() => { if (cur === 'hist' && !document.querySelector('.hover') && document.activeElement !== q && !histOpen) loadHist(); }, 30000);
}
function histCo(e) { return (e.airline || '').replace(/\s*\(.*$/, '').trim() || 'Inconnue'; }  // livrée spéciale entre parenthèses : même compagnie
const SRC_SHORT = SRC_NAMES;
function histSrcTags(e) {  // « multi » : plusieurs sources ; sinon la source unique (les anciens avions sans information comptent pour Flightradar24)
  const s = e.src && e.src.length ? e.src : ['fr24'];
  return s.length >= 2 ? ['multi'] : [s[0]];
}
function histMatcher(skip) {  // filtre cumulable : un avion passe si, pour chaque critère choisi, il correspond à l'une de ses valeurs ; skip = critère ignoré (pour les compteurs de son propre menu)
  const now = Date.now() / 1000, lim = histPeriod === 'day' ? now - 86400 : (histPeriod === 'week' ? now - 7 * 86400 : 0), q = histQ.trim().toLowerCase();
  return e => {
    if (e.t < lim || (histAlert && !e.al) || (histTc && !e.tc)) return false;
    if (q && ![e.model, e.reg, e.cs, e.airline, e.frm, e.to, e.fi, e.ti, e.code].join(' ').toLowerCase().includes(q)) return false;
    if (skip !== 'type' && fType.size && !fType.has(e.cat || '?')) return false;
    if (skip !== 'air' && fAir.size && !fAir.has(histCo(e))) return false;
    if (skip !== 'brand' && fBrand.size) {
      if (!fBrand.has(e.br)) return false;
      if ([...fFam].some(k => k.startsWith(e.br + '|')) && !fFam.has(e.br + '|' + e.fa)) return false;
    }
    if (skip !== 'src' && fSrc.size && !histSrcTags(e).some(x => fSrc.has(x))) return false;
    return true;
  };
}
function histPick() {
  let L = HIST.entries.filter(histMatcher(''));
  if (histSort === 'often') L = L.slice().sort((a, b) => b.n - a.n || b.t - a.t);
  return L;
}
function histPhoto(e, cls) {
  const ph = el('div', cls || 'hph'), noph = () => { ph.append(el('span', null, '✈')); };
  if (e.photo) { const im = document.createElement('img'); im.loading = 'lazy'; im.alt = ''; im.src = '/api/history/photo?id=' + encodeURIComponent(e.id) + (e.mp ? '&v=' + e.mp : ''); im.onerror = () => { im.remove(); noph(); }; ph.append(im); } else noph();
  return ph;
}
function histRoute(e) { return [e.frm || e.fi || '?', e.to || e.ti || '?']; }
function histBadges(e) {
  const bd = el('div', 'hbadges');
  if (e.al) bd.append(el('span', 'hbadge alert', 'Alerte'));
  if (e.ml) { const m = el('span', 'hbadge mlat', 'MLAT'); m.title = tl('Position calculée par multilatération (MLAT) par la source'); bd.append(m); }
  if (e.src && e.src.length >= 2) { const m = el('span', 'hbadge multi', '⇄ ' + e.src.length); m.title = _t('Vu par {0} sources : {1}', e.src.length, e.src.map(x => SRC_SHORT[x] || x).join(', ')); bd.append(m); }
  if (e.n === 1 && e.reg) bd.append(el('span', 'hbadge new', '1re fois'));
  if (e.tc) { const q = el('span', 'hbadge cnt', '?'); q.title = tl('Type inconnu : ouvrez la fiche pour classer cet avion'); bd.append(q); }
  if (e.mil) { const m = el('span', 'hbadge cnt', 'MIL'); m.title = tl('Avion militaire'); bd.append(m); }
  if (e.ulm) { const u = el('span', 'hbadge cnt', 'ULM'); u.title = tl('Immatriculation F-J : ultra léger motorisé'); bd.append(u); }
  if (e.rare) bd.append(el('span', 'hbadge rare', 'Type rare'));
  if (e.n >= 2) { const c = el('span', 'hbadge cnt', '×' + e.n); c.title = _t('{0} fois vu', e.n); bd.append(c); }  // déjà vu : le nombre de passages, en gris
  return bd;
}
function histPager(host, pages) {
  host.innerHTML = ''; if (pages <= 1) return;
  const go = p => { histPage = Math.min(pages, Math.max(1, p)); drawHist(); const c = $('#hFilt'); if (c) c.scrollIntoView({block: 'nearest'}); };  // 'nearest' : la page ne bouge pas si le début de la liste est déjà visible
  const add = (label, p, cls, dis) => { const b = el('button', 'hpg' + (cls ? ' ' + cls : ''), label); b.disabled = !!dis; b.onclick = () => go(p); host.append(b); };
  host.append(el('span', 'hpi', _t('Page {0} sur {1}', histPage, pages)));
  add('‹', histPage - 1, '', histPage === 1);
  const set = new Set([1, 2, pages - 1, pages]); for (let p = histPage - 2; p <= histPage + 2; p++) set.add(p);
  let last = 0;
  for (const p of [...set].filter(p => p >= 1 && p <= pages).sort((a, b) => a - b)) { if (p - last > 1) host.append(el('span', 'hpe', '…')); add(String(p), p, p === histPage ? 'on' : ''); last = p; }
  add('›', histPage + 1, '', histPage === pages);
}
const histAnyFilter = () => !!(fType.size || fAir.size || fBrand.size || fFam.size || fSrc.size || histAlert || histTc);
function histClear() { fType.clear(); fAir.clear(); fBrand.clear(); fFam.clear(); fSrc.clear(); histAlert = false; histTc = false; histOpen = ''; histMq = ''; }
function histDim(name) {  // contenu du menu : lignes {k, label, n, on, sub, cat}, ensemble choisi
  const rows = HIST.entries.filter(histMatcher(name)), cnt = new Map(), items = [];
  const bump = (k, e) => cnt.set(k, (cnt.get(k) || 0) + 1);
  if (name === 'type') {
    for (const e of rows) bump(e.cat || '?');
    for (const [c, l] of HIST.cats) { const n = cnt.get(c) || 0; if (n || fType.has(c)) items.push({k: c, label: l, n: n, on: fType.has(c), cat: c}); }
    const n = cnt.get('?') || 0; if (n || fType.has('?')) items.push({k: '?', label: tl('Type inconnu'), n: n, on: fType.has('?')});
    return {items, set: fType};
  }
  if (name === 'air') {
    for (const e of rows) bump(histCo(e), e);
    for (const k of new Set([...cnt.keys(), ...fAir])) items.push({k, label: k, n: cnt.get(k) || 0, on: fAir.has(k)});
    items.sort((a, b) => b.n - a.n || a.label.localeCompare(b.label));
    return {items, set: fAir};
  }
  if (name === 'brand') {
    const fam = new Map();
    for (const e of rows) { bump(e.br); const k = e.br + '|' + e.fa; fam.set(k, (fam.get(k) || 0) + 1); }
    const bs = [...new Set([...cnt.keys(), ...fBrand])].sort((a, b) => (cnt.get(b) || 0) - (cnt.get(a) || 0) || a.localeCompare(b));
    for (const b of bs) {
      items.push({k: b, label: b, n: cnt.get(b) || 0, on: fBrand.has(b)});
      if (fBrand.has(b)) for (const [k, n] of [...fam].filter(x => x[0].startsWith(b + '|')).sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]))) items.push({k, label: k.slice(b.length + 1), n, on: fFam.has(k), sub: true});
    }
    return {items, set: fBrand};
  }
  for (const e of rows) for (const x of histSrcTags(e)) bump(x);  // src
  items.push({k: 'multi', label: tl('Vus par plusieurs sources'), n: cnt.get('multi') || 0, on: fSrc.has('multi')});
  for (const n of Object.keys(SRC_NAMES)) { const c = cnt.get(n) || 0; if (c || fSrc.has(n) || n === 'fr24') items.push({k: n, label: _t('{0} seulement', SRC_NAMES[n]), n: c, on: fSrc.has(n)}); }
  return {items, set: fSrc};
}
function histToggle(name, k) {
  const set = name === 'type' ? fType : (name === 'air' ? fAir : (name === 'src' ? fSrc : (k.includes('|') ? fFam : fBrand)));
  if (set.has(k)) { set.delete(k); if (set === fBrand) for (const f of [...fFam]) if (f.startsWith(k + '|')) fFam.delete(f); } else set.add(k);
  histPage = 1; drawHist();
}
function histPopup(name, wrap) {
  const pop = el('div', 'hpop'), single = name === 'period' || name === 'sort';
  let items;
  if (name === 'period') items = [['day', "Aujourd'hui"], ['week', '7 jours'], ['all', 'Tout']].map(([k, l]) => ({k, label: tl(l), on: histPeriod === k}));
  else if (name === 'sort') items = [['recent', 'Récents'], ['often', 'Habitués']].map(([k, l]) => ({k, label: tl(l), on: histSort === k}));
  else items = histDim(name).items;
  const mq = histMq.trim().toLowerCase(), list = el('div', 'hpl');
  if (!single && (items.length > 8 || histMq)) {
    const i = document.createElement('input'); i.className = 'hmq'; i.type = 'search'; i.autocomplete = 'off'; i.placeholder = tl('Chercher…'); i.value = histMq;
    i.oninput = () => { histMq = i.value; drawFilters(histPick().length); };
    pop.append(i);
  }
  for (const it of items) {
    if (mq && !it.label.toLowerCase().includes(mq) && !it.on) continue;
    const b = el('button', 'hpi2' + (it.on ? ' on' : '') + (it.sub ? ' sub' : ''));
    if (single) b.append(el('i', 'hrad')); else b.append(el('i', 'hbox'));
    if (it.cat) b.append(planeSvg({shapes: HIST.shapes}, it.cat, 20));
    b.append(el('span', 't', it.label)); if (it.n !== undefined) b.append(el('b', null, String(it.n)));
    b.onclick = () => {
      if (name === 'period') { histPeriod = it.k; histSave(); histOpen = ''; histPage = 1; drawHist(); }
      else if (name === 'sort') { histSort = it.k; histSave(); histOpen = ''; histPage = 1; drawHist(); }
      else histToggle(name, it.k);
    };
    list.append(b);
  }
  if (!list.firstChild) list.append(el('p', 'note', 'Aucun résultat'));
  pop.append(list); wrap.append(pop);
}
function drawFilters(total) {
  const f = $('#hFilt'); if (!f) return;
  const hadQ = document.activeElement && document.activeElement.classList && document.activeElement.classList.contains('hmq');
  f.innerHTML = '';
  const fl = el('div', 'hfl'); fl.innerHTML = '<svg viewBox="0 0 24 24"><path d="M3 5h18l-7 8v6l-4 2v-8z"/></svg>'; fl.append(document.createTextNode(tl('Filtrer et trier'))); f.append(fl);
  const menu = (name, label, n) => {
    const w = el('div', 'hmw'), b = el('button', 'hchip' + (n ? ' on' : '')); b.append(document.createTextNode(label)); if (n) b.append(el('em', null, String(n))); b.append(document.createTextNode('▾'));
    b.onclick = () => { histOpen = histOpen === name ? '' : name; histMq = ''; drawFilters(total); };
    w.append(b); if (histOpen === name) histPopup(name, w); f.append(w);
  };
  const flag = (label, on, cls, fn) => { const b = el('button', 'hchip ' + cls + (on ? ' on' : ''), label); b.onclick = () => { fn(); histPage = 1; drawHist(); }; f.append(b); };
  menu('period', histPeriod === 'day' ? tl("Aujourd'hui") : (histPeriod === 'week' ? tl('7 jours') : tl('Tout')), 0);
  menu('sort', histSort === 'often' ? tl('Habitués') : tl('Récents'), 0);
  flag(tl("Zone d'alerte"), histAlert, 'al', () => { histAlert = !histAlert; });
  if (HIST.entries.some(e => e.tc) || histTc) flag(tl('À classer'), histTc, 'al', () => { histTc = !histTc; });
  menu('type', tl('Type'), fType.size); menu('air', tl('Compagnie'), fAir.size); menu('brand', tl('Constructeur'), fBrand.size + fFam.size);
  if (HIST.entries.some(e => e.src && e.src.some(x => x !== 'fr24'))) menu('src', tl('Source'), fSrc.size);
  f.append(el('span', 'hsp'));
  if (histAnyFilter()) { const c = el('button', 'hchip clr', 'Effacer'); c.onclick = () => { histClear(); histPage = 1; drawHist(); }; f.append(c); }
  f.append(el('small', null, _t(total > 1 ? '{0} avions' : '{0} avion', total)));
  // filtres choisis : un jeton par valeur, retirable d'un clic
  const a = $('#hAct'); a.innerHTML = '';
  const tok = (label, fn) => { const s = el('span', 'htok'), x = el('button', null, '✕'); x.title = tl('Retirer'); x.onclick = fn; s.append(document.createTextNode(label), x); a.append(s); };
  for (const k of fType) { const m = HIST.cats.find(x => x[0] === k); tok(_t('Type : {0}', m ? m[1] : tl('Type inconnu')), () => histToggle('type', k)); }
  for (const k of fAir) tok(_t('Compagnie : {0}', k), () => histToggle('air', k));
  for (const k of fBrand) tok(_t('Constructeur : {0}', k), () => histToggle('brand', k));
  for (const k of fFam) { const i = k.indexOf('|'); tok(k.slice(0, i) + ' ' + k.slice(i + 1), () => histToggle('brand', k)); }
  for (const k of fSrc) tok(k === 'multi' ? tl('Vus par plusieurs sources') : _t('{0} seulement', SRC_NAMES[k] || k), () => histToggle('src', k));
  if (hadQ) { const i = f.querySelector('.hmq'); if (i) { i.focus(); const n = i.value.length; try { i.setSelectionRange(n, n); } catch (e) {} } }
}
function drawHist() {
  if (!HIST) return;
  const L = histPick(), pages = Math.max(1, Math.ceil(L.length / histPer));
  if (histPage > pages) histPage = pages;
  const from = (histPage - 1) * histPer, part = L.slice(from, from + histPer), res = $('#hRes'); res.innerHTML = '';
  drawFilters(L.length);
  if (histMode === 'list') {
    res.className = 'hrows';
    part.forEach((e, k) => {
      const r = el('button', 'hrow'), rt = histRoute(e), t1 = el('div'), t2 = el('div');
      t1.append(el('b', null, e.model && e.model !== '?' ? e.model : (e.code || '?')), el('small', null, e.airline || ' '));
      t2.className = 'hroutel'; t2.append(el('b', null, rt[0] + ' → ' + rt[1]), el('small', null, [e.fi, e.ti].filter(Boolean).join(' → ') || ' '));
      const t3 = el('div'); t3.append(el('b', null, e.reg || e.cs || '?'), el('small', null, e.reg ? (e.cs || ' ') : ' '));  // immatriculation, puis indicatif dessous
      r.append(histPhoto(e, 'hrt'), t1, t2, t3, el('small', null, ago(e.t)), histBadges(e));
      r.onclick = () => histSheet(L, from + k); res.append(r);
    });
  } else {
    res.className = 'hgrid';
    part.forEach((e, k) => {
      const c = el('button', 'hcard'), ph = histPhoto(e);
      ph.append(histBadges(e));
      const bo = el('div', 'hbody'), r = histRoute(e), rt = el('div', 'hroute');
      rt.append(el('span', null, r[0]), el('i', null, '→'), el('span', null, r[1]));
      const mt = el('div', 'hmeta'); mt.append(el('code', null, e.reg || e.cs || '?'), el('span', null, ago(e.t)));
      bo.append(el('b', null, e.model && e.model !== '?' ? e.model : (e.code || '?')), el('div', 'ha', e.airline || ' '), rt, mt);
      c.append(ph, bo); c.onclick = () => histSheet(L, from + k); res.append(c);
    });
  }
  histPager($('#hPg1'), pages); histPager($('#hPg2'), pages);
  $('#hEmpty').textContent = L.length ? '' : tl(HIST.entries.length ? 'Aucun avion ne correspond à ces filtres.' : "Aucun avion pour le moment. Dès qu'un avion passe au-dessus de chez vous, il apparaît ici avec sa photo.");
}
function histTable(e) {  // tous les passages de cet appareil (même immatriculation) vus par le programme
  const rows = [];  // un passage par ligne : début, fin, alerte, et l'entrée pour l'indicatif et le trajet
  for (const x of (e.reg ? HIST.entries.filter(y => y.reg === e.reg) : [e])) {
    const ps = x.ps && x.ps.length ? x.ps : [[x.t, x.l, 0]];
    ps.forEach((p, k) => rows.push({t: p[0], l: p[1], al: k === ps.length - 1 ? x.al : p[2], cs: x.cs, frm: x.frm, to: x.to, fi: x.fi, ti: x.ti}));
  }
  rows.sort((a, b) => b.t - a.t);
  const w = el('div', 'hht'), tb = document.createElement('table'), hd = document.createElement('tr'); tb.className = 'htab';
  w.append(el('h5', null, _t('Passages de {0}', e.reg || e.cs || e.id)));
  for (const h of ['Date et heure', 'Vu pendant', 'Indicatif', 'Trajet', 'Alerte']) hd.append(el('th', null, h));
  tb.append(hd);
  for (const x of rows) {
    const r = document.createElement('tr'), m = Math.round((x.l - x.t) / 60), rt = histRoute(x);
    r.append(el('td', null, new Date(x.t * 1000).toLocaleString()), el('td', null, m >= 1 ? (m >= 90 ? Math.floor(m / 60) + ' h ' + String(m % 60).padStart(2, '0') : m + ' min') : '–'),
             el('td', null, x.cs || '–'), el('td', null, rt[0] + ' → ' + rt[1]), el('td', null, x.al ? tl('Oui') : ''));
    tb.append(r);
  }
  w.append(tb); return w;
}
function histSheet(L, i) {
  const e = L[i]; const old = document.querySelector('.hover'); if (old) old.remove();
  const ov = el('div', 'hover'), sh = el('div', 'hsheet');
  ov.onclick = ev => { if (ev.target === ov) ov.remove(); };
  const ph = histPhoto(e); ph.append(histBadges(e));
  const sc = el('div', 'hsc');
  sc.append(el('h3', null, e.model && e.model !== '?' ? e.model : (e.code || '?')), el('div', 'ha', e.airline || ' '));
  if (e.mp) sc.append(el('div', 'hcr', tl('Votre photo personnelle')));
  else if (e.photo && e.credit) sc.append(el('div', 'hcr', _t('© {0} (via JetPhotos)', e.credit)));
  const after = async () => { ov.remove(); await loadHist(); };
  // ---- onglet Infos
  const pInfo = el('div', 'htp'), r = histRoute(e), dl = document.createElement('dl'); dl.className = 'hdl';
  const row = (k, v) => { if (!v) return; dl.append(el('dt', null, k), el('dd', null, v)); };
  const when = t => new Date(t * 1000).toLocaleString();
  row('Immatriculation', e.reg); row('Indicatif', e.cs); row('Type ICAO', e.code);
  row('Constructeur', e.br !== 'Inconnu' ? e.br + (e.fa ? ' · ' + e.fa : '') : '');
  row('Trajet', r[0] + (e.fi ? ' (' + e.fi + ')' : '') + ' → ' + r[1] + (e.ti ? ' (' + e.ti + ')' : ''));
  row('Premier passage', when(e.t) + ' · ' + ago(e.t));
  if (e.ml) row('MLAT', tl('Position calculée par multilatération'));
  if (e.src && e.src.length) row('Sources', e.src.map(x => SRC_SHORT[x] || x).join(' + '));
  if (e.l - e.t > 120) row('Dernier passage', when(e.l));
  row("Zone d'alerte", e.al ? _t("Entré dans la zone le {0}", when(e.al)) : '');
  pInfo.append(dl, exLinks(e));
  // ---- onglet Passages : tous les passages de cet appareil vus par le programme
  const pPas = el('div', 'htp'); pPas.append(histTable(e));
  // ---- onglet Classer (la recherche de suggestion ne part que quand on l'ouvre)
  const pCls = el('div', 'htp'), st = {edit: false};
  const drawC = () => pCls.replaceChildren(classifyBlock(e, st, drawC, after));
  // ---- onglet Photo : photo personnelle, pour les avions sans photo (avions légers, ULM...)
  const pPh = el('div', 'htp');
  pPh.append(el('p', 'note', e.mp ? 'Votre photo personnelle remplace celle de JetPhotos, sur l\'écran comme dans cette page.' : (e.photo ? 'Photo de JetPhotos, affichée en haut de la fiche. Votre propre photo la remplacerait.' : 'Aucune photo pour cet avion.')));
  if (/^[0-9a-f]{6}$/.test(e.id) || e.reg) {
    const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/*'; inp.style.display = 'none';
    const add = el('button', 'b s', e.mp ? 'Changer ma photo' : 'Ajouter ma photo'); add.title = tl('Remplace la photo affichée pour cet avion, sur l\'écran comme ici');
    add.onclick = () => inp.click();
    inp.onchange = async () => {
      const f = inp.files && inp.files[0]; if (!f) return;
      try {
        const img = await new Promise((ok, ko) => { const i = new Image(), u = URL.createObjectURL(f); i.onload = () => { URL.revokeObjectURL(u); ok(i); }; i.onerror = () => ko(new Error(tl('Image illisible'))); i.src = u; });
        const k = Math.min(1, 1600 / Math.max(img.width, img.height)), cv = document.createElement('canvas');
        cv.width = Math.round(img.width * k); cv.height = Math.round(img.height * k); cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
        const data = cv.toDataURL('image/jpeg', 0.88).split(',')[1];
        await api('/api/myphoto', {id: e.id, data: data}); toast('Photo enregistrée'); await after();
      } catch (er) { toast(er.message, true); }
    };
    const nav = el('div', 'hnav'); nav.append(inp, add);
    if (e.mp) { const rm = el('button', 'b s', 'Retirer ma photo'); rm.onclick = async () => { try { await api('/api/myphoto', {id: e.id, remove: true}); toast('Photo retirée'); await after(); } catch (er) { toast(er.message, true); } }; nav.append(rm); }
    pPh.append(nav);
  } else pPh.append(el('p', 'note', 'Impossible d\'ajouter une photo : cet avion n\'a ni adresse ICAO ni immatriculation connue, le programme ne saurait pas la retrouver quand l\'avion repasse. Saisissez son immatriculation dans l\'onglet Classer.'));
  // ---- onglets
  const tabs = el('div', 'htabs'), panes = [pInfo, pPas, pCls, pPh], btns = [];
  const show = k => {
    btns.forEach((b, n) => b.classList.toggle('on', n === k)); panes.forEach((p, n) => { p.style.display = n === k ? '' : 'none'; });
    if (k === 2 && !pCls.firstChild) drawC();
  };
  [['Infos', 0], ['Passages', 1], ['Classer', 2], ['Photo', 3]].forEach(([t, k]) => {
    const b = el('button', null, t); if (k === 2 && e.tc) b.append(el('span', 'hdot')); b.onclick = () => show(k); btns.push(b); tabs.append(b);
  });
  const xb = el('button', 'hx', '✕'); xb.title = tl('Fermer'); xb.onclick = () => ov.remove(); ph.append(xb);
  ov._nav = d => { if (L[i + d]) histSheet(L, i + d); };
  sh.append(ph, sc, tabs, ...panes); ov.append(sh); document.body.append(ov);
  show(e.tc ? 2 : 0);  // un avion à classer s'ouvre directement sur l'onglet Classer
}

/* ---------- Heure du Pi et prochaine action du planning ---------- */
const p2 = n => String(n).padStart(2, '0');
function fmtBytes(n) {
  const u = [[1e9, 'Go'], [1e6, 'Mo'], [1e3, 'Ko']];
  for (const [d, name] of u) if (n >= d) { const v = n / d; return (v >= 100 ? v.toFixed(0) : v.toFixed(1)).replace('.', I18N.lang === 'fr' ? ',' : '.') + ' ' + _t(name); }
  return n + ' ' + _t('o');
}
const fmtPct = p => { const sep = I18N.lang === 'fr' ? ',' : '.'; return p > 0 && p < 0.1 ? '< 0' + sep + '1' : String(Math.round(p * 10) / 10).replace('.', sep); };
function piNow() { return lastSt && lastSt.now ? lastSt.now.epoch + (performance.now() - lastStAt) / 1000 : null; }
function piDate(epoch) { return new Date(epoch * 1000 + lastSt.now.offset * 60000); }  // lire avec les getUTC*
function fmtIn(sec) { sec = Math.max(0, Math.round(sec)); const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60); return h ? h + ' h ' + p2(m) + ' min' : (m ? m + ' min' : sec + ' s'); }
function dayDiff(a, b) { return Math.round((Date.UTC(b.getUTCFullYear(), b.getUTCMonth(), b.getUTCDate()) - Date.UTC(a.getUTCFullYear(), a.getUTCMonth(), a.getUTCDate())) / 86400000); }
function schedNextText() {
  const sc = lastSt && lastSt.schedule, n = piNow();
  if (!sc || !sc.enabled || n === null) return '';
  let txt;
  if (sc.next_to === null || sc.next_epoch === null) txt = _t('Planning actif : aucun changement programmé.');
  else {
    const d = piDate(sc.next_epoch), hhmm = p2(d.getUTCHours()) + ':' + p2(d.getUTCMinutes()), diff = dayDiff(piDate(n), d), left = fmtIn(sc.next_epoch - n);
    const day = d.toLocaleDateString(I18N.lang, {weekday: 'long', timeZone: 'UTC'});
    txt = sc.next_to
      ? (diff <= 0 ? _t('Prochaine action : allumage à {0} (dans {1})', hhmm, left) : (diff === 1 ? _t('Prochaine action : allumage demain à {0} (dans {1})', hhmm, left) : _t('Prochaine action : allumage {2} à {0} (dans {1})', hhmm, left, day)))
      : (diff <= 0 ? _t('Prochaine action : extinction à {0} (dans {1})', hhmm, left) : (diff === 1 ? _t('Prochaine action : extinction demain à {0} (dans {1})', hhmm, left) : _t('Prochaine action : extinction {2} à {0} (dans {1})', hhmm, left, day)));
  }
  return sc.error ? txt + '\n' + sc.error : txt;
}
function tickClock() {
  const n = piNow(); if (n === null) return;
  const d = piDate(n), c = $('#clk'), cd = $('#clkd');
  if (c) c.textContent = p2(d.getUTCHours()) + ':' + p2(d.getUTCMinutes()) + ':' + p2(d.getUTCSeconds());
  if (cd) cd.textContent = d.toLocaleDateString(I18N.lang, {weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC'}) + (lastSt.now.tz ? ' · ' + lastSt.now.tz : '');
  if (rows.sched) {
    const on = !!(lastSt.schedule && lastSt.schedule.enabled);
    rows.sched.r.style.display = on ? '' : 'none';
    if (on) { const x = schedNextText(); if (rows.sched.sub.textContent !== x) { rows.sched.sub.textContent = x; rows.sched.sub.style.whiteSpace = 'pre-line'; } }
  }
  if (typeof updSchedInfo === 'function') updSchedInfo();
}

/* ---------- Planning de l'écran : calendrier hebdomadaire ---------- */
const SCH_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'], SCH_NAMES = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'], HOUR_PX = 40, SNAP = 15;
let updSchedInfo = null;
function sp(key) { return allParams().find(p => p.id === 'web:schedule.' + key); }
function sval(key) { const p = sp(key); return p ? pval(p) : ''; }
function sset(key, v) { const p = sp(key); if (p) setEdit(p, String(v)); }
const mmTxt = m => p2(Math.floor(m / 60)) + ':' + p2(m % 60);
function mergeSlots(arr) { arr = arr.map(x => x.slice()).sort((x, y) => x[0] - y[0]); const o = []; for (const [a, b] of arr) { if (o.length && a <= o[o.length - 1][1]) o[o.length - 1][1] = Math.max(o[o.length - 1][1], b); else o.push([a, b]); } return o; }
function parseSlots(v) { const out = []; for (const part of String(v || '').split(',')) { const m = /^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$/.exec(part); if (m) { const a = +m[1] * 60 + +m[2], b = +m[3] * 60 + +m[4]; if (a < b && b <= 1440) out.push([a, b]); } } return mergeSlots(out); }
const slotsStr = arr => mergeSlots(arr).map(([a, b]) => mmTxt(a) + '-' + mmTxt(b)).join(',');
function renderSchedule(box) {
  if (!lastSt) pollStatus();
  const top = el('div', 'list'), enRow = el('div', 'li'), lt = el('div', 'lt');
  lt.append(el('b', null, 'Activer le planning'), el('small', null, "Hors des plages d'allumage, l'écran est éteint. Un allumage ou une extinction manuels restent possibles : le planning reprend à la prochaine heure programmée."));
  const tg = toggle(sval('enabled') === 'true', v => { sset('enabled', v ? 'true' : 'false'); });
  enRow.append(lt, tg.label); top.append(enRow);
  const info = el('div', 'li stack'), il = el('div', 'lt'), clockLine = el('b'), nextLine = el('small');
  nextLine.style.whiteSpace = 'pre-line'; il.append(clockLine, nextLine); info.append(il); top.append(info); box.append(top);
  updSchedInfo = () => {
    if (!clockLine.isConnected) return;
    const n = piNow(); if (n === null) return;
    const d = piDate(n);
    clockLine.textContent = _t('Heure du Pi : {0}', p2(d.getUTCHours()) + ':' + p2(d.getUTCMinutes()) + ':' + p2(d.getUTCSeconds()) + (lastSt.now.tz ? ' (' + lastSt.now.tz + ')' : ''));
    const sc = lastSt.schedule;
    nextLine.textContent = sc && sc.enabled ? (sc.wanted ? _t('Le planning veut l\'écran allumé maintenant.') : _t('Le planning veut l\'écran éteint maintenant.')) + '\n' + schedNextText() : _t('Planning enregistré inactif : l\'écran n\'est pas géré automatiquement.');
    const today = (piDate(n).getUTCDay() + 6) % 7;
    cal.querySelectorAll('.calday').forEach((e, i) => e.classList.toggle('today', i === today));
    const nl = cal.querySelector('.nowl'); if (nl) { nl.remove(); }
    const col = cal.querySelectorAll('.calcol')[today];
    if (col) { const l = el('div', 'nowl'); l.style.top = ((d.getUTCHours() * 60 + d.getUTCMinutes()) / 60 * HOUR_PX) + 'px'; col.append(l); }
  };
  const tools = el('div', 'tools');
  const b1 = el('button', 'b s', 'Tous les jours 07:00-23:00'), b2 = el('button', 'b s', 'Tout effacer');
  b1.onclick = () => { for (const d of SCH_DAYS) sset(d, '07:00-23:00'); draw(); };
  b2.onclick = () => { for (const d of SCH_DAYS) sset(d, ''); draw(); };
  tools.append(b1, b2);
  box.append(el('h2', 't', 'Calendrier hebdomadaire'), tools,
    el('p', 'note', "Les plages bleues sont les heures où l'écran est allumé. Faites glisser sur une journée pour tracer une plage (un simple clic en crée une d'une heure), tirez ses bords pour l'ajuster, déplacez-la pour la changer d'heure ou de jour, ✕ pour la supprimer. Le bouton ⧉ copie la journée sur toute la semaine."));
  const cal = el('div', 'cal'); box.append(cal);
  const place = (d, a, b) => { d.style.top = (a / 60 * HOUR_PX) + 'px'; d.style.height = Math.max((b - a) / 60 * HOUR_PX, 8) + 'px'; };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const snap = m => Math.round(m / SNAP) * SNAP;
  const minAt = (col, y) => clamp((y - col.getBoundingClientRect().top) / HOUR_PX * 60, 0, 1440);
  const colAtX = x => { const cols = [...cal.querySelectorAll('.calcol')]; return cols.find(c => { const r = c.getBoundingClientRect(); return x >= r.left && x < r.right; }) || null; };
  function commit(day, arr) { sset(day, slotsStr(arr)); }
  function block([a, b], k) {
    const d = el('div', 'blk'); place(d, a, b);
    const lab = el('span', null, mmTxt(a) + '–' + mmTxt(b)); d.append(lab);
    const del = el('button', 'bx', '✕'); del.title = 'Supprimer'; del.onpointerdown = e => e.stopPropagation();
    del.onclick = () => { commit(k, parseSlots(sval(k)).filter(x => !(x[0] === a && x[1] === b))); draw(); };
    d.append(del);
    const hT = el('div', 'rh t'), hB = el('div', 'rh b'); d.append(hT, hB);
    const start = mode => e => {
      if (e.button !== 0) return; e.stopPropagation(); e.preventDefault();
      const col0 = d.parentElement, off = minAt(col0, e.clientY) - a, len = b - a; let A = a, B = b, day = k;
      d.setPointerCapture(e.pointerId); d.classList.add('drag');
      const mv = ev => {
        if (mode === 'move') {
          A = clamp(snap(minAt(col0, ev.clientY) - off), 0, 1440 - len); B = A + len;
          const c = colAtX(ev.clientX); if (c) { day = c.dataset.day; d.style.transform = 'translateX(' + (c.getBoundingClientRect().left - col0.getBoundingClientRect().left) + 'px)'; }
        } else if (mode === 'top') { A = clamp(snap(minAt(col0, ev.clientY)), 0, b - SNAP); B = b; }
        else { B = clamp(snap(minAt(col0, ev.clientY)), a + SNAP, 1440); A = a; }
        place(d, A, B); lab.textContent = mmTxt(A) + '–' + mmTxt(B);
      };
      const up = () => {
        d.removeEventListener('pointermove', mv); d.removeEventListener('pointerup', up); d.removeEventListener('pointercancel', up);
        const rest = parseSlots(sval(k)).filter(x => !(x[0] === a && x[1] === b));
        if (day !== k) { commit(k, rest); const o = parseSlots(sval(day)); o.push([A, B]); commit(day, o); } else { rest.push([A, B]); commit(k, rest); }
        draw();
      };
      d.addEventListener('pointermove', mv); d.addEventListener('pointerup', up); d.addEventListener('pointercancel', up);
    };
    d.addEventListener('pointerdown', start('move')); hT.addEventListener('pointerdown', start('top')); hB.addEventListener('pointerdown', start('bottom'));
    return d;
  }
  function attachCol(col, k) {
    col.addEventListener('pointerdown', e => {
      if (e.target !== col || e.button !== 0) return;
      const mouse = e.pointerType === 'mouse', m0 = Math.floor(minAt(col, e.clientY) / SNAP) * SNAP;
      let a = m0, b = m0 + SNAP, moved = false;
      const ghost = el('div', 'blk ghost'); col.append(ghost); place(ghost, a, b);
      if (mouse) col.setPointerCapture(e.pointerId);
      const end = () => { col.removeEventListener('pointermove', mv); col.removeEventListener('pointerup', up); col.removeEventListener('pointercancel', cancel); ghost.remove(); };
      const mv = ev => { const m1 = Math.floor(minAt(col, ev.clientY) / SNAP) * SNAP; a = Math.min(m0, m1); b = Math.min(1440, Math.max(m0, m1) + SNAP); if (b - a > SNAP) moved = true; place(ghost, a, b); };
      const up = () => { end(); if (!moved) { a = Math.min(m0, 1380); b = a + 60; } const arr = parseSlots(sval(k)); arr.push([a, b]); commit(k, arr); draw(); };
      const cancel = () => end();
      if (mouse) col.addEventListener('pointermove', mv);
      col.addEventListener('pointerup', up); col.addEventListener('pointercancel', cancel);
    });
  }
  function draw() {
    cal.innerHTML = '';
    const head = el('div', 'calh'); head.append(el('div'));
    SCH_DAYS.forEach((k, i) => {
      const h = el('div', 'calday', SCH_NAMES[i]), cp = el('button', 'calcp', '⧉'); cp.title = 'Copier ce jour sur toute la semaine';
      cp.onclick = () => { const v = sval(k); for (const d of SCH_DAYS) sset(d, v); draw(); }; h.append(cp); head.append(h);
    });
    const body = el('div', 'calb'), axis = el('div');
    for (let h = 0; h < 24; h++) { const l = el('div', 'calhr', p2(h) + ':00'); l.style.height = HOUR_PX + 'px'; axis.append(l); }
    body.append(axis);
    SCH_DAYS.forEach(k => { const col = el('div', 'calcol'); col.style.height = (24 * HOUR_PX) + 'px'; col.dataset.day = k; for (const r of parseSlots(sval(k))) col.append(block(r, k)); attachCol(col, k); body.append(col); });
    cal.append(head, body);
    if (updSchedInfo) updSchedInfo();
  }
  draw();
}

/* ---------- Contenu des étiquettes et du panneau photo (éditeur de champs) ---------- */
const LBL_PX = {small: 13, medium: 17, large: 21}, LBL_SIZES = [['small', 'Petit'], ['medium', 'Moyen'], ['large', 'Grand']];
function pget(id) { return allParams().find(p => p.id === id); }
function pvalue(id) { const p = pget(id); return p ? pval(p) : ''; }
function pset(id, v) { const p = pget(id); if (p) setEdit(p, String(v)); }
function fieldOrder(ed) {
  const names = ed.fields.map(f => f.id);
  let o = String(pvalue(ed.order)).split(',').map(x => x.trim()).filter(x => names.includes(x));
  o = o.filter((x, i) => o.indexOf(x) === i);
  for (const n of names) if (!o.includes(n)) o.push(n);
  return o;
}
function renderFields(box, cat) {
  const ed = cat.editor, panel = ed.mode === 'panel', F = Object.fromEntries(ed.fields.map(f => [f.id, f]));
  const sample = {model: 'Airbus A320', registration: 'F-GKXA', callsign: 'AFR1234', airline: 'Air France', route: 'Paris  →  Nice',
    altitude: panel ? _t('Altitude {0}', '3 000 ft') : '3 000 ft', speed: panel ? _t('Vitesse {0}', '450 km/h') : '450 km/h', credit: '© J. Dupont / JetPhotos'};
  const colors = panel ? {model: '#fff', registration: '#fff', callsign: '#fff', airline: '#dce1e6', route: '#dce1e6', altitude: '#ff9696', speed: '#ff9696', credit: '#8c96a0'}
    : {model: '#fff', registration: '#fff', callsign: '#fff', airline: '#bec8d2', route: '#bec8d2', altitude: '#bec8d2', speed: '#bec8d2'};
  const prev = el('div', 'lprev sticky'), list = el('div', 'list');
  if (panel) prev.style.cssText = 'display:block;max-width:380px;padding:10px';
  box.append(el('h2', 't', 'Aperçu'), prev, el('h2', 't', 'Contenu, ordre et style'), list);
  const on = (k, w) => pvalue(F[k].ids[w]) === 'true', val = (k, w) => pvalue(F[k].ids[w]), set = (k, w, v) => pset(F[k].ids[w], v);
  function preview() {
    prev.innerHTML = '';
    if (panel) { const ph = el('div', null, 'photo'); ph.style.cssText = 'height:70px;border-radius:6px;background:#1f2a38;color:#5b6b80;display:flex;align-items:center;justify-content:center;font-size:12px;margin-bottom:8px'; prev.append(ph); }
    const lines = [];
    for (const k of fieldOrder(ed)) {
      if (!on(k, 'show')) continue;
      if (on(k, 'same') && lines.length) lines[lines.length - 1].push(k); else lines.push([k]);
    }
    if (!lines.length) { prev.append(el('span', 'chip', panel ? 'aucun texte' : 'aucune étiquette')); return; }
    for (const ln of lines) {
      const d = el('div'); d.style.whiteSpace = 'nowrap';
      ln.forEach((k, i) => {
        if (i) { const s = el('span', null, '  ·  '); s.style.color = panel ? '#dce1e6' : '#bec8d2'; s.style.fontSize = LBL_PX[val(ln[i - 1], 'size')] + 'px'; d.append(s); }
        const s = el('span', null, sample[k]);
        s.style.fontSize = LBL_PX[val(k, 'size')] + 'px'; s.style.fontWeight = on(k, 'bold') ? '700' : '400';
        s.style.fontStyle = on(k, 'italic') ? 'italic' : 'normal'; s.style.color = colors[k];
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
    const order = fieldOrder(ed), save = () => pset(ed.order, order.join(','));
    order.forEach((k, i) => {
      const row = el('div', 'lrow' + (on(k, 'show') ? '' : ' off')), top = el('div', 'top');
      const up = tbtn('▲', false, () => { if (i > 0) { [order[i - 1], order[i]] = [order[i], order[i - 1]]; save(); draw(); } });
      const dn = tbtn('▼', false, () => { if (i < order.length - 1) { [order[i + 1], order[i]] = [order[i], order[i + 1]]; save(); draw(); } });
      up.disabled = i === 0; dn.disabled = i === order.length - 1;
      const tg = toggle(on(k, 'show'), v => { set(k, 'show', v ? 'true' : 'false'); draw(); });
      const nm = el('div'); nm.style.flex = '1'; nm.append(el('b', null, F[k].name)); if (F[k].hint) { const h = el('small', null, F[k].hint); h.style.cssText = 'display:block;color:var(--mut);font-size:12px;font-weight:400'; nm.append(h); }
      top.append(nm, up, dn, tg.label);
      const opt = el('div', 'opt');
      const sz = el('div', 'seg');
      for (const [v, t] of LBL_SIZES) { const b = el('button', val(k, 'size') === v ? 'on' : '', t); b.onclick = () => { set(k, 'size', v); draw(); }; sz.append(b); }
      opt.append(sz,
        tbtn('G', on(k, 'bold'), () => { set(k, 'bold', on(k, 'bold') ? 'false' : 'true'); draw(); }, 'Gras'),
        tbtn('I', on(k, 'italic'), () => { set(k, 'italic', on(k, 'italic') ? 'false' : 'true'); draw(); }, 'Italique'),
        tbtn('Même ligne', on(k, 'same'), () => { set(k, 'same', on(k, 'same') ? 'false' : 'true'); draw(); }, "Afficher sur la même ligne que l'élément précédent"));
      row.append(top, opt); list.append(row);
    });
    preview();
  }
  draw();
}

/* ---------- Mises à jour ---------- */
function ago(ts) { const d = Math.max(0, Math.round(Date.now() / 1000 - ts)); return d < 90 ? _t("à l'instant") : (d < 5400 ? _t('il y a {0} min', Math.round(d / 60)) : (d < 129600 ? _t('il y a {0} h', Math.round(d / 3600)) : _t('il y a {0} j', Math.round(d / 86400)))); }
function fmtEl(s) { return s >= 60 ? Math.floor(s / 60) + ' min ' + (s % 60) + ' s' : s + ' s'; }
async function pollUpd() {
  try {
    const u = await api('/api/update'); UPD = u;
    const busy = u.running || u.restarting;
    if (updWasRunning && !busy && u.ok === true && u.to_label) { updWasRunning = false; renderUpd(); setTimeout(() => { if (!updQuick) location.hash = '#upd'; location.reload(); }, 2500); return; }
    if (updWasRunning && !busy && u.ok === false) { toast(_t('Dernière tentative en échec : {0}', u.error), true); updQuick = false; }
    updWasRunning = busy;
    renderUpd();
    if (!u.check && !busy && !updAuto && !updBusy) { updAuto = true; checkUpd(); }
  } catch (e) {
    if (updWasRunning) { UPD = Object.assign({}, UPD, {restarting: true, running: false}); renderUpd(true); }
  }
}
async function quickUpdate() {
  try { await api('/api/update/start', {}); updWasRunning = true; updQuick = true; await pollUpd(); pollStatus(); } catch (e) { toast(e.message, true); }
}
async function startRollback(pv) {
  if (!pv) return;
  if (!confirm(_t("Revenir à la version {0} ? L'affichage sera relancé, puis webadmin redémarrera.", vbase(pv.label)))) return;
  try { await api('/api/update/rollback', {hash: pv.short}); updWasRunning = true; updQuick = false; await pollUpd(); } catch (e) { toast(e.message, true); }
}
async function checkUpd() {
  updBusy = true; renderUpd();
  try { UPD = await api('/api/update/check', {}); } catch (e) { toast(e.message, true); }
  updBusy = false; renderUpd(); pollStatus();
}
async function startUpd() {
  try { await api('/api/update/start', {}); updWasRunning = true; await pollUpd(); } catch (e) { toast(e.message, true); }
}
let updDetailsOpen = null, updLogOpen = false, updQuick = false;
const vbase = l => String(l || '').replace(/-g[0-9a-f]{7,}$/, '');  // v1.5.2-2-g43d42dd -> v1.5.2-2 (le commit est affiché à part)
function renderUpd(lost) {
  if (!UPD) return;
  const u = UPD, c = u.check, busy = u.running || u.restarting;
  const cur = u.current || (c && c.ok ? c.current : null), behind = c && c.ok ? c.behind : 0;
  // --- carte résumé
  const sm = $('#updSummary'); sm.innerHTML = '';
  const row = el('div', 'urow'), left = el('div'), side = el('div', 'uside'); row.style.alignItems = 'flex-start'; left.style.cssText = 'flex:1 1 240px;min-width:0';
  left.append(el('div', 'usub ulab', 'Version installée'));
  const vr = el('div', 'uvr'); vr.append(el('span', 'ubig', cur ? vbase(cur.label) : '-'), chip(u.channel === 'stable' ? 'canal stable' : 'canal développement'));
  if (u.channel !== 'stable' && cur && cur.short && vbase(cur.label) !== cur.short) { const cm = el('span', 'ucm'); cm.append(el('small', null, 'commit'), el('span', 'chip', cur.short)); vr.append(cm); }
  left.append(vr);
  const stat = el('div', 'ustat');
  if (behind) {
    stat.classList.add('new');
    stat.append(el('span', null, '●'), el('span', null, _t('Une mise à jour est disponible : {0}', vbase(c.latest.label)) + ' · ' + _t(behind > 1 ? '{0} nouveautés' : '{0} nouveauté', behind)));
  } else if (c && c.ok) stat.append(el('span', null, '✓'), el('span', null, 'Vous avez la dernière version'));
  else if (c && !c.ok) { stat.classList.add('bad'); stat.append(el('span', null, '✕'), el('span', null, 'Vérification impossible')); }
  else stat.append(el('span', null, '○'), el('span', null, 'Pas encore vérifié'));
  left.append(stat);
  const bc = el('button', behind ? 'ulink' : 'b s', updBusy ? 'Vérification...' : (behind ? 'Vérifier maintenant' : 'Vérifier les mises à jour')); bc.disabled = updBusy || busy; bc.onclick = checkUpd;
  if (behind) { const bu = el('button', 'b p s', _t('Mettre à jour vers {0}', vbase(c.latest.label))); bu.disabled = busy || updBusy || !c.can_update; bu.onclick = startUpd; side.append(bu); }
  side.append(bc);
  row.append(left, side); sm.append(row);
  const meta = el('div', 'umeta'), up = s => s.charAt(0).toUpperCase() + s.slice(1);
  if (c && c.checked_at) meta.append(el('span', null, up(_t('vérifié {0}', ago(c.checked_at)))));
  if (u.auto) {
    const left_s = Math.round(((c && c.checked_at ? c.checked_at : Date.now() / 1000) + (u.hours || 12) * 3600) - Date.now() / 1000);
    meta.append(el('span', null, up(_t('prochaine vérification {0}', left_s < 90 ? tl("dans un instant") : (left_s < 5400 ? _t('dans {0} min', Math.round(left_s / 60)) : _t('dans {0} h', Math.round(left_s / 3600)))))));
    if (u.auto_install) meta.append(el('span', null, 'Installation automatique activée'));
  } else meta.append(el('span', null, 'Vérification automatique désactivée'));
  const lk = el('button', 'ulink', 'Réglages automatiques'); lk.onclick = () => { go('cfg'); curCat = 'update'; renderMenu(); renderCat(); };
  meta.append(lk); sm.append(meta);
  // --- avertissements
  const warn = $('#updWarn'), w = [];
  if (c && !c.ok) w.push(c.error);
  if (c && c.ok) {
    if (c.dirty.length) w.push(_t('Des fichiers du logiciel ont été modifiés localement ({0}) : la mise à jour est bloquée pour ne rien écraser.', c.dirty.slice(0, 5).join(', ')));
    if (c.ahead) w.push(c.behind ? _t('Cette installation contient {0} commit(s) local(aux) absent(s) de GitHub : mise à jour impossible sans conflit.', c.ahead) : _t('Cette installation contient {0} commit(s) local(aux) absent(s) de GitHub.', c.ahead));
    if (c.behind && c.installer_changed) w.push("Le programme d'installation (install.sh) a changé dans cette version. Webadmin ne met pas à jour les composants système : si une nouvelle fonction ne marche pas, relancez l'installeur.");
  }
  warn.style.display = w.length ? 'block' : 'none'; warn.textContent = w.map(tl).join('\n'); warn.style.whiteSpace = 'pre-line';
  // --- suivi compact pendant la mise à jour
  const run = $('#updRun'), last = $('#lastRow'), det = $('#updSteps'), out = $('#updOut');
  const toggle2 = (box, open, label, fn) => { box.innerHTML = ''; box.append(el('span', 'chev' + (open ? '' : ' shut'), '▾'), el('span', null, label)); box.onclick = fn; };
  run.style.display = busy ? 'block' : 'none';
  const idleOpen = updDetailsOpen === null ? u.ok === false : updDetailsOpen;
  let showOut = false;
  if (busy) {
    const pct = u.pct || 0, n = u.steps.length, i = u.steps.findIndex(x => x.status === 'running'), lowerFirst = t => t.charAt(0).toLowerCase() + t.slice(1);
    $('#runArc').setAttribute('stroke-dasharray', (pct * 2.1362).toFixed(1) + ' 214'); $('#runPct').textContent = pct + ' %';
    const rv = $('#runVer'); rv.innerHTML = '';
    if (u.mode === 'rollback') rv.append(el('span', 'usub', 'Retour arrière'));
    if (u.from_label && u.to_label) rv.append(el('span', 'chip', vbase(u.from_label)), el('span', 'uarr', '→'), el('span', 'chip', vbase(u.to_label)));
    else if (u.to_label) rv.append(el('span', 'chip', vbase(u.to_label)));
    rv.style.display = rv.childNodes.length ? 'flex' : 'none';
    const rs = $('#runStep'); rs.className = 'usub';
    const restarting = lost || u.restarting;
    $('#runT').textContent = restarting ? tl('Redémarrage de webadmin') : (i >= 0 ? tl(u.steps[i].label) : tl(u.mode === 'rollback' ? 'Retour à la version précédente' : 'Mise à jour en cours'));
    if (restarting) rs.textContent = tl('Webadmin redémarre, la page va se recharger...');
    else if (i >= 0) {
      const parts = [_t('Étape {0} sur {1}', i + 1, n)];
      if (u.steps[i].elapsed > 2) parts.push(fmtEl(u.steps[i].elapsed));
      if (i + 1 < n) parts.push(_t('ensuite : {0}', lowerFirst(tl(u.steps[i + 1].label))));
      rs.textContent = parts.join(' · ');
    } else rs.textContent = '';
    toggle2($('#logTog'), updLogOpen, 'Journal détaillé', () => { updLogOpen = !updLogOpen; renderUpd(lost); });
    showOut = updLogOpen;
    last.style.display = 'none'; det.style.display = 'none';
  } else if (u.started) {
    const bad = u.ok === false, from = vbase(u.from_label), to = vbase(u.to_label);
    last.style.display = 'flex'; last.className = 'ulast' + (bad ? ' bad' : ''); last.innerHTML = '';
    const txt = bad ? _t('Dernière tentative en échec : {0}', u.error) : (from && to && from !== to ? _t(u.mode === 'rollback' ? 'Retour arrière : {0} → {1}, {2}' : 'Dernière mise à jour : {0} → {1}, {2}', from, to, ago(u.finished)) : (u.done_msg || ''));
    last.append(el('span', 'ic', bad ? '✕' : '✓'), el('span', null, txt));
    const more = el('span', 'more'); more.style.marginLeft = 'auto'; more.append(el('span', 'chev' + (idleOpen ? '' : ' shut'), '▾'), el('span', null, 'Détails')); more.firstChild.style.cssText = 'display:inline-block;transition:transform .15s;margin-right:4px' + (idleOpen ? '' : ';transform:rotate(-90deg)');
    last.append(more); last.onclick = () => { updDetailsOpen = !idleOpen; renderUpd(); };
    det.style.display = idleOpen ? 'block' : 'none'; showOut = idleOpen;
    det.innerHTML = '';
    const icon = {pending: '○', running: '◐', done: '✓', skipped: '–', error: '✕'};
    for (const s of u.steps) {
      const d = el('div', 'stp ' + s.status); d.append(el('span', 'ic', icon[s.status] || '○'), el('span', null, s.label));
      if (s.detail) d.append(el('small', null, s.detail));
      det.append(d);
    }
  } else { last.style.display = 'none'; det.style.display = 'none'; }
  out.style.display = showOut ? 'block' : 'none';
  if (showOut) { const atEnd = out.scrollTop + out.clientHeight >= out.scrollHeight - 30; out.textContent = u.lines.join('\n') + (u.live ? '\n' + u.live : ''); if (atEnd) out.scrollTop = out.scrollHeight; }
  const nw = $('#updNew'), cl = $('#updCommits'); cl.innerHTML = '';
  if (u.history && u.history.length && !busy) {
    nw.style.display = 'block';
    // Une version = une étiquette git (vX.Y.Z) : elle regroupe son commit et les commits plus anciens jusqu'à l'étiquette précédente.
    const groups = [], newest = u.history.find(m => m.tag);  // version publiée la plus récente : les commits qui la suivent sont numérotés v1.5.2-1, -2...
    const vlab = m => m.tag ? m.tag : (newest && m.num > newest.num ? newest.tag + '-' + (m.num - newest.num) : '');
    for (const m of u.history) {
      if (m.tag) groups.push({key: m.tag, title: _t('Version {0}', m.tag.replace(/^v/, '')), date: m.date, items: []});
      else if (!groups.length) groups.push({key: '_dev', title: 'En développement', sub: newest ? _t('non publiée · après {0}', newest.tag) : 'non publiée', items: []});
      groups[groups.length - 1].items.push(m);
    }
    const isCur = m => u.current && m.short === u.current.short;
    const fbOf = m => (m.new || isCur(m)) ? null : (u.fallbacks || []).find(f => m.short.startsWith(f.short) || f.short.startsWith(m.short));
    groups.forEach((g, gi) => {
      const shut = g.key in histShut ? histShut[g.key] : gi > 0;
      const head = el('div', 'vh' + (shut ? ' shut' : ''));
      head.append(el('span', 'chev', '▾'), el('b', null, g.title));
      if (g.sub) head.append(el('span', 'chip', g.sub));
      if (g.items.some(m => m.new)) head.append(el('span', 'chip ok', 'nouveau'));
      if (g.items.some(m => u.current && m.short === u.current.short)) head.append(el('span', 'chip', 'installée'));
      if (g.items.some(m => fbOf(m))) head.append(el('span', 'chip', 'version de secours'));
      head.append(el('small', null, (g.date ? g.date + ' · ' : '') + _t(g.items.length > 1 ? '{0} commits' : '{0} commit', g.items.length)));
      const body = el('div', 'vb'); body.style.display = shut ? 'none' : 'block';
      head.onclick = () => { const s = body.style.display !== 'none'; body.style.display = s ? 'none' : 'block'; head.classList.toggle('shut', s); histShut[g.key] = s; };
      for (const m of g.items) {
        const d = el('div', 'cm'), t = el('span', null, m.subject);
        const vl = vlab(m); d.append(el('code', null, (vl ? vl + ' · ' : '') + m.short + ' · ' + m.date), t);
        if (m.new) d.append(el('span', 'chip ok', 'nouveau'));
        if (u.current && m.short === u.current.short) d.append(el('span', 'chip', 'installé'));
        const fb = fbOf(m);
        if (fb) { const rb = el('button', 'b s', 'Revenir à cette version'); rb.title = fb.label; rb.onclick = () => startRollback(fb); d.append(rb); }
        body.append(d);
      }
      cl.append(head, body);
    });
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
setInterval(tickClock, 1000);
setInterval(() => { if (cur === 'log' && $('#logAuto').checked) loadLogs(); }, 3000);
setInterval(() => { if (cur === 'cfg' && (curCat === 'position' || curCat === 'mapstyle')) pollBuild(); }, 2000);
setInterval(() => { if (updWasRunning || (cur === 'upd' && ++updTick % 7 === 0)) pollUpd(); }, 1500);
pollStatus(); pollBuild();
loadSettings().catch(e => toast(e.message, true));
if (location.hash === '#upd') { history.replaceState(null, '', location.pathname); go('upd'); }
{ let rs = null; try { rs = JSON.parse(sessionStorage.getItem('fdRestore') || 'null'); sessionStorage.removeItem('fdRestore'); } catch (e) {}
  if (rs && rs.tab && rs.tab !== 'home') {  // retour sur l'onglet (et la catégorie) d'avant la coupure
    go(rs.tab);
    if (rs.tab === 'cfg' && rs.cat) { const t = setInterval(() => { if (SET && SET.cats && SET.cats[rs.cat]) { clearInterval(t); curCat = rs.cat; renderMenu(); renderCat(); } }, 200); setTimeout(() => clearInterval(t), 8000); }
  } }
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
    threading.Thread(target=sched_loop, daemon=True).start()
    threading.Thread(target=cache_loop, daemon=True).start()
    MQTT.configure(S.ini)
    MQTT.start()
    print(f"Administration sur http://{S.HOST}:{S.PORT}  (app : {S.APP_DIR})", flush=True)
    Server((S.HOST, S.PORT), Handler).serve_forever()
