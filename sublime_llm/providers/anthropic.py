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
_PROBE_TIMEOUT = 5

# Offline fallback only. list_models() discovers the live set from /v1/models;
# this list is used when that request can't be made (no key, no network) so the
# model picker still has something to show. Keep it to current, broadly useful
# models — live discovery surfaces everything the account can actually access.
_DEFAULT_MODELS = [
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]

# The only sampling params the plugin sends today are temperature/top_p, but we
# treat the whole group together because newer models remove them as a set.
_SAMPLING_PARAMS = ("temperature", "top_p", "top_k")

# Phrases (besides the param name itself) that mark a 400 as a rejected
# *parameter* rather than a content/format problem. Kept broad on purpose:
# dropping optional sampling params is harmless, so this errs toward retrying,
# and it keeps working if Anthropic changes the exact error wording — no code
# change needed.
_PARAM_REJECTION_HINTS = (
    "not supported",
    "unsupported",
    "not permitted",
    "not allowed",
    "unexpected",
    "unrecognized",
    "extra inputs",
    "extra fields",
    "deprecated",
    "remove",
)

# Runtime cache of models observed to reject sampling params this session.
# Populated on the first rejection so later requests to the same model omit
# those params and skip a wasted round-trip. Learned, not hardcoded — resets on
# plugin reload. Set mutation from the streaming thread is GIL-atomic.
_MODELS_REJECTING_SAMPLING = set()


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
        # An explicit override pins the list and skips the network call.
        # Otherwise discover live from the Models API and fall back to the
        # built-in list when that endpoint can't be reached.
        override = (self.settings_dict or {}).get("anthropic_models")
        if isinstance(override, list) and override:
            return [str(m) for m in override]
        fetched = self._fetch_models()
        if fetched:
            return fetched
        return list(_DEFAULT_MODELS)

    def _fetch_models(self) -> List[str]:
        """Discover available models via GET /v1/models; [] if unavailable."""
        key = self._get_key()
        if not key:
            return []
        url = self.base_url + "/models?limit=1000"
        headers = {"x-api-key": key, "anthropic-version": self.anthropic_version}
        try:
            resp = self._open_url(
                url, method="GET", headers=headers, body=None, timeout=_PROBE_TIMEOUT
            )
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:
                pass
            _log.warning("anthropic list_models: request failed (HTTP %s)", e.code)
            return []
        except Exception as e:
            _log.warning(
                "anthropic list_models: request failed (%s)", type(e).__name__
            )
            return []
        try:
            raw = resp.read()
        except Exception as e:
            _log.warning("anthropic list_models: read failed (%s)", type(e).__name__)
            return []
        finally:
            try:
                resp.close()
            except Exception:
                pass
        try:
            data = json.loads(raw.decode("utf-8"))
            models = [
                m["id"]
                for m in data.get("data", [])
                if isinstance(m, dict) and "id" in m
            ]
        except Exception:
            _log.warning("anthropic list_models: malformed JSON (%d bytes)", len(raw))
            return []
        models.sort()
        return models

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
        # Omit sampling params for models known (this session) to reject them,
        # so we don't force a 400-then-retry on every request.
        if model not in _MODELS_REJECTING_SAMPLING:
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

    @staticmethod
    def _sampling_rejected(body_msg: str, body: dict) -> bool:
        """Whether a 400 looks like the model rejecting a sampling param we sent.

        Newer Claude models (Opus 4.7+, Sonnet 5, Fable 5) reject
        temperature/top_p/top_k with a 400. We recognize that from the error
        naming the field, or from generic "unsupported parameter" phrasing, and
        keep the match broad because dropping an optional sampling param is
        always safe — the model just falls back to its own default.
        """
        if not any(name in body for name in _SAMPLING_PARAMS):
            return False
        if not body_msg:
            return False
        lowered = body_msg.lower()
        if any(name in lowered for name in _SAMPLING_PARAMS):
            return True
        return any(hint in lowered for hint in _PARAM_REJECTION_HINTS)

    def _post_with_retry(self, body: dict, timeout: int):
        """POST /messages, retrying once without sampling params on a 400 that
        rejects them (and remembering the model so later requests skip them)."""
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
            if self._sampling_rejected(body_msg, body):
                retry_body = {
                    k: v for k, v in body.items() if k not in _SAMPLING_PARAMS
                }
                if retry_body != body:
                    model = body.get("model")
                    if model:
                        _MODELS_REJECTING_SAMPLING.add(model)
                    _log.warning(
                        "anthropic: model rejected a sampling parameter; "
                        "retrying without temperature/top_p/top_k"
                    )
                    return self._post_messages(retry_body, timeout=timeout)
            # Not a recoverable sampling rejection; surface the original detail.
            raise ProviderError(
                "BAD_REQUEST",
                "Anthropic rejected the request (HTTP 400){0}".format(
                    " — " + body_msg if body_msg else " — no detail returned"
                ),
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
