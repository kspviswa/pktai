from __future__ import annotations

from typing import Optional, Dict, Any, List, Tuple

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
from ..services.config import (
    ensure_initialized as cfg_ensure_initialized,
    list_providers as cfg_list_providers,
    upsert_provider as cfg_upsert_provider,
)


class SettingsScreen(ModalScreen[Optional[Dict[str, Any]]]):
    """Popup to configure LLM model and parameters.

    Dismisses with a dict of overrides or None if cancelled.
    """

    CSS = """
    SettingsScreen {
        align: center middle;
    }
    #dialog {
        width: 90;
        max-width: 120;
        border: round $primary;
        padding: 1 3;
        background: $surface;
    }
    #title { content-align: center middle; padding: 0 0 1 0; }
    .row { padding: 0 0 1 0; }
    #actions { padding-top: 1; }
    #value_hint { color: $text 70%; }
    .inline { layout: horizontal; }
    #provider_row Select { width: 1fr; }
    /* Make form controls expand for breathing room */
    .row Input { width: 1fr; }
    .row Select { width: 1fr; }
    /* Model row specifics: let selector/input grow; keep test button compact */
    #model_select { width: 1fr; }
    #model_input { width: 1fr; }
    #test_btn { width: 8; margin-left: 1; }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, *, current: Optional[Dict[str, Any]] = None) -> None:
        super().__init__()
        self._current = current or {}
        self._llm = LLMService.from_env()
        self._models: List[str] = []
        # Provider presets populated from ~/.pktai/pktai.yaml only
        self._presets: Dict[str, Tuple[str, str]] = {}
        # Load user providers from YAML (~/.pktai/pktai.yaml)
        self._supports_list: Dict[str, bool] = {}
        self._static_models: Dict[str, List[str]] = {}
        try:
            cfg_ensure_initialized()
            for p in cfg_list_providers():
                alias = str(p.get("alias") or "").strip()
                if not alias:
                    continue
                base_url = str(p.get("base_url") or "").strip()
                api_key = str(p.get("api_key") or "")
                if base_url:
                    # Add/override preset for this alias
                    self._presets[alias] = (base_url, api_key)
                self._supports_list[alias] = bool(p.get("supports_list", True))
                sm = p.get("static_models") or []
                if isinstance(sm, list):
                    self._static_models[alias] = [str(x) for x in sm if isinstance(x, (str, int, float))]
            # Always include a Custom option as a UI affordance (not a provider preset)
            self._presets["Custom"] = ("", "")
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            with Vertical(id="settings_root"):
                yield Static("LLM Settings", id="title")
                # Provider / host
                with Vertical(classes="row", id="provider_row"):
                    yield Static("Model host (provider)")
                    yield Select(options=[(k, k) for k in self._presets.keys()], id="provider_select")
                # Base URL + API key
                with Vertical(classes="row"):
                    yield Static("Base URL")
                    yield Input(placeholder="https://.../v1", id="base_url")
                with Vertical(classes="row"):
                    yield Static("API Key")
                    yield Input(placeholder="sk-...", password=True, id="api_key")
                # Alias (only for Custom provider)
                with Vertical(classes="row", id="alias_row"):
                    yield Static("Alias")
                    yield Input(placeholder="e.g., My Provider", id="alias")
                # Model
                with Vertical(classes="row"):
                    yield Static("Model")
                    with Horizontal(classes="inline"):
                        # Dropdown is used for known providers; hidden for Custom
                        yield Select(options=[("Loading models...", "")], id="model_select")
                        # Free-text input used for Custom provider
                        yield Input(placeholder="Comma-separated models (e.g., modelA, modelB)", id="model_input")
                        # Compact test connection button (hidden for Custom)
                        yield Button("🔌", id="test_btn", variant="primary")
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
        model_input = self.query_one("#model_input", Input)
        provider_select = self.query_one("#provider_select", Select)
        base_url_in = self.query_one("#base_url", Input)
        api_key_in = self.query_one("#api_key", Input)
        alias_row = self.query_one("#alias_row", Vertical)
        alias_in = self.query_one("#alias", Input)
        temp_value = self.query_one("#temperature_value", Static)
        topp_value = self.query_one("#top_p_value", Static)
        temp_slider = self.query_one("#temperature_slider", Slider) if HAS_SLIDER else None  # type: ignore[name-defined]
        topp_slider = self.query_one("#top_p_slider", Slider) if HAS_SLIDER else None  # type: ignore[name-defined]
        temp_input = self.query_one("#temperature_input", Input) if not HAS_SLIDER else None
        topp_input = self.query_one("#top_p_input", Input) if not HAS_SLIDER else None
        max_tokens = self.query_one("#max_tokens", Input)
        context_window = self.query_one("#context_window", Input)

        # Prefill provider/base_url/api_key/model from current or env
        # Determine initial provider based on current/base_url
        cur = dict(self._current)
        init_base = str(cur.get("base_url") or self._llm.base_url)
        init_key = str(cur.get("api_key") or self._llm.api_key)
        init_model = str(cur.get("model") or self._llm.model)
        # Pick provider by matching base URL prefix among YAML providers (fallback: Custom)
        prov = "Custom"
        for name, (url, _k) in self._presets.items():
            if name != "Custom" and url and init_base.startswith(url):
                prov = name
                break
        provider_select.value = prov
        base_url_in.value = init_base
        # Alias visibility and value (only for Custom)
        try:
            is_custom = prov == "Custom"
            # Toggle alias row
            try:
                alias_row.display = is_custom  # type: ignore[attr-defined]
            except Exception:
                try:
                    alias_row.styles.display = "block" if is_custom else "none"
                except Exception:
                    pass
            # Toggle model input vs select and test button
            try:
                model_input.display = is_custom  # type: ignore[attr-defined]
            except Exception:
                try:
                    model_input.styles.display = "block" if is_custom else "none"
                except Exception:
                    pass
            try:
                model_select.display = not is_custom  # type: ignore[attr-defined]
            except Exception:
                try:
                    model_select.styles.display = "block" if not is_custom else "none"
                except Exception:
                    pass
            try:
                test_btn = self.query_one("#test_btn", Button)
                try:
                    test_btn.display = not is_custom  # type: ignore[attr-defined]
                except Exception:
                    test_btn.styles.display = "block" if not is_custom else "none"
            except Exception:
                pass
        except Exception:
            pass
        # Prefill alias and model input values when Custom
        if prov == "Custom":
            alias_in.value = str(self._current.get("alias", ""))
            model_input.value = init_model if init_model else ""
        # Prefill API key: prefer explicit override; else YAML preset; special-case Ollama placeholder
        try:
            preset_key = ""
            if prov in self._presets:
                _url, preset_key = self._presets.get(prov, ("", ""))
            # If user didn't explicitly pass an override, use preset key from YAML
            key_val = init_key if str(cur.get("api_key") or "") else preset_key
            if prov.startswith("Ollama") and not key_val:
                api_key_in.value = ""
                try:
                    api_key_in.placeholder = "API KEY NOT NEEDED"
                except Exception:
                    pass
            else:
                api_key_in.value = key_val or ""
        except Exception:
            api_key_in.value = init_key
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

        # Load models for initial provider: use static list if provider doesn't support list()
        if prov != "Custom":
            try:
                if self._supports_list.get(prov, True) is False:
                    static_list = self._static_models.get(prov, [])
                    options = [(m, m) for m in static_list] or [(self._llm.model or "", self._llm.model or "")]
                    model_select.set_options(options)
                    model_select.value = options[0][1]
                else:
                    models = await self._llm.list_models()
                    self._models = models or []
                    options = [(m, m) for m in self._models]
                    if not options:
                        options = [(self._llm.model or "", self._llm.model or "")]
                    model_select.set_options(options)
                    # Selection policy: if user has not overridden a model, prefer the first discovered model
                    user_overrode_model = bool(cur.get("model"))
                    if not user_overrode_model and options:
                        model_select.value = options[0][1]
                    else:
                        current_model = init_model
                        selected = current_model if any(m == current_model for m in self._models) else options[0][1]
                        model_select.value = selected
            except Exception:
                model_select.set_options([(self._llm.model or "", self._llm.model or "")])
                model_select.value = init_model or (self._llm.model or "")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # type: ignore[override]
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id == "test_btn":
            # If provider doesn't support list(), load static models from YAML instead of calling list()
            provider = self.query_one("#provider_select", Select).value or "Custom"
            if self._supports_list.get(str(provider), True) is False:
                static_list = self._static_models.get(str(provider), [])
                model_select = self.query_one("#model_select", Select)
                options = [(m, m) for m in static_list] or [(self._llm.model or "", self._llm.model or "")]
                model_select.set_options(options)
                model_select.value = options[0][1]
                self.app.notify("Loaded static models from ~/.pktai/pktai.yaml", severity="information")
                return
            # Otherwise, build a temporary client and try to list models
            base_url = (self.query_one("#base_url", Input).value or "").strip()
            api_key = (self.query_one("#api_key", Input).value or "").strip()
            # Apply preset if chosen and fields are empty
            if provider in self._presets:
                preset_url, _preset_key = self._presets[provider]
                if not base_url:
                    base_url = preset_url
            if not base_url:
                self.app.notify("Base URL is required to test.", severity="warning")
                return
            try:
                tmp = LLMService.from_config(base_url=base_url, api_key=api_key or "", model=self._llm.model)
                worker = self.app.run_worker(self._do_test_and_update(tmp))
                setattr(self, "_test_worker", worker)
            except Exception as e:
                self.app.notify(f"Test failed: {e}", severity="error")
            return
        if event.button.id == "save":
            # Collect values
            provider = self.query_one("#provider_select", Select).value or "Custom"
            base_url = (self.query_one("#base_url", Input).value or "").strip()
            api_key = (self.query_one("#api_key", Input).value or "").strip()
            # Apply preset defaults if any missing
            if provider in self._presets:
                preset_url, preset_key = self._presets[provider]
                base_url = base_url or preset_url
                api_key = api_key or preset_key
            # Model: from input for Custom (comma-separated), from select otherwise
            if provider == "Custom":
                model_raw = (self.query_one("#model_input", Input).value or "").strip()
                models_list = [m.strip() for m in model_raw.split(",") if m.strip()]
                model = models_list[0] if models_list else ""
            else:
                model = self.query_one("#model_select", Select).value or (self._llm.model or "")
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

            overrides: Dict[str, Any] = {"model": model, "base_url": base_url, "api_key": api_key, "provider": provider}
            if provider == "Custom":
                alias_val = (self.query_one("#alias", Input).value or "").strip()
                if alias_val:
                    overrides["alias"] = alias_val
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

            # Persist to YAML
            try:
                if provider == "Custom":
                    # Require alias and base_url; prevent alias conflict
                    alias_val = (self.query_one("#alias", Input).value or "").strip()
                    if not alias_val or not base_url:
                        self.app.notify("Alias and Base URL are required for Custom provider.", severity="warning")
                        return
                    # Conflict check
                    existing = {str(p.get("alias")) for p in cfg_list_providers() if isinstance(p, dict)}
                    if alias_val in existing:
                        self.app.notify(f"Alias '{alias_val}' already exists. Choose a different name.", severity="error")
                        return
                    # Persist with static_models (from comma-separated input) and supports_list=False
                    cfg_upsert_provider(
                        alias=alias_val,
                        base_url=base_url,
                        api_key=api_key,
                        supports_list=False,
                        static_models=models_list if 'models_list' in locals() else [],
                    )
                else:
                    # Known provider: persist updated api_key/base_url under its alias
                    cfg_upsert_provider(alias=str(provider), base_url=base_url, api_key=api_key)
            except Exception as e:
                self.app.notify(f"Failed to save provider: {e}", severity="error")
                return
            self.dismiss(overrides)

    if HAS_SLIDER:
        def on_slider_changed(self, event: Slider.Changed) -> None:  # type: ignore[override]
            if event.slider.id == "temperature_slider":
                self.query_one("#temperature_value", Static).update(f"{event.value/100:.2f}")
            elif event.slider.id == "top_p_slider":
                self.query_one("#top_p_value", Static).update(f"{event.value/100:.2f}")

    async def _do_test_and_update(self, tmp: LLMService) -> None:
        """Run connectivity test and update model list on success."""
        try:
            ok, ids, err = await tmp.ping()
            model_select = self.query_one("#model_select", Select)
            if ok:
                opts = [(m, m) for m in (ids or [])]
                if not opts:
                    opts = [(tmp.model, tmp.model)]
                model_select.set_options(opts)
                model_select.value = opts[0][1]
                self.app.notify("Connection ok.", severity="information")
            else:
                self.app.notify(f"Connection failed: {err}", severity="error")
        except Exception as e:
            self.app.notify(f"Test error: {e}", severity="error")

    def on_select_changed(self, event: Select.Changed) -> None:  # type: ignore[override]
        # When provider changes, immediately set base URL; fill API key only if empty
        if event.select.id == "provider_select":
            name = str(event.value or "")
            preset = self._presets.get(name)
            if preset is None:
                return
            url, key = preset
            base_url_in = self.query_one("#base_url", Input)
            api_key_in = self.query_one("#api_key", Input)
            base_url_in.value = url or ""
            # Load API key from YAML preset for the selected provider
            api_key_in.value = key or ""
            try:
                if name.startswith("Ollama") and not api_key_in.value:
                    api_key_in.placeholder = "API KEY NOT NEEDED"
                else:
                    api_key_in.placeholder = "sk-..."
            except Exception:
                pass
            # If provider doesn't support list(), set model dropdown to static list now
            try:
                if self._supports_list.get(name, True) is False:
                    ms = self.query_one("#model_select", Select)
                    models = self._static_models.get(name, [])
                    opts = [(m, m) for m in models]
                    if not opts:
                        opts = [(self._llm.model or "", self._llm.model or "")]
                    ms.set_options(opts)
                    ms.value = opts[0][1]
            except Exception:
                pass
            # Toggle UI depending on provider
            try:
                model_select = self.query_one("#model_select", Select)
                model_input = self.query_one("#model_input", Input)
                alias_row = self.query_one("#alias_row", Vertical)
                test_btn = self.query_one("#test_btn", Button)
                is_custom = name == "Custom"
                # Alias row
                try:
                    alias_row.display = is_custom  # type: ignore[attr-defined]
                except Exception:
                    try:
                        alias_row.styles.display = "block" if is_custom else "none"
                    except Exception:
                        pass
                # Model input vs select
                try:
                    model_input.display = is_custom  # type: ignore[attr-defined]
                except Exception:
                    try:
                        model_input.styles.display = "block" if is_custom else "none"
                    except Exception:
                        pass
                try:
                    model_select.display = not is_custom  # type: ignore[attr-defined]
                except Exception:
                    try:
                        model_select.styles.display = "block" if not is_custom else "none"
                    except Exception:
                        pass
                # Test button hidden for Custom
                try:
                    test_btn.display = not is_custom  # type: ignore[attr-defined]
                except Exception:
                    try:
                        test_btn.styles.display = "block" if not is_custom else "none"
                    except Exception:
                        pass
                # For non-Custom, clear models until user tests connection
                if not is_custom:
                    try:
                        model_select.set_options([("Click the button to load models", "")])
                        model_select.value = ""
                    except Exception:
                        pass
            except Exception:
                pass
