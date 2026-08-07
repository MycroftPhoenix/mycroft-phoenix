# Virtual Enclosure — Design Notes for Phoenix

**Status** : Reference (2026-08-05)
**Author** : OpenCode (with Steve)
**Scope** : How a *virtual enclosure* (face / eyes / LED ring / screen / animations)
can connect to Phoenix **without touching the core**.

---

## 1. What an enclosure is

On the original Mycroft, the "enclosure" is the physical body of the assistant:
the Mark-1's 32×8 LED face (eyes, mouth, visemes), the Mark-2's screen, or a
generic GPIO face plate. It subscribes to the message bus and renders the
assistant's state: **idle → wake word heard → listening → thinking → speaking**.

Phoenix has **no built-in enclosure**. This is a deliberate decision:

- The core (STT, wake word, pipeline, TTS, skills) must never depend on a
  display — Phoenix runs headless on servers and in the cloud too.
- Anyone can build their own enclosure (tkinter window, LED strip, web page,
  phone app...) **as an optional consumer** of the message hub. It can be
  enabled or disabled at will, and it can never break the assistant.

This document explains exactly how such an enclosure connects. It is written
as an ideas/reference guide for developers who want to build their own.

---

## 2. The hub: how Phoenix components talk

Phoenix replaced the Mycroft WebSocket message bus with a 100% in-memory
pub/sub hub. There is **no network socket** in the core.

```python
from mycroft.messagebus import get_hub

hub = get_hub()          # process-wide singleton

hub.on("phoenix.speak", my_handler)     # subscribe
hub.once("enclosure.idle", handler)     # subscribe, auto-unsubscribe
hub.remove("phoenix.speak", my_handler)
hub.remove_all_listeners()              # careful!

hub.emit("enclosure.idle")              # publish (no data, or dict)
hub.emit("enclosure.speak", {"utterance": "hello"})
hub.wait_for("mycroft.stop", timeout=5) # blocking wait, returns the message
```

Hub API (see `mycroft/messagebus/internal.py`):

| Method | Purpose |
|--------|---------|
| `on(type, handler)` | Subscribe. Handlers receive an `InternalMessage`. |
| `once(type, handler)` | Subscribe for one delivery. |
| `remove(type, handler)` | Unsubscribe. |
| `remove_all_listeners(type=None)` | Unsubscribe all (or one type). |
| `emit(type, data=None, context=None)` | Publish. Accepts a raw type string or an `InternalMessage`. |
| `add_external_handler(fn)` | Register a bridge handler — *see §5, external processes*. |
| `wait_for(type, timeout=None)` | Block until the message arrives; raises `TimeoutError`. |

`InternalMessage` fields: `msg_type`, `data` (dict), `context` (dict), plus
helpers `reply()`, `response()`, `forward()`, `publish()`, `serialize()`.

Notes:
- Handlers may be plain functions **or coroutines** — async handlers are
  scheduled automatically.
- Subscribing to `"*"` receives **every** message.
- Every handler runs synchronously in the emitting thread; keep enclosure
  rendering work in its own thread so it never blocks STT/TTS.

---

## 3. Message protocol an enclosure can use

These are the real messages exchanged by the Phoenix core (verified in
`mycroft/audio/voice_loop.py` and the skills):

### Listen (consume)

| Message | Data | Meaning |
|---------|------|---------|
| `recognizer_loop:utterance` | `{"utterances": ["<text>"]}` | User phrase recognized. |
| `phoenix.speak` | `{"utterance": "<text>"}` | The assistant is speaking this reply (voice loop & web UI both consume it). |
| `mycroft.stop` | — | Stop current playback / activity. |
| `mycroft.stop.handled` | `{"by": "<component>"}` | Somebody handled the stop request. |

### Emit (control)

| Message | Data | Meaning |
|---------|------|---------|
| `phoenix.speak` | `{"utterance": "<text>"}` | Ask the voice loop to say something (e.g. from a text-input enclosure). |
| `recognizer_loop:utterance` | `{"utterances": ["<text>"]}` | Inject a phrase as if the user said it (text mode). |
| `mycroft.stop` | — | Interrupt the assistant. |

### Suggested state tracking (no core change needed)

A classic Mycroft enclosure animates on these transitions. Phoenix's voice
loop currently emits the two core events above; an enclosure can derive state
from them:

```
wake word detected  → not emitted by default (see §6)
utterance received  → listening finished → show "thinking"
phoenix.speak       → show "speaking" + subtitles (data.utterance)
silence             → back to idle
```

If you need *finer* events (`wakeword`, `audio_output_start/end`,
`recording_started`, ...), the clean way is to have your enclosure **emit** a
control message or patch nothing — see §6, the recommended approach.

---

## 4. Integration patterns

### Pattern A — in-process (recommended)

Run inside the same Python process (e.g. a thread started by the voice loop or
a plugin). Straightforward, zero serialization, and your enclosure gets full
`InternalMessage` objects.

```python
from threading import Thread
from mycroft.messagebus import get_hub

class MyEnclosure:
    def __init__(self):
        self.hub = get_hub()
        self.state = "idle"
        self.hub.on("recognizer_loop:utterance", self.on_utterance)
        self.hub.on("phoenix.speak", self.on_speak)

    def on_utterance(self, msg):
        self.state = "thinking"
        self.render()                      # your UI update

    def on_speak(self, msg):
        self.state = "speaking"
        self.subtitle(msg.data.get("utterance", ""))
        self.render()

    def render(self):
        ...                                # paint your face / LEDs / screen
```

### Pattern B — legacy adapter (for existing Mycroft code)

