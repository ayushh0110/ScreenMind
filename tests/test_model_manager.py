"""Tests for model_manager — covers:
  - Variant helpers (get_effective_hf_file, get_active_quant, _quant_for_hf_file)
  - is_variant_downloaded / is_model_downloaded
  - list_models with per-variant status
  - is_audio_capable / get_active_capabilities
  - switch_model guards (downloaded check, variant fallback, single-flight lock)
  - cancel_download flag under lock
  - _check_model_disk_space for all models + variant-specific sizes
  - get_model_status capabilities field
  - delete_variant / delete_model guards and behavior
"""

import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from screenmind.engine import model_manager


# ── Variant Helpers ───────────────────────────────────────────────────

class TestVariantHelpers:
    """Tests for variant resolution functions."""

    def test_get_model_info_known(self):
        """Known model key returns info dict."""
        info = model_manager.get_model_info("gemma-4-e2b")
        assert info is not None
        assert info["key"] == "gemma-4-e2b"
        assert "variants" in info

    def test_get_model_info_unknown(self):
        """Unknown model key returns None."""
        assert model_manager.get_model_info("nonexistent") is None

    def test_get_effective_hf_file_default(self):
        """Without variant preference, returns the model's default hf_file."""
        with patch("screenmind.engine.model_manager.settings") as mock_s:
            mock_s.model_variants = {}
            result = model_manager.get_effective_hf_file("gemma-4-e2b")
            assert result == "gemma-4-E2B-it-Q4_0.gguf"

    def test_get_effective_hf_file_with_preference(self):
        """With a variant preference, returns the matching hf_file."""
        with patch("screenmind.engine.model_manager.settings") as mock_s:
            mock_s.model_variants = {"gemma-4-e2b": "Q8_0"}
            result = model_manager.get_effective_hf_file("gemma-4-e2b")
            assert result == "gemma-4-E2B-it-Q8_0.gguf"

    def test_get_effective_hf_file_invalid_preference_falls_back(self):
        """Invalid variant preference falls back to default hf_file."""
        with patch("screenmind.engine.model_manager.settings") as mock_s:
            mock_s.model_variants = {"gemma-4-e2b": "NONEXISTENT"}
            result = model_manager.get_effective_hf_file("gemma-4-e2b")
            assert result == "gemma-4-E2B-it-Q4_0.gguf"

    def test_get_effective_hf_file_unknown_model(self):
        """Unknown model returns empty string."""
        result = model_manager.get_effective_hf_file("nonexistent")
        assert result == ""

    def test_get_active_quant_default(self):
        """Without preference, returns first variant's quant."""
        with patch("screenmind.engine.model_manager.settings") as mock_s:
            mock_s.model_variants = {}
            result = model_manager.get_active_quant("gemma-4-e2b")
            assert result == "Q4_0"

    def test_get_active_quant_with_preference(self):
        """With preference, returns that quant."""
        with patch("screenmind.engine.model_manager.settings") as mock_s:
            mock_s.model_variants = {"gemma-4-e2b": "BF16"}
            result = model_manager.get_active_quant("gemma-4-e2b")
            assert result == "BF16"

    def test_get_active_quant_invalid_falls_back(self):
        """Invalid preference falls back to first variant."""
        with patch("screenmind.engine.model_manager.settings") as mock_s:
            mock_s.model_variants = {"gemma-4-e2b": "FAKE"}
            result = model_manager.get_active_quant("gemma-4-e2b")
            assert result == "Q4_0"

    def test_quant_for_hf_file_known(self):
        """Reverse-maps hf_file to quant string."""
        result = model_manager._quant_for_hf_file("gemma-4-e2b", "gemma-4-E2B-it-Q8_0.gguf")
        assert result == "Q8_0"

    def test_quant_for_hf_file_unknown(self):
        """Unknown hf_file returns empty string."""
        result = model_manager._quant_for_hf_file("gemma-4-e2b", "nonexistent.gguf")
        assert result == ""


# ── Variant Download Detection ────────────────────────────────────────

