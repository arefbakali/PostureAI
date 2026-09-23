"""
============================================================
 PostureAI V2.1 — Moteur de posture (multi-critères + calibration)
 Adapté à l'usage réel : utilisateur ASSIS, webcam frontale/haute
============================================================
CE QUE CE MODULE FAIT :

CAS D'USAGE CIBLE : développeur / gamer / étudiant / télétravailleur
assis devant son écran, webcam intégrée en haut de l'écran, à une
distance de travail normale. Dans cette configuration, seuls le
visage, la tête, le cou, les épaules et parfois le haut du torse
sont visibles à la caméra — les hanches ne le sont presque jamais.
Le moteur est donc conçu pour fonctionner PLEINEMENT sans elles ;
si elles sont visibles (webcam plus reculée), elles n'apportent
qu'un signal BONUS, jamais une condition bloquante.

1. Extrait plusieurs métriques posturales à partir des landmarks
   MediaPipe Pose (2D image + coordonnées 3D "world landmarks"),
   en utilisant uniquement nez / yeux / oreilles / épaules (+ haut
   du torse si visible) :

   a) Forward Head (tête en avant / "tech neck" / rapprochement de
      l'écran) — combine 3 signaux complémentaires, tous utilisables
      en vue quasi frontale :
      - image 2D : décalage horizontal oreille (ou œil si l'oreille
        n'est pas assez visible) / épaule, normalisé par la largeur
        des épaules (indépendant des hanches et de la distance
        caméra).
      - 3D "world landmarks" : profondeur (axe z) oreille/épaule
        dans le repère métrique MediaPipe — disponible même sans
        hanches visibles, plus fiable qu'un angle 2D seul en vue de
        face.
      - proximité à l'écran : largeur des épaules rapportée à la
        largeur de l'image, comparée à la baseline. Une croissance
        de ce ratio = l'utilisateur se rapproche progressivement de
        l'écran, ce qui accompagne quasi toujours une tête en avant.
      Les trois sont combinés par une moyenne pondérée (poids dans
      config.py), redistribuée automatiquement si l'un des signaux
      manque (ex : pas de world landmarks).

   b) Neck tilt : angle entre le vecteur (milieu épaules -> nez) et
      la verticale de l'image — capte l'inclinaison tête/cou,
      fonctionne nativement en vue frontale.

   c) Trunk lean / Slouch (affaissement) :
      - signal PRINCIPAL, sans hanches : ratio "longueur de cou"
        = distance verticale épaule -> oreille/œil, normalisée par
        la largeur des épaules. Quand on se voûte ou que les
        épaules remontent (haussement, affaissement), ce ratio
        diminue par rapport à la baseline.
      - signal BONUS, si les deux hanches sont visibles avec une
        confiance suffisante : angle (milieu hanches -> milieu
        épaules) vs verticale (2D + profondeur 3D), mélangé au
        signal principal. Jamais requis pour que la détection
        fonctionne.

   d) Shoulder asymmetry / inclinaison latérale : combine la
      différence de hauteur entre les deux épaules (signal principal)
      et la différence de hauteur entre les deux oreilles/yeux
      (signal secondaire), ce qui capte à la fois des épaules
      déséquilibrées ET une tête penchée d'un côté (posture
      asymétrique), sans dépendre des hanches.

2. CALIBRATION PERSONNELLE : au démarrage, quelques secondes
   ASSIS, dans une posture correcte devant l'écran, servent de
   référence individuelle (baseline) pour chacune de ces métriques,
   avec une tolérance dérivée de l'écart-type observé.

3. SCORE GLOBAL 0-100 — FORMULE :

       score = 0.40 * forward_head_score
             + 0.25 * trunk_lean_score      (slouch)
             + 0.20 * neck_tilt_score
             + 0.15 * shoulder_asym_score

   Chaque métrique est convertie en sous-score selon son écart à la
   baseline personnelle (jamais un seuil unique/absolu), puis
   combinée par cette moyenne pondérée. Un score de 100 = posture
   quasi identique à la calibration ; le score ne peut PAS rester
   élevé si un seul indicateur "semble bon" pendant que les autres
   se dégradent (ex: une position volontairement inconfortable mais
   qui garde la tête droite fera quand même chuter le score via le
   slouch et/ou l'asymétrie). Les poids sont justifiés dans
   config.py.

4. Une couche de lissage (moyenne mobile exponentielle) + une durée
   minimale avant tout changement de statut (hystérésis temporelle)
   évitent le clignotement bon/mauvais et les faux positifs liés au
   bruit frame-à-frame.

5. Détection de cadrage caméra invalide (landmarks peu visibles,
   utilisateur trop près/loin/hors cadre) -> message de
   repositionnement. Ce message ne demande JAMAIS de vue de profil
   ou 3/4 : la détection est pensée pour une webcam quasi frontale.

AVERTISSEMENT : ceci est un outil de sensibilisation au bien-être/
ergonomie au poste de travail. Ce n'est PAS un dispositif médical
et ne remplace pas l'avis d'un professionnel de santé (kiné,
médecin) en cas de douleur persistante.
============================================================
"""

