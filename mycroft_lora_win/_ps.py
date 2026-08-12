"""Helpers PowerShell — pilote l'API vocale Windows native (System.Speech).

System.Speech (.NET Framework, intégré à Windows) fournit TTS/STT 100% local,
sans aucun appel réseau ni dépendance pip. On l'invoque via le PowerShell
présent nativement sur Windows (pas de subprocess lourd tant qu'on batch pas).
"""

import subprocess


def run_powershell(script: str, timeout: int = 60):
    """Exécute ``script`` via PowerShell ; retourne (stdout, stderr, code)."""
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout,
    )
    return proc.stdout, proc.stderr, proc.returncode


def list_voices() -> list:
    """Noms des voix TTS installées (ex. 'Microsoft Zira Desktop')."""
    out, _err, rc = run_powershell(
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "($s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }) -join \"`n\""
    )
    if rc != 0 or not out.strip():
        return []
    return [v for v in out.splitlines() if v.strip()]


def voices_by_culture() -> dict:
    """{nom_voix: culture} (ex. {'Microsoft Zira Desktop': 'en-US'})."""
    out, _err, rc = run_powershell(
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "($s.GetInstalledVoices() | ForEach-Object { "
        "$_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture.Name }) -join \"`n\""
    )
    result = {}
    if rc == 0 and out.strip():
        for line in out.splitlines():
            if "|" in line:
                name, culture = line.rsplit("|", 1)
                result[name.strip()] = culture.strip()
    return result


def find_voice(lang: str) -> str | None:
    """Retourne le nom d'une voix dont la culture correspond à ``lang``.

    Priorité : correspondance exacte (fr-FR), puis préfixe (fr).
    """
    lang = (lang or "").lower()
    if not lang:
        return None
    prefix = lang.split("-")[0]
    voices = voices_by_culture()
    for name, culture in voices.items():
        if culture.lower() == lang:
            return name
    for name, culture in voices.items():
        if culture.lower().startswith(prefix):
            return name
    return None
