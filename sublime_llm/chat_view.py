"""Chat view surface for sublime-llm."""
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import sublime
import sublime_plugin

from . import persistence
from .logging_setup import get_logger

CHAT_VIEW_SETTING = "sublime_llm_chat_view"
CHAT_VIEW_STREAMING_SETTING = "sublime_llm_streaming"
CHAT_VIEW_NAME = "LLM Chat"
CHAT_SYNTAX_PATH = "Packages/LLM/ChatMarkdown.sublime-syntax"


@dataclass
class ChatViewHandle:
    view_id: int
    cancel_event: Any = field(default_factory=threading.Event)
    streaming: bool = False


# Per-window registry mapping window id to ChatViewHandle.
_registry: Dict[int, ChatViewHandle] = {}


def _find_existing_chat_view(window) -> Optional[object]:
    handle = _registry.get(window.id())
    if handle is not None:
        for view in window.views():
            if view.id() == handle.view_id and view.settings().get(CHAT_VIEW_SETTING):
                return view
        # Stale entry; clear it and fall through to a workspace scan.
        _registry.pop(window.id(), None)

    # Sublime may have restored the chat tab from the workspace while our
    # in-memory registry was wiped (Sublime restart or plugin reload). View
    # settings persist with the workspace, so look for any view that still
    # carries the chat-view marker and adopt it.
    for view in window.views():
        try:
            if view.settings().get(CHAT_VIEW_SETTING):
                _registry[window.id()] = ChatViewHandle(
                    view_id=view.id(),
                    cancel_event=threading.Event(),
                    streaming=False,
                )
                # Clear any stale streaming flag from a session that was
                # killed mid-stream.
                try:
                    view.settings().set(CHAT_VIEW_STREAMING_SETTING, False)
                except Exception:
                    pass
                return view
        except Exception:
            continue
    return None


def _target_group_for_chat(window) -> int:
    """Pick a group to host the chat view without changing the window layout."""
    try:
        return window.active_group()
    except Exception:
        return 0


class ChatView:
    def __init__(self, view) -> None:
        self._view = view

    def get_view(self):
        return self._view

    def get_handle(self) -> Optional[ChatViewHandle]:
        window = self._view.window() if self._view is not None else None
        if window is None:
            return None
        return _registry.get(window.id())

    def get_cancel_event(self):
        handle = self.get_handle()
        if handle is None:
            return None
        return handle.cancel_event

    def set_streaming(self, streaming: bool) -> None:
        handle = self.get_handle()
        if handle is not None:
            handle.streaming = bool(streaming)
        try:
            self._view.settings().set(CHAT_VIEW_STREAMING_SETTING, bool(streaming))
        except Exception:
            pass
        # While streaming, the whole buffer is read-only — the streaming text
        # command temporarily lifts it for each insert. When streaming ends,
        # restore the cursor-based protection.
        try:
            if streaming:
                self._view.set_read_only(True)
            else:
                _update_protection(self._view)
        except Exception:
            pass

    @classmethod
    def is_chat_view(cls, view) -> bool:
        if view is None:
            return False
        try:
            return bool(view.settings().get(CHAT_VIEW_SETTING))
        except Exception:
            return False

    @classmethod
    def find(cls, window) -> Optional["ChatView"]:
        existing = _find_existing_chat_view(window)
        if existing is None:
            return None
        return cls(existing)

    @classmethod
    def create_or_focus(cls, window) -> "ChatView":
        existing = _find_existing_chat_view(window)
        if existing is not None:
            group, _ = window.get_view_index(existing)
            if group >= 0:
                window.focus_group(group)
            window.focus_view(existing)
            return cls(existing)

        target_group = _target_group_for_chat(window)
        view = window.new_file()
        view.set_name(CHAT_VIEW_NAME)
        view.set_scratch(True)
        view.settings().set(CHAT_VIEW_SETTING, True)
        view.settings().set(CHAT_VIEW_STREAMING_SETTING, False)
        try:
            view.assign_syntax(CHAT_SYNTAX_PATH)
        except Exception:
            get_logger().warning("failed to assign ChatMarkdown syntax")
        window.set_view_index(view, target_group, 0)
        window.focus_group(target_group)
        window.focus_view(view)
        # MVP: leave the view editable; streaming-time read-only comes in B5.
        view.set_read_only(False)
        _registry[window.id()] = ChatViewHandle(
            view_id=view.id(), cancel_event=threading.Event(), streaming=False
        )
        chat_view = cls(view)
        loaded: Optional[str] = None
        try:
            loaded = persistence.load_chat(window)
        except Exception:
            get_logger().warning("chat persistence: load raised; starting fresh")
            loaded = None
        if loaded:
            view.run_command("sublime_llm_append", {"text": loaded})
            view.sel().clear()
            view.sel().add(sublime.Region(view.size()))
            view.show(view.size())
        else:
            chat_view.init_template()
        return chat_view

    def init_template(self) -> None:
        view = self._view
        view.run_command("sublime_llm_append", {"text": "<user> "})
        view.sel().clear()
        view.sel().add(sublime.Region(view.size()))
        view.show(view.size())

    def read_input(self) -> str:
        view = self._view
        text = view.substr(sublime.Region(0, view.size()))
        # Accept the current "<user> " marker plus two legacy variants so
        # older saved chats still load: the previous "<user>\n" form and the
        # original "### User\n" markdown-header form.
        idx = -1
        last_len = 0
        for marker in ("<user> ", "<user>\n", "### User\n"):
            j = text.rfind(marker)
            if j > idx:
                idx = j
                last_len = len(marker)
        if idx >= 0:
            return text[idx + last_len:].strip()
        return text.strip()

    def append_turn(self, role: str, text: str) -> None:
        self._view.run_command(
            "sublime_llm_append",
            {"text": "<{0}> {1}\n".format(role.lower(), text)},
        )

    def append_raw(self, text: str) -> None:
        self._view.run_command("sublime_llm_append", {"text": text})

    def _append_streamed(self, text: str) -> None:
        view = self._view
        view.run_command("sublime_llm_append", {"text": text})
        try:
            visible_end = view.visible_region().end()
        except Exception:
            visible_end = view.size()
        if visible_end >= view.size() - 400:
            view.show(view.size())

    def append_user_marker(self) -> None:
        view = self._view
        view.run_command(
            "sublime_llm_append", {"text": "\n<user> ", "trim_trailing": True}
        )
        view.sel().clear()
        view.sel().add(sublime.Region(view.size()))
        view.show(view.size())


