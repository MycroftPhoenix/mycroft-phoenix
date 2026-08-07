#!/usr/bin/env python3
"""
Adaptateur PiperTTS -> TTSBackend.

Permet d'utiliser Piper via l'interface unifiée TTSBackend
sans modifier le code existant.
"""

import io
import os
import tempfile
from typing import Optional, Dict, Any, List

import importlib.util

# Import base sans passer par mycroft.tts.__init__
_base_spec = importlib.util.spec_from_file_location("base", r"E:\opencode\assistant_locale-Mycroft-phoenix\mycroft\tts\base.py")
_base = importlib.util.module_from_spec(_base_spec)
_base_spec.loader.exec_module(_base)
TTSBackend = _base.TTSBackend
TTSFactory = _base.TTSFactory

# Import PiperTTS original sans passer par mycroft.tts.__init__
_piper_spec = importlib.util.spec_from_file_location("piper_orig", r"E:\opencode\assistant_locale-Mycroft-phoenix\mycroft\tts\piper_tts.py")
_piper = importlib.util.module_from_spec(_piper_spec)
_piper_spec.loader.exec_module(_piper)
PiperOriginal = _piper.PiperTTS


class PiperTTS(TTSBackend):
    """Wrapper PiperTTS implémentant l'interface TTSBackend."""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._piper = PiperOriginal(
            lang=self.config.get("lang", "fr-FR"),
            config=self.config,
        )
        self.current_voice = self.config.get("voice", "fr_FR-siwis-medium")

    def synthesize(self, text: str, **kwargs) -> bytes:
        voice = kwargs.get("voice", self.current_voice)
        old_voice = self._piper.voice
        if voice != old_voice:
            self._piper.voice = voice

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        try:
            wav_path, _ = self._piper.get_tts(text, wav_path)
            if wav_path and os.path.exists(wav_path):
                with open(wav_path, "rb") as f:
                    return f.read()
            return b""
        finally:
            if voice != old_voice:
                self._piper.voice = old_voice
            if os.path.exists(wav_path):
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass

    def get_available_voices(self) -> List[Dict[str, Any]]:
        # Voix Piper françaises courantes
        return [
            {"id": "fr_FR-siwis-medium", "name": "Femme (siwis-medium)", "lang": "fr-FR"},
            {"id": "fr_FR-gilles-low", "name": "Homme grave (gilles-low)", "lang": "fr-FR"},
            {"id": "fr_FR-mls-medium", "name": "Femme (mls-medium)", "lang": "fr-FR"},
            {"id": "fr_FR-upmc-medium", "name": "Homme (upmc-medium)", "lang": "fr-FR"},
        ]

    def set_voice(self, voice_id: str) -> bool:
        voices = [v["id"] for v in self.get_available_voices()]
        if voice_id in voices:
            self.current_voice = voice_id
            return True
        return False

    def get_current_voice(self) -> Optional[str]:
        return self.current_voice


# Enregistrement automatique
TTSFactory.register("piper", PiperTTS)