# Mycroft-Phoenix — Modular Architecture & Packaging

**Status** : Proposal (v0.1)
**Date** : 2026-08-05
**Author** : OpenCode (with Steve)
**Related to** : `doc/design_mcp_hub.md`, `pyproject.toml`

---

## 0. Naming — why `mycroft-phoenix` and not `phoenix`

- **`phoenix` alone is taken**: the *Phoenix* platform of the Government of
  Canada (payroll system, launched 2016, notorious failure) owns that name in
  the public mind. Our packages must be immediately identifiable and never
  confused with it.
- **`mycroft-phoenix-*`** is our brand: full project name, distinct from the
  official `mycroft-*` packages (Mycroft Core, `mycroft-core`, etc.) while
  staying in the ecosystem.
- pip conventions: `mycroft-phoenix-hub`, `mycroft-phoenix-brain`,
  `mycroft-phoenix-audio`, `mycroft-phoenix-skills`, `mycroft-phoenix-memory`,
  `mycroft-phoenix-client`, `mycroft-phoenix-mcp`, `mycroft-phoenix-server`.

---

## 1. Principle

Mycroft-Phoenix is split into **distinct modules, each replaceable** by an
alternative module (community or third-party). Each module is a **pip package,
installable independently**, that can also be used as a **dependency of other
projects**.

Goals:
- **Clients vs server**: the hub is the single contract — an alternative
  client plugs in without touching the server, and vice versa.
- **pip packaging**: `pip install mycroft-phoenix-server`,
  `pip install mycroft-phoenix-client`, etc.
- **Community**: contribute a module (new TTS, remote brain, Android client)
  without understanding everything else.
- **Windows-compatible**: a real differentiator (official Mycroft and forks
  are Linux-only).

---

## 2. The 7 modules

| # | Module (pip package) | Content | Replaceable by |
|---|----------------------|---------|-----------------|
| 1 | **`mycroft-phoenix-hub`** | `mycroft/hub/`, `mycroft/messagebus/` | any bus (MQTT, websocket, zmq) |
| 2 | **`mycroft-phoenix-brain`** | `mycroft/pipeline.py` + `mycroft/capabilities/` | remote LLM, MCP brain |
| 3 | **`mycroft-phoenix-audio`** | `mycroft/audio/`, `mycroft/stt/`, `mycroft/tts/`, `mycroft/setup_audio.py` | any STT/TTS |
| 4 | **`mycroft-phoenix-skills`** | `mycroft/skills/` | plugin system (dynamic loading) |
| 5 | **`mycroft-phoenix-memory`** | `mycroft/memory/kuzu_*.py` + `*.kuzu` databases | SQLite, other graph |
| 6 | **`mycroft-phoenix-client`** | `mycroft/client/text/chat.py`, `mycroft/client/speech/` | lightweight client (Raspberry Pi) |
| 7 | **`mycroft-phoenix-mcp`** | MCP node (phase 1 of `design_mcp_hub.md`) | any AI |

### Contract between modules

- **Hub** = single contract. `emit`/`on`/`wait_for`/`add_external_handler`
  (`mycroft/messagebus/internal.py`).
- **Brain** = text contract → response (`Pipeline.process(text) -> Dict`).
- **Audio** = TTS contract → sound file, STT → text.
- **Memory** = contract via `WriteQueue`/`KuzuWorker` (write) + direct reads.

---

## 3. Per-module dependency files

Each module has **its own pip dependencies** (no monorepo-wide global
dependencies). Detailed list below.

### 3.1 `mycroft-phoenix-hub`
**Zero external dependency** (pure stdlib). Ideal as the base of any project
using an event bus.

```toml
dependencies = []          # stdlib only (threading, asyncio, uuid)
```

### 3.2 `mycroft-phoenix-brain`
The brain: NER pipeline → intent → LLM → response.

