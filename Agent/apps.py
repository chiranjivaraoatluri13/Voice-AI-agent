from __future__ import annotations

import json
import os
import re
import time
from difflib import SequenceMatcher
from typing import List, Tuple, Optional, Dict
from datetime import datetime

from agent.adb import AdbClient
from agent.learner import CommandLearner
from agent.label_loader import LabelLoader

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

    # Gemini / Bard
    "gemini": ["com.google.android.apps.bard"],
    "bard": ["com.google.android.apps.bard"],

    # Chrome
    "chrome": ["com.android.chrome"],
    "browser": ["com.android.chrome"],

    # Maps
    "maps": ["com.google.android.apps.maps"],
    "google maps": ["com.google.android.apps.maps"],

    # Photos
    "photos": ["com.google.android.apps.photos"],
    "google photos": ["com.google.android.apps.photos"],

    # WhatsApp
    "whatsapp": ["com.whatsapp"],
    "wa": ["com.whatsapp"],

    # Telegram
    "telegram": ["org.telegram.messenger"],

    # Spotify
    "spotify": ["com.spotify.music"],

    # Netflix
    "netflix": ["com.netflix.mediaclient"],

    # Instagram
    "instagram": ["com.instagram.android"],
    "insta": ["com.instagram.android"],

    # X / Twitter
    "twitter": ["com.twitter.android"],

    # Canvas
    "canvas": ["com.instructure.candroid"],

    # ChatGPT
    "chatgpt": ["com.openai.chatgpt"],

    # Perplexity
    "perplexity": ["ai.perplexity.app.android"],

    # LinkedIn
    "linkedin": ["com.linkedin.android"],

    # Coursera
    "coursera": ["org.coursera.android"],

    # Pinterest
    "pinterest": ["com.pinterest"],

    # Samsung apps
    "samsung notes": ["com.samsung.android.app.notes"],
    "notes": ["com.samsung.android.app.notes"],
    "samsung health": ["com.sec.android.app.shealth"],
    "health": ["com.sec.android.app.shealth"],
    "galaxy shop": ["com.samsung.android.galaxy"],
    "my files": ["com.sec.android.app.myfiles"],
    "files": ["com.sec.android.app.myfiles"],
    "calculator": ["com.sec.android.app.popupcalculator"],
    "clock": ["com.sec.android.app.clockpackage"],
    "calendar": ["com.samsung.android.calendar"],
    "gallery": ["com.sec.android.gallery3d"],
    "voice recorder": ["com.sec.android.app.voicenote"],
    "recorder": ["com.sec.android.app.voicenote"],
    "contacts": ["com.samsung.android.app.contacts"],

    # Spacedesk
    "spacedesk": ["ph.spacedesk.beta"],

    # OneDrive
    "onedrive": ["com.microsoft.skydrive"],

    # Lufthansa
    "lufthansa": ["com.lufthansa.android.lufthansa"],

    # WhatsApp Business
    "whatsapp business": ["com.whatsapp.w4b"],
}


