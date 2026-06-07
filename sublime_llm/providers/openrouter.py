"""OpenRouter provider."""
from typing import Optional

from .openai import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    name = "openrouter"
    _provider_label = "OpenRouter"
    _default_base_url = "https://openrouter.ai/api/v1"
    _secret_provider_name = "openrouter"

    def _attribution_headers(self) -> dict:
        s = self.settings_dict or {}
        out = {}
        referer = s.get("openrouter_referer")
        if referer:
            out["HTTP-Referer"] = referer
        title = s.get("openrouter_title")
        if title:
            out["X-Title"] = title
        return out

    def _default_headers(self) -> dict:
        headers = super()._default_headers()
        headers.update(self._attribution_headers())
        return headers

    def _list_models_headers(self) -> Optional[dict]:
        # OpenRouter's /models endpoint does not require auth. Return only
        # attribution headers if configured, else None.
        attribution = self._attribution_headers()
        return attribution or None

    def _requires_key_for_listing(self) -> bool:
        return False
