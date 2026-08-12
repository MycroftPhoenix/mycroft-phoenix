"""Classes de base locales — miroir de l'interface TTS/STT de Mycroft-Phoenix.

Volontairement SANS dépendance sur le core : le paquet ``mycroft_lora_win``
se branche sur Phoenix via le bus standardisé (registre TTS/STT), exactement
comme les autres moteurs. Connexion = structuralement compatible, pas un import.
"""

from typing import Iterable, Optional


class TTSBackend:
    """Protocole commun d'un moteur de synthèse vocale (compatible speech.py)."""

    type = "base"
    description = ""

    def __init__(self, cfg: dict):
        self.config = cfg
        self.id = str(cfg.get("id") or self.type)
        self.sample_rate = int(cfg.get("sample_rate") or 22050)
        self.language = str(cfg.get("language") or "fr")

    def health(self) -> bool:
        raise NotImplementedError

    def synthesize(self, text: str) -> Iterable[bytes]:
        """Émet des paquets de PCM brut (int16 mono) — streaming."""
        raise NotImplementedError

    def status(self) -> dict:
        try:
            ok = self.health()
        except Exception:
            ok = False
        return {"id": self.id, "type": self.type, "healthy": ok,
                "sample_rate": self.sample_rate, "language": self.language}


class STTBackend:
    """Protocole commun d'un moteur de reconnaissance vocale (compatible speech.py)."""

    type = "base"
    description = ""

    def __init__(self, cfg: dict):
        self.config = cfg
        self.id = str(cfg.get("id") or self.type)
        self.language = str(cfg.get("language") or "fr")
        self.default_sample_rate = int(cfg.get("sample_rate") or 16000)

    def health(self) -> bool:
        raise NotImplementedError

    def transcribe(self, audio: bytes, sample_rate: int = 16000) -> Optional[str]:
        raise NotImplementedError

    def status(self) -> dict:
        try:
            ok = self.health()
        except Exception:
            ok = False
        return {"id": self.id, "type": self.type, "healthy": ok,
                "language": self.language}
