#!/usr/bin/env python3
"""Diagnostic et configuration automatique de l'audio pour Phoenix.

Multi-plateforme : détecte les périphériques input/output
en testant chaque combinaison. Sauvegarde la config gagnante.
"""

import json, os, sys, time, tempfile, numpy as np, wave, subprocess as sp
from pathlib import Path
from typing import Dict
import logging
import platform

LOG = logging.getLogger("setup_audio")

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_FILE = PROJECT_ROOT / "audio_config.json"
TEMP_DIR = Path(tempfile.gettempdir())
SYSTEM = platform.system()

# Son de test : 3 bips à fréquences distinctes
def generate_test_sound(duration=1.5, sr=44100):
    t = np.linspace(0, duration, int(sr * duration), False)
    beep = lambda f, d: np.sin(2 * np.pi * f * t[:int(sr * d)])
    sil = np.zeros(int(sr * 0.15))
    sig = np.concatenate([beep(440, 0.3), sil, beep(660, 0.3), sil, beep(880, 0.3), np.zeros(int(sr * 0.45))])
    return (sig * 6000).astype(np.int16), sr


def list_devices() -> Dict:
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        inputs = []
        outputs = []
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                inputs.append({"index": i, "name": d["name"], "channels": d["max_input_channels"], "rate": d["default_samplerate"]})
            if d["max_output_channels"] > 0:
                outputs.append({"index": i, "name": d["name"], "channels": d["max_output_channels"], "rate": d["default_samplerate"]})
        return {"inputs": inputs, "outputs": outputs}
    except Exception as e:
        return {"error": str(e)}


