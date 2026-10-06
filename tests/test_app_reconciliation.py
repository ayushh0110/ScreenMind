"""Tests for three-signal app reconciliation (Issue #6).

Validates that _normalize() correctly reconciles OS-detected app name,
window title, and Gemma's visual guess to produce accurate app_name
and activity_category values.

See: https://github.com/ayushh0110/ScreenMind/issues/6
"""

import pytest

from screenmind.engine.analyzer import (
    GemmaAnalyzer,
    _extract_app_from_title,
    _extract_simple_title,
    _is_browser_window,
    _is_more_specific_name,
    _lookup_known_category,
)
from screenmind.storage.models import ActivityRecord


# ── Helper: _extract_app_from_title ──────────────────────────────────────────


class TestExtractAppFromTitle:
    """Test the L1 title ' - ' extraction logic."""

    def test_standard_convention(self):
        assert _extract_app_from_title("main.py - Visual Studio Code") == "Visual Studio Code"

    def test_browser_title(self):
        assert _extract_app_from_title("YouTube - Google Chrome") == "Google Chrome"

    def test_multiple_dashes(self):
        assert _extract_app_from_title("John Doe - Engineer - LinkedIn") == "LinkedIn"

    def test_en_dash(self):
        assert _extract_app_from_title("main.py \u2013 IntelliJ IDEA") == "IntelliJ IDEA"

    def test_em_dash(self):
        assert _extract_app_from_title("Document \u2014 LibreOffice") == "LibreOffice"

    def test_no_dash(self):
        assert _extract_app_from_title("AnyType") is None

    def test_none_input(self):
        assert _extract_app_from_title(None) is None

    def test_empty_string(self):
        assert _extract_app_from_title("") is None

    def test_filename_rejection_mkv(self):
        """Reversed convention: 'mpv - movie.mkv' should NOT extract 'movie.mkv'."""
        assert _extract_app_from_title("mpv - movie.mkv") is None

    def test_filename_rejection_py(self):
        assert _extract_app_from_title("nano - config.py") is None

    def test_filename_rejection_txt(self):
        assert _extract_app_from_title("vim - notes.txt") is None

    def test_app_name_with_dot_not_extension(self):
        """App names like 'Vue.js' should not be rejected if not a known extension... 
        but 'js' IS a known extension so it would be rejected."""
        # This is a known limitation — very rare in practice
        assert _extract_app_from_title("Project - Vue.js") is None

    def test_candidate_too_long(self):
        long_name = "A" * 41
        assert _extract_app_from_title(f"content - {long_name}") is None

    def test_candidate_too_short(self):
        assert _extract_app_from_title("content - A") is None

    def test_discord_title(self):
        assert _extract_app_from_title("#general - Discord") == "Discord"

    def test_spotify_title(self):
        assert _extract_app_from_title("Song Name - Artist - Spotify") == "Spotify"


# ── Helper: _extract_simple_title ────────────────────────────────────────────


class TestExtractSimpleTitle:
    """Test the L3 simple title extraction logic."""

    def test_clean_app_name(self):
        assert _extract_simple_title("AnyType") == "AnyType"

    def test_calculator(self):
        assert _extract_simple_title("Calculator") == "Calculator"

    def test_rejects_path(self):
        assert _extract_simple_title("~/Documents") is None

    def test_rejects_terminal_prompt(self):
        assert _extract_simple_title("user@host: ~") is None

    def test_rejects_untitled(self):
        assert _extract_simple_title("Untitled") is None

    def test_rejects_new_document(self):
        assert _extract_simple_title("New Document") is None

    def test_rejects_document_prefix(self):
        assert _extract_simple_title("Document1") is None

    def test_rejects_long_title(self):
        assert _extract_simple_title("This is a very long window title text") is None

    def test_rejects_file_extension(self):
        assert _extract_simple_title("config.py") is None

    def test_microsoft_teams(self):
        assert _extract_simple_title("Microsoft Teams") == "Microsoft Teams"

    def test_empty_string(self):
        assert _extract_simple_title("") is None

    def test_whitespace_only(self):
        assert _extract_simple_title("   ") is None


