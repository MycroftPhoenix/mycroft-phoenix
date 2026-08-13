"""
LadybugStorageAdapter + LadybugChatter — stockage et conversation LadybugDB.

Deux couches, toutes deux sur LadybugDB (real_ladybug, API compatible Kuzu,
accès sans pyarrow) :

1. ``LadybugStorageAdapter``
   Adapter de stockage ChatterBot (interface StorageAdapter) dans un graphe
   LadybugDB :
       (Statement {text PK, search_text, conversation, persona,
                   in_response_to, search_in_response_to,
                   created_at, confidence}) -[:HAS_TAG]-> (Tag {name PK})
   Avantages vs SQLStorageAdapter : zéro SQLAlchemy, pas de modèle spaCy
   (LowercaseTagger + text_search), base par langue ``data/chatterbot/``.

2. ``LadybugChatter``
   Fallback conversationnel léger (sans dépendre du runtime ChatterBot) :
   deux bases par langue — ``<lang>_corpus.lbdb`` (verrouillée, read-only,
   pré-entraînée) et ``<lang>_user.lbdb`` (lecture-écriture, apprentissage
   des interactions). Matching déterministe par chevauchement de tokens sur
   les relations du graphe (in_response_to / search_*).
"""

import logging
import os
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from chatterbot.storage import StorageAdapter
from chatterbot.conversation import Statement
from chatterbot.tagging import LowercaseTagger

logger = logging.getLogger(__name__)

try:
    import real_ladybug as _ladybug
except ImportError:  # pragma: no cover
    _ladybug = None


# ── Modèles factices (interface ChatterBot) ───────────────────────────────

class _GraphModel:
    """Modèle Statement pour l'interface StorageAdapter (graphe)."""
    extra_statement_field_names: list = []


class _TagModel:
    pass


# ── Adapter ───────────────────────────────────────────────────────────────

