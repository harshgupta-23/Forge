import os
import re
import sys
import subprocess
from pathlib import Path
from langchain_core.tools import tool

os.environ["PLAYWRIGHT_LOOP_ALLOW_THREAD_SWITCH"] = "1"
_PLAYWRIGHT_INSTANCE = None
_PERSISTENT_CONTEXT = None

def _ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        print("  \033[90m[Installing playwright…]\033[0m", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "playwright"], timeout=120)
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], timeout=300)
        from playwright.sync_api import sync_playwright
        return sync_playwright

@tool
def browser_action(instructions: str) -> str:
    """
    Generalised browser automation via Playwright (Chromium).

    Pass plain-English instructions. Always include the full URL. Examples:
    - "Go to https://youtube.com and search for lo-fi music"
    - "Go to https://google.com and search for Python tutorials, return top 5 links"
    """
    global _PLAYWRIGHT_INSTANCE, _PERSISTENT_CONTEXT
    sync_playwright = _ensure_playwright()

    instr = instructions.strip()
    instr_lower = instr.lower()
    headless = os.environ.get("BROWSER_HEADLESS", "false").lower() != "false"

    url_match = re.search(r'https?://[^\s,]+', instr)
    start_url = url_match.group(0).rstrip(".,)") if url_match else None

    wants_search   = any(w in instr_lower for w in ["search for", "search ", "look up", "find "])
    wants_fill     = any(w in instr_lower for w in ["fill", "enter ", "type ", "input "])
    wants_click    = any(w in instr_lower for w in ["click", "press", "submit", "button"])
    wants_download = any(w in instr_lower for w in ["download", "save file", "get file"])
    wants_extract  = any(w in instr_lower for w in ["return", "get ", "extract", "list", "titles", "links", "text"])

    search_query = ""
    for pattern in [r"search for (.+?)(?:\s+on\b|\s+in\b|\s+at\b|,|$)", r"search (.+?)(?:\s+on\b|\s+in\b|\s+at\b|,|$)"]:
        m = re.search(pattern, instr, re.IGNORECASE)
        if m:
            search_query = m.group(1).strip().rstrip(",.")
            break

    field_pairs = re.findall(r'(\w[\w\s]*)=([^\s,]+)', instr)
    is_youtube = start_url and "youtube.com" in start_url
    is_google  = start_url and ("google.com" in start_url or start_url == "https://google.com")
    results    = []
    timeout_ms = 30_000

    try:
        if _PLAYWRIGHT_INSTANCE is None:
            _PLAYWRIGHT_INSTANCE = sync_playwright().start()

        p = _PLAYWRIGHT_INSTANCE
        user_data_dir = os.environ.get("CHROME_USER_DATA_DIR", "./chrome_profile")

        if _PERSISTENT_CONTEXT is None:
            try:
                print("  \033[90m[browser] Launching Chrome...\033[0m", flush=True)
                _PERSISTENT_CONTEXT = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel="chrome",
                    headless=headless,
                    viewport={"width": 1280, "height": 800},
                    accept_downloads=True,
                )
                results.append("Launched Chrome.")
            except Exception as e:
                print(f"  \033[91m[browser] Profile locked or Chrome not found: {e}\033[0m", flush=True)
                browser = p.chromium.launch(headless=headless)
                context = browser.new_context(viewport={"width": 1280, "height": 800}, accept_downloads=True)
                _PERSISTENT_CONTEXT = context
                results.append("WARNING: Using isolated Chromium instance (system Chrome unavailable).")

        context = _PERSISTENT_CONTEXT
        page = context.pages[0] if context.pages else context.new_page()

        if start_url:
            print(f"  \033[90m[browser] → {start_url}\033[0m", flush=True)
            page.goto(start_url, wait_until="domcontentloaded", timeout=timeout_ms)
            results.append(f"Navigated to: {page.url}")

        if wants_search and search_query:
            print(f"  \033[90m[browser] Searching: {search_query}\033[0m", flush=True)
            if is_youtube:
                search_selectors = ['input#search', 'input[name="search_query"]']
            elif is_google:
                search_selectors = ['textarea[name="q"]', 'input[name="q"]']
            else:
                search_selectors = ['input[name="q"]', 'input[type="search"]', 'textarea[name="q"]']

            typed = False
            for sel in search_selectors:
                try:
                    page.wait_for_selector(sel, timeout=4000)
                    page.click(sel)
                    page.fill(sel, search_query)
                    page.keyboard.press("Enter")
                    page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                    results.append(f"Searched for: '{search_query}'")
                    typed = True
                    break
                except Exception:
                    continue
            if not typed:
                results.append(f"WARNING: Could not find search box on {page.url}.")

        if wants_fill and field_pairs:
            for field_name, field_value in field_pairs:
                fn = field_name.strip().lower()
                for sel in [f'input[name="{fn}"]', f'input[placeholder*="{fn}" i]']:
                    try:
                        page.wait_for_selector(sel, timeout=2000)
                        page.fill(sel, field_value)
                        results.append(f"Filled {field_name}={field_value}")
                        break
                    except Exception:
                        continue

        if wants_click and not wants_search:
            btn_words = re.findall(r'click\s+(\w+)|press\s+(\w+)', instr, re.I)
            btn_text  = next((w for grp in btn_words for w in grp if w), "Submit")
            try:
                page.get_by_role("button", name=re.compile(btn_text, re.I)).first.click(timeout=5000)
                page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                results.append(f"Clicked: {btn_text}")
            except Exception:
                results.append(f"WARNING: Could not click '{btn_text}'")

        if wants_download:
            all_urls = re.findall(r'https?://[^\s,]+', instr)
            dl_url   = all_urls[-1] if all_urls else None
            save_dir = Path(os.environ.get("AGENT_WORK_DIR", str(Path.home() / "Downloads")))
            save_dir.mkdir(parents=True, exist_ok=True)
            if dl_url:
                with page.expect_download(timeout=60_000) as dl_info:
                    page.goto(dl_url, timeout=timeout_ms)
                dl        = dl_info.value
                save_path = save_dir / dl.suggested_filename
                dl.save_as(save_path)
                results.append(f"Downloaded: {save_path}")

        if wants_extract or not any([wants_search, wants_fill, wants_click, wants_download]):
            page.wait_for_timeout(1500)
            if "link" in instr_lower or "url" in instr_lower:
                links     = page.eval_on_selector_all("a[href]", "els => els.slice(0,20).map(e => ({text: e.innerText.trim(), href: e.href}))")
                extracted = [f"  [{l['text']}]({l['href']})" for l in links[:15] if l["text"] and l["href"].startswith("http")]
                results.append("Links:\n" + "\n".join(extracted))
            else:
                body = page.inner_text("body")
                if len(body) > 4000:
                    body = body[:4000] + "\n\n[...truncated...]"
                results.append(f"Page ({page.title()}):\n{body}")

        return "\n\n".join(results) if results else "Completed."

    except Exception as exc:
        return f"ERROR in browser_action: {exc}"