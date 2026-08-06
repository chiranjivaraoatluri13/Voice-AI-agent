# =========================
# FILE: agent/parallel.py
# =========================
"""
Parallel Processing Pipeline for Voice Agent.

Groq NLU is the authority for understanding commands.
TF-IDF is only a cheap hint for speculative screen pre-fetch.

Architecture:
  1. Fire Groq NLU immediately (true natural language understanding).
  2. In parallel, optionally pre-fetch UI tree / screenshot (ADB),
     using a TF-IDF hint so we don't block Groq on USB I/O.
  3. Execute with Groq's command; inject pre-fetched screen data when useful.

This avoids TF-IDF/hardcoded shortcuts causing mismatches on conversational
commands like "my eyes are paining" or "I am unable to hear anything".
"""

import time
import concurrent.futures
from typing import Optional
from dataclasses import dataclass, field


# Actions that benefit from screen data (UI tree dump and/or screenshot).
SCREEN_ACTIONS = frozenset({
    "VISION_QUERY",
    "FIND_VISUAL",
    "SCREEN_INFO",
    "SEARCH_IN_APP",
    "INSTALL_APP",
    "SEND_MESSAGE",
    "TYPE_AND_SEND",
    "TAP_SEND",
    "APP_ACTION",
    "OPEN_CONTENT_IN_APP",
    "SKIP_AD",
})


@dataclass
class ScreenPreFetchResult:
    """Holds pre-fetched screen state captured speculatively during NLU."""
    ui_elements: list = field(default_factory=list)
    screenshot_b64: str = ""
    capture_time: float = 0.0
    success: bool = False


def _prefetch_ui_tree(ui_analyzer) -> list:
    """Reuse the watcher's fresh UI tree; only pay for ADB when it's stale."""
    try:
        cached = ui_analyzer.get_cached_elements()
        if cached:
            return cached
        # Single attempt: this runs speculatively while NLU is still deciding,
        # and retrying a stuck dump here stalls the command outright. If it
        # misses, the executing handler captures again with full retries.
        ui_analyzer.capture_ui_tree(force_refresh=True, attempts=1)
        return ui_analyzer.last_elements.copy()
    except Exception as e:
        print(f"  ⚠️ Pre-fetch UI tree failed: {e}")
        return []


def _prefetch_screenshot(vision) -> str:
    """Capture screenshot as base64 via ADB (serialized through AdbClient._lock)."""
    try:
        return vision.capture_screenshot_b64()
    except Exception as e:
        print(f"  ⚠️ Pre-fetch screenshot failed: {e}")
        return ""


def speculative_prefetch(ui_analyzer, vision, fetch_screenshot: bool = False) -> ScreenPreFetchResult:
    """
    Capture UI tree and optionally screenshot while Groq NLU runs.
    """
    result = ScreenPreFetchResult()
    t0 = time.perf_counter()

    result.ui_elements = _prefetch_ui_tree(ui_analyzer)

    if fetch_screenshot and vision:
        result.screenshot_b64 = _prefetch_screenshot(vision)

    result.capture_time = (time.perf_counter() - t0) * 1000
    result.success = bool(result.ui_elements) or bool(result.screenshot_b64)
    return result


def process_command_parallel(
    utterance: str,
    engine,       # IntentEngine
    screen,       # ScreenController
    device,       # DeviceController
    apps,         # AppResolver
    learner,      # CommandLearner
    adb,          # AdbClient
    current_app: str = "",
    execute_fn=None,  # execute_command function reference
):
    """
    Process a voice command with Groq-first NLU + parallel screen pre-fetch.

    Returns:
        The Command object (or None if not understood).
    """
    raw = utterance.strip()
    if not raw:
        return None

    t_start = time.perf_counter()

    # Background watcher owns ADB while idle; hand the bus to the command now
    # or the foreground prefetch queues behind it on AdbClient._lock.
    vision = getattr(screen, "vision", None)
    if vision is not None:
        try:
            vision.pause_watching()
        except Exception:
            pass

    # TF-IDF is ONLY a prefetch hint — never the final action decision
    needs_screen, needs_screenshot = engine.prefetch_hint(raw)

    stats_before = dict(getattr(engine, "stats", {}) or {})

    prefetch_result = None
    cmd = None
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    try:
        nlu_future = pool.submit(engine.understand, raw, current_app)

        prefetch_future = None
        if needs_screen:
            prefetch_future = pool.submit(
                speculative_prefetch,
                screen.ui_analyzer,
                screen.vision,
                needs_screenshot,
            )

        # Always wait for Groq / understand — it is the authority
        cmd = nlu_future.result(timeout=15)

        # Only collect prefetch if the final action actually needs the screen
        if cmd and cmd.action in SCREEN_ACTIONS and prefetch_future is not None:
            try:
                # Must outlast a single dump. Abandoning one mid-flight doesn't
                # free the ADB lock, so the handler's own capture just queued
                # behind it and the command paid for two dumps instead of one.
                prefetch_result = prefetch_future.result(timeout=17)
            except Exception as e:
                print(f"  ⚠️ Prefetch wait failed: {e}")
                prefetch_result = None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    elapsed = (time.perf_counter() - t_start) * 1000
    try:
        if cmd:
            prefetch_ms = prefetch_result.capture_time if prefetch_result else 0
            mode = _nlu_mode(stats_before, getattr(engine, "stats", {}) or {})
            if prefetch_result and prefetch_result.success:
                mode += "+prefetch"
            _log_parallel(cmd.action, mode, elapsed, prefetch_ms)
            if cmd.action in SCREEN_ACTIONS and prefetch_result and prefetch_result.success:
                _inject_prefetch(screen, prefetch_result)
            if execute_fn:
                execute_fn(cmd, device, apps, learner, screen, adb, current_app, engine)
        return cmd
    finally:
        if vision is not None:
            try:
                vision.resume_watching()
            except Exception:
                pass


def _inject_prefetch(screen, prefetch: ScreenPreFetchResult) -> None:
    """Inject pre-fetched screen data into ScreenController."""
    if prefetch.ui_elements:
        screen.ui_analyzer.last_elements = prefetch.ui_elements
        screen.ui_analyzer._cached_elements = prefetch.ui_elements.copy()
        screen.ui_analyzer._cache_timestamp = time.time()
        screen.ui_analyzer._cache_generation = getattr(
            screen.adb, "screen_generation", 0
        )

    if prefetch.screenshot_b64:
        screen.vision._last_screenshot_b64 = prefetch.screenshot_b64
        screen.vision._last_screenshot_time = time.time()

    screen.mark_prefetch_fresh()


def _nlu_mode(before: dict, after: dict) -> str:
    """Report which tier actually classified, instead of always claiming Groq."""
    for key, label in (
        ("tier2", "groq"),
        ("cache_hit", "cache"),
        ("tier1", "tfidf"),
    ):
        if after.get(key, 0) > before.get(key, 0):
            return label
    return "fast-path"


def _log_parallel(action: str, mode: str, total_ms: float, prefetch_ms: float) -> None:
    """Log parallel pipeline timing."""
    try:
        print(f"  ⚡ [{mode}] {action} in {total_ms:.0f}ms (prefetch: {prefetch_ms:.0f}ms)")
    except UnicodeEncodeError:
        print(f"  [parallel] [{mode}] {action} in {total_ms:.0f}ms (prefetch: {prefetch_ms:.0f}ms)")
