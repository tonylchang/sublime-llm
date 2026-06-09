# Installation

This guide covers installing LLM into Sublime Text 4 on macOS, Linux, and Windows. For configuration and usage after install, see the [README](README.md).

## Requirements

- **Sublime Text 4, build 4050 or newer.** The plugin uses the Python 3.8 plugin host introduced in build 4050. Check your build with `Help -> About Sublime Text` (macOS: `Sublime Text -> About Sublime Text`).
- **Network access** if you plan to use a hosted provider (OpenAI, Anthropic, OpenRouter, DeepSeek, or a custom OpenAI-compatible endpoint). No network is required for Ollama.
- **Optional: [Ollama](https://ollama.com)** if you want to run models locally.

## Locate your Packages directory

The Sublime `Packages` directory is where third-party packages live. From inside Sublime, run `Preferences -> Browse Packages...` to open it. The default paths are:

- **macOS:** `~/Library/Application Support/Sublime Text/Packages/`
- **Linux:** `~/.config/sublime-text/Packages/`
- **Windows:** `%APPDATA%\Sublime Text\Packages\`

These paths are referenced as `<Packages>` below.

### Option A — clone directly into the Packages directory

```sh
cd '<Packages>'
git clone https://github.com/tonylchang/sublime-llm.git
```

The directory name **must** be `LLM` (not `LLM-main` or similar) — the plugin's syntax file references `Packages/LLM/ChatMarkdown.sublime-syntax`.

### Option B — clone elsewhere and symlink

Useful if you want the working copy somewhere outside Sublime's Packages directory (for example, alongside your other repos).

```sh
git clone https://github.com/tonylchang/sublime-llm.git ~/git/sublime-llm
ln -s ~/git/sublime-llm '<Packages>/LLM'
```

On Windows, use `mklink /D` from an elevated `cmd.exe`:

```cmd
mklink /D "%APPDATA%\Sublime Text\Packages\LLM" "C:\path\to\your\clone"
```

### Restart Sublime Text

After cloning or symlinking, restart Sublime Text so the plugin host loads the package.

## Verify the install

1. Open the command palette (`Ctrl+Shift+P` / `Cmd+Shift+P`) and type `LLM:`. You should see entries like `LLM: Open Chat`, `LLM: Choose Provider`, `LLM: Show Status`.
2. Run `LLM: Open Chat`. A new tab named **LLM Chat** should appear with a `<user> ` prompt at the bottom.
3. Run `LLM: Show Status`. The status panel should report the active provider, model, base URL, and a list of available models.

If any of these fail, open the Sublime console with ``Ctrl+` `` and look for `sublime-llm` log lines.

## First-time setup

### Path A — local with Ollama (no API key)

1. Install [Ollama](https://ollama.com) and start the server: `ollama serve` (or use the desktop app).
2. Pull the default model: `ollama pull llama3.2`.
3. Type a message in the chat view's input region and press `Ctrl+Enter` (macOS: `Cmd+Enter`) to send.

No LLM-specific configuration is required for this default path. Run `LLM: Choose Model` only if you want to switch to a different pulled model.

### Path B — hosted provider (OpenAI, Anthropic, OpenRouter, DeepSeek, custom)

1. Open `Preferences -> Package Settings -> LLM -> Settings` and set `provider` and `model`. Example:

   ```json
   {
     "provider": "anthropic",
     "model": "claude-opus-4-7"
   }
   ```

2. Provide an API key. The recommended path is the external config file at `~/.config/sublime-llm/config.json` (macOS/Linux) or `%APPDATA%\sublime-llm\config.json` (Windows). A template is shipped at [`config.example.json`](config.example.json) at the repo root — copy it into place and edit:

   ```sh
   mkdir -p ~/.config/sublime-llm
   cp '<Packages>/LLM/config.example.json' ~/.config/sublime-llm/config.json
   chmod 600 ~/.config/sublime-llm/config.json
   $EDITOR ~/.config/sublime-llm/config.json
   ```

   The shape stores provider-level settings under `providers.<name>`:

   ```json
   {
     "active_provider": "anthropic",
     "providers": {
       "anthropic": {
         "api_key": "sk-ant-...",
         "model": "claude-opus-4-7"
       }
     }
   }
   ```

   Any value containing `REPLACE_ME` is treated as a placeholder and ignored, so an unedited copy is harmless. The plugin enforces `0600` permissions on this file when it writes it. Existing legacy key-only `secrets.json` installs are still readable for backward compatibility. See the [README](README.md#external-provider-config-and-api-keys) for the full key-resolution chain.

3. Run `LLM: Show External Config Status` to confirm the key was picked up.
4. Send a test message via `LLM: Open Chat`.

## Updating

### Package Control

Updates land automatically. Run `Package Control: Upgrade Package` to pull the newest tagged release immediately.

### Manual install

Pull from the clone:

```sh
cd '<Packages>/LLM'   # or wherever your clone lives
git pull
```

Sublime auto-reloads the plugin on file change.

## Uninstall

### Package Control

Run `Package Control: Remove Package` and pick `LLM`.

### Manual install

Remove the directory or symlink from the Packages directory:

```sh
rm -rf '<Packages>/LLM'   # or `unlink` if it's a symlink
```

Optional cleanup of user state:

- Per-project chat transcripts: `<Packages>/User/sublime-llm/chats/`
- User overrides: `<Packages>/User/LLM.sublime-settings`
- External config file: `~/.config/sublime-llm/config.json` (macOS/Linux) or `%APPDATA%\sublime-llm\config.json` (Windows)
- Legacy key-only file: existing `secrets.json` installs are still readable for backward compatibility; new installs should use `config.json`

## Troubleshooting

**Commands don't appear in the palette.** Confirm the directory under `<Packages>` is named exactly `LLM` and that you restarted Sublime after install.

**`failed to assign ChatMarkdown syntax` in the console.** Same root cause — the syntax file is loaded by the path `Packages/LLM/ChatMarkdown.sublime-syntax`. Rename the directory to `LLM`.

**`Ollama is not running`.** Start the Ollama server (`ollama serve` or the desktop app) and confirm it's reachable at `http://localhost:11434`. The plugin also honors `OLLAMA_HOST` if your server is on another port.

**`MISSING_CREDENTIAL` or `BAD_CREDENTIAL` for a hosted provider.** Run `LLM: Show External Config Status` to see where each key was resolved from. On macOS, GUI apps launched from the Dock or Spotlight don't inherit your shell's environment variables — use the external config file instead, or launch Sublime from a terminal with `subl`.

For other issues, see the [Troubleshooting section of the README](README.md#troubleshooting).
