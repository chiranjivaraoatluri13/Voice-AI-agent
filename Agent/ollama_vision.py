# =========================
# FILE: agent/ollama_vision.py
# =========================
"""
Screen vision — CONTINUOUS WATCHING MODE (Gemini).

Groq is NOT used here (rate limits on vision). Intent/STT still use Groq elsewhere.

Background thread: screenshots + Gemini inventory → live screen index
Command path: read cached index first; targeted Gemini locate only on miss.
"""

import json
import base64
import time
import threading
import os
import tempfile
from typing import Optional, Dict, Tuple, List
from dataclasses import dataclass, field
from dotenv import load_dotenv
import re
from agent.console import CONSOLE
from agent.gemini_models import (
    preferred_model,
    model_candidates,
    is_transient_model_error,
    build_client,
)

load_dotenv(override=True)

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Tablet screenshots are ~1.1MB as PNG (~1.5MB base64). Half-scale JPEG keeps
# every label readable at ~5% of the bytes, which is the difference between
# staying inside the vision API quota and exhausting it.
VISION_IMAGE_SCALE = float(os.environ.get("VISION_IMAGE_SCALE", "0.5"))
VISION_IMAGE_QUALITY = int(os.environ.get("VISION_IMAGE_QUALITY", "70"))

_compress_cache: Dict[str, Tuple[str, str]] = {}


def compress_for_vision(b64_png: str) -> Tuple[str, str]:
    """
    Shrink a base64 PNG screenshot for upload.

    Returns (base64_data, mime_type); falls back to the original PNG when
    Pillow is unavailable or the image can't be decoded. Coordinates are
    unaffected because every caller works in percentages or a 0-1000 grid.
    """
    if not b64_png or not PIL_AVAILABLE or VISION_IMAGE_SCALE >= 1.0:
        return b64_png, "image/png"

    key = f"{len(b64_png)}:{hash(b64_png[:2048])}:{hash(b64_png[-2048:])}"
    hit = _compress_cache.get(key)
    if hit:
        return hit

    try:
        import io
        raw = base64.b64decode(b64_png)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        w = max(1, int(img.width * VISION_IMAGE_SCALE))
        h = max(1, int(img.height * VISION_IMAGE_SCALE))
        buf = io.BytesIO()
        img.resize((w, h), Image.LANCZOS).save(
            buf, format="JPEG", quality=VISION_IMAGE_QUALITY, optimize=True
        )
        out = (base64.b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg")
    except Exception:
        return b64_png, "image/png"

    _compress_cache.clear()  # only the newest screenshot is ever reused
    _compress_cache[key] = out
    return out


@dataclass
class VisionResult:
    description: str
    coordinates: Optional[Tuple[int, int]] = None
    confidence: float = 0.0
    elements: List[Dict] = field(default_factory=list)


def _word_eq(text: str, word: str) -> bool:
    """True if `word` appears as a whole token in `text` (not as a substring)."""
    if not text or not word:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text.lower()))


