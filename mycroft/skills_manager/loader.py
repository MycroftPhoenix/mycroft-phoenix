#!/usr/bin/env python3
"""Chargement dynamique des skills installes.

Le loader scanne le dossier skills (data_dir/skills) et charge chaque skill
qui suit le contrat Phoenix :
    - __init__.py expose `create_skill()` -> instance
    - l'instance expose `init(bus, subscribe=..., tts=...)`
    - et une methode de detection d'intent (convention `_detect_*_intent`)
    - et `_handle_utterance(message)` pour traiter l'utterance

Le routing se fait par priorite de detection : chaque skill est interroge
pour savoir s'il reconnait l'utterance ; le premier qui repond gagne.
"""

import importlib.util
import inspect
import logging
import sys
from pathlib import Path

LOG = logging.getLogger("mycroft.skills_manager.loader")


class LoadedSkill:
    """Skill charge en memoire avec ses capacites de detection."""

    def __init__(self, name, module, instance, detect, handle):
        self.name = name
        self.module = module
        self.instance = instance
        self._detect = detect
        self._handle = handle

    def detect_intent(self, text):
        try:
            return self._detect(text)
        except Exception as e:
            LOG.warning("Skill %s detect: %s", self.name, e)
            return None

    def handle(self, message):
        try:
            return self._handle(message)
        except Exception as e:
            LOG.warning("Skill %s handle: %s", self.name, e)
            return None

    @property
    def skill_id(self):
        return self.name


def _find_detect_method(instance):
    """Trouve la methode de detection d'intent par convention."""
    for name, fn in inspect.getmembers(instance, inspect.ismethod):
        if name.startswith("_detect_") and name.endswith("_intent"):
            return fn
    return None


def _find_handle_method(instance):
    for name, fn in inspect.getmembers(instance, inspect.ismethod):
        if name == "_handle_utterance":
            return fn
    return None


def load_skill(skills_dir: Path, name: str):
    """Charge un skill depuis skills_dir/<name>."""
    skill_dir = skills_dir / name
    init_file = skill_dir / "__init__.py"
    if not init_file.exists():
        return None

    spec = importlib.util.spec_from_file_location(
        f"phoenix_skill_{name}", init_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    create = getattr(module, "create_skill", None)
    if not callable(create):
        return None

    instance = create()
    detect = _find_detect_method(instance)
    handle = _find_handle_method(instance)
    if detect is None or handle is None:
        return None

    return LoadedSkill(name, module, instance, detect, handle)


def scan_skills(skills_dir: Path, hub, tts=None):
    """Charge tous les skills installes dans skills_dir."""
    loaded = []
    if not skills_dir.is_dir():
        return loaded
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        try:
            skill = load_skill(skills_dir, skill_dir.name)
            if skill is None:
                LOG.info("Skill ignore (pas de contrat Phoenix): %s",
                         skill_dir.name)
                continue
            # init() est appele avec les arguments supportes par le skill
            import inspect as _inspect
            sig = _inspect.signature(skill.instance.init)
            kwargs = {}
            if "subscribe" in sig.parameters:
                kwargs["subscribe"] = False
            if "tts" in sig.parameters:
                kwargs["tts"] = tts
            skill.instance.init(hub, **kwargs)
            loaded.append(skill)
            print(f"[Skills] charge: {skill.name}")
        except Exception as e:
            LOG.exception("Echec chargement skill %s: %s", skill_dir.name, e)
    return loaded


def first_match(skills, text):
    """Retourne le premier skill qui reconnait l'utterance (ou None)."""
    for skill in skills:
        intent = skill.detect_intent(text)
        if intent:
            return skill, intent
    return None, None
