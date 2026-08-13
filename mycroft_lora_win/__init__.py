"""mycroft-lora-win — intégration native Windows pour Mycroft-Phoenix.

Successeur *local et privé* de l'assistant que Cortana était : exploite la
couche vocale/shell de Windows (SAPI) sans aucune dépendance serveur Microsoft.

Backends prêts à brancher dans ``mycroft.capabilities`` via :func:`register`.
"""

from ._ps import list_voices
from .shell import WindowsShell, launch_app, notify, open_settings
from .stt import WindowsSAPIstt
from .tts import WindowsSAPItts

__all__ = [
    "WindowsSAPItts",
    "WindowsSAPIstt",
    "WindowsShell",
    "list_voices",
    "launch_app",
    "open_settings",
    "notify",
    "register",
]


def register(tts_registry: dict | None = None,
              stt_registry: dict | None = None) -> None:
    """Branche les backends Windows sur le bus TTS/STT de Mycroft-Phoenix.

    Le core appelle ``mycroft_lora_win.register(speech._TTS_REGISTRY,
    speech._STT_REGISTRY)`` — le paquet n'importe JAMAIS le core (zéro
    dépendance). Idempotent (setdefault).
    """
    if tts_registry is not None:
        tts_registry.setdefault("windows", WindowsSAPItts)
    if stt_registry is not None:
        stt_registry.setdefault("windows", WindowsSAPIstt)
