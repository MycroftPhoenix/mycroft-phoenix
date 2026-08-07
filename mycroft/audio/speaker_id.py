#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Speaker ID Phoenix — identification du locuteur via ECAPA-TDNN (ONNX, CPU).

Back-end : sherpa-onnx (k2-fsa) qui encapsule intégralement le
pré-traitement (STFT n_fft=400, hop=160, win=400, 80 mels, log +
normalisation global-mean) : zéro code de prétraitement à faire,
zéro risque d'écarts entre entraînement et inférence.

Modèle validé : 3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx
  - 26.4 MB, embedding 192 dims, entraîné sur VoxCeleb
  - CPU-only, onnxruntime sous-jacent, léger en RAM, sans CUDA
  - Validation discrimination : même locuteur cos ~0.69-0.79,
    locuteurs différents cos ~0.00-0.34  → seuil 0.6 fiable.

Pipeline (étape 2 du schéma multi-locuteurs) :
  1. Audio 16 kHz mono → sherpa_onnx accept_waveform
  2. Inférence ECAPA-TDNN → embedding 192 dims (déjà normalisé L2)
  3. Identification : distance cosinus contre les profils enregistrés

API :
    enc = SpeakerEncoder()
    emb = enc.embed(audio_int16)          # np.ndarray[192]
    profs = SpeakerProfiles()             # JSON persistant
    profs.add("Steve", emb)
    name, score = profs.identify(emb)     # ("Steve", 0.84) | ("Inconnu", 0.12)
"""

import os
import json
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
MODEL_DIR = PROJECT_ROOT / "models" / "speaker"
MODEL_PATH = MODEL_DIR / "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx"
PROFILES_FILE = PROJECT_ROOT / "speaker_profiles.json"

EMBED_DIM = 192
SAMPLE_RATE = 16000

# Seuil de similarité cosinus pour accepter un locuteur connu.
# > seuil : reconnu ; sinon : "Inconnu" (protocole de création de profil).
COSINE_THRESHOLD = 0.60


class _ExtractorCache:
    """Singleton lazy d'extracteur sherpa-onnx (chargement une fois)."""

    _inst = None

    @classmethod
    def get(cls):
        if cls._inst is None:
            import sherpa_onnx
            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODEL_PATH))
            if not cfg.validate():
                raise FileNotFoundError("Modèle sherpa-onnx invalide: %s" % MODEL_PATH)
            cls._inst = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
        return cls._inst


class SpeakerEncoder:
    """Extrait une empreinte vocale (embedding 192d) depuis un audio 16 kHz.

    Le pré-traitement complet (STFT, fbank mel, log, normalisation
    global-mean) est réalisé en interne par sherpa-onnx : on ne fournit
    qu'un signal audio float32 à 16 kHz mono.

    Retourne un vecteur normalisé L2 (prêt pour la distance cosinus).
    """

    def __init__(self, model_path: Path = MODEL_PATH):
        if not Path(model_path).exists():
            raise FileNotFoundError("Modèle ECAPA/Sherpa absent: %s" % model_path)
        self.session = _ExtractorCache.get()
        self.dim = self.session.dim  # 192

    def embed(self, audio: np.ndarray):
        """Embedding 192d depuis un signal 16 kHz mono (int16 ou float32)."""
        audio = np.asarray(audio)
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        else:
            audio = audio.astype(np.float32)
            if audio.dtype.kind == 'f' and np.max(np.abs(audio)) > 1.0:
                audio = audio / 32768.0
        audio = np.ascontiguousarray(audio.reshape(-1))

        stream = self.session.create_stream()
        stream.accept_waveform(SAMPLE_RATE, audio)
        stream.input_finished()
        if not self.session.is_ready(stream):
            # Audio trop court : padding silencieux jusqu'à ce que le modèle lise assez.
            pad = np.zeros(int(0.5 * SAMPLE_RATE), dtype=np.float32)
            stream.accept_waveform(SAMPLE_RATE, pad)
            stream.input_finished()
        emb = np.array(self.session.compute(stream), dtype=np.float32).flatten()
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        return emb


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    return float(np.dot(a, b) / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-9))


class SpeakerProfiles:
    """Gestion des profils locuteurs (empreintes + noms), stockés en JSON.

    Le schéma multi-locuteurs stocke : (Profil: nom) ──[A_POUR_VOIX]──> (vecteur).
    Ici le JSON est le format portable ; une migration vers le graphe Kuzu
    (noeud Profil) est possible plus tard sans changer l'API.
    """

    def __init__(self, path: Path = PROFILES_FILE):
        self.path = Path(path)
        self.profiles = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return {name: np.asarray(v, dtype=np.float32) for name, v in data.items()}
            except Exception:
                pass
        return {}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(
                {name: emb.tolist() for name, emb in self.profiles.items()},
                f, ensure_ascii=False, indent=2,
            )

    def names(self):
        return list(self.profiles.keys())

    def add(self, name: str, embedding: np.ndarray):
        """Enregistre (ou met à jour) le profil vocal d'un locuteur."""
        self.profiles[name] = np.asarray(embedding, dtype=np.float32)
        self._save()

    def identify(self, embedding: np.ndarray, threshold: float = COSINE_THRESHOLD):
        """Retourne (nom, score) du meilleur profil, ou ("Inconnu", score).

        Branch A : cosine >= seuil → locuteur reconnu.
        Branch B : sinon → profil "Inconnu".
        """
        best_name = "Inconnu"
        best_score = 0.0
        for name, ref in self.profiles.items():
            score = _cosine(embedding, ref)
            if score > best_score:
                best_score = score
                best_name = name
        if best_score >= threshold and best_name in self.profiles:
            return best_name, best_score
        return "Inconnu", best_score
