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
