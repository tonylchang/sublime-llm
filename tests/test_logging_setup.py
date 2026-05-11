"""Tests for sublime_llm.logging_setup."""
import logging
import unittest

from sublime_llm import logging_setup
from sublime_llm.logging_setup import (
    SecretRedactFilter,
    get_logger,
    register_secret,
    unregister_secret,
)


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


class LoggingSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = get_logger()
        self.handler = _ListHandler()
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.handler.addFilter(SecretRedactFilter())
        self.logger.addHandler(self.handler)

    def tearDown(self) -> None:
        self.logger.removeHandler(self.handler)
        # Reset registered secrets between tests.
        logging_setup._secrets.clear()

    def _last(self) -> str:
        return self.handler.records[-1]

    def test_registered_secret_redacted(self) -> None:
        register_secret("my-secret-123")
        self.logger.info("the key is my-secret-123")
        self.assertIn("[REDACTED]", self._last())
        self.assertNotIn("my-secret-123", self._last())

    def test_bearer_token_redacted(self) -> None:
        self.logger.info("Authorization: Bearer sk-abc123def456ghi789jkl0")
        self.assertIn("[REDACTED]", self._last())
        self.assertNotIn("sk-abc123def456ghi789jkl0", self._last())

    def test_anthropic_key_shape_redacted(self) -> None:
        self.logger.info("key=sk-ant-XXXXXXXXXXXXXXXXXXXX")
        self.assertIn("[REDACTED]", self._last())
        self.assertNotIn("sk-ant-XXXXXXXXXXXXXXXXXXXX", self._last())

    def test_openai_key_shape_redacted(self) -> None:
        self.logger.info("key=sk-ABCDEFGHIJKLMNOPQRSTUVWX")
        self.assertIn("[REDACTED]", self._last())
        self.assertNotIn("sk-ABCDEFGHIJKLMNOPQRSTUVWX", self._last())

    def test_unregister_secret_reverses(self) -> None:
        register_secret("rotating-secret")
        unregister_secret("rotating-secret")
        self.logger.info("value is rotating-secret here")
        self.assertIn("rotating-secret", self._last())

    def test_args_redacted(self) -> None:
        register_secret("arg-secret")
        self.logger.info("value=%s", "arg-secret")
        self.assertIn("[REDACTED]", self._last())
        self.assertNotIn("arg-secret", self._last())

    def test_non_string_args_do_not_crash(self) -> None:
        self.logger.info("count=%d size=%d", 5, 10)
        self.assertIn("count=5 size=10", self._last())


if __name__ == "__main__":
    unittest.main()
