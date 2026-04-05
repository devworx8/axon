"""Compatibility shims for legacy server chat routes."""
from __future__ import annotations

import sys


async def _legacy_server_chat_stream_delegate(body, request):
    return await _chat_route_handlers.chat_stream(body, request)


def install_server_chat_stream_compat_shim() -> None:
    """Rebind the legacy `server.py` stream route to the extracted handler."""
    server_module = sys.modules.get("server")
    if server_module is None:
        return
    target = getattr(server_module, "chat_stream", None)
    if not callable(target):
        return
    if getattr(target, "__module__", "") != "server":
        return
    if getattr(target, "__code__", None) is _legacy_server_chat_stream_delegate.__code__:
        return
    target.__code__ = _legacy_server_chat_stream_delegate.__code__
    target.__defaults__ = _legacy_server_chat_stream_delegate.__defaults__
    target.__kwdefaults__ = _legacy_server_chat_stream_delegate.__kwdefaults__