import math
import time
from collections import deque
from dataclasses import dataclass, field

from . import config


# ============================================================
# Structures de données
# ============================================================

@dataclass
class RawMetrics:
    """Métriques posturales brutes extraites d'une frame."""
    forward_head: float = 0.0     # combinaison image + 3D + proximité écran
    neck_tilt: float = 0.0        # degrés d'écart à la verticale
    trunk_lean: float = 0.0       # ratio "longueur de cou" (+ bonus hanches si dispo)
    shoulder_asym: float = 0.0    # ratio (0-1) d'asymétrie épaules + tête
    hip_lean_deg: float = None    # bonus optionnel (None si hanches non visibles)
    valid: bool = False
    framing_issue: str = ""       # "" si OK, sinon message à afficher


@dataclass
class ScoredMetrics:
    overall_score: float = 100.0
    forward_head_score: float = 100.0
    trunk_lean_score: float = 100.0
    neck_tilt_score: float = 100.0
    shoulder_asym_score: float = 100.0
    raw: RawMetrics = field(default_factory=RawMetrics)


@dataclass
class Baseline:
    forward_head: float = 0.0
    forward_head_tol: float = config.MIN_TOLERANCE_RATIO
    neck_tilt: float = 0.0
    neck_tilt_tol: float = config.MIN_TOLERANCE_DEG
    trunk_lean: float = 0.0
    trunk_lean_tol: float = config.MIN_TOLERANCE_RATIO
    shoulder_asym: float = 0.0
    shoulder_asym_tol: float = config.MIN_TOLERANCE_RATIO
    hip_lean: float = 0.0
    hip_lean_tol: float = config.MIN_TOLERANCE_DEG
    hip_ready: bool = False       # True seulement si les hanches étaient
                                   # visibles pendant assez d'échantillons
                                   # de calibration (bonus, jamais requis)
    ready: bool = False


# ============================================================
# Fonctions géométriques
# ============================================================

def _angle_from_vertical_deg(dx, dy):
    """Angle (degrés) entre un vecteur (dx, dy) et la verticale (0,-1)."""
    # atan2(dx, -dy) = 0 quand le vecteur pointe pile vers le haut.
    return math.degrees(math.atan2(dx, -dy))


def _dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _weighted_avg(pairs):
    """Moyenne pondérée qui ignore les valeurs None et redistribue
    automatiquement leur poids sur les valeurs disponibles.
    pairs: liste de (valeur_ou_None, poids)."""
    total_w = sum(w for v, w in pairs if v is not None)
    if total_w <= 0:
        return 0.0
    return sum(v * w for v, w in pairs if v is not None) / total_w


