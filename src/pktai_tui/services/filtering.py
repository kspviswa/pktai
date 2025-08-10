"""
Wireshark-like display filter evaluator for in-memory PyShark packets.

Supported subset (best-effort, Python-side only; does NOT spawn tshark):
- Protocol-only: "tcp", "http", "ngap" → hasattr(pkt, layer)
- Field presence: "ip.src" → layer present and field exists
- Equality / inequality: "ip.src == 1.2.3.4", "sctp.dstport != 38412"
- Logical AND/OR with parentheses: &&, ||, and/or synonyms

Non-goals / Unsupported (raise NotImplementedError):
- contains, matches, =~, in, range ops, <, <=, >, >=, bitwise, regex, arithmetic, tcp.flags-style bits, etc.

Example usage with a preloaded capture:
    import pyshark
    from pktai_tui.services.filtering import filter_packets

    cap = pyshark.FileCapture("trace.pcapng")
    packets = list(cap)  # materialize first; do NOT pass a lazy capture
    ngap_pkts = filter_packets(packets, "ngap && sctp.dstport == 38412")
    print(len(ngap_pkts))

Performance: This is a convenience utility for in-memory interactive filtering.
For very large datasets, using tshark's native display_filter via FileCapture is
usually faster.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Union

# ----------------------------- Tokenizer -----------------------------

TokenType = str

@dataclass(frozen=True)
class Token:
    type: TokenType
    value: str
    pos: int


class Lexer:
    """Simple lexer for a Wireshark-like tiny subset.

    Tokens:
    - IDENT: [A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)? (we also allow repeated dots during parse)
    - STRING: '...' or "..."
    - NUMBER: [0-9]+
    - OP: ==, !=, &&, ||, (, )
    """

    def __init__(self, text: str):
        self.original = text
        # normalize logical words to symbols and trim spaces
        text = text.strip()
        text = self._normalize_logicals(text)
        self.text = text
        self.i = 0

    @staticmethod
    def _normalize_logicals(s: str) -> str:
        # Replace case-insensitive ' and ' / ' or ' with && / || [word boundaries]
        import re
        s = re.sub(r"\bAND\b", "&&", s, flags=re.IGNORECASE)
        s = re.sub(r"\bOR\b", "||", s, flags=re.IGNORECASE)
        return s

    def _peek(self) -> str:
        return self.text[self.i] if self.i < len(self.text) else ""

    def _advance(self) -> str:
        ch = self._peek()
        self.i += 1
        return ch

    def _error_near(self) -> str:
        start = max(0, self.i - 10)
        end = min(len(self.text), self.i + 10)
        snippet = self.text[start:end]
        return f"near '{snippet}' at {self.i}"

    def tokens(self) -> List[Token]:
        toks: List[Token] = []
        while self.i < len(self.text):
            ch = self._peek()
            if ch.isspace():
                self._advance()
                continue

            pos = self.i

            # Multi-char ops first
            if self.text.startswith("==", self.i):
                toks.append(Token("OP_EQ", "==", pos))
                self.i += 2
                continue
            if self.text.startswith("!=", self.i):
                toks.append(Token("OP_NE", "!=", pos))
                self.i += 2
                continue
            if self.text.startswith("&&", self.i):
                toks.append(Token("OP_AND", "&&", pos))
                self.i += 2
                continue
            if self.text.startswith("||", self.i):
                toks.append(Token("OP_OR", "||", pos))
                self.i += 2
                continue

            # Unsupported operators: report early
            for op, name in [(" contains ", "contains"), (" matches ", "matches"), (" in ", "in")]:
                if self.text[self.i:].lower().startswith(op.strip() + " "):
                    raise NotImplementedError(f"Unsupported operator: {name}")

            # Single-char tokens
            if ch == '(':
                toks.append(Token("LPAREN", ch, pos))
                self._advance()
                continue
            if ch == ')':
                toks.append(Token("RPAREN", ch, pos))
                self._advance()
                continue
            if ch in "<>":
                raise NotImplementedError(f"Unsupported operator: {ch}")

            # String literal
            if ch in ('"', "'"):
                quote = self._advance()
                val = []
                while self.i < len(self.text) and self._peek() != quote:
                    c = self._advance()
                    if c == "\\" and self.i < len(self.text):
                        val.append(self._advance())
                    else:
                        val.append(c)
                if self._peek() != quote:
                    raise ValueError(f"Unterminated string literal {self._error_near()}")
                self._advance()  # closing quote
                toks.append(Token("STRING", "".join(val), pos))
                continue

            # Number literal
            if ch.isdigit():
                num = []
                while self._peek().isdigit():
                    num.append(self._advance())
                toks.append(Token("NUMBER", "".join(num), pos))
                continue

            # Identifier (layer/field possibly with dots processed in parser)
            if ch.isalpha() or ch == '_':
                ident = []
                while True:
                    c = self._peek()
                    if c.isalnum() or c in ['_', '.']:
                        ident.append(self._advance())
                    else:
                        break
                toks.append(Token("IDENT", "".join(ident), pos))
                continue

            raise ValueError(f"Invalid character '{ch}' {self._error_near()}")

        return toks


# ------------------------------- Parser ------------------------------

@dataclass
class Node:
    pass

@dataclass
class Or(Node):
    left: Node
    right: Node

@dataclass
class And(Node):
    left: Node
    right: Node

@dataclass
class Paren(Node):
    expr: Node

@dataclass
class Protocol(Node):
    layer: str  # lower-case

@dataclass
class FieldPresence(Node):
    layer: str  # lower-case
    field: str

@dataclass
class Compare(Node):
    layer: str  # lower-case
    field: Optional[str]  # if None, comparing the layer itself (rare)
    op: str  # '==' or '!='
    literal: Union[str, int]


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.i = 0

    def _peek(self) -> Optional[Token]:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _advance(self) -> Token:
        tok = self._peek()
        if tok is None:
            raise ValueError("Unexpected end of input")
        self.i += 1
        return tok

    def _match(self, *types: TokenType) -> Optional[Token]:
        tok = self._peek()
        if tok and tok.type in types:
            self.i += 1
            return tok
        return None

    def parse(self) -> Node:
        if not self.tokens:
            raise ValueError("Empty expression")
        node = self._parse_expr()
        if self._peek() is not None:
            raise ValueError(f"Invalid display filter syntax near: '{self._peek().value}'")
        return node

    def _parse_expr(self) -> Node:
        node = self._parse_term()
        while True:
            if self._match("OP_OR"):
                right = self._parse_term()
                node = Or(node, right)
            else:
                break
        return node

    def _parse_term(self) -> Node:
        node = self._parse_factor()
        while True:
            if self._match("OP_AND"):
                right = self._parse_factor()
                node = And(node, right)
            else:
                break
        return node

    def _parse_factor(self) -> Node:
        if self._match("LPAREN"):
            expr = self._parse_expr()
            if not self._match("RPAREN"):
                raise ValueError("Missing closing ')' in display filter")
            return Paren(expr)

        ident = self._match("IDENT")
        if ident:
            # Lookahead for possible patterns: presence, protocol-only, or compare
            layer, field = self._split_ident(ident.value)

            # Equality / inequality
            op_tok = self._match("OP_EQ", "OP_NE")
            if op_tok:
                lit_tok = self._match("STRING", "NUMBER", "IDENT")
                if not lit_tok:
                    raise ValueError("Expected literal after comparison operator")
                literal: Union[str, int]
                if lit_tok.type == "NUMBER":
                    literal = int(lit_tok.value)
                else:
                    literal = lit_tok.value
                return Compare(layer=layer.lower(), field=field, op=("==" if op_tok.type == "OP_EQ" else "!="), literal=literal)

            # Field presence: layer.field
            if field is not None:
                return FieldPresence(layer=layer.lower(), field=field)

            # Protocol-only
            return Protocol(layer=layer.lower())

        raise ValueError("Invalid display filter syntax near: factor")

    @staticmethod
    def _split_ident(value: str) -> Tuple[str, Optional[str]]:
        # Allow a.b (single dot). If multiple dots, treat first as layer.field and keep remainder joined for field name.
        if '.' in value:
            parts = value.split('.')
            layer = parts[0]
            field = '.'.join(parts[1:]) if len(parts) > 1 else None
            return layer, field
        return value, None


# ------------------------------ Evaluator ----------------------------

def _get_layer(pkt: Any, layer: str, layer_cache: dict[str, Any]) -> Optional[Any]:
    if layer in layer_cache:
        return layer_cache[layer]
    obj = getattr(pkt, layer, None)
    layer_cache[layer] = obj
    return obj


def _has_field(layer_obj: Any, field: str) -> bool:
    if layer_obj is None:
        return False
    # Try exact, lower, and replacing '-' with '_'
    candidates = [field, field.lower(), field.replace('-', '_'), field.lower().replace('-', '_')]
    for name in candidates:
        if hasattr(layer_obj, name):
            return True
    # Fallback: dir() membership test (pyshark layer exposes attributes)
    try:
        names = dir(layer_obj)
        return any(name in names for name in candidates)
    except Exception:
        return False


def _get_field_value(layer_obj: Any, field: str) -> Any:
    if layer_obj is None:
        return None
    candidates = [field, field.lower(), field.replace('-', '_'), field.lower().replace('-', '_')]
    for name in candidates:
        if hasattr(layer_obj, name):
            return getattr(layer_obj, name)
    # Some pyshark fields can be retrieved via get_field if present
    getter = getattr(layer_obj, "get_field", None)
    if callable(getter):
        for name in candidates:
            try:
                val = getter(name)
                if val is not None:
                    return val
            except Exception:
                continue
    return None


def _to_number_if_possible(v: Any):
    try:
        if isinstance(v, bool):
            return False, v
        if isinstance(v, (int, float)):
            return True, int(v)
        if isinstance(v, str) and v.isdigit():
            return True, int(v)
        return False, v
    except Exception:
        return False, v


def _eval(node, pkt: Any) -> bool:
    layer_cache: dict[str, Any] = {}

    def eval_node(n) -> bool:
        if isinstance(n, Paren):
            return eval_node(n.expr)
        if isinstance(n, Or):
            return eval_node(n.left) or eval_node(n.right)
        if isinstance(n, And):
            return eval_node(n.left) and eval_node(n.right)
        if isinstance(n, Protocol):
            return hasattr(pkt, n.layer)
        if isinstance(n, FieldPresence):
            layer_obj = _get_layer(pkt, n.layer, layer_cache)
            return _has_field(layer_obj, n.field)
        if isinstance(n, Compare):
            layer_obj = _get_layer(pkt, n.layer, layer_cache)
            if n.field is None:
                left_val = layer_obj
            else:
                left_val = _get_field_value(layer_obj, n.field)
            if left_val is None:
                return False

            right_val = n.literal

            # Attempt numeric comparison when both are numeric-like
            l_is_num, l_num = _to_number_if_possible(left_val)
            r_is_num, r_num = _to_number_if_possible(right_val)
            if l_is_num and r_is_num:
                res = (l_num == r_num)
            else:
                res = str(left_val) == str(right_val)

            return res if n.op == '==' else (not res)

        raise RuntimeError("Unknown AST node")

    return eval_node(node)


# -------------------------- Public API -------------------------------

def filter_packets(packets: List[Any], display_filter: str) -> List[Any]:
    """Filter a preloaded list of PyShark packets using a Wireshark-like subset.

    Args:
        packets: list of pyshark.packet.packet.Packet (already materialized)
        display_filter: Wireshark-like expression string.

    Returns:
        A filtered list of packets matching the expression.

    Raises:
        NotImplementedError: if an unsupported operator is used.
        ValueError: on syntax errors.
    """
    if display_filter is None or str(display_filter).strip() == "":
        return list(packets)

    lexer = Lexer(display_filter)
    tokens = lexer.tokens()
    parser = Parser(tokens)
    try:
        ast = parser.parse()
    except NotImplementedError:
        raise
    except Exception as e:
        raise ValueError(f"Invalid display filter syntax: {e}") from e

    result: List[Any] = []
    for pkt in packets:
        try:
            if _eval(ast, pkt):
                result.append(pkt)
        except Exception:
            continue
    return result


def nl_to_display_filter(nl_query: str) -> str:
    """Very small heuristic mapper from natural language to a display filter string.

    This is intentionally simple: it extracts common protocol tokens and simple
    field equalities (ip.src/dst and sctp ports) when phrased plainly.

    Examples:
    - "get me all ngap packets" -> "ngap"
    - "show sctp dst port 38412" -> "sctp.dstport == 38412"
    - "tcp from 1.2.3.4" -> "tcp && ip.src == 1.2.3.4"
    """
    s = (nl_query or "").strip()
    if not s:
        return ""
    import re
    s_low = s.lower()

    # Known protocol keywords
    protos = ["tcp", "udp", "ip", "ipv6", "http", "sctp", "ngap", "nas_5gs"]
    found_protos = [p for p in protos if re.search(rf"\b{re.escape(p)}\b", s_low)]

    # IP address
    ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", s_low)
    ip_str = ip_match.group(1) if ip_match else None

    # Ports
    port_match = re.search(r"port\s+(\d{1,5})", s_low)
    port_val = port_match.group(1) if port_match else None
    dst_hint = bool(re.search(r"\bdst|destination\b", s_low))
    src_hint = bool(re.search(r"\bsrc|source\b", s_low))

    parts: list[str] = []
    for p in found_protos:
        parts.append(p)

    if ip_str:
        if src_hint:
            parts.append(f"ip.src == {ip_str}")
        elif dst_hint:
            parts.append(f"ip.dst == {ip_str}")
        else:
            # ambiguous: match either side
            parts.append(f"(ip.src == {ip_str} || ip.dst == {ip_str})")

    if port_val:
        side = "dstport" if dst_hint else ("srcport" if src_hint else "dstport")
        # Prefer SCTP or TCP if mentioned; default to sctp
        if "sctp" in found_protos:
            parts.append(f"sctp.{side} == {port_val}")
        elif "tcp" in found_protos:
            parts.append(f"tcp.{side} == {port_val}")
        else:
            parts.append(f"sctp.{side} == {port_val}")

    return " && ".join(parts) if parts else s_low


__all__ = [
    "filter_packets",
    "Lexer",
    "Parser",
    "nl_to_display_filter",
]