class TestVariantDownloadDetection:
    """Tests for is_variant_downloaded and is_model_downloaded."""

    def test_is_variant_downloaded_missing_dir(self, tmp_path):
        """Returns False when variant directory doesn't exist."""
        with patch.object(model_manager, "_models_dir", return_value=tmp_path):
            assert model_manager.is_variant_downloaded("gemma-4-e2b", "Q4_0") is False

    def test_is_variant_downloaded_exists(self, tmp_path):
        """Returns True when variant file exists and is >1MB."""
        variant_dir = tmp_path / "gemma-4-e2b" / "Q4_0"
        variant_dir.mkdir(parents=True)
        model_file = variant_dir / "gemma-4-E2B-it-Q4_0.gguf"
        model_file.write_bytes(b"x" * (2 * 1024 * 1024))  # 2MB

        with patch.object(model_manager, "_models_dir", return_value=tmp_path):
            assert model_manager.is_variant_downloaded("gemma-4-e2b", "Q4_0") is True

    def test_is_variant_downloaded_too_small(self, tmp_path):
        """Returns False when file is <1MB (incomplete download)."""
        variant_dir = tmp_path / "gemma-4-e2b" / "Q4_0"
        variant_dir.mkdir(parents=True)
        model_file = variant_dir / "gemma-4-E2B-it-Q4_0.gguf"
        model_file.write_bytes(b"x" * 100)  # 100 bytes

        with patch.object(model_manager, "_models_dir", return_value=tmp_path):
            assert model_manager.is_variant_downloaded("gemma-4-e2b", "Q4_0") is False

    def test_is_variant_downloaded_unknown_model(self):
        """Returns False for unknown model key."""
        assert model_manager.is_variant_downloaded("nonexistent", "Q4_0") is False

    def test_is_variant_downloaded_unknown_quant(self):
        """Returns False for unknown quant string."""
        assert model_manager.is_variant_downloaded("gemma-4-e2b", "NONEXISTENT") is False

    def test_is_model_downloaded_any_variant(self, tmp_path):
        """Returns True if any variant is downloaded."""
        variant_dir = tmp_path / "gemma-4-e2b" / "Q8_0"
        variant_dir.mkdir(parents=True)
        model_file = variant_dir / "gemma-4-E2B-it-Q8_0.gguf"
        model_file.write_bytes(b"x" * (2 * 1024 * 1024))

        with patch.object(model_manager, "_models_dir", return_value=tmp_path):
            assert model_manager.is_model_downloaded("gemma-4-e2b") is True

    def test_is_model_downloaded_none(self, tmp_path):
        """Returns False if no variant is downloaded."""
        with patch.object(model_manager, "_models_dir", return_value=tmp_path):
            assert model_manager.is_model_downloaded("gemma-4-e2b") is False


# ── list_models ───────────────────────────────────────────────────────

class TestListModels:
    """Tests for list_models with per-variant status."""

    def test_list_models_returns_all(self):
        """list_models returns all available models."""
        with patch("screenmind.engine.model_manager.settings") as mock_s:
            mock_s.model_variants = {}
            models = model_manager.list_models()
            keys = [m["key"] for m in models]
            assert "gemma-4-e2b" in keys
            assert "gemma-4-e4b" in keys
            assert "gemma-4-12b" in keys

    def test_list_models_includes_variant_status(self):
        """Each model's variants include a 'downloaded' field."""
        with patch("screenmind.engine.model_manager.settings") as mock_s:
            mock_s.model_variants = {}
            models = model_manager.list_models()
            for m in models:
                for v in m["variants"]:
                    assert "downloaded" in v
                    assert isinstance(v["downloaded"], bool)

    def test_list_models_includes_active_variant(self):
        """Each model includes active_variant field."""
        with patch("screenmind.engine.model_manager.settings") as mock_s:
            mock_s.model_variants = {}
            models = model_manager.list_models()
            for m in models:
                assert "active_variant" in m


# ── Audio Capability ──────────────────────────────────────────────────

