import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from .tts import TTS, TTSValidator
from mycroft.util.log import LOG
from mycroft.util.platform_ext import is_linux, is_windows, is_mac, executable_exists


class PiperTTS(TTS):
    def __init__(self, lang, config):
        validator = PiperValidator(self)
        super().__init__(lang, config, validator, audio_ext='wav', phonetic_spelling=False)
        self.voice = config.get('voice', 'fr_FR-siwis-medium')
        self.piper_path = self._find_piper()
        self.model_path = self._find_model()
        self.speaker_id = config.get('speaker_id')
        self.noise_scale = config.get('noise_scale', 0.667)
        self.length_scale = config.get('length_scale', 1.0)
        self.noise_w = config.get('noise_w', 0.8)
        self.sentence_silence = config.get('sentence_silence', 0.2)

    def _find_piper(self):
        piper = self.config.get('piper_path') or shutil.which('piper')
        if piper:
            return piper
        candidates = [
            '/usr/bin/piper',
            '/usr/local/bin/piper',
            str(Path.home() / '.local' / 'bin' / 'piper'),
        ]
        if is_windows():
            candidates.extend([
                'C:\\piper\\piper\\piper.exe',
                'C:\\piper\\piper.exe',
                'C:\\Program Files\\piper\\piper.exe',
            ])
        for c in candidates:
            if Path(c).exists():
                return c
        return 'piper'

    def _find_model(self):
        model = self.config.get('model_path')
        if model and Path(model).exists():
            return model
        data_dir = Path(self.config.get('data_dir', self._default_data_dir()))
        model_file = data_dir / f'{self.voice}.onnx'
        if model_file.exists():
            return str(model_file)
        json_file = data_dir / f'{self.voice}.json'
        if json_file.exists():
            return str(json_file)
        return str(data_dir / f'{self.voice}.onnx')

    def _default_data_dir(self):
        if is_windows():
            candidates = [
                str(Path('C:\\piper\\piper\\voices')),
                str(Path('C:\\piper\\voices')),
                str(Path.home() / 'AppData' / 'Local' / 'piper' / 'voices'),
            ]
            for c in candidates:
                if Path(c).exists():
                    return c
            return str(Path.home() / 'AppData' / 'Local' / 'piper' / 'voices')
        return str(Path.home() / '.local' / 'share' / 'piper' / 'voices')

    @property
    def available_languages(self):
        return {'en-US', 'en-GB', 'de-DE', 'fr-FR', 'es-ES', 'it-IT',
                'nl-NL', 'pt-BR', 'ru-RU', 'sv-SE', 'ar', 'pl-PL',
                'uk-UA', 'vi-VN', 'zh-CN'}

    def get_tts(self, sentence, wav_file):
        model = self._find_model()
        model_path_obj = Path(model)
        json_file = model_path_obj.with_suffix('.json')
        sentence = self._sanitize_fr(sentence)
        cmd = [self.piper_path, '--model', model, '--output-file', wav_file]
        if json_file.exists():
            cmd.extend(['--config', str(json_file)])
        if self.speaker_id is not None:
            cmd.extend(['--speaker', str(self.speaker_id)])
        cmd.extend([
            '--noise-scale', str(self.noise_scale),
            '--length-scale', str(self.length_scale),
            '--noise-w', str(self.noise_w),
            '--sentence-silence', str(self.sentence_silence),
        ])
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            out, err = proc.communicate(input=sentence.encode('utf-8'),
                                        timeout=30)
            if proc.returncode != 0:
                LOG.error('Piper TTS error: %s', err.decode())
                return wav_file, None
            return wav_file, None
        except FileNotFoundError:
            LOG.error('Piper binary not found at %s', self.piper_path)
            raise
        except subprocess.TimeoutExpired:
            LOG.error('Piper TTS timed out')
            proc.kill()
            proc.communicate()
            return wav_file, None

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


class PiperValidator(TTSValidator):
    def __init__(self, tts):
        super().__init__(tts)

    def validate_lang(self):
        lang = self.tts.lang.split('-')[0].lower()
        supported = {l.split('-')[0].lower() for l in self.tts.available_languages}
        if lang not in supported:
            raise ValueError(f'Language {self.tts.lang} not supported by PiperTTS')

    def validate_connection(self):
        if not executable_exists(self.tts.piper_path) and not Path(self.tts.piper_path).exists():
            raise FileNotFoundError(
                f'Piper binary not found. Install: pip install piper-tts '
                f'or download from https://github.com/rhasspy/piper'
            )

    def get_tts_class(self):
        return PiperTTS
