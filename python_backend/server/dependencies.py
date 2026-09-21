"""
dependencies.py — Session state, configuration management, tree graph persistence,
and shared utility functions.
"""

import os
import sys
import json
import glob
import uuid
import pathlib
from datetime import datetime, timezone
from typing import Optional, Any
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from server.schemas.events import ChatHistoryOutbound, TreeDataOutbound

HOME = pathlib.Path.home()
BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

def _resolve_agent_home() -> pathlib.Path:
    target = HOME / ".forge"
    try:
        target.mkdir(parents=True, exist_ok=True)
        test_file = target / ".write_test"
        test_file.touch()
        test_file.unlink(missing_ok=True)
        return target
    except (PermissionError, OSError) as p_err:
        fallback = pathlib.Path("/tmp/.forge")
        fallback.mkdir(parents=True, exist_ok=True)
        print(f"[dependencies] Warning: Cannot write to {target} ({p_err}). Falling back to {fallback}")
        return fallback

AGENT_HOME = _resolve_agent_home()
CONFIG_PATH = AGENT_HOME / "config.json"
SESSION_DIR = AGENT_HOME / "agent_sessions"
TOKEN_LOG_PATH = AGENT_HOME / "token_usage.log"
SCRIPTS_DIR = AGENT_HOME / "agent_scripts"
AUDIT_LOG_DIR = AGENT_HOME / "agent_audit_logs"
PLAYWRIGHT_BROWSERS_DIR = AGENT_HOME / "playwright-browsers"
PIP_INSTALL_DIR = AGENT_HOME / "python-packages"
CHROME_PROFILE_DIR = AGENT_HOME / "chrome_profile"

# Ensure all subdirectories inside AGENT_HOME exist
for d in (SESSION_DIR, SCRIPTS_DIR, AUDIT_LOG_DIR, PLAYWRIGHT_BROWSERS_DIR, PIP_INSTALL_DIR, CHROME_PROFILE_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Point all tool and library paths strictly to ~/.forge
os.environ["AGENT_AUDIT_DIR"] = str(SCRIPTS_DIR)
os.environ["CHROME_USER_DATA_DIR"] = str(CHROME_PROFILE_DIR)
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_DIR)
if str(PIP_INSTALL_DIR) not in sys.path:
    sys.path.insert(0, str(PIP_INSTALL_DIR))

_existing_pypath = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = str(PIP_INSTALL_DIR) + (os.pathsep + _existing_pypath if _existing_pypath else "")


def _consolidate_legacy_folders() -> None:
    """Migrates any stray directories outside ~/.forge into ~/.forge and cleans them up."""
    legacy_mappings = [
        (HOME / ".agent_scripts", SCRIPTS_DIR),
        (HOME / "agent_audit_logs", AUDIT_LOG_DIR),
        (PROJECT_ROOT / "chrome_profile", CHROME_PROFILE_DIR),
        (BACKEND_DIR / "chrome_profile", CHROME_PROFILE_DIR),
    ]
    for old_dir, new_dir in legacy_mappings:
        if old_dir.exists() and old_dir.is_dir() and old_dir.resolve() != new_dir.resolve():
            try:
                for item in old_dir.iterdir():
                    dest = new_dir / item.name
                    if not dest.exists():
                        try:
                            import shutil
                            shutil.move(str(item), str(dest))
                        except Exception:
                            pass
                try:
                    old_dir.rmdir()
                except Exception:
                    pass
            except Exception:
                pass


_consolidate_legacy_folders()


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        template = PROJECT_ROOT / "config.template.json"
        if template.exists():
            import shutil
            shutil.copy(template, CONFIG_PATH)
        else:
            save_config({
                "API_KEY": "",
                "MODEL": "gemma-4-26b-a4b-it",
                "API_BASE": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "AGENT_WORK_DIR": str(AGENT_HOME / "agent_outputs"),
                "DATABASE_URL": "",
                "THEME": "dark"
            })
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: dict[str, Any]) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def apply_config_to_env(cfg: dict[str, Any]) -> None:
    for key in ("API_KEY", "MODEL", "API_BASE", "AGENT_WORK_DIR", "DATABASE_URL"):
        if key in cfg:
            os.environ[key] = str(cfg[key])


# Apply configuration at import time
apply_config_to_env(load_config())


