#!/usr/bin/env python3
"""Skill Storyteller pour Mycroft Phoenix.

Génère, mémorise et raconte des histoires aux enfants.
Base Kuzu complètement indépendante (phoenix_stories.kuzu)
— zéro contamination avec les données réelles (crises, convs).

Multi-voix Supertonic : narrateur (femme), personnages (garçon, grave, ...).
Format à balises : chaque ligne commence par ''personnage'' suivi du texte.
Les balises ne sont PAS prononcées, elles choisissent la voix.
L'histoire est synthétisée d'un bloc (concaténation des voix) et émise
en UN SEUL message web — fluidité totale.
"""

import logging
import os
import random
import re
from typing import Dict, List, Optional

LOG = logging.getLogger("mycroft.skill.storyteller")

from .examples_fr import FEW_SHOT_STORIES
from .generation import StoryGenerator, create_generator
from .parser import StoryParser
from .storage import StoryStorage
from mycroft.tts.base import TTSFactory


class StorytellerSkill:
    """Skill de génération et narration d'histoires.
    Base isolée — ne touche PAS à phoenix.kuzu / phoenix_personal.kuzu.
    """

    def __init__(self):
        self.bus = None
        self.lang = "fr"
        self.generator = None
        self.parser = StoryParser()
        self.storage = StoryStorage()
        self.tts = None
        self._conversation = []

    def init(self, bus, subscribe=True, tts=None):
        self.bus = bus
        self.tts = tts
        if self.tts is None:
            # Fallback: essaie de créer via factory
            try:
                self.tts = TTSFactory.create("supertonic", {})
            except Exception:
                pass

        # Générateur LLM (Ollama par défaut, keep_alive court)
        self.generator = create_generator(
            backend="ollama",
            ollama_url="http://localhost:11434",
            model="qwen2.5:1.5b",
            keep_alive="30s",  # court pour libérer RAM
            timeout=120,
        )

        if subscribe:
            self.bus.on("recognizer_loop:utterance", self._handle_utterance)
            self.bus.on("storyteller:generate", self._on_generate)
            self.bus.on("storyteller:continue", self._on_continue)
            self.bus.on("storyteller:recall", self._on_recall)

        LOG.info("StorytellerSkill initialisé (modulaire)")

    def _handle_utterance(self, message):
        utterances = message.data.get("utterances", [])
        if not utterances:
            return
        text = utterances[0].lower().strip()
        if not text:
            return

        intent = self._detect_story_intent(text)
        if not intent:
            return

        if self._is_negative_request(text):
            intent = "new"

        if intent == "recall":
            self._recall_story(text)
        elif intent == "continue":
            self._continue_story(text)
        else:
            self._start_new_story(text, intent)

    def _detect_story_intent(self, text: str) -> Optional[str]:
        norm = text.replace("'", " ").replace("’", " ").lower()
        story_keywords = {
            "new": [
                "raconte moi une histoire", "raconte moi un conte",
                "invente une histoire", "imagine une histoire",
                "je veux une histoire", "je voudrais une histoire",
                "raconte nous une histoire", "tell me a story",
                "make up a story",
            ],
            "recall": [
                "l histoire de", "l histoire du", "l histoire des",
                "l histoire que", "souviens toi", "parle moi de",
                "tell me about", "story about", "remember",
                "raconte l histoire", "quelle histoire",
            ],
            "continue": [
                "continue", "suite", "après", "et après", "ensuite",
                "next", "continue the story", "what happens next",
            ],
            "new_broad": [
                "une histoire de", "raconte moi", "raconte nous",
                "raconter", "histoire", "conte", "story",
            ],
        }
        for intent, keywords in story_keywords.items():
            for kw in keywords:
                if kw in norm:
                    return intent if intent != "new_broad" else "new"
        return None

    def _is_negative_request(self, text: str) -> bool:
        norm = text.replace("'", " ").replace("’", " ").lower()
        negation = ["pas", "non", "une autre", "pas celle", "autre",
                    "différent", "different", "j en veux pas",
                    "pas l histoire"]
        return any(n in norm for n in negation)

    def _start_new_story(self, text: str, intent: str):
        theme, characters, age = self._parse_request(text)

        LOG.info("Generating NEW story: theme=%s characters=%s age=%s", theme, characters, age)
        self.speak("Laisse-moi inventer une histoire...")

        story_text = self.generator.generate(theme, characters, age, examples=FEW_SHOT_STORIES)
        if not story_text:
            self.speak("Je n'ai pas réussi à inventer une histoire aujourd'hui. Réessaie plus tard.")
            return

        title, segments = self.parser.parse(story_text)
        story_id = self.storage.save(title, story_text, theme, characters, age)

        self._conversation = segments
        self._tell_story_segments(segments)

    def _continue_story(self, text: str):
        if not self._conversation:
            self.speak("Je n'ai pas d'histoire en cours. Demande-moi de t'en raconter une nouvelle !")
            return

        story_so_far = "\n".join(
            f"''{seg.get('speaker', 'narrateur')}'' {seg.get('text', '')}"
            for seg in self._conversation[-5:]
        )

        chars = [s["speaker"] for s in self._conversation if s["speaker"] != "narrateur"]
        story_text = self.generator.continue_story(story_so_far, chars)
        if not story_text:
            return

        _, segments = self.parser.parse(story_text)
        self._conversation.extend(segments)
        self._tell_story_segments(segments)

    def _recall_story(self, text: str):
        theme, characters, _ = self._parse_request(text)
        stories = self.storage.search(theme)
        if not stories:
            self.speak(f"Je ne connais pas d'histoire sur {theme}. Tu veux que j'en invente une ?")
            return

        story = self.storage.load(stories[0]["id"])
        if story:
            self.speak(f"Ah oui ! {story['title']}")
            _, segments = self.parser.parse(story["content"])
            self._tell_story_segments(segments)

    def _parse_request(self, text: str) -> tuple:
        text_lower = text.lower()
        age = random.choice(["3", "4", "5", "6", "7"])

        themes = [
            "star wars", "starwars", "la guerre des étoiles",
            "super-héros", "super héros", "superhero",
            "dragon", "princesse", "chevalier", "fée", "magie",
            "animal", "forêt", "aventure", "amitié", "famille",
            "école", "rêve", "étoile", "lune", "océan",
            "chat", "chien", "lapin", "ours", "renard",
            "sirène", "pirate", "robot", "espace", "planète",
            "princess", "knight", "fairy", "magic",
            "animal", "forest", "adventure", "friendship", "family",
            "space", "robot", "pirate", "mermaid",
        ]
        theme = "aventure"
        for t in themes:
            if t in text_lower:
                theme = t
                break

        characters = ""
        char_match = re.search(r"(?:avec|et|personnage[s]?[:\s]+)(.+)", text_lower)
        if char_match:
            characters = char_match.group(1).strip()[:100]

        return theme, characters, age

    def _tell_story_segments(self, segments: List[Dict]):
        """Synthétise chaque segment avec la voix du personnage, concatène
        en un seul flux audio fluide, et émet UN message web avec le texte
        complet (sans balises) + l'audio pré-synthétisé.

        L'affichage web et l'audio sont parfaitement synchronisés et
        sans fragmentation.
        """
        if self.tts is None:
            LOG.warning("TTS non disponible, fallback texte seul")
            display = "\n".join(seg["text"] for seg in segments)
            self.speak(display)
            return

        display_lines = []
        audio_chunks = []

        for seg in segments:
            speaker = seg.get("speaker", "narrateur")
            text = seg.get("text", "")
            if not text:
                continue
            display_lines.append(text)

            # Synthèse avec la voix du personnage
            sid = self.parser.get_voice_sid(speaker)
            if hasattr(self.tts, "synthesize_with_sid"):
                wav = self.tts.synthesize_with_sid(text, sid)
            else:
                wav = self.tts.synthesize(text)
            if wav:
                audio_chunks.append(wav)

        display = "\n".join(display_lines)

        if audio_chunks:
            try:
                if hasattr(self.tts, "concat_wavs"):
                    full_audio = self.tts.concat_wavs(audio_chunks, pause_ms=180)
                else:
                    from mycroft.audio.mixer import AudioMixer
                    mixer = AudioMixer()
                    full_audio = mixer.concat_segments(audio_chunks, pause_ms=180)

                # Un seul message : texte complet + audio prêt à jouer
                self.speak(display, meta={"audio": full_audio})
                return
            except Exception as e:
                LOG.error("Concaténation audio échouée, fallback segmenté: %s", e)

        # Fallback : un seul message texte
        self.speak(display)

    def _on_generate(self, message):
        data = message.data or {}
        self._start_new_story(
            data.get("text", "raconte moi une histoire"),
            data.get("intent", "new"),
        )

    def _on_continue(self, message):
        self._continue_story("")

    def _on_recall(self, message):
        self._recall_story(message.data.get("text", "histoire"))

    def speak(self, utterance, meta=None):
        if self.bus:
            msg = {"utterance": utterance, "lang": self.lang}
            if meta:
                msg["meta"] = meta
            self.bus.emit("phoenix.speak", msg)


def create_skill():
    return StorytellerSkill()