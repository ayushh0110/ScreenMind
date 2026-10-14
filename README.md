<div align="center">

<br>

<img src="https://img.shields.io/badge/🧠_ScreenMind-Your_AI_Memory-8B5CF6?style=for-the-badge&labelColor=0a0e1a" alt="ScreenMind" height="40">

<br><br>

**Captures your screen → Analyzes with Gemma 4 → Builds a searchable AI memory**<br>
**100% local. 100% private. Zero cloud dependencies.**

<br>

[![PyPI](https://img.shields.io/pypi/v/screenmind?style=flat-square&logo=pypi&logoColor=white&label=PyPI)](https://pypi.org/project/screenmind/)
[![CI](https://github.com/ayushh0110/ScreenMind/actions/workflows/ci.yml/badge.svg)](https://github.com/ayushh0110/ScreenMind/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/ayushh0110/ScreenMind/graph/badge.svg)](https://codecov.io/gh/ayushh0110/ScreenMind)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Gemma 4](https://img.shields.io/badge/Gemma_4-E2B_%7C_E4B_%7C_12B-8B5CF6?style=flat-square&logo=google&logoColor=white)](https://ai.google.dev/gemma)
[![llama.cpp](https://img.shields.io/badge/llama.cpp-Local_Inference-333?style=flat-square)](https://github.com/ggerganov/llama.cpp)
[![License MIT](https://img.shields.io/badge/License-MIT-10B981?style=flat-square)](LICENSE)
[![MCP Ready](https://img.shields.io/badge/MCP-Claude_%7C_Cursor_%7C_VSCode-F59E0B?style=flat-square)](MCP_SETUP.md)
[![Website](https://img.shields.io/badge/Website-screenmind.pages.dev-0a0e1a?style=flat-square&logo=cloudflare&logoColor=white)](https://screenmind.pages.dev)

<br>

[**Website**](https://screenmind.pages.dev) · [**Features**](#-features) · [**Comparison**](#-how-screenmind-compares) · [**Gemma 4 Deep Dive**](#-how-gemma-4-is-used) · [**Quick Start**](#-quick-start) · [**Architecture**](#-architecture) · [**Agent Platform**](#-agent-platform) · [**MCP**](#-mcp-server-claude--cursor--vs-code) · [**API**](#-api-reference)

<br>

![Timeline — AI-analyzed screen activity feed](docs/screenshots/timeline.png)

| Agents | 
|:---:|
| ![Agents](docs/screenshots/agents.png) |

<br>

**💬 Chat in Action** — *Ask anything about your screen history*

![Chat Demo — conversational AI with screen memory](docs/screenshots/chat-demo.gif)

</div>

<br>

> **Microsoft showed the world wants screen-aware AI with Recall.** But Recall stores data in plaintext, sends telemetry, and was met with massive privacy backlash. ScreenMind is the open-source, privacy-first alternative — every screenshot analyzed, every insight generated, every search result — all computed locally using Gemma 4's multimodal capabilities.
>
> It's not just a screen recorder. It's an **AI memory** you can talk to, search through, and build automations on top of.

---


## ✨ Features

### 🧠 Core Intelligence

- **📸 Smart Capture** — Content-change detection, not a fixed timer. Captures when your screen *actually* changes.
- **🔬 Gemma 4 Vision Analysis** — Every screenshot analyzed: app detection, activity categorization, mood, scene description, spatial layout regions.
- **🔍 Hybrid Search** — Semantic embeddings (MiniLM) + FTS5 keyword search. Find anything by *meaning*, not just keywords.
- **💬 Chat with Memory** — Conversational RAG with follow-up support. Ask "what did Alex say on Discord?" → get the actual message.
- **🧠 Model Hub** — In-app model download with **variant selection** (Q4_0, Q8_0, BF16, etc.). Supports Gemma 4 E2B, E4B, and 12B. Chat and Summary are locked with witty brain animations until the model is ready — then auto-unlock. No terminal needed.
- **🎙️ Voice Memos** — Hold `Ctrl+Shift+V` → Gemma 4's native audio encoder transcribes. Screenshot captured alongside, full transcript searchable. Audio always saved, even if transcription fails — re-transcribe any time.
- **🎤 Meeting Transcription** — Auto-detects Zoom, Teams, Webex, Slack and Discord apps, plus Google Meet, Teams, Zoom and Webex in a browser tab. Records only after voice is detected, transcribes, and generates structured summaries. Off by default (Settings → Audio).
- **📊 Analytics Dashboard** — Category breakdown, top apps, hourly heatmap, meeting stats, focus metrics.
- **⏪ Day Rewind** — Timelapse playback of your entire day with play/pause/scrub/speed controls.
- **🚀 Desktop Launcher** — Splash screen with auto-open dashboard. Desktop shortcut auto-created on first run.
- **🔄 Run at Startup** — Cross-platform auto-start (Windows Registry, macOS LaunchAgent, Linux XDG). Toggle from Settings or CLI.

### ⚡ Performance

- **Three Analysis Modes** — Accurate (~76s, deep thinking + layout), Balanced (~40s, thinking), or Fast (~12s, no thinking). You choose.
- **Per-App pHash Cache** — 3-tier caching with app-aware staleness. Communication apps refresh faster than IDEs. Significantly fewer inference calls.
- **Chat-First GPU Priority** — Chat cancels in-flight analysis instantly. GPU freed in <1s.
- **Parallel Pipeline** — Dev context detection and embedding generation run concurrently (~2-3s savings per frame).
- **Auto-Pause Heavy Apps** — Games, video editors, 3D software detected → capture pauses automatically.

### 🔒 Privacy & Security

- **100% Local** — All data stays on your machine. No telemetry. Ever. The network is only used to download llama-server and models, and for integrations you turn on.
- **Sensitive Data Filter** — Auto-redacts credit cards, SSNs, API keys, passwords before storage.
- **Encryption at Rest** — AES encryption for screenshots (Fernet, key in the OS keyring).
- **Dashboard PIN Lock** — Salted PBKDF2 PIN, session-based auth with configurable auto-lock timeout.
- **Incognito Mode** — One click: no captures, no bookmarks, no meeting recording.
- **Data Retention** — Screenshots, recordings and history older than N days (default 7) are deleted automatically.

<details>
<summary><b>🔌 Integrations & Extensibility</b></summary>

<br>

| Integration | Description |
|---|---|
| 🤖 **Agent Platform** | Build automations in Markdown (English) or Python. Drop a file, get an agent. |
| 🔌 **MCP Server** | Expose screen history to Claude Desktop, Cursor, VS Code |
| 📓 **Obsidian** | Auto-sync daily summaries to your vault |
| 📋 **Notion** | Push summaries to a Notion database |
| 🪝 **Webhooks** | Fire events to Slack, Discord, IFTTT (HMAC signed, auto-retry) |
| 🔔 **Smart Notifications** | Distraction alerts, break reminders |
| ⭐ **Auto-Bookmark** | Keyword triggers (`git push`, `deploy`) auto-flag important moments |

</details>

### ⌨️ System-Wide Hotkeys

| Hotkey | Action |
|---|---|
| `Ctrl+Shift+B` | 📸 Instant bookmarked capture |
| `Ctrl+Shift+P` | ⏸ Toggle pause/resume |
| `Ctrl+Shift+V` | 🎤 Hold to record voice memo |

> All hotkeys customizable from Settings. On macOS, global hotkeys aren't supported yet — use the dashboard. On Linux they need root or membership in the `input` group.

---

## 📊 How ScreenMind Compares

| Feature | **ScreenMind** | **Screenpipe** | **Microsoft Recall** |
|---|---|---|---|
| **License** | ✅ MIT (fully open-source) | Source-available (commercial license required for business use) | Proprietary |
| **Cost** | ✅ Free forever | Free (personal) / Paid (commercial) | Requires $1000+ Copilot+ PC |
| **Privacy** | ✅ 100% local processing. Zero telemetry. Ever. | Local-first, optional cloud | Telemetry opt-in. Data stayed local after backlash. |
| **Min. hardware** | ✅ Any GPU ≥4GB VRAM (or CPU-only) | 8GB RAM, modern CPU | 40 TOPS NPU + 16GB RAM + BitLocker + Windows Hello |
| **AI architecture** | ✅ Single model family — Gemma 4 (E2B / E4B / 12B) does vision + audio + reasoning | Multiple models — OCR + Whisper + external LLM | Proprietary NPU model |
| **Audio/meetings** | ✅ Native — Gemma 4 audio encoder (no Whisper needed) | Whisper-based transcription | ❌ Not supported |
| **Smart capture** | ✅ pHash deduplication + idle detection + auto-pause for games | Event-driven (app switches, clicks) | Periodic snapshots |
| **Search** | ✅ Semantic (MiniLM embeddings) + FTS5 keyword — hybrid fusion | Semantic + keyword + a11y tree | Semantic only (NPU) |
| **Chat with memory** | ✅ Full conversational RAG with follow-ups and vision fallback | ❌ | ❌ |
| **Agent system** | ✅ No-code Markdown agents + Python SDK + MCP server | Pipes (TypeScript) + MCP | ❌ |
| **In-app Model Hub** | ✅ Download, switch, manage models + variants (Q4_0/Q8_0/BF16) from UI — no terminal | ❌ | ❌ |
| **Encryption** | ✅ AES (Fernet) + OS keyring | Optional | TPM + BitLocker |
| **PII auto-redaction** | ✅ Transparent regex — CC (Luhn-validated), SSN, API keys, passwords | AI-based PII model | Content filtering |
| **Integrations** | ✅ Obsidian · Notion · Webhooks · MCP | MCP, SDK (Tauri/Electron/Swift) | Windows ecosystem only |
| **Platform** | ✅ Windows · macOS · Linux (X11 + Wayland) | Windows · macOS · Linux | Windows 11 only (Copilot+ PCs) |

> **TL;DR:** ScreenMind is the only option that's fully MIT open-source, runs on any hardware (including a $150 GPU), handles vision + audio + reasoning with a single local model, and lets you actually *chat* with your screen memory.

---

## 🧠 How Gemma 4 Is Used

Gemma 4 is not a bolt-on — it's architecturally load-bearing. ScreenMind uses **all three modalities** (E2B shown as default; E4B and 12B also supported):

### 1. Vision — Screenshot Analysis
Every screenshot is sent to Gemma 4 with OCR context. It returns structured JSON:
- App name, activity category, summary, detailed context
- Mood classification, confidence score
- Rich scene description (every visible element inventoried)
- Layout regions (sidebar, chat area, toolbar boundaries)

**Three modes** *(benchmarked on GTX 1650 4GB — scales dramatically with better GPUs):*
- **Accurate** — single call with thinking (~76s). Best layout detection.
- **Balanced** — thinking enabled, analysis-only (~40s). Richer descriptions than Fast.
- **Fast** — no-thinking prefill trick (~12s). Layout via OCR clustering instead.

<details>
<summary><b>⚡ GPU Scaling — How fast on your hardware?</b></summary>

<br>

The numbers above are from a **GTX 1650 (4GB VRAM)** — a worst-case scenario where the model spills to CPU RAM. With more VRAM, the entire model fits on GPU and inference speeds up dramatically:

| GPU | VRAM | Bandwidth | Regime | ~Fast Mode | Why |
|---|---|---|---|---|---|
| **GTX 1650** *(baseline)* | 4 GB | ~190 GB/s | spilling | ~12s | CPU-bottlenecked, partial offload |
| **RTX 3060** | 12 GB | ~360 GB/s | full fit | ~3-4s | Spill eliminated — the big jump |
| **RTX 4060 Ti** | 16 GB | ~290 GB/s | full fit | ~2-3s | Fits easily, more compute for vision |
| **RTX 3090** | 24 GB | ~935 GB/s | full fit | ~1-2s | High bandwidth |
| **RTX 4090** | 24 GB | ~1000 GB/s | full fit | ~1s | Top consumer card |

> **Key insight:** The biggest jump is from "spilling" (model doesn't fit in VRAM) to "full fit" (it does). Any GPU with ≥6GB VRAM should run E2B entirely on GPU and see 3-5x speedup over the baseline.

</details>

### 2. Audio — Voice Memos & Meeting Transcription
Gemma 4's encoder-free architecture handles audio natively across all model sizes. ScreenMind uses it for:
- Voice memo transcription (hold hotkey → speak → release)
- Meeting transcription (15s chunks, map-reduce summarization for long meetings)

No Whisper dependency. One model handles everything.


### 3. Reasoning — Summaries, Chat, Agents
- **Daily summaries** with deep reasoning (`think=True`)
- **Chat answers** grounded in actual screen data (text-first RAG with vision fallback)
- **Agent execution** — Gemma processes markdown agent prompts with injected screen data

### Supported Models

| Model | Variants | VRAM | Audio |
|---|---|---|---|
| **Gemma 4 E2B** (2B) — *default* | Q4_0 · Q8_0 · BF16 | ~4 GB | ✅ |
| **Gemma 4 E4B** (4B) | Q4_0 · Q8_0 · BF16 | ~6 GB | ✅ |
| **Gemma 4 12B** | IQ3_M · Q4_K_M · Q5_K_M · Q6_K · Q8_0 | ~10 GB | ✅ |

E2B is the recommended default — it checks all the boxes:

| Constraint | Why It Rules Out Alternatives |
|---|---|
| Must run **continuously in background** | Rules out 12B+ models on low-VRAM GPUs |
| Must understand **screenshots natively** | Rules out text-only models |
| Must stay **100% local** for privacy | Rules out cloud APIs |
| Must handle **audio natively** | Rules out models without audio encoder |
| Must be **fast enough** for the 40s capture cycle | E2B: 12-76s on GTX 1650, ~1-4s on RTX 3060+ |

If you have more VRAM, E4B offers richer analysis. The 12B model gives the best text reasoning for complex prompts.

> E2B and E4B come from [ggml-org](https://huggingface.co/ggml-org) (official llama.cpp-compatible GGUFs), 12B from [bartowski](https://huggingface.co/bartowski). Models are stored in `~/.screenmind/models/`.

---

## 🚀 Quick Start

> **Requirements:** Python 3.10+ · GPU recommended (4GB+ VRAM) · ~2GB disk for model (E2B Q4_0)

#### 1️⃣ Install

```bash
pip install screenmind
```

#### 2️⃣ Run

```bash
screenmind              # Normal start (foreground)
screenmind --launch     # Splash screen + auto-open dashboard
screenmind --background # Run silently without console window
```

#### 3️⃣ Open → **http://127.0.0.1:7777** 

On first run, ScreenMind will:
- Prompt to install AI packages (~2.5GB one-time download)
- Auto-detect your GPU and download `llama-server` if not found (CUDA/CPU auto-selected)
- Open the **Model Hub** — pick your model + quantization variant, download with progress tracking right in the UI
- Chat and Summary stay locked (🧠💤 *"I need my brain to think!"*) until the model is ready, then auto-unlock
- Start `llama-server` in background (or adopt an already-running external server)
- Show the welcome screen to set up an optional PIN
- Create `~/.screenmind/` for data storage, `~/.screenmind/models/` for GGUF files
- Auto-create a desktop shortcut

<details>
<summary><b>🖥️ More CLI Options</b></summary>

<br>

```bash
screenmind --install-startup    # Register to start at system login
screenmind --uninstall-startup  # Remove from system startup
screenmind --install-shortcut   # Create desktop shortcut
screenmind --version            # Show version
screenmind --help               # Show all options
```

</details>

<details>
<summary><b>🔧 Developer Install (from source)</b></summary>

<br>

```bash
git clone https://github.com/ayushh0110/ScreenMind.git
cd ScreenMind

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -e ".[ai,dev]"
```

</details>

<details>
<summary><b>⚙️ Optional: Configure via .env</b></summary>

<br>

```bash
cp .env.example .env
# Edit capture interval, blocked apps, hotkeys, etc.
```

Or configure everything from the **Settings** tab in the dashboard.

</details>

---

## 🏗️ Architecture

> For a full deep-dive into threading, caching, search internals, and the privacy pipeline, see [**architecture.md**](architecture.md).

```
┌─────────────────────────────────────────────────────────────────────┐
│                          ScreenMind                                  │
│                                                                     │
│  ┌────────────┐    ┌──────────────┐    ┌─────────────────────────┐ │
│  │  Capture   │───▶│  Async Queue │───▶│    Analysis Worker      │ │
│  │  Worker    │    │  (max: 100)  │    │                         │ │
│  │            │    └──────────────┘    │  ┌───────────────────┐  │ │
│  │ • Screen   │                        │  │  Per-App pHash    │  │ │
│  │ • Window   │                        │  │  Cache (3-tier)   │  │ │
│  │ • Dedup    │                        │  └───────────────────┘  │ │
│  │ • A11y     │                        │           │             │ │
│  │ • Privacy  │                        │           ▼             │ │
│  └────────────┘                        │  ┌───────────────────┐  │ │
│                                        │  │   EasyOCR         │  │ │
│  ┌────────────┐                        │  │   (text extract)  │  │ │
│  │   Audio    │                        │  └───────────────────┘  │ │
│  │   Worker   │                        │           │             │ │
│  │            │                        │           ▼             │ │
│  │ • Meeting  │                        │  ┌───────────────────┐  │ │
│  │   detect   │                        │  │   Gemma 4 E2B     │  │ │
│  │ • Record   │                        │  │   (via llama.cpp) │  │ │
│  │ • Transcr. │                        │  │   Vision + Audio  │  │ │
│  └────────────┘                        │  └───────────────────┘  │ │
│                                        │           │             │ │
│  ┌────────────┐                        │           ▼             │ │
│  │   Agent    │                        │  ┌───────────────────┐  │ │
│  │  Scheduler │                        │  │  Layout Analyzer  │  │ │
│  │            │                        │  │  (spatial OCR)    │  │ │
│  │ • .md AI   │                        │  └───────────────────┘  │ │
│  │ • .py code │                        │           │             │ │
│  └────────────┘                        │           ▼             │ │
│                                        │  ┌───────────────────┐  │ │
│                                        │  │  MiniLM-L6-v2     │  │ │
│                                        │  │  (embeddings)     │  │ │
│                                        │  └───────────────────┘  │ │
│                                        └─────────────────────────┘ │
│                                                    │               │
│                                                    ▼               │
│                                        ┌───────────────────┐       │
│                                        │   SQLite (WAL)    │       │
│                                        │   + FTS5 index    │       │
│                                        └─────────┬─────────┘       │
│                                                  │                 │
│  ┌───────────────────────────────────────────────┘                 │
│  │                                                                 │
│  ▼                                                                 │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    FastAPI REST Server                         │ │
│  │  /timeline · /search · /chat · /stats · /agents · /mcp       │ │
│  │                                                               │ │
│  │  ┌───────────────────────────────────────────────────────┐   │ │
│  │  │           Web Dashboard (Vanilla JS SPA)               │   │ │
│  │  │  Timeline · Chat · Search · Analytics · Agents · Settings │ │
│  │  └───────────────────────────────────────────────────────┘   │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### Multi-Model AI Pipeline

```
Screenshot → EasyOCR (text) → Gemma 4 E2B (understanding) → MiniLM (embeddings) → SQLite + FTS5
                                     ↑
                              OCR text fed as context
                              (Gemma sees image + reads text)
```

Four AI models working in concert, with Gemma 4 as the brain:
1. **EasyOCR** — extracts raw screen text
2. **Gemma 4 E2B** — understands what you're doing (vision + reasoning)
3. **MiniLM-L6-v2** — generates semantic vectors for natural language search
4. **FTS5** — indexes text for instant keyword search

---

## 🤖 Agent Platform

ScreenMind includes a full agent/plugin system. Build any automation on top of your screen data.

### Two Modes

| Mode | File Type | For | Example |
|---|---|---|---|
| 🤖 AI Agent | `.md` | Everyone | Write a prompt in English → Gemma runs it on your data |
| 🐍 Python Plugin | `.py` | Developers | Full code with SDK access, state persistence, LLM calls |

### Markdown Agent Example

```markdown
---
name: Daily Focus Report
schedule: every 6h
data: timeline, apps, mood
output: local, obsidian
---

Analyze my screen activity and generate a focus report:
- How many hours of deep work vs shallow work?
- What were my main distractions?
- Give me a focus score out of 10.
```

Drop this file in `~/.screenmind/agents/` and turn on **Settings → Automation → Agent System** — it then runs on its schedule.

### Python Plugin SDK

```python
"""
name: URL Tracker
schedule: every 1h
"""
from screenmind.screenmind_sdk import get_activities, get_urls_visited, load_state, save_state, ask_gemma

def run(context):
    # Today's activities filtered by app
    activities = get_activities(app="Chrome", limit=20)

    # Persistent state across runs
    last_count = load_state("url_count", 0)
    urls = get_urls_visited()
    save_state("url_count", len(urls))

    # Ask Gemma (GPU-safe — waits for the model to be idle)
    insight = ask_gemma(f"Summarize these URLs: {[u['url'] for u in urls[:10]]}")
    return f"{len(urls) - last_count} new URLs.\n\n{insight}"
```

Python plugins must be approved once per session (**✅ Approve & Run**) unless auto-run is enabled. See the full guide: [**Build Your Own Agent**](docs/BUILD_YOUR_OWN_AGENT.md).

### Data Selectors (Frontmatter)

Markdown agents declare what data they need:

| Selector | Injects |
|---|---|
| `timeline` | Recent activities with timestamps, apps, summaries |
| `apps` | App usage counts + category breakdown |
| `urls` | URLs visited (extracted from browser address bars) |
| `meetings` | Meeting summaries and durations |
| `mood` | Mood/sentiment from screen analysis |

Agents receive today's data, sized to your Context Window setting.

### 4 Agents Ship Built-In

- **daily-journal.md** — First-person journal entry from your day
- **focus-report.md** — Focus score, deep work hours, distractions
- **meeting-actions.md** — Action items and decisions from today's recorded meetings (off by default)
- **code-changelog.md** — Summarize coding activity (commits, files, repos)

---

## 🔌 MCP Server (Claude / Cursor / VS Code)

ScreenMind exposes your screen history to any MCP-compatible AI tool:

```bash
python -m screenmind.mcp_server  # stdio transport
```

Install the MCP extra (`pip install "screenmind[mcp]"`), then add ScreenMind to your client. **Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json` on Windows, `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):
```json
{
  "mcpServers": {
    "screenmind": {
      "command": "python",
      "args": ["-m", "screenmind.mcp_server"]
    }
  }
}
```

Claude Code, Cursor and VS Code setup: see [**MCP_SETUP.md**](MCP_SETUP.md).

### Tools Available

| Tool | Description |
|---|---|
| `search_screen` | Semantic + keyword search across all history |
| `get_recent_activity` | Last N activities with full details |
| `get_activity_by_time` | Activities for a specific date/time range |
| `get_daily_summary` | AI-generated daily summary |
| `capture_now` | Trigger instant screenshot |
| `get_stats` | Usage statistics |
| `search_audio` | Search meeting transcripts |
| `get_screenshot` | Screenshot file path for an activity ID |

---

## 📡 API Reference

Full Swagger docs at `http://127.0.0.1:7777/docs`

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/status` | System health, worker stats |
| `GET` | `/api/timeline?date=2026-05-21` | Activities for a date |
| `GET` | `/api/search?q=debugging auth` | Hybrid semantic + keyword search |
| `POST` | `/api/chat` | Conversational AI with screen memory (SSE stream) |
| `GET` | `/api/stats?date_from=…&date_to=…` | Analytics: categories, apps, tracked hours, meetings |
| `GET` | `/api/rewind?date=2026-05-21` | Timelapse frames |
| `POST` | `/api/summary/generate?date=…` | Generate AI daily summary (past dates only) |
| `POST` | `/api/standup/generate?date=…` | Generate standup notes |
| `POST` | `/api/activities/{id}/reanalyze` | Re-analyze a screenshot, or re-transcribe a voice memo |
| `DELETE` | `/api/activities/{id}` | Delete an activity with its screenshot / recording |
| `GET` | `/api/memos?date=…` | Voice memos for a date |
| `GET` | `/api/meetings?date=…` | Meeting transcripts and summaries |
| `GET` | `/api/agents` | List all agents |
| `POST` | `/api/agents/{name}/run` | Trigger agent execution |
| `GET` | `/api/models` | List available models + variants |
| `POST` | `/api/models/variant` | Set preferred quantization variant |
| `POST` | `/api/models/pull` | Download a model variant and start it |
| `POST` | `/api/models/delete` | Delete a downloaded model variant |
| `POST` | `/api/capture/pause` · `/api/capture/resume` | Pause / resume capture |
| `POST` | `/api/capture/bookmark` | Bookmarked screenshot now (refused in incognito) |
| `POST` | `/api/incognito/toggle` | Toggle incognito mode |
| `POST` | `/api/shutdown` | Graceful shutdown (localhost only) |

---

<details>
<summary><h2>⚙️ Configuration</h2></summary>

<br>

Settings can be changed in the **Settings** dashboard (saved to `~/.screenmind/settings.json`), or set as environment variables / in a `.env` file. Every setting in [`screenmind/config.py`](screenmind/config.py) can be set this way using its name in upper case. Values saved from the dashboard take precedence.

| Variable | Default | Description |
|----------|---------|-------------|
| `CAPTURE_INTERVAL` | `40` | Max seconds between captures (10–120) |
| `ANALYSIS_MODE` | `fast` | `fast` (~12s), `balanced` (~40s), or `merged` (~76s, accurate) |
| `PERFORMANCE_MODE` | `balanced` | GPU layers: `minimal` / `balanced` / `maximum` |
| `CONTEXT_WINDOW` | `6144` | llama-server context size (2048–16384) |
| `BLOCKED_APPS` | *(empty)* | Comma-separated apps to never capture |
| `HEAVY_APPS` | `game,valorant,…` | App-name substrings that pause capture (games, editors) |
| `MEETING_TRANSCRIPTION` | `false` | Record and transcribe detected meetings |
| `MEETING_APPS` | `zoom,teams,meet,webex,slack,discord` | Meeting keywords (apps and browser tabs) |
| `RETENTION_DAYS` | `7` | Auto-delete data older than N days (0 = forever) |
| `ENCRYPTION_ENABLED` | `false` | Encrypt screenshots at rest |
| `SENSITIVE_FILTER_ENABLED` | `true` | Redact credit cards, SSNs, API keys, JWTs, passwords |
| `AGENTS_ENABLED` | `false` | Run agents on their schedules |
| `CAPTURE_PAUSED` | `true` | Capture state, persisted across restarts |
| `DATA_DIR` | `~/.screenmind` | Where all data is stored |
| `API_PORT` | `7777` | Dashboard / API port |
| `LLAMA_SERVER_PORT` | `5809` | llama-server port |
| `SCREENMIND_LOG_LEVEL` | `INFO` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SCREENMIND_LOG_FILE` | *(none)* | Path to a log file (rotating, 10MB × 3 backups) |

</details>

---

## 🔧 Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Vision + Audio AI** | Gemma 4 (E2B / E4B / 12B via llama.cpp) | Vision + audio + reasoning, runs locally on 4GB+ VRAM |
| **Inference Server** | llama-server (llama.cpp) | Direct GGUF inference, OpenAI-compatible API |
| **OCR** | EasyOCR | Extracts screen text fed to Gemma as context |
| **Embeddings** | all-MiniLM-L6-v2 | 80MB, runs on CPU, 384-dim vectors for semantic search |
| **Backend** | FastAPI + Uvicorn | Async-first, auto-generated API docs |
| **Database** | SQLite (WAL) + FTS5 | Zero-config, concurrent reads, full-text search |
| **Capture** | mss + ctypes/UI Automation | Native screen capture + accessibility text extraction |
| **Wayland Capture** | grim (wlroots) / XDG Portal | Automatic fallback; no X11 dependency on Wayland |
| **Frontend** | Vanilla JS + CSS | No build step, instant load, dark glassmorphism UI |
| **Platform** | Windows / macOS / Linux (X11 + Wayland) | Abstraction layer with OS-specific adapters |

---

### 🐧 Wayland Support

ScreenMind auto-detects Wayland sessions and uses compositor-native capture:

| Compositor | Capture | Window Detection | Notes |
|---|---|---|---|
| **Sway** | ✅ grim | ✅ swaymsg IPC | Full support |
| **Hyprland** | ✅ grim | ✅ hyprctl IPC | Full support |
| **Niri** | ✅ grim | ✅ niri msg IPC | Full support |
| **river / Wayfire / labwc** | ✅ grim | ⚠️ Title only (no IPC) | Capture works, app name may be unavailable |
| **GNOME (Mutter)** | ⚠️ XDG Portal | ❌ No IPC available | Portal prompts on every capture — not viable for background recording |
| **KDE (KWin)** | ⚠️ XDG Portal | ❌ No IPC available | Same as GNOME |

**Install grim** (recommended for wlroots compositors):
```bash
# Arch
sudo pacman -S grim

# Ubuntu / Debian (if available)
sudo apt install grim

# Fedora
sudo dnf install grim
```

**GNOME / KDE Wayland**: Best-effort only. Screenshots use the XDG Desktop Portal,
which prompts for permission on each capture — not viable for continuous background
recording. For full functionality, use an X11 session or a wlroots-based compositor with grim.

**Optional** (for portal fallback): `python3-gi` / `python-gobject` system package.

---

<details>
<summary><h2>📁 Project Structure</h2></summary>

<br>

```
ScreenMind/
├── screenmind/                   # The Python package
│   ├── main.py                   # Entry point — starts all services, CLI flags
│   ├── config.py                 # Settings (.env + settings.json overrides)
│   ├── launcher.py               # Splash screen launcher (tkinter)
│   ├── startup.py                # Run-at-login registration
│   ├── setup_llama.py            # Detect / download llama-server
│   ├── screenmind_sdk.py         # SDK for Python plugin agents
│   ├── mcp_server.py             # MCP server for Claude / Cursor / VS Code
│   │
│   ├── capture/                  # Screenshot capture layer
│   │   ├── screen.py             # Capture facade (mss / Wayland backend)
│   │   ├── wayland.py            # Wayland backend (grim / XDG Portal)
│   │   ├── window.py             # Active window detection
│   │   ├── dedup.py              # Perceptual hash deduplication
│   │   ├── hotkey.py             # Global hotkeys (bookmark, pause, voice)
│   │   └── voice_recorder.py     # Mic recording for voice memos
│   │
│   ├── engine/                   # AI & intelligence layer
│   │   ├── analyzer.py           # Gemma 4 screenshot analysis (3 modes)
│   │   ├── llm_client.py         # llama-server client (chat, vision, audio)
│   │   ├── model_manager.py      # Server lifecycle, model download/switch
│   │   ├── embedder.py           # MiniLM semantic embeddings
│   │   ├── ocr.py                # EasyOCR text extraction
│   │   ├── layout_analyzer.py    # Spatial OCR organization
│   │   ├── dev_context.py        # Git repo/branch/diff detection
│   │   ├── a11y_extractor.py     # Accessibility text extraction
│   │   ├── agent_runner.py       # Agent scheduling & execution
│   │   ├── voice_memo.py         # Voice memo transcription + storage
│   │   └── browsers.py           # Browser identification per platform
│   │
│   ├── workers/                  # Background processing
│   │   ├── capture_worker.py     # Smart capture loop, privacy, incognito
│   │   ├── analysis_worker.py    # OCR → Gemma → Layout → Embed → Store
│   │   └── audio_worker.py       # Meeting detection & transcription
│   │
│   ├── storage/                  # Data persistence
│   │   ├── database.py           # SQLite + FTS5 + migrations
│   │   ├── files.py              # Screenshot / recording files and cleanup
│   │   └── models.py             # Pydantic data models
│   │
│   ├── privacy/                  # Privacy & security
│   │   ├── encryption.py         # Fernet encryption at rest
│   │   └── data_filter.py        # Sensitive data redaction
│   │
│   ├── platform_support/         # Cross-platform abstraction
│   │   ├── base.py               # PlatformAdapter interface
│   │   ├── windows.py            # Win32 + UI Automation
│   │   ├── macos.py              # Quartz + AXUIElement
│   │   └── linux.py              # xdotool / Wayland IPC + AT-SPI
│   │
│   ├── integrations/             # External connections
│   │   ├── obsidian.py           # Vault markdown export
│   │   ├── notion.py             # Notion API export
│   │   ├── webhooks.py           # HTTP webhooks (named hooks, HMAC, retry)
│   │   └── smart_notify.py       # Distraction / break / focus notifications
│   │
│   ├── api/                      # REST API + dashboard
│   │   ├── server.py             # FastAPI app + PIN middleware
│   │   ├── dependencies.py       # Shared state for routes
│   │   ├── serializers.py        # Response shaping for the dashboard
│   │   ├── routes/               # 16 route modules
│   │   └── static/               # Web dashboard (HTML + CSS + JS)
│   │
│   ├── ui/overlay.py             # On-screen overlay notifications
│   ├── default_agents/           # 4 built-in agents (.md)
│   └── assets/                   # Logo, favicon
│
├── tests/                        # pytest suite
├── docs/                         # BUILD_YOUR_OWN_AGENT.md, screenshots
├── architecture.md               # System design deep-dive
├── MCP_SETUP.md                  # MCP client setup
├── requirements.txt              # Full pinned dependencies
└── requirements-test.txt         # Lightweight CI dependencies (no PyTorch)
```

</details>

---

## 🛡️ Error Handling & Resilience

| Scenario | Behavior |
|----------|----------|
| **llama-server not found** | Auto-downloads correct binary from GitHub releases (CUDA/CPU auto-detected). Checks disk space first. |
| **External llama-server running** | Auto-detects and adopts. Known models show as active; unknown models show amber warning. |
| **Model not downloaded** | Model Hub shows lock screen with download cards. Progress tracked in UI. Chat/Summary locked until ready. |
| **GPU out of memory** | Detects OOM, retries with delay, re-queues on persistent failure. |
| **Duplicate frames** | pHash dedup skips identical screenshots (threshold: 8 hamming distance). |
| **Stale queue items** | Captures >3 min old auto-skipped. Backfilled during idle. |
| **App in blocklist** | Silently skips — no screenshot saved. |
| **Meeting app closed** | Process-alive check (native apps) + silence detection + 5-min timeout away from the meeting. |
| **Voice transcription fails** | Audio + screenshot saved regardless. Playable in the Memos tab, and can be re-transcribed later. `<unusedN>` garbage tokens auto-stripped. |
| **Chat during analysis** | Cancels in-flight inference, frees GPU in <1s, re-queues analysis. |
| **Re-analyze triggered** | Full context (app name, title, URLs) passed — same quality as original analysis. |
| **Crash recovery** | Stale meetings cleaned on startup. Unanalyzed entries backfilled. Capture pause state persisted. |
| **Corrupt settings file** | `settings.json` is written atomically; an unreadable file is kept as `settings.json.corrupt-<timestamp>` instead of being overwritten. |
| **llama-server starts late** | Analysis resumes and meeting transcription becomes available within 30s of the server coming up. |

---

## 🎨 Dashboard

The web dashboard at `http://127.0.0.1:7777` features:

- **Timeline** — Browse activities by date with thumbnails, AI summaries, category badges
- **Chat** — Conversational AI with screen memory. Ask anything about your history. Locked with 🧠💤 brain animation until model is ready.
- **Search** — Semantic + keyword hybrid search with OCR highlighting on screenshots
- **Analytics** — Category and top-app charts, tracked hours, meeting stats and analysis status for a day, week or month
- **Rewind** — Timelapse player with play/pause/scrub/speed controls
- **Memos** — Voice memos with audio player, transcript and re-transcribe
- **Agents** — Create, edit, run, and monitor agents
- **Bookmarks** — Everything you bookmarked (hotkey, menu, or auto-bookmark keywords)
- **Meetings** — Recorded meetings with structured summaries and full transcripts
- **Summary** — AI daily summary and standup notes for any past day
- **Settings** — Model Hub (download/switch models with progress), Shortcuts, Capture, AI, Audio, Privacy, Automation, Integrations, Storage

Dark glassmorphism UI. No build step. Instant load.

---

## 🧪 Development

Run the test suite:

```bash
# Fast (lightweight deps — same as CI, no PyTorch)
pip install -r requirements-test.txt
pip install -e .
pytest --cov=screenmind --cov-report=term-missing -q

# Full (includes the ML stack — sentence-transformers, easyocr)
pip install -e ".[ai,dev]"
pytest --cov=screenmind --cov-report=term-missing -q
```

CI runs on every push/PR (Windows, Python 3.10) with the lightweight deps, plus a JavaScript syntax check and a no-`print()` lint. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 🤝 Contributing

Contributions welcome! See [**CONTRIBUTING.md**](CONTRIBUTING.md) for guidelines. High-impact areas:

- 🍎 **macOS/Linux testing** — platform adapters exist, need real hardware testing
- 🐳 **Docker container** — one-command setup
- 🧩 **Community agent registry** — share agents between users
- 🌐 **Browser extension** — richer URL/tab context
- 📤 **Export formats** — Markdown, CSV, JSON

---

## ⭐ Show Your Support

If you find ScreenMind useful, please consider:

- **⭐ Star this repo** — it helps others discover the project
- **🍴 Fork it** — build your own agents and features
- **🐛 Report issues** — help us improve
- **📣 Share it** — tell others about privacy-first AI

<div align="center">

<br>

<a href="https://github.com/ayushh0110/ScreenMind/stargazers"><img src="https://img.shields.io/github/stars/ayushh0110/ScreenMind?style=social" alt="Stars"></a>
<a href="https://github.com/ayushh0110/ScreenMind/network/members"><img src="https://img.shields.io/github/forks/ayushh0110/ScreenMind?style=social" alt="Forks"></a>

<br>

</div>

---

## 📝 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

<br>

**Built with 🧠 Gemma 4 · 🔒 100% Local · 🚀 Zero Cloud Dependencies**

*Vision + Audio + Reasoning — all three modalities, one model, your machine.*

<br>

<sub>Made with ❤️ by <a href="https://github.com/ayushh0110">ayushh0110</a></sub>

</div>
