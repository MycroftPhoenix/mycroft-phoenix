"""
Gestionnaire de configuration Phoenix.
Gere le premier lancement et les preferences utilisateur.
"""

import json
import os
from pathlib import Path

LOG_NAME = "phoenix.config"

# Emplacement du fichier de config
_CONFIG_DIR = Path.home() / ".config" / "phoenix"
_CONFIG_FILE = _CONFIG_DIR / "phoenix_config.json"

# Config par défaut
DEFAULT_CONFIG = {
    "voice_backend": None,       # "phoenix" ou "windows" (None = pas encore choisi)
    "stt_module": "vosk",        # "vosk" ou "windows_speech"
    "tts_module": "piper",       # "piper" ou "windows"
    "language": "fr",
    "vosk_model_path": "",
    "piper_voice": "fr_FR-siwis-medium",
    "ollama_model": "qwen2.5:0.5b",
    "wake_word": "phoenix",      # Mot de reveil (lowercase)
    "wake_word_enabled": True,   # Detection du mot de reveil activee
    "first_run": True,
}

# Presets de mots de reveil
WAKE_WORD_PRESETS = [
    {"id": "phoenix",    "label": "Phoenix",    "spoken": "hey phoenix",  "desc": "Réveil avec 'Hey Phoenix'"},
    {"id": "mycroft",    "label": "Mycroft",    "spoken": "hey mycroft",  "desc": "Réveil avec 'Hey Mycroft'"},
    {"id": "phoenix_2",  "label": "Phoenix (court)", "spoken": "phoenix", "desc": "Réveil avec juste 'Phoenix'"},
    {"id": "mycroft_2",  "label": "Mycroft (court)", "spoken": "mycroft", "desc": "Réveil avec juste 'Mycroft'"},
    {"id": "custom",     "label": "Personnalisé", "spoken": "",            "desc": "Entrer votre propre mot de réveil"},
    {"id": "none",       "label": "Pas de mot de réveil", "spoken": "",    "desc": "Écoute en continu, sans mot de déclenchement"},
]


def _ensure_config_dir():
    """Cree le repertoire de config s'il n'existe pas."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    """Charge la configuration depuis le fichier JSON."""
    _ensure_config_dir()
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # Fusionner avec les defaults (pour les cles manquantes)
            config = {**DEFAULT_CONFIG, **saved}
            return config
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config):
    """Sauvegarde la configuration dans le fichier JSON."""
    _ensure_config_dir()
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def is_first_run():
    """Verifie si c'est le premier lancement."""
    config = load_config()
    return config.get("first_run", True) is True


def prompt_voice_backend():
    """
    Demande a l'utilisateur de choisir son backend vocal et son mot de reveil.
    Retourne le dict de config mis a jour.
    """
    import sys

    config = load_config()

    print()
    print("=" * 55)
    print("  MYCROFT PHOENIX — Configuration vocale")
    print("=" * 55)
    print()
    print("  Choisissez votre systeme de reconnaissance et")
    print("  synthese vocale :")
    print()
    print("  [1] Phoenix local (hors ligne)")
    print("      STT: Vosk  |  TTS: Piper")
    print("      Privé, multilingue, sans internet")
    print()
    print("  [2] Windows intégré")
    print("      STT: Speech Recognition  |  TTS: SAPI5")
    print("      Déjà installé, prêt à l'emploi")
    print()

    while True:
        try:
            choice = input("  Votre choix [1/2] : ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            choice = "1"

        if choice == "1":
            config["voice_backend"] = "phoenix"
            config["stt_module"] = "vosk"
            config["tts_module"] = "piper"
            print()
            print("  ✓ Backend Phoenix sélectionné (Vosk + Piper)")
            break
        elif choice == "2":
            config["voice_backend"] = "windows"
            config["stt_module"] = "windows_speech"
            config["tts_module"] = "windows"
            print()
            print("  ✓ Backend Windows sélectionné (Speech + SAPI5)")
            break
        else:
            print("  ✗ Choix invalide. Tapez 1 ou 2.")

    print()

    # Demander la langue
    print("  Langue principale :")
    print("  [1] Français  [2] English  [3] Español  [4] Deutsch")
    try:
        lang_choice = input("  Langue [1/2/3/4] : ").strip()
    except (EOFError, KeyboardInterrupt):
        lang_choice = "1"

    lang_map = {"1": "fr", "2": "en", "3": "es", "4": "de"}
    config["language"] = lang_map.get(lang_choice, "fr")

    lang_names = {"fr": "Français", "en": "English", "es": "Español", "de": "Deutsch"}
    print(f"  ✓ Langue: {lang_names.get(config['language'], 'Français')}")
    print()

    # Demander le mot de reveil
    config = prompt_wake_word(config)

    # Sauvegarder
    config["first_run"] = False
    save_config(config)

    print("  Configuration sauvegardée dans:")
    print(f"  {_CONFIG_FILE}")
    print()
    print("=" * 55)
    print()

    return config


def prompt_wake_word(config=None):
    """
    Demande a l'utilisateur de choisir son mot de revel.
    Retourne le dict de config mis a jour.
    """
    if config is None:
        config = load_config()

    print()
    print("  Mot de réveil :")
    print("  Dit « Hey <nom> » pour activer l'écoute.")
    print()

    for i, preset in enumerate(WAKE_WORD_PRESETS, 1):
        print(f"  [{i}] {preset['desc']}")

    print()
    while True:
        try:
            choice = input("  Votre choix [1-6] : ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            choice = "1"

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(WAKE_WORD_PRESETS):
                selected = WAKE_WORD_PRESETS[idx]
                break
        except (ValueError, IndexError):
            pass
        print("  ✗ Choix invalide.")

    if selected["id"] == "none":
        config["wake_word"] = ""
        config["wake_word_enabled"] = False
        print()
        print("  ✓ Pas de mot de réveil — écoute en continu")
    elif selected["id"] == "custom":
        print()
        try:
            custom = input("  Entrez votre mot de réveil (ex: « salut phoenix ») : ").strip()
        except (EOFError, KeyboardInterrupt):
            custom = "phoenix"
        if custom:
            config["wake_word"] = custom.lower()
            config["wake_word_enabled"] = True
            print(f"  ✓ Mot de réveil: « {custom} »")
        else:
            config["wake_word"] = "phoenix"
            config["wake_word_enabled"] = True
            print("  ✓ Mot de réveil: « phoenix » (défaut)")
    else:
        config["wake_word"] = selected["spoken"]
        config["wake_word_enabled"] = True
        print(f"  ✓ Mot de réveil: « {selected['spoken']} »")

    print()
    return config


def get_or_prompt_config():
    """
    Charge la config. Si premier lancement, demande a l'utilisateur.
    Retourne le dict de config.
    """
    config = load_config()
    if config.get("first_run", True):
        return prompt_voice_backend()
    return config


def update_config(**kwargs):
    """Met a jour des champs specifiques de la config."""
    config = load_config()
    config.update(kwargs)
    save_config(config)
    return config
