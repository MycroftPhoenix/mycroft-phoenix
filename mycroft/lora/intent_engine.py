"""
IntentEngine — Moteur d'intent pur Python (TF-IDF + cosinus similarity).

Remplace ChatterBot comme moteur conversationnel intégré à Mycroft Phoenix.
Zéro dépendance externe (stdlib + kuzu).
Stockage persistant dans Kuzu, index TF-IDF en mémoire pour matching rapide.
"""

import json
import logging
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Mots vides (stopwords) — retirés du vocabulaire TF-IDF pour éviter que des
# questions factuelles (« quelle est la capitale de la France ») ne collent à
# un intent par chevauchement de mots-outils. Francais + anglais + bases
# espagnol/italien/allemand/portugais.
STOPWORDS = frozenset({
    # Français
    "a", "ai", "au", "aux", "avec", "avait", "avez", "avons", "c", "ca", "ce",
    "cela", "ces", "cet", "cette", "combien", "comme", "comment", "d", "dans",
    "de", "des", "du", "en", "es", "est", "et", "ete", "etes", "etre", "etais",
    "fait", "fais", "je", "la", "le", "les", "lui", "ma", "mais", "me", "mes",
    "moi", "mon", "ne", "ni", "nos", "notre", "nous", "on", "ont", "ou", "où",
    "par", "pas", "plus", "pour", "pourquoi", "qu", "quand", "que", "quel",
    "quelle", "quelles", "quels", "qui", "quoi", "sa", "sans", "se", "ses",
    "si", "son", "suis", "sur", "ta", "te", "tes", "toi", "ton", "tout",
    "tous", "toute", "toutes", "tu", "un", "une", "va", "vers", "vos",
    "votre", "vous", "y", "estce", "j", "m", "n", "s", "t", "l",
    "plus", "monde",
    # Anglais
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "he", "her", "his", "how", "i", "if", "in", "into", "is", "it", "its",
    "may", "me", "might", "my", "no", "not", "of", "on", "or", "our", "shall",
    "she", "should", "so", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "those", "to", "too", "very", "was",
    "we", "were", "what", "when", "where", "which", "who", "whom", "why",
    "will", "with", "would", "you", "your", "it's", "you're", "that's",
    "what's", "dont", "can't", "won't", "isnt", "im", "youre", "theres",
    # Espagnol
    "el", "los", "las", "unos", "unas", "yo", "tu", "él", "nosotros", "vosotros",
    "ellos", "ellas", "usted", "ustedes", "mi", "mis", "su", "sus", "nuestro",
    "nuestra", "es", "son", "está", "esta", "para", "con", "sin", "por", "que",
    "cuando", "como", "más", "también",
    # Italien
    "il", "lo", "gli", "i", "uno", "una", "del", "della", "degli", "delle",
    "e", "ed", "in", "con", "per", "che", "quando", "come", "più", "anche",
    "sono", "sei", "siamo", "siete",
    # Allemand
    "der", "die", "das", "ein", "eine", "einen", "einem", "einer", "und",
    "oder", "aber", "nicht", "ist", "sind", "ich", "du", "er", "sie", "wir",
    "ihr", "mit", "für", "von", "zu", "auf", "wie", "was", "wann", "wo",
    "mein", "meine", "dein", "deine",
    # Portugais
    "o", "os", "um", "uma", "uns", "umas", "e", "em", "de", "do", "da", "dos",
    "das", "para", "com", "sem", "por", "que", "quando", "como", "mais",
    "também", "sou", "é", "são", "está",
})


