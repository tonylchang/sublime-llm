"""Tests for sublime_llm.providers.base."""
import unittest

from sublime_llm.providers import (
    ChatMessage,
    Done,
    Provider,
    ProviderError,
    ProviderHealth,
    TextDelta,
)


class ProviderAbstractTests(unittest.TestCase):
    def test_provider_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            Provider({})  # type: ignore[abstract]


class ChatMessageTests(unittest.TestCase):
    def test_valid_roles(self) -> None:
        ChatMessage("system", "hi")
        ChatMessage("user", "hi")
        ChatMessage("assistant", "hi")

    def test_invalid_role_raises(self) -> None:
        with self.assertRaises(ValueError):
            ChatMessage("bogus", "x")


class ProviderErrorTests(unittest.TestCase):
    def test_str_returns_message(self) -> None:
        err = ProviderError("UNREACHABLE", "msg", False)
        self.assertEqual(str(err), "msg")

    def test_attributes_accessible(self) -> None:
        err = ProviderError("RATE_LIMITED", "slow down", True)
        self.assertEqual(err.code, "RATE_LIMITED")
        self.assertEqual(err.message, "slow down")
        self.assertTrue(err.retryable)

    def test_retryable_defaults_false(self) -> None:
        err = ProviderError("BAD_CREDENTIAL", "nope")
        self.assertFalse(err.retryable)


class EventTypeTests(unittest.TestCase):
    def test_text_delta(self) -> None:
        d = TextDelta(text="hello")
        self.assertEqual(d.text, "hello")

    def test_done(self) -> None:
        d = Done(reason="stop", usage={"tokens": 5})
        self.assertEqual(d.reason, "stop")
        self.assertEqual(d.usage, {"tokens": 5})

    def test_done_usage_optional(self) -> None:
        d = Done(reason="stop")
        self.assertIsNone(d.usage)


class ProviderHealthTests(unittest.TestCase):
    def test_members(self) -> None:
        self.assertTrue(hasattr(ProviderHealth, "OK"))
        self.assertTrue(hasattr(ProviderHealth, "UNREACHABLE"))
        self.assertTrue(hasattr(ProviderHealth, "MISSING_CREDENTIAL"))
        self.assertTrue(hasattr(ProviderHealth, "MISCONFIGURED"))


if __name__ == "__main__":
    unittest.main()
