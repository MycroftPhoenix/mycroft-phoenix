"""Backend TTS natif Windows via System.Speech (voix du système, 100% local).

Synthétise vers un fichier WAV puis émet le PCM brut (int16 mono) en flux.
Branche sur le bus TTS de Mycroft-Phoenix (registre) — hérite de ``_base.TTSBackend``,
aucune dépendance sur le core ni sur pip (PowerShell + System.Speech intégrés).
"""

import logging
import os
import tempfile

from ._base import TTSBackend
from ._ps import find_voice, run_powershell

_LOGGER = logging.getLogger(__name__)


def _speak_script(wav_path: str, txt_path: str, voice: str | None) -> str:
    voice_stmt = ""
    if voice:
        voice_stmt = "$s.SelectVoice('%s'); " % voice.replace("'", "''")
    return (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        + voice_stmt +
        "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo("
        "22050, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
        "[System.Speech.AudioFormat.AudioChannel]::Mono); "
        "$s.SetOutputToWaveFile('%s', $f); "
        "$t = [System.IO.File]::ReadAllText('%s', [System.Text.Encoding]::UTF8); "
        "$s.Speak($t); "
        "$s.Dispose()"
    ) % (wav_path, txt_path)


class WindowsSAPItts(TTSBackend):
    """TTS via les voix natives Windows (System.Speech). Aucun appel réseau."""

    type = "windows"
    description = "SAPI/.NET TTS — voix Windows natives (System.Speech), 100% local"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.sample_rate = 22050  # SpeechAudioFormatInfo 22,05 kHz
        # Voix explicite, sinon sélection auto par culture (langue du backend)
        self._voice = cfg.get("voice") or find_voice(self.language)

    def health(self) -> bool:
        try:
            out, _err, rc = run_powershell("Add-Type -AssemblyName System.Speech; 'OK'")
            return rc == 0 and "OK" in out
        except Exception as exc:  # pragma: no cover
            _LOGGER.debug("TTS Windows indisponible: %s", exc)
            return False

    def synthesize(self, text: str):
        """Émet des paquets de PCM int16 mono (22,05 kHz) depuis un WAV WAV."""
        fd, wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        tfd, txt = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(tfd, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            run_powershell(_speak_script(wav, txt, self._voice), timeout=60)
            with open(wav, "rb") as fh:
                data = fh.read()
            pcm = data[44:]  # saute l'en-tête WAV (44 octets)
            for i in range(0, len(pcm), 4096):
                yield pcm[i:i + 4096]
        finally:
            for p in (wav, txt):
                try:
                    os.remove(p)
                except OSError:
                    pass
