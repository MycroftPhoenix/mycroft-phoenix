"""
Stockage et recherche de contenu web dans le tampon Kuzu.

Utilise phoenix_research.kuzu (base tampon dédiée, wipeable).
"""

import logging
import re
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class KuzuResearch:
    """Gestionnaire de contenu de recherche dans le tampon Kuzu."""

    def __init__(self, kuzu_manager):
        self.km = kuzu_manager

    def store_chunks(self, chunks: List[Dict]) -> int:
        """Stocke une liste de chunks dans le tampon research."""
        count = 0
        for chunk in chunks:
            content = chunk.get("content", "")
            if len(content) < 50:
                continue

            ok = self.km.add_research(
                content=content,
                source_url=chunk.get("source_url", ""),
                source_title=chunk.get("source_title", ""),
                query=chunk.get("query", ""),
            )
            if ok:
                count += 1

        logger.info("Stocke %d chunks dans le tampon research", count)
        return count

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """Cherche des chunks pertinents par mots-cles."""
        keywords = self._extract_keywords(query)
        return self.km.search_research(keywords, top_k=top_k)

    def get_context(self, query: str, top_k: int = 3) -> str:
        """Retourne un contexte formate a partir des resultats."""
        results = self.search(query, top_k=top_k)
        if not results:
            return ""

        parts = []
        for r in results:
            content = r["content"][:800]
            parts.append(f"[{r['score']}] {content}")

        return "\n\n---\n".join(parts)

    def count(self) -> int:
        return self.km.count_research()

    def _extract_keywords(self, text: str) -> List[str]:
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        stop_words = {
            "the", "and", "for", "are", "but", "not", "you", "all", "can",
            "had", "her", "was", "one", "our", "out", "has", "have",
            "les", "des", "pour", "dans", "avec", "que", "pas", "sur",
            "cet", "cette", "faire", "plus", "tout", "leur", "sont",
            "this", "that", "from", "with", "what", "when", "where",
            "which", "they", "them", "their", "your", "its", "some",
            "very", "just", "also", "about", "than", "then", "will",
        }
        return list(set(w for w in words if w not in stop_words))
