"""sublime-llm plugin entry point. Sublime auto-loads this file at the package root."""
from .sublime_llm.logging_setup import get_logger
from .sublime_llm.chat_view import ChatViewEvents
from .sublime_llm.commands import (
    SublimeLlmCancelCommand,
    SublimeLlmChooseModelCommand,
    SublimeLlmChooseProviderCommand,
    SublimeLlmClearChatCommand,
    SublimeLlmOpenChatCommand,
    SublimeLlmRenderLastResponseCommand,
    SublimeLlmSendFileCommand,
    SublimeLlmSendSelectionCommand,
    SublimeLlmShowSecretStatusCommand,
    SublimeLlmShowStatusCommand,
    SublimeLlmSubmitCommand,
)
from .sublime_llm.text_commands import SublimeLlmAppendCommand, SublimeLlmNoopCommand


def plugin_loaded() -> None:
    get_logger().info("sublime-llm loaded")


__all__ = [
    "ChatViewEvents",
    "SublimeLlmAppendCommand",
    "SublimeLlmNoopCommand",
    "SublimeLlmCancelCommand",
    "SublimeLlmChooseModelCommand",
    "SublimeLlmChooseProviderCommand",
    "SublimeLlmClearChatCommand",
    "SublimeLlmOpenChatCommand",
    "SublimeLlmRenderLastResponseCommand",
    "SublimeLlmSendFileCommand",
    "SublimeLlmSendSelectionCommand",
    "SublimeLlmShowSecretStatusCommand",
    "SublimeLlmShowStatusCommand",
    "SublimeLlmSubmitCommand",
    "plugin_loaded",
]
