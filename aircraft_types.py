"""Formes d'icone des avions et correspondance type ICAO -> categorie.
Partage entre le programme d'affichage (main.py) et webadmin (liste visuelle des types)."""
import os
import re

PERSO_DIR = "photos_perso"  # photos personnelles (webadmin, fiche d'un avion) : <adresse ICAO>.jpg ou <immatriculation>.jpg


def perso_names(hx, reg):
    """Noms de fichier possibles de la photo personnelle d'un avion, dans l'ordre de recherche : adresse ICAO (6 chiffres hexa), puis immatriculation."""
    out = []
    h = (hx or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{6}", h):
        out.append(h + ".jpg")
    r = re.sub(r"[^A-Z0-9-]", "", (reg or "").upper())
    if r:
        out.append(r + ".jpg")
    return out


def perso_find(base, hx, reg):
    """Chemin de la photo personnelle de cet avion (dans le dossier base), ou None."""
    for n in perso_names(hx, reg):
        p = os.path.join(base, PERSO_DIR, n)
        if os.path.isfile(p):
            return p
    return None


def _build(L, fw, wy, Sp, sweep, tc, rc, ty, T, tsw, tch):
    nr = L * 0.12
    R = [(0, -L/2), (fw*0.8, -L/2 + nr), (fw, -L/2 + 2*nr), (fw, wy), (Sp, wy + sweep),
         (Sp, wy + sweep + tc), (fw, wy + rc), (fw, ty), (T, ty + tsw),
         (T, ty + tsw + tch), (fw*0.5, ty + tch), (0, L/2)]
    return R + [(-x, y) for x, y in reversed(R[1:-1])]


SHAPES = {
    "narrow":   _build(26, 1.8, -1, 12, 6, 2.2, 6, 9, 5, 2.5, 2.2),
    "wide":     _build(34, 2.4, -2, 16, 8, 2.6, 8, 12, 6.5, 3, 2.5),
    "quad":     _build(38, 3.0, -3, 19, 9, 3.0, 10, 14, 8, 3, 3),
    "regional": _build(22, 1.6, -0.5, 9.5, 4.5, 2, 5, 7.5, 4.5, 2, 2),
    "turbo":    _build(22, 1.7, -2, 13, 0.5, 2.8, 3.2, 8, 4.5, 1, 2.2),
    "light":    _build(14, 1.2, -3, 10, 0, 2.4, 2.4, 5, 3.5, 0, 1.8),
    "ulm":      _build(10, 0.9, -2.2, 9.5, 0, 2.6, 2.6, 3.6, 3.4, 0, 1.3),  # ultra leger motorise : petit, longues ailes droites
    "bizjet":   _build(18, 1.4, 0, 8, 4, 1.6, 4, 6, 3.5, 1.5, 1.5),
    "heli":     [(-2,-4),(2,-4),(2.5,2),(0.7,3),(0.7,12),(2.2,12),(2.2,13),(-2.2,13),(-2.2,12),(-0.7,12),(-0.7,3),(-2.5,2)],
}

CATS = {
    "narrow": "A318 A319 A320 A321 A19N A20N A21N B731 B732 B733 B734 B735 B736 B737 B738 B739 B37M B38M B39M B3XM B752 B753 BCS1 BCS3 MD81 MD82 MD83 MD87 MD88 MD90 B712 B722",
    "wide": "A306 A310 A332 A333 A338 A339 A359 A35K B762 B763 B764 B772 B77L B77W B773 B788 B789 B78X DC10 MD11",
    "quad": "A388 A342 A343 A345 A346 B741 B742 B743 B744 B748 B74S B74R A124 IL76 IL96",
    "regional": "E170 E175 E190 E195 E290 E295 E75L E75S E135 E145 CRJ1 CRJ2 CRJ7 CRJ9 CRJX SU95 RJ85 RJ1H F100 F70 B461 B462 B463",
    "turbo": "AT43 AT44 AT45 AT46 AT72 AT73 AT75 AT76 DH8A DH8B DH8C DH8D SF34 SB20 JS31 JS32 JS41 D328 F50 F27 E120 B190 BE20 BE9L PC12 C208 TBM7 TBM8 TBM9 AN26 AN12 C130 C30J A400",
    "light": "C150 C152 C162 C172 C177 C182 C185 C206 C210 PA18 PA28 P28A P28R PA32 PA34 PA44 PA46 SR20 SR22 DR40 DA20 DA40 DA42 DA62 TB10 TB20 TB21 BE33 BE35 BE36 BE58 M20P M20T AA5 RV7 RV8 RV9 GLID PIVI S22T",
    "ulm": "ULAC P92 CTSW CTLS",
    "bizjet": "C25A C25B C25C C25M C510 C525 C550 C560 C56X C680 C68A C700 C750 CL30 CL35 CL60 CL64 GLF2 GLF3 GLF4 GLF5 GLF6 GL5T GL7T GALX G150 G280 E35L E55P FA50 FA7X FA8X FA6X F900 F2TH LJ35 LJ40 LJ45 LJ60 LJ75 E50P H25B H25C PRM1 SF50 EA50 BE40 ASTR",
    "heli": "EC20 EC25 EC30 EC35 EC45 EC55 EC75 EC13 AS32 AS35 AS50 AS55 AS65 AS3B H60 H47 H46 H53 H500 H160 H135 H145 H175 H225 R22 R44 R66 B06 B407 B412 B429 B105 B212 A109 A119 A139 A169 A189 S76 S92 S61 AW09 NH90 MI8 MI26 KA32 EXPL",
}
BUILTIN = {code: cat for cat, codes in CATS.items() for code in codes.split()}
ORDER = list(SHAPES)


def read_extra(path):
    """Lit types_extra.txt : {CODE: categorie} (lignes invalides ignorees)."""
    out = {}
    try:
        for line in open(path, encoding="utf-8-sig"):
            p = line.split("#")[0].split()
            if len(p) == 2 and p[1] in SHAPES:
                out[p[0].upper()] = p[1]
    except OSError:
        pass
    return out


# Mots du nom du modele (fourni par Flightradar24) -> categorie. Le premier groupe qui correspond l'emporte.
HINTS = [
    ("heli", ["helicopter", "eurocopter", "robinson r", "sikorsky", "agusta", "bell 2", "bell 4", "hughes", "guimbal", "cabri", "mil mi", "kamov",
              "bo 105", "bo-105", "md 500", "md 600", "md 900", "airbus h", "as350", "as355", "ec135", "ec145", "ec130"]),
    ("bizjet", ["gulfstream", "learjet", "citation", "falcon", "challenger", "global 5", "global 6", "global 7", "global express", "hawker", "pc-24",
                "phenom", "praetor", "legacy", "hondajet", "eclipse 5", "vision sf50", "beechjet", "premier", "astra", "bd-100", "cessna cj"]),
    ("quad", ["a380", "a340", "boeing 747", "747-", "an-124", "il-76", "c-5 galaxy"]),
    ("wide", ["a330", "a350", "a300", "a310", "boeing 767", "boeing 777", "boeing 787", "767-", "777-", "787-", "dc-10", "md-11", "il-96"]),
    ("regional", ["embraer", "erj", "crj", "canadair regional", "bombardier crj", "superjet", "fokker 70", "fokker 100", "avro rj", "bae 146", "rj85", "rj100"]),
    ("turbo", ["atr ", "atr-", "dash 8", "dhc-8", "saab 340", "saab 2000", "dornier 328", "jetstream", "king air", "beech 1900", "pc-12", "caravan", "tbm",
               "piaggio", "cessna 208", "turboprop", "an-26", "c-130", "hercules", "a400", "l-410", "fokker 50", "fokker 27", "brasilia", "swearingen",
               "twin otter", "dhc-6", "pc-6", "emb-120"]),
    ("narrow", ["a318", "a319", "a320", "a321", "a220", "boeing 737", "boeing 757", "boeing 717", "737-", "757-", "md-8", "md-9", "dc-9", "bombardier cs",
                "tu-154", "yak-42", "c919"]),
    ("ulm", ["ulm", "ultralight", "ultra-light", "ultra light", "microlight", "trike", "paramotor", "flight design", "tecnam p92", "p92 "]),
    ("light", ["cessna 1", "cessna 2", "piper", "cirrus sr", "diamond", "robin ", "dr400", "tecnam", "mooney", "bonanza", "baron", "grob", "glider",
               "glasfl", "schleicher", "ultralight", "pitts", "extra ", "zlin", "socata", "rallye", "jodel", " cub", "aeronca", "stinson", "maule", "van's",
               "rutan", "wt9", "dyn'aero", "pioneer", "savannah", "ikarus", "evektor", "cessna 3", "cessna 4", "cap-10", "cap 10", "mudry", "aerospool", "wt-9", "j-3"]),
]


def suggest(model):
    """Categorie probable d'apres le nom du modele, ou None si rien ne correspond."""
    m = " " + (model or "").lower() + " "
    for cat, words in HINTS:
        if any(w in m for w in words):
            return cat
    return None


# ---- classement d'apres la base officielle OACI (doc 8643) : categorie de vol, moteurs, masse
_AIRLINER_MAKERS = ("AIRBUS", "BOEING", "MCDONNELL DOUGLAS", "DOUGLAS", "TUPOLEV", "YAKOVLEV", "IRKUT")
_REGIONAL_MAKERS = ("EMBRAER", "FOKKER", "SUKHOI", "MITSUBISHI", "AVRO", "BAE SYSTEMS", "HARBIN")
_BIZ_WORDS = ("phenom", "legacy", "praetor", "emb-500", "emb-505", "emb-545", "emb-550", "challenger 3", "challenger 6", "challenger 5", "global", "corporate")


def _one(mfr, model, desc, wtc, n, etype):
    """Categorie d'une fiche de la base OACI. desc = LandPlane, Helicopter...; wtc = categorie de turbulence (L, M, H, J)."""
    if desc in ("Helicopter", "Gyrocopter", "Tiltrotor"):
        return "heli"
    if etype.startswith("Turboprop"):
        return "turbo"
    if etype != "Jet":
        return "light"
    name = (mfr + " " + model).lower()
    mfr = mfr.upper()
    if wtc in ("H", "J"):
        return "quad" if n >= 4 else "wide"
    if any(w in name for w in _BIZ_WORDS):
        return "bizjet"
    if n >= 4:
        return "regional"
    if "regional jet" in name or "crj" in name or "328" in name or mfr.startswith(_REGIONAL_MAKERS):
        return "regional"
    if mfr in _AIRLINER_MAKERS or "cseries" in name or "bd-500" in name or "c919" in name or "mc-21" in name or "a-220" in name:
        return "narrow"
    return "bizjet"


def classify_icao(recs):
    """recs = fiches OACI d'un meme code [(fabricant, modele, description, wtc, nb_moteurs, type_moteur)].
    Retourne (categorie, nom du modele) d'apres la categorie la plus frequente."""
    votes = {}
    for r in recs:
        votes.setdefault(_one(*r), []).append(r)
    # une seule fiche "Regional Jet" suffit : les autres fiches du meme code sont des versions executives (ex. CRJ2)
    cat = "regional" if "regional" in votes else max(votes, key=lambda c: len(votes[c]))
    r = votes[cat][0]
    return cat, (r[0].title() + " " + r[1]).strip()
