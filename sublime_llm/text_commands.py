"""Text commands for sublime-llm."""
import sublime
import sublime_plugin


class SublimeLlmNoopCommand(sublime_plugin.TextCommand):
    def run(self, edit) -> None:
        return


class SublimeLlmAppendCommand(sublime_plugin.TextCommand):
    def run(self, edit, text: str, trim_trailing: bool = False) -> None:
        was_read_only = self.view.is_read_only()
        self.view.set_read_only(False)
        if trim_trailing:
            full = self.view.substr(sublime.Region(0, self.view.size()))
            stripped = full.rstrip()
            if len(stripped) < len(full):
                self.view.replace(edit, sublime.Region(0, self.view.size()), stripped)
        self.view.insert(edit, self.view.size(), text)
        self.view.set_read_only(was_read_only)
