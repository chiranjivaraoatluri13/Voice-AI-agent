# =========================
# FILE: agent/voice_overlay.py
# =========================
"""
Floating always-on-top microphone overlay.

Tkinter runs exclusively on the main thread. VoiceSession callbacks arrive on
the listener thread, so every public setter only enqueues work; a short
`root.after` poll drains the queue and paints. Touching tk from another thread
is what freezes or crashes the overlay on Windows.
"""

from __future__ import annotations

import json
import math
import queue
import time
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional, Tuple

from agent.voice_session import VoiceState

# Key colour punched out by -transparentcolor so the rounded panel floats.
_TRANSPARENT = "#010203"

_COMPACT = (96, 96)
_EXPANDED = (340, 170)
_AUTO_COLLAPSE_MS = 6000
_POLL_MS = 40
_ANIM_MS = 40
_DRAG_THRESHOLD = 4
_BUSY_STALL_S = 8.0

_POS_FILE = Path(__file__).resolve().parent.parent / ".voice_overlay.json"

# State → (glyph, fill, ring)
_PALETTE = {
    VoiceState.STARTING: ("#94a3b8", "#1e293b", None),
    VoiceState.OFF: ("#64748b", "#1e293b", None),
    VoiceState.LISTENING: ("#22c55e", "#052e16", "#22c55e"),
    VoiceState.SPEECH: ("#4ade80", "#052e16", "#4ade80"),
    VoiceState.TRANSCRIBING: ("#38bdf8", "#0c4a6e", "#38bdf8"),
    VoiceState.BUSY: ("#6366f1", "#1e1b4b", "#6366f1"),
    VoiceState.ERROR: ("#ef4444", "#450a0a", "#ef4444"),
}

_STATUS_LABEL = {
    VoiceState.STARTING: "Connecting…",
    VoiceState.OFF: "Mic off — click to talk",
    VoiceState.LISTENING: "Listening…",
    VoiceState.SPEECH: "Hearing you…",
    VoiceState.TRANSCRIBING: "Transcribing…",
    VoiceState.BUSY: "Working…",
    VoiceState.ERROR: "Error",
}


