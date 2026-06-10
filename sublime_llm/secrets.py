"""External config and secret resolver for sublime-llm."""
import json
import os
from typing import Optional, Set, Tuple

from .logging_setup import get_logger, register_secret
from .settings import get_settings, is_placeholder

_CONFIG_FILENAME = "config.json"
_SECRETS_FILENAME = "secrets.json"  # Legacy key-only file name.
_session_warned: Set[str] = set()


def _is_posix() -> bool:
    return os.name != "nt"


def _config_dir() -> str:
    if _is_posix():
        return os.path.expanduser("~/.config/sublime-llm")
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "sublime-llm")


def get_external_config_file_path() -> str:
    return os.path.join(_config_dir(), _CONFIG_FILENAME)


def get_secrets_file_path() -> str:
    """Return the legacy key-only secrets path kept for backward compatibility."""
    return os.path.join(_config_dir(), _SECRETS_FILENAME)


def _warn_loose_permissions(path: str) -> None:
    if not _is_posix():
        return
    try:
        st = os.stat(path)
        if st.st_mode & 0o077:
            get_logger().warning(
                "external config file at %s has loose permissions; recommend chmod 600",
                path,
            )
    except OSError:
        pass


def _read_json_file(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    _warn_loose_permissions(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as err:
        _warn_once("config-read:" + path, "cannot read %s: %s; ignoring it", path, err)
        return {}
    except json.JSONDecodeError as err:
        _warn_once(
            "config-parse:" + path, "%s is not valid JSON (%s); ignoring it", path, err
        )
        return {}
    if isinstance(data, dict):
        return data
    _warn_once(
        "config-shape:" + path, "%s must contain a JSON object; ignoring it", path
    )
    return {}


def _read_external_config() -> dict:
    return _read_json_file(get_external_config_file_path())


def _read_secrets_file() -> dict:
    """Read the legacy top-level provider->key secrets file."""
    return _read_json_file(get_secrets_file_path())


def get_external_config() -> dict:
    return _read_external_config()


def get_provider_config(provider_name: str) -> dict:
    data = _read_external_config()
    providers = data.get("providers")
    if not isinstance(providers, dict):
        return {}
    cfg = providers.get(provider_name.lower())
    if isinstance(cfg, dict):
        return dict(cfg)
    return {}


def get_active_provider_from_external_config() -> Optional[str]:
    data = _read_external_config()
    name = data.get("active_provider") or data.get("provider")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _warn_once(token: str, message: str, *args) -> None:
    if token in _session_warned:
        return
    _session_warned.add(token)
    get_logger().warning(message, *args)


def _key_from_external_provider_config(provider_name: str) -> Optional[str]:
    cfg = get_provider_config(provider_name)
    for key_name in ("api_key", "key", "token"):
        value = cfg.get(key_name)
        if value and not is_placeholder(value):
            return value
    return None


def resolve_key(provider_name: str) -> Tuple[Optional[str], str]:
    env_name = "{0}_API_KEY".format(provider_name.upper())
    env_val = os.environ.get(env_name)
    if env_val and not is_placeholder(env_val):
        register_secret(env_val)
        return env_val, "env"

    config_val = _key_from_external_provider_config(provider_name)
    if config_val:
        register_secret(config_val)
        return config_val, "external_config"

    legacy_data = _read_secrets_file()
    legacy_val = legacy_data.get(provider_name.lower())
    if legacy_val and not is_placeholder(legacy_val):
        register_secret(legacy_val)
        return legacy_val, "file"

    settings = get_settings()
    settings_key = "{0}_api_key".format(provider_name.lower())
    settings_val = settings.get(settings_key)
    allow = bool(settings.get("allow_secrets_in_settings_file", False))
    if settings_val and not is_placeholder(settings_val):
        if allow:
            _warn_once(
                "settings-storage-insecure",
                "storing API keys in the settings file is insecure; prefer env var or external config file",
            )
            register_secret(settings_val)
            return settings_val, "settings"
        _warn_once(
            "settings-ignored:" + provider_name.lower(),
            "ignoring %s API key from settings file because allow_secrets_in_settings_file is false",
            provider_name.lower(),
        )

    return None, "missing"


def get_resolution_source(provider_name: str) -> str:
    _, source = resolve_key(provider_name)
    return source


def _ensure_config_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if _is_posix():
        os.makedirs(parent, mode=0o700, exist_ok=True)
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass
    else:
        os.makedirs(parent, exist_ok=True)


def _write_json_secure(path: str, data: dict) -> None:
    _ensure_config_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    if _is_posix():
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def store_key_in_file(provider_name: str, key: str) -> None:
    """Store a provider API key in the external config file.

    New writes use config.json under providers.<name>.api_key. The old
    secrets.json path remains readable for existing installs.
    """
    path = get_external_config_file_path()
    data = _read_external_config()
    providers = data.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    provider_cfg = providers.get(provider_name.lower())
    if not isinstance(provider_cfg, dict):
        provider_cfg = {}
    provider_cfg["api_key"] = key
    providers[provider_name.lower()] = provider_cfg
    data["providers"] = providers
    _write_json_secure(path, data)
