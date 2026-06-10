"""Anthropic provider."""
import json
import socket
import ssl
import threading
import urllib.error
import urllib.request
from typing import Iterator, List, Optional, Tuple

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

_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
_DEFAULT_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 4096
_READ_TIMEOUT = 60

_DEFAULT_MODELS = [
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]


def _build_ssl_context() -> ssl.SSLContext:
    if _CA_FILE:
        return ssl.create_default_context(cafile=_CA_FILE)
    return ssl.create_default_context()


def _normalize_base_url(raw: str) -> str:
    if not raw:
        return _DEFAULT_BASE_URL
    return raw.strip().rstrip("/")


class _StreamState:
    def __init__(self) -> None:
        self.stop_reason: Optional[str] = None
        self.usage: Optional[dict] = None


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, settings_dict: dict) -> None:
        super().__init__(settings_dict)
        raw = (settings_dict or {}).get("base_url")
        self.base_url = _normalize_base_url(raw or _DEFAULT_BASE_URL)
        self.anthropic_version = str(
            (settings_dict or {}).get("anthropic_version") or _DEFAULT_VERSION
        )

    def _get_key(self) -> Optional[str]:
        key, _source = resolve_key("anthropic")
        return key

    def _default_headers(self) -> dict:
        key = self._get_key()
        if not key:
            raise ProviderError(
                "MISSING_CREDENTIAL",
                "Anthropic API key is not configured. Set ANTHROPIC_API_KEY or add it to config.json.",
                False,
            )
        return {
            "x-api-key": key,
            "anthropic-version": self.anthropic_version,
            "content-type": "application/json",
        }

    def is_available(self) -> ProviderHealth:
        # Anthropic has no cheap health endpoint; treat key presence as OK.
        key = self._get_key()
        if not key:
            return ProviderHealth.MISSING_CREDENTIAL
        return ProviderHealth.OK

    def list_models(self) -> List[str]:
        override = (self.settings_dict or {}).get("anthropic_models")
        if isinstance(override, list) and override:
            return [str(m) for m in override]
        return list(_DEFAULT_MODELS)

    def _translate_messages(
        self, messages: List[ChatMessage]
    ) -> Tuple[str, List[dict]]:
        sys_parts: List[str] = []
        msgs: List[dict] = []
        for m in messages:
            if m.role == "system":
                if m.content:
                    sys_parts.append(m.content)
            elif m.role in ("user", "assistant"):
                msgs.append({"role": m.role, "content": m.content})
        return ("\n\n".join(sys_parts), msgs)

    def _build_body(
        self, messages: List[ChatMessage], model: str, options: dict, stream: bool
    ) -> dict:
        system_str, msgs = self._translate_messages(messages)
        opts = options or {}
        max_tokens = opts.get("max_tokens")
        if max_tokens is None:
            max_tokens = _DEFAULT_MAX_TOKENS
        body: dict = {
            "model": model,
            "messages": msgs,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if system_str:
            body["system"] = system_str
        if opts.get("temperature") is not None:
            body["temperature"] = opts["temperature"]
        if opts.get("top_p") is not None:
            body["top_p"] = opts["top_p"]
        stop = opts.get("stop_sequences")
        if stop is None:
            stop = opts.get("stop")
        if stop is not None:
            body["stop_sequences"] = stop
        return body

    def _open_url(
        self,
        url: str,
        method: str,
        headers: dict,
        body: Optional[bytes],
        timeout: int,
    ):
        req = urllib.request.Request(url, data=body, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        ctx = _build_ssl_context()
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)

    def _read_error_body(self, err: urllib.error.HTTPError) -> str:
        """Pull the API's error message out of the HTTPError body, if present."""
        try:
            raw = err.read()
        except Exception:
            return ""
        if not raw:
            return ""
        try:
            obj = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            text = raw.decode("utf-8", errors="replace").strip()
            return text[:300]
        if isinstance(obj, dict):
            inner = obj.get("error")
            if isinstance(inner, dict):
                msg = inner.get("message")
                if msg:
                    return str(msg)
            msg = obj.get("message")
            if msg:
                return str(msg)
        return ""

    def _map_http_error(
        self, err: urllib.error.HTTPError, model: str
    ) -> ProviderError:
        code = err.code
        body_msg = self._read_error_body(err)
        suffix = " — {0}".format(body_msg) if body_msg else ""
        if code == 401:
            return ProviderError(
                "BAD_CREDENTIAL",
                "Anthropic API key is invalid." + suffix,
                False,
            )
        if code == 404:
            return ProviderError(
                "MODEL_NOT_FOUND",
                "Model '{0}' not found on Anthropic.{1}".format(model, suffix),
                False,
            )
        if code == 429:
            return ProviderError(
                "RATE_LIMITED",
                "Anthropic rate limit reached." + suffix,
                True,
            )
        if code == 529 or (500 <= code < 600):
            return ProviderError(
                "SERVER_ERROR",
                "Anthropic server error. Try again in a moment." + suffix,
                True,
            )
        if code == 400:
            return ProviderError(
                "BAD_REQUEST",
                "Anthropic rejected the request (HTTP 400){0}".format(
                    suffix or " — no detail returned"
                ),
                False,
            )
        return ProviderError(
            "HTTP_ERROR",
            "Anthropic returned HTTP {0}.{1}".format(code, suffix),
            False,
        )

    def _map_url_error(self, e: urllib.error.URLError) -> ProviderError:
        reason = getattr(e, "reason", None)
        if isinstance(reason, ConnectionRefusedError):
            return ProviderError(
                "UNREACHABLE",
                "Anthropic is unreachable. Check your network.",
                True,
            )
        if isinstance(reason, socket.timeout):
            return ProviderError("TIMEOUT", "Request timed out.", True)
        if isinstance(reason, socket.gaierror):
            return ProviderError(
                "UNREACHABLE",
                "Anthropic is unreachable. Check your network.",
                True,
            )
        return ProviderError(
            "UNREACHABLE",
            "Anthropic is unreachable. Check your network.",
            True,
        )

    def _post_messages(self, body: dict, timeout: int):
        url = self.base_url + "/messages"
        headers = self._default_headers()
        raw = json.dumps(body).encode("utf-8")
        return self._open_url(
            url, method="POST", headers=headers, body=raw, timeout=timeout
        )

    # Models that reject `temperature` (or other params) report it via 400.
    # We detect those once, drop the offending field, and retry transparently.
    _RETRYABLE_PARAM_PATTERNS = (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("top_k", "top_k"),
    )

    def _param_to_drop_from_400(self, body_msg: str):
        if not body_msg:
            return None
        lowered = body_msg.lower()
        if "deprecated" not in lowered and "not supported" not in lowered and "unsupported" not in lowered:
            return None
        for needle, field in self._RETRYABLE_PARAM_PATTERNS:
            if needle in lowered:
                return field
        return None

    def _post_with_retry(self, body: dict, timeout: int):
        """POST /messages, retrying once with a deprecated param stripped on 400."""
        try:
            return self._post_messages(body, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            body_msg = self._read_error_body(e)
            try:
                e.close()
            except Exception:
                pass
            drop = self._param_to_drop_from_400(body_msg)
            if drop is None or drop not in body:
                # Not a known recoverable case; re-raise as a fresh HTTPError-like
                # ProviderError so the caller surfaces the original detail.
                raise ProviderError(
                    "BAD_REQUEST",
                    "Anthropic rejected the request (HTTP 400){0}".format(
                        " — " + body_msg if body_msg else " — no detail returned"
                    ),
                    False,
                )
            _log.warning(
                "anthropic: dropping '%s' and retrying (model rejected it)", drop
            )
            retry_body = dict(body)
            retry_body.pop(drop, None)
            return self._post_messages(retry_body, timeout=timeout)

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
            resp = self._post_with_retry(body, timeout=_READ_TIMEOUT)
        except ConnectionRefusedError:
            raise ProviderError(
                "UNREACHABLE",
                "Anthropic is unreachable. Check your network.",
                True,
            )
        except socket.timeout:
            raise ProviderError("TIMEOUT", "Request timed out.", True)
        except socket.gaierror:
            raise ProviderError(
                "UNREACHABLE",
                "Anthropic is unreachable. Check your network.",
                True,
            )
        except urllib.error.HTTPError as e:
            mapped = self._map_http_error(e, model)
            try:
                e.close()
            except Exception:
                pass
            raise mapped
        except urllib.error.URLError as e:
            raise self._map_url_error(e)

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
        content = data.get("content") or []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
        if content and isinstance(content[0], dict):
            return content[0].get("text", "")
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
            resp = self._post_with_retry(body, timeout=_READ_TIMEOUT)
        except ConnectionRefusedError:
            raise ProviderError(
                "UNREACHABLE",
                "Anthropic is unreachable. Check your network.",
                True,
            )
        except socket.timeout:
            raise ProviderError("TIMEOUT", "Request timed out.", True)
        except socket.gaierror:
            raise ProviderError(
                "UNREACHABLE",
                "Anthropic is unreachable. Check your network.",
                True,
            )
        except urllib.error.HTTPError as e:
            mapped = self._map_http_error(e, model)
            try:
                e.close()
            except Exception:
                pass
            raise mapped
        except urllib.error.URLError as e:
            raise self._map_url_error(e)

        state = _StreamState()
        try:
            for event_type, data_str in iter_sse_lines(resp, cancel_event):
                if event_type == "ping":
                    continue
                if event_type in ("message_start", "content_block_start", "content_block_stop"):
                    continue
                if event_type == "content_block_delta":
                    try:
                        obj = json.loads(data_str)
                    except Exception:
                        _log.warning("anthropic stream: malformed content_block_delta")
                        continue
                    delta = obj.get("delta") or {}
                    dtype = delta.get("type")
                    if dtype == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield TextDelta(text=text)
                    continue
                if event_type == "message_delta":
                    try:
                        obj = json.loads(data_str)
                    except Exception:
                        _log.warning("anthropic stream: malformed message_delta")
                        continue
                    delta = obj.get("delta") or {}
                    if isinstance(delta, dict) and delta.get("stop_reason"):
                        state.stop_reason = delta.get("stop_reason")
                    usage = obj.get("usage")
                    if isinstance(usage, dict):
                        state.usage = usage
                    continue
                if event_type == "message_stop":
                    yield Done(
                        reason=state.stop_reason or "end_turn",
                        usage=state.usage,
                    )
                    return
                if event_type == "error":
                    try:
                        obj = json.loads(data_str)
                    except Exception:
                        obj = {}
                    err = obj.get("error") if isinstance(obj, dict) else None
                    msg = "Anthropic streaming error"
                    if isinstance(err, dict):
                        msg = err.get("message", msg)
                    raise ProviderError("SERVER_ERROR", msg, True)
        finally:
            try:
                resp.close()
            except Exception:
                pass