class PostureExtractor:
    """Convertit les landmarks MediaPipe bruts en RawMetrics.

    Conçu pour une webcam QUASI FRONTALE et un utilisateur ASSIS :
    seuls nez / yeux / oreilles / épaules sont requis. Les hanches
    sont utilisées en bonus si elles sont visibles avec une
    confiance suffisante, mais ne conditionnent jamais la validité
    d'une frame.
    """

    def __init__(self, mp_pose):
        self.mp_pose = mp_pose

    def _head_ref(self, ear, eye):
        """Retourne l'oreille si elle est assez visible, sinon l'œil
        (souvent mieux détecté en vue frontale, oreille partiellement
        cachée par les cheveux ou l'angle de la webcam)."""
        return ear if ear.visibility >= config.EAR_MIN_VISIBILITY else eye

    def extract(self, image_landmarks, world_landmarks, frame_w, frame_h):
        PL = self.mp_pose.PoseLandmark
        lm = image_landmarks

        nose = lm[PL.NOSE]
        l_ear, r_ear = lm[PL.LEFT_EAR], lm[PL.RIGHT_EAR]
        l_eye, r_eye = lm[PL.LEFT_EYE], lm[PL.RIGHT_EYE]
        l_shoulder, r_shoulder = lm[PL.LEFT_SHOULDER], lm[PL.RIGHT_SHOULDER]
        l_hip, r_hip = lm[PL.LEFT_HIP], lm[PL.RIGHT_HIP]

        l_ref = self._head_ref(l_ear, l_eye)
        r_ref = self._head_ref(r_ear, r_eye)

        raw = RawMetrics()

        # --- visibilité minimale : nez, épaules, oreille-ou-œil de
        #     chaque côté. Les hanches NE sont PAS requises. ---
        core_vis = min(
            nose.visibility, l_shoulder.visibility, r_shoulder.visibility,
            max(l_ear.visibility, l_eye.visibility),
            max(r_ear.visibility, r_eye.visibility),
        )
        if core_vis < config.MIN_LANDMARK_VISIBILITY:
            raw.valid = False
            raw.framing_issue = "Visage/épaules peu visibles : reviens bien en face de la caméra."
            return raw

        # --- vérification de cadrage : bords de l'image (hanches exclues) ---
        pts_to_check = [nose, l_shoulder, r_shoulder, l_ref, r_ref]
        m = config.FRAME_MARGIN_RATIO
        out_of_frame = any(
            p.x < m or p.x > 1 - m or p.y < m or p.y > 1 - m for p in pts_to_check
        )
        if out_of_frame:
            raw.valid = False
            raw.framing_issue = "Repositionne-toi : certains points clés sortent du cadre."
            return raw

        # --- vérification distance caméra via largeur des épaules ---
        shoulder_width_px = abs((l_shoulder.x - r_shoulder.x) * frame_w)
        shoulder_ratio = shoulder_width_px / max(frame_w, 1)
        if shoulder_ratio < config.SHOULDER_WIDTH_MIN_RATIO:
            raw.valid = False
            raw.framing_issue = "Rapproche-toi un peu de la caméra."
            return raw
        if shoulder_ratio > config.SHOULDER_WIDTH_MAX_RATIO:
            raw.valid = False
            raw.framing_issue = "Éloigne-toi un peu de la caméra."
            return raw

        # ---- coordonnées pixels ----
        l_ref_px = (l_ref.x * frame_w, l_ref.y * frame_h)
        r_ref_px = (r_ref.x * frame_w, r_ref.y * frame_h)
        l_sh_px = (l_shoulder.x * frame_w, l_shoulder.y * frame_h)
        r_sh_px = (r_shoulder.x * frame_w, r_shoulder.y * frame_h)
        nose_px = (nose.x * frame_w, nose.y * frame_h)

        shoulder_w_px = max(_dist2(l_sh_px, r_sh_px), 1e-6)
        mid_shoulder_px = ((l_sh_px[0] + r_sh_px[0]) / 2.0, (l_sh_px[1] + r_sh_px[1]) / 2.0)

        # côté le plus visible, utilisé pour les calculs "single-side"
        use_left = (l_ref.visibility + l_shoulder.visibility) >= (r_ref.visibility + r_shoulder.visibility)
        ref_px = l_ref_px if use_left else r_ref_px
        shoulder_px = l_sh_px if use_left else r_sh_px

        # ---------------------------------------------------------------
        # a) FORWARD HEAD — image (2D) + profondeur (3D) + proximité écran
        # ---------------------------------------------------------------
        dx_img = (ref_px[0] - shoulder_px[0]) / shoulder_w_px
        forward_head_img_ratio = abs(dx_img)  # 0 = tête alignée, plus grand = tête avancée

        forward_head_3d_ratio = None
        if world_landmarks is not None:
            wl = world_landmarks
            w_ref = (wl[PL.LEFT_EAR] if use_left else wl[PL.RIGHT_EAR])
            w_shoulder = wl[PL.LEFT_SHOULDER] if use_left else wl[PL.RIGHT_SHOULDER]
            w_l_sh, w_r_sh = wl[PL.LEFT_SHOULDER], wl[PL.RIGHT_SHOULDER]
            shoulder_w_3d = max(math.dist(
                (w_l_sh.x, w_l_sh.y, w_l_sh.z), (w_r_sh.x, w_r_sh.y, w_r_sh.z)), 1e-6)
            dz = w_ref.z - w_shoulder.z  # profondeur : négatif = vers la caméra
            forward_head_3d_ratio = abs(dz) / shoulder_w_3d

        # proximité progressive à l'écran : largeur des épaules / largeur
        # image. Une hausse par rapport à la baseline = rapprochement.
        proximity_ratio = shoulder_ratio

        raw.forward_head = _weighted_avg([
            (forward_head_img_ratio, config.FORWARD_HEAD_IMAGE_WEIGHT),
            (forward_head_3d_ratio, config.FORWARD_HEAD_DEPTH_WEIGHT),
            (proximity_ratio, config.FORWARD_HEAD_PROXIMITY_WEIGHT),
        ])

        # ---------------------------------------------------------------
        # b) NECK TILT — angle (milieu épaules -> nez) vs verticale
        # ---------------------------------------------------------------
        dxn = nose_px[0] - mid_shoulder_px[0]
        dyn = nose_px[1] - mid_shoulder_px[1]
        raw.neck_tilt = _angle_from_vertical_deg(dxn, dyn)

        # ---------------------------------------------------------------
        # c) TRUNK LEAN / SLOUCH — signal principal SANS hanches :
        #    ratio "longueur de cou" = distance verticale épaule ->
        #    oreille/œil, normalisée par la largeur des épaules.
        #    Se voûter / hausser les épaules fait diminuer ce ratio.
        # ---------------------------------------------------------------
        l_neck_len = (l_sh_px[1] - l_ref_px[1]) / shoulder_w_px
        r_neck_len = (r_sh_px[1] - r_ref_px[1]) / shoulder_w_px
        raw.trunk_lean = (l_neck_len + r_neck_len) / 2.0

        # ---- bonus optionnel : hanches visibles avec confiance suffisante ----
        raw.hip_lean_deg = None
        if (l_hip.visibility >= config.HIP_MIN_VISIBILITY_FOR_BONUS
                and r_hip.visibility >= config.HIP_MIN_VISIBILITY_FOR_BONUS):
            l_hip_px = (l_hip.x * frame_w, l_hip.y * frame_h)
            r_hip_px = (r_hip.x * frame_w, r_hip.y * frame_h)
            mid_hip_px = ((l_hip_px[0] + r_hip_px[0]) / 2.0, (l_hip_px[1] + r_hip_px[1]) / 2.0)
            dxt = mid_shoulder_px[0] - mid_hip_px[0]
            dyt = mid_shoulder_px[1] - mid_hip_px[1]
            trunk_lean_2d = _angle_from_vertical_deg(dxt, dyt)

            trunk_lean_3d = None
            if world_landmarks is not None:
                wl = world_landmarks
                w_l_sh, w_r_sh = wl[PL.LEFT_SHOULDER], wl[PL.RIGHT_SHOULDER]
                w_l_hip, w_r_hip = wl[PL.LEFT_HIP], wl[PL.RIGHT_HIP]
                mid_sh_3d = ((w_l_sh.x + w_r_sh.x) / 2, (w_l_sh.y + w_r_sh.y) / 2, (w_l_sh.z + w_r_sh.z) / 2)
                mid_hip_3d = ((w_l_hip.x + w_r_hip.x) / 2, (w_l_hip.y + w_r_hip.y) / 2, (w_l_hip.z + w_r_hip.z) / 2)
                dz_trunk = mid_sh_3d[2] - mid_hip_3d[2]
                dy_trunk = mid_hip_3d[1] - mid_sh_3d[1]
                trunk_lean_3d = math.degrees(math.atan2(abs(dz_trunk), max(abs(dy_trunk), 1e-6)))

            if trunk_lean_3d is not None:
                raw.hip_lean_deg = 0.6 * abs(trunk_lean_2d) + 0.4 * trunk_lean_3d
            else:
                raw.hip_lean_deg = abs(trunk_lean_2d)

        # ---------------------------------------------------------------
        # d) SHOULDER ASYMMETRY + inclinaison latérale de la tête
        # ---------------------------------------------------------------
        shoulder_diff_ratio = abs(l_sh_px[1] - r_sh_px[1]) / shoulder_w_px
        head_diff_ratio = abs(l_ref_px[1] - r_ref_px[1]) / shoulder_w_px
        raw.shoulder_asym = (
            config.SHOULDER_ASYM_SHOULDER_WEIGHT * shoulder_diff_ratio
            + config.SHOULDER_ASYM_HEAD_WEIGHT * head_diff_ratio
        )

        raw.valid = True
        raw.framing_issue = ""
        return raw


