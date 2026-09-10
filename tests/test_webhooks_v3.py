"""Tests for webhook v3 features: fire_all, send_to_hook, named hooks."""
import json
from unittest.mock import patch, MagicMock, PropertyMock
import pytest

from screenmind.integrations.webhooks import (
    fire_all,
    send_to_hook,
    _get_hook_by_name,
    _get_extra_hooks,
    _send_with_retry_named,
)


# ── _get_hook_by_name ──────────────────────────────────────────────────

class TestGetHookByName:
    """Look up webhook profiles by name."""

    @patch("screenmind.integrations.webhooks.settings")
    def test_default_returns_main_settings(self, mock_settings):
        mock_settings.webhook_url = "http://example.com"
        mock_settings.webhook_events = "daily_summary,bookmark"
        mock_settings.webhook_secret = "secret123"
        mock_settings.webhook_headers = "X-Custom: val"
        mock_settings.webhook_enabled = True

        hook = _get_hook_by_name("default")
        assert hook is not None
        assert hook["name"] == "default"
        assert hook["url"] == "http://example.com"
        assert hook["enabled"] is True

    @patch("screenmind.integrations.webhooks.settings")
    def test_default_returns_none_when_no_url(self, mock_settings):
        mock_settings.webhook_url = ""
        assert _get_hook_by_name("default") is None

    @patch("screenmind.integrations.webhooks.settings")
    def test_named_hook_from_extras(self, mock_settings):
        mock_settings.webhook_extra = json.dumps([
            {"name": "discord", "url": "http://discord.com/webhook", "events": "daily_summary", "enabled": True},
            {"name": "slack", "url": "http://slack.com/webhook", "events": "bookmark", "enabled": False},
        ])
        hook = _get_hook_by_name("discord")
        assert hook is not None
        assert hook["name"] == "discord"

    @patch("screenmind.integrations.webhooks.settings")
    def test_unknown_name_returns_none(self, mock_settings):
        mock_settings.webhook_extra = "[]"
        assert _get_hook_by_name("nonexistent") is None


# ── _get_extra_hooks ───────────────────────────────────────────────────

class TestGetExtraHooks:

    @patch("screenmind.integrations.webhooks.settings")
    def test_valid_json_list(self, mock_settings):
        mock_settings.webhook_extra = json.dumps([{"name": "test"}])
        hooks = _get_extra_hooks()
        assert len(hooks) == 1
        assert hooks[0]["name"] == "test"

    @patch("screenmind.integrations.webhooks.settings")
    def test_invalid_json_returns_empty(self, mock_settings):
        mock_settings.webhook_extra = "not-json"
        assert _get_extra_hooks() == []

    @patch("screenmind.integrations.webhooks.settings")
    def test_empty_string_returns_empty(self, mock_settings):
        mock_settings.webhook_extra = ""
        assert _get_extra_hooks() == []

    @patch("screenmind.integrations.webhooks.settings")
    def test_json_dict_instead_of_list_returns_empty(self, mock_settings):
        mock_settings.webhook_extra = '{"not": "a list"}'
        assert _get_extra_hooks() == []


# ── fire_all ───────────────────────────────────────────────────────────