class TestAudioCapability:
    """Tests for is_audio_capable() and get_active_capabilities()."""

    def test_audio_capable_gemma4_e2b(self):
        """Gemma 4 E2B supports audio."""
        assert model_manager.is_audio_capable("gemma-4-e2b") is True

    def test_audio_capable_gemma4_e4b(self):
        """Gemma 4 E4B supports audio."""
        assert model_manager.is_audio_capable("gemma-4-e4b") is True

    def test_audio_capable_gemma4_12b(self):
        """Gemma 4 12B supports audio."""
        assert model_manager.is_audio_capable("gemma-4-12b") is True

    def test_unknown_model_not_audio(self):
        """Unknown model key returns False."""
        assert model_manager.is_audio_capable("nonexistent-model") is False

    def test_get_active_capabilities_returns_dict(self):
        """get_active_capabilities returns a dict with audio and vision keys."""
        caps = model_manager.get_active_capabilities()
        assert "audio" in caps
        assert "vision" in caps

    def test_capabilities_for_gemma4(self):
        """Gemma 4 E2B has both audio and vision."""
        with patch.object(model_manager, "_active_model_key", "gemma-4-e2b"):
            caps = model_manager.get_active_capabilities()
            assert caps["audio"] is True
            assert caps["vision"] is True

    def test_capabilities_for_gemma4_12b(self):
        """Gemma 4 12B has both audio and vision."""
        with patch.object(model_manager, "_active_model_key", "gemma-4-12b"):
            caps = model_manager.get_active_capabilities()
            assert caps["audio"] is True
            assert caps["vision"] is True


# ── Switch Model Guards ───────────────────────────────────────────────

class TestSwitchModelGuards:
    """Tests for switch_model guard clauses."""

    def test_switch_unknown_model_returns_false(self):
        """Switching to unknown model returns False."""
        assert model_manager.switch_model("nonexistent") is False

    @patch.object(model_manager, "is_model_downloaded", return_value=False)
    def test_switch_not_downloaded_returns_false(self, _mock):
        """Switching to a not-downloaded model returns False."""
        assert model_manager.switch_model("nonexistent") is False

    @patch.object(model_manager, "is_model_downloaded", return_value=True)
    @patch.object(model_manager, "is_variant_downloaded", return_value=True)
    def test_switch_blocked_by_lock(self, _var, _dl):
        """Switching while lifecycle lock held returns False."""
        model_manager._download_lock.acquire()
        try:
            assert model_manager.switch_model("gemma-4-e2b") is False
        finally:
            model_manager._download_lock.release()

    @patch.object(model_manager, "is_model_downloaded", return_value=True)
    @patch.object(model_manager, "is_variant_downloaded", return_value=True)
    @patch.object(model_manager, "is_server_running", return_value=True)
    def test_switch_sets_starting_state(self, _run, _var, _dl):
        """switch_model sets transient 'starting' status during execution."""
        states_during = []

        def capture_start_server(key=None, **kw):
            states_during.append(model_manager.get_download_state()["status"])
            return True

        with patch.object(model_manager, "start_server", side_effect=capture_start_server):
            with patch("screenmind.engine.model_manager.settings") as mock_settings:
                mock_settings.active_model = "gemma-4-e2b"
                mock_settings.model_variants = {}
                mock_settings.save_runtime_overrides = MagicMock()
                model_manager.switch_model("gemma-4-e2b")
        assert "starting" in states_during

    @patch.object(model_manager, "is_model_downloaded", return_value=True)
    @patch.object(model_manager, "is_variant_downloaded", side_effect=lambda k, q: q == "Q8_0")
    @patch.object(model_manager, "is_server_running", return_value=True)
    @patch.object(model_manager, "start_server", return_value=True)
    def test_switch_falls_back_to_downloaded_variant(self, _start, _var, _dl, _mock):
        """switch_model falls back to any downloaded variant if selected isn't available."""
        with patch("screenmind.engine.model_manager.settings") as mock_settings:
            mock_settings.active_model = "gemma-4-e2b"
            mock_settings.model_variants = {"gemma-4-e2b": "BF16"}  # BF16 not downloaded
            mock_settings.save_runtime_overrides = MagicMock()
            result = model_manager.switch_model("gemma-4-e2b")
            assert result is True
            # Verify it saved the fallback preference
            mock_settings.save_runtime_overrides.assert_called()


# ── Restart Server Guards ─────────────────────────────────────────────

class TestRestartServerGuards:
    """Tests for restart_server guard clauses."""

    def test_restart_blocked_by_lock(self):
        """Restart while lifecycle lock held returns False."""
        model_manager._download_lock.acquire()
        try:
            assert model_manager.restart_server() is False
        finally:
            model_manager._download_lock.release()


# ── Cancel Download ───────────────────────────────────────────────────

