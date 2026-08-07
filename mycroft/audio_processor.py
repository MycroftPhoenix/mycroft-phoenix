"""
AudioProcessor — Pont entre microphone, STT, pipeline NLU et TTS.

Supporte deux backends :
  - "phoenix" : Vosk (STT offline) + Piper/SoundDevice (TTS offline)
  - "windows" : SpeechRecognition (STT OS) + SAPI5 (TTS OS)

Usage:
    proc = AudioProcessor(pipeline, config)
    proc.run_voice_loop()          # boucle interactive
    proc.listen_once()             # une seule ecoute → reponse
    proc.speak("Bonjour !")        # synthese vocale seule
"""

import io
import os
import sys
import wave
import json
import queue
import tempfile
import logging
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger("phoenix.audio")

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_DURATION_MS = 30
SILENCE_THRESHOLD = 500


# ──────────────────────────────────────────────
#  Captation audio (microphone)
# ──────────────────────────────────────────────

def _capture_audio_sounddevice(duration_sec=5, sample_rate=SAMPLE_RATE, channels=CHANNELS):
    """
    Enregistre depuis le microphone avec sounddevice.
    Retourne les donnees brutes (bytes) en format 16-bit PCM.
    """
    try:
        import sounddevice as sd
    except ImportError:
        raise RuntimeError("sounddevice non installe: pip install sounddevice")

    logger.info("Ecoute en cours (%.1fs)...", duration_sec)
    audio = sd.rec(
        int(duration_sec * sample_rate),
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
    )
    sd.wait()
    return audio.tobytes()


