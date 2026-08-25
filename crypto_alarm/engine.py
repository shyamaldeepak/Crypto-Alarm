"""Alert evaluation engine and watch loop."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .models import Alert
from .notify import Notifier
from .prices import PriceError, PriceProvider
from .storage import AlertStore


@dataclass
class Trigger:
    """A fired alert paired with the price that fired it."""

    alert: Alert
    price: float
    fired_at: str

    def title(self) -> str:
        return f"{self.alert.coin.upper()} alert"

    def message(self) -> str:
        arrow = "rose above" if self.alert.direction == "above" else "fell below"
        text = (
            f"{self.alert.coin.upper()} {arrow} {self.alert.target:,.8g} "
            f"{self.alert.currency.upper()} (now {self.price:,.8g})"
        )
        return f"{text} — {self.alert.note}" if self.alert.note else text

    def to_dict(self) -> dict:
        return {
            "fired_at": self.fired_at,
            "alert_id": self.alert.id,
            "coin": self.alert.coin,
            "currency": self.alert.currency,
            "direction": self.alert.direction,
            "target": self.alert.target,
            "price": self.price,
            "note": self.alert.note,
        }


class AlertEngine:
    """Checks stored alerts against live prices and dispatches notifications."""

    def __init__(
        self,
        store: AlertStore,
        provider: PriceProvider,
        notifier: Notifier,
        history_path: Path | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.notifier = notifier
        self.history_path = history_path or (store.home / "history.jsonl")

    # -- one pass ------------------------------------------------------
    def fetch_prices(self, alerts: Iterable[Alert]) -> dict[tuple[str, str], float]:
        """Fetch every (coin, currency) pair needed by ``alerts``."""
        by_currency: dict[str, set[str]] = {}
        for alert in alerts:
            by_currency.setdefault(alert.currency, set()).add(alert.coin)

        prices: dict[tuple[str, str], float] = {}
        for currency, coins in by_currency.items():
            for coin, price in self.provider.get_prices(sorted(coins), currency).items():
                prices[(coin, currency)] = price
        return prices

    def check_once(self, now: datetime | None = None) -> list[Trigger]:
        """Evaluate all alerts once, notifying and persisting any that fire."""
        now = now or datetime.now(timezone.utc)
        alerts = self.store.load()
        active = [a for a in alerts if a.enabled]
        if not active:
            return []

        prices = self.fetch_prices(active)
        triggers: list[Trigger] = []

        for alert in active:
            price = prices.get((alert.coin, alert.currency))
            if price is None:
                continue
            if not alert.matches(price) or not alert.is_armed(now):
                continue
            alert.mark_triggered(now)
            triggers.append(Trigger(alert=alert, price=price, fired_at=now.isoformat(timespec="seconds")))

        if triggers:
            self.store.replace_all(alerts)
            for trigger in triggers:
                self.notifier.send(trigger.title(), trigger.message())
                self._record(trigger)

        return triggers

    def _record(self, trigger: Trigger) -> None:
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with self.history_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(trigger.to_dict()) + "\n")
        except OSError:
            pass  # history is a nicety, never a reason to lose an alert

    def history(self, limit: int = 20) -> list[dict]:
        if not self.history_path.exists():
            return []
        lines = self.history_path.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    # -- loop ----------------------------------------------------------
    def watch(
        self,
        interval: float = 60.0,
        max_iterations: int | None = None,
        on_tick: Callable[[int, list[Trigger]], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> list[Trigger]:
        """Poll prices every ``interval`` seconds until interrupted or exhausted."""
        fired: list[Trigger] = []
        iteration = 0

        while max_iterations is None or iteration < max_iterations:
            iteration += 1
            try:
                triggers = self.check_once()
            except PriceError as exc:
                triggers = []
                if on_tick is None:
                    print(f"warning: {exc}")
            fired.extend(triggers)

            if on_tick is not None:
                on_tick(iteration, triggers)

            if not self.store.load() or not any(a.enabled for a in self.store.load()):
                break
            if max_iterations is not None and iteration >= max_iterations:
                break
            sleep(interval)

        return fired
