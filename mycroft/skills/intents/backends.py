"""
Backends de stockage des intents de skills.

Chaque skill déclare ses intents (nom + exemples). Ils peuvent être stockés :
- en JSON (fichier `skill.json` de la skill) — source déclarative partagée
- en graphe (LadybugDB par défaut, Kuzu en option) — base dédiée
  `data/skills_intents.kuzu`

La base opérationnelle `phoenix.kuzu` est VERROUILLÉE : toute écriture passe
par la WriteQueue (`kuzu_resilience.py`), jamais par cet outil.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Abstraction ────────────────────────────────────────────────────────────

class SkillIntentBackend:
    """Interface commune : nom, intents, ajout, suppression, chargement."""

    name: str = "abstract"

    def load(self) -> Dict[str, List[str]]:
        """Retourne {intent_name: [examples]}."""
        raise NotImplementedError

    def add_intent(self, skill: str, intent: str, examples: List[str]) -> None:
        raise NotImplementedError

    def remove_example(self, skill: str, intent: str, example: str) -> bool:
        raise NotImplementedError

    def list_intents(self) -> Dict[str, List[str]]:
        return self.load()


# ── Backend JSON (skill.json) ──────────────────────────────────────────────

class JsonIntentBackend(SkillIntentBackend):
    """Lit/écrit `mycroft/skills/<skill>/skill.json` (intents[].examples)."""

    name = "json"

    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)

    def skill_path(self, skill: str) -> Path:
        return self.skills_dir / skill / "skill.json"

    def load(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for skill_json in sorted(self.skills_dir.glob("*/skill.json")):
            try:
                with open(skill_json, encoding="utf-8") as f:
                    data = json.load(f)
                for intent_data in data.get("intents", []):
                    name = intent_data.get("name")
                    if not name:
                        continue
                    examples = intent_data.get("examples") or intent_data.get("utterances") or []
                    result[name] = list(examples)
            except Exception as e:
                logger.warning("skill.json illisible %s: %s", skill_json, e)
        return result

    def add_intent(self, skill: str, intent: str, examples: List[str]) -> None:
        path = self.skill_path(skill)
        data = {}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        data.setdefault("name", skill)
        data.setdefault("version", "1.0.0")
        data.setdefault("intents", [])
        entry = None
        for it in data["intents"]:
            if it.get("name") == intent:
                entry = it
                break
        if entry is None:
            entry = {"name": intent, "examples": []}
            data["intents"].append(entry)
        entry.setdefault("examples", [])
        for ex in examples:
            if ex not in entry["examples"]:
                entry["examples"].append(ex)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def remove_example(self, skill: str, intent: str, example: str) -> bool:
        path = self.skill_path(skill)
        if not path.exists():
            return False
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        removed = False
        for it in data.get("intents", []):
            if it.get("name") == intent:
                examples = it.get("examples", [])
                if example in examples:
                    examples.remove(example)
                    removed = True
        if removed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        return removed


# ── Backend graphe (LadybugDB / Kuzu) ──────────────────────────────────────

class GraphIntentBackend(SkillIntentBackend):
    """
    Base dédiée `data/skills_intents.kuzu` (LadybugDB par défaut, Kuzu en
    option). Schéma : Intent(name) -[HAS]-> Utterance(text).

    N'écrit JAMAIS dans phoenix.kuzu (base opérationnelle verrouillée).
    """

    name = "ladybug"  # surchargé selon le module chargé

    def __init__(self, db_path: Path, module: str = "ladybug"):
        self.db_path = Path(db_path)
        self.module = module
        if module == "kuzu":
            import kuzu as graph
            self.name = "kuzu"
        else:
            import real_ladybug as graph
            self.name = "ladybug"
        self._graph = graph
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self):
        db = self._graph.Database(str(self.db_path))
        return self._graph.Connection(db)

    def _init_schema(self) -> None:
        conn = self._conn()
        try:
            conn.execute("CREATE NODE TABLE Intent (name STRING, skill STRING, PRIMARY KEY (name))")
        except Exception:
            pass
        try:
            conn.execute("CREATE NODE TABLE Utterance (text STRING, PRIMARY KEY (text))")
        except Exception:
            pass
        try:
            conn.execute("CREATE REL TABLE HAS (FROM Intent TO Utterance)")
        except Exception:
            pass
        try:
            conn.execute("CREATE NODE TABLE IntentIndex (id INT64, intent_name STRING, PRIMARY KEY (id))")
        except Exception:
            pass

    def load(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        try:
            conn = self._conn()
            r = conn.execute(
                "MATCH (i:Intent)-[:HAS]->(u:Utterance) RETURN i.name, u.text ORDER BY i.name"
            )
            for row in r.get_as_arrow().to_pylist():
                name = row.get("i.name")
                text = row.get("u.text")
                if name and text:
                    result.setdefault(name, []).append(text)
        except Exception as e:
            logger.warning("lecture graphe d'intents impossible: %s", e)
        return result

    def add_intent(self, skill: str, intent: str, examples: List[str]) -> None:
        conn = self._conn()
        for ex in examples:
            conn.execute(
                "MERGE (i:Intent {name: $n, skill: $s})",
                parameters={"n": intent, "s": skill},
            )
            conn.execute(
                "MERGE (u:Utterance {text: $t})",
                parameters={"t": ex},
            )
            conn.execute(
                "MATCH (i:Intent {name: $n}) MATCH (u:Utterance {text: $t}) "
                "MERGE (i)-[:HAS]->(u)",
                parameters={"n": intent, "t": ex},
            )

    def remove_example(self, skill: str, intent: str, example: str) -> bool:
        conn = self._conn()
        try:
            conn.execute(
                "MATCH (i:Intent {name: $n})-[r:HAS]->(u:Utterance {text: $t}) DELETE r",
                parameters={"n": intent, "t": example},
            )
            return True
        except Exception as e:
            logger.warning("suppression graphe impossible: %s", e)
            return False


# ── Fabrique ───────────────────────────────────────────────────────────────

DEFAULT_DB_PATH = Path("data/skills_intents.kuzu")


def get_backend(backend: str, skills_dir: Path, db_path: Path = DEFAULT_DB_PATH) -> SkillIntentBackend:
    """Retourne le backend demandé (json | ladybug | kuzu)."""
    backend = (backend or "ladybug").lower()
    if backend == "json":
        return JsonIntentBackend(skills_dir)
    if backend in ("ladybug", "kuzu"):
        return GraphIntentBackend(db_path, module=backend)
    raise ValueError(f"backend inconnu: {backend} (json, ladybug, kuzu)")
