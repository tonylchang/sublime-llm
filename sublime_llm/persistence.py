"""Per-project chat persistence to disk."""
import hashlib
import os
import re
from typing import Optional

try:
    import sublime  # type: ignore
except ImportError:
    sublime = None  # type: ignore

from sublime_llm.logging_setup import get_logger

# Tests can override this to point at a tempdir.
_TEST_STORAGE_ROOT: Optional[str] = None


def _storage_root() -> Optional[str]:
    if _TEST_STORAGE_ROOT is not None:
        return _TEST_STORAGE_ROOT
    if sublime is None:
        return None
    try:
        packages = sublime.packages_path()
    except Exception:
        return None
    return os.path.join(packages, "User", "sublime-llm", "chats")


def _slug_for_project(project_file_name: str) -> str:
    basename = os.path.splitext(os.path.basename(project_file_name))[0]
    basename = re.sub(r"[^A-Za-z0-9_-]", "_", basename)[:24]
    hashpart = hashlib.sha1(project_file_name.encode()).hexdigest()[:12]
    return "{0}.{1}".format(basename, hashpart)


def get_chat_path(window) -> Optional[str]:
    root = _storage_root()
    if root is None:
        return None
    if window is None:
        return None
    try:
        project = window.project_file_name()
    except Exception:
        project = None
    if project:
        slug = _slug_for_project(project)
    else:
        try:
            wid = window.id()
        except Exception:
            return None
        slug = "window-{0}".format(wid)
    return os.path.join(root, "{0}.md".format(slug))


def save_chat(window, text: str) -> bool:
    if not text or not text.strip():
        return False
    path = get_chat_path(window)
    if path is None:
        return False
    log = get_logger()
    parent = os.path.dirname(path)
    tmp = path + ".tmp"
    try:
        os.makedirs(parent, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        return True
    except OSError as err:
        log.warning("chat persistence: save failed for %s: %s", path, err)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def load_chat(window) -> Optional[str]:
    path = get_chat_path(window)
    if path is None:
        return None
    if not os.path.exists(path):
        return None
    log = get_logger()
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as err:
        log.warning("chat persistence: load failed for %s: %s", path, err)
        return None
    if not content:
        log.warning("chat persistence: %s is empty", path)
        return None
    return content


def clear_chat(window) -> bool:
    path = get_chat_path(window)
    if path is None:
        return False
    if not os.path.exists(path):
        return False
    log = get_logger()
    try:
        os.remove(path)
        return True
    except OSError as err:
        log.warning("chat persistence: clear failed for %s: %s", path, err)
        return False
