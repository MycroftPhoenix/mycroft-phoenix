import os
from pathlib import Path
from mycroft.util.log import LOG
from mycroft.util.platform_ext import is_linux, is_windows, is_mac, executable_exists
from mycroft.configuration import Configuration


_BACKENDS_BY_OS = {
    'linux': ['vosk', 'google', 'mycroft', 'dummy'],
    'windows': ['vosk', 'google', 'bing', 'dummy'],
    'mac': ['vosk', 'google', 'dummy'],
}


def _check_vosk():
    try:
        import vosk
        model_path = os.environ.get(
            'VOSK_MODEL_PATH',
            str(Path.home() / '.config' / 'mycroft' / 'vosk' / 'model')
        )
        if os.path.exists(model_path):
            return True
        LOG.warning('Vosk model not found at %s', model_path)
        return False
    except ImportError:
        return False


def auto_select_stt():
    config = Configuration.get()
    stt_config = config.get('stt', {})
    preferred = stt_config.get('module')

    if preferred and preferred != 'auto':
        return preferred

    if _check_vosk():
        return 'vosk'

    LOG.info('No offline STT found, using google (requires internet)')
    return 'google'


def patch_stt_config():
    config = Configuration.get()
    stt_config = config.get('stt', {})
    module = stt_config.get('module', 'auto')
    if module == 'auto':
        selected = auto_select_stt()
        LOG.info('Auto-selected STT module: %s', selected)
        if 'module' not in stt_config or stt_config['module'] == 'auto':
            stt_config['module'] = selected
    return stt_config
