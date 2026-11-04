#!/usr/bin/env python3
"""Download NSE 5-minute candles from DhanHQ into the backtester CSV format.

Requires DHAN_ACCESS_TOKEN in the environment and instruments.csv with:
symbol,security_id
Example: RELIANCE,2885
This is historical market-data retrieval only; it places no orders.
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

URL = "https://api.dhan.co/v2/charts/intraday"


def chunks(start: date, end: date, days: int = 89):
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=days), end)
        yield cursor, stop
        cursor = stop + timedelta(days=1)


def fetch_chunk(session, token, security_id, start, end):
    payload = {
        "securityId": str(security_id),
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "interval": "5",
        "oi": False,
        "fromDate": f"{start:%Y-%m-%d} 09:15:00",
        "toDate": f"{end:%Y-%m-%d} 15:30:00",
    }
    response = session.post(
        URL,
        headers={"access-token": token, "Content-Type": "application/json",
                 "Accept": "application/json"},
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not data.get("timestamp"):
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    required = ("open", "high", "low", "close", "volume", "timestamp")
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"Unexpected Dhan response; missing fields: {missing}")
    lengths = {len(data[k]) for k in required}
    if len(lengths) != 1:
        raise ValueError("Dhan candle arrays have inconsistent lengths")
    ts = pd.to_datetime(data["timestamp"], unit="s", utc=True).tz_convert("Asia/Kolkata")
    return pd.DataFrame({
        "timestamp": ts,
        "open": data["open"], "high": data["high"], "low": data["low"],
        "close": data["close"], "volume": data["volume"],
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instruments", default="data/intraday_5m/instruments.csv")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--output-dir", default="data/intraday_5m")
    parser.add_argument("--pause", type=float, default=0.25, help="Seconds between API calls")
    args = parser.parse_args()

    token = os.environ.get("DHAN_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Set DHAN_ACCESS_TOKEN in your environment; never commit it.")
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if start > end:
        raise SystemExit("--start must be on or before --end")
    instruments = pd.read_csv(args.instruments, dtype={"symbol": str, "security_id": str})
    if not {"symbol", "security_id"}.issubset(instruments.columns):
        raise SystemExit("instruments.csv must contain symbol,security_id columns")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    failures = []
    for row in instruments.itertuples(index=False):
        symbol, security_id = str(row.symbol).strip().upper(), str(row.security_id).strip()
        frames = []
        try:
            for left, right in chunks(start, end):
                frames.append(fetch_chunk(session, token, security_id, left, right))
                time.sleep(args.pause)
            frame = pd.concat(frames, ignore_index=True)
            if not frame.empty:
                frame = frame.drop_duplicates("timestamp").sort_values("timestamp")
                frame.to_csv(out_dir / f"{symbol}.csv", index=False)
            print(f"{symbol}: {len(frame):,} candles")
        except Exception as exc:
            failures.append({"symbol": symbol, "error": str(exc)})
            print(f"FAILED {symbol}: {exc}")

    if failures:
        pd.DataFrame(failures).to_csv(out_dir / "download_failures.csv", index=False)
        raise SystemExit(f"{len(failures)} symbols failed; see download_failures.csv")


if __name__ == "__main__":
    main()
