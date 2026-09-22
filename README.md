# Forge — Enterprise-Grade Autonomous AI Agent Platform

[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph%20StateGraph-blue?logo=python)](https://github.com/langchain-ai/langgraph)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI%20%26%20Uvicorn-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![pgvector](https://img.shields.io/badge/Vector%20Store-PostgreSQL%20%2B%20pgvector-336791?logo=postgresql)](https://github.com/pgvector/pgvector)
[![Tauri v2](https://img.shields.io/badge/Desktop-Tauri%20v2%20(Rust)-FFC131?logo=tauri)](https://tauri.app)
[![Docker](https://img.shields.io/badge/DevOps-Docker%20%26%20Compose-2496ED?logo=docker)](https://www.docker.com)
[![Terraform](https://img.shields.io/badge/IaC-Terraform%20(AWS)-844FBA?logo=terraform)](https://www.terraform.io)
[![LangSmith](https://img.shields.io/badge/Observability-LangSmith%20Tracing-FF6F00)](https://www.langchain.com/langsmith)
[![Ragas](https://img.shields.io/badge/Evaluation-Ragas%20CI%2FCD-4CAF50)](https://github.com/explodinggradients/ragas)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

> **Forge** is a high-performance, local-first autonomous AI agent designed for complex multi-turn reasoning, stateful conversational branching, and local execution. Built with a decoupled **Tauri (Rust)** desktop shell, an async **FastAPI** streaming gateway, a multi-node **LangGraph** engine, **pgvector** hybrid RAG, dynamic context pruning, and automated **Ragas** CI/CD continuous evaluation.

![Forge UI](docs/screenshot.png)

---

## 🌟 Why Forge?

Traditional AI assistants force users into linear, fragile chat threads where context bloat burns tokens and dead-end tool failures pollute reasoning. **Forge solves this with a tree-native architecture:**

- 🌿 **Interactive Decision Tree Canvas**: Explore multiple parallel lines of reasoning on an infinite n8n-style zoomable canvas. Fork conversations from any previous turn with instantaneous time-travel rollback.
- ✂️ **Dynamic Context Pruning**: JIT algorithmic compaction that tombstones failed tool retries, truncates bulky outputs, and hierarchically summarizes subtrees—cutting token costs by over 40% while keeping the active branch lean.
- 🔍 **Hybrid pgvector RAG & Reranking**: Enterprise retrieval combining pgvector cosine similarity with PostgreSQL full-text keyword search via Reciprocal Rank Fusion (RRF) and two-tier LLM reranking.
- 🛡️ **Zero-Crash Stateful Checkpointing**: Durable persistence powered by `AsyncPostgresSaver` (with zero-configuration local `AsyncSqliteSaver` fallback) preserving complete execution histories across application restarts.
- 📊 **Production Observability & Automated Evaluation**: Thread-scoped LangSmith tracing and an automated Ragas continuous evaluation harness integrated into GitHub Actions CI.
- ☁️ **Cloud-Ready & Hybrid Decoupled**: Multi-stage non-root Docker containerization, AWS Terraform infrastructure (ECS Fargate, RDS PostgreSQL, ALB), and thin-client remote connectivity.

---

## 🏛️ System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Tauri Desktop App                     │
│  ┌─────────────────────────────┐   ┌─────────────────────┐  │
│  │ Rust Shell (src-tauri)      │   │ Frontend UI (src)   │  │
│  │ - Window & sidecar manager  │   │ - Vanilla JS + CSS  │  │
│  │ - Hybrid thin-client mode   │   │ - Pan/zoom SVG tree │  │
│  │ - Native drag-drop bridge   │   │ - Marked.js + HLJS  │  │
│  └─────────────────────────────┘   └──────────▲──────────┘  │
└───────────────────────────────────────────────┼─────────────┘
                                                │ ws://localhost:8765 / HTTP REST & SSE
┌───────────────────────────────────────────────▼─────────────┐
│                 FastAPI Gateway (python_backend/server)     │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ FastAPI Application (main.py, routes/ws.py, rest.py)  │  │
│  │ - Discriminated Union Event Validation (Pydantic v2)  │  │
│  │ - Dynamic CORS & 5h/24h Rolling Token Telemetry       │  │
│  │ - REST Endpoints, OpenAPI docs (/docs), & SSE Stream │  │
│  └───────────────────────────▲───────────────────────────┘  │
│                              │                               │
│  ┌───────────────────────────▼───────────────────────────┐  │
│  │ LangGraph Multi-Node Engine (python_backend/engine)   │  │
│  │ - StateGraph: Planner -> Agent -> Evaluator -> Tools  │  │
│  │ - Strict Gemma turn alternation & ToolMessage merge   │  │
│  │ - Dynamic Context Pruner (Tombstoning & Truncation)   │  │
│  │ - Hierarchical Subtree Summarizer (SHA-256 caching)   │  │
│  │ - BPE Tokenizer with Tiktoken & Regex Fallback        │  │
│  └───────────▲───────────────────▲───────────────────▲───┘  │
│              │                   │                   │       │
│  ┌───────────▼───────────┐ ┌─────▼───────────┐ ┌─────▼─────┐ │
│  │ Dual Checkpoint Store │ │ pgvector & RAG  │ │ Observ.   │ │
│  │ - AsyncPostgresSaver  │ │ - VectorStore   │ │ - Tracer  │ │
│  │ - AsyncSqliteSaver    │ │ - Embeddings    │ │ - Smith   │ │
│  │ - Metadata & Summaries│ │ - Reranker      │ │ - Ragas   │ │
│  └───────────────────────┘ └─────────────────┘ └───────────┘ │
│                              ▲                               │
│  ┌───────────────────────────┴───────────────────────────┐  │
│  │ Extensible Tooling Engine (python_backend/tools/)     │  │
│  │ - Zero-config auto-discovery & sandbox firewall       │  │
│  │ - Semantic search, Playwright, Python execution, etc. │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## ⚡ Key Engineering Highlights

### 1. Multi-Node LangGraph Loop & Role-Decoupled Models
Decomposes complex requests into discrete, observable steps with role-specific model specialization:
- **`planner`**: Intelligent task decomposition (`MODEL_PLANNER`) formulating execution plans before actions start.
- **`agent`**: Real async token-by-token streaming (`MODEL`) via `AsyncOpenAI`, with XML tag suppression buffering and balanced bracket fallback parsing.
- **`tools`**: Concurrent async tool execution with automatic exception isolation and parameter fallbacks.
- **`evaluator` & `recovery`**: Two-strike self-healing guardrail. On repeated failure, routes to `recovery` with schema-compliant `ToolMessage` reflection before terminating infinite loops.
- **`summarizer`**: Hierarchical subtree summarization (`MODEL_SUMMARIZER`) compressing historical turns without context degradation.

### 2. Algorithmic Context Pruning & Hierarchical Summaries
- **Dead-end Tombstoning**: Verbose tracebacks and failed commands are replaced with single-line tombstones as soon as a retry succeeds, preventing catastrophic hallucination loops.
- **Bulky Output Truncation**: Intelligently samples head/tail snippets of large outputs (>400 tokens) with reduction markers.
- **Hierarchical Block Summarization**: Progressively summarizes historical conversation blocks and caches summaries using deterministic SHA-256 keys (`forge_turn_summaries`).
- **Dead-end Subtree Pruning**: Heuristic beam search evaluates branch progress and automatically flags dead-end paths on the canvas.

### 3. Hybrid RAG with Cross-Encoder Reranking
- **pgvector Vector Store**: HNSW-indexed vector similarity with unconstrained dimension probing (OpenAI, Gemini, Ollama).
- **Keyword Search**: GIN-indexed full-text search preserving camelCase and code tokens.
- **Reciprocal Rank Fusion (RRF)**: Merges lexical and vector ranking lists:
  $$RRF(d) = \sum_{m \in M} \frac{1}{60 + \text{rank}_m(d)}$$
- **Two-Tier Reranker**: Rapid LLM relevance scoring with zero-dependency lexical fallback—delivering high precision without 1.5GB PyTorch binary dependencies.

### 4. Enterprise Observability & Automated Evaluation
- **LangSmith Tracing**: Unifies multi-node LangGraph cycles, tool calls, and latency spans under a thread-scoped trace tree.
- **Dual-Mode Ragas CI/CD Harness**: Evaluates Faithfulness, Answer Relevance, Context Precision (MAP), and Context Recall. Features a deterministic offline scoring mode to run robustly in CI pipelines without relying on external API secrets.

### 5. Cloud-Native DevOps & Hybrid Client
- **Multi-Stage Docker Build**: Isolates build compilers, drops privileges to a non-root `forge:1000:1000` user, pre-configures headless Chromium, and runs native `/health` checks.
- **Terraform IaC for AWS**: Modular cloud blueprint provisioning a VPC, subnets across 2 AZs, RDS PostgreSQL 16 + pgvector, ECS Fargate, Secrets Manager, and an ALB with extended `300s` WebSocket idle timeout.
- **Hybrid Client Architecture**: Allows running the Tauri UI as a thin client connecting to a remote backend (`BACKEND_MODE=remote`), bypassing local sidecar execution.

---

## 🛠️ Built-in Tool Suite & Defense-in-Depth Security Guardrails

| Tool | Capabilities |
|---|---|
| `semantic_search` | Hybrid vector + BM25 keyword search over ingested documents with RRF and session isolation |
| `browser_action` | Playwright Chromium automation (page navigation, form fill, content extraction, screenshots) |
| `run_local_python_script` | Subprocess Python execution with AST analysis, environment scrubbing, and Linux `bwrap` isolation |
| `read_file` / `write_file` | Filesystem operations bounded to `AGENT_WORK_DIR` with 10 MB limit and path jail enforcement |
| `copy_file` / `list_directory` | Workspace-jailed file copying and directory tree inspection |
| `web_search` | Live internet search via DuckDuckGo |
| `pip_install` | Dynamic package installer into an isolated user environment at runtime |
| `take_screenshot` / `read_clipboard` | Native desktop system utilities |

### 🔒 Enterprise Defense-in-Depth Guardrails (`security.py`)
- **Cross-Platform Workspace Jail (`is_path_safe`)**: Confines all file operations strictly to `AGENT_WORK_DIR` with Windows UNC (`\\?\...`) and case-insensitive normalization across Linux and Windows.
- **Unconditional System Blocklist**: System folders (`~/.ssh`, `~/.aws`, `~/.bashrc`, `/etc`, `C:\Windows`, `C:\Program Files`, registry hives) and project secrets (`.env`, `config.json`, backend source) are unconditionally blocked.
- **Dynamic Attached-File Authorization**: Session-scoped authorization dynamically allows reading external files dragged/attached by the user without breaching system directory blocklists.
- **Subprocess Credential Scrubbing (`SAFE_ENV_WHITELIST`)**: Subprocesses run with a stripped environment, preventing child, grandchild, and descendant processes from inheriting sensitive credentials (`OPENAI_API_KEY`, `DATABASE_URL`, `AWS_*`).
- **Linux Bubblewrap (`bwrap`) Filesystem Isolation**: Mounts an isolated filesystem (`--ro-bind / /`, `--tmpfs ~/.ssh`, `--tmpfs ~/.aws`) for Python scripts while preserving network egress for legitimate external requests.
- **AST Static Code Analysis**: Pre-execution AST inspection blocks dangerous modules (`pty`, `winreg`, `ctypes`) and dynamic execution primitives (`eval`, `exec`).
- **DLP Secret Masking & XML Delimiters**: Automatic outbound token redaction (OpenAI, Anthropic, GitHub, AWS, private keys, database URLs) and structured `<tool_output name="..." safe_data_only="true">` delimiters to mitigate indirect prompt injection.
- **Two-Strike Loop Recovery**: Detects repeated tool failures with identical arguments; Strike 1 injects schema-compliant reflection guidance to steer the agent to alternative tools, while Strike 2 enforces a hard termination to prevent token drain.

### Instant Tool Extensibility
Drop any Python file decorated with `@tool` into `python_backend/tools/` or `~/.forge/tools/`:

```python
from langchain_core.tools import tool

@tool
def calculate_custom_metric(query: str) -> str:
    """Computes specialized domain metrics. The LLM reads this docstring to decide when to call the tool."""
    return f"Computed metric for {query}"
```
*Discovered and loaded dynamically on next startup with zero recompilation.*

---

## 🚀 Quickstart

### Prerequisites
- Python 3.11+ (or [`uv`](https://github.com/astral-sh/uv))
- Node.js 18+
- Rust (stable, for Tauri builds)
- Google Chrome / Chromium

### 1. Local Development
```bash
# Clone the repository
git clone https://github.com/harshgupta-23/Forge.git
cd Forge

# Linux setup & start
bash linux/setup.sh
bash linux/start.sh

# Windows setup & start
windows\setup.bat
windows\start.bat
```

### 2. Containerized Deployment (One Command)
```bash
# Launch FastAPI backend + PostgreSQL with pgvector
docker compose up -d --build

# Or use the launcher flag
bash linux/start.sh --docker
```

### 3. Run Automated Evaluation & Test Suites
```bash
# Runs all 8 test suites (Phases 1–6 regression + Ragas evaluation + Guardrails)
npm test
```

---

## 📋 Comprehensive Tech Stack

| Layer | Technologies |
|---|---|
| **Desktop Shell** | Tauri v2, Rust, WebKitGTK / WebView2 |
| **Frontend UI** | Vanilla JavaScript (ES6+), SVG Canvas, Marked.js, Highlight.js |
| **Backend Gateway** | FastAPI, Uvicorn, Pydantic v2, Server-Sent Events (SSE), WebSockets |
| **Agent Core** | LangGraph, LangChain Core, OpenAI Python SDK |
| **Data & Retrieval** | PostgreSQL 16, pgvector, aiosqlite, AsyncPostgresSaver, RRF Fusion |
| **Observability** | LangSmith (`@traceable`, `LangChainTracer`), BPE Tokenizer (`tiktoken`) |
| **Evaluation** | Ragas continuous evaluation metrics, GitHub Actions CI/CD |
| **Infrastructure** | Docker (multi-stage non-root), Docker Compose, Terraform (AWS) |

---

## 📄 License

Distributed under the **Apache License 2.0**. See [`LICENSE`](LICENSE) for more information.
