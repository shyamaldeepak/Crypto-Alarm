# Crypto Alarm

A lightweight command-line crypto price alarm. Set price targets, then let it watch
the market and shout when one is crossed.

**No third-party dependencies** — live prices come from the free
[CoinGecko](https://www.coingecko.com/) API using only the Python standard library.

## Install

```bash
pip install -e .          # exposes the `crypto-alarm` command
# or just run it in place:
python main.py --help
```

Requires Python 3.10+.

## Quick start

```bash
crypto-alarm price btc eth sol                                   # live quotes
crypto-alarm add --coin BTC --target 100000 --direction above    # arm an alert
crypto-alarm add --coin ETH --target 2000 --direction below --note "buy the dip"
crypto-alarm list                                                # see what's armed
crypto-alarm watch --interval 60 --desktop                       # poll until it fires
```

```
COIN  PRICE          24H       MARKET CAP
----  -------------  --------  -----------------
BTC   78,970.00 USD  ▲ +0.13%  1,585,330,678,917
ETH   2,462.91 USD   ▼ -0.25%  297,167,392,021
```

## Commands

| Command | What it does |
| --- | --- |
| `add` | Arm an alert: `--coin --target --direction` (+ `--currency --note --repeat --cooldown`) |
| `list` | Show armed alerts (`--all` includes disabled, `--json` for scripting) |
| `remove <id>…` | Delete alerts by ID, or `--all` |
| `enable <id>` / `disable <id>` | Re-arm or pause an alert |
| `price [coins…]` | Live prices with 24h change and market cap (defaults to coins you watch) |
| `search <query>` | Find a coin's CoinGecko id by name or symbol |
| `check` | Evaluate every alert once against live prices |
| `watch` | Poll on an interval and fire alerts (`--interval --iterations --verbose`) |
| `history` | Alerts that have already fired (`-n`, `--json`) |

### Alert behaviour

- **One-shot by default** — an alert disables itself once it fires, so you are not
  spammed while the price hovers at your target. `enable <id>` re-arms it.
- **`--repeat`** keeps it armed and re-fires no more often than `--cooldown` seconds
  (default 300).
- Crossings are inclusive: a target of 100,000 `above` fires at exactly 100,000.

### Notifications

`check` and `watch` accept notification flags, and they stack:

```bash
crypto-alarm watch --desktop --webhook https://hooks.slack.com/services/XXX --no-bell
```

| Flag | Channel |
| --- | --- |
| *(default)* | Terminal line + bell |
| `--no-bell` | Terminal line only |
| `--desktop` | `notify-send` (Linux), `osascript` (macOS), `msg` (Windows) |
| `--webhook URL` | JSON `POST` — Slack/Discord compatible |

### Where data lives

Alerts and fire history are stored in `~/.crypto-alarm/` (`alerts.json`, `history.jsonl`).
Override with `--home /path` or the `CRYPTO_ALARM_HOME` environment variable — handy
for keeping separate alert sets:

```bash
CRYPTO_ALARM_HOME=~/.crypto-alarm/trading crypto-alarm list
```

### Other currencies

Any CoinGecko quote currency works:

```bash
crypto-alarm price btc --currency eur
crypto-alarm add --coin BTC --target 90000 --direction above --currency eur
```

Unknown tickers fall through to CoinGecko ids, so `crypto-alarm price the-open-network`
works even without a built-in alias. Use `search` to find the id.

## Running as a background watcher

```bash
nohup crypto-alarm watch --interval 120 --desktop >> ~/.crypto-alarm/watch.log 2>&1 &
```

## Library use

```python
from crypto_alarm import Alert, should_trigger_alert
from crypto_alarm.engine import AlertEngine
from crypto_alarm.notify import ConsoleNotifier
from crypto_alarm.prices import CoinGeckoProvider
from crypto_alarm.storage import AlertStore

should_trigger_alert(25000, 24000, "above")  # -> True

store = AlertStore()
store.add(Alert(coin="btc", target=100000, direction="above"))
AlertEngine(store, CoinGeckoProvider(), ConsoleNotifier()).check_once()
```

## Layout

| Module | Responsibility |
| --- | --- |
| [crypto_alarm/models.py](crypto_alarm/models.py) | `Alert` dataclass — thresholds, cooldown, arming rules |
| [crypto_alarm/prices.py](crypto_alarm/prices.py) | CoinGecko provider (retries, caching) + offline stub |
| [crypto_alarm/storage.py](crypto_alarm/storage.py) | Atomic JSON persistence |
| [crypto_alarm/notify.py](crypto_alarm/notify.py) | Console / desktop / webhook channels |
| [crypto_alarm/engine.py](crypto_alarm/engine.py) | Evaluation pass, watch loop, fire history |
| [crypto_alarm/cli.py](crypto_alarm/cli.py) | Argument parsing and output formatting |

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The suite is fully offline — network calls are stubbed, so it runs anywhere.
