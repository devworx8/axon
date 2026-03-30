"""
Axon Browser Bridge — Playwright CDP bridge for browser automation.

Starts a headless or headed Chromium instance on demand,
connects via Chrome DevTools Protocol, and executes approved
browser actions (click, scroll, type, navigate, screenshot, inspect).

Usage:
    bridge = BrowserBridge()
    await bridge.start(headless=False)
    result = await bridge.execute_action({
        "action_type": "navigate",
        "url": "https://example.com",
    })
    await bridge.stop()
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

_log = logging.getLogger("axon.browser_bridge")

# Lazy playwright import — only needed when bridge is active
_playwright: Optional[Playwright] = None
_lock = asyncio.Lock()
_ALLOWED_ACTION_TYPES = {
    "navigate",
    "click",
    "type",
    "scroll",
    "screenshot",
    "inspect",
    "wait",
    "go_back",
    "go_forward",
    "evaluate",
}
_READ_ONLY_EVAL_DENY_RE = re.compile(
    r"""
    (?:
        (?<![=!<>])=(?!=|>) |
        \b(?:let|const|var|function|async|await|delete|fetch|XMLHttpRequest)\b |
        \b(?:document\.write|window\.open|postMessage|dispatchEvent)\b |
        \.(?:append|prepend|remove|replaceWith|click|submit|focus|blur|fill|type|setAttribute)\s*\( |
        \b(?:localStorage|sessionStorage)\.setItem\s*\( |
        \b(?:history\.(?:pushState|replaceState))\s*\( |
        \b(?:window|document|location)\.location\s*=
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


async def _ensure_playwright():
    """Lazy-import and start playwright."""
    global _playwright
    if _playwright is not None:
        return
    try:
        from playwright.async_api import async_playwright
        _playwright = await async_playwright().start()
    except ImportError:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        )


def _is_safe_read_only_evaluate(script: str) -> bool:
    sample = str(script or "").strip()
    if not sample or len(sample) > 1200:
        return False
    if _READ_ONLY_EVAL_DENY_RE.search(sample):
        return False
    return any(marker in sample.lower() for marker in ("document", "window", "location", "queryselector", "innertext"))


class BrowserBridge:
    """Manages a single browser instance for Axon browser actions."""

    def __init__(self) -> None:
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._cached_title: str = ""
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started and self._browser is not None

    @property
    def current_url(self) -> str:
        if self._page:
            try:
                return self._page.url
            except Exception:
                return ""
        return ""

    @property
    def current_title(self) -> str:
        if self._page:
            try:
                # Use a cached title — don't await here
                return getattr(self, '_cached_title', '')
            except Exception:
                return ""
        return ""

    async def start(self, headless: bool = False, proxy: Optional[dict[str, str]] = None):
        """Launch browser. Pass proxy={"server": "socks5://..."} for proxy."""
        async with _lock:
            if self._started:
                return
            await _ensure_playwright()
            launch_opts: dict[str, Any] = {"headless": headless}
            if proxy:
                launch_opts["proxy"] = proxy
            assert _playwright is not None
            self._browser = await _playwright.chromium.launch(**launch_opts)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Axon/1.0",
            )
            self._page = await self._context.new_page()
            self._started = True
            _log.info("Browser bridge started (headless=%s)", headless)

    async def stop(self):
        """Shut down the browser."""
        global _playwright
        async with _lock:
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
            if _playwright:
                try:
                    await _playwright.stop()
                except Exception:
                    pass
                _playwright = None
            self._browser = None
            self._context = None
            self._page = None
            self._cached_title = ""
            self._started = False
            _log.info("Browser bridge stopped")

    async def execute_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a browser action. Returns {"success": bool, "result": str, "screenshot": str|None}.

        Supported action_types:
            navigate, click, type, scroll, screenshot, inspect, wait,
            go_back, go_forward, evaluate
        """
        if not self._started or not self._page:
            return {"success": False, "result": "Browser not started. Call start() first.", "screenshot": None}

        action_type = action.get("action_type", "").lower()
        target = action.get("target", "")
        value = action.get("value", "")
        url = action.get("url", "")
        if action_type not in _ALLOWED_ACTION_TYPES:
            return {"success": False, "result": f"Unknown action_type: {action_type}", "screenshot": None}

        try:
            if action_type == "navigate":
                nav_url = url or target
                if not nav_url.startswith(("http://", "https://")):
                    nav_url = "https://" + nav_url
                await self._page.goto(nav_url, wait_until="domcontentloaded", timeout=30000)
                self._cached_title = await self._page.title()
                return {"success": True, "result": f"Navigated to {self._page.url}", "screenshot": None}

            elif action_type == "click":
                if target:
                    await self._page.click(target, timeout=10000)
                    await self._page.wait_for_load_state("domcontentloaded", timeout=5000)
                    return {"success": True, "result": f"Clicked: {target}", "screenshot": None}
                return {"success": False, "result": "No target selector provided", "screenshot": None}

            elif action_type == "type":
                if target and value:
                    await self._page.fill(target, value, timeout=10000)
                    return {"success": True, "result": f"Typed into {target}", "screenshot": None}
                return {"success": False, "result": "Need target selector and value", "screenshot": None}

            elif action_type == "scroll":
                direction = value or "down"
                pixels = int(action.get("pixels", 500))
                if direction == "down":
                    await self._page.evaluate(f"window.scrollBy(0, {pixels})")
                elif direction == "up":
                    await self._page.evaluate(f"window.scrollBy(0, -{pixels})")
                elif direction == "top":
                    await self._page.evaluate("window.scrollTo(0, 0)")
                elif direction == "bottom":
                    await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                return {"success": True, "result": f"Scrolled {direction} {pixels}px", "screenshot": None}

            elif action_type == "screenshot":
                img_bytes = await self._page.screenshot(full_page=False, type="png")
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                return {"success": True, "result": f"Screenshot of {self._page.url}", "screenshot": b64}

            elif action_type == "inspect":
                # Return page structure summary
                result = await self._page.evaluate("""() => {
                    const title = document.title;
                    const url = window.location.href;
                    const links = [...document.querySelectorAll('a[href]')].slice(0, 20).map(a => ({text: a.textContent?.trim().slice(0, 60), href: a.href}));
                    const buttons = [...document.querySelectorAll('button, input[type="submit"]')].slice(0, 15).map(b => b.textContent?.trim().slice(0, 60) || b.value || '(unnamed)');
                    const inputs = [...document.querySelectorAll('input, textarea, select')].slice(0, 15).map(i => ({type: i.type, name: i.name || '', placeholder: i.placeholder || ''}));
                    const headings = [...document.querySelectorAll('h1,h2,h3')].slice(0, 10).map(h => h.textContent?.trim().slice(0, 80));
                    const text = document.body?.innerText?.slice(0, 2000) || '';
                    return {title, url, links, buttons, inputs, headings, textPreview: text};
                }""")
                return {"success": True, "result": result, "screenshot": None}

            elif action_type == "wait":
                ms = int(value or 1000)
                ms = min(ms, 10000)  # Cap at 10s
                await asyncio.sleep(ms / 1000)
                return {"success": True, "result": f"Waited {ms}ms", "screenshot": None}

            elif action_type == "go_back":
                await self._page.go_back(wait_until="domcontentloaded", timeout=10000)
                return {"success": True, "result": f"Went back to {self._page.url}", "screenshot": None}

            elif action_type == "go_forward":
                await self._page.go_forward(wait_until="domcontentloaded", timeout=10000)
                return {"success": True, "result": f"Went forward to {self._page.url}", "screenshot": None}

            elif action_type == "evaluate":
                if not value:
                    return {"success": False, "result": "No JavaScript expression provided", "screenshot": None}
                if not _is_safe_read_only_evaluate(value):
                    return {"success": False, "result": "Unsafe evaluate payload blocked. Use inspect or an approved browser action instead.", "screenshot": None}
                result = await self._page.evaluate(value)
                return {"success": True, "result": str(result)[:5000], "screenshot": None}

        except Exception as exc:
            return {"success": False, "result": f"Action failed: {exc}", "screenshot": None}

    async def get_page_text(self, max_chars: int = 5000) -> str:
        """Get visible text content of the current page."""
        if not self._page:
            return ""
        try:
            text = await self._page.evaluate("document.body?.innerText || ''")
            return text[:max_chars]
        except Exception:
            return ""

    def status(self) -> dict[str, Any]:
        return {
            "running": self.is_running,
            "url": self.current_url,
            "title": self.current_title,
        }


# Module-level singleton
_bridge_instance: Optional[BrowserBridge] = None


def get_bridge() -> BrowserBridge:
    """Get or create the singleton browser bridge."""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = BrowserBridge()
    return _bridge_instance
