# Mycroft-Phoenix — Graphe Complet des Modules

> **FICHIER OBLIGATOIRE** : Toute session OpenCode travaillant sur ce projet
> doit lire CE FICHIER en premier avant toute modification du code.
> Dernière mise à jour : 2026-08-16

---

## 1. Architecture Vue d'Ensemble

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          MYCROFT-PHOENIX                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │              VOICE LOOP (Orchestrateur Principal)                 │ │
│  │  Fichier : mycroft/audio/voice_loop.py (872 lignes)              │ │
│  │  Rôle : Boucle STT → Hub → Pipeline → TTS                        │ │
│  │  Initialisation : TOUS les composants du système                  │ │
│  └──────────────┬────────────────────────────────────────────────────┘ │
│                  │                                                      │
│         ┌───────┴───────┐                                              │
│         ▼               ▼                                              │
│  ┌──────────────┐  ┌────────────────────────────────────────────────┐ │
│  │  STT (Vosk)  │  │           HUB (Message Bus Interne)            │ │
│  │  Fichier :   │  │  Fichiers :                                     │ │
│  │  mycroft/    │  │  - mycroft/hub/hub.py (221 lignes)             │ │
│  │  audio/      │  │  - mycroft/messagebus/internal.py (187 lignes) │ │
│  │  stt/        │  │  - mycroft/hub/adapters.py (50 lignes)         │ │
│  │  vosk_stt.py │  │  Rôle : Pub/sub interne, zéro réseau           │ │
│  └──────────────┘  └────────────────────────────────────────────────┘ │
│                                    │                                    │
│                  ┌─────────────────┼─────────────────┐                 │
│                  ▼                 ▼                  ▼                 │
│  ┌─────────────────────┐ ┌───────────────┐ ┌───────────────────────┐ │
│  │  PIPELINE (Cerveau) │ │    SKILLS     │ │    WEB SERVER         │ │
│  │  Fichier :          │ │  Fichiers :   │ │  Fichier :            │ │
│  │  mycroft/           │ │  skills/      │ │  mycroft/web/         │ │
│  │  pipeline.py        │ │  skills_mgr/  │ │  server.py            │ │
│  │  (1412 lignes)      │ │  hybrid_skill │ │  (282 lignes)         │ │
│  └──────────┬──────────┘ └───────────────┘ └───────────────────────┘ │
│             │                                                          │
│             ▼                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐│
│  │                       MEMORY SYSTEM                                ││
│  │  Fichiers : mycroft/memory/                                        ││
│  │  - kuzu_manager.py    (Kuzu graph DB)                             ││
│  │  - kuzu_resilience.py (WriteQueue, snapshots)                     ││
│  │  - azelia_knowledge.py (Story knowledge)                          ││
│  │  - story_db.py        (Story database)                            ││
│  └───────────────────────────────────────────────────────────────────┘│
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐│
│  │                       TTS SYSTEM                                   ││
│  │  Fichiers : mycroft/tts/                                           ││
│  │  - piper_tts.py    (Piper - par défaut)                           ││
│  │  - supertonic.py   (Supertonic-3 - haute qualité)                 ││
│  │  - windows_tts.py  (SAPI Windows)                                 ││
│  └───────────────────────────────────────────────────────────────────┘│
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐│
│  │                    EXISTING MCP                                    ││
│  │  Fichier : kuzu_mcp.py (272 lignes)                               ││
│  │  Rôle : Serveur MCP FastMCP pour Kuzu                             ││
│  │  Transport : HTTP (port 8765) ou stdio                             ││
│  │  Tools : kuzu_read, kuzu_write, kuzu_status, kuzu_snapshot        ││
│  └───────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Détail des Modules

### 2.1 Pipeline (Cerveau)

