"""Catalogue des themes de l'orbe : 42 ambiances en plus des 6 d'origine.

Chaque theme n'est qu'une palette de quatre couleurs et un style de matiere
(`nacre` : sphere irisee douce, `plasma` : bandes liquides tres vives). A
partir de cette description, ce module fabrique tout le reste :

  * le rendu ultra sur carte graphique (`orb_gpu.GPU_THEMES`) ;
  * le rendu de secours sur processeur (`orb_blob.BLOB_THEMES`) ;
  * les couleurs des panneaux (menu, historique, saisie, journal) ;
  * la bulle claire ou sombre.

Ajouter un theme = ajouter une ligne a `CATALOG`.
"""

from __future__ import annotations

# cle : (nom fr, nom en, famille, matiere, clair ?, lueur, ondulation, 4 couleurs RVB)
CATALOG = {
    "soleil": ("Soleil couchant", "Sunset", "chaud", "nacre", False, 0.7, 0.08,
               ((255, 120, 40), (240, 60, 100), (140, 60, 210), (255, 186, 60))),
    "lave": ("Lave", "Lava", "chaud", "plasma", False, 0.75, 0.14,
             ((255, 70, 30), (255, 150, 30), (200, 20, 40), (255, 220, 90))),
    "or": ("Or royal", "Royal gold", "chaud", "nacre", False, 0.5, 0.07,
           ((255, 206, 90), (230, 160, 40), (255, 236, 170), (200, 130, 60))),
    "ambre": ("Ambre", "Amber", "chaud", "nacre", False, 0.45, 0.07,
              ((255, 170, 60), (200, 100, 40), (255, 210, 130), (160, 80, 50))),
    "corail": ("Corail", "Coral", "chaud", "nacre", True, 0.3, 0.075,
               ((255, 128, 110), (255, 184, 150), (80, 210, 200), (255, 150, 180))),
    "rubis": ("Rubis", "Ruby", "chaud", "plasma", False, 0.65, 0.12,
              ((230, 30, 70), (150, 10, 60), (255, 90, 120), (120, 30, 140))),
    "ocean": ("Océan", "Ocean", "frais", "plasma", False, 0.55, 0.12,
              ((20, 170, 220), (10, 90, 200), (40, 220, 200), (30, 60, 150))),
    "abysse": ("Abysse", "Abyss", "frais", "plasma", False, 0.9, 0.11,
               ((0, 230, 200), (10, 40, 120), (60, 120, 255), (0, 150, 170))),
    "glacier": ("Glacier", "Glacier", "frais", "nacre", True, 0.3, 0.06,
                ((200, 236, 255), (150, 200, 255), (230, 250, 255), (170, 220, 240))),
    "menthe": ("Menthe", "Mint", "frais", "nacre", True, 0.3, 0.07,
               ((120, 230, 190), (160, 245, 220), (90, 200, 220), (200, 255, 210))),
    "emeraude": ("Émeraude", "Emerald", "frais", "nacre", False, 0.6, 0.08,
                 ((20, 200, 120), (10, 130, 90), (90, 240, 170), (20, 160, 160))),
    "foret": ("Forêt", "Forest", "frais", "nacre", False, 0.45, 0.07,
              ((90, 170, 80), (40, 110, 70), (170, 210, 90), (60, 150, 130))),
    "minuit": ("Minuit", "Midnight", "frais", "nacre", False, 0.6, 0.065,
               ((60, 90, 200), (20, 30, 90), (180, 196, 230), (90, 70, 180))),
    "galaxie": ("Galaxie", "Galaxy", "cosmique", "nacre", False, 0.95, 0.09,
                ((130, 60, 255), (255, 80, 200), (40, 140, 255), (255, 200, 255))),
    "synthwave": ("Synthwave", "Synthwave", "cosmique", "plasma", False, 0.8, 0.13,
                  ((255, 60, 180), (120, 50, 255), (40, 200, 255), (255, 140, 60))),
    "cyberpunk": ("Cyberpunk", "Cyberpunk", "cosmique", "plasma", False, 0.85, 0.14,
                  ((255, 20, 160), (0, 240, 255), (250, 240, 40), (140, 40, 255))),
    "matrix": ("Matrix", "Matrix", "cosmique", "plasma", False, 0.8, 0.12,
               ((40, 255, 90), (0, 140, 50), (170, 255, 120), (0, 200, 120))),
    "toxique": ("Toxique", "Toxic", "cosmique", "plasma", False, 0.8, 0.14,
                ((190, 255, 30), (60, 220, 40), (240, 255, 120), (0, 180, 110))),
    "prisme": ("Prisme", "Prism", "cosmique", "plasma", False, 0.6, 0.12,
               ((255, 80, 80), (255, 210, 60), (60, 220, 140), (80, 120, 255))),
    "lavande": ("Lavande", "Lavender", "doux", "nacre", True, 0.3, 0.07,
                ((190, 160, 255), (230, 190, 255), (160, 190, 255), (255, 200, 236))),
    "sakura": ("Sakura", "Sakura", "doux", "nacre", True, 0.3, 0.07,
               ((255, 170, 200), (255, 220, 230), (240, 140, 190), (255, 240, 220))),
    "bonbon": ("Barbe à papa", "Cotton candy", "doux", "nacre", True, 0.35, 0.08,
               ((255, 160, 220), (140, 210, 255), (200, 170, 255), (255, 210, 240))),
    # --- Relief & matieres : nouvelles matieres du shader (orb_materials) --- #
    "amethyste": ("Améthyste", "Amethyst", "relief", "cristal", False, 0.7, 0.0,
                  ((176, 96, 255), (96, 40, 200), (236, 190, 255), (255, 255, 255))),
    "diamant": ("Diamant", "Diamond", "relief", "cristal", False, 0.6, 0.0,
                ((210, 240, 255), (120, 170, 255), (255, 255, 255), (190, 225, 255))),
    "terre": ("Planète bleue", "Blue planet", "relief", "planete", False, 0.8, 0.0,
              ((70, 140, 70), (24, 74, 170), (170, 140, 90), (110, 180, 255))),
    "mars": ("Planète rouge", "Red planet", "relief", "planete", False, 0.6, 0.0,
             ((205, 95, 50), (120, 52, 36), (232, 160, 100), (255, 170, 120))),
    "exoplanete": ("Exoplanète", "Exoplanet", "relief", "planete", False, 0.9, 0.0,
                   ((60, 220, 180), (70, 24, 130), (230, 120, 255), (120, 255, 230))),
    "magma": ("Magma", "Magma", "relief", "magma", False, 0.8, 0.0,
              ((255, 90, 20), (95, 75, 70), (255, 160, 40), (255, 240, 150))),
    "chrome": ("Chrome liquide", "Liquid chrome", "relief", "chrome", False, 0.35, 0.08,
               ((230, 240, 255), (40, 50, 70), (120, 180, 255), (220, 225, 235))),
    "or_liquide": ("Or liquide", "Liquid gold", "relief", "chrome", False, 0.5, 0.08,
                   ((255, 232, 170), (90, 60, 20), (255, 190, 80), (255, 196, 90))),
    "reacteur": ("Réacteur", "Arc reactor", "relief", "reacteur", False, 0.8, 0.0,
                 ((70, 220, 255), (40, 70, 110), (150, 240, 255), (255, 255, 255))),
    "noyau_rouge": ("Noyau rouge", "Red core", "relief", "reacteur", False, 0.8, 0.0,
                    ((255, 60, 60), (90, 40, 45), (255, 150, 120), (255, 230, 220))),
    "oeil_dragon": ("Œil de dragon", "Dragon eye", "relief", "oeil", False, 0.5, 0.0,
                    ((255, 200, 40), (200, 60, 0), (255, 240, 120), (255, 230, 200))),
    "oeil_celeste": ("Œil céleste", "Celestial eye", "relief", "oeil", False, 0.5, 0.0,
                     ((130, 225, 255), (20, 80, 180), (210, 250, 255), (220, 235, 255))),
    "trou_noir": ("Trou noir", "Black hole", "relief", "trou_noir", False, 0.5, 0.0,
                  ((255, 140, 40), (180, 40, 20), (255, 200, 120), (255, 240, 200))),
    "quasar": ("Quasar", "Quasar", "relief", "trou_noir", False, 0.6, 0.0,
               ((120, 170, 255), (90, 40, 210), (200, 160, 255), (225, 240, 255))),
    "organique": ("Organique", "Organic", "relief", "cellules", False, 0.5, 0.0,
                  ((120, 230, 120), (255, 80, 160), (60, 180, 140), (200, 255, 200))),
    "hologramme": ("Hologramme", "Hologram", "relief", "hologramme", False, 0.7, 0.0,
                   ((60, 230, 255), (40, 120, 255), (180, 255, 255), (220, 255, 255))),
    "holo_vert": ("Hologramme vert", "Green hologram", "relief", "hologramme", False, 0.7, 0.0,
                  ((70, 255, 120), (20, 140, 60), (200, 255, 200), (220, 255, 220))),
    "marbre": ("Marbre et or", "Marble & gold", "relief", "marbre", True, 0.25, 0.0,
               ((238, 236, 232), (110, 110, 120), (215, 172, 80), (200, 205, 215))),
    "marbre_noir": ("Marbre noir", "Black marble", "relief", "marbre", False, 0.3, 0.0,
                    ((34, 34, 40), (205, 205, 215), (222, 182, 92), (90, 90, 110))),
    "orage": ("Orage", "Storm", "relief", "orage", False, 0.6, 0.06,
              ((132, 140, 178), (22, 24, 44), (110, 120, 255), (225, 232, 255))),
}

