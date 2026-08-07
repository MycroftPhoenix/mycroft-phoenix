# Windows Integration Plan — Phoenix Assistant

## Overview

Phoenix can be integrated into Windows in two ways:

- **Approach A — Deep integration** (replace Cortana, system agent)
- **Approach B — Standalone** (no OS integration)

Each approach is independent. One, the other, or both can be implemented.
A final section covers the open-source Linux equivalent.

---

## Approach A — Full Windows Integration

### Goal
Phoenix becomes the system voice assistant: replaces Cortana in the taskbar,
activates from the lock screen, responds to the system wake word, and integrates
into the Windows Search Bar.

### 1. ConversationalAgent API (LAF Token)

**File:** `Windows.ApplicationModel.ConversationalAgent.dll`
**Prerequisite:** Limited Access Feature (LAF) token — requested via
[Microsoft LAF Request Form](https://aka.ms/LAFRequest).

```python
# mycroft/windows/agent_activation.py
# Relies on AgentActivationRuntime API to:
# - Activate Phoenix by voice from anywhere (lock screen, desktop, search)
# - Listen for the system wake word (no polling)
# - Set Phoenix as the default agent (replaces Cortana)
```

**What it allows:**
- System voice activation (even from lock screen)
- `Signal` to trigger the agent (system KWS)
- No background audio polling

**Without LAF token:** use DetectionOverride or stay on custom polling.

### 2. Native Windows Wake Word (KeywordDetector)

Windows already includes DNN/CNN models for the wake word:

```
C:\Windows\System32\Keywords\
├── en-US\*.table (ti_dnn_...)
├── fr-FR\*.table
├── de-DE\*.table
├── ja-JP\*.table
├── zh-CN\*.table
└── ...
```

**File:** `mycroft/windows/keyword_detector.py`

```python
# Uses native Windows models via the KeywordDetector API
# - 12 available languages
# - DNN and CNN models
# - Low latency, low power
# - No need to download Porcupine/Vosk
```

**API:** `Windows.Media.SpeechRecognition.KeywordDetectionManager`
(accessible even without LAF in some cases).

### 3. Native Windows STT

Two options:

#### a) Windows.Media.SpeechRecognition (UWP, modern)

**File:** `mycroft/stt/windows_modern_stt.py`

```python
# Uses Windows.Media.SpeechRecognition.SpeechRecognizer
# - DICTATION GRAMMAR (continuous dictation, no constraint)
# - Languages installed with Language Packs
# - Real-time streaming recognition
# - Supports pause detection speech
```

**Advantages:** native performance, no extra model, accurate.

#### b) Vosk (fallback, already integrated)

`voice_loop.py` already uses Vosk. We keep Vosk as the fallback for
systems without an installed language pack.

### 4. Native OneCore TTS (SAPI COM)

**File (existing):** `mycroft/tts/windows_tts.py`
**Current state:** uses `SAPI.SpVoice` → only returns SAPI voices
(Zira Desktop en-US). The OneCore voices (Caroline, Nathalie, Claude) are
not listed via `GetVoices()`, you need `SpObjectTokenCategory` with the OneCore path.

#### Fix for OneCore Voices

```python
# windows_tts.py — Improved _init_sapi method
def _init_sapi(self):
    import win32com.client
    self._speaker = win32com.client.Dispatch("SAPI.SpVoice")
    cat = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
    cat.SetId(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices")
    # ^ Correct registry path for OneCore voices
    tokens = cat.EnumerateTokens()
    for i, token in enumerate(tokens):
        voice_name = token.GetAttribute("Name")
        # Caroline, Claude, Nathalie (fr-CA), Linda, Richard (en-CA)
```

**Available OneCore voices (confirmed):**

| Name | Language | Gender |
|------|----------|--------|
| Caroline | fr-CA | Female |
| Claude | fr-CA | Male |
| Nathalie | fr-CA | Female |
| Linda | en-CA | Female |
| Richard | en-CA | Male |
| Zira | en-US | Female (classic SAPI) |

### 5. Replacing Cortana

#### a) Registry — system registrations

**File:** `mycroft/windows/cortana_replacement.py`

```powershell
# Replace Cortana with Phoenix in the Registry keys:

# Default agent (Windows 11 22H2+)
HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Search\DefaultAgent
  → Phoenix.exe

# Voice activation
HKLM\SOFTWARE\Microsoft\Speech_OneCore\AudioInput\KeywordDetector
  → Phoenix

# Search bar integration
HKCU\Software\Microsoft\Windows\CurrentVersion\Search
  SearchboxTaskbarMode = 1  # enable
  BingSearchEnabled = 0     # disable Bing, keep Phoenix
```

#### b) Search Bar (Windows search bar)

**Mechanism:** Windows Search supports third-party Search Providers
(double-click in the bar → opens a provider).

```python
# Implement a UWP Search Provider (COM / Desktop Bridge)
# - When the user types in the bar, Phoenix captures it
# - Local responses (Kuzu) + web (API Gateway)
# - Results shown in a Phoenix window
```

**Non-UWP alternative:** a shell app that listens to the clipboard
or uses `ISearchBoxInfo` (COM).

#### c) Agent Activation Runtime (AarSvc)

**Windows service:** `Agent Activation Runtime` starts voice agents
at boot. For Phoenix to be recognized:

```
1. Register a COM CLSID for Phoenix
2. Define Phoenix as "ConversationalAgent" in the manifest
3. AarSvc launches Phoenix at system startup
```

### 6. Windows Background Service

**File:** `mycroft/windows/phoenix_service.py`

```python
# Windows service (win32serviceutil)
# - Starts at boot
# - Listens for the wake word
# - Shows an icon in the system tray
# - Auto-restarts on crash
```

```powershell
# Service installation
sc create PhoenixAgent binPath="C:\Program Files\Phoenix\phoenix_service.exe"
sc start PhoenixAgent
```

### 7. System Tray Icon + Interface

**File:** `mycroft/windows/tray.py`

```python
# Icon in the notification area
# - Left click: open the interface
# - Right click: menu (mute, settings, quit)
# - State: listening / speaking / inactive
```

### 8. Architecture Diagram (Windows Integration)

```
┌─────────────────────────────────────────────────────────┐
│                   Windows System                          │
├─────────────────────────────────────────────────────────┤
│  Lock Screen  │  Search Bar  │  Taskbar  │  Notifications │
├─────────────────────────────────────────────────────────┤
│  ConversationalAgent (AarSvc)  │  KeywordDetector       │
│  Activation | Unlock           │  Wake Word             │
├─────────────────────────────────────────────────────────┤
│  Windows.Media.SpeechRecognition  │  SAPI OneCore TTS    │
│  (native STT)                     │  (native TTS)         │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────── Phoenix ──────────────────────┐       │
│  │  Windows Service │ Tray Icon │ Kuzu DB        │       │
│  │  Full pipeline │ Skills │ API Gateway         │       │
│  │  Ollama LLM │ IntentMatcher │ Crisis Detection │       │
│  └───────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
```

### Prerequisites / Limitations

| Component | Required | Alternative |
|-----------|----------|-------------|
| ConversationalAgent API | Microsoft LAF Token | Works without (custom wake word) |
| Windows 11 22H2+ | OS | Windows 10 too, but reduced features |
| UWP Search Provider | MS certification | Standalone application |
| SAPI OneCore | Windows 8+ | Already available |
| KeywordDetector | Windows 10+ | Vosk/Porcupine fallback |

---

## Approach B — Standalone Application

### Goal
Phoenix runs as a normal application, without system integration.
Manual or logon startup, no special permissions needed,
compatible with Windows 10 and 11.

### 1. Architecture

```
┌──────────────────────────────┐
│         Phoenix              │
├──────────────────────────────┤
│  Pipeline (already existing)  │
│  Vosk STT │ Piper/SAPI TTS   │
│  Kuzu DB │ Ollama LLM        │
│  Skills │ Crisis Detection   │
├──────────────────────────────┤
│  Startup : Registry / Folder │
│  Wake word : Vosk (custom)   │
│  Tray icon : yes             │
└──────────────────────────────┘
```

### 2. Startup

**Three modes:**

#### a) Manual startup (terminal)
```bash
phoenix            # existing entry point
phoenix-chat       # text interface
phoenix-diag       # audio diagnostics
```

#### b) Automatic startup (logon)
```powershell
# Registry Run
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v Phoenix /t REG_SZ /d "C:\Program Files\Phoenix\phoenix.exe --background"

# Or Startup folder
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Phoenix.lnk
```

#### c) Windows service (without agent integration)
```python
# Simple service, no AarSvc needed
# Just a win32serviceutil.ServiceFramework
# Starts at boot, listens for the wake word
```

### 3. Custom Wake Word

**File:** `mycroft/wake_word/porcupine.py` or `mycroft/wake_word/vosk.py`

```python
# Option 1: Porcupine (Picovoice)
# - Lightweight, accurate, cross-platform
# - Free (2 wake words), paid for more
# - .ppn file to download

# Option 2: Vosk (same model as STT)
# - Already installed
# - Heavier (CPU)
# - No license

# Option 3: OpenWakeWord
# - Open-source (Apache 2.0)
# - Based on TensorFlow Lite
# - "Hey Firefox", "Hey Computer" pre-trained
# - French model to train
```

**Recommended:** Vosk (already present, zero extra dependency).

### 4. TTS

**Two options (already implemented):**

| Option | Advantages | Disadvantages |
|--------|------------|---------------|
| SAPI OneCore (fix windows_tts.py) | Natural French voices | Windows only |
| Piper | Cross-platform | Less natural voices, ~1 GB |

**Default config:** SAPI OneCore if available → Piper fallback.

### 5. STT

**Vosk (already integrated):**
- `voice_loop.py` uses `KaldiRecognizer` via Vosk
- French model `vosk-model-small-fr-0.22` (~35 MB)
- Works 100% offline

### 6. User Interface

**Available modes:**
1. **Voice-only** (no UI, just tray icon)
2. **Text chat** (`phoenix-chat`, terminal)
3. **Graphical interface** (coming, tkinter or PyQt)

**Tray icon:**
```python
# InfiSy / pystray (if available)
# Menu: Enable/Disable, Settings, Quit
```

### 7. Data / Persistence

**Kuzu DB (already integrated):**
- `phoenix.kuzu`: operational database
- WriteQueue + KuzuWorker for resilience
- Snapshots/checkpoints in `mycroft-kuzu/`

**Configuration files:**
- `phoenix_config.json` (existing)
- `audio_config.json` (existing)

### 8. Compatibility

| Feature | Windows 10 | Windows 11 |
|---------|-----------|------------|
| Vosk STT | ✅ | ✅ |
| SAPI TTS | ✅ | ✅ (OneCore+) |
| Piper TTS | ✅ | ✅ |
| Tray icon | ✅ | ✅ |
| Wake word | ✅ | ✅ |
| Service | ✅ | ✅ |

---

## Open-Source Linux Equivalent

### Goal
The same functionality as Approach A (system integration), but with
100% open-source technologies on Linux.

### 1. Shell Integration (Cortana / Search Bar equivalent)

#### a) GNOME Shell Search Provider

**File:** `mycroft/linux/gnome_search_provider.py`

```python
# DBus interface org.gnome.Shell.SearchProvider2
# Phoenix registers as a search provider
# Results: knowledge base, skills, web
# The user types Super then their query
```

`.search-provider.ini` file:
```ini
[Shell Search Provider]
DesktopId=phoenix.desktop
BusName=org.phoenix.SearchProvider
ObjectPath=/org/phoenix/SearchProvider
```

#### b) KDE Plasma KRunner

**File:** `mycroft/linux/krunner.py`

```python
# KRunner plugin (krunner python)
# KPlugin MetaData + DBus interface
# org.kde.krunner1
```

`.desktop` file:
```
[Desktop Entry]
Type=Service
X-KDE-ServiceTypes=Plasma/Runner
X-KDE-PluginInfo-Name=phoenix
X-KDE-PluginInfo-Category=System
```

#### c) Unity / Budgie / Others

- **Unity Lens** (Legacy): dbus `com.canonical.Unity.Lens`
- **Budgie Raven**: Budgie plugin
- **XFCE Panel**: XFCE panel plugin

### 2. Wake Word

| Technology | License | French model |
|------------|---------|--------------|
| **OpenWakeWord** | Apache 2.0 | To train |
| **Porcupine** | Apache 2.0 (base) | Yes (paid) |
| **Vosk KWS** | Apache 2.0 | Yes (same STT model) |
| **Precise** | Apache 2.0 | No (Mycroft legacy) |
| **Snowboy** | MIT | Yes (abandoned) |

**Recommended:** Vosk KWS (same model as STT, zero overhead).

### 3. Open-Source STT

| Technology | License | Quality | French |
|------------|---------|---------|--------|
| **Vosk** | Apache 2.0 | Good | ✅ `vosk-model-small-fr-0.22` |
| **Whisper** (OpenAI) | MIT | Excellent | ✅ (multilingual) |
| **Whisper.cpp** | MIT | Excellent | ✅ (lightweight) |
| **Coqui STT** | MPL 2.0 | Good | ✅ |
| **DeepSpeech** (Mozilla) | MPL 2.0 | Average | ✅ (abandoned) |
| **wav2vec 2.0** (Meta) | MIT | Very good | ✅ (needs GPU) |

**Recommended:** Vosk (lightweight, offline) + Whisper (GPU fallback for high accuracy).

### 4. Open-Source TTS

| Technology | License | Quality | French |
|------------|---------|---------|--------|
| **Piper** | MIT | Good | ✅ (already installed) |
| **Coqui TTS** | MPL 2.0 | Very good | ✅ |
| **eSpeak-NG** | GPL 3.0 | Robotic | ✅ |
| **Festival** | MIT | Robotic | ✅ |
| **Mimic** (Mycroft) | Apache 2.0 | Good | No |
| **Mimic 3** | Apache 2.0 | Very good | No |

**Recommended:** Piper (already integrated) for everyday use, Coqui TTS for
superior quality.

### 5. System Service (AarSvc equivalent)

**Technology:** systemd user service

```ini
# ~/.config/systemd/user/phoenix.service
[Unit]
Description=Phoenix Assistant

[Service]
ExecStart=%h/.local/bin/phoenix --background
Restart=always

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable phoenix
systemctl --user start phoenix
```

**D-Bus activation:** (on-demand startup)
```xml
<!-- /usr/share/dbus-1/services/org.phoenix.service -->
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Services 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <service>
    <name>org.phoenix</name>
    <exec>/usr/bin/phoenix --dbus</exec>
  </service>
</busconfig>
```

### 6. Audio (Windows Speech Stack equivalent)

| Windows | Linux Equivalent |
|---------|------------------|
| WASAPI | **PipeWire** (modern) / PulseAudio |
| SAPI COM | **D-Bus** + GStreamer |
| Windows.Media.SpeechRecognition | **Vosk** / Whisper (no native OS equivalent) |
| KeywordDetector | **OpenWakeWord** / Vosk KWS |
| OneCore Voices | **Piper** / Coqui TTS |

**PipeWire** is recommended (Wayland-compatible, low latency,
replaces PulseAudio and JACK).

### 7. Functional Equivalence

| Feature | Windows A (Integrated) | Windows B (Standalone) | Linux |
|---------|------------------------|------------------------|-------|
| System voice activation | ✅ ConversationalAgent | ❌ | ❌ (no equivalent API) |
| Wake word | ✅ KeywordDetector | ✅ Vosk | ✅ Vosk / OpenWakeWord |
| STT | ✅ Win.Media.SpeechRecognition | ✅ Vosk | ✅ Vosk / Whisper |
| TTS | ✅ OneCore SAPI | ✅ SAPI / Piper | ✅ Piper / Coqui |
| Search bar | ✅ UWP Search Provider | ❌ | ✅ GNOME / KDE Runner |
| Background service | ✅ AarSvc | ✅ Run / Service | ✅ systemd |
| Lock screen | ✅ LAF | ❌ | ❌ |
| Tray icon | ✅ | ✅ | ✅ |
| Cross-platform | ❌ | ❌ | ✅ |
| 100% open-source | ❌ | ✅ | ✅ |
| Works offline | ✅ | ✅ | ✅ |

## Dependencies per Component

### Approach A (Windows Integrated)

```
pywin32                     # SAPI COM, Windows service
comtypes                    # advanced COM (optional)
windows-applicationmodel    # ConversationalAgent (if LAF)
Pillow                      # tray icon
```

### Approach B (Windows Standalone)

```
vosk                        # STT (already installed)
sounddevice                 # audio capture (already installed)
pywin32                     # SAPI TTS (optional, otherwise Piper)
pystray / infi.sy           # tray icon (optional)
```

### Linux (Open-Source)

```
vosk                        # STT
sounddevice                 # audio capture
piper-tts                   # TTS (or Coqui)
pygobject                   # GNOME integration (dbus)
dbus-python                 # D-Bus service
openwakeword                # wake word (optional)
pystray                     # tray icon (optional)
```

## Conclusion

**Approach A (Windows Integrated)** is the ultimate vision: Phoenix replaces
Cortana, integrates everywhere. But it depends on the Microsoft LAF Token and
proprietary Windows APIs.

**Approach B (Standalone)** is the pragmatic path: works now, on all Windows
versions, without external dependencies. Everything is already implemented
except the OneCore TTS fix and the tray icon.

**Linux** can reproduce ~80% of Approach A's features with open-source
components. The main difference is the lack of a ConversationalAgent API
equivalent (lock screen activation).

Efforts should prioritize the OneCore TTS fix and the Vosk wake word,
which benefit all three targets.
