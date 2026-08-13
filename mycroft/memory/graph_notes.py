"""
Enregistrement de notes / apprentissages dans le graphe LadybugDB.

Le graphe persiste les faits appris (nodes Statement + tag ``note`` dans
``data/chatterbot/notes.lbdb``) pour les retrouver plus tard (résultats de
tests, décisions, apprentissages). LadybugDB = mémoire tenace du core.

CLI::

    python -m mycroft.memory record "contenu" \\
        [--category dev] [--tags opencode,backend] [--base-dir <dir>]
    python -m mycroft.memory list [--limit 20] [--base-dir <dir>]

``base-dir`` par défaut = répertoire courant (là où Phoenix écrit ses bases).
"""

import argparse
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def _notes_path(base_dir: Optional[str] = None) -> Path:
    base = Path(base_dir) if base_dir else Path(os.getcwd())
    return base / "data" / "chatterbot" / "notes.lbdb"


def _open_notes(base_dir: Optional[str] = None):
    from mycroft.memory.chatterbot_ladybug import LadybugStorageAdapter

    path = _notes_path(base_dir)
    return LadybugStorageAdapter(db_path=path, read_only=False)


def record(content: str, category: str = "general", tags: str = "",
           base_dir: Optional[str] = None) -> None:
    """Ajoute une note dans le graphe LadybugDB (tag ``note``)."""
    adapter = _open_notes(base_dir)
    try:
        adapter.create(
            text=content.strip(),
            search_text="note " + content.strip(),
            conversation="notes",
            persona="phoenix",
            created_at=datetime.now().isoformat(),
            tags=["note", category, *[t.strip() for t in tags.split(",") if t.strip()]],
        )
        logger.info("Note enregistrée dans le graphe LadybugDB (category=%s)", category)
    finally:
        adapter.close()


def list_notes(limit: int = 20, base_dir: Optional[str] = None) -> List[dict]:
    """Liste les notes récentes du graphe LadybugDB."""
    adapter = _open_notes(base_dir)
    try:
        statements = adapter.filter(tags=["note"], order_by=["created_at"],
                                    page_size=max(int(limit) * 2, 10))
        notes = [
            {"content": st.text, "tags": st.tags, "created_at": st.created_at}
            for st in statements
            if st.conversation == "notes"
        ]
        notes.sort(key=lambda n: str(n["created_at"] or ""), reverse=True)
        return notes[: max(int(limit), 1)]
    finally:
        adapter.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Notes dans le graphe Phoenix (LadybugDB)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_rec = sub.add_parser("record", help="Enregistrer une note")
    p_rec.add_argument("content")
    p_rec.add_argument("--category", default="general")
    p_rec.add_argument("--tags", default="")
    p_rec.add_argument("--base-dir", default=None)

    p_list = sub.add_parser("list", help="Lister les notes")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--base-dir", default=None)

    args = parser.parse_args()

    if args.command == "record":
        record(args.content, category=args.category, tags=args.tags, base_dir=args.base_dir)
        print("OK")
    elif args.command == "list":
        for n in list_notes(limit=args.limit, base_dir=args.base_dir):
            ts = str(n["created_at"])[:19]
            print(f"[{ts}] {n['content']}  tags={','.join(n['tags'])}")


if __name__ == "__main__":
    main()
