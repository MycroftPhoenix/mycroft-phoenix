"""Adaptation LoRA (Low-Rank Adaptation) pour les modèles d'IA de Mycroft-Phoenix.

Entraînement d'adaptateurs LoRA et gestion de l'inférence sur modèles
locaux. Concerne uniquement le fine-tuning d'IA — pas la mémoire ni
les capacités du système (voir mycroft.memory, mycroft.capabilities,
mycroft.knowledge).
"""

# Imports paresseux - charger uniquement quand necessaire
# from .trainer import LoRATrainer
# from .adapter_manager import AdapterManager
# from .ai_backend import AIBackends, ai_backends_from_config

__all__ = [
    "LoRATrainer", "AdapterManager", "AIBackends", "ai_backends_from_config",
]
