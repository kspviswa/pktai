from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual import work
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.widgets import Header, Footer, Button, Label, DataTable
from textual_fspicker import FileOpen

# PyShark imports
try:
    import pyshark  # type: ignore
except Exception:  # pragma: no cover - handled at runtime
    pyshark = None  # textual will present an error banner later


SUPPORTED_EXTENSIONS = {".pcap", ".pcapng"}


@dataclass
class PacketRow:
    no: int
    time: str
    src: str
    dst: str
    proto: str
    length: int
    info: str


class TitleBar(Container):
    """A simple title bar with a File menu button."""

    def compose(self) -> ComposeResult:
        yield Container(
            Button("File", id="btn-file"),
            Label("pktai TUI", id="title"),
            id="titlebar-row",
        )

    DEFAULT_CSS = """
    TitleBar #titlebar-row {
        height: 3;
        dock: top;
        layout: horizontal;
        padding: 0 1;
    }
    TitleBar #title {
        content-align: center middle;
        width: 1fr;
    }
    """


class PacketList(Vertical):
    """Top-pane style list using DataTable to display packets."""

    table: DataTable

    def compose(self) -> ComposeResult:
        self.table = DataTable(zebra_stripes=True)
        self.table.add_columns("No.", "Time", "Source", "Destination", "Protocol", "Length", "Info")
        yield self.table

    def add_packet(self, row: PacketRow) -> None:
        self.table.add_row(
            str(row.no),
            row.time,
            row.src,
            row.dst,
            row.proto,
            str(row.length),
            row.info,
        )

    def clear(self) -> None:
        self.table.clear()


class PktaiTUI(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    """

    BINDINGS = [
        ("o", "open_capture", "Open"),
        ("q", "quit", "Quit"),
    ]

    capture_path: reactive[Optional[Path]] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Header()
        yield TitleBar()
        yield PacketList()
        yield Footer()

    def on_mount(self) -> None:
        self.packet_list = self.query_one(PacketList)

    @work
    async def action_open_capture(self) -> None:
        # Use textual-fspicker's FileOpen dialog
        selected: Optional[Path] = await self.push_screen_wait(FileOpen(title="Open Capture"))
        if selected is None:
            return
        if selected.suffix.lower() not in SUPPORTED_EXTENSIONS:
            self.notify(f"Unsupported file type: {selected.suffix}", severity="error")
            return
        await self.load_capture(selected)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-file":
            await self.action_open_capture()

    async def load_capture(self, path: Path) -> None:
        if pyshark is None:
            self.notify("PyShark is not installed. Please run: uv sync", severity="error")
            return
        if not path.exists():
            self.notify(f"File not found: {path}", severity="error")
            return
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            self.notify(f"Unsupported file type: {path.suffix}", severity="error")
            return

        self.capture_path = path
        self.packet_list.clear()
        # Run parsing in a background worker thread to avoid blocking UI
        self.parse_packets(path)

    @work(thread=True, exclusive=True)
    def parse_packets(self, path: Path) -> None:
        """Parse packets and feed the table incrementally (background thread)."""
        # Hint: Using keep_packets=False prevents high memory usage
        try:
            cap = pyshark.FileCapture(str(path), keep_packets=False)
        except Exception as e:  # pragma: no cover
            self.call_from_thread(self.notify, f"Failed to open capture: {e}", severity="error")
            return

        def safe_attr(obj, name, default: str = "") -> str:
            try:
                return getattr(obj, name)
            except Exception:
                return default

        no = 0
        try:
            for packet in cap:
                no += 1
                t = safe_attr(packet, "sniff_time", None)
                time_str = t.strftime("%H:%M:%S.%f")[:-3] if t else ""
                proto = safe_attr(packet, "highest_layer", "")
                src = dst = ""
                if hasattr(packet, "ip"):
                    src = safe_attr(packet.ip, "src")
                    dst = safe_attr(packet.ip, "dst")
                elif hasattr(packet, "ipv6"):
                    src = safe_attr(packet.ipv6, "src")
                    dst = safe_attr(packet.ipv6, "dst")
                elif hasattr(packet, "eth"):
                    src = safe_attr(packet.eth, "src")
                    dst = safe_attr(packet.eth, "dst")
                length = 0
                try:
                    length = int(safe_attr(packet, "length", "0"))
                except Exception:
                    pass
                info = proto
                try:
                    if hasattr(packet, "info") and packet.info:
                        info = str(packet.info)
                    else:
                        tl = safe_attr(packet, "transport_layer", "")
                        info = tl or proto
                except Exception:
                    pass

                row = PacketRow(no=no, time=time_str, src=src, dst=dst, proto=proto, length=length, info=info)
                self.call_from_thread(self.packet_list.add_packet, row)
        finally:
            try:
                cap.close()
            except Exception:
                pass


def main() -> None:
    app = PktaiTUI()
    app.run()


if __name__ == "__main__":
    main()
