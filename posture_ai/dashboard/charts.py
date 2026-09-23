"""
============================================================
 PostureAI — Graphiques du dashboard (générés côté serveur)
============================================================
POURQUOI CE MODULE EXISTE :

La première version du dashboard utilisait Chart.js chargé depuis un
CDN public (cdnjs.cloudflare.com). Sur certains réseaux (pare-feu
d'entreprise, proxy restrictif, poste sans connexion sortante), ce
CDN est bloqué et les graphiques ne s'affichent jamais — c'est
exactement ce qui a été constaté.

Solution : les courbes sont maintenant générées EN PNG, côté serveur,
avec matplotlib — la même bibliothèque et le même style visuel que
l'ancien rapport de fin de session (nuage de points coloré par statut
+ anneau de répartition). Le navigateur n'a plus qu'à afficher une
image (<img src="/api/today_evolution.png">), sans dépendre d'aucune
ressource externe : tout fonctionne hors ligne.

Les deux fonctions publiques renvoient des bytes PNG prêts à être
envoyés directement dans une réponse Flask.
============================================================
"""

import io

import matplotlib
matplotlib.use("Agg")  # pas d'affichage interactif, juste du rendu fichier
import matplotlib.pyplot as plt

from .. import config

# Palette identique à celle utilisée dans le HUD caméra et l'ancien
# rapport PNG, pour une cohérence visuelle totale de l'application.
COLOR_GOOD = "#4ade80"
COLOR_WARNING = "#fbbf24"
COLOR_BAD = "#f87171"
PANEL_BG = "#15161c"
TEXT_COLOR = "#eef0f4"
MUTED_COLOR = "#9398a6"
GRID_COLOR = "#262832"

_STATUS_COLORS = {"BONNE": COLOR_GOOD, "LIMITE": COLOR_WARNING, "MAUVAISE": COLOR_BAD}


def _empty_figure(figsize, message):
    """Image de substitution propre quand il n'y a pas encore de données,
    plutôt qu'un graphique vide ou une erreur côté client."""
    fig = plt.figure(figsize=figsize, facecolor=PANEL_BG, dpi=140)
    ax = fig.add_subplot(111)
    ax.set_facecolor(PANEL_BG)
    ax.axis("off")
    ax.text(0.5, 0.5, message, ha="center", va="center", color=MUTED_COLOR,
             fontsize=11, wrap=True, transform=ax.transAxes)
    return fig


def _fig_to_png_bytes(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), dpi=140,
                bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def render_today_evolution_png(points):
    """points : liste de dicts {t (minutes), score (0-100), status}.
    Nuage de points du score au fil de la journée, coloré par statut,
    avec les seuils BONNE/LIMITE tracés en pointillés (même principe
    que l'ancien rapport CVA, appliqué ici au score 0-100)."""
    if not points:
        fig = _empty_figure(
            (7.4, 3.2),
            "Aucune mesure aujourd'hui pour l'instant.\nLance une session PostureAI pour voir la courbe ici.",
        )
        return _fig_to_png_bytes(fig)

    times = [p["t"] for p in points]
    scores = [p["score"] for p in points]
    point_colors = [_STATUS_COLORS.get(p["status"], MUTED_COLOR) for p in points]

    fig = plt.figure(figsize=(7.4, 3.2), facecolor=PANEL_BG, dpi=140)
    ax = fig.add_subplot(111)
    ax.set_facecolor(PANEL_BG)

    ax.scatter(times, scores, c=point_colors, s=7, linewidths=0)
    ax.axhline(config.SCORE_GOOD_THRESHOLD, color=COLOR_GOOD, linestyle="--", linewidth=1, alpha=0.55)
    ax.axhline(config.SCORE_WARNING_THRESHOLD, color=COLOR_WARNING, linestyle="--", linewidth=1, alpha=0.55)

    ax.set_ylim(0, 100)
    ax.set_xlabel("Minutes depuis le début", color=MUTED_COLOR, fontsize=9)
    ax.set_ylabel("Score", color=MUTED_COLOR, fontsize=9)
    ax.tick_params(colors=MUTED_COLOR, labelsize=8)
    ax.grid(True, color=GRID_COLOR, linewidth=0.6)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    fig.tight_layout()
    return _fig_to_png_bytes(fig)


def render_today_donut_png(breakdown):
    """breakdown : dict {good_pct, warning_pct, bad_pct} ou None.
    Anneau de répartition Bonne/Limite/Mauvaise de la journée, avec le
    % de bonne posture affiché au centre."""
    if not breakdown:
        fig = _empty_figure((4.4, 3.2), "Pas encore de\ndonnées aujourd'hui")
        return _fig_to_png_bytes(fig)

    labels = ["Bonne", "Limite", "Mauvaise"]
    values = [breakdown["good_pct"], breakdown["warning_pct"], breakdown["bad_pct"]]
    colors_pie = [COLOR_GOOD, COLOR_WARNING, COLOR_BAD]

    # évite un donut vide/invalide si les 3 valeurs sont à 0
    if sum(values) <= 0:
        values = [1, 0, 0]

    fig = plt.figure(figsize=(4.4, 3.2), facecolor=PANEL_BG, dpi=140)
    ax = fig.add_subplot(111)
    ax.set_facecolor(PANEL_BG)

    wedges, _ = ax.pie(
        values, colors=colors_pie, startangle=90,
        wedgeprops=dict(width=0.38, edgecolor=PANEL_BG, linewidth=2),
    )
    ax.legend(
        wedges, labels, loc="lower center", bbox_to_anchor=(0.5, -0.18),
        facecolor=PANEL_BG, labelcolor=TEXT_COLOR, ncol=3, frameon=False, fontsize=8,
    )
    ax.text(0, 0.06, f"{breakdown['good_pct']:.0f}%", ha="center", va="center",
             color=TEXT_COLOR, fontsize=17, fontweight="bold")
    ax.text(0, -0.14, "bonne posture", ha="center", va="center",
             color=MUTED_COLOR, fontsize=8.5)

    fig.tight_layout()
    return _fig_to_png_bytes(fig)