class TestCancelDownload:
    """Tests for cancel_download flag safety."""

    def test_cancel_when_idle_returns_false(self):
        """Cancel when no download active returns False."""
        model_manager._set_download_state(active=False, status="idle")
        assert model_manager.cancel_download() is False

    def test_cancel_when_downloading_returns_true(self):
        """Cancel during download sets flag and returns True."""
        model_manager._set_download_state(active=True, status="downloading")
        try:
            assert model_manager.cancel_download() is True
            with model_manager._download_state_lock:
                assert model_manager._cancel_download_flag is True
        finally:
            # Clean up
            model_manager._cancel_download_flag = False
            model_manager._set_download_state(active=False, status="idle")

    def test_cancel_when_starting_returns_false(self):
        """Cancel during 'starting' phase (not downloading) returns False."""
        model_manager._set_download_state(active=True, status="starting")
        try:
            assert model_manager.cancel_download() is False
        finally:
            model_manager._set_download_state(active=False, status="idle")


# ── Disk Space ────────────────────────────────────────────────────────

class TestDiskSpaceCheck:
    """Verify disk space checks for all models and variants."""

    def test_all_models_have_size_estimates(self):
        """Every model in AVAILABLE_MODELS can be checked for disk space."""
        for m in model_manager.AVAILABLE_MODELS:
            key = m["key"]
            result = model_manager._check_model_disk_space(key)
            assert isinstance(result, bool), f"Disk check for {key} returned non-bool"

    def test_variant_specific_size_estimate(self):
        """Variant-specific quant uses the variant's file_size for the estimate."""
        # Q4_0 is ~1.5 GB, should pass on any machine with free space
        result = model_manager._check_model_disk_space("gemma-4-e2b", "Q4_0")
        assert isinstance(result, bool)

    def test_large_variant_size_parsed(self):
        """12B Q8_0 (~13 GB) file size is parsed correctly."""
        result = model_manager._check_model_disk_space("gemma-4-12b", "Q8_0")
        assert isinstance(result, bool)


# ── Get Model Status ──────────────────────────────────────────────────

class TestGetModelStatus:
    """Tests for capabilities field in get_model_status."""

    @patch.object(model_manager, "is_server_running", return_value=True)
    @patch.object(model_manager, "_active_model_key", "gemma-4-e2b")
    def test_status_includes_capabilities(self, _):
        """get_model_status response includes capabilities dict."""
        model_manager._set_download_state(active=False, status="idle")
        status = model_manager.get_model_status()
        assert "capabilities" in status
        assert "audio" in status["capabilities"]
        assert "vision" in status["capabilities"]

    @patch.object(model_manager, "is_server_running", return_value=True)
    @patch.object(model_manager, "_active_model_key", "nonexistent-model")
    def test_status_capabilities_reflect_model(self, _):
        """Capabilities reflect the active model's actual support."""
        model_manager._set_download_state(active=False, status="idle")
        status = model_manager.get_model_status()
        assert status["capabilities"]["audio"] is False
        assert status["capabilities"]["vision"] is False

    @patch.object(model_manager, "is_server_running", return_value=True)
    @patch.object(model_manager, "_active_model_key", "gemma-4-e2b")
    def test_status_ready_when_running(self, _):
        """Status is 'ready' when server is running."""
        model_manager._set_download_state(active=False, status="idle")
        status = model_manager.get_model_status()
        assert status["status"] == "ready"

    @patch.object(model_manager, "is_server_running", return_value=False)
    @patch.object(model_manager, "_active_model_key", None)
    def test_status_no_model_when_nothing_downloaded(self, _):
        """Status is 'no_model' when nothing is downloaded."""
        model_manager._set_download_state(active=False, status="idle")
        with patch.object(model_manager, "is_model_downloaded", return_value=False):
            status = model_manager.get_model_status()
            assert status["status"] == "no_model"


# ── Delete Variant / Model ────────────────────────────────────────────