| Propriété | Valeur |
|-----------|--------|
| **Fichier** | `mycroft/pipeline.py` |
| **Classe** | `PhoenixPipeline` |
| **Lignes** | 1412 |
| **Entrée principale** | `process(text: str, context: Optional[str])` |
| **Sortie** | `Dict{response, thinking, intent, severity, confidence}` |
| **Dépendances** | Hub, Ollama (API), Memory, IntentEngine, CrisisDetector |

**Méthodes clés** :
```
process(text, context)        → Dict  # Point d'entrée principal
query_ollama(prompt, ...)     → str   # Appel LLM
extract_entities(text)        → List  # NER spaCy
match_intent(text)            → Dict  # Intent matching
_mcp_server_active()          → bool  # Vérifie si MCP tourne
get_available_models()        → List  # Modèles Ollama
set_model(model_id)           → bool  # Change le modèle
```

**Sous-composants internes** :
- `THINKING_CAPABLE_PATTERNS` : Détection modèles avec thinking
- `THINKING_TAG_PATTERNS` : Parsing tags `<think>`
- `_model_has_thinking()` : Vérifie si modèle supporte thinking
- `_parse_thinking_response()` : Sépare thinking vs réponse

---

### 2.2 Hub (Message Bus)

| Propriété | Valeur |
|-----------|--------|
| **Fichiers** | `mycroft/hub/hub.py`, `mycroft/messagebus/internal.py` |
| **Classes** | `Hub`, `InternalMessage`, `HubAdapter` |
| **Rôle** | Communication interne pub/sub, zéro réseau |
| **Thread-safe** | Oui (Lock) |

**Méthodes Hub** :
```
on(msg_type, handler)         → None    # Abonnement
once(msg_type, handler)       → None    # Abonnement unique
emit(msg_type, data, context) → None    # Publication
wait_for(msg_type, timeout)   → Message # Attente réponse
wait_for_response(msg, ...)   → Message # Attente réponse à un msg
remove(msg_type, handler)     → None    # Désabonnement
add_external_handler(handler) → None    # Handler externe (MCP)
```

**Événements critiques** :

| Événement | Producteur | Consommateur | Données |
|-----------|------------|--------------|---------|
| `recognizer_loop:utterance` | VoiceLoop | Skills, Pipeline | `{utterances: [text]}` |
| `phoenix.speak` | Pipeline, Skills | VoiceLoop, Web | `{utterance: text}` |
| `phoenix.think` | Pipeline | Web | `{utterance: thinking}` |
| `speak` | Ancien Mycroft | TTS legacy | `{utterance: text}` |

---

### 2.3 Voice Loop (Orchestrateur)

| Propriété | Valeur |
|-----------|--------|
| **Fichier** | `mycroft/audio/voice_loop.py` |
| **Lignes** | 872 |
| **Rôle** | Boucle principale, initialisation de tout |
| **Entrée** | Stream audio (micro) |
| **Sortie** | `phoenix.speak` events |

**Initialisation** :
```
__init__()
  ├── load_audio_config()
  ├── autodetect_audio()
  ├── Vosk STT (model)
  ├── Wake word (VoskGrammarWakeWord)
  ├── TTS (Supertonic ou Piper)
  ├── PhoenixPipeline(str(PROJECT_ROOT))
  ├── get_hub()
  ├── PadatiousService (intents .intent)
  ├── scan_skills(skills_dir)  → List[skills]
  └── WebServer(hub, pipeline)
```

**Boucle de traitement** :
```
_stt_loop()           → Queue[音频]
_process_loop()       → Pipeline.process()
_handle_utterance_locked(text)
  ├── Padatious.match_skill()  → priorité 1
  ├── first_match(skills)      → priorité 2
  ├── pipeline.research_context()
  └── pipeline.process()       → result
      ├── hub.emit("phoenix.think")
      └── hub.emit("phoenix.speak")
```

---

### 2.4 Skills System

