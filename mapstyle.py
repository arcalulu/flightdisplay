"""Style du fond de carte : themes, couches affichees, couleurs. Partage entre build_map_vector.py (construction de l'image)
et webadmin (page « Style de la carte »). Aucune dependance autre que la bibliotheque standard (Pillow n'est utilise que par render)."""
import re

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Couleurs de chaque theme. Le theme "dark" reproduit exactement l'apparence d'origine.
COLOR_KEYS = ["land", "water", "forest", "park", "aero", "building", "road_minor", "road_major", "road_high", "rail", "taxiway", "runway", "boundary", "label"]
COLOR_LABELS = {
    "land": "Terre", "water": "Eau", "forest": "Forêts", "park": "Parcs", "aero": "Aéroports", "building": "Bâtiments",
    "road_minor": "Petites routes", "road_major": "Routes principales", "road_high": "Autoroutes", "rail": "Voies ferrées",
    "taxiway": "Voies de circulation", "runway": "Pistes", "boundary": "Frontières", "label": "Noms de lieux",
}
PRESETS = {
    "dark": dict(label="Sombre", colors=dict(land="#15191c", water="#2c3236", forest="#111517", park="#181e20", aero="#46494c", building="#23292d",
                                             road_minor="#262c30", road_major="#343b41", road_high="#454d54", rail="#353b40", taxiway="#50555a",
                                             runway="#696e73", boundary="#596470", label="#96a5b9")),
    "black": dict(label="Noir", colors=dict(land="#000000", water="#10161c", forest="#050707", park="#080a0b", aero="#1c1f22", building="#0d0f11",
                                            road_minor="#14171a", road_major="#20252a", road_high="#2c3238", rail="#1f2327", taxiway="#32383e",
                                            runway="#4a4f55", boundary="#3a424a", label="#7f8da0")),
    "light": dict(label="Clair", colors=dict(land="#f2f2ee", water="#cfdce6", forest="#dde6d6", park="#e3ead9", aero="#e4e2dc", building="#e6e4de",
                                             road_minor="#e0ded8", road_major="#d3d1ca", road_high="#c3c0b8", rail="#b9b6ae", taxiway="#c9c6be",
                                             runway="#bbb8b0", boundary="#b0b0b0", label="#666b70")),
    "voyager": dict(label="Voyager", colors=dict(land="#f6f1e9", water="#aad3df", forest="#cfe3c0", park="#d9e8c9", aero="#e6ddd0", building="#e3d8cb",
                                                 road_minor="#ffffff", road_major="#fcd6a4", road_high="#f7b267", rail="#a0a0a0", taxiway="#d8cfc2",
                                                 runway="#b7a99a", boundary="#a68fb0", label="#5a5a5a")),
    "radar": dict(label="Radar", colors=dict(land="#021208", water="#031c10", forest="#03160b", park="#04190d", aero="#08331c", building="#05230f",
                                             road_minor="#0b3a20", road_major="#0f4d2a", road_high="#17703d", rail="#0f4d2a", taxiway="#126034",
                                             runway="#15c060", boundary="#1d6b3a", label="#3fe08a")),
}
DEFAULT_PRESET = "dark"

# Couches : identifiant -> (valeur par defaut, libelle). Par defaut, l'apparence d'origine : eau, rivieres, aeroports, pistes.
LAYERS = {
    "water": (True, "Eau (lacs, mer)"), "rivers": (True, "Rivières et canaux"), "aerodromes": (True, "Aéroports"), "runways": (True, "Pistes"),
    "taxiways": (False, "Voies de circulation"), "forest": (False, "Forêts"), "parks": (False, "Parcs et espaces verts"),
    "roads_major": (False, "Routes principales et autoroutes"), "roads_minor": (False, "Petites routes"), "rail": (False, "Voies ferrées"),
    "buildings": (False, "Bâtiments"), "boundaries": (False, "Frontières"),
}
CITY_KINDS = ["city", "town", "village"]


def color_ok(v):
    return bool(v) and bool(HEX_RE.match(v.strip()))


def hex_rgb(v):
    v = v.lstrip("#")
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


def palette(preset, overrides=None):
    """Couleurs finales (tuples RGB) : le theme, puis les couleurs personnalisees valides."""
    base = dict(PRESETS.get(preset, PRESETS[DEFAULT_PRESET])["colors"])
    for k, v in (overrides or {}).items():
        if k in base and color_ok(str(v)):
            base[k] = str(v).strip().lower()
    return {k: hex_rgb(v) for k, v in base.items()}


def from_config(cfg):
    """Lit le style dans un ConfigParser (sections [mapstyle], [map] forest, [cities]). Les valeurs absentes donnent l'apparence d'origine."""
    g = lambda sec, key, d: cfg.get(sec, key, fallback=d)
    style = dict(preset=g("mapstyle", "preset", DEFAULT_PRESET), colors={}, show={}, road_width=1.0)
    if style["preset"] not in PRESETS:
        style["preset"] = DEFAULT_PRESET
    for k in COLOR_KEYS:
        v = g("mapstyle", "color_" + k, "").strip()
        if color_ok(v):
            style["colors"][k] = v
    for k, (d, _) in LAYERS.items():
        raw = g("mapstyle", "show_" + k, "").strip().lower()
        style["show"][k] = d if raw not in ("true", "false", "1", "0", "yes", "no") else raw in ("true", "1", "yes")
    # compatibilite : [map] forest existait avant la page de style
    if g("mapstyle", "show_forest", "").strip() == "":
        style["show"]["forest"] = cfg.getboolean("map", "forest", fallback=False)
    try:
        style["road_width"] = max(0.3, min(4.0, float(g("mapstyle", "road_width", "1"))))
    except ValueError:
        pass
    return style


