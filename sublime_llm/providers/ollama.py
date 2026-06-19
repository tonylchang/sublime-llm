"""Ollama provider."""
import json
import os
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
from ..streaming import iter_ndjson_lines

try:
    import certifi
    _CA_FILE = certifi.where()
except ImportError:
    _CA_FILE = None

_log = get_logger()

_DEFAULT_BASE_URL = "http://localhost:11434"
_PROBE_TIMEOUT = 3
_READ_TIMEOUT = 60


def _build_ssl_context() -> ssl.SSLContext:
    if _CA_FILE:
        return ssl.create_default_context(cafile=_CA_FILE)
    return ssl.create_default_context()


def _normalize_base_url(raw: str) -> str:
    if not raw:
        return _DEFAULT_BASE_URL
    s = raw.strip().rstrip("/")
    if "://" not in s:
        s = "http://" + s
    return s


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, settings_dict: dict) -> None:
        super().__init__(settings_dict)
        raw = (settings_dict or {}).get("base_url")
        if not raw:
            raw = os.environ.get("OLLAMA_HOST", "")
        if not raw:
            raw = _DEFAULT_BASE_URL
        self.base_url = _normalize_base_url(raw)

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
        url = self.base_url + "/api/tags"
        try:
            resp = self._open_url(url, method="GET", timeout=_PROBE_TIMEOUT)
        except ConnectionRefusedError:
            return ProviderHealth.UNREACHABLE
        except socket.timeout:
            return ProviderHealth.UNREACHABLE
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:
                pass
            return ProviderHealth.MISCONFIGURED
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, ConnectionRefusedError):
                return ProviderHealth.UNREACHABLE
            if isinstance(reason, socket.timeout):
                return ProviderHealth.UNREACHABLE
            return ProviderHealth.MISCONFIGURED
        except OSError:
            return ProviderHealth.MISCONFIGURED
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
        return ProviderHealth.MISCONFIGURED

    def list_models(self) -> List[str]:
        url = self.base_url + "/api/tags"
        try:
            resp = self._open_url(url, method="GET", timeout=_PROBE_TIMEOUT)
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:
                pass
            _log.warning("ollama list_models: request failed (HTTPError)")
            return []
        except Exception as e:
            _log.warning("ollama list_models: request failed (%s)", type(e).__name__)
            return []
        try:
            raw = resp.read()
        except Exception as e:
            _log.warning("ollama list_models: read failed (%s)", type(e).__name__)
            return []
        finally:
            try:
                resp.close()
            except Exception:
                pass
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            _log.warning("ollama list_models: malformed JSON (%d bytes)", len(raw))
            return []
        try:
            return [m["name"] for m in data.get("models", []) if "name" in m]
        except Exception:
            return []

    def _build_options(self, options: dict) -> dict:
        opts = {}
        if "temperature" in options and options["temperature"] is not None:
            opts["temperature"] = options["temperature"]
        if "top_p" in options and options["top_p"] is not None:
            opts["top_p"] = options["top_p"]
        if "stop" in options and options["stop"] is not None:
            opts["stop"] = options["stop"]
        if "max_tokens" in options and options["max_tokens"] is not None:
            opts["num_predict"] = options["max_tokens"]
        extras = options.get("provider_kwargs") or {}
        for k, v in extras.items():
            opts[k] = v
        return opts

    def _messages_payload(self, messages: List[ChatMessage]) -> list:
        return [{"role": m.role, "content": m.content} for m in messages]

    def _post_chat(self, payload: dict, stream: bool):
        url = self.base_url + "/api/chat"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        timeout = _READ_TIMEOUT
        return self._open_url(url, method="POST", headers=headers, body=body, timeout=timeout)

    def _map_http_error(self, err: urllib.error.HTTPError, model: str) -> ProviderError:
        code = err.code
        if code == 404:
            return ProviderError(
                "MODEL_NOT_FOUND",
                "Model '{0}' not found on ollama.".format(model),
                False,
            )
        if 500 <= code < 600:
            return ProviderError(
                "SERVER_ERROR",
                "ollama server error. Try again in a moment.",
                True,
            )
        return ProviderError(
            "HTTP_ERROR",
            "ollama returned HTTP {0}.".format(code),
            False,
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
        payload = {
            "model": model,
            "messages": self._messages_payload(messages),
            "stream": False,
            "options": self._build_options(options or {}),
        }
        # Non-streaming cancellation is best-effort: the urlopen call itself blocks.
        try:
            resp = self._post_chat(payload, stream=False)
        except ConnectionRefusedError:
            raise ProviderError(
                "UNREACHABLE",
                "Ollama is not running. Start it with `ollama serve`.",
                False,
            )
        except socket.timeout:
            raise ProviderError(
                "TIMEOUT",
                "Request timed out. Provider may be overloaded.",
                True,
            )
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:
                pass
            raise self._map_http_error(e, model)
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, ConnectionRefusedError):
                raise ProviderError(
                    "UNREACHABLE",
                    "Ollama is not running. Start it with `ollama serve`.",
                    False,
                )
            if isinstance(reason, socket.timeout):
                raise ProviderError(
                    "TIMEOUT",
                    "Request timed out. Provider may be overloaded.",
                    True,
                )
            raise ProviderError("NETWORK_ERROR", "Network error contacting ollama.", True)
        if cancel_event is not None and cancel_event.is_set():
            try:
                resp.close()
            except Exception:
                pass
            return ""
        try:
            raw = resp.read()
        except socket.timeout:
            raise ProviderError(
                "TIMEOUT",
                "Request timed out. Provider may be overloaded.",
                True,
            )
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
        return data.get("message", {}).get("content", "")

    def stream(
        self,
        messages: List[ChatMessage],
        model: str,
        options: dict,
        cancel_event: threading.Event,
    ) -> Iterator[StreamEvent]:
        if cancel_event is not None and cancel_event.is_set():
            return
        payload = {
            "model": model,
            "messages": self._messages_payload(messages),
            "stream": True,
            "options": self._build_options(options or {}),
        }
        try:
            resp = self._post_chat(payload, stream=True)
        except ConnectionRefusedError:
            raise ProviderError(
                "UNREACHABLE",
                "Ollama is not running. Start it with `ollama serve`.",
                False,
            )
        except socket.timeout:
            raise ProviderError(
                "TIMEOUT",
                "Request timed out. Provider may be overloaded.",
                True,
            )
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:
                pass
            raise self._map_http_error(e, model)
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, ConnectionRefusedError):
                raise ProviderError(
                    "UNREACHABLE",
                    "Ollama is not running. Start it with `ollama serve`.",
                    False,
                )
            if isinstance(reason, socket.timeout):
                raise ProviderError(
                    "TIMEOUT",
                    "Request timed out. Provider may be overloaded.",
                    True,
                )
            raise ProviderError("NETWORK_ERROR", "Network error contacting ollama.", True)

        _USAGE_KEYS = (
            "total_duration",
            "load_duration",
            "prompt_eval_count",
            "prompt_eval_duration",
            "eval_count",
            "eval_duration",
        )
        try:
            for obj in iter_ndjson_lines(resp, cancel_event):
                if obj.get("done", False):
                    usage = {k: obj[k] for k in _USAGE_KEYS if k in obj}
                    yield Done(reason=obj.get("done_reason", "stop"), usage=usage)
                    return
                msg = obj.get("message") or {}
                text = msg.get("content", "") if isinstance(msg, dict) else ""
                if text:
                    yield TextDelta(text=text)
        finally:
            try:
                resp.close()
            except Exception:
                pass
