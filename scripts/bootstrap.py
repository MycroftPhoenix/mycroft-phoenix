#!/usr/bin/env python3
"""
Bootstrap Phoenix - Installation tout-en-un multi-plateforme.

Usage:
    python scripts/bootstrap.py          # Setup complet
    python scripts/bootstrap.py --quick   # Vérifie seulement
    python scripts/bootstrap.py --venv    # Crée un venv + installe les deps
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# Répertoires de données utilisateur (hors du projet)
SYSTEM = platform.system()
if SYSTEM == "Windows":
    DATA_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Phoenix"
elif SYSTEM == "Darwin":
    DATA_DIR = Path.home() / "Library" / "Application Support" / "Phoenix"
else:
    DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "phoenix"

PROJECT_ROOT = Path(__file__).parent.parent
VENV_DIR = PROJECT_ROOT / "venv"
CONFIG_FILE = PROJECT_ROOT / "audio_config.json"
PHOENIX_CONFIG = PROJECT_ROOT / "phoenix_config.json"

VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip"
VOSK_DIR = DATA_DIR / "vosk-model-small-fr-0.22"
PIPER_VOICES = {
    "fr_FR-siwis-medium": "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx",
    "fr_FR-gilles-low": "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/gilles/low/fr_FR-gilles-low.onnx",
}
PIPER_MODELS_DIR = DATA_DIR / "piper-voices"


def log(msg: str, ok: bool = True):
    icon = "OK" if ok else "ERR"
    print(f"  [{icon}] {msg}")


def check_python():
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 9):
        log(f"Python {v.major}.{v.minor} détecté (>=3.9 requis)", False)
        return False
    log(f"Python {v.major}.{v.minor}.{v.micro}")
    return True


def check_deps():
    missing = []
    for pkg in ["sounddevice", "vosk", "numpy", "kuzu", "sklearn", "requests"]:
        try:
            __import__(pkg.replace("sklearn", "sklearn"))
        except ImportError:
            missing.append(pkg)
    if missing:
        log(f"Paquets manquants: {', '.join(missing)}", False)
        return False
    log("Toutes les dépendances Python installées")
    return True


def install_deps():
    log("Installation des dépendances...")
    req = PROJECT_ROOT / "requirements" / "phoenix.txt"
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req)],
                       capture_output=True, text=True)
    if r.returncode == 0:
        log("Dépendances installées")
    else:
        log(f"Échec: {r.stderr[:200]}", False)


def create_venv():
    if VENV_DIR.exists():
        shutil.rmtree(VENV_DIR)
    log("Création du venv...")
    r = subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], capture_output=True)
    if r.returncode != 0:
        log("Échec création venv", False)
        return None

    # Déterminer le python du venv
    if SYSTEM == "Windows":
        pip = VENV_DIR / "Scripts" / "python.exe"
    else:
        pip = VENV_DIR / "bin" / "python"

    log("Installation des dépendances dans le venv...")
    req = PROJECT_ROOT / "requirements" / "phoenix.txt"
    r = subprocess.run([str(pip), "-m", "pip", "install", "-r", str(req)],
                       capture_output=True, text=True)
    if r.returncode == 0:
        log("Venv prêt")
    else:
        log(f"Échec: {r.stderr[:200]}", False)
    return pip


def ensure_data_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PIPER_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    log(f"Répertoire de données: {DATA_DIR}")


def download_vosk():
    if VOSK_DIR.exists():
        log(f"Modèle Vosk déjà présent: {VOSK_DIR}")
        return True
    log("Téléchargement du modèle Vosk français... (50MB)")
    zip_path = str(tempfile.gettempdir() / "vosk-model.zip")
    try:
        urllib.request.urlretrieve(VOSK_URL, zip_path)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(DATA_DIR)
        os.unlink(zip_path)
        log("Modèle Vosk téléchargé et décompressé")
        return True
    except Exception as e:
        log(f"Échec téléchargement Vosk: {e}", False)
        return False


def download_piper_voices():
    PIPER_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in PIPER_VOICES.items():
        model_path = PIPER_MODELS_DIR / f"{name}.onnx"
        if model_path.exists():
            log(f"Voix {name} déjà présente")
            continue
        log(f"Téléchargement de la voix {name}...")
        try:
            urllib.request.urlretrieve(url, str(model_path))
            log(f"Voix {name} téléchargée")
        except Exception as e:
            log(f"Échec: {e}", False)


def check_piper_binary():
    candidates = ["piper", "/usr/bin/piper", "/usr/local/bin/piper"]
    for c in candidates:
        if shutil.which(c) or Path(c).exists():
            log(f"Piper trouvé: {shutil.which(c) or c}")
            return True
    # Windows
    if SYSTEM == "Windows":
        for p in [Path("C:/piper/piper/piper.exe"), Path.home() / "piper" / "piper.exe"]:
            if p.exists():
                log(f"Piper trouvé: {p}")
                return True
    log("Piper non installé. Télécharge: https://github.com/rhasspy/piper/releases", False)
    return False


def init_kuzu_databases():
    """Crée les bases Kuzu dans DATA_DIR si absentes."""
    dbs = ["phoenix", "phoenix_personal", "phoenix_research", "phoenix_stories"]
    for name in dbs:
        db_path = DATA_DIR / f"{name}.kuzu"
        if db_path.exists():
            log(f"Base {name}.kuzu déjà existante: {db_path}")
            continue
        try:
            import kuzu
            db = kuzu.Database(str(db_path))
            conn = kuzu.Connection(db)
            # Schema minimal
            conn.execute("CREATE NODE TABLE IF NOT EXISTS Memory (id STRING, content STRING, category STRING, created TIMESTAMP, PRIMARY KEY (id))")
            conn.execute("CREATE NODE TABLE IF NOT EXISTS Intent (id STRING, name STRING, PRIMARY KEY (id))")
            log(f"Base {name}.kuzu créée")
        except Exception as e:
            log(f"Échec création {name}: {e}", False)


def detect_audio():
    """Détection rapide des périphériques audio."""
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        ins = [d for d in devs if d["max_input_channels"] > 0]
        outs = [d for d in devs if d["max_output_channels"] > 0]
        log(f"Micros détectés: {len(ins)}, Sorties: {len(outs)}")
        for d in ins[:3]:
            log(f"  IN [{d['index']}] {d['name']}")
        for d in outs[:3]:
            log(f"  OUT [{d['index']}] {d['name']}")

        # Config automatique
        cfg_in = {"device_index": 0, "name": "default"}
        cfg_out = {"device_index": 0, "name": "default"}
        for d in ins:
            if "USB" in d["name"] or "Logitech" in d["name"]:
                cfg_in = {"device_index": d["index"], "name": d["name"]}
                break
        if ins and cfg_in["name"] == "default":
            cfg_in = {"device_index": ins[0]["index"], "name": ins[0]["name"]}
        for d in outs:
            if "HDMI" in d["name"] or "hdmi" in d["name"]:
                cfg_out = {"device_index": d["index"], "name": d["name"]}
                break
        if outs and cfg_out["name"] == "default":
            cfg_out = {"device_index": outs[0]["index"], "name": outs[0]["name"]}

        config = {
            "input": cfg_in | {"channels": 1, "rate": 48000, "backend": "sounddevice"},
            "output": cfg_out | {"channels": 2, "rate": 44100, "backend": "paplay", "pulseaudio_sink": "", "alsa_hdmi_card": ""},
            "stt": {"model": str(VOSK_DIR), "sample_rate": 16000},
            "tts": {"voice": "fr_FR-siwis-medium", "model_dir": str(PIPER_MODELS_DIR)},
            "wake_word": "phoenix",
            "data_dir": str(DATA_DIR),
        }

        # PulseAudio sink HDMI (Linux)
        if SYSTEM == "Linux":
            try:
                r = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=3)
                for line in r.stdout.split("\n"):
                    if "hdmi" in line.lower():
                        config["output"]["pulseaudio_sink"] = line.split("\t")[1]
                        break
            except Exception:
                pass

        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        log(f"Config audio sauvegardée: {CONFIG_FILE}")
        return True
    except Exception as e:
        log(f"Échec détection audio: {e}", False)
        return False


def update_phoenix_config():
    """Met à jour phoenix_config.json pour utiliser DATA_DIR."""
    if not PHOENIX_CONFIG.exists():
        return
    with open(PHOENIX_CONFIG) as f:
        cfg = json.load(f)
    cfg["memory"]["kuzu_path"] = str(DATA_DIR / "phoenix.kuzu")
    cfg["stt"]["model_path"] = str(VOSK_DIR)
    cfg["tts"]["voice_path"] = str(PIPER_MODELS_DIR / "fr_FR-siwis-medium.onnx")
    cfg["tts"]["model_dir"] = str(PIPER_MODELS_DIR)
    cfg["tts"]["piper_path"] = str(PIPER_MODELS_DIR)
    cfg["data_dir"] = str(DATA_DIR)
    cfg["setup"]["completed"] = True
    cfg["setup"]["first_run"] = False
    with open(PHOENIX_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)
    log("phoenix_config.json mis à jour")


def main():
    parser = argparse.ArgumentParser(description="Bootstrap Phoenix")
    parser.add_argument("--quick", action="store_true", help="Vérifie seulement l'installation")
    parser.add_argument("--venv", action="store_true", help="Crée un venv + installe les deps")
    parser.add_argument("--no-download", action="store_true", help="Ne pas télécharger les modèles")
    args = parser.parse_args()

    print("\n=== Phoenix Bootstrap ===")
    print(f"Système: {SYSTEM}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Répertoire données: {DATA_DIR}")
    print()

    # 1. Python
    if not check_python():
        sys.exit(1)

    # 2. Data dirs
    ensure_data_dirs()

    # 3. Mode quick: juste vérifier
    if args.quick:
        check_deps()
        check_piper_binary()
        init_kuzu_databases()
        detect_audio()
        print("\nVérification terminée.")
        return

    # 4. Venv (optionnel)
    python = sys.executable
    if args.venv:
        p = create_venv()
        if p:
            python = str(p)

    # 5. Dépendances (si pas dans un venv)
    if not args.venv:
        if not check_deps():
            print("\nInstallation des dépendances...")
            install_deps()

    # 6. Modèles
    if not args.no_download:
        download_vosk()
        download_piper_voices()

    # 7. Piper binaire
    check_piper_binary()

    # 8. Kuzu
    init_kuzu_databases()

    # 9. Audio
    detect_audio()

    # 10. Config
    update_phoenix_config()

    print(f"\n✅ Phoenix prêt dans {DATA_DIR}")
    print(f"   Lance: python {PROJECT_ROOT / 'voice_loop.py'}")
    if args.venv:
        print(f"   Avec venv: {python}")
    print()


if __name__ == "__main__":
    main()
