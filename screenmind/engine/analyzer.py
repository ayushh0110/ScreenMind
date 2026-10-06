"""
Gemma 4 Screenshot Analyzer
Sends screenshots to Gemma 4 via llama-server and parses structured activity data.
The core intelligence engine of ScreenMind.

Three analysis methods:
  - analyze_screenshot(): Merged mode — single call with thinking for both
    analysis + layout detection. ~76s, best accuracy.
  - analyze_screenshot_balanced(): Balanced mode — thinking enabled for analysis
    only (no layout). ~40-50s, better quality than fast.
  - analyze_screenshot_fast(): Fast mode — no-thinking call for analysis only.
    ~12s, layout handled by OCR clustering in layout_analyzer.py.
"""

import base64
import logging
import io
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

from PIL import Image

from screenmind.config import settings
from screenmind.engine import llm_client
from screenmind.storage.models import ActivityRecord

logger = logging.getLogger("screenmind.engine.analyzer")


# ── The Prompt ───────────────────────────────────────────────────────────────
# This is the most critical piece of the entire project.
# It turns a raw screenshot into structured intelligence.

VALID_CATEGORIES = {
    "coding", "browsing", "communication", "writing",
    "design", "media", "terminal", "meeting", "idle", "other",
}

VALID_MOODS = {"productive", "distracted", "collaborative", "learning", "neutral"}


# ── App Reconciliation Data ──────────────────────────────────────────────────
# Three-signal reconciliation: OS process name + window title + Gemma vision.
# See: https://github.com/ayushh0110/ScreenMind/issues/6

# Process names that are generic wrappers/runtimes — they tell us nothing
# about the actual application.  When the OS returns one of these, we skip it
# and fall back to window-title extraction or Gemma's visual guess.
GENERIC_PROCESS_NAMES = frozenset({
    # Language runtimes
    "electron", "java", "javaw", "python", "pythonw", "python3",
    "node", "ruby", "perl", "dotnet",
    # OS-level wrappers
    "applicationframehost",   # Windows UWP (Calculator, Mail, Settings …)
    "wslhost", "conhost",     # Windows console wrappers
    "gnome-shell", "plasmashell",  # Linux desktop shells
    # Framework / browser-as-platform wrappers
    "cefsharp", "nwjs", "tauri",
    "msedge",  # Edge browser AND Edge PWAs — title disambiguates
})

# Known process names → correct activity_category.
# Used to override Gemma's category for NON-BROWSER windows only.
# Browsers are detected via title suffix (see _BROWSER_TITLE_SUFFIXES)
# and always trust Gemma's content-aware category.
KNOWN_APP_CATEGORIES = {
    # Terminal emulators (most commonly misidentified as "coding")
    "alacritty": "terminal", "kitty": "terminal", "wezterm": "terminal",
    "hyper": "terminal", "iterm2": "terminal", "iterm": "terminal",
    "terminal": "terminal", "windowsterminal": "terminal",
    "cmd": "terminal", "powershell": "terminal", "pwsh": "terminal",
    "wt": "terminal",
    "gnome-terminal": "terminal", "konsole": "terminal", "tilix": "terminal",
    "foot": "terminal", "st": "terminal", "urxvt": "terminal", "xterm": "terminal",
    # Communication
    "discord": "communication", "slack": "communication",
    "teams": "communication", "microsoft teams": "communication",
    "telegram": "communication", "whatsapp": "communication",
    "signal": "communication",
    "thunderbird": "communication", "outlook": "communication",
    # Writing / Notes (often misidentified as "coding" due to dark UI)
    "anytype": "writing", "obsidian": "writing", "notion": "writing",
    "typora": "writing", "marktext": "writing", "logseq": "writing",
    "notepad": "writing", "wordpad": "writing",
    "libreoffice": "writing",
    # Media
    "spotify": "media", "vlc": "media", "mpv": "media",
    # Design
    "figma": "design", "gimp": "design", "inkscape": "design",
    # Meetings
    "zoom": "meeting",
}

# File extensions used to reject filename candidates from title extraction.
# Prevents reversed conventions like "mpv - movie.mkv" → extracting "movie.mkv".
_FILE_EXTENSIONS = frozenset({
    # Code
    'py', 'js', 'ts', 'rs', 'go', 'java', 'c', 'cpp', 'h', 'rb', 'php', 'cs',
    'kt', 'swift', 'lua', 'sh', 'bash', 'zsh', 'ps1',
    # Web / Config
    'html', 'css', 'json', 'yaml', 'yml', 'toml', 'xml', 'ini', 'cfg', 'conf',
    # Documents
    'txt', 'md', 'log', 'csv', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    # Media
    'mp4', 'mkv', 'avi', 'mov', 'webm', 'mp3', 'flac', 'wav', 'ogg',
    # Images
    'png', 'jpg', 'jpeg', 'gif', 'svg', 'bmp', 'webp', 'ico',
})

