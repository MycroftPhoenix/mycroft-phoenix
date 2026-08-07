#!/usr/bin/env python3
"""Gestion des skills Mycroft Phoenix.

Remplace le MSM original (MycroftAI/mycroft-skills + backend mycroft.ai)
par un systeme local branche sur le catalogue GitHub du projet.

- manager.py : coeur (catalogue GitHub public, install/remove)
- cli.py     : version terminal (list / install / remove / requirements / web)
- web.py     : serveur web local minimaliste (page + API JSON)
- loader.py  : chargement dynamique des skills dans voice_loop

Le catalogue est le depot dedie MycroftPhoenix/mycroft-phoenix-skills
(public, donc aucune cle API requise). Le coeur mycroft-phoenix n'a
AUCUNE dependance vers les skills : en leur absence, il fonctionne
normalement (routing sans skills).
"""

from .manager import SkillsManager
from .loader import scan_skills, load_skill, first_match

__all__ = ["SkillsManager", "scan_skills", "load_skill", "first_match"]
