# Web Control Panel & Universal Voice Client — Spécification

Module : `mycroft/admin/`
Serveur HTTP embarqué dans le core Mycroft-Phoenix.
Objectif : un seul point d'entrée web = **panneau de contrôle** + **client de chat texte/vocal** + **télédiagnostic**, headless par nature, utilisable depuis n'importe quel appareil pourvu d'un navigateur (téléphone, tablette, PC LAN, Echo Show via Silk, etc.) **sans aucune installation ni modification de l'appareil**.

---

## 1. Principe

Le micro et le haut-parleur de l'appareil client (getUserMedia / WebAudio) ne sont qu'une **périphérie réseau** du core :

```
navigateur (micro / haut-parleur / clavier)
        │  WebSocket (audio opus bidirectionnel) + HTTP (JSON)
        ▼
┌─────────────────────────── CORE (Pi / PC : Windows, Linux, macOS) ─────┐
│  mycroft/admin/server.py   serveur HTTP + SPA + WebSocket /ws/voice   │
│  STT local (vosk/whisper) → Pipeline (LadybugDB / ChatterBot / skills │
│  / AI backends) → TTS local (piper/pico) → renvoi audio               │
└───────────────────────────────────────────────────────────────────────┘
```

Tout reste sur le réseau local ; aucun passage par le cloud obligatoire.

---

## 2. Vue d'ensemble des routes

### Configuration (panneau de contrôle)
| Méthode | Route | Description |
|---|---|---|
| GET | `/` | SPA (page web) |
| GET | `/api/config` | Config complète (sans secrets) |
| GET/PUT | `/api/config/ai` | Providers AI (CRUD) |
| GET | `/api/config/ai/status` | Santé de chaque backend (dispo, latence) |
| POST | `/api/config/ai/test` | Test/ping d'un provider |
| GET/PUT | `/api/config/skills` | Catalogue skills (install/desinstall, activer/desactiver) |
| GET | `/api/config/tts` / `/api/config/stt` | Choix du moteur (vosk/whisper, piper/pico) |
| GET | `/api/memory` | Vues de la mémoire LadybugDB (stats, recherche) |
| POST | `/api/memory/learn` | Ajout manuel d'une paire question/réponse |
| GET | `/api/system` | CPU/RAM/disque, uptime, version core |
| POST | `/api/system/reboot` / `.../shutdown` | Contrôle appareil (derrière auth) |
| GET | `/api/diagnostic` | État du pipeline : skills chargés, backends intents, chatterbot, ladybug |

### Chat
| Méthode | Route | Description |
|---|---|---|
| GET | `/api/chat` | Historique récent (issu de LadybugDB) |
| POST | `/api/chat` | Message texte `{"text": "..."}` → réponse `{"text": "...", "source": "skill|chatterbot|ai|fallback"}` |
| WS | `/ws/voice` | Session audio vocale (voir §3) |

---

## 3. Protocole audio (WebSocket `/ws/voice`)

Session unique à la fois (lock serveur).

```
client → serveur : { "type": "config",  "sample_rate": 16000, "channels": 1, "format": "opus" }
client → serveur : { "type": "audio",   "data": "<base64 opus frame>" }  (en continu, tout le flux = 1 requête)
client → serveur : { "type": "end" }
serveur → client : { "type": "text",   "data": "la phrase reconnue (STT)" }     (optionnel, retour visuel)
serveur → client : { "type": "audio",  "data": "<base64 opus frame>" }          (flux TTS continu)
serveur → client : { "type": "done",   "data": {"text": "...", "source": "..."} }
```

- STT : accumulateur de frames → VAD simple (niveau RMS) → segmentation en fin de phrase.
- TTS : streaming frame par frame pour démarrage rapide.
- Timeout d'inactivité : 30 s → `{ "type": "timeout" }`.

---

## 4. Intégration pipeline (réutilisation de l'existant)

