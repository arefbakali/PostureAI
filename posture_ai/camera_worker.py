"""
============================================================
 PostureAI V2 — Boucle caméra + interface OpenCV moderne
============================================================
Pipeline par frame :
    Webcam --> MediaPipe Pose (landmarks 2D + "world" 3D)
           --> PostureExtractor (4 métriques, sans hanches requises)
           --> Calibrator (phase de calibration) OU PostureScorer
           --> StatusTracker (hystérésis temporelle)
           --> SessionStats (agrégation + Smart Break + streak + motivation)
           --> UI dark/moderne (score animé, mini-courbe en direct,
               mini-barres, badges, liste des problèmes détectés)
           --> Alertes (overlay toujours au-dessus + notification
               Windows + son natif) si mauvaise posture persistante,
               ET messages de motivation lors des bonnes séries
           --> écriture périodique en base SQLite (+ mise à jour EN
               DIRECT de la session pour le dashboard)

Raccourcis clavier :
    q / ESC -> quitter (génère le résumé de session)
    c       -> relancer une calibration
    p       -> pause / reprendre
    F11     -> basculer le mode plein écran (touche 'f' en secours,
               le code clavier de F11 variant selon l'OS/le pilote)
    m       -> basculer le mode minimal (HUD réduit pour démo/plein écran)
    d       -> ouvrir le dashboard local dans le navigateur

RENDU DE TEXTE : `cv2.putText` ne supporte pas l'UTF-8 (les accents et
emoji s'affichaient comme "??" — voir posture_ai/ui_render.py pour le
détail). Tout le texte de ce module passe donc par un `TextLayer` PIL,
et les emoji sont remplacés par de petites icônes vectorielles.

Gestion des erreurs : toute exception levée pendant le traitement
d'une frame est capturée et journalisée sans interrompre la session
(une frame corrompue ne doit jamais faire planter l'application).
La caméra et les fenêtres sont toujours proprement libérées, même
en cas d'erreur inattendue, grâce à un bloc try/finally.
"""

import time
from collections import deque

import cv2

from . import config, database, sound_utils
from .posture_engine import (
    PostureExtractor, Calibrator, PostureScorer, StatusTracker, classify_score,
)
from .session_stats import SessionStats, build_session_summary
from .ui_render import (
    TextLayer, draw_sparkline,
    icon_warning, icon_coffee, icon_eye, icon_badge,
    SIZE_TITLE, SIZE_META, SIZE_SCORE, SIZE_STATUS, SIZE_SECTION,
    SIZE_LABEL, SIZE_SMALL, SIZE_TOAST,
)

try:
    import mediapipe as mp
    _MEDIAPIPE_AVAILABLE = True
except ImportError:
    _MEDIAPIPE_AVAILABLE = False


# ============================================================
# Aides de dessin (formes uniquement — le texte passe par TextLayer)
# ============================================================

def draw_rounded_panel(img, x, y, w, h, color=config.COLOR_PANEL, alpha=0.6, radius=16):
    overlay = img.copy()
    x2, y2 = x + w, y + h
    cv2.rectangle(overlay, (x + radius, y), (x2 - radius, y2), color, -1)
    cv2.rectangle(overlay, (x, y + radius), (x2, y2 - radius), color, -1)
    for cx, cy in [(x + radius, y + radius), (x2 - radius, y + radius),
                   (x + radius, y2 - radius), (x2 - radius, y2 - radius)]:
        cv2.circle(overlay, (cx, cy), radius, color, -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)


def draw_bar(img, x, y, w, h, ratio, color, bg=(60, 60, 66)):
    ratio = max(0.0, min(1.0, ratio))
    cv2.rectangle(img, (x, y), (x + w, y + h), bg, -1)
    cv2.rectangle(img, (x, y), (x + int(w * ratio), y + h), color, -1)
    cv2.rectangle(img, (x, y), (x + w, y + h), (210, 210, 210), 1)


