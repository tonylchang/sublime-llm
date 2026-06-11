"""Tests for sublime_llm.settings."""
import json
import os
import tempfile
from unittest import mock

from unittesting import DeferrableTestCase

from LLM.sublime_llm import settings as settings_mod
from LLM.sublime_llm.settings import (
    DEFAULTS,
    Settings,
    get_settings,
    is_placeholder,
)


class PlaceholderTests(DeferrableTestCase):
    def test_replace_me_is_placeholder(self) -> None:
        self.assertTrue(is_placeholder("sk-REPLACE_ME"))
        self.assertTrue(is_placeholder("replace_me"))

    def test_your_key_here_is_placeholder(self) -> None:
        self.assertTrue(is_placeholder("YOUR_KEY_HERE"))
        self.assertTrue(is_placeholder("prefix-your_key_here-suffix"))

    def test_dots_is_placeholder(self) -> None:
        self.assertTrue(is_placeholder("...."))
        self.assertTrue(is_placeholder("sk-........"))

    def test_three_dots_not_placeholder(self) -> None:
        self.assertFalse(is_placeholder("sk-..."))

    def test_empty_and_whitespace_is_placeholder(self) -> None:
        self.assertTrue(is_placeholder(""))
        self.assertTrue(is_placeholder("   "))
        self.assertTrue(is_placeholder(None))

    def test_real_key_shape_not_placeholder(self) -> None:
        self.assertFalse(is_placeholder("sk-abc123def456ghi789"))
        self.assertFalse(is_placeholder("ollama"))


class _EmptySettings:
    """Stands in for a sublime.Settings object with no keys set."""

    def get(self, key, default=None):
        return default


class SettingsTests(DeferrableTestCase):
    def setUp(self) -> None:
        # Ensure a fresh settings instance for each test.
        settings_mod._instance = None
        self._tmpdir = tempfile.mkdtemp()
        self._tmp_config_path = os.path.join(self._tmpdir, "config.json")
        self._config_path_patch = mock.patch(
            "LLM.sublime_llm.secrets.get_external_config_file_path",
            return_value=self._tmp_config_path,
        )
        self._config_path_patch.start()
        self.settings = Settings()

    def tearDown(self) -> None:
        self._config_path_patch.stop()
        settings_mod._instance = None
        try:
            if os.path.exists(self._tmp_config_path):
                os.remove(self._tmp_config_path)
            os.rmdir(self._tmpdir)
        except OSError:
            pass

    def _write_external_config(self, data: dict) -> None:
        with open(self._tmp_config_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        if os.name != "nt":
            os.chmod(self._tmp_config_path, 0o600)

    def test_defaults_loaded_from_shipped_settings(self) -> None:
        # The shipped LLM.sublime-settings matches DEFAULTS.
        self.assertEqual(self.settings.get_provider(), DEFAULTS["provider"])
        self.assertEqual(self.settings.get_base_url(), DEFAULTS["base_url"])
        self.assertEqual(self.settings.get_temperature(), DEFAULTS["temperature"])
        self.assertEqual(self.settings.get_max_tokens(), DEFAULTS["max_tokens"])
        self.assertEqual(self.settings.get_system_prompt(), DEFAULTS["system_prompt"])
        self.assertEqual(self.settings.get_model(), DEFAULTS["model"])
        self.assertEqual(self.settings.get_model(), "llama3.2")

    def test_missing_key_returns_default(self) -> None:
        # Swap in an empty settings object to simulate missing keys.
        self.settings._sublime_settings = _EmptySettings()
        self.assertEqual(self.settings.get_provider(), DEFAULTS["provider"])
        self.assertEqual(self.settings.get_max_tokens(), DEFAULTS["max_tokens"])

    def test_get_settings_returns_singleton(self) -> None:
        a = get_settings()
        b = get_settings()
        self.assertIs(a, b)

    def test_add_on_change_callback_registered(self) -> None:
        calls = []
        self.settings.add_on_change(lambda: calls.append(1))
        # Directly invoke the internal notifier rather than touching settings on disk.
        self.settings._on_change()
        self.assertEqual(calls, [1])

    def test_get_matches_typed_accessor(self) -> None:
        self.assertEqual(self.settings.get("provider"), self.settings.get_provider())

    def test_get_returns_default_for_unknown_key(self) -> None:
        self.assertEqual(self.settings.get("nonexistent_key", "fallback"), "fallback")
        self.assertIsNone(self.settings.get("nonexistent_key"))

    def test_external_config_supplies_active_provider_and_provider_settings(self) -> None:
        self._write_external_config(
            {
                "active_provider": "ollama",
                "providers": {
                    "ollama": {
                        "base_url": "http://llm-box:11434",
                        "model": "llama3.2",
                    }
                },
            }
        )
        self.assertEqual(self.settings.get_provider(), "ollama")
        self.assertEqual(self.settings.get_base_url(), "http://llm-box:11434")
        self.assertEqual(self.settings.get_model(), "llama3.2")

    def test_external_config_provider_specific_flat_keys(self) -> None:
        self._write_external_config(
            {
                "providers": {
                    "openai": {
                        "base_url": "https://proxy.example/v1",
                        "model": "gpt-test",
                    },
                    "openrouter": {"referer": "https://example.com", "title": "Sublime LLM"},
                }
            }
        )
        self.assertEqual(self.settings.get("openai_base_url"), "https://proxy.example/v1")
        self.assertEqual(self.settings.get("openai_model"), "gpt-test")
        self.assertEqual(self.settings.get("openrouter_referer"), "https://example.com")
        self.assertEqual(self.settings.get("openrouter_title"), "Sublime LLM")
