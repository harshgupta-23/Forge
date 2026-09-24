# Forge — System Architecture & Engineering Specifications

> **Audience**: Systems engineers, contributors, and security auditors seeking an in-depth technical analysis of Forge's execution engine, state machines, storage adapters, and guardrail models.

---

## 1. High-Level Architecture

Forge is engineered with a decoupled, local-first topology separating the native presentation shell, the async streaming server, and the stateful agent orchestration runtime:

```
┌────────────────────────────────────────────────────────────────────────┐
│                          Tauri v2 Desktop Shell                        │
│  ┌─────────────────────────────┐   ┌────────────────────────────────┐  │
│  │ Rust Core (src-tauri)       │   │ Primary Chat Window (src/)     │  │
│  │ - Embedded sidecar manager  │   │ - Vanilla ES6+ Canvas & UI     │  │
│  │ - Thin-client cloud mode    │   │ - role=main WebSocket channel  │  │
│  │ - Native drag-drop bridge   │   │ - Multi-window manager         │  │
│  └─────────────────────────────┘   └──────────────▲─────────────────┘  │
│                                                   │                    │
│                                    ┌──────────────┴─────────────────┐  │
│                                    │ Detached Tree Canvas           │  │
│                                    │ - Standalone WebviewWindow     │  │
│                                    │ - role=secondary socket        │  │
│                                    └──────────────▲─────────────────┘  │
└───────────────────────────────────────────────────┼────────────────────┘
                                                    │ ws://localhost:8765/ws
                                                    │ (?role=main vs ?role=secondary)
┌───────────────────────────────────────────────────▼────────────────────┐
│                    FastAPI Gateway (python_backend/server)             │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ FastAPI Gateway (main.py, routes/ws.py, rest.py)                 │  │
│  │ - ConnectionManager: Role-based delayed shutdown protection      │  │
│  │ - Pydantic Discriminated Union Event Validation                  │  │
│  │ - Dynamic CORS & 5h/24h Sliding Window Token Telemetry           │  │
│  │ - REST Endpoints, OpenAPI Docs (/docs), & SSE Stream Endpoint    │  │
│  └───────────────────────────────▲──────────────────────────────────┘  │
│                                  │                                      │
│  ┌───────────────────────────────▼──────────────────────────────────┐  │
│  │ LangGraph Multi-Node Engine (python_backend/engine)              │  │
│  │ - StateGraph: topic_gate -> planner -> agent -> evaluator -> tools│ │
│  │ - Strict Gemma turn alternation & ToolMessage merge              │  │
│  │ - Non-destructive JIT Dynamic Context Pruner (tombstoning)       │  │
│  │ - Hierarchical Subtree Summarizer (SHA-256 block cache)          │  │
│  │ - Model-aware BPE Tokenizer & Savings Telemetry                  │  │
│  └───────────▲───────────────────▲───────────────────▲──────────────┘  │
│              │                   │                   │                  │
│  ┌───────────▼───────────┐ ┌─────▼───────────┐ ┌─────▼────────┐         │
│  │ Dual Checkpoint Store │ │ pgvector & RAG  │ │ Observ.      │         │
│  │ - AsyncPostgresSaver  │ │ - VectorStore   │ │ - Tracer     │         │
│  │ - AsyncSqliteSaver    │ │ - Embeddings    │ │ - Smith      │         │
│  │ - Unified db_execute  │ │ - Two-Tier Rerank││ - Ragas CI   │         │
│  └───────────────────────┘ └─────────────────┘ └──────────────┘         │
│                              ▲                                          │
│  ┌───────────────────────────┴──────────────────────────────────────┐  │
│  │ Extensible Tooling Engine (python_backend/tools/)                │  │
│  │ - Zero-config auto-discovery from tools/ & ~/.forge              │  │
│  │ - 5-stage defense-in-depth security guardrail engine             │  │
│  │ - Browser automation, sandboxed Python, workspace filesystem     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Multi-Node State Machine Flow

Conversation turns in Forge do not execute as monolithic API calls. They transition through a compiled LangGraph `StateGraph`:

```
               [ User Input ]
                      │
                      ▼
              ┌───────────────┐
              │  topic_gate   │ ──(Topic Shift Detected)──► [ Interactive Branch Prompt ]
              └───────┬───────┘
                      │ (Topic Aligned)
                      ▼
              ┌───────────────┐
              │    planner    │ ──► Decomposes goal into structured plan
              └───────┬───────┘
                      │
                      ▼
       ┌──────────► ┌───┐
       │            │agent│ ──► Token-by-token streaming & XML tag suppression
       │            └───┬─┘
       │                │
       │                ▼
       │        ┌───────────────┐
       │        │   evaluator   │ ──(Task Complete)──► [ END ]
       │        └───────┬───────┘
       │                │
       │       ┌────────┴────────┐
