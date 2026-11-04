#!/usr/bin/env python3
"""Split Yahoo Finance combined 5-minute OHLCV CSV into per-symbol files.

The output format matches scripts/intraday_backtest.py:
  timestamp,open,high,low,close,volume

Example:
  python scripts/import_yahoo_5m.py \
    --input /path/to/all_nse_5m.csv.gz \
    --output-dir data/intraday_5m

Optional universe filter:
  python scripts/import_yahoo_5m.py --input all_nse_5m.csv.gz \
    --symbols-file nifty500_symbols.csv --output-dir data/intraday_5m
The symbols file must contain a SYMBOL column or one symbol per line.
"""

import argparse
from pathlib import Path
import pandas as pd

REQUIRED = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]


def load_symbols(path: str | None) -> set[str] | None:
    if not path:
        return None
    p = Path(path)
    if p.suffix.lower() == ".csv":
        frame = pd.read_csv(p)
        col = next((c for c in frame.columns if c.strip().upper() == "SYMBOL"), None)
        if col is None:
            raise ValueError("Symbols CSV must contain a SYMBOL column")
        values = frame[col].dropna().astype(str).str.strip()
    else:
        values = pd.read_csv(p, header=None)[0].dropna().astype(str).str.strip()
    return set(values.str.replace(r"\.NS$", "", regex=True).str.upper())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Combined .csv or .csv.gz")
    parser.add_argument("--output-dir", default="data/intraday_5m")
    parser.add_argument("--symbols-file", help="Optional CSV/TXT universe filter")
    parser.add_argument("--chunksize", type=int, default=500_000)
    args = parser.parse_args()

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    allowed = load_symbols(args.symbols_file)
    seen = set()
    total_rows = 0

    for chunk in pd.read_csv(args.input, compression="infer", chunksize=args.chunksize):
        chunk.columns = [str(c).strip().lower() for c in chunk.columns]
        missing = set(REQUIRED) - set(chunk.columns)
        if missing:
            raise ValueError(f"Input is missing columns: {sorted(missing)}")

        chunk["symbol"] = chunk["symbol"].astype(str).str.strip().str.upper()
        if allowed is not None:
            chunk = chunk[chunk["symbol"].isin(allowed)]
        if chunk.empty:
            continue

        chunk["timestamp"] = pd.to_datetime(chunk["timestamp"], errors="coerce")
        for col in ["open", "high", "low", "close", "volume"]:
            chunk[col] = pd.to_numeric(chunk[col], errors="coerce")
        chunk = chunk.dropna(subset=REQUIRED)
        chunk = chunk[(chunk[["open", "high", "low", "close"]] > 0).all(axis=1)]
        chunk = chunk[chunk["volume"] >= 0]
        chunk = chunk[REQUIRED]

        for symbol, group in chunk.groupby("symbol", sort=False):
            path = output / f"{symbol}.csv"
            write_header = not path.exists()
            group.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").to_csv(
                path, mode="a", header=write_header, index=False
            )
            seen.add(symbol)
            total_rows += len(group)

    # Final stable ordering and duplicate removal across chunk boundaries.
    for symbol in sorted(seen):
        path = output / f"{symbol}.csv"
        frame = pd.read_csv(path, parse_dates=["timestamp"])
        frame = frame.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        frame.to_csv(path, index=False)

    print(f"Imported {total_rows:,} rows across {len(seen):,} symbols into {output}")


if __name__ == "__main__":
    main()
