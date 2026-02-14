#!/usr/bin/env python3
"""
Quick verification that the XML parsing fix works.
"""

import subprocess
import sys

print("""
================================================================================
VERIFYING XML PARSING FIX
================================================================================

The issue was: XML retrieved but NOT parsed (0 elements)
Root cause: ADB client uses errors="replace" which corrupts XML special chars
Solution: Use binary mode for XML retrieval, then decode with errors="ignore"

================================================================================
RUNNING FIXED DIAGNOSTIC
================================================================================
""")

result = subprocess.run([sys.executable, "test_cache_debug.py"], cwd=".", capture_output=False)

if result.returncode == 0:
    print("\n" + "="*80)
    print("✅ VERIFICATION COMPLETE")
    print("="*80)
    print("\nIf you saw '✅ UI CAPTURE WORKING' above, the fix worked!")
    print("\nNow try:")
    print("  python main.py")
    print("\nThen say: 'click subscribe'")
    print("="*80 + "\n")
else:
    print("\n❌ Verification failed. Check output above for errors.")
    sys.exit(1)
