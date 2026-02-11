# =========================
# FILE: agent/controller.py
# =========================
"""
Controller v5 — SPEED FOCUSED.

Key speed fixes:
1. _get_current_app() ONLY called for commands that need context
   (open, send, play/pause, search) — NOT for back, home, volume, scroll
2. Vision background thread pre-captures screenshots
3. UI element finders reuse already-captured tree (no extra ADB calls)
4. Basic commands (back, home, volume) are truly instant
"""

import re
import time
from agent.adb import AdbClient
from agent.device import DeviceController
from agent.apps import AppResolver
from agent.learner import CommandLearner
from agent.screen_controller import ScreenController
from agent.planner import plan
from agent.schema import Command

# Commands that DON'T need current app context
# These skip _get_current_app() entirely → instant
NO_CONTEXT_ACTIONS = {
    "EXIT", "WAKE", "BACK", "HOME", "CLOSE_ALL", "TAP", "TYPE_TEXT",
    "SCROLL", "REINDEX_APPS", "FIND_APP", "KEYEVENT",
    "VOLUME_UP", "VOLUME_DOWN",
    "TEACH_LAST", "TEACH_CUSTOM", "TEACH_SHORTCUT", "FORGET_MAPPING", "LIST_MAPPINGS",
}


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


def _find_scrollable_bounds(screen):
    """Uses cached UI tree. No ADB call."""
    if not screen.ui_analyzer.last_elements:
        screen.ui_analyzer.capture_ui_tree()
    
    best = None
    best_area = 0
    for elem in screen.ui_analyzer.last_elements:
        if elem.scrollable:
            w = elem.bounds[2] - elem.bounds[0]
            h = elem.bounds[3] - elem.bounds[1]
            if w > 50 and h > 50 and w * h > best_area:
                best_area = w * h
                best = elem.bounds
    if best:
        return best
    
    for elem in screen.ui_analyzer.last_elements:
        cls = elem.class_name.lower()
        if any(s in cls for s in ["recyclerview", "listview", "scrollview", "nestedscrollview"]):
            w = elem.bounds[2] - elem.bounds[0]
            h = elem.bounds[3] - elem.bounds[1]
            if w > 100 and h > 200 and w * h > best_area:
                best_area = w * h
                best = elem.bounds
    return best


def run_cli() -> None:
    adb = AdbClient()
    devs = adb.ensure_device()
    print("✅ Connected:", len(devs), "device(s)")

    device = DeviceController(adb)
    learner = CommandLearner()
    apps = AppResolver(adb, learner)
    screen = ScreenController(adb, device)
    device.wake()

    # Workflow system (self-contained, graceful degradation)
    from agent import workflow_runner as wf_runner

    try:
        w, h = device.screen_size()
        print(f"📱 {w}x{h}")
        screen.vision.set_screen_size(w, h)
    except Exception:
        pass

    print("📦 Loading apps...")
    stats = apps.initialize()
    print(f"✅ {stats['total']} apps, {stats['time_ms']}ms")

    if learner.mappings:
        print(f"🎓 {len(learner.mappings)} mappings")
    wf_count = wf_runner.workflow_count()
    if wf_count:
        print(f"📚 {wf_count} learned workflow(s)")

    # Start background vision watching
    screen.start_watching()

    print("\n" + "="*50)
    print("back | home | close | scroll up/down | swipe left")
    print("open youtube | type hello | write hi and send")
    print("click subscribe | search cats on youtube")
    print("play | pause | volume up | sound more up")
    print("teach me to <task>  | list workflows | exit")
    print("="*50 + "\n")

    # Cache current app lazily
    _cached_app = ""
    _cached_app_time = 0

    while True:
        try:
            utter = input("> ").strip()
            if not utter:
                continue
            
            # ── WORKFLOW HOOK (self-contained, safe) ──
            action, data = wf_runner.intercept(utter)
            if action == "handled":
                continue  # Workflow system handled it entirely
            elif action == "execute":
                # Replay learned workflow steps
                current_app = _get_current_app(adb)
                for i, step_cmd in enumerate(data):
                    print(f"  ▶ Step {i+1}: {step_cmd}")
                    sub = plan(step_cmd, current_app=current_app)
                    if sub and sub.action != "EXIT":
                        execute_command(sub, device, apps, learner, screen, adb, current_app)
                        time.sleep(0.5)
                        current_app = _get_current_app(adb)
                print(f"✅ Done\n")
                continue
            else:
                # "pass" — normal flow, utter may have been modified during recording
                utter = data
            
            # ── NORMAL COMMAND (unchanged from v5) ──
            t_lower = utter.lower().strip()
            needs_context = _needs_app_context(t_lower)
            if needs_context:
                now = time.time()
                if now - _cached_app_time > 2.0:
                    _cached_app = _get_current_app(adb)
                    _cached_app_time = now
                current_app = _cached_app
            else:
                current_app = _cached_app

            cmd = plan(utter, current_app=current_app)
            if not cmd:
                print("❌ Didn't understand.")
                continue
            if cmd.action == "EXIT":
                screen.stop_watching()
                if hasattr(apps, 'install_listener') and apps.install_listener:
                    apps.install_listener.stop()
                print("Stopping.")
                break
            
            execute_command(cmd, device, apps, learner, screen, adb, current_app)

        except KeyboardInterrupt:
            screen.stop_watching()
            print("\nStopping.")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()