# ── Helper: _is_more_specific_name ───────────────────────────────────────────


class TestIsMoreSpecificName:
    """Test word-boundary substring matching."""

    def test_code_to_vs_code(self):
        assert _is_more_specific_name("code", "vs code") is True

    def test_chrome_to_google_chrome(self):
        assert _is_more_specific_name("chrome", "google chrome") is True

    def test_obs_to_obs_studio(self):
        assert _is_more_specific_name("obs", "obs studio") is True

    def test_st_not_steam(self):
        """'st' should NOT match 'steam' — different apps."""
        assert _is_more_specific_name("st", "steam") is False

    def test_vim_not_neovim(self):
        """'vim' should NOT match 'neovim' — different apps."""
        assert _is_more_specific_name("vim", "neovim") is False

    def test_same_length(self):
        assert _is_more_specific_name("discord", "discord") is False

    def test_gemma_shorter(self):
        assert _is_more_specific_name("visual studio code", "vs code") is False

    def test_alacritty_not_vs_code(self):
        assert _is_more_specific_name("alacritty", "vs code") is False

    def test_hyper_to_hyper_terminal(self):
        assert _is_more_specific_name("hyper", "hyper terminal") is True


# ── Helper: _is_browser_window ───────────────────────────────────────────────


class TestIsBrowserWindow:
    """Test browser detection via title suffix."""

    def test_chrome(self):
        assert _is_browser_window("YouTube - Google Chrome") is True

    def test_firefox(self):
        assert _is_browser_window("Gmail - Mozilla Firefox") is True

    def test_edge(self):
        assert _is_browser_window("GitHub - Microsoft Edge") is True

    def test_brave(self):
        assert _is_browser_window("Reddit - Brave") is True

    def test_not_browser(self):
        assert _is_browser_window("main.py - Visual Studio Code") is False

    def test_none(self):
        assert _is_browser_window(None) is False

    def test_no_suffix(self):
        assert _is_browser_window("AnyType") is False

    def test_pwa_no_suffix(self):
        """Edge PWAs don't have browser suffix."""
        assert _is_browser_window("Microsoft Teams") is False

    def test_process_name_firefox(self):
        """Fallback: OS reports 'firefox' even when title has no browser suffix."""
        assert _is_browser_window("Build Log - Jenkins", app_name_hint="firefox") is True

    def test_process_name_chrome(self):
        assert _is_browser_window("Some Web App", app_name_hint="chrome") is True

    def test_process_name_non_browser(self):
        """Non-browser process should not trigger browser detection."""
        assert _is_browser_window("Some Window", app_name_hint="alacritty") is False

    def test_title_suffix_takes_priority(self):
        """Title suffix detection works even without app_name_hint."""
        assert _is_browser_window("YouTube - Google Chrome", app_name_hint=None) is True


# ── Helper: _lookup_known_category ───────────────────────────────────────────


