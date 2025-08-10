from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import re

from .llm import LLMService
from .filtering import Lexer, Parser


THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
CODE_FENCE_PATTERN = re.compile(r"^```[a-zA-Z0-9_\-]*\n([\s\S]*?)\n```$", re.MULTILINE)


def sanitize_think(text: str) -> str:
    if not isinstance(text, str):
        return text
    return THINK_PATTERN.sub("", text).strip()


def strip_code_fences(text: str) -> str:
    if not isinstance(text, str):
        return text
    m = CODE_FENCE_PATTERN.match(text.strip())
    if m:
        return m.group(1).strip()
    return text.strip()


class Orchestrator:
    """Routes a user request to chat, packet, or filter agents."""

    def __init__(self) -> None:
        pass

    async def route(
        self,
        llm: LLMService,
        *,
        text: str,
        history: List[Dict[str, str]],
        overrides: Optional[Dict[str, Any]] = None,
        has_capture: bool = False,
        packet_dump: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Fast clamp: no capture -> cannot be packet/filter
        if not has_capture:
            content = await ChatAgent.run(llm, history=history, overrides=overrides)
            return {"mode": "chat", "text": content}

        # Heuristic-first: attempt NL->display filter conversion.
        # If the model can yield a filter string, prefer applying it immediately.
        try:
            df_try = await PacketFilterAgent.run(llm, text=text, overrides=overrides)
            df_try = sanitize_think(df_try).strip()
            if df_try:
                # Basic sanitation: single-line
                df_line = df_try.splitlines()[0].strip()
                if df_line and PacketFilterAgent.is_valid_display_filter(df_line):
                    return {"mode": "filter", "filter": df_line}
        except Exception:
            # ignore and fall back to classification
            pass

        # Classification via LLM (deterministic)
        system = (
            "You are an intent classifier for a packet analysis assistant.\n"
            "Decide which one label best fits the user's request: chat, packet, or filter.\n"
            "- chat: general conversation not directly about the currently loaded packet capture.\n"
            "- packet: analysis/explanation/summary/questions about the currently loaded capture's contents.\n"
            "- filter: requests to narrow the visible packets, e.g., 'show only X', 'get me all <proto>', 'filter packets by ...'.\n"
            "Return ONLY one of these exact words: chat | packet | filter. No punctuation or explanation."
        )
        try:
            label_raw = await llm.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                model=(overrides or {}).get("model"),
                temperature=0.0,
                top_p=1.0,
                max_tokens=4,
            )
            label = sanitize_think(label_raw).strip().lower()
            if "filter" in label:
                # Run filter agent
                df = await PacketFilterAgent.run(llm, text=text, overrides=overrides)
                if df:
                    return {"mode": "filter", "filter": df}
                # Fallback to chat if no filter derived
                content = await ChatAgent.run(llm, history=history, overrides=overrides)
                return {"mode": "chat", "text": content}
            if "packet" in label:
                content = await PacketAgent.run(
                    llm,
                    text=text,
                    history=history,
                    packet_dump=packet_dump or "",
                    overrides=overrides,
                )
                return {"mode": "packet", "text": content}
            # default chat
            content = await ChatAgent.run(llm, history=history, overrides=overrides)
            return {"mode": "chat", "text": content}
        except Exception:
            # Safe fallback: chat
            content = await ChatAgent.run(llm, history=history, overrides=overrides)
            return {"mode": "chat", "text": content}


class ChatAgent:
    @staticmethod
    async def run(
        llm: LLMService,
        *,
        history: List[Dict[str, str]],
        overrides: Optional[Dict[str, Any]] = None,
    ) -> str:
        content = await llm.chat(
            history,
            model=(overrides or {}).get("model"),
            temperature=(overrides or {}).get("temperature"),
            top_p=(overrides or {}).get("top_p"),
            max_tokens=(overrides or {}).get("max_tokens"),
        )
        return content


class PacketAgent:
    SYSTEM_PROMPT = (
        "You are a packet analysis expert.\n"
        "You are given a textual summary of the currently loaded packet capture (subset).\n"
        "Answer the user's question strictly based on the provided packet context.\n"
        "If the answer is not derivable from the context, say that you cannot determine it from the provided packets.\n"
    )

    @staticmethod
    def _trim_history(history: List[Dict[str, str]], max_messages: int = 12) -> List[Dict[str, str]]:
        return history[-max_messages:] if len(history) > max_messages else history

    @staticmethod
    async def run(
        llm: LLMService,
        *,
        text: str,
        history: List[Dict[str, str]],
        packet_dump: str,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> str:
        msgs: List[Dict[str, str]] = [
            {"role": "system", "content": PacketAgent.SYSTEM_PROMPT},
            {"role": "system", "content": f"Packet Context (truncated):\n{packet_dump}"},
        ]
        msgs.extend(PacketAgent._trim_history(history))
        msgs.append({"role": "user", "content": text})
        content = await llm.chat(
            msgs,
            model=(overrides or {}).get("model"),
            temperature=(overrides or {}).get("temperature"),
            top_p=(overrides or {}).get("top_p"),
            max_tokens=(overrides or {}).get("max_tokens"),
        )
        return content


class PacketFilterAgent:
    SYSTEM_PROMPT = (
        "You translate natural language into a Wireshark display filter string.\n"
        "- Output ONLY the filter string, with no extra words or punctuation.\n"
        "- If the user's request is not a filter request, return an empty string.\n"
        "- Examples: 'get me all NGAP packets' -> 'ngap'; 'filter all ngap and ftp packets' -> 'ngap && ftp'\n"
    )

    @staticmethod
    async def run(
        llm: LLMService,
        *,
        text: str,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> str:
        msgs = [
            {"role": "system", "content": PacketFilterAgent.SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        raw = await llm.chat(
            msgs,
            model=(overrides or {}).get("model"),
            temperature=0.0,
            top_p=1.0,
            max_tokens=(overrides or {}).get("max_tokens"),
        )
        # Sanitize thinking and code fences
        s = sanitize_think(raw)
        s = strip_code_fences(s).strip()
        # Take only the first line, strip quotes/backticks
        if "\n" in s:
            s = s.splitlines()[0].strip()
        s = s.strip().strip('`').strip('"').strip("'")
        # Validate using our Lexer/Parser; if invalid, return empty
        return s if PacketFilterAgent.is_valid_display_filter(s) else ""

    @staticmethod
    def is_valid_display_filter(s: str) -> bool:
        if not s:
            return False
        try:
            tokens = Lexer(s).tokens()
            Parser(tokens).parse()
            return True
        except Exception:
            return False
