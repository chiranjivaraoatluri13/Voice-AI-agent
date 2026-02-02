# =========================
# FILE: agent/controller.py
# =========================
from agent.adb import AdbClient
from agent.device import DeviceController
from agent.apps import AppResolver
from agent.learner import CommandLearner
from agent.planner import plan
from agent.schema import Command

def run_cli() -> None:
    adb = AdbClient()
    devs = adb.ensure_device()

    print("✅ Connected devices:")
    for d in devs:
        print("  ", d)

    device = DeviceController(adb)
    learner = CommandLearner()  # **NEW: Initialize learner**
    apps = AppResolver(adb, learner)  # **NEW: Pass learner to apps**

    device.wake()

    try:
        w, h = device.screen_size()
        print(f"📱 Screen size: {w}x{h} ({'LANDSCAPE' if w > h else 'PORTRAIT'})")
    except Exception:
        print("⚠️ Could not determine screen size")

    # Fast startup: just refresh package list (labels are lazy)
    print("📦 Loading app list...")
    apps.refresh_packages()
    print(f"✅ App list ready: {len(apps.packages)} packages")
    
    # Load user mappings
    if learner.mappings:
        print(f"🎓 Loaded {len(learner.mappings)} custom mapping(s)")

    print("\n" + "="*60)
    print("COMMANDS:")
    print("="*60)
    print("📱 App Control:")
    print("  open gmail / open gmeet / open play store")
    print("  find gmail   (preview matches)")
    print()
    print("🎓 Learning Commands (NEW!):")
    print("  teach                    → teach last opened app")
    print("  teach google chrome      → 'google' will open Chrome")
    print("  forget google            → remove 'google' mapping")
    print("  list mappings            → show all learned shortcuts")
    print()
    print("📋 Other:")
    print("  reindex apps (refresh app list)")
    print("  scroll down / scroll up")
    print("  type hello world")
    print("  back / home / wake")
    print("  tap 540 1200")
    print("  exit")
    print("="*60 + "\n")

    while True:
        utter = input("> ").strip()
        cmd = plan(utter)

        if not cmd:
            print("❌ Didn't understand. Try 'list mappings' or 'open <app>'")
            continue

        if cmd.action == "EXIT":
            print("Stopping.")
            break

        try:
            execute_command(cmd, device, apps, learner)
        except Exception as e:
            print(f"❌ Error: {e}")

def execute_command(
    cmd: Command, 
    device: DeviceController, 
    apps: AppResolver,
    learner: CommandLearner
) -> None:
    # **NEW: Learning commands**
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

    # Existing commands
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
        return

    if cmd.action == "REINDEX_APPS":
        print("📦 Refreshing app list...")
        apps.refresh_packages()
        apps.label_cache.clear()
        print(f"✅ App list refreshed: {len(apps.packages)} packages")
        return

    if cmd.action == "FIND_APP":
        q = cmd.query or ""
        cands = apps.candidates(q, limit=10)
        if not cands:
            print(f"🔍 FIND: No candidates for '{q}'")
            return
        print(f"🔍 FIND candidates for '{q}':")
        for i, (score, label, pkg) in enumerate(cands, 1):
            # Show learned aliases
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

    print(f"⚠️ Unhandled command: {cmd}")
