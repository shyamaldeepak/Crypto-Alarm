"""Persistence for alerts (a small JSON file, written atomically)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Alert

ENV_VAR = "CRYPTO_ALARM_HOME"
SCHEMA_VERSION = 1


def default_home() -> Path:
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".crypto-alarm"


class AlertStore:
    """Loads and saves alerts from ``<home>/alerts.json``."""

    def __init__(self, home: Path | str | None = None) -> None:
        self.home = Path(home).expanduser() if home else default_home()
        self.path = self.home / "alerts.json"

    # -- io ------------------------------------------------------------
    def load(self) -> list[Alert]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{self.path} is not valid JSON: {exc}") from exc

        records = raw.get("alerts", []) if isinstance(raw, dict) else raw
        alerts = []
        for record in records:
            try:
                alerts.append(Alert.from_dict(record))
            except (TypeError, ValueError):
                continue  # skip corrupt entries rather than failing the whole file
        return alerts

    def save(self, alerts: list[Alert]) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        payload = {"version": SCHEMA_VERSION, "alerts": [a.to_dict() for a in alerts]}
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    # -- convenience ---------------------------------------------------
    def add(self, alert: Alert) -> Alert:
        alerts = self.load()
        alerts.append(alert)
        self.save(alerts)
        return alert

    def get(self, alert_id: str) -> Alert | None:
        return next((a for a in self.load() if a.id == alert_id), None)

    def remove(self, alert_id: str) -> bool:
        alerts = self.load()
        remaining = [a for a in alerts if a.id != alert_id]
        if len(remaining) == len(alerts):
            return False
        self.save(remaining)
        return True

    def clear(self) -> int:
        alerts = self.load()
        self.save([])
        return len(alerts)

    def update(self, alert: Alert) -> None:
        alerts = self.load()
        for index, existing in enumerate(alerts):
            if existing.id == alert.id:
                alerts[index] = alert
                break
        else:
            alerts.append(alert)
        self.save(alerts)

    def replace_all(self, alerts: list[Alert]) -> None:
        self.save(alerts)
