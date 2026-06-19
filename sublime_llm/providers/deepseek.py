"""DeepSeek provider."""
import json
import urllib.error
from typing import List

from ..logging_setup import get_logger
from .openai import OpenAIProvider

_log = get_logger()

_DEFAULT_MODELS = ["deepseek-v4-flash", "deepseek-v4-pro"]


class DeepSeekProvider(OpenAIProvider):
    name = "deepseek"
    _provider_label = "DeepSeek"
    _default_base_url = "https://api.deepseek.com"
    _secret_provider_name = "deepseek"

    def _fallback_models(self) -> List[str]:
        s = self.settings_dict or {}
        configured = s.get("deepseek_models")
        if isinstance(configured, list) and configured:
            return list(configured)
        return list(_DEFAULT_MODELS)

    def list_models(self) -> List[str]:
        headers = self._list_models_headers()
        if headers is None:
            return self._fallback_models()
        url = self.base_url + "/models"
        try:
            resp = self._open_url(url, method="GET", headers=headers, timeout=5)
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:
                pass
            _log.warning(
                "%s list_models: request failed (HTTPError); using fallback list",
                self.name,
            )
            return self._fallback_models()
        except Exception as e:
            _log.warning(
                "%s list_models: request failed (%s); using fallback list",
                self.name,
                type(e).__name__,
            )
            return self._fallback_models()
        try:
            code = resp.getcode()
        except Exception:
            code = 0
        if code != 200:
            try:
                resp.close()
            except Exception:
                pass
            _log.warning(
                "%s list_models: HTTP %d; using fallback list", self.name, code
            )
            return self._fallback_models()
        try:
            raw = resp.read()
        except Exception:
            return self._fallback_models()
        finally:
            try:
                resp.close()
            except Exception:
                pass
        try:
            data = json.loads(raw.decode("utf-8"))
            models = [
                m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m
            ]
        except Exception:
            return self._fallback_models()
        if not models:
            return self._fallback_models()
        models.sort()
        return models
