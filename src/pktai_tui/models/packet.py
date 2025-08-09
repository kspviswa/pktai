from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PacketRow:
    no: int
    time: str
    src: str
    dst: str
    proto: str
    length: int
    info: str