class AppResolver:
    """
    Fast + explainable app resolution with:
    - LabelLoader for complete label coverage (extracted + dumpsys + cache)
    - Persistent disk cache (labels survive restarts)
    - Startup diffing (only fetch labels for NEW apps)
    - System fallbacks for common apps
    - User-trained mappings via CommandLearner
    
    LATENCY FIX: All labels are pre-loaded at startup.
    NO dumpsys calls happen during search. This must be preserved.
    """

    def __init__(self, adb: AdbClient, learner: Optional[CommandLearner] = None) -> None:
        self.adb = adb
        self.packages: List[str] = []
        self.label_cache: Dict[str, str] = {}
        self.label_loader = LabelLoader(adb)
        # Learning system
        self.learner = learner if learner else CommandLearner()
        self.last_choice: Optional[Tuple[str, str, str]] = None  # (query, package, label)

    # ==========================================================
    # STARTUP: Full initialization (call once at startup)
    # ==========================================================
    def initialize(self) -> dict:
        """
        Full startup initialization:
        1. Fetch current package list from device
        2. Use LabelLoader to build complete label map:
           - Load disk cache (instant)
           - Load extracted labels from app_labels_map.txt (highest priority)
           - Batch dumpsys for uncovered apps
           - Package name fallback for anything remaining
        3. Save merged cache to disk
        
        Returns:
            dict with stats: {total, cached, extracted, missing, time_ms}
        """
        start = time.time()
        stats = {
            "total": 0,
            "cached": 0,
            "extracted": 0,
            "missing": 0,
            "time_ms": 0,
        }

        # Step 1: Fetch current package list
        self.refresh_packages()
        current_packages = set(self.packages)
        stats["total"] = len(current_packages)

        # Step 2: Use LabelLoader to build complete label map
        self.label_cache = self.label_loader.initialize(current_packages)

        # Step 3: Gather stats
        stats["extracted"] = len(self.label_loader.extracted_labels)
        stats["cached"] = len(self.label_cache)

        # Step 4: Check for apps with only fallback labels
        missing = self.label_loader.get_missing_labels(current_packages)
        stats["missing"] = len(missing)

        elapsed = (time.time() - start) * 1000
        stats["time_ms"] = round(elapsed)

        # Report missing labels
        if missing:
            print(f"\n⚠️ {len(missing)} app(s) have no real label (using package name):")
            for pkg in sorted(missing):
                fallback = self.label_cache.get(pkg, pkg)
                print(f"   {fallback} ({pkg})")
            print(f"   💡 Run extract_app_labels.ps1 to fix these\n")

        return stats

    # ==========================================================
    # PACKAGE DISCOVERY
    # ==========================================================
    def refresh_packages(self) -> None:
        """Fetch all launchable packages from device."""
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

    def full_reindex(self) -> dict:
        """
        Force a complete reindex: clear cache and re-fetch everything.
        Use when apps have been updated/renamed or after running extract_app_labels.ps1.
        """
        print("🔄 Full reindex: clearing cache...")
        self.label_loader.clear_cache()
        self.label_cache.clear()
        return self.initialize()

    # ==========================================================
    # LABEL RESOLUTION (always from cache — NO ADB calls)
    # ==========================================================
    def _label_for(self, pkg: str) -> str:
        """
        Get label for a package.
        ALWAYS a cache hit after initialize().
        NO ADB CALLS — this is critical for the latency fix.
        """
        if pkg in self.label_cache:
            return self.label_cache[pkg]

        # Fallback (should rarely happen after initialize)
        return LabelLoader.label_from_package_name(pkg)

    # ==========================================================
    # SYSTEM FALLBACK
    # ==========================================================
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
                print(f"📱 Using system fallback: {pkg}")
                return pkg
        return None

    # ==========================================================
    # CANDIDATE SEARCH (uses cached real labels — NO ADB calls)
    # ==========================================================
    def candidates(
        self, query: str, limit: int = 7
    ) -> List[Tuple[float, str, str]]:
        """
        Find candidate apps matching query.
        Uses REAL labels from cache — no dumpsys during search.
        
        LATENCY: This runs in milliseconds because all labels
        are pre-loaded in self.label_cache at startup.
        """
        q = query.strip().lower()
        if not q:
            return []

        if not self.packages:
            self.refresh_packages()

        scored: List[Tuple[float, str, str]] = []

        for pkg in self.packages:
            # Always use real label from cache
            label = self.label_cache.get(pkg, LabelLoader.label_from_package_name(pkg))
            lab = label.lower()

            # Score: fuzzy match + substring bonus
            s_fuzzy = SequenceMatcher(None, q, lab).ratio()
            s_sub = 0.15 if q in lab else 0.0

            # Also check against full package name for partial matches
            s_pkg = 0.10 if q in pkg.lower() else 0.0

            score = min(1.0, s_fuzzy + s_sub + s_pkg)
            scored.append((score, label, pkg))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:limit]

    # ==========================================================
    # RESOLVE OR ASK (with learning)
    # ==========================================================
    def resolve_or_ask(self, query: str, allow_learning: bool = True) -> Optional[str]:
        q = query.strip()
        if not q:
            return None

        # Direct package
        if "." in q and " " not in q:
            return q

        # Check user-trained mappings FIRST
        learned_pkg = self.learner.resolve(q)
        if learned_pkg:
            label = self._label_for(learned_pkg)
            print(f"🎓 Using learned mapping: '{q}' → {label}")
            self.last_choice = (q, learned_pkg, label)
            return learned_pkg

        # System fallback
        fb = self.try_system_fallback(q)
        if fb:
            label = self._label_for(fb)
            self.last_choice = (q, fb, label)
            return fb

        cands = self.candidates(q, limit=7)
        if not cands:
            print(f"❌ I couldn't find any app like '{q}'.")
            return None

        top_score, top_label, top_pkg = cands[0]

        # Auto-select if confident
        if top_score >= 0.78 and (
            len(cands) == 1 or top_score - cands[1][0] >= 0.10
        ):
            print(f"✅ Opening: {top_label} ({top_pkg})")
            self.last_choice = (q, top_pkg, top_label)
            return top_pkg

        # Ask user to choose
        print(f"🤔 I found multiple possible matches for '{q}'. Which one should I open?")
        for i, (score, label, pkg) in enumerate(cands, 1):
            aliases = self.learner.get_aliases_for(pkg)
            alias_str = f" [aliases: {', '.join(aliases)}]" if aliases else ""
            print(f"  {i}. {label} ({pkg}) score={score:.2f}{alias_str}")

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
            self.last_choice = (q, pkg, label)

            if allow_learning:
                self.learner.suggest_teaching(q, pkg, label)

            return pkg

        print("❌ Invalid choice.")
        return None

    # ==========================================================
    # TEACHING INTERFACE
    # ==========================================================
    def teach_last(self) -> bool:
        if not self.last_choice:
            print("❌ No recent app selection to teach.")
            return False

        query, package, label = self.last_choice
        self.learner.interactive_teach(query, package, label)
        return True

    def teach_custom(self, shortcut: str, query: str) -> bool:
        pkg = self.resolve_or_ask(query, allow_learning=False)
        if not pkg:
            return False

        label = self._label_for(pkg)
        self.learner.teach(shortcut, pkg, label)
        return True