# Window title suffixes that identify a browser window.
# When detected, Gemma's activity_category is trusted because it reflects
# the *content* being viewed (YouTube → media, Gmail → communication),
# which is more useful than a generic "browsing" override.
_BROWSER_TITLE_SUFFIXES = (
    "- Google Chrome", "- Mozilla Firefox", "- Firefox",
    "- Microsoft Edge", "- Brave", "- Opera", "- Safari",
    "- Vivaldi", "- Arc", "- Chromium", "- Zen Browser",
)

# Patterns in window titles that indicate content, not an app name.
# Used by _extract_simple_title() to reject non-app-name titles.
_SIMPLE_TITLE_REJECT = ('/', '\\', '@', ':', '$', '#', '~',
                        '.txt', '.py', '.js', '.ts', '.rs', '.go',
                        '.html', '.css', '.md', '.json', '.yaml')

# Known browser process names — secondary detection when title suffix is missing.
# Used as a fallback in _is_browser_window() when L1 title extraction shadows
# the OS browser name (e.g. title="Jenkins" from Firefox tab without suffix).
_BROWSER_PROCESS_NAMES = frozenset({
    "chrome", "chromium", "firefox", "firefox-esr",
    "brave", "opera", "safari", "vivaldi", "arc",
    "msedge",  # Also in GENERIC_PROCESS_NAMES — intentional overlap
})


def _extract_app_from_title(window_title: Optional[str]) -> Optional[str]:
    """Extract app name from the 'content - AppName' title convention.

    Most desktop apps set their window title as ``<document> - <AppName>``.
    This function takes the *last* segment after `` - `` (or `` – ``/`` — ``).

    Returns None if:
      - title is None / empty
      - title has no dash separator
      - the extracted candidate looks like a filename
    """
    if not window_title:
        return None
    # Try each dash variant: hyphen, en-dash, em-dash
    for sep in (" - ", " \u2013 ", " \u2014 "):
        parts = window_title.rsplit(sep, 1)
        if len(parts) == 2:
            candidate = parts[1].strip()
            if 2 <= len(candidate) <= 40:
                # Reject filenames (e.g., "movie.mkv" from "mpv - movie.mkv")
                if '.' in candidate:
                    ext = candidate.rsplit('.', 1)[-1].lower()
                    if ext in _FILE_EXTENSIONS:
                        continue  # Try next separator
                return candidate
    return None


def _extract_simple_title(window_title: str) -> Optional[str]:
    """Use a short clean title as the app name when no other signal is available.

    Handles cases like title='AnyType' or title='Calculator' where there is
    no `` - `` separator.  Rejects titles that look like content (paths,
    terminal prompts, document names).
    """
    title = window_title.strip()
    if not title or len(title) > 25:
        return None
    title_lower = title.lower()
    if any(p in title_lower for p in _SIMPLE_TITLE_REJECT):
        return None
    if title_lower.startswith(('untitled', 'new ', 'document')):
        return None
    return title


def _is_more_specific_name(hierarchy_name_lower: str, gemma_name_lower: str) -> bool:
    """Check if Gemma's name is a more specific (friendlier) version.

    Uses word-boundary matching to prevent false positives like
    ``st`` matching ``steam`` or ``vim`` matching ``neovim``.

    Examples:
      ("code",  "vs code")       → True  (Gemma is more specific)
      ("chrome", "google chrome") → True
      ("st",    "steam")         → False (not a word-boundary match)
      ("vim",   "neovim")        → False
    """
    if len(gemma_name_lower) <= len(hierarchy_name_lower):
        return False  # Gemma is same length or shorter — not more specific
    pattern = r'\b' + re.escape(hierarchy_name_lower) + r'\b'
    return bool(re.search(pattern, gemma_name_lower))


def _is_browser_window(
    window_title: Optional[str],
    app_name_hint: Optional[str] = None,
) -> bool:
    """Detect browser windows via title suffix or OS process name.

    Primary detection: title suffix (e.g. ``"- Google Chrome"``).
    Fallback: OS process name in ``_BROWSER_PROCESS_NAMES``.

    The fallback handles cases where L1 title extraction shadows the
    browser process name — e.g. title='Build Log - Jenkins' in Firefox
    would miss the suffix check, but OS reports 'firefox'.
    """
    if window_title and any(window_title.endswith(s) for s in _BROWSER_TITLE_SUFFIXES):
        return True
    if app_name_hint and app_name_hint.lower().strip() in _BROWSER_PROCESS_NAMES:
        return True
    return False