def _capture_audio_sounddevice_vad(sample_rate=SAMPLE_RATE, channels=CHANNELS,
                                    max_silence_sec=2.0, max_duration_sec=15):
    """
    Enregistre avec detection de fin de parole (VAD simple).
    Coupe quand le silence depasse max_silence_sec.
    Retourne les donnees brutes (bytes) en format 16-bit PCM.
    """
    try:
        import sounddevice as sd
    except ImportError:
        raise RuntimeError("sounddevice non installe: pip install sounddevice")

    import numpy as np

    block_size = int(sample_rate * BLOCK_DURATION_MS / 1000)
    frames = []
    silent_blocks = 0
    max_silent_blocks = int(max_silence_sec * 1000 / BLOCK_DURATION_MS)
    max_blocks = int(max_duration_sec * 1000 / BLOCK_DURATION_MS)

    logger.info("Ecoute active (parlez, je m'arrete au silence)...")

    with sd.InputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
        blocksize=block_size,
    ) as stream:
        for _ in range(max_blocks):
            data, overflowed = stream.read(block_size)
            frames.append(data.copy())
            rms = int(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
            if rms < SILENCE_THRESHOLD:
                silent_blocks += 1
                if silent_blocks >= max_silent_blocks:
                    logger.info("Silence detecte, fin de l'ecoute.")
                    break
            else:
                silent_blocks = 0

    if not frames:
        return b""

    audio = np.concatenate(frames, axis=0)
    return audio.tobytes()


# ──────────────────────────────────────────────
#  Backend STT
# ──────────────────────────────────────────────

class _VoskSTT:
    """STT via Vosk (hors ligne)."""

    def __init__(self, model_path="", lang="fr"):
        self.model_path = model_path
        self.lang = lang
        self._model = None
        self._rec = None

    def _ensure(self):
        if self._model is not None:
            return True
        try:
            from vosk import Model, KaldiRecognizer
        except ImportError:
            logger.error("Vosk non installe: pip install vosk")
            return False

        path = self.model_path
        if not path:
            candidates = [
                str(Path.home() / ".config" / "mycroft" / "vosk" / "model"),
                str(Path.home() / ".local" / "share" / "vosk" / "model"),
                os.path.join(os.path.dirname(__file__), "..", "vosk-model"),
            ]
            for c in candidates:
                if os.path.isdir(c):
                    path = c
                    break

        if not path or not os.path.isdir(path):
            logger.error(
                "Modele Vosk introuvable. Telechargez un modele depuis "
                "https://alphacephei.com/vosk/models et extrayez-le dans "
                "~/.config/mycroft/vosk/model"
            )
            return False

        try:
            self._model = Model(path)
            self._rec = KaldiRecognizer(self._model, SAMPLE_RATE)
            logger.info("Vosk charge depuis %s", path)
            return True
        except Exception as e:
            logger.error("Erreur chargement Vosk: %s", e)
            return False

    def transcribe(self, audio_data):
        """Transcrit des donnees audio (bytes 16-bit PCM) en texte."""
        if not self._ensure():
            return ""
        try:
            if self._rec.AcceptWaveform(audio_data):
                result = json.loads(self._rec.Result())
                return result.get("text", "")
            partial = json.loads(self._rec.PartialResult())
            return partial.get("partial", "")
        except Exception as e:
            logger.error("Erreur Vosk: %s", e)
            return ""


class _WindowsSTT:
    """STT via SpeechRecognition (Windows built-in)."""

    def __init__(self):
        self._recognizer = None

    def _ensure(self):
        if self._recognizer is not None:
            return True
        try:
            import speech_recognition as sr
            self._recognizer = sr.Recognizer()
            logger.info("SpeechRecognition (Windows) initialise")
            return True
        except ImportError:
            logger.error("speech_recognition non installe: pip install SpeechRecognition")
            return False

    def transcribe(self, audio_data):
        """Transcrit des donnees audio via l'API Windows."""
        if not self._ensure():
            return ""
        try:
            import speech_recognition as sr
            audio = sr.AudioData(audio_data, SAMPLE_RATE, 2)
            text = self._recognizer.recognize_windows(audio)
            logger.info("STT Windows: '%s'", text)
            return text
        except Exception as e:
            logger.error("Erreur Windows STT: %s", e)
            return ""


# ──────────────────────────────────────────────
#  Backend TTS
# ──────────────────────────────────────────────

class _VoskPiperTTS:
    """TTS via Piper (hors ligne). Joue le WAV directement."""

    def __init__(self, voice="fr_FR-siwis-medium"):
        self.voice = voice
        self._piper_path = self._find_piper()

    def _find_piper(self):
        import shutil
        piper = shutil.which("piper")
        if piper:
            return piper
        candidates = []
        if sys.platform == "win32":
            candidates = [
                "C:\\piper\\piper\\piper.exe",
                "C:\\piper\\piper.exe",
                "C:\\Program Files\\piper\\piper.exe",
                str(Path.home() / "AppData" / "Local" / "piper" / "piper.exe"),
            ]
        else:
            candidates = [
                "/usr/bin/piper",
                "/usr/local/bin/piper",
                str(Path.home() / ".local" / "bin" / "piper"),
            ]
        for c in candidates:
            if Path(c).exists():
                return c
        return None

    def _find_model(self):
        if sys.platform == "win32":
            data_dirs = [
                Path("C:\\piper\\voices"),
                Path.home() / "AppData" / "Local" / "piper" / "voices",
            ]
        else:
            data_dirs = [
                Path.home() / ".local" / "share" / "piper" / "voices",
            ]

        for data_dir in data_dirs:
            model = data_dir / f"{self.voice}.onnx"
            if model.exists():
                return str(model)
            if data_dir.exists():
                for f in data_dir.glob("fr_FR*.onnx"):
                    return str(f)

        return None

    def speak(self, text):
        """Genere et joue la synthese vocale."""
        if not self._piper_path:
            logger.error("Piper non trouve. Installez: pip install piper-tts")
            self._fallback_speak(text)
            return

        model = self._find_model()
        if not model:
            logger.error("Modele Piper introuvable pour '%s'", self.voice)
            self._fallback_speak(text)
            return

        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wav_path = f.name

            cmd = [
                self._piper_path,
                "--model", model,
                "--output-file", wav_path,
            ]
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            proc.communicate(input=text.encode("utf-8"), timeout=30)

            if proc.returncode == 0 and os.path.exists(wav_path):
                self._play_wav(wav_path)
            else:
                logger.error("Piper erreux (code %d)", proc.returncode)
                self._fallback_speak(text)

            try:
                os.unlink(wav_path)
            except OSError:
                pass

        except Exception as e:
            logger.error("Erreur Piper: %s", e)
            self._fallback_speak(text)

    def _play_wav(self, path):
        """Joue un fichier WAV."""
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME)
                return
            except Exception:
                pass

            for player in ["vlc", "mplayer", "ffplay"]:
                try:
                    subprocess.run(
                        [player, "--play-and-exit", path],
                        capture_output=True, timeout=30,
                    )
                    return
                except FileNotFoundError:
                    continue
        else:
            for cmd in [
                ["aplay", path],
                ["paplay", path],
                ["vlc", "--play-and-exit", path],
            ]:
                try:
                    subprocess.run(cmd, capture_output=True, timeout=30)
                    return
                except FileNotFoundError:
                    continue

        try:
            import sounddevice as sd
            import scipy.io.wavfile as wav
            rate, data = wav.read(path)
            sd.play(data, rate)
            sd.wait()
        except Exception as e:
            logger.error("Impossible de jouer le WAV: %s", e)

    def _fallback_speak(self, text):
        """Fallback TTS sans Piper."""
        if sys.platform == "win32":
            try:
                import win32com.client
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                speaker.Speak(text)
                return
            except Exception:
                pass

        for cmd in [
            ["espeak", text],
            ["espeak-ng", text],
            ["say", text],
        ]:
            try:
                subprocess.run(cmd, capture_output=True, timeout=30)
                return
            except FileNotFoundError:
                continue

        logger.warning("Aucun TTS disponible pour: '%s'", text[:50])


