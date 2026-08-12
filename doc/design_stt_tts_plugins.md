# Brancher un moteur STT / TTS (guide)

Le core **Mycroft-Phoenix ne connaît aucun moteur de voix en dur** : tout passe
par une interface standardisée (`mycroft/lora/speech.py`). Ce document explique
comment brancher un nouveau moteur de synthèse (TTS) ou de reconnaissance (STT)
sans toucher au core — et comment les utiliser depuis le web (`/api/chat` texte,
plus tard `/ws/voice` audio).

## 1. L'interface (le "standard maison")

Deux classes abstraites, dans `mycroft/lora/speech.py` :

| Classe       | Rôle                      | Méthode clé                                        |
|--------------|---------------------------|----------------------------------------------------|
| `TTSBackend` | synthèse vocale           | `synthesize(text) -> Iterable[bytes]` (PCM streaming) |
| `STTBackend` | reconnaissance vocale     | `transcribe(audio, sample_rate) -> str \| None`       |

Contrat commun à tous les moteurs :

- `health() -> bool` : installé / joignable / prêt (jamais d'exception).
- `status() -> dict` : `{id, type, healthy, sample_rate, language, ...}`
  (affiché par le panneau web).
- **TTS** : `synthesize()` émet des paquets de **PCM brut** (int16, mono,
  little-endian) au rythme de `sample_rate`. Le streaming est natif : un
  moteur qui produit au fil de l'eau est diffusé immédiatement, sinon on peut
  renvoyer la totalité d'un coup (le client n'a pas à le savoir).
- **STT** : `transcribe(audio, sample_rate)` reçoit le même format PCM brut.
- **Tous les imports sont paresseux** : si le moteur n'est pas installé,
  `health()` renvoie `False` au lieu de planter le core.

> Pourquoi PCM brut ? C'est le format natif des cartes son, des codecs (opus),
> de vosk, piper, kokoro… Toute lib audio sait le produire/consommer. On évite
> ainsi toute dépendance à un format propriétaire.

## 2. Config : choisir un moteur

`phoenix_config.json`, sections `stt` et `tts` (clé `engine` = nom du connecteur) :

```json
"tts": { "engine": "kokoro", "language": "fr", "voice": "af_heart",
         "model_path": "kokoro-v1.0.onnx", "voices_path": "voices-v1.0.bin" },
"stt": { "engine": "vosk", "language": "fr",
         "model_path": "vosk-model-small-fr-0.22" }
```

Le core construit les moteurs via `speech_from_config(config)`. Aucun autre
fichier de code ne référence un moteur précis.

## 3. Ajouter un nouveau TTS (exemple : edge-tts, voix cloud Microsoft)

1. **Sous-classer** `TTSBackend` dans `mycroft/lora/speech.py` :

```python
class EdgeTTS(TTSBackend):
    """Voix neuronales Microsoft via edge-tts (cloud, streaming)."""
    type = "edge-tts"
    description = "Voix Microsoft (edge-tts, cloud)"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.voice = cfg.get("voice", "fr-FR-DeniseNeural")
        self.sample_rate = 24000

    def health(self):
        import importlib.util
        return importlib.util.find_spec("edge_tts") is not None

    async def _run(self, text, path):
        import edge_tts
        comm = edge_tts.Communicate(text, self.voice)
        await comm.save(path)

    def synthesize(self, text):
        import asyncio, tempfile, os, wave
        fd, wav = tempfile.mkstemp(suffix=".wav"); os.close(fd)
        try:
            asyncio.run(self._run(text, wav))
            with wave.open(wav, "rb") as w:
                self.sample_rate = w.getframerate()
                yield w.readframes(w.getnframes())
        finally:
            try: os.remove(wav)
            except OSError: pass
```

2. **Enregistrer** dans le registry `_TTS_REGISTRY` :

```python
_TTS_REGISTRY = { ..., "edge-tts": EdgeTTS }
```

3. **Déclarer** la config : `"tts": { "engine": "edge-tts", "voice": "fr-FR-DeniseNeural" }`.

C'est tout : le web, le pipeline et `/ws/voice` l'utilisent sans modification.

## 4. Ajouter un nouveau STT (même principe)

1. Sous-classer `STTBackend` (`transcribe(audio, sample_rate)`).
2. L'enregistrer dans `_STT_REGISTRY`.
3. Le déclarer : `"stt": { "engine": "<mon-moteur>", ... }`.

## 5. Les moteurs fournis

| Moteur     | Type      | Usage                        | Dépendances                          |
|------------|-----------|------------------------------|--------------------------------------|
| Kokoro     | TTS       | **desktop temps réel CPU** (AMD/Intel sans GPU) — recommandé | `pip install kokoro-onnx onnxruntime` + `kokoro-v1.0.onnx` & `voices-v1.0.bin` (Hugging Face `hexgrad/Kokoro-82M`) |
| Piper      | TTS       | Raspberry Pi / machines faibles | binaire `piper` + modèle `.onnx`    |
| pico2wave  | TTS       | ultra léger, mono-shot        | paquet `libttspico-utils`            |
| dummy      | TTS       | tests (silence)               | —                                   |
| Vosk       | STT       | hors-ligne léger, FR OK (défaut) | `pip install vosk` + modèle (`vosk-model-small-fr-0.22`) |
| Whisper    | STT       | qualité max (plus gourmand)   | `pip install faster-whisper` (int8 CPU) |
| dummy      | STT       | tests (texte configuré)       | —                                   |

**Kokoro — installation rapide (Windows, ONNX CPU) :**

```powershell
pip install kokoro-onnx onnxruntime soundfile
# modèles depuis Hugging Face (hexgrad/Kokoro-82M) :
#   kokoro-v1.0.onnx  et  voices-v1.0.bin  → à côté du config, puis :
"tts": { "engine": "kokoro", "model_path": ".../kokoro-v1.0.onnx",
         "voices_path": ".../voices-v1.0.bin", "voice": "af_heart", "language": "fr" }
```

Test rapide (sans carte son) : le moteur doit répondre `healthy: true` au
`/api/config/ai/test` (ou `status()` directement).

## 6. Règles à respecter pour un branchement propre

1. **Jamais de code moteur dans le core** : le core appelle `synthesize()` /
   `transcribe()`, c'est tout.
2. **Imports paresseux** : le moteur absent ⇒ `health() == False`, pas d'erreur.
3. **PCM int16 mono LE** : convertir à la frontière du connecteur
   (numpy / `wave` / `soundfile` selon la lib).
4. **`sample_rate` renseigné** : le connecteur met à jour `self.sample_rate`
   s'il diffère de la config (ex. pico/edge renvoient leur propre cadence).
5. **Temps réel d'abord** : si le moteur stream, produisez les paquets au fil
   de l'eau (`yield`) pour un démarrage audio rapide.
6. **`status()` explicite** : indiquez `healthy` et les infos utiles au
   diagnostic du panneau web.
