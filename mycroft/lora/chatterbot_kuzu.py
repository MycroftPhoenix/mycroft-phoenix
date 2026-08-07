"""
IntentEngine + Kuzu Intent Matching.

Système d'intent matching combinant:
- IntentEngine (TF-IDF pur Python, zéro dépendance externe)
- Kuzu pour le stockage persistant des utterances
- Mots-clés pour les intents fixes à haute confiance
"""

import json
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class IntentMatcher:
    """
    Matcher d'intents — IntentEngine + Kuzu dual.

    Flow:
    1. Crisis check (system DB, priorité absolue)
    2. Keywords (intents fixes, confiance haute)
    3. IntentEngine (TF-IDF, fuzzy matching)
    4. Fallback

    System DB (phoenix.kuzu): intents, crises, config → READ-ONLY
    Personal DB (phoenix_personal.kuzu): conversations, skills → wipeable
    """
    
    def __init__(
        self,
        kuzu_manager,
        db_path: str = "./data/intents.db",
    ):
        """
        Args:
            kuzu_manager: Instance KuzuManager (triple DB)
            db_path: Chemin pour IntentEngine
        """
        self.kuzu_manager = kuzu_manager
        self.kuzu_graph = kuzu_manager.system_conn
        self.db_path = db_path
        self._engine = None
        self._intents: Dict[str, List[str]] = {}
        
    def initialize(self):
        """Initialise IntentEngine et charge les intents depuis Kuzu."""
        from mycroft.lora.intent_engine import IntentEngine

        self._engine = IntentEngine(db_path=self.db_path)

        # Charger les intents depuis Kuzu si disponible
        if self.kuzu_graph:
            self._engine.load_from_kuzu(self.kuzu_graph)
        else:
            logger.info("Kuzu non disponible - IntentEngine sans persistance")

        # Copier les intents dans self._intents pour compatibilité
        self._intents = self._engine._intents

        logger.info("IntentMatcher initialisé avec IntentEngine: %s", self._engine.status())
        
    def _load_intents_from_kuzu(self):
        """Charge les intents depuis Kuzu (délègue à IntentEngine)."""
        if self._engine and self.kuzu_graph:
            self._engine.load_from_kuzu(self.kuzu_graph)
            self._intents = self._engine._intents
            
    def _train_chatbot(self):
        """Entraîne IntentEngine sur les intents chargés (compat)."""
        if self._engine and self._intents:
            for intent_name, utterances in self._intents.items():
                self._engine.add_intent(intent_name, utterances)
            
    def add_intent(self, name: str, utterances: List[str]):
        """
        Ajoute un intent avec ses utterances.
        
        Args:
            name: Nom de l'intent
            utterances: Liste des phrases d'entraînement
        """
        if name not in self._intents:
            self._intents[name] = []
        self._intents[name].extend(utterances)
        
    def match(self, text: str, confidence_threshold: float = 0.6) -> Dict:
        """
        Matche un texte contre les intents connus.

        Priorité: Crisis check > Keywords (intents fixes) > IntentEngine (TF-IDF) > Fallback.
        Log les conversations dans la base personnelle.

        Args:
            text: Texte de l'utilisateur
            confidence_threshold: Seuil de confiance minimum

        Returns:
            Dict avec intent, confidence, response
        """
        result = None

        # PRIORITÉ 1: Sévérité santé mentale (échelle 1-4)
        severity = self._assess_severity(text)
        if severity["severity"] >= 4:
            result = severity  # Crise immédiate
        elif severity["severity"] >= 2:
            result = severity  # Préoccupation ou alerte
        elif severity["severity"] >= 1:
            result = severity  # Confort

        # PRIORITÉ 2: Keywords pour intents FIXES (greeting, time, date, etc.)
        # Avant ChatterBot pour éviter que le ML ne prenne le dessus
        if result is None:
            intent_kw = self._intent_keywords(text)
            if intent_kw["intent"] not in ("unknown", None):
                result = intent_kw

        # PRIORITÉ 3: IntentEngine (TF-IDF fuzzy matching)
        if result is None and self._engine:
            try:
                ie_result = self._engine.get_intent(text, threshold=confidence_threshold * 0.5)
                if ie_result["intent"] != "unknown":
                    result = {
                        "intent": ie_result["intent"],
                        "confidence": ie_result["confidence"],
                        "response": None,
                        "source": ie_result["source"],
                    }
            except Exception as e:
                logger.debug(f"IntentEngine erreur: {e}")

        # PRIORITÉ 4: Fallback
        if result is None:
            result = {
                "intent": "unknown",
                "confidence": 0.0,
                "response": "Je ne suis pas sûr de comprendre.",
                "source": "fallback",
            }

        # Logger dans la base personnelle (si disponible)
        if self.kuzu_manager and result.get("response"):
            try:
                self.kuzu_manager.log_conversation(
                    user_input=text,
                    response=str(result["response"]),
                    intent=result["intent"],
                    confidence=result["confidence"],
                    source=result["source"],
                )
            except Exception as e:
                logger.debug("Erreur log conversation: %s", e)

        return result

    def _find_intent_for_response(self, response_text: str) -> str:
        """Trouve l'intent correspondant à une réponse."""
        response_lower = response_text.lower()
        for intent_name, utterances in self._intents.items():
            for u in utterances:
                if u.lower() in response_lower or response_lower in u.lower():
                    return intent_name
        return "conversation"

    def _normalize(self, text: str) -> str:
        """Normalise le texte: minuscule + supprime accents + normalise apostrophes."""
        import unicodedata
        t = text.lower().strip()
        t = unicodedata.normalize('NFKD', t)
        t = ''.join(c for c in t if not unicodedata.combining(c))
        # Remplacer œ, æ
        t = t.replace('œ', 'oe').replace('æ', 'ae')
        # Normaliser apostrophes (droites et courbes) en espace
        t = t.replace("'", " ").replace("\u2019", " ").replace("\u2018", " ")
        t = " ".join(t.split())  # supprimer espaces multiples
        return t

    def _assess_severity(self, text: str) -> Dict:
        """
        Évalue la sévérité du contenu sur une échelle 1-4.

        1 = Confort (tristesse, deuil, dispute → écoute empathique)
        2 = Préoccupation (solitude, stress, vide léger → soutien + check-in)
        3 = Alerte (désespoir, fardeau, résignation → intervention + ressources)
        4 = Crise (suicide, automutilation, adieux → URGENCE numéros)
        """
        text_norm = self._normalize(text)

        patterns = {
            # Level 1 - Confort : tristesse passagère, deuil, disputes
            (1, "sadness"): [
                "je suis triste", "je me sens triste", "je suis peiné",
                "j'ai du chagrin", "je pleure", "j'ai pleuré",
                "mon chien", "mon chat", "mon animal", "mon ami est mort",
                "il est décédé", "elle est décédée", "perdre quelqu'un",
                "je suis en deuil", "enterrement", "funérailles",
                "je me suis disputé", "on s'est disputé", "on s'est fâché",
                "rupture", "il m'a quitté", "elle m'a quitté", "séparation",
                "mon copain", "ma copine", "conjoint", "conjointe",
                "je suis déçu", "je suis déçue",
                "j'ai eu une mauvaise journée", "ça va mal", "ça se passe mal",
            ],
            # Level 2 - Préoccupation : solitude, stress, anxiété, dépression
            (2, "loneliness"): [
                "je me sens seul", "je suis seul", "personne ne m'aime",
                "pas d'amis", "tout le monde me déteste",
                "je suis invisible", "personne ne me remarque",
                "je me sens exclu", "je suis toujours seul",
                "je me sens abandonné", "je suis abandonné",
            ],
            (2, "anxiety"): [
                "crise d'angoisse", "je ne peux pas respirer",
                "mon cœur bat trop vite", "je stresse", "en panique",
                "j'ai peur", "angoisse", "anxieux", "anxiete",
                "je ne vais pas y arriver", "tout va mal",
                "j'ai tres peur", "peur de tout",
            ],
            (2, "stress"): [
                "trop de pression", "je suis submergé", "je craque",
                "tout s'effondre", "je suis débordé",
                "trop de travail", "je n'arrive pas a gerer",
                "stress", "pression", "surcharge",
            ],
            (2, "sadness_deep"): [
                "c'est trop dur", "je n'arrive plus à", "je suis fatigué",
                "je suis fatiguée", "j'ai perdu goût", "plus de goût à rien",
                "je suis déprimé", "je suis déprimée", "je me sens déprimé",
                "je me sens déprimée", "déprimé", "dépression",
                "plus le moral", "perdu le moral", "pas le moral",
                "plus de joie de vivre",
            ],
            # Level 3 - Alerte : désespoir, vide profond
            (3, "hopelessness"): [
                "plus d'espoir", "rien ne va changer", "à quoi bon",
                "rien ne sert de lutter", "je suis résigné",
                "c'est toujours pareil", "rien ne change",
                "je suis coincé", "la vie n'a pas de sens",
                "la vie n'a plus de sens", "ça n'a plus de sens",
                "la vie n'a plus de saveur", "je suis en pilote automatique",
                "je ne reconnais plus moi-meme", "je suis fatigué d'exister",
                "life has no meaning anymore", "i am on autopilot",
                "i don't recognize myself anymore", "i am tired of existing",
            ],
            (3, "emptiness"): [
                "je suis vide", "je me sens vide",
                "je suis une charge", "je coule",
                "je m'efface", "je suis tanné de me battre",
                "j'en ai marre de survivre", "prends soin de mes proches",
                "dites a ma mere que je l'aime",
                "i feel empty inside", "i am a burden to everyone",
                "i am drowning", "i am fading away",
                "take care of my loved ones for me",
                "tell my family i love them",
            ],
            (3, "despair"): [
                "je ne veux plus", "je n'en peux plus",
                "je suis au bout", "je suis dépressif",
                "je ne sers à rien", "je suis un poids",
                "je veux que tout s'arrete", "je ne vois pas d'issue",
                "c'est trop lourd", "je suis résigné",
                "quoi bon", "a quoi bon",
            ],
            # Level 4 - Crise : suicide, auto-mutilation, préparatifs
            (4, "suicidal"): [
                "je veux mourir", "je veux me tuer", "suicide",
                "je ne veux plus vivre", "mettre fin à mes jours",
                "j ai envie de mourir", "j ai envie de me tuer",
                "je pense au suicide", "je pense a me tuer",
                "je vais me tuer", "je vais mourir",
                "i want to die", "kill myself",
            ],
            (4, "self_harm"): [
                "me faire du mal", "me scarifie", "me coupe",
                "la douleur physique", "les cicatrices",
                "je veux souffrir", "me blesser",
            ],
            (4, "preparatory"): [
                "je veux juste que la douleur s'arrete",
                "plus rien n'a d'importance", "je suis pret a tout",
                "c'est ma derniere semaine", "je fais mes adieux",
                "merci pour tout ce que vous avez fait",
                "je veux que vous sachiez", "je n'aurai plus jamais peur",
                "i just want the pain to stop",
                "nothing matters anymore", "i am ready for anything",
                "this is my last week", "i am saying my goodbyes",
                "thank you for everything you did",
                "i want you to know",
                "i will never be afraid again",
            ],
            # Level 3-4 : réponses à "comment ça va" inquiétantes
            (3, "distress_response"): [
                "je vais pas bien", "je ne vais pas bien",
                "ca va pas", "pas bien du tout", "plutot mal",
                "vous seriez plus heureux sans moi",
            ],
        }

        best = {"intent": "unknown", "confidence": 0.0, "response": None, "source": "severity_check", "severity": 0}

        for (level, intent), keywords in patterns.items():
            for keyword in keywords:
                kw_norm = self._normalize(keyword)
                if kw_norm in text_norm:
                    score = 0.6 + (level * 0.09)  # 0.69, 0.78, 0.87, 0.95
                    if score > best["confidence"]:
                        best = {
                            "intent": intent,
                            "confidence": round(min(score, 0.95), 2),
                            "response": None,
                            "source": "severity",
                            "severity": level,
                        }

        return best

    def _intent_keywords(self, text: str) -> Dict:
        """Keywords pour intents FIXES (greeting, time, date, etc.) - PAS santé mentale."""
        text_norm = self._normalize(text)

        keyword_map = {
            "greeting": ["bonjour", "salut", "hello", "hi", "coucou", "hey", "ciao", "hola", "bonsoir", "salutations", "bien le bonjour", "what's up", "howdy"],
            "farewell": ["au revoir", "bye", "adieu", "à bientôt", "see you", "ciao", "take care", "salut"],
            "how_are_you": ["comment ça va", "comment ca va", "ça va", "ca va", "tu vas bien", "comment vas-tu", "what's up", "quoi de neuf", "ça va bien", "comment allez-vous"],
            "name": ["comment tu t'appelles", "quel est ton nom", "tu es qui", "who are you", "what's your name", "tu t'appelles comment"],
            "weather": ["temps", "température", "temperature", "météo", "meteo", "weather", "quel temps", "combien de degrés", "combien de degres", "degrés", "degres", "il fait froid", "il fait chaud", "forecast", "prévisions", "previsions"],
            "time": ["heure", "midi", "minuit", "quelle heure", "il est quelle heure"],
            "date": ["date", "jour", "mois", "année", "aujourd'hui", "quelle date", "quel jour"],
            "thanks": ["merci", "thanks", "remercie", "gracias", "danke", "merci beaucoup", "thanks a lot"],
            "help": ["aide", "help", "aide-moi", "j'ai besoin d'aide", "assistance", "support"],
            "yes": ["oui", "yes", "d'accord", "ok", "yep", "sure"],
            "no": ["non", "no", "nope", "nop", "pas du tout", "not at all"],
        }

        words = set(text_norm.split())

        for intent, keywords in keyword_map.items():
            for keyword in keywords:
                kw_norm = self._normalize(keyword)
                kw_words = set(kw_norm.split())
                if kw_words.issubset(words):
                    return {
                        "intent": intent,
                        "confidence": 0.95,
                        "response": None,
                        "source": "keyword",
                    }

        # Fallback partiel
        def normalize_words(text):
            t = self._normalize(text)
            t = t.replace("'", " ").replace("\u2019", " ")
            return set(w for w in t.split() if len(w) >= 4)

        for intent, keywords in keyword_map.items():
            for keyword in keywords:
                kw_words = normalize_words(keyword)
                txt_words = normalize_words(text_norm)
                common = kw_words & txt_words
                if len(common) >= 2:
                    return {
                        "intent": intent,
                        "confidence": 0.85,
                        "response": None,
                        "source": "keyword_partial",
                    }

        return {"intent": "unknown", "confidence": 0.0, "response": "Je ne suis pas sûr de comprendre.", "source": "fallback"}

    def _keyword_fallback(self, text: str) -> Dict:
        """Ancien fallback - redirige vers _intent_keywords pour compat."""
        return self._intent_keywords(text)
        
    def train_from_file(self, filepath: str):
        """Entraîne depuis un fichier JSON (délègue à IntentEngine)."""
        if self._engine:
            self._engine.train_from_file(filepath)
            # Synchroniser self._intents
            self._intents = self._engine._intents
            logger.info("Entraîné depuis %s", filepath)
        else:
            logger.warning("IntentEngine non initialisé")
        
    def save_intents_to_kuzu(self):
        """Sauvegarde les intents dans le graphe Kuzu."""
        if not self.kuzu_graph:
            logger.warning("Kuzu non disponible, sauvegarde impossible")
            return
            
        try:
            for intent_name, utterances in self._intents.items():
                # Créer l'intent s'il n'existe pas
                self.kuzu_graph.query(f"""
                    MERGE (i:Intent {{name: '{intent_name}'}})
                """)
                
                # Ajouter les utterances
                for utterance in utterances:
                    # Échapper les guillemets
                    safe_utterance = utterance.replace("'", "\\'")
                    self.kuzu_graph.query(f"""
                        MATCH (i:Intent {{name: '{intent_name}'}})
                        CREATE (u:Utterance {{text: '{safe_utterance}'}})
                        CREATE (i)-[:HAS]->(u)
                    """)
                    
            logger.info(f"Sauvegardé {len(self._intents)} intents dans Kuzu")
            
        except Exception as e:
            logger.error(f"Erreur sauvegarde Kuzu: {e}")
            
    def list_intents(self) -> Dict[str, int]:
        """Retourne la liste des intents avec le nombre d'utterances."""
        return {name: len(utterances) for name, utterances in self._intents.items()}
        
    def status(self) -> Dict:
        """Retourne le statut du matcher."""
        base = {
            "kuzu_connected": self.kuzu_graph is not None,
            "num_intents": len(self._intents),
            "total_utterances": sum(len(u) for u in self._intents.values()),
        }
        if self._engine:
            base["engine"] = self._engine.status()
        return base
