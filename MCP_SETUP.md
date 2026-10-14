# ScreenMind MCP Server Setup

ScreenMind includes an MCP (Model Context Protocol) server that lets AI assistants like **Claude Desktop**, **Claude Code**, **Cursor**, **VS Code** and any other MCP client query your screen history directly.

## What It Does

The MCP server exposes your ScreenMind data as **tools** that AI assistants can call:

| Tool | Description |
|---|---|
| `search_screen` | Search screen history in natural language (semantic + keyword) |
| `get_recent_activity` | The most recent N analyzed activities (max 50) |
| `get_activity_by_time` | Activities for a date (`YYYY-MM-DD`), optionally between two hours |
| `get_daily_summary` | The AI-generated daily summary and standup notes for a date |
| `capture_now` | Trigger an instant bookmarked screenshot (needs the app running) |
| `get_stats` | Statistics for the last 7 days (categories, apps, repos, meetings) |
| `search_audio` | Search meeting transcripts and summaries |
| `get_screenshot` | The file path of the screenshot for an activity ID |

It also provides one resource, `screenmind://status`, with the active model and capture settings.

## Setup

### 1. Install the MCP extra

Install it into the **same Python environment** as ScreenMind:

```bash
pip install "screenmind[mcp]"
```

For semantic search the server also needs the AI extra (`pip install "screenmind[ai]"`). Without it, `search_screen` falls back to keyword search.

### 2. Configure your AI client

The server runs as `python -m screenmind.mcp_server` (stdio transport). Clients often don't see your activated virtualenv, so especially on Windows, set `command` to the **full path of the Python executable** that has ScreenMind installed, e.g. `C:\Users\you\venv\Scripts\python.exe` (in JSON, write each backslash as `\\`).

#### Claude Desktop

Edit the config file:
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

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

#### Claude Code

```bash
claude mcp add screenmind -- python -m screenmind.mcp_server
```

#### Cursor

Add to `~/.cursor/mcp.json` (or **Settings → MCP**):

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

#### VS Code

Add to `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "screenmind": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "screenmind.mcp_server"]
    }
  }
}
```

### 3. Restart your AI client

After saving the configuration, restart the client. ScreenMind should appear with 8 tools.

## Testing

Test the server with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector python -m screenmind.mcp_server
```

This opens a web UI where you can call each tool interactively.

## Example Prompts

- *"What was I working on today?"* → `get_recent_activity`
- *"Search my screen for discord messages"* → `search_screen`
- *"What did I do between 2pm and 5pm yesterday?"* → `get_activity_by_time`
- *"Give me my daily summary"* → `get_daily_summary`
- *"What did we decide in today's standup call?"* → `search_audio`
- *"Take a screenshot right now"* → `capture_now`

## How It Works

- The MCP server is a **separate process**. It reads ScreenMind's local SQLite database directly, so search and history tools work even when the ScreenMind app isn't running.
- `capture_now` asks the running app to take a bookmarked screenshot through its local API (`127.0.0.1:7777`). It returns an error if the app isn't running, and captures nothing while **incognito mode** is on.
- `get_screenshot` returns a file path inside ScreenMind's screenshots folder. If screenshot encryption is enabled, the file at that path is encrypted.

## Privacy

- The MCP server runs **locally** and only reads your local database.
- Your screen history is sent to the AI client you connect — and from there to that client's model provider (for example Anthropic for Claude Desktop). Only connect clients you trust with this data.
- Every tool is read-only except `capture_now`, which triggers a local screenshot.

## Requirements

- ScreenMind installed, with some captured screen data
- `mcp[cli]` installed in the same environment (`pip install "screenmind[mcp]"`)
- The ScreenMind app running, for `capture_now` only
