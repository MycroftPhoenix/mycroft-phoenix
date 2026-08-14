#!/usr/bin/env python3
"""
Supertonic-3 TTS Backend (sherpa-onnx).

Implémente l'interface TTSBackend pour usage plug-and-play
dans mycroft/tts/base.py. Zéro couplage avec voice_loop.
"""

import io
import os
import struct
import wave
from typing import Optional, Dict, Any, List

import importlib.util
_base_spec = importlib.util.spec_from_file_location("base", r"D:\mycroft-phoenix\mycroft\tts\base.py")
_base = importlib.util.module_from_spec(_base_spec)
_base_spec.loader.exec_module(_base)
TTSBackend = _base.TTSBackend
TTSFactory = _base.TTSFactory

try:
    import sherpa_onnx
    SHERPA_AVAILABLE = True
except ImportError:
    SHERPA_AVAILABLE = False


DEFAULT_MODEL_DIR = r"E:\opencode\sherpa-models\sherpa-onnx-supertonic-3-tts-int8-2026-05-11"


class SupertonicTTS(TTSBackend):
    """Backend TTS Supertonic-3 via sherpa-onnx."""

    # Voix testées et validées pour le français
    VOICE_MAP = {
        "fr-0": {"sid": 0, "lang": "fr", "name": "Femme claire (narrateur)"},
        "fr-1": {"sid": 1, "lang": "fr", "name": "Femme douce"},
        "fr-2": {"sid": 2, "lang": "fr", "name": "Homme léger"},
        "fr-3": {"sid": 3, "lang": "fr", "name": "Enfant/Garçon aigu"},
        "fr-4": {"sid": 4, "lang": "fr", "name": "Homme moyen"},
        "fr-5": {"sid": 5, "lang": "fr", "name": "Homme grave"},
        "fr-6": {"sid": 6, "lang": "fr", "name": "Très grave (dragon)"},
        "fr-7": {"sid": 7, "lang": "fr", "name": "Homme grave-moyen"},
        "fr-8": {"sid": 8, "lang": "fr", "name": "Homme moyen-bas"},
        "fr-9": {"sid": 9, "lang": "fr", "name": "Très grave (ogre)"},
    }

    def __init__(self, config: Dict[str, Any] = None):
        if not SHERPA_AVAILABLE:
            raise RuntimeError("sherpa-onnx non installé (pip install sherpa-onnx)")

        self.config = config or {}
        self.model_dir = self.config.get("model_dir", DEFAULT_MODEL_DIR)
        self.default_voice = self.config.get("default_voice", "fr-0")
        self.current_voice = self.default_voice
        self._tts = None
        self._load_model()

    def _load_model(self):
        """Charge le modèle sherpa-onnx une seule fois."""
        if self._tts is not None:
            return

        tts_config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                supertonic=sherpa_onnx.OfflineTtsSupertonicModelConfig(
                    duration_predictor=os.path.join(self.model_dir, "duration_predictor.int8.onnx"),
                    text_encoder=os.path.join(self.model_dir, "text_encoder.int8.onnx"),
                    vector_estimator=os.path.join(self.model_dir, "vector_estimator.int8.onnx"),
                    vocoder=os.path.join(self.model_dir, "vocoder.int8.onnx"),
                    tts_json=os.path.join(self.model_dir, "tts.json"),
                    unicode_indexer=os.path.join(self.model_dir, "unicode_indexer.bin"),
                    voice_style=os.path.join(self.model_dir, "voice.bin"),
                ),
                debug=False,
                num_threads=self.config.get("num_threads", 2),
                provider="cpu",
            ),
        )
        if not tts_config.validate():
            raise ValueError("Configuration Supertonic invalide")
        self._tts = sherpa_onnx.OfflineTts(tts_config)

    def synthesize(self, text: str, **kwargs) -> bytes:
        """Synthétise le texte avec la voix courante (ou override via kwargs)."""
        voice_id = kwargs.get("voice", self.current_voice)
        voice_info = self.VOICE_MAP.get(voice_id, self.VOICE_MAP[self.default_voice])

        gc = sherpa_onnx.GenerationConfig()
        gc.sid = voice_info["sid"]
        gc.speed = kwargs.get("speed", 1.0)
        gc.num_steps = kwargs.get("num_steps", 8)
        gc.extra = {"lang": voice_info["lang"]}

        audio = self._tts.generate(text, gc, None)
        return self._samples_to_wav(audio.samples, audio.sample_rate)

    def get_available_voices(self) -> List[Dict[str, Any]]:
        return [
            {"id": k, "name": v["name"], "lang": v["lang"]}
            for k, v in self.VOICE_MAP.items()
        ]

    def set_voice(self, voice_id: str) -> bool:
        if voice_id in self.VOICE_MAP:
            self.current_voice = voice_id
            return True
        return False

    def get_current_voice(self) -> Optional[str]:
        return self.current_voice

    @staticmethod
    def _samples_to_wav(samples, sample_rate: int) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            frames = b"".join(
                struct.pack("<h", max(-32768, min(32767, int(round(s * 32767)))))
                for s in samples
            )
            wf.writeframes(frames)
        return buf.getvalue()

    def concat_wavs(self, wavs: List[bytes], pause_ms: int = 180) -> bytes:
        """Concatène plusieurs WAV mono 16-bit 44.1kHz avec micro-pause."""
        if not wavs:
            return b""
        chunks = []
        rate = None
        for w in wavs:
            if not w:
                continue
            with wave.open(io.BytesIO(w), "rb") as wf:
                if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                    continue
                if rate is None:
                    rate = wf.getframerate()
                chunks.append(wf.readframes(wf.getnframes()))
        if not chunks:
            return b""
        if rate is None:
            rate = 44100
        pause = int(rate * pause_ms / 1000) * 2
        silence = b"\x00" * pause
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(silence.join(chunks))
        return buf.getvalue()


# Enregistrement automatique
TTSFactory.register("supertonic", SupertonicTTS)