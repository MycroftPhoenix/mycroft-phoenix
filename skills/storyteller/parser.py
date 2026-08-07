#!/usr/bin/env python3
"""
Parser d'histoires au format balises vocales.

Responsabilité unique : transformer le texte brut LLM en segments
structurés {speaker, text}, nettoyer les balises résiduelles.
"""

import logging
import re
from typing import List, Dict, Tuple, Optional

LOG = logging.getLogger("mycroft.storyteller.parser")


# Mapping par défaut : personnage -> voix (sid Supertonic)
DEFAULT_VOICES = {
    "narrateur": 0,    # femme
    "tim": 3,          # garçon/aigu
    "dragon": 6,       # grave
    "ogre": 9,
    "géant": 9,
    "géante": 6,
    "chevalier": 5,
    "roi": 5,
    "princesse": 0,
    "fée": 0,
    "reine": 0,
    "héros": 3,
    "héroïne": 0,
    "lapin": 3,
    "souris": 3,
    "animal": 3,
    "renard": 5,
    "ours": 5,
    "chat": 3,
    "chien": 3,
}


class StoryParser:
    """Parseur d'histoires au format ''personnage'' texte."""

    def __init__(self, voice_map: Dict[str, int] = None):
        self.voice_map = voice_map or DEFAULT_VOICES

    def parse(self, raw_text: str) -> Tuple[str, List[Dict]]:
        """
        Parse le texte brut LLM.

        Returns:
            tuple: (titre, segments)
                segments = [{"speaker": "...", "text": "..."}, ...]
        """
        lines = raw_text.strip().split("\n")
        title = "Une histoire"
        segments = []
        current_speaker = "narrateur"

        for line in lines:
            line = line.strip()
            if not line:
                continue
            line = line.replace("dragoon", "dragon")

            # Titre
            if line.upper().startswith("TITRE:") or line.startswith("TITRE"):
                title = line.split(":", 1)[-1].strip()
                continue

            # Balise en tête : ''personnage'' texte
            m = re.match(r"^''(.+?)''\s*(.*)$", line)
            if m:
                speaker = m.group(1).strip().lower()
                if "narrateur" in speaker:
                    speaker = "narrateur"
                current_speaker = speaker
                content = m.group(2).strip()
            else:
                content = line

            # Nettoyage : balises résiduelles ''...''
            content = re.sub(r"''.*?''", "", content).strip()

            # Nettoyage défensif : doublon "X dit ''X'' texte"
            if content:
                content = self._clean_redundant_speech(content, current_speaker)

            if content:
                segments.append({"speaker": current_speaker, "text": content})

        if not segments:
            segments = [{"speaker": "narrateur", "text": raw_text[:500]}]

        return title, segments

    def _clean_redundant_speech(self, content: str, speaker: str) -> str:
        """Retire le doublon typique du LLM : 'le dragon dit : Mon nom...'."""
        pattern = (
            r"^(?:le |la |un |une |l')?"
            + re.escape(speaker)
            + r"\s+(?:dit|a dit|répond|répondit|s'exclama|s'écria|s'écrie"
            + r"|demanda|demande|cria|dit-il)\b\s*(?:[:,\-\s]|$)"
        )
        return re.sub(pattern, "", content, count=1, flags=re.IGNORECASE).strip()

    def get_voice_sid(self, speaker: str) -> int:
        """Retourne le SID Supertonic pour un speaker."""
        name = speaker.strip().lower()
        for key, sid in self.voice_map.items():
            if key in name:
                return sid
        return self.voice_map.get("narrateur", 0)

    def segments_to_display_text(self, segments: List[Dict]) -> str:
        """Texte complet pour affichage chat (sans balises, avec sauts de ligne)."""
        return "\n".join(seg["text"] for seg in segments)