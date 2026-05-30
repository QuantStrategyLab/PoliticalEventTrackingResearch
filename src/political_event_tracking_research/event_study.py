from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .csv_utils import read_csv_rows, write_csv_rows


@dataclass(frozen=True)
class Event:
    event_id: str
    event_date: date
    symbol: str
    event_type: str
    direction: str
    confidence: str
    source_url: str
    notes: str


@dataclass(frozen=True)
class EventReturn:
    event_id: str
    event_date: date
    symbol: str
    event_type: str
    window_days: int
    base_date: date
    exit_date: date
    base_close: float
    exit_close: float
    return_pct: float
    benchmark_symbol: str
    benchmark_return_pct: float | None
    abnormal_return_pct: float | None

    def to_row(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "event_date": self.event_date.isoformat(),
            "symbol": self.symbol,
            "event_type": self.event_type,
            "window_days": self.window_days,
            "base_date": self.base_date.isoformat(),
            "exit_date": self.exit_date.isoformat(),
            "base_close": f"{self.base_close:.6f}",
            "exit_close": f"{self.exit_close:.6f}",
            "return_pct": f"{self.return_pct:.6f}",
            "benchmark_symbol": self.benchmark_symbol,
            "benchmark_return_pct": "" if self.benchmark_return_pct is None else f"{self.benchmark_return_pct:.6f}",
            "abnormal_return_pct": "" if self.abnormal_return_pct is None else f"{self.abnormal_return_pct:.6f}",
        }


PriceTable = dict[str, dict[date, float]]


def parse_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def load_events(path: str | Path) -> list[Event]:
    events: list[Event] = []
    for row in read_csv_rows(path):
        events.append(
            Event(
                event_id=row["event_id"],
                event_date=parse_date(row["event_date"]),
                symbol=row["symbol"].upper(),
                event_type=row["event_type"],
                direction=row.get("direction", ""),
                confidence=row.get("confidence", ""),
                source_url=row.get("source_url", ""),
                notes=row.get("notes", ""),
            )
        )
    return events


def load_prices(path: str | Path) -> PriceTable:
    prices: PriceTable = {}
    for row in read_csv_rows(path):
        date_value = row.get("date") or row.get("as_of")
        if not date_value:
            raise ValueError("Price rows must include either 'date' or 'as_of'.")
        symbol = row["symbol"].upper()
        prices.setdefault(symbol, {})[parse_date(date_value)] = float(row["close"])
    return prices


def sorted_dates(prices: PriceTable, symbol: str) -> list[date]:
    return sorted(prices.get(symbol.upper(), {}))


def first_trading_date_on_or_after(dates: list[date], target: date) -> date | None:
    for candidate in dates:
        if candidate >= target:
            return candidate
    return None


def trading_date_offset(dates: list[date], base: date, offset: int) -> date | None:
    try:
        base_index = dates.index(base)
    except ValueError:
        return None
    target_index = base_index + offset
    if target_index >= len(dates):
        return None
    return dates[target_index]


def percentage_return(start: float, end: float) -> float:
    if start == 0:
        raise ValueError("Cannot compute return from a zero start price.")
    return (end / start - 1.0) * 100.0


def compute_event_returns(
    events: list[Event],
    prices: PriceTable,
    windows: tuple[int, ...] = (1, 5, 20),
    benchmark_symbol: str = "SPY",
) -> list[EventReturn]:
    results: list[EventReturn] = []
    benchmark_symbol = benchmark_symbol.upper()

    for event in events:
        symbol_dates = sorted_dates(prices, event.symbol)
        base_date = first_trading_date_on_or_after(symbol_dates, event.event_date)
        if base_date is None:
            continue
        base_close = prices[event.symbol][base_date]

        benchmark_base_close = prices.get(benchmark_symbol, {}).get(base_date)

        for window in windows:
            exit_date = trading_date_offset(symbol_dates, base_date, window)
            if exit_date is None:
                continue
            exit_close = prices[event.symbol][exit_date]
            event_return = percentage_return(base_close, exit_close)

            benchmark_return: float | None = None
            abnormal_return: float | None = None
            if benchmark_base_close is not None:
                benchmark_exit_close = prices.get(benchmark_symbol, {}).get(exit_date)
                if benchmark_exit_close is not None:
                    benchmark_return = percentage_return(benchmark_base_close, benchmark_exit_close)
                    abnormal_return = event_return - benchmark_return

            results.append(
                EventReturn(
                    event_id=event.event_id,
                    event_date=event.event_date,
                    symbol=event.symbol,
                    event_type=event.event_type,
                    window_days=window,
                    base_date=base_date,
                    exit_date=exit_date,
                    base_close=base_close,
                    exit_close=exit_close,
                    return_pct=event_return,
                    benchmark_symbol=benchmark_symbol,
                    benchmark_return_pct=benchmark_return,
                    abnormal_return_pct=abnormal_return,
                )
            )

    return results


def parse_windows(value: str) -> tuple[int, ...]:
    windows = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    if not windows:
        raise ValueError("At least one window is required.")
    if any(window < 0 for window in windows):
        raise ValueError("Windows must be non-negative trading-day offsets.")
    return windows


def run_event_study(
    events_path: str | Path,
    prices_path: str | Path,
    output_path: str | Path,
    windows: tuple[int, ...] = (1, 5, 20),
    benchmark_symbol: str = "SPY",
) -> list[EventReturn]:
    events = load_events(events_path)
    prices = load_prices(prices_path)
    results = compute_event_returns(events, prices, windows=windows, benchmark_symbol=benchmark_symbol)
    write_csv_rows(
        output_path,
        [
            "event_id",
            "event_date",
            "symbol",
            "event_type",
            "window_days",
            "base_date",
            "exit_date",
            "base_close",
            "exit_close",
            "return_pct",
            "benchmark_symbol",
            "benchmark_return_pct",
            "abnormal_return_pct",
        ],
        [result.to_row() for result in results],
    )
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a lightweight daily-close event study.")
    parser.add_argument("--events", required=True, help="CSV event file.")
    parser.add_argument("--prices", required=True, help="CSV price file with date/as_of,symbol,close.")
    parser.add_argument("--output", required=True, help="Output CSV path.")
    parser.add_argument("--windows", default="1,5,20", help="Comma-separated trading-day offsets.")
    parser.add_argument("--benchmark", default="SPY", help="Benchmark symbol for abnormal returns.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    run_event_study(
        events_path=args.events,
        prices_path=args.prices,
        output_path=args.output,
        windows=parse_windows(args.windows),
        benchmark_symbol=args.benchmark,
    )


if __name__ == "__main__":
    main()