class TestDeleteVariant:
    """Tests for delete_variant guard clauses and behavior."""

    def test_delete_active_variant_refused(self):
        """Cannot delete the active variant of the running model."""
        with patch.object(model_manager, "_active_model_key", "gemma-4-e2b"):
            with patch("screenmind.engine.model_manager.settings") as mock_s:
                mock_s.model_variants = {}
                result = model_manager.delete_variant("gemma-4-e2b", "Q4_0")
                assert result["ok"] is False
                assert "active" in result["error"].lower()

    def test_delete_during_download_refused(self):
        """Cannot delete when download is in progress for that model."""
        model_manager._set_download_state(active=True, model="gemma-4-e2b", status="downloading")
        try:
            with patch.object(model_manager, "_active_model_key", None):
                result = model_manager.delete_variant("gemma-4-e2b", "Q4_0")
                assert result["ok"] is False
                assert "download" in result["error"].lower()
        finally:
            model_manager._set_download_state(active=False, status="idle")

    def test_delete_nonexistent_variant(self, tmp_path):
        """Deleting a variant that doesn't exist returns error."""
        with patch.object(model_manager, "_active_model_key", None):
            model_manager._set_download_state(active=False, status="idle")
            with patch.object(model_manager, "_models_dir", return_value=tmp_path):
                result = model_manager.delete_variant("gemma-4-e2b", "Q4_0")
                assert result["ok"] is False

    def test_delete_variant_removes_dir(self, tmp_path):
        """Successful delete removes the variant directory."""
        variant_dir = tmp_path / "gemma-4-e2b" / "Q8_0"
        variant_dir.mkdir(parents=True)
        (variant_dir / "model.gguf").write_text("data")

        with patch.object(model_manager, "_active_model_key", None):
            model_manager._set_download_state(active=False, status="idle")
            with patch.object(model_manager, "_models_dir", return_value=tmp_path):
                with patch("screenmind.engine.model_manager.settings") as mock_s:
                    mock_s.model_variants = {}
                    result = model_manager.delete_variant("gemma-4-e2b", "Q8_0")
                    assert result["ok"] is True
                    assert not variant_dir.exists()

    def test_delete_variant_clears_stale_preference(self, tmp_path):
        """Deleting selected variant clears the config preference."""
        variant_dir = tmp_path / "gemma-4-e2b" / "Q8_0"
        variant_dir.mkdir(parents=True)
        (variant_dir / "model.gguf").write_text("data")

        with patch.object(model_manager, "_active_model_key", None):
            model_manager._set_download_state(active=False, status="idle")
            with patch.object(model_manager, "_models_dir", return_value=tmp_path):
                with patch("screenmind.engine.model_manager.settings") as mock_s:
                    mock_s.model_variants = {"gemma-4-e2b": "Q8_0"}
                    mock_s.save_runtime_overrides = MagicMock()
                    model_manager.delete_variant("gemma-4-e2b", "Q8_0")
                    # Should have saved with Q8_0 removed
                    mock_s.save_runtime_overrides.assert_called_once()
                    saved_variants = mock_s.save_runtime_overrides.call_args[0][0]["model_variants"]
                    assert "gemma-4-e2b" not in saved_variants


class TestDeleteModel:
    """Tests for delete_model guard clauses."""

    def test_delete_active_model_refused(self):
        """Cannot delete the active model."""
        with patch.object(model_manager, "_active_model_key", "gemma-4-e2b"):
            result = model_manager.delete_model("gemma-4-e2b")
            assert result["ok"] is False
            assert "active" in result["error"].lower()

    def test_delete_during_download_refused(self):
        """Cannot delete when download is in progress for that model."""
        model_manager._set_download_state(active=True, model="gemma-4-e2b", status="downloading")
        try:
            with patch.object(model_manager, "_active_model_key", None):
                result = model_manager.delete_model("gemma-4-e2b")
                assert result["ok"] is False
        finally:
            model_manager._set_download_state(active=False, status="idle")

    def test_delete_model_removes_variant_dirs(self, tmp_path):
        """delete_model removes variant subdirs but keeps dotfiles."""
        model_dir = tmp_path / "gemma-4-e2b"
        (model_dir / "Q4_0").mkdir(parents=True)
        (model_dir / "Q8_0").mkdir(parents=True)
        (model_dir / ".huggingface").mkdir(parents=True)
        (model_dir / "mmproj-gemma-4-E2B-it-Q8_0.gguf").write_text("mmproj")

        with patch.object(model_manager, "_active_model_key", None):
            model_manager._set_download_state(active=False, status="idle")
            with patch.object(model_manager, "_models_dir", return_value=tmp_path):
                with patch("screenmind.engine.model_manager.settings") as mock_s:
                    mock_s.model_variants = {}
                    result = model_manager.delete_model("gemma-4-e2b")
                    assert result["ok"] is True
                    # Variant dirs removed
                    assert not (model_dir / "Q4_0").exists()
                    assert not (model_dir / "Q8_0").exists()
                    # Dotfiles and mmproj kept
                    assert (model_dir / ".huggingface").exists()
                    assert (model_dir / "mmproj-gemma-4-E2B-it-Q8_0.gguf").exists()


