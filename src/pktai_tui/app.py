from __future__ import annotations
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual import work
from textual.reactive import reactive
from textual.containers import Horizontal, Vertical, Container, VerticalScroll
from textual_fspicker import FileOpen
from textual.widgets import Header, Footer, Tree, Input, Button, Static, LoadingIndicator, DataTable
import os
import textwrap
import asyncio
from rich.text import Text
from rich.markdown import Markdown as RichMarkdown
from urllib.parse import urlparse

from .models import PacketRow
from .services.config import ensure_initialized as cfg_ensure_initialized
from .ui import PacketList, SettingsScreen, DataViewer
from .services.capture import parse_capture, build_packet_view
from .services.capture import packets_to_text
from .services.filtering import filter_packets, nl_to_display_filter
from .services import LLMService
from .services.agents import Orchestrator

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
        # Scrollable message list
        with VerticalScroll(id="chat_log"):
            # Messages will be appended programmatically as containers
            pass
        # Input row
        with Horizontal(id="chat_input_row"):
            yield Input(placeholder="Type a message...", id="chat_input_box")
            yield Button("Send", id="send_btn", variant="primary")
        # New chat button below input row
        yield Button("New Chat", id="new_chat_btn", variant="success")
        # Connectivity status (green/red light + model name)
        yield Static("🔴 Checking...", id="conn_status")

    def on_mount(self) -> None:
        # Chat state
        self._messages: list[dict[str, str]] = []  # role: user/assistant, content: text
        # Widgets
        self.chat_log = self.query_one("#chat_log", VerticalScroll)
        self.chat_input = self.query_one("#chat_input_box", Input)
        self.send_button = self.query_one("#send_btn", Button)
        self.new_chat_button = self.query_one("#new_chat_btn", Button)
        self.conn_status = self.query_one("#conn_status", Static)
        # Pending assistant message placeholder refs
        self._pending: dict[str, object] | None = None
        # LLM service abstraction
        self.llm_service = LLMService.from_env()
        # Orchestrator for routing between chat/packet/filter
        self.orchestrator = Orchestrator()
        # Current in-flight worker for LLM request (for cancellation)
        self._current_worker = None  # type: ignore[assignment]
        # Initial connectivity check
        self.app.run_worker(self._update_connectivity())

    def _make_avatar(self, role: str) -> Static:
        emoji = "👤" if role == "user" else "🤖"
        return Static(emoji, classes=f"avatar {role}")

    def _mount_markdown(self, parent: Container, content: str, classes: str = "main") -> None:
        """Render markdown content using native Textual widget if available; fallback to Static with Rich Markdown renderable."""
        # Try Textual Markdown widget
        md_widget = None
        try:
            from textual.widgets import Markdown as MarkdownWidget  # type: ignore
            md_widget = MarkdownWidget((content or "").strip())
            if classes:
                md_widget.classes = classes
            parent.mount(md_widget)
            return
        except Exception:
            md_widget = None
        # Fallback: Static with rich.markdown.Markdown renderable
        renderable = RichMarkdown((content or "").strip())
        node = Static(renderable, classes=classes or "main")
        parent.mount(node)

    def _append_message(self, role: str, content: str) -> None:
        # Container per message: Horizontal(avatar | bubble)
        row = Horizontal(classes=f"msg {role}")
        # Mount row first before mounting children to avoid MountError
        self.chat_log.mount(row)
        try:
            row.styles.height = "auto"
            row.styles.margin = 0
            row.styles.padding = 0
        except Exception:
            pass
        # Avatar
        row.mount(self._make_avatar(role))
        # Bubble container for message content
        bubble = Vertical(classes=f"bubble {role}")
        row.mount(bubble)
        try:
            bubble.styles.height = "auto"
            bubble.styles.margin = 0
            bubble.styles.padding = 1
        except Exception:
            pass

        if role == "assistant":
            self._populate_assistant_bubble(bubble, content)
        else:
            self._mount_markdown(bubble, content, classes="main")

        # Auto-scroll to bottom
        self.chat_log.scroll_end(animate=False)

    async def _send_and_get_reply(self, prompt: str) -> None:
        # Optimistic UI: show user message
        self._append_message("user", prompt)
        self._messages.append({"role": "user", "content": prompt})
        # Toggle button to STOP state (keep enabled to allow cancel)
        try:
            self.send_button.label = "Stop"
            self.send_button.variant = "error"
        except Exception:
            pass
        # Create inline pending assistant row with spinner, right after user message
        pending_row = Horizontal(classes="msg assistant pending")
        self.chat_log.mount(pending_row)
        pending_row.mount(self._make_avatar("assistant"))
        pending_bubble = Vertical(classes="bubble assistant")
        pending_row.mount(pending_bubble)
        spinner = LoadingIndicator(classes="inline_spinner")
        pending_bubble.mount(spinner)
        # Keep reference to replace later
        self._pending = {"row": pending_row, "bubble": pending_bubble, "spinner": spinner}
        try:
            # Apply overrides from Settings, if any
            overrides = {}
            try:
                overrides = dict(self.app.get_llm_overrides())  # type: ignore[attr-defined]
            except Exception:
                overrides = {}
            content = await self.llm_service.chat(
                self._messages,
                model=overrides.get("model"),
                temperature=overrides.get("temperature"),
                top_p=overrides.get("top_p"),
                max_tokens=overrides.get("max_tokens"),
            )
            self._messages.append({"role": "assistant", "content": content})
            # Remove pending row and create final assistant message
            try:
                if isinstance(self._pending, dict):
                    pending_row = self._pending.get("row")
                    if pending_row:
                        pending_row.remove()
                # Create final assistant message
                self._append_message("assistant", content)
            finally:
                self._pending = None
        except asyncio.CancelledError:
            # Cancelled by user; remove pending row and echo system notice
            try:
                if isinstance(self._pending, dict):
                    pending_row = self._pending.get("row")
                    if pending_row:
                        pending_row.remove()
            finally:
                self._pending = None
            self.chat_log.mount(Static("(generation stopped)", classes="system"))
        except Exception as e:
            self.app.notify(f"Chat error: {e}", severity="error")
        finally:
            # Restore Send button appearance
            try:
                self.send_button.label = "Send"
                self.send_button.variant = "primary"
            except Exception:
                pass
            # Clear current worker ref
            self._current_worker = None
            pass

    def _clear_chat(self) -> None:
        self._messages = []
        # Clear message widgets
        for child in list(self.chat_log.children):
            child.remove()
        self.chat_log.mount(Static("(New chat started)", classes="system"))
        self._pending = None
        self.chat_input.value = ""
        self.chat_input.focus()

    def apply_llm_config(self, overrides: dict[str, object] | None) -> None:
        """Apply overrides by rebuilding the LLM client and refreshing connectivity."""
        try:
            o = dict(overrides or {})
            base_url = str(o.get("base_url") or self.llm_service.base_url)
            api_key = str(o.get("api_key") or self.llm_service.api_key)
            model = str(o.get("model") or self.llm_service.model)
            temp = o.get("temperature")
            temperature = None
            try:
                if temp is not None:
                    temperature = float(temp)  # type: ignore[arg-type]
            except Exception:
                temperature = None
            self.llm_service = LLMService.from_config(
                base_url=base_url,
                api_key=api_key,
                model=model,
                temperature=temperature,
            )
        except Exception as e:
            self.app.notify(f"Failed to apply LLM config: {e}", severity="error")
        # Update status label
        self.app.run_worker(self._update_connectivity())

    async def _update_connectivity(self) -> None:
        """Ping current LLM endpoint and update status light and label."""
        try:
            ok, _models, err = await self.llm_service.ping()
            # Gather overrides to determine display values
            try:
                overrides = {}
                try:
                    overrides = dict(self.app.get_llm_overrides())  # type: ignore[attr-defined]
                except Exception:
                    overrides = {}
                model_name = overrides.get("model") or self.llm_service.model
                base_url = overrides.get("base_url") or self.llm_service.base_url
                alias = overrides.get("alias") if isinstance(overrides, dict) else None
            except Exception:
                model_name = self.llm_service.model
                base_url = getattr(self.llm_service, "base_url", "")
                alias = None

            # Extract host from base_url for compact display
            host = ""
            try:
                parsed = urlparse(str(base_url or ""))
                host = parsed.hostname or (str(base_url) if base_url else "")
            except Exception:
                host = str(base_url or "")

            # Build status with emojis: light + model + host (+ optional alias)
            parts = [
                ("🧠 " + str(model_name or "")).strip(),
                ("🌐 " + str(host or "")).strip(),
            ]
            if alias:
                try:
                    a = str(alias).strip()
                    if a:
                        parts.append("🏷️ " + a)
                except Exception:
                    pass
            text_core = " • ".join([p for p in parts if p and not p.endswith(" ")])

            if ok:
                self.conn_status.update(f"🟢 {text_core}")
            else:
                self.conn_status.update(f"🔴 {text_core} ({err})")
        except Exception as e:
            # Best-effort fallback text
            try:
                parsed = urlparse(getattr(self.llm_service, "base_url", ""))
                host = parsed.hostname or getattr(self.llm_service, "base_url", "")
            except Exception:
                host = getattr(self.llm_service, "base_url", "")
            self.conn_status.update(
                f"🔴 🧠 {getattr(self.llm_service, 'model', '')} • 🌐 {host} ({e})"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:  # type: ignore[override]
        # Handle chat send/new
        if event.button.id == "send_btn":
            # If a worker is running, treat as STOP
            if self._current_worker and getattr(self._current_worker, "is_running", False):
                try:
                    self._current_worker.cancel()
                except Exception:
                    pass
                return
            # Otherwise, normal SEND flow
            text = (self.chat_input.value or "").strip()
            if not text:
                return
            # Route via unified handler to support slash-commands
            self._handle_submit(text)
            self.chat_input.value = ""
            self.chat_input.focus()
        elif event.button.id == "new_chat_btn":
            self._clear_chat()
        # No per-button toggle now; reasoning is shown via Tree expander

    def _populate_assistant_bubble(self, bubble: Vertical, content: str) -> None:
        """Populate the given assistant bubble with main content and optional reasoning Tree."""
        # Extract <think> block
        think_text = None
        start = content.find("<think>")
        end = content.find("</think>")
        if start != -1 and end != -1 and end > start:
            think_text = content[start + len("<think>"):end].strip()
            content = (content[:start] + content[end + len("</think>"):]).strip()

        # Optional reasoning as collapsible Tree (shown above main content)
        if think_text:
            t = Tree("Thought process", classes="think_tree")
            # Ensure the tree doesn't expand vertically
            try:
                t.styles.height = "auto"
                t.styles.min_height = 0
                t.styles.flex_grow = 0
                t.styles.margin = 0
                t.styles.padding = 0
                t.show_guides = False
            except Exception:
                pass
            # Add each line as a child node for readability
            # Pre-wrap lines to avoid horizontal overflow since Tree labels don't soft-wrap reliably
            wrapped: list[str] = []
            for ln in think_text.splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                wrapped.extend(textwrap.fill(ln, width=70).splitlines())
            lines = wrapped or [think_text]
            if not lines:
                lines = [think_text]
            for ln in lines:
                renderable = Text(ln, no_wrap=False, overflow="fold")
                node = t.root.add(renderable)
                try:
                    node.allow_expand = False
                except Exception:
                    pass
            # Start collapsed by default to avoid reserving vertical space
            try:
                t.root.collapse()
            except Exception:
                pass
            bubble.mount(t)

        # Main content (below reasoning), render as Markdown
        self._mount_markdown(bubble, content, classes="main")

    def on_input_submitted(self, event: Input.Submitted) -> None:  # type: ignore[override]
        if event.input.id == "chat_input_box":
            text = (event.value or "").strip()
            if not text:
                return
            self._handle_submit(text)
            self.chat_input.value = ""
            self.chat_input.focus()

    # -------------------- Slash command routing --------------------
    def _handle_submit(self, text: str) -> None:
        """Route chat input to command handler or LLM depending on prefix."""
        if text.startswith("/"):
            self._handle_command(text)
        else:
            # Fire and forget async call
            # Toggle button to STOP now
            try:
                self.send_button.label = "Stop"
                self.send_button.variant = "error"
            except Exception:
                pass
            worker = self.app.run_worker(self._send_via_orchestrator(text))
            self._current_worker = worker

    async def _send_via_orchestrator(self, prompt: str) -> None:
        """Send input through orchestrator to select an agent and handle reply/side-effects."""
        # Optimistic UI: show user message
        self._append_message("user", prompt)
        self._messages.append({"role": "user", "content": prompt})
        # Create pending assistant bubble with spinner
        pending_row = Horizontal(classes="msg assistant pending")
        self.chat_log.mount(pending_row)
        pending_row.mount(self._make_avatar("assistant"))
        pending_bubble = Vertical(classes="bubble assistant")
        pending_row.mount(pending_bubble)
        spinner = LoadingIndicator(classes="inline_spinner")
        pending_bubble.mount(spinner)
        self._pending = {"row": pending_row, "bubble": pending_bubble, "spinner": spinner}

        try:
            overrides = {}
            try:
                overrides = dict(self.app.get_llm_overrides())  # type: ignore[attr-defined]
            except Exception:
                overrides = {}

            # Determine capture availability and prepare packet dump within budget
            try:
                raw_packets = list(self.app.get_raw_packets())  # type: ignore[attr-defined]
            except Exception:
                raw_packets = []
            has_capture = bool(raw_packets)

            # Derive char budget from context_window if provided
            ctx = overrides.get("context_window") if isinstance(overrides, dict) else None
            try:
                ctx_tokens = int(ctx) if ctx is not None else 8192
            except Exception:
                ctx_tokens = 8192
            # Rough 4 chars per token heuristic, reserve room for prompts/answer
            max_chars = max(2000, int(ctx_tokens * 4 * 0.6))
            packet_dump = packets_to_text(raw_packets, max_packets=200, max_chars=max_chars) if has_capture else ""

            result = await self.orchestrator.route(
                self.llm_service,
                text=prompt,
                history=self._messages,
                overrides=overrides,
                has_capture=has_capture,
                packet_dump=packet_dump,
            )

            # Remove pending
            try:
                if isinstance(self._pending, dict):
                    r = self._pending.get("row")
                    if r:
                        r.remove()
            finally:
                self._pending = None

            mode = (result.get("mode") or "chat").lower()
            if mode == "filter":
                df = (result.get("filter") or "").strip()
                if df:
                    # Apply filter and echo
                    self.app.apply_display_filter(df)
                    self._append_message("assistant", f"Applied display filter: {df}")
                else:
                    self._append_message("assistant", "(No display filter derived)")
                # Do not push assistant content to history for filter-only
                return

            # Chat or packet: show assistant content and store in history
            content = str(result.get("text") or "(no response)")
            self._messages.append({"role": "assistant", "content": content})
            self._append_message("assistant", content)

        except asyncio.CancelledError:
            try:
                if isinstance(self._pending, dict):
                    r = self._pending.get("row")
                    if r:
                        r.remove()
            finally:
                self._pending = None
            self.chat_log.mount(Static("(generation stopped)", classes="system"))
        except Exception as e:
            self.app.notify(f"Chat error: {e}", severity="error")
        finally:
            try:
                self.send_button.label = "Send"
                self.send_button.variant = "primary"
            except Exception:
                pass
            self._current_worker = None

    def _handle_command(self, text: str) -> None:
        """Parse and execute slash commands. Currently supports:
        - /df <display_filter>
        """
        parts = text[1:].strip().split(maxsplit=1)
        if not parts:
            self.app.notify("Empty command.", severity="warning")
            return
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "df":
            df = arg.strip()
            if not df:
                self.app.notify("Usage: /df <display_filter>", severity="warning")
                return
            # Execute filter against currently loaded packets
            self.app.apply_display_filter(df)
            # Echo action in chat for traceability
            self._append_message("assistant", f"Applied display filter: {df}")
            return

        # Unknown command
        self.app.notify(f"Unknown command: /{cmd}", severity="warning")


class PktaiTUI(App):
    TITLE = "pktai 🤖"
    SUB_TITLE = "AI-assisted packet analysis in your terminal 💻"
    # Minimal CSS purely for layout sizing
    CSS = """
    Screen { layout: vertical; }
    #body { layout: horizontal; height: 1fr; }
    #left { width: 3fr; layout: vertical; }
    #chat { width: 1fr; layout: vertical; border: round $primary; overflow-x: hidden; }

    PacketList { height: 3fr; overflow-y: auto; }
    /* Details area split: Tree over DataViewer */
    #details { height: 4fr; overflow-y: auto; }
    #data_viewer { height: 1fr; border: round $secondary; overflow-x: hidden; overflow-y: auto; }
    #dv_header { dock: top; padding: 0 1; content-align: left middle; }
    #dv_body { padding: 1; text-wrap: wrap; }
    #dv_body.highlight { background: $secondary 10%; }

    /* Chat pane layout */
    #chat_header { dock: top; padding: 1 1; content-align: center middle; }
    #chat_log { height: 1fr; overflow-y: auto; overflow-x: hidden; padding: 1; }
    #chat_input_row { layout: horizontal; height: auto; padding: 1; }
    #chat_input_box { width: 1fr; }
    #send_btn { width: 12; margin-left: 1; }
    #new_chat_btn { width: 1fr; padding: 0 1; margin: 0 1 1 1; }

    /* Chat message styling */
    .msg { layout: horizontal; padding: 0; margin: 0 0 1 0; height: auto; min-height: 0; }
    .msg.user { content-align: left top; }
    .msg.assistant { content-align: left top; }
    .avatar { width: 3; min-width: 3; content-align: center middle; margin: 1 1 0 0; }
    .avatar.user { color: $accent; }
    .avatar.assistant { color: $secondary; }
    .bubble { width: 1fr; layout: vertical; padding: 1; margin: 0; overflow-x: hidden; min-height: 0; }
    .bubble .main { text-wrap: wrap; padding: 0; margin: 0; }
    .think_tree { opacity: 0.6; width: 1fr; overflow-x: hidden; overflow-y: hidden; margin: 0 0 1 0; padding: 0; border: none; height: auto; min-height: 0; }
    .inline_spinner { width: auto; height: auto; }
    .system { text-style: italic; color: $text 70%; padding: 1; }
    
    """

    BINDINGS = [
        ("o", "open_capture", "Open"),
        ("s", "open_settings", "Settings"),
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
                # Binary/ASCII data viewer beneath details
                yield DataViewer(id="data_viewer")
            yield ChatPane(id="chat")
        yield Footer()

    def on_mount(self) -> None:
        # Ensure ~/.pktai/pktai.yaml exists so providers/models can be loaded
        try:
            cfg_ensure_initialized()
        except Exception:
            pass
        self.packet_list = self.query_one(PacketList)
        self.details_tree = self.query_one("#details", Tree)
        self.data_viewer = self.query_one("#data_viewer", DataViewer)
        # Ensure DataViewer starts empty until a capture is loaded
        try:
            self.data_viewer.clear()
        except Exception:
            pass
        # Store raw pyshark packet objects to allow in-memory filtering
        self._raw_packets: list[object] = []
        # LLM overrides saved from Settings screen
        self._llm_overrides: dict[str, object] = {}

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

    @work
    async def action_open_settings(self) -> None:
        """Open the LLM settings screen and save overrides if provided."""
        result = await self.push_screen_wait(SettingsScreen(current=self._llm_overrides))
        if result:
            # Save overrides and notify
            self._llm_overrides = dict(result)
            self.notify("LLM settings saved.", severity="information")
            # Apply to chat pane and refresh status
            try:
                chat = self.query_one("#chat", ChatPane)
                chat.apply_llm_config(self._llm_overrides)
            except Exception:
                pass

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
        # Reset store
        self._raw_packets = []
        parse_capture(
            path,
            emit,
            notify_error=lambda msg: self.call_from_thread(self.notify, msg, severity="error"),
            on_packet_obj=lambda pkt: self._raw_packets.append(pkt),
        )

    # -------------------- Filtering workflow (LLM-callable) --------------------
    def rebuild_from_packets(self, packets: list[object]) -> None:
        """Rebuild PacketList and details from given pyshark packets (UI thread)."""
        # Clear existing
        self.packet_list.clear()
        self.details_tree.clear()
        self.details_tree.root.label = "Packet details"
        self.details_tree.root.expand()
        # Rebuild rows
        for idx, pkt in enumerate(packets, start=1):
            try:
                row, details, per_layer, proto, per_layer_lines = build_packet_view(pkt, idx)
                self.packet_list.add_packet(row, details, per_layer, proto, per_layer_lines)
            except Exception:
                continue

    def apply_display_filter(self, display_filter: str) -> None:
        """Apply a Wireshark-like display filter to currently loaded packets and refresh UI.

        Intended to be called by the LLM tool layer passing `display_filter`.
        """
        if not getattr(self, "_raw_packets", None):
            self.notify("No capture loaded to filter.", severity="warning")
            return
        try:
            filtered = filter_packets(self._raw_packets, display_filter)
        except NotImplementedError as e:
            self.notify(f"Unsupported filter: {e}", severity="error")
            return
        except ValueError as e:
            self.notify(f"Invalid filter: {e}", severity="error")
            return
        # Rebuild UI from filtered set
        self.rebuild_from_packets(filtered)

    def apply_nl_query(self, nl_query: str) -> str:
        """Convert a natural-language query to display_filter and apply it.

        Returns the derived display_filter string for transparency.
        """
        df = nl_to_display_filter(nl_query)
        self.apply_display_filter(df)
        return df

    def _update_details_from_key(self, key: object) -> None:
        # Render details into the Tree widget with expandable per-layer sections
        self.details_tree.clear()
        # Clear data viewer when the packet changes
        try:
            self.data_viewer.clear()
        except Exception:
            pass
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

    # --------- Details Tree selection -> DataViewer update ---------
    def _update_data_viewer_from_tree_node(self, node) -> None:
        """Derive bytes from the selected Tree node text and update DataViewer.

        Heuristics:
        - If line contains hex bytes (e.g., "aa bb cc" or "aa:bb:cc"), parse them.
        - If contains 0xNN.., parse as integer to bytes.
        - Else, use the textual value's bytes (UTF-8) as a fallback.
        """
        # Do not update if no capture is loaded or if the root node is selected
        if not self._has_capture_loaded():
            return
        try:
            if node is self.details_tree.root:
                return
        except Exception:
            pass
        try:
            label = str(getattr(node, "label", "") or "")
        except Exception:
            label = ""
        title = label.strip() or "Field"

        text = title

        # Extract portion after colon for typical "  key: value" lines
        try:
            after_colon = text.split(":", 1)[1].strip()
        except Exception:
            after_colon = text

        by: bytes | None = None

        # Try hex sequence (bytes separated by space or colon)
        import re
        hex_seq = re.search(r"((?:[0-9a-fA-F]{2}[:\s])+[0-9a-fA-F]{2})", after_colon)
        if hex_seq:
            raw = hex_seq.group(1)
            try:
                cleaned = raw.replace(":", " ").split()
                by = bytes(int(h, 16) for h in cleaned)
            except Exception:
                by = None

        # Try single big hex value like 0x1A2B or plain hex string
        if by is None:
            m = re.search(r"0x([0-9a-fA-F]+)", after_colon)
            if m:
                try:
                    val = int(m.group(1), 16)
                    length = max(1, (val.bit_length() + 7) // 8)
                    by = val.to_bytes(length, "big")
                except Exception:
                    by = None
        if by is None:
            m2 = re.search(r"\b([0-9a-fA-F]{4,})\b", after_colon)
            if m2 and len(m2.group(1)) % 2 == 0:
                try:
                    by = bytes.fromhex(m2.group(1))
                except Exception:
                    by = None

        # Try decimal integer
        if by is None:
            m3 = re.search(r"\b(\d+)\b", after_colon)
            if m3:
                try:
                    val = int(m3.group(1))
                    length = max(1, (val.bit_length() + 7) // 8)
                    by = val.to_bytes(length, "big")
                except Exception:
                    by = None

        # Fallback to UTF-8 encoding of the value text
        if by is None:
            try:
                by = after_colon.encode("utf-8") if after_colon else text.encode("utf-8")
            except Exception:
                by = b""

        try:
            self.data_viewer.set_bytes(by or b"", title=title)
        except Exception:
            pass

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:  # type: ignore[override]
        self._update_data_viewer_from_tree_node(event.node)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:  # type: ignore[override]
        self._update_data_viewer_from_tree_node(event.node)

    # Update on highlight and on explicit selection
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:  # type: ignore[override]
        self._update_details_from_key(event.row_key)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:  # type: ignore[override]
        self._update_details_from_key(event.row_key)

    # --------- Accessors ---------
    def get_llm_overrides(self) -> dict[str, object]:
        return getattr(self, "_llm_overrides", {})

    def get_raw_packets(self) -> list[object]:
        """Return the in-memory list of raw pyshark packet objects (may be empty)."""
        try:
            return list(getattr(self, "_raw_packets", []) or [])
        except Exception:
            return []

    # Internal helper
    def _has_capture_loaded(self) -> bool:
        try:
            if not getattr(self, "_raw_packets", None):
                return False
            table = getattr(self.packet_list, "table", None)
            if table is None:
                return False
            count = getattr(table, "row_count", 0)
            return bool(count and count > 0)
        except Exception:
            return False




def main() -> None:
    app = PktaiTUI()
    app.run()


if __name__ == "__main__":
    main()