class _WindowsTTS:
    """TTS via SAPI5 (Windows built-in)."""

    def __init__(self):
        self._speaker = None

    def _ensure(self):
        if self._speaker is not None:
            return True
        try:
            import win32com.client
            self._speaker = win32com.client.Dispatch("SAPI.SpVoice")
            logger.info("SAPI5 TTS initialise")
            return True
        except Exception as e:
            logger.error("SAPI5 non disponible: %s", e)
            return False

    def speak(self, text):
        """Joue le texte via SAPI5 (bloquant)."""
        if self._ensure():
            try:
                self._speaker.Speak(text)
            except Exception as e:
                logger.error("Erreur SAPI5: %s", e)


# ──────────────────────────────────────────────
#  AudioProcessor principal
# ──────────────────────────────────────────────

class AudioProcessor:
    """
    Pont audio complet: Microphone → STT → Pipeline → TTS → Haut-parleur.

    Args:
        pipeline: PhoenixPipeline (de mycroft.pipeline)
        config: dict de config (voice_backend, stt_module, tts_module, etc.)
    """

    def __init__(self, pipeline, config=None):
        self.pipeline = pipeline
        self.config = config or {}

        backend = self.config.get("voice_backend", "phoenix")
        lang = self.config.get("language", "fr")

        # Initialiser STT
        if backend == "windows" or self.config.get("stt_module") == "windows_speech":
            self.stt = _WindowsSTT()
            logger.info("STT: Windows Speech Recognition")
        else:
            model_path = self.config.get("vosk_model_path", "")
            self.stt = _VoskSTT(model_path=model_path, lang=lang)
            logger.info("STT: Vosk (offline)")

        # Initialiser TTS
        if backend == "windows" or self.config.get("tts_module") == "windows":
            self.tts = _WindowsTTS()
            logger.info("TTS: Windows SAPI5")
        else:
            voice = self.config.get("piper_voice", "fr_FR-siwis-medium")
            self.tts = _VoskPiperTTS(voice=voice)
            logger.info("TTS: Piper (offline)")

        # Mot de revel
        self.wake_word = self.config.get("wake_word", "").lower().strip()
        self.wake_word_enabled = self.config.get("wake_word_enabled", True) and bool(self.wake_word)
        self._listening = False

        if self.wake_word_enabled:
            logger.info("Mot de revel: '%s'", self.wake_word)
        else:
            logger.info("Mot de revel desactive — ecoute en continu")

    def _check_wake_word(self, text):
        """
        Verifie si le mot de revel est present dans le texte.
        Retourne la commande (texte sans le wake word) ou None si pas de wake word.

        Detection inclusive : si le wake word est present, on le retire et on
        retourne le reste. Si pas de wake word, on retourne le texte entier.
        """
        if not text:
            return None

        text_lower = text.lower().strip()

        # Si pas de wake word configure, traiter directement
        if not self.wake_word_enabled:
            return text_lower

        # Chercher le wake word dans le texte
        idx = text_lower.find(self.wake_word)
        if idx >= 0:
            after = text_lower[idx + len(self.wake_word):].strip()
            if after:
                logger.debug("Wake word '%s' detecte, commande: '%s'", self.wake_word, after)
                return after
            else:
                logger.debug("Wake word '%s' sans commande", self.wake_word)
                return None

        # Fallback : intents connus sans wake word (evite les faux negatifs Vosk)
        known_intents = [
            "bonjour", "salut", "hello", "hey",
            "au revoir", "goodbye", "bye",
            "merci", "thanks",
            "aide", "help",
            "arrete", "stop",
        ]
        for intent_word in known_intents:
            if intent_word in text_lower:
                logger.debug("Intent connu detecte sans wake word: '%s'", intent_word)
                return text_lower

        return None

    def listen_once(self, duration_sec=5):
        """
        Ecoute une seule phrase et retourne le texte transcrit.
        Utilise VAD pour couper au silence.
        """
        try:
            audio_data = _capture_audio_sounddevice_vad()
        except Exception as e:
            logger.error("Erreur capture audio: %s", e)
            return ""

        if not audio_data:
            return ""

        return self.stt.transcribe(audio_data)

    def speak(self, text):
        """Fait parler le systeme."""
        if not text:
            return
        logger.info("TTS: '%s'", text[:80])
        self.tts.speak(text)

    def process_and_speak(self, text):
        """
        Traite le texte via le pipeline NLU et fait la reponse a voix haute.
        Retourne le dict result du pipeline.
        """
        result = self.pipeline.process(text)
        response = result.get("response", "")

        if response:
            self.speak(response)

        return result

    def run_voice_loop(self):
        """
        Boucle vocale interactive.
        Ecoute → Wake word → STT → Pipeline → TTS → Ecoute...
        'stop' ou Ctrl+C pour quitter.
        """
        print()
        print("=" * 50)
        if self.wake_word_enabled:
            print("  Phoenix — Mode vocal actif")
            print(f"  Mot de revel: « {self.wake_word} »")
            print("  Dites le mot de revel, puis votre commande.")
        else:
            print("  Phoenix — Mode vocal actif")
            print("  Ecoute en continu (pas de mot de revel).")
        print("  Tapez 'stop' en mode texte pour quitter.")
        print("=" * 50)
        print()

        self._listening = True

        try:
            while self._listening:
                try:
                    # 1. Ecouter
                    print("🎤  Ecoute...", end="", flush=True)
                    text = self.listen_once()

                    if not text:
                        print(" (rien detecte)")
                        continue

                    print(f"  → \"{text}\"")

                    # 2. Verifier le mot de revel
                    command = self._check_wake_word(text)
                    if command is None:
                        if self.wake_word_enabled:
                            print(f"  ⏸  Mot de revel non detecte — ignore")
                        continue

                    # 3. Verifier commande d'arret
                    if command.strip() in ("stop", "quit", "arrete", "quitter"):
                        self.speak("Au revoir !")
                        break

                    # 4. Traiter via pipeline
                    result = self.process_and_speak(command)

                    # 5. Afficher
                    intent = result.get("intent", {})
                    intent_name = intent.get("intent", "unknown")
                    confidence = intent.get("confidence", 0.0)
                    response = result.get("response", "")

                    print(f"  🎯 Intent: {intent_name} ({confidence:.2f})")
                    print(f"  🤖 {response}")
                    print()

                except KeyboardInterrupt:
                    print()
                    break
                except EOFError:
                    break

        finally:
            self._listening = False
            print("Mode vocal arrete.")

    def run_text_loop(self):
        """
        Boucle texte interactive (sans microphone).
        Pour les tests ou quand le micro n'est pas disponible.
        """
        print()
        print("  Phoenix — Mode texte")
        print("  Tapez 'quit' pour quitter, 'voice' pour passer en mode vocal")
        print()

        while True:
            try:
                text = input("👤 ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not text:
                continue
            if text.lower() in ("quit", "exit", "q"):
                break
            if text.lower() == "voice":
                self.run_voice_loop()
                continue

            result = self.process_and_speak(text)

            intent = result.get("intent", {})
            print(f"  🎯 {intent.get('intent', '?')} ({intent.get('confidence', 0):.2f})")
            if result.get("safety", {}).get("triggered"):
                print(f"  🛡️  ALERTE SECURITE")
            print(f"  🤖 {result.get('response', '')}")
            print()
