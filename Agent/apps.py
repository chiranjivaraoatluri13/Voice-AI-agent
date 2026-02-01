from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List, Tuple, Optional

from agent.adb import AdbClient

# -------------------------
# Known system app fallbacks (fast path)
# -------------------------
SYSTEM_FALLBACKS = {
    # YouTube
    "youtube": ["com.google.android.youtube"],
    "yt": ["com.google.android.youtube"],

    # Play Store
    "play store": ["com.android.vending", "com.google.android.finsky"],
    "playstore": ["com.android.vending", "com.google.android.finsky"],
    "play": ["com.android.vending", "com.google.android.finsky"],

    # Gmail / Meet
    "gmail": ["com.google.android.gm"],
    "google meet": ["com.google.android.apps.tachyon"],
    "meet": ["com.google.android.apps.tachyon"],
    "gmeet": ["com.google.android.apps.tachyon"],

    # Phone / Dialer
    "phone": ["com.samsung.android.dialer", "com.google.android.dialer"],
    "dialer": ["com.samsung.android.dialer", "com.google.android.dialer"],

    # Messages
    "messages": [
        "com.google.android.apps.messaging",
        "com.android.messaging",
        "com.samsung.android.messaging",
    ],

    # Settings / Camera
    "settings": ["com.android.settings"],
    "camera": [
        "com.sec.android.app.camera",
        "com.android.camera",
        "com.google.android.GoogleCamera",
    ],
}


class AppResolver:
    """
    Fast + explainable app resolution:
    - One-time fast package list
    - Lazy label fetch (dumpsys only for top candidates)
    - System fallbacks for common apps
    - Asks user when ambiguous
    """

    def __init__(self, adb: AdbClient) -> None:
        self.adb = adb
        self.packages: List[str] = []
        self.label_cache: dict[str, str] = {}

    # -------------------------
    # Package discovery
    # -------------------------
    def refresh_packages(self) -> None:
        out = self.adb.run(
            [
                "shell",
                "cmd",
                "package",
                "query-activities",
                "--brief",
                "-a",
                "android.intent.action.MAIN",
                "-c",
                "android.intent.category.LAUNCHER",
            ]
        )

        pkgs = set()
        for line in out.splitlines():
            line = line.strip()
            if "/" in line:
                pkgs.add(line.split("/")[0])

        self.packages = sorted(pkgs)

    # -------------------------
    # Label resolution (lazy)
    # -------------------------
    def _label_for(self, pkg: str) -> str:
        if pkg in self.label_cache:
            return self.label_cache[pkg]

        # Try real label via dumpsys
        try:
            out = self.adb.run(["shell", "dumpsys", "package", pkg])
            m = re.search(
                r"application-label(?:-[a-zA-Z-]+)?:\s*(.+)", out
            )
            if m:
                label = m.group(1).strip()
                if label:
                    self.label_cache[pkg] = label
                    return label
        except Exception:
            pass

        # Fallback label from package tail
        fallback = (
            pkg.split(".")[-1]
            .replace("-", " ")
            .replace("_", " ")
            .title()
        )
        self.label_cache[pkg] = fallback
        return fallback

    # -------------------------
    # System fallback check
    # -------------------------
    def _installed(self, pkg: str) -> bool:
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
                print(f"🔁 Using system fallback: {pkg}")
                return pkg
        return None

    # -------------------------
    # Candidate search (FAST)
    # -------------------------
    def candidates(
        self, query: str, limit: int = 7
    ) -> List[Tuple[float, str, str]]:
        q = query.strip().lower()
        if not q:
            return []

        if not self.packages:
            self.refresh_packages()

        # -------- Pass 1: cheap scoring (NO dumpsys) --------
        cheap_scored: List[Tuple[float, str, str]] = []
        for pkg in self.packages:
            label = self.label_cache.get(pkg)
            if not label:
                label = (
                    pkg.split(".")[-1]
                    .replace("-", " ")
                    .replace("_", " ")
                    .title()
                )

            lab = label.lower()
            s_fuzzy = SequenceMatcher(None, q, lab).ratio()
            s_sub = 0.15 if q in lab else 0.0
            score = min(1.0, s_fuzzy + s_sub)
            cheap_scored.append((score, label, pkg))

        cheap_scored.sort(key=lambda x: x[0], reverse=True)

        # -------- Pass 2: refine only top pool --------
        pool = cheap_scored[: max(limit * 4, 20)]
        refined: List[Tuple[float, str, str]] = []

        for _, _, pkg in pool:
            real_label = self._label_for(pkg)
            lab = real_label.lower()
            s_fuzzy = SequenceMatcher(None, q, lab).ratio()
            s_sub = 0.15 if q in lab else 0.0
            new_score = min(1.0, s_fuzzy + s_sub)
            refined.append((new_score, real_label, pkg))

        refined.sort(key=lambda x: x[0], reverse=True)
        return refined[:limit]

    # -------------------------
    # Resolve or ask user
    # -------------------------
    def resolve_or_ask(self, query: str) -> Optional[str]:
        q = query.strip()
        if not q:
            return None

        # Direct package
        if "." in q and " " not in q:
            return q

        # System fallback
        fb = self.try_system_fallback(q)
        if fb:
            return fb

        cands = self.candidates(q, limit=7)
        if not cands:
            print(f"❌ I couldn't find any app like '{q}'.")
            return None

        top_score, top_label, top_pkg = cands[0]

        if top_score >= 0.78 and (
            len(cands) == 1 or top_score - cands[1][0] >= 0.10
        ):
            print(f"✅ Opening: {top_label} ({top_pkg})")
            return top_pkg

        print(f"🤔 I found multiple possible matches for '{q}'. Which one should I open?")
        for i, (score, label, pkg) in enumerate(cands, 1):
            print(f"  {i}. {label} ({pkg}) score={score:.2f}")

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
