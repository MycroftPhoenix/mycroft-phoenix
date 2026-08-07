#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Voice Loop Phoenix - STT → Hub → Pipeline → TTS
Multi-plateforme, auto-détection audio, zéro dépendance Mycroft.
"""

import os
import sys
import io
import re
import unicodedata
import time
import wave
import json
import queue
import threading
import subprocess
import platform
import tempfile
import signal
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vosk import Model, KaldiRecognizer
import numpy as np
from mycroft.pipeline import PhoenixPipeline
from mycroft.messagebus import get_hub, InternalMessage
from mycroft.audio.wakeword_fr import VoskGrammarWakeWord
from mycroft.skills.storyteller import create_skill

CONFIG_FILE = PROJECT_ROOT / "audio_config.json"
TEMP_DIR = Path(tempfile.gettempdir())

PA_CONTINUE = 1  # pyaudio.paContinue (callback doit retourner un tuple sur Windows)


def load_audio_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def find_model_dir() -> str:
    candidates = [
        str(TEMP_DIR / "vosk-model-small-fr-0.22"),
        str(PROJECT_ROOT / "data" / "vosk-model-small-fr-0.22"),
        str(Path.home() / ".config" / "mycroft" / "vosk" / "vosk-model-small-fr-0.22"),
        str(Path.home() / ".config" / "mycroft" / "vosk" / "model"),
        str(Path.home() / "vosk-model-small-fr-0.22"),
        str(Path(os.environ.get("APPDATA", "")) / "mycroft" / "vosk" / "model"),
        "vosk-model-small-fr-0.22",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return candidates[0]


def list_devices():
    """Liste tous les périphériques audio."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        inputs, outputs = [], []
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                inputs.append({"index": i, "name": d["name"]})
            if d["max_output_channels"] > 0:
                outputs.append({"index": i, "name": d["name"]})
        return {"inputs": inputs, "outputs": outputs}
    except Exception:
        return {"inputs": [], "outputs": []}


def autodetect_audio() -> dict:
    """Détecte la configuration audio automatiquement."""
    config = load_audio_config()
    if config.get("input", {}).get("device_index") is not None:
        return config

    devs = list_devices()
    cfg = {
        "input": {"device_index": 0, "name": "default", "channels": 1, "rate": 48000, "backend": "sounddevice"},
        "output": {"device_index": 0, "name": "default", "channels": 2, "rate": 44100, "backend": "paplay", "pulseaudio_sink": "", "alsa_hdmi_card": ""},
        "stt": {"model": find_model_dir(), "sample_rate": 16000},
        "tts": {"voice": "fr_FR-siwis-medium", "model_dir": str(Path.home() / ".local" / "share" / "piper" / "voices")},
        "wake_word": "phoenix",
    }

    # Chercher micro USB Logitech
    for d in devs["inputs"]:
        if "Logitech" in d["name"] or "USB" in d["name"]:
            cfg["input"]["device_index"] = d["index"]
            cfg["input"]["name"] = d["name"]
            break
    if cfg["input"]["name"] == "default" and devs["inputs"]:
        cfg["input"]["device_index"] = devs["inputs"][0]["index"]
        cfg["input"]["name"] = devs["inputs"][0]["name"]

    # Chercher sortie HDMI
    for d in devs["outputs"]:
        if "HDMI" in d["name"] or "hdmi" in d["name"]:
            cfg["output"]["device_index"] = d["index"]
            cfg["output"]["name"] = d["name"]
            cfg["output"]["alsa_hdmi_card"] = f"{d['index']},3"
            break
    if cfg["output"]["name"] == "default" and devs["outputs"]:
        cfg["output"]["device_index"] = devs["outputs"][0]["index"]
        cfg["output"]["name"] = devs["outputs"][0]["name"]

    # Chercher PulseAudio sink HDMI
    try:
        r = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=3)
        for line in r.stdout.split("\n"):
            if "hdmi" in line.lower():
                cfg["output"]["pulseaudio_sink"] = line.split("\t")[1]
                break
    except Exception:
        pass

    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    print(f"[Audio] Config sauvegardée: {CONFIG_FILE}")
    return cfg


