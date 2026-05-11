"""Tests for sublime_llm.registry."""
import json
import os
import tempfile
import unittest
from unittest import mock

from sublime_llm import settings as settings_mod
from sublime_llm.providers.anthropic import AnthropicProvider
from sublime_llm.providers.custom import CustomOpenAIProvider
from sublime_llm.providers.deepseek import DeepSeekProvider
from sublime_llm.providers.ollama import OllamaProvider
from sublime_llm.providers.openai import OpenAIProvider
from sublime_llm.providers.openrouter import OpenRouterProvider
from sublime_llm.registry import get_active_provider, get_provider


class GetProviderTests(unittest.TestCase):
    def test_ollama(self) -> None:
        p = get_provider("ollama", {})
        self.assertIsInstance(p, OllamaProvider)

    def test_openai(self) -> None:
        p = get_provider("openai", {})
        self.assertIsInstance(p, OpenAIProvider)

    def test_anthropic(self) -> None:
        p = get_provider("anthropic", {})
        self.assertIsInstance(p, AnthropicProvider)

    def test_openrouter(self) -> None:
        p = get_provider("openrouter", {})
        self.assertIsInstance(p, OpenRouterProvider)
        # OpenRouter extends OpenAI; ensure base URL is the OpenRouter default.
        self.assertEqual(p.base_url, "https://openrouter.ai/api/v1")

    def test_deepseek(self) -> None:
        p = get_provider("deepseek", {})
        self.assertIsInstance(p, DeepSeekProvider)

    def test_custom(self) -> None:
        p = get_provider(
            "custom", {"custom_base_url": "http://localhost:1234/v1"}
        )
        self.assertIsInstance(p, CustomOpenAIProvider)
        self.assertEqual(p.base_url, "http://localhost:1234/v1")

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            get_provider("bogus", {})


class ActiveProviderExternalConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        settings_mod._instance = None
        self._tmpdir = tempfile.mkdtemp()
        self._tmp_config_path = os.path.join(self._tmpdir, "config.json")
        self._patch = mock.patch(
            "sublime_llm.secrets.get_external_config_file_path",
            return_value=self._tmp_config_path,
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
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

    def test_active_ollama_uses_external_base_url(self) -> None:
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
        p = get_active_provider()
        self.assertIsInstance(p, OllamaProvider)
        self.assertEqual(p.base_url, "http://llm-box:11434")


if __name__ == "__main__":
    unittest.main()
