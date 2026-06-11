"""Tests for chat_parser."""

from unittesting import DeferrableTestCase

from LLM.sublime_llm.chat_parser import parse_messages


class ParseMessagesTests(DeferrableTestCase):
    def test_basic_three_turn(self):
        text = "<user>\nhello\n\n<assistant>\nhi\n\n<user>\ngoodbye"
        msgs = parse_messages(text, "")
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0].role, "user")
        self.assertEqual(msgs[0].content, "hello")
        self.assertEqual(msgs[1].role, "assistant")
        self.assertEqual(msgs[1].content, "hi")
        self.assertEqual(msgs[2].role, "user")
        self.assertEqual(msgs[2].content, "goodbye")

    def test_system_prompt_prepended_when_buffer_has_no_system(self):
        text = "<user>\nhello"
        msgs = parse_messages(text, "You are a helpful assistant.")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "system")
        self.assertEqual(msgs[0].content, "You are a helpful assistant.")
        self.assertEqual(msgs[1].role, "user")

    def test_system_prompt_not_prepended_when_buffer_starts_with_system(self):
        text = "<system>\nbuilt-in system\n\n<user>\nhello"
        msgs = parse_messages(text, "settings system")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "system")
        self.assertEqual(msgs[0].content, "built-in system")
        self.assertEqual(msgs[1].role, "user")
        self.assertEqual(msgs[1].content, "hello")

    def test_empty_segments_skipped(self):
        text = "<user>\n\n\n<assistant>\nreal\n\n<user>\nq"
        msgs = parse_messages(text, "")
        # The empty first user segment is skipped.
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "assistant")
        self.assertEqual(msgs[0].content, "real")
        self.assertEqual(msgs[1].role, "user")
        self.assertEqual(msgs[1].content, "q")

    def test_empty_buffer_with_system_prompt(self):
        msgs = parse_messages("", "sys")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].role, "system")

    def test_empty_buffer_no_system_prompt(self):
        msgs = parse_messages("", "")
        self.assertEqual(msgs, [])

    def test_system_prompt_empty_no_prepend(self):
        text = "<user>\nhi"
        msgs = parse_messages(text, "")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].role, "user")

    def test_preserves_order(self):
        text = "<system>\nsys\n\n<user>\nu1\n\n<assistant>\na1\n\n<user>\nu2"
        msgs = parse_messages(text, "")
        roles = [m.role for m in msgs]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])

    def test_legacy_markdown_markers_still_parse(self):
        # Older chats saved with the markdown-header format must still load.
        text = "### User\nhello\n\n### Assistant\nhi"
        msgs = parse_messages(text, "")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "user")
        self.assertEqual(msgs[1].role, "assistant")

    def test_same_line_irc_format(self):
        # The current format puts content on the same line as the marker.
        text = "<user> what is 2+2?\n<assistant> 2+2 equals 4.\n<user> "
        msgs = parse_messages(text, "")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "user")
        self.assertEqual(msgs[0].content, "what is 2+2?")
        self.assertEqual(msgs[1].role, "assistant")
        self.assertEqual(msgs[1].content, "2+2 equals 4.")
        # Trailing empty "<user> " is dropped (no body).

    def test_markdown_header_inside_body_does_not_split_turn(self):
        # An assistant response that contains "### Heading" markdown should
        # parse as one assistant turn, not be split at the heading.
        text = (
            "<user> question\n"
            "<assistant> Sure!\n"
            "### A section heading\n"
            "More content here.\n"
        )
        msgs = parse_messages(text, "")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[1].role, "assistant")
        self.assertIn("### A section heading", msgs[1].content)
        self.assertIn("More content here.", msgs[1].content)

    def test_same_line_multi_line_body(self):
        text = (
            "<user> show me a function\n"
            "<assistant> Here is one:\n"
            "```python\n"
            "def hi():\n"
            "    print('hi')\n"
            "```\n"
        )
        msgs = parse_messages(text, "")
        self.assertEqual(len(msgs), 2)
        self.assertIn("def hi", msgs[1].content)

    def test_mixed_markers_parse(self):
        # If a chat was migrated mid-conversation, both styles must coexist.
        text = "### User\nold question\n\n<assistant>\nnew answer\n\n<user>\nfollow up"
        msgs = parse_messages(text, "")
        self.assertEqual([m.role for m in msgs], ["user", "assistant", "user"])
        self.assertEqual(msgs[0].content, "old question")
        self.assertEqual(msgs[1].content, "new answer")
        self.assertEqual(msgs[2].content, "follow up")
