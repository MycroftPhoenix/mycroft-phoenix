"""
Gestionnaire Dual Kuzu pour Phoenix.

Sépare les données système (crises, intents, config) des données personnelles
(conversations, learning, skills) et des données de recherche web (tampon).

Architecture:
  phoenix.kuzu           → SYSTEM: intents, utterances, crises (READ-ONLY)
  phoenix_personal.kuzu  → PERSONAL: conversations, learning, skills (wipeable)
  phoenix_research.kuzu  → RESEARCH: contenu web scrappé (tampon, wipeable)

Les bases sont stockées dans le répertoire utilisateur (~/.local/share/phoenix/,
%APPDATA%/Phoenix/, etc.) pour être persistantes entre les mises à jour.
"""

import kuzu
import logging
import os
import sys
import shutil
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class _WritesDisabled:
    """Marqueur : quand la WriteQueue n'est pas disponible, les écritures sont silencieusement ignorées."""


_NOWRITE = _WritesDisabled()


def _get_base_dir() -> Path:
    """Detecte le répertoire des bases Kuzu.

    Ordre:
    1. Variable d'environnement PHOENIX_DATA_DIR
    2. Répertoire du projet (dev, si .kuzu present)
    3. Répertoire de l'exécutable (standalone PyInstaller)
    4. Répertoire de données utilisateur (%APPDATA%/phoenix ou ~/.local/share/phoenix)
    """
    env = os.environ.get("PHOENIX_DATA_DIR")
    if env:
        return Path(env)

    # Mode PyInstaller/Nuitka standalone
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent

    # Dev : répertoire du projet (cherche phoenix.kuzu)
    p = Path(__file__).parent.parent.parent
    if (p / "phoenix.kuzu").exists():
        return p

    return Path(get_data_dir())

# Schema du systeme (ne JAMAIS modifier sans backup)
SYSTEM_SCHEMA = """
NODE TABLES:
  Intent (name STRING PRIMARY KEY)
  Utterance (text STRING PRIMARY KEY)
  ChangeLog (id STRING PRIMARY KEY, timestamp STRING, description STRING, category STRING)
  SecurityMeasure (name STRING PRIMARY KEY, type STRING, description STRING, enabled BOOLEAN)
  HardwareProfile (id STRING PRIMARY KEY, profile STRING, details STRING)
  ArchitectureDecision (id STRING PRIMARY KEY, title STRING, rationale STRING, date STRING)

REL TABLES:
  HAS (FROM Intent TO Utterance)
"""

# Schema personnel (wipeable)
PERSONAL_SCHEMA = """
NODE TABLES:
  Conversation (id STRING PRIMARY KEY, timestamp STRING, user_input STRING,
                response STRING, intent STRING, confidence DOUBLE, source STRING, lang STRING)
  Learning (id STRING PRIMARY KEY, content STRING, category STRING,
            tags STRING, created_at STRING)
  Skill (name STRING PRIMARY KEY, description STRING, category STRING,
         utterances STRING, enabled BOOLEAN DEFAULT true)
  UserProfile (id STRING PRIMARY KEY, name STRING, preferences STRING,
               created_at STRING, last_seen STRING)

REL TABLES:
  HAS_SKILL (FROM UserProfile TO Skill)
  LEARNED_FROM (FROM Learning TO Conversation)
"""

# Schema tampon recherche web (wipeable)
RESEARCH_SCHEMA = """
NODE TABLES:
  Research (id STRING PRIMARY KEY, content STRING, source_url STRING,
            source_title STRING, query STRING, created_at STRING)
"""


