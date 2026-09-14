# Forge — Local AI Assistant

> A local-first desktop AI assistant featuring tree-style conversation branching, context pruning, and instant extensibility with custom Python tools.

![Forge UI](docs/screenshot.png)

---

## What is Forge?

Forge is an autonomous desktop AI agent that executes directly on your machine instead of running solely in a cloud browser tab. It connects any OpenAI-compatible model (such as Google AI Studio, Ollama, OpenRouter, or LM Studio) to local system capabilities: file management, Playwright browser automation, script execution, clipboard access, and screen capture.

Unlike traditional linear chatbots, Forge organizes conversations into an interactive **decision tree**. You can explore multiple lines of thought, branch new directions from any past turn, and prune alternative context paths to dramatically reduce token consumption.

To extend the agent, simply drop a Python file into the tools directory. The agent automatically discovers it on the next run with zero registration or recompilation.

The UI is a native Tauri desktop app (Rust shell + lightweight frontend). The backend is a Python WebSocket sidecar running LangGraph, communicating locally over `ws://localhost:8765`.

---

## Architecture

![Architecture diagram](docs/architecture.svg)

*The frontend communicates with the Python backend exclusively over a local WebSocket — no HTTP server, no REST API, no external relay.*

---

## Features

### 🌿 Tree-Based Conversation & Context Pruning
- **Branching conversation tree** — conversations are stored as a tree graph of turns rather than a flat linear list.
- **Context pruning for token savings** — jumping to any branch or previous turn automatically prunes alternative branches and descendant context from the prompt sent to the LLM, keeping context lean and saving tokens.
- **Interactive n8n-style tree viewer** — floating, draggable, and resizable canvas with smooth pan-and-zoom (centered on mouse cursor), SVG cubic bezier curve connectors, and active path highlighting.
- **Branch labeling** — rename and label any branch point directly on the canvas to organize your exploration paths.
- **Context summarization** — one-click compression (`Summarise`) that compresses older turns into a summary node via the LLM while retaining the last two turns verbatim.
- **Rolling token telemetry** — real-time token counter per turn, with rolling 5-hour and 24-hour token usage metrics displayed in the header.

### 📂 Session Persistence & Management
- **In-app session browser** — browse, preview, resume, rename, and delete past conversation trees directly from the UI (`Previous Sessions`).
- **Zero-loss persistence** — every session is saved as a complete tree graph in `~/.forge/agent_sessions/session_<id>.json`.
- **Exportable text logs** — human-readable session transcripts including start time, end time, duration, and total token count saved to `.txt`.

### ⚙ Autonomous Tool-Using Agent
- **LangGraph reasoning loop** — iterative agent execution (up to 10 rounds) that calls real local tools based on dynamic model decisions.
- **Real-time streaming** — tokens stream live word-by-word; internal `<thought>` / `<thinking>` blocks are stripped before display.
- **Instant generation stop** — `Stop` button immediately halts generation or running tools via backend threading events.
- **Extensible custom tools** — drop any Python file decorated with `@tool` into `python_backend/tools/` or `~/.forge/tools/` to make it live instantly.
- **Browser automation** — Playwright-based browser tool that opens Chrome, searches, fills forms, navigates pages, downloads files, and extracts content.
- **Local Python execution** — executes scripts in a subprocess with timeouts and returns combined stdout/stderr.
- **File attachments** — native drag-and-drop file attachment via Tauri webview window events, plus direct absolute path attachment.

### 🛡 Security & Guardrails
- **Protected path firewall** — `is_path_protected` prevents reading, writing, or executing against `config.json`, `.env`, or the `python_backend/` codebase to prevent prompt injection attacks.
- **Destructive command detection** — inspects scripts for dangerous patterns (`os.remove`, `rm -rf`, `DROP TABLE`) and requires explicit confirmation.
- **Script audit logging** — every executed script is archived with a timestamp in `~/.agent_scripts/`.
- **Private credentials** — API keys and settings are stored locally in `~/.forge/config.json` and never sent anywhere except your chosen LLM endpoint.

### 💻 Cross-Platform & Modern UI
- **Dedicated Windows & Linux workflows** — specialized scripts for development setup and launcher in `windows/` and `linux/`.
- **`uv` & standard Python support** — automatically uses `uv` for lightning-fast virtual environment and package installation if available, with automatic fallback to standard Python 3.11+.
- **Zero-dependency inline SVG UI** — cross-platform vector icons that render crisply on Linux (WebKitGTK) without requiring extra system font downloads.
- **Dark & light themes** — built-in theme toggle with syntax highlighting for code blocks (`highlight.js`) and markdown support (`marked.js`) with one-click code copy buttons.
- **Graceful shutdown** — closing the window saves the active session and cleanly terminates the Python sidecar.

---

## Getting started

You can use Forge by installing the pre-built application or running it directly from source.

### Option A — Pre-built installer (recommended for end users)

1. Download the latest installer from the [Releases](../../releases) page:
   - **Windows:** `.msi`
   - **Linux:** `.deb` or `.AppImage`
2. Run the installer (no Python, Node.js, or Rust required).
3. Launch **Forge** from your application launcher.

> **First launch note:** On first run, Forge automatically downloads Chromium in the background to `~/.forge/playwright-browsers/` for the `browser_action` tool.

### Option B — Run from source (developers)

**Requirements:** Python 3.11+ (or `uv`), Node.js 18+, Rust (stable), Google Chrome