def _lookup_known_category(app_name: str) -> Optional[str]:
    """Look up the known activity category for an app name.

    Handles:
      - Case differences  (``AnyType`` → ``anytype``)
      - Linux 15-char truncation  (``gnome-terminal-`` → ``gnome-terminal``)
      - Full names containing a dict key  (``Microsoft Teams`` contains ``teams``)
    """
    name = app_name.lower().strip().rstrip("-. ")

    # Exact match (fastest path)
    if name in KNOWN_APP_CATEGORIES:
        return KNOWN_APP_CATEGORIES[name]

    # Prefix match — handles truncation and version suffixes
    #   "gnome-terminal-" → startswith("gnome-terminal")  ✓
    #   "anytype 0.38"    → startswith("anytype")         ✓
    for known, cat in KNOWN_APP_CATEGORIES.items():
        if name.startswith(known):
            return cat
        # Reverse prefix only for minor truncation (e.g. Linux 15-char comm limit).
        # Require name to be at least 5 chars AND within 3 chars of the known key
        # to prevent false matches like "not" → "notion" or "sl" → "slack".
        if known.startswith(name) and len(name) >= 5 and len(name) >= len(known) - 3:
            return cat

    # Word-in-phrase — handles full names like "Microsoft Teams"
    #   re.search(r'\bteams\b', "microsoft teams")  ✓
    for known, cat in KNOWN_APP_CATEGORIES.items():
        if re.search(r'\b' + re.escape(known) + r'\b', name):
            return cat

    return None

ANALYSIS_PROMPT = """You are given two tasks. Divide your attention 40% on analysis and 60% on layout accuracy. Do layout FIRST.

TASK 1 (60% — DO FIRST) — LAYOUT (HIGH ACCURACY REQUIRED):
Look at this screenshot. Identify ALL distinct VISUAL LAYOUT REGIONS with TIGHT boundaries. Try to get as many distinct regions as possible.

ACCURACY IS CRITICAL:
- Give coordinates as PRECISE as possible — measure exactly where each panel starts and ends
- Each region should TIGHTLY wrap ONLY its content — do NOT make regions wider or smaller than the actual visual panel
- For apps with sidebars: sidebars are typically NARROW (10-16% of screen width). The sidebar region should end exactly where the sidebar panel ends (NOT where the main content starts). Do NOT overestimate sidebar width.
- VERTICAL SPLITS ARE CRITICAL: Always look for left-right panel divisions (sidebars, split views, file explorers, profile panels). These are as important as horizontal splits.
- RIGHT PANELS: Many apps have a panel on the right side (profile panels, detail views, info panels). Always check if there is a distinct right-side panel.
- Toolbars/headers are typically THIN (3-6% of screen height). Do NOT overestimate their height.
- Identify regions for complex layouts (sidebar, content columns, panels, toolbars, status bars)
- Especially detect: toolbars at top, status bars at bottom — these get missed often
- "name": descriptive label (e.g., "nav_sidebar", "chat_messages", "email_list", "toolbar", "profile_panel")
- "x_start": left edge as fraction 0.0-1.0 of screen width
- "x_end": right edge as fraction 0.0-1.0
- "y_start": top edge as fraction 0.0-1.0 of screen height
- "y_end": bottom edge as fraction 0.0-1.0
- "content_type": one of: "navigation", "messages", "email_list", "user_profile", "toolbar", "code", "content"

TASK 2 (40% — AFTER LAYOUT) — ANALYSIS:
{"app_name": "main app visible", "activity_category": "ONE of: coding, browsing, communication, writing, design, media, terminal, meeting, idle, other", "activity_summary": "one specific sentence about what user is doing", "detailed_context": "2-3 sentences with specifics like file names, URLs, topics", "visible_text_snippets": ["up to 5 key text items visible"], "mood": "ONE of: productive, distracted, collaborative, learning, neutral", "confidence": 0.85, "scene_description": "DETAILED inventory of everything visible on screen — list each item individually"}

Rules:
- Be SPECIFIC: not "user is coding" but "editing auth_middleware.py in VS Code"
- scene_description: list EVERY visible item individually. Do NOT summarize.

Example layout: [{"name":"toolbar","x_start":0.0,"x_end":1.0,"y_start":0.0,"y_end":0.05,"content_type":"toolbar"},{"name":"nav_sidebar","x_start":0.0,"x_end":0.15,"y_start":0.05,"y_end":0.96,"content_type":"navigation"},{"name":"main_content","x_start":0.15,"x_end":0.75,"y_start":0.05,"y_end":0.96,"content_type":"messages"},{"name":"profile_panel","x_start":0.75,"x_end":1.0,"y_start":0.05,"y_end":0.96,"content_type":"user_profile"},{"name":"taskbar","x_start":0.0,"x_end":1.0,"y_start":0.96,"y_end":1.0,"content_type":"toolbar"}]

Return ONLY a JSON object: {"layout": [...], "analysis": {...}}
Return ONLY valid JSON, nothing else."""


