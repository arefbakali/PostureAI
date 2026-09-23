"""
============================================================
 PostureAI V2 — Icône system tray
============================================================
Permet à PostureAI de tourner en arrière-plan : Pause / Reprendre /
Ouvrir le dashboard / Quitter, accessibles même si la fenêtre webcam
est fermée ou réduite.

Utilise 'pystray' (icône générée à la volée avec Pillow, aucune
image externe requise).
============================================================
"""

import threading

from PIL import Image, ImageDraw

try:
    import pystray
    _TRAY_AVAILABLE = True
except Exception:
    _TRAY_AVAILABLE = False


def _make_icon_image(color=(90, 200, 250)):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=(20, 20, 26, 255))
    # petite silhouette "posture" stylisée
    draw.ellipse((26, 12, 38, 24), fill=color)          # tête
    draw.line((32, 24, 32, 44), fill=color, width=5)    # colonne
    draw.line((32, 30, 20, 38), fill=color, width=5)    # bras
    draw.line((32, 30, 44, 38), fill=color, width=5)    # bras
    draw.line((32, 44, 22, 58), fill=color, width=5)    # jambe
    draw.line((32, 44, 42, 58), fill=color, width=5)    # jambe
    return img


class TrayController:
    """Encapsule l'icône system tray. app_controller doit fournir :
        on_toggle_pause() -> bool (nouvel état paused)
        on_open_dashboard()
        on_quit()
        is_paused() -> bool
    """

    def __init__(self, app_controller):
        self.app = app_controller
        self._icon = None
        self._thread = None

    def available(self):
        return _TRAY_AVAILABLE

    def start(self):
        if not _TRAY_AVAILABLE:
            print("[!] 'pystray' non disponible : pas d'icône system tray (l'appli continue de fonctionner).")
            return

        def _toggle_pause(icon, item):
            self.app.on_toggle_pause()
            self._refresh_menu()

        def _open_dashboard(icon, item):
            self.app.on_open_dashboard()

        def _quit(icon, item):
            self.app.on_quit()
            icon.stop()

        def _pause_label(item):
            return "Reprendre" if self.app.is_paused() else "Mettre en pause"

        menu = pystray.Menu(
            pystray.MenuItem("PostureAI V2", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(_pause_label, _toggle_pause),
            pystray.MenuItem("Ouvrir le dashboard", _open_dashboard),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", _quit),
        )

        self._icon = pystray.Icon("PostureAI", _make_icon_image(), "PostureAI V2", menu)
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def _refresh_menu(self):
        if self._icon:
            try:
                self._icon.update_menu()
            except Exception:
                pass

    def notify_status_color(self, status):
        """Change discrètement l'icône selon le statut de posture."""
        if not _TRAY_AVAILABLE or self._icon is None:
            return
        color_map = {
            "BONNE": (100, 220, 90),
            "LIMITE": (255, 165, 0),
            "MAUVAISE": (235, 60, 60),
        }
        try:
            self._icon.icon = _make_icon_image(color_map.get(status, (90, 200, 250)))
        except Exception:
            pass

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
