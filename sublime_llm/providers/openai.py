"""OpenAI provider."""
import json
import socket
import ssl
import threading
import urllib.error
import urllib.request
from typing import Iterator, List, Optional

from ..logging_setup import get_logger
from .base import (
    ChatMessage,
    Done,
    Provider,
    ProviderError,
    ProviderHealth,
    StreamEvent,
    TextDelta,
)
from ..secrets import resolve_key
from ..streaming import iter_sse_lines

try:
    import certifi
    _CA_FILE = certifi.where()
except ImportError:
    _CA_FILE = None

_log = get_logger()

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_PROBE_TIMEOUT = 5
_READ_TIMEOUT = 60
_DEFAULT_MAX_TOKENS = 4096


def _build_ssl_context() -> ssl.SSLContext:
    if _CA_FILE:
        return ssl.create_default_context(cafile=_CA_FILE)
    return ssl.create_default_context()


def _normalize_base_url(raw: str, default: str) -> str:
    if not raw:
        return default
    s = raw.strip().rstrip("/")
    if "://" not in s:
        s = "https://" + s
    return s


class OpenAIProvider(Provider):
    name = "openai"
    _provider_label = "OpenAI"
    _default_base_url = _DEFAULT_BASE_URL
    _secret_provider_name = "openai"

    def __init__(self, settings_dict: dict) -> None:
        super().__init__(settings_dict)
        raw = (settings_dict or {}).get("base_url")
        self.base_url = _normalize_base_url(raw, self._default_base_url)

    def _get_key(self) -> Optional[str]:
        key, _src = resolve_key(self._secret_provider_name)
        return key

    def _default_headers(self) -> dict:
        key = self._get_key()
        if not key:
            raise ProviderError(
                "MISSING_CREDENTIAL",
                "{0} API key is not configured. Set {1}_API_KEY or add it to config.json.".format(
                    self._provider_label,
                    self._secret_provider_name.upper(),
                ),
                False,
            )
        return {
            "Authorization": "Bearer {0}".format(key),
            "Content-Type": "application/json",
        }

    def _open_url(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict] = None,
        body: Optional[bytes] = None,
        timeout: int = 30,
    ):
        req = urllib.request.Request(url, data=body, method=method)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        ctx = _build_ssl_context()
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)

    def is_available(self) -> ProviderHealth:
        if not self._get_key():
            return ProviderHealth.MISSING_CREDENTIAL
        try:
            headers = self._default_headers()
        except ProviderError:
            return ProviderHealth.MISSING_CREDENTIAL
        url = self.base_url + "/models"
        try:
            resp = self._open_url(url, method="GET", headers=headers, timeout=_PROBE_TIMEOUT)
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
            return ProviderHealth.MISCONFIGURED
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, ConnectionRefusedError):
                return ProviderHealth.UNREACHABLE
            if isinstance(reason, socket.timeout):
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

    def _list_models_headers(self) -> Optional[dict]:
        key = self._get_key()
        if not key:
            return None
        return {"Authorization": "Bearer {0}".format(key)}

    def list_models(self) -> List[str]:
        headers = self._list_models_headers()
        if headers is None and self._requires_key_for_listing():
            _log.warning("%s list_models: API key not configured", self.name)
            return []
        url = self.base_url + "/models"
        try:
            resp = self._open_url(url, method="GET", headers=headers, timeout=_PROBE_TIMEOUT)
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:
                pass
            _log.warning("%s list_models: request failed (HTTPError)", self.name)
            return []
        except Exception as e:
            _log.warning("%s list_models: request failed (%s)", self.name, type(e).__name__)
            return []
        try:
            raw = resp.read()
        except Exception as e:
            _log.warning("%s list_models: read failed (%s)", self.name, type(e).__name__)
            return []
        finally:
            try:
                resp.close()
            except Exception:
                pass
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            _log.warning("%s list_models: malformed JSON (%d bytes)", self.name, len(raw))
            return []
        try:
            models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
        except Exception:
            return []
        models.sort()
        return models

    def _requires_key_for_listing(self) -> bool:
        return True

    def _messages_payload(self, messages: List[ChatMessage]) -> list:
        return [{"role": m.role, "content": m.content} for m in messages]

    def _build_body(self, messages: List[ChatMessage], model: str, options: dict, stream: bool) -> dict:
        opts = options or {}
        body = {
            "model": model,
            "messages": self._messages_payload(messages),
            "stream": stream,
        }
        if "temperature" in opts and opts["temperature"] is not None:
            body["temperature"] = opts["temperature"]
        if "top_p" in opts and opts["top_p"] is not None:
            body["top_p"] = opts["top_p"]
        if "stop" in opts and opts["stop"] is not None:
            body["stop"] = opts["stop"]
        max_tokens = opts.get("max_tokens", _DEFAULT_MAX_TOKENS)
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        return body

    def _chat_url(self) -> str:
        return self.base_url + "/chat/completions"

    def _post_chat(self, body: dict):
        headers = self._default_headers()
        data = json.dumps(body).encode("utf-8")
        return self._open_url(
            self._chat_url(),
            method="POST",
            headers=headers,
            body=data,
            timeout=_READ_TIMEOUT,
        )

    def _map_http_error(self, err: urllib.error.HTTPError, model: str) -> ProviderError:
        code = err.code
        if code == 401:
            return ProviderError(
                "BAD_CREDENTIAL",
                "{0} API key is invalid or expired.".format(self._provider_label),
                False,
            )
        if code == 429:
            return ProviderError(
                "RATE_LIMITED",
                "{0} rate limit reached. Try again shortly.".format(self._provider_label),
                True,
            )
        if code == 404:
            return ProviderError(
                "MODEL_NOT_FOUND",
                "Model '{0}' not found on {1}.".format(model, self._provider_label),
                False,
            )
        if 500 <= code < 600:
            return ProviderError(
                "SERVER_ERROR",
                "{0} server error. Try again in a moment.".format(self._provider_label),
                True,
            )
        return ProviderError(
            "HTTP_ERROR",
            "{0} returned HTTP {1}.".format(self._provider_label, code),
            False,
        )

    def _wrap_network_error(self, e: Exception) -> ProviderError:
        if isinstance(e, ConnectionRefusedError):
            return ProviderError(
                "UNREACHABLE",
                "{0} is unreachable. Check your network.".format(self._provider_label),
                True,
            )
        if isinstance(e, socket.timeout):
            return ProviderError("TIMEOUT", "Request timed out.", True)
        if isinstance(e, urllib.error.URLError):
            reason = getattr(e, "reason", None)
            if isinstance(reason, ConnectionRefusedError):
                return ProviderError(
                    "UNREACHABLE",
                    "{0} is unreachable. Check your network.".format(self._provider_label),
                    True,
                )
            if isinstance(reason, socket.timeout):
                return ProviderError("TIMEOUT", "Request timed out.", True)
            return ProviderError(
                "UNREACHABLE",
                "{0} is unreachable. Check your network.".format(self._provider_label),
                True,
            )
        return ProviderError(
            "NETWORK_ERROR",
            "Network error contacting {0}.".format(self._provider_label),
            True,
        )

    def complete(
        self,
        messages: List[ChatMessage],
        model: str,
        options: dict,
        cancel_event: threading.Event,
    ) -> str:
        if cancel_event is not None and cancel_event.is_set():
            return ""
        body = self._build_body(messages, model, options or {}, stream=False)
        try:
            resp = self._post_chat(body)
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:
                pass
            raise self._map_http_error(e, model)
        except (ConnectionRefusedError, socket.timeout, urllib.error.URLError) as e:
            raise self._wrap_network_error(e)
        if cancel_event is not None and cancel_event.is_set():
            try:
                resp.close()
            except Exception:
                pass
            return ""
        try:
            raw = resp.read()
        except socket.timeout:
            raise ProviderError("TIMEOUT", "Request timed out.", True)
        finally:
            try:
                resp.close()
            except Exception:
                pass
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ProviderError(
                "STREAM_CORRUPTED",
                "Stream corrupted. Partial response may be incomplete.",
                False,
            )
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ""

    def stream(
        self,
        messages: List[ChatMessage],
        model: str,
        options: dict,
        cancel_event: threading.Event,
    ) -> Iterator[StreamEvent]:
        if cancel_event is not None and cancel_event.is_set():
            return
        body = self._build_body(messages, model, options or {}, stream=True)
        try:
            resp = self._post_chat(body)
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:
                pass
            raise self._map_http_error(e, model)
        except (ConnectionRefusedError, socket.timeout, urllib.error.URLError) as e:
            raise self._wrap_network_error(e)

        try:
            for _event_type, data_str in iter_sse_lines(resp, cancel_event):
                if not data_str:
                    continue
                if data_str == "[DONE]":
                    return
                try:
                    chunk = json.loads(data_str)
                except Exception:
                    raise ProviderError(
                        "STREAM_CORRUPTED",
                        "Stream corrupted. Partial response may be incomplete.",
                        False,
                    )
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice0 = choices[0] if isinstance(choices[0], dict) else {}
                delta = choice0.get("delta") or {}
                text = delta.get("content") if isinstance(delta, dict) else None
                if text:
                    yield TextDelta(text=text)
                finish = choice0.get("finish_reason")
                if finish:
                    yield Done(reason=finish, usage=chunk.get("usage"))
                    return
        finally:
            try:
                resp.close()
            except Exception:
                pass
