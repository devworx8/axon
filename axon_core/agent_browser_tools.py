"""Browser automation tools for the Axon agent ReAct loop.

Bounded context: browser tool definitions, argument normalization,
and async execution via the Playwright-based browser_bridge.

These tools let the agent navigate, screenshot, inspect, click,
type, scroll, and evaluate JavaScript in a live browser session.
Screenshots are saved to disk and their path is returned so the
agent loop can inject the image into vision-capable LLM context.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

_SCREENSHOT_DIR = Path("/tmp/axon_screenshots")

BROWSER_TOOL_NAMES: set[str] = {
    "browser_navigate",
    "browser_screenshot",
    "browser_inspect",
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_evaluate",
}

BROWSER_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": (
                "Navigate the browser to a URL. Auto-starts the browser if not running. "
                "Use for opening web pages, localhost dev servers, or HTML files served locally."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to navigate to (e.g. http://localhost:3000, https://example.com)"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": (
                "Take a screenshot of the current browser page. Returns a text description "
                "and saves the PNG to disk. The image is fed into your vision context so you "
                "can SEE the page and reason about layout, styles, and content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "full_page": {
                        "type": "boolean",
                        "description": "Capture full scrollable page (default: false, viewport only)",
                        "default": False,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_inspect",
            "description": (
                "Inspect the current page structure. Returns: title, URL, headings, links, "
                "buttons, inputs, and a text preview. Use to understand page layout and find "
                "CSS selectors for click/type actions."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an element on the page using a CSS selector. Use browser_inspect first to find selectors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the element to click (e.g. 'button.submit', '#login-btn', 'a[href=\"/about\"]')"},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Type text into an input field on the page. Uses CSS selector to target the input.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the input element"},
                    "text": {"type": "string", "description": "Text to type into the input"},
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "Scroll the page. Direction: up, down, top, bottom.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "top", "bottom"],
                        "description": "Scroll direction",
                        "default": "down",
                    },
                    "pixels": {"type": "integer", "description": "Pixels to scroll (default 500)", "default": 500},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_evaluate",
            "description": (
                "Run read-only JavaScript on the page and return the result. "
                "Useful for checking computed styles, element dimensions, data attributes, "
                "or any DOM state. Mutations are blocked for safety."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "JavaScript expression to evaluate (e.g. \"document.querySelector('.header').getBoundingClientRect()\")",
                    },
                },
                "required": ["expression"],
            },
        },
    },
]

# ── Argument normalization ────────────────────────────────────────────────────

_ARG_ALIASES: dict[str, dict[str, str]] = {
    "browser_navigate": {"target": "url", "page": "url", "address": "url", "href": "url"},
    "browser_click": {"target": "selector", "element": "selector", "css": "selector"},
    "browser_type": {"target": "selector", "element": "selector", "input": "selector", "value": "text", "content": "text"},
    "browser_scroll": {"dir": "direction", "amount": "pixels"},
    "browser_evaluate": {"script": "expression", "js": "expression", "code": "expression", "value": "expression"},
}

_ALLOWED_KEYS: dict[str, set[str]] = {
    "browser_navigate": {"url"},
    "browser_screenshot": {"full_page"},
    "browser_inspect": set(),
    "browser_click": {"selector"},
    "browser_type": {"selector", "text"},
    "browser_scroll": {"direction", "pixels"},
    "browser_evaluate": {"expression"},
}


def normalize_browser_tool_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Normalize and clean browser tool arguments."""
    normalized = dict(args or {})
    aliases = _ARG_ALIASES.get(name, {})
    for alias, canonical in aliases.items():
        if alias in normalized and canonical not in normalized:
            normalized[canonical] = normalized.pop(alias)
        else:
            normalized.pop(alias, None)
    allowed = _ALLOWED_KEYS.get(name, set())
    if allowed:
        normalized = {k: v for k, v in normalized.items() if k in allowed}
    return normalized


# ── Async executor ────────────────────────────────────────────────────────────

_SCREENSHOT_RESULT_PREFIX = "[BROWSER_SCREENSHOT_PATH:"


def is_screenshot_result(result: str) -> bool:
    """Check if a tool result contains a screenshot path for vision injection."""
    return _SCREENSHOT_RESULT_PREFIX in str(result or "")


def extract_screenshot_path(result: str) -> str | None:
    """Extract the screenshot file path from a tool result."""
    text = str(result or "")
    start = text.find(_SCREENSHOT_RESULT_PREFIX)
    if start < 0:
        return None
    start += len(_SCREENSHOT_RESULT_PREFIX)
    end = text.find("]", start)
    if end < 0:
        return None
    path = text[start:end].strip()
    return path if os.path.isfile(path) else None


