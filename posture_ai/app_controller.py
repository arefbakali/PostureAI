"""
============================================================
 PostureAI V2 — Contrôleur d'application
============================================================
Fait le lien entre les différents threads de l'application :

  - Thread principal  : boucle caméra OpenCV (CameraWorker)
  - Thread dédié      : overlay d'alerte Tkinter (AlertOverlay)
  - Thread dédié      : icône system tray (TrayController, via pystray)
  - Thread dédié      : serveur Flask du dashboard (à la demande)

Cette classe est volontairement simple (pas de framework d'IoC) :
chaque composant reçoit une référence vers l'AppController et
l'appelle pour les actions transverses (pause, ouverture du
dashboard, arrêt complet, etc.).
============================================================
"""

import threading
import webbrowser

from . import config, database
from .alerts import AlertOverlay
from .camera_worker import CameraWorker
from .tray_icon import TrayController


class AppController:
    def __init__(self):
        database.init_db()
        self.alert_overlay = AlertOverlay()
        self.camera_worker = CameraWorker(self)
        self.tray = TrayController(self)
        self._dashboard_thread = None
        self._dashboard_ready = threading.Event()
        self._paused = False

    # ------------------------------------------------------------
    def start(self):
        self.alert_overlay.start()
        self.tray.start()
        # Le dashboard est démarré dès le lancement de l'application
        # (et non plus seulement au clic sur l'icône system tray) afin
        # qu'il soit accessible même si le tray n'est pas disponible sur
        # la machine (ex: 'pystray' manquant) ou si l'utilisateur ne
        # pense pas à cliquer dessus.
        self._ensure_dashboard_running()
        # La boucle caméra tourne dans le thread principal (obligatoire
        # pour un rendu OpenCV fiable sous Windows).
        self.camera_worker.run()

    # ---- callbacks utilisés par CameraWorker ----
    def show_alert_overlay(self, message):
        self.alert_overlay.show(message)

    def hide_alert_overlay(self):
        self.alert_overlay.hide()

    def on_camera_stopped(self, summary):
        self.alert_overlay.stop()
        if self.tray:
            self.tray.stop()

    # ---- callbacks utilisés par TrayController et CameraWorker ----
    def is_paused(self):
        return self._paused

    def on_toggle_pause(self):
        self._paused = not self._paused
        self.camera_worker.set_paused(self._paused)
        return self._paused

    def on_open_dashboard(self):
        self._ensure_dashboard_running()
        # Laisse le temps au serveur Flask de démarrer si ce n'était pas
        # déjà le cas (normalement déjà lancé depuis .start()).
        self._dashboard_ready.wait(timeout=3.0)
        webbrowser.open(f"http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}/")

    def on_quit(self):
        self.camera_worker.request_stop()

    # ------------------------------------------------------------
    def _ensure_dashboard_running(self):
        if self._dashboard_thread and self._dashboard_thread.is_alive():
            return

        def _run():
            try:
                from .dashboard.server import create_app
                from werkzeug.serving import make_server
                app = create_app()
                # make_server() lie le port immédiatement (lève OSError
                # tout de suite si occupé), contrairement à app.run() qui
                # ne le fait qu'après avoir démarré sa propre boucle.
                server = make_server(config.DASHBOARD_HOST, config.DASHBOARD_PORT, app)
                self._dashboard_ready.set()
                print(f"[PostureAI] Dashboard disponible sur "
                      f"http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}/")
                server.serve_forever()
            except (OSError, SystemExit) as e:
                # Port déjà utilisé (ex: une autre instance de PostureAI
                # tourne déjà) : ne pas planter l'application pour autant.
                # NOTE : dans ce cas précis, le dashboard de l'AUTRE
                # instance reste accessible sur le même port.
                print(f"[!] Impossible de démarrer le dashboard sur le port "
                      f"{config.DASHBOARD_PORT} (probablement déjà utilisé).")
                print(f"    -> Une instance tourne peut-être déjà : essaie "
                      f"d'ouvrir http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}/ directement.")
                self._dashboard_ready.set()  # débloque on_open_dashboard() malgré l'échec
            except Exception as e:
                print(f"[!] Erreur inattendue au démarrage du dashboard (ignorée) : {e}")
                self._dashboard_ready.set()

        self._dashboard_thread = threading.Thread(target=_run, daemon=True)
        self._dashboard_thread.start()
