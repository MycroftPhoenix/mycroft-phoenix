# SESSION LOG — Mycroft-Phoenix (pour continuité entre sessions Claude/OpenCode)

> Ce fichier est un checkpoint de travail. Toute IA (Claude, OpenCode, etc.)
> qui reprend le travail sur ce projet devrait lire ce fichier EN PREMIER
> avant de refaire du diagnostic depuis zero.

## 2026-08-14 — Session de remise en route apres migration E:\ -> D:\

### Contexte
Le disque E:\ (ancien emplacement du projet, `E:\opencode\assistant_locale-Mycroft-phoenix`)
appartenait au fils de Steve. Il a ete rapporte/repare, et le projet a ete
transfere sur un vieux disque dur interne: `D:\mycroft-phoenix`.
Repo GitHub: https://github.com/MycroftPhoenix/mycroft-phoenix (branch main)

### Bugs trouves et corriges (commits pousses sur main)
1. **`c4eaa24`** — Chemins caches E:\opencode -> D:\mycroft-phoenix:
   - `lancer-phoenix.bat`: variable APP corrigee
   - `mycroft/tts/piper_adapter.py`: 2x importlib.util.spec_from_file_location vers base.py/piper_tts.py corriges
   - `mycroft/tts/supertonic.py`: importlib vers base.py corrige
   - `mycroft/audio/voice_loop.py`: fix UnicodeEncodeError cp1252 (meme bug que build_module_map.py, commit 5b46157) via `stream.reconfigure(encoding="utf-8", errors="replace")`
   - **PAS corrige** (non bloquant): `mycroft/audio/supertonic_tts.py` et `mycroft/tts/supertonic.py` ont encore `DEFAULT_MODEL_DIR = E:\opencode\sherpa-models\...` — dossier sherpa-models introuvable nulle part sur cette machine (ni D:, ni C:). Pas grave car Piper est le moteur TTS actif, pas Supertonic. A fixer si/quand les modeles sherpa sont retransferes.
   - **PAS corrige** (non bloquant): `mycroft/pipeline.py` ligne ~509 a un fallback candidate `E:\opencode\.opencode\api_gateway.py` pour la meteo — code deja protege par `os.path.exists()`, echoue silencieusement (juste pas de meteo).

2. **BUG MAJEUR TROUVE (non encore commite au moment d'ecrire ceci si ce message a saute)**:
   `mycroft/audio/voice_loop.py` `main()` faisait `stream.reconfigure(encoding="utf-8", errors="replace")`
   SANS `line_buffering=True`. Consequence: quand le process tourne avec stdout redirige
   (pas un vrai TTY — le cas via Desktop Commander, services Windows, logs redirige vers fichier, etc.),
   Python passe en **buffering bloc** au lieu de line-buffering. Tous les `print()` SANS
   `flush=True` explicite restent coinces dans le buffer et n'apparaissent JAMAIS dans les logs
   qu'on lit en direct (invisible jusqu'a ce que le buffer se remplisse ou que le process se termine).
   **C'est tres probablement la cause du "ca repond pas" que la derniere IA (a court de tokens)
   n'a pas pu diagnostiquer** — le pipeline traitait bel et bien les requetes, mais ca semblait
   mort car aucun log de confirmation ne sortait.
   **FIX**: ajouter `line_buffering=True` au `stream.reconfigure(...)` dans `main()`.
   Verifie empiriquement: avec le fix, `[Pipeline] Traitement: ...` et `[Skill:date_time] Intent: heure`
   apparaissent immediatement apres une requete chat.

### Etat actuel confirme fonctionnel (teste via curl + logs, 2026-08-14 ~08h45)
- Demarrage propre via `D:\mycroft-phoenix\lancer-phoenix.bat` (utilise `C:\ProgramData\miniforge3\python.exe`,
  PAS le python du PATH qui est WindowsApps 3.14 sans vosk installe)
- Vosk STT charge, wake word "phoenix" actif
- Piper TTS actif (voix fr_FR-siwis-medium, model trouve via `C:/piper/voices` — chemin hardcode
  cherche AVANT le config; `C:\piper\piper\piper.exe` existe aussi)
- Interface web Flask sur port 8181, **accessible en LAN** (host 0.0.0.0, confirme via test depuis
  cell Steve a 192.168.0.8)
