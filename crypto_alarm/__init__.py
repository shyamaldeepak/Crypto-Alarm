"""Crypto Alarm — track crypto prices and fire alerts when they cross your targets."""

from __future__ import annotations

__version__ = "0.2.0"

from .models import Alert, should_trigger_alert

__all__ = ["Alert", "should_trigger_alert", "__version__"]
