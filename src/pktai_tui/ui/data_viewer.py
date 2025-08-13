from __future__ import annotations
from typing import Iterable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class DataViewer(Vertical):
    """A compact, non-interactive data viewer that shows Hex and ASCII.

    Call `set_bytes(data: bytes, title: str | None)` to render.
    """

    def compose(self) -> ComposeResult:
        self.header = Static("Field Data", id="dv_header")
        self.body = Static("(select a field)", id="dv_body")
        yield self.header
        yield self.body

    def clear(self) -> None:
        self.body.update("(select a field)")

    def set_bytes(self, data: bytes | None, title: str | None = None) -> None:
        if title:
            try:
                self.header.update(f"Field Data • {title}")
            except Exception:
                pass
        if not data:
            self.clear()
            return
        # Render classic hex + ASCII (16 bytes per row)
        lines: list[str] = []
        for offset, chunk in _chunks_with_offset(data, 16):
            hex_part = " ".join(f"{b:02X}" for b in chunk)
            # Pad hex part to fixed width (16 bytes => 47 chars incl. spaces)
            hex_part = hex_part.ljust(16 * 3 - 1)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"{offset:04X}:  {hex_part}  | {ascii_part}")
        text = "\n".join(lines)
        # Highlight by using a class on the body (CSS controls look); ensure update first
        self.body.update(text or "(no data)")
        try:
            self.body.add_class("highlight")
        except Exception:
            pass


def _chunks(data: bytes, size: int) -> Iterable[bytes]:
    for i in range(0, len(data), size):
        yield data[i : i + size]


def _chunks_with_offset(data: bytes, size: int) -> Iterable[tuple[int, bytes]]:
    for i in range(0, len(data), size):
        yield i, data[i : i + size]
