import sys

try:
    import win32com.client
    voices = win32com.client.Dispatch("SAPI.SpVoice")
    print("SAPI SpVoice OK")
    for i in range(voices.Count):
        v = voices.Voice(i)
        print(f"  Voix {i}: {v.GetDescription()} (lang={v.Language})")
except ImportError:
    print("pywin32 non installe - necessite: pip install pywin32")
except Exception as e:
    print(f"SAPI SpVoice: {e}")

try:
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens") as key:
        for i in range(1024):
            try:
                name = winreg.EnumKey(key, i)
                print(f"Registry OneCore Voice: {name}")
            except OSError:
                break
except Exception as e:
    print(f"Registry: {e}")

# Test if we can use ctypes to access SAPI
try:
    import ctypes
    from ctypes import wintypes, com
    print(f"ctypes OK (COM accessible via ctypes)")
    print(f"  ole32: {hasattr(ctypes.windll, 'ole32')}")
except Exception as e:
    print(f"ctypes: {e}")
