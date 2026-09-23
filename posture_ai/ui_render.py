"""
============================================================
 PostureAI V2 — Rendu UI professionnel (texte + icônes)
============================================================
POURQUOI CE MODULE EXISTE :

`cv2.putText` (OpenCV) ne sait dessiner que les polices "Hershey"
intégrées, qui ne supportent PAS l'UTF-8. Tout caractère accentué
(é, è, à...) ou emoji est encodé sur plusieurs octets ; OpenCV les
affiche alors comme des "?" illisibles (ex: "Détail" -> "D??tail").

CE MODULE RÉSOUT CE PROBLÈME en dessinant le texte avec Pillow (PIL),
qui supporte nativement l'UTF-8 et les polices système (Segoe UI sous
Windows), avec anti-aliasing — un rendu net et professionnel.

Principe : dessiner les FORMES (panneaux, barres, anneaux, icônes)
directement sur l'image OpenCV (rapide), mais accumuler tout le TEXTE
dans une file (`TextLayer`) et ne faire la conversion vers/depuis PIL
qu'UNE SEULE FOIS par frame (`flush()`), pour rester performant.

Les emojis (⚠, 🔒, ☕, 👀, 🏅) ne sont pas non plus fiables avec les
polices système classiques (glyphes manquants). Ils sont donc
remplacés ici par de petites icônes vectorielles monochromes dessinées
avec des primitives OpenCV (rectangles, arcs, lignes) — plus sobre et
plus "pro" qu'un emoji multicolore de toute façon.
============================================================
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------
# Chargement des polices (avec repli si Segoe UI absente, ex: hors
# Windows). Mis en cache pour éviter de recharger à chaque frame.
# ------------------------------------------------------------
_REGULAR_CANDIDATES = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
_BOLD_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

_font_cache = {}


def _load_font(size, bold=False):
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    candidates = _BOLD_CANDIDATES if bold else _REGULAR_CANDIDATES
    font = None
    for path in candidates:
        try:
            font = ImageFont.truetype(path, size)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=size)
        except Exception:
            font = ImageFont.load_default()
    _font_cache[key] = font
    return font


# ------------------------------------------------------------
# Échelle typographique "pro" : tailles modestes et cohérentes,
# plutôt qu'un texte surdimensionné (voir GUIDE.md, retour utilisateur).
# ------------------------------------------------------------
SIZE_TITLE = 20      # ex: "PostureAI V2"
SIZE_META = 12       # ex: timer de session, mentions discrètes
SIZE_SCORE = 26      # chiffre au centre de l'anneau de score
SIZE_STATUS = 14     # BONNE / LIMITE / MAUVAISE
SIZE_SECTION = 13    # en-têtes de panneau ("Détail posture")
SIZE_LABEL = 12      # libellés de métriques
SIZE_SMALL = 11      # texte discret (raccourcis, hints)
SIZE_TOAST = 13      # messages d'alerte / motivation


class TextLayer:
    """Accumule des demandes de dessin de texte pour la frame en cours,
    puis les applique en une seule passe PIL (`flush`). Réutiliser une
    seule instance par frame évite les conversions BGR<->RGB répétées."""

    def __init__(self):
        self._items = []

    def reset(self):
        self._items.clear()

    def add(self, text, pos, size=SIZE_LABEL, color=(235, 235, 240), bold=False, anchor="la"):
        """pos = (x, y). color = tuple BGR (comme le reste du code OpenCV).
        anchor : voir PIL ImageDraw.text (par défaut 'la' = gauche/haut)."""
        self._items.append((text, pos, size, color, bold, anchor))

    def measure(self, text, size=SIZE_LABEL, bold=False):
        """Retourne (largeur, hauteur) approximatives du texte, pour
        aligner/centrer avant même d'avoir appelé flush()."""
        font = _load_font(size, bold)
        try:
            bbox = font.getbbox(text)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            return (len(text) * size // 2, size)

    def flush(self, frame_bgr):
        """Convertit la frame en PIL, dessine tout le texte accumulé,
        reconvertit en tableau BGR OpenCV, et vide la file."""
        if not self._items:
            return frame_bgr
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        draw = ImageDraw.Draw(pil_img)
        for text, pos, size, color_bgr, bold, anchor in self._items:
            font = _load_font(size, bold)
            color_rgb = (color_bgr[2], color_bgr[1], color_bgr[0])
            try:
                draw.text(pos, text, font=font, fill=color_rgb, anchor=anchor)
            except Exception:
                draw.text(pos, text, font=font, fill=color_rgb)
        self.reset()
        out = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        return out


# ============================================================
# Icônes vectorielles (remplacent les emojis, non fiables avec les
# polices système et peu "professionnels" de toute façon)
# ============================================================

def icon_privacy_lock(frame, x, y, s, color):
    """Petit cadenas : corps + anse. (x, y) = coin haut-gauche, s = taille."""
    body_top = y + s * 0.45
    cv2.rectangle(frame, (int(x), int(body_top)), (int(x + s), int(y + s)), color, -1, cv2.LINE_AA)
    center = (int(x + s / 2), int(y + s * 0.42))
    axes = (int(s * 0.28), int(s * 0.32))
    cv2.ellipse(frame, center, axes, 0, 180, 360, color, max(2, int(s * 0.14)), cv2.LINE_AA)


def icon_warning(frame, x, y, s, color):
    """Triangle d'alerte avec point d'exclamation (formes, pas de texte)."""
    p1 = (int(x + s / 2), int(y))
    p2 = (int(x), int(y + s))
    p3 = (int(x + s), int(y + s))
    pts = np.array([p1, p2, p3], dtype=np.int32)
    cv2.polylines(frame, [pts], True, color, max(2, int(s * 0.1)), cv2.LINE_AA)
    bar_top = (int(x + s / 2), int(y + s * 0.35))
    bar_bot = (int(x + s / 2), int(y + s * 0.68))
    cv2.line(frame, bar_top, bar_bot, color, max(2, int(s * 0.12)), cv2.LINE_AA)
    cv2.circle(frame, (int(x + s / 2), int(y + s * 0.85)), max(1, int(s * 0.06)), color, -1, cv2.LINE_AA)


def icon_coffee(frame, x, y, s, color):
    """Tasse de pause-café stylisée : corps trapézoïdal + anse + vapeur."""
    top_w, bot_w, cup_h = s * 0.8, s * 0.55, s * 0.5
    top_y = y + s * 0.4
    bot_y = top_y + cup_h
    top_l, top_r = x + (s - top_w) / 2, x + (s + top_w) / 2
    bot_l, bot_r = x + (s - bot_w) / 2, x + (s + bot_w) / 2
    pts = np.array([(top_l, top_y), (top_r, top_y), (bot_r, bot_y), (bot_l, bot_y)], dtype=np.int32)
    cv2.polylines(frame, [pts], True, color, max(2, int(s * 0.08)), cv2.LINE_AA)
    handle_c = (int(top_r + s * 0.08), int(top_y + cup_h * 0.4))
    cv2.ellipse(frame, handle_c, (int(s * 0.13), int(s * 0.15)), 0, -100, 100, color,
                max(1, int(s * 0.07)), cv2.LINE_AA)
    for dx in (0.32, 0.58):
        x0 = int(x + s * dx)
        cv2.line(frame, (x0, int(top_y - 2)), (x0 - int(s * 0.06), int(y)), color,
                 max(1, int(s * 0.06)), cv2.LINE_AA)


def icon_eye(frame, x, y, s, color):
    """Œil stylisé (règle des 20-20-20)."""
    center = (int(x + s / 2), int(y + s / 2))
    axes = (int(s / 2), int(s * 0.32))
    cv2.ellipse(frame, center, axes, 0, 0, 360, color, max(2, int(s * 0.09)), cv2.LINE_AA)
    cv2.circle(frame, center, max(2, int(s * 0.16)), color, -1, cv2.LINE_AA)


def icon_badge(frame, x, y, s, color):
    """Médaille/badge de streak : cercle + ruban."""
    center = (int(x + s / 2), int(y + s * 0.4))
    r = int(s * 0.35)
    cv2.circle(frame, center, r, color, -1, cv2.LINE_AA)
    cv2.circle(frame, center, int(r * 0.55), (20, 20, 26), -1, cv2.LINE_AA)
    tail_y = int(y + s)
    cv2.line(frame, (center[0] - int(r * 0.5), center[1] + int(r * 0.3)),
              (center[0] - int(r * 0.9), tail_y), color, max(2, int(s * 0.08)), cv2.LINE_AA)
    cv2.line(frame, (center[0] + int(r * 0.5), center[1] + int(r * 0.3)),
              (center[0] + int(r * 0.9), tail_y), color, max(2, int(s * 0.08)), cv2.LINE_AA)


def icon_spark(frame, x, y, s, color):
    """Petite icône 'tendance' (flèche montante) pour le mini-graphe."""
    pts = np.array([
        (int(x), int(y + s)), (int(x + s * 0.3), int(y + s * 0.55)),
        (int(x + s * 0.55), int(y + s * 0.75)), (int(x + s), int(y)),
    ], dtype=np.int32)
    cv2.polylines(frame, [pts], False, color, max(2, int(s * 0.14)), cv2.LINE_AA)


# ============================================================
# Mini-graphe (sparkline) — tendance du score en direct
# ============================================================

def draw_sparkline(frame, x, y, w, h, values, color, bg=(32, 32, 38), grid=(55, 55, 62),
                    min_v=0, max_v=100):
    """Dessine un mini-graphe linéaire des dernières valeurs (0-100)."""
    cv2.rectangle(frame, (x, y), (x + w, y + h), bg, -1)
    # ligne de référence (seuil "BONNE")
    good_y = y + h - int((80 - min_v) / (max_v - min_v) * h)
    cv2.line(frame, (x, good_y), (x + w, good_y), grid, 1, cv2.LINE_AA)

    if len(values) >= 2:
        n = len(values)
        pts = []
        for i, v in enumerate(values):
            px = x + int(i * w / max(n - 1, 1))
            vv = max(min_v, min(max_v, v))
            py = y + h - int((vv - min_v) / (max_v - min_v) * h)
            pts.append((px, py))
        for i in range(1, len(pts)):
            cv2.line(frame, pts[i - 1], pts[i], color, 2, cv2.LINE_AA)
        cv2.circle(frame, pts[-1], 3, color, -1, cv2.LINE_AA)

    cv2.rectangle(frame, (x, y), (x + w, y + h), (90, 90, 98), 1, cv2.LINE_AA)
