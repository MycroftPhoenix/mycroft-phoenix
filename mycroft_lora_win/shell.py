"""Intégration shell Windows (successeur local de l'intégration Cortana).

- Lancement d'applications / ouverture de paramètres : sans dépendance.
- Notifications (toast), contrôle média : via l'API WinRT
  (``Windows.UI.Notifications`` / ``Windows.Media``) -> nécessite ``pywinrt``.
  À activer quand le paquet ``pywinrt`` sera installé (Windows 11 / 24H2+).
"""

import logging
import subprocess

_LOGGER = logging.getLogger(__name__)


def launch_app(target: str) -> bool:
    """Lance un exécutable, une URL ou un document. Retourne le succès."""
    try:
        subprocess.Popen(target, shell=True)
        return True
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("launch_app(%r) échoué: %s", target, exc)
        return False


def open_settings(page: str = "ms-settings:") -> bool:
    """Ouvre une page des Paramètres Windows (ex. 'ms-settings:speech')."""
    return launch_app(page)


def notify(title: str, message: str) -> bool:
    """Affiche une notification toast Windows.

    Nécessite ``pywinrt`` (API WinRT Windows.UI.Notifications). À brancher
    quand le paquet ``pywinrt`` sera installé (Windows 11 / 24H2+).
    """
    _LOGGER.warning(
        "notify() nécessite pywinrt (WinRT Windows.UI.Notifications) ; "
        "à implémenter quand le paquet sera ajouté."
    )
    return False


class WindowsShell:
    """Sélection granulaire des capacités Windows (via config ``windows``).

    Chaque élément est activable individuellement ; le core lit la section
    ``windows`` de phoenix_config.json et instancie ce shell. Aucune dépendance
    dure : les capacités non disponibles se contentent de renvoyer ``False``.
    """

    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.notifications = bool(cfg.get("notifications", True))
        self.app_launch = bool(cfg.get("app_launch", True))
        self.media = bool(cfg.get("media", False))  # WinRT, différé

    def launch_app(self, target: str) -> bool:
        if not self.app_launch:
            return False
        return launch_app(target)

    def open_settings(self, page: str = "ms-settings:") -> bool:
        if not self.app_launch:
            return False
        return open_settings(page)

    def notify(self, title: str, message: str) -> bool:
        if not self.notifications:
            return False
        return notify(title, message)

    def status(self) -> dict:
        return {
            "notifications": self.notifications,
            "app_launch": self.app_launch,
            "media": self.media,
        }
