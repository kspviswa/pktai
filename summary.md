### Chat Stop/Cancel Button (2025-08-10)

- Added interrupt support for in-flight LLM responses in the Chat pane.

#### What Changed
- `src/pktai_tui/app.py`
  - When a prompt is sent, the blue "Send" button toggles to a red "Stop" button.
  - Pressing "Stop" cancels the in-flight background worker running the LLM call.
  - On cancel, the pending spinner row is removed and a system line "(generation stopped)" is appended.
  - After completion or cancellation, the button reverts back to blue "Send".
  - Internals: stores the worker handle (`self._current_worker`) and catches `asyncio.CancelledError` to clean up UI state.

#### Usage
- Type a prompt and press Send; to interrupt, press Stop.

#### Notes / Follow-ups
- Streaming plus partial rendering would pair well with Stop for better UX; we can add token-level streaming next.
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

## LLM Abstraction, Settings Modal, and Markdown Chat (2025-08-09)

- Introduced a services-layer abstraction for the LLM and added a compact, modal Settings screen with model selection and generation controls. Enhanced the chat pane to render Markdown natively.

### What Changed
- `src/pktai_tui/services/llm.py`
  - Added `LLMService` encapsulating OpenAI-compatible chat.
  - `from_env()` reads `OLLAMA_BASE_URL`, `OPENAI_API_KEY`, `OLLAMA_MODEL`, and optional `LLM_TEMPERATURE`.
  - `chat(messages, model, temperature, top_p, max_tokens, extra)` to support per-call overrides.
  - `list_models()` to enumerate models from the Ollama/OpenAI-compatible server.
- `src/pktai_tui/services/__init__.py`
  - Exported `LLMService`.
- `src/pktai_tui/app.py`
  - `ChatPane` now uses `LLMService` instead of constructing `AsyncOpenAI` directly.
  - Added Settings shortcut binding: `("s", "open_settings", "Settings")` and session-scoped overrides storage (`_llm_overrides`).
  - LLM calls apply overrides if present.
  - Chat messages now render Markdown:
    - Uses `textual.widgets.Markdown` when available.
    - Fallback to `Static` with `rich.markdown.Markdown` renderable.
- `src/pktai_tui/ui/settings.py`
  - New `SettingsScreen` as a centered `ModalScreen` (popover-style) with a slim dialog.
  - Model dropdown populated via `LLMService.list_models()`; selects current or first available.
  - Controls: temperature and top_p (sliders when available, else inputs), max_tokens and context_window inputs.
  - Save dismisses the modal and persists overrides to the app; Cancel/Esc discards.
  - Robustness:
    - Handles environments without `textual.widgets.Slider` by falling back to inputs.
    - Fixed duplicate ID issue by using `.row` class for section containers (no repeated IDs).
- `src/pktai_tui/ui/__init__.py`
  - Exported `SettingsScreen`.

### Usage
- Open Settings: press `s`.
- Pick a model and adjust temperature/top_p (sliders or inputs), set max tokens/context window, then Save.
- If Settings is never opened, env defaults are used (`OLLAMA_MODEL`, `LLM_TEMPERATURE`, etc.).
- Chat supports Markdown formatting in both user and assistant messages.

### Notes / Follow-ups
- Optional persistence: write overrides to a config file to survive restarts.
- Streaming responses could improve perceived latency; add streaming support in `LLMService` and UI.
- Consider exposing nucleus/top-k and presence/frequency penalties if backend supports them.

## Agentic Orchestrator & Sub-Agents (2025-08-10)

- Added an in-repo orchestrator that routes chat input between Chat, Packet, and Packet Filter agents. NL display-filter requests immediately update the packets pane.

### What Changed
- added config file support
- `src/pktai_tui/services/agents.py`
  - Implemented `Orchestrator.route()` with filter-first heuristic; accepts a filter only if it parses via our `Lexer`/`Parser` (prevents misrouting packet questions).
  - Implemented `ChatAgent`, `PacketAgent`, `PacketFilterAgent` with output sanitation (removes `<think>` and code fences).
  - `PacketFilterAgent.is_valid_display_filter()` to validate LLM-produced filters.
- `src/pktai_tui/app.py`
  - `ChatPane` now calls the orchestrator; on `mode == "filter"`, calls `apply_display_filter()` and echoes: `Applied display filter: <filter>`.
  - Added `PktaiTUI.get_raw_packets()` accessor used by the orchestrator flow.
