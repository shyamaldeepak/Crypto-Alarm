"""Notification channels used when an alert fires."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Protocol

BELL = "\a"


class Notifier(Protocol):
    def send(self, title: str, message: str) -> bool:
        """Deliver a notification; return True when it was delivered."""


class ConsoleNotifier:
    """Prints the alert to stdout (optionally ringing the terminal bell)."""

    def __init__(self, bell: bool = True, stream=None) -> None:
        self.bell = bell
        self.stream = stream or sys.stdout

    def send(self, title: str, message: str) -> bool:
        prefix = BELL if self.bell else ""
        self.stream.write(f"{prefix}🔔 {title} — {message}\n")
        self.stream.flush()
        return True


class DesktopNotifier:
    """Best-effort desktop notification via notify-send / osascript / msg."""

    def send(self, title: str, message: str) -> bool:
        try:
            if sys.platform == "darwin" and shutil.which("osascript"):
                script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
                subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=10)
                return True
            if shutil.which("notify-send"):
                subprocess.run(["notify-send", title, message], check=True, capture_output=True, timeout=10)
                return True
            if sys.platform.startswith("win") and shutil.which("msg"):
                subprocess.run(["msg", "*", f"{title}: {message}"], check=True, capture_output=True, timeout=10)
                return True
        except (subprocess.SubprocessError, OSError):
            return False
        return False


class WebhookNotifier:
    """POSTs a JSON payload to a webhook (Slack/Discord compatible)."""

    def __init__(self, url: str, timeout: float = 10.0) -> None:
        self.url = url
        self.timeout = timeout

    def send(self, title: str, message: str) -> bool:
        body = json.dumps({"text": f"{title} — {message}", "title": title, "message": message}).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "crypto-alarm"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return 200 <= response.status < 300
        except (urllib.error.URLError, TimeoutError, OSError):
            return False


class MultiNotifier:
    """Fans a notification out to several channels; succeeds if any does."""

    def __init__(self, notifiers: list[Notifier]) -> None:
        self.notifiers = notifiers

    def send(self, title: str, message: str) -> bool:
        return any([notifier.send(title, message) for notifier in self.notifiers])