def _needs_app_context(t: str) -> bool:
    """Quick check: does this command need to know current app?"""
    # These commands need context for proper routing
    if any(t.startswith(p) for p in ["open ", "send ", "play", "pause", "stop", "resume",
                                      "next", "skip", "previous", "search ", "find "]):
        return True
    if any(kw in t for kw in ["what do you see", "describe screen"]):
        return True
    return False


def execute_command(cmd, device, apps, learner, screen, adb, current_app=""):
    # === INSTANT commands (no ADB overhead) ===
    if cmd.action == "WAKE":
        device.wake(); return
    if cmd.action == "HOME":
        device.home(); return
    if cmd.action == "BACK":
        device.back(); return
    if cmd.action == "CLOSE_ALL":
        device.close_all_apps(); return
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

    # === Scroll (fast — one ADB swipe) ===
    if cmd.action == "SCROLL":
        d = cmd.direction or "DOWN"
        amt = max(1, min(cmd.amount, 10))
        if d in ("LEFT", "RIGHT"):
            for _ in range(amt):
                device.scroll_horizontal(d)
        else:
            bounds = _find_scrollable_bounds(screen) if screen.ui_analyzer.last_elements else None
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
            sub_cmd = plan(step, current_app=current_app)
            if sub_cmd and sub_cmd.action != "EXIT":
                execute_command(sub_cmd, device, apps, learner, screen, adb, current_app)
                # Update current app after each step (app may have changed)
                import time as _t
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
        if pkg: device.launch(pkg)
        return

    # === Vision queries ===
    if cmd.action == "SCREEN_INFO":
        intent = screen.router.parse_query(cmd.query or "what do you see?")
        screen._execute_info(intent); return
    if cmd.action == "VISION_QUERY":
        if cmd.query: screen.execute_query(cmd.query)
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
        screen.ui_analyzer.capture_ui_tree(force_refresh=True)
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


def _do_search(cmd, device, apps, screen, adb):
    query = cmd.query or ""
    if not query: return

    if cmd.text:
        pkg = apps.resolve_or_ask(cmd.text, allow_learning=False)
        if pkg:
            device.launch(pkg)
            time.sleep(1.5)
            screen.ui_analyzer.last_tree = None

    time.sleep(0.3)
    screen.ui_analyzer.capture_ui_tree(force_refresh=True)
    elem = _find_search(screen)

    if elem:
        device.tap(*elem.center)
        time.sleep(0.5)
        device.clear_text_field()
        time.sleep(0.3)
        device.type_text(query)
        time.sleep(0.3)
        adb.run(["shell", "input", "keyevent", "KEYCODE_ENTER"])
        print(f"✅ Searched: {query}")
    else:
        print("❌ No search bar found")


