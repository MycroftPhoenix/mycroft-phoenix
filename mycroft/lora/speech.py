"""
Moteurs STT / TTS brancables — synthèse et reconnaissance vocale.

Le core ne connaît que l'interface ``STTBackend`` / ``TTSBackend`` : le moteur
réel (kokoro, piper, pico, vosk, whisper…) est choisi par la config
(phoenix_config.json, sections ``stt`` et ``tts``). On peut donc changer de
moteur, ou en brancher un nouveau, sans toucher au code du core — voir
``doc/design_stt_tts_plugins.md``.

Protocole commun
================

- ``health() -> bool``  : le moteur est installé, joignable et prêt.
- ``status() -> dict``  : infos pour le panneau web (id, type, healthy, voix…).
- TTS : ``synthesize(text) -> Iterable[bytes]`` émet des paquets de PCM brut
  (int16, mono, little-endian) au rythme de ``sample_rate`` (streaming).
- STT : ``transcribe(audio: bytes, sample_rate) -> str | None``.

Tous les imports de moteurs sont paresseux : un moteur non installé est
simplement ``health() == False`` (aucune erreur au démarrage).

Config (phoenix_config.json) ::

    "tts": {
      "engine": "kokoro",            # ou piper | pico | dummy
      "language": "fr",
      "sample_rate": 24000,
      "model_path": "kokoro-v1.0.onnx",
      "voices_path": "voices-v1.0.bin"
    },
    "stt": {
      "engine": "vosk",              # ou whisper | dummy
      "language": "fr",
      "model_path": "vosk-model-small-fr-0.22",
      "sample_rate": 16000
    }
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Interfaces
# --------------------------------------------------------------------------

class TTSBackend:
    """Protocole commun d'un moteur de synthèse vocale."""

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
    """Protocole commun d'un moteur de reconnaissance vocale."""

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


# --------------------------------------------------------------------------
# Connecteurs TTS
# --------------------------------------------------------------------------

class KokoroTTS(TTSBackend):
    """Kokoro TTS (82M params) via ONNX Runtime — temps réel sur CPU.

    Nécessite : ``pip install kokoro-onnx onnxruntime`` + les fichiers
    ``kokoro-v1.0.onnx`` et ``voices-v1.0.bin`` (cf. doc plugins).
    """

    type = "kokoro"
    description = "Kokoro TTS (ONNX, temps réel sur CPU)"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.model_path = cfg.get("model_path") or "kokoro-v1.0.onnx"
        self.voices_path = cfg.get("voices_path") or "voices-v1.0.bin"
        self.voice = cfg.get("voice") or "af_heart"  # voix du modèle
        self.speed = float(cfg.get("speed", 1.0))
        if not cfg.get("sample_rate"):
            self.sample_rate = 24000

    def health(self) -> bool:
        for mod in ("onnxruntime", "kokoro_onnx"):
            if __import__("importlib").util.find_spec(mod) is None:
                return False
        return os.path.exists(self.model_path) and os.path.exists(self.voices_path)

    def synthesize(self, text: str) -> Iterable[bytes]:
        from kokoro_onnx import Kokoro

        kokoro = Kokoro(self.model_path, self.voices_path)
        samples, _ = kokoro.create(
            text, voice=self.voice, speed=self.speed, lang=self.language
        )
        import numpy as np

        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        yield pcm


