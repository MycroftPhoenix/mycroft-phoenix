"""
NLU Pipeline for Mycroft Phoenix.

Pipeline unifié combinant:
- spaCy pour NER (Named Entity Recognition)
- ChatterBot pour conversation
- LoRA + smollm pour intent matching intelligent
- Kuzu pour mémoire persistante
- all-minilm pour embeddings sémantiques
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class NLUConfig:
    """Configuration du pipeline NLU."""
    
    def __init__(
        self,
        spacy_model: str = "xx_ent_wiki_sm",
        chatterbot_corpus: str = "chatterbot.corpus.french",
        lora_adapters_dir: str = "./adapters",
        ollama_model: str = "smollm:1.7b",
        embedding_model: str = "all-minilm",
    ):
        self.spacy_model = spacy_model
        self.chatterbot_corpus = chatterbot_corpus
        self.lora_adapters_dir = lora_adapters_dir
        self.ollama_model = ollama_model
        self.embedding_model = embedding_model


class NLUPipeline:
    """
    Pipeline NLU unifié pour Phoenix.
    
    Chaîne de traitement:
    1. spaCy → NER (entités nommées)
    2. LoRA + smollm → Intent matching intelligent
    3. ChatterBot → Fallback conversation
    4. Kuzu → Mémoire persistante
    """
    
    def __init__(self, config: Optional[NLUConfig] = None):
        self.config = config or NLUConfig()
        
        self._spacy_nlp = None
        self._adapter_manager = None
        self._chatterbot = None
        self._kuzu_graph = None
        self._embedding_model = None
        
    def initialize(self):
        """Initialise tous les composants du pipeline."""
        logger.info("Initialisation du pipeline NLU...")
        
        # 1. spaCy pour NER
        try:
            import spacy
            self._spacy_nlp = spacy.load(self.config.spacy_model)
            logger.info(f"spaCy chargé: {self.config.spacy_model}")
        except Exception as e:
            logger.warning(f"spaCy non disponible: {e}")
            
        # 2. LoRA Adapter Manager
        try:
            from .adapter_manager import AdapterManager
            self._adapter_manager = AdapterManager(self.config.lora_adapters_dir)
            self._adapter_manager.scan_adapters()
            logger.info(f"LoRA: {len(self._adapter_manager._registry)} adaptateurs trouvés")
        except Exception as e:
            logger.warning(f"LoRA non disponible: {e}")
            
        # 3. ChatterBot
        try:
            from chatterbot import ChatBot
            from chatterbot.trainers import ListTrainer
            
            self._chatterbot = ChatBot(
                "Phoenix",
                storage_adapter="chatterbot.storage.SQLStorageAdapter",
                database_uri="sqlite:///phoenix_chatterbot.db",
            )
            logger.info("ChatterBot chargé")
        except Exception as e:
            logger.warning(f"ChatterBot non disponible: {e}")
            
        # 4. all-minilm pour embeddings
        try:
            self._load_embedding_model()
        except Exception as e:
            logger.warning(f"Modèle d'embeddings non disponible: {e}")
            
        logger.info("Pipeline NLU initialisé")
        
    def _load_embedding_model(self):
        """Charge le modèle d'embeddings all-minilm via Ollama."""
        try:
            import requests
            
            # Vérifier si all-minilm est disponible dans Ollama
            response = requests.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m["name"] for m in models]
                
                if any("all-minilm" in name for name in model_names):
                    logger.info("all-minilm disponible dans Ollama")
                    self._embedding_model = "all-minilm"
                else:
                    logger.info("all-minilm non trouvé, embeddings indisponibles")
            else:
                logger.warning("Ollama non accessible")
        except Exception as e:
            logger.warning(f"Erreur vérification all-minilm: {e}")
            
    def process(self, text: str) -> Dict:
        """
        Traite un texte à travers le pipeline NLU.
        
        Args:
            text: Texte de l'utilisateur
            
        Returns:
            Dict avec les résultats du pipeline
        """
        result = {
            "text": text,
            "entities": [],
            "intent": None,
            "confidence": 0.0,
            "response": None,
            "source": None,
        }
        
        # 1. NER avec spaCy
        if self._spacy_nlp:
            doc = self._spacy_nlp(text)
            result["entities"] = [
                {"text": ent.text, "label": ent.label_}
                for ent in doc.ents
            ]
            
        # 2. LoRA intent matching
        if self._adapter_manager and self._adapter_manager._registry:
            try:
                response, intent = self._adapter_manager.generate(text)
                if response:
                    result["response"] = response
                    result["intent"] = intent
                    result["confidence"] = 0.9  # LoRA haute confiance
                    result["source"] = "lora"
                    return result
            except Exception as e:
                logger.debug(f"LoRA pas applicable: {e}")
                
        # 3. Fallback ChatterBot
        if self._chatterbot:
            try:
                response = self._chatterbot.get_response(text)
                result["response"] = str(response)
                result["confidence"] = 0.7
                result["source"] = "chatterbot"
                return result
            except Exception as e:
                logger.debug(f"ChatterBot pas applicable: {e}")
                
        # 4. Pas de réponse trouvée
        result["response"] = "Je ne suis pas sûr de comprendre. Pouvez-vous reformuler?"
        result["source"] = "fallback"
        return result
        
    def train_chatterbot(self, intent_name: str, utterances: List[str]):
        """
        Entraîne ChatterBot sur de nouvelles utterances.
        
        Args:
            intent_name: Nom de l'intent
            utterances: Liste des phrases d'entraînement
        """
        if not self._chatterbot:
            logger.warning("ChatterBot non initialisé")
            return
            
        from chatterbot.trainers import ListTrainer
        
        trainer = ListTrainer(self._chatterbot)
        trainer.train(utterances)
        logger.info(f"ChatterBot entraîné sur {len(utterances)} utterances pour '{intent_name}'")
        
    def train_lora(
        self,
        intent_name: str,
        utterances: List[str],
        output_dir: Optional[str] = None,
    ) -> str:
        """
        Entraîne un adaptateur LoRA pour un intent.
        
        Args:
            intent_name: Nom de l'intent
            utterances: Liste des phrases d'entraînement
            output_dir: Répertoire de sortie (optionnel)
            
        Returns:
            Chemin vers l'adaptateur sauvegardé
        """
        from .trainer import LoRATrainer
        
        trainer = LoRATrainer()
        trainer.add_intent(intent_name, utterances)
        
        if output_dir is None:
            output_dir = f"{self.config.lora_adapters_dir}/{intent_name}"
            
        return trainer.train(output_dir)
        
    def embed_text(self, text: str) -> Optional[List[float]]:
        """
        Génère un embedding pour un texte via all-minilm (Ollama).
        
        Args:
            text: Texte à embedder
            
        Returns:
            Vecteur d'embedding ou None
        """
        if not self._embedding_model:
            return None
            
        try:
            import requests
            
            response = requests.post(
                "http://localhost:11434/api/embeddings",
                json={
                    "model": "all-minilm",
                    "prompt": text,
                },
            )
            
            if response.status_code == 200:
                return response.json().get("embedding")
            else:
                logger.warning(f"Erreur embedding: {response.status_code}")
                return None
                
        except Exception as e:
            logger.warning(f"Erreur embedding: {e}")
            return None
            
    def find_similar(self, query: str, candidates: List[str], top_k: int = 3) -> List[Tuple[str, float]]:
        """
        Trouve les textes les plus similaires à une requête.
        
        Args:
            query: Texte de recherche
            candidates: Liste des textes candidats
            top_k: Nombre de résultats à retourner
            
        Returns:
            Liste de (texte, score) triée par pertinence
        """
        query_embedding = self.embed_text(query)
        if not query_embedding:
            return []
            
        scored = []
        for candidate in candidates:
            candidate_embedding = self.embed_text(candidate)
            if candidate_embedding:
                # Cosine similarity
                import numpy as np
                similarity = np.dot(query_embedding, candidate_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(candidate_embedding)
                )
                scored.append((candidate, float(similarity)))
                
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
        
    def status(self) -> Dict:
        """Retourne le statut du pipeline NLU."""
        return {
            "spacy": self._spacy_nlp is not None,
            "lora": self._adapter_manager is not None and bool(self._adapter_manager._registry),
            "chatterbot": self._chatterbot is not None,
            "embeddings": self._embedding_model is not None,
            "lora_adapters": list(self._adapter_manager._registry.keys()) if self._adapter_manager else [],
        }
