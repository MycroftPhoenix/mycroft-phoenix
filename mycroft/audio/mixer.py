#!/usr/bin/env python3
"""
Mixer audio découplé pour Phoenix.

Gère la concaténation, le mixage et la lecture audio
indépendamment de voice_loop.py et des skills.
"""

import io
import os
import wave
import subprocess
import platform
from typing import List, Optional, Dict, Any
import numpy as np


class AudioMixer:
    """
    Mixeur audio simple : concaténation WAV + lecture sur device configuré.

    Usage:
        mixer = AudioMixer(config)
        audio = mixer.concat_segments([wav1, wav2, wav3], pause_ms=180)
        mixer.play(audio)
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._platform = platform.system()

    def concat_segments(
        self,
        wav_segments: List[bytes],
        pause_ms: int = 180,
        crossfade_ms: int = 0
    ) -> bytes:
        """
        Concatène plusieurs segments WAV (mono 16-bit, même sample rate).

        Args:
            wav_segments: Liste de bytes WAV
            pause_ms: Pause en ms entre segments (défaut 180ms)
            crossfade_ms: Crossfade en ms (0 = pas de crossfade)

        Returns:
            bytes: WAV unique concaténé
        """
        if not wav_segments:
            return b""

        chunks = []
        rate = None
        for wav in wav_segments:
            if not wav:
                continue
            try:
                with wave.open(io.BytesIO(wav), "rb") as wf:
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

        pause = int(rate * pause_ms / 1000) * 2  # 2 octets/échantillon
        silence = b"\x00" * pause

        if crossfade_ms > 0 and len(chunks) > 1:
            return self._concat_with_crossfade(chunks, rate, crossfade_ms)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(silence.join(chunks))
        return buf.getvalue()

    def _concat_with_crossfade(
        self, chunks: List[bytes], rate: int, crossfade_ms: int
    ) -> bytes:
        """Concaténation avec crossfade linéaire entre segments."""
        cf_samples = int(rate * crossfade_ms / 1000)
        all_samples = []
        for i, chunk in enumerate(chunks):
            samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
            if i > 0 and cf_samples > 0:
                # Crossfade avec segment précédent
                prev = all_samples[-cf_samples:] if len(all_samples) >= cf_samples else all_samples
                fade_in = np.linspace(0, 1, min(cf_samples, len(samples)))
                fade_out = np.linspace(1, 0, min(cf_samples, len(prev)))
                crossfade = prev * fade_out + samples[:len(fade_in)] * fade_in
                all_samples[-cf_samples:] = crossfade.astype(np.int16).tobytes()  # approx
            all_samples.extend(samples)
        # Simplifié: concaténation directe pour l'instant
        return self.concat_segments(chunks, pause_ms=0)

    def play(self, wav_data: bytes, device_index: Optional[int] = None) -> bool:
        """
        Joue un WAV sur le device configuré.

        Args:
            wav_data: Données WAV complètes
            device_index: Override device (sinon config)

        Returns:
            bool: True si succès
        """
        try:
            if self._platform == "Linux":
                return self._play_linux(wav_data)
            elif self._platform == "Windows":
                return self._play_windows(wav_data, device_index)
            elif self._platform == "Darwin":
                return self._play_macos(wav_data)
            return False
        except Exception as e:
            print(f"[AudioMixer] Erreur lecture: {e}")
            return False

    def _play_linux(self, wav_data: bytes) -> bool:
        pa_sink = self.config.get("output", {}).get("pulseaudio_sink", "")
        tmp = f"/tmp/phoenix_{os.getpid()}.wav"
        with open(tmp, "wb") as f:
            f.write(wav_data)
        try:
            if pa_sink:
                subprocess.run(["paplay", "-d", pa_sink, tmp], check=True)
            else:
                alsa = self.config.get("output", {}).get("alsa_hdmi_card", "0,3")
                subprocess.run(["aplay", "-D", f"plughw:{alsa}", tmp], check=True)
            return True
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _play_windows(self, wav_data: bytes, device_index: Optional[int]) -> bool:
        import pyaudio
        with wave.open(io.BytesIO(wav_data), "rb") as wf:
            wav_rate = wf.getframerate()
            wav_ch = wf.getnchannels()
            frames = wf.readframes(wf.getnframes())

        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32)

        # Resampling si nécessaire
        p = pyaudio.PyAudio()
        dev_idx = device_index or int(self.config.get("output", {}).get("device_index", -1))
        try:
            if dev_idx < 0 or dev_idx >= p.get_device_count():
                dev_idx = p.get_default_output_device_info()["index"]
            dev_info = p.get_device_info_by_index(dev_idx)
            dev_rate = int(dev_info["defaultSampleRate"])
        except Exception:
            dev_idx = p.get_default_output_device_info()["index"]
            dev_rate = int(p.get_device_info_by_index(dev_idx)["defaultSampleRate"])

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
        s.stop_stream()
        s.close()
        p.terminate()
        return True

    def _play_macos(self, wav_data: bytes) -> bool:
        tmp = f"/tmp/phoenix_{os.getpid()}.wav"
        with open(tmp, "wb") as f:
            f.write(wav_data)
        try:
            subprocess.run(["afplay", tmp], check=True)
            return True
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


# Fonction helper pour compatibilité legacy
def create_mixer(config: Dict[str, Any] = None) -> AudioMixer:
    return AudioMixer(config)