def play_beep(config: dict, freq: int = 440, dur: float = 0.15,
              n_bips: int = 1):
    """Joue un/des bip(s) sur la sortie configurée (multi-plateforme)."""
    import numpy as np
    sr = 44100
    sig = np.array([], dtype=np.int16)
    gap = int(sr * 0.08)
    for _ in range(n_bips):
        t = np.linspace(0, dur, int(sr * dur), False)
        beep = (np.sin(2 * np.pi * freq * t) * 6000).astype(np.int16)
        sig = np.concatenate([sig, beep, np.zeros(gap, dtype=np.int16)])
    wav = str(TEMP_DIR / "phoenix_beep.wav")
    with wave.open(wav, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(sig.tobytes())

    _platform = platform.system()
    out = config.get("output", {})
    try:
        if _platform == "Linux":
            pa_sink = out.get("pulseaudio_sink", "")
            if pa_sink:
                subprocess.run(["paplay", "-d", pa_sink, wav], capture_output=True)
            else:
                subprocess.run(["aplay", "-D", f"plughw:{out.get('alsa_hdmi_card', '0,3')}", wav], capture_output=True)
        elif _platform == "Darwin":
            subprocess.run(["afplay", wav], capture_output=True)
        elif _platform == "Windows":
            import pyaudio
            with wave.open(wav, "rb") as wf:
                p = pyaudio.PyAudio()
                s = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                           channels=wf.getnchannels(), rate=wf.getframerate(), output=True)
                data = wf.readframes(1024)
                while data:
                    s.write(data)
                    data = wf.readframes(1024)
                s.stop_stream(); s.close(); p.terminate()
    except Exception as e:
        print(f"[Audio] Impossible de jouer le bip: {e}")
    if os.path.exists(wav):
        os.unlink(wav)


def play_wake_beep(config: dict):
    """Bip de confirmation quand le wake word est capté."""
    play_beep(config, freq=880, dur=0.12, n_bips=2)


def play_test_sound(config: dict):
    """Joue un son de confirmation sur la sortie configurée (multi-plateforme)."""
    play_beep(config, freq=440, dur=0.5, n_bips=1)


