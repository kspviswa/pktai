from __future__ import annotations
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual import work
from textual.reactive import reactive
from textual.containers import Horizontal, Vertical, Container
from textual_fspicker import FileOpen
from textual.widgets import Header, Footer, Tree, Input, Button, RichLog, Static
import os
from openai import AsyncOpenAI

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
        # Header
        yield Static("Chat", id="chat_header")
        # Chat log fills available space with soft wrapping
        yield RichLog(id="chat_log", wrap=True, auto_scroll=True)
        # Input row
        with Horizontal(id="chat_input_row"):
            yield Input(placeholder="Type a message...", id="chat_input_box")
            yield Button("Send", id="send_btn", variant="primary")
        # New chat button below input row
        yield Button("New Chat", id="new_chat_btn", variant="success")

    def on_mount(self) -> None:
        # Chat state
        self._messages: list[dict[str, str]] = []  # role: user/assistant, content: text
        # Widgets
        self.chat_log = self.query_one("#chat_log", RichLog)
        self.chat_input = self.query_one("#chat_input_box", Input)
        self.send_button = self.query_one("#send_btn", Button)
        self.new_chat_button = self.query_one("#new_chat_btn", Button)
        # LLM client
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        api_key = os.getenv("OPENAI_API_KEY", "ollama")  # Ollama ignores but required by client
        self.llm = AsyncOpenAI(base_url=base_url, api_key=api_key)

    def _append_to_log(self, role: str, text: str) -> None:
        prefix = "You" if role == "user" else "LLM"
        # RichLog will handle soft wrapping based on available width
        # Preserve existing newlines in the message
        lines = text.splitlines() or [""]
        for line in lines:
            self.chat_log.write(f"[{prefix}] {line}")

    async def _send_and_get_reply(self, prompt: str) -> None:
        # Optimistic UI: show user message
        self._append_to_log("user", prompt)
        self._messages.append({"role": "user", "content": prompt})
        # Disable send while in-flight
        self.send_button.disabled = True
        try:
            resp = await self.llm.chat.completions.create(
                model=os.getenv("OLLAMA_MODEL", "qwen3:latest"),
                messages=self._messages,
                temperature=0.2,
            )
            content = resp.choices[0].message.content if resp.choices else "(no response)"
            if content is None:
                content = "(no response)"
            self._messages.append({"role": "assistant", "content": content})
            self._append_to_log("assistant", content)
        except Exception as e:
            self.app.notify(f"Chat error: {e}", severity="error")
        finally:
            self.send_button.disabled = False

    def _clear_chat(self) -> None:
        self._messages = []
        self.chat_log.clear()
        self.chat_log.write_line("(New chat started)")
        self.chat_input.value = ""
        self.chat_input.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:  # type: ignore[override]
        if event.button.id == "send_btn":
            text = (self.chat_input.value or "").strip()
            if not text:
                return
            # Fire and forget async call
            self.app.run_worker(self._send_and_get_reply(text))
            self.chat_input.value = ""
            self.chat_input.focus()
        elif event.button.id == "new_chat_btn":
            self._clear_chat()

    def on_input_submitted(self, event: Input.Submitted) -> None:  # type: ignore[override]
        if event.input.id == "chat_input_box":
            text = (event.value or "").strip()
            if not text:
                return
            self.app.run_worker(self._send_and_get_reply(text))
            self.chat_input.value = ""
            self.chat_input.focus()


class PktaiTUI(App):
    TITLE = "pktai 🤖"
    SUB_TITLE = "AI-assisted packet analysis in your terminal 💻"
    # Minimal CSS purely for layout sizing
    CSS = """
    Screen { layout: vertical; }
    #body { layout: horizontal; height: 1fr; }
    #left { width: 3fr; layout: vertical; }
    #chat { width: 1fr; layout: vertical; border: round $primary; overflow-x: hidden; }

    PacketList { height: 1fr; overflow-y: auto; }
    #details { height: 1fr; overflow-y: auto; }

    /* Chat pane layout */
    #chat_header { dock: top; padding: 1 1; content-align: center middle; }
    #chat_log { height: 1fr; overflow-y: auto; overflow-x: hidden; text-wrap: wrap; }
    #chat_input_row { layout: horizontal; height: auto; padding: 1; }
    #chat_input_box { width: 1fr; }
    #send_btn { width: 12; margin-left: 1; }
    #new_chat_btn { width: 1fr; padding: 0 1; margin: 0 1 1 1; }
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
