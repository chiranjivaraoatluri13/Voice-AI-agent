# =========================
# FILE: agent/label_loader.py
# =========================
"""
App label loading system with:
1. Auto-generation of app_labels_map.txt on first launch via aapt2
2. Background polling for real-time app install/uninstall detection
3. Disk cache for instant subsequent launches
4. Batch dumpsys fallback
5. Package name fallback (last resort)

IMPORTANT: This file is separate from apps.py to protect the latency fix.
Do NOT merge this into apps.py.
"""

import json
import os
import re
import subprocess
import shutil
import tempfile
import platform
import threading
import time
from typing import Dict, Optional, Set, Callable, List
from datetime import datetime


# File paths
LABEL_CACHE_FILE = "app_label_cache.json"
EXTRACTED_LABELS_FILE = "app_labels_map.txt"

# -------------------------------------------------------------------------
# KNOWN LABELS: Samsung/system apps where aapt2 extraction fails.
# These apps use split APKs, protected paths, or resource-only labels
# that aapt2 cannot pull. This dict fills the gap.
# Priority: extracted (aapt2) > KNOWN > dumpsys > fallback
# Add new entries here when you find aapt2 fails for a specific app.
# -------------------------------------------------------------------------
KNOWN_LABELS = {
    # Samsung system apps
    "com.sec.android.app.sbrowser": "Samsung Internet",
    "com.sec.android.app.clockpackage": "Clock",
    "com.sec.android.app.popupcalculator": "Calculator",
    "com.sec.android.app.shealth": "Samsung Health",
    "com.sec.android.app.myfiles": "My Files",
    "com.sec.android.app.voicenote": "Voice Recorder",
    "com.sec.android.app.camera": "Camera",
    "com.sec.android.easyMover": "Smart Switch",
    "com.sec.android.gallery3d": "Gallery",
    "com.samsung.android.app.spage": "Samsung Free",
    "com.samsung.android.app.notes": "Samsung Notes",
    "com.samsung.android.app.contacts": "Contacts",
    "com.samsung.android.voc": "Samsung Members",
    "com.samsung.android.mdx": "Link to Windows",
    "com.samsung.android.calendar": "Calendar",
    "com.samsung.android.dialer": "Phone",
    "com.samsung.android.messaging": "Messages",
    "com.samsung.android.galaxy": "Galaxy Shop",
    "com.samsung.android.tvplus": "Samsung TV Plus",
    "com.sec.android.app.samsungapps": "Galaxy Store",
    # Google system apps (if aapt2 fails)
    "com.google.android.googlequicksearchbox": "Google",
    "com.google.android.apps.tachyon": "Google Meet",
    "com.google.android.apps.docs.editors.docs": "Google Docs",
}

# aapt2 path detection
AAPT2_SEARCH_PATHS = [
    # Common Windows SDK locations
    os.path.expanduser(r"~\AppData\Local\Android\Sdk\build-tools"),
    r"C:\Android\Sdk\build-tools",
    # Common Linux/Mac SDK locations
    os.path.expanduser("~/Android/Sdk/build-tools"),
    os.path.expanduser("~/Library/Android/sdk/build-tools"),
]