| Propriété | Valeur |
|-----------|--------|
| **Fichiers** | `mycroft/skills_manager/hybrid_skill.py`, `loader.py`, `padatious_service.py` |
| **Classe base** | `HybridSkill` (Phoenix) ou `FallbackSkill` (Mycroft original) |
| **Contrat Phoenix** | `create_skill()` → instance, `init(bus, subscribe, tts)` |
| **Détection** | `_detect_*_intent(text)` → Optional[intent_name] |
| **Handler** | `_handle_utterance(message)` |

**Skills existantes** :
| Skill | Fichier | Intent |
|-------|---------|--------|
| `date_time` | `skills/date_time/` | time, date |
| `smarthome` | `skills/smarthome/` | turn_on, turn_off, list_devices, ... |

**Flux skill** :
```
VoiceLoop._handle_utterance_locked(text)
  → first_match(skills, text)
  → skill._detect_*_intent(text)  # Détection
  → skill._handle_utterance(msg)  # Exécution
  → skill._speak(response)        # Via hub.emit("phoenix.speak")
```

---

### 2.5 Memory System

| Propriété | Valeur |
|-----------|--------|
| **Fichiers** | `mycroft/memory/*.py` |
| **Base** | Kuzu (graph DB) |
| **Résilience** | WriteQueue + KuzuWorker + snapshots |
| **Bases** | `system` (phoenix.kuzu), `personal`, `research` |

**Composants** :
```
memory/
  ├── kuzu_manager.py       # Gestionnaire principal Kuzu
  ├── kuzu_resilience.py    # WriteQueue, KuzuWorker, snapshots
  ├── kuzu_research.py      # Recherche dans le graphe
  ├── azelia_knowledge.py   # Connaissances Azelia
  ├── story_db.py           # Base de données histoires
  ├── graph_notes.py        # Notes dans le graphe
  └── chatterbot_kuzu.py    # ChatterBot avec Kuzu
```

**Pattern WriteQueue** :
```
Écriture → WriteQueue.enqueue() → KuzuWorker.process_one() → Kuzu
Lecture  → Direct (Kuzu supporte lectures concurrentes)
```

---

### 2.6 Web Server

| Propriété | Valeur |
|-----------|--------|
| **Fichier** | `mycroft/web/server.py` |
| **Framework** | Flask |
| **Port** | 8181 (configurable) |
| **Auth** | mycroft/phoenix (configurable) |

**Abonnements Hub** :
```python
hub.on("phoenix.speak", self._on_speak)        # Réponses
hub.on("phoenix.think", self._on_think)        # Thinking mode
hub.on("recognizer_loop:utterance", self._on_utterance)
```

**Routes** :
```
GET  /              → Chat UI (index.html)
POST /chat          → Envoyer message
GET  /api/history   → Historique chat
GET  /api/status    → État système
POST /api/model     → Changer modèle
```

---

### 2.7 STT System

| Propriété | Valeur |
|-----------|--------|
| **Fichiers** | `mycroft/stt/vosk_stt.py`, `mycroft/audio/wakeword_fr.py` |
| **Moteur** | Vosk (offline) |
| **Modèle** | vosk-model-small-fr-0.22 |
| **Wake word** | VoskGrammarWakeWord ("phoenix") |

---

### 2.8 TTS System

| Propriété | Valeur |
|-----------|--------|
| **Fichiers** | `mycroft/tts/*.py` |
| **Moteurs** | Piper (défaut), Supertonic-3 (haute qualité), Windows SAPI |
| **Voix FR** | fr_FR-siwis-medium (Piper), fr-0 (Supertonic) |

---

### 2.9 MCP Existant (Kuzu)

| Propriété | Valeur |
|-----------|--------|
| **Fichier** | `kuzu_mcp.py` |
| **SDK** | FastMCP (`mcp.server.fastmcp`) |
| **Transport** | HTTP (port 8765) ou stdio |
| **Base** | Kuzu (phoenix.kuzu) |

**Tools exposés** :
| Tool | Fonction | ReadOnly |
|------|----------|----------|
| `kuzu_write` | Écriture via WriteQueue | Non |
| `kuzu_read` | Lecture directe | Oui |
| `kuzu_status` | État système | Oui |
| `kuzu_snapshot` | Créer snapshot | Non |

