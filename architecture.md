# ScreenMind — System Architecture

> **Privacy-First Local Screen Activity Journal + AI Memory**
> Powered by Gemma 4 (E2B / E4B / 12B — Vision + Audio + Reasoning) via llama.cpp

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            ScreenMind                                    │
│                                                                         │
│  ┌──────────────┐   ┌────────────┐   ┌───────────────────────────────┐ │
│  │ Capture      │──▶│ Async Queue│──▶│ Analysis Worker               │ │
│  │ Worker       │   │ (max: 100) │   │                               │ │
│  │              │   └────────────┘   │ pHash Cache → OCR → Gemma 4   │ │
│  │ • mss / grim │                    │ → Layout → Embeddings → Store │ │
│  │ • pHash dedup│                    └───────────────────────────────┘ │
│  │ • A11y text  │                                                      │
│  │ • Privacy    │   ┌────────────┐   ┌───────────────────────────────┐ │
│  └──────────────┘   │ Audio      │   │ Agent Scheduler               │ │
│                     │ Worker     │   │                               │ │
│  ┌──────────────┐   │            │   │ • .md → Gemma prompt          │ │
│  │ Hotkey       │   │ • Detect   │   │ • .py → SDK execution         │ │
│  │ Listener     │   │ • Record   │   │ • Interval scheduling         │ │
│  │              │   │ • Transcr. │   └───────────────────────────────┘ │
│  │ • Bookmark   │   │ • Summary  │                                     │
│  │ • Pause      │   └────────────┘              │                      │
│  │ • Voice memo │                               ▼                      │
│  └──────────────┘                    ┌───────────────────┐             │
│                                      │ SQLite (WAL)      │             │
│                                      │ + FTS5 index      │             │
│                                      │ + Embeddings BLOB │             │
│                                      └─────────┬─────────┘             │
│                                                │                       │
│  ┌─────────────────────────────────────────────┴─────────────────────┐ │
│  │                    FastAPI REST Server (:7777)                     │ │
│  │  /timeline · /search · /chat · /stats · /agents · /rewind · ...   │ │
│  │                                                                   │ │
│  │  ┌───────────────────────────────────────────────────────────┐   │ │
│  │  │              Web Dashboard (Vanilla JS SPA)                │   │ │
│  │  │  Timeline · Chat · Search · Analytics · Memos · Agents    │   │ │
│  │  └───────────────────────────────────────────────────────────┘   │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ┌───────────────────┐                                                 │
│  │ MCP Server (stdio)│ ← Claude Desktop / Claude Code / Cursor / VS Code│
│  │ Separate process  │                                                 │
│  └───────────────────┘                                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

**Core principle:** everything is computed locally. Screenshots, analysis, search, and chat all run on your machine, and there is no telemetry. The network is only used to download llama-server and models, and for integrations you turn on (webhooks, Notion).

---

## 2. Multi-Model AI Pipeline

```
Screenshot
    │
    ├──▶ EasyOCR (text extraction, ~3-10s, CPU)
    │         │
    │         ▼
    ├──▶ Gemma 4 (understanding, 12-76s, GPU)  ◀── OCR text fed as context
    │         │
    │         ├── Structured JSON: app, category, summary, mood, scene
    │         └── Layout regions: sidebar, chat area, toolbar (accurate mode)
    │
    ├──▶ Layout Analyzer (spatial OCR clustering, ~0ms, CPU)  ← fast/balanced modes
    │         │
    │         └── Organized text with [SECTION] headers
    │
    └──▶ MiniLM-L6-v2 (semantic embedding, ~50ms, CPU)
              │
              └── 384-dim vector for similarity search

    All results → SQLite + FTS5
```

