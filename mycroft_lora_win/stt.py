"""Backend STT natif Windows via System.Speech (reconnaissance dictée, local).

Utilise ``SpeechRecognitionEngine`` + grammaire de dictée (offline). Aucune
dépendance pip (PowerShell + System.Speech intégrés). La langue de
reconnaissance dépend des packs linguistiques installés dans Windows.
"""

import logging
import os
import tempfile
import wave

from ._base import STTBackend
from ._ps import run_powershell

_LOGGER = logging.getLogger(__name__)


def _write_wav(pcm: bytes, sample_rate: int, channels: int = 1, width: int = 2) -> str:
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return path


class WindowsSAPIstt(STTBackend):
    """STT via la dictée Windows (System.Speech). 100% local."""

    type = "windows"
    description = "SAPI/.NET STT — dictée Windows (System.Speech), 100% local"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._timeout = float(cfg.get("timeout") or 8.0)
        self._lang = cfg.get("language") or "fr-FR"

    def health(self) -> bool:
        try:
            out, _err, rc = run_powershell("Add-Type -AssemblyName System.Speech; 'OK'")
            return rc == 0 and "OK" in out
        except Exception as exc:  # pragma: no cover
            _LOGGER.debug("STT Windows indisponible: %s", exc)
            return False

    def transcribe(self, audio: bytes, sample_rate: int = 16000) -> str | None:
        wav = _write_wav(audio, sample_rate)
        try:
            return self._recognize(wav)
        finally:
            try:
                os.remove(wav)
            except OSError:
                pass

    def _recognize(self, wav: str) -> str | None:
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$r = New-Object System.Speech.Recognition.SpeechRecognitionEngine; "
            "$r.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar)); "
            "$r.InitialSilenceTimeout = [TimeSpan]::FromSeconds(%d); "
            "$r.BabbleTimeout = [TimeSpan]::FromSeconds(%d); "
            "$r.SetInputToWaveFile('%s'); "
            "$res = $r.Recognize(); "
            "if ($res) { $res.Text } else { '' }"
        ) % (int(self._timeout), int(self._timeout), wav)
        try:
            out, _err, _rc = run_powershell(script, timeout=int(self._timeout) + 5)
        except Exception as exc:  # pragma: no cover
            _LOGGER.debug("reconnaissance Windows: %s", exc)
            return None
        return out.strip() or None