class OllamaVision:
    """
    Gemini vision (default gemini-3.6-flash) with continuous watching & element finding.
    Class name kept for compatibility with existing imports.
    """
    
    def __init__(self, model: str = None) -> None:
        self.model = preferred_model(model)
        self.client = None
        self.available = False
        self.screen_width = 1080
        self.screen_height = 2400
        
        # Background watching state
        self._watch_thread: Optional[threading.Thread] = None
        self._watching = False
        self._paused = False  # pause during active commands (ADB contention)
        self._screenshot_interval = 1.5
        self._map_interval = 8.0  # min gap between vision inventories
        # Idle backoff: a static screen never needs a new inventory. Intervals
        # grow while nothing changes so sitting at the prompt costs no quota.
        self._map_interval_max = 120.0
        # Progressive idle backoff. Each screencap holds the ADB bus for ~1.2s,
        # so the longer the screen sits still the less often we look.
        self._idle_intervals = (3.0, 6.0, 10.0)
        self._last_map_signature = ""
        self._last_shot_signature = ""
        self._unchanged_cycles = 0
        self._last_description = ""
        self._last_description_time = 0
        self._last_screenshot_b64 = ""
        self._last_screenshot_time = 0
        self._screenshot_lock = threading.Lock()
        self._adb = None

        # Live screen understanding (UI text + vision labels)
        self._map_lock = threading.Lock()
        self._screen_map: List[Dict] = []       # vision items
        self._ui_index: List[Dict] = []         # accessibility-tree items
        self._last_map_time = 0.0
        self._last_ui_index_time = 0.0
        self._map_busy = False
        self._map_refresh_count = 0
        self._last_map_error = ""
        self._rate_limited_until = 0.0
        self._rate_limit_notified = False
        self._force_map_refresh = False
        
        self._screenshot_path = os.path.join(tempfile.gettempdir(), "vision_watch.png")
        
        self._check_availability()

    def _check_availability(self) -> None:
        load_dotenv(override=True)
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if api_key and GENAI_AVAILABLE:
            try:
                self.client = build_client(api_key)
                self.available = True
                try:
                    print(f"🖼️ Vision backend: Gemini ({self.model})")
                except UnicodeEncodeError:
                    print(f"[Vision] Gemini ({self.model})")
            except Exception as e:
                self.available = False
                print(f"⚠️ Gemini Vision client initialization failed: {e}")
        else:
            self.available = False
            if not GENAI_AVAILABLE:
                print("⚠️ google-genai not installed. Vision disabled. pip install google-genai")
            elif not api_key:
                print("⚠️ GEMINI_API_KEY not set. Vision features disabled.")
    
    def set_screen_size(self, w: int, h: int) -> None:
        self.screen_width = w
        self.screen_height = h
    
    # =========================================================
    # BACKGROUND WATCHING
    # =========================================================
    def start_watching(self, adb) -> None:
        """Continuously capture + understand the screen so taps use a live index."""
        self._adb = adb
        if not self.available:
            return
        if self._watching:
            return
        self._watching = True
        self._paused = False
        # Force an immediate first inventory (don't wait for _map_interval)
        self._last_map_time = 0.0
        self._force_map_refresh = True
        self._watch_thread = threading.Thread(
            target=self._watch_loop, name="vision-watch", daemon=True
        )
        self._watch_thread.start()
        try:
            print("👁️ Live screen watch ON — indexing UI + vision map in background")
        except UnicodeEncodeError:
            print("[Vision] Live screen watch ON")

    def warm_start(self, adb, timeout_s: float = 25.0) -> bool:
        """
        Block briefly at process start: screenshot + first vision inventory NOW.
        Returns True if a screen map (or at least a screenshot) is ready.
        """
        self._adb = adb
        if not self.available:
            return False
        try:
            print("🔥 Warming vision (screenshot + screen map)…")
        except UnicodeEncodeError:
            print("[Vision] Warming…")

        t0 = time.time()
        shot = self.capture_screenshot_b64(force=True, background=False)
        if not shot:
            print("⚠️ Vision warmup: screenshot failed")
            return False

        # Run map build in this thread so the CLI doesn't open cold
        self._force_map_refresh = True
        self._refresh_screen_map()
        ready = bool(self._screen_map) or bool(self._last_description)
        elapsed = (time.time() - t0) * 1000
        n = 0
        with self._map_lock:
            n = len(self._screen_map)
        if ready and n:
            try:
                print(f"✅ Vision warm ({n} map items, {elapsed:.0f}ms)")
            except UnicodeEncodeError:
                print(f"[Vision] warm ({n} items, {elapsed:.0f}ms)")
        elif self._rate_limited_until > time.time():
            print(f"⚠️ Vision warmup hit rate-limit — UI index will still warm ({elapsed:.0f}ms)")
        else:
            print(f"⚠️ Vision warmup partial (screenshot only, {elapsed:.0f}ms)")
        return bool(shot)

    def stop_watching(self) -> None:
        self._watching = False
        if self._watch_thread and self._watch_thread.is_alive():
            self._watch_thread.join(timeout=2.0)
        self._watch_thread = None

    def pause_watching(self) -> None:
        """Stop issuing background captures. Returns immediately: foreground
        priority in AdbClient already keeps new background work out of the way,
        and blocking here would only relocate the wait, not remove it."""
        self._paused = True

    def resume_watching(self) -> None:
        self._paused = False

    def _watch_loop(self) -> None:
        """
        Keep the screenshot warm and re-inventory the screen only when it
        actually changes.

        A screencap costs ~1.2s of exclusive ADB time and a vision inventory
        uploads a full screenshot, so polling on a fixed timer starved the ADB
        bus and drained the vision API quota while the user sat at the prompt.
        """
        while self._watching:
            interval = self._screenshot_interval
            try:
                if self._paused:
                    time.sleep(0.3)
                    continue
                if self._adb is not None and self._adb.foreground_pending():
                    time.sleep(0.1)
                    continue

                self.capture_screenshot_b64(force=True, background=True)
                signature = self.screenshot_signature()
                changed = bool(signature) and signature != self._last_shot_signature
                self._last_shot_signature = signature

                if changed:
                    self._unchanged_cycles = 0
                else:
                    self._unchanged_cycles += 1
                    interval = self._idle_interval_for(self._unchanged_cycles)

                now = time.time()
                if now < self._rate_limited_until:
                    time.sleep(max(interval, self._screenshot_interval))
                    continue

                force = getattr(self, "_force_map_refresh", False)
                if force or self._should_refresh_map(signature, now):
                    self._force_map_refresh = False
                    self._refresh_screen_map(signature)
            except Exception as e:
                self._last_map_error = str(e)
            time.sleep(interval)

    def _idle_interval_for(self, unchanged_cycles: int) -> float:
        """Back off capture cadence the longer the screen stays unchanged."""
        if unchanged_cycles < 3:
            return self._screenshot_interval
        step = min((unchanged_cycles - 3) // 3, len(self._idle_intervals) - 1)
        return self._idle_intervals[step]

    def _should_refresh_map(self, signature: str, now: float) -> bool:
        """Re-inventory only on a changed screen, with a slow idle heartbeat."""
        age = now - self._last_map_time
        if age < self._map_interval:
            return False
        # Screen changed since the last inventory → refresh.
        if signature and signature != self._last_map_signature:
            return True
        # Unchanged: fall back to a very slow heartbeat so a missed change
        # (e.g. identical-looking screenshot) still self-heals eventually.
        return age >= self._map_interval_max

    def _note_rate_limit(self, detail: str = "", backoff_s: float = 60.0) -> None:
        """Back off vision API calls; print once so the CLI prompt isn't flooded."""
        self._rate_limited_until = time.time() + backoff_s
        self._last_map_error = f"rate limited ({detail[:80]})" if detail else "rate limited"
        if not self._rate_limit_notified:
            self._rate_limit_notified = True
            try:
                CONSOLE.notice(
                    f"⚠️ Gemini vision rate-limited — UI index keeps running; "
                    f"vision map resumes in ~{int(backoff_s)}s"
                )
            except Exception:
                pass

    @staticmethod
    def _is_rate_limit_text(text: str) -> bool:
        return is_transient_model_error(text)

    @staticmethod
    def _strip_model_noise(text: str, prefer_json: bool = True) -> str:
        """Remove thinking blocks / markdown fences so JSON can parse."""
        if not text:
            return ""
        import re
        text = re.sub(r"<think>[\s\S]*?(?:</think>|$)", "", text, flags=re.I)
        text = re.sub(r"<thinking>[\s\S]*?(?:</thinking>|$)", "", text, flags=re.I)
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = text.replace("```", "").strip()
        if prefer_json:
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                return m.group(0)
        return text

    def screenshot_signature(self) -> str:
        """Cheap fingerprint of the last screenshot, for change detection."""
        with self._screenshot_lock:
            b64 = self._last_screenshot_b64
        if not b64:
            return ""
        return f"{len(b64)}:{hash(b64[:4096])}:{hash(b64[-4096:])}"

    def screenshot_age(self) -> float:
        """Seconds since the last screenshot. Large when the watcher is idle."""
        with self._screenshot_lock:
            if not self._last_screenshot_b64:
                return 1e9
            return time.time() - self._last_screenshot_time

    def capture_screenshot_b64(self, force: bool = False,
                               background: bool = False) -> str:
        """Capture screenshot and return as base64. Cached ~1s unless force=True."""
        now = time.time()
        with self._screenshot_lock:
            if (
                not force
                and (now - self._last_screenshot_time) < 1.0
                and self._last_screenshot_b64
            ):
                return self._last_screenshot_b64

        if not self._adb:
            return ""
        try:
            png = b""
            # Single round trip; `screencap -p` + `pull` costs 2 ADB calls + disk I/O
            try:
                raw = self._adb.run_binary(["exec-out", "screencap", "-p"], timeout=20,
                                           background=background)
                if raw[:8] == b"\x89PNG\r\n\x1a\n":
                    png = raw
                elif raw:
                    # Some shells still translate LF -> CRLF on exec-out
                    fixed = raw.replace(b"\r\n", b"\n")
                    if fixed[:8] == b"\x89PNG\r\n\x1a\n":
                        png = fixed
            except Exception:
                png = b""

            if not png:
                self._adb.run(["shell", "screencap", "-p", "/sdcard/screenshot.png"],
                              background=background)
                self._adb.run(["pull", "/sdcard/screenshot.png", self._screenshot_path],
                              background=background)
                with open(self._screenshot_path, "rb") as f:
                    png = f.read()

            b64 = base64.b64encode(png).decode("utf-8")
            with self._screenshot_lock:
                self._last_screenshot_b64 = b64
                self._last_screenshot_time = time.time()
            return b64
        except Exception:
            return ""

    def ingest_ui_elements(self, elements: list) -> None:
        """
        Merge accessibility-tree labels into the live index (cheap, every UI dump).
        This is what makes 'spiderman' / pin titles instantly tappable without a
        fresh vision API call.
        """
        items: List[Dict] = []
        for e in elements or []:
            text = (getattr(e, "text", None) or "").strip()
            desc = (getattr(e, "content_desc", None) or "").strip()
            label = text or desc
            if not label or len(label) < 2:
                continue
            # Skip pure chrome noise
            low = label.lower()
            if low in {"for you", "home", "search", "back", "ok", "cancel"}:
                continue
            try:
                x, y = e.center
            except Exception:
                continue
            w = e.bounds[2] - e.bounds[0]
            h = e.bounds[3] - e.bounds[1]
            if w < 20 or h < 20:
                continue
            items.append({
                "label": label,
                "type": "ui",
                "x": int(x),
                "y": int(y),
                "source": "ui",
                "aliases": self._aliases_for(label),
            })
        with self._map_lock:
            self._ui_index = items
            self._last_ui_index_time = time.time()
            # Keep a human summary available for "what do you see"
            vision_labels = [i["label"] for i in self._screen_map[:6]]
            ui_labels = [i["label"][:60] for i in items[:8]]
            parts = []
            if vision_labels:
                parts.append("Vision: " + "; ".join(vision_labels))
            if ui_labels:
                parts.append("UI: " + "; ".join(ui_labels))
            if parts:
                self._last_description = " | ".join(parts)
                self._last_description_time = time.time()

    @staticmethod
    def _aliases_for(label: str) -> List[str]:
        """Generate fuzzy aliases (spiderman/spider-man, budha/buddha)."""
        low = label.lower()
        aliases = {low}
        compact = low.replace("-", " ").replace("_", " ")
        aliases.add(compact)
        aliases.add(compact.replace(" ", ""))
        # Common OCR / speech typos
        replacements = {
            "spider-man": "spiderman",
            "spiderman": "spider man",
            "buddha": "budha",
            "budha": "buddha",
            "lego": "lego",
        }
        for a, b in replacements.items():
            if a in compact:
                aliases.add(compact.replace(a, b))
        return list(aliases)

    def _refresh_screen_map(self, signature: str = "") -> None:
        """Ask vision to inventory the screen; store labels + coords for instant taps."""
        if self._map_busy or self._paused or not self.available or not self.client:
            return
        if time.time() < self._rate_limited_until:
            return
        b64 = self.capture_screenshot_b64()
        if not b64:
            self._last_map_error = "no screenshot"
            return
        self._last_map_signature = signature or self.screenshot_signature()

        self._map_busy = True
        try:
            prompt = (
                "You are indexing a mobile screenshot for voice commands.\n"
                "List up to 14 tappable content items the user might name "
                "(people, characters, animals, products, pins, posts, buttons).\n"
                "Include alternate names (e.g. spiderman, spider-man, lego spiderman).\n"
                "Return ONLY valid JSON, no thinking, no markdown:\n"
                '{"items":[{"label":"lego spiderman","aliases":["spiderman","spider man"],'
                '"type":"pin","x_pct":35,"y_pct":40},{"label":"buddha pixel art",'
                '"aliases":["budha","buddha"],"type":"pin","x_pct":70,"y_pct":35}]}\n'
            )
            result = self.analyze_image(
                b64, prompt, temperature=0.0, is_b64=True, max_tokens=700
            )
            raw = self._strip_model_noise(result.description)
            if self._is_rate_limit_text(result.description) or self._is_rate_limit_text(raw):
                self._note_rate_limit(result.description or raw)
                with self._map_lock:
                    self._last_map_time = time.time()
                    self._map_refresh_count += 1
                return

            items: List[Dict] = []
            try:
                data = json.loads(raw)
                for it in data.get("items", []) or []:
                    label = str(it.get("label") or "").strip()
                    if not label:
                        continue
                    x, y = self._pct_to_xy(it.get("x_pct", 50), it.get("y_pct", 50))
                    aliases = it.get("aliases") or []
                    if isinstance(aliases, str):
                        aliases = [aliases]
                    aliases = [str(a).lower() for a in aliases] + self._aliases_for(label)
                    items.append({
                        "label": label,
                        "type": str(it.get("type") or "item"),
                        "x": x,
                        "y": y,
                        "source": "vision",
                        "aliases": list(set(aliases)),
                    })
            except Exception as e:
                self._last_map_error = f"json parse: {e}; raw={raw[:80]!r}"
                items = []

            with self._map_lock:
                # Keep previous map on empty parse (don't wipe a good index)
                if items:
                    self._screen_map = items
                    self._last_description = "On screen: " + "; ".join(
                        i["label"] for i in items[:10]
                    )
                    self._last_description_time = time.time()
                    self._last_map_error = ""
                    self._rate_limit_notified = False
                self._last_map_time = time.time()
                self._map_refresh_count += 1

            if items:
                # Runs on the watcher thread: re-printing the prompt here used
                # to splice into whatever the user was typing.
                CONSOLE.status(f"  🗺️ Screen map updated ({len(items)} items)")
        finally:
            self._map_busy = False

    def combined_index(self) -> List[Dict]:
        """UI index + vision map (vision preferred when labels overlap)."""
        with self._map_lock:
            ui = list(self._ui_index)
            vis = list(self._screen_map)
            ui_age = time.time() - self._last_ui_index_time
            vis_age = time.time() - self._last_map_time
        # Drop stale layers
        if ui_age > 12:
            ui = []
        if vis_age > 12:
            vis = []
        return vis + ui

    def find_in_screen_map(self, description: str) -> VisionResult:
        """Instant match against live UI+vision index (no new API call)."""
        q = (description or "").lower().strip()
        if not q:
            return VisionResult(description="empty query", confidence=0.0)

        stop = {
            "the", "a", "an", "on", "to", "of", "post", "pin", "item", "card",
            "picture", "photo", "image", "click", "tap", "please", "can", "you",
            "video", "channel",
        }
        q_norm = q.replace("'", " ").replace("’", " ").replace("-", " ")
        q_tokens = {t for t in q_norm.split() if t not in stop and len(t) > 2}
        q_compact = q_norm.replace(" ", "")
        # speech typos
        typo = {"budha": "buddha", "spiderman": "spider man"}
        for a, b in typo.items():
            if a in q_norm:
                q_tokens |= set(b.split())

        # Query word → labels that CONTAIN the query but are the wrong control
        # e.g. "subscribe" must not match "17.3K subscribers"
        false_friends = {
            "subscribe": ("subscribers", "subscriber", "subscribed to"),
            "like": ("liked", "likes", "likely"),
            "follow": ("followers", "following"),
            "share": ("shared", "shares"),
        }

        items = self.combined_index()
        if not items:
            return VisionResult(description="screen map empty/stale", confidence=0.0)

        best = None
        best_score = 0.0
        for it in items:
            label = (it.get("label") or "").lower().strip()
            aliases = [a.lower() for a in (it.get("aliases") or [])] + [label]
            blob = " ".join(aliases)
            blob_compact = blob.replace("-", " ").replace(" ", "")

            # Reject false friends (subscribe ≠ subscribers count)
            rejected = False
            for tok in q_tokens:
                friends = false_friends.get(tok, ())
                if friends and any(f in blob for f in friends):
                    # Allow only if an alias is exactly the action word
                    if not any(a.strip() == tok for a in aliases):
                        rejected = True
                        break
            if rejected:
                continue

            score = 0.0
            for tok in q_tokens:
                # Exact whole-label / whole-alias match wins hard
                if any(a.strip() == tok for a in aliases):
                    score += 10
                elif any(_word_eq(a, tok) for a in aliases):
                    score += 8
                elif tok in blob or tok in blob_compact:
                    score += 3
                elif any(a.startswith(tok) or tok.startswith(a[:4]) for a in aliases if len(a) > 3):
                    score += 1.5
            if q_compact and q_compact == blob_compact:
                score += 6
            elif q_compact and q_compact in blob_compact:
                score += 2
            if it.get("source") == "vision":
                score += 0.3
            if score > best_score:
                best_score = score
                best = it

        if not best or best_score < 2.5:
            return VisionResult(description="no map match", confidence=0.0)

        return VisionResult(
            description=f"live:{best.get('source')}:{best.get('label')}",
            coordinates=(int(best["x"]), int(best["y"])),
            confidence=min(0.98, 0.6 + 0.08 * best_score),
        )

    def cached_screen_summary(self) -> str:
        """Return last understood screen summary (no new API call if fresh)."""
        with self._map_lock:
            desc = self._last_description
            age = time.time() - self._last_description_time
            n = len(self._screen_map) + len(self._ui_index)
        if desc and age < 15:
            return f"{desc}\n(live index: {n} items, age {age:.1f}s)"
        return ""
    
    # =========================================================
    # CORE VISION (Gemini — Groq not used for images)
    # =========================================================
    def analyze_image(self, image_path_or_b64: str, prompt: str,
                      temperature: float = 0.1, is_b64: bool = False,
                      max_tokens: int = 500,
                      disable_thinking: bool = True) -> VisionResult:
        if not self.available or not self.client:
            return VisionResult(description="Vision not available", confidence=0.0)

        try:
            if is_b64:
                image_data = image_path_or_b64
            else:
                with open(image_path_or_b64, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            return VisionResult(description=f"Error: {e}", confidence=0.0)

        image_data, mime = compress_for_vision(image_data)
        contents = [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime, "data": image_data}},
            ],
        }]
        last_err: Optional[Exception] = None
        for model in model_candidates(self.model):
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=contents,
                )
                if model != self.model:
                    CONSOLE.status(f"   ↻ Gemini vision switched to {model}")
                    self.model = model
                content = (getattr(response, "text", None) or "").strip()
                if not content:
                    try:
                        parts = response.candidates[0].content.parts
                        content = "".join(getattr(p, "text", "") or "" for p in parts).strip()
                    except Exception:
                        content = ""
                if "<think>" in content.lower() or "<thinking>" in content.lower() or "```" in content:
                    prefer_json = "{" in content and "}" in content
                    content = self._strip_model_noise(content, prefer_json=prefer_json)
                return VisionResult(description=content, confidence=0.85)
            except Exception as e:
                last_err = e
                if is_transient_model_error(e):
                    continue
                break

        err = str(last_err or "unknown")
        if self._is_rate_limit_text(err):
            self._note_rate_limit(err, backoff_s=45.0)
        return VisionResult(description=f"Error: {err}", confidence=0.0)

    def _pct_to_xy(self, x_pct, y_pct) -> Tuple[int, int]:
        """
        Convert model-reported coordinates to screen pixels.

        Models sometimes ignore the 0-100 percentage contract and answer on the
        0-1000 normalized grid instead, which previously produced taps far off
        screen (e.g. x_pct=597 became x=11462 on a 1920px display).
        """
        def axis(value, extent: int) -> int:
            v = float(value)
            if v <= 100.0:
                frac = v / 100.0
            elif v <= 1000.0:
                frac = v / 1000.0
            else:
                frac = v / float(extent) if extent else 0.5
            return int(max(0.0, min(1.0, frac)) * extent)

        return axis(x_pct, self.screen_width), axis(y_pct, self.screen_height)

    def find_element(self, image_path_or_b64: str, description: str,
                     is_b64: bool = False) -> VisionResult:
        """Find element by text OR visual appearance using Gemini Vision."""
        prompt = f"""Locate "{description}" on this mobile screen for tapping.
x_pct and y_pct are PERCENTAGES from 0 to 100 of the image width/height.
Never return pixel coordinates.
Return ONLY JSON (no thinking, no markdown):
{{"found": true, "x_pct": 50, "y_pct": 45, "element_type": "photo", "description": "short label"}}
or {{"found": false, "reason": "not visible"}}"""

        result = self.analyze_image(image_path_or_b64, prompt, 0.1, is_b64, max_tokens=250)
        raw = self._strip_model_noise(result.description)
        
        try:
            data = json.loads(raw)
            if data.get('found'):
                x_pct = data.get('x_pct')
                y_pct = data.get('y_pct')
                if x_pct is not None and y_pct is not None:
                    x, y = self._pct_to_xy(x_pct, y_pct)
                else:
                    x = int(data.get('x', self.screen_width // 2))
                    y = int(data.get('y', self.screen_height // 2))
                
                return VisionResult(
                    description=f"{data.get('element_type', 'element')}: {data.get('description', description)}",
                    coordinates=(x, y),
                    confidence=0.85
                )
        except Exception:
            coords = self._extract_coords(result.description)
            if coords:
                return VisionResult(description=description, coordinates=coords, confidence=0.6)
        
        return VisionResult(description=result.description, confidence=0.2)
    
    def find_element_fast(self, description: str) -> VisionResult:
        """Prefer live screen index; only call vision API if index misses."""
        mapped = self.find_in_screen_map(description)
        if mapped.coordinates and mapped.confidence >= 0.55:
            return mapped

        b64 = self.capture_screenshot_b64()
        if not b64:
            return VisionResult(description="No screenshot available", confidence=0.0)
        return self.find_element(b64, description, is_b64=True)
    
    def describe_screen(self, image_path: str = None, detailed: bool = False) -> VisionResult:
        if not self.available:
            return VisionResult(description="Vision not available", confidence=0.0)
        
        # Enhanced prompt to describe icons, buttons, AND text
        prompt = """Describe this mobile screen:
- App name or what it shows
- Main visual elements (icons, buttons, badges, images)
- Text labels and their locations
- Available actions (what can be tapped?)
Under 100 words."""
        
        if detailed:
            prompt = """Detailed screen description:
- App/content type
- Layout (top/middle/bottom sections)
- Icons with descriptions (subscribe, share, menu, settings, etc.)
- Text, labels, buttons
- Colors and visual state
- Interactive elements location"""
        
        if image_path:
            return self.analyze_image(image_path, prompt, 0.3)
        
        b64 = self.capture_screenshot_b64()
        if b64:
            return self.analyze_image(b64, prompt, 0.3, is_b64=True)
        return VisionResult(description="No screenshot", confidence=0.0)
    
    def describe_screen_fast(self) -> str:
        """Prefer live index summary; only call vision if stale/empty."""
        cached = self.cached_screen_summary()
        if cached:
            # Return the human summary line without the meta footer for speech
            return cached.split("\n(live index:")[0].strip()
        if self._last_description and (time.time() - self._last_description_time) < 5.0:
            return self._strip_model_noise(self._last_description, prefer_json=False) or self._last_description
        result = self.describe_screen()
        desc = self._strip_model_noise(result.description, prefer_json=False) or result.description
        self._last_description = desc
        self._last_description_time = time.time()
        return desc
    
    def answer_question(self, image_path: str, question: str) -> VisionResult:
        prompt = f"Question about this mobile screen: {question}\nAnswer concisely."
        return self.analyze_image(image_path, prompt, 0.2)
    
    def find_icon_by_appearance(self, description: str) -> VisionResult:
        """
        Find element by visual appearance (icon, color, button type).
        Better for non-text UI elements like colored garments, buttons, badges, etc.
        """
        b64 = self.capture_screenshot_b64()
        if not b64:
            return VisionResult(description="No screenshot available", confidence=0.0)
        
        prompt = f"""Find "{description}" on this mobile screen.

Instructions:
1. Locate the visual object matching "{description}" (colored item, clothing, icon, photo, badge).
2. Estimate the center location as percentage coordinates:
   - x_pct: 0 (left edge) to 100 (right edge)
   - y_pct: 0 (top edge) to 100 (bottom edge)

Return ONLY valid JSON:
{{"found": true, "x_pct": 50, "y_pct": 45, "element_type": "photo/garment/icon", "visual_description": "green shirt"}}
If not visible, return ONLY JSON: {{"found": false}}"""
        
        result = self.analyze_image(b64, prompt, 0.1, is_b64=True, max_tokens=250)
        raw = self._strip_model_noise(result.description)
        try:
            data = json.loads(raw)
            if data.get('found'):
                x_pct = data.get('x_pct')
                y_pct = data.get('y_pct')
                if x_pct is not None and y_pct is not None:
                    x, y = self._pct_to_xy(x_pct, y_pct)
                else:
                    x = int(data.get('x', self.screen_width // 2))
                    y = int(data.get('y', self.screen_height // 2))
                return VisionResult(
                    description=f"{data.get('element_type', 'element')}: {data.get('visual_description', description)}",
                    coordinates=(x, y),
                    confidence=0.85
                )
        except Exception:
            pass
        
        # Fallback to coordinate extraction if JSON fails
        coords = self._extract_coords(raw or result.description)
        if coords:
            return VisionResult(description=description, coordinates=coords, confidence=0.5)

        return VisionResult(description=result.description, confidence=0.2)
    
    def find_nth_item(self, image_path: str, item_type: str, position: int) -> VisionResult:
        ords = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
        return self.find_element(image_path, f"the {ords.get(position, f'{position}th')} {item_type}")
    
    # =========================================================
    # Utilities
    # =========================================================
    def _extract_coords(self, text: str) -> Optional[Tuple[int, int]]:
        import re
        patterns = [
            r'coordinates?\s*\(?\s*(\d+)\s*,\s*(\d+)',
            r'"x"\s*:\s*(\d+).*?"y"\s*:\s*(\d+)',
            r'x\s*[:=]\s*(\d+).*?y\s*[:=]\s*(\d+)',
            r'\((\d+)\s*,\s*(\d+)\)',
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE | re.DOTALL)
            if m:
                x, y = int(m.group(1)), int(m.group(2))
                if 0 <= x <= self.screen_width and 0 <= y <= self.screen_height:
                    return (x, y)
        return None
    
    def validate_coordinates(self, x: int, y: int) -> bool:
        return 0 <= x <= self.screen_width and 0 <= y <= self.screen_height


GroqVision = OllamaVision  # legacy alias
GeminiVision = OllamaVision
