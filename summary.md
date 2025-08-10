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
