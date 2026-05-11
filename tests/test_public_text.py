"""Static checks for public/user-facing text."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicTextTests(unittest.TestCase):
    def test_status_messages_use_sublime_llm_prefix(self) -> None:
        commands = (ROOT / "sublime_llm" / "commands.py").read_text(encoding="utf-8")
        self.assertNotIn('status_message("LLM:', commands)
        self.assertNotIn("status_message('LLM:", commands)
        self.assertNotIn('return "LLM:', commands)

    def test_public_docs_use_sublime_llm_command_prefix(self) -> None:
        checked = [
            ROOT / "README.md",
            ROOT / "INSTALL.md",
            ROOT / "CHANGELOG.md",
            ROOT / "messages" / "install.txt",
            ROOT / "messages" / "1.0.0.txt",
        ]
        offenders = []
        for path in checked:
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\bLLM:", text):
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


if __name__ == "__main__":
    unittest.main()
