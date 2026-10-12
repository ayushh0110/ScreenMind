"""
Audio Worker — Meeting Transcription
Auto-detects meeting apps, captures dual-channel audio (system + mic),
transcribes with Gemma 4's native audio encoder, and generates meeting summaries.
"""

import io
import logging
import subprocess
import sys
import time
import threading
import wave
from datetime import datetime
from typing import Optional, List

import numpy as np

from screenmind.config import settings
from screenmind.storage.database import Database

logger = logging.getLogger("screenmind.workers.audio_worker")


# Meeting app keywords
MEETING_APPS = None  # Loaded from settings at runtime

# Grace period (seconds) — keep recording if user briefly switches away
# Process-alive check handles native apps immediately; this is the safety-net timeout
MEETING_GRACE_PERIOD = 300  # 5 min — fallback for browser-based meetings

# Audio probe settings — confirm voice activity before recording
PROBE_DURATION = 2       # seconds of audio to sample per device
PROBE_COOLDOWN = 5       # seconds between probes when meeting app is in foreground
PROBE_RMS_THRESHOLD = 0.008  # minimum RMS energy to count as "voice detected" (lowered for Discord/earphone setups)
SILENCE_AUTO_STOP_CHUNKS = 3  # stop meeting after N consecutive silent chunks (both mic+sys)

# Confirmation probing — avoid false triggers from notification sounds or ambient noise
PROBE_CONFIRM_COUNT = 2      # require N consecutive voice-detected probes before starting
PROBE_CONFIRM_WINDOW = 20    # probes must happen within N seconds to count as consecutive


# Re-check llama-server this often while transcription is unavailable, so
# meeting transcription recovers when the server starts after ScreenMind.
AVAILABILITY_RECHECK_SECONDS = 30


# Map meeting app keywords → native process names, per platform.
# Browser-based meetings (Meet, web Teams) have no process → timeout only.
# Matching is exact on the executable's base name (case-insensitive), so an
# editor with "discord" in a file path never counts as Discord running.
_MEETING_PROCESSES = {
    "win32": {
        "discord": ["Discord.exe"],
        "zoom": ["Zoom.exe"],
        "teams": ["ms-teams.exe"],
        "webex": ["webexmta.exe"],
        "slack": ["slack.exe"],
    },
    "darwin": {
        "discord": ["Discord"],
        "zoom": ["zoom.us"],
        "teams": ["MSTeams", "Microsoft Teams"],
        "webex": ["Webex"],
        "slack": ["Slack"],
    },
    "linux": {  # Linux truncates process names to 15 chars; all fit
        "discord": ["Discord", "discord"],
        "zoom": ["zoom"],
        "teams": ["teams", "teams-for-linux"],
        "webex": ["webex"],
        "slack": ["slack"],
    },
}


def _meeting_process_names(app_name: str) -> Optional[List[str]]:
    """Native process names to watch for a meeting app, or None if unknown."""
    table = _MEETING_PROCESSES.get(sys.platform, _MEETING_PROCESSES["linux"])
    app_lower = app_name.lower()
    for key, names in table.items():
        if key in app_lower:
            return names
    return None