def merge(style, over):
    """Applique des remplacements venant de la page (preset, colors, show, road_width) sur un style."""
    out = dict(preset=style["preset"], colors=dict(style["colors"]), show=dict(style["show"]), road_width=style["road_width"])
    if not over:
        return out
    if over.get("preset") in PRESETS:
        out["preset"] = over["preset"]
    if isinstance(over.get("colors"), dict):
        out["colors"] = {k: v for k, v in over["colors"].items() if k in COLOR_KEYS and color_ok(str(v))}
    if isinstance(over.get("show"), dict):
        for k, v in over["show"].items():
            if k in LAYERS:
                out["show"][k] = bool(v)
    try:
        if "road_width" in over:
            out["road_width"] = max(0.3, min(4.0, float(over["road_width"])))
    except (TypeError, ValueError):
        pass
    return out


_HIGH = {"highway", "motorway", "trunk", "motorway_link", "trunk_link"}
_MAJOR = {"major_road", "primary", "secondary", "primary_link", "secondary_link"}
_MINOR = {"medium_road", "minor_road", "tertiary", "tertiary_link", "residential", "service", "unclassified", "living_street", "road"}
_FOREST = {"forest", "wood"}
_PARK = {"park", "garden", "recreation_ground", "nature_reserve", "golf_course", "village_green", "grass", "meadow"}
_AERO = {"aerodrome", "airfield"}
_RIVER = {"river", "canal"}


def classify(layer, gt, kind, kd):
    """Categorie de dessin d'un objet de tuile vectorielle (None = ignore). gt : 1 point, 2 ligne, 3 polygone."""
    kind, kd = (kind or ""), (kd or "")
    if layer == "water":
        return "water" if gt == 3 else ("river" if gt == 2 and kind in _RIVER else None)
    if layer in ("landuse", "natural", "earth"):
        if gt != 3:
            return None
        if kind in _AERO and layer == "landuse":
            return "aero"
        if kind in _FOREST:
            return "forest"
        if kind in _PARK:
            return "park"
        return None
    if layer in ("roads", "transit") and gt == 2:
        if kd == "runway" or kind == "runway":
            return "runway"
        if kd == "taxiway" or kind == "taxiway":
            return "taxiway"
        if kind == "rail" or kd == "rail" or (layer == "transit" and kind in ("train", "railway")):
            return "rail"
        if kind in _HIGH or kd in _HIGH:
            return "road_high"
        if kind in _MAJOR or kd in _MAJOR:
            return "road_major"
        if kind in _MINOR or kd in _MINOR:
            return "road_minor"
        return None
    if layer == "buildings" and gt == 3:
        return "building"
    if layer == "boundaries" and gt == 2:
        return "boundary"
    return None


# categorie de dessin -> option qui l'active
_ENABLE = {"water": "water", "river": "rivers", "aero": "aerodromes", "runway": "runways", "taxiway": "taxiways", "forest": "forest", "park": "parks",
           "road_high": "roads_major", "road_major": "roads_major", "road_minor": "roads_minor", "rail": "rail", "building": "buildings", "boundary": "boundaries"}
POLY = ["forest", "park", "aero", "water", "building"]
LINES = ["boundary", "rail", "road_minor", "road_major", "road_high", "taxiway", "river", "runway"]
_COLOR = {"forest": "forest", "park": "park", "aero": "aero", "water": "water", "building": "building", "boundary": "boundary", "rail": "rail",
          "road_minor": "road_minor", "road_major": "road_major", "road_high": "road_high", "taxiway": "taxiway", "river": "water", "runway": "runway"}
_WIDTH = {"boundary": 1.0, "rail": 1.0, "road_minor": 1.0, "road_major": 1.6, "road_high": 2.2, "taxiway": 1.6, "river": 2.0, "runway": 3.0}
_SCALED = {"road_minor", "road_major", "road_high"}


def wanted(style):
    """Categories de dessin a collecter, d'apres les couches cochees."""
    return {c for c, opt in _ENABLE.items() if style["show"].get(opt)}


def render(draw_list, style, size, S):
    """Dessine l'image de fond. draw_list : {categorie: [[(points, exterieur?), ...], ...]} avec des points deja en pixels x S.
    Retourne (image PIL, palette)."""
    from PIL import Image, ImageDraw
    pal = palette(style["preset"], style["colors"])
    W, H = size
    img = Image.new("RGB", (W * S, H * S), pal["land"])
    d = ImageDraw.Draw(img)
    on = wanted(style)
    for k in POLY:
        if k not in on:
            continue
        col = pal[_COLOR[k]]
        for feat in draw_list.get(k, []):
            for pts, ex in feat:
                if ex:
                    d.polygon(pts, fill=col)
            for pts, ex in feat:
                if not ex:
                    d.polygon(pts, fill=pal["land"])
    for k in LINES:
        if k not in on:
            continue
        w = max(1, int(round(_WIDTH[k] * S * (style["road_width"] if k in _SCALED else 1.0))))
        for feat in draw_list.get(k, []):
            d.line(feat[0][0], fill=pal[_COLOR[k]], width=w, joint="curve" if k == "river" else None)
    return img, pal