Mycroft's original enclosure code (`mycroft/client/enclosure/*`) instantiates
`MessageBusClient()` and calls `on/once/emit/run_forever/wait_for_response`.
Phoenix does **not** install the `mycroft_bus_client` PyPI package, so that
import fails. If you want to reuse legacy code, write a thin adapter that maps
the `MessageBusClient` API onto the hub:

```python
from mycroft.messagebus import get_hub

class HubMessageBusClient:
    """Minimal adapter exposing the legacy MessageBusClient API."""
    def __init__(self, **kwargs):
        self.hub = get_hub()
        self.connected = True          # always connected, no network

    def on(self, msg_type, handler):        self.hub.on(msg_type, handler)
    def once(self, msg_type, handler):      self.hub.once(msg_type, handler)
    def remove(self, msg_type, handler):    self.hub.remove(msg_type, handler)
    def emit(self, msg, **kwargs):
        data = getattr(msg, "data", None) or kwargs
        mtype = getattr(msg, "msg_type", None) or msg
        self.hub.emit(mtype, data)
    def wait_for_response(self, msg, *a, **k):
        return self.hub.wait_for(getattr(msg, "msg_type", msg) + ".response")
    def run_forever(self):               pass   # hub lives in the core process
    def run(self):                       pass
    def close(self):                     pass
```

### Pattern C — external process / network bridge

If the enclosure runs in a **separate process** (a phone app, a browser page,
a remote device), bridge the hub over any transport you like. The hub has a
dedicated hook for this:

```python
from mycroft.messagebus import get_hub
import json, websockets   # or sockets, MQTT, HTTP, ...

hub = get_hub()

def bridge_handler(msg):
    # forward every hub message to your remote enclosure
    socket.send(json.dumps(msg.serialize()))

unregister = hub.add_external_handler(bridge_handler)
```

- `add_external_handler(fn)` is called for **every** message published, exactly
  like a `"*"` subscriber, but isolated from the in-process handler list.
- Feed the reverse direction with `hub.emit(...)` from your network thread.
- `InternalMessage.serialize()` returns `{"type", "data", "context"}` ready for
  JSON.

---

## 5. Pitfalls discovered (checklist for enclosure developers)

1. **`mycroft.enclosure` package import is broken** in the Phoenix tree
   (`mycroft/enclosure/__init__.py` imports `.api` → `display_manager` →
   `get_ipc_directory`, which raises `ImportError`). Use the submodules under
   `mycroft/client/enclosure/` instead — their `__init__.py` is empty and safe
   to import.
2. **`start_message_bus_client` blocks forever on the hub.** The legacy helper
   in `mycroft/util/process_utils.py` does `bus.once('open', ...)` then
   `bus_connected.wait()`. A hub adapter never emits `'open'` (there is no
   socket). Either don't use that helper, or short-circuit it when the client
   reports `connected is True` from the start.
3. **Missing legacy dependencies**: `mycroft_bus_client`, `tornado`, `websocket`
   are **not** installed. Don't `pip install` them into Phoenix — adapt instead
   (Pattern B/C).
4. **`get_arch` is not exported** by `mycroft.util` in the lightweight build
   (the legacy `mycroft.api` module imports it). The function still lives in
   `mycroft/util/platform.py`. Any config/API path that used it is legacy-only.
5. **Keep the enclosure optional.** Wrap construction in `try/except` and make
   sure a missing display, tkinter, or network never prevents the voice loop
   from starting.

---

## 6. Reference design: a Mark-2 style desktop window

To prove the concept, a virtual Mark-2 was prototyped as a tkinter window
(no dependency beyond the stdlib, cross-platform Windows/Linux/macOS). It is a
good starting point for your own enclosure. Ideas it demonstrated:

- **LED ring** — a 12-LED ring drawn as circles, resizable with the window,
  colored by state.
- **Idle screen** — live clock + date when the assistant is silent.
- **State machine** — distinct visuals for *idle*, *listening*, *thinking*,
  *speaking*.
- **Subtitles** — shows the last user phrase and the assistant's spoken reply
  (`phoenix.speak` data.utterance).
- **Text input bar** — lets the user type, then `hub.emit("recognizer_loop:utterance", ...)`
  so the assistant answers without a microphone.

The real Mark-2 palette (from the original Mycroft theme) for an authentic look:

| Element | Color |
|---------|-------|
| Main blue | `#22A7F0` |
| Tertiary blue | `#4DE0FF` |
| Tertiary green | `#40DBB0` |
| Background | `#16324F` |

Architecture to replicate:

```
┌─────────────────────────────┐
│  Enclosure (your process)    │
│  ┌─────────────────────────┐ │
│  │ render()  ← state       │ │   render on its own thread
│  └─────────────────────────┘ │
│  hub.on(...)   hub.emit(...) │   Pattern A (in-process)
│        │            ▲        │
└────────┼────────────┼────────┘
         ▼            │
      ┌─── get_hub()  ───┐
      │   Phoenix core   │
      └──────────────────┘
```

For **finer state events** (wake word detection, TTS start/end), don't patch
the core: have your enclosure derive them, or bridge a separate service that
wraps STT/TTS callbacks and re-emits standard `recognizer_loop:*` events on the
hub. The core stays untouched and the enclosure stays removable.

---

## 7. Guidelines (the contract)

1. An enclosure is **read-only** on the core: it subscribes, renders, and may
   emit *control* messages (`phoenix.speak`, `recognizer_loop:utterance`,
   `mycroft.stop`). It never modifies core modules.
2. It must start/stop **independently** — enabling an enclosure is never
   required for the assistant to work.
3. If it fails (missing tkinter, no display, network error), the failure is
   contained: log it and keep the voice loop running.
4. Ship it as its own package/module, not inside `mycroft/audio` or
   `mycroft/pipeline`.