```toml
dependencies = [
    "kuzu>=0.7",                    # memory (via mycroft-phoenix-memory)
    "requests>=2.28",               # Ollama / OpenAI API calls
    "beautifulsoup4>=4.12",         # scraping (capabilities/research.py)
    "duckduckgo_search>=7.0",       # search (capabilities/research.py)
    "langdetect>=1.0",              # language detection (pipeline)
    "scikit-learn>=1.2",            # embeddings / similarity
    "numpy>=1.24",
    "mycroft-phoenix-hub",          # internal messages
    "mycroft-phoenix-memory",       # Kuzu access (WriteQueue)
]
```
**Optional external dependency**: Ollama (local LLM), *not* in pip deps.

### 3.3 `mycroft-phoenix-audio`
STT + TTS + audio capture.

```toml
dependencies = [
    "sounddevice>=0.4",             # capture
    "pyaudio>=0.2",                 # capture (Windows)
    "vosk>=0.3",                    # local STT
    "speech_recognition>=3.10",     # alternative STT
    "gTTS>=2.3",                    # Google TTS
    "numpy>=1.24",
    "mycroft-phoenix-hub",
]
```
**Alternative TTS** (optional extras): `piper`, `espeak`, `pyttsx3`
(`mycroft/tts/` already contains several backends: windows_tts, espeak_tts,
piper_tts, gtts, mary_tts, remote_tts, polly_tts, yandex_tts, ibm_tts,
fa_tts).

### 3.4 `mycroft-phoenix-skills`
Skill system + built-in skills.

```toml
dependencies = [
    "mycroft-phoenix-hub",
    "padatious>=0.4",               # intent parsing
]
```

### 3.5 `mycroft-phoenix-memory`
Kuzu persistence with resilience.

```toml
dependencies = [
    "kuzu>=0.7",
]
```
No dependency on the rest of Mycroft-Phoenix. Reusable by other projects
(like the current `mycroft-lora` fine-tuning package, while the memory moved to
`mycroft/memory/`, to be renamed `mycroft-phoenix-memory`).

### 3.6 `mycroft-phoenix-client`
Text and voice clients.

```toml
dependencies = [
    "mycroft-phoenix-hub",
    "mycroft-phoenix-brain",        # for local process
    "requests>=2.28",               # if remote HTTP client
]
```

### 3.7 `mycroft-phoenix-mcp`
MCP node (phase 1).

```toml
dependencies = [
    "mcp>=1.0",                     # official Python MCP SDK
    "mycroft-phoenix-hub",
    "mycroft-phoenix-brain",
]
```

---

## 4. Dependency graph

```
mycroft-phoenix-hub     (no deps)
   │
   ├──► mycroft-phoenix-memory    (kuzu only)
   │          │
   │          ▼
   ├──► mycroft-phoenix-brain     (hub + memory + AI libs)
   │          │
   │          ▼
   ├──► mycroft-phoenix-audio     (hub + audio libs)
   │          │
   ├──► mycroft-phoenix-skills    (hub + padatious)
   │          │
   │          ▼
   ├──► mycroft-phoenix-client    (hub + brain)
   │
   └──► mycroft-phoenix-mcp       (hub + brain + mcp sdk)
```

- **`mycroft-phoenix-hub`** is the root: installable alone, base of
  everything.
- **`mycroft-phoenix-memory`** only depends on kuzu: reusable outside
  Mycroft-Phoenix.
- **`mycroft-phoenix-client`** can work in **remote mode** (without a local
  brain) if an HTTP transport is added → this is the future Raspberry Pi
  client.

---

## 5. pip packaging

### 5.1 Target structure (monorepo → multi-packages)

Each module lives in `packages/mycroft-phoenix-<module>/` with its own
`pyproject.toml`, `README.md`, `LICENSE.md` (Apache-2.0).