SPLIT_ANALYSIS_PROMPT = """Analyze this screenshot. Return ONLY a JSON object:
{"app_name": "main app visible", "activity_category": "ONE of: coding, browsing, communication, writing, design, media, terminal, meeting, idle, other", "activity_summary": "one specific sentence about what user is doing", "detailed_context": "2-3 sentences with specifics", "visible_text_snippets": ["up to 5 key text items"], "mood": "ONE of: productive, distracted, collaborative, learning, neutral", "confidence": 0.85, "scene_description": "DETAILED inventory of everything visible"}

Be SPECIFIC: not "user is coding" but "editing auth_middleware.py in VS Code".
scene_description: list EVERY visible item individually. Do NOT summarize.
Return ONLY valid JSON."""


class GemmaAnalyzer:
    """
    Analyzes screenshots using Gemma 4 via llama-server.
    Handles image encoding, prompt construction, response parsing,
    and graceful error recovery.
    """

    def __init__(self):
        self._initialized = False

    def _ensure_client(self):
        """Check llama-server is reachable."""
        if not self._initialized:
            if llm_client.is_available():
                self._initialized = True
                logger.info(f"Connected to llama-server at {settings.llama_server_host}")
            else:
                raise ConnectionError(f"Cannot reach llama-server at {settings.llama_server_host}")

    def analyze_screenshot(
        self,
        image: Image.Image,
        window_title: Optional[str] = None,
        app_name_hint: Optional[str] = None,
        ocr_text: Optional[str] = None,
        active_urls: Optional[list] = None,
    ):
        """
        Analyze a screenshot and detect layout in a single merged call.

        Returns:
            Tuple of (ActivityRecord, list of layout region dicts).
            Layout regions may be empty if detection fails.
        """
        self._ensure_client()

        # Build the prompt with optional context hints
        prompt = ANALYSIS_PROMPT
        hints = []
        if app_name_hint:
            hints.append(f"OS-detected app: {app_name_hint}")
        if window_title:
            hints.append(f"Window title: {window_title}")
        if active_urls:
            hints.append(f"URLs visible in screenshot: {', '.join(active_urls)}")
        if ocr_text:
            # Strategy B: unique words, noise removed — reduces token count
            # while preserving vocabulary for Gemma to identify app/content
            words = ocr_text.lower().split()
            words = [w for w in words if len(w) > 2]
            filtered_ocr = ' '.join(sorted(set(words)))
            hints.append(f"Extracted text (accurate):\n{filtered_ocr}")
        if hints:
            prompt += f"\n\nContext: {chr(10).join(hints)}"

        # Convert image to bytes for llama-server
        image_bytes = self._image_to_bytes(image)

        start_time = time.time()

        try:
            raw_response = llm_client.chat_with_images(
                prompt=prompt,
                images=[image_bytes],
                temperature=0.0,
                max_tokens=1800,
            )

            elapsed = time.time() - start_time
            logger.info(f"Inference completed in {elapsed:.1f}s")

            # Parse the merged response (layout + analysis in one JSON)
            record, regions = self._parse_merged_response(raw_response, app_name_hint, window_title)
            return record, regions

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Error after {elapsed:.1f}s: {e}")
            return ActivityRecord(
                app_name=app_name_hint or "unknown",
                activity_category="other",
                activity_summary=f"Analysis failed: {str(e)[:100]}",
                confidence=0.0,
            ), []

    def analyze_from_path(self, image_path: Path, **kwargs):
        """Convenience method to analyze from a file path.
        Returns (ActivityRecord, list of layout regions)."""
        from screenmind.privacy.encryption import open_image
        image = open_image(image_path)
        return self.analyze_screenshot(image, **kwargs)

    def analyze_screenshot_balanced(
        self,
        image: Image.Image,
        window_title: Optional[str] = None,
        app_name_hint: Optional[str] = None,
        ocr_text: Optional[str] = None,
        active_urls: Optional[list] = None,
    ):
        """
        Balanced mode: analysis with thinking (no layout), ~40-50s.

        Same prompt as fast mode (SPLIT_ANALYSIS_PROMPT — analysis only),
        but called via chat_with_images() without the prefill trick,
        allowing Gemma to think naturally. Produces richer scene_description
        and activity_summary than fast mode.

        Layout regions are computed separately via cluster_ocr_layout().

        Returns:
            Tuple of (ActivityRecord, empty list).
        """
        self._ensure_client()

        hints = []
        if app_name_hint:
            hints.append(f"OS-detected app: {app_name_hint}")
        if window_title:
            hints.append(f"Window title: {window_title}")
        if active_urls:
            hints.append(f"URLs visible in screenshot: {', '.join(active_urls)}")
        if ocr_text:
            words = ocr_text.lower().split()
            words = [w for w in words if len(w) > 2]
            filtered_ocr = ' '.join(sorted(set(words)))
            hints.append(f"Extracted text (accurate):\n{filtered_ocr}")
        context_str = f"\n\nContext: {chr(10).join(hints)}" if hints else ""

        prompt = SPLIT_ANALYSIS_PROMPT + context_str
        image_bytes = self._image_to_bytes(image)

        start_time = time.time()
        try:
            # chat_with_images() — no prefill = natural thinking enabled
            raw_response = llm_client.chat_with_images(
                prompt=prompt,
                images=[image_bytes],
                temperature=0.0,
                max_tokens=1024,
            )

            elapsed = time.time() - start_time
            logger.info(f"Balanced analysis done in {elapsed:.1f}s")

            # _parse_response() strips <think>...</think> tags before JSON parsing
            record = self._parse_response(raw_response, app_name_hint, window_title)
            return record, []

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Balanced analysis error after {elapsed:.1f}s: {e}")
            return ActivityRecord(
                app_name=app_name_hint or "unknown",
                activity_category="other",
                activity_summary=f"Analysis failed: {str(e)[:100]}",
                confidence=0.0,
            ), []

    def analyze_screenshot_fast(
        self,
        image: Image.Image,
        window_title: Optional[str] = None,
        app_name_hint: Optional[str] = None,
        ocr_text: Optional[str] = None,
        active_urls: Optional[list] = None,
    ):
        """
        Fast mode: analysis only (no thinking), ~12s. Layout done via OCR clustering.

        Returns:
            Tuple of (ActivityRecord, empty list). Layout regions are computed
            separately in analysis_worker using cluster_ocr_layout().
        """
        self._ensure_client()

        hints = []
        if app_name_hint:
            hints.append(f"OS-detected app: {app_name_hint}")
        if window_title:
            hints.append(f"Window title: {window_title}")
        if active_urls:
            hints.append(f"URLs visible in screenshot: {', '.join(active_urls)}")
        if ocr_text:
            words = ocr_text.lower().split()
            words = [w for w in words if len(w) > 2]
            filtered_ocr = ' '.join(sorted(set(words)))
            hints.append(f"Extracted text (accurate):\n{filtered_ocr}")
        context_str = f"\n\nContext: {chr(10).join(hints)}" if hints else ""

        image_bytes = self._image_to_bytes(image)
        img_b64 = base64.b64encode(image_bytes).decode()
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": SPLIT_ANALYSIS_PROMPT + context_str},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            ]},
            {"role": "assistant", "content": "<think>\n</think>\n"},
        ]

        # Flow: Gemma → parse → repair → regex → retry inference → fail
        for attempt in range(2):
            start_time = time.time()
            try:
                raw = llm_client.chat(
                    messages=messages,
                    temperature=0.0 if attempt == 0 else 0.1,
                    max_tokens=500,
                )
                elapsed = time.time() - start_time
                logger.info(f"Fast analysis done in {elapsed:.1f}s")

                # Run through the full parse pipeline
                record = self._safe_parse_json(raw)
                if record:
                    return self._normalize(record, app_name_hint, window_title), []

                # Pipeline exhausted — retry inference
                if attempt == 0:
                    logger.warning("All parse methods failed, retrying inference...")
                    continue

            except Exception as e:
                elapsed = time.time() - start_time
                if attempt == 0:
                    logger.warning(f"Fast analysis error, retrying: {e}")
                    continue
                logger.error(f"Fast analysis failed after {elapsed:.1f}s: {e}")

        return ActivityRecord(
            app_name=app_name_hint or "unknown",
            activity_category="other",
            activity_summary=f"Analysis failed",
            confidence=0.0,
        ), []

    def _safe_parse_json(self, raw: str) -> Optional[ActivityRecord]:
        """Full parse pipeline: extract → parse → repair → regex.
        Returns ActivityRecord on success, None if everything fails.

        Flow:
          1. Extract JSON string from raw Gemma output
          2. Try json.loads() — if good, return
          3. Try _repair_json() — fix common issues, re-parse — if good, return
          4. Try _regex_fallback() — salvage individual fields — if good, return
          5. Return None → caller decides to retry inference
        """
        if not raw:
            return None

        json_str = self._extract_json(raw)
        if json_str:
            # Step 1: Direct parse
            try:
                data = json.loads(json_str)
                return ActivityRecord(**data)
            except json.JSONDecodeError:
                pass
            except Exception:
                pass  # Pydantic validation error etc.

            # Step 2: Repair and re-parse
            repaired = self._repair_json(json_str)
            if repaired:
                try:
                    data = json.loads(repaired)
                    logger.debug("JSON repaired successfully")
                    return ActivityRecord(**data)
                except Exception:
                    pass

        # Step 3: Regex fallback — extract fields individually
        fallback = self._regex_fallback(raw)
        if fallback.activity_summary != "Unable to parse response":
            logger.debug("Used regex fallback")
            return fallback

        return None

    def _image_to_bytes(self, image: Image.Image) -> bytes:
        """
        Convert PIL Image to JPEG bytes, resized for optimal Gemma 4 input.
        768px balances quality vs VRAM usage on 4GB GPUs.
        """
        # Resize if larger than 768px (fits 4GB VRAM)
        max_dim = 768
        if max(image.size) > max_dim:
            ratio = max_dim / max(image.size)
            new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)

        # Convert to RGB if necessary (screenshots can be RGBA)
        if image.mode != "RGB":
            image = image.convert("RGB")

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    def _parse_merged_response(
        self,
        raw: str,
        app_name_hint: Optional[str] = None,
        window_title: Optional[str] = None,
    ):
        """
        Parse merged response containing both layout and analysis.
        Returns (ActivityRecord, list of region dicts).
        Falls back to analysis-only parsing if merged format fails.
        """
        # Strip thinking tags
        if "<think>" in raw and "</think>" in raw:
            raw = raw.split("</think>")[-1].strip()
        if "...done thinking." in raw:
            raw = raw.split("...done thinking.")[-1].strip()

        # Try to extract the full merged JSON
        json_str = self._extract_json(raw)
        if json_str:
            try:
                data = json.loads(json_str)
                if isinstance(data, dict):
                    # Extract layout regions
                    regions = data.get("layout", [])
                    # Normalize region coordinates (0-100 → 0-1)
                    valid_regions = []
                    for r in regions:
                        if all(k in r for k in ['x_start', 'x_end', 'y_start', 'y_end']):
                            for k in ['x_start', 'x_end', 'y_start', 'y_end']:
                                if r[k] > 1.0:
                                    r[k] = r[k] / 100.0
                            valid_regions.append(r)

                    # Extract analysis (strip layout key to avoid Pydantic extra-field error)
                    analysis_data = data.get("analysis", data)
                    if "layout" in analysis_data:
                        analysis_data = {k: v for k, v in analysis_data.items() if k != "layout"}
                    record = ActivityRecord(**analysis_data)
                    record = self._normalize(record, app_name_hint, window_title)
                    return record, valid_regions
            except json.JSONDecodeError:
                # Try repairing before falling back
                repaired = self._repair_json(json_str)
                if repaired:
                    try:
                        data = json.loads(repaired)
                        if isinstance(data, dict):
                            regions = data.get("layout", [])
                            valid_regions = []
                            for r in regions:
                                if all(k in r for k in ['x_start', 'x_end', 'y_start', 'y_end']):
                                    for k in ['x_start', 'x_end', 'y_start', 'y_end']:
                                        if r[k] > 1.0:
                                            r[k] = r[k] / 100.0
                                    valid_regions.append(r)
                            analysis_data = data.get("analysis", data)
                            if "layout" in analysis_data:
                                analysis_data = {k: v for k, v in analysis_data.items() if k != "layout"}
                            record = ActivityRecord(**analysis_data)
                            logger.debug("JSON repaired successfully (merged)")
                            return self._normalize(record, app_name_hint, window_title), valid_regions
                    except Exception:
                        pass
                logger.debug("Merged parse error (repair failed)")
            except Exception as e:
                logger.debug(f"Merged parse error: {e}")

        # Fallback: try parsing as analysis-only (old format)
        logger.debug("Falling back to analysis-only parsing")
        record = self._parse_response(raw, app_name_hint, window_title)
        return record, []

    def _parse_response(
        self,
        raw: str,
        app_name_hint: Optional[str] = None,
        window_title: Optional[str] = None,
    ) -> ActivityRecord:
        """
        Parse Gemma 4's response into an ActivityRecord.
        Handles various response formats:
        1. Clean JSON
        2. JSON wrapped in markdown code blocks
        3. JSON with thinking/explanation text before/after
        4. Malformed JSON (regex fallback)
        """
        # Strip the "thinking" part if present (Gemma 4 sometimes uses <think> tags)
        if "<think>" in raw and "</think>" in raw:
            raw = raw.split("</think>")[-1].strip()

        # Also handle "Thinking..." / "...done thinking." pattern
        if "...done thinking." in raw:
            raw = raw.split("...done thinking.")[-1].strip()

        # Try to extract JSON from the response
        json_str = self._extract_json(raw)

        if json_str:
            try:
                data = json.loads(json_str)
                record = ActivityRecord(**data)
                return self._normalize(record, app_name_hint, window_title)
            except (json.JSONDecodeError, Exception) as e:
                logger.debug(f"JSON parse error: {e}")

        # Fallback: try to extract key fields with regex
        logger.debug("Falling back to regex extraction")
        return self._normalize(self._regex_fallback(raw), app_name_hint, window_title)

    def _normalize(
        self,
        record: ActivityRecord,
        app_name_hint: Optional[str] = None,
        window_title: Optional[str] = None,
    ) -> ActivityRecord:
        """Normalize fields and reconcile app identity using three signals.

        Hierarchy for app name (first non-empty wins, then compared with Gemma):
          L1: Title " - " extraction  (most reliable pattern)
          L2: OS process name         (ground truth, skip generic wrappers)
          L3: Title simple extraction  (short clean title, for OS=None/generic)
          L4: Gemma's visual guess     (last resort — kept as-is)

        At whichever level we get a name, we compare with Gemma using word-boundary
        substring matching.  If Gemma is a more specific version of our name
        (e.g. OS='code' → Gemma='VS Code'), we keep Gemma's friendlier name.
        Otherwise we use the hierarchy value.

        Category reconciliation:
          - Browser windows → trust Gemma (content-aware: YouTube=media)
          - Known apps      → use KNOWN_APP_CATEGORIES override
          - Unknown apps    → trust Gemma (no override info available)
        """
        original_app = record.app_name
        original_cat = record.activity_category

        # ── Phase 1: Walk the hierarchy to find best app name ────────
        resolved_name = None

        # macOS: the window owner from Quartz is ground truth, and titles rarely
        # end with the app name (Terminal: "dir — cmd — 120×30"), so use it first.
        if sys.platform == "darwin" and app_name_hint:
            if app_name_hint.lower().strip() not in GENERIC_PROCESS_NAMES:
                resolved_name = app_name_hint

        # L1: Title " - " extraction ("main.py - Visual Studio Code" → "Visual Studio Code")
        title_app = None if resolved_name else _extract_app_from_title(window_title)
        if title_app:
            resolved_name = title_app

        # L2: OS process name (skip generic wrappers like 'electron', 'java')
        if not resolved_name and app_name_hint:
            if app_name_hint.lower().strip() not in GENERIC_PROCESS_NAMES:
                resolved_name = app_name_hint

        # L3: Simple title ("AnyType", "Calculator" — for when OS is None or generic)
        if not resolved_name and window_title:
            simple = _extract_simple_title(window_title)
            if simple:
                resolved_name = simple

        # L4: Gemma's guess stays as-is (implicit — record.app_name unchanged)

        # ── Phase 2: Compare resolved name with Gemma's guess ────────
        if resolved_name:
            resolved_lower = resolved_name.lower().strip()
            gemma_lower = record.app_name.lower().strip()
            if _is_more_specific_name(resolved_lower, gemma_lower):
                pass  # Gemma is more specific (e.g., "code" → "VS Code") — keep it
            else:
                record.app_name = resolved_name

        # ── Phase 3+4: Category resolution ────────────────────────────
        # Check known category override FIRST — if found, skip Gemma
        # normalization entirely (avoids wasted work when overriding).
        is_browser = _is_browser_window(window_title, app_name_hint)
        final_app = record.app_name

        if is_browser:
            # Browser: trust Gemma's content-based category, just normalize it
            cat = record.activity_category.lower().strip()
            for valid in VALID_CATEGORIES:
                if valid in cat:
                    record.activity_category = valid
                    break
            else:
                record.activity_category = "other"
        else:
            known_cat = _lookup_known_category(final_app)
            if known_cat:
                # Authoritative override — skip Gemma normalization
                record.activity_category = known_cat
            else:
                # No override — normalize Gemma's raw category
                cat = record.activity_category.lower().strip()
                for valid in VALID_CATEGORIES:
                    if valid in cat:
                        record.activity_category = valid
                        break
                else:
                    record.activity_category = "other"

        cat_after_resolution = record.activity_category

        # ── Mood normalization ────────────────────────────────────────
        mood = record.mood.lower().strip()
        for valid in VALID_MOODS:
            if valid in mood:
                record.mood = valid
                break
        else:
            record.mood = "neutral"

        # ── Confidence clamping ───────────────────────────────────────
        if record.confidence == 0.0 and record.activity_summary and "failed" not in record.activity_summary.lower():
            record.confidence = 0.7
        record.confidence = max(0.0, min(1.0, record.confidence))

        # ── Reconciliation logging ────────────────────────────────────
        if record.app_name != original_app:
            logger.debug(f"Reconcile App: '{original_app}' → '{record.app_name}' "
                  f"(hint={app_name_hint}, title={window_title})")
        if record.activity_category != cat_after_resolution:
            logger.debug(f"Reconcile Category: '{original_cat}' → '{record.activity_category}'")

        return record

    def _repair_json(self, broken: str) -> Optional[str]:
        """Attempt to fix common JSON issues from Gemma output.
        Handles: trailing commas, missing closing braces/brackets,
        truncated strings, and unescaped newlines.
        Returns repaired JSON string or None if unfixable."""
        import re as _re
        s = broken.strip()

        # Fix unescaped newlines inside string values
        s = _re.sub(r'(?<!\\)\n', '\\n', s)

        # Fix trailing commas before } or ]
        s = _re.sub(r',\s*([}\]])', r'\1', s)

        # Fix truncated strings — add closing quote if odd number of quotes
        quote_count = s.count('"') - s.count('\\"')
        if quote_count % 2 != 0:
            s += '"'

        # Fix missing closing brackets/braces
        open_braces = s.count('{') - s.count('}')
        open_brackets = s.count('[') - s.count(']')
        s += ']' * max(0, open_brackets)
        s += '}' * max(0, open_braces)

        # Validate it's now parseable
        try:
            json.loads(s)
            return s
        except json.JSONDecodeError:
            return None

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract a JSON object from text, handling various wrapper formats."""
        # 1. Try: text is already clean JSON
        text = text.strip()
        if text.startswith("{") and text.endswith("}"):
            return text

        # 2. Try: JSON in markdown code block
        code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block_match:
            return code_block_match.group(1)

        # 3. Try: find the first { ... } block in the text
        brace_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
        if brace_match:
            return brace_match.group(0)

        # 4. Try: find JSON array-containing object
        deep_match = re.search(r"\{.*\}", text, re.DOTALL)
        if deep_match:
            return deep_match.group(0)

        return None

    def _regex_fallback(self, text: str) -> ActivityRecord:
        """
        Last-resort extraction using regex patterns.
        Tries to salvage useful data even from badly formatted responses.
        """

        def extract_field(pattern: str, default: str = "") -> str:
            match = re.search(pattern, text, re.IGNORECASE)
            return match.group(1).strip() if match else default

        return ActivityRecord(
            app_name=extract_field(r'"?app_name"?\s*[:=]\s*"([^"]+)"', "unknown"),
            activity_category=extract_field(
                r'"?activity_category"?\s*[:=]\s*"([^"]+)"', "other"
            ),
            activity_summary=extract_field(
                r'"?activity_summary"?\s*[:=]\s*"([^"]+)"', "Unable to parse response"
            ),
            detailed_context=extract_field(
                r'"?detailed_context"?\s*[:=]\s*"([^"]+)"', ""
            ),
            mood=extract_field(r'"?mood"?\s*[:=]\s*"([^"]+)"', "neutral"),
            confidence=0.3,  # Low confidence for regex-extracted data
        )

    def is_available(self) -> bool:
        """Check if llama-server is reachable."""
        return llm_client.is_available()