def _rounded_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
    **kwargs,
) -> int:
    """Draw a rounded rectangle as a single polygon (no ttk dependency)."""
    r = max(0.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class MicOverlay:
    """Compact / expanded floating mic button for the voice front-end."""

    def __init__(
        self,
        on_toggle: Optional[Callable[[], None]] = None,
        on_text_command: Optional[Callable[[str], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_toggle = on_toggle
        self._on_text_command = on_text_command
        self._on_quit = on_quit

        self._queue: queue.Queue = queue.Queue()
        self._closed = False
        self._ready = False
        self._mode = "compact"
        self._pinned = False
        self._state = VoiceState.STARTING
        self._level = 0.0
        self._status = _STATUS_LABEL[VoiceState.STARTING]
        self._transcript = ""
        self._message_kind = "info"
        self._anim_t = 0.0
        self._busy_since: Optional[float] = None
        self._collapse_after_id: Optional[str] = None

        self._drag_armed = False
        self._dragging = False
        self._drag_origin = (0, 0)
        self._win_origin = (0, 0)
        self._press_on_mic = False

        self.root = tk.Tk()
        self.root.title("Voice Agent")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.93)
        except tk.TclError:
            pass

        self._transparent = False
        try:
            self.root.configure(bg=_TRANSPARENT)
            self.root.wm_attributes("-transparentcolor", _TRANSPARENT)
            self._transparent = True
        except tk.TclError:
            self.root.configure(bg="#0f172a")

        self.canvas = tk.Canvas(
            self.root,
            width=_COMPACT[0],
            height=_COMPACT[1],
            highlightthickness=0,
            bd=0,
            bg=_TRANSPARENT if self._transparent else "#0f172a",
        )
        self.canvas.pack(fill="both", expand=True)

        # Entry lives in expanded mode only; created once, shown/hidden.
        self._entry_var = tk.StringVar()
        self._entry = tk.Entry(
            self.root,
            textvariable=self._entry_var,
            font=("Segoe UI", 10),
            bg="#1e293b",
            fg="#e2e8f0",
            insertbackground="#e2e8f0",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#334155",
            highlightcolor="#38bdf8",
        )
        self._entry.bind("<Return>", self._on_entry_return)
        self._entry_window: Optional[int] = None

        self._menu = tk.Menu(
            self.root,
            tearoff=0,
            bg="#1e293b",
            fg="#e2e8f0",
            activebackground="#334155",
            activeforeground="#f8fafc",
            font=("Segoe UI", 9),
        )
        self._menu.add_command(label="Start", command=self._menu_start)
        self._menu.add_command(label="Stop", command=self._menu_stop)
        self._menu.add_separator()
        self._menu.add_command(label="Expand", command=lambda: self._set_mode("expanded"))
        self._menu.add_command(label="Compact", command=lambda: self._set_mode("compact"))
        self._menu.add_separator()
        self._menu.add_command(label="Reset position", command=self._reset_position)
        self._menu.add_command(label="Quit", command=self._request_quit)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<ButtonPress-3>", self._on_right)
        self.root.bind("<Escape>", lambda _e: self._request_quit())

        self._place_initial()
        self._redraw()
        self.root.after(_POLL_MS, self._poll)
        self.root.after(_ANIM_MS, self._tick)

    # ------------------------------------------------------------------
    # Public API (thread-safe — enqueue only)
    # ------------------------------------------------------------------
    def set_state(self, state: VoiceState, detail: str = "") -> None:
        self._queue.put(("state", state, detail))

    def set_level(self, level: float) -> None:
        self._queue.put(("level", float(level)))

    def set_message(self, kind: str, text: str) -> None:
        self._queue.put(("message", kind, text))

    def set_ready(self, ready: bool = True) -> None:
        self._queue.put(("ready", bool(ready)))

    def close(self) -> None:
        self._queue.put(("close",))

    def run(self) -> None:
        """Blocking tk mainloop — call from the main thread only."""
        try:
            self.root.mainloop()
        finally:
            self._closed = True

    # ------------------------------------------------------------------
    # Queue drain / animation
    # ------------------------------------------------------------------
    def _poll(self) -> None:
        if self._closed:
            return
        try:
            while True:
                item = self._queue.get_nowait()
                self._apply(item)
        except queue.Empty:
            pass
        if not self._closed:
            self.root.after(_POLL_MS, self._poll)

    def _apply(self, item: tuple) -> None:
        kind = item[0]
        if kind == "state":
            _, state, detail = item
            self._state = state
            if state == VoiceState.BUSY:
                if self._busy_since is None:
                    self._busy_since = time.monotonic()
            else:
                self._busy_since = None
            label = _STATUS_LABEL.get(state, str(state))
            if detail and state in (VoiceState.ERROR, VoiceState.BUSY, VoiceState.LISTENING):
                if state == VoiceState.BUSY and detail:
                    self._transcript = detail
                elif state == VoiceState.ERROR:
                    self._status = detail or label
                elif state == VoiceState.LISTENING and detail:
                    self._status = f"Listening on {detail}"
                else:
                    self._status = label
            else:
                self._status = label
            self._redraw()
        elif kind == "level":
            self._level = max(0.0, min(1.0, item[1]))
        elif kind == "message":
            _, msg_kind, text = item
            self._message_kind = msg_kind
            text = (text or "").strip()
            if not text:
                return
            if msg_kind in ("heard", "transcript"):
                self._transcript = text.strip('"')
                self._status = "Heard"
                self._auto_expand()
            elif msg_kind == "error":
                self._status = text
                self._auto_expand()
            elif msg_kind == "warn":
                self._status = text
                self._auto_expand()
            else:
                self._status = text
            self._redraw()
        elif kind == "ready":
            self._ready = item[1]
            if self._ready and self._state == VoiceState.STARTING:
                self._state = VoiceState.OFF
                self._status = _STATUS_LABEL[VoiceState.OFF]
            self._redraw()
        elif kind == "close":
            self._destroy()

    def _tick(self) -> None:
        if self._closed:
            return
        self._anim_t += _ANIM_MS / 1000.0
        # Stall hint while the agent sits on a blocking prompt.
        if (
            self._state == VoiceState.BUSY
            and self._busy_since is not None
            and (time.monotonic() - self._busy_since) >= _BUSY_STALL_S
        ):
            stall = "Still working — check the terminal, it may be asking a question."
            if self._status != stall:
                self._status = stall
                self._auto_expand()
        self._redraw()
        if not self._closed:
            self.root.after(_ANIM_MS, self._tick)

    # ------------------------------------------------------------------
    # Geometry / persistence
    # ------------------------------------------------------------------
    def _place_initial(self) -> None:
        w, h = _COMPACT
        x, y = self._load_position(w, h)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _load_position(self, w: int, h: int) -> Tuple[int, int]:
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        default = (sw - w - 24, sh - h - 80)
        try:
            data = json.loads(_POS_FILE.read_text(encoding="utf-8"))
            x, y = int(data["x"]), int(data["y"])
        except Exception:
            return default
        return self._clamp(x, y, w, h)

    def _save_position(self) -> None:
        try:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            _POS_FILE.write_text(
                json.dumps({"x": x, "y": y}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _clamp(self, x: int, y: int, w: int, h: int) -> Tuple[int, int]:
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        return x, y

    def _reset_position(self) -> None:
        w = self.root.winfo_width() or _COMPACT[0]
        h = self.root.winfo_height() or _COMPACT[1]
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = sw - w - 24, sh - h - 80
        self.root.geometry(f"+{x}+{y}")
        self._save_position()

    def _set_mode(self, mode: str, pinned: Optional[bool] = None) -> None:
        if mode not in ("compact", "expanded"):
            return
        if pinned is not None:
            self._pinned = pinned
        self._mode = mode
        w, h = _EXPANDED if mode == "expanded" else _COMPACT
        x, y = self._clamp(self.root.winfo_x(), self.root.winfo_y(), w, h)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas.config(width=w, height=h)
        self._redraw()
        self._save_position()

    def _auto_expand(self) -> None:
        if self._mode != "expanded":
            self._set_mode("expanded")
        if self._pinned:
            return
        if self._collapse_after_id is not None:
            try:
                self.root.after_cancel(self._collapse_after_id)
            except Exception:
                pass
        self._collapse_after_id = self.root.after(
            _AUTO_COLLAPSE_MS, self._auto_collapse
        )

    def _auto_collapse(self) -> None:
        self._collapse_after_id = None
        if not self._pinned and self._mode == "expanded":
            self._set_mode("compact")

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def _redraw(self) -> None:
        if self._closed:
            return
        self.canvas.delete("all")
        if self._mode == "compact":
            self._draw_compact()
        else:
            self._draw_expanded()

    def _draw_compact(self) -> None:
        w, h = _COMPACT
        cx, cy = w / 2, h / 2
        self._draw_mic_button(cx, cy, radius=34)

    def _draw_expanded(self) -> None:
        w, h = _EXPANDED
        pad = 10
        _rounded_rect(
            self.canvas,
            pad,
            pad,
            w - pad,
            h - pad,
            radius=18,
            fill="#0f172a",
            outline="#1e293b",
            width=2,
        )
        # Mic on the left.
        self._draw_mic_button(48, h / 2 - 8, radius=28)

        pin = "📌" if self._pinned else ""
        self.canvas.create_text(
            90,
            28,
            text=f"{self._status} {pin}".strip(),
            anchor="w",
            fill="#e2e8f0",
            font=("Segoe UI", 10, "bold"),
            width=220,
        )
        transcript = self._transcript or "—"
        self.canvas.create_text(
            90,
            58,
            text=transcript[:80],
            anchor="w",
            fill="#94a3b8",
            font=("Segoe UI", 9),
            width=220,
        )
        # Type-to-command field.
        if self._entry_window is not None:
            try:
                self.canvas.delete(self._entry_window)
            except Exception:
                pass
        self._entry_window = self.canvas.create_window(
            90,
            h - 42,
            window=self._entry,
            anchor="w",
            width=220,
            height=26,
        )

    def _draw_mic_button(self, cx: float, cy: float, radius: float) -> None:
        glyph, fill, ring = _PALETTE.get(
            self._state, _PALETTE[VoiceState.OFF]
        )
        # Soft outer disc.
        self.canvas.create_oval(
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
            fill=fill,
            outline="#1e293b",
            width=2,
        )
        self._draw_ring(cx, cy, radius, ring)
        self._draw_mic_glyph(cx, cy, glyph, scale=radius / 34.0)

    def _draw_ring(
        self,
        cx: float,
        cy: float,
        radius: float,
        color: Optional[str],
    ) -> None:
        if not color:
            return
        t = self._anim_t
        state = self._state
        r = radius + 4

        if state == VoiceState.LISTENING:
            # Slow breath.
            pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * 2.2))
            width = 2 + 2 * pulse
            self.canvas.create_oval(
                cx - r,
                cy - r,
                cx + r,
                cy + r,
                outline=color,
                width=width,
            )
        elif state == VoiceState.SPEECH:
            # Level-reactive ring.
            pulse = 0.4 + 0.6 * max(0.0, min(1.0, self._level))
            rr = r + 6 * pulse
            self.canvas.create_oval(
                cx - rr,
                cy - rr,
                cx + rr,
                cy + rr,
                outline=color,
                width=2 + 3 * pulse,
            )
        elif state in (VoiceState.TRANSCRIBING, VoiceState.BUSY):
            self._draw_arc(cx, cy, r + 2, color, t * (220 if state == VoiceState.BUSY else 280))
        elif state == VoiceState.STARTING:
            pulse = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 1.4))
            self.canvas.create_oval(
                cx - r,
                cy - r,
                cx + r,
                cy + r,
                outline="#64748b",
                width=1 + pulse,
            )
        elif state == VoiceState.ERROR:
            self.canvas.create_oval(
                cx - r,
                cy - r,
                cx + r,
                cy + r,
                outline=color,
                width=3,
            )

    def _draw_arc(
        self,
        cx: float,
        cy: float,
        r: float,
        color: str,
        deg_per_s: float,
    ) -> None:
        # Tk arcs use degrees; start rotates so the gap travels around.
        start = (self._anim_t * deg_per_s) % 360.0
        self.canvas.create_arc(
            cx - r,
            cy - r,
            cx + r,
            cy + r,
            start=start,
            extent=110,
            style=tk.ARC,
            outline=color,
            width=3,
        )

    def _draw_mic_glyph(
        self,
        cx: float,
        cy: float,
        color: str,
        scale: float = 1.0,
    ) -> None:
        s = scale
        # Capsule body.
        bw, bh = 7 * s, 14 * s
        top, bot = cy - 10 * s, cy + 4 * s
        self.canvas.create_oval(
            cx - bw,
            top,
            cx + bw,
            top + 2 * bw,
            fill=color,
            outline="",
        )
        self.canvas.create_oval(
            cx - bw,
            bot - 2 * bw,
            cx + bw,
            bot,
            fill=color,
            outline="",
        )
        self.canvas.create_rectangle(
            cx - bw,
            top + bw,
            cx + bw,
            bot - bw,
            fill=color,
            outline="",
        )
        # Cradle (U).
        cradle_r = 12 * s
        self.canvas.create_arc(
            cx - cradle_r,
            cy - 6 * s,
            cx + cradle_r,
            cy + 14 * s,
            start=200,
            extent=140,
            style=tk.ARC,
            outline=color,
            width=max(2, int(2.5 * s)),
        )
        # Stand + base.
        self.canvas.create_line(
            cx,
            cy + 12 * s,
            cx,
            cy + 18 * s,
            fill=color,
            width=max(2, int(2.5 * s)),
        )
        self.canvas.create_line(
            cx - 8 * s,
            cy + 18 * s,
            cx + 8 * s,
            cy + 18 * s,
            fill=color,
            width=max(2, int(2.5 * s)),
        )

    # ------------------------------------------------------------------
    # Pointer / menu
    # ------------------------------------------------------------------
    def _hit_mic(self, x: int, y: int) -> bool:
        if self._mode == "compact":
            cx, cy, r = _COMPACT[0] / 2, _COMPACT[1] / 2, 40
        else:
            cx, cy, r = 48, _EXPANDED[1] / 2 - 8, 34
        return (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2

    def _on_press(self, event: tk.Event) -> None:
        self._drag_armed = True
        self._dragging = False
        self._drag_origin = (event.x_root, event.y_root)
        self._win_origin = (self.root.winfo_x(), self.root.winfo_y())
        self._press_on_mic = self._hit_mic(event.x, event.y)

    def _on_motion(self, event: tk.Event) -> None:
        if not self._drag_armed:
            return
        dx = event.x_root - self._drag_origin[0]
        dy = event.y_root - self._drag_origin[1]
        if not self._dragging:
            if abs(dx) < _DRAG_THRESHOLD and abs(dy) < _DRAG_THRESHOLD:
                return
            self._dragging = True
        x = self._win_origin[0] + dx
        y = self._win_origin[1] + dy
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x, y = self._clamp(x, y, w, h)
        self.root.geometry(f"+{x}+{y}")

    def _on_release(self, event: tk.Event) -> None:
        was_drag = self._dragging
        on_mic = self._press_on_mic
        self._drag_armed = False
        self._dragging = False
        self._press_on_mic = False
        if was_drag:
            self._save_position()
            return
        # Compact: whole surface toggles. Expanded: only the mic disc.
        if self._mode == "compact" or on_mic:
            if self._on_toggle:
                try:
                    self._on_toggle()
                except Exception:
                    pass

    def _on_double(self, _event: tk.Event) -> None:
        # Pin keeps the panel expanded so transcripts stay visible.
        if self._mode == "compact":
            self._set_mode("expanded", pinned=True)
        else:
            self._pinned = not self._pinned
            if not self._pinned:
                self._auto_expand()  # schedule collapse from now
            self._redraw()

    def _on_right(self, event: tk.Event) -> None:
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _on_entry_return(self, _event: tk.Event) -> None:
        text = self._entry_var.get().strip()
        if not text:
            return
        self._entry_var.set("")
        self._transcript = text
        self._status = "Typed"
        self._redraw()
        if self._on_text_command:
            try:
                self._on_text_command(text)
            except Exception:
                pass

    def _menu_start(self) -> None:
        # Toggle only starts when currently off — callers own the real state.
        if self._on_toggle and self._state in (
            VoiceState.OFF,
            VoiceState.ERROR,
            VoiceState.STARTING,
        ):
            try:
                self._on_toggle()
            except Exception:
                pass

    def _menu_stop(self) -> None:
        if self._on_toggle and self._state in (
            VoiceState.LISTENING,
            VoiceState.SPEECH,
            VoiceState.TRANSCRIBING,
            VoiceState.BUSY,
        ):
            try:
                self._on_toggle()
            except Exception:
                pass

    def _request_quit(self) -> None:
        if self._on_quit:
            try:
                self._on_quit()
            except Exception:
                pass
        self._destroy()

    def _destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._save_position()
        try:
            self.root.quit()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
