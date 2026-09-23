"""
============================================================
 PostureAI V2 — Persistance SQLite
============================================================
Stocke uniquement des métriques numériques (jamais d'image/vidéo) :
  - sessions : une ligne par session d'utilisation
  - samples  : échantillons agrégés (~1 par seconde) pour tracer
               l'évolution du score dans le temps et repérer les
               moments de la journée où la posture se dégrade.

Toutes les opérations sont protégées par un verrou car la caméra
(thread dédié) et le dashboard Flask (thread serveur) accèdent tous
les deux à la base.
============================================================
"""

import sqlite3
import threading
from datetime import datetime, timedelta

from . import config

_lock = threading.Lock()


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts REAL NOT NULL,
    end_ts REAL,
    date TEXT NOT NULL,
    duration_s REAL DEFAULT 0,
    avg_score REAL DEFAULT 0,
    pct_good REAL DEFAULT 0,
    pct_warning REAL DEFAULT 0,
    pct_bad REAL DEFAULT 0,
    alerts_count INTEGER DEFAULT 0,
    best_streak_s REAL DEFAULT 0,
    forward_head_bad_pct REAL DEFAULT 0,
    slouch_bad_pct REAL DEFAULT 0,
    shoulder_imbalance_bad_pct REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    score REAL NOT NULL,
    status TEXT NOT NULL,
    forward_head_score REAL,
    trunk_lean_score REAL,
    neck_tilt_score REAL,
    shoulder_asym_score REAL,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_samples_session ON samples(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date);
"""


def get_connection():
    conn = sqlite3.connect(config.DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock:
        conn = get_connection()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


def start_session():
    now = datetime.now()
    with _lock:
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO sessions (start_ts, date) VALUES (?, ?)",
                (now.timestamp(), now.strftime("%Y-%m-%d")),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def add_sample(session_id, ts, score, status, sub_scores):
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO samples
                   (session_id, ts, score, status, forward_head_score,
                    trunk_lean_score, neck_tilt_score, shoulder_asym_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, ts, score, status,
                 sub_scores.get("forward_head"), sub_scores.get("trunk_lean"),
                 sub_scores.get("neck_tilt"), sub_scores.get("shoulder_asym")),
            )
            conn.commit()
        finally:
            conn.close()


def update_session_live(session_id, stats):
    """Met à jour la ligne de session EN COURS (sans la clôturer) avec les
    statistiques cumulées jusqu'à présent. Appelée périodiquement pendant
    la session (voir camera_worker.py) afin que le dashboard reflète la
    situation en direct, et pas seulement les sessions déjà terminées.
    Même format de `stats` que end_session()."""
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                """UPDATE sessions SET duration_s=?, avg_score=?,
                   pct_good=?, pct_warning=?, pct_bad=?, alerts_count=?,
                   best_streak_s=?, forward_head_bad_pct=?, slouch_bad_pct=?,
                   shoulder_imbalance_bad_pct=? WHERE id=?""",
                (
                    stats.get("duration_s", 0), stats.get("avg_score", 0),
                    stats.get("pct_good", 0), stats.get("pct_warning", 0),
                    stats.get("pct_bad", 0), stats.get("alerts_count", 0),
                    stats.get("best_streak_s", 0), stats.get("forward_head_bad_pct", 0),
                    stats.get("slouch_bad_pct", 0), stats.get("shoulder_imbalance_bad_pct", 0),
                    session_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def end_session(session_id, stats):
    """stats: dict avec duration_s, avg_score, pct_good, pct_warning, pct_bad,
    alerts_count, best_streak_s, forward_head_bad_pct, slouch_bad_pct,
    shoulder_imbalance_bad_pct."""
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                """UPDATE sessions SET end_ts=?, duration_s=?, avg_score=?,
                   pct_good=?, pct_warning=?, pct_bad=?, alerts_count=?,
                   best_streak_s=?, forward_head_bad_pct=?, slouch_bad_pct=?,
                   shoulder_imbalance_bad_pct=? WHERE id=?""",
                (
                    datetime.now().timestamp(), stats.get("duration_s", 0),
                    stats.get("avg_score", 0), stats.get("pct_good", 0),
                    stats.get("pct_warning", 0), stats.get("pct_bad", 0),
                    stats.get("alerts_count", 0), stats.get("best_streak_s", 0),
                    stats.get("forward_head_bad_pct", 0), stats.get("slouch_bad_pct", 0),
                    stats.get("shoulder_imbalance_bad_pct", 0), session_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_sessions(days=30):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with _lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE date >= ? ORDER BY start_ts ASC", (since,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_today_sessions():
    return get_sessions_for_date(datetime.now().strftime("%Y-%m-%d"))


def get_sessions_for_date(date_str):
    """Toutes les sessions d'une date précise (format 'YYYY-MM-DD')."""
    with _lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE date = ? ORDER BY start_ts ASC", (date_str,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_samples_for_session(session_id):
    with _lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM samples WHERE session_id=? ORDER BY ts ASC", (session_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_hourly_bad_distribution(days=14):
    """Retourne, pour chaque heure de la journée (0-23), la moyenne du
    score sur les N derniers jours -> permet d'identifier les moments
    où la posture se dégrade le plus."""
    since = (datetime.now() - timedelta(days=days)).timestamp()
    with _lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT s.ts as ts, s.score as score FROM samples s
                   JOIN sessions ses ON ses.id = s.session_id
                   WHERE s.ts >= ?""",
                (since,),
            ).fetchall()
        finally:
            conn.close()

    buckets = {h: [] for h in range(24)}
    for r in rows:
        hour = datetime.fromtimestamp(r["ts"]).hour
        buckets[hour].append(r["score"])

    result = []
    for h in range(24):
        vals = buckets[h]
        avg = sum(vals) / len(vals) if vals else None
        result.append({"hour": h, "avg_score": avg, "n": len(vals)})
    return result


def get_streak_days():
    """Nombre de jours consécutifs (jusqu'à aujourd'hui inclus) avec
    au moins une session enregistrée."""
    with _lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT DISTINCT date FROM sessions ORDER BY date DESC"
            ).fetchall()
        finally:
            conn.close()

    dates = {r["date"] for r in rows}
    if not dates:
        return 0

    streak = 0
    day = datetime.now().date()
    while day.strftime("%Y-%m-%d") in dates:
        streak += 1
        day -= timedelta(days=1)
    return streak