class LadybugStorageAdapter(StorageAdapter):
    """
    Stocke les Statement/Tag de ChatterBot dans une base LadybugDB.

    Kwargs acceptés:
        db_path (str|Path): Chemin du fichier .lbdb (prioritaire).
        database_uri (str): URI — 'ladybug:///chemin' ou chemin simple.
        read_only (bool): ouvrir la base en lecture seule (corpus partagé).
    """

    SCHEMA = [
        "CREATE NODE TABLE Statement ("
        "text STRING, search_text STRING, conversation STRING, "
        "persona STRING, in_response_to STRING, "
        "search_in_response_to STRING, created_at STRING, "
        "confidence DOUBLE, PRIMARY KEY (text))",
        "CREATE NODE TABLE Tag (name STRING, PRIMARY KEY (name))",
        "CREATE REL TABLE HAS_TAG (FROM Statement TO Tag)",
        "CREATE REL TABLE RESPONDS_TO (FROM Statement TO Statement)",
    ]

    # Champs texte ordonnables (anti-injection pour ORDER BY)
    _SORTABLE = {"text", "created_at", "conversation", "persona", "confidence"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if _ladybug is None:
            raise ImportError("real_ladybug n'est pas installé (pip install real_ladybug)")

        self.read_only = bool(kwargs.get("read_only", False))
        self.db_path = Path(self._resolve_path(kwargs))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.db = _ladybug.Database(str(self.db_path), read_only=self.read_only)
        self.conn = _ladybug.Connection(self.db)
        if not self.read_only:
            self._init_schema()

    # ── Utilitaires ───────────────────────────────────────────────────────

    @staticmethod
    def _resolve_path(kwargs) -> str:
        db_path = kwargs.get("db_path")
        if db_path:
            return str(db_path)
        uri = kwargs.get("database_uri", "phoenix_chatterbot.lbdb")
        uri = str(uri)
        for prefix in ("ladybug:///", "ladybug://", "ladybug:"):
            if uri.startswith(prefix):
                return uri[len(prefix):]
        return uri

    def _init_schema(self) -> None:
        for stmt in self.SCHEMA:
            try:
                self.conn.execute(stmt)
            except Exception:
                pass  # table déjà existante

    def _rows(self, query: str, params: dict = None):
        """Exécute et retourne les lignes (sans pyarrow)."""
        result = self.conn.execute(query, parameters=params or {})
        return result.get_all()

    # ── Interface StorageAdapter ──────────────────────────────────────────

    def get_statement_model(self):
        return _GraphModel

    def get_tag_model(self):
        return _TagModel

    def get_preferred_tagger(self):
        """Pas de modèle spaCy → démarrage rapide, faible empreinte RAM."""
        return LowercaseTagger

    def get_preferred_search_algorithm(self):
        """text_search: compatible tout stockage, sans index POS-lemma."""
        return "text_search"

    def count(self) -> int:
        rows = self._rows("MATCH (s:Statement) RETURN COUNT(*) AS c")
        return rows[0][0] if rows else 0

    def remove(self, statement_text: str) -> None:
        if self.read_only:
            return
        self.conn.execute(
            "MATCH (s:Statement {text: $t}) DETACH DELETE s",
            parameters={"t": statement_text},
        )
        # Nettoyer les références croisées
        self.conn.execute(
            "MATCH (s:Statement {in_response_to: $t}) "
            "SET s.in_response_to = '', s.search_in_response_to = ''",
            parameters={"t": statement_text},
        )

    def _statement_to_row(self, s) -> dict:
        created = s.created_at
        if isinstance(created, datetime):
            created = created.isoformat()
        return {
            "text": s.text,
            "search_text": s.search_text or "",
            "conversation": s.conversation or "",
            "persona": s.persona or "",
            "in_response_to": s.in_response_to or "",
            "search_in_response_to": s.search_in_response_to or "",
            "created_at": str(created),
            "confidence": float(getattr(s, "confidence", 0) or 0),
        }

    def _row_to_statement(self, row: dict) -> Statement:
        return Statement(
            text=row["text"],
            in_response_to=row.get("in_response_to"),
            search_text=row.get("search_text", ""),
            conversation=row.get("conversation", ""),
            persona=row.get("persona", ""),
            search_in_response_to=row.get("search_in_response_to", ""),
            created_at=row.get("created_at") or datetime.now().isoformat(),
            confidence=row.get("confidence", 0),
            tags=row.get("tags", []),
        )

    def create(self, **kwargs) -> Statement:
        statement = Statement(**kwargs)
        self.update(statement)
        return statement

    def create_many(self, statements) -> None:
        for statement in statements:
            self.update(statement)

    def update(self, statement) -> None:
        if self.read_only:
            return
        data = self._statement_to_row(statement)
        self.conn.execute(
            "MERGE (s:Statement {text: $text}) "
            "SET s.search_text = $search_text, s.conversation = $conversation, "
            "s.persona = $persona, s.in_response_to = $in_response_to, "
            "s.search_in_response_to = $search_in_response_to, "
            "s.created_at = $created_at, s.confidence = $confidence",
            parameters=data,
        )
        for tag in statement.tags:
            self.conn.execute(
                "MERGE (t:Tag {name: $name})", parameters={"name": tag}
            )
            self.conn.execute(
                "MATCH (s:Statement {text: $text}) "
                "MATCH (t:Tag {name: $name}) MERGE (s)-[:HAS_TAG]->(t)",
                parameters={"text": statement.text, "name": tag},
            )

    def filter(self, **kwargs):
        """
        Retourne les Statement correspondant aux critères.

        Critères objet: text, in_response_to, persona, conversation,
            search_text, search_in_response_to, confidence
        Critères spéciaux: tags, order_by, page_size, exclude_text,
            exclude_text_words, persona_not_startswith,
            search_text_contains, search_in_response_to_contains
        """
        where = []
        params = {}

        object_fields = {
            "text", "in_response_to", "persona", "conversation",
            "search_text", "search_in_response_to",
        }
        for field in object_fields:
            if field in kwargs and kwargs[field] is not None:
                where.append(f"s.{field} = ${field}")
                params[field] = kwargs[field]

        if "confidence" in kwargs and kwargs["confidence"] is not None:
            where.append("s.confidence >= $confidence")
            params["confidence"] = kwargs["confidence"]

        exclude_text = kwargs.get("exclude_text")
        if exclude_text:
            where.append("s.text <> $exclude_text")
            params["exclude_text"] = exclude_text

        exclude_words = kwargs.get("exclude_text_words") or []
        for i, word in enumerate(exclude_words):
            where.append(f"NOT CONTAINS(s.text, $ew{i})")
            params[f"ew{i}"] = word

        if kwargs.get("persona_not_startswith"):
            where.append("NOT STARTS_WITH(s.persona, $pns)")
            params["pns"] = kwargs["persona_not_startswith"]

        if kwargs.get("search_text_contains"):
            where.append("CONTAINS(s.search_text, $stc)")
            params["stc"] = kwargs["search_text_contains"]

        if kwargs.get("search_in_response_to_contains"):
            where.append("CONTAINS(s.search_in_response_to, $sirc)")
            params["sirc"] = kwargs["search_in_response_to_contains"]

        tags = kwargs.get("tags") or []
        match_clauses = ["MATCH (s:Statement)"]
        for i, tag in enumerate(tags):
            match_clauses.append(
                f"MATCH (s)-[:HAS_TAG]->(t{i}:Tag {{name: $tag{i}}})"
            )
            params[f"tag{i}"] = tag

        query = " ".join(match_clauses)
        if where:
            query += " WHERE " + " AND ".join(where)

        # Kuzu/Ladybug exige RETURN (pas de MATCH...WHERE...LIMIT sans RETURN)
        query += (" RETURN s.text, s.search_text, s.conversation, s.persona, "
                  "s.in_response_to, s.search_in_response_to, s.created_at, s.confidence")

        order_by = kwargs.get("order_by")
        if isinstance(order_by, str):
            order_by = [order_by]
        if order_by:
            # 'id' n'existe pas dans le graphe (text = PK) → on ordonne par created_at
            order_map = {"id": "created_at"}
            orders = [order_map.get(o, o) for o in order_by if o in self._SORTABLE or o == "id"]
            if orders:
                query += " ORDER BY " + ", ".join(f"s.{o}" for o in orders)

        page_size = kwargs.get("page_size", 1000)
        query += f" LIMIT {int(page_size)}"

        try:
            result = self.conn.execute(query, parameters=params)
        except Exception:
            return []

        return self._statements_from_result(result)

    def _statements_from_result(self, result) -> list:
        statements = []
        for row in result.rows_as_dict():
            row_data = {k.split(".")[-1]: v for k, v in row.items() if "." in k}
            # tags du statement
            stmt_text = row_data.get("text")
            row_data["tags"] = self._get_tags(stmt_text)
            statements.append(self._row_to_statement(row_data))
        return statements

    def link_response(self, answer_text: str, question_text: str) -> None:
        """Crée la relation graphe (réponse)-[:RESPONDS_TO]->(question)."""
        if self.read_only:
            return
        self.conn.execute(
            "MATCH (a:Statement {text: $a}) "
            "MATCH (q:Statement {text: $q}) "
            "CREATE (a)-[:RESPONDS_TO]->(q)",
            parameters={"a": answer_text, "q": question_text},
        )

    def responses_for(self, question_text: str) -> list:
        """Réponses (Statement) reliées à la question par RESPONDS_TO."""
        result = self.conn.execute(
            "MATCH (a:Statement)-[:RESPONDS_TO]->(q:Statement {text: $q}) "
            "RETURN a.text, a.search_text, a.conversation, a.persona, "
            "a.in_response_to, a.search_in_response_to, a.created_at, a.confidence",
            parameters={"q": question_text},
        )
        return self._statements_from_result(result)

    def _get_tags(self, text) -> list:
        rows = self._rows(
            "MATCH (s:Statement {text: $t})-[:HAS_TAG]->(tag:Tag) RETURN tag.name",
            params={"t": text},
        )
        return [r[0] for r in rows]

    def get_random(self) -> Statement:
        result = self.conn.execute("MATCH (s:Statement) RETURN s, s.text ORDER BY random() LIMIT 1")
        rows = list(result.rows_as_dict())
        if not rows:
            raise self.EmptyDatabaseException()
        row = rows[0]
        data = {k.split(".")[-1]: v for k, v in row.items() if "." in k}
        data["tags"] = self._get_tags(data["text"])
        return self._row_to_statement(data)

    def drop(self) -> None:
        if self.read_only:
            return
        try:
            self.conn.execute("MATCH (s:Statement) DETACH DELETE s")
            self.conn.execute("MATCH (t:Tag) DETACH DELETE t")
        except Exception as e:
            self.logger.warning("drop LadybugDB impossible: %s", e)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass


# ── Normalisation partagée ────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Minuscules, accents retirés, ponctuation → espace, apostrophes → espace."""
    import re as _re
    t = (text or "").lower().strip()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("œ", "oe").replace("æ", "ae")
    t = t.replace("'", " ").replace("\u2019", " ").replace("\u2018", " ")
    t = _re.sub(r"[^\w\s]", " ", t, flags=_re.UNICODE)
    return " ".join(t.split())


def tokenize(text: str) -> List[str]:
    """Tokens normalisés, en ignorant les mots vides très courts."""
    words = [w for w in normalize(text).split() if len(w) >= 3]
    return words


# ── Fallback conversationnel LadybugDB ────────────────────────────────────

class LadybugChatter:
    """
    Fallback conversationnel sur LadybugDB (sans dépendre du runtime
    ChatterBot). Deux bases par langue :
      - ``<lang>_corpus.lbdb`` : verrouillée, read-only, pré-entraînée
        (corpus ChatterBot + corpus Mycroft, paires Q→A).
      - ``<lang>_user.lbdb``  : lecture-écriture, apprentissage des
        interactions de l'utilisateur.

    get_response() cherche dans l'ordre :
      1. paire Q→A exacte (user, puis corpus) — relation in_response_to ;
      2. réponse floue par chevauchement de tokens sur les search_* ;
      3. écho du plus proche énoncé connu (faible confiance) ;
      4. None (le pipeline retombe sur son fallback générique / LLM).
    """

    def __init__(
        self,
        name: str = "Phoenix",
        lang: str = "fr",
        data_dir: Optional[Path] = None,
        corpus_db: Optional[Path] = None,
        user_db: Optional[Path] = None,
        threshold: float = 0.55,
    ):
        if _ladybug is None:
            raise ImportError("real_ladybug n'est pas installé (pip install real_ladybug)")

        data_dir = Path(data_dir or ".")
        self.name = name
        self.lang = lang
        self.threshold = threshold
        self.corpus_db = Path(corpus_db) if corpus_db else data_dir / "chatterbot" / f"{lang}_corpus.lbdb"
        self.user_db = Path(user_db) if user_db else data_dir / "chatterbot" / f"{lang}_user.lbdb"

        self.corpus = LadybugStorageAdapter(db_path=self.corpus_db, read_only=True)
        self.user = LadybugStorageAdapter(db_path=self.user_db, read_only=False)

    # ── Matching ──────────────────────────────────────────────────────────

    def _overlap(self, q_tokens: List[str], candidate_tokens: List[str]) -> float:
        """Fraction des tokens de la requête présents chez le candidat."""
        if not q_tokens or not candidate_tokens:
            return 0.0
        qset = set(q_tokens)
        cset = set(candidate_tokens)
        if not qset:
            return 0.0
        return len(qset & cset) / len(qset)

    def _best_fuzzy(self, storage: LadybugStorageAdapter, text: str) -> Optional[Statement]:
        """Meilleur candidat parmi les statements dont search_* chevauche le texte."""
        q_tokens = tokenize(text)
        if not q_tokens:
            return None
        best = None
        best_score = 0.0
        try:
            statements = storage.filter(order_by=["created_at"], page_size=10000)
        except Exception as e:
            logger.debug("filter LadybugChatter: %s", e)
            return None
        for st in statements:
            ctx = st.search_in_response_to or st.in_response_to or ""
            score = self._overlap(q_tokens, tokenize(ctx))
            if score > best_score:
                best_score = score
                best = st
        if best is None or best_score < self.threshold:
            return None
        best.confidence = best_score
        return best

    def _echo(self, storage: LadybugStorageAdapter, text: str) -> Optional[Statement]:
        """Écho du statement le plus proche par son search_text (faible confiance)."""
        q_tokens = tokenize(text)
        if not q_tokens:
            return None
        best = None
        best_score = 0.0
        try:
            statements = storage.filter(order_by=["created_at"], page_size=10000)
        except Exception as e:
            logger.debug("echo LadybugChatter: %s", e)
            return None
        for st in statements:
            score = self._overlap(q_tokens, tokenize(st.search_text or st.text))
            if score > best_score:
                best_score = score
                best = st
        if best is None or best_score < 0.5:
            return None
        best.confidence = min(best_score, self.threshold - 0.05)
        return best

    def _best_question(self, text: str) -> Optional[Statement]:
        """Meilleure question connue (tag 'question') par chevauchement."""
        q_tokens = tokenize(text)
        if not q_tokens:
            return None
        best = None
        best_score = 0.0
        try:
            statements = self.corpus.filter(tags=["question"], page_size=10000)
        except Exception as e:
            logger.debug("best_question LadybugChatter: %s", e)
            return None
        for st in statements:
            score = self._overlap(q_tokens, tokenize(st.search_text or st.text))
            if score > best_score:
                best_score = score
                best = st
        if best is None or best_score < self.threshold:
            return None
        best.confidence = best_score
        return best

    def get_response(self, text: str) -> Optional[Statement]:
        """Retourne la meilleure réponse connue, ou None."""
        if not text or not text.strip():
            return None
        q = normalize(text)
        if not q:
            return None

        # 1. Paire Q→A exacte (appris / corpus ChatterBot)
        for storage in (self.user, self.corpus):
            try:
                found = storage.filter(in_response_to=q, order_by=["confidence"])
            except Exception as e:
                logger.debug("get_response exact: %s", e)
                found = []
            if found:
                return found[0]

        # 2. Question floue → réponse via la relation RESPONDS_TO du graphe
        question = self._best_question(text)
        if question is not None:
            answers = self.corpus.responses_for(question.text)
            if answers:
                answers[0].confidence = question.confidence or self.threshold
                return answers[0]

        # 3. Réponse floue (chevauchement de tokens sur le contexte Q)
        for storage in (self.user, self.corpus):
            best = self._best_fuzzy(storage, text)
            if best is not None:
                return best

        # 4. Écho du plus proche énoncé connu
        return self._echo(self.corpus, text)

    # ── Apprentissage ─────────────────────────────────────────────────────

    def learn(self, input_text: str, response_text: str) -> None:
        """Mémorise la paire (input → response) dans la base utilisateur."""
        if not input_text or not response_text:
            return
        q = normalize(input_text)
        if not q:
            return
        try:
            self.user.create(
                text=response_text,
                in_response_to=q,
                search_in_response_to=q,
                search_text=normalize(response_text),
                conversation="main",
                persona=self.name,
            )
        except Exception as e:
            logger.debug("learn LadybugChatter: %s", e)

    def status(self) -> Dict:
        try:
            corpus_count = self.corpus.count()
        except Exception:
            corpus_count = -1
        try:
            user_count = self.user.count()
        except Exception:
            user_count = -1
        return {
            "lang": self.lang,
            "corpus_db": str(self.corpus_db),
            "user_db": str(self.user_db),
            "corpus_statements": corpus_count,
            "user_statements": user_count,
            "threshold": self.threshold,
        }

    def close(self) -> None:
        try:
            self.corpus.close()
        except Exception:
            pass
        try:
            self.user.close()
        except Exception:
            pass


def ladybug_chatter_from_config(config: dict, base_dir: str) -> Optional[LadybugChatter]:
    """Fabrique un LadybugChatter depuis phoenix_config.json (section chatterbot)."""
    try:
        cb = config.get("chatterbot") or {}
        if not cb.get("enabled", False):
            return None
        lang = (config.get("languages") or ["fr"])[0]
        data_dir = Path(base_dir) / "data"
        return LadybugChatter(
            name=config.get("phoenix", {}).get("name", "Phoenix"),
            lang=lang,
            data_dir=data_dir,
            threshold=float(cb.get("threshold", 0.55)),
        )
    except Exception as e:
        logger.warning("LadybugChatter indisponible: %s", e)
        return None