class KuzuManager:
    """
    Gestionnaire centralisé des trois bases Kuzu.

    - system_conn:   lecture seule sur phoenix.kuzu (intents, crises)
    - personal_conn: lecture/écriture sur phoenix_personal.kuzu (conversations)
    - research_conn: lecture/écriture sur phoenix_research.kuzu (tampon web)
    """

    def __init__(self, base_dir: str = None, write_queue=None, worker=None):
        self.base_dir = Path(base_dir) if base_dir else _get_base_dir()
        self.worker = worker  # KuzuWorker optionnel : ses connexions servent de référence
        self.system_db: Optional[kuzu.Database] = None
        self.system_conn: Optional[kuzu.Connection] = None
        self.personal_db: Optional[kuzu.Database] = None
        self.personal_conn: Optional[kuzu.Connection] = None
        self.research_db: Optional[kuzu.Database] = None
        self.research_conn: Optional[kuzu.Connection] = None
        self.write_queue = write_queue

    def _conn_from_worker(self, name: str) -> Optional[kuzu.Connection]:
        """Retourne la connexion courante du worker pour une base (lecture/écriture
        via l'unique writer). Kuzu n'autorise qu'un seul Database par fichier."""
        if not self.worker:
            return None
        handle = self.worker._dbs.get(name)
        if handle is not None and handle.is_open:
            return handle._conn
        return None

    def initialize(self) -> bool:
        """Initialise les trois bases Kuzu. Lance une exception si une base critique échoue."""
        ok = self._init_system()
        if not ok:
            raise RuntimeError(f"Base systeme introuvable dans {self.base_dir}")
        ok = self._init_personal()
        if not ok:
            raise RuntimeError("Base personnelle non initialisable")
        ok = self._init_research()
        if not ok:
            raise RuntimeError("Base recherche non initialisable")
        return True

    def _init_system(self) -> bool:
        """Ouvre la base systeme (phoenix.kuzu)."""
        try:
            # Si un worker est actif, réutiliser sa connexion (lock exclusif Kuzu)
            wconn = self._conn_from_worker("system")
            if wconn is not None:
                self.system_conn = wconn
                result = self.system_conn.execute("MATCH (i:Intent) RETURN count(i) AS cnt;")
                if result.has_next():
                    count = result.get_next()[0]
                    logger.info("Base systeme (worker): %d intents charges", count)
                    return count > 0
                return False

            db_path = str(self.base_dir / "phoenix.kuzu")
            if not os.path.exists(db_path):
                logger.warning("Base systeme non trouvee: %s", db_path)
                return False

            self.system_db = kuzu.Database(db_path)
            self.system_conn = kuzu.Connection(self.system_db)

            # Verifier qu'elle contient des intents
            result = self.system_conn.execute("MATCH (i:Intent) RETURN count(i) AS cnt;")
            if result.has_next():
                count = result.get_next()[0]
                logger.info("Base systeme: %d intents charges", count)
                return count > 0

            logger.warning("Base systeme vide")
            return False
        except Exception as e:
            logger.error("Erreur base systeme: %s", e)
            return False

    def _init_personal(self) -> bool:
        """Ouvre ou cree la base personnelle (phoenix_personal.kuzu)."""
        try:
            wconn = self._conn_from_worker("personal")
            if wconn is not None:
                self.personal_conn = wconn
                result = self.personal_conn.execute("CALL show_tables() RETURN *")
                tables = []
                while result.has_next():
                    tables.append(result.get_next()[1])
                self._ensure_schema(tables)
                logger.info("Base personnelle (worker) initialisee")
                return True

            db_path = str(self.base_dir / "phoenix_personal.kuzu")
            self.personal_db = kuzu.Database(db_path)
            self.personal_conn = kuzu.Connection(self.personal_db)

            # Verifier si le schema existe, sinon le creer
            result = self.personal_conn.execute("CALL show_tables() RETURN *")
            tables = []
            while result.has_next():
                tables.append(result.get_next()[1])

            self._ensure_schema(tables)

            logger.info("Base personnelle initialisee")
            return True
        except Exception as e:
            logger.error("Erreur base personnelle: %s", e)
            return False

    def _ensure_schema(self, existing_tables: List[str]):
        """Cree les tables manquantes dans la base personnelle.
        Les node tables sont creees avant les rel tables.
        """
        node_tables = {
            "Conversation": "CREATE NODE TABLE IF NOT EXISTS Conversation (id STRING PRIMARY KEY, timestamp STRING, user_input STRING, response STRING, intent STRING, confidence DOUBLE, source STRING, lang STRING)",
            "Learning": "CREATE NODE TABLE IF NOT EXISTS Learning (id STRING PRIMARY KEY, content STRING, category STRING, tags STRING, created_at STRING)",
            "Skill": "CREATE NODE TABLE IF NOT EXISTS Skill (name STRING PRIMARY KEY, description STRING, category STRING, utterances STRING, enabled BOOLEAN DEFAULT true)",
            "UserProfile": "CREATE NODE TABLE IF NOT EXISTS UserProfile (id STRING PRIMARY KEY, name STRING, preferences STRING, created_at STRING, last_seen STRING)",
        }
        rel_tables = {
            "HAS_SKILL": "CREATE REL TABLE IF NOT EXISTS HAS_SKILL (FROM UserProfile TO Skill)",
            "LEARNED_FROM": "CREATE REL TABLE IF NOT EXISTS LEARNED_FROM (FROM Learning TO Conversation)",
        }
        for name, stmt in node_tables.items():
            if name not in existing_tables:
                try:
                    self.personal_conn.execute(stmt)
                    logger.info("Table %s creee", name)
                except Exception as e:
                    logger.debug("Erreur creation table %s: %s", name, e)
        for name, stmt in rel_tables.items():
            if name not in existing_tables:
                try:
                    self.personal_conn.execute(stmt)
                    logger.info("Table %s creee", name)
                except Exception as e:
                    logger.debug("Erreur creation table %s: %s", name, e)

    def _create_personal_schema(self):
        """Cree le schema complet de la base personnelle (premiere initialisation)."""
        tables = [
            "CREATE NODE TABLE IF NOT EXISTS Conversation (id STRING PRIMARY KEY, timestamp STRING, user_input STRING, response STRING, intent STRING, confidence DOUBLE, source STRING, lang STRING)",
            "CREATE NODE TABLE IF NOT EXISTS Learning (id STRING PRIMARY KEY, content STRING, category STRING, tags STRING, created_at STRING)",
            "CREATE NODE TABLE IF NOT EXISTS Skill (name STRING PRIMARY KEY, description STRING, category STRING, utterances STRING, enabled BOOLEAN DEFAULT true)",
            "CREATE NODE TABLE IF NOT EXISTS UserProfile (id STRING PRIMARY KEY, name STRING, preferences STRING, created_at STRING, last_seen STRING)",
            "CREATE REL TABLE IF NOT EXISTS HAS_SKILL (FROM UserProfile TO Skill)",
            "CREATE REL TABLE IF NOT EXISTS LEARNED_FROM (FROM Learning TO Conversation)",
        ]
        for stmt in tables:
            try:
                self.personal_conn.execute(stmt)
            except Exception as e:
                logger.debug("Table deja existante ou erreur: %s", e)
        logger.info("Schema personnel cree")

    def wipe_personal(self) -> bool:
        """
        EFFACE TOUTES les données personnelles. Recovery complet.

        La base systeme (phoenix.kuzu) n'est JAMAIS touchee.
        Les conversations, learning et skills personnels sont supprimés.
        """
        db_path = self.base_dir / "phoenix_personal.kuzu"
        if not db_path.exists():
            logger.info("Base personnelle deja absente")
            return True

        try:
            # Fermer la connection d'abord
            self.personal_conn = None
            self.personal_db = None

            # Kuzu stocke en fichier unique
            os.remove(db_path)
            # Supprimer aussi le WAL et lock si present
            for ext in ["", "-lock", "-wal"]:
                p = self.base_dir / f"phoenix_personal.kuzu{ext}"
                if p.exists():
                    os.remove(p)

            logger.warning("Base personnelle SUPPRIMEE: %s", db_path)

            # Recréer vide
            return self._init_personal()
        except Exception as e:
            logger.error("Erreur wipe personnel: %s", e)
            return False

    def backup_personal(self, backup_name: str = None) -> Optional[Path]:
        """Sauvegarde la base personnelle avant wipe."""
        import datetime
        src = self.base_dir / "phoenix_personal.kuzu"
        if not src.exists():
            return None

        if backup_name is None:
            backup_name = f"phoenix_personal_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

        backup_dir = self.base_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        dst = backup_dir / backup_name

        try:
            import shutil
            shutil.copy2(src, dst)
            logger.info("Backup personnel: %s", dst)
            return dst
        except Exception as e:
            logger.error("Erreur backup: %s", e)
            return None

    # ── Recherche web (tampon) ──

    def _init_research(self) -> bool:
        """Ouvre ou cree la base recherche (phoenix_research.kuzu)."""
        try:
            wconn = self._conn_from_worker("research")
            if wconn is not None:
                self.research_conn = wconn
                result = self.research_conn.execute("CALL show_tables() RETURN *")
                tables = []
                while result.has_next():
                    tables.append(result.get_next()[1])
                if "Research" not in tables:
                    self._create_research_schema()
                logger.info("Base recherche (worker) initialisee")
                return True

            db_path = str(self.base_dir / "phoenix_research.kuzu")
            self.research_db = kuzu.Database(db_path)
            self.research_conn = kuzu.Connection(self.research_db)

            result = self.research_conn.execute("CALL show_tables() RETURN *")
            tables = []
            while result.has_next():
                tables.append(result.get_next()[1])

            if "Research" not in tables:
                self._create_research_schema()

            logger.info("Base recherche initialisee")
            return True
        except Exception as e:
            logger.error("Erreur base recherche: %s", e)
            return False

    def _create_research_schema(self):
        """Cree le schema de la base recherche."""
        try:
            self.research_conn.execute("""
                CREATE NODE TABLE IF NOT EXISTS Research (
                    id STRING PRIMARY KEY,
                    content STRING,
                    source_url STRING,
                    source_title STRING,
                    query STRING,
                    created_at STRING
                )
            """)
            logger.info("Schema recherche cree")
        except Exception as e:
            logger.debug("Erreur creation schema research: %s", e)

    def _enqueue_or_execute(self, cypher: str, db_name: str = "personal", source: str = "phoenix"):
        """Passe par la WriteQueue si disponible, sinon exécute directement."""
        if self.write_queue:
            self.write_queue.enqueue(source=source, cypher=cypher, db_name=db_name)
            return True
        return False

    def add_research(self, content: str, source_url: str = "",
                     source_title: str = "", query: str = "") -> bool:
        """Ajoute un chunk de recherche dans le tampon."""
        import uuid
        from datetime import datetime

        rid = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()
        safe_content = content.replace("'", "\\'")[:5000]
        safe_url = source_url.replace("'", "\\'")
        safe_title = source_title.replace("'", "\\'")
        safe_query = query.replace("'", "\\'")

        cypher = f"""
            CREATE (r:Research {{
                id: '{rid}',
                content: '{safe_content}',
                source_url: '{safe_url}',
                source_title: '{safe_title}',
                query: '{safe_query}',
                created_at: '{timestamp}'
            }})
        """
        if self._enqueue_or_execute(cypher, db_name="research", source="research"):
            return True

        if not self.research_conn:
            return False
        try:
            self.research_conn.execute(cypher)
            return True
        except Exception as e:
            logger.debug("Erreur add research: %s", e)
            return False

    def search_research(self, keywords: List[str], top_k: int = 5) -> List[Dict]:
        """Cherche dans les chunks de recherche par mots-cles."""
        if not self.research_conn or not keywords:
            return []

        try:
            conditions = " OR ".join(
                f"CONTAINS(l.content, '{kw}')" for kw in keywords
            )
            cypher = f"""
                MATCH (l:Research)
                WHERE {conditions}
                RETURN l.content, l.source_url, l.source_title, l.query, l.created_at
                LIMIT 50
            """
            result = self.research_conn.execute(cypher)

            matches = []
            while result.has_next():
                row = result.get_next()
                content = row[0]

                score = sum(1 for kw in keywords if kw in content.lower())
                if score > 0:
                    matches.append({
                        "content": content,
                        "score": score,
                        "source_url": row[1] or "",
                        "source_title": row[2] or "",
                        "query": row[3] or "",
                        "created_at": row[4] or "",
                    })

            matches.sort(key=lambda x: x["score"], reverse=True)
            return matches[:top_k]

        except Exception as e:
            logger.debug("Erreur search research: %s", e)
            return []

    def wipe_research(self) -> bool:
        """EFFACE le tampon de recherche. Recreable via web research."""
        db_path = self.base_dir / "phoenix_research.kuzu"
        if not db_path.exists():
            return True

        try:
            self.research_conn = None
            self.research_db = None

            os.remove(db_path)
            for ext in ["", "-lock", "-wal"]:
                p = self.base_dir / f"phoenix_research.kuzu{ext}"
                if p.exists():
                    os.remove(p)

            logger.warning("Base recherche SUPPRIMEE: %s", db_path)
            return self._init_research()
        except Exception as e:
            logger.error("Erreur wipe research: %s", e)
            return False

    def count_research(self) -> int:
        """Nombre de chunks de recherche stockes."""
        if not self.research_conn:
            return 0
        try:
            result = self.research_conn.execute("MATCH (r:Research) RETURN count(r)")
            if result.has_next():
                return result.get_next()[0]
        except Exception:
            pass
        return 0

    # ── Conversations ──

    def log_conversation(self, user_input: str, response: str, intent: str,
                         confidence: float, source: str, lang: str = "fr"):
        """Enregistre une conversation dans la base personnelle."""
        import uuid
        from datetime import datetime

        conv_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()
        safe_input = user_input.replace("'", "\\'")
        safe_response = response.replace("'", "\\'")

        cypher = f"""
            CREATE (c:Conversation {{
                id: '{conv_id}',
                timestamp: '{timestamp}',
                user_input: '{safe_input}',
                response: '{safe_response}',
                intent: '{intent}',
                confidence: {confidence},
                source: '{source}',
                lang: '{lang}'
            }})
        """
        if self._enqueue_or_execute(cypher, db_name="personal", source=source):
            return

        if not self.personal_conn:
            return
        try:
            self.personal_conn.execute(cypher)
        except Exception as e:
            logger.debug("Erreur log conversation: %s", e)

    def get_recent_conversations(self, limit: int = 10) -> List[Dict]:
        """Retourne les conversations récentes pour le contexte."""
        if not self.personal_conn:
            return []

        try:
            result = self.personal_conn.execute(f"""
                MATCH (c:Conversation)
                RETURN c.user_input, c.response, c.intent, c.timestamp
                ORDER BY c.timestamp DESC
                LIMIT {limit}
            """)

            conversations = []
            while result.has_next():
                row = result.get_next()
                conversations.append({
                    "user_input": row[0],
                    "response": row[1],
                    "intent": row[2],
                    "timestamp": row[3],
                })
            return conversations
        except Exception as e:
            logger.debug("Erreur get conversations: %s", e)
            return []

    def get_conversation_count(self) -> int:
        """Nombre total de conversations enregistrées."""
        if not self.personal_conn:
            return 0
        try:
            result = self.personal_conn.execute("MATCH (c:Conversation) RETURN count(c)")
            if result.has_next():
                return result.get_next()[0]
        except Exception:
            pass
        return 0

    # ── Learning ──

    def add_learning(self, content: str, category: str = "general", tags: str = ""):
        """Ajoute un fait appris."""
        import uuid
        from datetime import datetime

        lid = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()
        safe_content = content.replace("'", "\\'")

        cypher = f"""
            CREATE (l:Learning {{
                id: '{lid}',
                content: '{safe_content}',
                category: '{category}',
                tags: '{tags}',
                created_at: '{timestamp}'
            }})
        """
        if self._enqueue_or_execute(cypher, db_name="personal", source="learning"):
            return

        if not self.personal_conn:
            return
        try:
            self.personal_conn.execute(cypher)
        except Exception as e:
            logger.debug("Erreur add learning: %s", e)

    # ── Skills ──

    def add_skill(self, name: str, description: str, category: str = "custom",
                  utterances: str = ""):
        """Ajoute un skill personnalisé."""
        safe_desc = description.replace("'", "\\'")
        safe_utts = utterances.replace("'", "\\'")

        cypher = f"""
            MERGE (s:Skill {{
                name: '{name}',
                description: '{safe_desc}',
                category: '{category}',
                utterances: '{safe_utts}',
                enabled: true
            }})
        """
        if self._enqueue_or_execute(cypher, db_name="personal", source="skill"):
            return

        if not self.personal_conn:
            return
        try:
            self.personal_conn.execute(cypher)
        except Exception as e:
            logger.debug("Erreur add skill: %s", e)

    def get_skills(self) -> List[Dict]:
        """Liste tous les skills actifs."""
        if not self.personal_conn:
            return []

        try:
            result = self.personal_conn.execute(
                "MATCH (s:Skill) WHERE s.enabled = true RETURN s.name, s.description, s.category"
            )
            skills = []
            while result.has_next():
                row = result.get_next()
                skills.append({"name": row[0], "description": row[1], "category": row[2]})
            return skills
        except Exception:
            return []

    # ── Cycle de vie ──

    def close(self):
        """Ferme toutes les connexions Kuzu."""
        import gc
        for attr in ("system_conn", "personal_conn", "research_conn",
                     "system_db", "personal_db", "research_db"):
            obj = getattr(self, attr, None)
            if obj is not None:
                del obj
                setattr(self, attr, None)
        gc.collect()
        logger.info("[KuzuManager] Connexions fermées")

    # ── Status ──

    def status(self) -> Dict:
        """Statut des trois bases."""
        return {
            "system_connected": self.system_conn is not None,
            "personal_connected": self.personal_conn is not None,
            "research_connected": self.research_conn is not None,
            "conversation_count": self.get_conversation_count(),
            "skill_count": len(self.get_skills()),
            "research_count": self.count_research(),

        }
