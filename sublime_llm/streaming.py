"""Generic SSE and NDJSON line iterators."""
import json
import threading
from typing import Iterator, Tuple

from .logging_setup import get_logger

_log = get_logger()


def iter_sse_lines(response, cancel_event: threading.Event) -> Iterator[Tuple[str, str]]:
    """Yield (event_type, data_str) tuples from a Server-Sent Events response."""
    event_type = "message"
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                break
            raw = response.readline()
            if not raw:
                break
            try:
                line = raw.decode("utf-8")
            except Exception:
                continue
            line = line.rstrip("\r\n")
            if line == "":
                event_type = "message"
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
                continue
            if line.startswith("data:"):
                data = line[len("data:"):].lstrip(" ")
                if data == "[DONE]":
                    return
                yield (event_type, data)
                event_type = "message"
                continue
    except GeneratorExit:
        try:
            response.close()
        except Exception:
            pass
        raise
    except Exception:
        try:
            response.close()
        except Exception:
            pass
        raise
    finally:
        if cancel_event is not None and cancel_event.is_set():
            try:
                response.close()
            except Exception:
                pass


def iter_ndjson_lines(response, cancel_event: threading.Event) -> Iterator[dict]:
    """Yield parsed JSON dicts, one per newline-delimited line."""
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                break
            raw = response.readline()
            if not raw:
                break
            try:
                line = raw.decode("utf-8")
            except Exception:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                _log.warning("ndjson: skipping malformed line (%d bytes)", len(raw))
                continue
            yield obj
    except GeneratorExit:
        try:
            response.close()
        except Exception:
            pass
        raise
    except Exception:
        try:
            response.close()
        except Exception:
            pass
        raise
    finally:
        if cancel_event is not None and cancel_event.is_set():
            try:
                response.close()
            except Exception:
                pass
