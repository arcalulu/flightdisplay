#!/usr/bin/env python3
"""Traductions de Flight display (bibliotheque standard uniquement), partagees par main.py et webadmin.

Le francais est la langue source : les textes du code sont les cles. Chaque langue est un fichier
lang/<code>.json de la forme {"_meta": {"name": "English"}, "strings": {"texte francais": "traduction"}}.
Un texte absent du fichier reste en francais. Une cle peut contenir des emplacements {0}, {1}... :
elle sert alors de modele (« Espace libre : {0} Mo » reconnait « Espace libre : 120 Mo »).
Pour ajouter une langue : copier lang/en.json en lang/<code>.json, changer _meta.name et traduire les valeurs
(voir lang/check_lang.py), puis redemarrer webadmin : la langue apparait dans Reglages > Langue.
"""
import json, os, re

LANG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lang")
SOURCE = "fr"
_PH = re.compile(r"\{(\d+)\}")

_code = SOURCE
_exact = {}
_templates = []   # (regex compile, indices des groupes, traduction)
_cache = {}


def _read(code):
    with open(os.path.join(LANG_DIR, code + ".json"), encoding="utf-8-sig") as fh:
        d = json.load(fh)
    return d if isinstance(d, dict) else {}


def languages():
    """Langues disponibles : [{"code": "fr", "name": "Français"}, ...], francais en premier."""
    out = []
    try:
        names = sorted(f[:-5] for f in os.listdir(LANG_DIR) if f.endswith(".json") and re.fullmatch(r"[a-z]{2,3}(-[A-Za-z]{2,4})?", f[:-5]))
    except OSError:
        names = []
    for code in names:
        try:
            name = (_read(code).get("_meta") or {}).get("name") or code
        except Exception:
            continue
        out.append(dict(code=code, name=str(name)))
    if not any(l["code"] == SOURCE for l in out):
        out.insert(0, dict(code=SOURCE, name="Français"))
    out.sort(key=lambda l: (l["code"] != SOURCE, l["code"]))
    return out


def _compile(key, value):
    parts = _PH.split(key)           # texte, indice, texte, indice, ..., texte
    rx = "".join(re.escape(p) if i % 2 == 0 else "(.+?)" for i, p in enumerate(parts))
    return re.compile("^" + rx + "$", re.S), [int(x) for x in parts[1::2]], value


def set_language(code):
    """Active une langue ; un code inconnu ou illisible revient au francais. Renvoie le code actif."""
    global _code, _exact, _templates, _cache
    code = (code or SOURCE).strip().lower()
    strings = {}
    if code != SOURCE:
        try:
            strings = {k: v for k, v in (_read(code).get("strings") or {}).items() if isinstance(k, str) and isinstance(v, str) and v}
        except Exception:
            code, strings = SOURCE, {}
    _code, _exact, _cache = code, strings, {}
    _templates = [_compile(k, v) for k, v in strings.items() if _PH.search(k)]
    return _code


def current():
    return _code


def _fill(template, args):
    return _PH.sub(lambda m: str(args[int(m.group(1))]) if int(m.group(1)) < len(args) else m.group(0), template)


def _lookup(s):
    if s in _exact:
        return _exact[s]
    for rx, idx, value in _templates:
        m = rx.match(s)
        if m:
            args = {}
            for i, g in zip(idx, m.groups()):
                args[i] = _lookup(g)  # les valeurs captees sont traduites a leur tour (« Modele : {0} »)
            return _PH.sub(lambda mm: args.get(int(mm.group(1)), mm.group(0)), value)
    if " ; " in s:
        return " ; ".join(_lookup(p) for p in s.split(" ; "))
    return s


def tr(s, *args):
    """Traduit un texte. Avec des arguments, s est un modele {0}, {1}... ; sans argument, s peut etre un texte deja
    compose (« Espace libre : 120 Mo »), reconnu grace aux modeles de la langue."""
    if not isinstance(s, str) or not s:
        return s
    if args:
        return _fill(_exact.get(s, s), args)
    if _code == SOURCE:
        return s
    r = _cache.get(s)
    if r is None:
        if len(_cache) > 4000:
            _cache.clear()
        r = _cache[s] = _lookup(s)
    return r


def js_table():
    """Donnees pour le navigateur : {"lang": code, "strings": {...}}."""
    return dict(lang=_code, strings=_exact)