# ============================================================
# Calibration
# ============================================================

class Calibrator:
    """Collecte des échantillons pendant CALIBRATION_DURATION_S secondes
    et calcule la baseline personnelle (moyenne + tolérance)."""

    def __init__(self, duration_s=config.CALIBRATION_DURATION_S):
        self.duration_s = duration_s
        self._samples = []
        self._start_time = None
        self.done = False
        self.baseline = Baseline()

    def start(self):
        self._start_time = time.time()
        self._samples = []
        self.done = False
        self.baseline = Baseline()

    def progress(self):
        if self._start_time is None:
            return 0.0
        return min(1.0, (time.time() - self._start_time) / self.duration_s)

    def remaining_s(self):
        if self._start_time is None:
            return self.duration_s
        return max(0.0, self.duration_s - (time.time() - self._start_time))

    def feed(self, raw_metrics: RawMetrics):
        if self.done or self._start_time is None:
            return
        if raw_metrics.valid:
            self._samples.append(raw_metrics)
        if time.time() - self._start_time >= self.duration_s:
            self._finalize()

    def _finalize(self):
        if len(self._samples) < config.CALIBRATION_MIN_SAMPLES:
            # Pas assez d'échantillons valides : on relance une calibration
            # (l'appelant peut vérifier .baseline.ready == False).
            self.done = True
            self.baseline.ready = False
            return

        def mean_std(values):
            n = len(values)
            mean = sum(values) / n
            var = sum((v - mean) ** 2 for v in values) / n
            return mean, math.sqrt(var)

        fh_mean, fh_std = mean_std([s.forward_head for s in self._samples])
        nt_mean, nt_std = mean_std([s.neck_tilt for s in self._samples])
        tl_mean, tl_std = mean_std([s.trunk_lean for s in self._samples])
        sa_mean, sa_std = mean_std([s.shoulder_asym for s in self._samples])

        # ---- bonus optionnel : baseline des hanches, seulement si elles
        #      étaient visibles pendant une majorité des échantillons.
        #      Jamais requis : si absent, hip_ready reste False et le
        #      score s'appuie entièrement sur les signaux tête/épaules. ----
        hip_samples = [s.hip_lean_deg for s in self._samples if s.hip_lean_deg is not None]
        hip_ready = len(hip_samples) >= max(5, len(self._samples) // 2)
        if hip_ready:
            hip_mean, hip_std = mean_std(hip_samples)
            hip_tol = max(2.5 * hip_std, config.MIN_TOLERANCE_DEG)
        else:
            hip_mean, hip_tol = 0.0, config.MIN_TOLERANCE_DEG

        # Tolérance = 2.5x l'écart-type observé (marge naturelle de
        # mouvement), avec un plancher pour éviter une tolérance nulle.
        self.baseline = Baseline(
            forward_head=fh_mean,
            forward_head_tol=max(2.5 * fh_std, config.MIN_TOLERANCE_RATIO),
            neck_tilt=nt_mean,
            neck_tilt_tol=max(2.5 * nt_std, config.MIN_TOLERANCE_DEG),
            trunk_lean=tl_mean,
            trunk_lean_tol=max(2.5 * tl_std, config.MIN_TOLERANCE_RATIO),
            shoulder_asym=sa_mean,
            shoulder_asym_tol=max(2.5 * sa_std, config.MIN_TOLERANCE_RATIO),
            hip_lean=hip_mean,
            hip_lean_tol=hip_tol,
            hip_ready=hip_ready,
            ready=True,
        )
        self.done = True


# ============================================================
# Scoring
# ============================================================

def _submetric_score(value, baseline_value, tolerance):
    """Convertit un écart à la baseline en sous-score 0-100.

    - écart nul (= baseline)          -> 100
    - écart == tolerance               -> ~50
    - écart >= 2x tolerance            -> proche de 0
    Une posture ne peut dévier que "d'un seul côté" utile pour
    forward_head/trunk_lean/shoulder_asym (ce sont des magnitudes),
    mais pour neck_tilt un écart dans les deux sens est pénalisé.
    """
    deviation = abs(value - baseline_value) / max(tolerance, 1e-6)
    score = 100.0 * math.exp(-0.35 * deviation * deviation)
    return max(0.0, min(100.0, score))


class PostureScorer:
    def __init__(self):
        self._score_ema = None

    def reset_smoothing(self):
        self._score_ema = None

    def score(self, raw: RawMetrics, baseline: Baseline) -> ScoredMetrics:
        fh_score = _submetric_score(raw.forward_head, baseline.forward_head, baseline.forward_head_tol)
        nt_score = _submetric_score(raw.neck_tilt, baseline.neck_tilt, baseline.neck_tilt_tol)
        tl_score = _submetric_score(raw.trunk_lean, baseline.trunk_lean, baseline.trunk_lean_tol)
        sa_score = _submetric_score(raw.shoulder_asym, baseline.shoulder_asym, baseline.shoulder_asym_tol)

        # ---- bonus optionnel hanches : si elles étaient visibles pendant
        #      la calibration ET le sont sur cette frame, elles affinent
        #      le sous-score "tronc/slouch" ; sinon celui-ci repose
        #      entièrement sur le ratio cou/épaules (webcam frontale). ----
        if baseline.hip_ready and raw.hip_lean_deg is not None:
            hip_score = _submetric_score(raw.hip_lean_deg, baseline.hip_lean, baseline.hip_lean_tol)
            w = config.TRUNK_HIP_BONUS_WEIGHT
            tl_score = (1 - w) * tl_score + w * hip_score

        overall_raw = (
            config.WEIGHT_FORWARD_HEAD * fh_score
            + config.WEIGHT_TRUNK_LEAN * tl_score
            + config.WEIGHT_NECK_TILT * nt_score
            + config.WEIGHT_SHOULDER_ASYM * sa_score
        )

        if self._score_ema is None:
            self._score_ema = overall_raw
        else:
            a = config.SCORE_EMA_ALPHA
            self._score_ema = a * overall_raw + (1 - a) * self._score_ema

        return ScoredMetrics(
            overall_score=self._score_ema,
            forward_head_score=fh_score,
            trunk_lean_score=tl_score,
            neck_tilt_score=nt_score,
            shoulder_asym_score=sa_score,
            raw=raw,
        )


def classify_score(score):
    if score >= config.SCORE_GOOD_THRESHOLD:
        return "BONNE"
    elif score >= config.SCORE_WARNING_THRESHOLD:
        return "LIMITE"
    else:
        return "MAUVAISE"


class StatusTracker:
    """Applique une hystérésis temporelle : un nouveau statut doit
    persister STATUS_MIN_DURATION_S avant d'être adopté officiellement.
    Évite le clignotement bon/mauvais dû au bruit frame-à-frame."""

    def __init__(self):
        self.current_status = "BONNE"
        self._pending_status = None
        self._pending_since = None

    def update(self, instant_status):
        now = time.time()
        if instant_status == self.current_status:
            self._pending_status = None
            self._pending_since = None
            return self.current_status

        if instant_status != self._pending_status:
            self._pending_status = instant_status
            self._pending_since = now
            return self.current_status

        if now - self._pending_since >= config.STATUS_MIN_DURATION_S:
            self.current_status = instant_status
            self._pending_status = None
            self._pending_since = None

        return self.current_status
