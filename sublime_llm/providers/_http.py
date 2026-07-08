"""Shared HTTP helpers for the urllib-based providers.

Centralizes the SSL context, base-URL normalization, and request plumbing that
every provider used to duplicate. Providers still reference ``urllib.request``
through their own module namespace for error handling, so existing tests that
patch ``providers.<name>.urllib.request.urlopen`` continue to intercept the
request made here (it patches the shared ``urllib.request`` module attribute).
"""
import ssl
import urllib.request
from typing import Optional

try:
    import certifi
    _CA_FILE = certifi.where()
except ImportError:
    _CA_FILE = None


def build_ssl_context() -> ssl.SSLContext:
    if _CA_FILE:
        return ssl.create_default_context(cafile=_CA_FILE)
    return ssl.create_default_context()


def normalize_base_url(raw: str, default: str, scheme: Optional[str] = None) -> str:
    """Trim a trailing slash; prepend ``scheme://`` when the URL lacks a scheme.

    Pass ``scheme=None`` to leave a scheme-less URL untouched (Anthropic), or
    ``"http"``/``"https"`` to default one in (Ollama/OpenAI-compatible).
    """
    if not raw:
        return default
    s = raw.strip().rstrip("/")
    if scheme and "://" not in s:
        s = "{0}://{1}".format(scheme, s)
    return s


def open_url(url, method="GET", headers=None, body=None, timeout=30):
    """Issue a urllib request using the shared (certifi-aware) SSL context."""
    req = urllib.request.Request(url, data=body, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=timeout, context=build_ssl_context())
