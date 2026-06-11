"""Tests for sublime_llm.persistence."""
import hashlib
import os
import tempfile
from unittest import mock

from unittesting import DeferrableTestCase

from LLM.sublime_llm import persistence


class FakeWindow:
    def __init__(self, project=None, win_id=12345):
        self._project = project
        self._win_id = win_id

    def project_file_name(self):
        return self._project

    def id(self):
        return self._win_id


class PersistenceTests(DeferrableTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._prev_root = persistence._TEST_STORAGE_ROOT
        persistence._TEST_STORAGE_ROOT = self._tmp.name

    def tearDown(self) -> None:
        persistence._TEST_STORAGE_ROOT = self._prev_root

    def test_save_writes_file_with_content(self) -> None:
        window = FakeWindow(project="/proj/foo.sublime-project")
        ok = persistence.save_chat(window, "hello world")
        self.assertTrue(ok)
        path = persistence.get_chat_path(window)
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "hello world")

    def test_save_returns_false_on_empty_text(self) -> None:
        window = FakeWindow(project="/proj/foo.sublime-project")
        self.assertFalse(persistence.save_chat(window, ""))
        self.assertFalse(persistence.save_chat(window, "   \n\t"))
        path = persistence.get_chat_path(window)
        self.assertFalse(os.path.exists(path))

    def test_load_returns_none_when_no_file(self) -> None:
        window = FakeWindow(project="/proj/missing.sublime-project")
        self.assertIsNone(persistence.load_chat(window))

    def test_load_returns_content_for_existing_file(self) -> None:
        window = FakeWindow(project="/proj/foo.sublime-project")
        path = persistence.get_chat_path(window)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("### User\nhi\n")
        self.assertEqual(persistence.load_chat(window), "### User\nhi\n")

    def test_save_then_load_round_trip(self) -> None:
        window = FakeWindow(project="/proj/round.sublime-project")
        body = "### User\nhello\n\n### Assistant\nworld\n"
        self.assertTrue(persistence.save_chat(window, body))
        self.assertEqual(persistence.load_chat(window), body)

    def test_two_projects_get_different_files(self) -> None:
        w_a = FakeWindow(project="/proj/a.sublime-project")
        w_b = FakeWindow(project="/proj/b.sublime-project")
        path_a = persistence.get_chat_path(w_a)
        path_b = persistence.get_chat_path(w_b)
        self.assertNotEqual(path_a, path_b)
        persistence.save_chat(w_a, "AAA")
        persistence.save_chat(w_b, "BBB")
        self.assertEqual(persistence.load_chat(w_a), "AAA")
        self.assertEqual(persistence.load_chat(w_b), "BBB")

    def test_two_windows_without_projects_get_different_files(self) -> None:
        w1 = FakeWindow(project=None, win_id=111)
        w2 = FakeWindow(project=None, win_id=222)
        path1 = persistence.get_chat_path(w1)
        path2 = persistence.get_chat_path(w2)
        self.assertNotEqual(path1, path2)
        self.assertIn("window-111", path1)
        self.assertIn("window-222", path2)

    def test_clear_removes_file(self) -> None:
        window = FakeWindow(project="/proj/clear.sublime-project")
        persistence.save_chat(window, "content")
        path = persistence.get_chat_path(window)
        self.assertTrue(os.path.exists(path))
        self.assertTrue(persistence.clear_chat(window))
        self.assertFalse(os.path.exists(path))

    def test_clear_returns_false_when_no_file(self) -> None:
        window = FakeWindow(project="/proj/never.sublime-project")
        self.assertFalse(persistence.clear_chat(window))

    def test_atomic_write_preserves_existing_on_failure(self) -> None:
        window = FakeWindow(project="/proj/atomic.sublime-project")
        path = persistence.get_chat_path(window)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("ORIGINAL")

        real_replace = os.replace

        def boom(src, dst):
            raise OSError("simulated replace failure")

        with mock.patch.object(persistence.os, "replace", side_effect=boom):
            ok = persistence.save_chat(window, "NEW CONTENT")
        self.assertFalse(ok)
        # Original is preserved.
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "ORIGINAL")
        # Tmp file cleaned up.
        self.assertFalse(os.path.exists(path + ".tmp"))
        # And after the patch is gone, real os.replace still works.
        self.assertIs(os.replace, real_replace)

    def test_slug_derivation_is_deterministic(self) -> None:
        project = "/Users/me/work/myproj.sublime-project"
        window = FakeWindow(project=project)
        path = persistence.get_chat_path(window)
        filename = os.path.basename(path)
        # Format: {basename}.{hashpart}.md
        self.assertTrue(filename.startswith("myproj."))
        self.assertTrue(filename.endswith(".md"))
        # Hashpart is 12 hex chars.
        middle = filename[len("myproj."):-len(".md")]
        self.assertEqual(len(middle), 12)
        expected_hash = hashlib.sha1(project.encode()).hexdigest()[:12]
        self.assertEqual(middle, expected_hash)
        # Re-computing must match (deterministic).
        again = persistence.get_chat_path(FakeWindow(project=project))
        self.assertEqual(path, again)
