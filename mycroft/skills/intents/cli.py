"""
CLI `phoenix-skill-intent` — gestion des intents de skills.

Usage:
    phoenix-skill-intent add SKILL INTENT --examples "..." [...] [--backend json|ladybug|kuzu]
    phoenix-skill-intent list [--skill NAME] [--backend ...]
    phoenix-skill-intent remove SKILL INTENT --example "..." [--backend ...]
    phoenix-skill-intent load SKILL [--backend ladybug]   # skill.json -> graphe
    phoenix-skill-intent migrate --from json --to ladybug # sync backends

La base opérationnelle phoenix.kuzu reste verrouillée (WriteQueue uniquement).
Cet outil écrit dans la base DÉDIÉE data/skills_intents.kuzu et/ou skill.json.
"""

import argparse
import os
import sys
from pathlib import Path

from mycroft.skills.intents.backends import get_backend


def _default_skills_dir() -> Path:
    """Racine du projet depuis ce fichier (mycroft/skills/intents/..)."""
    return Path(__file__).resolve().parents[3] / "mycroft" / "skills"


def _default_db_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "skills_intents.kuzu"


def cmd_add(args) -> int:
    backend = get_backend(args.backend, args.skills_dir, args.db_path)
    if not args.examples:
        print("Erreur: au moins un --examples requis.", file=sys.stderr)
        return 2
    backend.add_intent(args.skill, args.intent, args.examples)
    print(f"[OK] Intent '{args.intent}' de la skill '{args.skill}' ajouté "
          f"(backend {backend.name}, {len(args.examples)} exemples).")
    return 0


def cmd_list(args) -> int:
    intents = get_backend(args.backend, args.skills_dir, args.db_path).list_intents()
    if args.skill:
        intents = {k: v for k, v in intents.items() if k.startswith(args.skill + ".") or k == args.skill}
    if not intents:
        print(f"(aucun intent — backend {args.backend})")
        return 0
    for name, examples in sorted(intents.items()):
        print(f"{name} ({len(examples)}):")
        for ex in examples:
            print(f"  - {ex}")
    return 0


def cmd_remove(args) -> int:
    backend = get_backend(args.backend, args.skills_dir, args.db_path)
    ok = backend.remove_example(args.skill, args.intent, args.example)
    if ok:
        print(f"[OK] Exemple supprimé de '{args.intent}'.")
        return 0
    print(f"Exemple introuvable dans '{args.intent}' (backend {backend.name}).", file=sys.stderr)
    return 1


def cmd_load(args) -> int:
    """Charge les intents d'une skill.json vers le graphe (et inversement)."""
    json_be = get_backend("json", args.skills_dir, args.db_path)
    graph_be = get_backend(args.backend, args.skills_dir, args.db_path)
    if args.backend == "json":
        print("load: la cible est déjà json, rien à faire.", file=sys.stderr)
        return 2
    skill_path = json_be.skill_path(args.skill)
    if not skill_path.exists():
        print(f"skill.json introuvable: {skill_path}", file=sys.stderr)
        return 1
    data = {}
    import json as _json
    with open(skill_path, encoding="utf-8") as f:
        data = _json.load(f)
    count = 0
    for it in data.get("intents", []):
        name = it.get("name")
        examples = it.get("examples") or it.get("utterances") or []
        if name and examples:
            graph_be.add_intent(args.skill, name, examples)
            count += 1
    print(f"[OK] {count} intents de '{args.skill}' chargés dans le graphe ({args.backend}).")
    return 0


def cmd_migrate(args) -> int:
    src = get_backend(args.from_backend, args.skills_dir, args.db_path)
    dst = get_backend(args.to_backend, args.skills_dir, args.db_path)
    intents = src.load()
    count = 0
    for name, examples in intents.items():
        skill = name.split(".")[0]
        dst.add_intent(skill, name, examples)
        count += len(examples)
    print(f"[OK] Migration {args.from_backend} -> {args.to_backend}: {count} exemples.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="phoenix-skill-intent",
        description="Gestion des intents de skills (JSON skill.json / LadybugDB / Kuzu).",
    )
    parser.add_argument("--skills-dir", type=Path, default=_default_skills_dir(),
                        help="répertoire des skills (défaut: mycroft/skills)")
    parser.add_argument("--db-path", type=Path, default=_default_db_path(),
                        help="base graphe dédiée (défaut: data/skills_intents.kuzu)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="ajouter un intent avec exemples")
    p_add.add_argument("skill")
    p_add.add_argument("intent")
    p_add.add_argument("--examples", nargs="+", required=True)
    p_add.add_argument("--backend", default="ladybug")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="lister les intents")
    p_list.add_argument("--skill", default=None)
    p_list.add_argument("--backend", default="ladybug")
    p_list.set_defaults(func=cmd_list)

    p_rm = sub.add_parser("remove", help="supprimer un exemple d'un intent")
    p_rm.add_argument("skill")
    p_rm.add_argument("intent")
    p_rm.add_argument("--example", required=True)
    p_rm.add_argument("--backend", default="ladybug")
    p_rm.set_defaults(func=cmd_remove)

    p_load = sub.add_parser("load", help="charger skill.json vers le graphe")
    p_load.add_argument("skill")
    p_load.add_argument("--backend", default="ladybug")
    p_load.set_defaults(func=cmd_load)

    p_mig = sub.add_parser("migrate", help="synchroniser deux backends")
    p_mig.add_argument("--from-backend", required=True, choices=["json", "ladybug", "kuzu"])
    p_mig.add_argument("--to-backend", required=True, choices=["json", "ladybug", "kuzu"])
    p_mig.set_defaults(func=cmd_migrate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
