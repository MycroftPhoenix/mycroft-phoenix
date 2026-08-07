#!/usr/bin/env python3
"""Gestionnaire de skills Mycroft Phoenix.

- list : liste les skills installes et disponibles (catalogue GitHub)
- install <nom> : installe un skill par nom
- remove <nom> : desinstalle un skill
- requirements <nom> : affiche / installe les dependances pip d'un skill

Usage:
    python -m mycroft.skills_manager list
    python -m mycroft.skills_manager install <nom>
    python -m mycroft.skills_manager remove <nom>
    python -m mycroft.skills_manager requirements <nom>
    python -m mycroft.skills_manager web            # serveur web local
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def default_skills_dir():
    from mycroft.data_manager import DataManager
    dm = DataManager()
    return dm.get_data_dir() / "skills"


def _manager():
    from mycroft.skills_manager.manager import SkillsManager
    skills_dir = default_skills_dir()
    print(f"Repertoire skills : {skills_dir}")
    return SkillsManager(skills_dir)


def cmd_list(show_all=True):
    m = _manager()
    installed = m.list_installed()
    print(f"\n=== Skills installes ({len(installed)}) ===")
    for s in installed:
        print(f"  {s['name']:20} v{s['version']:8} {s['description']}")
    try:
        remote = m.list_remote()
        print(f"\n=== Disponibles dans le catalogue ({len(remote)}) ===")
        for s in remote:
            mark = "[installe]" if s["installed"] else "[dispo]    "
            print(f"  {mark} {s['name']:20} v{s['version']:8} {s['description']}")
    except Exception as e:
        print(f"\n(!) Catalogue indisponible: {e}")
        print("    Le depot est peut-etre prive ou hors ligne.")


def cmd_install(name):
    m = _manager()
    print(f"Installation de '{name}'...")
    try:
        dest = m.install(name)
        print(f"OK : {dest}")
        req = m.skill_requirements(name)
        if req:
            print(f"\nDependances pip de '{name}' :\n{req}")
            answer = input("Installer ces dependances ? [o/N] ").strip().lower()
            if answer in ("o", "oui", "y", "yes"):
                result = m.install_requirements(name)
                print(result.stdout or result.stderr or "dependances installees")
        else:
            print("Aucune dependance pip.")
    except FileExistsError as e:
        print(f"(!) {e}")
    except ValueError as e:
        print(f"(!) {e}")
    except Exception as e:
        print(f"(!) Erreur: {e}")


def cmd_remove(name):
    m = _manager()
    print(f"Desinstallation de '{name}'...")
    try:
        m.remove(name)
        print("OK")
    except FileNotFoundError as e:
        print(f"(!) {e}")
    except Exception as e:
        print(f"(!) Erreur: {e}")


def cmd_requirements(name):
    m = _manager()
    req = m.skill_requirements(name)
    if req:
        print(f"Requirements de '{name}' :\n{req}")
    else:
        print(f"'{name}' non installe ou sans dependances.")


def cmd_web():
    try:
        from mycroft.skills_manager.web import SkillsWeb
        SkillsWeb().start()
    except Exception as e:
        print(f"(!) Erreur serveur web: {e}")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        cmd_list()
        return 0
    cmd = argv[0]
    if cmd == "list":
        cmd_list()
    elif cmd == "install" and len(argv) > 1:
        cmd_install(argv[1])
    elif cmd == "remove" and len(argv) > 1:
        cmd_remove(argv[1])
    elif cmd == "requirements" and len(argv) > 1:
        cmd_requirements(argv[1])
    elif cmd == "web":
        cmd_web()
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
