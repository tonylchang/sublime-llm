"""Tests for sublime_llm.providers.custom."""
import io
import json
import threading
import urllib.error
from unittest import mock

from unittesting import DeferrableTestCase

from LLM.sublime_llm.providers import ChatMessage
from LLM.sublime_llm.providers.base import ProviderHealth
from LLM.sublime_llm.providers.custom import CustomOpenAIProvider


class MockResponse:
    def __init__(self, body: bytes = b"", status: int = 200, headers=None) -> None:
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


def _patch_no_secret_file():
    return mock.patch(
        "LLM.sublime_llm.secrets._read_secrets_file",
        return_value={},
    )


def _no_custom_key():
    return mock.patch.dict("os.environ", {"CUSTOM_API_KEY": ""}, clear=False)


def _custom_key():
    return mock.patch.dict(
        "os.environ", {"CUSTOM_API_KEY": "sk-cu-test12345"}, clear=False
    )


class BaseUrlTests(DeferrableTestCase):
    def test_missing_base_url_is_misconfigured(self) -> None:
        with _no_custom_key(), _patch_no_secret_file():
            p = CustomOpenAIProvider({})
            self.assertEqual(p.is_available(), ProviderHealth.MISCONFIGURED)

    def test_base_url_normalized(self) -> None:
        with _no_custom_key(), _patch_no_secret_file():
            p = CustomOpenAIProvider(
                {"custom_base_url": "http://localhost:1234/v1/"}
            )
            self.assertEqual(p.base_url, "http://localhost:1234/v1")


class HeaderTests(DeferrableTestCase):
    def test_with_key_sends_authorization(self) -> None:
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        ).encode("utf-8")
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["headers"] = dict(req.header_items())
            return MockResponse(body=body, status=200)

        with _custom_key(), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            p = CustomOpenAIProvider({"custom_base_url": "http://localhost:1234/v1"})
            p.complete(
                [ChatMessage("user", "hi")],
                "local-model",
                {},
                threading.Event(),
            )

        lowered = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertEqual(lowered.get("authorization"), "Bearer sk-cu-test12345")

    def test_without_key_omits_authorization_and_no_error(self) -> None:
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        ).encode("utf-8")
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["headers"] = dict(req.header_items())
            return MockResponse(body=body, status=200)

        with _no_custom_key(), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            p = CustomOpenAIProvider({"custom_base_url": "http://localhost:1234/v1"})
            # Should not raise MISSING_CREDENTIAL.
            out = p.complete(
                [ChatMessage("user", "hi")],
                "local-model",
                {},
                threading.Event(),
            )

        lowered = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertNotIn("authorization", lowered)
        self.assertEqual(out, "ok")


class ListModelsTests(DeferrableTestCase):
    def test_list_models_404_falls_back_to_configured(self) -> None:
        err = urllib.error.HTTPError(
            url="http://localhost:1234/v1/models",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b"nope"),
        )
        with _no_custom_key(), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=err,
        ):
            p = CustomOpenAIProvider(
                {
                    "custom_base_url": "http://localhost:1234/v1",
                    "custom_models": ["local-llama-3", "local-mistral"],
                }
            )
            self.assertEqual(p.list_models(), ["local-llama-3", "local-mistral"])

    def test_list_models_success(self) -> None:
        body = json.dumps(
            {"data": [{"id": "local-llama-3"}, {"id": "local-mistral"}]}
        ).encode("utf-8")
        with _no_custom_key(), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            return_value=MockResponse(body=body, status=200),
        ):
            p = CustomOpenAIProvider(
                {"custom_base_url": "http://localhost:1234/v1"}
            )
            self.assertEqual(p.list_models(), ["local-llama-3", "local-mistral"])

    def test_list_models_404_empty_fallback(self) -> None:
        err = urllib.error.HTTPError(
            url="http://localhost:1234/v1/models",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b"nope"),
        )
        with _no_custom_key(), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=err,
        ):
            p = CustomOpenAIProvider({"custom_base_url": "http://localhost:1234/v1"})
            self.assertEqual(p.list_models(), [])


class LabelTests(DeferrableTestCase):
    def test_custom_label_used_in_errors(self) -> None:
        err = urllib.error.HTTPError(
            url="http://localhost:1234/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b"rate limited"),
        )
        from LLM.sublime_llm.providers import ProviderError as _PE
        with _no_custom_key(), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=err,
        ):
            p = CustomOpenAIProvider(
                {
                    "custom_base_url": "http://localhost:1234/v1",
                    "custom_label": "LM Studio",
                }
            )
            with self.assertRaises(_PE) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "local-model",
                    {},
                    threading.Event(),
                )
            self.assertIn("LM Studio", cm.exception.message)
