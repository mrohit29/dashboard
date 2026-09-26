import os
import json
import argparse
from datetime import datetime, time

import pytz
import pandas as pd
import yfinance as yf
import pandas_ta as ta

IST = pytz.timezone("Asia/Kolkata")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Reuse the exact watchlist from the live scanner without running its main().
ns = {}
with open(os.path.join(ROOT, "scripts", "stock_scanner.py"), encoding="utf-8") as f:
    exec(f.read().split("def main():")[0], ns)

WATCHLIST = ns["WATCHLIST"]


def replay_one(symbol, date):
    target = pd.Timestamp(date)
    start = (target - pd.Timedelta(days=12)).strftime("%Y-%m-%d")
    end = (target + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    # The live scanner uses roughly 10 days of 5-minute history. We need
    # the preceding candles so the 20/375-candle rolling indicators exist.
    d = yf.Ticker(symbol).history(
        start=start,
        end=end,
        interval="5m",
        auto_adjust=False,
    )

    if d.empty:
        return []

    d = d.copy()

    if d.index.tz is None:
        d.index = d.index.tz_localize("UTC").tz_convert(IST)
    else:
        d.index = d.index.tz_convert(IST)

    # Same indicators as the live scanner.
    d["VWAP"] = ta.vwap(d.High, d.Low, d.Close, d.Volume)
    d["VS"] = d.Volume.rolling(20).mean()
    d["V5"] = d.Volume.rolling(375).mean()
    # Actual previous 5 completed trading days for the breakout reference.
    daily = yf.Ticker(symbol).history(period="15d", interval="1d", auto_adjust=False)
    if daily.index.tz is None:
        daily.index = daily.index.tz_localize(IST)
    else:
        daily.index = daily.index.tz_convert(IST)
    daily = daily[daily.index.date < target.date()]
    prev5 = daily.tail(5)
    if len(prev5) < 5:
        return []
    five_day_high = float(prev5.High.max())
    five_day_low = float(prev5.Low.min())
    d["ATR"] = ta.atr(d.High, d.Low, d.Close, length=14)

    day = d[d.index.date == target.date()].copy()
    if day.empty:
        return []

    # Opening range: 09:00 through 09:40 IST.
    morning = day[
        (day.index.hour == 9) &
        (day.index.minute < 45)
    ]

    if morning.empty:
        return []

    orbhi = float(morning.High.max())
    orblo = float(morning.Low.min())
    signals = []

    for i in range(len(day)):
        x = day.iloc[i]
        p = float(x.Close)

        # The live scanner does not evaluate before 09:45.
        if day.index[i].time() < time(9, 45):
            continue

        bull = (
            int(p > x.VWAP)
            + int(x.Volume > 1.5 * x.VS)
            + int(x.Volume > 2 * x.V5)
        )
        bear = (
            int(p < x.VWAP)
            + int(x.Volume > 1.5 * x.VS)
            + int(x.Volume > 2 * x.V5)
        )

        direction = None

        if (
            bull >= 3
            and p > orbhi
            and p > five_day_high
        ):
            direction = "LONG"

        elif (
            bear >= 3
            and p < orblo
            and p < five_day_low
        ):
            direction = "SHORT"

        if not direction:
            continue

        # Same SL search used by the live scanner.
        sl = None
        for j in range(max(0, i - 20), i):
            c = day.iloc[j]

            if direction == "LONG" and c.Close < c.Open:
                sl = float(c.Low * 0.9995)
                break

            if direction == "SHORT" and c.Close > c.Open:
                sl = float(c.High * 1.0005)
                break

        # Same ATR fallback.
        if sl is None:
            atr = float(x.ATR) if pd.notna(x.ATR) else p * 0.01
            sl = p - 1.5 * atr if direction == "LONG" else p + 1.5 * atr

        risk = abs(p - sl) / p * 100

        if risk > 1:
            continue

        target_price = (
            p + 2 * (p - sl)
            if direction == "LONG"
            else p - 2 * (sl - p)
        )

        signals.append({
            "symbol": symbol.replace(".NS", ""),
            "time": day.index[i].strftime("%H:%M"),
            "direction": direction,
            "entry": round(p, 2),
            "sl": round(sl, 2),
            "target": round(target_price, 2),
            "risk_pct": round(risk, 2),
        })

    return signals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    signals = []

    for symbol in WATCHLIST:
        try:
            signals.extend(replay_one(symbol, args.date))
        except Exception as exc:
            print(f"{symbol}: {exc}")

    result = {
        "date": args.date,
        "generated_ist": datetime.now(IST).isoformat(),
        "signals": signals,
        "unique_stocks": sorted({x["symbol"] for x in signals}),
    }

    output_path = os.path.join(
        ROOT,
        "data",
        f"historical_scanner_{args.date}.json",
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(
        json.dumps(
            {
                "date": args.date,
                "signals": len(signals),
                "unique_stocks": len(result["unique_stocks"]),
                "stocks": result["unique_stocks"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
