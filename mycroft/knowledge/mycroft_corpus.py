"""
Importer des corpus → LadybugDB (intents de skills + conversations).

Sources :
- Skills Mycroft originaux : ``vocab/<lang>/*.intent`` (phrases d'intention
  padatious, groupes ``(a|b)``) et ``dialog/<lang>/*.dialog`` (templates de
  réponse ``{{var}}``).
- ``mycroft-core/mycroft/res/text/<lang>`` : dialogs système.
- Corpus ChatterBot (optionnel) : paire Q→A conversationnelles.

Cibles (toujours LadybugDB) :
- ``data/skills_intents.lbdb`` : graphe ``Intent -[HAS]-> Utterance``
  (exactitude de la compréhension).
- ``data/chatterbot/<lang>_corpus.lbdb`` : paires Q→A (corpus conversationnel,
  base verrouillée read-only au runtime).

Usage :
    python -m mycroft.knowledge import \
        --lang fr --skills <dossier_skills> --data-dir <data> \
        [--core-res-text <mycroft-core/mycroft/res/text>] [--chatterbot-corpus]
"""

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Code langue Mycroft (dossiers vocab/dialog) par langue Phoenix
LANG_MAP = {
    "fr": "fr-fr",
    "en": "en-us",
    "es": "es-es",
    "de": "de-de",
    "it": "it-it",
    "pt": "pt-pt",
}

_ALT = re.compile(r"\(([^()]*)\)")
_VAR = re.compile(r"\{\{.*?\}\}")  # placeholders de dialogue {{var}}


def normalize(text: str) -> str:
    """Normalisation identique à LadybugChatter (lower + sans accents)."""
    import unicodedata
    t = (text or "").lower().strip()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("œ", "oe").replace("æ", "ae")
    t = t.replace("'", " ").replace("\u2019", " ").replace("\u2018", " ")
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    return " ".join(t.split())


def _tokens(stem: str) -> Set[str]:
    """Tokens d'un nom de fichier : camelCase + séparateurs (HowAreYou → how,are,you)."""
    s = stem
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return {w for w in re.split(r"[^a-z0-9]+", s.lower()) if len(w) >= 3}


def expand_padatious(line: str, max_phrases: int = 8192) -> List[str]:
    """
    Développe une ligne padatious en énoncés explicites.

    ``(quelle heure est-il|l'heure) (maintenant|)`` → toutes les combinaisons
    des groupes d'alternatives ``(a|b|c)`` (une alternative vide autorisée).
    """
    line = line.strip()
    if not line:
        return []
    phrases = [line]
    while True:
        new: List[str] = []
        expanded_any = False
        for p in phrases:
            m = _ALT.search(p)
            if not m:
                new.append(p)
                continue
            expanded_any = True
            prefix, suffix = p[:m.start()], p[m.end():]
            for choice in m.group(1).split("|"):
                cand = (prefix + choice + suffix)
                cand = re.sub(r"\s{2,}", " ", cand).strip()
                new.append(cand)
        phrases = new
        if not expanded_any or len(phrases) > max_phrases:
            break
    return [p for p in phrases if p]


def read_intents(skill_dir: Path, lang_code: str) -> Dict[str, List[str]]:
    """{intent_stem: [utterances]} depuis vocab/<lang>/*.intent."""
    result: Dict[str, List[str]] = {}
    vocab = skill_dir / "vocab" / lang_code
    if not vocab.exists():
        return result
    for f in sorted(vocab.glob("*.intent")):
        utterances: List[str] = []
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:
            logger.warning("intent illisible %s: %s", f, e)
            continue
        for line in lines:
            utterances.extend(expand_padatious(line))
        if utterances:
            result[f.stem] = list(dict.fromkeys(utterances))
    return result


