import os
import pkgutil
import importlib
import importlib.util
from pathlib import Path

ALL_TOOLS = []
AUDIT_LOG_DIR = None  # set this if your tools use it

_tools_dir = os.path.dirname(__file__)

for _, module_name, _ in pkgutil.iter_modules([_tools_dir]):
    try:
        module = importlib.import_module(f'tools.{module_name}')
        if hasattr(module, module_name):
            ALL_TOOLS.append(getattr(module, module_name))
    except Exception as e:
        print(f"[tools/__init__.py] Failed to load {module_name}: {e}")

# ── User custom tools (loaded from disk at runtime) ───────────────────────
# Works for both dev and MSI users
CUSTOM_TOOLS_DIR = Path.home() / ".myagent" / "tools"
CUSTOM_TOOLS_DIR.mkdir(parents=True, exist_ok=True)

for py_file in CUSTOM_TOOLS_DIR.glob("*.py"):
    module_name = py_file.stem
    if module_name.startswith('_'):
        continue
    try:
        spec   = importlib.util.spec_from_file_location(module_name, py_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, module_name):
            ALL_TOOLS.append(getattr(module, module_name))
            print(f"[tools] Loaded custom tool: {module_name}")
        else:
            print(f"[tools] No function named '{module_name}' found in {py_file.name}")
    except Exception as e:
        print(f"[tools] Failed to load custom tool {module_name}: {e}")

# AUDIT_LOG_DIR used by main.py for /logs command
AUDIT_LOG_DIR = Path.home() / "agent_audit_logs"