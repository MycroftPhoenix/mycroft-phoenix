"""
LoRA Adapter Manager for Mycroft Phoenix.

Gère le chargement et l'utilisation des adaptateurs LoRA.
Charge dynamiquement les adaptateurs nécessaires depuis le disque.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AdapterManager:
    """
    Gestionnaire d'adaptateurs LoRA pour Phoenix.
    
    Charge les adaptateurs depuis un répertoire et les associe aux intents.
    Permet de charger/décharger dynamiquement les adaptateurs nécessaires.
    
    Usage:
        manager = AdapterManager("./adapters")
        manager.scan_adapters()
        
        # Charger un adaptateur spécifique
        model, tokenizer = manager.load_adapter("greeting_fr")
        
        # Ou charger par intent
        model, tokenizer = manager.load_for_intent("Bonjour!")
    """
    
    def __init__(self, adapters_dir: str = "./adapters"):
        """
        Args:
            adapters_dir: Répertoire contenant les adaptateurs LoRA
        """
        self.adapters_dir = Path(adapters_dir)
        self.adapters_dir.mkdir(parents=True, exist_ok=True)
        
        # Registre des adaptateurs: {adapter_name: {path, intents, metadata}}
        self._registry: Dict[str, dict] = {}
        
        # Modèle de base chargé (singleton)
        self._base_model = None
        self._base_model_id = None
        self._tokenizer = None
        
    def scan_adapters(self) -> List[str]:
        """
        Scanne le répertoire des adaptateurs et charge le registre.
        
        Returns:
            Liste des noms d'adaptateurs trouvés
        """
        self._registry.clear()
        
        for adapter_dir in self.adapters_dir.iterdir():
            if adapter_dir.is_dir():
                metadata_file = adapter_dir / "metadata.json"
                if metadata_file.exists():
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                    
                    self._registry[adapter_dir.name] = {
                        "path": str(adapter_dir),
                        "intents": metadata.get("intents", []),
                        "model_id": metadata.get("model_id", ""),
                        "num_samples": metadata.get("num_samples", 0),
                    }
                    
        adapter_names = list(self._registry.keys())
        logger.info(f"Adaptateurs trouvés: {adapter_names}")
        return adapter_names
        
    def get_adapter_for_intent(self, intent_name: str) -> Optional[str]:
        """
        Trouve l'adaptateur correspondant à un intent.
        
        Args:
            intent_name: Nom de l'intent
            
        Returns:
            Nom de l'adaptateur ou None
        """
        for adapter_name, info in self._registry.items():
            if intent_name in info["intents"]:
                return adapter_name
        return None
        
    def list_intents(self) -> Dict[str, str]:
        """
        Retourne la correspondance intent → adaptateur.
        
        Returns:
            Dict[intent_name, adapter_name]
        """
        result = {}
        for adapter_name, info in self._registry.items():
            for intent in info["intents"]:
                result[intent] = adapter_name
        return result
        
    def _load_base_model(self, model_id: str):
        """Charge le modèle de base (une seule fois)."""
        if self._base_model_id == model_id:
            return
            
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        
        logger.info(f"Chargement du modèle de base: {model_id}")
        
        self._tokenizer = AutoTokenizer.from_pretrained(model_id)
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token
            
        self._base_model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype=torch.float32,
            device_map="cpu",
        )
        self._base_model_id = model_id
        
    def load_adapter(self, adapter_name: str) -> Tuple[object, object]:
        """
        Charge un adaptateur LoRA spécifique.
        
        Args:
            adapter_name: Nom de l'adaptateur à charger
            
        Returns:
            Tuple (model, tokenizer)
        """
        if adapter_name not in self._registry:
            raise ValueError(f"Adaptateur '{adapter_name}' non trouvé")
            
        import torch
        from peft import PeftModel
        
        info = self._registry[adapter_name]
        
        # Charger le modèle de base si nécessaire
        self._load_base_model(info["model_id"])
        
        # Charger l'adaptateur
        logger.info(f"Chargement de l'adaptateur: {adapter_name}")
        model = PeftModel.from_pretrained(
            self._base_model,
            info["path"],
        )
        
        return model, self._tokenizer
        
    def load_for_intent(self, text: str) -> Tuple[object, object, Optional[str]]:
        """
        Charge l'adaptateur le plus pertinent pour un texte donné.
        
        Args:
            text: Texte de l'utilisateur
            
        Returns:
            Tuple (model, tokenizer, matched_intent)
        """
        # Matching simple par mots-clés (peut être amélioré avec all-minilm)
        text_lower = text.lower()
        
        for intent_name, adapter_name in self.list_intents().items():
            if intent_name.replace("_", " ") in text_lower:
                model, tokenizer = self.load_adapter(adapter_name)
                return model, tokenizer, intent_name
                
        # Par défaut, charger le premier adaptateur disponible
        if self._registry:
            first_adapter = list(self._registry.keys())[0]
            model, tokenizer = self.load_adapter(first_adapter)
            return model, tokenizer, None
            
        raise ValueError("Aucun adaptateur disponible")
        
    def unload_all(self):
        """Décharge tous les modèles de la mémoire."""
        import gc
        import torch
        
        if self._base_model is not None:
            del self._base_model
            self._base_model = None
            self._tokenizer = None
            self._base_model_id = None
            gc.collect()
            logger.info("Modèles déchargés de la mémoire")
            
    def generate(
        self,
        text: str,
        max_new_tokens: int = 50,
        temperature: float = 0.7,
    ) -> Tuple[str, Optional[str]]:
        """
        Génère une réponse pour un texte donné.
        
        Args:
            text: Texte de l'utilisateur
            max_new_tokens: Nombre max de tokens à générer
            temperature: Température de génération
            
        Returns:
            Tuple (response_text, matched_intent)
        """
        import torch
        
        # Charger l'adaptateur approprié
        model, tokenizer, intent = self.load_for_intent(text)
        
        # Tokeniser l'entrée
        inputs = tokenizer(text, return_tensors="pt")
        
        # Générer
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                do_sample=temperature > 0,
                pad_token_id=tokenizer.eos_token_id,
            )
            
        # Décoder la réponse
        response = tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # Nettoyer (enlever l'entrée de la réponse)
        if response.startswith(text):
            response = response[len(text):].strip()
            
        return response, intent