1. **Clone repository:**
   ```bash
   git clone https://github.com/harshgupta-23/Forge.git
   cd Forge
   ```

2. **First-time setup:**
   - **Windows:** `windows\setup.bat`
   - **Linux:** `bash linux/setup.sh`
   *(Automatically sets up Python venv, installs dependencies, and configures Playwright.)*

3. **Launch application:**
   - **Windows:** `windows\start.bat`
   - **Linux:** `bash linux/start.sh`
   *(Starts the Python sidecar and opens the Tauri UI.)*

---

## Configuration

Click the **Settings** (⚙) button in the top bar to configure:

1. **API Key** — Your model provider key (Google AI Studio keys work out of the box: `AIzaSy...`).
2. **Active Engine Model** — Default is `gemma-4-27b-it` (or any model identifier your provider supports).
3. **API Base URL** — Leave blank for Google AI Studio, or set custom endpoint (e.g. Ollama, OpenRouter).
4. **Working Output Path** — Directory where the agent writes generated files.
5. Click **Commit Setup Changes** to apply immediately without restarting.

Configuration is saved to `~/.forge/config.json` outside the source tree.

### Supported API providers

| Provider | Base URL |
|---|---|
| Google AI Studio | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| Ollama (local) | `http://localhost:11434/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| LM Studio | `http://localhost:1234/v1` |

---

## Building installer packages (developers)

**Requirements:** Python 3.11+ (or `uv`), Node.js 18+, Rust (stable), internet connection

**Windows (MSI):**
```powershell
powershell -ExecutionPolicy Bypass -File windows\build_installer.ps1
```

**Linux (deb / appimage):**
```bash
bash linux/build_installer.sh
```

Packages are output to `src-tauri/target/release/bundle/`.

---

## Built-in tools

| Tool | What it does |
|---|---|
| `web_search` | Searches the web and returns results via DuckDuckGo |
| `browser_action` | Full browser automation via Playwright — navigate, search, fill forms, extract content, download files |
| `read_file` | Reads a file from disk and returns its contents (path protected) |
| `write_file` | Writes content to a file on disk (path protected) |
| `run_local_python_script` | Executes a Python script locally and returns stdout/stderr with security audit logging |
| `take_screenshot` | Captures a screenshot and saves it to the working directory |
| `read_clipboard` | Reads the current clipboard contents |
| `write_clipboard` | Writes text to the clipboard |
| `list_directory` | Lists files and folders in a directory |
| `copy_file` | Copies a file from one path to another |
| `pip_install` | Installs a Python package into isolated user environment at runtime |
| `get_environment_info` | Returns system info — OS, Python version, environment variables |

---

## Adding custom tools

Drop any Python file into `python_backend/tools/` or `~/.forge/tools/`:

```python
# python_backend/tools/my_tool.py
from langchain_core.tools import tool

@tool
def my_tool(input: str) -> str:
    """
    One-sentence description of what this tool does.
    The agent uses this docstring to decide when to call the tool.
    """
    return "result"
```

Restart Forge and the tool is live. No registration or rebuild required.

### Rules for custom tools

- Decorated function must match the file name (without `.py`).
- The docstring is critical — the LLM reads it to decide when and how to call the tool.
- Return a string — the agent receives the return value as context.
- Tools can import any library in the Python environment, call subprocesses, or invoke external APIs.

---

## Guardrails

Built-in tools check every file path against a protection policy before executing:

```python
def is_path_protected(file_path: str) -> bool:
    """Returns True if the path targets config.json, a dot-env file, or the backend folder."""
    target_path = Path(file_path).resolve()
    backend_dir = Path(__file__).parent.parent.resolve()

    if target_path.name.lower() in ("config.json", ".env"):
        return True
    if backend_dir in target_path.parents or target_path == backend_dir:
        return True
    return False
```

This prevents the agent from reading or modifying API keys (`config.json`), `.env` files, or the `python_backend/` codebase — even if prompted by web injection or malicious files.

---

## What gets committed to git

| Path | Committed | Reason |
|---|---|---|
| `src/` | ✅ | Frontend HTML/JS/CSS |
| `src-tauri/src/` | ✅ | Rust source |
| `src-tauri/tauri.conf.json` | ✅ | Tauri config |
| `python_backend/agent.py` | ✅ | Core agent |
| `python_backend/app.py` | ✅ | WebSocket sidecar |
| `python_backend/tools/` | ✅ | Built-in tools |
| `python_backend/requirements.txt` | ✅ | Dev dependencies |
| `python_backend/requirements-embed.txt` | ✅ | Bundler build dependencies |
| `config.template.json` | ✅ | Safe default config |
| `windows/` | ✅ | Windows setup, start, clean, and MSI build scripts |
| `linux/` | ✅ | Linux setup, start, clean, and package build scripts |
| `config.json` | ❌ | Contains your API key |
| `python_backend/.venv/` | ❌ | Virtual environment |
| `python_backend/chrome_profile/` | ❌ | Browser session data |
| `node_modules/` | ❌ | npm packages |
| `src-tauri/target/` | ❌ | Rust build output |
| `src-tauri/resources/` | ❌ | Generated by build scripts |

---

## Current limitations

- **Python scripts only** — `run_local_python_script` runs Python only. Shell tasks (PowerShell or Bash) currently need a Python `subprocess` wrapper or a dedicated custom tool.
- **Single user, local only** — the WebSocket sidecar runs on localhost and is designed for one active session at a time.

---

## License

[Apache License 2.0](LICENSE)

