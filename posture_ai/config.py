"""
============================================================
 PostureAI V2 — Configuration centrale
============================================================
Toutes les constantes ajustables du projet sont ici. Modifie ce
fichier plutôt que d'aller chercher des valeurs éparpillées dans
le code.
============================================================
"""

import os

# ------------------------------------------------------------
# Chemins
# ------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DB_PATH = os.path.join(DATA_DIR, "postureai.db")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ------------------------------------------------------------
# Caméra
# ------------------------------------------------------------
# 0 / 1        -> webcam intégrée / USB du PC
# "http://IP:PORT/video" -> flux d'un téléphone (app "IP Webcam"), voir GUIDE.md
CAMERA_SOURCE = 0
MIRROR_PREVIEW = True
REQUESTED_WIDTH = 960
REQUESTED_HEIGHT = 540

# ------------------------------------------------------------
# Vie privée
# ------------------------------------------------------------
# PostureAI V2 ne sauvegarde JAMAIS d'image ou de vidéo de l'utilisateur.
# Seules des métriques numériques (angles, scores) sont stockées en local
# dans une base SQLite. Ce drapeau est affiché dans l'UI pour rappel.
PRIVACY_MODE = True

# ------------------------------------------------------------
# Calibration
# ------------------------------------------------------------
CALIBRATION_DURATION_S = 8.0          # durée de la calibration guidée (5-10s demandé)
CALIBRATION_MIN_SAMPLES = 20          # nb minimum d'échantillons valides requis

# Tolérance minimale (évite une tolérance nulle si l'utilisateur est
# resté parfaitement immobile pendant la calibration).
MIN_TOLERANCE_DEG = 4.0
MIN_TOLERANCE_RATIO = 0.03

# ------------------------------------------------------------
# Pondération du score global (doit sommer à 1.0)
# ------------------------------------------------------------
# Ces poids reflètent l'impact ergonomique relatif de chaque
# signal pour un poste de travail assis (littérature "tech neck" /
# forward head posture) : la tête projetée vers l'avant (et le fait
# de se rapprocher progressivement de l'écran, regroupés dans le
# même signal) est le facteur le plus fréquemment rapporté en
# télétravail, suivi de l'affaissement du tronc/des épaules.
WEIGHT_FORWARD_HEAD = 0.40
WEIGHT_TRUNK_LEAN = 0.25
WEIGHT_NECK_TILT = 0.20
WEIGHT_SHOULDER_ASYM = 0.15

# ------------------------------------------------------------
# Pondération interne de la métrique "Forward Head" (doit sommer à 1.0
# lorsque les 3 composantes sont disponibles ; redistribuée
# automatiquement si l'une d'elles manque, ex: pas de world landmarks)
#   - image_weight  : angle oreille/épaule (2D), normalisé par la
#                     largeur des épaules (fonctionne toujours)
#   - depth_weight  : profondeur 3D oreille/épaule (world landmarks),
#                     plus précise en vue frontale que le 2D seul
#   - proximity_weight : détecte le fait de se rapprocher
#                     progressivement de l'écran (largeur des épaules
#                     / largeur de l'image, comparée à la baseline)
# ------------------------------------------------------------
FORWARD_HEAD_IMAGE_WEIGHT = 0.45
FORWARD_HEAD_DEPTH_WEIGHT = 0.35
FORWARD_HEAD_PROXIMITY_WEIGHT = 0.20

# Bonus optionnel : quand les hanches SONT visibles (webcam plus
# éloignée, plan large), elles apportent une information
# supplémentaire sur l'inclinaison du tronc. Ce n'est jamais requis :
# sans hanches, le score "tronc/slouch" repose entièrement sur le
# ratio cou/épaules (voir posture_engine.py).
TRUNK_HIP_BONUS_WEIGHT = 0.35