class PiperTTS(TTSBackend):
    """Piper (voix neurales locales, léger — bon pour Raspberry Pi).

    Nécessite le binaire ``piper`` (ou le chemin via ``piper_path``) et un
    modèle ``.onnx`` (``voice_path``). Streaming via stdin/stdout raw PCM.
    """

    type = "piper"
    description = "Piper (voix neurales locales, léger)"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.bin = cfg.get("piper_path") or "piper"
        self.voice_path = cfg.get("voice_path") or cfg.get("model_path")
        self.length_scale = float(cfg.get("length_scale", 1.0))
        if not cfg.get("sample_rate"):
            self.sample_rate = 22050

    def health(self) -> bool:
        if self.voice_path and not os.path.exists(self.voice_path):
            return False
        return shutil.which(self.bin) is not None

    def synthesize(self, text: str) -> Iterable[bytes]:
        cmd = [self.bin, "--model", self.voice_path, "--output-raw",
               "--length-scale", str(self.length_scale)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        out, _ = proc.communicate(text.encode("utf-8"), timeout=120)
        if proc.returncode != 0 or not out:
            logger.warning("piper: échec (rc=%s)", proc.returncode)
            return
        yield out


class PicoTTS(TTSBackend):
    """Pico TTS (pico2wave) — ultra léger, mono-shot (non streaming)."""

    type = "pico"
    description = "pico2wave (SVox Pico, ultra léger, mono-shot)"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.bin = cfg.get("pico_path") or "pico2wave"
        if not cfg.get("sample_rate"):
            self.sample_rate = 16000

    def health(self) -> bool:
        return shutil.which(self.bin) is not None

    def synthesize(self, text: str) -> Iterable[bytes]:
        import wave

        fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            cmd = [self.bin, "-w", wav_path, text]
            subprocess.run(cmd, capture_output=True, timeout=60, check=False)
            with wave.open(wav_path, "rb") as w:
                self.sample_rate = w.getframerate()
                yield w.readframes(w.getnframes())
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass


# --------------------------------------------------------------------------
# Connecteurs STT
# --------------------------------------------------------------------------

class VoskSTT(STTBackend):
    """Vosk — reconnaissance hors-ligne légère, multilingue (FR OK).

    Nécessite : ``pip install vosk`` + un modèle (ex. ``vosk-model-small-fr-0.22``).
    """

    type = "vosk"
    description = "Vosk (hors-ligne, léger, multilingue)"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.model_path = cfg.get("model_path")
        self.model = None  # chargé paresseusement

    def health(self) -> bool:
        if __import__("importlib").util.find_spec("vosk") is None:
            return False
        return bool(self.model_path) and os.path.exists(self.model_path)

    def _get_model(self):
        if self.model is None:
            from vosk import Model
            self.model = Model(self.model_path)
        return self.model

    def transcribe(self, audio: bytes, sample_rate: int = 16000) -> Optional[str]:
        import vosk

        rec = vosk.KaldiRecognizer(self._get_model(), sample_rate)
        if rec.AcceptWaveform(audio):
            return json.loads(rec.Result()).get("text") or None
        partial = json.loads(rec.FinalResult()).get("text") or None
        return partial


class WhisperSTT(STTBackend):
    """Whisper (faster-whisper) — qualité maximale, plus gourmand.

    Nécessite : ``pip install faster-whisper``. Modèle par défaut ``small``,
    quantifié int8 sur CPU (raisonnable sur AMD A-10).
    """

    type = "whisper"
    description = "Whisper (faster-whisper, qualité maximale)"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.model_name = cfg.get("model") or "small"
        self.device = cfg.get("device", "cpu")
        self.compute_type = cfg.get("compute_type", "int8")
        self._model = None

    def health(self) -> bool:
        return __import__("importlib").util.find_spec("faster_whisper") is not None

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_name, device=self.device,
                                       compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio: bytes, sample_rate: int = 16000) -> Optional[str]:
        import io
        import wave

        # faster-whisper attend un chemin fichier (ou un reader de son)
        fd, tmp = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with wave.open(tmp, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sample_rate)
                w.writeframes(audio)
            segments, _ = self._get_model().transcribe(tmp, language=self.language)
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text or None
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass


# --------------------------------------------------------------------------
# Moteur dummy (tests / développement sans audio)
# --------------------------------------------------------------------------

class DummyTTS(TTSBackend):
    """TTS factice : renvoie un court silence PCM. Pour les tests."""

    type = "dummy"
    description = "Moteur factice pour les tests (aucune audio)"

    def health(self) -> bool:
        return True

    def synthesize(self, text: str) -> Iterable[bytes]:
        yield b"\x00\x00" * int(self.sample_rate * 0.1)  # 100 ms de silence


class DummySTT(STTBackend):
    """STT factice : renvoie le texte configuré (``reply``). Pour les tests."""

    type = "dummy"
    description = "Moteur factice pour les tests (aucune audio)"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.reply = str(cfg.get("reply") or "bonjour")

    def health(self) -> bool:
        return True

    def transcribe(self, audio: bytes, sample_rate: int = 16000) -> Optional[str]:
        return self.reply


# --------------------------------------------------------------------------
# Registry + fabriques
# --------------------------------------------------------------------------

_TTS_REGISTRY: Dict[str, type] = {
    "kokoro": KokoroTTS,
    "piper": PiperTTS,
    "pico": PicoTTS,
    "dummy": DummyTTS,
}

_STT_REGISTRY: Dict[str, type] = {
    "vosk": VoskSTT,
    "whisper": WhisperSTT,
    "dummy": DummySTT,
}


def _engine_name(cfg: dict) -> str:
    """Nom du connecteur : clé ``engine``, alias legacy ``provider``."""
    return str(cfg.get("engine") or cfg.get("provider") or "dummy").lower()


def build_tts(cfg: dict) -> Optional[TTSBackend]:
    cls = _TTS_REGISTRY.get(_engine_name(cfg))
    if cls is None:
        logger.warning("Moteur TTS inconnu: %s", _engine_name(cfg))
        return None
    try:
        return cls(cfg)
    except Exception as e:
        logger.warning("TTS %s non construit: %s", _engine_name(cfg), e)
        return None


def build_stt(cfg: dict) -> Optional[STTBackend]:
    cls = _STT_REGISTRY.get(_engine_name(cfg))
    if cls is None:
        logger.warning("Moteur STT inconnu: %s", _engine_name(cfg))
        return None
    try:
        return cls(cfg)
    except Exception as e:
        logger.warning("STT %s non construit: %s", _engine_name(cfg), e)
        return None


def speech_from_config(config: dict):
    """Fabrique (stt, tts) depuis phoenix_config.json (sections stt/tts)."""
    stt_cfg = config.get("stt") or {}
    tts_cfg = config.get("tts") or {}
    stt = build_stt(stt_cfg)
    tts = build_tts(tts_cfg)
    if stt is None and stt_cfg:
        logger.warning("Aucun moteur STT actif (config: %s)", stt_cfg)
    if tts is None and tts_cfg:
        logger.warning("Aucun moteur TTS actif (config: %s)", tts_cfg)
    return stt, tts
