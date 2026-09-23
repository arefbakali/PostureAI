"""
============================================================
 PostureAI V2 — Statistiques de session en direct
============================================================
Agrège, pendant une session caméra active :
  - le temps passé par statut (BONNE / LIMITE / MAUVAISE)
  - le score moyen
  - le nombre d'alertes envoyées
  - le meilleur streak (durée continue en bonne posture)
  - le % de frames où chaque sous-métrique était "mauvaise"
    (Forward Head / Slouch / Shoulder imbalance) -> alimente les
    conseils personnalisés de fin de session
  - la logique "Smart Break" (proposer une pause après plusieurs
    mauvaises postures rapprochées)
  - le badge de streak "30 min de bonne posture"
  - des messages de MOTIVATION (pas seulement des alertes) déclenchés
    à intervalles de streak continu en bonne posture, pour renforcer
    positivement plutôt que de ne parler que des problèmes
============================================================
"""

import random
import time
from collections import deque

from . import config

# Seuils de streak continu (secondes) déclenchant un message positif,
# distincts du badge "30 minutes" qui reste un jalon plus solennel.
MOTIVATION_STREAK_THRESHOLDS_S = [3 * 60, 10 * 60, 20 * 60]

MOTIVATION_MESSAGES = [
    "Belle posture, continue comme ça !",
    "Ton dos te dit merci.",
    "Excellent maintien depuis un moment !",
    "Tu tiens le rythme, bravo.",
    "Posture impeccable — garde le cap.",
    "Bien joué, ta colonne vertébrale apprécie.",
]


class SessionStats:
    def __init__(self):
        self.start_time = time.time()
        self._last_tick = self.start_time
        self.status_seconds = {"BONNE": 0.0, "LIMITE": 0.0, "MAUVAISE": 0.0}
        self.score_sum = 0.0
        self.score_count = 0
        self.alerts_count = 0

        self._current_streak_start = self.start_time
        self.best_streak_s = 0.0
        self._streak_badge_awarded = False
        self._motivation_thresholds_hit = set()

        # % de frames "mauvaises" par sous-métrique (pour les conseils)
        self.submetric_bad_frames = {"forward_head": 0, "trunk_lean": 0, "shoulder_asym": 0}
        self.total_valid_frames = 0

        # Smart Break : historique des transitions vers "MAUVAISE"
        self._bad_events = deque()
        self._last_break_suggestion = 0.0

        # Règle 20-20-20
        self._last_20_20_20 = self.start_time

    # ------------------------------------------------------------
    def update(self, status, score, scored_metrics):
        now = time.time()
        dt = now - self._last_tick
        self._last_tick = now
        self.status_seconds[status] += dt

        self.score_sum += score
        self.score_count += 1

        self.total_valid_frames += 1
        if scored_metrics.forward_head_score < config.SCORE_WARNING_THRESHOLD:
            self.submetric_bad_frames["forward_head"] += 1
        if scored_metrics.trunk_lean_score < config.SCORE_WARNING_THRESHOLD:
            self.submetric_bad_frames["trunk_lean"] += 1
        if scored_metrics.shoulder_asym_score < config.SCORE_WARNING_THRESHOLD:
            self.submetric_bad_frames["shoulder_asym"] += 1

        # --- streak de bonne posture ---
        if status == "BONNE":
            streak_duration = now - self._current_streak_start
            self.best_streak_s = max(self.best_streak_s, streak_duration)
        else:
            self._current_streak_start = now
            self._motivation_thresholds_hit.clear()  # nouvelle série -> nouveaux paliers

    def current_streak_s(self):
        if self.status_seconds is None:
            return 0.0
        return time.time() - self._current_streak_start

    def just_reached_streak_badge(self):
        """Retourne True une seule fois lorsque le streak de 30 min est atteint."""
        if not self._streak_badge_awarded and self.current_streak_s() >= config.STREAK_BADGE_S:
            self._streak_badge_awarded = True
            return True
        return False

    def pop_motivation_message(self):
        """Retourne un message de motivation (str) la première fois que le
        streak continu franchit l'un des paliers définis, sinon None.
        Contrairement aux alertes (qui signalent un problème), ces
        messages renforcent positivement une bonne posture soutenue."""
        streak = self.current_streak_s()
        for threshold in MOTIVATION_STREAK_THRESHOLDS_S:
            if streak >= threshold and threshold not in self._motivation_thresholds_hit:
                self._motivation_thresholds_hit.add(threshold)
                return random.choice(MOTIVATION_MESSAGES)
        return None

    def register_alert(self):
        self.alerts_count += 1

    def register_bad_transition(self):
        """À appeler quand le statut devient MAUVAISE (nouvelle occurrence)."""
        now = time.time()
        self._bad_events.append(now)
        while self._bad_events and now - self._bad_events[0] > config.SMART_BREAK_WINDOW_S:
            self._bad_events.popleft()

    def should_suggest_break(self):
        now = time.time()
        if now - self._last_break_suggestion < config.SMART_BREAK_COOLDOWN_S:
            return False
        if len(self._bad_events) >= config.SMART_BREAK_BAD_EVENTS:
            self._last_break_suggestion = now
            self._bad_events.clear()
            return True
        return False

    def should_trigger_20_20_20(self):
        if not config.RULE_20_20_20_ENABLED:
            return False
        now = time.time()
        if now - self._last_20_20_20 >= config.RULE_20_20_20_INTERVAL_S:
            self._last_20_20_20 = now
            return True
        return False

    # ------------------------------------------------------------
    def total_time(self):
        return sum(self.status_seconds.values()) or 1e-6

    def good_ratio(self):
        return self.status_seconds["BONNE"] / self.total_time()

    def avg_score(self):
        return self.score_sum / self.score_count if self.score_count else 0.0

    def top_issue(self):
        """Retourne le nom de la sous-métrique la plus souvent problématique,
        utilisé pour générer un conseil personnalisé de fin de session."""
        if self.total_valid_frames == 0:
            return None
        pct = {k: v / self.total_valid_frames for k, v in self.submetric_bad_frames.items()}
        worst = max(pct, key=pct.get)
        if pct[worst] < 0.15:
            return None
        return worst

    def to_db_stats(self):
        total = self.total_time()
        return {
            "duration_s": total,
            "avg_score": self.avg_score(),
            "pct_good": 100 * self.status_seconds["BONNE"] / total,
            "pct_warning": 100 * self.status_seconds["LIMITE"] / total,
            "pct_bad": 100 * self.status_seconds["MAUVAISE"] / total,
            "alerts_count": self.alerts_count,
            "best_streak_s": self.best_streak_s,
            "forward_head_bad_pct": 100 * self.submetric_bad_frames["forward_head"] / max(self.total_valid_frames, 1),
            "slouch_bad_pct": 100 * self.submetric_bad_frames["trunk_lean"] / max(self.total_valid_frames, 1),
            "shoulder_imbalance_bad_pct": 100 * self.submetric_bad_frames["shoulder_asym"] / max(self.total_valid_frames, 1),
        }


