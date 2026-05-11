"""Tests for sublime_llm.providers.openrouter."""
import io
import json
import threading
import unittest
import urllib.error
from unittest import mock

from sublime_llm.providers import ChatMessage, ProviderError
from sublime_llm.providers.openrouter import OpenRouterProvider


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
        "sublime_llm.secrets._read_secrets_file",
        return_value={},
    )


def _no_or_key():
    return mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False)


def _or_key():
    return mock.patch.dict(
        "os.environ", {"OPENROUTER_API_KEY": "sk-or-test12345"}, clear=False
    )


class BaseUrlTests(unittest.TestCase):
    def test_default_base_url(self) -> None:
        p = OpenRouterProvider({})
        self.assertEqual(p.base_url, "https://openrouter.ai/api/v1")


class ListModelsTests(unittest.TestCase):
    def test_list_models_without_key(self) -> None:
        body = json.dumps(
            {"data": [{"id": "openai/gpt-4o"}, {"id": "anthropic/claude-opus-4"}]}
        ).encode("utf-8")
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            return MockResponse(body=body, status=200)

        with _no_or_key(), _patch_no_secret_file(), mock.patch(
            "sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            p = OpenRouterProvider({})
            models = p.list_models()

        self.assertEqual(models, ["anthropic/claude-opus-4", "openai/gpt-4o"])
        self.assertEqual(captured["url"], "https://openrouter.ai/api/v1/models")
        # No Authorization header should be sent on /models.
        lowered = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertNotIn("authorization", lowered)


class HeadersTests(unittest.TestCase):
    def test_attribution_headers_present_when_configured(self) -> None:
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        ).encode("utf-8")
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["headers"] = dict(req.header_items())
            return MockResponse(body=body, status=200)

        settings = {
            "openrouter_referer": "https://example.test",
            "openrouter_title": "Sublime LLM Tests",
        }
        with _or_key(), _patch_no_secret_file(), mock.patch(
            "sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            p = OpenRouterProvider(settings)
            p.complete(
                [ChatMessage("user", "hi")],
                "openai/gpt-4o",
                {},
                threading.Event(),
            )

        # urllib normalizes header names to first-letter-cap form.
        lowered = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertEqual(lowered.get("http-referer"), "https://example.test")
        self.assertEqual(lowered.get("X-title".lower()), "Sublime LLM Tests")
        self.assertTrue(lowered.get("authorization", "").startswith("Bearer "))

    def test_attribution_headers_omitted_when_not_configured(self) -> None:
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        ).encode("utf-8")
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["headers"] = dict(req.header_items())
            return MockResponse(body=body, status=200)

        with _or_key(), _patch_no_secret_file(), mock.patch(
            "sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            p = OpenRouterProvider({})
            p.complete(
                [ChatMessage("user", "hi")],
                "openai/gpt-4o",
                {},
                threading.Event(),
            )

        lowered = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertNotIn("http-referer", lowered)
        self.assertNotIn("x-title", lowered)


class ErrorMessageTests(unittest.TestCase):
    def test_401_says_openrouter(self) -> None:
        err = urllib.error.HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"bad key"),
        )
        with _or_key(), _patch_no_secret_file(), mock.patch(
            "sublime_llm.providers.openai.urllib.request.urlopen",
            side_effect=err,
        ):
            p = OpenRouterProvider({})
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "openai/gpt-4o",
                    {},
                    threading.Event(),
                )
            self.assertIn("OpenRouter", cm.exception.message)
            self.assertNotIn("OpenAI ", cm.exception.message)

    def test_missing_credential_says_openrouter(self) -> None:
        with _no_or_key(), _patch_no_secret_file():
            p = OpenRouterProvider({})
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "openai/gpt-4o",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "MISSING_CREDENTIAL")
            self.assertIn("OpenRouter", cm.exception.message)
            self.assertIn("OPENROUTER_API_KEY", cm.exception.message)


if __name__ == "__main__":
    unittest.main()
