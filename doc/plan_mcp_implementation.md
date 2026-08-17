# Plan d'Implémentation MCP dans Mycroft-Phoenix

> **Date** : 2026-08-16
> **Statut** : EN COURS
> **Objectif** : Intégrer MCP (Model Context Protocol) pour exposer Phoenix
> comme serveur IA local et hub multi-appareils

---

## 📋 Résumé Exécutif

Mycroft-Phoenix sera transformé en **serveur MCP local** capable de :
1. Exposer ses capacités (pipeline, skills, TTS) à toute IA compatible MCP
2. Consommer des serveurs MCP externes comme capabilities
3. Servir de hub cerveau pour des clients légers (Raspberry Pi, etc.)
4. Offrir des services d'édition aux éditeurs open-source

---

## 🎯 Phases d'Implémentation

### Phase 1 : Nœud MCP Local ⏱️ 0.5 jour

**Objectif** : Exposer Phoenix à une IA locale via MCP

**Livrables** :
- [ ] Créer `mycroft/mcp/__init__.py`
- [ ] Créer `mycroft/mcp/phoenix_mcp.py` (~200 lignes)
- [ ] Implémenter les outils de base :
  - `phoenix_process` : Traiter texte via Pipeline
  - `phoenix_speak` : Déclencher TTS
  - `phoenix_status` : État du système
  - `phoenix_models` : Lister modèles Ollama
  - `phoenix_set_model` : Changer modèle
- [ ] Transport stdio pour Claude/OpenCode
- [ ] Tests de base

**Fichiers à créer/modifier** :
```
mycroft/mcp/__init__.py          (nouveau)
mycroft/mcp/phoenix_mcp.py       (nouveau)
```

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

**Critères de validation** :
- [ ] `phoenix_process` retourne une réponse valide
- [ ] `phoenix_status` retourne l'état du système
- [ ] Compatible avec Claude Desktop et OpenCode

---

### Phase 2 : Debug via Hub ⏱️ 0.5 jour

**Objectif** : Observer et piloter Phoenix en live depuis une IA

**Livrables** :
- [ ] Outils supplémentaires :
  - `phoenix_subscribe` : Écouter événements Hub
  - `phoenix_pipeline_trace` : Traçabilité complète
  - `phoenix_logs` : Lire logs
  - `phoenix_skills_list` : Lister skills
  - `phoenix_memory_query` : Interroger Kuzu

**Fichiers à modifier** :
```
mycroft/mcp/phoenix_mcp.py      (ajout outils)
```

**Critères de validation** :
- [ ] `phoenix_subscribe` reçoit les événements en temps réel
- [ ] `phoenix_pipeline_trace` montre le flux complet
- [ ] `phoenix_memory_query` exécute du Cypher

---

### Phase 3 : Backend LLM Remplaçable ⏱️ 1 jour

**Objectif** : Phoenix peut déléguer son cerveau à une IA externe

**Livrables** :
- [ ] Option dans la config : `llm.backend = "local" | "mcp"`
- [ ] Si backend MCP : appeler un serveur MCP au lieu d'Ollama
- [ ] Safeguard : crise (severity >= 4) toujours locale
- [ ] Fallback automatique si MCP indisponible

**Fichiers à modifier** :
```
mycroft/pipeline.py             (modification query_ollama)
phoenix_config.json             (ajout section llm.backend)
```

**Critères de validation** :
- [ ] Le pipeline peut utiliser un backend MCP
- [ ] Les réponses de crise restent locales
- [ ] Le fallback fonctionne

---

### Phase 4 : Hub Multi-Appareils ⏱️ 2 jours

**Objectif** : Distribuer le cerveau aux clients légers

**Architecture** :
```
┌─────────────────────┐      HTTP/JSON      ┌─────────────────────┐
│   Raspberry Pi      │ ◄─────────────────► │  Serveur Principal  │
│   (Client)          │                      │  (MCP Hub)          │
│  - STT/TTS          │                      │  - Ollama/LLM       │
│  - Wake word        │                      │  - Memory           │
│  - Aucune IA        │                      │  - Skills           │
└─────────────────────┘                      └─────────────────────┘
```

