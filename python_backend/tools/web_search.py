import sys
import subprocess
from langchain_core.tools import tool

def _ensure_ddgs():
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ddgs"], timeout=60)
        from ddgs import DDGS
        return DDGS

@tool
def web_search(query: str, max_results: int = 8) -> str:
    """
    Search the web using DuckDuckGo. Returns titles, URLs, and snippets.
    Use for live information: news, prices, docs, anything not in LLM training data.
    Auto-installs ddgs if missing.
    """
    try:
        DDGS = _ensure_ddgs()
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query.strip(), max_results=max_results):
                results.append(
                    f"Title  : {r.get('title', '')}\n"
                    f"URL    : {r.get('href', '')}\n"
                    f"Snippet: {r.get('body', '')}"
                )
        if not results:
            return "No results found."
        return f"Search: {query}\n\n" + "\n\n─────\n\n".join(results)
    except Exception as exc:
        return f"ERROR searching: {exc}"