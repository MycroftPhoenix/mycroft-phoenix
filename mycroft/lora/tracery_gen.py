"""
Génération de texte procédural (Tracery) pour Phoenix.

- ``generate`` : varie une sortie (personnalité, histoire) → imprime N textes.
- ``train`` : génère des paires (question, réponse) et les injecte dans la
  base utilisateur LadybugDB pour entraîner/varier ChatterBot.

Grammaires : ``data/grammars/<nom>.json``. Symboles racines :
``origin`` pour generate ; ``user`` / ``bot`` pour train (cohérence des paires
via actions ``[cle:valeur]`` partagées).

Exemples ::

    python -m mycroft.lora.tracery_gen generate --grammar variation --count 5
    python -m mycroft.lora.tracery_gen generate --grammar histoire --count 2
    python -m mycroft.lora.tracery_gen train --grammar entrainement --count 200 --base-dir .
"""

import argparse
import json
import logging
import os
import random
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def load_grammar(name_or_path: str, base_dir: Optional[str] = None) -> dict:
    path = Path(name_or_path)
    if not path.exists():
        path = Path(base_dir or os.getcwd()) / "data" / "grammars" / f"{name_or_path}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def generate(grammar: dict, symbol: str = "origin", count: int = 1,
             seed: Optional[int] = None) -> List[str]:
    from mycroft.lora.tracery import Tracery

    rng = random.Random(seed)
    return [Tracery(grammar, rng=rng).expand(symbol).strip()
            for _ in range(int(count))]


def train(grammar: dict, count: int = 200, base_dir: Optional[str] = None,
          lang: str = "fr", seed: Optional[int] = None) -> tuple:
    """Génère des paires (user, bot) cohérentes et les apprend à LadybugDB."""
    from mycroft.lora.chatterbot_ladybug import LadybugStorageAdapter, normalize
    from mycroft.lora.tracery import Tracery

    base = Path(base_dir or os.getcwd())
    path = base / "data" / "chatterbot" / f"{lang}_user.lbdb"
    path.parent.mkdir(parents=True, exist_ok=True)

    adapter = LadybugStorageAdapter(db_path=path, read_only=False)
    rng = random.Random(seed)
    n = 0
    try:
        for _ in range(int(count)):
            # un seul Tracery par paire : les actions [cle:valeur] du user
            # (ex. l'objet) sont réutilisées par le bot via la pile.
            t = Tracery(grammar, rng=rng)
            q = t.expand("user").strip()
            a = t.expand("bot").strip()
            if not q or not a:
                continue
            # Même comportement que LadybugChatter.learn, plus la création
            # explicite de la question (issue de la génération, donc inconnue).
            adapter.create(
                text=q,
                search_text=normalize(q),
                search_in_response_to="",
                conversation="main",
                persona="user",
            )
            adapter.create(
                text=a,
                in_response_to=q,
                search_in_response_to=q,
                search_text=normalize(a),
                conversation="main",
                persona="phoenix",
            )
            adapter.link_response(a, q)
            n += 1
    finally:
        adapter.close()
    return n, str(path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Génération procédurale (Tracery)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="Générer des textes variés")
    p_gen.add_argument("--grammar", required=True, help="nom ou chemin de la grammaire")
    p_gen.add_argument("--symbol", default="origin")
    p_gen.add_argument("--count", type=int, default=1)
    p_gen.add_argument("--seed", type=int, default=None)
    p_gen.add_argument("--base-dir", default=None)

    p_tr = sub.add_parser("train", help="Générer des paires et les apprendre à LadybugDB")
    p_tr.add_argument("--grammar", required=True)
    p_tr.add_argument("--count", type=int, default=200)
    p_tr.add_argument("--lang", default="fr")
    p_tr.add_argument("--seed", type=int, default=None)
    p_tr.add_argument("--base-dir", default=None)

    args = parser.parse_args()

    try:
        grammar = load_grammar(args.grammar, args.base_dir)
    except FileNotFoundError:
        print(f"Grammaire introuvable : {args.grammar} "
              f"(data/grammars/<nom>.json ou chemin)", file=sys.stderr)
        sys.exit(1)

    if args.command == "generate":
        for text in generate(grammar, symbol=args.symbol, count=args.count, seed=args.seed):
            print(text)
    elif args.command == "train":
        n, path = train(grammar, count=args.count, base_dir=args.base_dir,
                        lang=args.lang, seed=args.seed)
        print(f"{n} paires apprises dans {path}")


if __name__ == "__main__":
    main()
