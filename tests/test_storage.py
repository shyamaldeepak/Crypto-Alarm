import json

import pytest

from crypto_alarm.models import Alert
from crypto_alarm.storage import AlertStore, default_home


@pytest.fixture()
def store(tmp_path):
    return AlertStore(tmp_path)


def test_empty_store_loads_nothing(store):
    assert store.load() == []


def test_add_and_get_round_trip(store):
    alert = store.add(Alert(coin="btc", target=100000, direction="above"))
    assert store.get(alert.id) == alert
    assert store.path.exists()


def test_remove_reports_whether_it_matched(store):
    alert = store.add(Alert(coin="btc", target=1, direction="above"))
    assert store.remove(alert.id) is True
    assert store.remove(alert.id) is False
    assert store.load() == []


def test_update_persists_changes(store):
    alert = store.add(Alert(coin="eth", target=5000, direction="above"))
    alert.enabled = False
    store.update(alert)
    assert store.get(alert.id).enabled is False


def test_clear_returns_the_number_removed(store):
    store.add(Alert(coin="btc", target=1, direction="above"))
    store.add(Alert(coin="eth", target=2, direction="below"))
    assert store.clear() == 2
    assert store.load() == []


def test_corrupt_entries_are_skipped_not_fatal(store):
    good = Alert(coin="btc", target=1, direction="above")
    store.home.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"alerts": [good.to_dict(), {"coin": "eth", "direction": "sideways"}]}))
    assert [a.id for a in store.load()] == [good.id]


def test_invalid_json_raises_a_clear_error(store):
    store.home.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        store.load()


def test_home_honours_the_environment_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYPTO_ALARM_HOME", str(tmp_path / "custom"))
    assert default_home() == tmp_path / "custom"