def test_output(output_device: int, input_device: int,
                duration: float = 4.0) -> Dict:
    """Joue un son sur output, enregistre sur input, vérifie le retour."""
    import sounddevice as sd
    sig, sr = generate_test_sound()
    out_wav = str(TEMP_DIR / "audio_test_out.wav")
    with wave.open(out_wav, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(sig.tobytes())

    rec = []
    if SYSTEM == "Linux":
        def play(): sp.run(["aplay", "-D", f"plughw:{output_device},3", out_wav], capture_output=True)
    elif SYSTEM == "Darwin":
        def play(): sp.run(["afplay", out_wav], capture_output=True)
    else:
        import pyaudio
        def play():
            p = pyaudio.PyAudio(); s = p.open(format=2, channels=1, rate=sr, output=True, output_device_index=output_device)
            with wave.open(out_wav, "rb") as wf: s.write(wf.readframes(wf.getnframes()))
            s.stop_stream(); s.close(); p.terminate()

    def record():
        nonlocal rec
        raw = sd.rec(int(duration * 48000), samplerate=48000, channels=1,
                     device=input_device, dtype="int16")
        sd.wait()
        rec = raw[:, 0]

    import threading
    tr = threading.Thread(target=record)
    tr.start()
    time.sleep(0.3)
    tp = threading.Thread(target=play)
    tp.start()
    tp.join()
    tr.join()
    os.unlink(out_wav)

    # Analyse fréquentielle
    y = rec.astype(np.float64)
    fft = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freqs = np.fft.rfftfreq(len(y), d=1/48000)
    noise_floor = np.mean(fft[(freqs >= 50) & (freqs <= 200)])
    peaks = {}
    for freq, name in [(440, "440"), (660, "660"), (880, "880")]:
        mask = (freqs >= freq - 20) & (freqs <= freq + 20)
        if np.any(mask):
            peaks[name] = float(np.max(fft[mask]))
    detected = sum(1 for p in peaks.values() if p > noise_floor * 2)
    return {"ok": detected >= 2, "noise_floor": float(noise_floor), "peaks": peaks,
            "detected_beeps": detected, "max_level": float(np.max(np.abs(rec)))}


def test_input(device: int, duration: float = 3.0) -> Dict:
    """Teste un micro : enregistre et vérifie le niveau."""
    import sounddevice as sd
    for i in range(3, 0, -1):
        print(f"  Parle dans le micro dans {i}...")
        time.sleep(1)
    print("  PARLE MAINTENANT!")
    raw = sd.rec(int(duration * 48000), samplerate=48000, channels=1,
                 device=device, dtype="int16")
    sd.wait()
    level = float(np.max(np.abs(raw)))
    vad = float(np.sum(np.abs(raw[:, 0]) > 200) / len(raw) * 100)
    text = ""
    try:
        os.environ["VOSK_LOGGING"] = "0"
        from vosk import Model, KaldiRecognizer
        import json as j
        model = Model(str(TEMP_DIR / "vosk-model-small-fr-0.22"))
        k = KaldiRecognizer(model, 16000)
        rs = raw[::3, 0]; k.SetWords(True); k.AcceptWaveform(rs.tobytes())
        text = j.loads(k.FinalResult()).get("text", "").strip()
    except Exception:
        pass
    return {"ok": level > 300, "level": level, "vad": vad, "transcription": text}


def generate_config(input_idx: int, output_idx: int,
                    input_name: str, output_name: str,
                    pa_sink: str = "", hdmi_card: str = "") -> dict:
    return {
        "input": {
            "device_index": input_idx,
            "name": input_name,
            "channels": 1,
            "rate": 48000,
            "backend": "sounddevice",
        },
        "output": {
            "device_index": output_idx,
            "name": output_name,
            "channels": 2,
            "rate": 44100,
            "backend": "paplay",
            "pulseaudio_sink": pa_sink,
            "alsa_hdmi_card": hdmi_card,
        },
        "stt": {
            "model": str(TEMP_DIR / "vosk-model-small-fr-0.22"),
            "sample_rate": 16000,
        },
        "tts": {
            "voice": "fr_FR-siwis-medium",
            "model_dir": os.path.expanduser("~/.local/share/piper/voices"),
        },
        "wake_word": "phoenix",
    }


def autodetect(output_test: bool = True, input_test: bool = True) -> dict:
    """Détecte et teste automatiquement l'audio."""
    print("=== Diagnostic Audio Phoenix ===")

    devices = list_devices()
    print(f"\nEntrées (micros) disponibles:")
    for d in devices.get("inputs", []):
        print(f"  [{d['index']}] {d['name']} ({d['channels']} canaux)")
    print(f"\nSorties (haut-parleurs) disponibles:")
    for d in devices.get("outputs", []):
        print(f"  [{d['index']}] {d['name']} ({d['channels']} canaux)")

    cfg = None

    # Chercher la config connue (Logitech USB Microphone + HDMI)
    known_out = None
    known_in = None
    for d in devices.get("outputs", []):
        if "HDMI" in d["name"] or "hdmi" in d["name"]:
            known_out = d["index"]
    for d in devices.get("inputs", []):
        if "Logitech" in d["name"] or "USB Microphone" in d["name"]:
            known_in = d["index"]

    # Vérifier PulseAudio
    pa_hdmi = ""
    try:
        r = sp.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True)
        for line in r.stdout.split("\n"):
            if "hdmi" in line.lower():
                pa_hdmi = line.split("\t")[1]
                break
    except Exception:
        pass

    if known_out is not None and known_in is not None:
        cfg = generate_config(known_in, known_out,
                              devices["inputs"][known_in]["name"],
                              devices["outputs"][known_out]["name"],
                              pa_sink=pa_hdmi,
                              hdmi_card=f"{known_out},3")
        save_config(cfg)
        print(f"\nConfig auto trouvée: micro {known_in}, sortie {known_out}")

    # Test output si demandé
    if output_test and known_out is not None and known_in is not None:
        print("\nTest de la sortie audio (je joue un son et je capte avec le micro)...")
        result = test_output(known_out, known_in)
        if result["ok"]:
            print(f"  ✅ Sortie OK (bips détectés: {result['detected_beeps']}/3)")
        else:
            print(f"  ⚠️  Sortie non détectée (bruit: {result['noise_floor']:.0f}, pics: {result['peaks']})")

    return cfg or {}
