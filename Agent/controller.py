# =========================
# FILE: agent/controller.py
# =========================
"""
Controller v7 — Parallel processing pipeline.

Changes from v6:
  - Integrated parallel processing pipeline (agent/parallel.py)
  - Overlaps Groq LLM/Vision API calls with ADB screen captures
  - Action-aware speculative pre-fetch (only for screen-needing commands)
  - ADB calls serialized via threading.Lock for Windows safety
"""

import re
import sys
import time
import urllib.parse
from typing import Optional, Tuple
from agent.adb import AdbClient
from agent.console import CONSOLE
from agent.schema import Command
from agent.screen_inspector import ScreenInspector

# Commands that DON'T need current app context
# These skip _get_current_app() entirely → instant
NO_CONTEXT_ACTIONS = {
    "EXIT", "WAKE", "BACK", "HOME", "CLOSE_ALL", "CLOSE_APP", "TAP", "TYPE_TEXT",
    "SCROLL", "REINDEX_APPS", "FIND_APP", "KEYEVENT",
    "VOLUME_UP", "VOLUME_DOWN", "VOLUME_MUTE", "VOLUME_UNMUTE", "VOLUME_MAX",
    "TEACH_LAST", "TEACH_CUSTOM", "TEACH_SHORTCUT", "FORGET_MAPPING", "LIST_MAPPINGS",
    "DEVICE_FEATURE",  # Device controls don't need app context
}

# Keywords that trigger device feature commands (avoid bare "screen" —
# it steals "what do you see on screen?" into the device mapper).
DEVICE_KEYWORDS = {
    "enable", "disable", "turn on", "turn off", "toggle",
    "wifi", "bluetooth", "torch", "flashlight",
    "brightness", "vibration", "location", "airplane",
    "dnd", "do not disturb", "battery saver", "battery",
    "nfc", "mobile data", "hotspot", "flash",
    "device status", "available features",
    "screen brightness", "screen timeout", "auto rotate",
    "auto-rotate", "do not disturb",
    # Absolute volume/sound ("set the volume to 50") must hit DeviceCommandMapper
    "volume", "sound",
}

# Phrases that are clearly screen/vision questions, not device toggles
SCREEN_INFO_CUES = (
    "what do you see", "what's on screen", "whats on screen",
    "what is on screen", "describe screen", "describe the screen",
    "describe what", "read the screen", "on the screen",
    "what's on the screen", "what can you see",
)


def _safe_input(prompt: str) -> str:
    """
    Safe input handler for Windows PowerShell / Cursor terminal compatibility.

    Background threads are muted for the duration: a write landing mid-line
    corrupts the console's edit buffer, so the half-typed text got spliced onto
    the next command instead of being replaced.
    """
    CONSOLE.begin_prompt()
    try:
        return input(prompt).strip()
    except EOFError:
        # Piped stdin (non-interactive) → exit cleanly.
        # Interactive TTY sometimes raises EOFError spuriously (Cursor/PS glitches,
        # accidental Ctrl+Z) — ignore and keep the agent running.
        if sys.stdin is not None and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
            return ""
        return "__EOF__"
    except KeyboardInterrupt:
        raise
    finally:
        CONSOLE.end_prompt()


def _is_device_command(query: str) -> bool:
    """True only for real device toggles — not screen-description questions."""
    query_lower = query.lower().strip()
    if any(cue in query_lower for cue in SCREEN_INFO_CUES):
        return False
    if query_lower.endswith("?") and "screen" in query_lower and any(
        w in query_lower for w in ("see", "what", "describe", "show", "read")
    ):
        return False
    return any(keyword in query_lower for keyword in DEVICE_KEYWORDS)