class VoskStreamingSTT:
    """Vosk STT streaming multi-plateforme."""
    def __init__(self, model_path: str, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Modèle Vosk introuvable: {model_path}")
        self._model = Model(model_path)
        self._rec = KaldiRecognizer(self._model, sample_rate)
        print(f"[Vosk] Modèle chargé: {model_path}")

    def process_chunk(self, audio_data: bytes) -> tuple:
        if self._rec.AcceptWaveform(audio_data):
            result = json.loads(self._rec.Result())
            text = result.get('text', '').strip()
            if text:
                return text, True
        partial = json.loads(self._rec.PartialResult())
        return partial.get('partial', '').strip(), False


class PiperTTS:
    """Piper TTS local, multi-plateforme."""
    def __init__(self, voice: str = "fr_FR-siwis-medium", config: dict = None):
        self.voice = voice
        self.config = config or {}
        self._platform = platform.system()
        self.piper_path = self._find_piper()
        self.model_path = self._find_model()

    def _find_piper(self) -> str:
        if self._platform == "Windows":
            candidates = [
                "C:/piper/piper/piper.exe",
                str(Path.home() / "piper" / "piper.exe"),
                str(Path.home() / "AppData" / "Local" / "piper" / "piper.exe"),
            ]
        else:
            candidates = ["/usr/bin/piper", "/usr/local/bin/piper", "piper"]
        for c in candidates:
            if Path(c).exists():
                return c
        try:
            subprocess.run(["piper", "--version"], capture_output=True, check=True)
            return "piper"
        except Exception:
            pass
        print("[Piper] Binaire introuvable — vérifie l'installation")
        return "piper"

    def _find_model(self) -> str:
        if self._platform == "Windows":
            data_dirs = [
                Path("C:/piper/voices"),
                Path.home() / "AppData" / "Local" / "piper" / "voices",
            ]
        else:
            data_dirs = [
                Path.home() / ".local" / "share" / "piper" / "voices",
                Path("/usr/share/piper/voices"),
                Path("/opt/piper/voices"),
            ]
        for d in data_dirs:
            model = d / f"{self.voice}.onnx"
            if model.exists():
                return str(model)
        # Fallback: répertoire du modèle depuis config
        model_dir = self.config.get("tts", {}).get("model_dir", "")
        if model_dir:
            model = Path(model_dir) / f"{self.voice}.onnx"
            if model.exists():
                return str(model)
        print(f"[Piper] Modèle introuvable: {self.voice}")
        return ""

    @staticmethod
    def _sanitize_fr(text: str) -> str:
        """Workaround piper.exe/espeak-ng: le caractere accentue 'e-aigu' est
        bafouille ('etait' -> 'a-t-il cooperer'). Valide sur phrase reelle
        (2026-08-06) : desaccentuer (NFD strip Mn) avant envoi a Piper donne
        un audio propre et naturel sur siwis-medium ET mls-medium, car
        espeak-ng devine les accents du contexte."""
        if not any(unicodedata.combining(c) for c in unicodedata.normalize('NFD', text)):
            return text
        return ''.join(c for c in unicodedata.normalize('NFD', text)
                       if unicodedata.category(c) != 'Mn')

    def synthesize(self, text: str) -> bytes:
        if not self.model_path or not Path(self.model_path).exists():
            return b""
        text = self._sanitize_fr(text)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_file = f.name
        try:
            cmd = [
                self.piper_path, "--model", self.model_path,
                "--output_file", wav_file,
                "--noise-scale", "0.667", "--length-scale", "1.0", "--noise-w", "0.8",
            ]
            proc = subprocess.run(cmd, input=text.encode("utf-8"),
                                  capture_output=True, timeout=30)
            if proc.returncode != 0:
                return b""
            audio = Path(wav_file).read_bytes()
            os.unlink(wav_file)
            return audio
        except Exception as e:
            print(f"[Piper] Erreur: {e}")
            if os.path.exists(wav_file):
                os.unlink(wav_file)
            return b""

    def play_audio(self, audio_data: bytes):
        if not audio_data:
            return
        out = self.config.get("output", {})
        pa_sink = out.get("pulseaudio_sink", "")
        # FIX concurrence: nom de fichier unique par appel (evite qu'un thread
        # ecrase l'audio en cours de lecture d'un autre thread -- cause du
        # bug "audio different du texte affiche" avec le web chat threaded=True)
        import uuid as _uuid
        wav = str(TEMP_DIR / f"phoenix_play_{_uuid.uuid4().hex[:8]}.wav")
        try:
            with wave.open(io.BytesIO(audio_data), "rb") as wf:
                Path(wav).write_bytes(wf.readframes(wf.getnframes()))
            if self._platform == "Linux":
                if pa_sink:
                    subprocess.run(["paplay", "-d", pa_sink, wav], capture_output=True)
                else:
                    alsa = out.get("alsa_hdmi_card", "0,3")
                    subprocess.run(["aplay", "-D", f"plughw:{alsa}", wav], capture_output=True)
            elif self._platform == "Windows":
                import pyaudio
                # FIX 2026-08-04: utiliser le device de sortie CONFIGURE (device_index)
                # au lieu du device par defaut, et resampler a son taux si besoin.
                # Avant: le device HDMI (index 35) etait ignore -> audio sur le mauvais
                # haut-parleur et voix deformee ("weird") car Piper sort en 22050 Hz
                # alors que le device est en 44100 Hz.
                dev_idx = int(out.get("device_index", -1))
                p = pyaudio.PyAudio()
                try:
                    if dev_idx < 0 or dev_idx >= p.get_device_count():
                        dev_idx = p.get_default_output_device_info()["index"]
                    dev_info = p.get_device_info_by_index(dev_idx)
                    dev_rate = int(dev_info["defaultSampleRate"])
                except Exception:
                    dev_idx = p.get_default_output_device_info()["index"]
                    dev_info = p.get_device_info_by_index(dev_idx)
                    dev_rate = int(dev_info["defaultSampleRate"])
                try:
                    with wave.open(io.BytesIO(audio_data), "rb") as wf:
                        wav_rate = wf.getframerate()
                        wav_ch = wf.getnchannels()
                        wav_width = wf.getsampwidth()
                        frames = wf.readframes(wf.getnframes())
                    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
                    # Resample si le taux du WAV differe du device (Piper=22050, device=44100)
                    if wav_rate != dev_rate:
                        ratio = dev_rate / float(wav_rate)
                        n_out = int(round(audio.shape[0] * ratio))
                        x_old = np.linspace(0, 1, num=audio.shape[0], endpoint=False)
                        x_new = np.linspace(0, 1, num=n_out, endpoint=False)
                        audio = np.interp(x_new, x_old, audio).astype(np.float32)
                        wav_rate = dev_rate
                    s = p.open(
                        format=pyaudio.paInt16,
                        channels=wav_ch,
                        rate=wav_rate,
                        output=True,
                        output_device_index=dev_idx,
                    )
                    s.write(audio.astype(np.int16).tobytes())
                    s.stop_stream(); s.close()
                finally:
                    p.terminate()
            elif self._platform == "Darwin":
                with wave.open(io.BytesIO(audio_data), "rb") as wf:
                    Path(wav).write_bytes(wf.readframes(wf.getnframes()))
                subprocess.run(["afplay", wav], capture_output=True)
            if os.path.exists(wav):
                os.unlink(wav)
        except Exception as e:
            print(f"[Piper] Erreur lecture: {e}")


class VoiceLoop:
    """Boucle vocale complète: STT → Hub → Pipeline → TTS
    Multi-plateforme, auto-détection audio."""
    
    def __init__(
        self,
        vosk_model: str = None,
        piper_voice: str = "fr_FR-siwis-medium",
        sample_rate: int = 16000,
        chunk_size: int = 4000,
        config: dict = None,
    ):
        self.config = config or autodetect_audio()
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.running = False
        self.audio_queue = queue.Queue()
        self.armed = False   # wake word détecté → capture la phrase suivante
        self._capture_start = 0.0

        # STT
        model_path = vosk_model or self.config.get("stt", {}).get("model", find_model_dir())
        stt_rate = self.config.get("stt", {}).get("sample_rate", sample_rate)
        self.stt = VoskStreamingSTT(model_path, stt_rate)

        # Wake word FR (Vosk grammar "phoenix")
        try:
            self.wake = VoskGrammarWakeWord(model_dir=model_path)
            print(f"[WakeWord] Vosk FR actif (mot: {self.wake.wake_word})")
        except Exception as e:
            print(f"[WakeWord] Désactivé: {e}")
            self.wake = None

        # TTS: supertonic par défaut (accent FR correct, zéro glitch 'é'),
        # fallback Piper si indisponible. Config: tts.engine = 'supertonic'|'piper'.
        tts_cfg = self.config.get("tts", {})
        engine = tts_cfg.get("engine", "supertonic")
        self.tts = None
        if engine == "supertonic":
            try:
                from mycroft.audio.supertonic_tts import SupertonicTTS
                super_voice = tts_cfg.get("supertonic_voice", "fr-0")
                super_tts = SupertonicTTS(super_voice, self.config)
                # Câbler le playback : réutilise le lecteur audio de Piper
                # (même device, resampling), on remplace seulement la synthèse.
                super_tts.config["_play_audio_fn"] = self._play_audio_fn
                self.tts = super_tts
                print(f"[TTS] Supertonic-3 actif (voix {super_voice})")
            except Exception as e:
                print(f"[TTS] Supertonic indisponible ({e}), fallback Piper")
                self.tts = None
        if self.tts is None:
            self.tts = PiperTTS(piper_voice, self.config)
            print("[TTS] Piper actif")

        # Pipeline
        self.pipeline = PhoenixPipeline(str(PROJECT_ROOT))
        self.hub = get_hub()
        self.hub.on("phoenix.speak", self._on_speak)

        # Skill storyteller (histoires pour enfants). subscribe=False :
        # le routing se fait dans _handle_utterance_locked (priorite skill).
        try:
            self.storyteller = create_skill()
            self.storyteller.init(self.hub, subscribe=False, tts=self.tts)
            print("[Storyteller] Skill histoire initialisée")
        except Exception as e:
            print(f"[Storyteller] Désactivée: {e}")
            self.storyteller = None

        # Interface web (serveur Flask en thread daemon)
        self.web = None
        web_cfg = self.config.get("web", {})
        if web_cfg.get("enabled", True):
            try:
                from mycroft.web.server import WebServer
                self.web = WebServer(
                    hub=self.hub,
                    host=web_cfg.get("host", "127.0.0.1"),
                    port=web_cfg.get("port", 8181),
                    username=web_cfg.get("username"),
                    password=web_cfg.get("password"),
                )
                print("[WebUI] Interface web préparée")
            except Exception as e:
                print(f"[WebUI] Désactivée: {e}")
                self.web = None

        self._platform = platform.system()
        self._sd_stream = None

        print("[VoiceLoop] Initialisé")

    def _on_speak(self, message: InternalMessage):
        utterance = message.data.get("utterance", "")
        meta = message.data.get("meta") or {}
        audio = meta.get("audio")
        if audio:
            # Audio pré-synthétisé (storyteller multi-voix) : jouer tel quel.
            print(f"[TTS] (audio multi-voix) {utterance[:80]}")
            self.tts.play_audio(audio)
            return
        if utterance:
            print(f"[TTS] {utterance}")
            audio = self.tts.synthesize(utterance)
            if audio:
                self.tts.play_audio(audio)

    def _play_audio_fn(self, audio_data: bytes, config: dict = None):
        """Joue des bytes WAV sur le device configuré (réutilisé par Supertonic)."""
        cfg = config or self.config
        import uuid as _uuid
        wav = str(TEMP_DIR / f"phoenix_play_{_uuid.uuid4().hex[:8]}.wav")
        try:
            with wave.open(io.BytesIO(audio_data), "rb") as wf:
                Path(wav).write_bytes(wf.readframes(wf.getnframes()))
            if self._platform == "Linux":
                pa_sink = cfg.get("output", {}).get("pulseaudio_sink", "")
                if pa_sink:
                    subprocess.run(["paplay", "-d", pa_sink, wav], capture_output=True)
                else:
                    alsa = cfg.get("output", {}).get("alsa_hdmi_card", "0,3")
                    subprocess.run(["aplay", "-D", f"plughw:{alsa}", wav], capture_output=True)
            elif self._platform == "Windows":
                import pyaudio
                dev_idx = int(cfg.get("output", {}).get("device_index", -1))
                p = pyaudio.PyAudio()
                try:
                    if dev_idx < 0 or dev_idx >= p.get_device_count():
                        dev_idx = p.get_default_output_device_info()["index"]
                    dev_info = p.get_device_info_by_index(dev_idx)
                    dev_rate = int(dev_info["defaultSampleRate"])
                except Exception:
                    dev_idx = p.get_default_output_device_info()["index"]
                    dev_info = p.get_device_info_by_index(dev_idx)
                    dev_rate = int(dev_info["defaultSampleRate"])
                try:
                    with wave.open(io.BytesIO(audio_data), "rb") as wf:
                        wav_rate = wf.getframerate()
                        wav_ch = wf.getnchannels()
                        wav_width = wf.getsampwidth()
                        frames = wf.readframes(wf.getnframes())
                    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
                    if wav_rate != dev_rate:
                        ratio = dev_rate / float(wav_rate)
                        n_out = int(round(audio.shape[0] * ratio))
                        x_old = np.linspace(0, 1, num=audio.shape[0], endpoint=False)
                        x_new = np.linspace(0, 1, num=n_out, endpoint=False)
                        audio = np.interp(x_new, x_old, audio).astype(np.float32)
                        wav_rate = dev_rate
                    s = p.open(
                        format=pyaudio.paInt16,
                        channels=wav_ch,
                        rate=wav_rate,
                        output=True,
                        output_device_index=dev_idx,
                    )
                    s.write(audio.astype(np.int16).tobytes())
                    s.stop_stream(); s.close()
                finally:
                    p.terminate()
            elif self._platform == "Darwin":
                with wave.open(io.BytesIO(audio_data), "rb") as wf:
                    Path(wav).write_bytes(wf.readframes(wf.getnframes()))
                subprocess.run(["afplay", wav], capture_output=True)
            if os.path.exists(wav):
                os.unlink(wav)
        except Exception as e:
            print(f"[Piper] Erreur lecture: {e}")

    def initialize_pipeline(self):
        print("[Pipeline] Initialisation...")
        self.pipeline.initialize()
        print("[Pipeline] Prêt")

    def _audio_callback(self, in_data, frames, time_info, status):
        self.audio_queue.put(bytes(in_data))
        if self._platform == "Windows":
            return (None, PA_CONTINUE)
        return None

    def _stt_loop(self):
        wake = self.wake
        # durée de capture de la phrase après le wake word (en secondes)
        capture_window = 5.0
        while self.running:
            try:
                chunk = self.audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                # 1) On écoute le wake word (Vosk FR) tant qu'on n'est pas armé
                if wake is not None and not self.armed:
                    if wake.detect(np.frombuffer(chunk, dtype=np.int16)):
                        self.armed = True
                        self._capture_start = time.time()
                        self.stt._rec.Reset()
                        # Bip de confirmation (non bloquant pour la capture)
                        try:
                            threading.Thread(
                                target=play_wake_beep, args=(self.config,), daemon=True
                            ).start()
                        except Exception:
                            pass
                        print(f"[WakeWord] '{wake.wake_word}' détecté — capture {capture_window:.0f}s")
                    continue

                # 2) Armé : on envoie l'audio au STT pour reconnaître la phrase
                text, is_final = self.stt.process_chunk(chunk)
                if text and is_final:
                    print(f"[STT] Final: {text}")
                    self.hub.emit("recognizer_loop:utterance", {"utterances": [text]})
                    self.armed = False

                # Timeout de capture : on réarme l'écoute du wake word
                if self.armed and time.time() - self._capture_start > capture_window:
                    print("[WakeWord] Fin de fenêtre de capture — réécoute")
                    self.armed = False
                    self.stt._rec.Reset()
            except Exception as e:
                print(f"[STT] Erreur: {e}")

    def _process_loop(self):
        # FIX concurrence: le web chat (Flask threaded=True) et la boucle
        # vocale peuvent toutes deux emettre "recognizer_loop:utterance" sur
        # des threads differents. Sans verrou, deux appels Ollama+TTS peuvent
        # tourner en parallele et melanger leur audio (fichier temp partage,
        # texte affiche vs audio joue desynchronises). Un seul traitement a
        # la fois, peu importe la source (voix ou web).
        processing_lock = threading.Lock()

        def handle_utterance(message: InternalMessage):
            text = message.data.get("utterances", [""])[0]
            if not text:
                return
            if not processing_lock.acquire(blocking=False):
                print(f"[Pipeline] Occupe, requete ignoree: {text}")
                return
            try:
                self._handle_utterance_locked(text)
            finally:
                processing_lock.release()

        self.hub.on("recognizer_loop:utterance", handle_utterance)
        while self.running:
            time.sleep(0.1)

    def _handle_utterance_locked(self, text: str):
        """Traitement complet d'une utterance -- appele avec le verrou
        de traitement deja acquis (une seule instance a la fois)."""
        print(f"[Pipeline] Traitement: {text}")

        # Priorite skill storyteller : si l'utilisateur demande une
        # histoire, on ne passe pas par le pipeline (sinon double reponse).
        if self.storyteller is not None:
            intent = self.storyteller._detect_story_intent(text.lower())
            if intent:
                print(f"[Storyteller] Intent: {intent}")
                self.storyteller._handle_utterance(
                    InternalMessage("recognizer_loop:utterance",
                                    {"utterances": [text]})
                )
                return

        context = ""
        try:
            context = self.pipeline.research_context(text, top_k=2)
        except Exception:
            pass

        result = self.pipeline.process(text, context=context)
        response = result.get("response", "")
        intent = result.get("intent", {}).get("intent", "unknown")
        confidence = result.get("intent", {}).get("confidence", 0.0)
        severity = result.get("intent", {}).get("severity", 0)
        print(f"[Pipeline] Intent: {intent} (conf: {confidence:.2f}, sev: {severity})")

        try:
            if hasattr(self.pipeline, 'kuzu_manager') and self.pipeline.kuzu_manager:
                self.pipeline.kuzu_manager.log_conversation(
                    user_input=text, response=response,
                    intent=intent, confidence=confidence,
                    source="voice_loop"
                )
        except Exception:
            pass

        if response:
            self.hub.emit("phoenix.speak", {"utterance": response})

    def start(self):
        if self.running:
            return
        self.running = True
        self.initialize_pipeline()

        # Interface web : démarrage en thread daemon
        if self.web is not None:
            self.web.set_status(
                model=self.pipeline.current_model,
                voice=getattr(self.tts, "voice", ""),
                wake_word=getattr(self.wake, "wake_word", "phoenix") if self.wake else "désactivé",
            )
            self.web.pipeline_ready = True
            try:
                self.web.start()
            except Exception as e:
                print(f"[WebUI] Erreur démarrage: {e}")

        self.stt_thread = threading.Thread(target=self._stt_loop, daemon=True)
        self.stt_thread.start()
        self.process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self.process_thread.start()

        # Stream audio via sounddevice (Linux) ou pyaudio (Windows)
        dev_idx = self.config.get("input", {}).get("device_index")
        if self._platform == "Linux":
            import sounddevice as sd
            self._sd_stream = sd.InputStream(
                device=dev_idx,
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                callback=self._audio_callback,
            )
            self._sd_stream.start()
        else:
            import pyaudio
            self._pa = pyaudio.PyAudio()
            self._pa_stream = self._pa.open(
                format=pyaudio.paInt16, channels=1, rate=self.sample_rate,
                input=True, frames_per_buffer=self.chunk_size,
                stream_callback=self._audio_callback,
            )
            self._pa_stream.start_stream()

        print("[VoiceLoop] En écoute... (Ctrl+C pour arrêter)")

    def stop(self):
        print("[VoiceLoop] Fermeture en cours...")
        self.running = False
        if self._platform == "Linux" and self._sd_stream:
            self._sd_stream.stop()
        elif hasattr(self, "_pa_stream") and self._pa_stream:
            self._pa_stream.stop_stream()
            self._pa_stream.close()
            self._pa.terminate()

        # Arrêt résilient du pipeline
        if hasattr(self, "pipeline") and self.pipeline:
            try:
                self.pipeline.shutdown()
            except Exception as e:
                print(f"[VoiceLoop] Erreur arrêt pipeline: {e}")

        print("[VoiceLoop] Arrêté")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Phoenix Voice Loop")
    parser.add_argument("--vosk-model", help="Chemin vers le modèle Vosk")
    parser.add_argument("--piper-voice", default="fr_FR-siwis-medium", help="Voix Piper")
    parser.add_argument("--sample-rate", type=int, default=16000, help="Sample rate audio")
    parser.add_argument("--setup", action="store_true", help="Lancer le wizard de configuration")
    parser.add_argument("--list-models", action="store_true", help="Afficher les modèles disponibles")
    parser.add_argument("--autodetect", action="store_true", help="Forcer la re-détection audio")
    parser.add_argument("--diagnostic", action="store_true", help="Lancer le diagnostic audio")
    args = parser.parse_args()

    # Diagnostic
    if args.diagnostic:
        from mycroft.setup_audio import list_devices, test_output, test_input
        devs = list_devices()
        print("\nPériphériques détectés:")
        print("  Entrées:")
        for d in devs.get("inputs", []):
            print(f"    [{d['index']}] {d['name']} ({d['channels']} canaux)")
        print("  Sorties:")
        for d in devs.get("outputs", []):
            print(f"    [{d['index']}] {d['name']} ({d['channels']} canaux)")
        if devs.get("inputs") and devs.get("outputs"):
            print("\nTest boucle audio (sortie → micro)...")
            r = test_output(devs["outputs"][0]["index"], devs["inputs"][0]["index"])
            print(f"  Résultat: {'OK' if r['ok'] else 'ÉCHEC'} (bips: {r['detected_beeps']}/3)")
        return 0

    # Forcer autodetect
    if args.autodetect:
        cfg = autodetect_audio()
        play_test_sound(cfg)
        print("Configuration audio terminée.")
        return 0

    pipeline = PhoenixPipeline(str(PROJECT_ROOT))

    if args.setup:
        pipeline.setup_wizard()
        return 0

    if args.list_models:
        models = pipeline.get_available_models()
        print("\nModèles disponibles:")
        for m in models:
            dflt = " (défaut)" if m.get("default") else ""
            print(f"  - {m['id']}: {m['name']}{dflt}")
            print(f"    {m['description']}, RAM: {m['ram_required']}")
        print(f"\nModèle actuel: {pipeline.current_model}")
        return 0

    # Config avec autodetect
    cfg = load_audio_config()
    if not cfg:
        print("[Audio] Aucune config trouvée, autodétection...")
        cfg = autodetect_audio()
        play_test_sound(cfg)

    vosk_model = args.vosk_model or cfg.get("stt", {}).get("model", find_model_dir())
    if not Path(vosk_model).exists():
        print(f"Modèle Vosk introuvable: {vosk_model}")
        return 1

    loop = VoiceLoop(vosk_model=vosk_model, piper_voice=args.piper_voice,
                     sample_rate=args.sample_rate, config=cfg)
    try:
        loop.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[VoiceLoop] Arrêt demandé...")
    finally:
        loop.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())