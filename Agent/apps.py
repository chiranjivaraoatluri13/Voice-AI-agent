# =========================
# FILE: agent/apps.py
# =========================
from __future__ import annotations
from difflib import SequenceMatcher
from typing import List, Tuple, Optional
import re

from agent.adb import AdbClient

SYSTEM_FALLBACKS = {
    # Play Store
    "play store": ["com.android.vending", "com.google.android.finsky"],
    "playstore": ["com.android.vending", "com.google.android.finsky"],
    "play": ["com.android.vending", "com.google.android.finsky"],

    # Gmail / Meet (common packages)
    "gmail": ["com.google.android.gm"],
    "google meet": ["com.google.android.apps.tachyon"],
    "meet": ["com.google.android.apps.tachyon"],
    "gmeet": ["com.google.android.apps.tachyon"],

    # Phone / Dialer
    "phone": ["com.samsung.android.dialer", "com.google.android.dialer"],
    "dialer": ["com.samsung.android.dialer", "com.google.android.dialer"],

    # Messages
    "messages": ["com.google.android.apps.messaging", "com.android.messaging", "com.samsung.android.messaging"],

    # Settings / Camera
    "settings": ["com.android.settings"],
    "camera": ["com.sec.android.app.camera", "com.android.camera", "com.google.android.GoogleCamera"],
}

class AppResolver:
    """
    Fast startup:
      - fetch launcher package list once (single adb call)
    Lazy label fetch:
      - only dumpsys a package when needed
    Transparent resolution:
      - provides ranked candidates & asks user to pick when ambiguous
    """
    def __init__(self, adb: AdbClient) -> None:
        self.adb = adb
        self.packages: List[str] = []
        self.label_cache: dict[str, str] = {}

    def refresh_packages(self) -> None:
        out = self.adb.run([
            "shell", "cmd", "package", "query-activities",
            "--brief", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER"
        ])
        pkgs = set()
        for line in out.splitlines():
            line = line.strip()
            if "/" in line:
                pkgs.add(line.split("/")[0])
        self.packages = sorted(pkgs)

    def _label_for(self, pkg: str) -> str:
        if pkg in self.label_cache:
            return self.label_cache[pkg]

        # Try dumpsys label
        try:
            out = self.adb.run(["shell", "dumpsys", "package", pkg])
            m = re.search(r"application-label(?:-[a-zA-Z-]+)?:\s*(.+)", out)
            if m:
                label = m.group(1).strip()
                if label:
                    self.label_cache[pkg] = label
                    return label
        except Exception:
            pass

        # fallback label from package tail
        fallback = pkg.split(".")[-1].replace("-", " ").replace("_", " ").title()
        self.label_cache[pkg] = fallback
        return fallback

    def _installed(self, pkg: str) -> bool:
        # cheap-ish: pm path returns 0 when installed
        try:
            self.adb.run(["shell", "pm", "path", pkg])
            return True
        except Exception:
            return False

    def try_system_fallback(self, query: str) -> Optional[str]:
        key = query.strip().lower()
        if key not in SYSTEM_FALLBACKS:
            return None
        for pkg in SYSTEM_FALLBACKS[key]:
            if self._installed(pkg):
                return pkg
        return None

    def candidates(self, query: str, limit: int = 7) -> List[Tuple[float, str, str]]:
        q = query.strip().lower()
        if not q:
            return []
        if not self.packages:
            self.refresh_packages()

        scored: List[Tuple[float, str, str]] = []
        for pkg in self.packages:
            label = self._label_for(pkg)
            lab = label.lower()

            s_fuzzy = SequenceMatcher(None, q, lab).ratio()
            s_sub = 0.15 if q in lab else 0.0
            score = min(1.0, s_fuzzy + s_sub)

            scored.append((score, label, pkg))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:limit]

    def resolve_or_ask(self, query: str) -> Optional[str]:
        """
        Returns a package. If ambiguous, prints options and asks user to choose.
        """
        q = query.strip()
        if not q:
            return None

        # Direct package name
        if "." in q and " " not in q:
            return q

        # System fallbacks
        fb = self.try_system_fallback(q)
        if fb:
            print(f"🔁 Using system fallback for '{q}' -> {fb}")
            return fb

        cands = self.candidates(q, limit=7)
        if not cands:
            print(f"❌ I couldn't find any app like '{q}'.")
            return None

        top_score, top_label, top_pkg = cands[0]
        if top_score >= 0.78 and (len(cands) == 1 or (top_score - cands[1][0] >= 0.10)):
            print(f"✅ Opening: {top_label} ({top_pkg}) score={top_score:.2f}")
            return top_pkg

        print(f"🤔 I found multiple possible matches for '{q}'. Which one should I open?")
        for i, (score, label, pkg) in enumerate(cands, 1):
            print(f"  {i}. {label}  ({pkg})  score={score:.2f}")

        choice = input("Type a number (or 0 to cancel): ").strip()
        if not choice.isdigit():
            print("❌ Not a number. Cancelled.")
            return None
        n = int(choice)
        if n == 0:
            print("Cancelled.")
            return None
        if 1 <= n <= len(cands):
            _, label, pkg = cands[n - 1]
            print(f"✅ Opening: {label} ({pkg})")
            return pkg

        print("❌ Invalid choice.")
        return None
