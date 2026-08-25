import json

import pytest

from crypto_alarm import cli
from crypto_alarm.prices import PriceError
from crypto_alarm.storage import AlertStore


class FakeProvider:
    """Stands in for CoinGecko so the CLI tests never touch the network."""

    prices = {"btc": 78000.0, "eth": 2400.0}

    def __init__(self, *args, **kwargs):
        pass

    def get_prices(self, coins, currency="usd"):
        return {c.lower(): self.prices[c.lower()] for c in coins if c.lower() in self.prices}

    def get_market(self, coins, currency="usd"):
        found = {
            c.lower(): {
                "price": self.prices[c.lower()],
                "change_24h": 1.5,
                "market_cap": 1_000_000.0,
                "volume_24h": 500.0,
            }
            for c in coins
            if c.lower() in self.prices
        }
        if not found:
            raise PriceError("no market data")
        return found

    def search(self, query, limit=10):
        return [{"id": "bitcoin", "symbol": "BTC", "name": "Bitcoin", "rank": "1"}]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(cli, "CoinGeckoProvider", FakeProvider)


@pytest.fixture()
def home(tmp_path):
    return str(tmp_path)


def run(argv, home=None):
    return cli.main((["--home", home] if home else []) + argv)


def test_no_arguments_prints_help(capsys):
    assert cli.main([]) == 0
    assert "usage: crypto-alarm" in capsys.readouterr().out


def test_add_then_list(home, capsys):
    assert run(["add", "--coin", "BTC", "--target", "100000", "--direction", "above"], home) == 0
    assert "Added alert" in capsys.readouterr().out

    assert run(["list"], home) == 0
    out = capsys.readouterr().out
    assert "BTC" in out and "100,000" in out


def test_list_json_is_machine_readable(home, capsys):
    run(["add", "--coin", "eth", "--target", "5000", "--direction", "above", "--note", "moon"], home)
    capsys.readouterr()

    run(["list", "--json"], home)
    data = json.loads(capsys.readouterr().out)

    assert data[0]["coin"] == "eth" and data[0]["note"] == "moon"


def test_add_rejects_a_bad_target(home, capsys):
    assert run(["add", "--coin", "btc", "--target", "-1", "--direction", "above"], home) == 2
    assert "must be a positive number" in capsys.readouterr().err


def test_remove_and_remove_all(home, capsys):
    run(["add", "--coin", "btc", "--target", "1", "--direction", "above"], home)
    alert_id = AlertStore(home).load()[0].id
    capsys.readouterr()

    assert run(["remove", alert_id], home) == 0
    assert "Removed" in capsys.readouterr().out
    assert run(["remove", "nope"], home) == 0
    assert "No alert with ID nope" in capsys.readouterr().out

    run(["add", "--coin", "btc", "--target", "1", "--direction", "above"], home)
    capsys.readouterr()
    assert run(["remove", "--all"], home) == 0
    assert AlertStore(home).load() == []


def test_remove_without_target_is_a_usage_error(home, capsys):
    assert run(["remove"], home) == 2
    assert "provide an alert ID or --all" in capsys.readouterr().err


def test_disable_and_enable(home, capsys):
    run(["add", "--coin", "btc", "--target", "1", "--direction", "above"], home)
    alert_id = AlertStore(home).load()[0].id
    capsys.readouterr()

    assert run(["disable", alert_id], home) == 0
    assert AlertStore(home).load()[0].enabled is False
    assert run(["enable", alert_id], home) == 0
    assert AlertStore(home).load()[0].enabled is True

    capsys.readouterr()
    assert run(["enable", "missing"], home) == 1


def test_check_fires_a_stored_alert(home, capsys):
    run(["add", "--coin", "btc", "--target", "70000", "--direction", "above"], home)
    capsys.readouterr()

    assert run(["check", "--no-bell"], home) == 0
    assert "rose above" in capsys.readouterr().out


def test_check_reports_when_nothing_triggers(home, capsys):
    run(["add", "--coin", "btc", "--target", "999999", "--direction", "above"], home)
    capsys.readouterr()

    run(["check", "--no-bell"], home)
    assert "nothing triggered" in capsys.readouterr().out


def test_check_manual_mode_needs_a_full_triple(home, capsys):
    assert run(["check", "--price", "100"], home) == 2
    assert "requires --target and --direction" in capsys.readouterr().err


def test_legacy_flag_interface_still_works(capsys):
    assert cli.main(["--price", "25000", "--target", "24000", "--direction", "above"]) == 0
    assert "ALERT TRIGGERED" in capsys.readouterr().out


def test_legacy_flag_interface_when_not_triggered(capsys):
    assert cli.main(["--price", "23000", "--target", "24000", "--direction", "above"]) == 0
    assert "No alert yet" in capsys.readouterr().out


def test_price_command_renders_a_table(capsys):
    assert cli.main(["price", "btc", "eth"]) == 0
    out = capsys.readouterr().out
    assert "BTC" in out and "78,000.00 USD" in out and "+1.50%" in out


def test_price_command_defaults_to_coins_you_watch(home, capsys):
    run(["add", "--coin", "eth", "--target", "5000", "--direction", "above"], home)
    capsys.readouterr()

    run(["price"], home)
    out = capsys.readouterr().out
    assert "ETH" in out and "BTC" not in out


def test_price_error_is_reported_cleanly(capsys):
    assert cli.main(["price", "not-a-coin"]) == 1
    assert "error: no market data" in capsys.readouterr().err


def test_search_command(capsys):
    assert cli.main(["search", "bitcoin"]) == 0
    assert "bitcoin" in capsys.readouterr().out


def test_watch_requires_an_enabled_alert(home, capsys):
    assert run(["watch", "--iterations", "1"], home) == 1
    assert "No enabled alerts" in capsys.readouterr().out


def test_watch_runs_and_fires(home, capsys):
    run(["add", "--coin", "btc", "--target", "70000", "--direction", "above"], home)
    capsys.readouterr()

    assert run(["watch", "--iterations", "1", "--interval", "0", "--no-bell", "--verbose"], home) == 0
    out = capsys.readouterr().out
    assert "rose above" in out and "1 alert(s) fired" in out


def test_history_command(home, capsys):
    run(["add", "--coin", "btc", "--target", "70000", "--direction", "above"], home)
    run(["check", "--no-bell"], home)
    capsys.readouterr()

    assert run(["history"], home) == 0
    assert "BTC" in capsys.readouterr().out

    run(["history", "--json"], home)
    assert json.loads(capsys.readouterr().out)[0]["coin"] == "btc"


def test_history_is_empty_by_default(home, capsys):
    assert run(["history"], home) == 0
    assert "No alerts have fired yet" in capsys.readouterr().out
