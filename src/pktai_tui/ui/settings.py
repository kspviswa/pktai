from __future__ import annotations

from typing import Optional, Dict, Any, List

from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, Container
from textual.widgets import Static, Button, Input, Select

# Optional Slider (depends on Textual version)
try:  # pragma: no cover - environment dependent
    from textual.widgets import Slider  # type: ignore
    HAS_SLIDER = True
except Exception:  # pragma: no cover - fallback if not present
    Slider = None  # type: ignore
    HAS_SLIDER = False

from ..services import LLMService


class SettingsScreen(ModalScreen[Optional[Dict[str, Any]]]):
    """Popup to configure LLM model and parameters.

    Dismisses with a dict of overrides or None if cancelled.
    """

    CSS = """
    SettingsScreen {
        align: center middle;
    }
    #dialog {
        width: 60;
        max-width: 80;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    #title { content-align: center middle; padding: 0 0 1 0; }
    .row { padding: 0 0 1 0; }
    #actions { padding-top: 1; }
    #value_hint { color: $text 70%; }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, *, current: Optional[Dict[str, Any]] = None) -> None:
        super().__init__()
        self._current = current or {}
        self._llm = LLMService.from_env()
        self._models: List[str] = []

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            with Vertical(id="settings_root"):
                yield Static("LLM Settings", id="title")
                # Model
                with Vertical(classes="row"):
                    yield Static("Model")
                    yield Select(options=[("Loading models...", "")], id="model_select")
                # Temperature (slider 0-100 mapped to 0-1)
                with Vertical(classes="row"):
                    yield Static("Temperature (0-1)")
                    if HAS_SLIDER:
                        with Horizontal():
                            yield Slider(id="temperature_slider", min=0, max=100, step=1)  # type: ignore[name-defined]
                            yield Static("", id="temperature_value", classes="value")
                    else:
                        with Horizontal():
                            yield Input(placeholder="0.00-1.00", id="temperature_input")
                            yield Static("", id="temperature_value", classes="value")
                # Top-p (slider 0-100 mapped to 0-1)
                with Vertical(classes="row"):
                    yield Static("Top-p (0-1)")
                    if HAS_SLIDER:
                        with Horizontal():
                            yield Slider(id="top_p_slider", min=0, max=100, step=1)  # type: ignore[name-defined]
                            yield Static("", id="top_p_value", classes="value")
                    else:
                        with Horizontal():
                            yield Input(placeholder="0.00-1.00", id="top_p_input")
                            yield Static("", id="top_p_value", classes="value")
                # Max tokens
                with Vertical(classes="row"):
                    yield Static("Max tokens")
                    yield Input(placeholder="e.g., 1024", id="max_tokens")
                # Context window
                with Vertical(classes="row"):
                    yield Static("Context window (tokens)")
                    yield Input(placeholder="e.g., 8192", id="context_window")
                # Actions
                with Horizontal(id="actions"):
                    yield Button("Save", id="save", variant="success")
                    yield Button("Cancel", id="cancel", variant="primary")

    async def on_mount(self) -> None:
        # Widgets
        model_select = self.query_one("#model_select", Select)
        temp_value = self.query_one("#temperature_value", Static)
        topp_value = self.query_one("#top_p_value", Static)
        temp_slider = self.query_one("#temperature_slider", Slider) if HAS_SLIDER else None  # type: ignore[name-defined]
        topp_slider = self.query_one("#top_p_slider", Slider) if HAS_SLIDER else None  # type: ignore[name-defined]
        temp_input = self.query_one("#temperature_input", Input) if not HAS_SLIDER else None
        topp_input = self.query_one("#top_p_input", Input) if not HAS_SLIDER else None
        max_tokens = self.query_one("#max_tokens", Input)
        context_window = self.query_one("#context_window", Input)

        # Prefill sliders
        def to_pct(v: float) -> int:
            try:
                return max(0, min(100, int(round(v * 100))))
            except Exception:
                return 0

        t_cur = self._current.get("temperature")
        if HAS_SLIDER and temp_slider is not None:
            temp_slider.value = to_pct(float(t_cur) if t_cur is not None else float(self._llm.temperature))
            temp_value.update(f"{temp_slider.value/100:.2f}")
        else:
            v = float(t_cur) if t_cur is not None else float(self._llm.temperature)
            temp_input.value = f"{v:.2f}"  # type: ignore[union-attr]
            temp_value.update(f"{v:.2f}")

        p_cur = self._current.get("top_p")
        if HAS_SLIDER and topp_slider is not None:
            topp_slider.value = to_pct(float(p_cur) if p_cur is not None else 1.0)
            topp_value.update(f"{topp_slider.value/100:.2f}")
        else:
            v = float(p_cur) if p_cur is not None else 1.0
            topp_input.value = f"{v:.2f}"  # type: ignore[union-attr]
            topp_value.update(f"{v:.2f}")

        if "max_tokens" in self._current:
            max_tokens.value = str(self._current.get("max_tokens", ""))
        if "context_window" in self._current:
            context_window.value = str(self._current.get("context_window", ""))

        # Load models asynchronously
        try:
            models = await self._llm.list_models()
            self._models = models or []
            options = [(m, m) for m in self._models]
            if not options:
                options = [(self._llm.model, self._llm.model)]
            model_select.set_options(options)
            # Select current model if present; else first
            current_model = (self._current.get("model") or self._llm.model)
            selected = current_model if any(m == current_model for m in self._models) else options[0][1]
            model_select.value = selected
        except Exception:
            model_select.set_options([(self._llm.model, self._llm.model)])
            model_select.value = self._llm.model

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # type: ignore[override]
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id == "save":
            # Collect values
            model = self.query_one("#model_select", Select).value or self._llm.model
            temp_slider = self.query_one("#temperature_slider", Slider) if HAS_SLIDER else None  # type: ignore[name-defined]
            topp_slider = self.query_one("#top_p_slider", Slider) if HAS_SLIDER else None  # type: ignore[name-defined]
            temp_input = self.query_one("#temperature_input", Input) if not HAS_SLIDER else None
            topp_input = self.query_one("#top_p_input", Input) if not HAS_SLIDER else None
            max_tokens = (self.query_one("#max_tokens", Input).value or "").strip()
            ctx_raw = (self.query_one("#context_window", Input).value or "").strip()

            def as_int(s: str) -> Optional[int]:
                try:
                    return int(s)
                except Exception:
                    return None

            overrides: Dict[str, Any] = {"model": model}
            if HAS_SLIDER and temp_slider is not None:
                overrides["temperature"] = round(temp_slider.value / 100.0, 2)
            else:
                try:
                    overrides["temperature"] = round(float((temp_input.value or "0").strip()), 2)  # type: ignore[union-attr]
                except Exception:
                    overrides["temperature"] = self._llm.temperature
            if HAS_SLIDER and topp_slider is not None:
                overrides["top_p"] = round(topp_slider.value / 100.0, 2)
            else:
                try:
                    overrides["top_p"] = round(float((topp_input.value or "1").strip()), 2)  # type: ignore[union-attr]
                except Exception:
                    overrides["top_p"] = 1.0
            mt = as_int(max_tokens)
            if mt is not None:
                overrides["max_tokens"] = mt
            ctx = as_int(ctx_raw)
            if ctx is not None:
                overrides["context_window"] = ctx

            self.dismiss(overrides)

    if HAS_SLIDER:
        def on_slider_changed(self, event: Slider.Changed) -> None:  # type: ignore[override]
            if event.slider.id == "temperature_slider":
                self.query_one("#temperature_value", Static).update(f"{event.value/100:.2f}")
            elif event.slider.id == "top_p_slider":
                self.query_one("#top_p_value", Static).update(f"{event.value/100:.2f}")
