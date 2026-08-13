"""
Détecteur de crise multicouche.

Pipeline de détection:
1. Scan lexical rapide (subtil + preparatoire + direct)
2. Validation LLM guardrail (optionnel)
3. Scoring temporel (fenêtre glissante)
4. Si alerte → lookup ressources géolocalisées

Ne gère JAMAIS la crise directement.
Redirige TOUJOURS vers les ressources existantes.
"""

import logging
from typing import Dict, Optional, List
from mycroft.capabilities.temporal_scorer import TemporalScorer
from mycroft.capabilities.locate_resources import CrisisLocator

logger = logging.getLogger(__name__)


class CrisisDetector:
    """
    Détecteur de crise multicouche avec scoring temporel.
    
    Architecture:
    - Couche 1: Lexical (keywords directs + subtils + préparatoires)
    - Couche 2: LLM guardrail (validation contextuelle)
    - Couche 3: Score temporel (accumulation sur fenêtre glissante)
    - Couche 4: Géolocalisation + ressources
    """

    # Keywords par catégorie (pour le scan lexical rapide)
    KEYWORDS = {
        "direct": [
            "je veux mourir", "je veux me tuer", "suicide",
            "mettre fin à mes jours", "je ne veux plus vivre",
            "kill myself", "i want to die",
        ],
        "subtle": [
            "je suis vide", "je suis une charge", "je coule",
            "je m'efface", "je suis tanné de me battre",
            "j'en ai marre de survivre", "prends soin de mes proches",
            "dites à ma mère que je l'aime",
            "i feel empty inside", "i am a burden",
            "i am drowning", "i am fading away",
        ],
        "preparatory": [
            "je fais mes adieux", "je veux que vous sachiez",
            "merci pour tout ce que vous avez fait",
            "c'est ma dernière semaine",
            "i am saying my goodbyes", "thank you for everything",
        ],
    }

    def __init__(
        self,
        window_size: int = 10,
        threshold: int = 3,
        use_llm: bool = True,
    ):
        """
        Args:
            window_size: Taille de la fenêtre glissante
            threshold: Score minimum pour déclencher alerte
            use_llm: Activer le LLM guardrail
        """
        self.use_llm = use_llm
        self._scorer = TemporalScorer(
            window_size=window_size,
            threshold=threshold,
        )
        self._locator = CrisisLocator()
        self._llm = None
        self._context: List[str] = []

    def initialize(self):
        """Initialise tous les sous-modules."""
        self._locator.initialize()

        if self.use_llm:
            try:
                from mycroft.lora.llm_guardrail import LLMGuardrail
                self._llm = LLMGuardrail()
                self._llm.initialize()
                if self._llm.is_available:
                    logger.info("LLM Guardrail activé")
                else:
                    logger.warning("LLM Guardrail indisponible, mode lexical seul")
                    self._llm = None
            except Exception as e:
                logger.warning(f"Erreur init LLM: {e}")
                self._llm = None

        logger.info("CrisisDetector initialisé")

    def analyze(self, text: str, user_country: Optional[str] = None) -> Dict:
        """
        Analyse un texte et retourne la détection de crise.
        
        Args:
            text: Le texte à analyser
            user_country: Code pays ISO (optionnel)
            
        Returns:
            {
                "alert": bool,
                "score": float,
                "signals": [...],
                "resources": {...},
                "response": str,
            }
        """
        text_lower = text.lower().strip()

        # Couche 1: Scan lexical rapide
        lexical_signals = self._lexical_scan(text_lower)

        # Couche 2: LLM guardrail (si disponible)
        llm_signal = None
        if self._llm and self._llm.is_available:
            llm_result = self._llm.analyze(text, context=self._context)
            if llm_result.get("crisis"):
                llm_signal = llm_result

        # Couche 3: Scoring temporel
        for signal in lexical_signals:
            self._scorer.add_signal(text, signal["category"])

        if llm_signal:
            self._scorer.add_signal(text, "llm_flag")

        # Mettre à jour le contexte
        self._context.append(text)
        if len(self._context) > 10:
            self._context = self._context[-10:]

        # Couche 4: Décision
        should_alert = self._scorer.should_alert()
        resources = {}
        response = ""

        if should_alert:
            # Géolocalisation
            resources = self._locator.get_resources(user_country)
            response = resources.get("spoken_response", "")
            logger.warning(f"ALERTE CRISE! Score={self._scorer.get_score()}, Country={user_country}")

        return {
            "alert": should_alert,
            "score": self._scorer.get_score(),
            "signals": lexical_signals,
            "llm_signal": llm_signal,
            "resources": resources,
            "response": response,
            "debug": self._scorer.get_debug_info(),
        }

    def _lexical_scan(self, text: str) -> List[Dict]:
        """Scan rapide des keywords par catégorie."""
        signals = []

        for category, keywords in self.KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    signals.append({
                        "category": category,
                        "keyword": keyword,
                        "score": TemporalScorer.SCORES.get(category, 1),
                    })
                    break  # Un signal par catégorie suffit

        return signals

    def get_resources(self, country_code: Optional[str] = None) -> Dict:
        """Retourne les ressources pour un pays."""
        return self._locator.get_resources(country_code)

    def get_debug_info(self) -> Dict:
        """Info de debug."""
        return {
            "scorer": self._scorer.get_debug_info(),
            "llm_available": self._llm.is_available if self._llm else False,
            "context_length": len(self._context),
        }

    def reset(self):
        """Réinitialise le détecteur."""
        self._scorer.reset()
        self._context.clear()
