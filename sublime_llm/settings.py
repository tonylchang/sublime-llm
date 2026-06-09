"""Settings reader for sublime-llm."""
import json
import os
import re
from typing import Any, Callable, List, Optional

try:
    import sublime  # type: ignore
except ImportError:
    sublime = None  # type: ignore

SETTINGS_FILENAME = "LLM.sublime-settings"
_ON_CHANGE_KEY = "sublime-llm"

DEFAULTS = {
    "provider": "ollama",
    "model": "llama3.2",
    "base_url": "http://localhost:11434",
    "temperature": 0.7,
    "max_tokens": 4096,
    "system_prompt": "",
}

PLACEHOLDER_PATTERNS = [
    re.compile(r"REPLACE_ME", re.I),
    re.compile(r"YOUR_KEY_HERE", re.I),
    re.compile(r"\.\.\.\.+"),
]

def is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    if not value.strip():
        return True
    for pat in PLACEHOLDER_PATTERNS:
        if pat.search(value):
            return True
    return False


def _strip_json_comments(text: str) -> str:
    out = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if nxt == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _load_from_file() -> dict:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, SETTINGS_FILENAME)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        return json.loads(_strip_json_comments(raw))
    except json.JSONDecodeError:
        return {}


class Settings:
    def __init__(self) -> None:
        self._callbacks: List[Callable[[], None]] = []
        self._sublime_settings = None
        self._file_cache: Optional[dict] = None
        if sublime is not None:
            try:
                self._sublime_settings = sublime.load_settings(SETTINGS_FILENAME)
                self._sublime_settings.add_on_change(_ON_CHANGE_KEY, self._on_change)
            except Exception:
                self._sublime_settings = None

    def _on_change(self) -> None:
        for cb in list(self._callbacks):
            try:
                cb()
            except Exception:
                pass

    def add_on_change(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)

    def _external_active_provider(self) -> Optional[str]:
        try:
            from .secrets import get_active_provider_from_external_config
            return get_active_provider_from_external_config()
        except Exception:
            return None

    def _external_provider_config(self, provider_name: str) -> dict:
        try:
            from .secrets import get_provider_config
            return get_provider_config(provider_name)
        except Exception:
            return {}

    def _get_without_external(self, key: str) -> Any:
        default = DEFAULTS.get(key)
        if self._sublime_settings is not None:
            return self._sublime_settings.get(key, default)
        if self._file_cache is None:
            self._file_cache = _load_from_file()
        return self._file_cache.get(key, default)

    def _external_value_for_key(self, key: str):
        provider = self._external_active_provider() or self._get_without_external("provider")
        provider_cfg = self._external_provider_config(str(provider)) if provider else {}
        if key == "provider":
            return self._external_active_provider()
        if key == "model":
            return provider_cfg.get("model")
        if key == "base_url":
            return provider_cfg.get("base_url")
        if key.endswith("_base_url"):
            provider_name = key[: -len("_base_url")]
            return self._external_provider_config(provider_name).get("base_url")
        if key.endswith("_model"):
            provider_name = key[: -len("_model")]
            return self._external_provider_config(provider_name).get("model")
        mapping = {
            "openrouter_referer": ("openrouter", "referer"),
            "openrouter_title": ("openrouter", "title"),
            "anthropic_models": ("anthropic", "models"),
            "deepseek_models": ("deepseek", "models"),
            "custom_base_url": ("custom", "base_url"),
            "custom_models": ("custom", "models"),
            "custom_label": ("custom", "label"),
            "custom_api_key": ("custom", "api_key"),
        }
        pair = mapping.get(key)
        if pair is not None:
            provider_name, field = pair
            return self._external_provider_config(provider_name).get(field)
        return None

    def _get(self, key: str) -> Any:
        external = self._external_value_for_key(key)
        if external is not None:
            return external
        return self._get_without_external(key)

    def get(self, key: str, default: Any = None) -> Any:
        external = self._external_value_for_key(key)
        if external is not None:
            return external
        # Fall back through DEFAULTS so callers see the same values that the
        # typed accessors (get_provider, etc.) return.
        fallback = DEFAULTS.get(key, default)
        if self._sublime_settings is not None:
            return self._sublime_settings.get(key, fallback)
        if self._file_cache is None:
            self._file_cache = _load_from_file()
        return self._file_cache.get(key, fallback)

    def get_provider(self) -> str:
        return str(self._get("provider"))

    def get_model(self) -> str:
        return str(self._get("model"))

    def get_base_url(self) -> str:
        return str(self._get("base_url"))

    def get_temperature(self) -> float:
        return float(self._get("temperature"))

    def get_max_tokens(self) -> int:
        return int(self._get("max_tokens"))

    def get_system_prompt(self) -> str:
        return str(self._get("system_prompt"))


_instance: Optional[Settings] = None


def get_settings() -> Settings:
    global _instance
    if _instance is None:
        _instance = Settings()
    return _instance
