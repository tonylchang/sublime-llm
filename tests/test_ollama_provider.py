"""Tests for sublime_llm.providers.ollama."""
import io
import json
import socket
import threading
import urllib.error
from unittest import mock

from unittesting import DeferrableTestCase

from LLM.sublime_llm.providers import (
    ChatMessage,
    Done,
    ProviderError,
    ProviderHealth,
    TextDelta,
)
from LLM.sublime_llm.providers.ollama import OllamaProvider


class MockResponse:
    def __init__(self, body: bytes = b"", status: int = 200, headers=None) -> None:
        self._body = body
        self._buf = io.BytesIO(body)
        self._status = status
        self.headers = headers or {}
        self.closed = False

    def read(self) -> bytes:
        return self._buf.read()

    def readline(self) -> bytes:
        if self.closed:
            return b""
        return self._buf.readline()

    def getcode(self) -> int:
        return self._status

    def close(self) -> None:
        self.closed = True


def _make_provider(base_url: str = "http://localhost:11434") -> OllamaProvider:
    return OllamaProvider({"base_url": base_url})


class BaseUrlNormalizationTests(DeferrableTestCase):
    def test_default_used(self) -> None:
        p = OllamaProvider({})
        self.assertEqual(p.base_url, "http://localhost:11434")

    def test_trailing_slash_stripped(self) -> None:
        p = OllamaProvider({"base_url": "http://localhost:11434/"})
        self.assertEqual(p.base_url, "http://localhost:11434")

    def test_env_var_without_scheme(self) -> None:
        with mock.patch.dict("os.environ", {"OLLAMA_HOST": "0.0.0.0:11434"}, clear=False):
            p = OllamaProvider({})
            self.assertEqual(p.base_url, "http://0.0.0.0:11434")


class ListModelsTests(DeferrableTestCase):
    def test_list_models_success(self) -> None:
        body = json.dumps({"models": [{"name": "llama3"}, {"name": "mistral"}]}).encode("utf-8")
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            return_value=MockResponse(body=body, status=200),
        ):
            p = _make_provider()
            self.assertEqual(p.list_models(), ["llama3", "mistral"])

    def test_list_models_error_returns_empty(self) -> None:
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            side_effect=ConnectionRefusedError(),
        ):
            p = _make_provider()
            self.assertEqual(p.list_models(), [])

    def test_list_models_closes_http_error(self) -> None:
        err = urllib.error.HTTPError(
            url="http://localhost:11434/api/tags",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(b"boom"),
        )
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            side_effect=err,
        ):
            p = _make_provider()
            self.assertEqual(p.list_models(), [])

        self.assertTrue(err.closed)


class IsAvailableTests(DeferrableTestCase):
    def test_is_available_ok(self) -> None:
        body = json.dumps({"models": []}).encode("utf-8")
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            return_value=MockResponse(body=body, status=200),
        ):
            p = _make_provider()
            self.assertEqual(p.is_available(), ProviderHealth.OK)

    def test_is_available_connection_refused(self) -> None:
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            side_effect=ConnectionRefusedError(),
        ):
            p = _make_provider()
            self.assertEqual(p.is_available(), ProviderHealth.UNREACHABLE)

    def test_is_available_timeout(self) -> None:
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            side_effect=socket.timeout(),
        ):
            p = _make_provider()
            self.assertEqual(p.is_available(), ProviderHealth.UNREACHABLE)

    def test_is_available_closes_http_error(self) -> None:
        err = urllib.error.HTTPError(
            url="http://localhost:11434/api/tags",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(b"boom"),
        )
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            side_effect=err,
        ):
            p = _make_provider()
            self.assertEqual(p.is_available(), ProviderHealth.MISCONFIGURED)

        self.assertTrue(err.closed)


