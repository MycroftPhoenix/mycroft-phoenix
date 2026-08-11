"""LoRA adapter training and management for Mycroft Phoenix."""

# Imports paresseux - charger uniquement quand necessaire
# from .trainer import LoRATrainer
# from .adapter_manager import AdapterManager
# from .nlu_pipeline import NLUPipeline, NLUConfig
# from .chatterbot_kuzu import IntentMatcher
# from .chatterbot_ladybug import LadybugStorageAdapter, LadybugChatter
# from .mycroft_corpus import import_mycroft_skills

__all__ = [
    "LoRATrainer", "AdapterManager", "NLUPipeline", "NLUConfig", "IntentMatcher",
    "LadybugStorageAdapter", "LadybugChatter",
]