---

## 3. Flux de Données Principal

```
Audio Input (micro)
       │
       ▼
┌──────────────┐
│  STT (Vosk)  │  Audio → Texte
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│                    HUB (emit)                            │
│  "recognizer_loop:utterance" {utterances: [text]}        │
└──────────────────────────────────────────────────────────┘
       │
       ├──► Skills (priorité 1-2)
       │    └── skill._detect_*_intent(text)
       │    └── skill._handle_utterance(message)
       │    └── skill._speak(response)
       │
       └──► Pipeline.process(text, context)  (priorité 3)
            │
            ├── extract_entities(text)  → entities
            ├── match_intent(text)      → intent_result
            │
            ├── [severity >= 4] → Réponse crise (fixe)
            ├── [severity 1-3]  → Réponse empathique (fixe)
            ├── [intent connu]  → Réponse fixe OU LLM (option)
            ├── [storytelling]  → LLM (modèle dédié)
            └── [unknown]       → LLM (fallback)
            │
            └── result = {response, thinking, intent, severity}
                 │
                 ├── hub.emit("phoenix.think", {utterance: thinking})
                 └── hub.emit("phoenix.speak", {utterance: response})
                      │
                      ▼
                 ┌──────────────┐
                 │  TTS Engine  │  Texte → Audio
                 └──────┬───────┘
                        │
                        ▼
                 Audio Output (haut-parleur)
```

---

## 4. Points d'Entrée MCP (Plan d'Implémentation)

### Phase 1 : Nœud MCP Local (0.5 jour)

**Fichier** : `mycroft/mcp/phoenix_mcp.py`

**Outils à exposer** :

| Tool | Fonction | Entrée | Sortie |
|------|----------|--------|--------|
| `phoenix_process` | `Pipeline.process(text)` | `{text: str, context?: str}` | `{response, thinking, intent}` |
| `phoenix_speak` | TTS | `{text: str}` | `{status: "ok"}` |
| `phoenix_skill` | Appeler skill | `{skill_name: str, text: str}` | `{response: str}` |
| `phoenix_emit` | Hub emit | `{msg_type: str, data: dict}` | `{status: "ok"}` |
| `phoenix_status` | État système | `{}` | `{model, skills, memory, uptime}` |
| `phoenix_models` | Lister modèles | `{}` | `[{id, name}]` |
| `phoenix_set_model` | Changer modèle | `{model_id: str}` | `{status: "ok"}` |

**Transport** : stdio (pour Claude, OpenCode)

**Configuration OpenCode** :
```json
{
  "mcpServers": {
    "phoenix": {
      "command": "python",
      "args": ["D:/mycroft-phoenix/mycroft/mcp/phoenix_mcp.py"]
    }
  }
}
```

---

### Phase 2 : Debug via Hub (0.5 jour)

**Outils supplémentaires** :

| Tool | Fonction |
|------|----------|
| `phoenix_subscribe` | Écouter événements Hub en temps réel |
| `phoenix_pipeline_trace` | Traçabilité NER → Intent → LLM → Réponse |
| `phoenix_logs` | Lire fichiers de log |
| `phoenix_skills_list` | Lister skills chargées |
| `phoenix_memory_query` | Interroger Kuzu (Cypher) |

---

### Phase 3 : Backend LLM Remplaçable (1 jour)

**Concept** : Le pipeline peut appeler un serveur MCP au lieu d'Ollama

```
Pipeline.process()
  │
  ├── [mode local]  → query_ollama()  → Ollama local
  └── [mode remote] → mcp_call("llm_complete", {prompt})  → MCP server
```

**Safeguard** : Les réponses de crise (severity >= 4) ne passent JAMAIS par un backend externe.

---

### Phase 4 : Hub Multi-Appareils (2 jours)