FAMILIES = {
    "fr": {"origine": "Originaux", "chaud": "Chauds", "frais": "Frais",
           "cosmique": "Néon & cosmos", "doux": "Pastels", "relief": "Relief & matières"},
    "en": {"origine": "Originals", "chaud": "Warm", "frais": "Cool",
           "cosmique": "Neon & cosmic", "doux": "Pastels", "relief": "Relief & materials"},
}
ORIGINAL_FAMILY = {"opale": "origine", "plasma": "origine", "aurore": "origine",
                   "nebuleuse": "origine", "jarvis": "origine", "siri": "origine"}
# Apercu (pastille du menu) des themes d'origine.
ORIGINAL_SWATCH = {
    "opale": ((250, 170, 200), (176, 156, 255), (255, 206, 160), (140, 228, 210)),
    "plasma": ((40, 224, 232), (40, 128, 240), (150, 96, 232), (118, 232, 204)),
    "aurore": ((80, 226, 248), (88, 124, 255), (170, 146, 250), (112, 196, 255)),
    "nebuleuse": ((70, 210, 255), (110, 64, 255), (220, 70, 220), (50, 80, 230)),
    "jarvis": ((30, 200, 255), (10, 90, 160), (160, 236, 255), (20, 140, 220)),
    "siri": ((10, 132, 255), (255, 60, 160), (48, 209, 88), (100, 210, 255)),
}


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)