def read_dialogs(skill_dir: Path, lang_code: str) -> Dict[str, List[str]]:
    """{dialog_stem: [lines]} depuis dialog/<lang>/*.dialog."""
    result: Dict[str, List[str]] = {}
    dialog = skill_dir / "dialog" / lang_code
    if not dialog.exists():
        return result
    for f in sorted(dialog.glob("*.dialog")):
        try:
            lines = [l.strip() for l in f.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        except Exception as e:
            logger.warning("dialog illisible %s: %s", f, e)
            continue
        if lines:
            result[f.stem] = lines
    return result


def _match_dialog_stems(intent_stem: str, dialog_stems: List[str]) -> List[str]:
    """Dialog stems dont un token commun avec l'intent (ex. time)."""
    it = _tokens(intent_stem)
    return [s for s in dialog_stems if it & _tokens(s)]


def import_mycroft_skills(
    skills_root: Path,
    lang: str,
    intents_db: Path,
    corpus_db: Optional[Path] = None,
    max_dialog_pairs: int = 20,
) -> Dict[str, int]:
    """
    Importe les intents et dialogs des skills Mycroft dans LadybugDB.

    Returns:
        {"skills": n, "intents": n, "utterances": n, "dialog_lines": n, "pairs": n}
    """
    from mycroft.skills.intents.backends import get_backend

    lang_code = LANG_MAP.get(lang, lang)
    skills_root = Path(skills_root)

    backend = get_backend("ladybug", skills_root, Path(intents_db))

    corpus = None
    if corpus_db is not None:
        from mycroft.memory.chatterbot_ladybug import LadybugStorageAdapter
        corpus = LadybugStorageAdapter(db_path=corpus_db, read_only=False)

    stats = {"skills": 0, "intents": 0, "utterances": 0, "dialog_lines": 0, "pairs": 0}

    skill_dirs = [d for d in sorted(skills_root.iterdir()) if d.is_dir() and not d.name.startswith(".")]
    for skill_dir in skill_dirs:
        intents = read_intents(skill_dir, lang_code)
        dialogs = read_dialogs(skill_dir, lang_code)
        if not intents and not dialogs:
            continue

        stats["skills"] += 1
        skill_name = skill_dir.name

        # 1. Intents → graphe Intent -[HAS]-> Utterance
        for stem, utterances in intents.items():
            intent_name = f"{skill_name}.{stem}"
            backend.add_intent(skill=skill_name, intent=intent_name, examples=utterances)
            stats["intents"] += 1
            stats["utterances"] += len(utterances)
            logger.info("intent %s (%d utterances)", intent_name, len(utterances))

        if corpus is None:
            continue

        # 2. Dialogs → corpus (statements + paires Q→A)
        for stem, lines in dialogs.items():
            for ln in lines:
                corpus.create(
                    text=ln,
                    search_text=normalize(ln),
                    tags=[f"skill:{skill_name}", "mycroft:dialog"],
                    persona="mycroft",
                )
            stats["dialog_lines"] += len(lines)

        # 3. Paires Q→A dans le graphe : noeuds question/réponse reliés par
        #    RESPONDS_TO (texte unique = PK, relation 1..N sans perte).
        dialog_stems = list(dialogs.keys())
        for stem, utterances in intents.items():
            target = _match_dialog_stems(stem, dialog_stems)
            if not target and stem in dialogs:
                target = [stem]
            if not target:
                # Pas de dialog pertinent → pas d'appariement hasardeux
                continue
            lines = [ln for s in target for ln in dialogs[s]]
            for u in utterances:
                q = normalize(u)
                if not q:
                    continue
                for ln in lines[:max_dialog_pairs]:
                    corpus.create(
                        text=ln,
                        search_text=normalize(ln),
                        tags=[f"skill:{skill_name}", f"intent:{stem}"],
                        persona="mycroft",
                    )
                    corpus.create(
                        text=q,
                        search_text=q,
                        tags=["question", f"skill:{skill_name}", f"intent:{stem}"],
                        persona="user",
                    )
                    corpus.link_response(answer_text=ln, question_text=q)
            stats["pairs"] += len(utterances) * min(len(lines), max_dialog_pairs)

    if corpus is not None:
        corpus.close()
    return stats


def import_core_res_text(res_text_root: Path, lang: str, corpus_db: Path) -> int:
    """Importe les dialogs syst��me de mycroft-core (res/text/<lang>)."""
    from mycroft.memory.chatterbot_ladybug import LadybugStorageAdapter

    lang_code = LANG_MAP.get(lang, lang)
    lang_dir = Path(res_text_root) / lang_code
    if not lang_dir.exists():
        logger.warning("res/text/%s introuvable: %s", lang_code, lang_dir)
        return 0

    corpus = LadybugStorageAdapter(db_path=corpus_db, read_only=False)
    n = 0
    for f in sorted(lang_dir.glob("*.dialog")):
        try:
            lines = [l.strip() for l in f.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        except Exception as e:
            logger.warning("dialog core illisible %s: %s", f, e)
            continue
        for ln in lines:
            corpus.create(
                text=ln,
                search_text=normalize(ln),
                tags=["mycroft:core", f"core:{f.stem}"],
                persona="mycroft",
            )
            n += 1
    corpus.close()
    logger.info("res/text/%s : %d lignes de dialogue importées", lang_code, n)
    return n


def import_chatterbot_corpus(lang: str, corpus_db: Path, name: str = "Phoenix") -> int:
    """
    Entraîne le corpus conversationnel ChatterBot dans la base LadybugDB.

    Nécessite chatterbot + chatterbot-corpus (shim chatterbot_corpus).
    """
    from mycroft.memory.chatterbot_ladybug import LadybugStorageAdapter

    try:
        from chatterbot import ChatBot
        from chatterbot.trainers import ChatterBotCorpusTrainer
    except ImportError as e:
        logger.warning("chatterbot indisponible, corpus ChatterBot ignoré: %s", e)
        return 0

    # Noms de corpus ChatterBot par langue Phoenix (data/<english|french|...>)
    CB_LANG = {
        "fr": "french", "en": "english", "es": "spanish",
        "de": "german", "it": "italian", "pt": "portuguese",
    }
    corpus_name = f"chatterbot.corpus.{CB_LANG.get(lang, lang)}"

    bot = ChatBot(
        name,
        storage_adapter="mycroft.memory.LadybugStorageAdapter",
        db_path=str(corpus_db),
        read_only=False,
        logic_adapters=["chatterbot.logic.BestMatch"],
    )
    trainer = ChatterBotCorpusTrainer(bot)
    trainer.train(corpus_name)
    bot.storage.close()
    try:
        return LadybugStorageAdapter(db_path=corpus_db).count()
    except Exception:
        return -1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="mycroft.knowledge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="Importe les corpus dans LadybugDB")
    p.add_argument("--lang", default="fr", help="Langue Phoenix (fr, en, es, de, it, pt)")
    p.add_argument("--skills", required=True, help="Dossier racine des skills Mycroft")
    p.add_argument("--data-dir", default="data", help="Dossier data/ (cibles LadybugDB)")
    p.add_argument("--core-res-text", default=None, help="mycroft-core/mycroft/res/text (optionnel)")
    p.add_argument("--chatterbot-corpus", action="store_true", help="Importe aussi le corpus ChatterBot")
    p.add_argument("--skills-intents", default=None, help="Base d'intents (défaut: data/skills_intents.lbdb)")

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.cmd == "import":
        data_dir = Path(args.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        intents_db = Path(args.skills_intents or (data_dir / "skills_intents.lbdb"))
        corpus_db = data_dir / "chatterbot" / f"{args.lang}_corpus.lbdb"

        stats = import_mycroft_skills(
            Path(args.skills),
            lang=args.lang,
            intents_db=intents_db,
            corpus_db=corpus_db,
        )
        print("Skills Mycroft importés:", stats)

        if args.core_res_text:
            n = import_core_res_text(Path(args.core_res_text), args.lang, corpus_db)
            print(f"Dialogs système (res/text): {n}")

        if args.chatterbot_corpus:
            n = import_chatterbot_corpus(args.lang, corpus_db)
            print(f"Corpus ChatterBot: {n} statements")

        print(f"Corpus: {corpus_db}")
        print(f"Intents: {intents_db}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
