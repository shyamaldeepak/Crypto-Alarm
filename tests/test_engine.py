import io
from datetime import datetime, timedelta, timezone

import pytest

from crypto_alarm.engine import AlertEngine
from crypto_alarm.models import Alert
from crypto_alarm.notify import ConsoleNotifier, MultiNotifier
from crypto_alarm.prices import PriceError, StaticPriceProvider
from crypto_alarm.storage import AlertStore


class RecordingNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, message):
        self.sent.append((title, message))
        return True


@pytest.fixture()
def setup(tmp_path):
    def _build(prices, alerts=()):
        store = AlertStore(tmp_path)
        for alert in alerts:
            store.add(alert)
        notifier = RecordingNotifier()
        engine = AlertEngine(store, StaticPriceProvider(prices), notifier)
        return engine, store, notifier

    return _build


def test_check_once_fires_and_notifies(setup):
    engine, store, notifier = setup({"btc": 78000}, [Alert(coin="btc", target=70000, direction="above")])

    triggers = engine.check_once()

    assert len(triggers) == 1
    assert triggers[0].price == 78000
    assert len(notifier.sent) == 1
    assert "rose above" in notifier.sent[0][1]
    assert store.load()[0].enabled is False  # one-shot alert disarmed itself


def test_check_once_is_quiet_when_nothing_crosses(setup):
    engine, _, notifier = setup({"btc": 60000}, [Alert(coin="btc", target=70000, direction="above")])
    assert engine.check_once() == []
    assert notifier.sent == []


def test_one_shot_alert_does_not_fire_twice(setup):
    engine, _, notifier = setup({"btc": 78000}, [Alert(coin="btc", target=70000, direction="above")])
    engine.check_once()
    engine.check_once()
    assert len(notifier.sent) == 1


def test_repeating_alert_fires_again_after_cooldown(setup):
    engine, _, notifier = setup(
        {"btc": 78000},
        [Alert(coin="btc", target=70000, direction="above", repeat=True, cooldown_seconds=60)],
    )
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    engine.check_once(start)
    engine.check_once(start + timedelta(seconds=30))
    engine.check_once(start + timedelta(seconds=61))

    assert len(notifier.sent) == 2


def test_disabled_alerts_are_ignored(setup):
    alert = Alert(coin="btc", target=1, direction="above", enabled=False)
    engine, _, notifier = setup({"btc": 78000}, [alert])
    assert engine.check_once() == []
    assert notifier.sent == []


def test_below_alerts_fire_on_a_drop(setup):
    engine, _, notifier = setup({"eth": 1800}, [Alert(coin="eth", target=2000, direction="below")])
    triggers = engine.check_once()
    assert len(triggers) == 1
    assert "fell below" in notifier.sent[0][1]


def test_missing_price_data_leaves_the_alert_armed(setup):
    engine, store, _ = setup({"btc": 78000}, [Alert(coin="btc", target=1, direction="above")])
    engine.provider = StaticPriceProvider({"btc": 78000, "doge": 0.1})
    store.add(Alert(coin="not-a-coin", target=1, direction="above"))

    triggers = engine.check_once()

    assert [t.alert.coin for t in triggers] == ["btc"]
    assert any(a.coin == "not-a-coin" and a.enabled for a in store.load())


def test_history_records_every_fired_alert(setup):
    engine, _, _ = setup({"btc": 78000}, [Alert(coin="btc", target=1, direction="above", note="hi")])
    engine.check_once()

    entries = engine.history()
    assert len(entries) == 1
    assert entries[0]["coin"] == "btc" and entries[0]["note"] == "hi"


def test_watch_stops_after_max_iterations(setup):
    engine, _, _ = setup({"btc": 60000}, [Alert(coin="btc", target=70000, direction="above")])
    slept = []

    fired = engine.watch(interval=5, max_iterations=3, on_tick=lambda i, t: None, sleep=slept.append)

    assert fired == []
    assert slept == [5, 5]  # no sleep after the final iteration


def test_watch_stops_early_once_every_alert_is_disarmed(setup):
    engine, _, _ = setup({"btc": 78000}, [Alert(coin="btc", target=70000, direction="above")])
    ticks = []

    fired = engine.watch(interval=1, max_iterations=10, on_tick=lambda i, t: ticks.append(i), sleep=lambda s: None)

    assert len(fired) == 1
    assert ticks == [1]


def test_watch_survives_a_price_provider_outage(setup):
    class BrokenProvider:
        def get_prices(self, coins, currency="usd"):
            raise PriceError("network down")

    engine, _, _ = setup({"btc": 78000}, [Alert(coin="btc", target=1, direction="above")])
    engine.provider = BrokenProvider()

    fired = engine.watch(interval=1, max_iterations=2, on_tick=lambda i, t: None, sleep=lambda s: None)

    assert fired == []


def test_multi_notifier_reports_success_if_any_channel_works(capsys):
    stream = io.StringIO()

    class Failing:
        def send(self, title, message):
            return False

    notifier = MultiNotifier([Failing(), ConsoleNotifier(bell=False, stream=stream)])
    assert notifier.send("BTC", "up") is True
    assert "BTC — up" in stream.getvalue()