class TestLookupKnownCategory:
    """Test known app category lookup with fuzzy matching."""

    def test_exact_match(self):
        assert _lookup_known_category("alacritty") == "terminal"

    def test_case_insensitive(self):
        assert _lookup_known_category("Alacritty") == "terminal"

    def test_anytype(self):
        assert _lookup_known_category("AnyType") == "writing"

    def test_discord(self):
        assert _lookup_known_category("Discord") == "communication"

    def test_spotify(self):
        assert _lookup_known_category("Spotify") == "media"

    def test_linux_truncation(self):
        """Linux /proc/pid/comm truncates to 15 chars."""
        assert _lookup_known_category("gnome-terminal-") == "terminal"

    def test_version_suffix(self):
        assert _lookup_known_category("anytype 0.38") == "writing"

    def test_word_in_phrase(self):
        """'Microsoft Teams' should match 'teams' in dict."""
        assert _lookup_known_category("Microsoft Teams") == "communication"

    def test_unknown_app(self):
        assert _lookup_known_category("myobscureapp") is None

    def test_trailing_whitespace(self):
        assert _lookup_known_category("  alacritty  ") == "terminal"

    def test_pwsh(self):
        assert _lookup_known_category("pwsh") == "terminal"

    def test_zoom(self):
        assert _lookup_known_category("zoom") == "meeting"

    def test_greedy_prefix_not_matches_notion(self):
        """'not' should NOT match 'notion' — too short for reverse prefix."""
        assert _lookup_known_category("not") is None

    def test_greedy_prefix_sl_matches_slack(self):
        """'sl' should NOT match 'slack' — too short."""
        assert _lookup_known_category("sl") is None

    def test_greedy_prefix_di_matches_discord(self):
        """'di' should NOT match 'discord' — too short."""
        assert _lookup_known_category("di") is None

    def test_valid_truncation_still_works(self):
        """'gnome-termin' (3 chars short) should still match 'gnome-terminal'."""
        assert _lookup_known_category("gnome-termin") == "terminal"


# ── Full reconciliation: _normalize() scenarios ─────────────────────────────


@pytest.fixture
def analyzer():
    return GemmaAnalyzer()


def _make_record(**kwargs):
    """Create an ActivityRecord with defaults for testing."""
    defaults = {
        "app_name": "unknown",
        "activity_category": "other",
        "activity_summary": "test",
        "mood": "neutral",
        "confidence": 0.8,
    }
    defaults.update(kwargs)
    return ActivityRecord(**defaults)


