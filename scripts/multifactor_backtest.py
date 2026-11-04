#!/usr/bin/env python3
"""Research-only multi-factor NSE intraday backtester (5-minute candles).

Tests all 2-, 3- and 4-factor combinations from:
trend (EMA20/EMA50), momentum (RSI14), relative volume (same clock slot,
prior sessions only), and trend strength (ADX14).
Signals are evaluated on completed candles and entered at the next bar open.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from intraday_backtest import (
    IST, apply_portfolio_limits, load_symbol, simulate_candidate, summarize,
)

FACTORS = ("trend", "momentum", "volume", "adx")
FACTOR_LABELS = {
    "trend": "EMA20/EMA50 trend",
    "momentum": "RSI14 momentum",
    "volume": "same-slot relative volume",
    "adx": "ADX14 trend strength",
}


def add_multifactor_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("timestamp").copy()
    close, high, low = df["close"], df["high"], df["low"]
    df["session"] = df["timestamp"].dt.date.astype(str)
    df["slot"] = df["timestamp"].dt.strftime("%H:%M")
    df["ema20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    df["ema50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi14"] = 100 - (100 / (1 + rs))
    df.loc[(loss == 0) & (gain > 0), "rsi14"] = 100
    df.loc[(gain == 0) & (loss > 0), "rsi14"] = 0

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/14, adjust=False, min_periods=14).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1/14, adjust=False, min_periods=14).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0, np.nan)
    df["adx14"] = dx.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    df["atr14"] = atr

    df["slot_volume_median20"] = df.groupby("slot", sort=False)["volume"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=10).median()
    )
    df["rvol_slot"] = df["volume"] / df["slot_volume_median20"].replace(0, np.nan)
    return df


def factor_conditions(bar: pd.Series, factors: tuple[str, ...], side: str) -> bool:
    for factor in factors:
        if factor == "trend":
            ok = bar["ema20"] > bar["ema50"] if side == "LONG" else bar["ema20"] < bar["ema50"]
        elif factor == "momentum":
            ok = bar["rsi14"] > 55 if side == "LONG" else bar["rsi14"] < 45
        elif factor == "volume":
            ok = bar["rvol_slot"] >= 1.3
        else:
            ok = bar["adx14"] > 20
        if not bool(ok):
            return False
    return True


def make_candidates(df: pd.DataFrame, factors: tuple[str, ...], side: str,
                    rr: float, stop_atr: float, max_stop_pct: float,
                    slippage_bps: float) -> list[dict]:
    out = []
    for session, day in df.groupby("session", sort=True):
        day = day.sort_values("timestamp").reset_index(drop=True)
        used = False
        for i, bar in day.iterrows():
            clock = bar["timestamp"].strftime("%H:%M")
            if clock < "09:45" or clock > "14:30" or used:
                continue
            needed = ["atr14", "ema20", "ema50", "rsi14", "adx14", "rvol_slot"]
            if not np.isfinite(bar[needed].astype(float)).all():
                continue
            if not factor_conditions(bar, factors, side) or i + 1 >= len(day):
                continue
            nxt = day.iloc[i+1]
            if (nxt["timestamp"] - bar["timestamp"]).total_seconds() > 305:
                continue
            atr = float(bar["atr14"])
            slip = slippage_bps / 10000
            entry = float(nxt["open"]) * (1 + slip if side == "LONG" else 1 - slip)
            distance = stop_atr * atr
            stop = entry - distance if side == "LONG" else entry + distance
            risk_pct = distance / entry if entry > 0 else 99
            if distance <= 0 or risk_pct > max_stop_pct:
                continue
            target = entry + rr*distance if side == "LONG" else entry - rr*distance
            score = sum([
                min(1.0, abs(float(bar["ema20"])-float(bar["ema50"])) / atr) if factor == "trend" else 0
                for factor in factors
            ]) + sum([
                min(1.0, abs(float(bar["rsi14"])-50)/20) if factor == "momentum" else 0
                for factor in factors
            ]) + sum([
                min(1.0, float(bar["rvol_slot"])/3) if factor == "volume" else 0
                for factor in factors
            ]) + sum([
                min(1.0, float(bar["adx14"])/40) if factor == "adx" else 0
                for factor in factors
            ])
            out.append({
                "symbol": str(bar["symbol"]), "session": session, "side": side,
                "signal_time": bar["timestamp"].isoformat(),
                "entry_time": nxt["timestamp"].isoformat(),
                "entry": entry, "stop": stop, "target": target,
                "risk_per_share": distance, "risk_pct": risk_pct,
                "rvol": float(bar["rvol_slot"]), "score": round(score, 4),
                "entry_bar_index": i+1, "bars": day,
                "slippage_bps": slippage_bps,
            })
            used = True
    return out


def evaluate(candidates, sessions, args):
    selected = [c for c in candidates if c["session"] in sessions]
    simulated = [
        simulate_candidate(c, args.capital, args.risk,
                           args.cost_bps_per_side, args.brokerage_per_order)
        for c in selected
    ]
    trades = [t for t in simulated if t is not None]
    accepted = apply_portfolio_limits(
        trades, args.max_positions, args.max_trades_day, args.daily_loss_limit
    )
    return summarize(accepted, args.capital), accepted


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default="data/intraday_5m")
    p.add_argument("--output", default="data/multifactor_research.json")
    p.add_argument("--trades-csv", default="data/multifactor_trades.csv")
    p.add_argument("--capital", type=float, default=100000)
    p.add_argument("--risk", type=float, default=500)
    p.add_argument("--daily-loss-limit", type=float, default=1000)
    p.add_argument("--stop-atr", type=float, default=1.5)
    p.add_argument("--max-stop-pct", type=float, default=0.02)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    p.add_argument("--cost-bps-per-side", type=float, default=6.0)
    p.add_argument("--brokerage-per-order", type=float, default=20.0)
    p.add_argument("--max-positions", type=int, default=2)
    p.add_argument("--max-trades-day", type=int, default=3)
    args = p.parse_args()

    files = sorted(Path(args.data_dir).glob("*.csv"))
    files = [f for f in files if f.name.lower() not in
             {"instruments.csv", "instruments.example.csv", "download_failures.csv"}]
    frames, failures, all_sessions = [], [], set()
    for path in files:
        try:
            frame = add_multifactor_features(load_symbol(path))
            frames.append(frame)
            all_sessions.update(frame["session"].unique())
        except Exception as exc:
            failures.append({"file": path.name, "error": str(exc)})
    dates = sorted(all_sessions)
    if len(dates) < 30:
        raise SystemExit(f"Only {len(dates)} sessions found; need at least 30.")
    n_train, n_valid = int(len(dates)*.60), int(len(dates)*.20)
    splits = {
        "train": set(dates[:n_train]),
        "validation": set(dates[n_train:n_train+n_valid]),
        "holdout_test": set(dates[n_train+n_valid:]),
    }

    rows = []
    best = None
    for size in (2, 3, 4):
        for factors in itertools.combinations(FACTORS, size):
            for side in ("LONG", "SHORT", "BOTH"):
                candidates = []
                sides = ("LONG", "SHORT") if side == "BOTH" else (side,)
                for frame in frames:
                    for direction in sides:
                        candidates.extend(make_candidates(
                            frame, factors, direction, 1.5, args.stop_atr,
                            args.max_stop_pct, args.slippage_bps
                        ))
                metrics = {name: evaluate(candidates, ds, args)[0]
                           for name, ds in splits.items()}
                row = {"factors": list(factors), "factor_names": [FACTOR_LABELS[x] for x in factors],
                       "side_mode": side, "reward_risk": 1.5, "stop_atr": args.stop_atr,
                       **metrics}
                rows.append(row)
                v = metrics["validation"]
                if v.get("trade_count", 0) >= 10:
                    key = v.get("expectancy_per_trade", float("-inf"))
                    if best is None or key > best[0]:
                        best = (key, row)

    output = {
        "strategy": "MULTIFACTOR_MOMENTUM_V1",
        "data_period": {"first_session": dates[0], "last_session": dates[-1], "sessions": len(dates)},
        "split": {"train_sessions": len(splits["train"]), "validation_sessions": len(splits["validation"]),
                  "holdout_test_sessions": len(splits["holdout_test"]), "chronological": True},
        "indicator_rules": {
            "trend": "LONG EMA20>EMA50; SHORT EMA20<EMA50",
            "momentum": "LONG RSI14>55; SHORT RSI14<45",
            "volume": "same clock-time slot volume >= 1.3x median of previous 20 sessions (minimum 10)",
            "adx": "ADX14>20 for either direction",
            "entry": "completed signal candle; enter next 5-minute candle open",
            "stop": f"{args.stop_atr} x ATR14 from entry; target 1.5R",
        },
        "parameters": vars(args),
        "best_validation_candidate": best[1] if best else None,
        "all_combinations": rows,
        "failed_files": failures,
        "warnings": [
            "Research only; not for live orders.",
            "40 sessions is a short sample and results may be unstable.",
            "Yahoo 5-minute data is limited and may contain gaps or vendor adjustments.",
            "Short trades are simulated; actual cash-market short availability and costs must be checked.",
            "Validation chooses combinations; holdout must remain untouched.",
        ],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(output, indent=2, allow_nan=False), encoding="utf-8")
    # Export validation/holdout trade ledgers for every combination in a separate compact file.
    ledgers = []
    for row in rows:
        factors = tuple(row["factors"])
        sides = ("LONG", "SHORT") if row["side_mode"] == "BOTH" else (row["side_mode"],)
        candidates = []
        for frame in frames:
            for direction in sides:
                candidates.extend(make_candidates(frame, factors, direction, 1.5,
                    args.stop_atr, args.max_stop_pct, args.slippage_bps))
        for split_name in ("validation", "holdout_test"):
            _, trades = evaluate(candidates, splits[split_name], args)
            for trade in trades:
                ledgers.append({**trade, "factors": "+".join(factors),
                                "side_mode": row["side_mode"], "split": split_name})
    pd.DataFrame(ledgers).to_csv(args.trades_csv, index=False)
    print(json.dumps({"strategy": output["strategy"], "sessions": len(dates),
                      "combinations_tested": len(rows), "best_validation_candidate": output["best_validation_candidate"],
                      "output": args.output, "trades_csv": args.trades_csv}, indent=2))


if __name__ == "__main__":
    main()