SUBMETRIC_LABELS = {
    "forward_head": "tête projetée vers l'avant (Forward Head / tech neck)",
    "trunk_lean": "buste penché / affaissé (Slouch)",
    "shoulder_asym": "asymétrie des épaules (Shoulder imbalance)",
}

SUBMETRIC_TIPS = {
    "forward_head": [
        "Recule ton écran ou remonte-le à hauteur des yeux pour limiter la tête projetée vers l'avant.",
        "Essaie l'exercice du menton rentré (chin tuck) 10x toutes les heures.",
    ],
    "trunk_lean": [
        "Cale le bas du dos contre le dossier de la chaise, bassin légèrement en avant.",
        "Vérifie la hauteur de ta chaise : les hanches doivent être légèrement au-dessus des genoux.",
    ],
    "shoulder_asym": [
        "Évite de tenir ton téléphone ou ta souris d'un seul côté pendant de longues périodes.",
        "Fais une pause étirement des trapèzes toutes les heures.",
    ],
}


def build_session_summary(stats: SessionStats):
    """Construit un résumé automatique de fin de session avec 2-3 conseils."""
    tips = []
    issue = stats.top_issue()
    if issue:
        tips.extend(SUBMETRIC_TIPS[issue][:2])
    if stats.good_ratio() < 0.5:
        tips.append("Pense à programmer des rappels de pause toutes les 30-45 minutes.")
    if not tips:
        tips.append("Belle session ! Continue sur cette lancée.")
    return {
        "duration_s": stats.total_time(),
        "avg_score": stats.avg_score(),
        "good_ratio": stats.good_ratio(),
        "alerts_count": stats.alerts_count,
        "best_streak_s": stats.best_streak_s,
        "top_issue_label": SUBMETRIC_LABELS.get(issue) if issue else None,
        "tips": tips[:3],
    }
