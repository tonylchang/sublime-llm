"""Text commands for sublime-llm."""
try:
    import sublime_plugin  # type: ignore
except ImportError:
    sublime_plugin = None  # type: ignore


_TextCommandBase = sublime_plugin.TextCommand if sublime_plugin is not None else object


class SublimeLlmNoopCommand(_TextCommandBase):  # type: ignore[misc,valid-type]
    def run(self, edit) -> None:
        return


class SublimeLlmAppendCommand(_TextCommandBase):  # type: ignore[misc,valid-type]
    def run(self, edit, text: str, trim_trailing: bool = False) -> None:
        was_read_only = self.view.is_read_only()
        self.view.set_read_only(False)
        if trim_trailing:
            full = self.view.substr(self._region(0, self.view.size()))
            stripped = full.rstrip()
            if len(stripped) < len(full):
                self.view.replace(edit, self._region(0, self.view.size()), stripped)
        self.view.insert(edit, self.view.size(), text)
        self.view.set_read_only(was_read_only)

    @staticmethod
    def _region(a: int, b: int):
        # Lazy import so the module stays importable outside Sublime.
        import sublime  # type: ignore
        return sublime.Region(a, b)
