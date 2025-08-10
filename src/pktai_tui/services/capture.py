from __future__ import annotations
from pathlib import Path
from typing import Callable, Any

from ..models import PacketRow

# Local import of pyshark to avoid hard dependency at import time
try:
    import pyshark  # type: ignore
except Exception:  # pragma: no cover - handled at runtime
    pyshark = None  # type: ignore


EmitFn = Callable[[PacketRow, str | None, dict[str, str], str | None, dict[str, list[str]]], None]


def _safe_attr(obj, name: str, default: str = "") -> str:
    try:
        return getattr(obj, name)
    except Exception:
        return default


def build_packet_view(packet: object, no: int) -> tuple[PacketRow, str, dict[str, str], str | None, dict[str, list[str]]]:
    """Build PacketRow and details for a single pyshark packet.

    Returns:
        (row, details_text, per_layer, proto, per_layer_lines)
    """
    def _safe_attr(obj, name: str, default: str | None = ""):
        try:
            return getattr(obj, name)
        except Exception:
            return default

    t = _safe_attr(packet, "sniff_time", None)
    time_str = t.strftime("%H:%M:%S.%f")[:-3] if t else ""
    highest = _safe_attr(packet, "highest_layer", "")
    src = dst = ""
    if hasattr(packet, "ip"):
        src = _safe_attr(packet.ip, "src")
        dst = _safe_attr(packet.ip, "dst")
    elif hasattr(packet, "ipv6"):
        src = _safe_attr(packet.ipv6, "src")
        dst = _safe_attr(packet.ipv6, "dst")
    elif hasattr(packet, "eth"):
        src = _safe_attr(packet.eth, "src")
        dst = _safe_attr(packet.eth, "dst")

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
        length = int(_safe_attr(packet, "length", "0"))
    except Exception:
        pass

    # Build Info summary aligned with chosen proto
    info = proto
    try:
        if proto == "TCP" and hasattr(packet, "tcp"):
            sport = _safe_attr(packet.tcp, "srcport")
            dport = _safe_attr(packet.tcp, "dstport")
            seq = _safe_attr(packet.tcp, "seq", "")
            ack = _safe_attr(packet.tcp, "ack", "")
            info = f"Src Port: {sport}, Dst Port: {dport}"
            if seq:
                info += f", Seq: {seq}"
            if ack:
                info += f", Ack: {ack}"
        elif proto == "UDP" and hasattr(packet, "udp"):
            sport = _safe_attr(packet.udp, "srcport")
            dport = _safe_attr(packet.udp, "dstport")
            ulen = _safe_attr(packet.udp, "length", "")
            info = f"Src Port: {sport}, Dst Port: {dport}"
            if ulen:
                info += f", Length: {ulen}"
        elif proto in ("IP", "IPv6"):
            info = f"{src} -> {dst}"
        else:
            tl = _safe_attr(packet, "transport_layer", "")
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
        frame_len = _safe_attr(packet, "length", "")
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
            eth_src = _safe_attr(packet.eth, "src")
            eth_dst = _safe_attr(packet.eth, "dst")
            eth_type = _safe_attr(packet.eth, "type")
            eth_len = _safe_attr(packet.eth, "len")
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
            ip_src = _safe_attr(packet.ip, "src")
            ip_dst = _safe_attr(packet.ip, "dst")
            ver = _safe_attr(packet.ip, "version", "4")
            ip_lines = [
                f"Internet Protocol Version {ver}, Src: {ip_src}, Dst: {ip_dst}"
            ]
            ip_text = "\n".join(ip_lines)
            details_lines.append(ip_text)
            per_layer["IP"] = ip_text
            per_layer_lines["IP"] = ip_lines
        elif hasattr(packet, "ipv6"):
            ip_src = _safe_attr(packet.ipv6, "src")
            ip_dst = _safe_attr(packet.ipv6, "dst")
            ipv6_lines = [
                f"Internet Protocol Version 6, Src: {ip_src}, Dst: {ip_dst}"
            ]
            ipv6_text = "\n".join(ipv6_lines)
            details_lines.append(ipv6_text)
            per_layer["IPv6"] = ipv6_text
            per_layer_lines["IPv6"] = ipv6_lines

        # Transport layer
        if hasattr(packet, "tcp"):
            sport = _safe_attr(packet.tcp, "srcport")
            dport = _safe_attr(packet.tcp, "dstport")
            seq = _safe_attr(packet.tcp, "seq", "")
            ack = _safe_attr(packet.tcp, "ack", "")
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
            sport = _safe_attr(packet.udp, "srcport")
            dport = _safe_attr(packet.udp, "dstport")
            ulen = _safe_attr(packet.udp, "length", "")
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
            data_val = _safe_attr(packet.data, "data", "")
            dlen = _safe_attr(packet.data, "len", "")
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
    return row, details_text, per_layer, proto, per_layer_lines