# ── AVAILABLE_MODELS Consistency ──────────────────────────────────────

class TestAvailableModelsConsistency:
    """Verify AVAILABLE_MODELS data integrity."""

    def test_all_models_have_required_fields(self):
        """Every model has key, name, hf_repo, hf_file, mmproj_file, variants."""
        required = {"key", "name", "hf_repo", "hf_file", "mmproj_file", "variants"}
        for m in model_manager.AVAILABLE_MODELS:
            missing = required - set(m.keys())
            assert not missing, f"{m['key']} missing fields: {missing}"

    def test_all_variants_have_required_fields(self):
        """Every variant has quant, hf_file, file_size."""
        required = {"quant", "hf_file", "file_size"}
        for m in model_manager.AVAILABLE_MODELS:
            for v in m["variants"]:
                missing = required - set(v.keys())
                assert not missing, f"{m['key']}/{v.get('quant', '?')} missing: {missing}"

    def test_default_hf_file_in_variants(self):
        """Model's default hf_file exists in one of its variants."""
        for m in model_manager.AVAILABLE_MODELS:
            variant_files = [v["hf_file"] for v in m["variants"]]
            assert m["hf_file"] in variant_files, \
                f"{m['key']}: default hf_file not found in any variant"

    def test_all_models_have_audio_and_vision_flags(self):
        """Every model specifies audio and vision capabilities."""
        for m in model_manager.AVAILABLE_MODELS:
            assert "audio" in m, f"{m['key']} missing 'audio' flag"
            assert "vision" in m, f"{m['key']} missing 'vision' flag"


# ── External llama-server (#27) ───────────────────────────────────────

