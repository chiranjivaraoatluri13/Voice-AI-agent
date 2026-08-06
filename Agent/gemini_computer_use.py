# =========================
# FILE: agent/gemini_computer_use.py
# =========================
"""
Gemini Computer Use (mobile) — screenshot → structured ADB actions.

Uses Google's Interactions API with environment=mobile so the model returns
click / type / open_app / go_back / wait / press_key calls on a 0–999 grid.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from agent.gemini_models import (
    preferred_model,
    model_candidates,
    is_transient_model_error,
    build_client,
)
from agent.ollama_vision import compress_for_vision

load_dotenv()

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


@dataclass
class GeminiActionResult:
    ok: bool
    actions: List[str] = field(default_factory=list)
    message: str = ""
    last_click: Optional[Tuple[int, int]] = None


class GeminiComputerUse:
    """Run a short mobile computer-use loop against the connected tablet."""

    def __init__(
        self,
        device,
        vision,
        model: Optional[str] = None,
        max_turns: int = 6,
    ) -> None:
        self.device = device
        self.vision = vision
        self.model = preferred_model(model)
        self.max_turns = max_turns
        self.client = None
        self.available = False
        self._last_error = ""
        self._check()

    def _check(self) -> None:
        # Prefer the project .env key the user configured (override shell leftovers)
        load_dotenv(override=True)
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            self._last_error = "GEMINI_API_KEY not set"
            print("⚠️ GEMINI_API_KEY not set. Gemini Computer Use disabled.")
            return
        if not GENAI_AVAILABLE:
            self._last_error = "google-genai not installed"
            print("⚠️ google-genai not installed. Run: pip install google-genai")
            return
        try:
            self.client = build_client(api_key)
            self.available = True
            try:
                print(f"✨ Gemini Computer Use ready ({self.model})")
            except UnicodeEncodeError:
                print(f"[Gemini] Computer Use ready ({self.model})")
        except Exception as e:
            self._last_error = str(e)
            print(f"⚠️ Gemini client init failed: {e}")

    def _screen_size(self) -> Tuple[int, int]:
        try:
            return self.device.screen_size()
        except Exception:
            return (
                getattr(self.vision, "screen_width", 1080),
                getattr(self.vision, "screen_height", 1920),
            )

    def _screenshot_b64(self, force: bool = True) -> Tuple[str, str]:
        """Return (base64, mime) downscaled for upload. Clicks use a 0-1000 grid,
        so shrinking the image doesn't move any coordinates."""
        try:
            b64 = self.vision.capture_screenshot_b64(force=force) or ""
        except Exception:
            return "", "image/png"
        if not b64:
            return "", "image/png"
        return compress_for_vision(b64)

    @staticmethod
    def _denorm(x: int, y: int, w: int, h: int) -> Tuple[int, int]:
        # Docs use 0–1000; some samples say 0–999. Clamp either way.
        nx = max(0, min(int(x), 1000))
        ny = max(0, min(int(y), 1000))
        return int(nx / 1000 * w), int(ny / 1000 * h)

    def _tool_config(self) -> List[Dict[str, Any]]:
        return [{
            "type": "computer_use",
            "environment": "mobile",
        }]

    def _function_calls(self, interaction) -> list:
        steps = getattr(interaction, "steps", None) or []
        return [s for s in steps if getattr(s, "type", "") == "function_call"]

    def _model_text(self, interaction) -> str:
        parts: List[str] = []
        for step in getattr(interaction, "steps", None) or []:
            if getattr(step, "type", "") != "model_output":
                continue
            for block in getattr(step, "content", None) or []:
                if getattr(block, "type", "") == "text" and getattr(block, "text", None):
                    parts.append(block.text)
        return " ".join(parts).strip()

    def _execute_calls(
        self, calls, w: int, h: int
    ) -> Tuple[List[Tuple[str, str, Dict]], Optional[Tuple[int, int]], List[str]]:
        results: List[Tuple[str, str, Dict]] = []
        last_click: Optional[Tuple[int, int]] = None
        log: List[str] = []

        for call in calls:
            fname = getattr(call, "name", "") or ""
            args = dict(getattr(call, "arguments", None) or {})
            call_id = getattr(call, "id", "") or ""
            intent = args.get("intent", "")
            action_result: Dict[str, Any] = {}
            try:
                print(f"   ✨ Gemini → {fname} {args}")
            except UnicodeEncodeError:
                print(f"   [Gemini] {fname} {args}")

            try:
                if fname in ("click", "click_at", "double_click", "long_press"):
                    ax, ay = self._denorm(int(args["x"]), int(args["y"]), w, h)
                    last_click = (ax, ay)
                    if fname == "long_press":
                        secs = int(args.get("seconds", 2))
                        self.device.long_press(ax, ay, duration_ms=secs * 1000)
                    elif fname == "double_click":
                        self.device.tap(ax, ay)
                        time.sleep(0.1)
                        self.device.tap(ax, ay)
                    else:
                        self.device.tap(ax, ay)
                    log.append(f"{fname}@({ax},{ay})")
                    time.sleep(0.35)

                elif fname in ("type", "type_text_at"):
                    if "x" in args and "y" in args:
                        ax, ay = self._denorm(int(args["x"]), int(args["y"]), w, h)
                        self.device.tap(ax, ay)
                        last_click = (ax, ay)
                        time.sleep(0.25)
                    text = str(args.get("text", ""))
                    try:
                        self.device.clear_text_field()
                    except Exception:
                        pass
                    time.sleep(0.15)
                    self.device.type_text(text)
                    if args.get("press_enter"):
                        self.device.adb.run(["shell", "input", "keyevent", "KEYCODE_ENTER"])
                    log.append(f"type:{text[:40]}")
                    time.sleep(0.35)

                elif fname == "open_app":
                    app_name = str(args.get("app_name", "")).strip()
                    action_result["note"] = (
                        f"open_app deferred to local resolver: {app_name}"
                    )
                    log.append(f"open_app:{app_name}")

                elif fname == "go_back":
                    self.device.back()
                    log.append("go_back")
                    time.sleep(0.3)

                elif fname == "wait":
                    time.sleep(float(args.get("seconds", 1)))
                    log.append("wait")

                elif fname == "press_key":
                    key = str(args.get("key", "")).lower()
                    key_map = {
                        "enter": "KEYCODE_ENTER",
                        "back": "KEYCODE_BACK",
                        "home": "KEYCODE_HOME",
                        "delete": "KEYCODE_DEL",
                        "backspace": "KEYCODE_DEL",
                        "tab": "KEYCODE_TAB",
                        "escape": "KEYCODE_ESCAPE",
                    }
                    code = key_map.get(key, f"KEYCODE_{key.upper()}" if key else "")
                    if code:
                        self.device.adb.run(["shell", "input", "keyevent", code])
                    log.append(f"press_key:{key}")
                    time.sleep(0.2)

                elif fname in ("take_screenshot", "list_apps"):
                    # Handled by returning a fresh screenshot in function_result
                    log.append(fname)

                elif fname in ("drag_and_drop", "scroll"):
                    # Best-effort swipe if start/end provided
                    if all(k in args for k in ("start_x", "start_y", "end_x", "end_y")):
                        x0, y0 = self._denorm(int(args["start_x"]), int(args["start_y"]), w, h)
                        x1, y1 = self._denorm(int(args["end_x"]), int(args["end_y"]), w, h)
                        self.device.adb.run([
                            "shell", "input", "swipe",
                            str(x0), str(y0), str(x1), str(y1), "350",
                        ])
                        log.append(f"swipe:({x0},{y0})→({x1},{y1})")
                        time.sleep(0.4)
                    else:
                        action_result["error"] = f"unhandled args for {fname}"
                else:
                    action_result["error"] = f"unhandled action: {fname}"
                    log.append(f"skip:{fname}")

                if intent:
                    action_result["intent"] = intent
            except Exception as e:
                action_result["error"] = str(e)
                log.append(f"err:{fname}:{e}")

            results.append((fname, call_id, action_result))

        return results, last_click, log

    def _function_responses(self, results, screenshot_b64: str,
                            mime: str = "image/png") -> list:
        responses = []
        for name, call_id, result in results:
            responses.append({
                "type": "function_result",
                "name": name,
                "call_id": call_id,
                "result": [
                    {"type": "text", "text": json.dumps(result or {"ok": True})},
                    {
                        "type": "image",
                        "data": screenshot_b64,
                        "mime_type": mime,
                    },
                ],
            })
        return responses

    def run_goal(self, goal: str) -> GeminiActionResult:
        """Execute a natural-language goal with Gemini Computer Use."""
        if not self.available or not self.client:
            return GeminiActionResult(ok=False, message=self._last_error or "Gemini unavailable")

        w, h = self._screen_size()
        shot, mime = self._screenshot_b64()
        if not shot:
            return GeminiActionResult(ok=False, message="No screenshot available")

        tools = self._tool_config()
        all_actions: List[str] = []
        last_click: Optional[Tuple[int, int]] = None

        interaction = None
        last_err: Optional[Exception] = None
        for model in model_candidates(self.model):
            try:
                interaction = self.client.interactions.create(
                    model=model,
                    input=[
                        {"type": "text", "text": goal},
                        {"type": "image", "data": shot, "mime_type": mime},
                    ],
                    tools=tools,
                )
                if model != self.model:
                    print(f"   ↻ Gemini Computer Use switched to {model}")
                    self.model = model
                break
            except Exception as e:
                last_err = e
                if is_transient_model_error(e):
                    continue
                self._last_error = str(e)
                return GeminiActionResult(ok=False, message=f"Gemini request failed: {e}")

        if interaction is None:
            self._last_error = str(last_err or "unknown")
            return GeminiActionResult(
                ok=False,
                message=f"Gemini request failed: {self._last_error}",
            )

        for turn in range(self.max_turns):
            calls = self._function_calls(interaction)
            if not calls:
                text = self._model_text(interaction)
                return GeminiActionResult(
                    ok=bool(all_actions),
                    actions=all_actions,
                    message=text or ("done" if all_actions else "no actions"),
                    last_click=last_click,
                )

            print(f"   ✨ Gemini turn {turn + 1}/{self.max_turns} ({len(calls)} action(s))")
            results, click, log = self._execute_calls(calls, w, h)
            all_actions.extend(log)
            if click:
                last_click = click

            new_shot, new_mime = self._screenshot_b64()
            if new_shot:
                shot, mime = new_shot, new_mime
            try:
                interaction = self.client.interactions.create(
                    model=self.model,
                    previous_interaction_id=interaction.id,
                    input=self._function_responses(results, shot, mime),
                    tools=tools,
                )
            except Exception as e:
                return GeminiActionResult(
                    ok=bool(all_actions),
                    actions=all_actions,
                    message=f"Gemini follow-up failed: {e}",
                    last_click=last_click,
                )

        return GeminiActionResult(
            ok=bool(all_actions),
            actions=all_actions,
            message="turn limit reached",
            last_click=last_click,
        )

    def find_and_tap(self, description: str) -> GeminiActionResult:
        return self.run_goal(
            f"On this Android tablet screen, tap exactly once on: {description}. "
            "Do not open other apps. Prefer a single precise click."
        )

    def search_on_screen(self, query: str) -> GeminiActionResult:
        return self.run_goal(
            f"On this Android tablet screen, find the TEXT search field "
            f"(not the camera/visual-search/lens icon), tap it, clear it, "
            f"type '{query}', and press enter/search. Complete the search."
        )

    def take_photo(self) -> GeminiActionResult:
        return self.run_goal(
            "On this Android camera screen, tap the shutter / capture button "
            "once to take a photo. Do not open settings or switch apps."
        )