def _running_process_names() -> set:
    """Lowercased executable base names of all running processes (macOS/Linux).

    `ps -A -o comm=` is the same on BSD (macOS) and procps (Linux), unlike
    pgrep's flags. macOS prints full paths for app bundles, so take the last
    path component.
    """
    result = subprocess.run(
        ["ps", "-A", "-o", "comm="],
        capture_output=True, text=True, timeout=3,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ps exited with {result.returncode}")
    return {
        line.strip().rsplit("/", 1)[-1].lower()
        for line in result.stdout.splitlines()
        if line.strip()
    }


class AudioWorker:
    """
    Background worker for meeting transcription.
    - Detects meeting apps via foreground window name
    - Captures system audio (WASAPI loopback) + microphone
    - Transcribes chunks with Gemma 4's audio encoder (via llama-server)
    - Accumulates transcript during meeting session
    - On meeting end: sends to Gemma for structured summary
    - Uses process-alive check + silence detection for robust end-of-meeting detection
    """

    def __init__(self, database: Database):
        self._db = database
        self._running = False
        self._available = False
        self._last_availability_check: float = 0.0

        # Session state
        self._in_meeting = False
        self._meeting_id: Optional[int] = None
        self._meeting_app: Optional[str] = None
        self._meeting_process: Optional[List[str]] = None  # e.g. ["Discord.exe"]
        self._session_start: Optional[datetime] = None
        self._session_transcript: List[str] = []
        self._last_meeting_app_seen: float = 0
        self._recording_thread: Optional[threading.Thread] = None
        self._stop_recording = threading.Event()

        # Audio probe state — confirms voice activity before starting
        self._probe_in_progress: bool = False
        self._probe_complete: bool = False
        self._probe_detected_audio: bool = False
        self._last_probe_time: float = 0
        self._pending_meeting_app: Optional[str] = None

        # Confirmation state — require multiple consecutive voice probes
        self._consecutive_voice_probes: int = 0
        self._first_voice_probe_time: float = 0

        # Audio config
        self._sample_rate = 16000  # Gemma audio encoder expects 16kHz
        self._chunk_duration = 15  # seconds per transcription chunk

        # Check transcription backend availability
        self._init_transcription()

    def _init_transcription(self):
        """Check that Gemma audio transcription is available via llama-server.

        Logs only on state changes, since this is re-run periodically while
        the server is down (see is_available).
        """
        was_available = self._available
        self._last_availability_check = time.time()
        try:
            from screenmind.engine import llm_client
            self._available = llm_client.is_available()
            error = None if self._available else "llama-server not available"
        except Exception as e:
            self._available = False
            error = f"Transcription init failed: {e}"

        if self._available and not was_available:
            logger.info("Gemma audio transcription ready (via llama-server).")
        elif error and not getattr(self, "_unavailable_logged", False):
            logger.warning(f"{error} — meeting transcription disabled until it is reachable")
        self._unavailable_logged = not self._available

    @property
    def is_available(self) -> bool:
        """Transcription enabled and llama-server reachable.

        If the server was down, it is re-checked at most every
        AVAILABILITY_RECHECK_SECONDS, so transcription recovers when
        llama-server starts after ScreenMind.
        """
        if not settings.meeting_transcription:
            return False
        if not self._available and (
            time.time() - self._last_availability_check >= AVAILABILITY_RECHECK_SECONDS
        ):
            self._init_transcription()
        return self._available

    @property
    def in_meeting(self) -> bool:
        return self._in_meeting

    def check_meeting(self, app_name: str):
        """
        Called by CaptureWorker every 5s with current foreground app name.
        Detects meeting start/end transitions.

        Uses audio probe confirmation: when a meeting app is detected,
        we sample mic + system audio briefly. Recording only starts if
        actual voice activity is found. The probe thread directly triggers
        meeting start for minimal delay (~2-3s from voice to recording).
        """
        if not self.is_available or not app_name:
            return

        app_lower = app_name.lower()
        is_meeting_app = any(m in app_lower for m in settings.meeting_apps_list)

        if is_meeting_app:
            self._last_meeting_app_seen = time.time()
            if not self._in_meeting and not self._probe_in_progress:
                # No probe running — start one if cooldown elapsed
                if time.time() - self._last_probe_time > PROBE_COOLDOWN:
                    self._pending_meeting_app = app_name
                    self._start_audio_probe()
                # else: probe is still running, wait for next cycle
        elif self._in_meeting:
            # Grace period with process-alive check
            elapsed = time.time() - self._last_meeting_app_seen
            if elapsed > MEETING_GRACE_PERIOD:
                # Hard timeout — meeting definitely over
                logger.info(f"Meeting timeout ({elapsed:.0f}s away) — stopping")
                self._stop_meeting()
            elif elapsed > 30 and not self._is_meeting_process_alive():
                # Process dead — meeting truly over (30s debounce)
                logger.info("Meeting app process ended — stopping")
                self._stop_meeting()
        else:
            # Not a meeting app and not in meeting — reset silence log
            self._silence_logged_app = None

    def _is_meeting_process_alive(self) -> bool:
        """Check if the meeting app's native process is still running.
        Returns True for browser-based meetings (no process to check).
        """
        if not self._meeting_process:
            return True  # Browser-based → assume alive, rely on timeout

        try:
            if sys.platform == "win32":
                for name in self._meeting_process:
                    result = subprocess.run(
                        ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                        capture_output=True, text=True, timeout=3,
                    )
                    if name.lower() in result.stdout.lower():
                        return True
                return False

            running = _running_process_names()
            return any(name.lower() in running for name in self._meeting_process)
        except Exception:
            return True  # Assume alive on error — don't stop recording

    def _start_audio_probe(self):
        """Kick off a background audio probe to detect voice activity."""
        self._probe_in_progress = True
        thread = threading.Thread(target=self._do_audio_probe, daemon=True)
        thread.start()

    def _do_audio_probe(self):
        """
        Quick audio probe: sample mic + system audio for ~1s each.
        If voice detected → directly triggers _start_meeting (no waiting
        for the next 5s check_meeting cycle).
        """
        detected = False
        try:
            import sounddevice as sd

            samples = int(PROBE_DURATION * self._sample_rate)

            # ── 1. Probe microphone ───────────────────────────────────
            try:
                mic_audio = sd.rec(
                    samples, samplerate=self._sample_rate,
                    channels=1, dtype="float32",
                )
                sd.wait()
                rms = np.sqrt(np.mean(mic_audio ** 2))
                if rms > PROBE_RMS_THRESHOLD:
                    detected = True
                    logger.info(f"Mic voice detected (RMS={rms:.4f})")
            except Exception as e:
                logger.debug(f"Mic probe failed: {e}")

            # ── 2. Probe system audio (loopback) ──────────────────────
            if not detected:
                try:
                    devices = sd.query_devices()
                    loopback_id = None
                    for i, d in enumerate(devices):
                        name = d.get("name", "").lower()
                        if ("loopback" in name or "stereo mix" in name) \
                                and d.get("max_input_channels", 0) > 0:
                            loopback_id = i
                            break

                    if loopback_id is not None:
                        sys_audio = sd.rec(
                            samples, samplerate=self._sample_rate,
                            channels=1, dtype="float32",
                            device=loopback_id,
                        )
                        sd.wait()
                        rms = np.sqrt(np.mean(sys_audio ** 2))
                        if rms > PROBE_RMS_THRESHOLD:
                            detected = True
                            logger.info(f"System audio detected (RMS={rms:.4f})")
                except Exception:
                    pass  # Loopback not available — mic-only probe is fine

        except ImportError:
            logger.debug("sounddevice not available for audio probe")
        except Exception as e:
            logger.debug(f"Audio probe error: {e}")
        finally:
            self._probe_in_progress = False
            self._last_probe_time = time.time()
            if detected:
                # Confirmation: require PROBE_CONFIRM_COUNT consecutive voice probes
                now = time.time()
                if (self._consecutive_voice_probes > 0 and
                        now - self._first_voice_probe_time > PROBE_CONFIRM_WINDOW):
                    # Too much time between probes — reset
                    self._consecutive_voice_probes = 0

                if self._consecutive_voice_probes == 0:
                    self._first_voice_probe_time = now
                self._consecutive_voice_probes += 1

                if self._consecutive_voice_probes >= PROBE_CONFIRM_COUNT:
                    # Confirmed! Start the meeting.
                    app = self._pending_meeting_app or "Unknown"
                    self._consecutive_voice_probes = 0
                    self._start_meeting(app)
                else:
                    logger.info(f"Voice probe {self._consecutive_voice_probes}/{PROBE_CONFIRM_COUNT} "
                          f"— confirming before starting meeting...")
            else:
                # No voice — reset confirmation counter
                self._consecutive_voice_probes = 0
                if not getattr(self, '_silence_logged_app', None) == self._pending_meeting_app:
                    self._silence_logged_app = self._pending_meeting_app
                    logger.info(f"{self._pending_meeting_app} in foreground but no voice detected — skipping")

    def _start_meeting(self, app_name: str):
        """Begin recording a meeting session."""
        # Guard: don't record if active model can't transcribe audio
        from screenmind.engine import model_manager
        if not model_manager.is_audio_capable():
            logger.info(f"Meeting detected ({app_name}) but active model "
                  f"has no audio encoder — skipping recording")
            return

        self._in_meeting = True
        self._meeting_app = app_name
        self._session_start = datetime.now()
        self._session_transcript = []
        self._last_meeting_app_seen = time.time()

        # Resolve process names for process-alive checks
        self._meeting_process = _meeting_process_names(app_name)

        # Insert meeting record
        self._meeting_id = self._db.insert_meeting(
            start_time=self._session_start,
            app_name=app_name,
        )
        proc_info = f", process={self._meeting_process}" if self._meeting_process else ", browser-based"
        logger.info(f"Meeting started ({app_name}{proc_info}) — recording...")

        # System-wide overlay notification
        try:
            from screenmind.ui.overlay import show_overlay_notification
            show_overlay_notification(
                title="ScreenMind is Transcribing",
                message=f"Meeting detected in {app_name} — recording audio...",
                duration=4.0,
                color="#ec4899",
            )
        except Exception:
            pass  # Notification is best-effort

        # Start recording in background thread
        self._stop_recording.clear()
        self._recording_thread = threading.Thread(
            target=self._recording_loop, daemon=True
        )
        self._recording_thread.start()

    def _stop_meeting(self):
        """End recording and trigger summary generation."""
        if not self._in_meeting:
            return

        self._in_meeting = False
        self._stop_recording.set()

        # Wait for recording thread to finish (skip if called from within it)
        if self._recording_thread and self._recording_thread.is_alive():
            if threading.current_thread() != self._recording_thread:
                self._recording_thread.join(timeout=5)

        end_time = datetime.now()
        duration = (end_time - self._session_start).total_seconds() / 60 if self._session_start else 0
        full_transcript = "\n".join(self._session_transcript)

        logger.info(f"Meeting ended ({duration:.1f} min, {len(self._session_transcript)} chunks)")

        # System-wide overlay notification
        try:
            from screenmind.ui.overlay import show_overlay_notification
            chunks = len(self._session_transcript)
            show_overlay_notification(
                title="✅ Meeting Recording Complete",
                message=f"{duration:.0f} min recorded • {chunks} audio chunks • Generating summary...",
                duration=5.0,
                color="#10b981",
            )
        except Exception:
            pass

        if self._meeting_id and full_transcript.strip():
            # Update with transcript (summary comes async)
            self._db.update_meeting(
                meeting_id=self._meeting_id,
                end_time=end_time,
                duration_minutes=round(duration, 1),
                transcript=full_transcript,
                summary="⏳ Generating summary...",
            )
            logger.info(f"Transcript saved ({len(full_transcript)} chars, {len(self._session_transcript)} chunks)")
            # Trigger summary in background thread
            summary_thread = threading.Thread(
                target=self._generate_summary,
                args=(self._meeting_id, full_transcript),
                daemon=True,
            )
            summary_thread.start()
        elif self._meeting_id:
            logger.warning(f"No transcript to save (session_transcript={len(self._session_transcript)} items)")
            self._db.update_meeting(
                meeting_id=self._meeting_id,
                end_time=end_time,
                duration_minutes=round(duration, 1),
                transcript="(No speech detected)",
                summary="No content to summarize.",
            )

        # Reset state
        self._meeting_id = None
        self._meeting_app = None
        self._meeting_process = None
        self._session_start = None
        self._session_transcript = []

    def _recording_loop(self):
        """
        Background thread: capture audio in chunks and transcribe.
        Records mic + system audio in parallel, transcribes each
        separately via Gemma for speaker-labeled output.
        """
        try:
            import sounddevice as sd
        except ImportError:
            logger.warning("sounddevice not installed — cannot record")
            return

        # Find system loopback device once (not every chunk)
        loopback_id = self._find_loopback_device(sd)


        # Track consecutive silent chunks for auto-stop
        consecutive_silent = 0

        while not self._stop_recording.is_set():
            try:
                samples = int(self._chunk_duration * self._sample_rate)
                mic_audio = None
                sys_audio = None

                # ── Record mic + system audio in parallel ─────────
                if loopback_id is not None:
                    # Use threads to record both simultaneously
                    mic_buf = {"data": None}
                    sys_buf = {"data": None}

                    def record_mic():
                        try:
                            mic_buf["data"] = sd.rec(
                                samples, samplerate=self._sample_rate,
                                channels=1, dtype="float32",
                            )
                            sd.wait()
                        except Exception as e:
                            logger.debug(f"Mic record error: {e}")

                    def record_sys():
                        try:
                            # Use a separate InputStream for system audio
                            buf = np.zeros((samples, 1), dtype="float32")
                            pos = [0]
                            def callback(indata, frames, time_info, status):
                                end = min(pos[0] + frames, samples)
                                n = end - pos[0]
                                buf[pos[0]:end] = indata[:n]
                                pos[0] = end
                            with sd.InputStream(
                                device=loopback_id, samplerate=self._sample_rate,
                                channels=1, dtype="float32", callback=callback
                            ):
                                # Wait for recording to complete or stop signal
                                start = time.time()
                                while pos[0] < samples and not self._stop_recording.is_set():
                                    time.sleep(0.05)
                                    if time.time() - start > self._chunk_duration + 2:
                                        break
                            sys_buf["data"] = buf[:pos[0]]
                        except Exception:
                            pass  # Loopback not available

                    mic_thread = threading.Thread(target=record_mic, daemon=True)
                    sys_thread = threading.Thread(target=record_sys, daemon=True)
                    mic_thread.start()
                    sys_thread.start()

                    # Wait for both to complete (or stop signal)
                    for _ in range(self._chunk_duration * 10 + 20):
                        if self._stop_recording.is_set():
                            try: sd.stop()
                            except: pass
                            break
                        if not mic_thread.is_alive() and not sys_thread.is_alive():
                            break
                        time.sleep(0.1)
                    mic_thread.join(timeout=2)
                    sys_thread.join(timeout=2)

                    mic_audio = mic_buf["data"]
                    sys_audio = sys_buf["data"]
                    if mic_audio is not None:
                        mic_audio = mic_audio.flatten()
                    if sys_audio is not None:
                        sys_audio = sys_audio.flatten()
                else:
                    # No loopback — mic only
                    audio_data = sd.rec(
                        samples, samplerate=self._sample_rate,
                        channels=1, dtype="float32",
                    )
                    for _ in range(self._chunk_duration * 10):
                        if self._stop_recording.is_set():
                            sd.stop()
                            break
                        time.sleep(0.1)
                    else:
                        sd.wait()
                    mic_audio = audio_data.flatten() if audio_data is not None else None

                # ── Transcribe mic and system audio separately ────
                # Keeps [You] / [Others] labels — accurate with earphones
                mic_had_speech = False
                sys_had_speech = False
                if mic_audio is not None and len(mic_audio) > self._sample_rate:
                    mic_had_speech = self._transcribe_chunk(self._normalize_audio(mic_audio), speaker="You")
                if sys_audio is not None and len(sys_audio) > self._sample_rate:
                    sys_had_speech = self._transcribe_chunk(self._normalize_audio(sys_audio), speaker="Others")

                # ── Silence-based auto-stop ───────────────────────
                # If both mic AND system are silent, user likely left the call
                if not mic_had_speech and not sys_had_speech:
                    consecutive_silent += 1
                    if consecutive_silent >= SILENCE_AUTO_STOP_CHUNKS:
                        logger.info(f"{consecutive_silent} consecutive silent chunks -- auto-stopping meeting")
                        self._stop_meeting()
                        return
                else:
                    consecutive_silent = 0

            except Exception as e:
                logger.error(f"Recording error: {e}")
                if not self._stop_recording.is_set():
                    time.sleep(2)

    @staticmethod
    def _find_loopback_device(sd):
        """Find WASAPI loopback or Stereo Mix device for system audio."""
        try:
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                name = d.get("name", "").lower()
                if ("loopback" in name or "stereo mix" in name) \
                        and d.get("max_input_channels", 0) > 0:
                    logger.info(f"Found system audio device: {d['name']}")
                    return i
        except Exception:
            pass
        logger.info("No system audio loopback found — mic only")
        return None

    @staticmethod
    def _normalize_audio(audio: np.ndarray) -> np.ndarray:
        """
        Normalize audio volume for consistent transcription input.
        Prevents issues with very quiet or very loud recordings.
        """
        if audio is None or len(audio) == 0:
            return audio
        peak = np.max(np.abs(audio))
        if peak > 0.001:  # Not silence
            audio = audio / peak * 0.85  # Normalize to 85% of max
        return audio

    def _transcribe_chunk(self, audio_data: np.ndarray, speaker: str = "You") -> bool:
        """Transcribe a single audio chunk with Gemma 4's audio encoder.
        Returns True if speech was detected and transcribed."""
        if len(audio_data) < self._sample_rate:
            return False  # Too short

        try:
            # Check if audio has actual content (not silence)
            rms = np.sqrt(np.mean(audio_data ** 2))
            if rms < 0.003:  # Silence threshold
                return False

            # Convert float32 numpy array to WAV bytes for Gemma
            audio_int16 = (audio_data * 32767).astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(self._sample_rate)
                wf.writeframes(audio_int16.tobytes())
            wav_bytes = buf.getvalue()

            from screenmind.engine import llm_client
            text = llm_client.transcribe_audio(
                audio_bytes=wav_bytes,
                prompt="Transcribe this audio accurately. Output only the transcription, nothing else.",
                audio_format="wav",
                temperature=0.1,
                max_tokens=1024,
            )

            text = text.strip() if text else ""
            if text and len(text) > 5:  # Ignore very short fragments
                self._session_transcript.append(f"[{speaker}] {text}")
                logger.info(f"[{speaker}] {text[:100]}{'...' if len(text) > 100 else ''}")
                return True
            return False
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return False

    def _generate_summary(self, meeting_id: int, transcript: str):
        """Generate a structured meeting summary using Gemma.
        Uses map-reduce for long transcripts: chunk → summarize each → combine.
        """
        try:
            from screenmind.engine import llm_client

            FINAL_PROMPT_TEMPLATE = """You are a meeting notes assistant. Summarize this meeting content into structured sections.
Be concise and actionable. Extract the key information.

{content}

Generate a structured summary with these exact sections:

TOPICS DISCUSSED:
- topic 1
- topic 2

PROBLEMS RAISED:
- problem (if any)

SOLUTIONS PROPOSED:
- solution (if any)

ACTION ITEMS:
- [Speaker] specific action item

If a section has no content, write "None discussed."
"""

            if len(transcript) <= 4000:
                # Short transcript — single call
                prompt = FINAL_PROMPT_TEMPLATE.format(content=f"Meeting transcript:\n{transcript}")
                summary = llm_client.generate(prompt=prompt, temperature=0.3, max_tokens=1024)
            else:
                # Long transcript — map-reduce
                # Step 1: chunk transcript into ~3000 char segments
                chunk_size = 3000
                chunks = []
                for i in range(0, len(transcript), chunk_size):
                    chunks.append(transcript[i:i + chunk_size])

                logger.info(f"Long transcript ({len(transcript)} chars) — "
                      f"map-reduce with {len(chunks)} chunks")

                # Step 2: summarize each chunk
                chunk_summaries = []
                for idx, chunk in enumerate(chunks):
                    chunk_prompt = (
                        f"Summarize this portion ({idx + 1}/{len(chunks)}) of a meeting transcript. "
                        f"Extract key topics, decisions, and action items. Be concise.\n\n"
                        f"Transcript segment:\n{chunk}"
                    )
                    try:
                        chunk_summary = llm_client.generate(
                            prompt=chunk_prompt, temperature=0.3, max_tokens=512,
                        )
                        if chunk_summary and chunk_summary.strip():
                            chunk_summaries.append(f"--- Part {idx + 1} ---\n{chunk_summary.strip()}")
                            logger.info(f"Chunk {idx + 1}/{len(chunks)} summarized")
                    except Exception as e:
                        logger.warning(f"Chunk {idx + 1} summary failed: {e}")
                        chunk_summaries.append(f"--- Part {idx + 1} ---\n(Summary failed)")

                # Step 3: combine chunk summaries into final structured summary
                combined = "\n\n".join(chunk_summaries)
                prompt = FINAL_PROMPT_TEMPLATE.format(
                    content=f"Combined meeting summaries:\n{combined[:4000]}"
                )
                summary = llm_client.generate(prompt=prompt, temperature=0.3, max_tokens=1024)

            if summary and summary.strip():
                self._db.update_meeting_summary(meeting_id, summary.strip())
                logger.info(f"Meeting summary generated ({len(summary)} chars)")
            else:
                logger.warning("Empty summary from Gemma")
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            self._db.update_meeting_summary(
                meeting_id, f"❌ Summary failed: {str(e)[:100]}"
            )

    def force_stop(self):
        """Force-stop current meeting recording (e.g., on shutdown)."""
        if self._in_meeting:
            self._stop_meeting()

    @property
    def stats(self) -> dict:
        return {
            "available": self._available,
            "enabled": settings.meeting_transcription,
            "in_meeting": self._in_meeting,
            "meeting_app": self._meeting_app,
            "transcript_chunks": len(self._session_transcript),
            "probing": self._probe_in_progress,
        }
