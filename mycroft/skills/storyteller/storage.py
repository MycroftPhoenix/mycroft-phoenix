#!/usr/bin/env python3
"""
Stockage des histoires (base Kuzu isolée).

Responsabilité unique : sauvegarder / charger / rechercher les histoires.
"""

import logging
import re
from typing import Optional, Dict, List

LOG = logging.getLogger("mycroft.storyteller.storage")


class StoryStorage:
    """Stockage des histoires dans base Kuzu isolée."""

    def __init__(self):
        self._db = None

    def _get_db(self):
        if self._db is None:
            from mycroft.lora.story_db import StoryDatabase
            self._db = StoryDatabase()
            self._db.initialize()
        return self._db

    def save(
        self,
        title: str,
        content: str,
        theme: str,
        characters: str,
        age: str,
    ) -> Optional[str]:
        """Sauvegarde une histoire complète."""
        db = self._get_db()
        sid = db.add(
            title=title,
            content=content,
            theme=theme,
            characters=characters,
            age_group=age,
            source="generated",
        )

        if sid and characters:
            for char_name in re.split(r'[,;]', characters):
                char_name = char_name.strip()
                if char_name and len(char_name) > 1:
                    db.add_character(sid, char_name)

        return sid

    def load(self, story_id: str) -> Optional[Dict]:
        """Charge une histoire par ID."""
        db = self._get_db()
        return db.get(story_id)

    def search(self, theme: str) -> List[Dict]:
        """Recherche des histoires par thème."""
        db = self._get_db()
        return db.search(theme)

    def by_theme(self, theme: str) -> List[Dict]:
        """Histoires par thème exact."""
        db = self._get_db()
        return db.by_theme(theme)

    def list_recent(self, limit: int = 10) -> List[Dict]:
        """Dernières histoires générées."""
        db = self._get_db()
        return db.list_recent(limit)