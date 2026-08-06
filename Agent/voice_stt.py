# =========================
# FILE: agent/voice_stt.py
# =========================
"""
Microphone capture and Groq Whisper speech-to-text.

Two pieces:

  MicListener   Streams the default input device and cuts it into utterances
                using energy-based voice activity detection. Yields one WAV
                blob per phrase so the user never has to hold a button.

  WhisperSTT    Sends a WAV blob to Groq `whisper-large-v3-turbo`.

Recognition accuracy is largely won here rather than in post-processing. Two
details matter most:

  * A pre-roll buffer. Detection needs a few blocks of audio before it is
    confident speech started, and those blocks contain the first phoneme —
    dropping them turns "open YouTube" into "pen YouTube".
  * A vocabulary prompt. Whisper accepts a text prompt that conditions
    decoding, so feeding it the actual command words and the labels of the
    apps installed on the tablet biases ambiguous audio toward terms this
    agent can act on ("scroll" over "school", "Temu" over "tay moo").

The noise floor is tracked continuously instead of measured once, because a
laptop fan spinning up mid-session would otherwise sit above a fixed threshold
and be transcribed as endless phantom speech.
"""

from __future__ import annotations

import io
import os
import queue
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional, Sequence

PREFERRED_RATE = 16000          # Whisper's native rate
SAMPLE_WIDTH = 2                # int16
CHANNELS = 1


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


@dataclass
class VadConfig:
    """Voice-activity thresholds. All times in milliseconds."""

    block_ms: int = 30
    # Consecutive voiced blocks needed to declare speech (debounces key clicks).
    start_blocks: int = 3
    # Trailing silence that ends a phrase. Long enough to survive the pause in
    # "open YouTube ... and search for jazz".
    silence_ms: int = 900
    # Shorter than this is a cough, a door, or a keystroke — not a command.
    min_speech_ms: int = 320
    # Hard stop so a stuck-open mic can't buffer forever.
    max_utterance_ms: int = 15000
    # Audio retained before the trigger point, prepended to the utterance.
    preroll_ms: int = 300
    # Speech must exceed noise_floor * multiplier.
    noise_multiplier: float = 3.0
    # Absolute int16 RMS floor, so a silent room can't drive the gate to zero.
    min_threshold: float = 170.0
    # Seconds of audio the callback may buffer before old blocks are dropped.
    max_buffer_s: float = 8.0

    @classmethod
    def from_env(cls) -> "VadConfig":
        return cls(
            silence_ms=_env_int("VOICE_SILENCE_MS", cls.silence_ms),
            min_speech_ms=_env_int("VOICE_MIN_SPEECH_MS", cls.min_speech_ms),
            max_utterance_ms=_env_int("VOICE_MAX_UTTERANCE_MS", cls.max_utterance_ms),
            noise_multiplier=_env_float("VOICE_NOISE_MULTIPLIER", cls.noise_multiplier),
            min_threshold=_env_float("VOICE_MIN_THRESHOLD", cls.min_threshold),
        )


@dataclass
class Utterance:
    """One detected phrase, as a self-contained WAV file in memory."""

    wav: bytes
    duration_ms: float
    peak_rms: float
    sample_rate: int


@dataclass
class Transcript:
    text: str
    latency_ms: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text) and not self.error


class MicUnavailable(RuntimeError):
    """No usable input device, or PortAudio/sounddevice is missing."""


def _load_sounddevice():
    try:
        import sounddevice as sd
    except Exception as e:
        raise MicUnavailable(
            "Microphone support needs the 'sounddevice' package: "
            "pip install sounddevice"
        ) from e
    return sd


def microphone_name() -> str:
    """Best-effort label for the active input device (for the UI)."""
    try:
        sd = _load_sounddevice()
        info = sd.query_devices(kind="input")
        name = str(info.get("name", "")).strip()
        # PortAudio truncates and sometimes mangles non-ASCII device names.
        return name.encode("ascii", "ignore").decode("ascii") or "Microphone"
    except Exception:
        return "Microphone"


