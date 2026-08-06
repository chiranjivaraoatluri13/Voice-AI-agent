# =========================
# FILE: agent/runtime.py
# =========================
"""
Shared agent runtime.

The dispatch chain (workflow hook → device features → parallel NLU pipeline)
used to live inline inside `run_cli`, which meant a second front-end had no way
to reach it without copying the loop body. Voice input needs exactly the same
routing as typed input — a mishandled transcript should fail the same way a
mistyped command does — so the setup and the per-utterance dispatch live here
and both front-ends drive the same object.
"""

import re
import time
from typing import List, Optional

from agent.adb import AdbClient
from agent.apps import AppResolver
from agent.device import DeviceController
from agent.device_command_mapper import DeviceCommandMapper
from agent.device_features import DeviceFeatureController
from agent.intent_engine import IntentEngine
from agent.learner import CommandLearner
from agent.screen_controller import ScreenController
from agent.parallel import process_command_parallel
from agent.controller import (
    execute_command,
    _get_current_app,
    _is_device_command,
    _needs_app_context,
)

HELP_TEXT = """
==================================================
back | home | close | scroll up/down | swipe left
open youtube | type hello | write hi and send
click subscribe | search cats on youtube
play | pause | volume up | sound more up
teach me to <task>  | list workflows | exit

📱 Device Controls:
enable wifi | turn on bluetooth | toggle torch
device status | available features
==================================================
"""


class AgentRuntime:
    """Owns the device connection and turns one utterance into one action."""

    def __init__(self, llm_model: str = "openai/gpt-oss-20b") -> None:
        self.llm_model = llm_model
        self.adb: Optional[AdbClient] = None
        self.device: Optional[DeviceController] = None
        self.learner: Optional[CommandLearner] = None
        self.apps: Optional[AppResolver] = None
        self.screen: Optional[ScreenController] = None
        self.engine: Optional[IntentEngine] = None
        self.device_mapper: Optional[DeviceCommandMapper] = None
        self.wf_runner = None
        self.ready = False
        self._closed = False
        self._cached_app = ""
        self._cached_app_time = 0.0

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Connect to the device and warm the caches. Slow (seconds) by nature."""
        self.adb = AdbClient()
        devs = self.adb.ensure_device()
        print("✅ Connected:", len(devs), "device(s)")

        self.device = DeviceController(self.adb)
        self.learner = CommandLearner()
        self.apps = AppResolver(self.adb, self.learner)
        self.screen = ScreenController(self.adb, self.device)
        self.engine = IntentEngine(llm_model=self.llm_model)

        device_features = DeviceFeatureController(self.adb)
        self.device_mapper = DeviceCommandMapper(device_features)

        self.device.wake()

        from agent import workflow_runner as wf_runner
        self.wf_runner = wf_runner

        try:
            w, h = self.device.screen_size()
            print(f"📱 {w}x{h}")
            self.screen.vision.set_screen_size(w, h)
        except Exception:
            pass

        # Warm the UI tree before accepting input (cheap, local) but let the
        # vision map build in the background — a slow/overloaded vision API
        # once held startup hostage for ~54s.
        try:
            self.screen.warm_start(wait_vision=False, start_background=False)
        except Exception as e:
            print(f"⚠️ Warm-start failed: {e}")

        print("📦 Loading apps...")
        stats = self.apps.initialize()
        print(f"✅ {stats['total']} apps, {stats['time_ms']}ms")

        # Only now hand the ADB bus to the background watcher.
        try:
            self.screen.start_watching()
        except Exception as e:
            print(f"⚠️ Live watch failed to start: {e}")

        if self.learner.mappings:
            print(f"🎓 {len(self.learner.mappings)} mappings")
        wf_count = self.wf_runner.workflow_count()
        if wf_count:
            print(f"📚 {wf_count} learned workflow(s)")

        self.ready = True

    @staticmethod
    def print_help() -> None:
        print(HELP_TEXT)

    # ------------------------------------------------------------------
    # Vocabulary (used to bias speech recognition toward real app names)
    # ------------------------------------------------------------------
    def app_vocabulary(self) -> List[str]:
        """Installed app labels, for STT prompt biasing and fuzzy correction."""
        if not self.apps:
            return []
        labels = []
        for label in (self.apps.label_cache or {}).values():
            label = (label or "").strip()
            if label and not label.startswith("com."):
                labels.append(label)
        # Learned shortcuts are what the user actually says out loud.
        try:
            labels.extend(str(k) for k in (self.learner.mappings or {}).keys())
        except Exception:
            pass
        seen = set()
        unique = []
        for label in labels:
            key = label.lower()
            if key not in seen:
                seen.add(key)
                unique.append(label)
        return unique

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def handle(self, utter: str) -> str:
        """
        Route one utterance through the full pipeline.

        Returns "ok", "empty", "exit", "unknown", or "error".
        """
        if not self.ready:
            return "error"

        utter = (utter or "").strip()
        if not utter:
            return "empty"

        try:
            # ── WORKFLOW HOOK (self-contained, safe) ──
            action, data = self.wf_runner.intercept(utter)
            if action == "handled":
                return "ok"
            if action == "execute":
                self._replay_workflow(data)
                return "ok"
            # "pass" — utter may have been modified during recording
            utter = data

            # ── DEVICE FEATURE COMMANDS (priority over intent engine) ──
            t_lower = utter.lower().strip()
            if _is_device_command(t_lower):
                try:
                    result = self.device_mapper.execute_device_command(utter)
                    # If the mapper doesn't recognize it, fall through to NLU
                    if not (result and "not a device command" in result.lower()):
                        print(result)
                        return "ok"
                except Exception as e:
                    print(f"⚠️ Device command failed: {e}")
                    return "error"

            # ── NORMAL COMMAND (parallel pipeline) ──
            current_app = self._current_app(t_lower)

            cmd = process_command_parallel(
                utterance=utter,
                engine=self.engine,
                screen=self.screen,
                device=self.device,
                apps=self.apps,
                learner=self.learner,
                adb=self.adb,
                current_app=current_app,
                execute_fn=execute_command,
            )
            if not cmd:
                print("❌ Didn't understand.")
                return "unknown"
            if cmd.action == "EXIT":
                return "exit"
            # execute_command already ran inside process_command_parallel
            return "ok"

        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return "error"

    def _replay_workflow(self, steps) -> None:
        current_app = _get_current_app(self.adb)
        for i, step_cmd in enumerate(steps):
            print(f"  ▶ Step {i+1}: {step_cmd}")
            sub = self.engine.understand(step_cmd, current_app=current_app)
            if sub and sub.action != "EXIT":
                execute_command(
                    sub, self.device, self.apps, self.learner,
                    self.screen, self.adb, current_app, self.engine,
                )
                time.sleep(0.5)
                current_app = _get_current_app(self.adb)
        print("✅ Done\n")

    def _current_app(self, t_lower: str) -> str:
        if _needs_app_context(t_lower):
            now = time.time()
            if now - self._cached_app_time > 2.0:
                self._cached_app = _get_current_app(self.adb)
                self._cached_app_time = now
        return self._cached_app

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """Idempotent — both front-ends and their signal handlers call it."""
        if self._closed:
            return
        self._closed = True
        self.ready = False
        try:
            if self.screen:
                self.screen.stop_watching()
        except Exception:
            pass
        try:
            listener = getattr(self.apps, "install_listener", None)
            if listener:
                listener.stop()
        except Exception:
            pass
