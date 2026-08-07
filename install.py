#!/usr/bin/env python3
"""
Phoenix Installer — cross-platform (Windows / Linux / macOS)

Supports 3 modes automatiquement détectés:

  Mode source (git clone)       → venv + pip install + init kuzu + modèles
  Mode pip install -e .          → init kuzu + modèles
  Mode standalone (exe)          → init kuzu + modèles

Usage:
    python install.py                # Installation complète
    python install.py --check        # Vérifier seulement
    python install.py --no-venv      # Forcer saut du venv
    python install.py --no-models    # Forcer saut des modèles STT/TTS
"""
import os
import sys
import subprocess
import platform
import urllib.request
import zipfile
import tarfile
import shutil
import json
from pathlib import Path
from typing import Optional, Tuple

MIN_PYTHON = (3, 10)
PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / "venv"
HERE = PROJECT_ROOT


# ── Couleurs ──
def _c(code: int, s: str) -> str:
    return s if not sys.stdout.isatty() else f"\033[{code}m{s}\033[0m"


green  = lambda t: _c(92, t)
yellow = lambda t: _c(93, t)
red    = lambda t: _c(91, t)
cyan   = lambda t: _c(96, t)
bold   = lambda t: _c(1, t)


# ── Détection du mode d'installation ──

def detect_mode() -> str:
    """Retourne 'source', 'editable', ou 'standalone'."""
    frozen = getattr(sys, "frozen", False)
    if frozen:
        return "standalone"

    # Vérifie si on est dans un pip install -e . ou pip install .
    pkg_file = HERE / "mycroft" / "py.typed"
    egg_link = list(HERE.glob("*.egg-link"))
    site_pkg = Path(sys.prefix) / "site-packages"
    installed_here = any(
        p.match("mycroft-core*.egg") or p.match("mycroft_core*.egg")
        for p in site_pkg.iterdir()
    ) if site_pkg.exists() else False

    if installed_here or egg_link:
        return "editable"

    return "source"


# ── Python check + auto-install ──

def _suggest_python_url():
    system = platform.system()
    if system == "Windows":
        return "https://www.python.org/downloads/"
    elif system == "Darwin":
        return "https://www.python.org/downloads/"
    return ""


def _auto_install_python() -> bool:
    """Tente d'installer Python automatiquement."""
    system = platform.system()

    if system == "Linux":
        # Detect package manager
        for pm, install_cmd in [
            ("apt-get", "sudo apt-get install -y python3.11 python3.11-venv"),
            ("dnf", "sudo dnf install -y python3.11"),
            ("yum", "sudo yum install -y python3.11"),
            ("pacman", "sudo pacman -S --noconfirm python"),
            ("zypper", "sudo zypper install -y python311"),
        ]:
            if shutil.which(pm):
                print(cyan(f"  Tentative: {install_cmd}"))
                r = subprocess.run(install_cmd.split(), capture_output=True, text=True)
                if r.returncode == 0 and shutil.which("python3.11"):
                    print(green("  Python 3.11 installé ✓"))
                    return True
                break
        return False

    if system == "Darwin":
        if shutil.which("brew"):
            r = subprocess.run(["brew", "install", "python@3.11"], capture_output=True)
            if r.returncode == 0:
                print(green("  Python 3.11 installé via brew ✓"))
                return True
        return False

    if system == "Windows":
        # Télécharge et lance l'installer officiel
        url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
        installer = HERE / "_python_installer.exe"
        print(cyan(f"  Téléchargement Python 3.11..."))
        try:
            urllib.request.urlretrieve(url, installer)
            print(cyan("  Lancement de l'installateur (suivez les instructions)..."))
            subprocess.run([str(installer), "/quiet", "InstallAllUsers=1", "PrependPath=1"])
            installer.unlink(missing_ok=True)
            print(green("  Python 3.11 installé ✓ (redémarrez le terminal si nécessaire)"))
            return True
        except Exception as e:
            print(yellow(f"  Échec: {e}"))
            installer.unlink(missing_ok=True)
            return False

    return False


