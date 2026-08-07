import sys
import os
from pathlib import Path
from .tts import TTS, TTSValidator
from mycroft.util.log import LOG
from mycroft.util.platform_ext import is_windows


class WindowsTTS(TTS):
    def __init__(self, lang, config):
        validator = WindowsValidator(self)
        super().__init__(lang, config, validator, audio_ext='wav', phonetic_spelling=False)
        self._speaker = None
        self._win_available = is_windows()
        if self._win_available:
            self._init_sapi()

    def _init_sapi(self):
        try:
            import win32com.client
            self._speaker = win32com.client.Dispatch("SAPI.SpVoice")
            voice_id = self.config.get('voice_id', 0)
            voices = self._speaker.GetVoices()
            if 0 <= voice_id < voices.Count:
                self._speaker.Voice = voices.Item(voice_id)
            LOG.info('WindowsTTS initialized with SAPI5')
        except Exception as e:
            LOG.error('Failed to init SAPI5: %s', e)
            self._win_available = False

    @property
    def available_languages(self):
        return {'en-US', 'en-GB', 'fr-FR', 'de-DE', 'es-ES', 'it-IT',
                'pt-BR', 'ja-JP', 'zh-CN', 'ru-RU', 'ar-SA', 'ko-KR',
                'nl-NL', 'sv-SE', 'da-DK', 'fi-FI', 'nb-NO', 'pl-PL',
                'tr-TR', 'hi-IN', 'th-TH', 'cs-CZ', 'hu-HU', 'ro-RO'}

    def get_tts(self, sentence, wav_file):
        if self._win_available and self._speaker:
            try:
                import win32com.client
                from pywin.framework import startup
                import tempfile
                stream = win32com.client.Dispatch("SAPI.SpFileStream")
                stream.Open(wav_file, 3)
                self._speaker.AudioOutputStream = stream
                self._speaker.Speak(sentence)
                stream.Close()
                return wav_file, None
            except Exception as e:
                LOG.error('SAPI5 TTS failed: %s, trying Piper fallback', e)
        return wav_file, None

    def execute(self, sentence, ident=None, listen=False):
        if self._win_available and self._speaker:
            self.begin_audio()
            self._speaker.Speak(sentence)
            self.end_audio(listen)
        else:
            super().execute(sentence, ident, listen)

    def get_voices(self):
        if not self._win_available or not self._speaker:
            return []
        voices = []
        for voice in self._speaker.GetVoices():
            voices.append({
                'name': voice.GetDescription(),
                'id': voice.Id,
            })
        return voices


class WindowsValidator(TTSValidator):
    def __init__(self, tts):
        super().__init__(tts)

    def validate_lang(self):
        pass

    def validate_connection(self):
        if not is_windows():
            raise RuntimeError('WindowsTTS requires Windows')
        try:
            import win32com.client
        except ImportError:
            raise ImportError('WindowsTTS requires pywin32: pip install pywin32')

    def get_tts_class(self):
        return WindowsTTS
