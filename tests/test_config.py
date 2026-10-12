"""Tests for config.py — settings parsing and properties."""

from screenmind.config import Settings


def test_default_settings():
    s = Settings(data_dir="/tmp/screenmind_test")
    assert s.capture_interval == 40
    assert s.screenshot_quality == 70
    assert s.ollama_model == "gemma4:e2b"
    assert s.api_port == 7777


def test_blocked_apps_list_empty():
    s = Settings(data_dir="/tmp/test", blocked_apps="")
    assert s.blocked_apps_list == []


def test_blocked_apps_list_parsing():
    s = Settings(data_dir="/tmp/test", blocked_apps="1password, banking, keychain")
    assert s.blocked_apps_list == ["1password", "banking", "keychain"]


def test_workspace_dirs_list():
    s = Settings(data_dir="/tmp/test", workspace_dirs="~/Projects, ~/Code")
    dirs = s.workspace_dirs_list
    assert len(dirs) == 2


def test_heavy_apps_list():
    s = Settings(data_dir="/tmp/test", heavy_apps="game,valorant,blender")
    assert "game" in s.heavy_apps_list
    assert "valorant" in s.heavy_apps_list
    assert len(s.heavy_apps_list) == 3


def test_meeting_apps_list():
    s = Settings(data_dir="/tmp/test", meeting_apps="zoom,teams,meet")
    assert "zoom" in s.meeting_apps_list
    assert len(s.meeting_apps_list) == 3


def test_num_gpu_layers():
    s = Settings(data_dir="/tmp/test", performance_mode="minimal")
    assert s.num_gpu_layers == 0

    s = Settings(data_dir="/tmp/test", performance_mode="balanced")
    assert s.num_gpu_layers == 15

    s = Settings(data_dir="/tmp/test", performance_mode="maximum")
    assert s.num_gpu_layers == 99


def test_data_path_resolution():
    s = Settings(data_dir="~/.screenmind")
    assert s.data_path.is_absolute()
    assert "~" not in str(s.data_path)


# ── settings.json migrations ───────────────────────────────────────────

import json

from screenmind.config import SETTINGS_SCHEMA_VERSION, Settings


def _settings_with_file(tmp_path, data=None):
    """A Settings instance whose settings.json (if any) has the given content."""
    s = Settings(data_dir=str(tmp_path))
    if data is not None:
        s.settings_json_path.write_text(json.dumps(data))
    s.load_runtime_overrides()
    return s


def _file(s):
    return json.loads(s.settings_json_path.read_text())


class TestJwtFilterRestore:
    def test_old_file_gets_jwt_back(self, tmp_path):
        s = _settings_with_file(tmp_path, {"sensitive_filter_types": "credit_card,ssn,api_key,password"})
        assert s.sensitive_filter_types == "credit_card,ssn,api_key,password,jwt"
        assert _file(s)["sensitive_filter_types"] == "credit_card,ssn,api_key,password,jwt"
        assert _file(s)["settings_schema_version"] == SETTINGS_SCHEMA_VERSION

    def test_migration_runs_once(self, tmp_path):
        """After the upgrade, a user who unchecks JWT keeps it unchecked."""
        s = _settings_with_file(tmp_path, {"sensitive_filter_types": "ssn"})
        s.save_runtime_overrides({"sensitive_filter_types": "ssn"})  # user unchecks JWT

        reloaded = _settings_with_file(tmp_path)
        assert reloaded.sensitive_filter_types == "ssn"

    def test_current_version_file_left_alone(self, tmp_path):
        s = _settings_with_file(tmp_path, {
            "sensitive_filter_types": "ssn",
            "settings_schema_version": SETTINGS_SCHEMA_VERSION,
        })
        assert s.sensitive_filter_types == "ssn"

    def test_empty_types_left_alone(self, tmp_path):
        """Empty already means "all default types" — adding jwt would narrow it."""
        s = _settings_with_file(tmp_path, {"sensitive_filter_types": ""})
        assert s.sensitive_filter_types == ""
        assert _file(s)["settings_schema_version"] == SETTINGS_SCHEMA_VERSION

    def test_old_file_without_types_only_stamped(self, tmp_path):
        s = _settings_with_file(tmp_path, {"capture_interval": 60})
        assert "sensitive_filter_types" not in _file(s)
        assert _file(s)["settings_schema_version"] == SETTINGS_SCHEMA_VERSION
        assert "jwt" in s.sensitive_filter_types  # default

    def test_no_file_is_not_created(self, tmp_path):
        """Creating settings.json early would skip the first-run welcome screen."""
        s = _settings_with_file(tmp_path)
        assert not s.settings_json_path.exists()

    def test_every_save_stamps_version(self, tmp_path):
        s = _settings_with_file(tmp_path)
        s.save_runtime_overrides({"capture_interval": 30})
        assert _file(s)["settings_schema_version"] == SETTINGS_SCHEMA_VERSION
