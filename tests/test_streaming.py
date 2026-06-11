"""Tests for sublime_llm.streaming."""
import io
import threading

from unittesting import DeferrableTestCase

from LLM.sublime_llm.streaming import iter_ndjson_lines, iter_sse_lines


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)
        self.closed = False

    def readline(self) -> bytes:
        if self.closed:
            return b""
        return self._buf.readline()

    def close(self) -> None:
        self.closed = True


class _ReadlineHook:
    """Wraps a FakeResponse; runs a callback before each readline call."""

    def __init__(self, inner: FakeResponse, before_readline) -> None:
        self._inner = inner
        self._before = before_readline
        self.closed = False

    def readline(self) -> bytes:
        self._before()
        return self._inner.readline()

    def close(self) -> None:
        self.closed = True
        self._inner.close()


class SSETests(DeferrableTestCase):
    def test_two_messages(self) -> None:
        data = b"data: chunk1\n\ndata: chunk2\n\n"
        resp = FakeResponse(data)
        ev = threading.Event()
        out = list(iter_sse_lines(resp, ev))
        self.assertEqual(out, [("message", "chunk1"), ("message", "chunk2")])

    def test_done_terminates(self) -> None:
        data = b"data: chunk1\n\ndata: [DONE]\n\ndata: ignored\n\n"
        resp = FakeResponse(data)
        ev = threading.Event()
        out = list(iter_sse_lines(resp, ev))
        self.assertEqual(out, [("message", "chunk1")])

    def test_named_event(self) -> None:
        data = b"event: foo\ndata: bar\n\n"
        resp = FakeResponse(data)
        ev = threading.Event()
        out = list(iter_sse_lines(resp, ev))
        self.assertEqual(out, [("foo", "bar")])

    def test_comment_skipped(self) -> None:
        data = b": keepalive\ndata: hello\n\n"
        resp = FakeResponse(data)
        ev = threading.Event()
        out = list(iter_sse_lines(resp, ev))
        self.assertEqual(out, [("message", "hello")])

    def test_cancellation_terminates_and_closes(self) -> None:
        data = b"data: a\n\ndata: b\n\ndata: c\n\n"
        inner = FakeResponse(data)
        ev = threading.Event()
        emitted = []

        wrapped = _ReadlineHook(inner, lambda: None)
        for evt in iter_sse_lines(wrapped, ev):
            emitted.append(evt)
            if len(emitted) == 1:
                ev.set()

        self.assertEqual(emitted, [("message", "a")])
        self.assertTrue(wrapped.closed)


class NDJSONTests(DeferrableTestCase):
    def test_three_lines(self) -> None:
        data = b'{"a":1}\n{"b":2}\n{"c":3}\n'
        resp = FakeResponse(data)
        ev = threading.Event()
        out = list(iter_ndjson_lines(resp, ev))
        self.assertEqual(out, [{"a": 1}, {"b": 2}, {"c": 3}])

    def test_empty_lines_skipped(self) -> None:
        data = b'\n{"a":1}\n\n{"b":2}\n'
        resp = FakeResponse(data)
        ev = threading.Event()
        out = list(iter_ndjson_lines(resp, ev))
        self.assertEqual(out, [{"a": 1}, {"b": 2}])

    def test_malformed_line_skipped(self) -> None:
        data = b'{"a":1}\nnot json\n{"b":2}\n'
        resp = FakeResponse(data)
        ev = threading.Event()
        out = list(iter_ndjson_lines(resp, ev))
        self.assertEqual(out, [{"a": 1}, {"b": 2}])

    def test_cancellation_terminates_and_closes(self) -> None:
        data = b'{"a":1}\n{"b":2}\n{"c":3}\n'
        inner = FakeResponse(data)
        ev = threading.Event()
        emitted = []

        wrapped = _ReadlineHook(inner, lambda: None)
        for obj in iter_ndjson_lines(wrapped, ev):
            emitted.append(obj)
            if len(emitted) == 1:
                ev.set()

        self.assertEqual(emitted, [{"a": 1}])
        self.assertTrue(wrapped.closed)