def _rms(block: bytes) -> float:
    """Root-mean-square amplitude of an int16 block."""
    import numpy as np

    if not block:
        return 0.0
    samples = np.frombuffer(block, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    # float64 accumulate: int16 squares overflow, and float32 loses precision
    # on long blocks, which quietly shifts the noise floor.
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def _to_wav(blocks: Sequence[bytes], sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(blocks))
    return buf.getvalue()


class MicListener:
    """Cuts the microphone stream into utterances via energy-based VAD."""

    def __init__(self, config: Optional[VadConfig] = None) -> None:
        self.cfg = config or VadConfig.from_env()
        self.sample_rate = PREFERRED_RATE
        self.noise_floor = 0.0
        self._level = 0.0

    @property
    def threshold(self) -> float:
        return max(self.cfg.min_threshold, self.noise_floor * self.cfg.noise_multiplier)

    def _open_stream(self, sd, on_block: Callable[[bytes], None]):
        """Open at 16 kHz if the device allows it, else at its native rate.

        Whisper resamples server-side, so falling back costs bandwidth but not
        accuracy — whereas refusing to open the stream costs the user the mic.
        """
        def callback(indata, _frames, _time, status):  # noqa: ANN001
            on_block(bytes(indata))

        errors = []
        for rate in (PREFERRED_RATE, None):
            try:
                if rate is None:
                    info = sd.query_devices(kind="input")
                    rate = int(info.get("default_samplerate") or 44100)
                blocksize = max(1, int(rate * self.cfg.block_ms / 1000))
                stream = sd.InputStream(
                    samplerate=rate,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=blocksize,
                    callback=callback,
                )
                stream.start()
                self.sample_rate = rate
                return stream
            except Exception as e:
                errors.append(f"{rate or 'device default'} Hz: {e}")
        raise MicUnavailable("Could not open microphone (" + "; ".join(errors) + ")")

    def stream_utterances(
        self,
        stop_event: threading.Event,
        gate: Optional[Callable[[], bool]] = None,
        on_level: Optional[Callable[[float], None]] = None,
        on_event: Optional[Callable[[str], None]] = None,
    ) -> Iterator[Utterance]:
        """
        Yield an `Utterance` per detected phrase until `stop_event` is set.

        gate      Returns True while audio should be discarded (e.g. the agent
                  is mid-command and the tablet's own speaker is audible).
        on_level  Receives a 0..1 loudness value for UI animation.
        on_event  Receives "speech_start" / "speech_end" / "too_short".
        """
        sd = _load_sounddevice()
        blocks: "queue.Queue[bytes]" = queue.Queue(
            maxsize=max(8, int(self.cfg.max_buffer_s * 1000 / self.cfg.block_ms))
        )

        def push(block: bytes) -> None:
            try:
                blocks.put_nowait(block)
            except queue.Full:
                # Drop the oldest: a stale block is worthless, and blocking
                # inside PortAudio's callback would glitch the whole stream.
                try:
                    blocks.get_nowait()
                    blocks.put_nowait(block)
                except (queue.Empty, queue.Full):
                    pass

        stream = self._open_stream(sd, push)
        try:
            yield from self._segment(blocks, stop_event, gate, on_level, on_event)
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _segment(
        self,
        blocks: "queue.Queue[bytes]",
        stop_event: threading.Event,
        gate: Optional[Callable[[], bool]],
        on_level: Optional[Callable[[float], None]],
        on_event: Optional[Callable[[str], None]],
    ) -> Iterator[Utterance]:
        cfg = self.cfg
        block_ms = cfg.block_ms
        preroll_len = max(1, int(cfg.preroll_ms / block_ms))
        silence_needed = max(1, int(cfg.silence_ms / block_ms))
        max_blocks = max(1, int(cfg.max_utterance_ms / block_ms))

        preroll: deque = deque(maxlen=preroll_len)
        voiced: List[bytes] = []
        voiced_run = 0
        silence_run = 0
        peak = 0.0
        in_speech = False
        # Seed the floor high enough that the very first blocks can't be
        # mistaken for speech before any ambient audio has been observed.
        self.noise_floor = max(self.noise_floor, cfg.min_threshold / cfg.noise_multiplier)

        def emit_level(value: float) -> None:
            if on_level:
                try:
                    on_level(value)
                except Exception:
                    pass

        def notify(kind: str) -> None:
            if on_event:
                try:
                    on_event(kind)
                except Exception:
                    pass

        def reset() -> None:
            nonlocal voiced, voiced_run, silence_run, in_speech, peak
            voiced = []
            voiced_run = 0
            silence_run = 0
            in_speech = False
            peak = 0.0

        while not stop_event.is_set():
            try:
                block = blocks.get(timeout=0.2)
            except queue.Empty:
                continue

            if gate and gate():
                # Muted: drain state so speech resumes from a clean slate.
                if in_speech:
                    notify("speech_end")
                reset()
                preroll.clear()
                emit_level(0.0)
                continue

            rms = _rms(block)
            thresh = self.threshold
            is_voice = rms > thresh

            if is_voice:
                peak = max(peak, rms)
            else:
                # Adapt only on non-speech so speech can't inflate the floor.
                self.noise_floor = (0.94 * self.noise_floor) + (0.06 * rms)

            emit_level(min(1.0, rms / max(thresh * 3.0, 1.0)))

            if not in_speech:
                preroll.append(block)
                voiced_run = voiced_run + 1 if is_voice else 0
                if voiced_run >= cfg.start_blocks:
                    in_speech = True
                    silence_run = 0
                    voiced = list(preroll)      # includes the speech onset
                    preroll.clear()
                    notify("speech_start")
                continue

            voiced.append(block)
            silence_run = 0 if is_voice else silence_run + 1

            done = silence_run >= silence_needed or len(voiced) >= max_blocks
            if not done:
                continue

            notify("speech_end")
            # Trailing silence carries no information and costs upload time.
            keep = voiced[: len(voiced) - silence_run] if silence_run else voiced
            duration_ms = len(keep) * block_ms
            captured_peak = peak
            reset()
            preroll.clear()
            emit_level(0.0)

            if duration_ms < cfg.min_speech_ms:
                notify("too_short")
                continue

            yield Utterance(
                wav=_to_wav(keep, self.sample_rate),
                duration_ms=duration_ms,
                peak_rms=captured_peak,
                sample_rate=self.sample_rate,
            )


# =========================================================
# GROQ WHISPER
# =========================================================

# Words the agent can actually act on. Whisper leans on this to disambiguate
# similar-sounding audio; the tablet's real app labels get appended at runtime.
BASE_VOCABULARY = (
    "scroll up, scroll down, swipe left, swipe right, go back, home screen, "
    "close app, recent apps, volume up, volume down, mute, unmute, maximum volume, "
    "brightness up, brightness down, Wi-Fi, Bluetooth, torch, flashlight, hotspot, "
    "mobile data, airplane mode, do not disturb, battery saver, auto rotate, "
    "screenshot, take a photo, open, launch, install, uninstall, search for, "
    "type, send, click, tap, subscribe, like, play, pause, next, previous"
)

WHISPER_PROMPT_LIMIT = 850   # Whisper caps the prompt near 224 tokens.


class WhisperSTT:
    """Groq-hosted Whisper, prompted with this agent's vocabulary."""

    DEFAULT_MODEL = "whisper-large-v3-turbo"

    def __init__(
        self,
        model: Optional[str] = None,
        vocabulary_provider: Optional[Callable[[], Sequence[str]]] = None,
        language: str = "en",
    ) -> None:
        self.model = model or os.environ.get("GROQ_STT_MODEL") or self.DEFAULT_MODEL
        self.language = language
        self._vocabulary_provider = vocabulary_provider
        self._prompt_cache: Optional[str] = None
        self._client = None
        self.error = ""
        self._init_client()

    def _init_client(self) -> None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            self.error = "GROQ_API_KEY not set — speech-to-text unavailable."
            return
        try:
            from groq import Groq
            self._client = Groq(api_key=api_key)
        except Exception as e:
            self.error = f"Groq client init failed: {e}"

    @property
    def available(self) -> bool:
        return self._client is not None

    def refresh_vocabulary(self) -> None:
        """Call once app labels are loaded, so the next prompt includes them."""
        self._prompt_cache = None

    def _prompt(self) -> str:
        if self._prompt_cache is not None:
            return self._prompt_cache

        parts = [
            "Voice commands for an Android tablet assistant.",
            "Vocabulary: " + BASE_VOCABULARY + ".",
        ]
        try:
            apps = list(self._vocabulary_provider() or []) if self._vocabulary_provider else []
        except Exception:
            apps = []
        if apps:
            parts.append("App names: " + ", ".join(apps[:60]) + ".")

        prompt = " ".join(parts)
        if len(prompt) > WHISPER_PROMPT_LIMIT:
            prompt = prompt[:WHISPER_PROMPT_LIMIT].rsplit(",", 1)[0] + "."
        self._prompt_cache = prompt
        return prompt

    def transcribe(self, utterance: Utterance, retries: int = 1) -> Transcript:
        """Transcribe an in-memory WAV. Never raises."""
        if not self.available:
            return Transcript(text="", error=self.error or "STT unavailable")

        t0 = time.perf_counter()
        last_error = ""
        for attempt in range(retries + 1):
            try:
                result = self._client.audio.transcriptions.create(
                    file=("speech.wav", utterance.wav),
                    model=self.model,
                    language=self.language,
                    prompt=self._prompt(),
                    # Greedy decoding: sampling invents plausible-sounding
                    # commands, and a wrong command taps the wrong button.
                    temperature=0.0,
                    response_format="text",
                )
                text = str(result).strip()
                return Transcript(
                    text=text,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            except Exception as e:
                last_error = str(e)
                if attempt < retries:
                    time.sleep(0.4)

        return Transcript(
            text="",
            latency_ms=(time.perf_counter() - t0) * 1000,
            error=f"Transcription failed: {last_error}",
        )


def transcribe_file(path: str, **kwargs) -> Optional[str]:
    """Transcribe an existing audio file. Kept for one-off scripts."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        print(f"⚠️ Could not read {path}: {e}")
        return None
    stt = WhisperSTT(**kwargs)
    result = stt.transcribe(Utterance(wav=data, duration_ms=0.0, peak_rms=0.0, sample_rate=PREFERRED_RATE))
    if not result.ok:
        print(f"⚠️ {result.error}")
        return None
    return result.text
