"""
Répertoires de données utilisateur pour Phoenix.

Les bases Kuzu et modèles sont stockés en dehors du répertoire d'installation
pour permettre les mises à jour sans perdre les apprentissages.
"""

import os
import platform
from pathlib import Path


def get_data_dir() -> str:
    """Retourne le répertoire de données utilisateur, créé si nécessaire.

    Ordre de priorité:
    1. Variable d'environnement PHOENIX_DATA_DIR
    2. Répertoire standard de la plateforme
    """
    env = os.environ.get("PHOENIX_DATA_DIR")
    if env:
        p = Path(env)
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    data_dir = base / "phoenix"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir)


def get_kuzu_path(name: str = "phoenix") -> str:
    """Retourne le chemin complet d'une base Kuzu dans le répertoire de données."""
    return str(Path(get_data_dir()) / f"{name}.kuzu")
