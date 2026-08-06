# =========================
# FILE: agent/voice_session.py
# =========================
"""
Voice session: microphone → Whisper → normalizer → agent command.

Runs the capture loop on its own thread so the overlay's tkinter mainloop keeps
painting and the agent keeps executing while the user is still talking.

The mic is gated while a command runs. The tablet sits next to the laptop with
its speaker on, so an unGated mic hears the video it just opened and transcribes
it as the next command — the agent ends up driving itself. Gating costs the
ability to interrupt, which is the better trade for a device controller.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Callable, Optional, Sequence

from agent.voice_normalizer import NormalizedSpeech, SpeechNormalizer
from agent.voice_stt import (
    MicListener,
    MicUnavailable,
    VadConfig,
    WhisperSTT,
    microphone_name,
)


class VoiceState(str, Enum):
    STARTING = "starting"      # agent still connecting to the tablet
    OFF = "off"                # mic off
    LISTENING = "listening"    # mic on, waiting for speech
    SPEECH = "speech"          # speech in progress
    TRANSCRIBING = "transcribing"
    BUSY = "busy"              # agent executing a command
    ERROR = "error"


StateCallback = Callable[[VoiceState, str], None]
LevelCallback = Callable[[float], None]
MessageCallback = Callable[[str, str], None]   # (kind, text)
CommandCallback = Callable[[str], None]


class VoiceSession:
    """Owns the listening thread and the mic's on/off state."""

    def __init__(
        self,
        on_command: CommandCallback,
        on_state: Optional[StateCallback] = None,
        on_level: Optional[LevelCallback] = None,
        on_message: Optional[MessageCallback] = None,
        app_vocabulary: Optional[Callable[[], Sequence[str]]] = None,
        gate_while_busy: bool = True,
    ) -> None:
        self._on_command = on_command
        self._on_state = on_state
        self._on_level = on_level
        self._on_message = on_message
        self.gate_while_busy = gate_while_busy

        self.mic = MicListener(VadConfig.from_env())
        self.stt = WhisperSTT(vocabulary_provider=app_vocabulary)
        self.normalizer = SpeechNormalizer(app_vocabulary=app_vocabulary)

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._busy = threading.Event()
        self._listening = False
        self._enabled = False          # agent ready to accept commands
        self.state = VoiceState.STARTING
        self.device_name = "Microphone"
        self.last_transcript = ""

    # ------------------------------------------------------------------
    # State plumbing
    # ------------------------------------------------------------------
    @property
    def listening(self) -> bool:
        return self._listening

    @property
    def ready(self) -> bool:
        return self._enabled

    def _set_state(self, state: VoiceState, detail: str = "") -> None:
        self.state = state
        if self._on_state:
            try:
                self._on_state(state, detail)
            except Exception:
                pass

    def _message(self, kind: str, text: str) -> None:
        if self._on_message:
            try:
                self._on_message(kind, text)
            except Exception:
                pass

    def set_ready(self, ready: bool = True) -> None:
        """Called once the agent has finished connecting to the tablet.

        The normalizer reads its vocabulary through a callable, so it picks up
        the installed app list on its own; only the Whisper prompt is cached
        and needs invalidating.
        """
        self._enabled = ready
        if ready:
            self.stt.refresh_vocabulary()
            if not self._listening:
                self._set_state(VoiceState.OFF)

    def set_busy(self, busy: bool) -> None:
        """Mute the mic while the agent drives the tablet."""
        if busy:
            self._busy.set()
            self._set_state(VoiceState.BUSY, self.last_transcript)
        else:
            self._busy.clear()
            if self._listening:
                self._set_state(VoiceState.LISTENING)
            else:
                self._set_state(VoiceState.OFF)

    def _gated(self) -> bool:
        return self.gate_while_busy and self._busy.is_set()

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------
    def toggle(self) -> bool:
        """Flip the mic. Returns the new listening state."""
        if self._listening:
            self.stop()
        else:
            self.start()
        return self._listening

    def start(self) -> bool:
        if self._listening:
            return True
        if not self._enabled:
            self._message("warn", "Still connecting to the tablet…")
            return False
        if not self.stt.available:
            self._set_state(VoiceState.ERROR, self.stt.error)
            self._message("error", self.stt.error or "Speech-to-text unavailable")
            return False

        self._stop.clear()
        self._listening = True
        self._thread = threading.Thread(
            target=self._run, name="voice-listener", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        if not self._listening:
            return
        self._listening = False
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if self._on_level:
            try:
                self._on_level(0.0)
            except Exception:
                pass
        self._set_state(VoiceState.OFF)

    def shutdown(self) -> None:
        self._stop.set()
        self._listening = False
        thread, self._thread = self._thread, None
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Listening loop
    # ------------------------------------------------------------------
    def _run(self) -> None:
        try:
            self.device_name = microphone_name()
            self._set_state(VoiceState.LISTENING, self.device_name)
            self._message("info", f"Listening on {self.device_name}")

            for utterance in self.mic.stream_utterances(
                stop_event=self._stop,
                gate=self._gated,
                on_level=self._on_level,
                on_event=self._on_mic_event,
            ):
                if self._stop.is_set():
                    break
                self._handle_utterance(utterance)

        except MicUnavailable as e:
            self._listening = False
            self._set_state(VoiceState.ERROR, str(e))
            self._message("error", str(e))
        except Exception as e:
            self._listening = False
            self._set_state(VoiceState.ERROR, str(e))
            self._message("error", f"Voice capture stopped: {e}")
        finally:
            if self._listening:
                self._set_state(VoiceState.OFF)

    def _on_mic_event(self, kind: str) -> None:
        if kind == "speech_start":
            self._set_state(VoiceState.SPEECH)
        elif kind == "speech_end" and self._listening and not self._busy.is_set():
            self._set_state(VoiceState.TRANSCRIBING)

    def _handle_utterance(self, utterance) -> None:
        self._set_state(VoiceState.TRANSCRIBING)
        result = self.stt.transcribe(utterance)

        if result.error:
            self._set_state(VoiceState.ERROR, result.error)
            self._message("error", result.error)
            if self._listening:
                self._set_state(VoiceState.LISTENING)
            return

        normalized: NormalizedSpeech = self.normalizer.normalize(result.text)

        if not normalized.accepted:
            # Heard something, but it wasn't a command. Say so quietly rather
            # than acting on it.
            if result.text.strip():
                self._message("dim", f'Ignored "{result.text.strip()}" ({normalized.reason})')
            if self._listening:
                self._set_state(VoiceState.LISTENING)
            return

        self.last_transcript = normalized.text
        if normalized.changed:
            self._message(
                "heard",
                f'"{normalized.raw.strip()}" -> "{normalized.text}"',
            )
        else:
            self._message("heard", f'"{normalized.text}"')

        self._set_state(VoiceState.BUSY, normalized.text)
        try:
            self._on_command(normalized.text)
        except Exception as e:
            self._message("error", f"Command dispatch failed: {e}")
