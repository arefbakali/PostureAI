"""
============================================================
 PostureAI V2 — Son d'alerte
============================================================
Remplace l'ancienne dépendance 'simpleaudio' (source de plantages/
problèmes d'installation sur certaines configs Windows) par le
module natif 'winsound' fourni avec Python sur Windows : aucune
dépendance externe, aucun fichier audio requis.

Sur les autres OS (utile pour dev/test hors Windows), on retombe
sur un bip silencieux (no-op) sans faire planter l'application.
============================================================
"""

import sys
import threading

_IS_WINDOWS = sys.platform.startswith("win")

if _IS_WINDOWS:
    try:
        import winsound
        _WINSOUND_AVAILABLE = True
    except ImportError:
        _WINSOUND_AVAILABLE = False
else:
    _WINSOUND_AVAILABLE = False


def play_alert_sound():
    """Joue un son d'alerte natif Windows, de façon non bloquante.

    Utilise l'alias système 'SystemExclamation' (le même son que les
    notifications Windows), ce qui donne un rendu cohérent avec l'OS
    plutôt qu'un bip synthétique.
    """
    if not _WINSOUND_AVAILABLE:
        return

    def _play():
        try:
            winsound.PlaySound(
                "SystemExclamation",
                winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except Exception:
            # Ne jamais faire planter l'application pour un problème de son.
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass

    threading.Thread(target=_play, daemon=True).start()


def play_success_chime():
    """Petit son discret joué quand un badge/streak est débloqué."""
    if not _WINSOUND_AVAILABLE:
        return

    def _play():
        try:
            winsound.PlaySound(
                "SystemAsterisk",
                winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except Exception:
            pass

    threading.Thread(target=_play, daemon=True).start()
