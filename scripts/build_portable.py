#!/usr/bin/env python3
"""
Build une distribution portable de Phoenix.

Crée un zip tout-inclus contenant:
  - Le code source
  - Un venv Python avec toutes les dépendances
  - Un launcher (bat/sh) pour exécuter sans installation
  - README, licence

Usage:
    python scripts/build_portable.py              # Build Linux
    python scripts/build_portable.py --windows     # Build Windows
    python scripts/build_portable.py --macos       # Build macOS
    python scripts/build_portable.py --all         # Build les 3 (si sur Linux)
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

SYSTEM = platform.system()
PROJECT_ROOT = Path(__file__).parent.parent
BUILD_DIR = PROJECT_ROOT / "dist" / "portable"
EXCLUDES = {
    ".git", "__pycache__", "*.pyc", "venv", "mycroft-kuzu",
    "backups", "log", "*.kuzu", "audio_config.json",
    "claude-memory.kuzu", "phoenix*.kuzu",
}


def create_launcher(target_os: str, venv_python: str) -> str:
    if target_os == "Windows":
        return f"""@echo off
REM Phoenix Assistant - Launcher Windows
set PHOENIX_ROOT=%~dp0
set DATA_DIR=%APPDATA%\\Phoenix

if not exist "%DATA_DIR%" (
    echo Premiere execution: configuration...
    "%PHOENIX_ROOT%venv\\Scripts\\python" "%PHOENIX_ROOT%scripts\\bootstrap.py" --no-download
)

"%PHOENIX_ROOT%venv\\Scripts\\python" "%PHOENIX_ROOT%mycroft\\audio\\voice_loop.py" %*
"""
    else:
        return f"""#!/bin/bash
# Phoenix Assistant - Launcher Linux/macOS
PHOENIX_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Détection XDG
if [ "$(uname)" = "Darwin" ]; then
    DATA_DIR="$HOME/Library/Application Support/Phoenix"
else
    DATA_DIR="${{XDG_DATA_HOME:-$HOME/.local/share}}/phoenix"
fi

export PHOENIX_DATA_DIR="$DATA_DIR"

# Premier lancement
if [ ! -d "$DATA_DIR" ]; then
    echo "Première exécution : configuration..."
    "$PHOENIX_ROOT/venv/bin/python" "$PHOENIX_ROOT/scripts/bootstrap.py" --no-download
fi

exec "$PHOENIX_ROOT/venv/bin/python" "$PHOENIX_ROOT/mycroft/audio/voice_loop.py" "$@"
"""


def build(target_os: str):
    print(f"=== Build portable Phoenix ({target_os}) ===")

    # Nettoyer
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    # Créer venv
    venv_dir = BUILD_DIR / "venv"
    print("Création du venv...")
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

    if target_os == "Windows":
        pip = venv_dir / "Scripts" / "python"
    else:
        pip = venv_dir / "bin" / "python"

    # Installer les dépendances dans le venv
    print("Installation des dépendances...")
    req = PROJECT_ROOT / "requirements" / "phoenix.txt"
    subprocess.run([str(pip), "-m", "pip", "install", "-r", str(req)], check=True)

    # Copier le code source
    print("Copie du code source...")
    for item in PROJECT_ROOT.iterdir():
        if item.name.startswith(".") or item.name in EXCLUDES or item.name == "dist":
            continue
        if item.is_dir():
            dest = BUILD_DIR / item.name
            shutil.copytree(item, dest, ignore=shutil.ignoredirs(*EXCLUDES))
        else:
            shutil.copy2(item, BUILD_DIR / item.name)

    # Nettoyer les .pyc et cachés
    for pyc in BUILD_DIR.rglob("__pycache__"):
        shutil.rmtree(pyc)
    for pyc in BUILD_DIR.rglob("*.pyc"):
        pyc.unlink()

    # Launcher
    print("Création du launcher...")
    launcher_content = create_launcher(target_os, str(pip))
    if target_os == "Windows":
        launcher = BUILD_DIR / "phoenix.bat"
        launcher.write_text(launcher_content)
    else:
        launcher = BUILD_DIR / "phoenix.sh"
        launcher.write_text(launcher_content)
        launcher.chmod(0o755)

    # README
    readme = BUILD_DIR / "README.txt"
    readme.write_text(f"""Phoenix Assistant v2.0 - Distribution Portable ({target_os})
{'='*60}

Utilisation:
  {target_os == "Windows" and "phoenix.bat" or "./phoenix.sh"}

Premier lancement:
  Le script crée automatiquement les bases de données Kuzu
  et télécharge les modèles (Vosk, Piper) dans votre
  répertoire utilisateur.

  Windows: %APPDATA%/Phoenix/
  macOS:   ~/Library/Application Support/Phoenix/
  Linux:   ~/.local/share/phoenix/

Les fichiers suivants sont dans ce zip:
  mycroft/audio/voice_loop.py - Boucle vocale principale
  scripts/         - Bootstrap et outils
  mycroft/         - Pipeline NLU et modules
  skills/          - Skills (storyteller, etc.)
  intents/         - Base d'intents
  venv/            - Environnement Python pré-installé
""")

    # Zipper
    print("Création du zip...")
    zip_name = PROJECT_ROOT / "dist" / f"phoenix-portable-{target_os.lower()}.zip"
    zip_name.parent.mkdir(parents=True, exist_ok=True)
    if zip_name.exists():
        zip_name.unlink()

    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(str(BUILD_DIR)):
            for f in files:
                file_path = os.path.join(root, f)
                arcname = os.path.relpath(file_path, str(BUILD_DIR))
                zf.write(file_path, arcname)

    print(f"Zip créé: {zip_name}")
    print(f"Taille: {zip_name.stat().st_size / 1024 / 1024:.1f} MB")

    # Nettoyer le répertoire de build
    shutil.rmtree(BUILD_DIR)
    print("Terminé.")


def main():
    parser = argparse.ArgumentParser(description="Build Phoenix portable")
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument("--windows", action="store_true", help="Build Windows")
    targets.add_argument("--macos", action="store_true", help="Build macOS")
    targets.add_argument("--linux", action="store_true", help="Build Linux (défaut)")
    targets.add_argument("--all", action="store_true", help="Build les 3")
    args = parser.parse_args()

    if args.all:
        build("Windows")
        build("Darwin")
        build("Linux")
    elif args.windows:
        build("Windows")
    elif args.macos:
        build("Darwin")
    else:
        build("Linux")


if __name__ == "__main__":
    main()
