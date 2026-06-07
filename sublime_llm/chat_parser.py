"""Chat buffer parser."""
import re
from typing import List

from .providers import ChatMessage

_HEADER_RE = re.compile(
    r"^(?:<(user|assistant|system)>|### (User|Assistant|System))",
    re.MULTILINE,
)


def _role_from_match(m) -> str:
    irc = m.group(1)
    if irc:
        return irc
    return (m.group(2) or "").lower()


def parse_messages(text: str, system_prompt: str = "") -> List[ChatMessage]:
    messages: List[ChatMessage] = []
    matches = list(_HEADER_RE.finditer(text or ""))
    starts_with_system = False
    if matches:
        first = matches[0]
        if _role_from_match(first) == "system" and (text[: first.start()].strip() == ""):
            starts_with_system = True
    for i, m in enumerate(matches):
        role = _role_from_match(m)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if not body:
            continue
        messages.append(ChatMessage(role=role, content=body))
    if system_prompt and not starts_with_system:
        messages.insert(0, ChatMessage(role="system", content=system_prompt))
    return messages
