"""Provider registry."""
from .providers import Provider
from .providers.anthropic import AnthropicProvider
from .providers.custom import CustomOpenAIProvider
from .providers.deepseek import DeepSeekProvider
from .providers.ollama import OllamaProvider
from .providers.openai import OpenAIProvider
from .providers.openrouter import OpenRouterProvider
from .settings import get_settings


_PROVIDER_CLASSES = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "openrouter": OpenRouterProvider,
    "deepseek": DeepSeekProvider,
    "custom": CustomOpenAIProvider,
}


# Optional provider-specific settings forwarded into a provider's settings_dict
# when present. Single source of truth shared by the active provider and the
# provider/model pickers (commands._settings_dict_for) so the two can't drift.
_PROVIDER_SETTING_KEYS = (
    "openrouter_referer",
    "openrouter_title",
    "anthropic_models",
    "deepseek_models",
    "custom_base_url",
    "custom_models",
    "custom_label",
    "custom_api_key",
    "allow_secrets_in_settings_file",
)


def get_provider(name: str, settings_dict: dict) -> Provider:
    cls = _PROVIDER_CLASSES.get(name)
    if cls is None:
        raise ValueError("unknown provider: {0}".format(name))
    return cls(settings_dict)


def build_settings_dict(provider_name: str) -> dict:
    """Assemble the settings_dict passed to a provider constructor.

    Ollama keeps the legacy "base_url" setting for backward compatibility;
    every other provider uses its own "<name>_base_url" override (or the
    provider's built-in default when unset). Provider-specific extras are
    forwarded when present.
    """
    settings = get_settings()
    settings_dict = {
        "temperature": settings.get_temperature(),
        "max_tokens": settings.get_max_tokens(),
    }
    if provider_name == "ollama":
        base_url = settings.get_base_url()
    else:
        base_url = settings.get("{0}_base_url".format(provider_name), "") or ""
    if base_url:
        settings_dict["base_url"] = base_url
    for k in _PROVIDER_SETTING_KEYS:
        v = settings.get(k, None)
        if v is not None:
            settings_dict[k] = v
    return settings_dict


def get_active_provider() -> Provider:
    name = get_settings().get_provider()
    return get_provider(name, build_settings_dict(name))