class LabelLoader:
    """
    Manages app label loading from multiple sources with priority:
    1. Extracted labels (app_labels_map.txt) - HIGHEST priority
    2. Auto-extracted via aapt2 (for new apps)
    3. Disk cache (app_label_cache.json) — only trusted if app_labels_map.txt exists
    4. Batch dumpsys output
    5. Package name fallback - LOWEST priority
    """

    def __init__(self, adb=None) -> None:
        self.adb = adb
        self.label_cache: Dict[str, str] = {}
        self.extracted_labels: Dict[str, str] = {}
        self.cache_file = LABEL_CACHE_FILE
        self.extracted_file = EXTRACTED_LABELS_FILE
        self.aapt2_path: Optional[str] = None
        self._detect_aapt2()

    # ==========================================================
    # AAPT2 DETECTION
    # ==========================================================
    def _detect_aapt2(self) -> None:
        """Find aapt2 in Android SDK build-tools."""
        aapt2_in_path = shutil.which("aapt2")
        if aapt2_in_path:
            self.aapt2_path = aapt2_in_path
            return

        for base_path in AAPT2_SEARCH_PATHS:
            if not os.path.exists(base_path):
                continue
            try:
                versions = sorted(os.listdir(base_path), reverse=True)
                for version in versions:
                    if platform.system() == "Windows":
                        candidate = os.path.join(base_path, version, "aapt2.exe")
                    else:
                        candidate = os.path.join(base_path, version, "aapt2")
                    if os.path.exists(candidate):
                        self.aapt2_path = candidate
                        return
            except Exception:
                continue

    # ==========================================================
    # SINGLE APP EXTRACTION (used by both init and listener)
    # ==========================================================
    def extract_label_for_package(self, pkg: str) -> Optional[str]:
        """
        Extract the real label for a single package using aapt2.
        Pull APK -> aapt2 dump badging -> parse label.
        """
        if not self.aapt2_path or not self.adb:
            return None

        tmp_dir = os.path.join(tempfile.gettempdir(), "chiru_apk_extract")
        os.makedirs(tmp_dir, exist_ok=True)
        local_apk = os.path.join(tmp_dir, f"{pkg}.apk")

        try:
            # Get APK path on device
            apk_path_output = self.adb.run(["shell", "pm", "path", pkg])
            # Handle split APKs — take base.apk if available
            apk_path = None
            for line in apk_path_output.splitlines():
                line = line.strip().replace("package:", "")
                if line.endswith("base.apk") or apk_path is None:
                    apk_path = line
                    if line.endswith("base.apk"):
                        break

            if not apk_path:
                return None

            # Pull APK to temp (always fresh)
            if os.path.exists(local_apk):
                os.remove(local_apk)
            self.adb.run(["pull", apk_path, local_apk])

            # Run aapt2 dump badging
            # encoding="utf-8" + errors="replace" prevents Windows cp1252 crashes
            result = subprocess.run(
                [self.aapt2_path, "dump", "badging", local_apk],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", errors="replace"
            )

            if result.returncode != 0:
                return None

            # Parse application-label (first match = default locale)
            for line in result.stdout.splitlines():
                if line.startswith("application-label:"):
                    label = line.replace("application-label:", "").strip().strip("'\"")
                    if label:
                        return label

        except Exception:
            pass
        finally:
            # Cleanup temp APK
            try:
                if os.path.exists(local_apk):
                    os.remove(local_apk)
            except Exception:
                pass

        return None

    # ==========================================================
    # BATCH EXTRACTION (first launch — all apps)
    # ==========================================================
    def auto_extract_all_labels(self, packages: Set[str]) -> Dict[str, str]:
        """
        Extract labels for ALL given packages using aapt2.
        Used on first launch when app_labels_map.txt doesn't exist.
        """
        if not self.aapt2_path or not self.adb:
            print("⚠️ aapt2 not available — cannot extract labels")
            return {}

        total = len(packages)
        labels = {}
        failed = 0

        print(f"🔧 First launch: extracting labels for {total} apps via aapt2...")
        print(f"   aapt2: {self.aapt2_path}")
        print(f"   This is one-time only. Please wait...\n")

        for i, pkg in enumerate(sorted(packages), 1):
            if i % 10 == 0 or i == total:
                print(f"   [{i}/{total}] Extracting... ({len(labels)} found so far)")

            label = self.extract_label_for_package(pkg)
            if label:
                labels[pkg] = label
            else:
                failed += 1

        # Save to app_labels_map.txt
        if labels:
            self._write_extracted_file(labels)

        print(f"\n   ✅ Extraction complete!")
        print(f"      Labels found: {len(labels)}/{total}")
        print(f"      Failed/skipped: {failed}")
        print(f"      Saved to: {self.extracted_file}\n")

        return labels

    def auto_extract_labels(self, packages: Set[str]) -> Dict[str, str]:
        """Extract labels for a SUBSET of packages (new apps only)."""
        if not self.aapt2_path or not self.adb or not packages:
            return {}

        labels = {}
        print(f"🔧 Extracting labels for {len(packages)} new app(s)...")

        for pkg in packages:
            label = self.extract_label_for_package(pkg)
            if label:
                labels[pkg] = label

        if labels:
            self._append_to_extracted_file(labels)
            print(f"   ✅ Extracted {len(labels)} new label(s)")

        return labels

    # ==========================================================
    # EXTRACTED LABELS FILE (app_labels_map.txt)
    # ==========================================================
    def load_extracted_labels(self) -> int:
        """Load labels from app_labels_map.txt."""
        self.extracted_labels = {}

        if not os.path.exists(self.extracted_file):
            return 0

        try:
            with open(self.extracted_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            for line in lines:
                line = line.strip()
                if not line or line == "Label=Package":
                    continue
                if line.startswith("pull_failed=") or line.startswith("no_label="):
                    continue

                eq_idx = line.find("=")
                if eq_idx < 1:
                    continue

                label = line[:eq_idx].strip()
                package = line[eq_idx + 1:].strip()

                if label and package:
                    self.extracted_labels[package] = label

            return len(self.extracted_labels)

        except Exception as e:
            print(f"⚠️ Could not load extracted labels: {e}")
            return 0

    def _write_extracted_file(self, labels: Dict[str, str]) -> None:
        """Write complete app_labels_map.txt from scratch."""
        try:
            with open(self.extracted_file, "w", encoding="utf-8") as f:
                f.write("Label=Package\n")
                for pkg, label in sorted(labels.items(), key=lambda x: x[1].lower()):
                    f.write(f"{label}={pkg}\n")
        except Exception as e:
            print(f"⚠️ Could not write {self.extracted_file}: {e}")

    def _append_to_extracted_file(self, new_labels: Dict[str, str]) -> None:
        """Append new labels to existing app_labels_map.txt."""
        try:
            if not os.path.exists(self.extracted_file):
                with open(self.extracted_file, "w", encoding="utf-8") as f:
                    f.write("Label=Package\n")

            with open(self.extracted_file, "a", encoding="utf-8") as f:
                for pkg, label in new_labels.items():
                    f.write(f"{label}={pkg}\n")
        except Exception as e:
            print(f"⚠️ Could not append to {self.extracted_file}: {e}")

    # ==========================================================
    # DISK CACHE (app_label_cache.json)
    # ==========================================================
    def load_disk_cache(self) -> int:
        if not os.path.exists(self.cache_file):
            self.label_cache = {}
            return 0
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.label_cache = data.get("labels", {})
                return len(self.label_cache)
        except Exception as e:
            print(f"⚠️ Could not load label cache: {e}")
            self.label_cache = {}
            return 0

    def save_disk_cache(self) -> None:
        try:
            data = {
                "labels": self.label_cache,
                "last_updated": datetime.now().isoformat(),
                "count": len(self.label_cache),
            }
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Could not save label cache: {e}")

    # ==========================================================
    # BATCH DUMPSYS (fallback for apps aapt2 can't extract)
    # ==========================================================
    def batch_fetch_from_dumpsys(self, target_packages: Set[str] = None) -> Dict[str, str]:
        if not self.adb:
            return {}

        labels = {}
        try:
            print("🔍 Running batch dumpsys for remaining apps...")
            raw_output = self.adb.run(["shell", "dumpsys", "package"])
            current_pkg = None

            for line in raw_output.splitlines():
                line = line.strip()
                pkg_match = re.match(r'Package\s+\[([^\]]+)\]', line)
                if pkg_match:
                    current_pkg = pkg_match.group(1)
                    continue

                if current_pkg:
                    label_match = re.match(
                        r'application-label(?:-[a-zA-Z-]+)?:\s*(.+)', line
                    )
                    if label_match:
                        label = label_match.group(1).strip().strip("'\"")
                        if label:
                            if target_packages is None or current_pkg in target_packages:
                                if current_pkg not in labels:
                                    labels[current_pkg] = label
        except Exception as e:
            print(f"⚠️ Batch dumpsys failed: {e}")

        return labels

    # ==========================================================
    # PACKAGE NAME FALLBACK
    # ==========================================================
    @staticmethod
    def label_from_package_name(pkg: str) -> str:
        return (
            pkg.split(".")[-1]
            .replace("-", " ")
            .replace("_", " ")
            .title()
        )

    # ==========================================================
    # MERGED INITIALIZATION (with cache poisoning fix)
    # ==========================================================
    def initialize(self, current_packages: Set[str]) -> Dict[str, str]:
        """
        Build complete label map.
        
        FIRST LAUNCH (no app_labels_map.txt):
          - IGNORE old cache (it has bad fallback names)
          - Extract ALL labels via aapt2
          - Batch dumpsys for remainder
          - Package name fallback for rest
          - Save everything fresh
        
        SUBSEQUENT LAUNCHES (app_labels_map.txt exists):
          - Load extracted labels (highest priority)
          - Load disk cache (trusted now)
          - Extract only genuinely NEW apps
          - Batch dumpsys for uncovered
          - Package name fallback for rest
        """
        is_first_launch = not os.path.exists(self.extracted_file)

        if is_first_launch:
            # ==============================
            # FIRST LAUNCH PATH
            # ==============================
            # CRITICAL FIX: Do NOT load old disk cache.
            # Old cache contains bad fallback labels like
            # "Clockpackage", "Sbrowser", "Popupcalculator"
            # which would poison the label map.
            print("📋 No app_labels_map.txt found — first launch detected")

            if os.path.exists(self.cache_file):
                print("🗑️ Clearing old cache (may contain bad labels)...")
                self.label_cache = {}
                try:
                    os.remove(self.cache_file)
                except Exception:
                    pass

            if self.aapt2_path:
                all_labels = self.auto_extract_all_labels(current_packages)
                self.extracted_labels = all_labels
            else:
                print("⚠️ aapt2 not found — falling back to dumpsys only")
                self.extracted_labels = {}

            # Batch dumpsys for anything aapt2 missed
            extracted_set = set(self.extracted_labels.keys())
            uncovered = current_packages - extracted_set

            dumpsys_labels = {}
            if uncovered:
                dumpsys_labels = self.batch_fetch_from_dumpsys(uncovered)

            # Build final: extracted > KNOWN > dumpsys > fallback (NO old cache)
            final_labels: Dict[str, str] = {}
            for pkg in current_packages:
                if pkg in self.extracted_labels:
                    final_labels[pkg] = self.extracted_labels[pkg]
                elif pkg in KNOWN_LABELS:
                    final_labels[pkg] = KNOWN_LABELS[pkg]
                elif pkg in dumpsys_labels:
                    final_labels[pkg] = dumpsys_labels[pkg]
                else:
                    final_labels[pkg] = self.label_from_package_name(pkg)

            self.label_cache = final_labels
            self.save_disk_cache()
            return final_labels

        else:
            # ==============================
            # SUBSEQUENT LAUNCH PATH
            # ==============================
            # Load extracted labels first (highest priority)
            extracted_count = self.load_extracted_labels()
            if extracted_count > 0:
                print(f"📋 Loaded {extracted_count} APK-extracted labels")

            # Load disk cache (trusted because app_labels_map.txt exists)
            cache_count = self.load_disk_cache()
            if cache_count > 0:
                print(f"💾 Loaded {cache_count} cached labels")

            # Find genuinely NEW apps not in extracted file
            extracted_set = set(self.extracted_labels.keys())
            new_apps = current_packages - extracted_set

            if new_apps and self.aapt2_path:
                new_labels = self.auto_extract_labels(new_apps)
                self.extracted_labels.update(new_labels)

            # Uncovered after extraction
            extracted_set = set(self.extracted_labels.keys())
            cached_set = set(self.label_cache.keys())
            covered = extracted_set | cached_set
            uncovered = current_packages - covered

            dumpsys_labels = {}
            if uncovered:
                dumpsys_labels = self.batch_fetch_from_dumpsys(uncovered)

            # Build final: extracted > KNOWN > dumpsys > cache > fallback
            final_labels: Dict[str, str] = {}
            for pkg in current_packages:
                if pkg in self.extracted_labels:
                    final_labels[pkg] = self.extracted_labels[pkg]
                elif pkg in KNOWN_LABELS:
                    final_labels[pkg] = KNOWN_LABELS[pkg]
                elif pkg in dumpsys_labels:
                    final_labels[pkg] = dumpsys_labels[pkg]
                elif pkg in self.label_cache:
                    final_labels[pkg] = self.label_cache[pkg]
                else:
                    final_labels[pkg] = self.label_from_package_name(pkg)

            self.label_cache = final_labels
            self.save_disk_cache()
            return final_labels

    # ==========================================================
    # UTILITIES
    # ==========================================================
    def get_missing_labels(self, current_packages: Set[str]) -> Set[str]:
        missing = set()
        extracted_set = set(self.extracted_labels.keys())
        known_set = set(KNOWN_LABELS.keys())
        for pkg in current_packages:
            if pkg in extracted_set or pkg in known_set:
                continue
            label = self.label_cache.get(pkg, "")
            fallback = self.label_from_package_name(pkg)
            if label == fallback:
                missing.add(pkg)
        return missing

    def clear_cache(self) -> None:
        self.label_cache = {}
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)
            print("🗑️ Label cache cleared")

    def clear_all(self) -> None:
        """Clear both cache and extracted labels (full reset)."""
        self.clear_cache()
        self.extracted_labels = {}
        if os.path.exists(self.extracted_file):
            os.remove(self.extracted_file)
            print("🗑️ Extracted labels file removed")


