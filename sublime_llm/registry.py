"""Provider registry."""
from sublime_llm.providers import Provider
from sublime_llm.providers.anthropic import AnthropicProvider
from sublime_llm.providers.custom import CustomOpenAIProvider
from sublime_llm.providers.deepseek import DeepSeekProvider
from sublime_llm.providers.ollama import OllamaProvider
from sublime_llm.providers.openai import OpenAIProvider
from sublime_llm.providers.openrouter import OpenRouterProvider
from sublime_llm.settings import get_settings


_PROVIDER_CLASSES = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "openrouter": OpenRouterProvider,
    "deepseek": DeepSeekProvider,
    "custom": CustomOpenAIProvider,
}


def get_provider(name: str, settings_dict: dict) -> Provider:
    cls = _PROVIDER_CLASSES.get(name)
    if cls is None:
        raise ValueError("unknown provider: {0}".format(name))
    return cls(settings_dict)


def get_active_provider() -> Provider:
    settings = get_settings()
    name = settings.get_provider()
    settings_dict = {
        "temperature": settings.get_temperature(),
        "max_tokens": settings.get_max_tokens(),
    }
    # Per-provider base URL. Ollama keeps the legacy "base_url" setting for
    # backward compatibility; every other provider uses its own
    # "<name>_base_url" override (or its built-in default if unset).
    if name == "ollama":
        base_url = settings.get_base_url()
    else:
        base_url = settings.get("{0}_base_url".format(name), "") or ""
    if base_url:
        settings_dict["base_url"] = base_url
    # Provider-specific extras are looked up lazily via settings.get() inside
    # callers (e.g. commands._settings_dict_for); registry only seeds shared
    # defaults so that callers without those extras still get a working
    # provider.
    for k in (
        "openrouter_referer",
        "openrouter_title",
        "anthropic_models",
        "deepseek_models",
        "custom_base_url",
        "custom_models",
        "custom_label",
        "custom_api_key",
    ):
        v = settings.get(k, None)
        if v is not None:
            settings_dict[k] = v
    return get_provider(name, settings_dict)