**Architecture distribuée** :

```
┌─────────────────────┐      HTTP/JSON      ┌─────────────────────┐
│   Raspberry Pi      │ ◄─────────────────► │  Serveur Principal  │
│   (Client)          │                      │  (MCP Hub)          │
│                     │                      │                     │
│  mycroft-phoenix-   │                      │  mycroft-phoenix-mcp│
│  client             │                      │  - Ollama/LLM       │
│  - Wake word        │                      │  - Memory (Kuzu)    │
│  - STT (Vosk)       │                      │  - Skills           │
│  - TTS (Piper)      │                      │  - Web Server       │
│  - Aucune IA locale │                      │  - SmartHome Server │
└─────────────────────┘                      └─────────────────────┘
```

**API HTTP** :

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/api/process` | POST | Traiter texte (reçoit réponse) |
| `/api/speak` | POST | Synthétiser texte |
| `/api/status` | GET | État du serveur |
| `/api/models` | GET | Modèles disponibles |
| `/ws/events` | WebSocket | Événements en temps réel |

**Authentification** : Token simple (configurable)

---

### Phase 5 : Services d'Édition (2-3 jours)

**Outils MCP pour éditeurs** :

| Tool | Fonction | Pour qui |
|------|----------|----------|
| `phoenix_correct` | Corriger texte | Éditeurs (VS Code, etc.) |
| `phoenix_explain` | Expliquer code | Éditeurs |
| `phoenix_complete` | Autocomplétion | Éditeurs |

---

## 5. Dépendances Inter-Modules

```
mycroft/hub (AUCUNE dépendance externe)
   │
   ├──► mycroft/memory (kuzu only)
   │          │
   │          ▼
   ├──► mycroft/pipeline (hub + memory + Ollama API)
   │          │
   │          ▼
   ├──► mycroft/audio (hub + STT + TTS)
   │          │
   ├──► mycroft/skills_manager (hub + padatious)
   │          │
   │          ▼
   ├──► mycroft/client (hub + pipeline)
   │
   └──► mycroft/mcp (hub + pipeline + mcp sdk)
```

---

## 6. Configuration Critique

| Fichier | Rôle |
|---------|------|
| `phoenix_config.json` | Config principale (LLM, web, storytelling) |
| `audio_config.json` | Config audio (STT, TTS, wake word) |
| `skills/smarthome/config.json` | Config domotique (URL, token) |
| `~/.config/phoenix/phoenix_config.json` | Config utilisateur |

---

## 7. Notes pour l'Implémentation MCP

### Règles à respecter

1. **Ne jamais** exposer les réponses de crise via MCP (severity >= 4)
2. **Toujours** passer par la WriteQueue pour les écritures Kuzu
3. **Utiliser** le Hub existant pour la communication interne
4. **Respecter** le pattern pub/sub existant
5. **Garder** la compatibilité avec le code existant

### Points d'attention

- `pipeline._mcp_server_active()` existe déjà → à réutiliser
- `hub.add_external_handler()` existe → pour les handlers MCP
- `InternalMessage` est le format de message standard
- Les skills utilisent `hybrid_skill.HybridSkill` comme base

### Tests

```bash
# Lancer le serveur MCP en mode stdio
python mycroft/mcp/phoenix_mcp.py

# Tester avec Claude Desktop ou OpenCode
# Config dans opencode.jsonc ou claude_desktop_config.json
```

---

## 8. Historique des Modifications

| Date | Modification | Auteur |
|------|--------------|--------|
| 2026-08-16 | Création du graphe complet | OpenCode |
| 2026-08-16 | Renommage Home Assistant → SmartHome | OpenCode |
| 2026-08-16 | Ajout thinking mode | OpenCode |
| 2026-08-16 | Fix Azelia context injection | OpenCode |

---

> **IMPORTANT** : Ce fichier doit être lu avant toute modification du code.
> Il contient l'architecture complète et les points d'entrée pour tous les modules.
