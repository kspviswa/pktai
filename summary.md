# pktai-tui Summary

- TL;DR: Added a right-side, dynamically wrapping Chat pane powered by an Ollama-backed LLM (via OpenAI client), with Send/Enter-to-send and New Chat, while preserving the packets + details workflow.

## Project Overview
- Name: pktai-tui
- Purpose: AI-assisted packet analysis in the terminal using Textual UI and PyShark.
- Entry point: `src/pktai_tui/app.py` (`PktaiTUI`)
- Dependencies: Textual, PyShark, textual-fspicker, OpenAI (for Ollama-compatible API)

## Current Architecture
- `PktaiTUI` (`src/pktai_tui/app.py`)
  - Top-level chrome: `Header`, `Footer`.
  - Main body: horizontal split (`#body`).
    - Left (`#left`):
      - `PacketList` (`#packets`) shows parsed packets.
      - `Tree` (`#details`) shows expandable per-layer details for the highlighted packet.
    - Right (`#chat`): `ChatPane` with message log, input + send button, and New Chat button.
- Parsing: `parse_capture()` in `src/pktai_tui/services/capture.py` feeds `PacketList` with `PacketRow` entries.
- Models: `PacketRow` in `src/pktai_tui/models.py` (imported as `.models`).
- File open: `textual-fspicker` dialog triggered by `o` key.

## Major Recent Changes
- Added `ChatPane` (in `src/pktai_tui/app.py`):
  - UI: `RichLog` for dynamic soft-wrapping and auto-scroll, input box, Send button, New Chat button.
  - Layout: New 75/25 horizontal split; left contains Packets + Details; right is Chat.
  - CSS: Ensures chat log fills available space (vertical scroll only), input row beneath, and a full-width slim green New Chat button.
- Chat Functionality:
  - Client: `AsyncOpenAI` pointed to Ollama (`OLLAMA_BASE_URL`, default `http://localhost:11434/v1`).
  - Model: `qwen3:latest` by default (override via `OLLAMA_MODEL`).
  - History: Maintains per-session messages (user/assistant) and appends to log.
  - Interactions: Click Send or press Enter to send; New Chat clears history and log.
  - Error handling: UI notifications on failures.
- Import/Widget Adjustments:
  - Replaced `TextLog` with `Log`, then with `RichLog` for true soft-wrapping.
  - Avoided attribute name clashes by using `chat_log`, `chat_input`, etc.
- Dependencies:
  - `pyproject.toml` updated with `openai>=1.30.0`.

## Configuration & Running
- Ensure dependencies installed (e.g., `uv sync`).
- Run Ollama locally and pull model once: `ollama run qwen3:latest`.
- Optional environment variables:
  - `OLLAMA_BASE_URL` (default `http://localhost:11434/v1`)
  - `OPENAI_API_KEY` (default `ollama`, required by the client but ignored by Ollama)
  - `OLLAMA_MODEL` (default `qwen3:latest`)
- Start app: run the `pktai` script (from `[project.scripts]`), or `python -m pktai_tui.app`.
- Open capture: press `o` to open a `.pcap`/`.pcapng` file.

## Quick One-Liners of What We Did
- Introduced a right-side Chat pane with dynamic soft-wrapping, hooked to Ollama via OpenAI client, with Send/Enter submit and New Chat reset.
- Refactored layout to a 75/25 split: left for packets/details, right for chat.
- Updated dependencies and CSS to support the new UX.

## Chat Pane Visual Enhancements (2025-08-09)

- Added speaker avatars in chat
  - User: `👤`; Assistant: `🤖` via `ChatPane._make_avatar()` and `.avatar` CSS class.
  - Adjusted avatar sizing and alignment (`width: 3`, top margin `1`) to align with first text line.

- Inline spinner during LLM processing
  - Shows right after the user message.
  - On response, the pending spinner row is removed and replaced with the final assistant message to avoid gaps.
  - `.inline_spinner { width: auto; height: auto; }`.

