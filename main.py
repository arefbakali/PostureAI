"""
============================================================
 PostureAI V2 — Point d'entrée
============================================================
Lance l'application complète :
  - calibration personnelle guidée
  - détection de posture multi-critères (score 0-100)
  - alertes visibles partout (overlay + notification + son)
  - icône system tray (Pause/Reprendre/Dashboard/Quitter)
  - dashboard local accessible depuis le tray ou http://127.0.0.1:5057

Lancement :
    python main.py
============================================================
"""

import sys


def _check_dependencies():
    missing = []
    for module_name, pip_name in [
        ("cv2", "opencv-python"),
        ("mediapipe", "mediapipe"),
        ("numpy", "numpy"),
    ]:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(pip_name)
    return missing


def main():
    missing = _check_dependencies()
    if missing:
        print("[X] Dépendances manquantes :", ", ".join(missing))
        print("    -> pip install -r requirements.txt")
        sys.exit(1)

    from posture_ai.app_controller import AppController

    app = AppController()
    try:
        app.start()
    except KeyboardInterrupt:
        print("\n[!] Interruption clavier — arrêt de PostureAI.")


if __name__ == "__main__":
    main()
