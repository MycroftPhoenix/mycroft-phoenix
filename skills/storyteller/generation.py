#!/usr/bin/env python3
"""
Génération d'histoires via LLM (Ollama / llama-cpp / API).

Responsabilité unique : demander au LLM une histoire selon prompt,
retourner le texte brut.
"""

import logging
import random
import requests
from typing import Optional, Dict, List

LOG = logging.getLogger("mycroft.storyteller.generation")

# Templates de prompts (format balises vocales)
PROMPT_GENERATE = """Tu es un conteur d'histoires pour enfants.
Génère une histoire courte en {language} pour un enfant de {age} ans.
{context}
Thème: {theme}
Personnages: {characters}

{examples}
Format de réponse STRICT (sans rien d'autre):
TITRE: <titre de l'histoire>

''narrateur'' <texte du narrateur>
''{char1}'' <dialogue du personnage 1>
''narrateur'' <suite>
''{char2}'' <dialogue du personnage 2>
...

IMPORTANT:
- Chaque ligne COMMENCE par une balise vocale entre guillemets doubles apostrophes :
  ''narrateur'' (voix femme) ou ''nom_du_personnage'' (sa propre voix).
- La balise est UNIQUEMENT un marqueur de voix : ne l'écris JAMAIS dans le texte parlé.
- Ne répète pas le nom du personnage juste après sa balise.
  MAUVAIS: ''dragon'' le dragon dit ''dragon'' Mon nom est Merlin
  BON: ''dragon'' Mon nom est Merlin et je suis le dragon enchanteur le plus beau du monde !
- Histoire courte (5-10 phrases), vocabulaire simple, fin heureuse.
- Invente une NOUVELLE histoire sur le thème demandé, ne copie pas l'exemple.
"""

PROMPT_CONTINUE = """Continue l'histoire suivante en {language} :
{story_so_far}

Format STRICT: chaque ligne commence par ''narrateur'' ou ''{characters}''.
La balise est un marqueur de voix, ne l'écris pas dans le texte parlé.
5-10 phrases, fin heureuse.
"""


class StoryGenerator:
    """Générateur d'histoires via LLM."""

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model: str = "qwen2.5:1.5b",
        keep_alive: str = "30s",  # court pour libérer RAM
        timeout: int = 120,
    ):
        self.ollama_url = ollama_url
        self.model = model
        self.keep_alive = keep_alive
        self.timeout = timeout

    def generate(
        self,
        theme: str,
        characters: str,
        age: str,
        context: str = "",
        examples: str = "",
    ) -> Optional[str]:
        """Génère une nouvelle histoire complète."""
        char_section = f"Personnages: {characters}" if characters else "Personnages: un personnage attachant"

        prompt = PROMPT_GENERATE.format(
            language="français",
            age=age,
            context=context,
            theme=theme,
            characters=char_section,
            examples=examples,
            char1="narrateur",
            char2=characters.split(",")[0].strip() if characters and "," in characters else "héros",
        )
        return self._query_llm(prompt)

    def continue_story(
        self,
        story_so_far: str,
        characters: List[str],
    ) -> Optional[str]:
        """Continue une histoire existante."""
        prompt = PROMPT_CONTINUE.format(
            language="français",
            story_so_far=story_so_far,
            characters=", ".join(characters),
        )
        return self._query_llm(prompt)

    def _query_llm(self, prompt: str) -> Optional[str]:
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": self.keep_alive,
                    "options": {
                        "temperature": 0.8,
                        "num_predict": 400,
                    },
                },
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return resp.json().get("response", "").strip()
            LOG.error("Ollama error %s: %s", resp.status_code, resp.text)
        except Exception as e:
            LOG.error("Erreur LLM: %s", e)
        return None


# Factory pour backends alternatifs
def create_generator(backend: str = "ollama", **kwargs) -> StoryGenerator:
    if backend == "ollama":
        return StoryGenerator(**kwargs)
    # TODO: llama-cpp, openai, anthropic
    raise ValueError(f"Backend génération non supporté: {backend}")