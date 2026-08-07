# Mycroft-Phoenix — Design: AI Server / MCP Hub

**Status** : Design proposal (v0.1)
**Date** : 2026-08-05
**Author** : OpenCode (with Steve)
**Related to** : `doc/plan_integration_windows.md`, `mycroft/pipeline.py`, `mycroft/messagebus/internal.py`

---

## 1. Vision

Mycroft-Phoenix becomes a **local AI server**, exposed as an **MCP node**, capable of:

1. **Exposing itself**: giving any MCP-compatible AI (OpenCode, Claude, others) tools to
   drive and debug Phoenix (pipeline, skills, TTS, messagebus).
2. **Consuming**: plugging external MCP servers (Chrome, LibreOffice, text editing…)
   as pipeline capabilities.
3. **Serving**: centralizing the "brain" (local Ollama LLM + remote models) and distributing
   it to resource-poor clients: old Raspberry Pi, old PCs, phones — via a simple protocol.
4. **Editing**: offering code correction / autocompletion / explanation to open-source
   editors via LSP and/or MCP.

**Philosophy**: not everyone can afford a big local model at home. Embedded AIs are becoming
widespread and their power is increasing. Phoenix is the compute hub that makes AI
accessible to lightweight devices.

---

## 2. General Architecture

```
                         ┌─────────────────────────────┐
                         │      LIGHTWEIGHT CLIENTS    │
                         │   Pi · old PC · phone       │
                         └──────────────┬──────────────┘
                                        │ HTTP/JSON (or MQTT)
                         ┌──────────────▼──────────────┐
                         │     MYCROFT-PHOENIX         │
                         │   (AI server / MCP hub)     │
                         │                             │
                         │  ┌───────────────────────┐  │
                         │  │  Pipeline (brain)     │  │  OpenAI-compatible API
                         │  │  query_ollama → LLM  │──┼──► local / remote Ollama
                         │  └──────────┬────────────┘  │
                         │             │               │
                         │  ┌──────────▼────────────┐  │
                         │  │  Hub / messagebus     │  │  (already existing)
                         │  └──────────┬────────────┘  │
                         │             │               │
                         │  ┌──────────▼────────────┐  │
                         │  │  Skills · STT · TTS   │  │  (already existing)
                         │  └───────────────────────┘  │
                         └───────┬──────────┬──────────┘
                                 │          │
                    (stdio MCP)  │          │  (stdio MCP)
                         ┌───────▼──────┐  ┌▼──────────────┐
                         │   AGENTS     │  │  EXTERNAL     │
                         │ OpenCode     │  │  MCP servers  │
                         │ Claude, etc. │  │ Chrome, Libre │
                         └──────────────┘  └───────────────┘
```

### Two complementary standards (see 2026-08-05 discussion)

| Level       | Standard                   | Role                                  |
|-------------|----------------------------|---------------------------------------|
| **Brain**   | OpenAI-compatible API      | Phoenix ↔ LLM (local Ollama, remote)  |
| **Capabilities** | MCP                   | Phoenix ↔ tools (skills, TTS, Chrome…) |

The "either Ollama or MCP" split is wrong. It is:
**brain via OpenAI API + capabilities via MCP**, both together.

---

## 3. Protocols at play (reminder)

| Protocol | Connects                       | Role                              |
|----------|--------------------------------|-----------------------------------|
| **LSP**  | Editor ↔ language analyzer     | Autocompletion, errors, navigation |
| **DAP**  | Editor ↔ debugger              | Breakpoints, variables            |
| **MCP**  | AI ↔ tools/capabilities        | Give an AI "hands"                |
| **OpenAI API** | App ↔ LLM               | Inference ("the brain")           |

**Key points**:
- MCP = AI-centric protocol (born for autonomous agents), inspired by LSP/DAP.
- Transport stdio (local process) or HTTP/SSE (remote, mobile apps).
- The OpenAI API supports **tool-calling**: the LLM can declare "I want to call tool X".
  This is the brain ↔ hands bridge.
- An MCP server can expose: **tools**, **resources**, **prompts**, **auth**, **streaming**.

---

## 4. Implementation phases

### Phase 1 — Local control MCP node (stdio, zero web)
Goal: expose Phoenix to a local AI via MCP.

**File**: `mycroft/mcp/phoenix_mcp.py` (~200 lines)
**Exposed tools**:
| Tool | Function |
|------|----------|
| `phoenix_process` | `Pipeline.process(text)` — the text → response core |
| `phoenix_speak` | Trigger TTS |
| `phoenix_skill` | Call a specific skill (e.g. `storyteller`) |
| `phoenix_emit` | Send a message on the Hub (debug/command) |
| `phoenix_status` | State: model, Ollama up/down, loaded skills |

**Deliverables**: the MCP script + an `mcp` block in the OpenCode config (and Claude Desktop).

