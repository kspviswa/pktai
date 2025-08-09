from __future__ import annotations
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable

from ..models.packet import PacketRow


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

    def add_packet(
        self,
        row: PacketRow,
        details: str | None = None,
        per_layer: dict[str, str] | None = None,
        proto: str | None = None,
        per_layer_lines: dict[str, list[str]] | None = None,
    ) -> None:
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