def _find_other_python() -> Optional[str]:
    """Cherche une version de Python compatible sur le PATH."""
    candidates = []
    system = platform.system()
    if system == "Windows":
        candidates = [
            r"C:\Program Files\Python311\python.exe",
            r"C:\Program Files\Python313\python.exe",
            r"C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe",
        ]
        # Scan via where
        try:
            r = subprocess.run(["where", "python3"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.strip().splitlines():
                p = line.strip()
                if p and p not in candidates:
                    candidates.append(p)
        except Exception:
            pass
    else:
        for name in ["python3.11", "python3.12", "python3.13", "python3.10"]:
            p = shutil.which(name)
            if p:
                candidates.append(p)

    for py in candidates:
        try:
            r = subprocess.run(
                [py, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0:
                ver = r.stdout.strip()
                parts = [int(x) for x in ver.split(".")]
                if (parts[0], parts[1]) >= MIN_PYTHON:
                    return py
        except Exception:
            continue
    return None


def ensure_python() -> Tuple[bool, Optional[str]]:
    """Vérifie Python. Retourne (ok, python_path)."""
    v = sys.version_info
    if (v.major, v.minor) >= MIN_PYTHON:
        print(green(f"  Python {v.major}.{v.minor}.{v.micro} ✓"))
        return True, sys.executable

    print(yellow(f"  Python {v.major}.{v.minor} détecté (minimum: {MIN_PYTHON[0]}.{MIN_PYTHON[1]})"))

    # Cherche un autre Python déjà installé
    other = _find_other_python()
    if other:
        print(green(f"  Trouvé Python compatible: {other}"))
        return True, other

    # Tente une installation automatique
    print(cyan("  Tentative d'installation automatique de Python..."))
    if _auto_install_python():
        other = _find_other_python()
        if other:
            print(green(f"  Utilisation: {other}"))
            return True, other
        return False, None

    print(red(f"\n  Installez Python ≥ {MIN_PYTHON[0]}.{MIN_PYTHON[1]} manuellement:"))
    url = _suggest_python_url()
    if url:
        print(f"    {url}")
    return False, None


# ── Standalone helpers ──

def _standalone_data_dir() -> Path:
    """Répertoire de données pour le mode standalone."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "data"
    return HERE / "data"


# ── Étapes ──

def step_venv(python_path: str, venv_path: Optional[Path] = None) -> Optional[Path]:
    """Crée un venv si pas déjà dedans."""
    in_venv = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )
    if in_venv:
        print(green("  Déjà dans un environnement virtuel ✓"))
        return Path(sys.prefix)

    target = venv_path or VENV_DIR
    if target.exists():
        print(yellow(f"  Le venv existe déjà: {target}"))
        return target

    print(cyan(f"  Création du venv: {target}"))
    r = subprocess.run([python_path, "-m", "venv", str(target)], capture_output=True)
    if r.returncode != 0:
        print(red(f"  Erreur création venv: {r.stderr.decode(errors='replace')[:200]}"))
        return None
    print(green(f"  Venv créé dans {target} ✓"))
    return target


def _venv_python(venv_path: Path) -> str:
    if platform.system() == "Windows":
        return str(venv_path / "Scripts" / "python.exe")
    return str(venv_path / "bin" / "python3")


def step_pip_install(python_path: str):
    """Installe les dépendances."""
    req = HERE / "requirements" / "requirements.txt"
    if not req.exists():
        print(yellow("  requirements/requirements.txt introuvable (skip)"))
        return
    print(cyan(f"  Installation des dépendances..."))
    r = subprocess.run([python_path, "-m", "pip", "install", "-r", str(req)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # Tentative sans version pin
        print(yellow("  Échec — tentative avec les dépendances minimales..."))
        with open(req) as f:
            pkgs = [line.split("==")[0].strip() for line in f
                    if line.strip() and not line.startswith("#")]
        for pkg in pkgs:
            subprocess.run([python_path, "-m", "pip", "install", pkg],
                           capture_output=True)
        print(yellow("  Essayez: pip install -r requirements/requirements.txt"))
    else:
        print(green("  Dépendances installées ✓"))


def step_install_editable(python_path: str):
    """pip install -e . pour le mode source."""
    print(cyan("  Installation du package en mode développement..."))
    r = subprocess.run(
        [python_path, "-m", "pip", "install", "-e", str(HERE)],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print(yellow(f"  ⚠ pip install -e a échoué: {r.stderr[:200]}"))
    else:
        print(green("  Package installé en mode editable ✓"))


def step_init_kuzu(python_path: Optional[str] = None):
    """Initialise les bases Kuzu."""
    interpreter = python_path or sys.executable
    print(cyan("  Initialisation des bases Kuzu..."))
    r = subprocess.run(
        [interpreter, "-c", """
import sys; sys.path.insert(0, r"{}")
try:
    from mycroft.lora.kuzu_manager import KuzuManager
    from mycroft.util.data_dirs import get_data_dir
    mgr = KuzuManager(get_data_dir())
    mgr.initialize()
    s = mgr.status()
    print(f"OK system={s['system']['size_mb']:.1f}MB personal={s['personal']['size_mb']:.1f}MB research={s['research']['size_mb']:.1f}MB")
    mgr.close()
except Exception as e:
    print(f"FAIL {e}")
""".format(HERE)],
        capture_output=True, text=True, timeout=30
    )
    out = r.stdout.strip()
    if "OK" in out:
        print(green(f"  Bases Kuzu initialisées: {out[3:]} ✓"))
    elif "FAIL" in out:
        print(yellow(f"  ⚠ Initialisation Kuzu: {out[5:]}"))
    else:
        print(yellow(f"  ⚠ Initialisation Kuzu: {out[:200]}"))


def step_download_vosk(python_path: Optional[str] = None):
    """Télécharge le modèle Vosk si absent."""
    data_dir = _standalone_data_dir() if detect_mode() == "standalone" else HERE / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    model_dir = data_dir / "vosk-model-small-fr-0.22"

    if model_dir.exists():
        print(green(f"  Modèle Vosk déjà présent ✓"))
        return

    url = "https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip"
    zip_path = data_dir / "vosk-model-small-fr-0.22.zip"

    print(cyan("  Téléchargement du modèle Vosk (35MB)..."))
    try:
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(data_dir)
        zip_path.unlink()
        print(green(f"  Modèle Vosk prêt ✓"))
    except Exception as e:
        print(yellow(f"  ⚠ Téléchargement Vosk: {e}"))
        zip_path.unlink(missing_ok=True)


def step_check_env():
    """Vérification finale."""
    print(cyan("\n── Vérification ──"))
    ok = True

    try:
        import kuzu
        print(green(f"  Kuzu {kuzu.__version__} ✓"))
    except ImportError:
        print(red("  Kuzu manquant (pip install kuzu)"))
        ok = False

    for mod, name in [("vosk", "Vosk"), ("sounddevice", "sounddevice")]:
        try:
            __import__(mod)
            print(green(f"  {name} ✓"))
        except ImportError:
            print(yellow(f"  {name} non installé (optionnel)"))

    return ok


# ── Main ──

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Installation Phoenix")
    parser.add_argument("--check", action="store_true", help="Vérifier l'environnement seulement")
    parser.add_argument("--no-venv", action="store_true", help="Ne pas créer de venv")
    parser.add_argument("--no-models", action="store_true", help="Ne pas télécharger les modèles")
    args = parser.parse_args()

    mode = detect_mode()
    system = platform.system()

    header = f" Installation Phoenix — {system} {platform.machine()} [{mode}]"
    print(bold(f"\n{'═'*len(header)}"))
    print(bold(f"  {header}"))
    print(bold(f"{'═'*len(header)}\n"))

    if args.check:
        sys.exit(0 if step_check_env() else 1)

    # Mode standalone: pas de venv/pip, juste init + modèles
    if mode == "standalone":
        print(bold("1. Base de données"))
        step_init_kuzu()
        if not args.no_models:
            print(bold("\n2. Modèles STT/TTS"))
            step_download_vosk()
        step_check_env()
        print(green(bold("\n✓ Installation standalone terminée\n")))
        return 0

    # Mode source / editable: Python check + venv + pip + init
    ok, python_path = ensure_python()
    if not ok:
        return 1

    if mode == "source":
        if not args.no_venv:
            print(bold("1. Environnement virtuel"))
            venv_path = step_venv(python_path)
            if venv_path:
                python_path = _venv_python(venv_path)

        print(bold("\n2. Dépendances Python"))
        step_pip_install(python_path)

        print(bold("\n3. Installation du package"))
        step_install_editable(python_path)

    # Init Kuzu (toujours)
    print(bold(f"\n{'4' if mode == 'source' else '2'}. Base de données"))
    step_init_kuzu(python_path)

    if not args.no_models:
        print(bold(f"\n{'5' if mode == 'source' else '3'}. Modèles STT/TTS"))
        step_download_vosk(python_path)

    step_check_env()

    print(bold(f"\n{'═'*len(header)}"))
    print(green(bold(f"  Installation réussie\n")))
    print(yellow("  Commandes:"))
    print("    phoenix          → Interface vocale")
    print("    phoenix-chat     → Interface texte")
    print("    phoenix-diag     → Diagnostic audio")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
