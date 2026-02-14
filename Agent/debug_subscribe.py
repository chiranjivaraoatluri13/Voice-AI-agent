"""
Debug: What does the UI tree see when you say 'subscribe'?
Run this while YouTube is open on a channel/video with the Subscribe button visible.

Usage: python debug_subscribe.py
"""
import sys
sys.path.insert(0, '.')
from agent.adb import AdbClient
from agent.ui_analyzer import UIAnalyzer

adb = AdbClient()
ui = UIAnalyzer(adb)

print("Capturing UI tree...")
ui.capture_ui_tree(force_refresh=True)

print(f"\nTotal elements: {len(ui.last_elements)}")

# Search for subscribe
print("\n=== Elements matching 'subscribe' ===")
results = ui.search("subscribe")
for i, elem in enumerate(results[:10]):
    print(f"  {i+1}. text='{elem.text}'")
    print(f"     desc='{elem.content_desc}'")
    print(f"     id='{elem.resource_id}'")
    print(f"     class={elem.class_name}")
    print(f"     bounds={elem.bounds}")
    print(f"     center={elem.center}")
    print(f"     clickable={elem.clickable}")
    print(f"     size={elem.width}x{elem.height}")
    print()

if not results:
    print("  ⚠️ No elements found with 'subscribe'!")
    print("  The subscribe button might use an image/icon without text.")
    print("  Trying content descriptions...")
    
    for elem in ui.last_elements:
        if "subscribe" in (elem.content_desc or "").lower():
            print(f"\n  Found via content_desc: '{elem.content_desc}'")
            print(f"    center={elem.center} clickable={elem.clickable}")

print("\n=== All visible TEXT elements (top 30) ===")
texts = [(e.text, e.center, e.clickable, e.class_name) 
         for e in ui.last_elements if e.text and len(e.text) > 1]
texts.sort(key=lambda x: x[1][1])  # sort by Y position
for txt, center, click, cls in texts[:30]:
    c = "🔘" if click else "  "
    print(f"  {c} '{txt}' at {center} ({cls})")
