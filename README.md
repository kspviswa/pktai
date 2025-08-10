# pktai

### AI-assisted packet analysis in your terminal 🚀🤖📦💻

<img width="300" height="300" alt="pktai_logo" src="https://github.com/user-attachments/assets/6c81e7e1-6ae2-4335-b354-fb92cebd91d2" />

Meet pktai — a modern, Textual-powered TUI that blends Wireshark-like workflows with an AI copilot. Open a pcap, browse packets, and chat with an on-device LLM (via Ollama) to explain what’s going on. Apply Wireshark-style display filters or just ask in natural language — pktai routes the request to the right tool, instantly.

Project URL: https://github.com/kspviswa/pktai

![](pktai_screen.png)

### Demo : https://www.youtube.com/watch?v=GnPRs-cBtQM 

## Highlights

- **Packet-first UI**: Left pane shows packets and expandable per-layer details.
- **Built-in Chat Copilot**: Right pane is a chat that understands your capture context.
- **Wireshark-like Filters**: Apply display filters inline or via slash commands.
- **NL → Filter**: Ask “get me all NGAP packets” — pktai applies `ngap` automatically.
- **Instant Stop**: Cancel in-flight LLM responses with a Stop button.
- **Zero mouse, pure keyboard**: Fast and ergonomic terminal UX powered by Textual.

## Installation

Requires Python 3.10+.

- Using pip:
  ```bash
  pip install pktai
  ```
- Using uv:
  ```bash
  uv add pktai
  ```

This installs the `pktai` command.

## Quickstart

1) Optional: run a local LLM with Ollama (default model `qwen3:latest`):
```bash
ollama run qwen3:latest
```

2) Launch pktai:
```bash
pktai
```

3) Open a capture file: press `o` and pick a `.pcap`/`.pcapng`.

## Using pktai

- **Browse packets**: Navigate the left pane; expand layers to inspect fields.
- **Chat analysis**: Ask questions in the right chat pane (e.g., “summarize traffic patterns”).
- **Stop generation**: While the model is responding, click `Stop` to cancel.
- **Display filter (slash command)**: Type:
  - `/df ngap && sctp.dstport == 38412`
  - `/df ip.src == 10.0.0.1 && tcp`
  This applies the filter immediately without calling the LLM.
- **Natural language filter**: Ask “show only NGAP packets with dst port 38412” — pktai converts NL → display filter and applies it.
- **Settings**: Press `s` to open a compact Settings modal; choose model and tune generation parameters.

## Feature Deep Dive

- **Agentic Orchestrator**: Routes your input between Filter, Packet, and Chat agents.
- **Filtering Engine**: Tokenizer + parser + evaluator for a practical Wireshark-like subset:
  - Protocol tokens (e.g., `tcp`, `ngap`), field presence (e.g., `ip.src`), equality/inequality on common fields (e.g., `ip.src == 1.2.3.4`, `sctp.dstport != 38412`), boolean `&&`/`||` with parentheses.
  - Unsupported operators like `contains`/`matches` raise a clear error.
- **LLM Abstraction**: `LLMService` (OpenAI-compatible) talks to Ollama; switch models easily.
- **Markdown Chat**: Renders assistant replies nicely; optional expandable “Thought process”.
- **Responsive UX**: Soft-wrapping chat log, tight spacing, and a cancelable generation flow.

## Tips & Troubleshooting

- If the chat doesn’t work, ensure Ollama is running and the model is available: `ollama run qwen3:latest`.
- To start without chat, simply use filtering and packet browsing; chat can be configured later.

## Project

- Repository: https://github.com/kspviswa/pktai

## License

MIT — see `LICENSE`.
