# =========================
# FILE: agent/voice_app.py
# =========================
"""
Voice front-end: floating mic overlay + AgentRuntime.

The overlay owns the main thread (tkinter requirement on Windows). A worker
thread boots the runtime, marks the session ready, then drains a command queue
so speech / typed input never block the paint loop.
"""

from __future__ import annotations

import queue
import signal
import threading
import time
from typing import Optional

from agent.runtime import AgentRuntime
from agent.voice_overlay import MicOverlay
from agent.voice_session import VoiceSession, VoiceState


def run_voice() -> None:
    """Blocking entry — returns when the overlay closes or the user exits."""
    print(
        "\n"
        "  Voice mode\n"
        "  • Click the mic to talk, click again to stop\n"
        "  • Right-click the overlay for Start / Stop / Expand / Quit\n"
        "  • Type in the expanded panel and press Enter to send a command\n"
    )

    cmd_q: queue.Queue[Optional[str]] = queue.Queue()
    runtime = AgentRuntime(llm_model="openai/gpt-oss-20b")
    overlay_holder: dict = {"overlay": None}
    session_holder: dict = {"session": None}
    shutdown_lock = threading.Lock()
    shut_down = {"done": False}

    def _shutdown(reason: str = "") -> None:
        with shutdown_lock:
            if shut_down["done"]:
                return
            shut_down["done"] = True
        if reason:
            print(reason, flush=True)
        # Unblock the worker if it is waiting on the queue.
        try:
            cmd_q.put_nowait(None)
        except Exception:
            pass
        session = session_holder.get("session")
        if session is not None:
            try:
                session.shutdown()
            except Exception:
                pass
        try:
            runtime.shutdown()
        except Exception:
            pass
        overlay = overlay_holder.get("overlay")
        if overlay is not None:
            try:
                overlay.close()
            except Exception:
                pass

    def on_command(text: str) -> None:
        # Listener thread — enqueue only; never touch tk or the runtime here.
        cmd_q.put(text)

    def on_state(state: VoiceState, detail: str = "") -> None:
        overlay = overlay_holder.get("overlay")
        if overlay is not None:
            overlay.set_state(state, detail)
        label = state.value if hasattr(state, "value") else str(state)
        extra = f" ({detail})" if detail else ""
        print(f"[voice] {label}{extra}", flush=True)

    def on_level(level: float) -> None:
        overlay = overlay_holder.get("overlay")
        if overlay is not None:
            overlay.set_level(level)

    def on_message(kind: str, text: str) -> None:
        overlay = overlay_holder.get("overlay")
        if overlay is not None:
            overlay.set_message(kind, text)
        prefix = {
            "error": "❌",
            "warn": "⚠️",
            "heard": "🎤",
            "dim": "·",
            "info": "ℹ️",
        }.get(kind, "·")
        print(f"{prefix} {text}", flush=True)

    def on_toggle() -> None:
        session = session_holder.get("session")
        if session is not None:
            session.toggle()

    def on_text_command(text: str) -> None:
        cmd_q.put(text)

    def on_quit() -> None:
        _shutdown("Stopping (overlay quit).")

    overlay = MicOverlay(
        on_toggle=on_toggle,
        on_text_command=on_text_command,
        on_quit=on_quit,
    )
    overlay_holder["overlay"] = overlay

    session = VoiceSession(
        on_command=on_command,
        on_state=on_state,
        on_level=on_level,
        on_message=on_message,
        app_vocabulary=runtime.app_vocabulary,
        gate_while_busy=True,
    )
    session_holder["session"] = session

    def worker() -> None:
        try:
            runtime.start()
            runtime.print_help()
            session.set_ready(True)
            overlay.set_ready(True)
            print("✅ Voice ready — click the mic to start listening.", flush=True)

            while not shut_down["done"]:
                try:
                    cmd = cmd_q.get(timeout=0.25)
                except queue.Empty:
                    continue
                if cmd is None or shut_down["done"]:
                    break
                cmd = (cmd or "").strip()
                if not cmd:
                    continue

                session.set_busy(True)
                try:
                    result = runtime.handle(cmd)
                except KeyboardInterrupt:
                    _shutdown("\nStopping.")
                    break
                except Exception as e:
                    print(f"❌ Error: {e}", flush=True)
                    result = "error"
                finally:
                    # Only clear busy if we are still the active front-end.
                    if not shut_down["done"]:
                        session.set_busy(False)

                if result == "exit":
                    _shutdown("Stopping.")
                    break
        except KeyboardInterrupt:
            _shutdown("\nStopping.")
        except Exception as e:
            print(f"❌ Voice worker failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            try:
                overlay.set_message("error", str(e))
                overlay.set_state(VoiceState.ERROR, str(e))
            except Exception:
                pass
            # Give the overlay a moment to show the error, then tear down.
            time.sleep(1.5)
            _shutdown()

    thread = threading.Thread(target=worker, name="voice-worker", daemon=True)
    thread.start()

    def _sig(_signum, _frame) -> None:
        _shutdown("\nStopping (Ctrl+C).")

    try:
        signal.signal(signal.SIGINT, _sig)
    except Exception:
        pass

    try:
        overlay.run()
    finally:
        _shutdown()
        thread.join(timeout=4.0)
