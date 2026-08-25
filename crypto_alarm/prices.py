"""Price providers.

The default provider talks to the free CoinGecko API using only the standard
library, so Crypto Alarm has no third-party dependencies.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable, Protocol

API_ROOT = "https://api.coingecko.com/api/v3"
USER_AGENT = "crypto-alarm/0.2 (+https://example.invalid)"

#: Common ticker symbols mapped to CoinGecko coin ids.
SYMBOL_ALIASES: dict[str, str] = {
    "btc": "bitcoin",
    "xbt": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "ada": "cardano",
    "xrp": "ripple",
    "doge": "dogecoin",
    "dot": "polkadot",
    "matic": "matic-network",
    "pol": "polygon-ecosystem-token",
    "ltc": "litecoin",
    "link": "chainlink",
    "avax": "avalanche-2",
    "bnb": "binancecoin",
    "trx": "tron",
    "atom": "cosmos",
    "xlm": "stellar",
    "near": "near",
    "arb": "arbitrum",
    "op": "optimism",
    "sui": "sui",
    "ton": "the-open-network",
    "shib": "shiba-inu",
    "usdt": "tether",
    "usdc": "usd-coin",
}


class PriceError(RuntimeError):
    """Raised when prices cannot be retrieved."""


def resolve_coin_id(coin: str) -> str:
    """Map a user-supplied ticker or id to a CoinGecko coin id."""
    key = coin.strip().lower()
    return SYMBOL_ALIASES.get(key, key)


class PriceProvider(Protocol):
    def get_prices(self, coins: Iterable[str], currency: str = "usd") -> dict[str, float]:
        """Return ``{coin: price}`` keyed by the caller's original coin names."""


class CoinGeckoProvider:
    """Fetches live prices from CoinGecko with retry and simple caching."""

    def __init__(self, timeout: float = 10.0, retries: int = 3, cache_ttl: float = 0.0) -> None:
        self.timeout = timeout
        self.retries = max(1, retries)
        self.cache_ttl = cache_ttl
        self._cache: dict[tuple[str, str], tuple[float, float]] = {}

    # -- http ----------------------------------------------------------
    def _get_json(self, path: str, params: dict[str, str]) -> dict:
        url = f"{API_ROOT}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        last_error: Exception | None = None

        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:  # pragma: no cover - network dependent
                last_error = exc
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:  # pragma: no cover
                last_error = exc
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                break

        raise PriceError(f"could not reach CoinGecko: {last_error}") from last_error

    # -- api -----------------------------------------------------------
    def get_prices(self, coins: Iterable[str], currency: str = "usd") -> dict[str, float]:
        currency = currency.lower()
        wanted = list(dict.fromkeys(c.strip().lower() for c in coins if c.strip()))
        if not wanted:
            return {}

        now = time.monotonic()
        prices: dict[str, float] = {}
        pending: list[str] = []
        for coin in wanted:
            cached = self._cache.get((coin, currency))
            if cached and self.cache_ttl and now - cached[0] < self.cache_ttl:
                prices[coin] = cached[1]
            else:
                pending.append(coin)

        if pending:
            id_by_coin = {coin: resolve_coin_id(coin) for coin in pending}
            payload = self._get_json(
                "/simple/price",
                {"ids": ",".join(sorted(set(id_by_coin.values()))), "vs_currencies": currency},
            )
            for coin, coin_id in id_by_coin.items():
                entry = payload.get(coin_id)
                if not entry or currency not in entry:
                    continue
                price = float(entry[currency])
                prices[coin] = price
                self._cache[(coin, currency)] = (now, price)

        missing = [c for c in wanted if c not in prices]
        if missing and not prices:
            raise PriceError(f"no price data for: {', '.join(missing)} (in {currency.upper()})")
        return prices

    def get_market(self, coins: Iterable[str], currency: str = "usd") -> dict[str, dict[str, float]]:
        """Return richer market data (price, 24h change, market cap, volume)."""
        currency = currency.lower()
        wanted = list(dict.fromkeys(c.strip().lower() for c in coins if c.strip()))
        if not wanted:
            return {}

        id_by_coin = {coin: resolve_coin_id(coin) for coin in wanted}
        payload = self._get_json(
            "/simple/price",
            {
                "ids": ",".join(sorted(set(id_by_coin.values()))),
                "vs_currencies": currency,
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
                "include_market_cap": "true",
            },
        )

        market: dict[str, dict[str, float]] = {}
        for coin, coin_id in id_by_coin.items():
            entry = payload.get(coin_id)
            if not entry or currency not in entry:
                continue
            market[coin] = {
                "price": float(entry[currency]),
                "change_24h": float(entry.get(f"{currency}_24h_change", 0.0)),
                "market_cap": float(entry.get(f"{currency}_market_cap", 0.0)),
                "volume_24h": float(entry.get(f"{currency}_24h_vol", 0.0)),
            }
        if not market:
            raise PriceError(f"no market data for: {', '.join(wanted)} (in {currency.upper()})")
        return market

    def search(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        """Look up coins by name or symbol."""
        payload = self._get_json("/search", {"query": query})
        results = []
        for coin in payload.get("coins", [])[:limit]:
            results.append(
                {
                    "id": coin.get("id", ""),
                    "symbol": (coin.get("symbol") or "").upper(),
                    "name": coin.get("name", ""),
                    "rank": str(coin.get("market_cap_rank") or "-"),
                }
            )
        return results


class StaticPriceProvider:
    """Offline provider backed by a fixed price table (used in tests/demos)."""

    def __init__(self, prices: dict[str, float], currency: str = "usd") -> None:
        self.prices = {k.lower(): float(v) for k, v in prices.items()}
        self.currency = currency.lower()

    def get_prices(self, coins: Iterable[str], currency: str = "usd") -> dict[str, float]:
        if currency.lower() != self.currency:
            raise PriceError(f"static provider only knows {self.currency.upper()}")
        return {c.lower(): self.prices[c.lower()] for c in coins if c.lower() in self.prices}
