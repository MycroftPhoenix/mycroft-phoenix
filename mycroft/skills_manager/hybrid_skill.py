#!/usr/bin/env python3
"""Base hybride de skill pour Mycroft Phoenix (mode Phoenix).

Un skill HYBRIDE tourne sur DEUX moteurs :
  - Mycroft Phoenix (`mycroft.skills_manager.loader`) : contrat
    `create_skill()` + `init(bus, subscribe, tts)` + `_detect_*_intent`
    + `_handle_utterance`, reponses via `phoenix.speak` / TTS.
  - Mycroft original et ses forks (`mycroft.skills`): le skill herite de
    `FallbackSkill` et s'enregistre comme fallback dans `initialize()`.

Le skill choisit sa base par import protege :
    try:
        from mycroft.skills.core import FallbackSkill as _Base
    except Exception:
        from mycroft.skills_manager.hybrid_skill import HybridSkill as _Base

Cette classe est la base utilisee quand le moteur original n'est PAS
disponible (cas Phoenix). Elle fournit aussi la surface minimale du style
Mycroft original (bind, initialize, speak, speak_dialog, settings...)
pour que les memes skills restent exploitables par du code ecrit pour
Mycroft (ex. futur moteur de compat, tests de l'engin original).

Aucune dependance externe (stdlib uniquement).
"""

import logging

LOG = logging.getLogger("mycroft.skills_manager.hybrid_skill")


class HybridSkill:
    """Base mode Phoenix : contrat Phoenix + surface de compat Mycroft."""

    reload_skill = True
    FALLBACK_PRIORITY = 70

    def __init__(self, name=None, bus=None, use_settings=True):
        self.name = name or self.__class__.__name__
        self.skill_id = ""
        self.resting_name = None
        self.settings = {}
        self.settings_write_path = None
        self.settings_meta = None
        self._bus = None
        self._tts = None
        if bus is not None:
            self.bind(bus)

    @property
    def bus(self):
        return self._bus

    # ------------------------------------------------------------------ #
    # Contrat Phoenix
    # ------------------------------------------------------------------ #

    def init(self, bus, subscribe=True, tts=None):
        """Point d'entree Phoenix. Le loader passe subscribe=False."""
        self._bus = bus
        self._tts = tts
        if subscribe:
            try:
                self.bus.on("recognizer_loop:utterance", self._handle_utterance)
            except Exception as e:
                LOG.warning("Abonnement bus impossible: %s", e)

    def _speak(self, utterance):
        """Reponse vocale Phoenix (TTS direct ou bus phoenix.speak)."""
        if self._tts is not None and callable(getattr(self._tts, "speak", None)):
            try:
                self._tts.speak(utterance)
                return
            except Exception:
                pass
        try:
            self.bus.emit("phoenix.speak", {"utterance": utterance})
        except Exception as e:
            LOG.warning("Emission phoenix.speak impossible: %s", e)

    # ------------------------------------------------------------------ #
    # Surface de compatibilite style Mycroft original
    # (no-op par defaut : ces appels ne concernent que le moteur original)
    # ------------------------------------------------------------------ #

    def bind(self, bus):
        """Le moteur original appelle bind(bus) apres create_skill()."""
        self._bus = bus

    def initialize(self):
        """Point d'entree original (apres _register_decorated)."""
        pass

    def load_data_files(self):
        pass

    def _register_decorated(self):
        pass

    def register_fallback(self, handler, priority=None):
        pass

    def remove_instance_handlers(self):
        pass

    def make_active(self):
        pass

    def speak(self, utterance, *args, **kwargs):
        return self._speak(utterance)

    def speak_dialog(self, key, data=None, *args, **kwargs):
        return self._speak(key)

    # ------------------------------------------------------------------ #
    # Intents fichiers `.intent` / `.entity` (padatious)
    # ------------------------------------------------------------------ #
    # Le MEME protocole bus que Mycroft original est emis sur le hub local
    # (zero reseau) : un service padatious abonne (PadatiousService) les
    # consomme. Si aucun service n'est abonne ou si padatious est absent,
    # l'emission est simplement ignoree -> inertie garantie.

    def register_intent_file(self, name, file_name):
        """Enregistre un intent a partir d'un fichier `.intent` (padatious)."""
        self._emit_intent_event("padatious:register_intent", name, file_name)

    def register_entity_file(self, name, file_name):
        """Enregistre une entite a partir d'un fichier `.entity` (padatious)."""
        self._emit_intent_event("padatious:register_entity", name, file_name)

    def remove_intent(self, intent_name):
        """Desenregistre un intent padatious."""
        self._emit_intent_event("detach_intent", intent_name)

    def detach_from_skill(self):
        """Desenregistre tous les intents de ce skill."""
        skill_id = self.skill_id or self.name
        if self._bus is None:
            return
        try:
            self._bus.emit("detach_skill", {"skill_id": skill_id})
        except Exception as e:
            LOG.warning("Emission detach_skill impossible: %s", e)

    def _emit_intent_event(self, event, name, file_name=None):
        """Emet un evenement d'intent sur le hub local (inert si pas de hub)."""
        if self._bus is None:
            LOG.debug("%s ignore (pas de bus): %s", event, name)
            return
        data = {"name": name}
        if file_name is not None:
            data["file_name"] = file_name
        try:
            self._bus.emit(event, data)
        except Exception as e:
            LOG.warning("Emission %s impossible: %s", event, e)

    def get_intro_message(self):
        return None

    def default_shutdown(self):
        self.remove_instance_handlers()
