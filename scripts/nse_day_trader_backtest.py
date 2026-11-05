#!/usr/bin/env python3
"""Chronological research backtest for NSE ORB + VWAP + same-slot RVOL.

Input: one CSV per symbol (timestamp, open, high, low, close, volume).
No live data, broker integration, or order placement.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from nse_day_trader_scanner import add_features, load_symbol


def build_candidates(frame: pd.DataFrame, rvol_min: float, min_price: float,
                     min_avg_value: float, max_risk_pct: float,
                     reward_risk: float, slippage_bps: float) -> list[dict[str, Any]]:
    candidates = []
    for session, raw_day in frame.groupby("session", sort=True):
        day = raw_day.sort_values("timestamp").reset_index(drop=True)
        if day.empty or int(day["orb_count"].iloc[0]) != 6:
            continue
        used = False
        for i in range(6, len(day) - 1):
            bar = day.iloc[i]
            clock = bar["timestamp"].strftime("%H:%M")
            if clock < "09:45" or clock > "14:30" or used:
                continue
            if not np.isfinite(bar["rvol"]) or float(bar["rvol"]) < rvol_min:
                continue
            if not np.isfinite(bar["vwap"]) or not np.isfinite(bar["atr14"]):
                continue
            price = float(bar["close"])
            if price < min_price:
                continue
            prior = day.iloc[:i + 1]
            avg_value = float((prior["close"] * prior["volume"]).tail(20).mean())
            if avg_value < min_avg_value:
                continue
            side = None
            if price > float(bar["orb_high"]) and price > float(bar["vwap"]) and price > float(bar["open"]):
                side = "LONG"
            elif price < float(bar["orb_low"]) and price < float(bar["vwap"]) and price < float(bar["open"]):
                side = "SHORT"
            if side is None:
                continue
            signal_ts = bar["timestamp"]
            next_bar = day.iloc[i + 1]
            if (next_bar["timestamp"] - signal_ts).total_seconds() > 305:
                continue
            atr = float(bar["atr14"])
            if abs(float(next_bar["open"]) - price) > 0.5 * atr:
                continue
            buffer = max(price * 0.0005, atr * 0.10)
            stop = float(bar["low"] - buffer) if side == "LONG" else float(bar["high"] + buffer)
            slip = slippage_bps / 10000.0
            entry = float(next_bar["open"]) * (1 + slip if side == "LONG" else 1 - slip)
            risk_ps = entry - stop if side == "LONG" else stop - entry
            risk_pct = risk_ps / entry * 100 if entry > 0 else math.inf
            if risk_ps <= 0 or risk_pct < 0.10 or risk_pct > max_risk_pct:
                continue
            target = entry + reward_risk * risk_ps if side == "LONG" else entry - reward_risk * risk_ps
            candidates.append({
                "symbol": str(bar["symbol"]), "session": session, "side": side,
                "signal_time": signal_ts.isoformat(),
                "entry_time": next_bar["timestamp"].isoformat(),
                "entry": entry, "stop": stop, "target": target,
                "risk_per_share": risk_ps, "risk_pct": risk_pct,
                "rvol": float(bar["rvol"]), "vwap": float(bar["vwap"]),
                "score": 50 + min(25, max(0, (float(bar["rvol"]) - rvol_min) * 12)),
                "bars": day, "entry_index": i + 1,
                "slippage_bps": slippage_bps,
            })
            used = True
    return candidates


def simulate(c: dict[str, Any], capital: float, risk_cash: float,
             cost_bps_side: float, brokerage: float) -> dict[str, Any] | None:
    qty = min(math.floor(risk_cash / c["risk_per_share"]),
              math.floor(capital / c["entry"]))
    if qty <= 0:
        return None
    bars = c["bars"]
    side, stop, target = c["side"], c["stop"], c["target"]
    slip = c["slippage_bps"] / 10000.0
    exit_px = None
    exit_ts = None
    reason = None
    for j in range(c["entry_index"], len(bars)):
        b = bars.iloc[j]
        if side == "LONG":
            stop_hit = float(b["low"]) <= stop
            target_hit = float(b["high"]) >= target
            if stop_hit:
                px = min(stop, float(b["open"])) if j > c["entry_index"] else stop
                exit_px, reason = px * (1 - slip), "STOP"
            elif target_hit:
                exit_px, reason = target * (1 - slip), "TARGET"
        else:
            stop_hit = float(b["high"]) >= stop
            target_hit = float(b["low"]) <= target
            if stop_hit:
                px = max(stop, float(b["open"])) if j > c["entry_index"] else stop
                exit_px, reason = px * (1 + slip), "STOP"
            elif target_hit:
                exit_px, reason = target * (1 + slip), "TARGET"
        if exit_px is not None:
            exit_ts = b["timestamp"]
            break
        if b["timestamp"].strftime("%H:%M") >= "15:25":
            exit_px = float(b["close"]) * (1 - slip if side == "LONG" else 1 + slip)
            exit_ts, reason = b["timestamp"], "EOD"
            break
    if exit_px is None:
        b = bars.iloc[-1]
        exit_px = float(b["close"]) * (1 - slip if side == "LONG" else 1 + slip)
        exit_ts, reason = b["timestamp"], "DATA_END"
    gross = ((exit_px - c["entry"]) if side == "LONG" else (c["entry"] - exit_px)) * qty
    variable_cost = (c["entry"] + exit_px) * qty * cost_bps_side / 10000.0
    fees = variable_cost + 2 * brokerage
    net = gross - fees
    return {
        "symbol": c["symbol"], "session": c["session"], "side": side,
        "signal_time": c["signal_time"], "entry_time": c["entry_time"],
        "exit_time": exit_ts.isoformat(), "entry": round(c["entry"], 4),
        "exit": round(exit_px, 4), "stop": round(stop, 4),
        "target": round(target, 4), "quantity": qty,
        "risk_per_share": round(c["risk_per_share"], 4),
        "initial_risk": round(qty * c["risk_per_share"], 2),
        "risk_pct": round(c["risk_pct"], 3), "rvol": round(c["rvol"], 3),
        "score": round(c["score"], 2), "exit_reason": reason,
        "gross_pnl": round(gross, 2), "estimated_costs": round(fees, 2),
        "net_pnl": round(net, 2),
        "r_multiple": round(net / (qty * c["risk_per_share"]), 3),
    }


def apply_risk_limits(trades: list[dict[str, Any]], max_positions: int,
                      max_trades_day: int, daily_loss_limit: float) -> list[dict[str, Any]]:
    accepted = []
    by_day: dict[str, list[dict[str, Any]]] = {}
    for trade in sorted(trades, key=lambda x: (x["entry_time"], -x["score"], x["symbol"])):
        day_trades = by_day.setdefault(trade["session"], [])
        entry_ts = pd.Timestamp(trade["entry_time"])
        active = [x for x in day_trades if pd.Timestamp(x["exit_time"]) > entry_ts]
        realized = sum(x["net_pnl"] for x in day_trades if pd.Timestamp(x["exit_time"]) <= entry_ts)
        reserved_risk = sum(x["initial_risk"] for x in active)
        proposed_risk = float(trade["initial_risk"])
        if (len(day_trades) >= max_trades_day or len(active) >= max_positions
                or realized - reserved_risk - proposed_risk <= -daily_loss_limit
                or any(x["symbol"] == trade["symbol"] for x in day_trades)):
            continue
        day_trades.append(trade)
        accepted.append(trade)
    return accepted


def metrics(trades: list[dict[str, Any]], capital: float) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "net_pnl": 0.0, "win_rate_pct": 0.0,
                "profit_factor": None, "expectancy": None, "max_drawdown": 0.0}
    t = pd.DataFrame(trades).sort_values("exit_time")
    pnl = t["net_pnl"].astype(float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    equity = pd.concat([pd.Series([capital]), capital + pnl.cumsum().reset_index(drop=True)], ignore_index=True)
    dd = equity - equity.cummax()
    gp, gl = float(wins.sum()), abs(float(losses.sum()))
    return {
        "trades": int(len(t)), "net_pnl": round(float(pnl.sum()), 2),
        "return_pct_on_starting_capital": round(float(pnl.sum() / capital * 100), 3),
        "win_rate_pct": round(float((pnl > 0).mean() * 100), 2),
        "profit_factor": round(gp / gl, 3) if gl else None,
        "expectancy": round(float(pnl.mean()), 2),
        "average_win": round(float(wins.mean()), 2) if len(wins) else 0,
        "average_loss": round(float(losses.mean()), 2) if len(losses) else 0,
        "max_drawdown": round(float(dd.min()), 2),
        "exit_reasons": {str(k): int(v) for k, v in t["exit_reason"].value_counts().items()},
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default=str(ROOT / "data" / "intraday_5m"))
    p.add_argument("--output", default=str(ROOT / "data" / "nse_day_trader_backtest.json"))
    p.add_argument("--trades-csv", default=str(ROOT / "data" / "nse_day_trader_trades.csv"))
    p.add_argument("--capital", type=float, default=100000)
    p.add_argument("--risk", type=float, default=500)
    p.add_argument("--daily-loss-limit", type=float, default=1000)
    p.add_argument("--rvol", type=float, default=1.5)
    p.add_argument("--min-price", type=float, default=20)
    p.add_argument("--min-avg-value", type=float, default=10000000)
    p.add_argument("--max-risk-pct", type=float, default=1.0)
    p.add_argument("--rr", type=float, default=1.5)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    p.add_argument("--cost-bps-per-side", type=float, default=6.0)
    p.add_argument("--brokerage-per-order", type=float, default=20.0)
    p.add_argument("--max-positions", type=int, default=2)
    p.add_argument("--max-trades-day", type=int, default=3)
    args = p.parse_args()

    candidates, failures, symbols = [], [], 0
    for path in sorted(Path(args.data_dir).glob("*.csv")):
        try:
            frame = add_features(load_symbol(path))
            candidates.extend(build_candidates(frame, args.rvol, args.min_price,
                args.min_avg_value, args.max_risk_pct, args.rr, args.slippage_bps))
            symbols += 1
        except Exception as exc:
            failures.append({"file": path.name, "error": str(exc)})
    simulated = [simulate(c, args.capital, args.risk, args.cost_bps_per_side,
                          args.brokerage_per_order) for c in candidates]
    simulated = [x for x in simulated if x is not None]
    accepted = apply_risk_limits(simulated, args.max_positions,
                                 args.max_trades_day, args.daily_loss_limit)

    all_dates = sorted({t["session"] for t in accepted})
    split = int(len(all_dates) * 0.60)
    val_end = int(len(all_dates) * 0.80)
    train_dates = set(all_dates[:split])
    val_dates = set(all_dates[split:val_end])
    test_dates = set(all_dates[val_end:])
    splits = {
        "train": [t for t in accepted if t["session"] in train_dates],
        "validation": [t for t in accepted if t["session"] in val_dates],
        "holdout": [t for t in accepted if t["session"] in test_dates],
    }
    result = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "strategy": "NSE_ORB30_VWAP_SAME_SLOT_RVOL_V1",
        "data_source": "local per-symbol 5-minute OHLCV CSVs; provider and adjustment provenance not independently verified",
        "symbols_loaded": symbols, "failed_files": failures,
        "candidate_trades_before_portfolio_limits": len(simulated),
        "accepted_trades_after_portfolio_limits": len(accepted),
        "date_range": [all_dates[0], all_dates[-1]] if all_dates else None,
        "split_dates": {
            "train": [min(train_dates), max(train_dates)] if train_dates else None,
            "validation": [min(val_dates), max(val_dates)] if val_dates else None,
            "holdout": [min(test_dates), max(test_dates)] if test_dates else None,
        },
        "parameters": {
            "capital_inr": args.capital, "risk_per_trade_inr": args.risk,
            "daily_loss_limit_inr": args.daily_loss_limit, "rvol_min": args.rvol,
            "minimum_price_inr": args.min_price, "minimum_average_5m_traded_value_inr": args.min_avg_value,
            "maximum_stop_risk_pct": args.max_risk_pct, "reward_risk": args.rr,
            "slippage_bps_each_side": args.slippage_bps,
            "estimated_variable_cost_bps_each_side": args.cost_bps_per_side,
            "brokerage_per_order_inr": args.brokerage_per_order,
            "max_positions": args.max_positions, "max_trades_per_day": args.max_trades_day,
        },
        "metrics": {"all": metrics(accepted, args.capital),
                    **{k: metrics(v, args.capital) for k, v in splits.items()}},
        "assumptions": [
            "Signals use completed candles; entry is next 5-minute candle open with adverse slippage.",
            "Only first qualifying signal per symbol per session is traded.",
            "Same-bar stop and target collision resolves to stop.",
            "Gap-through stop receives the worse bar open; entry gaps over 0.5 ATR are rejected.",
            "VWAP resets each session; same-slot RVOL uses prior observations only.",
            "One trade per symbol per session; portfolio caps are applied chronologically.",
            "Daily loss gate reserves open-trade risk and includes proposed new-trade risk.",
            "Costs are configurable estimates, not broker contract-note calculations.",
            "Chronological 60/20/20 date split; do not tune on holdout.",
            "No survivorship-bias-free universe, corporate-action or event/news adjustment is supplied.",
        ],
        "limitations": [
            "Third-party intraday data may be incomplete, delayed, adjusted or inaccurate.",
            "No spread, market impact, queue position, partial fills or execution latency model.",
            "Short-side cash equity execution restrictions are not modelled.",
            "Small or empty validation/holdout samples are not evidence of a robust edge.",
        ],
        "trades": accepted,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    Path(args.trades_csv).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(accepted).to_csv(args.trades_csv, index=False)
    print(json.dumps({
        "symbols_loaded": symbols, "failed_files": len(failures),
        "candidates": len(simulated), "accepted_trades": len(accepted),
        "date_range": result["date_range"], "metrics": result["metrics"],
        "output": str(out), "trades_csv": args.trades_csv,
    }, indent=2))


if __name__ == "__main__":
    main()