### Phase 2 — Debugging via the Hub
Goal: the external AI can observe and drive Phoenix live.
- `phoenix_subscribe`: listen to Hub messages (`add_external_handler`).
- `phoenix_pipeline_trace`: trace of an execution (NER → intent → LLM → response).
- Logs: the AI reads `log/` and proposes fixes.

### Phase 3 — Replaceable LLM backend (optional)
Goal: Phoenix can delegate its "brain" to an external AI.
- Option: the pipeline calls an MCP server instead of Ollama (brain interchangeability).
- **Safeguard**: crisis responses (severity ≥ 4) stay hardcoded, never delegated.

### Phase 4 — Multi-device hub (edge computing)
Goal: distribute the brain to lightweight clients.
- Simple HTTP/JSON API server-side (or MQTT for several devices).
- Clients: Raspberry Pi (STT/TTS/interface), old PCs, phones.
- The Pi needs no LLM: it sends text, receives the response to speak.

### Phase 5 — Editing services (LSP / MCP)
Goal: Phoenix helps with text and code editing in open-source editors.
- **LSP route**: a Phoenix "language server" (autocompletion, correction) for Kate/Gedit/VSCodium.
- **MCP route**: `phoenix_correct`, `phoenix_explain`, `phoenix_complete` tools consumed by
  MCP-supporting editors (more and more of them).
- The server delegates reasoning to Ollama internally: the editor needs neither GPU nor model.

---

## 5. Technical details

### Brain (OpenAI-compatible API)
- Already in place: `query_ollama()` in `mycroft/pipeline.py:289` (`/api/chat` endpoint).
- For a remote LLM: same call, different URL + key. No code change needed if going through
  an OpenAI-compatible client.

### Hub (already existing)
`mycroft/messagebus/internal.py` provides:
- `Hub.emit(msg_type, data)` — publish
- `Hub.on(msg_type, handler)` / `Hub.once` / `Hub.remove` — listen
- `Hub.wait_for(msg_type, timeout)` — wait for a response
- `Hub.add_external_handler(handler)` — plug external observers

### Skills (already existing)
Simple classes with methods (e.g. `DateTimeSkill`, `storyteller`). An MCP tool
`phoenix_skill` can invoke them by name.

### Python MCP SDK
- Same approach as the node SDK used by chrome-control (MIT license).
- stdio transport: launched as a local process by the client AI.

---

## 6. Reusability

The chrome-control node server (license **MIT**) is a reusable base:
- Its MCP architecture (stdio transport + handlers) is copyable into any server.
- Its AppleScript layer is replaceable by a CDP/Playwright backend for Windows/Linux.
- On other projects, the tool interface (10 handlers) is the valuable contract; the
  transport layer can be plugged onto any backend.

---

## 7. Open choices (to be decided)

1. **Python MCP client**: official `mcp` SDK (pip) vs minimal in-house implementation
   (stdio JSON-RPC, like the existing `kuzu_mcp.py`). → proposed: official SDK for robustness.
2. **Transport**: stdio (phase 1) then HTTP (phase 4). Can the same code be reused?
3. **Brain replacement**: keep Ollama as default and only delegate on request,
   or make the backend 100 % pluggable?
4. **Pi deployment**: which client protocol (HTTP/JSON vs MQTT)? Which lightweight STT/TTS?
5. **Security**: authentication of remote clients (phase 4) — simple token or more?

---

## 8. Suggested roadmap

| Step | Effort | Depends on |
|------|--------|------------|
| Phase 1: local MCP node | ~0.5 day | Python MCP SDK installed |
| Phase 2: debug via Hub | ~0.5 day | Phase 1 |
| Phase 3: pluggable LLM backend | ~1 day | Phase 1 |
| Phase 4: multi-device hub | ~2 days | Phases 1-2 |
| Phase 5: LSP/MCP editing | ~2-3 days | Phases 1-2 |

---

## 9. Risks and safeguards

- **Crisis (mental health)**: crisis responses (severity ≥ 4) must NEVER go through
  a delegated external backend. They stay hardcoded in the pipeline.
- **Network latency**: a Pi on Wi-Fi adds STT/TTS latency → to measure in phase 4.
- **LLM failure**: the pipeline already has a degraded mode (fixed responses, JSON
  `intent_engine`). To preserve during phase 3.
- **Kuzu locking**: `phoenix.kuzu` is protected by `kuzu_resilience.py` (WriteQueue).
  Any MCP access to the graph must go through the WriteQueue, never direct writes.

---

## 10. References

- `mycroft/pipeline.py` — STT → NER → Intent → LLM → TTS pipeline
- `mycroft/messagebus/internal.py` — event Hub
- `mycroft/skills/` — skills (date_time, intent_services, storyteller)
- `kuzu_resilience.py` — WriteQueue for phoenix.kuzu
- 2026-08-05 discussion: MCP / LSP / DAP / OpenAI API protocols
