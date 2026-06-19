"""Tests for sublime_llm.providers.deepseek."""
import io
import json
import threading
import urllib.error
from unittest import mock

from unittesting import DeferrableTestCase

from LLM.sublime_llm.providers import ChatMessage, ProviderError
from LLM.sublime_llm.providers.deepseek import DeepSeekProvider


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


def _ds_key():
    return mock.patch.dict(
        "os.environ", {"DEEPSEEK_API_KEY": "sk-ds-test12345"}, clear=False
    )


def _no_ds_key():
    return mock.patch.dict("os.environ", {"DEEPSEEK_API_KEY": ""}, clear=False)


class BaseUrlTests(DeferrableTestCase):
    def test_default_base_url(self) -> None:
        p = DeepSeekProvider({})
        self.assertEqual(p.base_url, "https://api.deepseek.com")


class KeyResolutionTests(DeferrableTestCase):
    def test_key_resolved_via_deepseek_env(self) -> None:
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        ).encode("utf-8")
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["headers"] = dict(req.header_items())
            return MockResponse(body=body, status=200)

        with _ds_key(), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            p = DeepSeekProvider({})
            p.complete(
                [ChatMessage("user", "hi")],
                "deepseek-v4-pro",
                {},
                threading.Event(),
            )

        lowered = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertEqual(lowered.get("authorization"), "Bearer sk-ds-test12345")


class ListModelsTests(DeferrableTestCase):
    def test_list_models_success(self) -> None:
        body = json.dumps(
            {"data": [{"id": "deepseek-v4-pro"}, {"id": "deepseek-v4-flash"}]}
        ).encode("utf-8")
        with _ds_key(), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            return_value=MockResponse(body=body, status=200),
        ):
            p = DeepSeekProvider({})
            self.assertEqual(p.list_models(), ["deepseek-v4-flash", "deepseek-v4-pro"])

    def test_list_models_falls_back_on_404(self) -> None:
        err = urllib.error.HTTPError(
            url="https://api.deepseek.com/models",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b"nope"),
        )
        with _ds_key(), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=err,
        ):
            p = DeepSeekProvider({})
            self.assertEqual(
                p.list_models(), ["deepseek-v4-flash", "deepseek-v4-pro"]
            )

        self.assertTrue(err.closed)

    def test_list_models_falls_back_on_connection_error(self) -> None:
        with _ds_key(), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=ConnectionRefusedError(),
        ):
            p = DeepSeekProvider({})
            self.assertEqual(
                p.list_models(), ["deepseek-v4-flash", "deepseek-v4-pro"]
            )

    def test_list_models_custom_fallback(self) -> None:
        err = urllib.error.HTTPError(
            url="https://api.deepseek.com/models",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b"nope"),
        )
        with _ds_key(), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=err,
        ):
            p = DeepSeekProvider({"deepseek_models": ["deepseek-r1", "deepseek-coder"]})
            self.assertEqual(p.list_models(), ["deepseek-r1", "deepseek-coder"])

    def test_list_models_no_key_uses_fallback(self) -> None:
        with _no_ds_key(), _patch_no_secret_file(), mock.patch(
            "LLM.sublime_llm.providers.openai.urllib.request.urlopen"
        ) as urlopen:
            p = DeepSeekProvider({})
            self.assertEqual(
                p.list_models(), ["deepseek-v4-flash", "deepseek-v4-pro"]
            )
            urlopen.assert_not_called()


class ErrorMessageTests(DeferrableTestCase):
    def test_missing_credential_says_deepseek(self) -> None:
        with _no_ds_key(), _patch_no_secret_file():
            p = DeepSeekProvider({})
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "deepseek-v4-pro",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "MISSING_CREDENTIAL")
            self.assertIn("DeepSeek", cm.exception.message)
