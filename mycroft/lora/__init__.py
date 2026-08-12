"""LoRA adapter training and management for Mycroft Phoenix."""

# Imports paresseux - charger uniquement quand necessaire
# from .trainer import LoRATrainer
# from .adapter_manager import AdapterManager
# from .nlu_pipeline import NLUPipeline, NLUConfig
# from .chatterbot_kuzu import IntentMatcher
# from .chatterbot_ladybug import LadybugStorageAdapter, LadybugChatter
# from .ai_backend import AIBackends, ai_backends_from_config
# from .speech import TTSBackend, STTBackend, build_tts, build_stt, speech_from_config
# from .mycroft_corpus import import_mycroft_skills

__all__ = [
    "LoRATrainer", "AdapterManager", "NLUPipeline", "NLUConfig", "IntentMatcher",
    "LadybugStorageAdapter", "LadybugChatter", "AIBackends", "ai_backends_from_config",
    "TTSBackend", "STTBackend", "build_tts", "build_stt", "speech_from_config",
]
