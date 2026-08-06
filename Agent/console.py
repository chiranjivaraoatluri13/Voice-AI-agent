# =========================
# FILE: agent/console.py
# =========================
"""
Console output coordination for the interactive CLI.

Background threads (the vision watcher, model fallbacks, the package install
listener) used to write straight to stdout while the user was part-way through
typing at the `> ` prompt. That does more than look untidy: the console keeps
the partially typed text in its line-edit buffer, so an interleaved write
corrupts the display while the buffer quietly retains the fragment. It then
gets submitted along with whatever is typed next — which is how "v" followed by
"view picture" reached the agent as "vview picture", and "click" plus "like the
video" arrived as "cllike".

So while the prompt is waiting for input, background chatter is held back:
progress messages are dropped and anything important is deferred until the user
has actually submitted a line.
"""

import threading
from typing import List


class Console:
    """Serializes stdout so background threads never interrupt typing."""

    MAX_PENDING = 8

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._at_prompt = False
        self._pending: List[str] = []
        self._dropped = 0

    # -- prompt lifecycle -------------------------------------------------
    def begin_prompt(self) -> None:
        with self._lock:
            self._at_prompt = True

    def end_prompt(self) -> None:
        """Leave the prompt and release anything held back while typing."""
        with self._lock:
            self._at_prompt = False
            pending, self._pending = self._pending, []
            self._dropped = 0
        for line in pending:
            self._write(line)

    # -- output -----------------------------------------------------------
    def status(self, message: str) -> None:
        """Progress chatter — dropped outright while the user is typing."""
        with self._lock:
            if self._at_prompt:
                self._dropped += 1
                return
        self._write(message)

    def notice(self, message: str) -> None:
        """Worth seeing — deferred rather than dropped while typing."""
        with self._lock:
            if self._at_prompt:
                if (message not in self._pending
                        and len(self._pending) < self.MAX_PENDING):
                    self._pending.append(message)
                return
        self._write(message)

    @staticmethod
    def _write(message: str) -> None:
        try:
            print(message, flush=True)
        except UnicodeEncodeError:
            # Windows consoles on a non-UTF-8 code page choke on the emoji.
            print(message.encode("ascii", "replace").decode("ascii"), flush=True)


CONSOLE = Console()