Four AI models working in concert:
1. **EasyOCR** — extracts raw screen text (what's written)
2. **Gemma 4** — understands what you're doing (the brain)
3. **Layout Analyzer** — organizes text by screen region (spatial intelligence)
4. **MiniLM-L6-v2** — enables "search by meaning" (semantic vectors)

---

## 3. Component Deep-Dive

### 3.1 Capture Worker

| Property | Detail |
|---|---|
| **Method** | `mss` (Windows, macOS, Linux X11); `grim` or the XDG Desktop Portal on Wayland |
| **Smart polling** | Checks every 5s. Saves on a content change at most every 10s, and always after `capture_interval` (default 40s) |
| **Deduplication** | Perceptual hash (pHash), Hamming distance ≤ 8 counts as unchanged |
| **Idle detection** | After 3+ unchanged checks, only captures every `capture_interval` |
| **A11y extraction** | Accessibility text read at capture time, so it comes from the right window |
| **Privacy** | Blocked apps are skipped; heavy apps (games, editors) pause capture; incognito captures nothing |
| **Output** | JPEG (quality 70) → `~/.screenmind/screenshots/YYYY-MM-DD/HH-MM-SS_mmm.jpg` |
| **Encryption** | Optional Fernet encryption in place after save |

Each saved capture is inserted into the database right away (status `pending`) so it shows on the timeline before analysis finishes.

```
Capture Loop:
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐
│ grab      │──▶│ pHash    │──▶│ A11y text│──▶│ DB insert +  │
│ (5s poll) │   │ dedup    │   │ extract  │   │ queue        │
│ (40s max) │   │          │   │          │   │              │
└──────────┘    └──────────┘   └──────────┘   └──────────────┘
                    │ duplicate?
                    └──▶ skip + delete file
```

### 3.2 Analysis Worker — Per-App pHash Cache (3 Tiers)

Most screenshots are nearly identical to the previous frame of the same window. The cache avoids redundant Gemma calls:

```
New screenshot → compute pHash → compare with cache[(app, title)]
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              ▼                         ▼                         ▼
         Diff 0-3                  Diff 4-10                  Diff 11+
      "IDENTICAL"               "MINOR"                    "FULL"
                                (cache still fresh)        (or cache stale)
    Copy everything           Re-run OCR only           Full pipeline:
    from cache                Reuse Gemma analysis      OCR → Gemma → Layout
    ~0ms                      Reuse layout regions      → Embed → Store
                              ~3-10s                    ~12-76s
```

| Tier | When | What Runs | Time |
|---|---|---|---|
| Identical (≤3) | Cursor blink, clock tick | Nothing — copy from cache | ~0ms |
| Minor (4-10) | Typing, scrolling — while the cached analysis is younger than 4 min (chat/mail apps) or 7 min (everything else) | OCR + text organization | ~3-10s |
| Full (11+, or stale cache) | App switch, new page | Everything | 12-76s |

The cache is an LRU of 30 entries keyed by `(app_name, window_title[:100])`. Bookmarked captures always get a full analysis.

Captures older than 3 minutes when they reach the front of the queue are marked `skipped`; when the queue is idle, skipped, pending and failed captures from today are re-analyzed one at a time (backfill).

### 3.3 Gemma 4 — Three Analysis Modes

| Mode | Method | Time | Layout Source |
|---|---|---|---|
| **Accurate** (`merged`) | Single call WITH thinking | ~76s | Gemma detects regions |
| **Balanced** | Analysis-only WITH thinking | ~40s | OCR bounding box clustering |
| **Fast** (default) | No-thinking prefill trick | ~12s | OCR bounding box clustering |

**Accurate mode:** one prompt asks for both layout regions (coordinates) and the activity analysis. Gemma uses its thinking budget to reason about spatial boundaries.

**Balanced mode:** the same analysis-only prompt as fast, but Gemma thinks naturally. Produces a richer `scene_description` and `activity_summary` than fast mode, without the layout overhead.

**Fast mode:** pre-fills an empty `<think>\n</think>\n` block in the assistant message, so Gemma skips reasoning and answers immediately.

The app name is reconciled from three signals — window title, OS process name and Gemma's visual guess — and the category is overridden for known apps (terminals, chat apps, editors). On macOS the OS-reported app name is trusted first, because window titles there rarely end with the app name.

### 3.4 Layout Analyzer — Spatial OCR Organization

Transforms raw OCR boxes into structured, section-labeled text:

```
Input: 200 OCR boxes with (x, y, width, height, text, confidence)
       + Layout regions [{"name": "nav_sidebar", "x_start": 0.0, "x_end": 0.15, ...}]

Process:
  1. Sort regions narrow-first (sidebar before main content)
  2. Classify each OCR box into a region by center-point
  3. Within chat regions: detect timestamps → attribute messages to senders
  4. Within other regions: group by Y-proximity (25px) into visual lines

Output:
  [NAV SIDEBAR]
  Home | Messages | Settings

  [CHAT MESSAGES]
  Alice: Hey, did you push the fix? | What's the status?
  Bob: Just merged it | Tests passing now

  [PROFILE PANEL]
  Alice | Online | Member since 2024
```

This organized text is what chat uses as context — not raw OCR dumps.

### 3.5 Chat — Text-First RAG with Vision Fallback

```
User question (+ context range: today / 7 days / 30 days / all)
      │
      ▼
┌─────────────────────┐
│ 1. Extract keywords │  Remove stopwords, keep meaningful terms
│ 2. Casual check     │  "hi", "thanks", "tell me a joke" → chatbot mode
└──────────┬──────────┘
           │
           ▼
┌──────────────────────┐
│ FTS5 probe           │  OR of keywords, within the context range
└──────────┬───────────┘
     ┌─────┴──────────────────────┐
   MATCH                       NO MATCH
     │                            │
     ▼                            ▼
┌──────────────────────┐   ┌──────────────────────────────┐
│ Re-rank candidates   │   │ Semantic search over the 500 │
│ 0.7 semantic         │   │ most recent activities;      │
│ 0.2 recency          │   │ use only if relevance ≥ 0.35 │
│ 0.1 FTS rank         │   └──────────────┬───────────────┘
└──────────┬───────────┘           (else chatbot mode)
           ▼                              │
     Top 5 activities ◀───────────────────┘
           │
           ▼
  Has organized/OCR text?  YES → text mode (send the text)
                           NO  → vision mode (send the screenshot)
  Empty answer → retry, then fall back to vision

GPU priority: chat cancels in-flight analysis → GPU freed in <1s → analysis re-queued at the front
```

### 3.6 Audio Worker — Meeting Transcription

Meeting transcription is off by default (`meeting_transcription`). It needs an audio-capable model and a reachable llama-server; if the server comes up after ScreenMind, transcription becomes available within 30 seconds.

```
Meeting Detection (CaptureWorker, every 5s — even when capture is paused,
                   never in incognito):

  Native app?  process name contains a meeting_apps keyword
               (zoom, teams, meet, webex, slack, discord)
  Browser?     window title matches a meeting tab, e.g.
               "Meet - abc-defg-hij", "Google Meet - <browser>",
               "<page> | Microsoft Teams", "Zoom Meeting - <browser>", "Webex"
      │
      YES → audio probe: 2s mic, then 2s system audio (RMS > 0.008)
      │         │
      │    2 voice probes within 20s → START RECORDING
      │
  Recording loop (15s chunks):
      │
      ├── Mic and system audio recorded in parallel, transcribed separately
      │   → "[You] ..." / "[Others] ..." lines via llm_client.transcribe_audio()
      │
      └── Stop signals:
            • 3 consecutive silent chunks (~45s)
            • Native app's process gone (checked after 30s away; watches the
              process the OS reported for the meeting window + known aliases)
            • 5 min away from the meeting window
            • Incognito turned on

  On Stop:
      │
      ▼
  Map-Reduce Summarization:
      Short (≤4000 chars): single Gemma call → structured summary
      Long (>4000 chars):  split into ~3000 char chunks
                           → summarize each chunk
                           → combine into the final summary
                           (TOPICS / PROBLEMS / SOLUTIONS / ACTION ITEMS)
```

Browser-tab patterns are anchored to how each service titles its own tab, so a video or search *about* Zoom or Teams doesn't start a recording. Each pattern applies only while its keyword is in `meeting_apps`.

**Voice memos:** hold the voice hotkey to record; release to stop. The WAV goes to `~/.screenmind/memos/YYYY-MM-DD/` with a screenshot. The full transcript is stored (searchable, readable in chat), and a memo is always saved even if transcription fails, so the audio stays playable. "Re-transcribe" runs transcription again on the saved WAV.

Gemma 4 handles audio natively — no Whisper dependency.

### 3.7 Agent System

```
~/.screenmind/agents/
├── daily-journal.md       ← Markdown agent (Gemma-powered)
├── focus-report.md        ← Markdown agent
├── meeting-actions.md     ← Markdown agent (disabled by default)
├── code-changelog.md      ← Markdown agent
├── my-tracker.py          ← Python plugin (SDK)
├── output/<agent>/        ← Saved outputs
├── state/<agent>.json     ← Plugin state
└── run_log.json           ← Last 30 runs
```

The scheduler runs only when the **Agent System** setting is on (off by default) and a model server is running. It checks every 60 seconds; schedules are `every <N>m`, `every <N>h` or `daily`.

**Markdown agents:**
```
Frontmatter → schedule, data sections, output destinations
    │
    ▼
Data injection → today's timeline / apps / urls / meetings / mood from the DB
    │              (sized to the context window: 800–12,000 chars)
    ▼
Gemma 4 → generate response
    │
    ▼
Route output → local file (always) + Obsidian vault / webhooks (Slack, Discord)
```

**Python plugins:**
```python
# SDK: get_activities(), get_urls_visited(), get_meetings(), search(),
#      save_state(), load_state(), ask_gemma(), notify(), capture_now()
# GPU-safe: ask_gemma() waits up to 60s for the model to be idle
# State isolation: one JSON file per agent in agents/state/
# Safety: plugins must be approved (per app session) unless auto-run is on
```

See [docs/BUILD_YOUR_OWN_AGENT.md](docs/BUILD_YOUR_OWN_AGENT.md).

### 3.8 Inference Priority & Cancellation

```
                    ┌─────────────────────┐
                    │   llama-server      │
                    │   (single slot)     │
                    │   --parallel 1      │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
         Analysis          Chat            Audio / Agents
         (background)      (user-facing)
              │                │
              │    User sends chat message
              │         │
              │         ▼
              │    cancel_current_inference()
              │         │
              │         ├── Set _cancel_event flag
              │         └── Close httpx.Client → llama-server frees the slot
              │
              ▼
         InferenceCancelled raised
              │
              └── Re-queue at FRONT of the priority deque
                  (processed before new queue items)
```

Every request is sent with `cache_prompt: true`, so llama-server reuses the cached prefix shared between requests (system prompts, analysis instructions) instead of re-processing it.

---

## 4. Storage Layer

### Data directory (`~/.screenmind/`)

| Path | Contents |
|---|---|
| `screenmind.db` | SQLite database (below) |
| `settings.json` | Settings changed from the dashboard. Written atomically; an unreadable file is kept as `settings.json.corrupt-<timestamp>` |
| `screenshots/YYYY-MM-DD/` | Screenshots (optionally encrypted) |
| `memos/YYYY-MM-DD/` | Voice memo recordings (WAV) |
| `models/` | GGUF models and vision/audio projectors |
| `agents/` | Agents, their outputs, state and run log |
| `webhook_log.db` | Webhook delivery log (last 200) |
| `llama/` | llama-server binaries (pip installs; source checkouts use `./llama/`) |
| `screenmind.log` | Log file in `--background` mode |

### SQLite schema (WAL mode, FTS5)

```sql
activities (
    id, timestamp, screenshot_path, window_title, detected_app,
    bookmarked, app_name, category, summary, details, visible_text,
    mood, confidence, embedding (BLOB), ocr_text, ocr_boxes (JSON),
    scene_description, organized_text, analyzed, analysis_error,
    analysis_method, active_url,
    status,        -- pending | ok | skipped | failed | dead
    created_at
)

dev_contexts (
    id, activity_id → activities(id), repo_name, branch,
    last_commit, changed_files (JSON), insertions, deletions
)

meetings (
    id, start_time, end_time, app_name, duration_minutes,
    transcript, summary, created_at
)

daily_summaries (
    id, date (UNIQUE), summary, standup, total_activities,
    category_breakdown (JSON), top_repos (JSON), productive_hours,
    created_at
)

schema_version (version)   -- versioned migrations (currently v7)

-- FTS5 virtual table, kept in sync by triggers
activities_fts (summary, details, ocr_text, app_name, scene_description, organized_text)

-- Indexes
idx_activities_timestamp, idx_activities_category, idx_activities_app,
idx_activities_bookmarked, idx_activities_analyzed, idx_activities_status,
idx_dev_repo, idx_dev_branch, idx_dev_activity
```

Timestamps are stored as naive **local** time (ISO format), and all date filters use the local calendar.

For voice memos, `details` holds the WAV path and `ocr_text` the full transcript. Deleting an activity — one at a time, "Clear Timeline", or data retention — also deletes its screenshot and memo recording.

### Embedding storage

| Property | Detail |
|---|---|
| **Model** | all-MiniLM-L6-v2 (80MB, CPU) |
| **Dimensions** | 384 floats |
| **Storage** | BLOB column in `activities` (`struct.pack`) |
| **Search** | The 500 most recent embeddings → numpy cosine similarity |
| **What's embedded** | summary + scene_description + details + app_name + category + visible text |

### Search: hybrid (semantic + keyword + meetings)

```
User query: "debugging auth"
      │
      ├──▶ MiniLM embed → cosine similarity vs stored vectors → ranked results
      │
      ├──▶ FTS5 MATCH "debugging auth" (phrase) → keyword matches
      │         (a result found by both is boosted and marked "hybrid")
      │
      └──▶ Meeting transcript/summary LIKE search → meeting results

      Merge + deduplicate → sort by relevance score → return top N
```

---

## 5. Privacy & Security Layer

```
┌─────────────────────────────────────────────────────────┐
│                    Privacy Pipeline                       │
│                                                         │
│  Capture Time:                                          │
│    • App blocklist (skipped entirely)                   │
│    • Heavy-app auto-pause (games, video editors)        │
│    • Incognito: no captures, no bookmark captures,      │
│      no meeting detection or recording                  │
│                                                         │
│  Before AI + Storage:                                   │
│    • Sensitive data filter (regex-based redaction)      │
│      - Credit cards (Luhn-validated) → [REDACTED:card]  │
│      - SSNs → [REDACTED:ssn]                            │
│      - API keys: OpenAI, Anthropic, Stripe, GitHub,     │
│        GitLab, AWS, Slack, Google, Notion, webhook      │
│        secrets → [REDACTED:key]                         │
│      - JWTs → [REDACTED:jwt]                            │
│      - Passwords (key=value patterns)                   │
│      - Email addresses (optional, off by default)       │
│                                                         │
│  At Rest:                                               │
│    • Optional Fernet encryption (screenshots)           │
│    • Key in the OS keyring, with a backup key file      │
│      (.encryption_key, mode 0600 on macOS/Linux)        │
│    • Magic header identifies encrypted files            │
│    • Transparent read: encrypted/unencrypted handled    │
│                                                         │
│  Access Control:                                        │
│    • Dashboard PIN (PBKDF2-SHA256, salted, 100k rounds) │
│    • HttpOnly session cookie, configurable timeout      │
│    • Middleware blocks the API without a session        │
│      (SDK/MCP endpoints are allowed from localhost)     │
│                                                         │
│  Data Retention:                                        │
│    • On startup, deletes activities, screenshots, memo  │
│      recordings, meetings and summaries older than N    │
│    • 1-365 days (default 7); 0 = keep forever           │
└─────────────────────────────────────────────────────────┘
```

---

## 6. Platform Abstraction

```
platform_support/
├── base.py          ← PlatformAdapter ABC
├── windows.py       ← Win32 ctypes + UI Automation
├── macos.py         ← Quartz window list + AXUIElement (pyobjc)
└── linux.py         ← xdotool/xprop (X11), compositor IPC (Wayland) + AT-SPI

Capabilities per platform:
┌──────────────┬─────────────────┬──────────────────┬───────────────────────┐
│ Feature      │ Windows         │ macOS            │ Linux                 │
├──────────────┼─────────────────┼──────────────────┼───────────────────────┤
│ Window title │ ctypes user32   │ Quartz           │ xdotool / xprop;      │
│              │                 │ (CGWindowList)   │ swaymsg, hyprctl,     │
│              │                 │                  │ niri msg on Wayland   │
│ App name     │ process image   │ window owner     │ /proc/<pid>/comm;     │
│              │ name            │ (Quartz)         │ app_id on Wayland     │
│ A11y text    │ UI Automation   │ AXUIElement      │ AT-SPI                │
│ Screenshot   │ mss             │ mss              │ mss; grim / XDG Portal│
│ Hotkeys      │ keyboard lib    │ not supported    │ keyboard lib (needs   │
│              │                 │ (use dashboard)  │ root / input group)   │
└──────────────┴─────────────────┴──────────────────┴───────────────────────┘
```

Browser identification (for meeting detection and app categories) is shared in `engine/browsers.py`, covering Windows process names, Linux X11/Wayland/Flatpak IDs and macOS app names.

---

## 7. Integrations & Extensibility

```
┌─────────────────────────────────────────────────────────────────┐
│                        Output Channels                           │
│                                                                 │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌────────────────┐  │
│  │Obsidian │  │ Notion  │  │ Webhooks │  │ MCP Server     │  │
│  │ Export  │  │ Export  │  │ (HTTP)   │  │ (stdio)        │  │
│  │         │  │         │  │          │  │                │  │
│  │ .md to  │  │ API push│  │ Slack    │  │ Claude Desktop │  │
│  │ vault   │  │ to DB   │  │ Discord  │  │ Claude Code    │  │
│  │         │  │         │  │ IFTTT    │  │ Cursor         │  │
│  └─────────┘  └─────────┘  │ Zapier   │  │ VS Code        │  │
│                             │ Custom   │  │                │  │
│                             │          │  │ 8 tools:       │  │
│                             │ Named    │  │ search, recent │  │
│                             │ profiles │  │ by_time, stats │  │
│                             │ HMAC sig │  │ summary, audio │  │
│                             │ Retry x1 │  │ capture, image │  │
│                             │ Log 200  │  │                │  │
│                             └──────────┘  └────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   Smart Notifications                     │  │
│  │  • Distraction alert (N min on entertainment)            │  │
│  │  • Break reminder (N min continuous work)                │  │
│  │  • Focus streak (2+ hours of coding in one app)          │  │
│  │  • Auto-bookmark (keyword triggers: git push, deploy)    │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Webhooks** support a default hook plus named extra profiles, each with its own URL(s), events, HMAC secret (`X-ScreenMind-Signature: sha256=...`) and custom headers. Failed deliveries are retried once after 5 seconds, and the last 200 deliveries are kept in `webhook_log.db`. Events sent today:

| Event | When |
|---|---|
| `daily_summary` | A daily summary or standup is generated |
| `bookmark` | A capture is auto-bookmarked by keyword |
| `agent_output` | An agent with `output: webhook` / `webhook:<name>` finishes |

The Settings page also lists `standup`, `meeting_end` and `capture_milestone`; these aren't emitted yet.

---

## 8. Performance Characteristics

| Metric | Value | Notes |
|---|---|---|
| Screenshot capture | ~50ms | mss grab + JPEG compress |
| pHash computation | ~15ms | imagehash.phash() |
| OCR extraction | 3-10s | EasyOCR on CPU (uses GPU if available) |
| Gemma 4 (accurate) | ~76s | Single call with thinking, GTX 1650 4GB |
| Gemma 4 (balanced) | ~40s | Thinking, layout via OCR clustering |
| Gemma 4 (fast) | ~12s | No-thinking prefill, same GPU |
| Embedding generation | ~50ms | MiniLM on CPU |
| Cache hit (identical) | ~0ms | Copy from memory |
| Cache hit (minor) | ~3-10s | OCR only, skip Gemma |
| Chat response | ~5-15s | Text mode. Vision mode: ~15-30s |
| Disk per day | ~80-150MB | Screenshots + DB (8hr active use, 40s interval) |
| RAM usage | ~1.5-2GB | Python + EasyOCR + MiniLM (Gemma runs in llama-server) |
| VRAM usage | ~3-4GB | Gemma 4 E2B Q4_0 (default). E4B ~6GB, 12B ~10GB |

### Resource Management

| Setting | Effect |
|---|---|
| Performance Mode: minimal | 0 GPU layers (CPU inference, slow but frees VRAM) |
| Performance Mode: balanced | 15 GPU layers (default) |
| Performance Mode: maximum | 99 GPU layers (all on GPU) |
| Context Window | `-c` for llama-server (default 6144). Lower saves VRAM; also sizes summary and agent prompts |
| Deferred Analysis | Queue captures, analyze only after 60s with no new captures |
| Auto-Pause Heavy Apps | Skip capture when games/editors are in the foreground |
| KV Cache Quantization | K cache q8_0, V cache q4_0. Saves VRAM, adds ~10s per inference (off by default) |
| Flash Attention | Faster + less VRAM (on by default) |

---

## 9. End-to-End Data Flow

```
┌─────────┐     ┌─────────┐     ┌──────────────────────────────────────┐
│  User   │     │ Screen  │     │         Analysis Pipeline            │
│  works  │────▶│ changes │────▶│                                      │
└─────────┘     └─────────┘     │  1. A11y text (at capture time)      │
                                │  2. pHash cache check                │
                                │     ├─ identical → done (0ms)        │
                                │     ├─ minor → OCR only (3-10s)      │
                                │     └─ full → continue               │
                                │  3. EasyOCR extraction               │
                                │  4. Sensitive data redaction          │
                                │  5. URL extraction                   │
                                │  6. Gemma 4 analysis (+ layout)      │
                                │  7. Organize text by regions         │
                                │  8. Git context (if coding)          │
                                │  9. MiniLM embedding                 │
                                │ 10. Store all to SQLite              │
                                │ 11. Focus-streak + auto-bookmark     │
                                └──────────────────────────────────────┘
                                                 │
                                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         User Queries                                  │
│                                                                      │
│  Timeline → browse by date                                           │
│  Search → semantic + keyword hybrid                                  │
│  Chat → RAG (text-first, vision fallback, conversation history)      │
│  Analytics → categories / apps / hours for a day, week or month      │
│  Rewind → timelapse playback                                         │
│  Summary → Gemma summary and standup notes over the day's activities │
│  Agents → scheduled automations on screen data                       │
│  MCP → external AI tools query screen history                        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 10. Why Gemma 4

### Supported Models

| Model | Variants | VRAM | Audio | Source |
|---|---|---|---|---|
| **Gemma 4 E2B** (2B) — *default* | Q4_0 · Q8_0 · BF16 | ~4 GB | ✅ | ggml-org |
| **Gemma 4 E4B** (4B) | Q4_0 · Q8_0 · BF16 | ~6 GB | ✅ | ggml-org |
| **Gemma 4 12B** | IQ3_M · Q4_K_M · Q5_K_M · Q6_K · Q8_0 | ~10 GB | ✅ | bartowski |

GGUF files and vision/audio projectors are downloaded from Hugging Face into `~/.screenmind/models/`. The Model Hub lets you download, switch, and delete variants from the dashboard, and an externally started llama-server is detected and adopted.

E2B is the recommended default:

| Constraint | Why It Rules Out Alternatives |
|---|---|
| Must run **continuously in background** | Rules out large models on low-VRAM GPUs |
| Must understand **screenshots natively** | Rules out text-only models |
| Must stay **100% local** for privacy | Rules out cloud APIs (Gemini, GPT-4V) |
| Must handle **audio natively** | Rules out models without an audio encoder |
| Must be **fast enough** for the 40s capture cycle | E2B: 12s (fast) to 76s (accurate) on a GTX 1650 |

With more VRAM, E4B gives richer analysis and 12B the strongest text reasoning.

---

## 11. Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Vision + Audio AI** | Gemma 4 (E2B / E4B / 12B) via llama.cpp | Vision + audio + reasoning, runs locally on 4GB+ VRAM |
| **Inference Server** | llama-server (llama.cpp) | Direct GGUF, OpenAI-compatible API |
| **OCR** | EasyOCR | Screen text fed to Gemma as context |
| **Embeddings** | all-MiniLM-L6-v2 | 80MB, CPU, 384-dim vectors |
| **Backend** | FastAPI + Uvicorn | Async, auto-docs, serves the dashboard |
| **Database** | SQLite (WAL) + FTS5 | Zero-config, concurrent reads, full-text search |
| **Capture** | mss; grim / XDG Portal on Wayland | Native capture on every platform |
| **Accessibility** | UI Automation / AXUIElement / AT-SPI | Exact on-screen text |
| **Frontend** | Vanilla JS + CSS (Chart.js for charts) | No build step, instant load |
| **Platform** | Windows / macOS / Linux (X11 + Wayland) | OS-specific adapters |
| **Agents** | Interval scheduler + SDK | Markdown (Gemma) + Python (code) |
| **MCP** | mcp[cli] (stdio transport) | Claude Desktop / Claude Code / Cursor / VS Code |
