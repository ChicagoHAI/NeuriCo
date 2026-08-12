"""Small terminal-native input surface with ordinary scrollback.

The composer owns exactly two live rows: a status row and a single-line input
row.  Durable output is always printed above those rows and is never repainted.
"""

from __future__ import annotations

import os
import select
import shutil
import sys
import termios
import threading
import tty
from collections.abc import Callable, Iterable
from typing import Optional, TextIO


_RESET = "\x1b[0m"
_MINT = "\x1b[1;38;5;115m"
_MUTED = "\x1b[38;5;246m"
_CLEAR_LINE = "\x1b[2K"


class NativeTerminalComposer:
    """Read one editable line while preserving native terminal scrollback."""

    def __init__(
        self,
        *,
        output: TextIO,
        lock: threading.RLock,
        status: Callable[[], tuple[str, str]],
    ) -> None:
        self._output = output
        self._lock = lock
        self._status = status
        self._active = False
        self._closed = threading.Event()
        self._buffer: list[str] = []
        self._cursor = 0
        self._prompt = "› "
        self._history: list[str] = []
        self._history_index: Optional[int] = None
        self._history_draft = ""
        self._input_bytes = b""
        self._paste_mode = False
        self._last_width = 0
        self._last_status = ("", "")

    @property
    def active(self) -> bool:
        return self._active

    def add_history(self, value: str) -> None:
        text = str(value).strip()
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)

    def close(self) -> None:
        self._closed.set()

    def refresh(self) -> None:
        with self._lock:
            if self._active:
                self._erase_locked()
                self._draw_locked()

    def write_block(self, lines: Iterable[str], *, blank_before: bool = False) -> None:
        rendered = list(lines)
        if not rendered:
            return
        with self._lock:
            if self._active:
                self._erase_locked()
            if blank_before:
                print(file=self._output)
            for line in rendered:
                print(line, file=self._output)
            if self._active:
                self._draw_locked()
            self._output.flush()

    def readline(self, prompt: str = "› ") -> str:
        if not sys.stdin.isatty():
            value = sys.stdin.readline()
            if value == "":
                raise EOFError
            return value.rstrip("\n")

        fd = sys.stdin.fileno()
        previous = termios.tcgetattr(fd)
        self._prompt = str(prompt)
        self._buffer = []
        self._cursor = 0
        self._history_index = None
        self._history_draft = ""
        self._input_bytes = b""
        self._paste_mode = False
        self._closed.clear()
        try:
            tty.setcbreak(fd)
            with self._lock:
                self._active = True
                self._write("\x1b[?2004h")
                self._draw_locked()
            while not self._closed.is_set():
                ready, _, _ = select.select([fd], [], [], 0.1)
                if ready:
                    data = os.read(fd, 256)
                    if not data:
                        raise EOFError
                    result = self._consume(data)
                    if result is not None:
                        return result
                width = self._width()
                status = self._status()
                if width != self._last_width or status != self._last_status:
                    with self._lock:
                        self._erase_locked()
                        self._draw_locked()
            raise EOFError
        finally:
            with self._lock:
                if self._active:
                    self._erase_locked()
                self._write("\x1b[?2004l")
                self._active = False
                self._output.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, previous)

    def _consume(self, data: bytes) -> Optional[str]:
        self._input_bytes += data
        changed = False
        while self._input_bytes:
            if self._paste_mode:
                end = self._input_bytes.find(b"\x1b[201~")
                if end < 0:
                    keep = min(5, len(self._input_bytes))
                    chunk = self._input_bytes[:-keep] if keep else self._input_bytes
                    self._input_bytes = self._input_bytes[-keep:] if keep else b""
                    if chunk:
                        self._insert_paste(chunk)
                        changed = True
                    break
                self._insert_paste(self._input_bytes[:end])
                self._input_bytes = self._input_bytes[end + 6 :]
                self._paste_mode = False
                changed = True
                continue

            if self._input_bytes.startswith(b"\x1b[200~"):
                self._input_bytes = self._input_bytes[6:]
                self._paste_mode = True
                continue

            sequence = self._escape_sequence()
            if sequence == "incomplete":
                break
            if sequence:
                changed = self._apply_escape(sequence) or changed
                continue

            byte = self._input_bytes[0]
            if byte in (10, 13):
                self._input_bytes = self._input_bytes[1:]
                text = "".join(self._buffer)
                if not text.strip():
                    changed = True
                    continue
                self.add_history(text)
                with self._lock:
                    self._erase_locked()
                    self._write(f"{_MINT}{self._prompt}{_RESET}{text}\r\n")
                    self._output.flush()
                    self._active = False
                return text
            if byte == 3:
                self._input_bytes = self._input_bytes[1:]
                with self._lock:
                    self._erase_locked()
                    self._write("^C\r\n")
                    self._output.flush()
                    self._active = False
                raise KeyboardInterrupt
            if byte == 4:
                self._input_bytes = self._input_bytes[1:]
                if not self._buffer:
                    raise EOFError
                if self._cursor < len(self._buffer):
                    del self._buffer[self._cursor]
                    changed = True
                continue
            if byte in (8, 127):
                self._input_bytes = self._input_bytes[1:]
                if self._cursor:
                    self._cursor -= 1
                    del self._buffer[self._cursor]
                    changed = True
                continue
            if byte == 1:  # Ctrl-A
                self._input_bytes = self._input_bytes[1:]
                self._cursor = 0
                changed = True
                continue
            if byte == 5:  # Ctrl-E
                self._input_bytes = self._input_bytes[1:]
                self._cursor = len(self._buffer)
                changed = True
                continue
            if byte == 11:  # Ctrl-K
                self._input_bytes = self._input_bytes[1:]
                del self._buffer[self._cursor :]
                changed = True
                continue
            if byte == 21:  # Ctrl-U
                self._input_bytes = self._input_bytes[1:]
                del self._buffer[: self._cursor]
                self._cursor = 0
                changed = True
                continue
            if byte == 23:  # Ctrl-W
                self._input_bytes = self._input_bytes[1:]
                while self._cursor and self._buffer[self._cursor - 1].isspace():
                    self._cursor -= 1
                    del self._buffer[self._cursor]
                while self._cursor and not self._buffer[self._cursor - 1].isspace():
                    self._cursor -= 1
                    del self._buffer[self._cursor]
                changed = True
                continue
            if byte < 32:
                self._input_bytes = self._input_bytes[1:]
                continue

            decoded = self._decode_character()
            if decoded is None:
                break
            self._buffer.insert(self._cursor, decoded)
            self._cursor += 1
            changed = True

        if changed:
            self.refresh()
        return None

    def _escape_sequence(self) -> str:
        if not self._input_bytes.startswith(b"\x1b"):
            return ""
        known = {
            b"\x1b[A": "up",
            b"\x1b[B": "down",
            b"\x1b[C": "right",
            b"\x1b[D": "left",
            b"\x1b[H": "home",
            b"\x1b[F": "end",
            b"\x1b[1~": "home",
            b"\x1b[3~": "delete",
            b"\x1b[4~": "end",
            b"\x1bOH": "home",
            b"\x1bOF": "end",
        }
        for raw, name in known.items():
            if self._input_bytes.startswith(raw):
                self._input_bytes = self._input_bytes[len(raw) :]
                return name
        if any(raw.startswith(self._input_bytes) for raw in known):
            return "incomplete"
        self._input_bytes = self._input_bytes[1:]
        return "unknown"

    def _apply_escape(self, name: str) -> bool:
        if name == "left" and self._cursor:
            self._cursor -= 1
            return True
        if name == "right" and self._cursor < len(self._buffer):
            self._cursor += 1
            return True
        if name == "home":
            self._cursor = 0
            return True
        if name == "end":
            self._cursor = len(self._buffer)
            return True
        if name == "delete" and self._cursor < len(self._buffer):
            del self._buffer[self._cursor]
            return True
        if name == "up":
            return self._history_move(-1)
        if name == "down":
            return self._history_move(1)
        return False

    def _history_move(self, delta: int) -> bool:
        if not self._history:
            return False
        if self._history_index is None:
            if delta > 0:
                return False
            self._history_draft = "".join(self._buffer)
            self._history_index = len(self._history) - 1
        else:
            target = self._history_index + delta
            if target >= len(self._history):
                self._history_index = None
                text = self._history_draft
                self._buffer = list(text)
                self._cursor = len(self._buffer)
                return True
            self._history_index = max(0, target)
        text = self._history[self._history_index]
        self._buffer = list(text)
        self._cursor = len(self._buffer)
        return True

    def _decode_character(self) -> Optional[str]:
        for size in range(1, min(4, len(self._input_bytes)) + 1):
            try:
                text = self._input_bytes[:size].decode("utf-8")
            except UnicodeDecodeError as exc:
                if exc.reason == "unexpected end of data":
                    continue
                self._input_bytes = self._input_bytes[1:]
                return "�"
            self._input_bytes = self._input_bytes[size:]
            return text
        return None

    def _insert_paste(self, raw: bytes) -> None:
        text = raw.decode("utf-8", errors="replace")
        text = " ".join(text.replace("\r", "\n").splitlines())
        if not text:
            return
        self._buffer[self._cursor : self._cursor] = list(text)
        self._cursor += len(text)

    def _erase_locked(self) -> None:
        # The composer never wraps: status and input therefore always occupy two rows.
        self._write(f"\r{_CLEAR_LINE}\x1b[1B\r{_CLEAR_LINE}\x1b[1A\r")

    def _draw_locked(self) -> None:
        width = self._width()
        state, status = self._status()
        self._last_width = width
        self._last_status = (state, status)
        status = status[: max(1, width - 2)]
        status_style = {
            "review_needed": "\x1b[30;48;5;221m",
            "failed": "\x1b[30;48;5;203m",
            "completed": "\x1b[30;48;5;115m",
        }.get(state, "\x1b[30;47m")
        prompt_width = len(self._prompt)
        available = max(4, width - prompt_width - 1)
        start = max(0, self._cursor - available + 1)
        visible = "".join(self._buffer[start : start + available])
        if start:
            visible = f"‹{visible[1:]}" if visible else "‹"
        if start + available < len(self._buffer) and visible:
            visible = f"{visible[:-1]}›"
        self._write(f"\r{_CLEAR_LINE}{_MINT}{self._prompt}{_RESET}{visible}\r\n")
        self._write(f"\r{_CLEAR_LINE}{status_style} {status} \x1b[K{_RESET}")
        cursor_column = prompt_width + self._cursor - start
        cursor_column = min(max(prompt_width, cursor_column), width - 1)
        self._write(f"\r\x1b[1A\x1b[{cursor_column}C")
        self._output.flush()

    @staticmethod
    def _width() -> int:
        return max(20, shutil.get_terminal_size((100, 24)).columns)

    def _write(self, text: str) -> None:
        self._output.write(text)
