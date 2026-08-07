#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wake word Phoenix — détection du mot d'activation "hey Phoenix" via
openWakeWord (modèles ONNX, CPU only, ~50-100 Mo RAM).

Pipeline (étape 1 du schéma multi-locuteurs) :
  1. Audio 16 kHz mono en flux continu (chunks de 80 ms = 1280 échantillons)
  2. openWakeWord inference (modèle hey_jarvis_v0.1.onnx par défaut)
  3. Score > seuil → événement "awakening" (phrase suivante à capturer)

Modèle validé : hey_jarvis_v0.1.onnx
  - Détecté à score 1.0 sur échantillon réel ("hey mycroft")
  - ATTENTION : ne détecte PAS la voix française Piper (score 0.077) →
    le modèle hey_jarvis est entraîné sur voix anglophones. Pour du
    français, il faut un modèle francophone (ou "hey_mycroft").

Usage streaming (recommandé) ou batch (fichier WAV) :
    ww = WakeWord()
    ww.start_stream()
    for chunk in audio_chunks():        # int16 16 kHz, 0.1s
        if ww.detect(chunk):
            handle_wake()
    ww.stop_stream()

API asynchrone compatible :
    ww.process_audio(audio_int16) -> bool   # True si wake détecté
"""

import os
import time
import numpy as np
from pathlib import Path
from queue import Queue, Empty

PROJECT_ROOT = Path(__file__).parent.parent.parent
OWW_RESOURCE_DIR = None

SAMPLE_RATE = 16000
CHUNK_SEC = 0.1          # 100 ms par chunk
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_SEC)  # 1600

# Modèle + seuil par défaut
DEFAULT_MODEL = "hey_jarvis_v0.1.onnx"
WAKE_THRESHOLD = 0.5

_oww = None  # instance openwakeword lazy


class WakeWord:
    """Détecteur de wake word openWakeWord (CPU, modèles ONNX).

    Le modèle est chargé à la demande (lazy) et réutilisé. Toutes les
    méthodes acceptent du PCM int16 16 kHz mono.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL,
                 threshold: float = WAKE_THRESHOLD):
        self.model_name = model_name
        self.threshold = threshold
        self._model = None
        self._buffer = np.array([], dtype=np.float32)

    def _lazy_init(self):
        if self._model is not None:
            return
        import openwakeword
        # openWakeWord charge les modèles depuis son répertoire resources/models
        oww_root = os.path.dirname(openwakeword.__file__)
        res_models = os.path.join(oww_root, "resources", "models")
        model_path = os.path.join(res_models, self.model_name)
        if not os.path.exists(model_path):
            from openwakeword.utils import download_models
            download_models([self.model_name.replace(".onnx", "")])
        # BUG FIX: wakeword_models doit être UNE LISTE de chemins (str),
        # pas un str seul. inference_framework="onnx" force le backend ONNX runtime.
        self._model = openwakeword.Model(
            wakeword_models=[model_path], inference_framework="onnx"
        )
        self._model.reset()

    def _float32_to_int16(self, audio):
        """Normalise n'importe quel PCM vers float32 [-1, 1] puis int16."""
        audio = np.asarray(audio)
        if audio.dtype == np.float32 or audio.dtype == np.float64:
            audio = np.clip(audio, -1.0, 1.0)
            audio = (audio * 32767).astype(np.int16)
        else:
            audio = audio.astype(np.int16)
        return audio

    def detect(self, audio_chunk: np.ndarray) -> bool:
        """Analyse un chunk audio int16 16 kHz → True si wake word détectée."""
        self._lazy_init()
        audio = self._float32_to_int16(audio_chunk)
        # openWakeWord attend float32 normalisé
        audio_f = audio.astype(np.float32) / 32768.0
        prediction = self._model.predict(audio_f)
        score = self._extract_score(prediction)
        return score >= self.threshold

    def process_audio(self, audio: np.ndarray) -> bool:
        """Alias streaming-friendly de :meth:`detect`."""
        return self.detect(audio)

    def detect_file(self, wav_path: str) -> float:
        """Score max du wake word sur un fichier WAV int16 16 kHz.

        Utile pour le test sans micro. Itère par chunks de 1280 échantillons
        (fenêtre standard openWakeWord) et renvoie le score max.
        """
        self._lazy_init()
        import wave
        with wave.open(wav_path, "rb") as wf:
            rate = wf.getframerate()
            n = wf.getnframes()
            data = np.frombuffer(wf.readframes(n), dtype=np.int16)
        # downsampling si besoin
        if rate != SAMPLE_RATE:
            data = data[np.linspace(0, len(data)-1, int(len(data)*SAMPLE_RATE/rate)).astype(np.int64)]
        audio_f = data.astype(np.float32) / 32768.0
        # openWakeWord découpe lui-même l'audio en frames internes (1280)
        # et renvoie une liste de scores par frame → max sur toute la liste.
        result = self._model.predict(audio_f)
        sc = self._extract_score(result)
        return sc

    def _extract_score(self, prediction: dict) -> float:
        """Extrait le score du modèle depuis le dict de prédiction.

        openWakeWord nomme la clé d'après le nom du modèle SANS extension
        (ex: ``hey_jarvis_v0.1``), alors que ``self.model_name`` contient
        ``hey_jarvis_v0.1.onnx``. On cherche la clé la plus ressemblante.
        """
        base = self.model_name
        if "." in base:
            base = base.rsplit(".", 1)[0]
        candidates = [k for k in prediction if base in k]
        if candidates:
            key = candidates[0]
        else:
            key = list(prediction)[0]
        scores = prediction[key]
        # l'API renvoie une liste de scores (un par frame) → prendre le max
        if isinstance(scores, (list, np.ndarray)):
            score = float(np.max(scores))
        else:
            score = float(scores)
        return score

    def reset(self):
        if self._model is not None:
            self._model.reset()

    def close(self):
        self._model = None
        self._buffer = np.array([], dtype=np.float32)


class WakeWordStream:
    """Détecteur de wake word en mode streaming continu.

    Utilise une queue interne pour accumuler les chunks audio, puis
    délègue à openWakeWord. Adapté à la boucle d'écoute de Phoenix.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL,
                 threshold: float = WAKE_THRESHOLD):
        self.ww = WakeWord(model_name, threshold)
        self._q = Queue()
        self._running = False

    def start(self):
        self._running = True

    def stop(self):
        self._running = False

    def feed(self, chunk: np.ndarray):
        self._q.put(self.ww._float32_to_int16(chunk))

    def check(self) -> bool:
        """Retire les chunks disponibles et renvoie True si wake détecté."""
        detected = False
        try:
            while True:
                chunk = self._q.get_nowait()
                if self.ww.detect(chunk):
                    detected = True
        except Empty:
            pass
        return detected
