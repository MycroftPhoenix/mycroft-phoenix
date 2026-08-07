import os
import sys
import shutil
import subprocess


def _os_name():
    if sys.platform.startswith('linux'):
        return 'linux'
    elif sys.platform == 'win32' or sys.platform == 'cygwin':
        return 'windows'
    elif sys.platform == 'darwin':
        return 'mac'
    return sys.platform


def _is_wayland():
    return os.environ.get('WAYLAND_DISPLAY') is not None


def is_linux():
    return _os_name() == 'linux'


def is_windows():
    return _os_name() == 'windows'


def is_mac():
    return _os_name() == 'mac'


def is_termux():
    return 'com.termux' in (os.environ.get('PREFIX') or '')


def is_raspberry_pi():
    try:
        with open('/proc/device-tree/model') as f:
            return 'Raspberry Pi' in f.read()
    except Exception:
        return False


def executable_exists(name):
    return shutil.which(name) is not None


def get_platform_label():
    parts = [_os_name().capitalize()]
    if is_raspberry_pi():
        parts.append('RPi')
    if is_termux():
        parts.append('Termux')
    if is_linux() and _is_wayland():
        parts.append('Wayland')
    return '-'.join(parts)


def get_default_audio_play_cmd():
    if is_windows():
        return None
    for cmd in ['paplay', 'aplay', 'ffplay', 'sox']:
        path = shutil.which(cmd)
        if path:
            return cmd
    return 'aplay'


def get_pulse_env(config):
    tts_config = config.get('tts', {})
    if tts_config.get('pulse_duck'):
        env = os.environ.copy()
        env['PULSE_PROP'] = 'media.role=phone'
        return env
    return None
