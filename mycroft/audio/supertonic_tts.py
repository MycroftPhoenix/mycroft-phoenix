#!/usr/bin/env python3
"""SupertonicTTS - remplacement Piper pour Phoenix (bug 'e-aigu' espeak-ng).

Interface compatible avec PiperTTS de voice_loop.py : synthesize(text) -> bytes.
Phonémisation native (pas espeak-ng) -> les accents français sont prononcés
correctement, zéro glitch 'a-t-il cooperer' ni 'atild'.

Modèle: Supertonic-3 (sherpa-onnx), 99M params, CPU, 31 langues.
Code MIT, modèle OpenRAIL-M.
"""
import io
import os
import struct
import wave

import sherpa_onnx

# Chemin par défaut des modèles (ajustable via config)
DEFAULT_MODEL_DIR = r"E:\opencode\sherpa-models\sherpa-onnx-supertonic-3-tts-int8-2026-05-11"

# Identifiants de voix du modèle (une trentaine de voix, fr dispo via lang='fr')
# sid 0 et 6 testés OK sur le français.
AVAILABLE_SIDS = [0, 6]


class SupertonicTTS:
    """TTS Supertonic-3 via sherpa-onnx, interface = PiperTTS (synthesize)."""

    def __init__(self, voice: str = "fr", config: dict = None):
        self.voice = voice  # peut etre 'fr' (langue) ou 'fr-<sid>'
        self.config = config or {}
        self.lang = "fr"
        self.sid = 0
        # Support d'une syntaxe 'fr-6' pour choisir la voix
        if "-" in str(voice):
            parts = str(voice).split("-")
            self.lang = parts[0]
            try:
                self.sid = int(parts[1])
            except ValueError:
                self.sid = 0
        self.model_dir = self.config.get("tts", {}).get(
            "supertonic_model_dir", DEFAULT_MODEL_DIR)
        self._tts = None

    def _load(self):
        if self._tts is not None:
            return self._tts
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
                num_threads=2,
                provider="cpu",
            ),
        )
        if not tts_config.validate():
            raise ValueError("Config Supertonic invalide")
        self._tts = sherpa_onnx.OfflineTts(tts_config)
        return self._tts

    def synthesize(self, text: str) -> bytes:
        """Synthétise le texte en WAV (bytes). Accents conservés."""
        return self.synthesize_with_sid(text, self.sid)

    def synthesize_with_sid(self, text: str, sid: int) -> bytes:
        """Synthétise le texte avec une voix précise (sid 0-9)."""
        try:
            tts = self._load()
        except Exception as e:
            print(f"[Supertonic] Erreur chargement: {e}")
            return b""
        try:
            gc = sherpa_onnx.GenerationConfig()
            gc.sid = int(sid) % 10
            gc.speed = 1.0
            gc.num_steps = 8
            gc.extra = {"lang": self.lang}
            audio = tts.generate(text, gc, None)
            return self._samples_to_wav(audio.samples, audio.sample_rate)
        except Exception as e:
            print(f"[Supertonic] Erreur synthèse (sid {sid}): {e}")
            return b""

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

    # Compatibilité: voice_loop appelle play_audio() sur self.tts aussi.
    # La classe PiperTTS a play_audio; on le délègue au même code.
    def play_audio(self, audio_data: bytes):
        # Délégué: on réutilise la fonction play du module parent si fournie.
        play = self.config.get("_play_audio_fn")
        if play:
            play(audio_data, self.config)
        else:
            print("[Supertonic] play_audio non câblé (fn manquante)")


def create_supertonic_tts(voice: str = "fr", config: dict = None) -> SupertonicTTS:
    return SupertonicTTS(voice, config)


def concat_wavs(wavs, pause_ms: int = 200) -> bytes:
    """Concatène plusieurs WAV (44100 Hz mono 16-bit) en un seul, avec une
    micro-pause de `pause_ms` ms entre chaque (respiration naturelle).

    Retourne un WAV unique. Retourne b'' si aucune entrée valide.
    """
    chunks = []
    rate = None
    for w in wavs:
        if not w:
            continue
        try:
            with wave.open(io.BytesIO(w), "rb") as wf:
                if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                    continue
                if rate is None:
                    rate = wf.getframerate()
                chunks.append(wf.readframes(wf.getnframes()))
        except Exception:
            continue
    if not chunks:
        return b""
    if rate is None:
        rate = 44100
    pause = int(rate * pause_ms / 1000) * 2  # 2 octets/échantillon mono 16-bit
    silence = b"\x00" * pause
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(silence.join(chunks))
    return buf.getvalue()