- Login web: mycroft/phoenix
- Pipeline traite les requetes chat et route vers le skill `date_time` correctement
- Ollama tourne (PID actif), mais **seul modele installe = `qwen3:0.6b`** (pas qwen2.5:0.5b/1.5b
  que la config exemple demandait — corrige dans phoenix_config.json)

### Fichiers de config crees/modifies
- **`D:\mycroft-phoenix\phoenix_config.json`** (n'existait PAS avant, seulement le .example) —
  cree avec llm.default_model=qwen3:0.6b, web.host=0.0.0.0, web.port=8181,
  memory.kuzu_path=./phoenix.kuzu. C'est CE fichier que lit `mycroft/pipeline.py`
  (PhoenixPipeline.CONFIG_FILE) et `mycroft/web/server.py` (section "web").
- **`D:\mycroft-phoenix\audio_config.json`** (existait deja) — ajoute `"engine": "piper"` dans
  la section tts (sinon defaut = "supertonic" qui plante silencieusement car sherpa-models absent),
  et corrige model_dir vers `C:\\piper\\piper\\voices`.
  **IMPORTANT**: c'est CE fichier (pas phoenix_config.json) que lit `voice_loop.py main()` via
  `load_audio_config()` pour choisir le moteur TTS.
  => DEUX fichiers de config distincts, ne pas les confondre.

### Probleme resolu en cours de session: processus fantome sur port 8181
Un vieux process `python -m mycroft.admin.server --base-dir C:\Users\ADMINI~1\AppData\Local\Temp\opencode\test_cfg`
(lance par une session de debug anterieure, probablement la derniere IA) tournait deja sur le
meme port 8181 que le vrai `voice_loop.py`, causant de la confusion (reponses "Phoenix fallback:
je ne suis pas sur de comprendre" venant du MAUVAIS serveur, pas du vrai pipeline). Tue (kill_process).
Ce process semble etre revenu une fois tout seul apres le premier kill (peut-etre une boucle retry
dans un cmd.exe parent) mais pas revu depuis le 2e kill. **A surveiller**: si `test_cfg` admin.server
reapparait, chercher son processus parent (`wmic process where "ProcessId=X" get ParentProcessId`)
pour trouver la source du respawn.

### Reste a faire / degrade actuellement (non bloquant pour usage de base)
1. **Kuzu (memoire graphe) en mode degrade**: aucune base `.kuzu` trouvee ni dans
   `D:\mycroft-phoenix\phoenix.kuzu` (systeme) ni `AppData\Roaming\phoenix\*.kuzu` (personal/research).
   `mycroft/memory/kuzu_manager.py` s'attend a ce que la base SYSTEME preexiste avec des noeuds
   Intent deja peuples (pas de creation auto) — voir `phoenix_config.example.json` section chatterbot,
   `import_command: python -m mycroft.knowledge import --lang fr --skills <dossier> --data-dir data --chatterbot-corpus`.
   Necessite le repo `mycroft-phoenix-skills` (deja transfere sur D:\ aussi, `D:\mycroft-phoenix-skills`).
   **PAS fait cette session** — necessite une commande d'import qui peut prendre du temps, a faire
   avec Steve present plutot qu'en autonome pendant qu'il dort.
2. **spaCy**: modele `xx_ent_wiki_sm` absent (`python -m spacy download xx_ent_wiki_sm` pas encore lance).
   Affecte extraction d'entites (ex: ville pour meteo).
3. **Supertonic-3 TTS**: dossier sherpa-models absent, chemins encore casses (E:\ hardcode).
   Piper fonctionne comme fallback actif, donc pas urgent.
4. Deux processus python residuels a surveiller au demarrage (voir section fantome ci-dessus).

### Comment relancer proprement (pour reference future)
```
D:\mycroft-phoenix\lancer-phoenix.bat
```
PAS `python voice_loop.py` directement depuis `mycroft\audio\` — ca utilise le python du PATH
(WindowsApps, sans vosk installe). Le .bat force `C:\ProgramData\miniforge3\python.exe`.

Avant de relancer, verifier qu'aucun vieux process n'occupe deja le port 8181:
```
netstat -ano | findstr :8181
wmic process where "ProcessId=X" get CommandLine
```
