# Build Your Own Agent

ScreenMind's agent system lets you create automations that run on your screen data. Agents are simple files in `~/.screenmind/agents/`, in one of two forms:

- **Markdown agents** (`.md`): a prompt in plain English. ScreenMind injects your screen data and runs it through the local Gemma model.
- **Python plugins** (`.py`): code with full programmatic control through the ScreenMind SDK.

## Before You Start

1. **Turn on the agent system:** Settings → Automation → **Agent System**. It is off by default; while it's off, nothing runs on a schedule. "Run Now" works either way.
2. **A model must be running.** The scheduler only runs agents while llama-server is up (Model Hub shows the model as ready).

Four agents ship with ScreenMind and are copied into your agents folder on first run: `daily-journal`, `focus-report`, `code-changelog`, and `meeting-actions` (off by default).

## Quick Start

### Option 1: Markdown agent (no coding)

Create `~/.screenmind/agents/my-agent.md`:

```markdown
---
name: My Custom Agent
schedule: every 2h
description: Describe what your agent does
enabled: true
output: local
data: timeline, apps
---
Your instructions to the AI go here.

Tell it what to analyze, extract, or summarize from your screen data.
Be specific about the output format you want.
```

ScreenMind runs your prompt on the schedule, with today's screen data appended after it.

### Option 2: Python plugin (full control)

Create `~/.screenmind/agents/my_plugin.py`. Metadata goes in the module docstring, which must be the very first thing in the file:

```python
"""
name: My Python Agent
schedule: every 1h
description: A custom Python plugin
enabled: true
output: local
"""
from screenmind.screenmind_sdk import get_recent_activity

def run(context):
    # context["agent_name"] — sanitized agent name (used for state files)
    # context["timestamp"]  — run start time, UTC ISO format
    # context["data_dir"]   — path to ~/.screenmind
    activities = get_recent_activity(minutes=60)
    return f"Processed {len(activities)} activities"
```

`run(context)` is called with the context dict; whatever it returns (converted to a string) becomes the agent's output.

> **Python plugins run inside the ScreenMind process with your user's permissions.** Only run code you wrote or trust. ScreenMind asks for approval before running a plugin (see [Approving Python plugins](#approving-python-plugins)).

Files whose names start with `_` are ignored, so you can keep helpers like `_utils.py` next to your agents.

## Frontmatter Reference

### Common fields (`.md` and `.py`)

