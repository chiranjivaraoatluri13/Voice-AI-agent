# =========================
# FILE: agent/controller.py
# =========================
"""
Complete controller integrating:
- App management (auto aapt2 extraction + install listener)
- Device control
- Learning system
- Vision capabilities (UI Automator + OCR + Ollama)
"""

from agent.adb import AdbClient
from agent.device import DeviceController
from agent.apps import AppResolver
from agent.learner import CommandLearner
from agent.screen_controller import ScreenController
from agent.planner import plan
from agent.schema import Command


def run_cli() -> None:
    """Main CLI loop with full vision capabilities"""
    
    # Initialize ADB
    adb = AdbClient()
    devs = adb.ensure_device()

    print("✅ Connected devices:")
    for d in devs:
        print("  ", d)

    # Initialize components
    device = DeviceController(adb)
    learner = CommandLearner()
    apps = AppResolver(adb, learner)
    screen = ScreenController(adb, device)

    device.wake()

    # Get screen info
    try:
        w, h = device.screen_size()
        print(f"📱 Screen size: {w}x{h} ({'LANDSCAPE' if w > h else 'PORTRAIT'})")
        screen.vision.set_screen_size(w, h)
    except Exception:
        print("⚠️ Could not determine screen size")

    # =====================================================
    # Initialize app database
    # On first launch: auto-extracts ALL labels via aapt2
    # On subsequent launches: loads from cache, extracts only new apps
    # Also starts background listener for real-time install detection
    # =====================================================
    print("\n📦 Initializing app database...")
    stats = apps.initialize()
    
    if stats.get("first_launch"):
        print(f"\n🎉 First launch setup complete!")
    
    print(f"✅ App database ready:")
    print(f"   Total apps:        {stats['total']}")
    print(f"   Labels available:  {stats['cached']}")
    if stats['extracted'] > 0:
        print(f"   APK-extracted:     {stats['extracted']}")
    if stats['missing'] > 0:
        print(f"   Missing labels:    {stats['missing']}")
    print(f"   Init time:         {stats['time_ms']}ms")

    # aapt2 status
    if apps.label_loader.aapt2_path:
        print(f"   🔧 aapt2:          available")
    else:
        print(f"   ⚠️ aapt2:          not found (new app labels may be limited)")

    # Install listener status
    if apps.install_listener and apps.install_listener._running:
        print(f"   👂 Install listener: active (new apps auto-detected)")
    else:
        print(f"   ⚠️ Install listener: not running")

    # Load user mappings
    if learner.mappings:
        print(f"🎓 Loaded {len(learner.mappings)} custom mapping(s)")
    
    # Check vision availability
    if screen.vision.available:
        print(f"👁️ Vision system ready: {screen.vision.model}")
    else:
        print("⚠️ Vision system not available (install: ollama pull llava-phi3)")
    
    if screen.ocr.available:
        print("🔍 OCR system ready")
    else:
        print("⚠️ OCR not available (install: pip install pytesseract)")

    print("\n" + "="*60)
    print("COMMANDS:")
    print("="*60)
    
    print("\n📱 Basic Control:")
    print("  back / home / wake")
    print("  tap 540 1200")
    print("  type hello world")
    print("  scroll down / scroll up")
    
    print("\n🎯 App Control:")
    print("  open canvas / open chatgpt / open ludo king")
    print("  open gmail / open youtube / open gemini")
    print("  find gmail")
    print("  reindex apps         → full re-extract all labels")
    
    print("\n🎓 Learning:")
    print("  teach                → teach last app")
    print("  teach google chrome  → 'google' = Chrome")
    print("  forget google        → remove mapping")
    print("  list mappings        → show shortcuts")
    
    print("\n👁️ Vision Queries:")
    print("  what do you see?     → describe screen")
    print("  click Subscribe      → find and click")
    print("  tap the first video  → position-based")
    print("  click the red button → visual search")
    
    print("\n📋 Other:")
    print("  exit")
    print("="*60)
    print("\n💡 New apps installed while running are auto-detected!\n")

    while True:
        try:
            utter = input("> ").strip()
            if not utter:
                continue
                
            cmd = plan(utter)

            if not cmd:
                print("❌ Didn't understand. Try 'what do you see?' or 'click Subscribe'")
                continue

            if cmd.action == "EXIT":
                # Cleanup
                if apps.install_listener:
                    apps.install_listener.stop()
                print("Stopping.")
                break

            execute_command(cmd, device, apps, learner, screen)
            
        except KeyboardInterrupt:
            if apps.install_listener:
                apps.install_listener.stop()
            print("\n\nStopping.")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()


