"""Minimal markdown -> minihtml converter for rendering chat responses."""
import html as _html
import re
from typing import List

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_FENCE_OPEN_RE = re.compile(r"^```\s*(\w*)\s*$")
_FENCE_CLOSE_RE = re.compile(r"^```\s*$")
_HRULE_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
_OL_RE = re.compile(r"^(\d+)\.\s+(.*)$")
_UL_RE = re.compile(r"^[-*+]\s+(.*)$")
_BLOCKQUOTE_RE = re.compile(r"^>\s?(.*)$")

_INLINE_CODE_RE = re.compile(r"`([^`\n]+?)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _render_inline(text: str) -> str:
    code_holes: List[str] = []

    def stash(m):
        code_holes.append("<code>" + _html.escape(m.group(1)) + "</code>")
        return "\x00{0}\x00".format(len(code_holes) - 1)

    stage1 = _INLINE_CODE_RE.sub(stash, text)
    escaped = _html.escape(stage1)
    escaped = _BOLD_RE.sub(r"<b>\1</b>", escaped)
    escaped = _STRIKE_RE.sub(r"<s>\1</s>", escaped)
    escaped = _ITALIC_RE.sub(r"<i>\1</i>", escaped)

    def link_repl(m):
        text_part = m.group(1)
        url = m.group(2)
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("subl:")):
            return m.group(0)
        return '<a href="{0}">{1}</a>'.format(_html.escape(url, quote=True), text_part)

    escaped = _LINK_RE.sub(link_repl, escaped)

    def restore(m):
        return code_holes[int(m.group(1))]

    return re.sub(r"\x00(\d+)\x00", restore, escaped)


def md_to_html(text: str) -> str:
    lines = (text or "").splitlines()
    out: List[str] = []
    list_stack: List[str] = []  # "ul" or "ol"
    in_code = False
    code_lang = ""
    code_buf: List[str] = []
    paragraph_buf: List[str] = []
    in_quote = False

    def flush_paragraph():
        if paragraph_buf:
            joined = " ".join(paragraph_buf).strip()
            if joined:
                out.append("<p>" + _render_inline(joined) + "</p>")
            paragraph_buf.clear()

    def close_lists():
        while list_stack:
            tag = list_stack.pop()
            out.append("</{0}>".format(tag))

    def close_quote():
        nonlocal in_quote
        if in_quote:
            out.append("</div>")
            in_quote = False

    for raw in lines:
        line = raw

        if in_code:
            if _FENCE_CLOSE_RE.match(line):
                code_text = "\n".join(code_buf)
                out.append(
                    '<div class="codeblock"><pre><code>{0}</code></pre></div>'.format(
                        _html.escape(code_text)
                    )
                )
                code_buf = []
                in_code = False
                code_lang = ""
            else:
                code_buf.append(line)
            continue

        m = _FENCE_OPEN_RE.match(line)
        if m:
            flush_paragraph()
            close_lists()
            close_quote()
            in_code = True
            code_lang = m.group(1)
            continue

        if not line.strip():
            flush_paragraph()
            close_lists()
            close_quote()
            continue

        if _HRULE_RE.match(line):
            flush_paragraph()
            close_lists()
            close_quote()
            out.append("<hr/>")
            continue

        m = _HEADER_RE.match(line)
        if m:
            flush_paragraph()
            close_lists()
            close_quote()
            level = min(len(m.group(1)), 6)
            out.append("<h{0}>{1}</h{0}>".format(level, _render_inline(m.group(2))))
            continue

        m = _BLOCKQUOTE_RE.match(line)
        if m:
            flush_paragraph()
            close_lists()
            if not in_quote:
                out.append('<div class="quote">')
                in_quote = True
            out.append("<p>" + _render_inline(m.group(1)) + "</p>")
            continue
        else:
            close_quote()

        m = _UL_RE.match(line)
        if m:
            flush_paragraph()
            if not list_stack or list_stack[-1] != "ul":
                close_lists()
                out.append("<ul>")
                list_stack.append("ul")
            out.append("<li>" + _render_inline(m.group(1)) + "</li>")
            continue

        m = _OL_RE.match(line)
        if m:
            flush_paragraph()
            if not list_stack or list_stack[-1] != "ol":
                close_lists()
                out.append("<ol>")
                list_stack.append("ol")
            out.append("<li>" + _render_inline(m.group(2)) + "</li>")
            continue

        # Plain paragraph line.
        close_lists()
        paragraph_buf.append(line.strip())

    if in_code and code_buf:
        out.append(
            '<div class="codeblock"><pre><code>{0}</code></pre></div>'.format(
                _html.escape("\n".join(code_buf))
            )
        )
    flush_paragraph()
    close_lists()
    close_quote()

    return "\n".join(out)


_BASE_CSS = """
html, body { padding: 8px 14px; font-size: 13px; line-height: 1.5; }
h1 { font-size: 1.5em; margin-top: 0.8em; margin-bottom: 0.3em; }
h2 { font-size: 1.3em; margin-top: 0.8em; margin-bottom: 0.3em; }
h3 { font-size: 1.15em; margin-top: 0.7em; margin-bottom: 0.3em; }
h4, h5, h6 { font-size: 1em; margin-top: 0.6em; margin-bottom: 0.2em; font-weight: bold; }
p { margin: 0.4em 0; }
ul, ol { margin: 0.3em 0; padding-left: 1.4em; }
li { margin: 0.1em 0; }
code { background-color: color(var(--background) blend(var(--foreground) 90%)); padding: 1px 4px; border-radius: 3px; font-family: monospace; }
.codeblock { background-color: color(var(--background) blend(var(--foreground) 92%)); padding: 8px 10px; margin: 0.5em 0; border-radius: 4px; }
.codeblock pre, .codeblock code { background-color: transparent; padding: 0; border-radius: 0; }
.quote { border-left: 3px solid color(var(--foreground) alpha(0.3)); padding-left: 10px; margin: 0.5em 0; color: color(var(--foreground) alpha(0.85)); }
.quote p { margin: 0.2em 0; }
a { color: var(--bluish); text-decoration: underline; }
hr { border: 0; border-top: 1px solid color(var(--foreground) alpha(0.25)); margin: 0.8em 0; }
s { color: color(var(--foreground) alpha(0.6)); }
"""


def wrap_minihtml(body_html: str, title: str = "") -> str:
    head = "<style>{0}</style>".format(_BASE_CSS)
    return "<html><body>{0}{1}</body></html>".format(head, body_html)