def build_vision_tool_message(
    text: str,
    image_path: str,
    *,
    use_api: bool = False,
    use_cli: bool = False,
) -> dict[str, Any]:
    """Build a message dict with an inline screenshot for vision-capable LLMs.

    Returns the right format for the active backend:
    - API/CLI: OpenAI-style content array with image_url
    - Ollama: content + images list
    """
    import base64 as _b64

    try:
        with open(image_path, "rb") as fh:
            b64_data = _b64.b64encode(fh.read()).decode("utf-8")
    except Exception:
        return {"role": "user", "content": text}

    if use_api or use_cli:
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_data}"}},
            ],
        }
    return {
        "role": "user",
        "content": text,
        "images": [b64_data],
    }


async def execute_browser_tool(name: str, args: dict[str, Any]) -> str:
    """Execute a browser tool asynchronously via the Playwright bridge.

    Returns a string result. For screenshots, the result includes a tagged
    path marker so the agent loop can inject the image into vision context.
    """
    try:
        from browser_bridge import get_bridge
    except ImportError:
        return "ERROR: browser_bridge module not available."

    normalized = normalize_browser_tool_args(name, args)
    bridge = get_bridge()

    if not bridge.is_running:
        try:
            await bridge.start(headless=False)
        except Exception as exc:
            return f"ERROR: Failed to start browser: {exc}"

    action_type = name.replace("browser_", "")
    action: dict[str, Any] = {"action_type": action_type}

    if action_type == "navigate":
        action["url"] = normalized.get("url", "")
    elif action_type == "screenshot":
        pass  # no extra args needed
    elif action_type == "inspect":
        pass
    elif action_type == "click":
        action["target"] = normalized.get("selector", "")
    elif action_type == "type":
        action["target"] = normalized.get("selector", "")
        action["value"] = normalized.get("text", "")
    elif action_type == "scroll":
        action["value"] = normalized.get("direction", "down")
        action["pixels"] = normalized.get("pixels", 500)
    elif action_type == "evaluate":
        action["value"] = normalized.get("expression", "")

    try:
        result = await bridge.execute_action(action)
    except Exception as exc:
        return f"ERROR: Browser action failed: {exc}"

    if not result.get("success"):
        return f"ERROR: {result.get('result', 'Unknown browser error')}"

    # ── Screenshot: save to disk and return tagged path ──
    if action_type == "screenshot" and result.get("screenshot"):
        _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"axon_{int(time.time())}_{os.getpid()}.png"
        filepath = _SCREENSHOT_DIR / filename
        try:
            img_bytes = base64.b64decode(result["screenshot"])
            filepath.write_bytes(img_bytes)
        except Exception as exc:
            return f"Screenshot captured but failed to save: {exc}"
        url = bridge.current_url or "unknown page"
        return (
            f"Screenshot of {url} saved ({len(img_bytes)} bytes).\n"
            f"{_SCREENSHOT_RESULT_PREFIX}{filepath}]\n"
            "The image has been injected into your vision context — "
            "describe what you see and reason about layout, styles, and content."
        )

    # ── Inspect: format the DOM summary ──
    if action_type == "inspect" and isinstance(result.get("result"), dict):
        info = result["result"]
        lines = [
            f"Page: {info.get('title', '?')}",
            f"URL:  {info.get('url', '?')}",
        ]
        headings = info.get("headings") or []
        if headings:
            lines.append(f"\nHeadings ({len(headings)}):")
            for h in headings:
                lines.append(f"  • {h}")
        buttons = info.get("buttons") or []
        if buttons:
            lines.append(f"\nButtons ({len(buttons)}):")
            for b in buttons:
                lines.append(f"  • {b}")
        inputs = info.get("inputs") or []
        if inputs:
            lines.append(f"\nInputs ({len(inputs)}):")
            for inp in inputs:
                desc = f"  • [{inp.get('type','?')}]"
                if inp.get("name"):
                    desc += f" name={inp['name']}"
                if inp.get("placeholder"):
                    desc += f" placeholder=\"{inp['placeholder']}\""
                lines.append(desc)
        links = info.get("links") or []
        if links:
            lines.append(f"\nLinks ({len(links)}):")
            for link in links[:15]:
                lines.append(f"  • {link.get('text', '?')} → {link.get('href', '?')}")
        text_preview = info.get("textPreview", "")
        if text_preview:
            lines.append(f"\nText preview:\n{text_preview[:1500]}")
        return "\n".join(lines)

    return str(result.get("result", "Done"))


__all__ = [
    "BROWSER_TOOL_NAMES",
    "BROWSER_TOOL_DEFS",
    "execute_browser_tool",
    "normalize_browser_tool_args",
    "is_screenshot_result",
    "extract_screenshot_path",
    "build_vision_tool_message",
]
