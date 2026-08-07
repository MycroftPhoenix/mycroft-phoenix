#!/usr/bin/env python3
"""
Interface commune pour tous les backends TTS (Text-to-Speech).

Permet d'ajouter de nouveaux moteurs TTS sans modifier voice_loop.py
ni les skills. Conforme au pattern Strategy.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import io


class TTSBackend(ABC):
    """Interface abstraite pour un moteur TTS."""

    @abstractmethod
    def synthesize(self, text: str, **kwargs) -> bytes:
        """
        Synthétise le texte en audio WAV brut.

        Args:
            text: Texte à synthétiser
            **kwargs: Paramètres optionnels (voice, speed, pitch, etc.)

        Returns:
            bytes: Données WAV complètes (header + frames)
        """
        pass

    @abstractmethod
    def get_available_voices(self) -> list:
        """Retourne la liste des voix disponibles pour ce backend."""
        pass

    @abstractmethod
    def set_voice(self, voice_id: str) -> bool:
        """Change la voix active. Retourne True si succès."""
        pass

    def get_current_voice(self) -> Optional[str]:
        """Voix actuellement sélectionnée (None = défaut)."""
        return None

    def supports_streaming(self) -> bool:
        """Ce backend supporte-t-il le streaming chunk par chunk ?"""
        return False

    def synthesize_stream(self, text: str, **kwargs):
        """Générateur pour streaming (optionnel)."""
        raise NotImplementedError("Streaming non supporté")


class TTSFactory:
    """Factory pour instancier le bon backend selon la config."""

    _backends = {}

    @classmethod
    def register(cls, name: str, backend_class):
        cls._backends[name] = backend_class

    @classmethod
    def create(cls, name: str, config: Dict[str, Any] = None) -> TTSBackend:
        if name not in cls._backends:
            raise ValueError(f"Backend TTS inconnu: {name}. Disponibles: {list(cls._backends.keys())}")
        return cls._backends[name](config or {})

    @classmethod
    def list_backends(cls) -> list:
        return list(cls._backends.keys())


def register_builtin_backends():
    """Enregistre les backends intégrés (appelé au démarrage)."""
    try:
        from mycroft.tts.piper_adapter import PiperTTS
        TTSFactory.register("piper", PiperTTS)
    except ImportError:
        pass

    try:
        from mycroft.tts.supertonic import SupertonicTTS
        TTSFactory.register("supertonic", SupertonicTTS)
    except ImportError:
        pass

    try:
        from mycroft.tts.espeak_tts import EspeakTTS
        TTSFactory.register("espeak", EspeakTTS)
    except ImportError:
        pass

    try:
        from mycroft.tts.dummy_tts import DummyTTS
        TTSFactory.register("dummy", DummyTTS)
    except ImportError:
        pass


# Auto-enregistrement à l'import
register_builtin_backends()