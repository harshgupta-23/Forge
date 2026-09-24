# Forge — Autonomous AI Agent Platform with Stateful Branching

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)](#)
[![Docker Support](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker)](#)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-blue?logo=python)](https://github.com/langchain-ai/langgraph)
[![Tauri v2](https://img.shields.io/badge/Desktop-Tauri_v2-FFC131?logo=tauri)](https://tauri.app)

> **Forge** is a local-first autonomous agent platform designed for complex, non-linear reasoning. Instead of rigid chat threads, Forge provides an interactive visual canvas that lets you explore parallel problem-solving paths, branch from any point in time, and execute multi-step automations with enterprise-grade guardrails.

![Forge UI](docs/screenshot.png)

---

## 🌟 Key Features

### 🌿 Visual Decision Tree & Conversation Branching
- **Non-Linear Reasoning:** Explore divergent lines of thought on an infinite zoomable canvas without losing context.
- **Time-Travel Rollback:** Step back to any prior reasoning turn or restart fresh branches from the conversation genesis (`node_root`).
- **Automatic Drift Detection:** Forge detects topic shifts in real time and prompts you to branch cleanly before context degrades.

### ⚡ Context-Optimized Reasoning Engine
- **Self-Cleaning Context:** Automatically compacts failed tool attempts and verbose logs into single-line tombstones once tasks succeed, cutting token usage by up to 40%.
- **Hierarchical Summarization:** Progressively compresses long execution histories into compact contextual memory blocks for complex, multi-hour workflows.
- **Zero-Loss Persistence:** Seamlessly resume sessions across application restarts with zero state corruption.

### 🔍 Precision Hybrid Knowledge Retrieval (RAG)
- **Unified Hybrid Search:** Combines semantic vector similarity with exact code and keyword matching to eliminate retrieval blind spots.
- **Two-Tier Reranking:** Surfaces the most relevant excerpts instantly to ensure accurate, grounded outputs without heavy runtime latency or multi-gigabyte models.

### 🛡️ Sandboxed Execution & Enterprise Guardrails
- **OS-Level Sandboxing:** Safe execution of Python scripts and browser automations isolated from host system credentials and sensitive directories.
- **Infinite Loop Protection:** Automated reflection guards detect repeated execution failures and divert the agent toward recovery strategies.
- **Sensitive Data Redaction (DLP):** Outbound inspection automatically masks API keys, tokens, and database credentials before they reach the model or logs.

---

## 🛠️ Built-in Capabilities

| Capability | What It Does |
|---|---|
| **Web & App Automation** | Headless browser execution to navigate pages, extract live data, and take screenshots |
| **Secure Code Execution** | Isolated Python runtime for data processing, math, and custom automation scripts |
| **Document Search** | Hybrid semantic and keyword search across local project files and notes |
| **Workspace File I/O** | Safe, sandboxed file operations confined strictly to your active project workspace |
| **Dynamic Extensions** | Add custom tools instantly by dropping a decorated Python function into your tools directory |

---

## 🚀 Quickstart

### Prebuilt Desktop Apps (Zero Setup)
Download the standalone installer for your platform from [Releases](https://github.com/harshgupta-23/Forge/releases) — no Python or Node.js toolchain required:
- **Windows**: `.msi` installer
- **Linux**: `.AppImage` (portable executable) or `.deb` package (Ubuntu/Debian)

---

### Running from Source / Containers

#### Prerequisites
- Python 3.11+
- Node.js 18+
- Rust & Cargo (for native desktop builds)

#### 1. Run with Docker (Recommended)

```bash
git clone https://github.com/harshgupta-23/Forge.git
cd Forge
docker compose up -d
```

Open your browser at `http://localhost:8765` or connect your desktop client.

#### 2. Local Desktop Installation

```bash
# Clone the repository
git clone https://github.com/harshgupta-23/Forge.git
cd Forge

# Linux / macOS
bash linux/setup.sh
bash linux/start.sh

# Windows
windows\setup.bat
windows\start.bat
```

---

## 🏛️ Architecture & Technical Specs

Forge decouples client presentation, workflow orchestration, and sandbox isolation:

- **Desktop Client:** Lightweight native desktop shell powered by Tauri (Rust) and an infinite SVG canvas.
- **Streaming Gateway:** High-performance async FastAPI backend with bi-directional WebSocket and SSE endpoints.
- **Execution & Storage:** Multi-node LangGraph state graph with swappable SQLite and PostgreSQL persistence.

> 📖 **Deep Technical Specifications**: For state machine transition rules, storage engine details, security models, and benchmark evaluation matrices, see the dedicated [**Architecture Guide (`docs/ARCHITECTURE.md`)**](docs/ARCHITECTURE.md).

---

## 📄 License

Distributed under the Apache 2.0 License. See [LICENSE](LICENSE) for details.
