# Security Policy

## Reporting a vulnerability

If you find a security issue in sublime-llm, please email **<tony@1x0.net>** with the details rather than opening a public GitHub issue.

Helpful information to include:

- A description of the issue and its impact.
- Steps to reproduce, or a minimal proof of concept.
- The plugin version (`git rev-parse HEAD` from your install, or the release tag).
- Your Sublime Text build number, OS, and provider configuration if relevant.

I'll acknowledge receipt within a few days and will coordinate a fix and disclosure timeline with you.

## Supported versions

Only the latest tagged release is supported with security fixes. Patches go out as a new release on the `main` branch.

## Scope

In scope:

- Code in this repository (`plugin.py`, `sublime_llm/`, the shipped `.sublime-*` files).
- The secret-resolution chain (`sublime_llm.secrets`) and the redacting log filter (`sublime_llm.logging_setup`).
- The chat persistence path under `Packages/User/sublime-llm/chats/`.
- Any of the bundled provider implementations under `sublime_llm/providers/`.

Out of scope:

- Vulnerabilities in upstream LLM providers (OpenAI, Anthropic, Ollama, etc.) — please report those to the relevant provider.
- Vulnerabilities in Sublime Text itself.
- Issues that require an attacker to already have write access to your Sublime `Packages/User/` directory or to your shell environment.

## What sublime-llm does to protect you

- API keys are never logged. Every handler attached to the plugin's logger has a redacting filter applied that masks both registered keys and common API-key shapes (`sk-...`, `sk-ant-...`, `Bearer ...`).
- The external config file (`~/.config/sublime-llm/config.json`) is created with `0600` permissions on the file and `0700` on its parent directory. The plugin warns when reading external config or legacy key-only files with looser permissions.
- Storing keys in `LLM.sublime-settings` is opt-in (`allow_secrets_in_settings_file`) and off by default; stray keys in that file are ignored at runtime with a warning.
- The plugin makes HTTP requests only to the configured provider's base URL. There is no telemetry.

See the [Security section of the README](README.md#security) for the user-facing guidance these protections enable.
