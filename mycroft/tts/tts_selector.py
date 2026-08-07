from mycroft.util.log import LOG
from mycroft.util.platform_ext import (
    is_linux, is_windows, is_mac, executable_exists, is_raspberry_pi
)
from mycroft.configuration import Configuration


_BACKENDS_BY_OS = {
    'linux': ['piper', 'mimic', 'espeak', 'google', 'dummy'],
    'windows': ['windows', 'piper', 'google', 'dummy'],
    'mac': ['piper', 'google', 'dummy'],
}


def _check_piper():
    import shutil
    import os
    from pathlib import Path
    if shutil.which('piper'):
        return True
    home = Path.home()
    for p in [home / '.local' / 'bin' / 'piper',
              Path('/usr/bin/piper'),
              Path('/usr/local/bin/piper')]:
        if p.exists():
            return True
    if is_windows():
        for p in [Path('C:\\Program Files\\piper\\piper.exe'),
                  Path('C:\\piper\\piper.exe')]:
            if p.exists():
                return True
    return False


def _check_mimic():
    return executable_exists('mimic')


def _check_espeak():
    return executable_exists('espeak')


def auto_select_tts():
    config = Configuration.get()
    tts_config = config.get('tts', {})
    preferred = tts_config.get('module')

    if preferred and preferred != 'auto':
        return preferred

    if is_windows():
        try:
            import win32com.client
            return 'windows'
        except ImportError:
            pass

    if _check_piper():
        return 'piper'

    if _check_mimic():
        return 'mimic'

    if _check_espeak():
        return 'espeak'

    LOG.warning('No local TTS engine found, falling back to dummy')
    return 'dummy'


def patch_tts_config():
    config = Configuration.get()
    tts_config = config.get('tts', {})
    module = tts_config.get('module', 'auto')
    if module == 'auto':
        selected = auto_select_tts()
        LOG.info('Auto-selected TTS module: %s', selected)
        if 'module' not in tts_config or tts_config['module'] == 'auto':
            tts_config['module'] = selected
    return tts_config