# ==============================================================
# BACKGROUND INSTALL LISTENER (polling — works on ALL devices)
# ==============================================================

class PackageInstallListener:
    """
    Background thread that polls for new/removed apps.
    
    Why polling instead of logcat?
    - logcat patterns vary across Android versions and manufacturers
    - Samsung, Pixel, OnePlus all log install events differently
    - Polling is 100% reliable on every device
    
    How it works:
    - Every 10 seconds, runs 'cmd package query-activities' (~200ms)
    - Compares against known package set
    - New packages -> extract label via aapt2 -> update cache
    - Removed packages -> clean up cache
    - Zero impact on main thread (daemon thread)
    """

    def __init__(
        self,
        adb,
        label_loader: LabelLoader,
        on_change: Optional[Callable[[str, str, str], None]] = None,
        poll_interval: int = 10,
    ) -> None:
        self.adb = adb
        self.label_loader = label_loader
        self.on_change = on_change
        self.poll_interval = poll_interval
        self._known_packages: Set[str] = set()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self, initial_packages: Set[str]) -> None:
        """Start polling for package changes."""
        if self._running:
            return
        self._known_packages = set(initial_packages)
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _get_current_packages(self) -> Set[str]:
        """Get currently installed launchable packages."""
        try:
            out = self.adb.run(
                [
                    "shell", "cmd", "package", "query-activities",
                    "--brief", "-a", "android.intent.action.MAIN",
                    "-c", "android.intent.category.LAUNCHER",
                ]
            )
            pkgs = set()
            for line in out.splitlines():
                line = line.strip()
                if "/" in line:
                    pkgs.add(line.split("/")[0])
            return pkgs
        except Exception:
            return self._known_packages

    def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            time.sleep(self.poll_interval)
            if not self._running:
                break

            try:
                current = self._get_current_packages()

                added = current - self._known_packages
                for pkg in added:
                    self._handle_install(pkg)

                removed = self._known_packages - current
                for pkg in removed:
                    self._handle_uninstall(pkg)

                self._known_packages = current

            except Exception:
                pass  # Don't crash background thread

    def _handle_install(self, pkg: str) -> None:
        """Handle a newly installed package."""
        print(f"\n📲 New app detected: {pkg}")

        # Wait for installation to fully complete
        time.sleep(2)

        label = self.label_loader.extract_label_for_package(pkg)

        if label:
            print(f"   ✅ Label: {label}")
            self.label_loader.extracted_labels[pkg] = label
            self.label_loader._append_to_extracted_file({pkg: label})
            self.label_loader.label_cache[pkg] = label
            self.label_loader.save_disk_cache()
        else:
            fallback = LabelLoader.label_from_package_name(pkg)
            label = fallback
            print(f"   ⚠️ Could not extract label, using: {fallback}")
            self.label_loader.label_cache[pkg] = fallback
            self.label_loader.save_disk_cache()

        if self.on_change:
            self.on_change("installed", pkg, label)

    def _handle_uninstall(self, pkg: str) -> None:
        """Handle a removed package."""
        label = self.label_loader.label_cache.pop(pkg, pkg)
        self.label_loader.extracted_labels.pop(pkg, None)
        self.label_loader.save_disk_cache()
        print(f"\n🗑️ App removed: {pkg} ({label})")

        if self.on_change:
            self.on_change("removed", pkg, label)