- `src/pktai_tui/services/capture.py`
  - Added `packets_to_text(packets, max_packets, max_chars)` to build a compact textual dump of the capture for the Packet Agent context.

### Usage
- NL filter: "get me all NGAP packets" → applies `ngap` and the packets pane reflects filtered results; chat shows a short confirmation.
- Packet analysis: "What can you tell me about this packet capture?" → routes to Packet Agent and answers based on the current capture context.

### Notes / Follow-ups
- Tune classification prompts and sampling of packet dump for very large captures.
- Add unit tests for `packets_to_text()` and filter validation edge cases.
- Consider showing the active display filter in the UI status area.

### YAML Providers Config & Settings Refactor (2025-08-12)

- Settings pane is now fully YAML-driven from `~/.pktai/pktai.yaml`. The file is auto-created on first run with a fact-checked providers template.

#### What Changed
- `src/pktai_tui/services/config.py`
  - Renamed config to `pktai.yaml` (under `~/.pktai/`).
  - `ensure_initialized()` seeds providers (Perplexity, OpenAI, Together, Groq, Fireworks, OpenRouter, DeepInfra, Ollama, LM Studio, Anthropic, Google Gemini, Cohere, Mistral). Removed Azure OpenAI.
- `src/pktai_tui/ui/settings.py`
  - Provider list comes only from YAML plus a “Custom” UI option.
  - API keys now load from YAML on open and when provider changes.
  - Save persists to YAML:
    - Known providers: saves `api_key` and `base_url` under the provider alias.
    - Custom providers: requires Alias + Base URL; checks alias conflicts (toast on conflict); saves `api_key`, `base_url`, `supports_list: false`, and `static_models` parsed from a comma-separated model input. The first model is used as the session model.
  - Custom model input placeholder: “Comma-separated models (e.g., modelA, modelB)”.
  - If a provider doesn’t support listing, static models from YAML populate the dropdown.
- `src/pktai_tui/app.py`
  - Ensures `~/.pktai/pktai.yaml` exists at startup.

#### Usage
- Press `s` to open Settings.
- Known provider: edit Base URL/API Key and Save to persist to YAML.
- Custom provider: enter Alias, Base URL, and comma-separated Models; Save to create a new YAML entry (with alias conflict protection).
- Reopen Settings or switch providers; saved API keys auto-populate.

## Wireshark-like Data Viewer in Details Pane (2025-08-12)

- Added a hex+ASCII Data Viewer beneath the packet details `Tree` that updates as you traverse fields, similar to Wireshark's data view.
- Selection/highlight sync: selecting or highlighting a field in `#details` updates the viewer and applies a subtle highlight to the viewer body.
- Parsing heuristics to derive bytes from detail lines:
  - Hex sequences like `aa bb cc` or `aa:bb:cc`.
  - `0x...` hex integers and decimal integers.
  - Fallback to UTF-8 bytes of the value text when needed.
- Safety/UX guards:
  - Viewer starts empty on app launch and remains empty until a capture is loaded.
  - Ignores updates when no capture is loaded and when the `Tree` root node is selected.

### What Changed
- `src/pktai_tui/ui/data_viewer.py`
  - New `DataViewer` widget rendering a classic hexdump (16 bytes/row) with left offsets and ASCII.
- `src/pktai_tui/ui/__init__.py`
  - Exported `DataViewer`.
- `src/pktai_tui/app.py`
  - Imported and mounted `DataViewer` under `#details` in the left column.
  - CSS layout updated: `PacketList { height: 3fr }`, `#details { height: 4fr }`, `#data_viewer { height: 1fr }`.
  - Event wiring: update viewer on `Tree.NodeHighlighted` and `Tree.NodeSelected`.
  - Clear viewer on mount and when packet selection changes; added `_has_capture_loaded()` helper to guard updates.

### Usage
- Open a capture (press `o`). Select a packet row; the details `Tree` populates.
- Move selection within `#details`; the Data Viewer shows the selected field in hex + ASCII.

### Notes / Follow-ups
- Consider mapping exact byte ranges via pyshark-provided offsets for per-byte highlighting.
- Add copy-to-clipboard for hex and a byte count/length header in the viewer.