class TestReconcileAppName:
    """Test the 4-level hierarchy for app name resolution."""

    @pytest.fixture(autouse=True)
    def _non_macos(self, monkeypatch):
        # These scenarios use Windows/Linux-style process names and titles.
        # macOS resolves the OS owner first; see TestReconcileAppNameMacOS.
        monkeypatch.setattr("screenmind.engine.analyzer.sys.platform", "win32")

    def test_scenario_1_alacritty_misidentified(self, analyzer):
        """Alacritty (terminal) misidentified as VS Code."""
        record = _make_record(app_name="VS Code", activity_category="coding")
        result = analyzer._normalize(record, app_name_hint="Alacritty", window_title="user@host: ~")
        assert result.app_name == "Alacritty"
        assert result.activity_category == "terminal"

    def test_scenario_2_anytype_misidentified(self, analyzer):
        """AnyType (notes) misidentified as VS Code."""
        record = _make_record(app_name="VS Code", activity_category="coding")
        result = analyzer._normalize(record, app_name_hint="AnyType", window_title="AnyType")
        assert result.app_name == "AnyType"
        assert result.activity_category == "writing"

    def test_scenario_3_vscode_more_specific(self, analyzer):
        """OS gives 'code', Gemma gives friendlier 'VS Code'."""
        record = _make_record(app_name="VS Code", activity_category="coding")
        result = analyzer._normalize(record, app_name_hint="code",
                                     window_title="main.py - Visual Studio Code")
        # L1 extracts "Visual Studio Code" from title
        # Compare: "visual studio code" is NOT a substring of "vs code" (different)
        # So we use the title extraction: "Visual Studio Code"
        assert result.app_name == "Visual Studio Code"

    def test_scenario_4_chrome_youtube(self, analyzer):
        """Chrome showing YouTube — category should be 'media', not 'browsing'."""
        record = _make_record(app_name="YouTube", activity_category="media")
        result = analyzer._normalize(record, app_name_hint="chrome",
                                     window_title="YouTube - Google Chrome")
        assert result.app_name == "Google Chrome"
        assert result.activity_category == "media"  # Browser: trust Gemma

    def test_scenario_5_firefox_gmail(self, analyzer):
        """Firefox showing Gmail — category should be 'communication'."""
        record = _make_record(app_name="Gmail", activity_category="communication")
        result = analyzer._normalize(record, app_name_hint="firefox",
                                     window_title="Gmail - Mozilla Firefox")
        assert result.app_name == "Mozilla Firefox"
        assert result.activity_category == "communication"  # Browser: trust Gemma

    def test_scenario_6_electron_discord_title(self, analyzer):
        """Electron wrapper with Discord in title."""
        record = _make_record(app_name="Discord", activity_category="communication")
        result = analyzer._normalize(record, app_name_hint="electron",
                                     window_title="#general - Discord")
        assert result.app_name == "Discord"
        assert result.activity_category == "communication"

    def test_scenario_7_electron_no_title(self, analyzer):
        """Electron wrapper, unhelpful title — use Gemma."""
        record = _make_record(app_name="Slack", activity_category="communication")
        result = analyzer._normalize(record, app_name_hint="electron",
                                     window_title="Untitled")
        assert result.app_name == "Slack"

    def test_scenario_8_msedge_pwa_teams(self, analyzer):
        """Edge PWA running Teams — no browser suffix."""
        record = _make_record(app_name="Teams", activity_category="communication")
        result = analyzer._normalize(record, app_name_hint="msedge",
                                     window_title="Microsoft Teams")
        assert result.app_name == "Microsoft Teams"
        assert result.activity_category == "communication"

    def test_scenario_9_msedge_browser(self, analyzer):
        """Edge as actual browser."""
        record = _make_record(app_name="GitHub", activity_category="browsing")
        result = analyzer._normalize(record, app_name_hint="msedge",
                                     window_title="GitHub - Microsoft Edge")
        assert result.app_name == "Microsoft Edge"
        assert result.activity_category == "browsing"  # Browser: trust Gemma

    def test_scenario_10_uwp_calculator(self, analyzer):
        """Windows UWP Calculator via ApplicationFrameHost."""
        record = _make_record(app_name="Calculator", activity_category="other")
        result = analyzer._normalize(record, app_name_hint="ApplicationFrameHost",
                                     window_title="Calculator")
        assert result.app_name == "Calculator"

    def test_scenario_11_os_none_anytype_title(self, analyzer):
        """OS returns None, but title says 'AnyType'."""
        record = _make_record(app_name="VS Code", activity_category="coding")
        result = analyzer._normalize(record, app_name_hint=None, window_title="AnyType")
        assert result.app_name == "AnyType"
        assert result.activity_category == "writing"

    def test_scenario_12_os_none_discord_title(self, analyzer):
        """OS returns None, Discord in title."""
        record = _make_record(app_name="Discord", activity_category="communication")
        result = analyzer._normalize(record, app_name_hint=None,
                                     window_title="#general - Discord")
        assert result.app_name == "Discord"
        assert result.activity_category == "communication"

    def test_scenario_13_os_none_untitled(self, analyzer):
        """OS=None, title='Untitled' — unavoidable: must use Gemma."""
        record = _make_record(app_name="VS Code", activity_category="coding")
        result = analyzer._normalize(record, app_name_hint=None, window_title="Untitled")
        assert result.app_name == "VS Code"
        assert result.activity_category == "coding"

    def test_scenario_14_st_not_steam(self, analyzer):
        """Short name 'st' (terminal) should NOT match Gemma's 'Steam'."""
        record = _make_record(app_name="Steam", activity_category="media")
        result = analyzer._normalize(record, app_name_hint="st", window_title="user@host: ~")
        assert result.app_name == "st"
        assert result.activity_category == "terminal"

    def test_scenario_15_vim_not_neovim(self, analyzer):
        """vim should NOT be treated as a more-specific version of neovim."""
        record = _make_record(app_name="Neovim", activity_category="coding")
        result = analyzer._normalize(record, app_name_hint="vim", window_title="config.py")
        assert result.app_name == "vim"

    def test_scenario_16_gnome_terminal_truncated(self, analyzer):
        """Linux 15-char truncation: 'gnome-terminal-'."""
        record = _make_record(app_name="Terminal", activity_category="terminal")
        result = analyzer._normalize(record, app_name_hint="gnome-terminal-",
                                     window_title="user@host: ~")
        assert result.app_name == "gnome-terminal-"
        assert result.activity_category == "terminal"

    def test_scenario_17_all_agree(self, analyzer):
        """All signals agree — no change needed."""
        record = _make_record(app_name="Discord", activity_category="communication")
        result = analyzer._normalize(record, app_name_hint="Discord",
                                     window_title="#general - Discord")
        assert result.app_name == "Discord"
        assert result.activity_category == "communication"

    def test_scenario_18_unknown_app(self, analyzer):
        """Unknown app not in dict — use OS name, keep Gemma category."""
        record = _make_record(app_name="VS Code", activity_category="coding")
        result = analyzer._normalize(record, app_name_hint="myobscureapp",
                                     window_title="Some Window")
        assert result.app_name == "myobscureapp"
        assert result.activity_category == "coding"  # Not in known dict → Gemma stays

    def test_scenario_19_browser_process_shadows_title(self, analyzer):
        """Firefox tab without browser suffix — OS 'firefox' still triggers browser detection."""
        record = _make_record(app_name="Jenkins", activity_category="browsing")
        result = analyzer._normalize(record, app_name_hint="firefox",
                                     window_title="Build Log - Jenkins")
        assert result.app_name == "Jenkins"  # L1 extracts from title
        assert result.activity_category == "browsing"  # Browser: trusts Gemma