- Thought process (reasoning) expander
  - Parses `<think>...</think>` and renders a collapsible `Tree` labeled “Thought process” above assistant text.
  - Collapsed by default; constrained with `height: auto`, `min-height: 0`, `flex_grow: 0`, and hidden guides for compactness.
  - Lines pre-wrapped (`textwrap.fill`) and rendered with `rich.text.Text(..., overflow="fold")` to avoid overflow.

- Spacing and wrapping fixes
  - Eliminated large vertical gaps by removing the extra pending row and constraining the reasoning tree.
  - Tight but readable message spacing: `.msg { margin: 0 0 1 0; }`.
  - Comfortable text padding: `.bubble { padding: 1; }` and runtime `bubble.styles.padding = 1`.
  - Chat log gutter for breathing room: `#chat_log { padding: 1; }`.
  - Ensured all containers use `height: auto; min-height: 0` and no unintended flex growth.

- Message rendering structure
  - Each message row is `Horizontal` with `avatar | bubble` and scrolls to end.
  - Assistant bubble: reasoning tree (if present) above main text content.

### Files Touched
- `src/pktai_tui/app.py`
  - `ChatPane._append_message()`
  - `ChatPane._send_and_get_reply()`
  - `ChatPane._populate_assistant_bubble()`
  - Embedded CSS for `#chat_log`, `.msg`, `.avatar`, `.bubble`, `.think_tree`, `.inline_spinner`.

### Notes / Follow-ups
- Optional polish: rounded chat bubbles and subtle background color for messages.
- Potential keyboard shortcuts for expanding/collapsing the reasoning tree.

## In-memory Filtering & Slash Commands (2025-08-09)

- Added Wireshark-like in-memory filtering module and integrated it into services and app flow.

### What Changed
- `src/pktai_tui/services/filtering.py`
  - Wireshark-like display filter subset with tokenizer, parser, evaluator.
  - Exports: `filter_packets(packets, display_filter)`, `nl_to_display_filter(nl_query)`.
- `src/pktai_tui/services/capture.py`
  - Extracted `build_packet_view(packet, index)` for reuse when rebuilding UI from filtered packets.
  - `parse_capture(..., on_packet_obj=...)` collects raw pyshark packets during parse.
- `src/pktai_tui/services/__init__.py`
  - Re-exported `build_packet_view`, `filter_packets`, `nl_to_display_filter`.
- `src/pktai_tui/app.py`
  - Stores raw packets (`self._raw_packets`).
  - New methods:
    - `rebuild_from_packets(packets)` to repopulate UI from a given packet list.
    - `apply_display_filter(display_filter)` to filter and refresh UI.
    - `apply_nl_query(nl_query)` to convert NL → display filter and apply it.
  - Chat input now supports slash-commands:
    - `/df <display_filter>` applies display filter without invoking the LLM.
    - Non-slash input continues to be sent to the LLM.
- `src/pktai_tui/filtering.py`
  - Backwards-compat shim that re-exports from `pktai_tui.services.filtering` with a deprecation note.
- `tests/test_filtering.py`
  - Updated imports to `from pktai_tui.services.filtering ...`.
- `README.md`
  - Updated examples to import from `pktai_tui.services.filtering` and demonstrate `nl_to_display_filter`.

### Usage
- From TUI chat input:
  - `/df ngap && sctp.dstport == 38412`
  - `/df ip.src == 10.0.0.1 && tcp`
- Programmatically within the app:
  - `self.apply_display_filter("ngap && sctp.dstport == 38412")`
  - `self.apply_nl_query("get me all ngap packets with dst port 38412")`

### Notes / Follow-ups
- Consider caching parsed ASTs for repeat filters to speed up toggling.
- Provide a visible banner or status line showing the active display filter.
- Add more operators over time (e.g., contains, ranges) with clear error messages for unsupported ones.
