"""Tests for sublime_llm.providers.anthropic."""
import io
import json
import threading
import unittest
import urllib.error
from unittest import mock

from sublime_llm.providers import (
    ChatMessage,
    Done,
    ProviderError,
    ProviderHealth,
    TextDelta,
)
from sublime_llm.providers.anthropic import AnthropicProvider


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


def _make_provider() -> AnthropicProvider:
    return AnthropicProvider({})


_KEY_ENV = {"ANTHROPIC_API_KEY": "sk-ant-test123abcdefghijklmnop"}


class TranslateMessagesTests(unittest.TestCase):
    def test_extract_and_concatenate_system(self) -> None:
        p = _make_provider()
        msgs = [
            ChatMessage("system", "Be brief."),
            ChatMessage("system", "Be polite."),
            ChatMessage("user", "Hi"),
            ChatMessage("assistant", "Hello"),
            ChatMessage("user", "How are you?"),
        ]
        system_str, out = p._translate_messages(msgs)
        self.assertEqual(system_str, "Be brief.\n\nBe polite.")
        self.assertEqual(
            out,
            [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
                {"role": "user", "content": "How are you?"},
            ],
        )

    def test_empty_system_when_none(self) -> None:
        p = _make_provider()
        msgs = [
            ChatMessage("user", "Hi"),
            ChatMessage("assistant", "Hello"),
        ]
        system_str, out = p._translate_messages(msgs)
        self.assertEqual(system_str, "")
        self.assertEqual(len(out), 2)


class IsAvailableTests(unittest.TestCase):
    def test_no_key_missing_credential(self) -> None:
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            with mock.patch(
                "sublime_llm.providers.anthropic.resolve_key",
                return_value=(None, "missing"),
            ):
                p = _make_provider()
                self.assertEqual(p.is_available(), ProviderHealth.MISSING_CREDENTIAL)

    def test_with_key_ok(self) -> None:
        with mock.patch.dict("os.environ", _KEY_ENV, clear=False):
            with mock.patch(
                "sublime_llm.providers.anthropic.resolve_key",
                return_value=(_KEY_ENV["ANTHROPIC_API_KEY"], "env"),
            ):
                p = _make_provider()
                self.assertEqual(p.is_available(), ProviderHealth.OK)


class ListModelsTests(unittest.TestCase):
    def test_default_list(self) -> None:
        p = _make_provider()
        models = p.list_models()
        self.assertIn("claude-opus-4-7", models)
        self.assertIn("claude-sonnet-4-6", models)
        self.assertIn("claude-haiku-4-5", models)
        # Order is preserved (preference encoded).
        self.assertEqual(models[0], "claude-opus-4-7")

    def test_settings_override(self) -> None:
        custom = ["claude-foo", "claude-bar"]
        p = AnthropicProvider({"anthropic_models": custom})
        self.assertEqual(p.list_models(), custom)


