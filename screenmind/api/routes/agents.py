"""Agent routes — CRUD, run, log, outputs for the plugin system."""

import asyncio
import os
import re
import subprocess
import sys

from fastapi import APIRouter, HTTPException, Request

from screenmind.config import settings
from screenmind.api.dependencies import db

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def list_agents():
    """List all installed agents with metadata."""
    from screenmind.engine.agent_runner import discover_agents, get_agent_log
    agents = discover_agents()
    log = get_agent_log()
    log_by_name = {}
    for entry in log:
        if entry["name"] not in log_by_name:
            log_by_name[entry["name"]] = entry
    for a in agents:
        a["last_run"] = log_by_name.get(a["name"])
    return {"agents": agents, "agents_enabled": settings.agents_enabled}


# ── SDK Data Endpoint ────────────────────────────────────────────────
# Must be defined BEFORE /{name}/ routes so FastAPI doesn't match "sdk" as a name.

@router.get("/sdk/activities")
async def sdk_activities(
    date: str = None,
    app: str = None,
    category: str = None,
    url_contains: str = None,
    has_url: bool = None,
    include_ocr: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    """SDK-specific activity query with full field access.

    Designed for Python plugins — richer fields than dashboard timeline.
    OCR text excluded by default to keep responses small.
    """
    from datetime import date as date_type, datetime

    target = date or str(datetime.now().date())
    conn = db._get_conn()

    # Build filtered query
    conditions = ["DATE(timestamp) = ?"]
    params = [target]

    if app:
        conditions.append("app_name = ?")
        params.append(app)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if url_contains:
        conditions.append("active_url LIKE ?")
        params.append(f"%{url_contains}%")
    if has_url:
        conditions.append("active_url IS NOT NULL AND active_url != ''")

    where = " AND ".join(conditions)
    params.extend([limit, offset])

    rows = conn.execute(
        f"""SELECT id, timestamp, app_name, category, summary, details,
                   mood, confidence, active_url, window_title,
                   scene_description, analysis_method, bookmarked
                   {', SUBSTR(ocr_text, 1, 500) AS ocr_text' if include_ocr else ''}
            FROM activities
            WHERE {where} AND status = 'ok'
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?""",
        params,
    ).fetchall()

    activities = []
    for r in rows:
        a = dict(r)
        activities.append(a)

    return {"activities": activities, "count": len(activities), "date": target}


@router.post("/{name}/toggle")
async def toggle_agent(name: str, request: Request):
    """Enable or disable an agent by rewriting its frontmatter."""
    from screenmind.engine.agent_runner import get_agents_dir
    body = await request.json()
    enabled = body.get("enabled", True)
    agents_dir = get_agents_dir()

    for ext in [".md", ".py"]:
        filepath = agents_dir / f"{name}{ext}"
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            content = re.sub(
                r"^(enabled:\s*)(true|false|yes|no)",
                f"\\g<1>{'true' if enabled else 'false'}",
                content, count=1, flags=re.MULTILINE
            )
            filepath.write_text(content, encoding="utf-8")
            return {"ok": True, "name": name, "enabled": enabled}

    return {"ok": False, "error": "Agent not found"}


@router.post("/{name}/run")
async def run_agent_now(name: str, request: Request):
    """Trigger an immediate agent run.
    Python agents require approval OR X-Confirm header.
    """
    from screenmind.engine.agent_runner import discover_agents, run_agent, _approved_plugins
    agents = discover_agents()
    for a in agents:
        if a.get("slug", a["name"]) == name:
            # Python agents: must be approved or have confirmation header
            if a["type"] == "python" and not settings.agents_auto_run_python:
                if a.get("filepath", "") not in _approved_plugins:
                    if request.headers.get("X-Confirm") != "true":
                        return {"status": "error", "error": "Python agent not approved. Approve it first or pass X-Confirm: true header."}
            result = await asyncio.get_event_loop().run_in_executor(None, lambda: run_agent(a))
            return result
    return {"status": "error", "error": "Agent not found"}


@router.post("/{name}/approve")
async def approve_agent(name: str, request: Request):
    """Approve a Python plugin to run. Requires X-Confirm header."""
    if request.headers.get("X-Confirm") != "true":
        raise HTTPException(status_code=403, detail="Approving Python agents requires X-Confirm: true header")
    from screenmind.engine.agent_runner import discover_agents, approve_plugin
    agents = discover_agents()
    for a in agents:
        if a.get("slug", a["name"]) == name and a["type"] == "python":
            approve_plugin(a["filepath"])
            return {"ok": True, "name": name}
    return {"ok": False, "error": "Agent not found"}


@router.delete("/{name}")
async def delete_agent(name: str):
    """Delete an agent file."""
    from screenmind.engine.agent_runner import get_agents_dir
    agents_dir = get_agents_dir()
    for ext in [".md", ".py"]:
        filepath = agents_dir / f"{name}{ext}"
        if filepath.exists():
            filepath.unlink()
            return {"ok": True, "deleted": name}
    return {"ok": False, "error": "Agent not found"}


@router.get("/log")
async def agent_log():
    """Return recent agent run log."""
    from screenmind.engine.agent_runner import get_agent_log
    return {"log": get_agent_log()}


@router.get("/{name}/outputs")
async def get_agent_outputs(name: str):
    """Return saved output files for an agent."""
    out_dir = settings.data_path / "agents" / "output" / name
    if not out_dir.exists():
        return {"outputs": []}
    files = sorted(out_dir.glob("*.md"), reverse=True)[:20]
    outputs = []
    for f in files:
        try:
            content = f.read_text(encoding="utf-8")
            outputs.append({
                "filename": f.name,
                "date": f.stem,
                "content": content[:3000],
                "size": len(content),
            })
        except Exception:
            pass
    return {"outputs": outputs, "total": len(list(out_dir.glob("*.md")))}


@router.post("/create")
async def create_agent(request: Request):
    """Create a new agent from template.
    Python agents require X-Confirm: true header.
    """
    from screenmind.engine.agent_runner import get_agents_dir
    body = await request.json()
    name = body.get("name", "my-agent").strip().lower().replace(" ", "-")
    agent_type = body.get("type", "markdown")
    agents_dir = get_agents_dir()

    # Python agent creation requires explicit confirmation
    if agent_type == "python" and request.headers.get("X-Confirm") != "true":
        raise HTTPException(status_code=403, detail="Python agent creation requires X-Confirm: true header")

    if agent_type == "python":
        filepath = agents_dir / f"{name}.py"
        content = f'''"""
name: {name}
schedule: every 1h
description: Custom Python plugin
enabled: true
output: local
"""
from screenmind.screenmind_sdk import get_recent_activity, notify

def run(context):
    activities = get_recent_activity(minutes=60)
    # Your logic here
    notify("Agent: {name}", f"Processed {{len(activities)}} activities")
    return f"Processed {{len(activities)}} activities"
'''
    else:
        filepath = agents_dir / f"{name}.md"
        content = f"""---
name: {name}
schedule: every 6h
description: Custom AI agent
enabled: true
output: local
---
Analyze the user's recent screen activity and provide a useful summary.
Focus on the most important and actionable insights.
"""

    if filepath.exists():
        return {"ok": False, "error": "Agent already exists"}
    filepath.write_text(content, encoding="utf-8")
    return {"ok": True, "name": name, "filepath": str(filepath)}


@router.get("/{name}/content")
async def get_agent_content(name: str):
    """Get the full content of an agent file for editing."""
    from screenmind.engine.agent_runner import get_agents_dir
    agents_dir = get_agents_dir()
    for ext in [".md", ".py"]:
        filepath = agents_dir / f"{name}{ext}"
        if filepath.exists():
            return {"ok": True, "name": name, "type": "python" if ext == ".py" else "markdown", "content": filepath.read_text(encoding="utf-8")}
    return {"ok": False, "error": "Agent not found"}


@router.put("/{name}/content")
async def update_agent_content(name: str, request: Request):
    """Update the content of an agent file.
    Python agents require X-Confirm: true header (prevents blind writes from scripts/XSS).
    """
    from screenmind.engine.agent_runner import get_agents_dir
    body = await request.json()
    content = body.get("content", "")
    agents_dir = get_agents_dir()
    for ext in [".md", ".py"]:
        filepath = agents_dir / f"{name}{ext}"
        if filepath.exists():
            # Python files require explicit confirmation header
            if ext == ".py" and request.headers.get("X-Confirm") != "true":
                raise HTTPException(status_code=403, detail="Python agent writes require X-Confirm: true header")
            filepath.write_text(content, encoding="utf-8")
            return {"ok": True, "name": name}
    return {"ok": False, "error": "Agent not found"}


@router.post("/{name}/open")
async def open_agent_in_editor(name: str):
    """Open agent file in the system's default code editor."""
    from screenmind.engine.agent_runner import get_agents_dir
    agents_dir = get_agents_dir()
    for ext in [".md", ".py"]:
        filepath = agents_dir / f"{name}{ext}"
        if filepath.exists():
            try:
                if sys.platform == "win32":
                    os.startfile(str(filepath))
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(filepath)])
                else:
                    subprocess.Popen(["xdg-open", str(filepath)])
                return {"ok": True, "name": name, "path": str(filepath)}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Agent not found"}