| Field | Default | Description |
|---|---|---|
| `name` | filename | Display name in the UI |
| `schedule` | `every 6h` (`.md`), `every 1h` (`.py`) | `every <N>m`, `every <N>h`, or `daily`. Anything else means every 6h |
| `description` | (empty) | One-line description shown in the UI |
| `enabled` | `true` | Whether the agent runs on schedule (`true`/`yes`/`1`) |
| `output` | `local` | Where output goes — see [Output destinations](#output-destinations) |

The scheduler checks every 60 seconds. Last-run times are kept in memory, so after ScreenMind restarts each enabled agent runs once on the first check.

### Markdown-only fields

| Field | Default | Description |
|---|---|---|
| `data` | `timeline, apps` | Which data sections to inject (below) |
| `model_requirement` | `0` | Context window (tokens) the agent works best with, e.g. `8192`. If your configured context window is smaller, the output starts with an upgrade hint |

### Data sections

Markdown agents receive **today's** data, limited to analyzed activities:

| Section | What it includes |
|---|---|
| `timeline` | Recent activities: time, app, category, short summary, site |
| `apps` | Top apps and activity categories with capture counts |
| `urls` | Most visited URLs (from browser address bars) |
| `meetings` | Today's recorded meetings: time, app, duration, AI summary |
| `mood` | Mood breakdown from screen analysis |

```yaml
data: urls, timeline          # research logging, AI tool tracking
data: apps, timeline          # time tracking, productivity reports
data: meetings, timeline      # meeting follow-ups, action items
data: urls, apps, meetings, mood, timeline   # everything (needs a larger context)
```

The injected data is sized to your **Context Window** setting: roughly 4 characters per token of what's left after the prompt and answer, between 800 and 12,000 characters. The timeline fills whatever budget remains, so a smaller context window means fewer activities.

## Output Destinations

Every successful run is **always** saved locally to `~/.screenmind/agents/output/<agent-file-name>/<YYYY-MM-DD_HH-MM>.md` — that's what the **📄 Outputs** button shows. `output` adds more destinations (comma-separated):

| Destination | What happens |
|---|---|
| `local` | Only the local copy above |
| `obsidian` | Also written to `<vault>/ScreenMind/Agents/<name>/<YYYY-MM-DD>.md` (one file per day, replaced on each run). Needs Obsidian export enabled with a vault path in Settings |
| `webhook` | Also POSTed to your default webhook (Settings → Webhooks) |
| `webhook:<hook-name>` | Also POSTed to a named extra webhook, e.g. `webhook:discord` |

Example: `output: local, obsidian, webhook:discord`

Webhook payloads are JSON with `event: "agent_output"`, the agent name and its output (first 1,900 characters, to fit Discord's limit).

## Approving Python Plugins

Unless **Auto-run Python plugins** is on (Settings → Automation), a Python plugin must be approved before it runs:

- New and unapproved plugins show **✅ Approve & Run** on their card.
- Scheduled runs of an unapproved plugin are skipped and logged as needing approval.
- Approval lasts until ScreenMind restarts.

## SDK Reference (Python plugins)

```python
from screenmind.screenmind_sdk import (
    # Data access
    get_recent_activity,     # Today's activities from the last N minutes
    get_activities_by_date,  # Activities for a date (YYYY-MM-DD)
    get_activities,          # Filtered query: date, app, category, url_contains
    get_urls_visited,        # Unique URLs for a date, with visit counts
    get_meetings,            # Meetings for a date
    get_app_usage,           # Capture counts and categories per app
    search,                  # Semantic + keyword search across all history
    get_summary,             # Daily AI summary text for a date
    get_stats,               # The app's /api/status (capture/analysis/model state)

    # Persistent state
    save_state, load_state, clear_state,

    # AI
    ask_gemma,               # Ask the local model a question

    # Actions
    notify,                  # Show an on-screen notification
    capture_now,             # Take a bookmarked screenshot
    write_file,              # Write a file inside ~/.screenmind
    get_output_dir,          # This agent's output folder
)
```

The SDK talks to the running ScreenMind app over its local API, so plugins work when they're run by ScreenMind (scheduled or Run Now).

### Data access examples

```python
# Activities filtered by app (exact app name as shown in the timeline)
coding = get_activities(app="Code", limit=20)

# Activities whose URL contains "github.com"
github = get_activities(url_contains="github.com")

# Unique URLs visited today
for u in get_urls_visited():
    print(f"{u['url']} — visited {u['count']}x")

# App usage: {"Code": {"captures": 45, "categories": ["coding"]}, ...}
usage = get_app_usage()

# Search all history
results = search("machine learning paper")
```

Notes:
- `get_activities`, `get_urls_visited` and `get_app_usage` default to today and only include analyzed activities.
- If you set a **dashboard PIN**, `search()`, `get_meetings()` and `get_summary()` return empty results, because those endpoints require the dashboard login. The other SDK calls keep working.
- `capture_now()` captures nothing while **incognito mode** is on.

### Persistent state

State is stored per agent in `~/.screenmind/agents/state/<agent>.json` (values must be JSON-serializable):

```python
save_state("last_checked", "2026-05-21T10:00:00")
save_state("tracked_items", [{"task": "Review PR", "done": False}])

items = load_state("tracked_items", [])   # default if missing

clear_state("tracked_items")   # one key
clear_state()                  # everything
```

### Ask Gemma

```python
answer = ask_gemma("Summarize the main topics from these activities: ...")

# Prepend the last 30 minutes of activity as context
answer = ask_gemma("What was I working on?", include_recent=True)

# Shorter answers
topic = ask_gemma("One-word topic for: ...", max_tokens=64)
```

`ask_gemma()` never interrupts screen analysis: it waits up to 60 seconds for the model to be idle and raises `RuntimeError` if it stays busy (or if inference fails). Catch it, and avoid calling it in tight loops — on GPUs with ≤4 GB VRAM it may time out during heavy capture.

## Example Agents

### Standup report (Markdown)

```markdown
---
name: Standup Report
schedule: daily
description: Generate a daily standup report
data: apps, timeline
---
Generate a standup report with three sections:
1. **What I did** — summarize work from the timeline
2. **What's next** — infer from recent patterns
3. **Blockers** — anything that seemed stuck or repetitive

Format as bullet points. Be concise.
```

### Brand listener (Python)

```python
"""
name: Brand Listener
schedule: every 30m
description: Alerts when brand keywords appear on screen
enabled: true
"""
from screenmind.screenmind_sdk import search, notify, save_state, load_state

KEYWORDS = ["ScreenMind", "my-company"]

def run(context):
    last_seen = load_state("last_id", 0)
    found = []

    for kw in KEYWORDS:
        for r in search(kw, limit=5):
            rid = r.get("id")
            if isinstance(rid, int) and rid > last_seen:   # meeting results use string IDs
                found.append(f"{kw}: {r.get('summary', '?')}")
                last_seen = max(last_seen, rid)

    save_state("last_id", last_seen)

    if found:
        notify("Brand Alert", f"{len(found)} mention(s) found!")
        return "## Brand Mentions\n" + "\n".join(f"- {f}" for f in found)
    return "No new brand mentions."
```

### Research logger (Python)

```python
"""
name: Research Logger
schedule: every 2h
description: Logs research sessions with sources
enabled: true
"""
from screenmind.screenmind_sdk import get_urls_visited, save_state, load_state, ask_gemma

RESEARCH_SITES = ["arxiv", "scholar.google", "stackoverflow", "docs.", "wiki"]

def run(context):
    sessions = load_state("sessions", [])
    research = [u for u in get_urls_visited() if any(s in u["url"] for s in RESEARCH_SITES)]

    if research:
        url_text = "\n".join(f"- {u['url']} ({u['count']}x)" for u in research[:8])
        try:
            topic = ask_gemma(
                f"What research topic connects these URLs?\n{url_text}\n"
                "Reply with a single topic name.",
                max_tokens=64,
            ).strip()
        except RuntimeError:
            topic = "Unknown topic"
        sessions.append({
            "date": context["timestamp"][:10],
            "topic": topic,
            "sources": len(research),
            "urls": [u["url"] for u in research[:5]],
        })
        save_state("sessions", sessions[-20:])  # keep the last 20

    return format_sessions(sessions)

def format_sessions(sessions):
    if not sessions:
        return "# Research Log\nNo research sessions tracked yet."
    lines = ["# Research Log\n"]
    for s in reversed(sessions[-10:]):
        lines.append(f"### {s['date']} — {s['topic']}")
        lines.append(f"{s['sources']} sources visited")
        lines += [f"- {u}" for u in s.get("urls", [])[:3]]
        lines.append("")
    return "\n".join(lines)
```

## Creating Agents from the Dashboard

1. Open the **Agents** tab.
2. Click **🤖 New AI Agent** or **🐍 New Python Plugin** and enter a name (lowercase letters, numbers, hyphens).
3. The built-in editor opens — write your prompt or code, then **💾 Save** (Ctrl+S).
4. Click **▶ Run Now** to test. Python plugins need **✅ Approve & Run** first.
5. Use the card's toggle to enable or disable scheduled runs.

You can also **📥 Import** an existing `.md` or `.py` file, or open a plugin in your own editor with **📂 Open in Editor**.

## Tips

1. **Start simple.** Begin with a markdown agent; move to Python when you need state, filtering or external calls.
2. **Be specific.** The more precise the prompt and output format, the better the result.
3. **Test with Run Now** before enabling a schedule, and check **📄 Outputs** and the **Agent Run Log**.
4. **Mind the data budget.** If output is thin, request fewer `data` sections or raise the Context Window in Settings.
5. **Keep `ask_gemma()` calls few** — each one waits for the GPU.

## Agent Lifecycle

```
Agent file created or edited in ~/.screenmind/agents/
        │
        ▼
Discovered on the next scheduler check / Agents tab load
        │
        ▼
Scheduled run (Agent System on, model running) — or Run Now
        │
        ├── Markdown: today's data injected → Gemma generates the output
        │
        └── Python: approved? → run(context) with SDK access
                │
                ▼
        Output saved locally (+ Obsidian / webhooks per `output`)
        Run recorded in the Agent Run Log (last 30 runs)
```