```
packages/
├── mycroft-phoenix-hub/       pyproject.toml + mycroft/hub, mycroft/messagebus
├── mycroft-phoenix-brain/     pyproject.toml + mycroft/pipeline.py, mycroft/capabilities/*
├── mycroft-phoenix-audio/     pyproject.toml + mycroft/audio, mycroft/stt, mycroft/tts
├── mycroft-phoenix-skills/    pyproject.toml + mycroft/skills
├── mycroft-phoenix-memory/    pyproject.toml + mycroft/memory/kuzu_*
├── mycroft-phoenix-client/    pyproject.toml + mycroft/client
├── mycroft-phoenix-mcp/       pyproject.toml + mycroft/mcp
```

### 5.2 Installation

```bash
# Full server (all-in-one, common usage)
pip install mycroft-phoenix-server  # = hub + brain + audio + skills + memory + client

# Individual components
pip install mycroft-phoenix-hub     # bus alone (dependency of any project)
pip install mycroft-phoenix-brain   # the brain alone
pip install mycroft-phoenix-client  # text client (remote server required)

# Module specific to another project
pip install mycroft-phoenix-memory  # e.g. third-party project wanting a resilient Kuzu graph
```

### 5.3 Server meta-package

A `mycroft-phoenix-server` meta-package aggregates the server modules:

```toml
[project]
name = "mycroft-phoenix-server"
dependencies = [
    "mycroft-phoenix-hub",
    "mycroft-phoenix-brain",
    "mycroft-phoenix-audio",
    "mycroft-phoenix-skills",
    "mycroft-phoenix-memory",
    "mycroft-phoenix-mcp",
]
```

---

## 6. Existing couplings to resolve (refactor)

Findings from the analysis (2026-08-05):

1. **`mycroft/tts/` and `mycroft/stt/`** import "core" modules inherited from
   Mycroft: `mycroft.api`, `mycroft.configuration`, `mycroft.metrics`,
   `mycroft.enclosure.api`, `mycroft.util.*`. → isolate them in a
   `mycroft-phoenix-core` layer (configuration + util) or lift them into each
   module.
2. **`mycroft/pipeline.py`** directly imports `mycroft.capabilities.*` and
   `mycroft.graph_hardware` → the brain must expose the `Pipeline.process()`
   interface and keep the rest internal.
3. **`mycroft/audio/voice_loop.py`** imports `pipeline`, `messagebus`,
   `skills`, `web` → it is the **orchestrator** (assembly point), keep it as a
   composition example, not as a base module.
4. **`phoenix.kuzu` and other `.kuzu` databases** at the repo root → move them
   to a data folder (`data/` or `~/.local/share/Phoenix`), outside the
   packages.

---

## 7. Splitting roadmap

| Step | Action | Effort |
|------|--------|--------|
| 1 | Create `packages/mycroft-phoenix-*` (7 folders) with pyproject + README + LICENSE | 1 day |
| 2 | Move the code (hub, messagebus first — zero dependency) | 0.5 day |
| 3 | Isolate `mycroft-phoenix-core` (config + util) to break tts/stt coupling | 1 day |
| 4 | Expose `Pipeline.process()` as a stable brain interface | 0.5 day |
| 5 | Extract `mycroft-phoenix-memory` (already almost standalone: `kuzu_resilience.py`) | 0.5 day |
| 6 | `pip install -e packages/mycroft-phoenix-*` and cross-import tests | 1 day |
| 7 | `mycroft-phoenix-server` meta-package + end-to-end tests | 0.5 day |

Total estimate: **~5 days** for a clean split, without changing behavior.

---

## 8. Community usage example

**Third-party project**: "I just want a local event bus for my app."
```bash
pip install mycroft-phoenix-hub
```
```python
from phoenix.hub import get_hub
hub = get_hub()
hub.on("data", handler)
hub.emit("data", {"x": 1})
```

**Raspberry Pi client**: installed with `pip install mycroft-phoenix-client`,
speaks HTTP to the central Mycroft-Phoenix server — no GPU or local model.

---

## 9. Safeguards (reminder)

- Crisis responses (severity ≥ 4): never delegated to an external backend.
- Kuzu writes: always via `WriteQueue` (`kuzu_resilience.py`), never direct.
- Windows compatibility: keep the `Path(__file__)` approach and existing OS
  detection (`platform_ext`).
