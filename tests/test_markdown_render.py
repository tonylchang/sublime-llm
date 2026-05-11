"""Tests for the markdown-to-minihtml renderer."""
import unittest

from sublime_llm.markdown_render import md_to_html, wrap_minihtml


class MarkdownRenderTests(unittest.TestCase):
    def test_paragraph(self):
        html = md_to_html("hello world")
        self.assertIn("<p>hello world</p>", html)

    def test_header(self):
        html = md_to_html("# Title\n## Sub")
        self.assertIn("<h1>Title</h1>", html)
        self.assertIn("<h2>Sub</h2>", html)

    def test_bold_italic(self):
        html = md_to_html("**bold** and *italic*")
        self.assertIn("<b>bold</b>", html)
        self.assertIn("<i>italic</i>", html)

    def test_inline_code(self):
        html = md_to_html("use `print()` to output")
        self.assertIn("<code>print()</code>", html)

    def test_code_block_with_lang(self):
        text = "```python\ndef hi():\n    pass\n```"
        html = md_to_html(text)
        self.assertIn("<div class=\"codeblock\">", html)
        self.assertIn("def hi", html)
        self.assertIn("pass", html)

    def test_unordered_list(self):
        text = "- one\n- two\n- three"
        html = md_to_html(text)
        self.assertIn("<ul>", html)
        self.assertEqual(html.count("<li>"), 3)

    def test_ordered_list(self):
        text = "1. a\n2. b\n3. c"
        html = md_to_html(text)
        self.assertIn("<ol>", html)
        self.assertEqual(html.count("<li>"), 3)

    def test_link(self):
        html = md_to_html("see [docs](https://example.com)")
        self.assertIn('href="https://example.com"', html)
        self.assertIn(">docs</a>", html)

    def test_link_with_dangerous_scheme_left_as_text(self):
        # We only allow http(s) and subl: schemes; everything else stays as
        # plain markdown text rather than producing an <a href="...">.
        html = md_to_html("click [here](javascript:alert(1))")
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn("<a ", html)

    def test_blockquote(self):
        # Use a <div class="quote"> wrapper rather than <blockquote>, which
        # Sublime's minihtml does not support.
        html = md_to_html("> quoted text")
        self.assertIn('<div class="quote">', html)
        self.assertIn("quoted text", html)
        self.assertNotIn("<blockquote", html)

    def test_hr(self):
        self.assertIn("<hr/>", md_to_html("---"))
        self.assertIn("<hr/>", md_to_html("***"))

    def test_html_in_input_is_escaped(self):
        html = md_to_html("<script>alert('x')</script>")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_wrap_minihtml(self):
        wrapped = wrap_minihtml("<p>hi</p>")
        self.assertTrue(wrapped.startswith("<html><body>"))
        self.assertIn("<style>", wrapped)
        self.assertIn("<p>hi</p>", wrapped)


if __name__ == "__main__":
    unittest.main()
