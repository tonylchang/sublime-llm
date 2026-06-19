"""Tests for sublime_llm.providers.openai."""
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
from LLM.sublime_llm.providers.openai import OpenAIProvider


_TEST_KEY_ENV = {"OPENAI_API_KEY": "sk-test12345abcdef"}


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


def _make_provider(settings: dict = None) -> OpenAIProvider:
    return OpenAIProvider(settings or {})


def _patch_no_secret_file():
    return mock.patch(
        "LLM.sublime_llm.secrets._read_secrets_file",
        return_value={},
    )


def _patch_env(env: dict):
    return mock.patch.dict("os.environ", env, clear=False)


class BaseUrlTests(DeferrableTestCase):
    def test_default_url(self) -> None:
        p = _make_provider({})
        self.assertEqual(p.base_url, "https://api.openai.com/v1")

    def test_override_url(self) -> None:
        p = _make_provider({"base_url": "https://example.com/v1/"})
        self.assertEqual(p.base_url, "https://example.com/v1")


class IsAvailableTests(DeferrableTestCase):
    def test_is_available_no_key(self) -> None:
        with _patch_env({"OPENAI_API_KEY": ""}), _patch_no_secret_file(), \
             mock.patch("LLM.sublime_llm.providers.openai.urllib.request.urlopen") as urlopen:
            p = _make_provider()
            self.assertEqual(p.is_available(), ProviderHealth.MISSING_CREDENTIAL)
            urlopen.assert_not_called()

    def test_is_available_ok(self) -> None:
        body = json.dumps({"data": []}).encode("utf-8")
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            return_value=MockResponse(body=body, status=200),
        ):
            p = _make_provider()
            self.assertEqual(p.is_available(), ProviderHealth.OK)

    def test_is_available_401(self) -> None:
        err = urllib.error.HTTPError(
            url="https://api.openai.com/v1/models",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"bad key"),
        )
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=err,
        ):
            p = _make_provider()
            self.assertEqual(p.is_available(), ProviderHealth.MISSING_CREDENTIAL)

    def test_is_available_connection_refused(self) -> None:
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=ConnectionRefusedError(),
        ):
            p = _make_provider()
            self.assertEqual(p.is_available(), ProviderHealth.UNREACHABLE)


class ListModelsTests(DeferrableTestCase):
    def test_list_models_sorted(self) -> None:
        body = json.dumps(
            {"data": [{"id": "gpt-4o"}, {"id": "gpt-3.5-turbo"}, {"id": "gpt-4"}]}
        ).encode("utf-8")
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            return_value=MockResponse(body=body, status=200),
        ):
            p = _make_provider()
            self.assertEqual(p.list_models(), ["gpt-3.5-turbo", "gpt-4", "gpt-4o"])

    def test_list_models_no_key(self) -> None:
        with _patch_env({"OPENAI_API_KEY": ""}), _patch_no_secret_file(), \
             mock.patch("LLM.sublime_llm.providers.openai.urllib.request.urlopen") as urlopen:
            p = _make_provider()
            self.assertEqual(p.list_models(), [])
            urlopen.assert_not_called()

    def test_list_models_error_returns_empty(self) -> None:
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=ConnectionRefusedError(),
        ):
            p = _make_provider()
            self.assertEqual(p.list_models(), [])

    def test_list_models_closes_http_error(self) -> None:
        err = urllib.error.HTTPError(
            url="https://api.openai.com/v1/models",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(b"boom"),
        )
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=err,
        ):
            p = _make_provider()
            self.assertEqual(p.list_models(), [])

        self.assertTrue(err.closed)


class CompleteTests(DeferrableTestCase):
    def test_complete_success(self) -> None:
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "hi there"}}]}
        ).encode("utf-8")
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            return_value=MockResponse(body=body, status=200),
        ):
            p = _make_provider()
            out = p.complete(
                [ChatMessage("user", "hello")],
                "gpt-4o",
                {"temperature": 0.2},
                threading.Event(),
            )
            self.assertEqual(out, "hi there")

    def test_complete_401(self) -> None:
        err = urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"bad key"),
        )
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=err,
        ):
            p = _make_provider()
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "gpt-4o",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "BAD_CREDENTIAL")
            self.assertFalse(cm.exception.retryable)

    def test_complete_429(self) -> None:
        err = urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b"rate limited"),
        )
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=err,
        ):
            p = _make_provider()
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "gpt-4o",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "RATE_LIMITED")
            self.assertTrue(cm.exception.retryable)

    def test_complete_404(self) -> None:
        err = urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b"no such model"),
        )
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=err,
        ):
            p = _make_provider()
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "gpt-9000",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "MODEL_NOT_FOUND")
            self.assertIn("gpt-9000", cm.exception.message)

    def test_complete_500(self) -> None:
        err = urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(b"boom"),
        )
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=err,
        ):
            p = _make_provider()
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "gpt-4o",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "SERVER_ERROR")
            self.assertTrue(cm.exception.retryable)

    def test_complete_missing_credential(self) -> None:
        with _patch_env({"OPENAI_API_KEY": ""}), _patch_no_secret_file():
            p = _make_provider()
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "gpt-4o",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "MISSING_CREDENTIAL")


class StreamTests(DeferrableTestCase):
    def _stream_body(self) -> bytes:
        chunks = [
            "data: " + json.dumps(
                {"choices": [{"delta": {"content": "Hel"}, "finish_reason": None}]}
            ),
            "",
            "data: " + json.dumps(
                {"choices": [{"delta": {"content": "lo"}, "finish_reason": None}]}
            ),
            "",
            "data: " + json.dumps(
                {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"total_tokens": 7}}
            ),
            "",
            "data: [DONE]",
            "",
        ]
        return ("\r\n".join(chunks) + "\r\n").encode("utf-8")

    def test_stream_yields_deltas_and_done(self) -> None:
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            return_value=MockResponse(body=self._stream_body(), status=200),
        ):
            p = _make_provider()
            events = list(
                p.stream(
                    [ChatMessage("user", "hi")],
                    "gpt-4o",
                    {},
                    threading.Event(),
                )
            )
        deltas = [e for e in events if isinstance(e, TextDelta)]
        dones = [e for e in events if isinstance(e, Done)]
        self.assertEqual([d.text for d in deltas], ["Hel", "lo"])
        self.assertEqual(len(dones), 1)
        self.assertEqual(dones[0].reason, "stop")
        self.assertEqual(dones[0].usage, {"total_tokens": 7})

    def test_stream_cancellation_mid_stream(self) -> None:
        resp = MockResponse(body=self._stream_body(), status=200)
        cancel = threading.Event()

        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            return_value=resp,
        ):
            p = _make_provider()
            collected = []
            for event in p.stream(
                [ChatMessage("user", "hi")],
                "gpt-4o",
                {},
                cancel,
            ):
                collected.append(event)
                if len(collected) == 1:
                    cancel.set()

        self.assertEqual(len(collected), 1)
        self.assertIsInstance(collected[0], TextDelta)
        self.assertEqual(collected[0].text, "Hel")
        self.assertTrue(resp.closed)

    def test_stream_connection_refused(self) -> None:
        with _patch_env(_TEST_KEY_ENV), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=ConnectionRefusedError(),
        ):
            p = _make_provider()
            gen = p.stream(
                [ChatMessage("user", "hi")],
                "gpt-4o",
                {},
                threading.Event(),
            )
            with self.assertRaises(ProviderError) as cm:
                list(gen)
            self.assertEqual(cm.exception.code, "UNREACHABLE")