def parse_capture(
    path: Path,
    emit: EmitFn,
    notify_error: Callable[[str], None] | None = None,
    on_packet_obj: Callable[[Any], None] | None = None,
) -> None:
    """
    Parse packets from the capture file at `path` and emit incremental results via `emit`.

    This function mirrors the original logic from `PktaiTUI.parse_packets`, but is UI-agnostic.
    """
    if pyshark is None:
        if notify_error:
            notify_error("PyShark is not installed. Please run: uv sync")
        return

    try:
        cap = pyshark.FileCapture(str(path), keep_packets=False)
    except Exception as e:  # pragma: no cover
        if notify_error:
            notify_error(f"Failed to open capture: {e}")
        return

    no = 0
    try:
        for packet in cap:
            no += 1
            row, details_text, per_layer, proto, per_layer_lines = build_packet_view(packet, no)
            emit(row, details_text, per_layer, proto, per_layer_lines)
            # Optionally give the caller access to the raw pyshark packet object
            try:
                if on_packet_obj is not None:
                    on_packet_obj(packet)
            except Exception:
                pass
    finally:
        try:
            cap.close()
        except Exception:
            pass


def packets_to_text(packets: list[object], *, max_packets: int = 200, max_chars: int = 50000) -> str:
    """Produce a compact textual dump of packets for LLM context.

    Uses `build_packet_view()` to keep formatting consistent with UI. Limits output
    by number of packets and total characters to fit within the LLM context window.
    """
    lines: list[str] = []
    if not packets:
        return "(no packets loaded)"

    count = 0
    char_budget = max(2000, int(max_chars))

    for idx, pkt in enumerate(packets, start=1):
        if count >= max_packets:
            break
        try:
            row, _details, _per_layer, _proto, per_layer_lines = build_packet_view(pkt, idx)
        except Exception:
            continue

        # Header line similar to table: No, Time, Src -> Dst, Proto, Len, Info
        header = f"#{row.no} {row.time} {row.src} -> {row.dst} [{row.proto}] len={row.length} | {row.info}"
        chunk_lines = [header]

        # Include the first line of key layers to stay compact
        order = ["FRAME", "SLL", "ETH", "IP", "IPv6", "TCP", "UDP", "DATA"]
        for name in order:
            try:
                lns = per_layer_lines.get(name, [])  # type: ignore[union-attr]
                if lns:
                    chunk_lines.append(lns[0])
            except Exception:
                continue

        # Append chunk if budget allows
        chunk_text = "\n".join(chunk_lines)
        # +1 for the extra newline between packets
        if (sum(len(x) for x in lines) + len(chunk_text) + 1) > char_budget:
            break
        lines.append(chunk_text)
        lines.append("")
        count += 1

    # If truncated, note it
    if count < len(packets):
        lines.append(f"(truncated: showed {count} of {len(packets)} packets)")

    return "\n".join(lines).strip()