def _do_open_content(cmd, device, apps, screen):
    content = cmd.query or "video"
    app_name = cmd.text or ""
    pos = cmd.amount
    if not app_name: return

    pkg = apps.resolve_or_ask(app_name, allow_learning=False)
    if not pkg: return
    device.launch(pkg)
    time.sleep(2.0)

    screen.ui_analyzer.capture_ui_tree(force_refresh=True)
    items = screen._find_items_ui(content)
    if items:
        idx = pos - 1 if pos > 0 else pos
        if 0 <= idx < len(items):
            device.tap(*items[idx].center)
            print(f"✅ #{pos} {content}"); return

    if screen.vision.available:
        r = screen.vision.find_element_fast(f"the {'first second third fourth fifth'.split()[pos-1] if 1<=pos<=5 else str(pos)+'th'} {content}")
        if r.coordinates and r.confidence > 0.4:
            device.tap(*r.coordinates)
            print(f"✅ #{pos} {content} (vision)"); return
    print(f"❌ Not found")


def _do_app_action(cmd, device, screen, adb):
    descs = (cmd.text or "").split("|")
    keyevent = cmd.package or ""
    screen.ui_analyzer.capture_ui_tree(force_refresh=True)
    for d in descs:
        if not d: continue
        for elem in screen.ui_analyzer.last_elements:
            if d.lower() in elem.content_desc.lower():
                device.tap(*elem.center); return
    if keyevent:
        adb.run(["shell", "input", "keyevent", keyevent]); return


# ===========================================================
# UI FINDERS — use already-captured tree, NO extra ADB calls
# ===========================================================

def _find_input(screen):
    for e in screen.ui_analyzer.last_elements:
        if "EditText" in e.class_name: return e
        if any(k in e.resource_id.lower() for k in ["input", "edit", "compose", "message", "entry"]): return e
        if any(k in e.content_desc.lower() for k in ["type a message", "message", "write", "compose"]): return e
    return None


def _tap_send(screen, device) -> bool:
    for e in screen.ui_analyzer.last_elements:
        if any(k in e.content_desc.lower() for k in ["send", "paper plane"]):
            if (e.bounds[2] - e.bounds[0]) > 10:
                device.tap(*e.center); return True
    for e in screen.ui_analyzer.last_elements:
        if any(k in e.resource_id.lower() for k in ["send", "btn_send", "send_button", "fab"]):
            device.tap(*e.center); return True
    for e in screen.ui_analyzer.last_elements:
        if (e.text or "").lower() in ("send", "submit", "post"):
            device.tap(*e.center); return True
    # Positional: button near EditText on right
    iy = None
    for e in screen.ui_analyzer.last_elements:
        if "EditText" in e.class_name: iy = e.center[1]; break
    if iy:
        try: sw, _ = device.screen_size()
        except: sw = 1080
        for e in screen.ui_analyzer.last_elements:
            if "Button" in e.class_name or "Image" in e.class_name:
                ex, ey = e.center
                if ex > sw * 0.65 and abs(ey - iy) < 120:
                    device.tap(ex, ey); return True
    return False


def _find_search(screen):
    for e in screen.ui_analyzer.last_elements:
        combined = (e.content_desc + e.text + e.resource_id).lower()
        if "EditText" in e.class_name and any(k in combined for k in ["search", "find", "query"]):
            return e
        if any(k in e.content_desc.lower() for k in ["search", "find", "magnify"]) and e.clickable:
            return e
        if any(k in e.resource_id.lower() for k in ["search", "action_search", "search_button"]):
            return e
    return None


if __name__ == "__main__":
    run_cli()
