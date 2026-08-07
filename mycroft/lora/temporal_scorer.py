"""
Scoring temporel pour la détection de crise.

Système de score glissant:
- Fenêtre de N dernières interactions
- Score par signal (direct=3, subtil=2, preparatoire=1)
- Seuil configurable pour déclencher l'alerte
- Décroissance temporelle (les signaux anciens pèsent moins)
"""

import time
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SignalScore:
    """Un signal de crise avec son score et timestamp."""
    text: str
    category: str  # "direct", "subtle", "preparatory", "llm_flag"
    score: int
    timestamp: float = field(default_factory=time.time)


class TemporalScorer:
    """
    Score glissant sur les N dernières interactions.
    
    Seuils:
    - direct (3 pts): "je veux mourir", "suicide"
    - subtle (2 pts): "je suis vide", "je coule"
    - preparatory (1 pt): "je fais mes adieux"
    - llm_flag (2 pts): flag du LLM guardrail
    """

    # Scores par catégorie
    SCORES = {
        "direct": 3,
        "subtle": 2,
        "preparatory": 1,
        "llm_flag": 2,
    }

    def __init__(
        self,
        window_size: int = 10,
        threshold: int = 3,
        decay_factor: float = 0.9,
    ):
        """
        Args:
            window_size: Nombre de messages dans la fenêtre glissante
            threshold: Score minimum pour déclencher l'alerte
            decay_factor: Facteur de décroissance (0.0-1.0)
        """
        self.window_size = window_size
        self.threshold = threshold
        self.decay_factor = decay_factor
        self._signals: deque = deque(maxlen=window_size)

    def add_signal(self, text: str, category: str, score: Optional[int] = None) -> float:
        """
        Ajoute un signal et retourne le score total actuel.
        
        Args:
            text: Le texte original
            category: "direct", "subtle", "preparatory", "llm_flag"
            score: Score personnalisé (sinon utilise SCORES[category])
        """
        if category not in self.SCORES:
            logger.warning(f"Catégorie inconnue: {category}")
            return self.get_score()

        signal_score = SignalScore(
            text=text,
            category=category,
            score=score or self.SCORES[category],
        )
        self._signals.append(signal_score)

        logger.debug(f"Signal ajouté: {category} ({signal_score.score}pts) → total={self.get_score():.1f}")
        return self.get_score()

    def get_score(self) -> float:
        """
        Calcule le score total avec décroissance temporelle.
        
        Plus un signal est récent, plus il pèse lourd.
        Les signaux récents (dernières 2 minutes) gardent 100% du score.
        """
        if not self._signals:
            return 0.0

        now = time.time()
        total = 0.0

        for signal in self._signals:
            age_seconds = now - signal.timestamp
            # Decay seulement après 2 minutes
            if age_seconds < 120:
                age_factor = 1.0
            else:
                age_factor = self.decay_factor ** ((age_seconds - 120) / 60)
            total += signal.score * age_factor

        return round(total, 2)

    def should_alert(self) -> bool:
        """Vérifie si le score dépasse le seuil."""
        return self.get_score() >= self.threshold

    def get_signals_by_category(self) -> dict:
        """Retourne les signaux groupés par catégorie."""
        result = {}
        for signal in self._signals:
            if signal.category not in result:
                result[signal.category] = []
            result[signal.category].append({
                "text": signal.text,
                "score": signal.score,
                "age_seconds": int(time.time() - signal.timestamp),
            })
        return result

    def get_recent_texts(self, n: int = 5) -> list:
        """Retourne les N derniers textes (pour contexte LLM)."""
        return [s.text for s in list(self._signals)[-n:]]

    def reset(self):
        """Réinitialise le score."""
        self._signals.clear()
        logger.info("Score temporel réinitialisé")

    def get_debug_info(self) -> dict:
        """Info de debug pour le monitoring."""
        return {
            "current_score": self.get_score(),
            "threshold": self.threshold,
            "should_alert": self.should_alert(),
            "signals_count": len(self._signals),
            "signals_by_category": self.get_signals_by_category(),
            "window_size": self.window_size,
        }