1. Le texte (venant de `/api/chat` ou du STT) entre dans le `pipeline` existant.
2. Priorité : **LadybugDB/ChatterBot** (réponse déjà connue) → **skills** (intents) → **AI backends** (priorité 6, §5) → fallback.
3. La réponse (texte) passe par le TTS pour le vocal ; le champ `source` indique quelle étape a répondu (utile au diagnostic).

---

## 5. AI backends (configurable depuis le panneau)

Abstraction `AIBackend` : `health()`, `chat(messages, ctx) -> str`, `timeout_s`, failover.

```json
"ai": {
  "enabled": true,
  "priority": 6,
  "timeout_s": 10,
  "providers": [
    {"id": "ollama",    "type": "ollama",  "host": "192.168.1.20", "port": 11434, "model": "llama3.1:8b"},
    {"id": "satellite", "type": "mycroft", "url": "http://192.168.1.10:8090"},
    {"id": "dev",       "type": "opencode","url": "http://dev-pc:4096", "api_key_env": "OPENCODE_TOKEN"},
    {"id": "openai",    "type": "openai",  "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY"}
  ]
}
```

- Ordre du tableau = priorité ; échec/timeout → provider suivant, puis fallback local.
- Chaque réponse est apprise dans LadybugDB (paires `RESPONDS_TO`) → distillation.
- Les secrets ne sont jamais renvoyés par l'API (`api_key_env` = nom de variable d'environnement).

Connecteurs prévus : `ollama` (LAN), `mycroft` (satellite Phoenix), `opencode` (développement/diagnostic), `openai`, `anthropic` (cloud optionnel).

---

## 6. Sécurité

| Mesure | Détail |
|---|---|
| Bind par défaut | `127.0.0.1` ; `lan: true` dans la config pour exposer sur le réseau |
| Token | `http.token` dans la config → exigé en en-tête `Authorization: Bearer` pour tout `/api/*` (sauf page `/`) |
| Secrets | jamais renvoyés ; seulement `api_key_env` |
| CORS | désactivé hors origine (même origine uniquement) |
| WebSocket | vérifie le token au handshake |
| Actions système | `/api/system/reboot|shutdown` → token obligatoire + confirmation |

---

## 7. Coexistence web + GUI

- **Headless (sans écran)** : on configure depuis n'importe quel navigateur du LAN → `http://<pi>:8090`.
- **Avec écran** : app locale légère (webview Python) chargeant `http://127.0.0.1:8090` — même page, même API, zéro double logique.

Une seule source de vérité : le serveur `mycroft/admin/`.

---

## 8. Fichiers prévus

```
mycroft/admin/
  __init__.py
  server.py            # serveur HTTP (stdlib http.server ou Flask léger), routes API + SPA
  auth.py              # token, bind LAN/localhost
  voice.py             # WebSocket /ws/voice, VAD, streaming STT/TTS
  config_ui/           # SPA statique (index.html, app.js, style.css) — vanilla JS, zéro build
mycroft/lora/
  ai_backend.py        # abstraction AIBackend + connecteurs (ollama, mycroft, opencode, openai, anthropic)
  ai_backends/
    __init__.py
    ollama.py  mycroft_satellite.py  opencode.py  openai.py  anthropic.py
```

## 9. Phases de mise en œuvre

1. **P0** — `ai_backend.py` + connecteurs `ollama`/`openai`/`mycroft`/`opencode` + intégration pipeline (priorité 6) + apprentissage LadybugDB.
2. **P1** — `mycroft/admin/server.py` : API config/santé + SPA panneau de contrôle + auth.
3. **P2** — Chat texte (`/api/chat`) + historique LadybugDB.
4. **P3** — `/ws/voice` : STT/TTS streaming, client vocal dans la SPA, webview pour écran.
5. **P4** — Télédiagnostic (`/api/diagnostic`, `/api/system`) + test des providers AI.

---

## 10. Dépendances cibles (minimales sur Pi)

- `websockets` (ou stdlib `websockets` inconnue → lib) pour le WS.
- STT : `vosk` (léger, hors-ligne). TTS : `piper-tts` (voix locales) ou `pico2wave`.
- Pas de framework web lourd : stdlib `http.server` suffit en P0/P1, Flask optionnel.