def serialize_message(msg: BaseMessage) -> Optional[dict[str, Any]]:
    from engine.utils import estimate_tokens
    if isinstance(msg, HumanMessage):
        content_str = str(msg.content)
        return {
            "type": "human",
            "content": content_str,
            "tokens": estimate_tokens(content_str)
        }
    elif isinstance(msg, AIMessage):
        content_str = str(msg.content or "")
        toks = estimate_tokens(content_str)
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                toks += estimate_tokens(tc.get("name", "")) + estimate_tokens(str(tc.get("args", "")))
        return {
            "type": "ai",
            "content": content_str,
            "tokens": toks
        }
    elif isinstance(msg, ToolMessage):
        content_str = str(msg.content or "")
        return {
            "type": "tool",
            "content": content_str,
            "name": getattr(msg, "name", "tool"),
            "tool_call_id": getattr(msg, "tool_call_id", "tool"),
            "tokens": estimate_tokens(content_str)
        }
    return None


def deserialize_message(d: dict[str, Any]) -> Optional[BaseMessage]:
    t = d.get("type")
    if t == "human":
        return HumanMessage(content=d.get("content", ""))
    elif t == "ai":
        return AIMessage(content=d.get("content", ""))
    elif t == "tool":
        return ToolMessage(
            content=d.get("content", ""),
            name=d.get("name", "tool"),
            tool_call_id=d.get("tool_call_id", "tool")
        )
    return None


def extract_tool_calls_and_results(intermediate_msgs: list[BaseMessage]):
    from engine.utils import estimate_tokens
    tool_calls = []
    tool_results = []
    for msg in intermediate_msgs:
        if isinstance(msg, AIMessage):
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_calls.extend(msg.tool_calls)
        elif isinstance(msg, ToolMessage):
            content_str = str(msg.content or "")
            summary = content_str.split('\n')[0][:80] if content_str else ""
            tool_results.append({
                "name": getattr(msg, "name", "tool"),
                "content": content_str,
                "summary": summary,
                "tokens": estimate_tokens(content_str)
            })
    return tool_calls, tool_results