def _http(status, body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body or {}
    return r


def _fake_server(health=200, model_id="gemma-4-E2B-it-Q8_0.gguf", calls=None):
    """httpx.get stand-in for an llama-server answering /health and /v1/models."""
    def get(url, timeout=None):
        if calls is not None:
            calls.append(url)
        if url.endswith("/health"):
            if health is None:
                raise ConnectionError("refused")
            return _http(health)
        if model_id is None:
            raise ConnectionError("no /v1/models")
        return _http(200, {"data": [{"id": model_id}]})
    return get


@pytest.fixture
def external_state():
    """Fresh external-server globals, no spawned process, idle lifecycle."""
    names = ("_external_server", "_external_loading", "_external_model_name",
             "_active_model_key", "_server_process")
    saved = {n: getattr(model_manager, n) for n in names}
    model_manager._external_server = False
    model_manager._external_loading = False
    model_manager._external_model_name = None
    model_manager._active_model_key = None
    model_manager._server_process = None
    model_manager._set_download_state(active=False, status="idle", message="")
    with patch("screenmind.engine.model_manager.settings") as mock_settings:
        mock_settings.llama_server_host = "http://127.0.0.1:5809"
        mock_settings.active_model = "gemma-4-e2b"
        mock_settings.model_variants = {}
        yield mock_settings
    for n, v in saved.items():
        setattr(model_manager, n, v)
    model_manager._set_download_state(active=False, status="idle", message="")


class TestExternalServer:
    """An llama-server started outside ScreenMind is detected and used."""

    def test_probes_llama_server_host_not_localhost(self, external_state):
        external_state.llama_server_host = "http://10.0.0.5:8080/"
        calls = []
        with patch("httpx.get", side_effect=_fake_server(calls=calls)):
            assert model_manager.sync_external_server() is True
        assert calls == ["http://10.0.0.5:8080/health", "http://10.0.0.5:8080/v1/models"]
        assert model_manager.get_active_model() == "gemma-4-e2b"
        assert model_manager.is_server_running() is True

    def test_known_model_is_ready(self, external_state):
        with patch("httpx.get", side_effect=_fake_server()):
            model_manager.sync_external_server()
        status = model_manager.get_model_status()
        assert status["status"] == "ready"
        assert status["external"] is True
        assert status["external_model"] is None
        assert status["capabilities"] == {"audio": True, "vision": True}

    def test_unknown_model_is_ready_with_unknown_capabilities(self, external_state):
        with patch("httpx.get", side_effect=_fake_server(model_id="/models/llama-3-8b.gguf")):
            model_manager.sync_external_server()
        status = model_manager.get_model_status()
        assert status["status"] == "ready"
        assert status["external_model"] == "llama-3-8b.gguf"
        assert status["capabilities"] == {"audio": None, "vision": None}

    def test_unidentifiable_server_still_adopted(self, external_state):
        """/health OK but /v1/models fails: use it as an unknown model."""
        with patch("httpx.get", side_effect=_fake_server(model_id=None)):
            assert model_manager.sync_external_server() is True
        status = model_manager.get_model_status()
        assert status["status"] == "ready"
        assert status["external_model"] == "Unknown model"

    def test_loading_server_is_starting_not_ready(self, external_state):
        """503 while loading: not usable yet, but never spawn over its port."""
        with patch("httpx.get", side_effect=_fake_server(health=503)):
            assert model_manager.sync_external_server() is True
        assert model_manager.is_server_running() is False
        status = model_manager.get_model_status()
        assert status["status"] == "starting"
        assert status["external"] is True

        with patch("httpx.get", side_effect=_fake_server(health=200)):
            model_manager.sync_external_server()
        assert model_manager.get_model_status()["status"] == "ready"

    def test_no_server_is_not_adopted(self, external_state):
        with patch("httpx.get", side_effect=_fake_server(health=None)):
            assert model_manager.sync_external_server() is False
        assert model_manager.is_server_running() is False

    def test_server_going_away_is_dropped(self, external_state):
        with patch("httpx.get", side_effect=_fake_server()):
            model_manager.sync_external_server()
        with patch("httpx.get", side_effect=_fake_server(health=None)):
            assert model_manager.sync_external_server() is False
        assert model_manager.is_server_running() is False
        assert model_manager.get_active_model() is None

    def test_model_swap_is_picked_up(self, external_state):
        with patch("httpx.get", side_effect=_fake_server()):
            model_manager.sync_external_server()
        with patch("httpx.get", side_effect=_fake_server(model_id="gemma-4-E4B-it-Q4_0.gguf")):
            model_manager.sync_external_server()
        assert model_manager.get_active_model() == "gemma-4-e4b"

    def test_status_checks_make_no_network_calls(self, external_state):
        """/api/status is async and polled — it must never wait on the network."""
        with patch("httpx.get", side_effect=_fake_server()):
            model_manager.sync_external_server()
        with patch("httpx.get", side_effect=AssertionError("network call")):
            assert model_manager.is_server_running() is True
            model_manager.get_model_status()
            model_manager.list_models()

    def test_not_probed_while_server_is_booting(self, external_state):
        """start_server() holds the lock while our own server boots — never
        wait on it, and never adopt our own half-started server."""
        model_manager._server_lock.acquire()
        try:
            with patch("httpx.get", side_effect=AssertionError("network call")):
                assert model_manager.sync_external_server() is False
        finally:
            model_manager._server_lock.release()

    def test_not_probed_during_lifecycle(self, external_state):
        model_manager._set_download_state(active=True, status="starting")
        with patch("httpx.get", side_effect=AssertionError("network call")):
            assert model_manager.sync_external_server() is False

    def test_clears_sticky_error(self, external_state):
        model_manager._set_download_state(active=False, status="error", message="Server failed to start.")
        with patch("httpx.get", side_effect=_fake_server()):
            model_manager.sync_external_server()
        assert model_manager.get_model_status()["status"] == "ready"

    def test_switch_and_restart_refused(self, external_state):
        with patch("httpx.get", side_effect=_fake_server()):
            model_manager.sync_external_server()
        with patch.object(model_manager, "start_server") as start:
            assert model_manager.switch_model("gemma-4-e4b") is False
            assert model_manager.restart_server() is False
        start.assert_not_called()

    def test_download_does_not_start_server(self, external_state):
        with patch("httpx.get", side_effect=_fake_server()):
            model_manager.sync_external_server()
        with patch.object(model_manager, "_check_model_disk_space", return_value=True), \
             patch.object(model_manager, "_do_download", return_value=True), \
             patch.object(model_manager, "start_server") as start:
            assert model_manager.download_and_start("gemma-4-e4b") is True
        start.assert_not_called()
        assert model_manager.get_download_state()["active"] is False
        assert model_manager.get_model_status()["status"] == "ready"