class TestFireAll:

    @patch("screenmind.integrations.webhooks._pool")
    @patch("screenmind.integrations.webhooks.settings")
    def test_fires_to_enabled_default(self, mock_settings, mock_pool):
        mock_settings.webhook_enabled = True
        mock_settings.webhook_url = "http://example.com"
        mock_settings.webhook_events = "daily_summary,bookmark"
        mock_settings.webhook_secret = ""
        mock_settings.webhook_headers = ""
        mock_settings.webhook_extra = "[]"

        count = fire_all("daily_summary", {"summary": "test"})
        assert count == 1
        mock_pool.submit.assert_called_once()

    @patch("screenmind.integrations.webhooks._pool")
    @patch("screenmind.integrations.webhooks.settings")
    def test_skips_disabled_default(self, mock_settings, mock_pool):
        mock_settings.webhook_enabled = False
        mock_settings.webhook_url = "http://example.com"
        mock_settings.webhook_extra = "[]"

        count = fire_all("daily_summary", {"summary": "test"})
        assert count == 0
        mock_pool.submit.assert_not_called()

    @patch("screenmind.integrations.webhooks._pool")
    @patch("screenmind.integrations.webhooks.settings")
    def test_skips_event_not_in_list(self, mock_settings, mock_pool):
        mock_settings.webhook_enabled = True
        mock_settings.webhook_url = "http://example.com"
        mock_settings.webhook_events = "bookmark"
        mock_settings.webhook_secret = ""
        mock_settings.webhook_headers = ""
        mock_settings.webhook_extra = "[]"

        count = fire_all("daily_summary", {"summary": "test"})
        assert count == 0

    @patch("screenmind.integrations.webhooks._pool")
    @patch("screenmind.integrations.webhooks.settings")
    def test_empty_events_allows_all(self, mock_settings, mock_pool):
        """Empty events string means fire on all events."""
        mock_settings.webhook_enabled = True
        mock_settings.webhook_url = "http://example.com"
        mock_settings.webhook_events = ""
        mock_settings.webhook_secret = ""
        mock_settings.webhook_headers = ""
        mock_settings.webhook_extra = "[]"

        count = fire_all("any_event", {"summary": "test"})
        assert count == 1

    @patch("screenmind.integrations.webhooks._pool")
    @patch("screenmind.integrations.webhooks.settings")
    def test_fires_to_extra_hooks(self, mock_settings, mock_pool):
        mock_settings.webhook_enabled = False
        mock_settings.webhook_url = ""
        mock_settings.webhook_extra = json.dumps([
            {"name": "discord", "url": "http://discord.com/webhook", "events": "daily_summary", "enabled": True},
        ])

        count = fire_all("daily_summary", {"summary": "test"})
        assert count == 1

    @patch("screenmind.integrations.webhooks._pool")
    @patch("screenmind.integrations.webhooks.settings")
    def test_skips_disabled_extra_hook(self, mock_settings, mock_pool):
        mock_settings.webhook_enabled = False
        mock_settings.webhook_url = ""
        mock_settings.webhook_extra = json.dumps([
            {"name": "discord", "url": "http://discord.com/webhook", "events": "daily_summary", "enabled": False},
        ])

        count = fire_all("daily_summary", {"summary": "test"})
        assert count == 0

    @patch("screenmind.integrations.webhooks._pool")
    @patch("screenmind.integrations.webhooks.settings")
    def test_fires_to_both_default_and_extras(self, mock_settings, mock_pool):
        mock_settings.webhook_enabled = True
        mock_settings.webhook_url = "http://default.com"
        mock_settings.webhook_events = "daily_summary"
        mock_settings.webhook_secret = ""
        mock_settings.webhook_headers = ""
        mock_settings.webhook_extra = json.dumps([
            {"name": "slack", "url": "http://slack.com", "events": "daily_summary", "enabled": True},
        ])

        count = fire_all("daily_summary", {"summary": "test"})
        assert count == 2


# ── send_to_hook ───────────────────────────────────────────────────────

class TestSendToHook:

    @patch("screenmind.integrations.webhooks._pool")
    @patch("screenmind.integrations.webhooks.settings")
    def test_sends_to_default_hook(self, mock_settings, mock_pool):
        mock_settings.webhook_url = "http://example.com"
        mock_settings.webhook_events = "agent_output"
        mock_settings.webhook_secret = ""
        mock_settings.webhook_headers = ""
        mock_settings.webhook_enabled = True

        result = send_to_hook("default", "my-agent", "Agent output text")
        assert result is True
        mock_pool.submit.assert_called_once()

    @patch("screenmind.integrations.webhooks._pool")
    @patch("screenmind.integrations.webhooks.settings")
    def test_returns_false_for_unknown_hook(self, mock_settings, mock_pool):
        mock_settings.webhook_extra = "[]"
        result = send_to_hook("nonexistent", "agent", "output")
        assert result is False
        mock_pool.submit.assert_not_called()

    @patch("screenmind.integrations.webhooks._pool")
    @patch("screenmind.integrations.webhooks.settings")
    def test_returns_false_for_disabled_hook(self, mock_settings, mock_pool):
        mock_settings.webhook_url = "http://example.com"
        mock_settings.webhook_events = ""
        mock_settings.webhook_secret = ""
        mock_settings.webhook_headers = ""
        mock_settings.webhook_enabled = False

        result = send_to_hook("default", "agent", "output")
        assert result is False

    @patch("screenmind.integrations.webhooks._pool")
    @patch("screenmind.integrations.webhooks.settings")
    def test_truncates_output_to_1900(self, mock_settings, mock_pool):
        mock_settings.webhook_url = "http://example.com"
        mock_settings.webhook_events = ""
        mock_settings.webhook_secret = ""
        mock_settings.webhook_headers = ""
        mock_settings.webhook_enabled = True

        long_output = "x" * 5000
        send_to_hook("default", "agent", long_output)

        # Verify the payload content field is under 2000 chars
        call_args = mock_pool.submit.call_args
        payload = call_args[0][2]  # third positional arg: (func, url, payload, ...)
        assert len(payload["content"]) < 2000
        assert len(payload["text"]) < 2000

    @patch("screenmind.integrations.webhooks._pool")
    @patch("screenmind.integrations.webhooks.settings")
    def test_sends_to_named_extra_hook(self, mock_settings, mock_pool):
        mock_settings.webhook_extra = json.dumps([
            {"name": "discord", "url": "http://discord.com/webhook", "events": "", "secret": "", "headers": "", "enabled": True},
        ])

        result = send_to_hook("discord", "my-agent", "Hello from agent")
        assert result is True
        mock_pool.submit.assert_called_once()
        # Verify hook_name passed correctly: (func, url, payload, secret, headers, event, hook_name)
        call_args = mock_pool.submit.call_args[0]
        assert call_args[6] == "discord"  # hook_name is 7th arg (index 6)
