"""Comprehensive tests for agent runner module."""
import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from screenmind.engine.agent_runner import (
    _parse_md_frontmatter, get_agents_dir, get_agent_log, _log_run,
)


class TestFrontmatterParsing:
    """Tests for markdown agent frontmatter parsing."""

    def test_full_frontmatter(self, tmp_path):
        """All frontmatter fields are parsed correctly."""
        f = tmp_path / "test-agent.md"
        f.write_text("""---
name: Daily Focus Report
schedule: every 6h
data: timeline, apps, mood
output: local, obsidian
description: Generates a focus score
enabled: true
model_requirement: 8192
---

Analyze my screen activity and generate a focus report.
Give me a score out of 10.
""", encoding="utf-8")

        meta = _parse_md_frontmatter(f)
        assert meta["name"] == "Daily Focus Report"
        assert meta["schedule"] == "every 6h"
        assert "timeline" in meta["data"]
        assert "apps" in meta["data"]
        assert "mood" in meta["data"]
        assert "local" in meta["output"]
        assert "obsidian" in meta["output"]
        assert meta["description"] == "Generates a focus score"
        assert meta["enabled"] is True
        assert meta["model_requirement"] == "8192"
        assert "Analyze my screen activity" in meta["prompt"]
        assert "score out of 10" in meta["prompt"]

    def test_no_frontmatter(self, tmp_path):
        """File without frontmatter uses full text as prompt."""
        f = tmp_path / "simple.md"
        f.write_text("Just tell me what I did today.", encoding="utf-8")

        meta = _parse_md_frontmatter(f)
        assert meta["prompt"] == "Just tell me what I did today."
        assert meta["name"] == "simple"
        assert meta["slug"] == "simple"

    def test_disabled_agent(self, tmp_path):
        """enabled: false is parsed correctly."""
        f = tmp_path / "disabled.md"
        f.write_text("""---
name: Disabled Agent
enabled: false
---

This should not run.
""", encoding="utf-8")

        meta = _parse_md_frontmatter(f)
        assert meta["enabled"] is False

    def test_defaults_applied(self, tmp_path):
        """Missing fields get sensible defaults."""
        f = tmp_path / "minimal.md"
        f.write_text("""---
name: Minimal
---

Do something.
""", encoding="utf-8")

        meta = _parse_md_frontmatter(f)
        assert meta["schedule"] == "every 6h"
        assert meta["output"] == "local"
        assert meta["data"] == "timeline, apps"
        assert meta["enabled"] is True

    def test_slug_is_filename_stem(self, tmp_path):
        """Slug is always the filename stem regardless of name field."""
        f = tmp_path / "my-cool-agent.md"
        f.write_text("""---
name: A Different Name
---

Prompt here.
""", encoding="utf-8")

        meta = _parse_md_frontmatter(f)
        assert meta["slug"] == "my-cool-agent"
        assert meta["name"] == "A Different Name"

    def test_multiline_prompt(self, tmp_path):
        """Prompt preserves multiline content."""
        f = tmp_path / "multi.md"
        f.write_text("""---
name: Multi
---

Line one.
Line two.
Line three.
""", encoding="utf-8")

        meta = _parse_md_frontmatter(f)
        assert "Line one." in meta["prompt"]
        assert "Line two." in meta["prompt"]
        assert "Line three." in meta["prompt"]


class TestAgentsDir:
    """Tests for agent directory management."""

    def test_get_agents_dir_exists(self):
        d = get_agents_dir()
        assert d.is_dir()

    def test_get_agents_dir_is_consistent(self):
        """Returns same path on repeated calls."""
        d1 = get_agents_dir()
        d2 = get_agents_dir()
        assert d1 == d2


class TestAgentLog:
    """Tests for agent run logging."""

    def test_get_agent_log_returns_list(self):
        log = get_agent_log()
        assert isinstance(log, list)

    def test_log_run_adds_entry(self):
        """_log_run adds an entry to the log."""
        before = len(get_agent_log())
        _log_run("test-agent", "markdown", "ok", output="test output", duration=1.5)
        after = len(get_agent_log())
        assert after >= before  # may wrap due to maxlen

    def test_log_entry_format(self):
        """Log entries have expected fields."""
        _log_run("format-test", "python", "error", error="something broke", duration=0.5)
        log = get_agent_log()
        entry = next((e for e in log if e["name"] == "format-test"), None)
        if entry:
            assert "timestamp" in entry
            assert entry["type"] == "python"
            assert entry["status"] == "error"
            assert "something broke" in entry["error"]
            assert entry["duration"] == 0.5

    def test_log_truncates_long_output(self):
        """Output is truncated to 500 chars."""
        long_output = "x" * 1000
        _log_run("truncate-test", "markdown", "ok", output=long_output)
        log = get_agent_log()
        entry = next((e for e in log if e["name"] == "truncate-test"), None)
        if entry:
            assert len(entry["output"]) <= 500


class TestMarkdownAgentData:
    """The data injected into markdown agent prompts."""

    def _run(self, activities, meetings, data="timeline, meetings"):
        from unittest.mock import MagicMock, patch
        from screenmind.engine import agent_runner
        fake_db = MagicMock()
        fake_db.get_activities_by_date.return_value = activities
        fake_db.get_meetings_by_date.return_value = meetings
        agent = {"name": "t", "prompt": "Do it", "_data_sections": {s.strip() for s in data.split(",")}}
        with patch("screenmind.storage.database.Database", return_value=fake_db), \
             patch("screenmind.engine.llm_client.generate", return_value="ok") as gen:
            agent_runner._run_markdown_agent(agent)
        return gen.call_args.kwargs["prompt"]

    def test_times_are_hh_mm_with_microsecond_timestamps(self):
        """Stored timestamps include microseconds; slicing showed "[5.123]"."""
        prompt = self._run(
            [{"status": "ok", "timestamp": "2026-10-13T14:30:05.123456", "app_name": "Code",
              "category": "coding", "summary": "Editing main.py"}],
            [{"start_time": "2026-10-13T15:00:00.654321", "app_name": "Zoom",
              "duration_minutes": 30, "summary": "Planning"}],
        )
        assert "[14:30] Code (coding): Editing main.py" in prompt
        assert "- 15:00 Zoom (30min): Planning" in prompt

    def test_meeting_summaries_not_cut_at_80_chars(self):
        summary = "ACTION ITEMS: " + "; ".join(f"[You] follow up on item {i}" for i in range(12))
        prompt = self._run([], [{"start_time": "2026-10-13T15:00:00", "app_name": "Zoom",
                                 "duration_minutes": 30, "summary": summary}], data="meetings")
        assert "follow up on item 10" in prompt
