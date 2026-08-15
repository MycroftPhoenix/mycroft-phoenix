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

## 2026-08-14 (suite) — Migration Kuzu -> LadybugDB + roadmap panneau config

### Migration Kuzu -> LadybugDB (demande explicite Steve)
**IMPORTANT — a savoir**: le vrai package `kuzu` fonctionne parfaitement sur cette
machine (teste directement: creation DB + table = OK). Le "Base introuvable" qu'on
voyait AVANT la migration etait uniquement du aux fichiers .kuzu absents (migration
E:\ -> D:\, jamais crees ici) — PAS un bug de la librairie kuzu elle-meme.
La migration vers LadybugDB est donc un choix architectural (Steve l'a demande),
PAS un correctif d'un bug. Les deux options auraient regle le probleme des bases
manquantes.

**Fait**:
- `mycroft/memory/kuzu_manager.py`: `import kuzu` -> `import real_ladybug as kuzu`
- `mycroft/memory/kuzu_resilience.py`: meme swap (2 endroits: `_DBHandle.__init__`,
  `restore_from_latest_snapshot`)
- API confirmee compatible (teste isolement): `Database(path)`, `Connection(db)`,
  `conn.execute(cypher, params_dict_positionnel)` — fonctionne identique a l'API kuzu.
- Teste: `KuzuManager()._init_personal()` cree `phoenix_personal.kuzu` (format
  real_ladybug) avec succes.
- `phoenix.kuzu` (systeme) reste "introuvable" — comportement ATTENDU, le code
  n'auto-cree jamais la base systeme (elle doit etre pre-peuplee avec des intents,
  voir plus bas "reste a faire"). Ce n'est pas une regression.

**PAS touche (decision Steve du 2026-08-14)**: `mycroft/memory/story_db.py` —
utilise encore le vrai `kuzu`, gere `phoenix_stories.kuzu` (1.1 Mo, donnees reelles
existantes a `C:\Users\Administrateur\AppData\Roaming\phoenix\phoenix_stories.kuzu`).
Fonctionne deja, pas prioritaire. A migrer plus tard si on veut la coherence complete
(mais attention: real_ladybug et kuzu reel n'ont PAS ete testes pour compatibilite
de FORMAT de fichier — un fichier cree par l'un n'est pas forcement lisible par
l'autre. A verifier avant de migrer story_db.py si jamais).

### Etat operationnel confirme (2026-08-14, apres migration Ladybug)
Redemarrage complet teste: Vosk + wake word + Piper TTS + Web UI (LAN) + Pipeline
+ skill date_time — tout fonctionne, aucune regression. Le seul "degrade" reste
le meme qu'avant: intents JSON au lieu de Kuzu/Ladybug system DB (phoenix.kuzu
jamais peuplee). **Phoenix est operationnel pour usage de base.**

