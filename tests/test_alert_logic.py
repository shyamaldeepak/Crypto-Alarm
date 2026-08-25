from datetime import datetime, timedelta, timezone

import pytest

from crypto_alarm import Alert, should_trigger_alert


def test_should_trigger_alert_above_target():
    assert should_trigger_alert(25000, 24000, "above") is True


def test_should_trigger_alert_below_target():
    assert should_trigger_alert(24000, 25000, "below") is True


def test_should_not_trigger_when_price_has_not_reached_target():
    assert should_trigger_alert(23000, 24000, "above") is False


def test_exact_match_counts_as_a_crossing():
    assert should_trigger_alert(24000, 24000, "above") is True
    assert should_trigger_alert(24000, 24000, "below") is True


def test_direction_is_normalised_and_validated():
    assert should_trigger_alert(25000, 24000, " Above ") is True
    with pytest.raises(ValueError):
        should_trigger_alert(25000, 24000, "sideways")


def test_alert_normalises_fields():
    alert = Alert(coin=" BTC ", target=100.0, direction="ABOVE", currency=" EUR ")
    assert (alert.coin, alert.direction, alert.currency) == ("btc", "above", "eur")


@pytest.mark.parametrize("target", [0, -5])
def test_alert_rejects_non_positive_targets(target):
    with pytest.raises(ValueError):
        Alert(coin="btc", target=target, direction="above")


def test_alert_round_trips_through_dict():
    alert = Alert(coin="eth", target=4000, direction="below", note="buy the dip")
    assert Alert.from_dict(alert.to_dict()) == alert


def test_one_shot_alert_disables_itself_after_firing():
    alert = Alert(coin="btc", target=100, direction="above")
    assert alert.is_armed() is True
    alert.mark_triggered()
    assert alert.enabled is False
    assert alert.trigger_count == 1
    assert alert.is_armed() is False


def test_repeating_alert_respects_its_cooldown():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    alert = Alert(coin="btc", target=100, direction="above", repeat=True, cooldown_seconds=300)
    alert.mark_triggered(now)

    assert alert.enabled is True
    assert alert.is_armed(now + timedelta(seconds=299)) is False
    assert alert.is_armed(now + timedelta(seconds=300)) is True