class CompleteTests(unittest.TestCase):
    def _resolve_patch(self):
        return mock.patch(
            "sublime_llm.providers.anthropic.resolve_key",
            return_value=(_KEY_ENV["ANTHROPIC_API_KEY"], "env"),
        )

    def test_happy_path_returns_text(self) -> None:
        body = json.dumps(
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "hello world"}],
                "stop_reason": "end_turn",
            }
        ).encode("utf-8")
        with self._resolve_patch(), mock.patch(
            "sublime_llm.providers.anthropic.urllib.request.urlopen",
            return_value=MockResponse(body=body, status=200),
        ):
            p = _make_provider()
            out = p.complete(
                [ChatMessage("user", "hi")],
                "claude-opus-4-7",
                {"max_tokens": 1024, "temperature": 0.5},
                threading.Event(),
            )
            self.assertEqual(out, "hello world")

    def test_max_tokens_always_in_body(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["body"] = req.data
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            body = json.dumps(
                {"content": [{"type": "text", "text": "ok"}]}
            ).encode("utf-8")
            return MockResponse(body=body, status=200)

        with self._resolve_patch(), mock.patch(
            "sublime_llm.providers.anthropic.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            p = _make_provider()
            p.complete(
                [ChatMessage("system", "be brief"), ChatMessage("user", "hi")],
                "claude-opus-4-7",
                {"max_tokens": 2048},
                threading.Event(),
            )

        sent = json.loads(captured["body"].decode("utf-8"))
        self.assertIn("max_tokens", sent)
        self.assertEqual(sent["max_tokens"], 2048)
        # system hoisted out of messages.
        self.assertEqual(sent.get("system"), "be brief")
        for m in sent["messages"]:
            self.assertNotEqual(m["role"], "system")
        # uses x-api-key not Authorization.
        header_keys = {k.lower() for k in captured["headers"].keys()}
        self.assertIn("x-api-key", header_keys)
        self.assertIn("anthropic-version", header_keys)
        self.assertNotIn("authorization", header_keys)

    def test_max_tokens_default_when_omitted(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["body"] = req.data
            body = json.dumps(
                {"content": [{"type": "text", "text": "ok"}]}
            ).encode("utf-8")
            return MockResponse(body=body, status=200)

        with self._resolve_patch(), mock.patch(
            "sublime_llm.providers.anthropic.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            p = _make_provider()
            p.complete(
                [ChatMessage("user", "hi")],
                "claude-opus-4-7",
                {},
                threading.Event(),
            )

        sent = json.loads(captured["body"].decode("utf-8"))
        self.assertIn("max_tokens", sent)
        self.assertEqual(sent["max_tokens"], 4096)

    def _http_error(self, code: int) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            url="https://api.anthropic.com/v1/messages",
            code=code,
            msg="err",
            hdrs=None,
            fp=io.BytesIO(b"err"),
        )

    def test_complete_401(self) -> None:
        with self._resolve_patch(), mock.patch(
            "sublime_llm.providers.anthropic.urllib.request.urlopen",
            side_effect=self._http_error(401),
        ):
            p = _make_provider()
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "claude-opus-4-7",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "BAD_CREDENTIAL")
            self.assertFalse(cm.exception.retryable)

    def test_complete_429(self) -> None:
        with self._resolve_patch(), mock.patch(
            "sublime_llm.providers.anthropic.urllib.request.urlopen",
            side_effect=self._http_error(429),
        ):
            p = _make_provider()
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "claude-opus-4-7",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "RATE_LIMITED")
            self.assertTrue(cm.exception.retryable)

    def test_complete_404(self) -> None:
        with self._resolve_patch(), mock.patch(
            "sublime_llm.providers.anthropic.urllib.request.urlopen",
            side_effect=self._http_error(404),
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

    def test_complete_529(self) -> None:
        with self._resolve_patch(), mock.patch(
            "sublime_llm.providers.anthropic.urllib.request.urlopen",
            side_effect=self._http_error(529),
        ):
            p = _make_provider()
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "claude-opus-4-7",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "SERVER_ERROR")
            self.assertTrue(cm.exception.retryable)

    def test_complete_missing_credential(self) -> None:
        with mock.patch(
            "sublime_llm.providers.anthropic.resolve_key",
            return_value=(None, "missing"),
        ):
            p = _make_provider()
            with self.assertRaises(ProviderError) as cm:
                p.complete(
                    [ChatMessage("user", "hi")],
                    "claude-opus-4-7",
                    {},
                    threading.Event(),
                )
            self.assertEqual(cm.exception.code, "MISSING_CREDENTIAL")


class StreamTests(unittest.TestCase):
    def _resolve_patch(self):
        return mock.patch(
            "sublime_llm.providers.anthropic.resolve_key",
            return_value=(_KEY_ENV["ANTHROPIC_API_KEY"], "env"),
        )

    def _happy_sse(self) -> bytes:
        events = [
            (
                "message_start",
                {"type": "message_start", "message": {"id": "msg_1"}},
            ),
            (
                "content_block_start",
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello"},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": " world"},
                },
            ),
            (
                "content_block_stop",
                {"type": "content_block_stop", "index": 0},
            ),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            ),
            (
                "message_stop",
                {"type": "message_stop"},
            ),
        ]
        parts = []
        for name, payload in events:
            parts.append("event: " + name)
            parts.append("data: " + json.dumps(payload))
            parts.append("")
        return ("\n".join(parts) + "\n").encode("utf-8")

    def test_stream_happy_path(self) -> None:
        body = self._happy_sse()
        with self._resolve_patch(), mock.patch(
            "sublime_llm.providers.anthropic.urllib.request.urlopen",
            return_value=MockResponse(body=body, status=200),
        ):
            p = _make_provider()
            events = list(
                p.stream(
                    [ChatMessage("user", "hi")],
                    "claude-opus-4-7",
                    {},
                    threading.Event(),
                )
            )
        deltas = [e for e in events if isinstance(e, TextDelta)]
        dones = [e for e in events if isinstance(e, Done)]
        self.assertEqual([d.text for d in deltas], ["Hello", " world"])
        self.assertEqual(len(dones), 1)
        self.assertEqual(dones[0].reason, "end_turn")
        self.assertIsNotNone(dones[0].usage)
        self.assertEqual(dones[0].usage.get("output_tokens"), 5)

    def test_stream_error_event_raises(self) -> None:
        events = [
            ("message_start", {"type": "message_start", "message": {"id": "msg_1"}}),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hi"},
                },
            ),
            (
                "error",
                {"type": "error", "error": {"type": "overloaded_error", "message": "overloaded"}},
            ),
        ]
        parts = []
        for name, payload in events:
            parts.append("event: " + name)
            parts.append("data: " + json.dumps(payload))
            parts.append("")
        body = ("\n".join(parts) + "\n").encode("utf-8")

        with self._resolve_patch(), mock.patch(
            "sublime_llm.providers.anthropic.urllib.request.urlopen",
            return_value=MockResponse(body=body, status=200),
        ):
            p = _make_provider()
            collected = []
            with self.assertRaises(ProviderError) as cm:
                for event in p.stream(
                    [ChatMessage("user", "hi")],
                    "claude-opus-4-7",
                    {},
                    threading.Event(),
                ):
                    collected.append(event)
            self.assertEqual(cm.exception.code, "SERVER_ERROR")
            self.assertIn("overloaded", cm.exception.message)
            # First delta should have been yielded before error.
            self.assertEqual(len(collected), 1)
            self.assertIsInstance(collected[0], TextDelta)


if __name__ == "__main__":
    unittest.main()
