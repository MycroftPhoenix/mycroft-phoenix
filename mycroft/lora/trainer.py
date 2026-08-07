"""
LoRA Trainer for Mycroft Phoenix.

Entraîne des adaptateurs LoRA sur des données d'intent/skill.
Optimisé pour CPU (pas de GPU requis).
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class LoRATrainer:
    """
    Entraîne des adaptateurs LoRA pour un modèle de language.
    
    Usage:
        trainer = LoRATrainer(model_id="HuggingFaceTB/SmolLM2-360M-Instruct")
        trainer.add_intent("greeting", ["Bonjour", "Salut", "Hello", "Hi"])
        trainer.add_intent("time", ["Quelle heure est-il", "Donne-moi l'heure"])
        trainer.train(output_dir="./adapters/greeting_fr")
    """
    
    def __init__(
        self,
        model_id: str = "HuggingFaceTB/SmolLM2-360M-Instruct",
        lora_r: int = 8,
        lora_alpha: int = 16,
        lora_dropout: float = 0.05,
        max_length: int = 128,
    ):
        """
        Args:
            model_id: Identifiant HuggingFace du modèle de base
            lora_r: Rang de la matrice LoRA (plus petit = plus léger)
            lora_alpha: Facteur d'échelle LoRA
            lora_dropout: Dropout LoRA
            max_length: Longueur max des séquences d'entraînement
        """
        self.model_id = model_id
        self.lora_r = lora_r
        self.lora_alpha = lora_alpha
        self.lora_dropout = lora_dropout
        self.max_length = max_length
        
        self._intents: Dict[str, List[str]] = {}
        self._model = None
        self._tokenizer = None
        
    def add_intent(self, name: str, utterances: List[str]):
        """
        Ajoute un intent avec ses utterances d'entraînement.
        
        Args:
            name: Nom de l'intent (ex: "greeting_fr")
            utterances: Liste des phrases d'entraînement
        """
        if name not in self._intents:
            self._intents[name] = []
        self._intents[name].extend(utterances)
        logger.info(f"Intent '{name}': {len(utterances)} utterances ajoutées")
        
    def load_data_from_kuzu(self, graph_query_fn, intent_name: str):
        """
        Charge les données d'entraînement depuis un graphe Kuzu.
        
        Args:
            graph_query_fn: Fonction qui exécute une requête Cypher
            intent_name: Nom de l'intent à charger
        """
        try:
            # Requête pour récupérer les utterances d'un intent
            query = f"""
            MATCH (i:Intent {{name: '{intent_name}'}})-[:HAS]->(u:Utterance)
            RETURN u.text AS text
            """
            results = graph_query_fn(query)
            
            if results:
                utterances = [r["text"] for r in results]
                self.add_intent(intent_name, utterances)
                logger.info(f"Chargé {len(utterances)} utterances pour '{intent_name}' depuis Kuzu")
            else:
                logger.warning(f"Aucune utterance trouvée pour '{intent_name}' dans Kuzu")
                
        except Exception as e:
            logger.error(f"Erreur chargement Kuzu pour '{intent_name}': {e}")
            
    def _prepare_dataset(self):
        """Prépare le dataset d'entraînement au format attendu par le modèle."""
        if not self._intents:
            raise ValueError("Aucun intent ajouté. Utilisez add_intent() d'abord.")
            
        import torch
        from datasets import Dataset
        
        # Format: "Intent: <name> / Response: <utterance>"
        texts = []
        for intent_name, utterances in self._intents.items():
            for utterance in utterances:
                texts.append({
                    "text": f"Intent: {intent_name} / Response: {utterance}"
                })
                
        dataset = Dataset.from_dict({"text": [t["text"] for t in texts]})
        
        def tokenize_fn(examples):
            return self._tokenizer(
                examples["text"],
                truncation=True,
                padding="max_length",
                max_length=self.max_length,
            )
            
        return dataset.map(tokenize_fn, batched=True)
        
    def train(
        self,
        output_dir: str,
        epochs: int = 3,
        batch_size: int = 1,
        learning_rate: float = 2e-4,
        logging_steps: int = 1,
    ) -> str:
        """
        Entraîne et sauvegarde l'adaptateur LoRA.
        
        Args:
            output_dir: Répertoire de sortie pour l'adaptateur
            epochs: Nombre d'époques d'entraînement
            batch_size: Taille du batch (1 pour CPU)
            learning_rate: Taux d'apprentissage
            logging_steps: Fréquence des logs
            
        Returns:
            Chemin vers l'adaptateur sauvegardé
        """
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments
        from peft import LoraConfig, get_peft_model
        
        logger.info(f"Chargement du modèle: {self.model_id}")
        
        # Charger le tokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token
            
        # Charger le modèle (CPU)
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            torch_dtype=torch.float32,
            device_map="cpu",
        )
        
        # Configurer LoRA
        lora_config = LoraConfig(
            r=self.lora_r,
            lora_alpha=self.lora_alpha,
            target_modules=["q_proj", "v_proj"],
            lora_dropout=self.lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
        )
        
        # Injecter LoRA
        self._model = get_peft_model(self._model, lora_config)
        self._model.print_trainable_parameters()
        
        # Préparer les données
        dataset = self._prepare_dataset()
        
        # Configurer l'entraînement
        training_args = TrainingArguments(
            output_dir=output_dir,
            per_device_train_batch_size=batch_size,
            num_train_epochs=epochs,
            learning_rate=learning_rate,
            logging_steps=logging_steps,
            save_strategy="no",  # On sauvegarde manuellement
            report_to="none",    # Pas de wandb/tensorboard
        )
        
        trainer = Trainer(
            model=self._model,
            args=training_args,
            train_dataset=dataset,
        )
        
        # Entraîner
        logger.info(f"Début de l'entraînement ({epochs} époques)")
        trainer.train()
        
        # Sauvegarder uniquement l'adaptateur
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        self._model.save_pretrained(str(output_path))
        
        # Sauvegarder les métadonnées
        metadata = {
            "model_id": self.model_id,
            "lora_r": self.lora_r,
            "lora_alpha": self.lora_alpha,
            "lora_dropout": self.lora_dropout,
            "intents": list(self._intents.keys()),
            "num_samples": sum(len(v) for v in self._intents.values()),
        }
        with open(output_path / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)
            
        logger.info(f"Adaptateur sauvegardé dans: {output_path}")
        
        # Nettoyer
        del self._model
        del self._tokenizer
        self._model = None
        self._tokenizer = None
        
        return str(output_path)
        
    def list_intents(self) -> Dict[str, int]:
        """Retourne la liste des intents avec le nombre d'utterances."""
        return {name: len(utterances) for name, utterances in self._intents.items()}
