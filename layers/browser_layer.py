"""
Browser preview layer using Playwright.
Manages a local dev server process + browser for screenshots.
Includes console log capture, interactive testing, and video recording.
"""
import asyncio
import os
import sys
import subprocess
import time
import tempfile
from pathlib import Path
from typing import Optional

_PYTHON = sys.executable

_browser = None
_page = None
_dev_proc: Optional[subprocess.Popen] = None
_dev_url: Optional[str] = None

# Console log buffer: list of {"level": str, "text": str, "timestamp": float}
# Logs persist across navigations — only cleared explicitly via get_console_logs(clear=True)
_console_logs: list[dict] = []
_console_capture_active: bool = False
_network_errors: list[dict] = []

# ── Dev server management ────────────────────────────────────────────────────

def _extract_flask_port(file_path: Path) -> int:
    """Read a Python file and extract the port from app.run(port=N) or similar."""
    import re
    try:
        text = file_path.read_text(errors="ignore")
        # Match: app.run(port=5025), uvicorn.run(app, port=5025), PORT=5025, --port 5025
        patterns = [
            r'["\']?port["\']?\s*[=:]\s*(\d{4,5})',   # port=5025 / port: 5025
            r'--port[=\s]+(\d{4,5})',                   # --port 5025
            r'\bPORT\s*=\s*(\d{4,5})',                  # PORT = 5025
            r'\.run\([^)]*?(\d{4,5})[^)]*\)',           # app.run("0.0.0.0", 5025)
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return 5000  # Flask default


def _detect_flask_app(p: Path):
    """Return (app_file, venv_python, port) for a Flask/FastAPI project, or None."""
    import re
    for fname in ("app.py", "main.py", "run.py", "server.py", "wsgi.py"):
        candidate = p / fname
        if not candidate.exists():
            # Check one subdir deep
            for sub in sorted(p.iterdir()):
                if sub.is_dir() and (sub / fname).exists():
                    candidate = sub / fname
                    p = sub
                    break
            else:
                continue
        text = candidate.read_text(errors="ignore")
        if not re.search(r'\bfrom\s+flask\b|\bimport\s+flask\b|\bfastapi\b|\bFlask\b|\bFastAPI\b', text, re.IGNORECASE):
            continue
        port = _extract_flask_port(candidate)
        # Prefer venv python if present
        venv_python = next(
            (str(v) for v in [p / "venv/bin/python", p / ".venv/bin/python"] if v.exists()),
            _PYTHON,
        )
        return str(candidate), venv_python, port, str(p)
    return None


def _detect_start_cmd(project_path: str) -> tuple[str, str, int]:
    """
    Auto-detect frontend project and how to serve it.
    Searches subdirectories if no frontend found at root.
    Returns (cmd, url, port).
    """
    p = Path(project_path)

    # Find the actual frontend root — check root then subdirs
    frontend_root = None
    for candidate in [p] + sorted(p.iterdir()) if p.is_dir() else [p]:
        if not candidate.is_dir():
            continue
        if (candidate / "package.json").exists():
            frontend_root = candidate
            break
        if (candidate / "index.html").exists():
            frontend_root = candidate
            break

    if frontend_root and (frontend_root / "package.json").exists():
        fp = str(frontend_root)
        if not (frontend_root / "node_modules").exists():
            print(f"[browser] installing npm deps in {fp}")
            subprocess.run("npm install", shell=True, cwd=fp,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pkg = (frontend_root / "package.json").read_text()
        if "next" in pkg:
            return f"cd {fp} && npm run dev", "http://localhost:3000", 3000
        if "vite" in pkg:
            return f"cd {fp} && npm run dev -- --host", "http://localhost:5173", 5173
        if "react-scripts" in pkg:
            return f"cd {fp} && npm start", "http://localhost:3000", 3000
        return f"cd {fp} && npm run dev", "http://localhost:3000", 3000

    if (p / "manage.py").exists():
        return f"{_PYTHON} manage.py runserver 8001", "http://localhost:8001", 8001

    # Flask / FastAPI detection
    flask_info = _detect_flask_app(p)
    if flask_info:
        app_file, venv_py, port, app_dir = flask_info
        print(f"[browser] detected Flask/FastAPI app: {app_file} on port {port}")
        return f"cd {app_dir} && {venv_py} {Path(app_file).name}", f"http://localhost:{port}", port

    # Static HTML — find best HTML file to serve
    serve_dir = frontend_root or p
    html_files = sorted(serve_dir.glob("*.html"))
    if not html_files:
        # Search one level deep
        html_files = sorted(p.glob("**/*.html"))
        if html_files:
            serve_dir = html_files[0].parent

    if html_files:
        # Prefer index.html, otherwise use first html file
        index = next((f for f in html_files if f.name == "index.html"), html_files[0])
        page = "" if index.name == "index.html" else f"/{index.name}"
        return (f"{_PYTHON} -m http.server 8080 --directory {serve_dir}",
                f"http://localhost:8080{page}", 8080)

    return f"{_PYTHON} -m http.server 8080 --directory {project_path}", "http://localhost:8080", 8080


_dev_project: str = ""  # track which project the server is for

async def start_server(project_path: str, custom_url: str = None) -> str:
    global _dev_proc, _dev_url, _dev_project
    # Reuse only if same project and still running
    if _dev_proc and _dev_proc.poll() is None and _dev_project == project_path:
        print(f"[browser] reusing server at {_dev_url}")
        return _dev_url
    # Kill old server if different project
    if _dev_proc and _dev_proc.poll() is None:
        _dev_proc.terminate()
        _dev_proc = None

    cmd, url, port = _detect_start_cmd(project_path)
    _dev_url = custom_url or url
    _dev_project = project_path

    # Auto-install Python requirements before starting a Python server
    p = Path(project_path)
    req_file = p / "requirements.txt"
    if not req_file.exists():
        # Search one level deep
        for sub in p.iterdir():
            if sub.is_dir() and (sub / "requirements.txt").exists():
                req_file = sub / "requirements.txt"
                break
    if req_file.exists():
        print(f"[browser] installing requirements from {req_file}")
        subprocess.run(
            f"{_PYTHON} -m pip install -r {req_file} -q --break-system-packages",
            shell=True, capture_output=True, timeout=120,
        )

    print(f"[browser] starting server: {cmd} in {project_path}")
    import tempfile as _tf
    _stderr_file = _tf.NamedTemporaryFile(delete=False, suffix=".log", mode="w")
    _dev_proc = subprocess.Popen(
        cmd, shell=True, cwd=project_path,
        stdout=subprocess.DEVNULL, stderr=_stderr_file,
    )
    _stderr_file.close()
    _stderr_path = _stderr_file.name

    # Wait for port to open (up to 45s)
    import socket
    ready = False
    for i in range(45):
        await asyncio.sleep(1)
        # Check if process already died
        if _dev_proc.poll() is not None:
            try:
                crash_log = open(_stderr_path).read()[-1000:]
            except Exception:
                crash_log = "(no output)"
            print(f"[browser] server process died after {i+1}s:\n{crash_log}")
            raise RuntimeError(f"Dev server crashed on startup:\n{crash_log}")
        try:
            s = socket.create_connection(("localhost", port), timeout=1)
            s.close()
            ready = True
            print(f"[browser] port {port} open after {i+1}s")
            break
        except OSError:
            pass

    if not ready:
        try:
            crash_log = open(_stderr_path).read()[-1000:]
        except Exception:
            crash_log = "(no output)"
        print(f"[browser] WARNING: port {port} never opened. stderr:\n{crash_log}")
        raise RuntimeError(f"Dev server did not start (port {port} never opened):\n{crash_log}")

    # Extra wait for JS bundlers to finish compiling
    await asyncio.sleep(3)

    # Verify the server is actually returning HTML content (not blank/JSON)
    import urllib.request
    import urllib.error
    for attempt in range(5):
        try:
            req = urllib.request.Request(_dev_url, headers={"Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                content_type = resp.headers.get("Content-Type", "")
                body_preview = resp.read(512).decode(errors="ignore")
                is_html = "html" in content_type.lower() or body_preview.strip().startswith(("<", "<!"))
                print(f"[browser] server response: ct={content_type!r} html={is_html} preview={body_preview[:80]!r}")
                if is_html:
                    break
                # JSON or empty response — wait for app to fully start
                await asyncio.sleep(2)
        except Exception as e:
            print(f"[browser] server probe attempt {attempt+1}: {e}")
            await asyncio.sleep(2)

    return _dev_url


async def stop_server():
    global _dev_proc, _dev_url
    if _dev_proc:
        _dev_proc.terminate()
        _dev_proc = None
        _dev_url = None


# ── Browser management ───────────────────────────────────────────────────────

async def _ensure_browser():
    global _browser, _page
    from playwright.async_api import async_playwright
    if _browser is None:
        pw = await async_playwright().start()
        _browser = await pw.chromium.launch(headless=True)
    if _page is None or _page.is_closed():
        _page = await _browser.new_page(viewport={"width": 1440, "height": 900})
        _setup_console_capture(_page, clear=True)
    return _page


# ── Console log capture ──────────────────────────────────────────────────────

def _setup_console_capture(page, clear: bool = False):
    """Attach console/network/crash listeners to a page.
    Logs persist across navigations — only cleared when explicitly requested."""
    global _console_capture_active
    if clear:
        _console_logs.clear()
        _network_errors.clear()
    _console_capture_active = True

    def _on_console(msg):
        _console_logs.append({
            "level": msg.type,
            "text": msg.text,
            "timestamp": time.time(),
        })

    def _on_page_error(error):
        _console_logs.append({
            "level": "error",
            "text": f"[PAGE ERROR] {error}",
            "timestamp": time.time(),
        })

    def _on_request_failed(request):
        failure = request.failure
        entry = {
            "level": "error",
            "text": f"[NETWORK FAIL] {request.method} {request.url} → {failure}",
            "timestamp": time.time(),
        }
        _console_logs.append(entry)
        _network_errors.append(entry)

    def _on_crash():
        _console_logs.append({
            "level": "error",
            "text": "[PAGE CRASH] The page crashed — likely out of memory or fatal JS error",
            "timestamp": time.time(),
        })

    def _on_load():
        _console_logs.append({
            "level": "info",
            "text": f"[NAV] Page loaded: {page.url}",
            "timestamp": time.time(),
        })

    page.on("console", _on_console)
    page.on("pageerror", _on_page_error)
    page.on("requestfailed", _on_request_failed)
    page.on("crash", _on_crash)
    page.on("load", _on_load)


def get_console_logs(clear: bool = False) -> list[dict]:
    """Return captured console logs (including network errors). Optionally clear the buffer."""
    logs = list(_console_logs)
    if clear:
        _console_logs.clear()
        _network_errors.clear()
    return logs


def format_console_logs(logs: list[dict] = None, max_lines: int = 50) -> str:
    """Format console logs into a readable string."""
    entries = logs if logs is not None else _console_logs
    if not entries:
        return "(no console output)"

    icons = {"log": "📝", "warn": "⚠️", "error": "❌", "info": "ℹ️", "debug": "🔍"}
    lines = []
    for entry in entries[-max_lines:]:
        icon = icons.get(entry["level"], "•")
        text = entry["text"][:200]
        lines.append(f"{icon} [{entry['level']}] {text}")
    return "\n".join(lines)


async def screenshot(url: str = None, full_page: bool = False) -> bytes:
    page = await _ensure_browser()
    # Clear stale logs from previous sessions before capturing new ones
    get_console_logs(clear=True)
    target = url or _dev_url or "http://localhost:3000"
    print(f"[browser] navigating to {target}")

    # Single navigation — no double-load that clears console
    nav_error = None
    try:
        await page.goto(target, wait_until="networkidle", timeout=30000)
    except Exception as e1:
        # Fallback: some pages never reach networkidle (streaming, websockets)
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=15000)
        except Exception as e2:
            nav_error = str(e2)
            print(f"[browser] navigation fallback: {e2}")

    # Hard fail on connection refused — don't send a blank screenshot
    if nav_error and "ERR_CONNECTION_REFUSED" in nav_error:
        raise RuntimeError(f"Cannot connect to {target} — server is not running or crashed. Start it first.\n{nav_error}")

    # Wait for JS frameworks to do initial render
    await asyncio.sleep(3)

    # Try to wait for visible content — SPA root elements or any child of body
    for selector in ("#root > *", "#app > *", "main", "body > div", "body > section", "body > *:not(script):not(style):not(link)"):
        try:
            await page.wait_for_selector(selector, state="visible", timeout=3000)
            print(f"[browser] content visible via selector: {selector}")
            break
        except Exception:
            continue

    # Diagnose blank page
    try:
        body_text = await page.inner_text("body")
        body_html = await page.inner_html("body")
        text_len = len(body_text.strip())
        html_len = len(body_html.strip())
        print(f"[browser] body text_len={text_len} html_len={html_len}")

        if text_len < 10 and html_len < 100:
            # Truly empty — page didn't load or app crashed
            print("[browser] page appears completely blank, waiting 6s more...")
            await asyncio.sleep(6)
        elif text_len < 10 and html_len >= 100:
            # HTML structure exists but no visible text — SPA still rendering
            print("[browser] SPA container exists but no text yet, waiting 4s more...")
            await asyncio.sleep(4)
            # One more check — force a reflow
            try:
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass
            await asyncio.sleep(1)
    except Exception:
        await asyncio.sleep(2)

    # Give async errors a moment to fire
    await asyncio.sleep(0.5)

    img = await page.screenshot(full_page=full_page)
    print(f"[browser] screenshot done {len(img)} bytes")

    # If screenshot is suspiciously small (< 5KB for 1440x900), it's likely blank white
    if len(img) < 5000:
        print("[browser] screenshot looks blank (< 5KB), waiting 5s and retrying...")
        await asyncio.sleep(5)
        img = await page.screenshot(full_page=full_page)
        print(f"[browser] retry screenshot {len(img)} bytes")

    return img


async def screenshot_with_console(url: str = None, full_page: bool = False) -> tuple[bytes, str]:
    """Take screenshot and return console logs captured during page load."""
    img = await screenshot(url, full_page)
    await asyncio.sleep(1)
    logs = format_console_logs()
    return img, logs


async def screenshot_mobile(url: str = None) -> bytes:
    from playwright.async_api import async_playwright
    target = url or _dev_url or "http://localhost:3000"
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(
        viewport={"width": 390, "height": 844},
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        device_scale_factor=3.0,
    )
    page = await ctx.new_page()
    _setup_console_capture(page)
    await page.goto(target, wait_until="networkidle", timeout=15000)
    await asyncio.sleep(1)
    img = await page.screenshot(full_page=False)
    await browser.close()
    return img


async def scroll(pixels: int = 500, url: str = None) -> bytes:
    page = await _ensure_browser()
    if url:
        await page.goto(url, wait_until="networkidle", timeout=15000)
    await page.evaluate(f"window.scrollBy(0, {pixels})")
    await asyncio.sleep(0.5)
    return await page.screenshot()


async def click(selector: str) -> bytes:
    page = await _ensure_browser()
    await page.click(selector, timeout=5000)
    await _wait_for_stable(page)
    return await page.screenshot()


async def navigate(url: str) -> bytes:
    page = await _ensure_browser()
    try:
        await page.goto(url, wait_until="networkidle", timeout=15000)
    except Exception:
        await page.goto(url, wait_until="domcontentloaded", timeout=10000)
    await asyncio.sleep(1.5)
    return await page.screenshot()


async def _wait_for_stable(page, timeout_ms: int = 3000):
    """Wait for the page to become stable after an action.
    Handles cases where an action causes navigation/refresh."""
    try:
        # Wait for any triggered navigation to settle
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        # Brief pause for async JS (React re-renders, API calls, error handlers)
        await asyncio.sleep(1.0)
        # Check if network is idle (short timeout — don't block forever)
        try:
            await page.wait_for_load_state("networkidle", timeout=2000)
        except Exception:
            pass
    except Exception:
        # Page might have navigated away — just wait
        await asyncio.sleep(1.5)


# ── Interactive testing actions ──────────────────────────────────────────────

async def fill_input(selector: str, value: str) -> bytes:
    """Fill a text input/textarea."""
    page = await _ensure_browser()
    await page.fill(selector, value, timeout=5000)
    await asyncio.sleep(0.5)
    return await page.screenshot()


async def select_option(selector: str, value: str) -> bytes:
    """Select an option from a <select> dropdown."""
    page = await _ensure_browser()
    await page.select_option(selector, value, timeout=5000)
    await _wait_for_stable(page)
    return await page.screenshot()


async def upload_file(selector: str, file_path: str) -> bytes:
    """Upload a file to a file input."""
    page = await _ensure_browser()
    await page.set_input_files(selector, file_path, timeout=5000)
    await _wait_for_stable(page, timeout_ms=5000)
    return await page.screenshot()


async def type_text(selector: str, text: str, delay: int = 50) -> bytes:
    """Type text character by character (simulates real typing)."""
    page = await _ensure_browser()
    await page.click(selector, timeout=5000)
    await page.type(selector, text, delay=delay)
    await asyncio.sleep(0.3)
    return await page.screenshot()


async def press_key(key: str) -> bytes:
    """Press a keyboard key (Enter, Tab, Escape, etc.)."""
    page = await _ensure_browser()
    await page.keyboard.press(key)
    await _wait_for_stable(page)
    return await page.screenshot()


async def wait_for_selector(selector: str, timeout: int = 10000) -> bool:
    """Wait for an element to appear on the page."""
    page = await _ensure_browser()
    try:
        await page.wait_for_selector(selector, timeout=timeout)
        return True
    except Exception:
        return False


async def get_page_text() -> str:
    """Get all visible text content from the page."""
    page = await _ensure_browser()
    try:
        return await page.inner_text("body")
    except Exception:
        return ""


async def evaluate_js(script: str) -> str:
    """Run arbitrary JavaScript in the page and return the result."""
    page = await _ensure_browser()
    try:
        result = await page.evaluate(script)
        return str(result) if result is not None else "(undefined)"
    except Exception as e:
        return f"[js error: {e}]"


# ── Page health audit ────────────────────────────────────────────────────────

_PAGE_AUDIT_JS = """() => {
    const issues = [];
    const info = [];

    // 1. Dead links: <a> with no real href or href="#"
    document.querySelectorAll('a').forEach(a => {
        const href = (a.getAttribute('href') || '').trim();
        const text = (a.textContent || '').trim().slice(0, 40);
        if (!href || href === '#' || href === 'javascript:void(0)' || href === 'javascript:;') {
            if (text) issues.push('DEAD_LINK: "' + text + '" → href="' + href + '"');
        }
    });

    // 2. Dead buttons: buttons with no onclick, no form, no type=submit, and no framework listeners
    document.querySelectorAll('button, [role="button"], input[type="button"]').forEach(btn => {
        const text = (btn.textContent || btn.value || '').trim().slice(0, 40);
        if (!text) return;
        const hasClick = btn.onclick !== null;
        const hasAttr = btn.hasAttribute('onclick') || btn.hasAttribute('ng-click') || btn.hasAttribute('@click') || btn.hasAttribute('v-on:click');
        const inForm = btn.closest('form') !== null;
        const isSubmit = btn.type === 'submit';
        // Check for React/framework event listeners (heuristic: __reactFiber, __vue__, etc.)
        const hasFramework = Object.keys(btn).some(k => k.startsWith('__react') || k.startsWith('__vue'));
        if (!hasClick && !hasAttr && !inForm && !isSubmit && !hasFramework) {
            issues.push('DEAD_BUTTON: "' + text + '" — no click handler detected');
        }
    });

    // 3. Broken images
    document.querySelectorAll('img').forEach(img => {
        if (!img.complete || img.naturalWidth === 0) {
            const src = (img.src || img.getAttribute('src') || '').slice(0, 80);
            issues.push('BROKEN_IMG: ' + src + (img.alt ? ' (alt="' + img.alt + '")' : ''));
        }
    });

    // 4. Orphaned forms: no action and no submit handler
    document.querySelectorAll('form').forEach(form => {
        const action = (form.getAttribute('action') || '').trim();
        const hasSubmit = form.onsubmit !== null || form.hasAttribute('onsubmit') || form.hasAttribute('@submit') || form.hasAttribute('v-on:submit');
        const hasFramework = Object.keys(form).some(k => k.startsWith('__react') || k.startsWith('__vue'));
        if (!action && !hasSubmit && !hasFramework) {
            const inputs = form.querySelectorAll('input, textarea, select').length;
            issues.push('ORPHAN_FORM: form with ' + inputs + ' inputs but no action/submit handler');
        }
    });

    // 5. Empty containers that likely should have content
    document.querySelectorAll('main, [role="main"], .content, .container, #app, #root, [data-page], [data-content]').forEach(el => {
        const text = (el.textContent || '').trim();
        const children = el.children.length;
        if (text.length < 5 && children < 2) {
            const id = el.id ? '#' + el.id : (el.className ? '.' + el.className.split(' ')[0] : el.tagName.toLowerCase());
            issues.push('EMPTY_CONTAINER: ' + id + ' appears empty (likely failed render)');
        }
    });

    // 6. Hidden interactive elements (might indicate UI bugs)
    document.querySelectorAll('button, a, input, select, textarea').forEach(el => {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        const text = (el.textContent || el.value || el.placeholder || '').trim().slice(0, 30);
        if (!text) return;
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
            // Skip if inside a dialog/modal that's meant to be hidden
            if (el.closest('dialog, [role="dialog"], .modal, [data-modal]')) return;
            issues.push('HIDDEN_INTERACTIVE: "' + text + '" is invisible (' + style.display + '/' + style.visibility + '/' + style.opacity + ')');
        }
        if (rect.width === 0 || rect.height === 0) {
            issues.push('ZERO_SIZE: "' + text + '" has 0 dimensions');
        }
    });

    // 7. Overlapped clickable elements (check if top element at center matches)
    document.querySelectorAll('button, a[href], input[type="submit"]').forEach(el => {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) return;
        const top = document.elementFromPoint(cx, cy);
        if (top && top !== el && !el.contains(top) && !top.contains(el)) {
            const text = (el.textContent || '').trim().slice(0, 30);
            const blocker = top.tagName.toLowerCase() + (top.className ? '.' + top.className.split(' ')[0] : '');
            issues.push('OVERLAPPED: "' + text + '" blocked by ' + blocker);
        }
    });

    // 8. Error boundaries / fallback UIs (React)
    document.querySelectorAll('[data-error-boundary], .error-boundary, .error-fallback').forEach(el => {
        const text = (el.textContent || '').trim().slice(0, 60);
        if (text) issues.push('ERROR_BOUNDARY: ' + text);
    });

    // 9. Collect page info summary
    const title = document.title || '(no title)';
    const visibleText = (document.body.innerText || '').trim();
    info.push('title: ' + title);
    info.push('text_length: ' + visibleText.length);
    info.push('interactive_elements: ' + document.querySelectorAll('button, a, input, select, textarea').length);
    info.push('images: ' + document.querySelectorAll('img').length);
    info.push('forms: ' + document.querySelectorAll('form').length);

    // 10. Check for common "something went wrong" patterns in visible text
    const lower = visibleText.toLowerCase();
    const errorPatterns = ['something went wrong', 'error occurred', 'page not found', '404', 'cannot read', 'undefined', 'failed to load', 'loading...'];
    errorPatterns.forEach(p => {
        if (lower.includes(p) && visibleText.length < 500) {
            issues.push('PAGE_TEXT_ISSUE: page shows "' + p + '" (possible error state)');
        }
    });

    // Also flag if page says "Loading..." and nothing else rendered
    if (lower === 'loading...' || lower === 'loading') {
        issues.push('STUCK_LOADING: page appears stuck on loading state');
    }

    return { issues: issues.slice(0, 20), info: info, pexo_errors: window.__PEXO_ERRORS__ || [] };
}"""


async def audit_page(page=None) -> dict:
    """Run a comprehensive health audit on the current page.
    Returns {"issues": [...], "info": [...], "pexo_errors": [...]}"""
    if page is None:
        page = await _ensure_browser()
    try:
        result = await page.evaluate(_PAGE_AUDIT_JS)
        return result
    except Exception as e:
        return {"issues": [f"[audit error: {e}]"], "info": [], "pexo_errors": []}


def format_audit(audit: dict) -> str:
    """Format audit results into a string for Claude."""
    parts = []
    issues = audit.get("issues", [])
    info = audit.get("info", [])
    pexo = audit.get("pexo_errors", [])

    if issues:
        parts.append(f"⚠️ PAGE ISSUES ({len(issues)}):")
        for iss in issues:
            parts.append(f"  • {iss}")
    else:
        parts.append("✅ No page issues detected.")

    if pexo:
        parts.append(f"\n🔴 RUNTIME ERRORS ({len(pexo)}):")
        for e in pexo[:8]:
            if isinstance(e, dict):
                parts.append(f"  • [{e.get('type','?')}] {e.get('msg','')} {e.get('src','')}:{e.get('line','')}")
            else:
                parts.append(f"  • {e}")

    if info:
        parts.append(f"\nPage info: {' | '.join(info)}")

    return "\n".join(parts)


# ── Video recording ──────────────────────────────────────────────────────────

_recording_context = None
_recording_page = None
_video_dir = None


async def start_recording(url: str = None) -> str:
    """Start a new browser context with video recording enabled."""
    global _recording_context, _recording_page, _video_dir

    # Clean up any stale recording context
    if _recording_context is not None:
        try:
            await _recording_context.close()
        except Exception:
            pass
        _recording_context = None
        _recording_page = None

    _video_dir = tempfile.mkdtemp(prefix="pexo_video_")
    target = url or _dev_url or "http://localhost:3000"

    await _ensure_browser()  # guarantees _browser is set

    _recording_context = await _browser.new_context(
        viewport={"width": 1440, "height": 900},
        record_video_dir=_video_dir,
        record_video_size={"width": 1440, "height": 900},
    )
    _recording_page = await _recording_context.new_page()
    _setup_console_capture(_recording_page, clear=True)
    try:
        await _recording_page.goto(target, wait_until="networkidle", timeout=30000)
    except Exception:
        await _recording_page.goto(target, wait_until="domcontentloaded", timeout=15000)
    await asyncio.sleep(2)
    print(f"[browser] recording started → {_video_dir} at {target}")
    return target


async def _exec_action_on_page(page, action: str, step: dict) -> None:
    """Execute a single action on a page (shared between recording and non-recording flows)."""
    selector = step.get("selector", "")
    value = step.get("value", "")

    if action == "click":
        # Try primary selector, then fallbacks
        fallbacks = step.get("fallback_selectors", [])
        for sel in [selector] + fallbacks:
            try:
                await page.click(sel, timeout=4000)
                return
            except Exception:
                if sel == fallbacks[-1] if fallbacks else selector:
                    raise
        raise RuntimeError(f"click failed: no selector matched among {[selector]+fallbacks}")

    elif action == "fill":
        await page.fill(selector, value, timeout=5000)

    elif action == "type":
        await page.click(selector, timeout=5000)
        await page.type(selector, value, delay=step.get("delay", 30))

    elif action == "select":
        await page.select_option(selector, value, timeout=5000)

    elif action == "upload":
        await page.set_input_files(selector, step["file_path"], timeout=5000)

    elif action == "press":
        await page.keyboard.press(step.get("key", "Enter"))

    elif action == "navigate":
        nav_url = step.get("url", value)
        try:
            await page.goto(nav_url, wait_until="networkidle", timeout=15000)
        except Exception:
            await page.goto(nav_url, wait_until="domcontentloaded", timeout=10000)

    elif action == "scroll":
        await page.evaluate(f"window.scrollBy(0, {step.get('pixels', 500)})")

    elif action == "wait":
        await asyncio.sleep(step.get("seconds", 2))

    elif action == "hover":
        await page.hover(selector, timeout=5000)

    elif action == "assert_text":
        # Assert that selector contains expected text
        expected = step.get("expected", value)
        try:
            el_text = await page.inner_text(selector, timeout=5000)
        except Exception:
            raise AssertionError(f"selector '{selector}' not found on page")
        if expected.lower() not in el_text.lower():
            raise AssertionError(f"expected '{expected}' in '{el_text[:100]}', got no match")

    elif action == "assert_visible":
        # Assert that element is visible
        try:
            visible = await page.is_visible(selector, timeout=5000)
        except Exception:
            visible = False
        if not visible:
            raise AssertionError(f"element '{selector}' is not visible")

    elif action == "assert_url":
        # Assert current URL contains expected string
        expected = step.get("expected", value)
        current = page.url
        if expected not in current:
            raise AssertionError(f"URL '{current}' does not contain '{expected}'")

    elif action == "assert_not_text":
        # Assert that selector does NOT contain text (check for error messages etc)
        forbidden = step.get("expected", value)
        try:
            el_text = await page.inner_text(selector, timeout=3000)
            if forbidden.lower() in el_text.lower():
                raise AssertionError(f"found forbidden text '{forbidden}' in element")
        except AssertionError:
            raise
        except Exception:
            pass  # element not found = text not present = assertion passes

    elif action in ("screenshot", "capture"):
        pass  # just takes a screenshot, handled by caller

    else:
        raise ValueError(f"Unknown action: '{action}'")


async def stop_recording() -> str | None:
    """Stop recording, wait for video to finalize, return file path."""
    global _recording_context, _recording_page, _video_dir
    if _recording_context is None:
        return None

    # Capture video reference BEFORE closing context
    video = _recording_page.video if _recording_page else None
    page_ref = _recording_page

    _recording_context_ref = _recording_context
    _recording_context = None
    _recording_page = None

    try:
        await _recording_context_ref.close()
    except Exception as e:
        print(f"[browser] recording context close error: {e}")

    video_path = None
    if video:
        try:
            # await video.path() BLOCKS until Playwright finishes writing the file
            video_path = await video.path()
            print(f"[browser] recording finalized → {video_path}")
        except Exception as e:
            print(f"[browser] video.path() failed: {e}")
            # Fallback: glob for the file and wait a moment
            await asyncio.sleep(2)
            if _video_dir:
                files = list(Path(_video_dir).glob("*.webm"))
                if files:
                    video_path = str(files[0])

    return video_path


# ── Test flow runner ─────────────────────────────────────────────────────────

async def run_test_flow(
    url: str,
    steps: list[dict],
    record: bool = True,
    progress_cb=None,
    send_step_screenshots: callable = None,
) -> dict:
    """
    Run a sequence of browser test steps with per-step screenshots, assertions,
    console log capture, URL tracking, and optional video recording.

    Supported actions:
      click, fill, type, select, upload, press, navigate, scroll, wait, hover,
      screenshot, assert_text, assert_visible, assert_url, assert_not_text

    Each step dict:
      {
        "action": str,
        "selector": str,           # CSS selector (for most actions)
        "value": str,              # text to type/fill or expected value for asserts
        "expected": str,           # alias for value in assert actions
        "description": str,        # human-readable label shown in results
        "fallback_selectors": [],  # tried in order if primary selector fails
        "key": str,                # for press action
        "file_path": str,          # for upload action
        "url": str,                # for navigate action
        "pixels": int,             # for scroll action
        "seconds": float,          # for wait action
        "abort_on_fail": bool,     # default True for asserts, False for others
      }

    Returns:
      {
        "step_results": [{"step": int, "action": str, "desc": str, "ok": bool,
                          "error": str|None, "url_before": str, "url_after": str,
                          "console_errors": [str]}],
        "screenshots": [bytes],    # one per step (first = initial page)
        "console_logs": str,
        "video_path": str|None,
        "errors": [str],           # summary of failed steps
        "passed": int,
        "failed": int,
      }
    """
    screenshots = []
    step_results = []
    errors = []

    # Set up page
    if record:
        await start_recording(url)
        page_ref = _recording_page
    else:
        page_ref = await _ensure_browser()
        get_console_logs(clear=True)
        try:
            await page_ref.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            await page_ref.goto(url, wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(2)

    # Initial screenshot — baseline state
    initial_img = await page_ref.screenshot()
    screenshots.append(initial_img)
    if send_step_screenshots:
        await send_step_screenshots(initial_img, "🔍 Initial state")

    for i, step in enumerate(steps):
        action = step.get("action", "")
        desc = step.get("description") or f"Step {i+1}: {action} {step.get('selector','')}"
        url_before = page_ref.url
        step_errors_before = len([e for e in _console_logs if e["level"] == "error"])

        if progress_cb:
            progress_cb(f"🧪 [{i+1}/{len(steps)}] {desc}")

        ok = True
        error_msg = None

        try:
            await _exec_action_on_page(page_ref, action, step)
            await _wait_for_stable(page_ref)
        except AssertionError as e:
            ok = False
            error_msg = f"ASSERTION FAILED: {e}"
        except Exception as e:
            ok = False
            error_msg = str(e)

        url_after = page_ref.url

        # Capture screenshot after this step
        try:
            img = await page_ref.screenshot()
        except Exception:
            img = initial_img  # fallback to last known good screenshot
        screenshots.append(img)

        # Collect new console errors since this step started
        step_console_errors = [
            e["text"] for e in _console_logs[step_errors_before:]
            if e["level"] == "error"
        ]

        # If step passed but new console errors appeared, flag them
        if ok and step_console_errors:
            error_msg = f"Step passed but {len(step_console_errors)} console error(s) appeared"

        result = {
            "step": i + 1,
            "action": action,
            "desc": desc,
            "ok": ok,
            "error": error_msg,
            "url_before": url_before,
            "url_after": url_after,
            "url_changed": url_before != url_after,
            "console_errors": step_console_errors,
        }
        step_results.append(result)

        if not ok:
            errors.append(f"Step {i+1} ({action}): {error_msg}")

        # Send per-step screenshot to Discord
        if send_step_screenshots:
            status = "✅" if ok else "❌"
            caption = f"{status} Step {i+1}: {desc}"
            if url_before != url_after:
                caption += f"\n🔀 URL: {url_after}"
            if step_console_errors:
                caption += f"\n⚠️ {len(step_console_errors)} console error(s)"
            await send_step_screenshots(img, caption)

        # Abort on failed assertion (or abort_on_fail=True steps) — page is in broken state
        is_assert = action.startswith("assert_")
        abort = step.get("abort_on_fail", is_assert)
        if not ok and abort:
            if progress_cb:
                progress_cb(f"⛔ Aborting after step {i+1} failure: {error_msg}")
            errors.append(f"[ABORTED at step {i+1}]")
            break

    # Finalize video
    video_path = None
    if record:
        video_path = await stop_recording()

    console = format_console_logs()
    passed = sum(1 for r in step_results if r["ok"])
    failed = sum(1 for r in step_results if not r["ok"])

    return {
        "step_results": step_results,
        "screenshots": screenshots,
        "console_logs": console,
        "video_path": video_path,
        "errors": errors,
        "passed": passed,
        "failed": failed,
    }


async def close_browser():
    global _browser, _page
    if _browser:
        await _browser.close()
        _browser = None
        _page = None
