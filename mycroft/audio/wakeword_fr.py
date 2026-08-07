#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wake word Phoenix FR — détection du mot d'activation "phoenix" via Vosk
(modèle français, mode grammar, CPU only).

Pourquoi Vosk FR et pas openWakeWord :
  - openWakeWord (hey_jarvis / hey_mycroft) est entraîné sur voix anglophones
    et ne réagit pas à la voix française (score ~0 sur TTS et voix FR).
  - Vosk modèle FR en mode grammar ne reconnaît QUE le mot cible → faible
    latence (détection via PartialResult), utile comme wake word.

Pipeline (étape 1 du schéma multi-locuteurs) :
  1. Audio 16 kHz mono en flux continu
  2. KaldiRecognizer en mode grammar ["phoenix", "[unk]"]
  3. "phoenix" détecté dans partial result → événement "awakening"

⚠️ [unk] est OBLIGATOIRE dans la grammar : sans lui, le décodeur se bloque
sur l'audio qui ne correspond pas au mot cible et ne reconnaît plus rien.

Usage streaming (recommandé) ou batch (fichier WAV) :
    ww = WakeWordFR()
    for chunk in audio_chunks():      # int16 16 kHz
        if ww.detect(chunk):
            handle_wake()

API asynchrone compatible :
    ww.process_audio(audio_int16) -> bool   # True si wake détecté
    ww.detect_file(wav_path) -> float       # score/max sur un fichier
"""

import json
import os
import wave
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

SAMPLE_RATE = 16000
CHUNK_SEC = 0.1          # 100 ms par chunk
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_SEC)  # 1600

# Vrai mot d'activation (français). "phoenix" est bien reconnu par le
# modèle vosk-model-small-fr-0.22 (3 détections validées sur phoenix.flac).
WAKE_WORD = "phoenix"

# Nombre de chunks consécutifs où le mot doit rester présent pour confirmer
# la détection (filtre les faux positifs transitoires de Vosk grammar).
# Les vrais "phoenix" durent ~2.4s (24 chunks) ; les faux 2-3 chunks.
CONFIRM_CHUNKS = 5

# Modèle Vosk français. On cherche d'abord un modèle local, sinon on laisse
# Vosk télécharger le sien (chemin à fournir explicitement).
DEFAULT_MODEL_DIR = None  # à définir : chemin du dossier vosk-model-...


class VoskGrammarWakeWord:
    """Détecteur de wake word français via Vosk (mode grammar).

    Charge le modèle Vosk à la demande (lazy). Accepte du PCM int16
    16 kHz mono. Le mot cible est donné par ``wake_word``.
    """

    def __init__(self, model_dir: str = DEFAULT_MODEL_DIR,
                 wake_word: str = WAKE_WORD,
                 confirm_chunks: int = CONFIRM_CHUNKS):
        self.model_dir = model_dir
        self.wake_word = wake_word
        self.confirm_chunks = confirm_chunks
        self.threshold = 0.0   # détection = mot présent (pas de score 0-1)
        self._model = None
        self._rec = None
        self._streak = 0       # chunks consécutifs avec le mot
        self._fired = False    # déjà déclenché pour cette occurrence

    def _lazy_init(self):
        if self._rec is not None:
            return
        if not self.model_dir:
            raise ValueError(
                "model_dir introuvable : fournir le chemin du modèle Vosk "
                "(ex: 'C:/.../vosk-model-small-fr-0.22')"
            )
        from vosk import Model, KaldiRecognizer
        self._model = Model(self.model_dir)
        # grammar = [mot_cible, "[unk]"] — [unk] obligatoire sinon blocage
        grammar = json.dumps([self.wake_word, "[unk]"])
        self._rec = KaldiRecognizer(self._model, SAMPLE_RATE, grammar)

    def detect(self, audio_chunk: np.ndarray) -> bool:
        """Analyse un chunk PCM int16 16 kHz → True quand le wake word est
        fraîchement prononcé.

        Le partial de Vosk en mode grammar est instable : le mot apparaît
        et disparaît de façon transitoire sur les faux positifs. On exige
        donc que le mot reste présent sur ``confirm_chunks`` chunks
        consécutifs avant de déclencher (filtre anti-faux-positifs).

        Une fois déclenché, on ne re-déclenche pas tant que le mot reste
        présent : on attend qu'il disparaisse puis réapparaisse (une
        occurrence = un seul True).
        """
        self._lazy_init()
        audio = audio_chunk
        # si on reçoit du float32, convertir en int16 (16 kHz attendu)
        if audio.dtype == np.float32:
            audio = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        buf = np.ascontiguousarray(audio).tobytes()
        if self._rec.AcceptWaveform(buf):
            # fin d'énoncé : le résultat final contient aussi le mot
            res = json.loads(self._rec.Result())
            had = self.wake_word in res.get("text", "").split()
        else:
            partial = self._rec.PartialResult()
            had = self.wake_word in json.loads(partial).get("partial", "").split()
        if not had:
            self._streak = 0
            self._fired = False
            return False
        self._streak += 1
        if self._streak >= self.confirm_chunks and not self._fired:
            self._fired = True
            return True
        return False

    def process_audio(self, audio: np.ndarray) -> bool:
        """Alias streaming-friendly de :meth:`detect`."""
        return self.detect(audio)

    def detect_file(self, wav_path: str) -> bool:
        """Wake word détecté au moins une fois dans un fichier WAV 16 kHz."""
        self._lazy_init()
        with wave.open(wav_path, "rb") as wf:
            if wf.getframerate() != SAMPLE_RATE:
                raise ValueError("detect_file attend un WAV 16 kHz")
            data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        for i in range(0, len(data), CHUNK_SAMPLES):
            chunk = data[i:i + CHUNK_SAMPLES]
            if len(chunk) < CHUNK_SAMPLES:
                chunk = np.pad(chunk, (0, CHUNK_SAMPLES - len(chunk)))
            if self.detect(chunk):
                return True
        return False

    def reset(self):
        if self._rec is not None:
            self._rec.Reset()
        self._streak = 0
        self._fired = False

    def close(self):
        self._rec = None
        self._model = None
