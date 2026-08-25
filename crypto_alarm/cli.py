"""Command-line interface for Crypto Alarm."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from . import __version__
from .engine import AlertEngine, Trigger
from .models import Alert
from .notify import ConsoleNotifier, DesktopNotifier, MultiNotifier, WebhookNotifier
from .prices import CoinGeckoProvider, PriceError
from .storage import AlertStore


# ---------------------------------------------------------------- helpers
def fmt_money(value: float, currency: str = "usd") -> str:
    digits = 2 if abs(value) >= 1 else 6
    return f"{value:,.{digits}f} {currency.upper()}"


def fmt_change(change: float) -> str:
    sign = "+" if change >= 0 else ""
    arrow = "▲" if change >= 0 else "▼"
    return f"{arrow} {sign}{change:.2f}%"


def render_table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()
    rule = "  ".join("-" * widths[i] for i in range(len(headers)))
    body = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows]
    return "\n".join([line, rule, *body])


def build_notifier(args: argparse.Namespace) -> MultiNotifier:
    channels = [ConsoleNotifier(bell=not getattr(args, "no_bell", False))]
    if getattr(args, "desktop", False):
        channels.append(DesktopNotifier())
    if getattr(args, "webhook", None):
        channels.append(WebhookNotifier(args.webhook))
    return MultiNotifier(channels)


def make_engine(args: argparse.Namespace) -> AlertEngine:
    store = AlertStore(getattr(args, "home", None))
    provider = CoinGeckoProvider(cache_ttl=5.0)
    return AlertEngine(store, provider, build_notifier(args))


# --------------------------------------------------------------- commands
def cmd_add(args: argparse.Namespace) -> int:
    alert = Alert(
        coin=args.coin,
        target=args.target,
        direction=args.direction,
        currency=args.currency,
        note=args.note or "",
        repeat=args.repeat,
        cooldown_seconds=args.cooldown,
    )
    AlertStore(args.home).add(alert)
    print(f"Added alert {alert.id}: {alert.describe()}" + (f" ({alert.note})" if alert.note else ""))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    alerts = AlertStore(args.home).load()
    if not args.all:
        alerts = [a for a in alerts if a.enabled]

    if args.json:
        print(json.dumps([a.to_dict() for a in alerts], indent=2))
        return 0

    if not alerts:
        print("No alerts configured. Add one with: crypto-alarm add --coin BTC --target 100000 --direction above")
        return 0

    rows = [
        [
            a.id,
            a.coin.upper(),
            a.direction,
            f"{a.target:,.8g}",
            a.currency.upper(),
            "on" if a.enabled else "off",
            "repeat" if a.repeat else "once",
            str(a.trigger_count),
            a.note[:28],
        ]
        for a in alerts
    ]
    print(render_table(rows, ["ID", "COIN", "DIR", "TARGET", "CCY", "STATE", "MODE", "HITS", "NOTE"]))
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    store = AlertStore(args.home)
    if args.all:
        count = store.clear()
        print(f"Removed {count} alert(s).")
        return 0
    if not args.id:
        print("error: provide an alert ID or --all", file=sys.stderr)
        return 2
    for alert_id in args.id:
        print(f"Removed {alert_id}." if store.remove(alert_id) else f"No alert with ID {alert_id}.")
    return 0


def _set_enabled(args: argparse.Namespace, enabled: bool) -> int:
    store = AlertStore(args.home)
    alert = store.get(args.id)
    if alert is None:
        print(f"No alert with ID {args.id}.", file=sys.stderr)
        return 1
    alert.enabled = enabled
    if enabled:
        alert.last_triggered_at = None
    store.update(alert)
    print(f"{'Enabled' if enabled else 'Disabled'} {alert.id}: {alert.describe()}")
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    return _set_enabled(args, True)


def cmd_disable(args: argparse.Namespace) -> int:
    return _set_enabled(args, False)


def cmd_price(args: argparse.Namespace) -> int:
    provider = CoinGeckoProvider()
    coins = args.coins or sorted({a.coin for a in AlertStore(args.home).load()}) or ["btc", "eth"]
    market = provider.get_market(coins, args.currency)

    if args.json:
        print(json.dumps(market, indent=2))
        return 0

    rows = [
        [
            coin.upper(),
            fmt_money(data["price"], args.currency),
            fmt_change(data["change_24h"]),
            f"{data['market_cap']:,.0f}",
        ]
        for coin, data in market.items()
    ]
    print(render_table(rows, ["COIN", "PRICE", "24H", "MARKET CAP"]))
    missing = [c for c in coins if c.lower() not in market]
    if missing:
        print(f"\nNo data for: {', '.join(missing)} (try `crypto-alarm search <name>`)", file=sys.stderr)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    results = CoinGeckoProvider().search(args.query, limit=args.limit)
    if not results:
        print(f"No coins matched {args.query!r}.")
        return 1
    rows = [[r["id"], r["symbol"], r["name"], r["rank"]] for r in results]
    print(render_table(rows, ["ID", "SYMBOL", "NAME", "RANK"]))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    # Manual one-shot mode: crypto-alarm check --price 25000 --target 24000 --direction above
    if args.price is not None:
        if args.target is None or args.direction is None:
            print("error: --price also requires --target and --direction", file=sys.stderr)
            return 2
        from .models import should_trigger_alert

        triggered = should_trigger_alert(args.price, args.target, args.direction)
        status = "ALERT TRIGGERED" if triggered else "No alert yet"
        print(
            f"{args.coin.upper()}: price={fmt_money(args.price, args.currency)}, "
            f"target={fmt_money(args.target, args.currency)}, direction={args.direction}, status={status}"
        )
        return 0

    engine = make_engine(args)
    if not engine.store.load():
        print("No alerts configured. Add one with `crypto-alarm add`, or pass --price/--target/--direction.")
        return 0

    triggers = engine.check_once()
    if not triggers:
        print(f"Checked {len([a for a in engine.store.load() if a.enabled])} alert(s) — nothing triggered.")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    engine = make_engine(args)
    alerts = [a for a in engine.store.load() if a.enabled]
    if not alerts:
        print("No enabled alerts to watch. Add one with `crypto-alarm add`.")
        return 1

    print(
        f"Watching {len(alerts)} alert(s) every {args.interval:g}s — Ctrl+C to stop."
        + (f" (max {args.iterations} checks)" if args.iterations else "")
    )

    def on_tick(iteration: int, triggers: list[Trigger]) -> None:
        if triggers or args.verbose:
            stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            remaining = len([a for a in engine.store.load() if a.enabled])
            print(f"[{stamp}] check #{iteration}: {len(triggers)} fired, {remaining} still armed")

    try:
        fired = engine.watch(interval=args.interval, max_iterations=args.iterations, on_tick=on_tick)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0

    print(f"Done — {len(fired)} alert(s) fired.")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    engine = make_engine(args)
    entries = engine.history(limit=args.limit)
    if not entries:
        print("No alerts have fired yet.")
        return 0
    if args.json:
        print(json.dumps(entries, indent=2))
        return 0
    rows = [
        [
            e["fired_at"],
            e["coin"].upper(),
            e["direction"],
            f"{e['target']:,.8g}",
            f"{e['price']:,.8g}",
            e.get("note", "")[:24],
        ]
        for e in entries
    ]
    print(render_table(rows, ["FIRED AT", "COIN", "DIR", "TARGET", "PRICE", "NOTE"]))
    return 0


# ----------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crypto-alarm",
        description="Track crypto prices and get alerted when they cross your targets.",
    )
    parser.add_argument("--version", action="version", version=f"crypto-alarm {__version__}")
    parser.add_argument("--home", help="Directory for alerts/history (default: ~/.crypto-alarm).")
    sub = parser.add_subparsers(dest="command")

    def notify_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--desktop", action="store_true", help="Also send a desktop notification.")
        p.add_argument("--webhook", help="Also POST alerts to this webhook URL (Slack/Discord compatible).")
        p.add_argument("--no-bell", action="store_true", help="Do not ring the terminal bell.")

    add = sub.add_parser("add", help="Add a price alert.")
    add.add_argument("--coin", required=True, help="Ticker or CoinGecko id (BTC, eth, solana...).")
    add.add_argument("--target", type=float, required=True, help="Target price.")
    add.add_argument("--direction", choices=["above", "below"], required=True)
    add.add_argument("--currency", default="usd", help="Quote currency (default: usd).")
    add.add_argument("--note", help="Free-text reminder shown when the alert fires.")
    add.add_argument("--repeat", action="store_true", help="Keep firing instead of disabling after the first hit.")
    add.add_argument("--cooldown", type=int, default=300, help="Seconds between repeats (default: 300).")
    add.set_defaults(func=cmd_add)

    lst = sub.add_parser("list", help="List configured alerts.")
    lst.add_argument("--all", action="store_true", help="Include disabled alerts.")
    lst.add_argument("--json", action="store_true")
    lst.set_defaults(func=cmd_list)

    rm = sub.add_parser("remove", help="Remove alerts by ID.")
    rm.add_argument("id", nargs="*")
    rm.add_argument("--all", action="store_true", help="Remove every alert.")
    rm.set_defaults(func=cmd_remove)

    en = sub.add_parser("enable", help="Re-arm an alert.")
    en.add_argument("id")
    en.set_defaults(func=cmd_enable)

    dis = sub.add_parser("disable", help="Disable an alert.")
    dis.add_argument("id")
    dis.set_defaults(func=cmd_disable)

    price = sub.add_parser("price", help="Show live prices.")
    price.add_argument("coins", nargs="*", help="Coins to quote (default: coins you have alerts for).")
    price.add_argument("--currency", default="usd")
    price.add_argument("--json", action="store_true")
    price.set_defaults(func=cmd_price)

    search = sub.add_parser("search", help="Find a coin's id by name or symbol.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.set_defaults(func=cmd_search)

    check = sub.add_parser("check", help="Evaluate alerts once against live prices.")
    check.add_argument("--coin", default="BTC", help="Coin label for manual mode.")
    check.add_argument("--price", type=float, help="Manual mode: current price instead of live data.")
    check.add_argument("--target", type=float, help="Manual mode: target price.")
    check.add_argument("--direction", choices=["above", "below"], help="Manual mode: trigger direction.")
    check.add_argument("--currency", default="usd")
    notify_flags(check)
    check.set_defaults(func=cmd_check)

    watch = sub.add_parser("watch", help="Poll prices continuously and fire alerts.")
    watch.add_argument("--interval", type=float, default=60.0, help="Seconds between checks (default: 60).")
    watch.add_argument("--iterations", type=int, help="Stop after this many checks (default: run forever).")
    watch.add_argument("--verbose", action="store_true", help="Print a line for every check.")
    notify_flags(watch)
    watch.set_defaults(func=cmd_watch)

    hist = sub.add_parser("history", help="Show alerts that have fired.")
    hist.add_argument("-n", "--limit", type=int, default=20)
    hist.add_argument("--json", action="store_true")
    hist.set_defaults(func=cmd_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Backwards compatibility with the original flag-only interface:
    #   crypto-alarm --price 25000 --target 24000 --direction above
    known = {"add", "list", "remove", "enable", "disable", "price", "search", "check", "watch", "history"}
    if argv and not (set(argv) & known) and any(a.startswith("--price") for a in argv):
        argv = ["check", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except PriceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
