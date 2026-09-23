"""
============================================================
 PostureAI — Dashboard local (Flask)
============================================================
Petit serveur Flask, exécuté uniquement en local (127.0.0.1), qui
sert une interface moderne et 100% centrée sur AUJOURD'HUI :
  - score du jour, % bonne posture, alertes, streak de jours
  - évolution du score de la journée (nuage de points coloré par
    statut, comme le rapport de fin de session), moment par moment
  - répartition Bonne/Limite/Mauvaise de la journée (anneau)
  - objectif quotidien, conseils personnalisés basés sur AUJOURD'HUI
  - meilleure session du jour

Pas d'historique 7/30 jours ni d'agrégat hebdomadaire : le dashboard
reste volontairement focalisé sur la session/journée en cours, à la
demande explicite de l'utilisateur.

Aucune vidéo/image n'est servie ni stockée : uniquement des
métriques numériques agrégées, lues directement dans SQLite
(mêmes tables `sessions`/`samples` alimentées par camera_worker.py).
============================================================
"""

from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, Response

from .. import database
from ..session_stats import SUBMETRIC_LABELS, SUBMETRIC_TIPS
from . import charts


def _fetch_today_points_and_breakdown():
    """Récupère les échantillons bruts d'aujourd'hui (table `samples`,
    toutes sessions confondues) et calcule les points du graphique +
    la répartition Bonne/Limite/Mauvaise. Utilisé à la fois par l'API
    JSON et par les images PNG générées par charts.py."""
    today_sessions = database.get_today_sessions()
    samples = []
    for s in today_sessions:
        samples.extend(database.get_samples_for_session(s["id"]))
    samples.sort(key=lambda r: r["ts"])

    if not samples:
        return [], None

    start_ts = samples[0]["ts"]
    # Sous-échantillonnage si la journée compte beaucoup de points,
    # pour garder un graphique lisible et rapide à générer (le calcul
    # de répartition, lui, utilise TOUS les échantillons).
    max_points = 600
    step = max(1, len(samples) // max_points)
    sampled = samples[::step]
    points = [
        {"t": round((r["ts"] - start_ts) / 60.0, 2), "score": round(r["score"], 1), "status": r["status"]}
        for r in sampled
    ]

    counts = {"BONNE": 0, "LIMITE": 0, "MAUVAISE": 0}
    for r in samples:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total = len(samples)
    breakdown = {
        "good_pct": round(100 * counts["BONNE"] / total, 1),
        "warning_pct": round(100 * counts["LIMITE"] / total, 1),
        "bad_pct": round(100 * counts["MAUVAISE"] / total, 1),
    }

    return points, breakdown


_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/summary")
    def api_summary():
        today_sessions = database.get_today_sessions()

        today_score = _avg([s["avg_score"] for s in today_sessions if s["avg_score"] is not None])
        today_good_pct = _avg([s["pct_good"] for s in today_sessions if s["pct_good"] is not None])
        today_duration = sum(s["duration_s"] or 0 for s in today_sessions)
        today_alerts = sum(s["alerts_count"] or 0 for s in today_sessions)

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday_sessions = database.get_sessions_for_date(yesterday)
        yesterday_score = _avg([s["avg_score"] for s in yesterday_sessions if s["avg_score"] is not None])

        best_session = max(today_sessions, key=lambda s: s["avg_score"] or 0, default=None)

        streak_days = database.get_streak_days()

        # Conseil personnalisé basé sur LA JOURNÉE EN COURS uniquement
        issue_totals = {"forward_head": 0.0, "trunk_lean": 0.0, "shoulder_asym": 0.0}
        n = 0
        for s in today_sessions:
            issue_totals["forward_head"] += s.get("forward_head_bad_pct") or 0
            issue_totals["trunk_lean"] += s.get("slouch_bad_pct") or 0
            issue_totals["shoulder_asym"] += s.get("shoulder_imbalance_bad_pct") or 0
            n += 1
        advice = None
        if n:
            worst_key = max(issue_totals, key=issue_totals.get)
            if issue_totals[worst_key] / n > 15:
                advice = {
                    "issue": SUBMETRIC_LABELS[worst_key],
                    "tips": SUBMETRIC_TIPS[worst_key],
                }

        daily_goal_minutes = 120  # objectif indicatif : 2h de bonne posture / jour
        good_minutes_today = sum(
            (s["duration_s"] or 0) * (s["pct_good"] or 0) / 100 for s in today_sessions
        ) / 60.0

        live_session = any(s["end_ts"] is None for s in today_sessions)

        return jsonify({
            "today_score": round(today_score, 1) if today_score is not None else None,
            "today_good_pct": round(today_good_pct, 1) if today_good_pct is not None else None,
            "today_duration_min": round(today_duration / 60.0, 1),
            "today_alerts": today_alerts,
            "yesterday_score": round(yesterday_score, 1) if yesterday_score is not None else None,
            "best_session": {
                "avg_score": round(best_session["avg_score"], 1),
                "duration_min": round((best_session["duration_s"] or 0) / 60.0, 1),
            } if best_session else None,
            "streak_days": streak_days,
            "advice": advice,
            "daily_goal_minutes": daily_goal_minutes,
            "good_minutes_today": round(good_minutes_today, 1),
            "live_session": live_session,
        })

    @app.route("/api/today_timeline")
    def api_today_timeline():
        """Version JSON des mêmes données que les PNG ci-dessous
        (conservée pour usage/débogage externe)."""
        points, breakdown = _fetch_today_points_and_breakdown()
        return jsonify({"points": points, "breakdown": breakdown})

    @app.route("/api/today_evolution.png")
    def api_today_evolution_png():
        """Nuage de points du score d'aujourd'hui, généré côté serveur
        avec matplotlib (voir charts.py) — fonctionne sans connexion
        internet, contrairement à un graphique JS chargé depuis un CDN."""
        points, _ = _fetch_today_points_and_breakdown()
        png_bytes = charts.render_today_evolution_png(points)
        return Response(png_bytes, mimetype="image/png", headers=_NO_CACHE_HEADERS)

    @app.route("/api/today_donut.png")
    def api_today_donut_png():
        """Anneau de répartition Bonne/Limite/Mauvaise du jour, en PNG."""
        _, breakdown = _fetch_today_points_and_breakdown()
        png_bytes = charts.render_today_donut_png(breakdown)
        return Response(png_bytes, mimetype="image/png", headers=_NO_CACHE_HEADERS)

    return app


def _avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None
