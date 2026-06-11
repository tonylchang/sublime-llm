"""Static checks for public/user-facing text."""
from pathlib import Path
import re

from unittesting import DeferrableTestCase


ROOT = Path(__file__).resolve().parents[1]


class PublicTextTests(DeferrableTestCase):
    def test_status_messages_use_llm_prefix(self) -> None:
        # User-facing status messages carry the "LLM:" brand prefix, not the
        # old "sublime-llm:" one.
        commands = (ROOT / "sublime_llm" / "commands.py").read_text(encoding="utf-8")
        self.assertNotIn('status_message("sublime-llm:', commands)
        self.assertNotIn("status_message('sublime-llm:", commands)
        self.assertNotIn('return "sublime-llm:', commands)

    def test_public_docs_use_llm_command_prefix(self) -> None:
        # Evergreen user-facing docs reference the current "LLM:" command
        # prefix. CHANGELOG and per-version upgrade messages are historical
        # and intentionally retain the old "sublime-llm:" names.
        checked = [
            ROOT / "README.md",
            ROOT / "INSTALL.md",
            ROOT / "messages" / "install.txt",
        ]
        offenders = []
        for path in checked:
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"sublime-llm:", text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(ROOT)}:{line}")
        self.assertEqual(offenders, [])

    def test_public_docs_prefer_config_json_over_external_secrets(self) -> None:
        checked = [
            ROOT / "README.md",
            ROOT / "INSTALL.md",
            ROOT / "SECURITY.md",
            ROOT / "messages" / "install.txt",
            ROOT / "messages" / "1.0.0.txt",
        ]
        offenders = []
        stale_patterns = [
            "external config/secrets file",
            "legacy secrets file",
            "legacy secrets files",
            "external secrets file",
            "Where to put your API keys",
            "~/.config/sublime-llm/secrets.json",
            "%APPDATA%\\sublime-llm\\secrets.json",
        ]
        for path in checked:
            text = path.read_text(encoding="utf-8")
            for pattern in stale_patterns:
                if pattern in text:
                    offenders.append(f"{path.relative_to(ROOT)} contains {pattern!r}")
        self.assertEqual(offenders, [])