(Action Needed)│                 │ (Repeated Failure Detected)
       ┌───────▼───────┐ ┌───────▼───────┐
       │     tools     │ │   recovery    │ ──► Strike 1: Schema reflection injection
       └───────┬───────┘ └───────┬───────┘     Strike 2: Hard abort to prevent token drain
               │                 │
               └─────────────────┘
```

### Execution Lifecycle:
1. **`topic_gate`**: Evaluates whether the incoming query is related to the active conversational branch. If an unrelated topic shift is detected, execution pauses and an interactive prompt offers the user a choice to fork a clean branch or continue.
2. **`planner`**: Queries the specialized planning model (`MODEL_PLANNER`) to create structured execution milestones.
3. **`agent`**: Invokes the primary reasoning model (`MODEL`) with token-by-token streaming via `AsyncOpenAI`. Includes an XML hysteresis buffer to suppress raw `<tool_call>` tags from flushing to the UI before arguments are validated.
4. **`evaluator`**: Conditional edge inspects agent decisions:
   - Completes execution (`END`) if final answer is produced.
   - Routes to `tools` when valid actions are scheduled.
   - Detects infinite retry loops and routes to `recovery`.
5. **`tools`**: Dispatches tools asynchronously in a thread pool, scrubbed by outbound DLP filters, and returns outputs enclosed in structured XML delimiters (`<tool_output safe_data_only="true">`).
6. **`recovery`**: Implements a two-strike self-healing circuit breaker. Strike 1 injects schema-compliant reflection guidance; Strike 2 enforces hard termination.

---

## 3. Storage Architecture & Stateful Checkpointing

Forge provides persistent, zero-loss time-travel across branches and application restarts through a unified database layer:

```
                    ┌─────────────────────────┐
                    │    CheckpointManager    │
                    └────────────┬────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │                               │
                 ▼                               ▼
       PostgreSQL 16 + pgvector         Local SQLite Fallback
       (AsyncPostgresSaver)             (AsyncSqliteSaver)
       - Async connection pool          - Persistent aiosqlite conn
       - Parameter conversion (%s)      - Standard ? placeholders