### Reste a faire (priorite Steve: system DB avant panneau config)
- Peupler `phoenix.kuzu`/`.lbdb` systeme avec les intents (voir session precedente:
  necessite `D:\mycroft-phoenix-skills`, pas de script d'import tout fait trouve
  encore — `mycroft/knowledge/` ne contient que `mycroft_corpus.py` +
  `mental_health_dataset.json`, pas de CLI d'import. A creer ou trouver.)

---

## IDEE FUTURE (roadmap, PAS urgent) — Panneau de configuration complet

Steve (non-programmeur, "taponer des scripts pour changer la config me fait chier")
demande un panneau web tout-en-un pour configurer Phoenix sans toucher au JSON a la
main. Proposition (a construire sur `mycroft/web/server.py`, deja existant):

**Fonctionnalites demandees**:
1. Audio: detection auto des peripheriques entree/sortie disponibles (deja fait en
   partie via `voice_loop.py --autodetect`/`--diagnostic`, juste pas expose en UI)
2. TTS/STT: afficher le moteur actif, permettre de changer (Piper/Supertonic pour
   TTS; Vosk pour STT eventuellement d'autres)
3. Sauvegarde de la config courante + rollback facile ("sans mal de tete") si un
   changement casse quelque chose
4. Telechargement + configuration automatique des modules necessaires (ex: modele
   Piper/Vosk manquant -> le panneau propose de le telecharger)
5. Assistance IA optionnelle pour guider la config (dependant si un LLM est
   disponible/configure)
6. Comptes utilisateurs multiples avec login/mot de passe propre a chacun (pas
   juste le seul compte mycroft/phoenix actuel)
7. Changer le wake word, avec une liste de mots recommandes + possibilite d'en
   essayer un invente par l'utilisateur

**Idee additionnelle (Claude, 2026-08-14)**: mode "tester avant d'appliquer" —
avant de sauvegarder un changement TTS/wake word, le tester en direct (synthese
d'un phrase test, ou 5 sec d'ecoute) pour eviter de sauvegarder-redemarrer-decouvrir
que ca marche pas.

**A eclaircir avant de commencer**: priorite relative vs le reste du backlog
(system DB intents en premier, selon Steve 2026-08-14). Autres parametres oublies
possibles a lister avec Steve avant de commencer le design.

---

## 2026-08-14 (suite 3) — Inventaire corpus a la racine D:\ (analyse en cours, checkpoints frequents car quota bas)

Steve a demande d'analyser les corpus/datasets qui trainent a la racine de D:\
(rien a voir avec mycroft-phoenix directement, mais presumement pour un futur
projet data/NLP — voir memoire long-terme: "corpus NLP francais Autisme-Dascalu
sur Ortolang/HuggingFace pour projet data potentiel").

### Inventaire brut (racine D:\, non-mycroft)
Fichiers zip (non extraits, tailles/contenus PAS encore verifies a ce stade):
- `autismedascalu.zip` — tres probablement le corpus "Autisme-Dascalu" (Ortolang/HuggingFace) deja mentionne dans le contexte Steve
- `camfr-treebank-mf-fpc.zip` — treebank francais (camerounais? "camfr" = Cameroon French?), MF-FPC = Multi-Function ou format specifique a determiner
- `corpus-parents-toxiques.zip` — corpus texte, sujet "parents toxiques" (sante mentale/temoignages?)
- `corpus-phileduc.zip` — "Phil'educ"? corpus philo/education
- `corpus-recits-ademe.zip` — recits lies a l'ADEME (agence francaise environnement/energie)?
- `csonu.zip` — a determiner (CSO+NU? Conseil Superieur ONU?)
- `derom.zip` — DEROM = possiblement "Dictionnaire Etymologique Roman" (corpus linguistique romaniste connu)
- `ema-ecrits-scolaires-1.zip` — EMA = ecrits d'eleves/scolaires, corpus scolaire
- `eval-dataset-bibcheck.zip` — dataset d'evaluation, verification bibliographique
- `eval-dataset-softwaretag.zip` — dataset d'evaluation, tagging de logiciels (mentions de logiciels dans du texte?)
- `evaluation-dataset-rnsr.zip` — RNSR = Repertoire National des Structures de Recherche (France) — dataset lie a la recherche academique
- `ftb.zip` — tres probablement French TreeBank (corpus syntaxique francais classique/connu en NLP)
- `neurosciences-corpus.zip` — corpus textes neurosciences
- `orthocorpus.zip` — corpus orthographe (verification/correction orthographique)
- `tdm-eval-dataset-ner.zip` — TDM (Text and Data Mining) dataset eval pour NER (Named Entity Recognition)
- `texttokids.zip` — corpus texte destine aux enfants (litterature jeunesse?)

Dossiers (non explores en profondeur encore):
- `erudit.org\` — tres probablement corpus/donnees de la plateforme Erudit (revues savantes quebecoises/francophones)
- `gouv quebec\` — donnees/corpus gouvernement du Quebec
- `université lavale\` (sic, typo pour "laval") — corpus/donnees Universite Laval

Autres fichiers a la racine (non-corpus):
- `Charte_Ortolang_V20150217.pdf` — charte d'utilisation Ortolang (plateforme francaise de ressources linguistiques) — confirme que plusieurs corpus ci-dessus viennent d'Ortolang
- `creativecommons.org.url` — raccourci web, probablement licence CC d'un des corpus
- `envs\`, `pkgs\` — tres probablement environnements Python/conda, PAS des corpus
- `mycroft-phoenix\`, `mycroft-phoenix-skills\` — projets deja documentes ailleurs dans ce log

### Prochaine etape (a faire quand la session reprend)
1. Verifier la Charte Ortolang (PDF) pour les conditions d'usage/licence de ces corpus
2. Lister le contenu de chaque zip SANS forcement extraire (via `Compress-Archive`/
   `tar -tf` ou Python zipfile.namelist()) pour confirmer les hypotheses ci-dessus
   sans consommer d'espace disque inutilement
3. Explorer `erudit.org\`, `gouv quebec\`, `université lavale\` (dossiers deja
   extraits, contenu inconnu)
4. Determiner le projet/objectif vise par Steve avec ces corpus (mentionne dans
   la memoire long-terme: potentiel projet data autour du corpus Autisme-Dascalu)

### Inventaire CONFIRME (contenu reel des zips, verifie 2026-08-14)

1. **autismedascalu.zip** (13 fichiers) — Corpus Autisme-Dascalu confirme.
   Dossiers nommes par sujet (ex: GERMAIN-06-5-09-13, LYRON-03-4-08-04) —
   probablement transcriptions/enregistrements d'enfants autistes avec codes
   anonymises (age/session). Format Ortolang tres probable (licence a verifier
   dans la Charte PDF a la racine).

2. **camfr-treebank-mf-fpc.zip** (5 fichiers) — Treebank francais MEDIEVAL
   (pas "camerounais" comme suppose) — "camfrv2.1_2025_09_12.conll" (format
   CoNLL, standard NLP pour annotation syntaxique) + guide d'annotation +
   image "phraseoMedieval.png". Corpus de francais ancien/medieval annote.

3. **corpus-parents-toxiques.zip** (3 fichiers) — PDF de documentation +
   nuage de mots. Petit corpus, sujet sensible (temoignages "parents toxiques").
   Pas de donnees brutes visibles dans les 3 fichiers listes — juste doc +
   visualisation, le vrai corpus texte est peut-etre ailleurs/pas inclus.

4. **corpus-phileduc.zip** (19 fichiers) — "Phil'educ": transcriptions de
   seances de philosophie a l'ecole (primaire + college), format CSV par
   seance/annee (ex: 2016_Questions_seance_1.csv, College/2015_classe_6eme...).

5. **corpus-recits-ademe.zip** (2 fichiers) — Un seul fichier texte
   "CORPUS RECITS.txt" lie a l'ADEME (agence francaise transition ecologique).

6. **csonu.zip** (4524 fichiers!) — LE PLUS GROS. Resolutions du Conseil de
   Securite de l'ONU (CSONU) 1946-2015, en anglais (dossier vu) et probablement
   aussi francais (pas confirme dans l'echantillon). Format XML individuel par
   resolution + fichier XSL de transformation (txm-front-xmlonu-xtz.xsl —
   "TXM" = plateforme d'analyse textometrique, format compatible TXM confirme).

7. **derom.zip** (578 fichiers) — DEROM confirme = Dictionnaire Etymologique
   Roman. Articles XML individuels par etymon (notation phonetique dans les
   noms de fichiers, ex: a'nEll-u.xml, 'trEm-e-.xml — notation API/phonetique
   des racines romanes reconstruites).

8. **ema-ecrits-scolaires-1.zip** (5817 fichiers!) — 2e plus gros. Ecrits
   scolaires d'eleves (ex: "ROUBAUD 3-3"), avec PDF de metadonnees/grilles
   d'ecriture ET scans images (jpg) des productions manuscrites d'eleves
   (CE1-2018-MN1-D1-E2.jpg etc). Corpus tres riche mais lourd (beaucoup
   d'images), sujet: apprentissage de l'ecriture.

9. **eval-dataset-bibcheck.zip** (9 fichiers) — Dataset d'evaluation
   verification bibliographique, 2 versions (v1/v2) en JSONL, avec description.
   Format TDM (Text and Data Mining) standard — metadata.xml present, meme
   structure que les 3 autres "eval-dataset-*"/"tdm-eval-*" ci-dessous —
   TOUS ces datasets (bibcheck, softwaretag, rnsr, ner) semblent venir de la
   MEME plateforme/collection (structure identique: metadata.xml + TDM.png +
   donnees). Probablement une collection d'evaluation pour outils de fouille
   de texte (TDM = Text and Data Mining), possiblement Istex ou similaire
   (plateforme francaise de fouille de textes scientifiques).

10. **eval-dataset-softwaretag.zip** (7 fichiers) — Detection de mentions de
    logiciels dans des articles scientifiques (PLoS methods/sentences corpus,
    Pubmed fulltext corpus) — format JSON.

11. **evaluation-dataset-rnsr.zip** (6 fichiers) — RNSR confirme = Repertoire
    National des Structures de Recherche. JSONL + guide d'utilisation PDF.

12. **ftb.zip** (277 fichiers) — French TreeBank confirme. Sous-dossier
    "corpus-fonctions" avec fichiers XML annotes syntaxiquement (categories
    grammaticales dans les extensions: .cat.xml, .aa.xml, .indent.xml) —
    corpus de reference classique en NLP francais (articles Le Monde annotes).

13. **neurosciences-corpus.zip** (3 fichiers) — Corpus bilingue neurosciences,
    format .tmx (Translation Memory eXchange — corpus PARALLELE de traduction,
    pas juste un corpus monolingue). Utile pour traduction/alignement de
    terminologie scientifique.

14. **orthocorpus.zip** (30 fichiers) — Corpus d'orthographe organise PAR
    ANNEE (1999 a 2022+), "Fichiers Orthocorpus v4_parAnnee" — probablement
    des dictees ou productions ecrites annotees en erreurs orthographiques
    sur plusieurs annees (utile pour un correcteur/detecteur d'erreurs).

15. **tdm-eval-dataset-ner.zip** (17 fichiers) — Meme famille que bibcheck/
    softwaretag/rnsr (voir #9). NER = Named Entity Recognition. Contient un
    fichier WikiNER neerlandais (aij-wikiner-nl-wp3.conll) — attention,
    PAS francais celui-la, format CoNLL standard NER.

16. **texttokids.zip** (3818 fichiers) — 3e plus gros. "Text to Kids":
    corpus d'apprentissage automatique (train/dev/test_prompt.tsv) +
    "CorpusAIA" avec annotations multiples (A1, WP7Fiction...) — corpus
    de litterature/texte pour enfants avec annotations riches, structure
    de type shared-task (train/dev/test split = format ML standard).

### Synthese / hypothese sur l'usage prevu (Claude, a valider avec Steve)
Ces corpus sont TOUS d'origine academique/Ortolang/TDM francophone (recherche
linguistique, NLP, sciences de l'education, sciences sociales). Rien a voir
directement avec mycroft-phoenix (assistant vocal domestique). Hypothese la
plus probable vu le contexte Steve (interet SpaCy/NLP, projet "Vision" avec
spaCy fr_core_news_sm + embeddings): **entrainement ou enrichissement d'un
modele de langue francais local** (fine-tuning, embeddings personnalises,
ou alimentation d'un moteur de recherche/RAG local) — possiblement pour
Mycroft-Phoenix lui-meme (comprehension du francais quebecois/familier) OU
pour un projet NLP francophone separe. A CONFIRMER avec Steve — ne pas
assumer/deviner l'usage exact sans son input.

### Points d'attention avant utilisation
- **Licences**: Charte_Ortolang_V20150217.pdf a la racine confirme que
  plusieurs corpus viennent d'Ortolang — verifier les conditions d'usage
  AVANT tout entrainement/redistribution (certains corpus academiques ont
  des restrictions, ex: usage recherche seulement, pas commercial).
  csonu.zip et evaluation-dataset-rnsr.zip semblent venir d'une plateforme
  TDM differente (Istex?) — licences potentiellement differentes aussi.
- **texttokids** et **ema-ecrits-scolaires** concernent des ENFANTS
  (productions scolaires, litterature jeunesse) — porter attention
  particuliere a la protection des donnees/anonymisation si utilise.
- **Poids/volume**: csonu (4524 fichiers), ema-ecrits-scolaires (5817,
  incluant des scans image), texttokids (3818) sont les 3 plus volumineux —
  a prioriser en dernier si l'espace disque ou le temps de traitement est
  une contrainte.

### PAS ENCORE FAIT (a la prochaine session)
- Explorer le contenu des dossiers deja extraits: `erudit.org\`,
  `gouv quebec\`, `université lavale\` (pas des zips, contenu inconnu)
- Lire la Charte Ortolang au complet pour les conditions de licence exactes
- Discuter avec Steve de l'usage prevu exact pour orienter le prochain travail