def _get_current_app(adb: AdbClient) -> str:
    try:
        out = adb.run(["shell", "dumpsys", "activity", "activities", "|", "grep", "mResumedActivity"])
        m = re.search(r'u0\s+(\S+)/', out)
        if m:
            return m.group(1)
        m = re.search(r'(\S+)/\S+\s+\w+\}', out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _find_scrollable_bounds(screen, vertical: bool = True):
    """Find the best scroll target from the ALREADY-cached UI tree.

    IMPORTANT: this must NOT trigger a UI capture. `uiautomator dump` takes
    ~1-2s, and scrolling needs to stay in the millisecond range. If no tree is
    cached we return None and the caller falls back to a fast center-screen
    swipe (which is rotation-aware and works in both orientations).

    For up/down scrolling, prefer tall (vertical) containers — in portrait the
    largest scrollable area is often a horizontal strip whose swipe wouldn't
    move the main feed.
    """
    if not screen.ui_analyzer.last_elements:
        return None

    def score_bounds(bounds: Tuple[int, int, int, int]) -> int:
        bw = bounds[2] - bounds[0]
        bh = bounds[3] - bounds[1]
        if bw <= 50 or bh <= 50:
            return 0
        area = bw * bh
        if vertical:
            if bh < bw:
                area //= 4
            elif bh < 200:
                area //= 2
        elif bw < bh:
            area //= 4
        return area

    best = None
    best_area = 0
    for elem in screen.ui_analyzer.last_elements:
        if elem.scrollable:
            area = score_bounds(elem.bounds)
            if area > best_area:
                best_area = area
                best = elem.bounds
    if best:
        return best

    for elem in screen.ui_analyzer.last_elements:
        cls = elem.class_name.lower()
        if any(s in cls for s in ["recyclerview", "listview", "scrollview", "nestedscrollview"]):
            bw = elem.bounds[2] - elem.bounds[0]
            bh = elem.bounds[3] - elem.bounds[1]
            if bw > 100 and bh > 200:
                area = score_bounds(elem.bounds)
                if area > best_area:
                    best_area = area
                    best = elem.bounds
    return best


def run_cli() -> None:
    # Imported late: agent.runtime imports this module for the shared dispatch
    # helpers, so a module-level import here would be circular.
    from agent.runtime import AgentRuntime

    runtime = AgentRuntime(llm_model="openai/gpt-oss-20b")
    runtime.start()
    runtime.print_help()

    while True:
        try:
            utter = _safe_input("> ")

            if utter == "__EOF__":
                runtime.shutdown()
                print("Stopping (stdin closed).")
                break

            if not utter:
                continue

            if runtime.handle(utter) == "exit":
                runtime.shutdown()
                print("Stopping.")
                break

        except KeyboardInterrupt:
            runtime.shutdown()
            print("\nStopping.")
            break


def _needs_app_context(t: str) -> bool:
    """Quick check: does this command need to know current app?"""
    # These commands need context for proper routing
    if any(t.startswith(p) for p in ["open ", "send ", "play", "pause", "stop", "resume",
                                      "next", "skip", "previous", "search ", "find "]):
        return True
    if any(kw in t for kw in ["what do you see", "describe screen"]):
        return True
    return False


def execute_command(cmd, device, apps, learner, screen, adb, current_app="", engine=None):  # ← engine added
    # === INSTANT commands (no ADB overhead) ===
    if cmd.action == "WAKE":
        device.wake(); return
    if cmd.action == "HOME":
        device.home(); return
    if cmd.action == "BACK":
        device.back(); return
    if cmd.action == "CLOSE_ALL":
        device.close_all_apps(); return
    if cmd.action == "CLOSE_APP":                      # ← NEW
        device.back(); print("✅ Closed app"); return
    if cmd.action == "TAP":
        if cmd.x is not None and cmd.y is not None:
            device.tap_exact(cmd.x, cmd.y)
        return
    if cmd.action == "TYPE_TEXT":
        device.type_text(cmd.text or ""); return
    if cmd.action == "KEYEVENT":
        if cmd.query:
            adb.run(["shell", "input", "keyevent", cmd.query])
        return

    # === Volume (instant) ===
    if cmd.action == "VOLUME_UP":
        device.volume_up(cmd.amount if cmd.amount > 1 else 2); return
    if cmd.action == "VOLUME_DOWN":
        device.volume_down(cmd.amount if cmd.amount > 1 else 2); return
    if cmd.action == "VOLUME_MAX":
        device.volume_max(); return
    if cmd.action == "VOLUME_MIN":
        device.volume_min(); return
    if cmd.action == "VOLUME_MUTE":                    # ← NEW
        adb.run(["shell", "input", "keyevent", "KEYCODE_VOLUME_MUTE"]); return
    if cmd.action == "VOLUME_UNMUTE":                  # ← NEW
        adb.run(["shell", "input", "keyevent", "KEYCODE_VOLUME_MUTE"]); return
    if cmd.action == "VOLUME_SET":
        # amount is 0–100 percent from NLU / device-mapper fallback
        pct = max(0, min(100, int(cmd.amount or 0)))
        try:
            from agent.device_features import DeviceFeatureController
            feats = DeviceFeatureController(adb)
            ok = feats.volume_set_percent(pct)
            cur = feats.volume_get()
            mx = feats.volume_max_index()
            if ok:
                print(f"✅ Volume set to {pct}% ({cur}/{mx})")
            else:
                print("❌ Failed to set volume")
        except Exception as e:
            print(f"❌ Failed to set volume: {e}")
        return

    # === Brightness (instant) ===
    if cmd.action == "BRIGHTNESS_UP":
        device.brightness_up(); print("✅ Brightness up"); return
    if cmd.action == "BRIGHTNESS_DOWN":
        device.brightness_down(); print("✅ Brightness down"); return

    # === Screenshot ===
    if cmd.action == "SCREENSHOT":
        try:
            path = device.screenshot()
            print(f"✅ Screenshot saved: {path}")
        except Exception as e:
            print(f"⚠️ Screenshot failed: {e}")
        return

    # === Media (instant) ===
    if cmd.action == "MEDIA_PLAY":
        device.media_play(); return
    if cmd.action == "MEDIA_PAUSE":
        device.media_pause(); return
    if cmd.action == "MEDIA_PLAY_PAUSE":
        device.media_play_pause(); return
    if cmd.action == "MEDIA_NEXT":
        device.media_next(); return
    if cmd.action == "MEDIA_PREVIOUS":
        device.media_previous(); return
    if cmd.action == "SKIP_AD":
        _do_skip_ad(screen); return

    # === Scroll (fast — one ADB swipe) ===
    if cmd.action == "SCROLL":
        d = cmd.direction or "DOWN"
        amt = max(1, min(cmd.amount, 10))
        # Refresh the effective display size ONCE at the start (~150ms dumpsys
        # display, then cached). This catches app-forced orientation (e.g. a
        # landscape-locked video app on a portrait tablet). Do NOT capture a UI
        # tree here — that costs ~1-2s per scroll.
        try:
            device.screen_size(force_refresh=True)
        except Exception:
            pass
        if d in ("LEFT", "RIGHT"):
            for _ in range(amt):
                device.scroll_horizontal(d)
        else:
            # Only use scrollable bounds if a tree is already cached; never
            # trigger a capture just to scroll.
            bounds = _find_scrollable_bounds(screen, vertical=True)
            for _ in range(amt):
                device.scroll_once(d, scroll_bounds=bounds)
        screen.ui_analyzer.last_tree = None
        screen.ui_analyzer.last_elements = []
        return

    # === Swipe (shorter, faster gesture) ===
    if cmd.action == "SWIPE":
        d = cmd.direction or "DOWN"
        amt = max(1, min(cmd.amount, 5))
        try:
            w, h = device.screen_size()
            cx, cy = w // 2, h // 2
            dist = min(w, h) // 3  # shorter than scroll
            for _ in range(amt):
                if d == "UP":
                    device.swipe(cx, cy, cx, cy - dist, 200)
                elif d == "DOWN":
                    device.swipe(cx, cy, cx, cy + dist, 200)
                elif d == "LEFT":
                    device.swipe(cx, cy, cx - dist, cy, 200)
                elif d == "RIGHT":
                    device.swipe(cx, cy, cx + dist, cy, 200)
        except Exception:
            pass
        screen.ui_analyzer.last_tree = None
        screen.ui_analyzer.last_elements = []
        return

    # === Multi-step: execute each step sequentially ===
    if cmd.action == "MULTI_STEP":
        steps = (cmd.query or "").split("|")
        print(f"📋 Multi-step: {len(steps)} commands")
        for i, step in enumerate(steps):
            step = step.strip()
            if not step:
                continue
            print(f"\n  Step {i+1}: {step}")
            if engine:
                sub_cmd = engine.understand(step, current_app=current_app)
            else:
                sub_cmd = None
            if sub_cmd and sub_cmd.action != "EXIT":
                execute_command(sub_cmd, device, apps, learner, screen, adb, current_app, engine)
                import time as _t
                # Wait longer after app launch — app needs time to fully load UI
                if sub_cmd.action == "OPEN_APP":
                    _t.sleep(2.0)
                else:
                    _t.sleep(0.5)
                current_app = _get_current_app(adb)
        return

    # === Learning (instant, no ADB) ===
    if cmd.action == "TEACH_LAST":
        apps.teach_last(); return
    if cmd.action == "TEACH_CUSTOM":
        if cmd.query and cmd.text: apps.teach_custom(cmd.query, cmd.text)
        return
    if cmd.action == "TEACH_SHORTCUT":
        if cmd.query and apps.last_choice:
            learner.teach(cmd.query, apps.last_choice[1], apps.last_choice[2])
        return
    if cmd.action == "FORGET_MAPPING":
        if cmd.query: learner.forget(cmd.query)
        return
    if cmd.action == "LIST_MAPPINGS":
        learner.list_mappings(); return

    # === App management ===
    if cmd.action == "REINDEX_APPS":
        stats = apps.full_reindex()
        print(f"✅ {stats['total']} apps, {stats['time_ms']}ms"); return
    if cmd.action == "FIND_APP":
        cands = apps.candidates(cmd.query or "", limit=10)
        for i, (s, l, p) in enumerate(cands, 1):
            print(f"  {i}. {l} ({p}) {s:.2f}")
        return
    if cmd.action == "OPEN_APP":
        pkg = apps.resolve_or_ask(cmd.query or "")
        if pkg:
            device.launch(pkg)
            screen.ui_analyzer.last_tree = None
            screen.ui_analyzer.last_elements = []
            screen.ui_analyzer._cached_elements = []
            screen._prefetch_fresh = False
        return

    # === Vision queries ===
    if cmd.action == "SCREEN_INFO":
        intent = screen.router.parse_query(cmd.query or "what do you see?")
        screen._execute_info(intent); return
    if cmd.action == "VISION_QUERY":
        if cmd.query: screen.execute_query(cmd.query)
        return
    if cmd.action == "TAKE_PHOTO":
        _do_take_photo(device, apps, screen)
        return
    if cmd.action == "FIND_VISUAL":
        if cmd.query: screen.find_and_tap(cmd.query)
        return

    # === Workflows ===
    if cmd.action == "SEND_MESSAGE":
        _do_send(cmd, device, apps, screen, adb); return
    if cmd.action == "TYPE_AND_SEND":
        _do_type_send(cmd, device, screen, adb); return
    if cmd.action == "TAP_SEND":
        screen._maybe_capture()
        if _tap_send(screen, device):
            print("✅ Sent!")
        else:
            adb.run(["shell", "input", "keyevent", "KEYCODE_ENTER"])
            print("✅ Sent (Enter)")
        return
    if cmd.action == "TYPE_AND_ENTER":
        if cmd.text:
            device.type_text(cmd.text)
            time.sleep(0.2)
            adb.run(["shell", "input", "keyevent", "KEYCODE_ENTER"])
        return
    if cmd.action == "SEARCH_IN_APP":
        _do_search(cmd, device, apps, screen, adb); return
    if cmd.action == "INSTALL_APP":
        _do_install_app(cmd, device, apps, screen, adb); return
    if cmd.action == "OPEN_CONTENT_IN_APP":
        _do_open_content(cmd, device, apps, screen); return
    if cmd.action == "APP_ACTION":
        _do_app_action(cmd, device, screen, adb); return


# ===========================================================
# WORKFLOWS — each does at most 1-2 UI tree captures
# ===========================================================

def _do_send(cmd, device, apps, screen, adb):
    recipient, message = cmd.query or "", cmd.text or ""
    app_name = cmd.package or "whatsapp"
    if not recipient or not message:
        print("❌ send <msg> to <contact>"); return

    pkg = apps.resolve_or_ask(app_name, allow_learning=False)
    if not pkg: return
    device.launch(pkg)
    time.sleep(1.5)

    # ONE capture for contact search
    screen.ui_analyzer.capture_ui_tree(force_refresh=True)
    elements = screen.ui_analyzer.search(recipient)
    hits = [e for e in elements if e.text and recipient.lower() in e.text.lower()]

    target = hits[0] if hits else (elements[0] if elements else None)
    if not target:
        print(f"❌ Contact not found: {recipient}"); return
    
    name = target.text or target.content_desc
    if name and name.lower().strip() != recipient.lower().strip():
        c = input(f"🤔 '{name}'? (y/n): ").strip().lower()
        if c not in ("y", "yes"): return
    
    device.tap(*target.center)
    time.sleep(1.0)

    # ONE capture for chat screen
    screen.ui_analyzer.capture_ui_tree(force_refresh=True)
    inp = _find_input(screen)
    if inp: device.tap(*inp.center); time.sleep(0.3)
    device.type_text(message)
    time.sleep(0.3)
    
    # Refresh for send (typing changes UI)
    screen.ui_analyzer.capture_ui_tree(force_refresh=True)
    if _tap_send(screen, device):
        print(f"✅ Sent!")
    else:
        adb.run(["shell", "input", "keyevent", "KEYCODE_ENTER"])
        print(f"✅ Sent (Enter)")


def _do_type_send(cmd, device, screen, adb):
    message = cmd.text or ""
    if not message: return

    print(f"💬 Typing: {message}")
    screen.ui_analyzer.capture_ui_tree(force_refresh=True)
    inp = _find_input(screen)
    if inp:
        print(f"   Found input: {inp.class_name}")
        device.tap(*inp.center)
        time.sleep(0.3)
    else:
        print("   ⚠️ No input field found, tapping bottom of screen")
        try:
            w, h = device.screen_size()
            device.tap(w // 2, int(h * 0.92))
            time.sleep(0.3)
        except Exception:
            pass

    device.type_text(message)
    time.sleep(0.3)
    
    # Refresh tree for send button (typing may show/change send button)
    screen.ui_analyzer.capture_ui_tree(force_refresh=True)
    if _tap_send(screen, device):
        print(f"✅ Sent!")
    else:
        print("   ⚠️ No send button found, pressing Enter")
        adb.run(["shell", "input", "keyevent", "KEYCODE_ENTER"])
        print(f"✅ Sent (Enter)")


def _do_install_app(cmd, device, apps, screen, adb):
    """
    Install via Play Store market://search — skips home-screen search hunting.
    Tablet Play Store often shows the listing + Install in a split panel.
    """
    app_name = (cmd.query or "").strip()
    if not app_name:
        print("❌ install <app name>")
        return

    try:
        screen.vision.pause_watching()
    except Exception:
        pass

    try:
        print(f"📦 Installing '{app_name}' from Play Store…")
        q = urllib.parse.quote(app_name)
        # Direct search intent — more reliable than tapping the home Search rail
        adb.run([
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", f"market://search?q={q}&c=apps",
        ])
        time.sleep(2.0)
        screen.ui_analyzer.last_tree = None
        screen._prefetch_fresh = False

        target = app_name.lower().strip()
        opened_listing = False

        for attempt in range(5):
            if attempt:
                time.sleep(0.7)
            screen.ui_analyzer.capture_ui_tree(force_refresh=True)
            elements = screen.ui_analyzer.last_elements or []
            if not elements:
                print(f"   ⏳ Waiting for Play Store… ({attempt + 1}/5)")
                continue

            # Prefer Install/Get already visible on the detail pane
            install_btn = _find_play_store_install_button(elements)
            if install_btn and (_play_listing_matches(elements, target) or opened_listing):
                btn_label = (install_btn.text or install_btn.content_desc or "Install").strip()
                low = btn_label.lower()
                if low == "open" or (low.startswith("open") and "install" not in low):
                    print(f"✅ '{app_name}' already installed (Open)")
                    return
                device.tap(*install_btn.center)
                print(f"✅ Tapped '{btn_label}' for {app_name}")
                _confirm_play_store_dialogs(screen, device)
                return

            # Open matching search result / listing title
            result = _find_play_store_listing(elements, target)
            if result:
                label = (result.text or result.content_desc or app_name).split("\n")[0][:60]
                print(f"   🎯 App result: {label}")
                device.tap(*result.center)
                opened_listing = True
                time.sleep(1.2)
                continue

            print(f"   ⏳ Waiting for '{app_name}' listing… ({attempt + 1}/5)")

        # Last resort: Gemini Computer Use / vision
        gemini = getattr(screen, "gemini", None)
        if gemini and getattr(gemini, "available", False):
            print("   ✨ Gemini → open listing and tap Install")
            g = gemini.run_goal(
                f"In Google Play Store, open the '{app_name}' app listing if needed, "
                f"then tap the Install or Get button once. Do not tap Open if already installed "
                f"unless Install is unavailable."
            )
            if g.ok:
                print(f"✅ Gemini install actions: {', '.join(g.actions) or 'done'}")
                return
            print(f"❌ Gemini install failed: {g.message}")
        elif screen.vision.available:
            hit = screen.vision.find_element_fast(f"the Install button for {app_name}")
            if hit.coordinates and hit.confidence > 0.4:
                device.tap(*hit.coordinates)
                print(f"✅ Tapped Install (vision) for {app_name}")
                return

        print(f"❌ Could not install '{app_name}' from Play Store")
    finally:
        try:
            screen.vision.resume_watching()
        except Exception:
            pass


def _play_listing_matches(elements, target: str) -> bool:
    """True if the current Play Store UI clearly shows the requested app."""
    for e in elements:
        blob = f"{e.text} {e.content_desc}".lower()
        if not blob.strip():
            continue
        first = blob.split("\n", 1)[0].strip()
        if first == target or target in first:
            return True
        if first.startswith(target + " ") or f"\n{target}\n" in f"\n{blob}\n":
            return True
    return False


def _find_play_store_listing(elements, target: str):
    """Pick the best search-result / title node for the app name."""
    candidates = []
    for e in elements:
        text = (e.text or "").strip()
        desc = (e.content_desc or "").strip()
        label = text or desc
        if not label:
            continue
        low = label.lower()
        first = low.split("\n", 1)[0].strip()
        # Skip chrome / actions
        if first in {"install", "get", "update", "open", "search", "sponsored"}:
            continue
        if any(k in low for k in ("voice search", "navigate up", "more options", "screenshot")):
            continue
        if target not in low and first not in target:
            continue
        score = 0
        if first == target or text.lower() == target:
            score += 40
        elif first.startswith(target):
            score += 30
        elif target in first:
            score += 20
        else:
            score += 10
        if e.clickable:
            score += 8
        if "TextView" in e.class_name and text.lower() == target:
            score += 12
        # Prefer larger result cards over tiny chips
        w = e.bounds[2] - e.bounds[0]
        h = e.bounds[3] - e.bounds[1]
        if w * h > 12000:
            score += 6
        # Left-rail labels are narrow — deprioritize
        if e.bounds[2] < 220:
            score -= 25
        candidates.append((score, e, label))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _find_play_store_install_button(elements):
    """
    Find Install/Get/Update. Play Store often exposes these as non-clickable
    TextViews that still receive taps.
    """
    preferred = ("install", "get", "update")
    best = None
    best_score = -1
    for e in elements:
        text = (e.text or "").strip()
        desc = (e.content_desc or "").strip()
        # Exact label wins; avoid "Install on more devices"
        for raw in (text, desc):
            low = raw.lower().strip()
            if not low:
                continue
            score = -1
            if low in preferred:
                score = 50 if low == "install" else 40
            elif low.split("\n", 1)[0].strip() in preferred:
                score = 35
            else:
                continue
            if e.clickable or "Button" in e.class_name:
                score += 5
            # Prefer the main CTA (not tiny / far-left)
            w = e.bounds[2] - e.bounds[0]
            if w > 80:
                score += 3
            if score > best_score:
                best_score = score
                best = e
    return best


def _confirm_play_store_dialogs(screen, device) -> None:
    time.sleep(1.0)
    try:
        screen.ui_analyzer.capture_ui_tree(force_refresh=True)
    except Exception:
        return
    for e in screen.ui_analyzer.last_elements or []:
        lab = (e.text or e.content_desc or "").strip().lower()
        if lab in {"accept", "ok", "continue", "install anyway", "update"} and (
            e.clickable or "Button" in e.class_name
        ):
            device.tap(*e.center)
            print(f"   ✓ Confirmed: {e.text or e.content_desc}")
            break


# Bare "sponsored" is not usable here: it also labels promoted items in the
# recommendations rail, which would make every skip request wait on a
# nonexistent ad. These strings only appear on the player itself.
_AD_MARKERS = (
    "visit advertiser", "stop ads", "why this ad",
    "video will play after ad", "ad will end",
)


def _ad_is_playing(screen) -> bool:
    """True when the player is showing an ad, not the requested video."""
    for elem in screen.ui_analyzer.last_elements or []:
        blob = f"{elem.text or ''} {elem.content_desc or ''}".lower()
        if any(marker in blob for marker in _AD_MARKERS):
            return True
    return False


def _do_skip_ad(screen) -> None:
    """
    Tap the on-screen "Skip ad" button.

    Deliberately never falls back to MEDIA_NEXT: that keyevent skips the whole
    video, which is what previously made "skip the ad" jump to the next video.
    """
    try:
        screen.vision.pause_watching()
    except Exception:
        pass

    try:
        # Reuse the pipeline's prefetched tree; forcing a dump here cost ~14s of
        # retries during playback just to discover there was no ad at all.
        screen._maybe_capture()
        hit = screen._find_chrome_button("skip ad")
        if hit:
            x, y, label = hit
            screen.device.tap(x, y)
            print(f"✅ Skipped ad ({label})")
            return

        if not _ad_is_playing(screen):
            print("ℹ️ No ad is playing — leaving the video alone")
            return

        # YouTube only enables Skip a few seconds into the ad.
        deadline = time.time() + 10.0
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            print(f"   ⏳ Ad playing — waiting for Skip button… ({attempt})")
            time.sleep(1.0)
            screen.ui_analyzer.capture_ui_tree(force_refresh=True)
            hit = screen._find_chrome_button("skip ad")
            if hit:
                x, y, label = hit
                screen.device.tap(x, y)
                print(f"✅ Skipped ad ({label})")
                return

        print("❌ This ad isn't skippable yet")
    finally:
        try:
            screen.vision.resume_watching()
        except Exception:
            pass


def _do_take_photo(device, apps, screen):
    """Press the camera shutter — cheap UI first, then Gemini, then guess."""
    try:
        screen.vision.pause_watching()
    except Exception:
        pass

    try:
        # Ensure we're in a camera app
        screen.ui_analyzer.capture_ui_tree(force_refresh=True)
        pkgs = [e.package for e in (screen.ui_analyzer.last_elements or []) if e.package]
        pkg = max(set(pkgs), key=pkgs.count) if pkgs else ""
        if "camera" not in pkg.lower():
            cam = apps.resolve_or_ask("camera", allow_learning=False)
            if cam:
                device.launch(cam)
                time.sleep(1.0)
                screen.ui_analyzer.capture_ui_tree(force_refresh=True)

        # Fast path: match shutter labels in the CURRENT UI tree (no vision race)
        shutter_cues = (
            "take pictures", "take picture", "take photo", "shutter",
            "capture", "camera shutter", "shoot",
        )
        for e in screen.ui_analyzer.last_elements or []:
            if not (e.clickable or "Button" in (e.class_name or "")):
                continue
            blob = f"{e.text or ''} {e.content_desc or ''} {e.resource_id or ''}".lower()
            if any(bad in blob for bad in ("switch", "front", "flash", "settings", "gallery", "mode")):
                continue
            if any(cue in blob for cue in shutter_cues):
                device.tap(*e.center)
                print(f"✅ Photo taken ({e.content_desc or e.text or e.resource_id})")
                return

        # Gemini Computer Use — one screenshot loop, not three vision races
        if getattr(screen, "gemini", None) and getattr(screen.gemini, "available", False):
            print("✨ Gemini → take photo")
            g = screen.gemini.take_photo()
            if g.ok:
                print(f"✅ Photo taken ({', '.join(g.actions) or 'shutter'})")
                return
            print(f"   ℹ️ Gemini photo miss: {g.message}")

        # Geometric fallback: landscape tablets often put shutter mid-right
        try:
            w, h = device.screen_size()
            if w > h:
                device.tap(int(w * 0.92), h // 2)
            else:
                device.tap(w // 2, int(h * 0.88))
            print("✅ Photo taken (shutter guess)")
            return
        except Exception:
            pass

        print("❌ Could not find shutter button")
    finally:
        try:
            screen.vision.resume_watching()
        except Exception:
            pass


def _do_search(cmd, device, apps, screen, adb):
    query = cmd.query or ""
    if not query:
        return

    # Pause background vision so ADB isn't contended during search
    try:
        screen.vision.pause_watching()
    except Exception:
        pass

    try:
        # Clean spurious or generic app targets
        target_app = (cmd.text or "").strip()
        if target_app:
            target_lower = target_app.lower()
            query_lower = query.lower()
            generic_terms = {
                "music", "video", "media", "song", "app", "application",
                "content", "something",
            }
            if target_lower in generic_terms or target_lower in query_lower:
                target_app = ""

        # Normalize google → chrome (omnibox search) when Chrome is the browser
        launch_name = target_app
        if target_app.lower() in {"google", "google search"}:
            # Prefer Google app if installed, else Chrome
            pkg_google = apps.resolve_or_ask("google", allow_learning=False)
            if pkg_google:
                launch_name = "google"
            else:
                launch_name = "chrome"

        if launch_name:
            pkg = apps.resolve_or_ask(launch_name, allow_learning=False)
            if pkg:
                device.launch(pkg)
                time.sleep(1.2)  # shorter than before — memory finds bar faster
                screen.ui_analyzer.last_tree = None
                screen._prefetch_fresh = False

        elem = None
        for attempt in range(3):
            if attempt:
                time.sleep(0.4)
            screen.ui_analyzer.capture_ui_tree(force_refresh=True)
            elem = _find_search(screen)
            if elem:
                break
            if attempt < 2:
                print(f"   ⏳ Waiting for search bar... ({attempt + 1}/3)")

        if elem:
            label = (elem.text or elem.content_desc or elem.resource_id or "").lower()
            # Reject camera / visual-search icons even if inspector slipped
            if any(bad in label for bad in (
                "camera", "visual search", "lens", "open camera", "photo search",
            )):
                print(f"   ⛔ Rejected non-text search target: '{label}'")
                elem = None

        if elem:
            device.tap(*elem.center)
            time.sleep(0.35)
            device.clear_text_field()
            time.sleep(0.2)
            device.type_text(query)
            time.sleep(0.2)
            adb.run(["shell", "input", "keyevent", "KEYCODE_ENTER"])
            print(f"✅ Searched: {query}")
        elif getattr(screen, "gemini", None) and getattr(screen.gemini, "available", False):
            print(f"✨ Gemini search → '{query}'")
            g = screen.gemini.search_on_screen(query)
            if g.ok:
                print(f"✅ Searched via Gemini: {query}")
            else:
                print(f"❌ Gemini search failed: {g.message}")
        else:
            print("❌ No search bar found")
    finally:
        try:
            screen.vision.resume_watching()
        except Exception:
            pass


def _find_search(screen):
    """
    Find the search / URL bar on the CURRENT screen.

    Live inspection wins over any stored knowledge: remembered hits replayed
    coordinates from a previous screen and tapped unrelated widgets.
    """
    elements = screen.ui_analyzer.last_elements
    if not elements:
        return None

    package = ""
    try:
        pkgs = [e.package for e in elements if e.package]
        package = max(set(pkgs), key=pkgs.count) if pkgs else ""
    except Exception:
        package = ""

    # 1) Live UI tree inspection
    search_target = ScreenInspector.find_search_target(elements)
    if search_target is not None:
        label = search_target.text or search_target.content_desc or search_target.resource_id
        print(f"   🔍 Search element: '{label}' at center={search_target.center}")
        return search_target

    # 2) Curated resource IDs for this package (stable identifiers, no coordinates)
    try:
        from agent.app_memory import APP_MEMORY
        hit = APP_MEMORY.resolve_search_bar_by_id(package, elements)
        if hit is not None:
            label = hit.text or hit.content_desc or hit.resource_id
            print(f"   🆔 Search element by resource id: '{label}' at center={hit.center}")
            return hit
    except Exception:
        pass

    return None


def _do_open_content(cmd, device, apps, screen):
    content = cmd.query or "video"
    app_name = cmd.text or ""
    pos = cmd.amount
    if not app_name:
        return

    pkg = apps.resolve_or_ask(app_name, allow_learning=False)
    if not pkg:
        return
    device.launch(pkg)
    time.sleep(2.0)

    items = screen._find_items_ui(content)
    if items:
        idx = pos - 1 if pos > 0 else pos
        if 0 <= idx < len(items):
            device.tap(*items[idx].center)
            print(f"✅ #{pos} {content}")
            return

    if screen.vision.available:
        r = screen.vision.find_element_fast(
            f"the {'first second third fourth fifth'.split()[pos-1] if 1<=pos<=5 else str(pos)+'th'} {content}"
        )
        if r.coordinates and r.confidence > 0.4:
            device.tap(*r.coordinates)
            print(f"✅ #{pos} {content} (vision)")
            return
    print("❌ Not found")


def _do_app_action(cmd, device, screen, adb):
    descs = (cmd.text or "").split("|")
    keyevent = cmd.package or ""
    screen._maybe_capture()
    for d in descs:
        if not d:
            continue
        for elem in screen.ui_analyzer.last_elements:
            if d.lower() in elem.content_desc.lower():
                device.tap(*elem.center)
                return
    if keyevent:
        adb.run(["shell", "input", "keyevent", keyevent])
        return


def _find_input(screen):
    for e in screen.ui_analyzer.last_elements:
        if "EditText" in e.class_name:
            return e
        if any(k in e.resource_id.lower() for k in ["input", "edit", "compose", "message", "entry"]):
            return e
        if any(k in e.content_desc.lower() for k in ["type a message", "message", "write", "compose"]):
            return e
    return None


def _tap_send(screen, device) -> bool:
    for e in screen.ui_analyzer.last_elements:
        if any(k in e.content_desc.lower() for k in ["send", "paper plane"]):
            if (e.bounds[2] - e.bounds[0]) > 10:
                device.tap(*e.center)
                return True
    for e in screen.ui_analyzer.last_elements:
        if any(k in e.resource_id.lower() for k in ["send", "btn_send", "send_button", "fab"]):
            device.tap(*e.center)
            return True
    for e in screen.ui_analyzer.last_elements:
        if (e.text or "").lower() in ("send", "submit", "post"):
            device.tap(*e.center)
            return True
    iy = None
    for e in screen.ui_analyzer.last_elements:
        if "EditText" in e.class_name:
            iy = e.center[1]
            break
    if iy:
        try:
            sw, _ = device.screen_size()
        except Exception:
            sw = 1080
        for e in screen.ui_analyzer.last_elements:
            if "Button" in e.class_name or "Image" in e.class_name:
                ex, ey = e.center
                if ex > sw * 0.65 and abs(ey - iy) < 120:
                    device.tap(ex, ey)
                    return True
    return False


if __name__ == "__main__":
    run_cli()
