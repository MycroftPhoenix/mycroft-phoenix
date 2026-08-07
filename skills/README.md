# Catalogue de skills Mycroft Phoenix

Ce dossier est le **catalogue officiel** de skills pour Mycroft Phoenix.
Chaque skill vit dans son propre sous-dossier et suit un contrat simple,
compatible avec le système d'installation local (remplace l'ancien MSM
de Mycroft basé sur `MycroftAI/mycroft-skills`).

## Structure d'un skill

```
skills/<nom_skill>/
├── skill.json          # métadonnées (nom, version, description, intents)
├── requirements.txt    # dépendances pip (optionnel)
└── __init__.py         # code du skill (contrat Phoenix)
```

### skill.json

```json
{
  "name": "mon_skill",
  "version": "1.0.0",
  "description": "Ce que fait le skill",
  "author": "Mycroft Phoenix",
  "license": "Apache-2.0",
  "category": "information",
  "intents": [
    {
      "name": "mon_intent",
      "examples": ["exemple de phrase"]
    }
  ]
}
```

### Contrat Phoenix (__init__.py)

```python
def create_skill():
    return MonSkill()


class MonSkill:
    def init(self, bus, subscribe=True, tts=None):
        self.bus = bus

    def _detect_mon_intent(self, text):
        """Retourne un nom d'intent si reconnu, sinon None."""
        ...

    def _handle_utterance(self, message):
        """Traite l'utterance et répond via self.bus."""
        ...
```

## Installation d'un skill

Trois interfaces, toutes branchées sur le catalogue GitHub public
(`MycroftPhoenix/mycroft-phoenix`, dossier `skills/`) — **aucune clé API
requise** car le dépôt est public.

### Terminal

```bash
python -m mycroft.skills_manager list
python -m mycroft.skills_manager install <nom>
python -m mycroft.skills_manager remove <nom>
python -m mycroft.skills_manager requirements <nom>
```

### Web local

```bash
python -m mycroft.skills_manager web
# -> http://127.0.0.1:8190
```

Interface minimaliste : liste les skills installés + disponibles,
boutons installer / désinstaller.

### Voix

Les skills installés sont chargés automatiquement au démarrage de la
boucle vocale (scan du dossier skills) et peuvent répondre directement
aux intents qu'ils reconnaissent.

## Où sont installés les skills ?

- Mode source : le dossier `skills/` du projet.
- Installation : `data_dir/skills/` (ex: `%LOCALAPPDATA%\Phoenix\skills`).
