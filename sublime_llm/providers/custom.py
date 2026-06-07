"""Custom OpenAI-compatible provider."""
import json
import socket
import urllib.error
from typing import List, Optional

from ..logging_setup import get_logger
from .base import ProviderHealth
from .openai import OpenAIProvider, _normalize_base_url

_log = get_logger()


class CustomOpenAIProvider(OpenAIProvider):
    name = "custom"
    _secret_provider_name = "custom"
    _default_base_url = ""

    def __init__(self, settings_dict: dict) -> None:
        s = settings_dict or {}
        # Label is user-configurable for error messages.
        self._provider_label = s.get("custom_label", "Custom")
        super().__init__(settings_dict)
        raw = s.get("custom_base_url") or s.get("base_url") or ""
        self.base_url = _normalize_base_url(raw, "")

    def _default_headers(self) -> dict:
        key = self._get_key()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer {0}".format(key)
        return headers

    def _list_models_headers(self) -> Optional[dict]:
        key = self._get_key()
        if not key:
            return None
        return {"Authorization": "Bearer {0}".format(key)}

    def _requires_key_for_listing(self) -> bool:
        return False

    def _fallback_models(self) -> List[str]:
        s = self.settings_dict or {}
        configured = s.get("custom_models")
        if isinstance(configured, list):
            return list(configured)
        return []

    def is_available(self) -> ProviderHealth:
        if not self.base_url:
            return ProviderHealth.MISCONFIGURED
        url = self.base_url + "/models"
        headers = self._list_models_headers()
        try:
            resp = self._open_url(url, method="GET", headers=headers, timeout=5)
        except ConnectionRefusedError:
            return ProviderHealth.UNREACHABLE
        except socket.timeout:
            return ProviderHealth.UNREACHABLE
        except urllib.error.HTTPError as e:
            code = e.code
            try:
                e.close()
            except Exception:
                pass
            if code == 401:
                return ProviderHealth.MISSING_CREDENTIAL
            if code == 404:
                # Endpoint not present is fine for custom servers; they're still reachable.
                return ProviderHealth.OK
            return ProviderHealth.MISCONFIGURED
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, (ConnectionRefusedError, socket.timeout)):
                return ProviderHealth.UNREACHABLE
            return ProviderHealth.UNREACHABLE
        except OSError:
            return ProviderHealth.UNREACHABLE
        try:
            code = resp.getcode()
        except Exception:
            code = 0
        try:
            resp.close()
        except Exception:
            pass
        if code == 200:
            return ProviderHealth.OK
        if code == 401:
            return ProviderHealth.MISSING_CREDENTIAL
        return ProviderHealth.MISCONFIGURED

    def list_models(self) -> List[str]:
        if not self.base_url:
            return self._fallback_models()
        url = self.base_url + "/models"
        headers = self._list_models_headers()
        try:
            resp = self._open_url(url, method="GET", headers=headers, timeout=5)
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:
                pass
            if e.code == 404:
                return self._fallback_models()
            _log.warning(
                "%s list_models: HTTP %d; using fallback list", self.name, e.code
            )
            return self._fallback_models()
        except Exception as e:
            _log.warning(
                "%s list_models: request failed (%s)", self.name, type(e).__name__
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
