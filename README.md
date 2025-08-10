# pktai

### AI-assisted packet analysis in your terminal 🚀🤖📦💻

<img width="300" height="300" alt="pktai_logo" src="https://github.com/user-attachments/assets/6c81e7e1-6ae2-4335-b354-fb92cebd91d2" />

## Wireshark-like in-memory filtering

You can filter a preloaded list of PyShark packets without spawning tshark using `filter_packets` in `pktai_tui.services.filtering`.

Example:

```python
import pyshark
from pktai_tui.services.filtering import filter_packets, nl_to_display_filter

cap = pyshark.FileCapture("trace.pcapng")
packets = list(cap)  # materialize first

# Keep NGAP packets with a specific SCTP destination port
df = nl_to_display_filter("get me all ngap packets with dst port 38412")
ngap_pkts = filter_packets(packets, df)
print(len(ngap_pkts))
```

Supported subset: protocol-only tokens (e.g., `tcp`, `ngap`), field presence (`ip.src`), equality/inequality on common fields (`ip.src == 1.2.3.4`, `sctp.dstport != 38412`), and logical `&&`/`||` with parentheses. Unsupported operators like `contains`/`matches` will raise `NotImplementedError`.

In the TUI, the app collects raw packet objects during parsing and exposes:
- `PktaiTUI.apply_display_filter("ngap && sctp.dstport == 38412")`
- `PktaiTUI.apply_nl_query("get me all ngap packets")` (returns the derived display filter)