def _mix(a, b, t: float):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _luma(rgb) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def panel_colors(colors, light: bool) -> dict:
    """Couleurs des panneaux Tk, accordees a la palette."""
    if light:
        accent = min(colors, key=_luma)
        accent = _mix(accent, (0, 0, 0), 0.25) if _luma(accent) > 150 else accent
        bg = _mix(colors[0], (255, 255, 255), 0.93)
        return {"bg": _hex(bg), "fg": _hex(_mix(accent, (20, 20, 30), 0.8)),
                "dim": _hex(_mix(accent, (120, 120, 130), 0.7)), "accent": _hex(accent),
                "active": _hex(_mix(bg, accent, 0.14))}
    accent = max(colors, key=_luma)
    bg = _mix(colors[1], (0, 0, 0), 0.9)
    return {"bg": _hex(bg), "fg": _hex(_mix(accent, (255, 255, 255), 0.85)),
            "dim": _hex(_mix(accent, (150, 150, 160), 0.6)), "accent": _hex(accent),
            "active": _hex(_mix(bg, accent, 0.2))}


def gpu_style(colors, matter: str, glow: float, ripple: float) -> dict:
    as_unit = tuple(tuple(v / 255.0 for v in rgb) for rgb in colors)
    from .orb_materials import MODES

    return {"colors": as_unit, "mode": MODES.get(matter, 0),
            "glow": glow, "ripple": ripple}


def blob_style(colors, light: bool, glow: float) -> dict:
    avg = tuple(sum(c[i] for c in colors) / len(colors) for i in range(3))
    base = _mix(avg, (255, 255, 255), 0.25) if light else _mix(avg, (0, 0, 0), 0.6)
    rim = _mix(max(colors, key=_luma), (255, 255, 255), 0.6)
    return {"base": tuple(int(v) for v in base), "sources": [tuple(c) for c in colors],
            "rim": tuple(int(v) for v in rim), "rim_strength": 0.45 if light else 0.55,
            "shine": 0.2 if light else 0.15, "alpha": 0.97, "glow": 0.0 if light else glow * 0.6,
            "wobble": 0.03 + glow * 0.006,
            "tints": {"listening": ((96, 240, 200), 0.32), "thinking": ((255, 170, 110), 0.32)}}


def label(theme: str, lang: str, strings: dict | None = None) -> str:
    if theme in CATALOG:
        return CATALOG[theme][0 if lang == "fr" else 1]
    text = (strings or {}).get(f"orb_theme_{theme}", theme.capitalize())
    return text.split(" (")[0]


def family(theme: str) -> str:
    return CATALOG[theme][2] if theme in CATALOG else ORIGINAL_FAMILY.get(theme, "origine")


def swatch(theme: str):
    return CATALOG[theme][7] if theme in CATALOG else ORIGINAL_SWATCH.get(theme)


def register(gpu_themes: dict, blob_themes: dict, theme_colors: dict) -> list[str]:
    """Ajoute le catalogue aux tables des moteurs de rendu ; renvoie les cles."""
    for key, (_fr, _en, _fam, matter, light, glow, ripple, colors) in CATALOG.items():
        gpu_themes.setdefault(key, gpu_style(colors, matter, glow, ripple))
        blob_themes.setdefault(key, blob_style(colors, light, glow))
        theme_colors.setdefault(key, panel_colors(colors, light))
    return list(CATALOG)


LIGHT = tuple(key for key, entry in CATALOG.items() if entry[4])

__all__ = ["CATALOG", "FAMILIES", "LIGHT", "register", "label", "family", "swatch",
           "panel_colors"]
