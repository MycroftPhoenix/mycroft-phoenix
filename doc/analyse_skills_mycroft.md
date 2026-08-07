# Analyse des 50 Skills Mycroft Originales — Application à Phoenix

**Date** : 2026-08-05
**Auteur** : OpenCode
**Sources** : 50 repos officiels `MycroftAI/skill-*` (GitHub, branche HEAD)
**Localisation** : `C:\Users\ADMINI~1\AppData\Local\Temp\opencode\mycroft_skills\extracted\`

---

## 1. Vue d'ensemble

| Métrique | Valeur |
|----------|--------|
| Skills téléchargées | 50/50 |
| Fichiers total | 9412 |
| Fichiers `.dialog` (réponses) | 4761 |
| Fichiers `.voc` (mots-clés) | 2310 |
| Fichiers `.intent` (phrases Padatious) | 981 |
| Locales distinctes | ~26 (dont 57 dossiers `fr-fr`) |

**Constat clé** : la base Mycroft original est un énorme corpus **"0 IA"** —
réponses pré-enregistrées + mots-clés + phrases d'intents, sans aucun LLM.
C'est exactement le format du module sans-IA qu'on veut pour les Raspberry Pi.

---

## 2. Structure d'une skill Mycroft (pattern à reproduire)

```
skill-xxx/
├── __init__.py          # class XxxSkill(MycroftSkill) + @intent_handler
├── vocab/<lang>/*.voc   # mots-clés (une ligne par variante)
├── dialog/<lang>/*.dialog  # réponses pré-enregistrées ({{var}} interpolation)
├── skill.json           # métadonnées + intents (déclaratif)
├── requirements.txt
└── README.md
```

- **`.voc`** : mots-clés à l'état brut — consommables directement par notre
  `IntentMatcher` (keywords map) et par `IntentEngine` (TF-IDF).
- **`.intent`** : phrases Padatious, entre parenthèses = variantes
  `(quelle heure est-il|l'heure)`. Peuvent être converties en exemples
  d'uttenances pour notre `skill.json`.
- **`.dialog`** : réponses avec `{{var}}` — compatible avec notre futur
  système de dialogue paramétré.

---

## 3. Skills réutilisables pour Phoenix (priorité décroissante)

### A. Intents & vocabulaire français directement exploitables

| Skill | Intents FR extraits | Usage Phoenix |
|-------|--------------------|---------------|
| **skill-date-time** | `quelle heure est-il`, `l'heure actuelle`, `date`, `année bissextile`, weekend | → enrichir `normal_responses` time/date |
| **skill-weather** | `prévisions`, `dehors`, `dois-je prendre un parapluie`, `froid/chaud`, `humide`, `nuageux`, `ensoleillé` | → vocabulaire météo complet (température, unités, dates) |
| **skill-alarm** | `réveille moi`, `alarme`, `supprime l'alarme`, jours `lundi…dimanche` | → future skill alarme |
| **skill-reminder** | `prochain rappel`, `annule les rappels du {date}`, `supprime tous les rappels` | → future skill rappels |
| **skill-joke** | `blague`, `fais moi rire`, `raconte moi une blague`, `chuck norris` | → skill blagues (offline) |
| **skill-spelling** | `épelle`, `épelle le mot`, `épellation de` | → skill épellation |
| **skill-singing** | `chante`, `chante moi une chanson` | → skill chant |
| **skill-stop** | `arrête`, `stop`, `silence`, `chut`, `tais-toi` | → intents d'arrêt TTS |
| **skill-ip** | `mon adresse IP`, SSID | → skill IP locale (pratique Pi) |

### B. Skills à réimplémenter en local (serveurs morts)

| Skill | Problème | Solution Phoenix |
|-------|----------|------------------|
| **skill-fallback-persona** | dépend de `training.mycroft.ai/persona` (mort) | → réponses empathiques locales (on a déjà la détection de détresse) |
| **skill-personal** | `who.am.i`, `dream`, `rhyme`, `when.was.i.born` — réponses fixes | → phrases FR déjà traduites, réutilisables telles quelles |
| **skill-wiki** | dépend d'API Wikipedia (libre, OK) | → réutilisable (recherche wiki = API Gateway) |
| **skill-npr-news / mycroft-radio** | dépendent de flux radio/news | → adapter à des flux FR vivants |

### C. Skills trop couplées à l'infra Mycroft (à ignorer)

`skill-pairing`, `skill-installer`, `skill-configuration`, `skill-homeassistant`,
`skill-pandora`, `skill-wink-iot`, `skill-mark-2*`, `skill-wifi-connect`,
`skill-homescreen` — dépendent de l'OS Mycroft, de mark-1/2, de comptes tiers,
ou d'une UI GUI spécifique.

---

## 4. Les 3 patterns d'intents Mycroft (pour notre IntentLoader)

1. **Adapt (`IntentBuilder`)** : `@intent_handler(IntentBuilder("X").require("voc").require("IP"))`
   → équivalent de nos keywords dans `_intent_keywords`.
2. **Padatious (`.intent`)** : phrases avec variantes entre parenthèses, entraînées par ML léger
   → équivalent de notre `IntentEngine` TF-IDF. **Convertibles en exemples `skill.json`.**
3. **Fichiers `.voc`** : vocabulaire par langue
   → notre `JsonIntentBackend`/`GraphIntentBackend` peut les ingérer tels quels
   pour l'entraînement TF-IDF.

---

## 5. Recommandations pour Phoenix

1. **Importer le vocabulaire fr-fr** de `date-time`, `weather`, `alarm`,
   `reminder`, `joke`, `spelling`, `singing`, `stop` dans notre base d'intents
   (via `phoenix-skill-intent load` ou un importateur `.voc`→intents).
2. **Réutiliser les réponses `.dialog` fr-fr** comme réponses fixes du mode
   "0 IA" (ex: `time.current.dialog` → « Il est {{time}} »).
3. **Réimplémenter `fallback-persona` en local** : garder le principe
   (repli empathique) mais sans serveur — brancher sur notre échelle de
   sévérité existante.
4. **Créer un convertisseur `.voc` → `skill.json`** pour que l'import des
   skills Mycroft passe par notre outil `phoenix-skill-intent`.
5. **Ne pas porter** les skills liées au matériel Mycroft / comptes tiers.

---

## 6. Sauvegarde au graph

Facts : `f22bd7a7` (inventaire), `75d1ac99` (intents réutilisables),
`9cc8fcd5` (fallback-persona + personal), `eca079c0` (structure skill + patterns).