# Pondération interne de l'asymétrie des épaules : la composante
# principale est la différence de hauteur des épaules ; une
# composante secondaire (différence de hauteur oreille/œil gauche vs
# droite) capte en plus l'inclinaison latérale de la tête, utile pour
# détecter une posture penchée d'un côté même quand les épaules
# semblent à peu près droites.
SHOULDER_ASYM_SHOULDER_WEIGHT = 0.70
SHOULDER_ASYM_HEAD_WEIGHT = 0.30

# ------------------------------------------------------------
# Classification du score (0-100), déjà relatif à la baseline
# de l'utilisateur car le score lui-même est calculé par rapport
# à sa calibration personnelle.
# ------------------------------------------------------------
SCORE_GOOD_THRESHOLD = 80
SCORE_WARNING_THRESHOLD = 60

# Lissage exponentiel du score affiché (0-1, plus haut = plus réactif)
SCORE_EMA_ALPHA = 0.25

# Durée minimale (s) qu'un nouveau statut doit "tenir" avant d'être
# officiellement adopté -> évite le clignotement bon/mauvais.
STATUS_MIN_DURATION_S = 1.3

# ------------------------------------------------------------
# Visibilité / cadrage caméra
# ------------------------------------------------------------
# NOTE V2.1 : PostureAI est pensé pour le cas d'usage réel le plus
# courant — développeur / gamer / étudiant ASSIS devant son écran,
# webcam intégrée en haut de l'écran, distance de travail normale.
# Dans cette configuration, seuls le visage, la tête, le cou, les
# épaules (et parfois le haut du torse) sont visibles ; les hanches
# ne le sont presque jamais. L'algorithme est donc conçu pour
# fonctionner PLEINEMENT sans les hanches (voir posture_engine.py),
# qui ne sont utilisées qu'en bonus si elles sont visibles.
MIN_LANDMARK_VISIBILITY = 0.5
EAR_MIN_VISIBILITY = 0.35             # sous ce seuil, on utilise l'œil comme repère de secours
HIP_MIN_VISIBILITY_FOR_BONUS = 0.5    # hanches utilisées seulement si confiance suffisante
FRAME_MARGIN_RATIO = 0.04             # marge de sécurité au bord de l'image
SHOULDER_WIDTH_MIN_RATIO = 0.10       # trop loin de la caméra si en dessous
SHOULDER_WIDTH_MAX_RATIO = 0.85       # webcam d'ordinateur portable = souvent très proche du visage

# ------------------------------------------------------------
# Alertes
# ------------------------------------------------------------
ALERT_GRACE_PERIOD_S = 4.0            # temps en mauvaise posture avant 1ère alerte
ALERT_REPEAT_EVERY_S = 20.0           # cooldown entre deux alertes (anti-spam)
ALERT_OVERLAY_LIFETIME_S = 6.0        # durée d'affichage de la bulle d'alerte

# Smart Break : proposer une pause si N mauvaises postures détectées
# (transitions vers "MAUVAISE") en moins de WINDOW secondes.
SMART_BREAK_BAD_EVENTS = 4
SMART_BREAK_WINDOW_S = 600.0          # 10 minutes
SMART_BREAK_COOLDOWN_S = 900.0        # ne pas re-suggérer avant 15 minutes

# Règle 20-20-20 : toutes les 20 minutes, regarder à 20 pieds pendant 20s
RULE_20_20_20_ENABLED = True
RULE_20_20_20_INTERVAL_S = 20 * 60.0

# Badge streak "bonne posture continue"
STREAK_BADGE_S = 30 * 60.0            # 30 minutes

# ------------------------------------------------------------
# Dashboard local (Flask)
# ------------------------------------------------------------
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 5057

# ------------------------------------------------------------
# Couleurs BGR (OpenCV) — palette dark/moderne
# ------------------------------------------------------------
COLOR_GOOD = (100, 220, 90)
COLOR_WARNING = (0, 165, 255)
COLOR_BAD = (60, 60, 235)
COLOR_PANEL = (22, 22, 26)
COLOR_TEXT = (235, 235, 240)
COLOR_MUTED = (150, 150, 158)
COLOR_ACCENT = (255, 195, 60)
COLOR_ACCENT2 = (255, 120, 210)