_PROTECT_MARKERS = ("<user> ", "<user>\n", "### User\n")


def _input_region_start(view) -> int:
    text = view.substr(sublime.Region(0, view.size()))
    best = -1
    for marker in _PROTECT_MARKERS:
        j = text.rfind(marker)
        if j < 0:
            continue
        end = j + len(marker)
        if end > best:
            best = end
    return best


def _update_protection(view) -> None:
    if not ChatView.is_chat_view(view):
        return
    if view.settings().get(CHAT_VIEW_STREAMING_SETTING):
        # The streaming text command toggles read_only itself.
        return
    start = _input_region_start(view)
    if start < 0:
        view.set_read_only(False)
        return
    sels = view.sel()
    all_in_input = all(s.begin() >= start and s.end() >= start for s in sels)
    view.set_read_only(not all_in_input)


# Event listener defined here to keep the chat-view lifecycle in one module.
# MVP: only clears the registry on chat-view close. The group-collapse cascade bug
# described in PLAN section 4 may still manifest; deferred to a later ticket.
class ChatViewEvents(sublime_plugin.EventListener):
    def on_selection_modified(self, view) -> None:
        try:
            _update_protection(view)
        except Exception:
            pass

    def on_activated(self, view) -> None:
        try:
            _update_protection(view)
        except Exception:
            pass

    def on_text_command(self, view, command_name, args):
        # Block backspace/delete-word at the input boundary so users cannot
        # erase backwards into the protected chat history.
        if not ChatView.is_chat_view(view):
            return None
        if view.settings().get(CHAT_VIEW_STREAMING_SETTING):
            return None
        if command_name not in ("left_delete", "delete_word"):
            return None
        start = _input_region_start(view)
        if start < 0:
            return None
        for s in view.sel():
            if s.empty() and s.begin() <= start:
                return ("sublime_llm_noop", {})
            if s.begin() < start:
                return ("sublime_llm_noop", {})
        return None

    def on_pre_close(self, view) -> None:
        if not ChatView.is_chat_view(view):
            return
        window = view.window()
        if window is None:
            return
        try:
            text = view.substr(sublime.Region(0, view.size()))
            persistence.save_chat(window, text)
        except Exception:
            get_logger().warning("chat persistence: save on view close failed")
        wid = window.id()
        handle = _registry.get(wid)
        if handle is not None and handle.view_id == view.id():
            _registry.pop(wid, None)

    def on_pre_close_window(self, window) -> None:
        if window is None:
            return
        try:
            wid = window.id()
        except Exception:
            return
        try:
            chat = ChatView.find(window)
            if chat is not None:
                view = chat.get_view()
                text = view.substr(sublime.Region(0, view.size()))
                persistence.save_chat(window, text)
        except Exception:
            get_logger().warning("chat persistence: save on window close failed")
        _registry.pop(wid, None)
