#!/usr/bin/env python3
"""Service d'intents padatious pour Mycroft Phoenix.

Permet aux skills (Phoenix ou compat Mycroft) d'utiliser les fichiers
`.intent` / `.entity` via le MEME protocole bus que Mycroft original
(`padatious:register_intent`, `padatious:register_entity`), sans avoir
besoin du moteur d'intents legacy.

Stabilite / inertie (exigence : connecter padatious SANS skills legacy
et sans rien casser) :
  - Si `padatious` (padatious-phoenix) n'est pas installe, le service se
    desactive proprement (un seul warning) et TOUTES les methodes deviennent
    des no-op : le chargement des skills Phoenix est inchange.
  - Sans intent enregistre, `match()` retourne None : le routage des skills
    Phoenix existants est strictement identique a avant.
  - Seuil de confiance par defaut a 0.8 (l'equivalent du match "medium" de
    Mycroft original) : seuls les intents `.intent` suffisamment certains
    routent vers le skill. Les phrases hors-intents retombent sur les skills
    Phoenix et le pipeline (comportement inchange). Configurable via
    `config["padatious"]["conf_threshold"]`.
  - Chaque appel est protege (try/except) : aucun fichier `.intent` mal forme
    ne peut faire planter le runtime.
  - Entrainement par defaut en `single_thread` (stable sous Windows).
"""

import logging
from pathlib import Path

LOG = logging.getLogger("mycroft.skills_manager.padatious_service")

DEFAULT_CACHE_DIR = Path.home() / ".mycroft-phoenix" / "padatious" / "cache"
DEFAULT_CONF_THRESHOLD = 0.8


class PadatiousService:
    """Gestionnaire d'intents `.intent` (padatious) en mode Phoenix.

    Le service est inerte par defaut : il ne fait quelque chose que si des
    fichiers `.intent` / `.entity` sont enregistres via le bus, et uniquement
    si `padatious` est importable dans l'environnement.
    """

    def __init__(self, cache_dir=None, single_thread=True, conf_threshold=None):
        self.hub = None
        self.enabled = False
        self.container = None
        self.single_thread = single_thread
        self.conf_threshold = (conf_threshold if conf_threshold is not None
                               else DEFAULT_CONF_THRESHOLD)
        self._registered = set()
        self._dirty = False
        self._trained = False

        try:
            from padatious import IntentContainer
        except Exception as e:
            LOG.warning("Padatious indisponible (%s): les fichiers .intent "
                        "des skills seront ignores.", e)
            return

        cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        try:
            self.container = IntentContainer(str(cache_dir))
            self.enabled = True
        except Exception as e:
            LOG.warning("Padatious inutilisable (cache %s): %s", cache_dir, e)

    # ------------------------------------------------------------------ #
    # Liaison au bus Phoenix
    # ------------------------------------------------------------------ #

    def bind(self, hub):
        """S'abonne aux evenements `padatious:*` sur le hub (protocole Mycroft)."""
        self.hub = hub
        if not self.enabled:
            return
        try:
            hub.on("padatious:register_intent", self._on_register_intent)
            hub.on("padatious:register_entity", self._on_register_entity)
            hub.on("detach_intent", self._on_detach_intent)
            hub.on("detach_skill", self._on_detach_skill)
        except Exception as e:
            LOG.warning("Liaison padatious au bus impossible: %s", e)

    @staticmethod
    def _data(message):
        return getattr(message, "data", message) or {}

    def _on_register_intent(self, message):
        data = self._data(message)
        self.register_intent(data.get("name"), data.get("file_name"))

    def _on_register_entity(self, message):
        data = self._data(message)
        self.register_entity(data.get("name"), data.get("file_name"))

    def _on_detach_intent(self, message):
        data = self._data(message)
        self.remove_intent(data.get("intent_name"))

    def _on_detach_skill(self, message):
        data = self._data(message)
        skill_id = data.get("skill_id")
        if not skill_id:
            return
        for name in list(self._registered):
            if name.startswith(skill_id):
                self.remove_intent(name)

    # ------------------------------------------------------------------ #
    # API publique
    # ------------------------------------------------------------------ #

    def register_intent(self, name, file_name):
        """Enregistre un fichier `.intent` (format Mycroft)."""
        if not self.enabled or not name or not file_name:
            return
        try:
            self.container.load_intent(name, file_name)
            self._registered.add(name)
            self._dirty = True
            if self._trained:
                self.train()
        except Exception as e:
            LOG.warning("Intent '%s' (%s) non charge: %s", name, file_name, e)

    def register_entity(self, name, file_name):
        """Enregistre un fichier `.entity` (format Mycroft)."""
        if not self.enabled or not name or not file_name:
            return
        try:
            self.container.load_entity(name, file_name)
            self._dirty = True
            if self._trained:
                self.train()
        except Exception as e:
            LOG.warning("Entity '%s' (%s) non chargee: %s", name, file_name, e)

    def remove_intent(self, name):
        """Retire un intent enregistre."""
        if not self.enabled or not name:
            return
        if name in self._registered:
            try:
                self.container.remove_intent(name)
            except Exception as e:
                LOG.warning("Intent '%s' non retire: %s", name, e)
            self._registered.discard(name)

    def train(self):
        """Entraine les intents enregistres (no-op s'il n'y a rien)."""
        if not self.enabled or not self._dirty:
            return
        try:
            self.container.train(single_thread=self.single_thread)
            self._dirty = False
            self._trained = True
        except Exception as e:
            LOG.warning("Entrainement padatious echoue: %s", e)

    def calc_intent(self, text):
        """Calcule l'intent padatious d'une utterance (None si rien)."""
        if not self.enabled or not text:
            return None
        try:
            return self.container.calc_intent(text)
        except Exception:
            return None

    def match(self, text):
        """Retourne l'intent padatious si conf >= seuil, sinon None."""
        intent = self.calc_intent(text)
        if intent is not None and getattr(intent, "conf", 0.0) >= self.conf_threshold:
            return intent
        return None

    def match_skill(self, text, skills):
        """Route une utterance vers un skill par nom (prefixe de l'intent).

        Le nom d'intent padatious est `<skill_id>:<intent>` -> le skill_id
        designe le dossier du skill charge par le loader.

        Retourne (skill, match) ou (None, match) si le skill n'est pas charge.
        """
        match = self.match(text)
        if match is None:
            return None, None
        skill_id = match.name.split(":")[0]
        for skill in skills:
            if getattr(skill, "name", None) == skill_id:
                return skill, match
        return None, match
