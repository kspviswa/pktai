from __future__ import annotations
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual import work
from textual.reactive import reactive
from textual.containers import Horizontal, Vertical, Container
from textual_fspicker import FileOpen
from textual.widgets import Header, Footer, Tree, Input, Button, Log, Static

from .models import PacketRow
from .ui import PacketList
from .services.capture import parse_capture

# PyShark imports
try:
    import pyshark  # type: ignore
except Exception:  # pragma: no cover - handled at runtime
    pyshark = None  # textual will present an error banner later


SUPPORTED_EXTENSIONS = {".pcap", ".pcapng"}


# Removed TitleBar; using only Header for top chrome
# Removed custom DetailsPane to use built-in Static widget instead


class ChatPane(Container):
    """Right-side chat pane: messages log and input box with send button.

    Business logic will be added later; this currently provides only the view.
    """

    def compose(self) -> ComposeResult:
        yield Static("Chat", id="chat_header")
        yield Log(id="chat_log")
        with Horizontal(id="chat_input_row"):
            yield Input(placeholder="Type a message...", id="chat_input_box")
            yield Button("Send", id="send_btn", variant="primary")


class PktaiTUI(App):
    TITLE = "pktai 🤖"
    SUB_TITLE = "AI-assisted packet analysis in your terminal 💻"
    # Minimal CSS purely for layout sizing
    CSS = """
    Screen { layout: vertical; }
    #body { layout: horizontal; height: 1fr; }
    #left { width: 3fr; layout: vertical; }
    #chat { width: 1fr; layout: vertical; border: round $primary; }

    PacketList { height: 1fr; overflow-y: auto; }
    #details { height: 1fr; overflow-y: auto; }

    /* Chat pane layout */
    #chat_header { dock: top; padding: 1 1; content-align: center middle; }
    #chat_log { height: 1fr; overflow-y: auto; }
    #chat_input_row { layout: horizontal; height: auto; padding: 1; }
    #chat_input_box { width: 1fr; }
    #send_btn { width: 12; margin-left: 1; }
    """

    BINDINGS = [
        ("o", "open_capture", "Open"),
        ("q", "quit", "Quit"),
    ]

    capture_path: reactive[Optional[Path]] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Header()
        # Body: horizontal split between left (packets + details) and right (chat)
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield PacketList(id="packets")
                # Use a Tree for expandable, per-layer details
                tree = Tree("Packet details")
                tree.id = "details"
                yield tree
            yield ChatPane(id="chat")
        yield Footer()

    def on_mount(self) -> None:
        self.packet_list = self.query_one(PacketList)
        self.details_tree = self.query_one("#details", Tree)

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
        # Clear details tree
        self.details_tree.clear()
        self.details_tree.root.label = "Packet details"
        self.details_tree.root.expand()
        # Run parsing in a background worker thread to avoid blocking UI
        self.parse_packets(path)

    @work(thread=True, exclusive=True)
    def parse_packets(self, path: Path) -> None:
        """Parse packets and feed the table incrementally (background thread)."""
        def emit(row: PacketRow, details: str | None, per_layer: dict[str, str], proto: str | None, per_layer_lines: dict[str, list[str]]) -> None:
            self.call_from_thread(self.packet_list.add_packet, row, details, per_layer, proto, per_layer_lines)

        parse_capture(path, emit, notify_error=lambda msg: self.call_from_thread(self.notify, msg, severity="error"))

    def _update_details_from_key(self, key: object) -> None:
        # Render details into the Tree widget with expandable per-layer sections
        self.details_tree.clear()
        root = self.details_tree.root
        root.label = "Packet details"
        # Preferred layer based on protocol column
        prefer_layer = self.packet_list.get_proto_for_key(key)
        layer_lines = getattr(self.packet_list, "layer_lines_by_key", {}).get(key) or {}
        # Display layers in a canonical order first, then any extras
        order = ["FRAME", "SLL", "ETH", "IP", "IPv6", "TCP", "UDP", "DATA"]
        seen = set()
        to_show = []
        for name in order:
            if name in layer_lines:
                to_show.append(name)
                seen.add(name)
        for name in layer_lines.keys():
            if name not in seen:
                to_show.append(name)
        # Build nodes
        preferred_node = None
        for name in to_show:
            lines = layer_lines.get(name, [])
            node = root.add(name)
            # If there are child lines, add and expand; otherwise make it a leaf
            if len(lines) > 1:
                for line in lines[1:]:
                    child = node.add(line)
                    try:
                        child.allow_expand = False
                    except Exception:
                        pass
                node.expand()
            else:
                try:
                    node.allow_expand = False  # prevent misleading expand affordance
                except Exception:
                    pass
            if prefer_layer and name.upper() == str(prefer_layer).upper():
                preferred_node = node
        root.expand()
        # If nothing structured, fallback to plain text
        if not to_show:
            details = self.packet_list.get_details_for_key(key)
            if details:
                root.add(details)
                root.expand()
            else:
                root.add("(No details for this packet)")
                root.expand()
        # Focus preferred
        if preferred_node is not None:
            self.details_tree.select_node(preferred_node)

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
