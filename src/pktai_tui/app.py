from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual import work
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.widgets import Header, Footer, Label, DataTable, Static
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


# Removed TitleBar; using only Header for top chrome


class PacketList(Vertical):
    """Top-pane style list using DataTable to display packets."""

    table: DataTable
    # map row key -> ethernet details string
    details_by_key: dict[object, str]

    def compose(self) -> ComposeResult:
        self.table = DataTable(zebra_stripes=True)
        self.table.add_columns("No.", "Time", "Source", "Destination", "Protocol", "Length", "Info")
        yield self.table

    def add_packet(self, row: PacketRow, eth_details: str | None = None) -> None:
        key = self.table.add_row(
            str(row.no),
            row.time,
            row.src,
            row.dst,
            row.proto,
            str(row.length),
            row.info,
            key=row.no,
        )
        if not hasattr(self, "details_by_key"):
            self.details_by_key = {}
        if eth_details:
            self.details_by_key[key] = eth_details

    def clear(self) -> None:
        self.table.clear()
        self.details_by_key = {}

    def get_details_for_key(self, key: object) -> str | None:
        return getattr(self, "details_by_key", {}).get(key)


# Removed custom DetailsPane to use built-in Static widget instead


class PktaiTUI(App):
    TITLE = "pktai 🤖"
    SUB_TITLE = "AI-assisted packet analysis in your terminal 💻"
    # Minimal CSS purely for layout sizing
    CSS = """
    Screen { layout: vertical; }
    PacketList { height: 1fr; overflow-y: auto; }
    #details { height: 1fr; overflow-y: auto; }
    """

    BINDINGS = [
        ("o", "open_capture", "Open"),
        ("q", "quit", "Quit"),
    ]

    capture_path: reactive[Optional[Path]] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Header()
        yield PacketList(id="packets")
        yield Static("Packet details will appear here when you highlight a row.", id="details")
        yield Footer()

    def on_mount(self) -> None:
        self.packet_list = self.query_one(PacketList)
        self.details_pane = self.query_one("#details", Static)

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

    # File button removed; open with 'o' binding only

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
        # Clear details pane
        self.details_pane.update("Packet details will appear here when you highlight a row.")
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

                # Build Ethernet details text if Ethernet layer present
                eth_details: str | None = None
                try:
                    if hasattr(packet, "eth"):
                        eth_src = safe_attr(packet.eth, "src")
                        eth_dst = safe_attr(packet.eth, "dst")
                        eth_type = safe_attr(packet.eth, "type")
                        eth_len = safe_attr(packet.eth, "len")
                        lines = [
                            f"Ethernet II",
                            f"  Source: {eth_src}",
                            f"  Destination: {eth_dst}",
                            f"  Type: {eth_type}",
                        ]
                        if eth_len:
                            lines.append(f"  Length: {eth_len}")
                        eth_details = "\n".join(lines)
                except Exception:
                    pass

                self.call_from_thread(self.packet_list.add_packet, row, eth_details)
        finally:
            try:
                cap.close()
            except Exception:
                pass

    def _update_details_from_key(self, key: object) -> None:
        details = self.packet_list.get_details_for_key(key)
        if details:
            self.details_pane.update(details)
        else:
            self.details_pane.update("(No Ethernet details for this packet)")

    # Update on highlight and on explicit selection
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:  # type: ignore[override]
        self._update_details_from_key(event.row_key)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:  # type: ignore[override]
        self._update_details_from_key(event.row_key)


def main() -> None:
    app = PktaiTUI()
    app.run()


if __name__ == "__main__":
    main()
