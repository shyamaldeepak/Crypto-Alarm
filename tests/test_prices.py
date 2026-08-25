import pytest

from crypto_alarm.prices import CoinGeckoProvider, PriceError, StaticPriceProvider, resolve_coin_id


def test_resolve_maps_tickers_to_coingecko_ids():
    assert resolve_coin_id("BTC") == "bitcoin"
    assert resolve_coin_id(" eth ") == "ethereum"


def test_resolve_passes_unknown_names_through_untouched():
    assert resolve_coin_id("some-new-coin") == "some-new-coin"


class StubProvider(CoinGeckoProvider):
    def __init__(self, payload, **kwargs):
        super().__init__(**kwargs)
        self.payload = payload
        self.calls = []

    def _get_json(self, path, params):
        self.calls.append((path, params))
        return self.payload


def test_get_prices_keys_results_by_the_requested_name():
    provider = StubProvider({"bitcoin": {"usd": 78000}, "ethereum": {"usd": 2400}})
    assert provider.get_prices(["BTC", "ethereum"]) == {"btc": 78000.0, "ethereum": 2400.0}


def test_get_prices_ignores_coins_the_api_did_not_return():
    provider = StubProvider({"bitcoin": {"usd": 78000}})
    assert provider.get_prices(["btc", "nonsense"]) == {"btc": 78000.0}


def test_get_prices_raises_when_nothing_resolves():
    provider = StubProvider({})
    with pytest.raises(PriceError, match="no price data"):
        provider.get_prices(["nonsense"])


def test_get_prices_deduplicates_and_caches():
    provider = StubProvider({"bitcoin": {"usd": 78000}}, cache_ttl=60)
    provider.get_prices(["btc", "BTC", " btc "])
    provider.get_prices(["btc"])
    assert len(provider.calls) == 1  # second call served from cache


def test_get_market_extracts_the_extra_fields():
    provider = StubProvider(
        {"bitcoin": {"usd": 78000, "usd_24h_change": -1.25, "usd_market_cap": 1e12, "usd_24h_vol": 4e10}}
    )
    data = provider.get_market(["btc"])["btc"]
    assert data["price"] == 78000 and data["change_24h"] == -1.25 and data["market_cap"] == 1e12


def test_search_flattens_the_api_response():
    provider = StubProvider({"coins": [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "market_cap_rank": 1}]})
    assert provider.search("btc") == [{"id": "bitcoin", "symbol": "BTC", "name": "Bitcoin", "rank": "1"}]


def test_static_provider_serves_a_fixed_table():
    provider = StaticPriceProvider({"BTC": 100})
    assert provider.get_prices(["btc", "eth"]) == {"btc": 100.0}
    with pytest.raises(PriceError):
        provider.get_prices(["btc"], currency="eur")
