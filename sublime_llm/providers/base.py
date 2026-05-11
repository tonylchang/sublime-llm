"""Provider abstraction."""
import abc
import enum
import threading
from dataclasses import dataclass
from typing import Iterator, List, Optional, Union


class ProviderHealth(enum.Enum):
    OK = "ok"
    UNREACHABLE = "unreachable"
    MISSING_CREDENTIAL = "missing_credential"
    MISCONFIGURED = "misconfigured"


_VALID_ROLES = ("system", "user", "assistant")


@dataclass
class ChatMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in _VALID_ROLES:
            raise ValueError("unknown role: {0}".format(self.role))


@dataclass
class TextDelta:
    text: str


@dataclass
class Done:
    reason: str
    usage: Optional[dict] = None


StreamEvent = Union[TextDelta, Done]


class ProviderError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def __str__(self) -> str:
        return self.message


class Provider(abc.ABC):
    name: str = ""

    def __init__(self, settings_dict: dict) -> None:
        self.settings_dict = settings_dict or {}

    @abc.abstractmethod
    def is_available(self) -> ProviderHealth:
        ...

    @abc.abstractmethod
    def list_models(self) -> List[str]:
        ...

    @abc.abstractmethod
    def complete(
        self,
        messages: List[ChatMessage],
        model: str,
        options: dict,
        cancel_event: threading.Event,
    ) -> str:
        ...

    @abc.abstractmethod
    def stream(
        self,
        messages: List[ChatMessage],
        model: str,
        options: dict,
        cancel_event: threading.Event,
    ) -> Iterator[StreamEvent]:
        ...
