"""Tests for sublime_llm.secrets."""
import json
import logging
import os
import tempfile
import unittest
from unittest import mock

from sublime_llm import logging_setup, secrets, settings as settings_mod
from sublime_llm.logging_setup import SecretRedactFilter, get_logger
from sublime_llm.secrets import (
    get_external_config_file_path,
    get_provider_config,
    get_secrets_file_path,
    resolve_key,
    store_key_in_file,
)


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


class _FakeSettings:
    def __init__(self, values: dict) -> None:
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


class SecretsTests(unittest.TestCase):
    def setUp(self) -> None:
        # Reset module state.
        secrets._session_warned.clear()
        logging_setup._secrets.clear()
        settings_mod._instance = None

        # Strip any provider-related env vars that could leak.
        self._env_patch = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        for var in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "DEEPSEEK_API_KEY",
            "CUSTOM_API_KEY",
        ):
            os.environ.pop(var, None)

        # Attach a list handler with the redaction filter to capture log output.
        self.logger = get_logger()
        self.handler = _ListHandler()
        self.handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        self.handler.addFilter(SecretRedactFilter())
        self.logger.addHandler(self.handler)

        # Default: empty fake settings so the settings fallback never fires
        # unless a test explicitly opts in via _set_fake_settings.
        self._set_fake_settings({})

        # Default: point external config and legacy secrets paths at temp files.
        self._tmpdir = tempfile.mkdtemp()
        self._tmp_config_path = os.path.join(self._tmpdir, "config.json")
        self._tmp_secrets_path = os.path.join(self._tmpdir, "secrets.json")
        self._config_path_patch = mock.patch.object(
            secrets, "get_external_config_file_path", return_value=self._tmp_config_path
        )
        self._legacy_path_patch = mock.patch.object(
            secrets, "get_secrets_file_path", return_value=self._tmp_secrets_path
        )
        self._config_path_patch.start()
        self._legacy_path_patch.start()

    def tearDown(self) -> None:
        self.logger.removeHandler(self.handler)
        self._config_path_patch.stop()
        self._legacy_path_patch.stop()
        self._env_patch.stop()
        secrets._session_warned.clear()
        logging_setup._secrets.clear()
        settings_mod._instance = None
        # Best-effort tmpdir cleanup.
        try:
            for path in (self._tmp_config_path, self._tmp_secrets_path):
                if os.path.exists(path):
                    os.remove(path)
            os.rmdir(self._tmpdir)
        except OSError:
            pass

    def _set_fake_settings(self, values: dict) -> None:
        self._fake_settings = _FakeSettings(values)
        if not hasattr(self, "_settings_patch") or self._settings_patch is None:
            self._settings_patch = mock.patch.object(
                secrets, "get_settings", return_value=self._fake_settings
            )
            self._settings_patch.start()
            self.addCleanup(self._settings_patch.stop)
        else:
            self._settings_patch.stop()
            self._settings_patch = mock.patch.object(
                secrets, "get_settings", return_value=self._fake_settings
            )
            self._settings_patch.start()

    def _write_secrets_file(self, data: dict, mode: int = 0o600) -> None:
        with open(self._tmp_secrets_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        if os.name != "nt":
            os.chmod(self._tmp_secrets_path, mode)

    def _write_external_config(self, data: dict, mode: int = 0o600) -> None:
        with open(self._tmp_config_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        if os.name != "nt":
            os.chmod(self._tmp_config_path, mode)

    def _records(self):
        return list(self.handler.records)

    # 1. Env var resolution.
    def test_env_var_resolution(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test12345abcdefghijklmnop"
        key, source = resolve_key("openai")
        self.assertEqual(key, "sk-test12345abcdefghijklmnop")
        self.assertEqual(source, "env")

    # 2. Placeholder env var rejected.
    def test_placeholder_env_var_rejected(self) -> None:
        os.environ["OPENAI_API_KEY"] = "REPLACE_ME"
        key, source = resolve_key("openai")
        self.assertIsNone(key)
        self.assertEqual(source, "missing")

    # 3. External config resolution.
    def test_file_resolution(self) -> None:
        self._write_external_config(
            {"providers": {"openai": {"api_key": "sk-fro...cdef"}}}
        )
        key, source = resolve_key("openai")
        self.assertEqual(key, "sk-fro...cdef")
        self.assertEqual(source, "external_config")

    def test_legacy_secrets_file_resolution(self) -> None:
        self._write_secrets_file({"openai": "sk-leg...cdef"})
        key, source = resolve_key("openai")
        self.assertEqual(key, "sk-leg...cdef")
        self.assertEqual(source, "file")

    def test_provider_config_reads_non_secret_values(self) -> None:
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
        self.assertEqual(
            get_provider_config("ollama"),
            {"base_url": "http://llm-box:11434", "model": "llama3.2"},
        )

    # 4. Loose permissions warning (POSIX-only).
    def test_loose_permissions_warning(self) -> None:
        if os.name == "nt":
            self.skipTest("permissions test not applicable on Windows")
        self._write_secrets_file(
            {"openai": "sk-fromfile1234567890abcdef"}, mode=0o644
        )
        resolve_key("openai")
        joined = "\n".join(self._records())
        self.assertIn("loose permissions", joined)
        self.assertIn("chmod 600", joined)

    # 5. Settings fallback gated off (default).
    def test_settings_fallback_gated_off(self) -> None:
        self._set_fake_settings(
            {
                "openai_api_key": "sk-fromsettings",
                "allow_secrets_in_settings_file": False,
            }
        )
        key, source = resolve_key("openai")
        self.assertIsNone(key)
        self.assertEqual(source, "missing")
        joined = "\n".join(self._records())
        self.assertIn(
            "ignoring openai API key from settings file because allow_secrets_in_settings_file is false",
            joined,
        )

    # 6. Settings fallback gated on.
    def test_settings_fallback_gated_on(self) -> None:
        self._set_fake_settings(
            {
                "openai_api_key": "sk-fromsettings12345abcdef",
                "allow_secrets_in_settings_file": True,
            }
        )
        key, source = resolve_key("openai")
        self.assertEqual(key, "sk-fromsettings12345abcdef")
        self.assertEqual(source, "settings")

    # 7. Placeholder in file rejected.
    def test_placeholder_in_file_rejected(self) -> None:
        self._write_secrets_file({"openai": "YOUR_KEY_HERE"})
        key, source = resolve_key("openai")
        self.assertIsNone(key)
        self.assertEqual(source, "missing")

    # 7b. Malformed external config warns instead of failing silently.
    def test_malformed_config_json_warns(self) -> None:
        with open(self._tmp_config_path, "w", encoding="utf-8") as f:
            f.write('{"providers": {"openai": ')
        key, source = resolve_key("openai")
        self.assertIsNone(key)
        self.assertEqual(source, "missing")
        joined = "\n".join(self._records())
        self.assertIn("is not valid JSON", joined)
        self.assertIn(self._tmp_config_path, joined)

    def test_malformed_config_json_warns_once_per_session(self) -> None:
        with open(self._tmp_config_path, "w", encoding="utf-8") as f:
            f.write("not json")
        resolve_key("openai")
        resolve_key("openai")
        warnings = [r for r in self._records() if "is not valid JSON" in r]
        self.assertEqual(len(warnings), 1)

    def test_non_object_config_json_warns(self) -> None:
        with open(self._tmp_config_path, "w", encoding="utf-8") as f:
            f.write('["not", "an", "object"]')
        key, source = resolve_key("openai")
        self.assertIsNone(key)
        self.assertEqual(source, "missing")
        joined = "\n".join(self._records())
        self.assertIn("must contain a JSON object", joined)

    # 8. Resolved keys get registered with the redacting logger.
    def test_resolved_key_is_registered_for_redaction(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-redactme1234567890abcdef"
        key, _ = resolve_key("openai")
        self.logger.info("key is %s", key)
        joined = "\n".join(self._records())
        self.assertIn("[REDACTED]", joined)
        self.assertNotIn("sk-redactme1234567890abcdef", joined)

    # 9. store_key_in_file writes with 0o600 on POSIX.
    def test_store_key_in_file_permissions(self) -> None:
        if os.name == "nt":
            self.skipTest("permissions test not applicable on Windows")
        store_key_in_file("openai", "stored-key")
        self.assertTrue(os.path.exists(self._tmp_config_path))
        mode = os.stat(self._tmp_config_path).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        with open(self._tmp_config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["providers"]["openai"]["api_key"], "stored-key")

    # 10. store_key_in_file preserves existing provider config.
    def test_store_key_in_file_preserves_others(self) -> None:
        self._write_external_config(
            {
                "active_provider": "openai",
                "providers": {
                    "openai": {"base_url": "https://proxy.example/v1"},
                    "anthropic": {"api_key": "b"},
                },
            }
        )
        store_key_in_file("openai", "c")
        with open(self._tmp_config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["active_provider"], "openai")
        self.assertEqual(data["providers"]["openai"]["base_url"], "https://proxy.example/v1")
        self.assertEqual(data["providers"]["openai"]["api_key"], "c")
        self.assertEqual(data["providers"]["anthropic"], {"api_key": "b"})


class GetSecretsFilePathTests(unittest.TestCase):
    def test_path_is_absolute(self) -> None:
        # Smoke test: path should be platform-appropriate and absolute-ish
        # (expanduser may leave a relative path only if HOME unset, edge case).
        legacy_path = get_secrets_file_path()
        self.assertTrue(legacy_path.endswith("secrets.json"))
        self.assertIn("sublime-llm", legacy_path)
        config_path = get_external_config_file_path()
        self.assertTrue(config_path.endswith("config.json"))
        self.assertIn("sublime-llm", config_path)


if __name__ == "__main__":
    unittest.main()