```

### Key Components:
- **`storage/db.py` (`db_execute`, `db_execute_batch`)**:
  A unified async database execution helper eliminating SQL duplication across database engines. Standardizes queries using `?` placeholders (automatically converted to `%s` when executing against PostgreSQL), manages transactions, and ensures auto-commit on writes.
- **`storage/tree_adapter.py`**:
  Aggregates LangGraph state history at completed conversational turn boundaries (`snapshot.next == ()`). Resolves parent turns, serializes tree topology, stitches tool calls into node cards, and supports `allow_root_active=True` so users can branch from session genesis (`node_root`).
- **`storage/metadata.py` & `storage/session_manager.py`**:
  - `forge_checkpoint_metadata`: Stores mutable node labels and pruning flags without altering immutable LangGraph checkpoint hashes.
  - `forge_turn_summaries`: Caches hierarchical subtree block summaries keyed by SHA-256 block hashes.
  - `forge_session_summaries`: Maintains lightweight metadata (node count, last preview, timestamps) for fast O(1) sidebar session listing.

---

## 4. Context Compaction & Token Economics

To prevent context bloat and runaway token consumption in long-running tasks, Forge applies deterministic, non-destructive compaction algorithms:

```
Full History
┌─────────────────────────────────────────────────────────────┐
│ Turn 1 (Root Goal) ── Verbatim (100% Invariant)             │
├─────────────────────────────────────────────────────────────┤
│ Turn 2..N-3 (Historical Intermediate Blocks)                │
│   ├── Bulky outputs (>400 tokens) -> Head/Tail Sampling     │
│   ├── Failed tool retries -> Single-line Tombstones         │
│   └── Summarized blocks -> SHA-256 Cached Hierarchical Text │
├─────────────────────────────────────────────────────────────┤
│ Turn N-2..N (Recent Turns) ── Verbatim (100% Invariant)     │
└─────────────────────────────────────────────────────────────┘
```

1. **Dead-End Tool Error Tombstoning**:
   When a failed command is followed by a successful retry or alternative approach, the raw traceback is replaced with a single-line tombstone:
   `[Tool retry succeeded: earlier attempt failed (...). Pruned for context efficiency]`
2. **Bulky Output Truncation**:
   Outputs exceeding 400 tokens are sampled at head and tail boundaries with reduction markers, preserving semantic anchors while discarding repetitious output.
3. **Exact BPE Token Counting**:
   Utilizes `tiktoken` with cached encodings (`cl100k_base`, `o200k_base`) and a deterministic regex fallback to compute per-turn context sizes and cumulative pruned savings.
4. **Heuristic Dead-End Beam Search**:
   Evaluates completed turns based on error density and progress. Abandoned or unproductive subtrees are marked `is_pruned = True` and revived only upon explicit user reactivation.

---

## 5. Defense-in-Depth Security Model

Forge implements a 5-stage zero-trust security architecture across local tools and agent actions:

```
User Prompt / Tool Call
           │
           ▼
[Stage 1: Path Jail & Boundary Enforcement] ──► Confines access to AGENT_WORK_DIR; dynamically authorizes user-attached files
           │
           ▼
[Stage 2: AST Static Code Inspection]       ──► Blocks dangerous modules (ctypes, winreg, pty) and dynamic eval/exec
           │
           ▼
[Stage 3: Subprocess Environment & Jail]    ──► Strips credentials (SAFE_ENV_WHITELIST) & applies Linux bwrap isolation
           │
           ▼
[Stage 4: Indirect Prompt Injection Guard]  ──► Encloses tool output in <tool_output safe_data_only="true"> tags
           │
           ▼
[Stage 5: Outbound DLP Secret Redaction]    ──► Masks API tokens, passwords, and private keys before LLM/UI delivery
```

- **Cross-Platform Workspace Jail (`is_path_safe`)**: Resolves directory traversal (`..`), symlinks, Windows UNC paths (`\\?\...`), and enforces case-insensitivity on Windows while unconditionally blocking system folders (`~/.ssh`, `~/.aws`, `~/.bashrc`, `/etc`, Windows system directories).
- **Subprocess Environment Scrubbing (`SAFE_ENV_WHITELIST`)**: Prevents child and grandchild processes from inheriting sensitive runtime secrets (`OPENAI_API_KEY`, `DATABASE_URL`, `AWS_*`).
- **Linux Bubblewrap (`bwrap`) Sandboxing**: Isolates Python executions with read-only root filesystems (`--ro-bind / /`), temporary memory overlays (`--tmpfs`), and restricted workspace write permissions while preserving outbound network egress.
- **AST Static Inspection**: Pre-screens script ASTs to reject dangerous modules (`ctypes`, `winreg`, `pty`) and dynamic execution primitives (`eval`, `exec`).
- **Outbound Data Loss Prevention (DLP)**: High-precision regex rules redact API keys (OpenAI, Anthropic, GitHub), private keys, and database passwords from tool responses and streaming events.

---

## 6. Hybrid RAG & Two-Tier Reranking

Retrieval in Forge unifies lexical exactness and semantic vector search without introducing heavy machine-learning runtime dependencies:

```
                      [ User Query ]
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
     pgvector Cosine Search        PostgreSQL Full-Text Search
    (or SQLite Cosine Fallback)    (GIN index with 'simple' dictionary)
              │                             │
              └──────────────┬──────────────┘
                             │
                             ▼
              Reciprocal Rank Fusion (RRF)
              RRF(d) = Σ [ 1 / (60 + rank(d)) ]
                             │
                             ▼
                    Two-Tier Reranker
           Tier 1: Fast LLM JSON Relevance Ranking
           Tier 2: Pure-Python Lexical Overlap Fallback
                             │
                             ▼
                [ Final Context Excerpts ]