class TestReconcileAppNameMacOS:
    """On macOS the Quartz window owner wins over title parsing."""

    @pytest.fixture(autouse=True)
    def _macos(self, monkeypatch):
        monkeypatch.setattr("screenmind.engine.analyzer.sys.platform", "darwin")

    def test_terminal_title_suffix_ignored(self, analyzer):
        """Terminal titles end in the window size, not the app name."""
        record = _make_record(app_name="Terminal", activity_category="terminal")
        result = analyzer._normalize(record, app_name_hint="Terminal",
                                     window_title="ScreenMind — python — 120×30")
        assert result.app_name == "Terminal"
        assert result.activity_category == "terminal"

    def test_owner_beats_title_segment(self, analyzer):
        record = _make_record(app_name="Slack", activity_category="communication")
        result = analyzer._normalize(record, app_name_hint="Slack",
                                     window_title="general (Channel) - TripleTen - Slack")
        assert result.app_name == "Slack"

    def test_no_owner_falls_back_to_title(self, analyzer):
        record = _make_record(app_name="Code", activity_category="coding")
        result = analyzer._normalize(record, app_name_hint=None,
                                     window_title="main.py - Visual Studio Code")
        assert result.app_name == "Visual Studio Code"


class TestBackwardCompatibility:
    """Ensure old calling convention (no hints) works unchanged."""

    def test_no_hints(self, analyzer):
        """Calling _normalize without hints should behave exactly like before."""
        record = _make_record(app_name="Chrome", activity_category="browsing", mood="productive")
        result = analyzer._normalize(record)
        assert result.app_name == "Chrome"
        assert result.activity_category == "browsing"
        assert result.mood == "productive"

    def test_no_hints_invalid_category(self, analyzer):
        record = _make_record(activity_category="invalid_thing", mood="unknown_mood")
        result = analyzer._normalize(record)
        assert result.activity_category == "other"
        assert result.mood == "neutral"

    def test_no_hints_confidence_clamping(self, analyzer):
        record = _make_record(confidence=0.0)
        result = analyzer._normalize(record)
        # confidence=0.0 with non-empty summary → default to 0.7
        assert result.confidence == 0.7