def execute_command(
    cmd: Command, 
    device: DeviceController, 
    apps: AppResolver,
    learner: CommandLearner,
    screen: ScreenController
) -> None:
    """Execute command with vision support"""
    
    # ==================
    # Vision Commands
    # ==================
    if cmd.action == "SCREEN_INFO":
        print("🔍 Analyzing screen...")
        query = cmd.query or "what do you see?"
        
        intent = screen.router.parse_query(query)
        if intent.type == "INFO":
            screen._execute_info(intent)
        else:
            answer = screen.ask(query)
            print(f"\n📱 {answer}\n")
        return
    
    if cmd.action == "VISION_QUERY":
        if not cmd.query:
            print("❌ No query provided")
            return
        
        print(f"🔍 Processing: {cmd.query}")
        success = screen.execute_query(cmd.query)
        
        if not success:
            print("💡 Tip: Try being more specific or use 'what do you see?' first")
        return
    
    if cmd.action == "FIND_VISUAL":
        if not cmd.query:
            print("❌ No search query")
            return
        
        success = screen.find_and_tap(cmd.query)
        if not success:
            print(f"❌ Could not find: {cmd.query}")
        return
    
    # ==================
    # Learning Commands
    # ==================
    if cmd.action == "TEACH_LAST":
        apps.teach_last()
        return
    
    if cmd.action == "TEACH_CUSTOM":
        if not cmd.query or not cmd.text:
            print("❌ Usage: teach <shortcut> <app>")
            print("   Example: teach google chrome")
            return
        apps.teach_custom(cmd.query, cmd.text)
        return
    
    if cmd.action == "TEACH_SHORTCUT":
        if not cmd.query:
            print("❌ Usage: teach <shortcut>")
            return
        if not apps.last_choice:
            print("❌ No recent app to teach. Open an app first.")
            return
        _, pkg, label = apps.last_choice
        learner.teach(cmd.query, pkg, label)
        return
    
    if cmd.action == "FORGET_MAPPING":
        if not cmd.query:
            print("❌ Usage: forget <shortcut>")
            return
        if learner.forget(cmd.query):
            print(f"✅ Forgot mapping for '{cmd.query}'")
        else:
            print(f"❌ No mapping found for '{cmd.query}'")
        return
    
    if cmd.action == "LIST_MAPPINGS":
        learner.list_mappings()
        return
    
    # ==================
    # Basic Commands
    # ==================
    if cmd.action == "WAKE":
        device.wake()
        return

    if cmd.action == "HOME":
        device.home()
        return

    if cmd.action == "BACK":
        device.back()
        return

    if cmd.action == "TAP":
        if cmd.x is None or cmd.y is None:
            print("❌ TAP requires x and y")
            return
        device.tap(cmd.x, cmd.y)
        return

    if cmd.action == "TYPE_TEXT":
        device.type_text(cmd.text or "")
        return

    if cmd.action == "SCROLL":
        amt = max(1, min(cmd.amount, 10))
        direction = cmd.direction or "DOWN"
        for _ in range(amt):
            device.scroll_once(direction)
        # Invalidate UI tree cache — screen content changed
        screen.ui_analyzer.last_tree = None
        screen.ui_analyzer.last_elements = []
        return

    # =====================================================
    # REINDEX: Full re-extraction of all labels
    # =====================================================
    if cmd.action == "REINDEX_APPS":
        print("🔄 Full reindex: clearing all caches and re-extracting...")
        stats = apps.full_reindex()
        print(f"✅ Reindex complete:")
        print(f"   Total apps:      {stats['total']}")
        print(f"   Labels available: {stats['cached']}")
        if stats['extracted'] > 0:
            print(f"   APK-extracted:   {stats['extracted']}")
        if stats['missing'] > 0:
            print(f"   Missing labels:  {stats['missing']}")
        print(f"   Time:            {stats['time_ms']}ms")
        return

    if cmd.action == "FIND_APP":
        q = cmd.query or ""
        cands = apps.candidates(q, limit=10)
        if not cands:
            print(f"🔍 FIND: No candidates for '{q}'")
            return
        print(f"🔍 FIND candidates for '{q}':")
        for i, (score, label, pkg) in enumerate(cands, 1):
            aliases = learner.get_aliases_for(pkg)
            alias_str = f" [shortcuts: {', '.join(aliases)}]" if aliases else ""
            print(f"  {i}. {label}  ({pkg})  score={score:.2f}{alias_str}")
        return

    if cmd.action == "OPEN_APP":
        q = cmd.query or ""
        pkg = apps.resolve_or_ask(q)
        if not pkg:
            return
        device.launch(pkg)
        return

    # ==================
    # Media Controls
    # ==================
    if cmd.action == "MEDIA_PLAY":
        device.media_play()
        print("▶️ Play")
        return

    if cmd.action == "MEDIA_PAUSE":
        device.media_pause()
        print("⏸️ Paused")
        return

    if cmd.action == "MEDIA_NEXT":
        device.media_next()
        print("⏭️ Next track")
        return

    if cmd.action == "MEDIA_PREVIOUS":
        device.media_previous()
        print("⏮️ Previous track")
        return

    # ==================
    # Volume Controls
    # ==================
    if cmd.action == "VOLUME_UP":
        steps = cmd.amount if cmd.amount > 1 else 2
        device.volume_up(steps)
        print(f"🔊 Volume up ({steps} steps)")
        return

    if cmd.action == "VOLUME_DOWN":
        steps = cmd.amount if cmd.amount > 1 else 2
        device.volume_down(steps)
        print(f"🔉 Volume down ({steps} steps)")
        return

    print(f"⚠️ Unhandled command: {cmd}")


if __name__ == "__main__":
    run_cli()
