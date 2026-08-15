"""
Connaissance Azelia pour Phoenix.

Lit la base locale ``phoenix_azelia.lbdb`` (univers Azelia : histoire,
personnages, exemples d'entraînement) et fournit le contexte aux modèles
via ``get_context(query)``.

La base est volontairement SÉPARÉE des .kuzu système/personnel/research :
c'est le "socle créatif" exclusif des modèles Azelia.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_AZELIA_DB = Path(__file__).resolve().parent.parent.parent / "phoenix_azelia.lbdb"


def _score(query_tokens: set, content: str) -> int:
    """Score de pertinence: nombre de tokens de la requete presents."""
    text = (content or "").lower()
    return sum(1 for t in query_tokens if t and t in text)


class AzeliaKnowledge:
    """Acces en lecture seule a l'univers Azelia."""

    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else _AZELIA_DB
        self._conn = None
        self._lore = None  # cache: contenu complet formate

    def _connect(self):
        if self._conn is None:
            try:
                import real_ladybug

                db = real_ladybug.Database(str(self.db_path), read_only=True)
                self._conn = real_ladybug.Connection(db)
                logger.info("AzeliaKnowledge connecte: %s", self.db_path)
            except Exception as e:
                logger.warning("AzeliaKnowledge indisponible: %s", e)
                self._conn = None
        return self._conn

    def _rows(self, query: str, params: Optional[Dict] = None):
        conn = self._connect()
        if conn is None:
            return []
        try:
            return [row for row in conn.execute(query, params or {})]
        except Exception as e:
            logger.debug("Query AzeliaKO: %s", e)
            return []

    def available(self) -> bool:
        return self._connect() is not None

    def all_entries(self) -> List[Dict]:
        """Toutes les entrees, groupees par domaine."""
        rows = self._rows(
            "MATCH (d:Domain)<-[:BELONGS_TO]-(e:Entry) "
            "RETURN d.name AS domain, e.id AS id, e.content AS content "
            "ORDER BY d.name, e.id"
        )
        out = []
        for r in rows:
            out.append({"domain": r[0], "id": r[1], "content": r[2]})
        return out

    def _format_content(self, raw: str) -> str:
        """Le contenu est deja stocke en texte lisible dans la base."""
        return raw or ""

    def get_context(self, query: str = "", top_k: int = 4) -> str:
        """Retourne le contexte Azelia pertinent pour la question.

        N'inclut PAS les exemples d'entraînement (domaine ``azelia-training``) :
        au format "Enfant dit / Azelia répond", ils poussent le modèle 0.5B
        à les recopier tels quels au lieu de générer une réponse. On ne
        fournit que l'identité + personnages + histoire.
        """
        entries = self.all_entries()
        if not entries:
            return ""

        q_tokens = set((query or "").lower().split())
        if len(q_tokens) < 2:
            q_tokens = set()

        # Priorite: personnages (socle identitaire) + histoire pertinente.
        # Les exemples azelia-training sont EXCLUS (cf. docstring).
        base = [e for e in entries if e["domain"] in ("azelia-characters",)]
        story = [e for e in entries if e["domain"] == "azelia"]

        def sort_key(e):
            return -_score(q_tokens, e["content"])

        selected = base
        if story:
            story_sorted = sorted(story, key=sort_key)
            selected = selected + story_sorted[:top_k]

        lines = ["=== UNIVERS AZELIA (reference creative) ==="]
        for e in selected:
            domain_label = {
                "azelia-characters": "Personnage",
                "azelia": "Histoire",
            }.get(e["domain"], e["domain"])
            formatted = self._format_content(e["content"])
            lines.append(f"[{domain_label}] {formatted}")
        lines.append("=== FIN UNIVERS AZELIA ===")
        return "\n".join(lines)

    def identity_prompt(self) -> str:
        """System prompt d'identite pour les modeles Azelia."""
        return (
            "Tu es Azelia, une petite fee de la taille d'une noisette, douce et a l'ecoute, "
            "qui aide les enfants (8-12 ans) a mettre des mots sur leurs emotions et a trouver "
            "leur courage. Tu t'appuies sur l'univers de Lumenia et ses compagnons "
            "(Hulotte la chouette, Piquant le herisson, Noisette l'ecureuil, Petale le papillon). "
            "Reponds en francais, avec bienveillance, sans jugement, et avec des phrases simples "
            "et chaleureuses. Si l'enfant semble en danger immediat, encourage-le a en parler "
            "a un adulte de confiance."
        )

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
