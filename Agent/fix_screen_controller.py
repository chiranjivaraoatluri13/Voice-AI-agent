"""
PATCH: Fix stale UI tree cache in screen_controller.py

The Problem:
  _try_content_desc() and _try_ui_tree_search() call:
    self.ui_analyzer.capture_ui_tree()     ← uses STALE cache!
  
  After back/scroll/navigation, the cache holds OLD screen elements.
  Text search finds nothing → falls to slow vision model.

The Fix (2 lines):
  Change capture_ui_tree() to capture_ui_tree(force_refresh=True)
  in _try_content_desc AND _try_ui_tree_search.

Also fix _find_items_ui() for "first video", "second video" support.

HOW TO APPLY:
  python fix_screen_controller.py
  
  (Run from your project root directory)
"""

import os
import sys

def apply_patch():
    path = os.path.join("agent", "screen_controller.py")
    if not os.path.exists(path):
        print(f"❌ File not found: {path}")
        print("   Run this from your project root directory")
        sys.exit(1)
    
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    original = content
    changes = 0
    
    # Fix 1: _try_content_desc — stale UI tree
    old1 = """        # Search UI tree for these content-descs
        self.ui_analyzer.capture_ui_tree()"""
    new1 = """        # Search UI tree for these content-descs
        self.ui_analyzer.capture_ui_tree(force_refresh=True)"""
    
    if old1 in content:
        content = content.replace(old1, new1, 1)
        changes += 1
        print("✅ Fix 1: _try_content_desc → force_refresh=True")
    elif "capture_ui_tree(force_refresh=True)" in content and "_try_content_desc" in content:
        print("⏭️ Fix 1: Already applied")
    else:
        print("⚠️ Fix 1: Could not find _try_content_desc pattern")
        print("   Manually change: self.ui_analyzer.capture_ui_tree()")
        print("   To:              self.ui_analyzer.capture_ui_tree(force_refresh=True)")
        print("   In the _try_content_desc method")
    
    # Fix 2: _try_ui_tree_search — stale UI tree
    # This could be either the simple version or the word-overlap version
    old2a = """    def _try_ui_tree_search(self, target: str) -> bool:
        \"\"\"Search UI tree by text, content-desc, resource-id.\"\"\"
        elements = self.ui_analyzer.search(target)"""
    new2a = """    def _try_ui_tree_search(self, target: str) -> bool:
        \"\"\"Search UI tree by text, content-desc, resource-id.\"\"\"
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        elements = self.ui_analyzer.search(target)"""
    
    old2b = """        self.ui_analyzer.capture_ui_tree()
        if not self.ui_analyzer.last_elements:
            return False
        
        tl = target.lower().strip()"""
    new2b = """        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        if not self.ui_analyzer.last_elements:
            return False
        
        tl = target.lower().strip()"""
    
    if old2a in content:
        content = content.replace(old2a, new2a, 1)
        changes += 1
        print("✅ Fix 2: _try_ui_tree_search → force_refresh=True")
    elif old2b in content:
        content = content.replace(old2b, new2b, 1)
        changes += 1
        print("✅ Fix 2: _try_ui_tree_search → force_refresh=True")
    else:
        print("⚠️ Fix 2: Could not find _try_ui_tree_search pattern")
        print("   Manually add: self.ui_analyzer.capture_ui_tree(force_refresh=True)")
        print("   At the start of _try_ui_tree_search method")
    
    # Fix 3: _find_items_ui — needed for "first video", "second video"
    old3 = """    def _find_items_ui(self, item_type: str) -> List[UIElement]:
        \"\"\"Find repeating items using UI Automator.\"\"\"
        self.ui_analyzer.capture_ui_tree()"""
    new3 = """    def _find_items_ui(self, item_type: str) -> List[UIElement]:
        \"\"\"Find repeating items using UI Automator.\"\"\"
        self.ui_analyzer.capture_ui_tree(force_refresh=True)"""
    
    if old3 in content:
        content = content.replace(old3, new3, 1)
        changes += 1
        print("✅ Fix 3: _find_items_ui → force_refresh=True")
    else:
        print("⏭️ Fix 3: _find_items_ui already fixed or not found")
    
    if changes > 0:
        # Backup
        backup = path + ".bak"
        with open(backup, "w", encoding="utf-8") as f:
            f.write(original)
        print(f"\n📦 Backup saved: {backup}")
        
        # Write fixed file
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ Patched {changes} location(s) in {path}")
    else:
        print("\nNo changes needed — all fixes already applied.")
    
    print("\nDone! Text search will now use fresh UI tree data.")


if __name__ == "__main__":
    apply_patch()