def draw_score_ring(img, cx, cy, radius, score, color):
    """Anneau de progression animé représentant le score 0-100."""
    cv2.circle(img, (cx, cy), radius, (55, 55, 60), 8)
    angle = int(360 * max(0, min(100, score)) / 100)
    cv2.ellipse(img, (cx, cy), (radius, radius), -90, 0, angle, color, 8, cv2.LINE_AA)


def flash_border(img, color, thickness=14):
    h, w = img.shape[:2]
    cv2.rectangle(img, (0, 0), (w, h), color, thickness)


def status_color(status):
    return {"BONNE": config.COLOR_GOOD, "LIMITE": config.COLOR_WARNING,
            "MAUVAISE": config.COLOR_BAD}.get(status, config.COLOR_TEXT)


# ============================================================
# Worker principal
# ============================================================

class CameraWorker:
    def __init__(self, app_controller):
        self.app = app_controller
        self._stop_requested = False
        self._paused = False
        self._fullscreen = False
        self._minimal_hud = False
        self._text = TextLayer()
        # Historique récent du score (pour la mini-courbe "tendance en
        # direct"), échantillonné à ~1 valeur/seconde -> ~2 min affichées.
        self._score_history = deque(maxlen=120)

    def request_stop(self):
        self._stop_requested = True

    def set_paused(self, paused):
        self._paused = paused

    def _toggle_fullscreen(self, window_name):
        self._fullscreen = not self._fullscreen
        prop = cv2.WINDOW_FULLSCREEN if self._fullscreen else cv2.WINDOW_NORMAL
        try:
            cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, prop)
        except Exception:
            pass

    # ------------------------------------------------------------
    def run(self):
        if not _MEDIAPIPE_AVAILABLE:
            print("[X] 'mediapipe' n'est pas installé. Lance : pip install -r requirements.txt")
            return

        try:
            mp_pose = mp.solutions.pose
        except AttributeError:
            print("[X] Cette version de 'mediapipe' n'expose pas l'API historique "
                  "'mediapipe.solutions.pose' utilisée par PostureAI.")
            print("    -> Installe la version testée : pip install mediapipe==0.10.14")
            return

        pose = mp_pose.Pose(model_complexity=1, min_detection_confidence=0.6,
                             min_tracking_confidence=0.6)
        extractor = PostureExtractor(mp_pose)

        cap = cv2.VideoCapture(config.CAMERA_SOURCE)
        if config.REQUESTED_WIDTH:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.REQUESTED_WIDTH)
        if config.REQUESTED_HEIGHT:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.REQUESTED_HEIGHT)

        if not cap.isOpened():
            print(f"[X] Impossible d'ouvrir la source vidéo : {config.CAMERA_SOURCE}")
            print("    -> Vérifie l'index de webcam ou l'URL du téléphone (voir GUIDE.md).")
            pose.close()
            return

        calibrator = Calibrator()
        calibrator.start()
        scorer = PostureScorer()
        tracker = StatusTracker()
        stats = SessionStats()

        session_id = database.start_session()

        window_name = "PostureAI - Correcteur de posture"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        print("=" * 60)
        print(" PostureAI démarré")
        print(" Calibration : reste ~8s en posture correcte, bien en face de la caméra.")
        print(" Raccourcis : q/ESC=quitter  c=recalibrer  p=pause  F11/f=plein écran  m=mode minimal  d=dashboard")
        print(" Mode vie privée : aucune image/vidéo n'est jamais enregistrée.")
        print("=" * 60)

        # État mutable de la boucle, regroupé dans un dict pour rester
        # simple à faire persister frame après frame.
        state = {
            "last_db_write": 0.0,
            "last_live_update": 0.0,
            "bad_streak_start": None,
            "last_alert_time": 0.0,
            "last_status_for_transition": "BONNE",
            "toast_message": None,
            "toast_until": 0.0,
            "toast_color": config.COLOR_ACCENT,
            "toast2_message": None,
            "toast2_until": 0.0,
            "toast2_color": config.COLOR_ACCENT2,
        }

        try:
            while not self._stop_requested:
                try:
                    stop_now = self._handle_frame(
                        cap, pose, mp_pose, extractor, calibrator, scorer, tracker,
                        stats, session_id, window_name, state,
                    )
                except Exception as e:
                    # Une frame corrompue / une erreur ponctuelle ne doit
                    # jamais faire planter toute la session.
                    print(f"[!] Erreur pendant le traitement d'une frame (ignorée) : {e}")
                    stop_now = False
                if stop_now:
                    break
        finally:
            cap.release()
            cv2.destroyAllWindows()
            pose.close()
            self.app.hide_alert_overlay()

            db_stats = stats.to_db_stats()
            database.end_session(session_id, db_stats)
            summary = build_session_summary(stats)
            self._print_summary(summary)
            self.app.on_camera_stopped(summary)

    # ------------------------------------------------------------
    def _handle_frame(self, cap, pose, mp_pose, extractor, calibrator, scorer, tracker,
                       stats, session_id, window_name, state):
        """Traite une frame et renvoie True si la boucle principale doit s'arrêter."""
        ok, frame = cap.read()
        if not ok:
            print("[X] Flux vidéo interrompu.")
            return True

        if config.MIRROR_PREVIEW:
            frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        self._text.reset()

        if self._paused:
            draw_rounded_panel(frame, 0, 0, w, h, color=(10, 10, 12), alpha=0.55, radius=0)
            self._text.add("PostureAI en pause", (w // 2, h // 2), size=SIZE_TITLE,
                            color=config.COLOR_ACCENT, bold=True, anchor="mm")
            self._text.add("Reprendre depuis l'icone system tray ou la touche P",
                            (w // 2, h // 2 + 30), size=SIZE_SMALL,
                            color=config.COLOR_MUTED, anchor="mm")
            frame = self._text.flush(frame)
            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:  # 27 = ESC
                return True
            if key == ord("p"):
                self._paused = False
            return False

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = pose.process(rgb)

        status = None
        score = None
        scored = None
        framing_issue = ""

        if results.pose_landmarks:
            raw = extractor.extract(
                results.pose_landmarks.landmark,
                results.pose_world_landmarks.landmark if results.pose_world_landmarks else None,
                w, h,
            )

            if not calibrator.done:
                if raw.valid:
                    calibrator.feed(raw)
                self._draw_calibration_ui(frame, calibrator, raw)
            elif raw.valid:
                scored = scorer.score(raw, calibrator.baseline)
                score = scored.overall_score
                instant_status = classify_score(score)
                status = tracker.update(instant_status)

                if status == "MAUVAISE" and state["last_status_for_transition"] != "MAUVAISE":
                    stats.register_bad_transition()
                state["last_status_for_transition"] = status

                stats.update(status, score, scored)
                self._draw_pose_skeleton(frame, results, mp_pose, status_color(status))
                now = time.time()

                if state["last_db_write"] == 0.0 or now - state["last_db_write"] >= 1.0:
                    database.add_sample(session_id, now, score, status, {
                        "forward_head": scored.forward_head_score,
                        "trunk_lean": scored.trunk_lean_score,
                        "neck_tilt": scored.neck_tilt_score,
                        "shoulder_asym": scored.shoulder_asym_score,
                    })
                    state["last_db_write"] = now
                    self._score_history.append(score)

                # Met à jour la ligne "sessions" EN DIRECT (sans la clore)
                # afin que le dashboard reflète la session en cours, et pas
                # seulement les sessions déjà terminées.
                if state["last_live_update"] == 0.0 or now - state["last_live_update"] >= 3.0:
                    database.update_session_live(session_id, stats.to_db_stats())
                    state["last_live_update"] = now

                # ---------------- Gestion des alertes ----------------
                if status == "MAUVAISE":
                    if state["bad_streak_start"] is None:
                        state["bad_streak_start"] = now
                    elif (now - state["bad_streak_start"] >= config.ALERT_GRACE_PERIOD_S
                          and now - state["last_alert_time"] >= config.ALERT_REPEAT_EVERY_S):
                        self._trigger_alert()
                        stats.register_alert()
                        state["last_alert_time"] = now
                        flash_border(frame, config.COLOR_BAD, thickness=14)
                else:
                    state["bad_streak_start"] = None
                    self.app.hide_alert_overlay()

                if self.app.tray:
                    self.app.tray.notify_status_color(status)

                # ---------------- Smart Break ----------------
                if stats.should_suggest_break():
                    state["toast_message"] = "smart_break"
                    state["toast_until"] = now + 8.0
                    self.app.show_alert_overlay("Pense à faire une courte pause (Smart Break)")
                    from .alerts import send_windows_notification
                    send_windows_notification(
                        "PostureAI — Smart Break",
                        "Plusieurs mauvaises postures détectées. Une petite pause te ferait du bien !",
                        cooldown_s=0,
                    )

                # ---------------- Règle 20-20-20 ----------------
                if stats.should_trigger_20_20_20():
                    state["toast_message"] = "rule_20_20_20"
                    state["toast_until"] = now + 8.0
                    from .alerts import send_windows_notification
                    send_windows_notification(
                        "PostureAI — Pause visuelle",
                        "Règle 20-20-20 : regarde au loin 20 secondes pour reposer tes yeux.",
                        cooldown_s=0,
                    )

                # ---------------- Badge de streak (30 min) ----------------
                if stats.just_reached_streak_badge():
                    state["toast_message"] = "badge"
                    state["toast_until"] = now + 6.0
                    sound_utils.play_success_chime()

                # ---------------- Message de motivation ----------------
                motivation = stats.pop_motivation_message()
                if motivation:
                    state["toast2_message"] = motivation
                    state["toast2_until"] = now + 5.0
            else:
                framing_issue = raw.framing_issue
        else:
            framing_issue = "Aucune personne détectée : place-toi face à la caméra."

        self._draw_hud(frame, status, score, scored, stats, calibrator, framing_issue)

        now = time.time()
        if state["toast_message"] and now < state["toast_until"]:
            self._draw_system_toast(frame, state["toast_message"], y_offset=0)
        if state["toast2_message"] and now < state["toast2_until"]:
            self._draw_motivation_toast(frame, state["toast2_message"], y_offset=48)

        frame = self._text.flush(frame)
        cv2.imshow(window_name, frame)
        key_ex = cv2.waitKeyEx(1)
        key = key_ex & 0xFF if key_ex != -1 else -1
        if key == ord("q") or key == 27:  # 27 = ESC
            return True
        elif key == ord("c"):
            calibrator.start()
            scorer.reset_smoothing()
            self._score_history.clear()
        elif key == ord("p"):
            self._paused = True
        elif key == ord("m"):
            self._minimal_hud = not self._minimal_hud
        elif key == ord("f") or key_ex in (7340032,):  # 'f' ou F11 (code Windows)
            self._toggle_fullscreen(window_name)
        elif key == ord("d"):
            self.app.on_open_dashboard()

        return False

    # ------------------------------------------------------------
    def _trigger_alert(self):
        self.app.show_alert_overlay("Redresse-toi : ta posture se dégrade")
        sound_utils.play_alert_sound()
        from .alerts import send_windows_notification
        send_windows_notification(
            "PostureAI", "⚠️ Redresse-toi — ta posture se dégrade depuis un moment.",
            cooldown_s=0,
        )

    # ------------------------------------------------------------
    def _draw_pose_skeleton(self, frame, results, mp_pose, color):
        PL = mp_pose.PoseLandmark
        h, w = frame.shape[:2]
        lm = results.pose_landmarks.landmark

        def px(landmark):
            return int(landmark.x * w), int(landmark.y * h)

        pairs = [
            (PL.LEFT_SHOULDER, PL.RIGHT_SHOULDER, (140, 140, 140)),
            (PL.LEFT_HIP, PL.RIGHT_HIP, (140, 140, 140)),
            (PL.LEFT_SHOULDER, PL.LEFT_HIP, color),
            (PL.RIGHT_SHOULDER, PL.RIGHT_HIP, color),
            (PL.LEFT_SHOULDER, PL.LEFT_EAR, color),
            (PL.RIGHT_SHOULDER, PL.RIGHT_EAR, color),
        ]
        for a, b, c in pairs:
            if lm[a].visibility > 0.4 and lm[b].visibility > 0.4:
                cv2.line(frame, px(lm[a]), px(lm[b]), c, 2, cv2.LINE_AA)

        for landmark_id in [PL.NOSE, PL.LEFT_EAR, PL.RIGHT_EAR, PL.LEFT_SHOULDER,
                             PL.RIGHT_SHOULDER, PL.LEFT_HIP, PL.RIGHT_HIP]:
            if lm[landmark_id].visibility > 0.4:
                cv2.circle(frame, px(lm[landmark_id]), 5, color, -1, cv2.LINE_AA)

    # ------------------------------------------------------------
    def _draw_calibration_ui(self, frame, calibrator, raw):
        h, w = frame.shape[:2]
        progress = calibrator.progress()
        draw_rounded_panel(frame, w // 2 - 220, h // 2 - 90, 440, 150, alpha=0.75)
        self._text.add("Calibration en cours", (w // 2, h // 2 - 60), size=SIZE_TITLE,
                        color=config.COLOR_ACCENT, bold=True, anchor="mm")
        if raw.valid:
            self._text.add("Reste immobile, en bonne posture, face à la caméra",
                            (w // 2, h // 2 - 28), size=SIZE_LABEL,
                            color=config.COLOR_TEXT, anchor="mm")
        else:
            self._text.add(raw.framing_issue or "Place-toi bien dans le cadre",
                            (w // 2, h // 2 - 28), size=SIZE_LABEL,
                            color=config.COLOR_WARNING, anchor="mm")
        draw_bar(frame, w // 2 - 190, h // 2 + 4, 380, 20, progress, config.COLOR_ACCENT)
        remaining = calibrator.remaining_s()
        self._text.add(f"{remaining:0.1f} s restantes", (w // 2, h // 2 + 44),
                        size=SIZE_LABEL, color=config.COLOR_TEXT, anchor="mm")

    # ------------------------------------------------------------
    def _draw_hud(self, frame, status, score, scored, stats, calibrator, framing_issue):
        h, w = frame.shape[:2]

        # bandeau haut : logo + timer (mention "100% local" retirée du
        # HUD caméra pour un rendu plus sobre — l'info reste disponible
        # dans le GUIDE et sur le dashboard si besoin)
        draw_rounded_panel(frame, 16, 16, 200, 58)
        self._text.add("PostureAI", (30, 26), size=SIZE_TITLE,
                        color=config.COLOR_ACCENT, bold=True)
        elapsed = stats.total_time()
        mm, ss = divmod(int(elapsed), 60)
        self._text.add(f"Session {mm:02d}:{ss:02d}", (30, 54), size=SIZE_META,
                        color=config.COLOR_MUTED)

        if not calibrator.done:
            return  # rien d'autre pendant la calibration

        if framing_issue:
            draw_rounded_panel(frame, 16, 88, 430, 54, alpha=0.75)
            icon_warning(frame, 30, 98, 30, config.COLOR_WARNING)
            self._text.add(framing_issue, (72, 106), size=SIZE_LABEL, color=config.COLOR_WARNING)
            return

        if status is None:
            return

        color = status_color(status)

        if self._minimal_hud:
            # ---- Mode minimal : juste un badge score + statut, discret ----
            draw_rounded_panel(frame, w // 2 - 110, 16, 220, 46, alpha=0.6)
            self._text.add(f"{int(round(score))}/100", (w // 2 - 20, 39), size=SIZE_STATUS,
                            color=color, bold=True, anchor="mm")
            self._text.add(status, (w // 2 + 55, 39), size=SIZE_STATUS,
                            color=color, bold=True, anchor="mm")
            return

        # anneau de score, coin haut-droit
        draw_rounded_panel(frame, w - 150, 16, 134, 150, alpha=0.55)
        draw_score_ring(frame, w - 83, 78, 46, score, color)
        self._text.add(str(int(round(score))), (w - 83, 75), size=SIZE_SCORE,
                        color=color, bold=True, anchor="mm")
        self._text.add(status, (w - 83, 143), size=SIZE_STATUS, color=color,
                        bold=True, anchor="mm")

        # mini-courbe "tendance en direct", sous le bandeau du haut
        spark_w, spark_h = 250, 46
        draw_rounded_panel(frame, 16, 82, spark_w + 24, spark_h + 34, alpha=0.55)
        self._text.add("Tendance (2 min)", (28, 90), size=SIZE_SMALL, color=config.COLOR_MUTED)
        draw_sparkline(frame, 28, 108, spark_w, spark_h, list(self._score_history), color)

        # mini-barres sous-métriques + problèmes détectés, bas-gauche
        # (positions calculées avec un curseur unique pour garantir que
        # le panneau est toujours assez haut pour tout son contenu)
        panel_w = 280
        issues = self._detected_issues(scored)
        header_h = 40
        row_h = 22
        rows = [
            ("Forward Head", scored.forward_head_score),
            ("Trunk / Slouch", scored.trunk_lean_score),
            ("Neck tilt", scored.neck_tilt_score),
            ("Shoulder balance", scored.shoulder_asym_score),
        ]
        content_h = header_h + len(rows) * row_h
        if issues:
            content_h += 26 + len(issues) * 18
        panel_h = content_h + 18  # marge de sécurité basse
        bottom_margin = 44  # laisse de la place pour la ligne de raccourcis
        top = h - panel_h - bottom_margin

        draw_rounded_panel(frame, 16, top, panel_w, panel_h)
        self._text.add("Détail posture", (28, top + 12), size=SIZE_SECTION,
                        color=config.COLOR_TEXT, bold=True)

        cursor_y = top + header_h
        for label, val in rows:
            self._text.add(label, (28, cursor_y), size=SIZE_LABEL, color=config.COLOR_MUTED)
            bar_color = (config.COLOR_GOOD if val >= config.SCORE_GOOD_THRESHOLD
                         else config.COLOR_WARNING if val >= config.SCORE_WARNING_THRESHOLD
                         else config.COLOR_BAD)
            draw_bar(frame, 160, cursor_y - 2, 110, 12, val / 100.0, bar_color)
            cursor_y += row_h

        if issues:
            cursor_y += 12
            icon_warning(frame, 26, cursor_y - 2, 16, config.COLOR_WARNING)
            self._text.add("Problèmes détectés", (48, cursor_y), size=SIZE_LABEL,
                            color=config.COLOR_WARNING, bold=True)
            cursor_y += 22
            for label in issues:
                self._text.add(f"- {label}", (28, cursor_y), size=SIZE_SMALL,
                                color=config.COLOR_MUTED)
                cursor_y += 18

        # barre "bonne posture" globale + streak, bas-droite
        draw_rounded_panel(frame, w - 300, h - 90, 284, 74)
        ratio = stats.good_ratio()
        self._text.add(f"Bonne posture : {ratio*100:4.0f}%", (w - 288, h - 78),
                        size=SIZE_LABEL, color=config.COLOR_TEXT)
        draw_bar(frame, w - 288, h - 58, 260, 12, ratio, config.COLOR_GOOD)
        streak_min = stats.current_streak_s() / 60.0
        self._text.add(f"Streak actuel : {streak_min:0.1f} min", (w - 288, h - 40),
                        size=SIZE_SMALL, color=config.COLOR_MUTED)

        self._text.add(
            "Q/ESC quitter  |  C recalibrer  |  P pause  |  F11 plein écran  |  M minimal  |  D dashboard",
            (16, h - 20), size=SIZE_SMALL, color=config.COLOR_MUTED)

    # ------------------------------------------------------------
    def _detected_issues(self, scored):
        """Liste courte (max 3) des problèmes actifs, en texte COURT
        pour tenir dans le panneau du HUD (les libellés détaillés de
        SUBMETRIC_LABELS sont réservés au dashboard, où il y a plus de
        place)."""
        short_labels = {
            "forward_head": "tête projetée vers l'avant",
            "trunk_lean": "buste penché / affaissé",
            "neck_tilt": "tête/cou inclinés",
            "shoulder_asym": "épaules asymétriques",
        }
        candidates = [
            ("forward_head", scored.forward_head_score),
            ("trunk_lean", scored.trunk_lean_score),
            ("neck_tilt", scored.neck_tilt_score),
            ("shoulder_asym", scored.shoulder_asym_score),
        ]
        issues = [short_labels[key] for key, val in candidates if val < config.SCORE_WARNING_THRESHOLD]
        return issues[:3]

    # ------------------------------------------------------------
    def _draw_system_toast(self, frame, kind, y_offset=0):
        """Toasts liés à une alerte/rappel système (icône + texte)."""
        h, w = frame.shape[:2]
        y = h // 2 - 130 + y_offset
        icon_fn, icon_color, text = {
            "smart_break": (icon_coffee, config.COLOR_ACCENT2,
                             "Smart Break : pense à faire une pause de 2-3 min"),
            "rule_20_20_20": (icon_eye, config.COLOR_ACCENT2,
                               "Règle 20-20-20 : regarde au loin 20 secondes"),
            "badge": (icon_badge, config.COLOR_ACCENT,
                      "Badge débloqué : 30 minutes de bonne posture !"),
        }.get(kind, (None, config.COLOR_ACCENT, ""))

        draw_rounded_panel(frame, w // 2 - 260, y, 520, 44, color=(30, 20, 30), alpha=0.88)
        if icon_fn:
            icon_fn(frame, w // 2 - 240, y + 8, 28, icon_color)
        self._text.add(text, (w // 2 - 195, y + 22), size=SIZE_TOAST,
                        color=icon_color, bold=True, anchor="lm")

    def _draw_motivation_toast(self, frame, message, y_offset=0):
        """Toast positif/motivant (distinct des alertes), fond vert doux."""
        h, w = frame.shape[:2]
        y = h // 2 - 130 + y_offset
        draw_rounded_panel(frame, w // 2 - 220, y, 440, 44, color=(18, 32, 20), alpha=0.88)
        self._text.add(message, (w // 2, y + 22), size=SIZE_TOAST,
                        color=config.COLOR_GOOD, bold=True, anchor="mm")

    # ------------------------------------------------------------
    def _print_summary(self, summary):
        print("\n" + "=" * 60)
        print(" Résumé de la session")
        print("=" * 60)
        mm, ss = divmod(int(summary["duration_s"]), 60)
        print(f"  Durée              : {mm:02d}:{ss:02d}")
        print(f"  Score moyen        : {summary['avg_score']:.0f}/100")
        print(f"  % bonne posture    : {summary['good_ratio']*100:.0f}%")
        print(f"  Alertes envoyées   : {summary['alerts_count']}")
        print(f"  Meilleur streak    : {summary['best_streak_s']/60:.1f} min")
        if summary["top_issue_label"]:
            print(f"  Point à travailler : {summary['top_issue_label']}")
        print("  Conseils :")
        for tip in summary["tips"]:
            print(f"    - {tip}")
        print("=" * 60)
