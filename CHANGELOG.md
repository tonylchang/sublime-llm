# Changelog

All notable changes to LLM (formerly `sublime-llm`) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.2] - 2026-06-06

### Changed
- Renamed the package to **LLM** (was `sublime-llm`) for Package Control. Command palette and menu captions are now prefixed `LLM:`, and the settings command is `Preferences: LLM Settings`.

### Fixed
- The chat-view syntax and the settings command now resolve under the `LLM` package directory (paths were hardcoded to `sublime-llm`).
- Renamed the settings file to `LLM.sublime-settings` (was `sublime-llm.sublime-settings`) so it matches the package name; Package Control flagged the old name because it was neither the package name nor a shipped syntax. User overrides now live in `<Packages>/User/LLM.sublime-settings`.

### Packaging
- The plugin uses relative imports and no longer manipulates `sys.path` in `plugin.py`.

## [1.0.1] - 2026-05-31

### Added
- `sublime-llm: Settings` command (command palette and `Preferences -> Package Settings -> sublime-llm -> Settings`) opens the default and user settings side by side.

### Changed
- `Send Selection to Chat` no longer ships a default key binding. The previous `Ctrl+Shift+L` / `Cmd+Shift+L` binding overrode Sublime's built-in "Split selection into lines". Use the command palette or right-click menu, or add your own binding (see README and the commented example in `Default.sublime-keymap`).
- The right-click `sublime-llm: Send Selection to Chat` entry is now hidden unless the selection is non-empty.

### Packaging
- Added `.gitattributes` so tests and docs are excluded from the installed package.

## [1.0.0] - 2026-05-10

Initial release.

### Added
- External provider config at `~/.config/sublime-llm/config.json`, with `active_provider` and provider-level settings under `providers.<name>`.
- Backward-compatible reading of the legacy key-only `secrets.json` file.
- Sublime Text 4 chat view with Markdown turn headers (`### User` / `### Assistant`).
- Ollama provider with NDJSON streaming and model discovery.
- OpenAI, Anthropic, OpenRouter, DeepSeek providers with SSE streaming.
- Generic OpenAI-compatible custom provider for LM Studio, llama.cpp, vLLM, Groq, Together, Fireworks, LiteLLM.
- Provider abstraction with normalized message format and uniform error mapping.
- Selected text -> chat workflow (right-click "sublime-llm: Send Selection to Chat" or `Ctrl+Shift+L` / `Cmd+Shift+L`).
- Per-window chat state with cancel-event tracking.
- Per-project chat persistence under `Packages/User/sublime-llm/chats/<slug>.md`.
- Cancellation via `Esc` (during stream) or `sublime-llm: Cancel` command palette entry.
- Settings reader with placeholder detection and live-reload via `add_on_change`.
- External config resolver chain: env vars -> `~/.config/sublime-llm/config.json` (0o600) -> legacy `secrets.json` -> settings file (gated off by default).
- Secret-redacting logging filter applied to every handler in the plugin's logger namespace.
- Token batching for streaming (50 ms / 64-char threshold) with conditional auto-scroll.
- Custom `ChatMarkdown.sublime-syntax` extending built-in Markdown with turn-header scopes.
- `sublime-llm: Open Chat`, `sublime-llm: Submit Message`, `sublime-llm: Cancel`, `sublime-llm: Clear Chat History`, `sublime-llm: Choose Model`, `sublime-llm: Choose Provider`, `sublime-llm: Show Status`, `sublime-llm: Show External Config Status` window commands.
- README with full settings reference and security guidance.

### Fixed
- Picker constructed every non-Ollama provider with the global `base_url` setting (defaulting to the Ollama URL), so `sublime-llm: Choose Model` requested models from the wrong endpoint. Now mirrors the registry's per-provider URL lookup.
- `sublime-llm: Choose Model` reported a generic "no models available" message for any failure mode. Now distinguishes missing API key, unreachable endpoint, misconfigured endpoint, and genuinely-empty results.
- Anthropic 400 errors swallowed the API's actual rejection reason; now surfaces the upstream error message.
- Anthropic auto-retries once with `temperature` (or `top_p` / `top_k`) stripped when the model rejects the parameter as deprecated, so newer Claude models work without manual configuration.
- Sublime restored the chat view tab from the workspace but the in-memory registry was empty, so the next message opened a second chat tab. Now scans the restored window for the chat-view marker setting and re-adopts the existing tab.
- Markdown blockquote rendering produced an empty bar in `Render Last Response` because Sublime's minihtml does not support `<blockquote>`. Now renders as a styled `<div class="quote">`.

### Security
- API keys never logged thanks to `SecretRedactFilter`.
- Recommended storage path is the external config file outside the usual dotfiles scope.
- Placeholder values (`REPLACE_ME`, `YOUR_KEY_HERE`, etc.) are rejected at load.
- Loose-permission warning on POSIX when the external config or legacy key-only file is more permissive than 0o600.

### Changed
- Command palette caption now refers to external config status instead of secret storage status.

[Unreleased]: https://github.com/tonylchang/sublime-llm/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/tonylchang/sublime-llm/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/tonylchang/sublime-llm/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/tonylchang/sublime-llm/releases/tag/v1.0.0
