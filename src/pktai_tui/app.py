from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual import work
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.widgets import Header, Footer, Label, DataTable, Static, Tree
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
    # map row key -> details string (multi-layer summary)
    details_by_key: dict[object, str]
    # map row key -> per-layer details
    layer_details_by_key: dict[object, dict[str, str]]
    # map row key -> highest layer/protocol string
    proto_by_key: dict[object, str]
    # map row key -> per-layer detailed lines for Tree
    layer_lines_by_key: dict[object, dict[str, list[str]]]

    def compose(self) -> ComposeResult:
        self.table = DataTable(zebra_stripes=True)
        # Ensure interactions are row-oriented so clicks/highlights affect the whole row
        # This also ensures row-based events fire (RowHighlighted/RowSelected)
        self.table.cursor_type = "row"
        self.table.add_columns("No.", "Time", "Source", "Destination", "Protocol", "Length", "Info")
        yield self.table

    def add_packet(self, row: PacketRow, details: str | None = None, per_layer: dict[str, str] | None = None, proto: str | None = None, per_layer_lines: dict[str, list[str]] | None = None) -> None:
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
        if not hasattr(self, "layer_details_by_key"):
            self.layer_details_by_key = {}
        if not hasattr(self, "proto_by_key"):
            self.proto_by_key = {}
        if not hasattr(self, "layer_lines_by_key"):
            self.layer_lines_by_key = {}
        if details:
            self.details_by_key[key] = details
        if per_layer is not None:
            self.layer_details_by_key[key] = per_layer
        if proto is not None:
            self.proto_by_key[key] = proto
        if per_layer_lines is not None:
            self.layer_lines_by_key[key] = per_layer_lines

    def clear(self) -> None:
        self.table.clear()
        self.details_by_key = {}
        self.layer_details_by_key = {}
        self.proto_by_key = {}
        self.layer_lines_by_key = {}

    def get_details_for_key(self, key: object, prefer_layer: str | None = None) -> str | None:
        # If a layer is preferred and exists, return that; else return combined details
        if prefer_layer:
            layer_map = getattr(self, "layer_details_by_key", {}).get(key)
            if layer_map:
                # Normalize lookups
                cand = layer_map.get(prefer_layer)
                if cand:
                    return cand
        return getattr(self, "details_by_key", {}).get(key)

    def get_proto_for_key(self, key: object) -> str | None:
        return getattr(self, "proto_by_key", {}).get(key)


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
        # Use a Tree for expandable, per-layer details
        tree = Tree("Packet details")
        tree.id = "details"
        yield tree
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
                highest = safe_attr(packet, "highest_layer", "")
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

                # Prefer a meaningful protocol over DATA
                proto = highest
                if hasattr(packet, "tcp"):
                    proto = "TCP"
                elif hasattr(packet, "udp"):
                    proto = "UDP"
                elif hasattr(packet, "ip"):
                    proto = "IP"
                elif hasattr(packet, "ipv6"):
                    proto = "IPv6"
                elif hasattr(packet, "sll"):
                    proto = "SLL"
                elif hasattr(packet, "eth"):
                    proto = "ETH"

                length = 0
                try:
                    length = int(safe_attr(packet, "length", "0"))
                except Exception:
                    pass
                # Build Info summary aligned with chosen proto
                info = proto
                try:
                    if proto == "TCP" and hasattr(packet, "tcp"):
                        sport = safe_attr(packet.tcp, "srcport")
                        dport = safe_attr(packet.tcp, "dstport")
                        seq = safe_attr(packet.tcp, "seq", "")
                        ack = safe_attr(packet.tcp, "ack", "")
                        info = f"Src Port: {sport}, Dst Port: {dport}"
                        if seq:
                            info += f", Seq: {seq}"
                        if ack:
                            info += f", Ack: {ack}"
                    elif proto == "UDP" and hasattr(packet, "udp"):
                        sport = safe_attr(packet.udp, "srcport")
                        dport = safe_attr(packet.udp, "dstport")
                        ulen = safe_attr(packet.udp, "length", "")
                        info = f"Src Port: {sport}, Dst Port: {dport}"
                        if ulen:
                            info += f", Length: {ulen}"
                    elif proto in ("IP", "IPv6"):
                        info = f"{src} -> {dst}"
                    else:
                        tl = safe_attr(packet, "transport_layer", "")
                        info = tl or proto
                except Exception:
                    pass

                row = PacketRow(no=no, time=time_str, src=src, dst=dst, proto=proto, length=length, info=info)

                # Build multi-layer details text similar to Wireshark
                details_lines: list[str] = []
                per_layer: dict[str, str] = {}
                per_layer_lines: dict[str, list[str]] = {}
                try:
                    # Frame summary
                    frame_len = safe_attr(packet, "length", "")
                    frame_text = f"Frame {no}: {frame_len} bytes" if frame_len else f"Frame {no}"
                    details_lines.append(frame_text)
                    per_layer["FRAME"] = frame_text
                    per_layer_lines["FRAME"] = [frame_text]

                    # Link-layer: Linux cooked capture or Ethernet
                    if hasattr(packet, "sll"):
                        link_text = "Linux cooked capture v1"
                        details_lines.append(link_text)
                        per_layer["SLL"] = link_text
                        per_layer_lines["SLL"] = [link_text]
                    elif hasattr(packet, "eth"):
                        eth_src = safe_attr(packet.eth, "src")
                        eth_dst = safe_attr(packet.eth, "dst")
                        eth_type = safe_attr(packet.eth, "type")
                        eth_len = safe_attr(packet.eth, "len")
                        eth_lines = [
                            "Ethernet II",
                            f"  Source: {eth_src}",
                            f"  Destination: {eth_dst}",
                        ]
                        if eth_type:
                            eth_lines.append(f"  Type: {eth_type}")
                        if eth_len:
                            eth_lines.append(f"  Length: {eth_len}")
                        eth_text = "\n".join(eth_lines)
                        details_lines.append(eth_text)
                        per_layer["ETH"] = eth_text
                        per_layer_lines["ETH"] = eth_lines

                    # Network layer
                    if hasattr(packet, "ip"):
                        ip_src = safe_attr(packet.ip, "src")
                        ip_dst = safe_attr(packet.ip, "dst")
                        ver = safe_attr(packet.ip, "version", "4")
                        ip_lines = [
                            f"Internet Protocol Version {ver}, Src: {ip_src}, Dst: {ip_dst}"
                        ]
                        ip_text = "\n".join(ip_lines)
                        details_lines.append(ip_text)
                        per_layer["IP"] = ip_text
                        per_layer_lines["IP"] = ip_lines
                    elif hasattr(packet, "ipv6"):
                        ip_src = safe_attr(packet.ipv6, "src")
                        ip_dst = safe_attr(packet.ipv6, "dst")
                        ipv6_lines = [
                            f"Internet Protocol Version 6, Src: {ip_src}, Dst: {ip_dst}"
                        ]
                        ipv6_text = "\n".join(ipv6_lines)
                        details_lines.append(ipv6_text)
                        per_layer["IPv6"] = ipv6_text
                        per_layer_lines["IPv6"] = ipv6_lines

                    # Transport layer
                    if hasattr(packet, "tcp"):
                        sport = safe_attr(packet.tcp, "srcport")
                        dport = safe_attr(packet.tcp, "dstport")
                        seq = safe_attr(packet.tcp, "seq", "")
                        ack = safe_attr(packet.tcp, "ack", "")
                        base = f"Transmission Control Protocol, Src Port: {sport}, Dst Port: {dport}"
                        if seq:
                            base += f", Seq: {seq}"
                        if ack:
                            base += f", Ack: {ack}"
                        details_lines.append(base)
                        per_layer["TCP"] = base
                        per_layer_lines["TCP"] = [base]
                        # Try to include more TCP fields generically
                        try:
                            names = getattr(packet.tcp, "field_names", [])
                            extra = []
                            for fn in names:
                                try:
                                    val = getattr(packet.tcp, fn)
                                    sval = str(val)
                                    if sval and fn not in ("srcport", "dstport", "seq", "ack"):
                                        extra.append(f"  {fn}: {sval}")
                                except Exception:
                                    continue
                            if extra:
                                per_layer_lines["TCP"].extend(extra)
                                details_lines.append("\n".join(extra))
                        except Exception:
                            pass
                    elif hasattr(packet, "udp"):
                        sport = safe_attr(packet.udp, "srcport")
                        dport = safe_attr(packet.udp, "dstport")
                        ulen = safe_attr(packet.udp, "length", "")
                        base = f"User Datagram Protocol, Src Port: {sport}, Dst Port: {dport}"
                        if ulen:
                            base += f", Length: {ulen}"
                        details_lines.append(base)
                        per_layer["UDP"] = base
                        per_layer_lines["UDP"] = [base]
                        try:
                            names = getattr(packet.udp, "field_names", [])
                            extra = []
                            for fn in names:
                                try:
                                    val = getattr(packet.udp, fn)
                                    sval = str(val)
                                    if sval and fn not in ("srcport", "dstport", "length"):
                                        extra.append(f"  {fn}: {sval}")
                                except Exception:
                                    continue
                            if extra:
                                per_layer_lines["UDP"].extend(extra)
                                details_lines.append("\n".join(extra))
                        except Exception:
                            pass

                    # Data/Application
                    if hasattr(packet, "data"):
                        data_val = safe_attr(packet.data, "data", "")
                        dlen = safe_attr(packet.data, "len", "")
                        data_lines = ["Data"]
                        if data_val:
                            data_lines.append(f"  Data (hex): {data_val}")
                            # ASCII preview
                            try:
                                hex_str = data_val.replace(":", "").replace(" ", "")
                                by = bytes.fromhex(hex_str)
                                ascii_preview = ''.join(chr(b) if 32 <= b < 127 else '.' for b in by)
                                data_lines.append(f"  Data (ascii): {ascii_preview}")
                            except Exception:
                                pass
                        if dlen:
                            data_lines.append(f"  [Length: {dlen}]")
                        data_text = "\n".join(data_lines)
                        details_lines.append(data_text)
                        per_layer["DATA"] = data_text
                        per_layer_lines["DATA"] = data_lines

                    # As a last resort, generically include any remaining layers and fields
                    try:
                        for layer in getattr(packet, "layers", []) or []:
                            lname = str(getattr(layer, "layer_name", "")).upper() or "LAYER"
                            if lname in per_layer_lines:
                                continue
                            lines = [lname]
                            names = getattr(layer, "field_names", []) or []
                            for fn in names:
                                try:
                                    val = getattr(layer, fn)
                                    sval = str(val)
                                    if sval:
                                        lines.append(f"  {fn}: {sval}")
                                except Exception:
                                    continue
                            if len(lines) > 1:
                                per_layer_lines[lname] = lines
                                per_layer[lname] = "\n".join(lines)
                                details_lines.append(per_layer[lname])
                    except Exception:
                        pass
                except Exception:
                    pass

                details_text = "\n".join(details_lines) if details_lines else "(No details available for this packet)"
                self.call_from_thread(self.packet_list.add_packet, row, details_text, per_layer, proto, per_layer_lines)
        finally:
            try:
                cap.close()
            except Exception:
                pass

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
