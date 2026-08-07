"""Base Kuzu dédiée aux histoires — complètement indépendante.

Ne partage RIEN avec phoenix.kuzu / phoenix_personal.kuzu.
Les histoires sont de la fiction et ne doivent pas contaminer
les conversations réelles, la détection de crise, ou les intents.

Schéma:
  Story (id, title, content, theme, characters, age_group, language, source, created_at)
  StoryCharacter (name, voice, description, created_at)
  HAS_CHARACTER (FROM Story TO StoryCharacter)
"""

import kuzu
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

SCHEMA_NODES = [
    "CREATE NODE TABLE IF NOT EXISTS Story (id STRING PRIMARY KEY, title STRING, content STRING, theme STRING, characters STRING, age_group STRING, language STRING, source STRING, created_at STRING)",
    "CREATE NODE TABLE IF NOT EXISTS StoryCharacter (name STRING PRIMARY KEY, voice STRING, description STRING, created_at STRING)",
]

SCHEMA_RELS = [
    "CREATE REL TABLE IF NOT EXISTS HAS_CHARACTER (FROM Story TO StoryCharacter)",
]


class StoryDatabase:
    """Base de données d'histoires uniquement — zéro contamination."""

    def __init__(self, db_dir: str = None):
        if db_dir is None:
            from mycroft.util.data_dirs import get_kuzu_path
            db_dir = os.environ.get(
                "PHOENIX_STORY_DB",
                get_kuzu_path("phoenix_stories"),
            )
        self.db_path = db_dir
        self._db: Optional[kuzu.Database] = None
        self._conn: Optional[kuzu.Connection] = None

    def initialize(self) -> bool:
        try:
            self._db = kuzu.Database(self.db_path)
            self._conn = kuzu.Connection(self._db)
            existing = self._get_table_names()
            for stmt in SCHEMA_NODES:
                name = stmt.split(" ")[3]
                if name not in existing:
                    self._conn.execute(stmt)
                    logger.info("Table %s créée", name)
            for stmt in SCHEMA_RELS:
                name = stmt.split(" ")[3]
                if name not in existing:
                    self._conn.execute(stmt)
                    logger.info("Relation %s créée", name)
            logger.info("StoryDatabase prête: %s", self.db_path)
            return True
        except Exception as e:
            logger.error("Erreur init StoryDatabase: %s", e)
            return False

    def _get_table_names(self) -> List[str]:
        try:
            r = self._conn.execute("CALL show_tables() RETURN *")
            names = []
            while r.has_next():
                names.append(r.get_next()[1])
            return names
        except Exception:
            return []

    def add(self, title: str, content: str, theme: str = "",
            characters: str = "", age_group: str = "",
            language: str = "fr", source: str = "generated") -> Optional[str]:
        sid = str(uuid.uuid4())[:12]
        ts = datetime.now().isoformat()
        safe = lambda s: s.replace("'", "\\'") if s else ""
        try:
            self._conn.execute(f"""
                CREATE (s:Story {{
                    id: '{sid}',
                    title: '{safe(title)}',
                    content: '{safe(content)[:10000]}',
                    theme: '{safe(theme)}',
                    characters: '{safe(characters)}',
                    age_group: '{safe(age_group)}',
                    language: '{safe(language)}',
                    source: '{safe(source)}',
                    created_at: '{ts}'
                }})
            """)
            return sid
        except Exception as e:
            logger.debug("Erreur add story: %s", e)
            return None

    def get(self, story_id: str) -> Optional[Dict]:
        try:
            r = self._conn.execute(f"""
                MATCH (s:Story {{id: '{story_id}'}})
                RETURN s.title, s.content, s.theme, s.characters,
                       s.age_group, s.language, s.source, s.created_at
            """)
            if r.has_next():
                row = r.get_next()
                return {"id": story_id, "title": row[0], "content": row[1],
                        "theme": row[2], "characters": row[3],
                        "age_group": row[4], "language": row[5],
                        "source": row[6], "created_at": row[7]}
        except Exception as e:
            logger.debug("Erreur get story: %s", e)
        return None

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        q = query.replace("'", "\\'")
        try:
            r = self._conn.execute(f"""
                MATCH (s:Story)
                WHERE CONTAINS(s.title, '{q}')
                   OR CONTAINS(s.theme, '{q}')
                   OR CONTAINS(s.characters, '{q}')
                   OR CONTAINS(s.content, '{q}')
                RETURN s.id, s.title, s.theme, s.characters,
                       s.age_group, s.language, s.created_at
                LIMIT {top_k}
            """)
            stories = []
            while r.has_next():
                row = r.get_next()
                stories.append({"id": row[0], "title": row[1], "theme": row[2],
                                "characters": row[3], "age_group": row[4],
                                "language": row[5], "created_at": row[6]})
            return stories
        except Exception as e:
            logger.debug("Erreur search stories: %s", e)
            return []

    def by_theme(self, theme: str) -> List[Dict]:
        return self.search(theme)

    def count(self) -> int:
        try:
            r = self._conn.execute("MATCH (s:Story) RETURN count(s)")
            if r.has_next():
                return r.get_next()[0]
        except Exception:
            pass
        return 0

    def add_character(self, story_id: str, char_name: str,
                      voice: str = "", description: str = ""):
        safe = lambda s: s.replace("'", "\\'") if s else ""
        ts = datetime.now().isoformat()
        try:
            self._conn.execute(f"""
                MERGE (c:StoryCharacter {{
                    name: '{safe(char_name)}',
                    voice: '{safe(voice)}',
                    description: '{safe(description)}',
                    created_at: '{ts}'
                }})
            """)
            self._conn.execute(f"""
                MATCH (s:Story {{id: '{story_id}'}})
                MATCH (c:StoryCharacter {{name: '{safe(char_name)}'}})
                MERGE (s)-[:HAS_CHARACTER]->(c)
            """)
        except Exception as e:
            logger.debug("Erreur add character: %s", e)

    def close(self):
        self._conn = None
        self._db = None
