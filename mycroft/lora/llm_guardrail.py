"""
LLM Guardrail pour la détection de crise.

Utilise Ollama (qwen2.5-coder:3b) avec un prompt JSON structuré
pour valider/amplifier la détection lexicale.

Prompt demande un JSON avec:
- crisis: true/false
- confidence: 0.0-1.0
- signals: ["direct", "subtle", "preparatory"]
- reasoning: explication courte
"""

import json
import logging
import urllib.request
from typing import Dict, Optional

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5-coder:3b"


CRISIS_PROMPT = """Tu es un système de détection de crise. Analyse le message suivant.

CONTEXTE: Ceci est une conversation avec un assistant vocal. Le message pourrait exprimer une détresse psychologique.

CATÉGORIES DE SIGNAUX:
- direct: mentions explicites de suicide ou de mort ("je veux mourir", "je veux me tuer")
- subtle: signaux indirects mais inquiétants ("je suis vide", "je coule", "je suis une charge")
- preparatory: signaux de préparation ("je fais mes adieux", "dites à ma mère que je l'aime")
- none: pas de signaux de crise

RÈGLES:
1. Si le message contient des signaux de crise, réponds {"crisis": true, "confidence": X, "signals": [...], "reasoning": "..."}
2. Si le message est ambigu, réponds {"crisis": true, "confidence": 0.5, "signals": [...], "reasoning": "..."}
3. Si pas de signaux, réponds {"crisis": false, "confidence": 0.9, "signals": [], "reasoning": "..."}

IMPORTANT: Réponds UNIQUEMENT avec un JSON valide, pas de texte additionnel.

Message: {message}
Réponse JSON:"""


class LLMGuardrail:
    """
    Guardrail LLM pour valider/amplifier la détection de crise.
    
    Utilise un prompt JSON structuré avec Ollama.
    """

    def __init__(self, model: str = DEFAULT_MODEL, timeout: int = 30):
        self.model = model
        self.timeout = timeout
        self._available = False

    def initialize(self):
        """Vérifie qu'Ollama est disponible."""
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("name", "") for m in data.get("models", [])]
                self._available = any(self.model in m for m in models)
                if self._available:
                    logger.info(f"LLM Guardrail: {self.model} disponible")
                else:
                    logger.warning(f"Modèle {self.model} non trouvé: {models}")
        except Exception as e:
            logger.warning(f"Ollama non disponible: {e}")
            self._available = False

    def analyze(self, message: str, context: Optional[list] = None) -> Dict:
        """
        Analyse un message avec le LLM.
        
        Args:
            message: Le message à analyser
            context: Messages précédents (optionnel, pour le contexte)
            
        Returns:
            {"crisis": bool, "confidence": float, "signals": list, "reasoning": str}
        """
        if not self._available:
            return self._fallback_response(message)

        # Construire le prompt avec contexte si disponible
        full_message = message
        if context:
            context_str = "\n".join(context[-3:])  # 3 derniers messages
            full_message = f"Messages précédents:\n{context_str}\n\nMessage actuel: {message}"

        prompt = CRISIS_PROMPT.format(message=full_message)

        try:
            response_text = self._call_ollama(prompt)
            return self._parse_response(response_text)
        except Exception as e:
            logger.error(f"Erreur LLM guardrail: {e}")
            return self._fallback_response(message)

    def _call_ollama(self, prompt: str) -> str:
        """Appelle Ollama API."""
        import urllib.request

        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 150,
            }
        }).encode("utf-8")

        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode())
            return data.get("response", "")

    def _parse_response(self, text: str) -> Dict:
        """Parse la réponse JSON du LLM."""
        text = text.strip()

        # Essayer de trouver un JSON dans la réponse
        start = text.find("{")
        end = text.rfind("}") + 1

        if start != -1 and end > start:
            json_str = text[start:end]
            try:
                result = json.loads(json_str)
                # Valider la structure
                return {
                    "crisis": bool(result.get("crisis", False)),
                    "confidence": float(result.get("confidence", 0.0)),
                    "signals": list(result.get("signals", [])),
                    "reasoning": str(result.get("reasoning", "")),
                    "source": "llm",
                }
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"JSON invalide du LLM: {e}")

        # Fallback si pas de JSON valide
        return self._fallback_response(text)

    def _fallback_response(self, message: str) -> Dict:
        """Réponse fallback quand le LLM n'est pas disponible."""
        # Détection basique heuristique
        crisis_keywords = [
            "mourir", "suicide", "tuer", "mort", "die", "kill",
            "vide", "charge", "coule", "efface", "tanné",
        ]
        message_lower = message.lower()
        found = [kw for kw in crisis_keywords if kw in message_lower]

        return {
            "crisis": len(found) > 0,
            "confidence": 0.7 if found else 0.3,
            "signals": ["direct"] if found else [],
            "reasoning": f"Fallback heuristique: {found}" if found else "Pas de signaux détectés",
            "source": "fallback",
        }

    @property
    def is_available(self) -> bool:
        return self._available
