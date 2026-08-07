"""
Garde-fou thermique pour le pipeline Phoenix.

Sur cet APU AMD A10 (FM2), le CPU et le GPU partagent le meme die :
le capteur "GPU Core" de LibreHardwareMonitor sert de sonde de temperature
du processeur. La limite duree conseillee pour un A10 est ~70C (throttle ~90C).

Lecture via LibreHardwareMonitorLib.dll (win), avec cache court pour ne pas
relancer PowerShell a chaque appel. Degradation propre si l'outil est absent.
"""

import logging
import os
import shutil
import subprocess
import time

logger = logging.getLogger(__name__)

# Limites de securite (C). Ajustable via env.
MAX_TEMP_SAFE = float(os.environ.get("PHOENIX_MAX_TEMP", "85"))   # abaisse -> refuse le run
MAX_TEMP_WARN = float(os.environ.get("PHOENIX_WARN_TEMP", "70"))  # au-dessus -> log warning

_CACHE_TTL = 4.0  # secondes entre deux lectures
_cache = {"time": 0.0, "temp": None, "avail": None}


def _encode_ps(script: str) -> str:
    """Encode un script PowerShell en -EncodedCommand (UTF-16LE base64)."""
    import base64
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _lhm_dir() -> str:
    """Localise le dossier LibreHardwareMonitor (win)."""
    candidates = [
        os.environ.get("LHM_DIR", ""),
        r"C:\Users\Administrateur\AppData\Local\Microsoft\WinGet\Packages\LibreHardwareMonitor.LibreHardwareMonitor_Microsoft.Winget.Source_8wekyb3d8bbwe",
        r"C:\Program Files\LibreHardwareMonitor",
        r"C:\Program Files (x86)\LibreHardwareMonitor",
    ]
    for c in candidates:
        if c and os.path.exists(os.path.join(c, "LibreHardwareMonitorLib.dll")):
            return c
    return ""


def get_cpu_temp_c() -> float:
    """Retourne la temperature CPU (proxy GPU Core) en degres C, ou NaN si indispo."""
    now = time.time()
    if now - _cache["time"] < _CACHE_TTL and _cache["temp"] is not None:
        return _cache["temp"]

    lhm = _lhm_dir()
    if not lhm:
        _cache.update({"time": now, "temp": float("nan"), "avail": False})
        return float("nan")

    lhm_esc = lhm.replace("'", "''")
    ps_code = f"""
Add-Type -Path '{lhm_esc}\\LibreHardwareMonitorLib.dll'
$c = New-Object LibreHardwareMonitor.Hardware.Computer
$c.IsGpuEnabled = $true
$c.Open()
Start-Sleep -Milliseconds 700
foreach ($hw in $c.Hardware) {{
    $hw.Update()
    foreach ($s in $hw.Sensors) {{
        if ($s.SensorType -eq 'Temperature' -and $s.Name -match 'GPU') {{
            [math]::Round($s.Value,1)
            $c.Close()
            exit 0
        }}
    }}
}}
$c.Close()
exit 1
"""
    encoded = _encode_ps(ps_code)
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            temp = float(r.stdout.strip().splitlines()[0])
            _cache.update({"time": now, "temp": temp, "avail": True})
            return temp
    except Exception as e:
        logger.debug("Lecture temperature CPU: %s", e)

    _cache.update({"time": now, "temp": float("nan"), "avail": False})
    return float("nan")


def safe_to_run_llm() -> bool:
    """True si la temperature CPU autorise une inference locale."""
    temp = get_cpu_temp_c()
    if temp != temp:  # NaN : capteur indisponible -> on laisse tourner (degradation douce)
        return True
    if temp >= MAX_TEMP_SAFE:
        logger.warning("Temperature CPU %.0fC >= seuil %.0fC — inference locale refusee", temp, MAX_TEMP_SAFE)
        return False
    if temp >= MAX_TEMP_WARN:
        logger.warning("Temperature CPU %.0fC >= %.0fC — attention surchauffe", temp, MAX_TEMP_WARN)
    return True
