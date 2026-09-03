"""Read the current Windows user proxy without persisting its address."""
from __future__ import annotations

import os
from urllib.parse import urlparse


def current_http_proxy() -> str | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
        if not enabled or not server:
            return None
        entries = str(server).split(";")
        selected = next((item.split("=", 1)[1] for item in entries if item.lower().startswith("https=")), None)
        selected = selected or next((item.split("=", 1)[1] for item in entries if item.lower().startswith("http=")), None)
        selected = selected or str(server)
        parsed = urlparse(selected if "://" in selected else f"http://{selected}")
        if not parsed.hostname or not parsed.port:
            return None
        return f"http://{parsed.hostname}:{parsed.port}"
    except (ImportError, OSError, ValueError):
        return None


def proxied_environment() -> dict[str, str]:
    environment = os.environ.copy()
    proxy = current_http_proxy()
    if proxy:
        environment.setdefault("HTTP_PROXY", proxy)
        environment.setdefault("HTTPS_PROXY", proxy)
        environment.setdefault("http_proxy", proxy)
        environment.setdefault("https_proxy", proxy)
    environment.setdefault("NO_PROXY", "localhost,127.0.0.1,::1")
    return environment