class IntentEngine:
    """
    Moteur d'intent matching basé sur TF-IDF + cosinus similarity.

    Flow:
      1. Crisis check (delegue a l'appelant)
      2. Keywords (intents fixes, confiance haute)
      3. TF-IDF matcher (fuzzy, style ChatterBot)
      4. Training reactif (apprend des corrections)
    """

    def __init__(self, storage=None, db_path: str = "./data/intents.db"):
        """
        Args:
            storage: Backend Kuzu (optionnel, utilise SQLite fallback sinon)
            db_path: Chemin base SQLite fallback
        """
        self._storage = storage
        self._db_path = db_path
        self._intents: Dict[str, List[str]] = {}
        self._idf: Dict[str, float] = {}
        self._vocab: set = set()
        self._total_docs: int = 0

    # ── Tokenisation / Normalisation ─────────────────────────────────────

    def _normalize(self, text: str) -> str:
        """Normalisation: minuscule, NFKD, supprime accents, apostrophes → espace."""
        t = text.lower().strip()
        t = unicodedata.normalize('NFKD', t)
        t = ''.join(c for c in t if not unicodedata.combining(c))
        t = t.replace('œ', 'oe').replace('æ', 'ae')
        t = t.replace("'", " ").replace("\u2019", " ").replace("\u2018", " ")
        t = re.sub(r'[^a-z0-9\s]', ' ', t)
        return " ".join(t.split())

    def _tokenize(self, text: str) -> List[str]:
        return [t for t in self._normalize(text).split()
                if t not in STOPWORDS and len(t) > 1]

    def _token_freqs(self, tokens: List[str]) -> Counter:
        return Counter(tokens)

    # ── TF-IDF ───────────────────────────────────────────────────────────

    def _compute_tf(self, freqs: Counter, total: int) -> Dict[str, float]:
        return {w: c / total for w, c in freqs.items()}

    def _compute_idf(self) -> Dict[str, float]:
        if self._total_docs < 1:
            return {}
        n = self._total_docs
        return {w: math.log((1 + n) / (1 + self._idf.get(w, 0))) + 1
                for w in self._vocab}

    def _tfidf_vector(self, tokens: List[str], idf: Dict[str, float]) -> Dict[str, float]:
        if not tokens:
            return {}
        freqs = self._token_freqs(tokens)
        tf = self._compute_tf(freqs, len(tokens))
        return {w: tf.get(w, 0) * idf.get(w, 1.0) for w in set(tokens) if w in idf}

    def _cosine_sim(self, v1: Dict[str, float], v2: Dict[str, float]) -> float:
        if not v1 or not v2:
            return 0.0
        dot = sum(v1.get(w, 0) * v2.get(w, 0) for w in set(list(v1.keys()) + list(v2.keys())))
        n1 = math.sqrt(sum(v ** 2 for v in v1.values()))
        n2 = math.sqrt(sum(v ** 2 for v in v2.values()))
        if n1 == 0 or n2 == 0:
            return 0.0
        return dot / (n1 * n2)

    # ── Index ────────────────────────────────────────────────────────────

    def _rebuild_index(self):
        """Reconstruit l'index TF-IDF depuis self._intents."""
        self._vocab = set()
        self._idf = {}
        self._total_docs = 0

        doc_freq = Counter()
        all_tokens = []

        for intent_name, utterances in self._intents.items():
            for utterance in utterances:
                tokens = self._tokenize(utterance)
                if not tokens:
                    continue
                all_tokens.append((intent_name, utterance, tokens))
                unique = set(tokens)
                for w in unique:
                    doc_freq[w] += 1
                self._total_docs += 1

        self._idf = dict(doc_freq)
        self._vocab = set(doc_freq.keys())

        logger.debug("Index reconstruit: %d docs, %d termes",
                     self._total_docs, len(self._vocab))

    # ── Entraînement ─────────────────────────────────────────────────────

    def train(self, utterances: List[str], intent_name: Optional[str] = None):
        """
        Entraîne sur une liste d'utterances.

        Si intent_name est fourni, les utterances sont assignées à cet intent.
        Sinon, utilise le nom de l'intent dérivé (compat ChatterBot ListTrainer).
        """
        if intent_name:
            if intent_name not in self._intents:
                self._intents[intent_name] = []
            self._intents[intent_name].extend(utterances)
        else:
            for utt in utterances:
                self._intents.setdefault("_unknown", []).append(utt)
        self._rebuild_index()

    def train_from_file(self, filepath: str):
        """
        Entraîne depuis un fichier JSON.

        Format:
          {"intents": [{"name": "greeting", "utterances": ["Bonjour", "Salut"]}]}
        """
        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)
        for intent_data in data.get("intents", []):
            name = intent_data["name"]
            utterances = intent_data.get("utterances", [])
            self._intents.setdefault(name, []).extend(utterances)
        self._rebuild_index()
        logger.info("Entraîné depuis %s (%d intents)", filepath, len(data.get("intents", [])))

    def add_intent(self, name: str, utterances: List[str]):
        """Ajoute un intent avec ses utterances."""
        self._intents.setdefault(name, []).extend(utterances)
        self._rebuild_index()

    def learn(self, utterance: str, intent_name: str):
        """Apprend un nouvel utterance pour un intent (entraînement réactif)."""
        self._intents.setdefault(intent_name, []).append(utterance)
        self._rebuild_index()

    # ── Matching ─────────────────────────────────────────────────────────

    def get_intent(self, text: str, threshold: float = 0.15) -> Dict:
        """
        Match le texte contre les intents connus via TF-IDF + cosinus.

        Args:
            text: Texte utilisateur
            threshold: Seuil de similarité minimum

        Returns:
            Dict avec intent, confidence, response, source
        """
        tokens = self._tokenize(text)
        if not tokens or self._total_docs < 1:
            return {"intent": "unknown", "confidence": 0.0, "response": None, "source": "fallback"}

        idf = self._compute_idf()
        query_vec = self._tfidf_vector(tokens, idf)

        best_intent = "unknown"
        best_score = 0.0

        for intent_name, utterances in self._intents.items():
            for utterance in utterances:
                utt_tokens = self._tokenize(utterance)
                if not utt_tokens:
                    continue
                utt_vec = self._tfidf_vector(utt_tokens, idf)
                score = self._cosine_sim(query_vec, utt_vec)
                if score > best_score:
                    best_score = score
                    best_intent = intent_name

        if best_score >= threshold:
            return {
                "intent": best_intent,
                "confidence": round(min(best_score, 0.95), 2),
                "response": None,
                "source": "tfidf",
            }

        return {"intent": "unknown", "confidence": round(best_score, 2),
                "response": None, "source": "fallback"}

    def get_response(self, text: str) -> Optional[str]:
        """
        Compat ChatterBot: retourne la réponse la plus probable (ou None).
        Les réponses sont stockées dans le graphe Response associé à l'intent.
        """
        result = self.get_intent(text)
        if result["intent"] != "unknown":
            return f"intent:{result['intent']}"
        return None

    # ── Persistance Kuzu ────────────────────────────────────────────────

    def load_from_kuzu(self, conn):
        """Charge les intents depuis le graphe Kuzu."""
        try:
            result = conn.execute("""
                MATCH (i:Intent)-[:HAS]->(u:Utterance)
                RETURN i.name AS intent, u.text AS utterance
                ORDER BY i.name
            """)
            count = 0
            while result.has_next():
                row = result.get_next()
                intent = row[0]
                utterance = row[1]
                if intent and utterance:
                    self._intents.setdefault(intent, []).append(utterance)
                    count += 1
            self._rebuild_index()
            logger.info("Chargé %d utterances depuis Kuzu (%d intents)",
                        count, len(self._intents))
        except Exception as e:
            logger.warning("Erreur chargement Kuzu: %s", e)

    def save_to_kuzu(self, conn):
        """Sauvegarde les intents dans le graphe Kuzu."""
        try:
            for intent_name, utterances in self._intents.items():
                conn.execute(f"""
                    MERGE (i:Intent {{name: '{intent_name}'}})
                """)
                for utterance in utterances:
                    safe = utterance.replace("'", "\\'")
                    conn.execute(f"""
                        MATCH (i:Intent {{name: '{intent_name}'}})
                        MERGE (u:Utterance {{text: '{safe}'}})
                        MERGE (i)-[:HAS]->(u)
                    """)
            logger.info("Sauvegardé %d intents dans Kuzu", len(self._intents))
        except Exception as e:
            logger.error("Erreur sauvegarde Kuzu: %s", e)

    # ── Stats ────────────────────────────────────────────────────────────

    def list_intents(self) -> Dict[str, int]:
        return {name: len(uts) for name, uts in self._intents.items()}

    def status(self) -> Dict:
        return {
            "engine": "intent_engine",
            "num_intents": len(self._intents),
            "total_utterances": sum(len(u) for u in self._intents.values()),
            "vocab_size": len(self._vocab),
            "total_docs": self._total_docs,
        }