class CompleteTests(DeferrableTestCase):
    def test_complete_success(self) -> None:
        body = json.dumps(
            {"message": {"role": "assistant", "content": "hello world"}}
        ).encode("utf-8")
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            return_value=MockResponse(body=body, status=200),
        ):
            p = _make_provider()
            out = p.complete(
                [ChatMessage("user", "hi")],
                "llama3",
                {"temperature": 0.5},
                threading.Event(),
            )
            self.assertEqual(out, "hello world")

    def test_complete_connection_refused(self) -> None:
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            side_effect=ConnectionRefusedError(),
        ):
            p = _make_provider()
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "llama3",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "UNREACHABLE")
            self.assertFalse(cm.exception.retryable)

    def test_complete_http_404(self) -> None:
        err = urllib.error.HTTPError(
            url="http://localhost:11434/api/chat",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b"model not found"),
        )
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            side_effect=err,
        ):
            p = _make_provider()
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "missing-model",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "MODEL_NOT_FOUND")
            self.assertIn("missing-model", cm.exception.message)

    def test_complete_http_500(self) -> None:
        err = urllib.error.HTTPError(
            url="http://localhost:11434/api/chat",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(b"boom"),
        )
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            side_effect=err,
        ):
            p = _make_provider()
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "llama3",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "SERVER_ERROR")
            self.assertTrue(cm.exception.retryable)

class StreamTests(DeferrableTestCase):
    def _stream_body(self) -> bytes:
        lines = [
            json.dumps({"message": {"role": "assistant", "content": "Hel"}, "done": False}),
            json.dumps({"message": {"role": "assistant", "content": "lo "}, "done": False}),
            json.dumps({"message": {"role": "assistant", "content": "world"}, "done": False}),
            json.dumps({
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": "stop",
                "total_duration": 100,
                "load_duration": 10,
                "prompt_eval_count": 4,
                "prompt_eval_duration": 20,
                "eval_count": 3,
                "eval_duration": 70,
            }),
        ]
        return ("\n".join(lines) + "\n").encode("utf-8")

    def test_stream_yields_deltas_and_done(self) -> None:
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            return_value=MockResponse(body=self._stream_body(), status=200),
        ):
            p = _make_provider()
            events = list(
                p.stream(
                    [ChatMessage("user", "hi")],
                    "llama3",
                    {},
                    threading.Event(),
                )
            )
        deltas = [e for e in events if isinstance(e, TextDelta)]
        dones = [e for e in events if isinstance(e, Done)]
        self.assertEqual([d.text for d in deltas], ["Hel", "lo ", "world"])
        self.assertEqual(len(dones), 1)
        self.assertEqual(dones[0].reason, "stop")
        self.assertEqual(dones[0].usage["total_duration"], 100)
        self.assertEqual(dones[0].usage["eval_count"], 3)
        self.assertIn("load_duration", dones[0].usage)

    def test_stream_connection_refused(self) -> None:
        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            side_effect=ConnectionRefusedError(),
        ):
            p = _make_provider()
            gen = p.stream(
                [ChatMessage("user", "hi")],
                "llama3",
                {},
                threading.Event(),
            )
            with self.assertRaises(ProviderError) as cm:
                list(gen)
            self.assertEqual(cm.exception.code, "UNREACHABLE")

    def test_stream_cancellation_mid_stream(self) -> None:
        body = self._stream_body()
        resp = MockResponse(body=body, status=200)
        cancel = threading.Event()

        with mock.patch(
            "LLM.sublime_llm.providers.ollama.urllib.request.urlopen",
            return_value=resp,
        ):
            p = _make_provider()
            collected = []
            for event in p.stream(
                [ChatMessage("user", "hi")],
                "llama3",
                {},
                cancel,
            ):
                collected.append(event)
                if len(collected) == 1:
                    cancel.set()

        # Should only have collected the first delta before cancellation.
        self.assertEqual(len(collected), 1)
        self.assertIsInstance(collected[0], TextDelta)
        self.assertEqual(collected[0].text, "Hel")
        self.assertTrue(resp.closed)