class ConversationTree:
    def __init__(self, session_id: Optional[str] = None, label: Optional[str] = None):
        self.session_id = session_id or f"sess_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.root_id = "node_root"
        self.active_node_id = "node_root"
        self.label = label
        self.nodes: dict[str, Any] = {
            "node_root": {
                "id": "node_root",
                "parent_id": None,
                "children_ids": [],
                "created_at": self.created_at,
                "type": "root",
                "user_message": None,
                "agent_message": None,
                "tool_calls": [],
                "label": None,
                "intermediate_messages": []
            }
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "root_id": self.root_id,
            "active_node_id": self.active_node_id,
            "label": self.label,
            "nodes": self.nodes
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConversationTree":
        tree = cls()
        tree.session_id = d.get("session_id", tree.session_id)
        tree.created_at = d.get("created_at", tree.created_at)
        tree.root_id = d.get("root_id", "node_root")
        tree.active_node_id = d.get("active_node_id", "node_root")
        tree.label = d.get("label")
        tree.nodes = d.get("nodes", tree.nodes)
        return tree

    def get_path(self, node_id: str) -> list[dict[str, Any]]:
        path = []
        curr_id = node_id
        while curr_id:
            node = self.nodes.get(curr_id)
            if not node:
                break
            path.append(node)
            if node.get("type") == "summary":
                break
            curr_id = node.get("parent_id")
        path.reverse()
        return path

    def get_active_path_messages(self) -> list[BaseMessage]:
        path = self.get_path(self.active_node_id)
        messages: list[BaseMessage] = []
        for node in path:
            if node.get("type") == "root":
                continue

            user_msg_dict = node.get("user_message")
            if user_msg_dict:
                messages.append(HumanMessage(content=user_msg_dict.get("content", "")))

            inter_msgs_dicts = node.get("intermediate_messages", [])
            for m_dict in inter_msgs_dicts:
                msg = deserialize_message(m_dict)
                if msg:
                    messages.append(msg)

            agent_msg_dict = node.get("agent_message")
            if agent_msg_dict:
                messages.append(AIMessage(content=agent_msg_dict.get("content", "")))

        return messages

    def create_node(
        self,
        parent_id: Optional[str],
        user_msg: Optional[HumanMessage],
        intermediate_msgs: list[BaseMessage],
        final_msg: Optional[AIMessage],
        label: Optional[str] = None,
        node_type: str = "turn"
    ) -> str:
        node_id = f"node_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:4]}"

        from engine.utils import estimate_tokens
        user_message_dict = None
        u_tok = 0
        if user_msg:
            content_str = str(user_msg.content)
            u_tok = estimate_tokens(content_str)
            user_message_dict = {
                "role": "user",
                "content": content_str,
                "attachments": [],
                "tokens": u_tok
            }

        agent_message_dict = None
        tool_calls = []
        tool_results = []
        a_tok = 0
        if final_msg:
            tool_calls, tool_results = extract_tool_calls_and_results(intermediate_msgs)
            final_content = str(final_msg.content or "")
            a_tok = estimate_tokens(final_content)
            agent_message_dict = {
                "role": "assistant",
                "content": final_content,
                "tool_calls": tool_calls,
                "tool_results": tool_results,
                "tokens": a_tok
            }

        t_tok = sum(r.get("tokens", 0) for r in tool_results)
        turn_tokens = u_tok + t_tok + a_tok

        intermediate_serialized = [
            serialize_message(m) for m in intermediate_msgs if serialize_message(m) is not None
        ]

        node = {
            "id": node_id,
            "parent_id": parent_id,
            "children_ids": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "type": node_type,
            "user_message": user_message_dict,
            "agent_message": agent_message_dict,
            "tool_calls": tool_calls,
            "label": label,
            "intermediate_messages": intermediate_serialized,
            "tokens": {
                "user": u_tok,
                "tools": t_tok,
                "agent": a_tok,
                "total": turn_tokens
            }
        }

        self.nodes[node_id] = node

        if parent_id and parent_id in self.nodes:
            if node_id not in self.nodes[parent_id]["children_ids"]:
                self.nodes[parent_id]["children_ids"].append(node_id)

        self.active_node_id = node_id
        return node_id

    def undo(self) -> str:
        active_node = self.nodes.get(self.active_node_id)
        if active_node and active_node.get("parent_id"):
            self.active_node_id = active_node["parent_id"]
            return self.active_node_id
        return self.active_node_id

    def save_tree(self, filepath: str) -> None:
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
        except Exception as exc:
            print(f"[dependencies] Error saving session tree: {exc}")


def load_or_create_tree(session_dir: pathlib.Path) -> ConversationTree:
    tree = ConversationTree()
    filepath = session_dir / f"session_{tree.session_id}.json"
    tree.save_tree(str(filepath))
    return tree


class Session:
    def __init__(self):
        self.tree = load_or_create_tree(SESSION_DIR)
        self.attached_files: dict[str, str] = {}
        self.stop_event = None
        self.generation_task = None


async def send_chat_and_tree(websocket, session: Session) -> None:
    path_msgs = session.tree.get_active_path_messages()
    serialized_path = []
    for m in path_msgs:
        ser = serialize_message(m)
        if ser:
            serialized_path.append(ser)

    chat_out = ChatHistoryOutbound(
        messages=serialized_path,
        active_node_id=session.tree.active_node_id
    )
    await websocket.send_text(chat_out.model_dump_json())

    tree_out = TreeDataOutbound(
        session_id=session.tree.session_id,
        root_id=session.tree.root_id,
        active_node_id=session.tree.active_node_id,
        nodes=session.tree.nodes
    )
    await websocket.send_text(tree_out.model_dump_json())


def list_available_sessions() -> list[dict[str, Any]]:
    sessions = []
    for filepath in glob.glob(str(SESSION_DIR / "session_*.json")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        nodes = d.get("nodes", {})
        if len(nodes) <= 1:
            continue
        preview = ""
        for node in nodes.values():
            if node.get("type") != "root" and node.get("user_message"):
                preview = node["user_message"].get("content", "")[:60]
                break
        sessions.append({
            "session_id": d.get("session_id"),
            "created_at": d.get("created_at"),
            "node_count": len(nodes),
            "preview": preview,
            "label": d.get("label"),
        })
    sessions.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    return sessions


def log_token_usage(tokens: int) -> None:
    try:
        with open(TOKEN_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "tokens": tokens}) + "\n")
    except Exception as exc:
        print(f"[dependencies] Could not log token usage: {exc}")


def get_token_usage_windows() -> dict[str, int]:
    now = datetime.now(timezone.utc)
    last_5h = 0
    last_24h = 0
    if TOKEN_LOG_PATH.exists():
        try:
            with open(TOKEN_LOG_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts = datetime.fromisoformat(entry["ts"])
                        tokens = int(entry.get("tokens", 0))
                    except Exception:
                        continue
                    age_hours = (now - ts).total_seconds() / 3600
                    if age_hours <= 24:
                        last_24h += tokens
                        if age_hours <= 5:
                            last_5h += tokens
        except Exception as exc:
            print(f"[dependencies] Could not read token usage log: {exc}")
    return {"last_5h": last_5h, "last_24h": last_24h}

