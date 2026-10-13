# Contributing to ScreenMind

Contributions are welcome — bug fixes, features, docs, tests, all of it.

## Setup

1. Fork and clone:
   ```bash
   git clone https://github.com/YOUR_USERNAME/ScreenMind.git
   cd ScreenMind
   ```

2. Create a virtual environment and install ScreenMind in editable mode with the AI and dev extras:
   ```bash
   python -m venv venv
   source venv/bin/activate      # Windows: venv\Scripts\activate
   pip install -e ".[ai,dev]"
   ```
   `requirements.txt` pins the full dependency set if you prefer exact versions (`pip install -r requirements.txt`).

3. Install llama-server (the local inference server):
   ```bash
   python -m screenmind.setup_llama
   ```
   Then start ScreenMind (`screenmind` or `python -m screenmind`) and download a model from the **Model Hub** in the dashboard.

4. Run the tests:
   ```bash
   pytest
   ```

### Lightweight setup (tests only)

CI installs `requirements-test.txt`, which skips PyTorch, EasyOCR and sentence-transformers (~2.5 GB). Code paths that need them degrade gracefully, so the whole suite runs without them:

```bash
pip install -r requirements-test.txt
pip install -e .
pytest
```

If you have the AI packages installed and the suite crashes inside `torch`/`transformers` while loading the embedding model, check that your versions match the pins in `pyproject.toml` — or use the lightweight setup above.

## What CI Checks

Every push and pull request runs on Windows (Python 3.10):

- **Tests:** `pytest` with coverage, using `requirements-test.txt`
- **JavaScript syntax:** `node --check` on every file in `screenmind/api/static/js/`
- **No bare `print()`:** `flake8 --select=T201` on source files (see below)

When you change dashboard JS or CSS, bump the `?v=` numbers in `screenmind/api/static/index.html` so browsers load the new files.

## Reporting Bugs

Open an [issue](https://github.com/ayushh0110/ScreenMind/issues) with:
- Your OS, Python version, and GPU (model + VRAM)
- Steps to reproduce
- Relevant logs (`~/.screenmind/screenmind.log` when running in the background) or screenshots

## Pull Requests

1. Branch off `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your changes and add tests where it makes sense
3. Run `pytest` to make sure nothing breaks
4. Open a PR against `main`

Keep commits focused — one logical change per commit.

## Coding Conventions

### Logging (no bare `print()`)

All output goes through Python's `logging` module — **never use bare `print()`** in source files. CI rejects PRs that add `print()` calls (enforced with `flake8-print`).

```python
import logging

logger = logging.getLogger("screenmind.<module_path>")
# e.g. "screenmind.workers.analysis_worker"

logger.info("Normal operation")
logger.warning("Something unexpected but recoverable")
logger.error("Something failed")
logger.debug("Verbose detail for troubleshooting")
```

**Rules:**
- Declare `logger` at **module level**, after all imports
- Use the `screenmind.<dotted.module.path>` naming convention
- Pick the right level: `info` for milestones, `warning` for degraded state, `error` for failures, `debug` for verbose detail
- **No emoji in logger messages** — they crash on Windows cp1252 terminals. Emoji in UI strings (overlay notifications, DB text) are fine
- If you genuinely need `print(file=sys.stderr)` (e.g. CLI output), add `# noqa: T201`

### Why?

The MCP server uses stdio transport — any stray `print()` to stdout corrupts the protocol and breaks IDE integrations. Logging goes to `stderr` by default.

### Platform-specific code

OS-specific window detection and accessibility code lives in `screenmind/platform_support/` behind the `PlatformAdapter` interface (`base.py`). Add platform behavior there rather than `sys.platform` checks in the engine.

## Where Help Is Needed

- **macOS and Linux testing** — the platform adapters exist but need more real-hardware testing (especially Wayland compositors)
- **Model testing** — trying ScreenMind with different Gemma quantizations and GPUs
- **Agent recipes** — useful agents for `screenmind/default_agents/`
- **MCP integrations** — new tools for the MCP server
- **Docs** — tutorials, hardware-specific setup guides, video walkthroughs

## Project Structure

```
ScreenMind/
├── screenmind/                 # The Python package
│   ├── main.py                 # Entry point — starts all services, CLI flags
│   ├── config.py               # Pydantic settings (.env + settings.json overrides)
│   ├── launcher.py             # Splash screen launcher (tkinter)
│   ├── startup.py              # Run-at-login registration (Windows/macOS/Linux)
│   ├── setup_llama.py          # Detect / download llama-server
│   ├── screenmind_sdk.py       # SDK for Python plugin agents
│   ├── mcp_server.py           # MCP server for Claude / Cursor / VS Code
│   ├── api/                    # FastAPI server, routes, web dashboard (static/)
│   ├── capture/                # Screen capture (mss, Wayland), hotkeys, voice recorder
│   ├── engine/                 # Gemma analysis, LLM client, model manager, OCR,
│   │                           # embeddings, layout, agents, voice memos, browsers
│   ├── workers/                # Capture, analysis and meeting (audio) workers
│   ├── storage/                # SQLite database, models, activity files
│   ├── integrations/           # Obsidian, Notion, webhooks, smart notifications
│   ├── platform_support/       # OS adapters: window detection + accessibility
│   ├── privacy/                # Encryption at rest, sensitive-data redaction
│   ├── ui/                     # On-screen overlay notifications
│   ├── default_agents/         # Agents copied to ~/.screenmind/agents on first run
│   └── assets/                 # Logo, favicon
├── tests/                      # pytest suite
├── docs/                       # BUILD_YOUR_OWN_AGENT.md, screenshots
├── architecture.md             # System design deep-dive
└── MCP_SETUP.md                # MCP client setup
```

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