**Livrables** :
- [ ] Serveur HTTP/JSON côté serveur
- [ ] Client léger pour Raspberry Pi
- [ ] Authentification par token
- [ ] WebSocket pour événements temps réel
- [ ] SmartHome serveur (Home Assistant Core intégré)

**Fichiers à créer** :
```
mycroft/mcp/server_http.py      (nouveau - serveur HTTP)
mycroft/mcp/client_light.py     (nouveau - client léger)
skills/smarthome_server/         (nouveau - serveur domotique)
```

**Critères de validation** :
- [ ] Le Raspberry Pi peut envoyer du texte et recevoir une réponse
- [ ] L'authentification fonctionne
- [ ] Les événements sont streamés en temps réel

---

### Phase 5 : Services d'Édition ⏱️ 2-3 jours

**Objectif** : Phoenix aide à l'édition dans les éditeurs open-source

**Livrables** :
- [ ] Outils MCP pour éditeurs :
  - `phoenix_correct` : Corriger texte
  - `phoenix_explain` : Expliquer code
  - `phoenix_complete` : Autocomplétion
- [ ] Intégration avec VS Code, VSCodium, etc.

**Fichiers à modifier** :
```
mycroft/mcp/phoenix_mcp.py      (ajout outils édition)
```

**Critères de validation** :
- [ ] `phoenix_correct` corrige le texte
- [ ] `phoenix_explain` explique le code
- [ ] Compatible avec les éditeurs MCP

---

## 📁 Structure des Fichiers

```
mycroft/
├── mcp/
│   ├── __init__.py
│   ├── phoenix_mcp.py          # Serveur MCP principal
│   ├── server_http.py          # Serveur HTTP (Phase 4)
│   └── client_light.py         # Client léger (Phase 4)
├── pipeline.py                 # Modifié : backend LLM
├── hub/
│   └── hub.py                  # inchangé
├── audio/
│   └── voice_loop.py           # inchangé
└── ...
```

---

## 🔧 Dépendances

| Phase | Dépendances |
|-------|-------------|
| 1 | `mcp>=1.0` (SDK Python) |
| 2 | Phase 1 |
| 3 | Phase 1 |
| 4 | Phases 1-2, `aiohttp` ou `flask` |
| 5 | Phases 1-2 |

---

## 🧪 Tests

### Phase 1
```bash
# Lancer le serveur MCP
python mycroft/mcp/phoenix_mcp.py

# Tester avec OpenCode
# Configurer opencode.jsonc puis :
# "Quel est l'état de Phoenix ?"
```

### Phase 4
```bash
# Côté serveur
python mycroft/mcp/server_http.py --port 8765

# Côté Raspberry Pi
python mycroft/mcp/client_light.py --server http://192.168.1.100:8765
```

---

## ⚠️ Points d'Attention

1. **Sécurité** : Ne jamais exposer les réponses de crise via MCP
2. **Performance** : Le MCP ajoute de la latence → à mesurer
3. **Compatibilité** : Garder le mode local fonctionnel
4. **Résilience** : Fallback automatique si MCP indisponible

---

## 📊 Estimation des Efforts

| Phase | Effort | Dépendances |
|-------|--------|-------------|
| Phase 1 | 0.5 jour | SDK MCP installé |
| Phase 2 | 0.5 jour | Phase 1 |
| Phase 3 | 1 jour | Phase 1 |
| Phase 4 | 2 jours | Phases 1-2 |
| Phase 5 | 2-3 jours | Phases 1-2 |
| **Total** | **6-7 jours** | |

---

## 🎯 Prochaines Étapes Immédiates

1. **Maintenant** : Installer le SDK MCP Python
2. **Phase 1** : Créer `mycroft/mcp/phoenix_mcp.py`
3. **Tester** : Vérifier avec Claude/OpenCode
4. **Documenter** : Mettre à jour `doc/module_graph.md`

---

> **Note** : Ce plan est un living document. Il sera mis à jour au fur
> et à mesure de l'avancement de l'implémentation.
