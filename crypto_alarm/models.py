"""Data model for a single price alert."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

DIRECTIONS = ("above", "below")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Alert:
    """A price threshold that fires when the market crosses it."""

    coin: str
    target: float
    direction: str
    id: str = field(default_factory=new_id)
    currency: str = "usd"
    note: str = ""
    enabled: bool = True
    repeat: bool = False
    cooldown_seconds: int = 300
    created_at: str = field(default_factory=_now)
    last_triggered_at: str | None = None
    trigger_count: int = 0

    def __post_init__(self) -> None:
        self.coin = self.coin.strip().lower()
        self.currency = self.currency.strip().lower()
        self.direction = self.direction.strip().lower()
        if self.direction not in DIRECTIONS:
            raise ValueError("direction must be either 'above' or 'below'")
        if self.target <= 0:
            raise ValueError("target must be a positive number")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds cannot be negative")

    # -- serialisation -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Alert":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    # -- behaviour -----------------------------------------------------
    def matches(self, price: float) -> bool:
        """Whether ``price`` satisfies this alert's threshold."""
        return should_trigger_alert(price, self.target, self.direction)

    def is_armed(self, now: datetime | None = None) -> bool:
        """Whether the alert is eligible to fire right now."""
        if not self.enabled:
            return False
        if self.last_triggered_at is None:
            return True
        if not self.repeat:
            return False
        now = now or datetime.now(timezone.utc)
        last = datetime.fromisoformat(self.last_triggered_at)
        return (now - last).total_seconds() >= self.cooldown_seconds

    def mark_triggered(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self.last_triggered_at = now.isoformat(timespec="seconds")
        self.trigger_count += 1
        if not self.repeat:
            self.enabled = False

    def describe(self) -> str:
        arrow = "↑" if self.direction == "above" else "↓"
        return f"{self.coin.upper()} {arrow} {self.target:,.8g} {self.currency.upper()}"


def should_trigger_alert(current_price: float, target_price: float, direction: str) -> bool:
    """Return whether the current price has crossed the configured trigger target."""
    direction_name = direction.lower().strip()

    if direction_name not in DIRECTIONS:
        raise ValueError("direction must be either 'above' or 'below'")

    if direction_name == "above":
        return current_price >= target_price

    return current_price <= target_price
