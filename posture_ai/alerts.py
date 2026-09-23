"""
============================================================
 PostureAI V2 — Alertes visibles partout
============================================================
Deux mécanismes, actifs même si la fenêtre webcam est réduite :

1. AlertOverlay : une petite fenêtre Tkinter "toujours au-dessus"
   (topmost), sans bordure, positionnée en haut à droite de l'écran,
   qui affiche "⚠️ Redresse-toi — ta posture se dégrade" et
   disparaît automatiquement dès que la posture redevient correcte
   (ou après ALERT_OVERLAY_LIFETIME_S secondes).

2. send_windows_notification : notification native Windows (toast)
   via la librairie 'plyer'. Se dégrade silencieusement (no-op) si
   plyer / le sous-système de notifications n'est pas disponible
   (ex: hors Windows, ou pywin32 manquant) — l'application continue
   de fonctionner normalement dans tous les cas.

Tkinter tourne dans son propre thread dédié (voir app_controller.py)
afin de ne jamais bloquer la boucle caméra ni le tray icon.
============================================================
"""

import queue
import sys
import threading
import time

from . import config

_IS_WINDOWS = sys.platform.startswith("win")

try:
    import tkinter as tk
    _TKINTER_AVAILABLE = True
except ImportError:
    _TKINTER_AVAILABLE = False

try:
    from plyer import notification as _plyer_notification
    _NOTIFICATIONS_AVAILABLE = True
except Exception:
    _NOTIFICATIONS_AVAILABLE = False


_last_notification_ts = 0.0
_notification_lock = threading.Lock()


def send_windows_notification(title, message, cooldown_s=config.ALERT_REPEAT_EVERY_S):
    """Envoie une notification système, avec un cooldown anti-spam.
    Ne fait jamais planter l'appelant : toute erreur est avalée."""
    global _last_notification_ts
    if not _NOTIFICATIONS_AVAILABLE:
        return
    with _notification_lock:
        now = time.time()
        if now - _last_notification_ts < cooldown_s:
            return
        _last_notification_ts = now

    def _send():
        try:
            _plyer_notification.notify(
                title=title,
                message=message,
                app_name="PostureAI",
                timeout=6,
            )
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


class AlertOverlay:
    """Petite fenêtre flottante toujours au premier plan.

    Fonctionne via une file de commandes thread-safe : le thread
    caméra appelle .show(message) / .hide() depuis n'importe quel
    thread, et cette classe traite les commandes dans SON PROPRE
    thread Tkinter (obligatoire : Tkinter doit être piloté par un
    seul thread).
    """

    def __init__(self):
        self._cmd_queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._visible = False
        self._auto_hide_at = None

    def start(self):
        if not _TKINTER_AVAILABLE:
            print("[!] 'tkinter' non disponible : pas de bulle d'alerte à l'écran "
                  "(les notifications système et le son restent actifs).")
            return
        self._thread.start()

    def show(self, message):
        if not _TKINTER_AVAILABLE:
            return
        self._cmd_queue.put(("show", message))

    def hide(self):
        if not _TKINTER_AVAILABLE:
            return
        self._cmd_queue.put(("hide", None))

    def stop(self):
        if not _TKINTER_AVAILABLE:
            return
        self._cmd_queue.put(("stop", None))

    # ---- interne : tourne exclusivement dans le thread Tkinter ----
    def _run(self):
        root = tk.Tk()
        root.withdraw()  # pas de fenêtre principale visible
        root.title("PostureAI - Alerte")

        popup = tk.Toplevel(root)
        popup.withdraw()
        popup.overrideredirect(True)          # pas de barre de titre
        popup.attributes("-topmost", True)    # toujours au-dessus
        try:
            popup.attributes("-alpha", 0.95)
        except tk.TclError:
            pass

        frame = tk.Frame(popup, bg="#1b1024", padx=18, pady=14,
                          highlightbackground="#ff5c8a", highlightthickness=2)
        frame.pack()
        label = tk.Label(
            frame, text="", font=("Segoe UI", 12, "bold"),
            bg="#1b1024", fg="#ffe08a", justify="left", wraplength=320,
        )
        label.pack()

        screen_w = popup.winfo_screenwidth()

        def position_popup():
            popup.update_idletasks()
            w = popup.winfo_width()
            x = screen_w - w - 24
            y = 40
            popup.geometry(f"+{x}+{y}")

        def poll():
            try:
                while True:
                    cmd, payload = self._cmd_queue.get_nowait()
                    if cmd == "show":
                        label.config(text=payload)
                        popup.deiconify()
                        position_popup()
                        self._visible = True
                        self._auto_hide_at = time.time() + config.ALERT_OVERLAY_LIFETIME_S
                    elif cmd == "hide":
                        popup.withdraw()
                        self._visible = False
                        self._auto_hide_at = None
                    elif cmd == "stop":
                        root.quit()
                        return
            except queue.Empty:
                pass

            if self._visible and self._auto_hide_at and time.time() >= self._auto_hide_at:
                popup.withdraw()
                self._visible = False
                self._auto_hide_at = None

            root.after(150, poll)

        root.after(150, poll)
        root.mainloop()
        try:
            root.destroy()
        except Exception:
            pass
