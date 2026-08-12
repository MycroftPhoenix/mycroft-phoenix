"""
Chargement/sauvegarde de phoenix_config.json + sanitisation des secrets.

Le serveur admin lit et écrit la même config que le pipeline (single source
of truth). Les valeurs sensibles (api_key, password, token) ne sont jamais
renvoyées par l'API — seulement les noms de variables d'environnement.
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Champs dont la VALEUR est un secret à ne jamais renvoyer
_SECRET_FIELDS = {"api_key", "password", "access_token", "refresh_token"}

# Champs autorisés à exister dans /api/config/ai (vus par le panneau)
_AI_KEYS = {"enabled", "priority", "timeout_s", "providers", "description"}


class AdminConfig:
    """Lit/écrit phoenix_config.json, avec défauts sûrs."""

    DEFAULTS = {
        "web": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 8181,
            "username": "mycroft",
            "password": "CHANGE_ME",
        },
        "ai": {
            "enabled": False,
            "priority": 6,
            "timeout_s": 10,
            "providers": [{"id": "local", "type": "local"}],
        },
    }

    def __init__(self, base_dir: str, config_file: str = "phoenix_config.json"):
        self.base_dir = Path(base_dir)
        self.config_path = self.base_dir / config_file
        self.config: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.config_path.exists():
            try:
                with open(self.config_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Config illisible (%s), défauts utilisés: %s", self.config_path, e)
        return {}

    def save(self) -> bool:
        """Écrit la config de façon atomique (fichier temporaire + rename)."""
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.base_dir), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.config_path)
            return True
        except Exception as e:
            logger.error("Sauvegarde config impossible: %s", e)
            return False

    # ── Accès sections ────────────────────────────────────────────────────

    def get(self, section: str) -> Dict[str, Any]:
        value = self.config.get(section, {})
        if not isinstance(value, dict):
            return {}
        return value

    def set(self, section: str, value: Dict[str, Any]) -> None:
        self.config[section] = value

    # ── Sanitisation ──────────────────────────────────────────────────────

    @classmethod
    def sanitize(cls, data: Any) -> Any:
        """Remplace les valeurs secrètes par '***' (récursif)."""
        if isinstance(data, dict):
            return {
                k: ("***" if k in _SECRET_FIELDS and isinstance(v, str) and v else cls.sanitize(v))
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [cls.sanitize(v) for v in data]
        return data

    @classmethod
    def sanitize_ai(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Section ai sans secrets (api_key → '***', api_key_env conservé)."""
        ai = config.get("ai", {})
        out = {k: v for k, v in ai.items() if k in _AI_KEYS}
        providers = []
        for p in ai.get("providers", []):
            if not isinstance(p, dict):
                continue
            clean = {k: v for k, v in p.items() if k != "api_key"}
            if "api_key" in p:
                clean["api_key"] = "***" if p.get("api_key") else ""
            providers.append(clean)
        out["providers"] = providers
        return out
