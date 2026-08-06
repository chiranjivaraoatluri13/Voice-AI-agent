# =========================
# FILE: agent/gemini_models.py
# =========================
"""Shared Gemini model selection + transient-error fallbacks."""

from __future__ import annotations

import os
from typing import Iterable, List, Optional

DEFAULT_MODEL = "gemini-3.6-flash"

# Tried in order when the preferred model is overloaded / unavailable.
_FALLBACK_CHAIN = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
)


def preferred_model(*overrides: Optional[str]) -> str:
    for value in overrides:
        if value:
            return value
    return (
        os.environ.get("GEMINI_VISION_MODEL")
        or os.environ.get("GEMINI_MODEL")
        or DEFAULT_MODEL
    )


def model_candidates(preferred: Optional[str] = None) -> List[str]:
    """Ordered unique model IDs to try for a request."""
    primary = preferred_model(preferred)
    out: List[str] = [primary]
    extra = os.environ.get("GEMINI_MODEL_FALLBACKS", "")
    for item in list(_FALLBACK_CHAIN) + [x.strip() for x in extra.split(",") if x.strip()]:
        if item and item not in out:
            out.append(item)
    return out


def build_client(api_key: str, timeout_s: Optional[float] = None):
    """
    Create a genai Client with a hard request timeout.

    Without one, an overloaded model can stall a call indefinitely — that is
    what turned a startup vision warmup into a ~54s block.
    """
    from google import genai

    if timeout_s is None:
        timeout_s = float(os.environ.get("GEMINI_TIMEOUT_S", "20"))
    try:
        from google.genai import types
        return genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
        )
    except Exception:
        # Older SDKs don't accept http_options — fall back to the plain client.
        return genai.Client(api_key=api_key)


def is_transient_model_error(err: object) -> bool:
    """True for capacity / rate / temporary Gemini failures worth retrying."""
    t = str(err or "").lower()
    needles = (
        "503",
        "unavailable",
        "high demand",
        "overloaded",
        "429",
        "rate limit",
        "resource_exhausted",
        "resource exhausted",
        "too many requests",
        "try again later",
        "temporarily",
    )
    return any(n in t for n in needles)