```

- **Reciprocal Rank Fusion (RRF)**: Merges ranked results from semantic cosine search and full-text keyword search without requiring fragile score normalization:
  $$RRF(d) = \sum_{m \in M} \frac{1}{60 + \text{rank}_m(d)}$$
- **Zero-Dependency Two-Tier Reranking**: Replaces multi-gigabyte PyTorch / cross-encoder dependencies with a lightweight, low-latency LLM scoring prompt backed by pure-Python lexical overlap fallback.

---

## 7. Dual Protocol Networking: WebSockets & SSE

Forge serves two distinct operational modalities through its FastAPI gateway:

| Protocol | Endpoint | Primary Use Case | Characteristics |
|---|---|---|---|
| **WebSocket** | `ws://localhost:8765/ws?role=main` | Desktop App (Primary) | Full-duplex bidirectional channel. Handles user inputs, cancellations, dynamic branch navigation, inline renaming, and session deletion. Controls server lifetime via delayed shutdown protection. |
| **WebSocket** | `ws://localhost:8765/ws?role=secondary` | Detached Tree Window | Session-scoped secondary channel for auxiliary canvas windows. Receives broadcast events without affecting server shutdown counters. |
| **Server-Sent Events (SSE)** | `POST /api/chat/stream` | External REST Clients | Unidirectional HTTP streaming protocol designed for programmatic integrations, CLI tools, and webhooks. |

---

## 8. Verification & Continuous Testing Matrix

Forge maintains 10 automated test suites executed via `npm test` (`scripts/run-tests.js`) and verified on GitHub Actions CI:

| Suite | File | Scope |
|---|---|---|
| **Phase 1** | `tests/test_phase1.py` | Pydantic event tagged union validation (`rename_session`, `delete_session`), Gemma turn alternation, thought stripping, graph compilation, delayed shutdown guard. |
| **Phase 2** | `tests/test_phase2.py` | Dual checkpointer persistence (SQLite / PostgreSQL), database reconnection, turn snapshot aggregation, `SessionManager` state transitions, `node_root` resolution. |
| **Phase 3** | `tests/test_phase3.py` | Recursive chunking, embeddings, pgvector and SQLite hybrid search, RRF fusion, two-tier reranker. |
| **Phase 4** | `tests/test_phase4.py` | Dynamic context pruning, bulky output truncation, dead-end tool tombstoning, BPE token savings telemetry, hierarchical summarization, dead-end beam search. |
| **Ragas Evals** | `tests/evals/test_ragas.py` | Continuous evaluation scoring Faithfulness, Answer Relevance, Context Precision, and Context Recall ($\ge 0.70$ quality gate) in live and deterministic offline modes. |
| **Phase 5** | `tests/test_phase5.py` | LangSmith thread-scoped tracer callbacks, credential precedence, golden dataset schema validation, evaluation report serialization. |
| **Phase 6** | `tests/test_phase6.py` | Multi-stage Dockerfile security, Docker Compose container coordination, AWS Terraform HCL declarations, dynamic CORS origins, thin-client launch scripts. |
| **Guardrails** | `tests/test_guardrails.py` | 5-stage defense-in-depth security: path jail, system blocklists, attached file authorization, DLP secret masking, environment scrubbing, AST code inspection, canary tokens. |
| **Undo** | `tests/test_undo.py` | Single-turn undo returning to root, two-turn rollback, multi-turn side-branch rollback with main branch preservation, continued conversation from parent turn. |
| **Topic Gate** | `tests/test_topic_gate.py` | Topic shift detection, 50-turn prompt limits, network error fallbacks, unparseable response fallbacks, multimodal list support, code fence parsing, conditional router gates. |
