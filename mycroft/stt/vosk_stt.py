import os
import json
import sys
from pathlib import Path
from threading import Thread
from queue import Queue, Empty
from mycroft.stt import STT, StreamingSTT, StreamThread
from mycroft.util.log import LOG


class VoskSTT(STT):
    def __init__(self):
        super().__init__()
        self._model = None
        self._rec = None
        self.model_path = self.config.get(
            'model_path',
            os.environ.get('VOSK_MODEL_PATH', self._default_model_path())
        )
        self.lang = self.config.get('lang', self.lang)
        self.sample_rate = self.config.get('sample_rate', 16000)

    def _default_model_path(self):
        return str(Path.home() / '.config' / 'mycroft' / 'vosk' / 'model')

    def _ensure_model(self):
        if self._model is not None:
            return True
        try:
            from vosk import Model, KaldiRecognizer
            if not os.path.exists(self.model_path):
                LOG.error(
                    'Vosk model not found at %s. '
                    'Download from https://alphacephei.com/vosk/models',
                    self.model_path
                )
                return False
            self._model = Model(self.model_path)
            self._rec = KaldiRecognizer(self._model, self.sample_rate)
            LOG.info('Vosk model loaded from %s', self.model_path)
            return True
        except ImportError:
            LOG.error('Vosk not installed: pip install vosk')
            return False
        except Exception as e:
            LOG.error('Failed to load Vosk model: %s', e)
            return False

    @property
    def available_languages(self):
        return {'en-US', 'en-GB', 'en-IN', 'de-DE', 'fr-FR', 'es-ES',
                'pt-BR', 'ru-RU', 'it-IT', 'nl-NL', 'pl-PL', 'zh-CN',
                'ja-JP', 'ko-KR', 'ar', 'tr-TR', 'vi-VN', 'uk-UA',
                'fa', 'ca', 'eo', 'hi', 'sw'}

    def execute(self, audio, language=None):
        if not self._ensure_model():
            return ''
        try:
            data = audio.get_raw_data(convert_rate=self.sample_rate,
                                      convert_width=2)
            if self._rec.AcceptWaveform(data):
                result = json.loads(self._rec.Result())
                text = result.get('text', '')
                self._rec.Reset()
                return text
            partial = json.loads(self._rec.PartialResult())
            return partial.get('partial', '')
        except Exception as e:
            LOG.error('Vosk STT error: %s', e)
            return ''


class VoskStreamThread(StreamThread):
    def __init__(self, queue, language, model_path, sample_rate):
        super().__init__(queue, language)
        self.model_path = model_path
        self.sample_rate = sample_rate
        self._model = None
        self._rec = None
        self._init_model()

    def _init_model(self):
        try:
            from vosk import Model, KaldiRecognizer
            self._model = Model(self.model_path)
            self._rec = KaldiRecognizer(self._model, self.sample_rate)
        except Exception as e:
            LOG.error('Vosk stream init failed: %s', e)

    def handle_audio_stream(self, audio, language):
        if not self._rec:
            return None
        for chunk in audio:
            if self._rec.AcceptWaveform(chunk):
                result = json.loads(self._rec.Result())
                self.text = result.get('text', '')
        if self._rec:
            partial = json.loads(self._rec.PartialResult())
            final = partial.get('partial', '')
            if final:
                self.text = final
        return self.text


class VoskStreamingSTT(StreamingSTT):
    def __init__(self):
        super().__init__()
        self.model_path = self.config.get(
            'model_path',
            os.environ.get('VOSK_MODEL_PATH',
                           str(Path.home() / '.config' / 'mycroft' / 'vosk' / 'model'))
        )
        self.sample_rate = self.config.get('sample_rate', 16000)
        self.can_stream = True

    def create_streaming_thread(self):
        return VoskStreamThread(
            self.queue, self.lang, self.model_path, self.sample_rate
        )
