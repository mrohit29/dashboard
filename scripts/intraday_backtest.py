#!/usr/bin/env python3
"""Research-grade, long/short NSE cash intraday ORB backtester.

Input: one CSV per symbol with timestamp, open, high, low, close, volume.
Timestamps may be ISO-8601 or naive IST. Bars are labelled by their START time.
Signals are evaluated only after a completed 5-minute bar; fills occur at the
NEXT bar open. If stop and target are both touched in one bar, stop wins.
This is a research simulator, not a broker execution engine.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IST = "Asia/Kolkata"
REQUIRED = {"timestamp", "open", "high", "low", "close", "volume"}


def load_symbol(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "datetime" in df.columns and "timestamp" not in df.columns:
        df = df.rename(columns={"datetime": "timestamp"})
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    if ts.isna().any():
        raise ValueError(f"{path.name}: invalid timestamps")
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(IST)
    else:
        ts = ts.dt.tz_convert(IST)
    df["timestamp"] = ts
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=list(REQUIRED - {"timestamp"}))
    df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    df = df[(df["timestamp"].dt.strftime("%H:%M") >= "09:15") &
            (df["timestamp"].dt.strftime("%H:%M") <= "15:25")].copy()
    valid = ((df["high"] >= df[["open", "close", "low"]].max(axis=1)) &
             (df["low"] <= df[["open", "close", "high"]].min(axis=1)) &
             (df["volume"] >= 0))
    df = df[valid].reset_index(drop=True)
    if df.empty:
        raise ValueError(f"{path.name}: no valid regular-session bars")
    df["symbol"] = path.stem.replace(".NS", "").upper()
    return df


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["session"] = df["timestamp"].dt.date.astype(str)
    df["slot"] = df["timestamp"].dt.strftime("%H:%M")
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    df["vwap"] = pv.groupby(df["session"]).cumsum() / df["volume"].groupby(df["session"]).cumsum().replace(0, np.nan)
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14, min_periods=10).mean()
    # Same clock-time volume compared only with earlier sessions; shift(1)
    # prevents the current session from leaking into its own baseline.
    df["slot_volume_median20"] = df.groupby("slot", sort=False)["volume"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=10).median()
    )
    df["rvol_slot"] = df["volume"] / df["slot_volume_median20"].replace(0, np.nan)
    # Opening range uses the six 5-minute bars beginning 09:15 through 09:40.
    opening = df[df["timestamp"].dt.strftime("%H:%M").between("09:15", "09:40")]
    ranges = opening.groupby("session").agg(orb_high=("high", "max"), orb_low=("low", "min"), orb_bars=("high", "count"))
    df = df.join(ranges, on="session")
    return df


def make_candidates(df: pd.DataFrame, rvol_min: float, rr: float,
                    max_stop_pct: float, slippage_bps: float) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for session, day in df.groupby("session", sort=True):
        day = day.sort_values("timestamp").reset_index(drop=True)
        if day["orb_bars"].iloc[0] != 6:
            continue
        used = False
        for i, bar in day.iterrows():
            clock = bar["timestamp"].strftime("%H:%M")
            if clock < "09:45" or clock > "14:30" or used:
                continue
            if not np.isfinite(bar["vwap"]) or not np.isfinite(bar["rvol_slot"]):
                continue
            side = None
            if bar["close"] > bar["orb_high"] and bar["close"] > bar["vwap"] and bar["rvol_slot"] >= rvol_min and bar["close"] > bar["open"]:
                side = "LONG"
            elif bar["close"] < bar["orb_low"] and bar["close"] < bar["vwap"] and bar["rvol_slot"] >= rvol_min and bar["close"] < bar["open"]:
                side = "SHORT"
            if side is None or i + 1 >= len(day):
                continue
            next_bar = day.iloc[i + 1]
            if (next_bar["timestamp"] - bar["timestamp"]).total_seconds() > 5 * 60 + 5:
                continue
            atr = float(bar["atr14"]) if np.isfinite(bar["atr14"]) else float(bar["close"]) * 0.005
            buffer = max(float(bar["close"]) * 0.0005, atr * 0.10)
            raw_stop = float(bar["low"] - buffer) if side == "LONG" else float(bar["high"] + buffer)
            slip = slippage_bps / 10000.0
            entry = float(next_bar["open"]) * (1 + slip if side == "LONG" else 1 - slip)
            stop = raw_stop
            risk_per_share = entry - stop if side == "LONG" else stop - entry
            risk_pct = risk_per_share / entry if entry > 0 else 99
            # Reject both noise-sized stops and impractically wide stops.
            if risk_per_share <= 0 or risk_pct < 0.002 or risk_pct > max_stop_pct:
                continue
            target = entry + rr * risk_per_share if side == "LONG" else entry - rr * risk_per_share
            # Do not chase a gap that has already consumed > 0.5 ATR.
            if abs(float(next_bar["open"]) - float(bar["close"])) > 0.5 * atr:
                continue
            score = 50.0 + min(25.0, max(0.0, (float(bar["rvol_slot"]) - rvol_min) * 12.0))
            score += min(15.0, abs(float(bar["close"]) - float(bar["orb_high"] if side == "LONG" else bar["orb_low"])) / atr * 5.0)
            candidates.append({
                "symbol": str(bar["symbol"]), "session": session, "side": side,
                "signal_time": bar["timestamp"].isoformat(),
                "entry_time": next_bar["timestamp"].isoformat(),
                "entry": entry, "stop": stop, "target": target,
                "risk_per_share": risk_per_share, "risk_pct": risk_pct,
                "rvol": float(bar["rvol_slot"]), "score": round(score, 2),
                "entry_bar_index": i + 1, "bars": day,
                "slippage_bps": slippage_bps,
            })
            used = True
    return candidates


def simulate_candidate(c: dict[str, Any], capital: float, risk_cash: float,
                       max_cost_bps_per_side: float, brokerage_per_order: float) -> dict[str, Any] | None:
    bars = c["bars"]
    side = c["side"]
    entry = float(c["entry"])
    stop = float(c["stop"])
    target = float(c["target"])
    qty_risk = math.floor(risk_cash / c["risk_per_share"])
    qty_capital = math.floor(capital / entry)
    qty = max(0, min(qty_risk, qty_capital))
    if qty <= 0:
        return None
    start = int(c["entry_bar_index"])
    exit_price = None
    exit_time = None
    reason = None
    slip = c["slippage_bps"] / 10000.0
    for j in range(start, len(bars)):
        b = bars.iloc[j]
        if side == "LONG":
            stop_hit = float(b["low"]) <= stop
            target_hit = float(b["high"]) >= target
            if stop_hit:
                # Gap-through stop receives the worse opening price.
                px = min(stop, float(b["open"])) if j > start else stop
                exit_price, reason = px * (1 - slip), "STOP"
            elif target_hit:
                exit_price, reason = target * (1 - slip), "TARGET"
        else:
            stop_hit = float(b["high"]) >= stop
            target_hit = float(b["low"]) <= target
            if stop_hit:
                px = max(stop, float(b["open"])) if j > start else stop
                exit_price, reason = px * (1 + slip), "STOP"
            elif target_hit:
                exit_price, reason = target * (1 + slip), "TARGET"
        if exit_price is not None:
            exit_time = b["timestamp"]
            break
        if b["timestamp"].strftime("%H:%M") >= "15:25":
            exit_price = float(b["close"]) * (1 - slip if side == "LONG" else 1 + slip)
            exit_time, reason = b["timestamp"], "EOD"
            break
    if exit_price is None:
        b = bars.iloc[-1]
        exit_price = float(b["close"]) * (1 - slip if side == "LONG" else 1 + slip)
        exit_time, reason = b["timestamp"], "DATA_END"
    gross = (exit_price - entry) * qty if side == "LONG" else (entry - exit_price) * qty
    turnover = (entry + exit_price) * qty
    variable_cost = turnover * (max_cost_bps_per_side / 10000.0)
    net = gross - variable_cost - 2 * brokerage_per_order
    return {
        "symbol": c["symbol"], "session": c["session"], "side": side,
        "signal_time": c["signal_time"], "entry_time": c["entry_time"],
        "exit_time": exit_time.isoformat(), "entry": round(entry, 4),
        "exit": round(exit_price, 4), "stop": round(stop, 4),
        "target": round(target, 4), "quantity": qty, "score": c["score"],
        "rvol": round(c["rvol"], 3), "exit_reason": reason,
        "gross_pnl": round(gross, 2), "estimated_costs": round(variable_cost + 2 * brokerage_per_order, 2),
        "net_pnl": round(net, 2), "initial_risk": round(c["risk_per_share"] * qty, 2),
        "r_multiple": round(net / (c["risk_per_share"] * qty), 3),
    }


def apply_portfolio_limits(trades: list[dict[str, Any]], max_positions: int,
                           max_trades_day: int, daily_loss_limit: float) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    by_day: dict[str, list[dict[str, Any]]] = {}
    for t in sorted(trades, key=lambda x: (x["entry_time"], -x["score"], x["symbol"])):
        day = t["session"]
        day_trades = by_day.setdefault(day, [])
        entry_ts = pd.Timestamp(t["entry_time"])
        active = [x for x in day_trades if pd.Timestamp(x["exit_time"]) > entry_ts]
        realized = sum(x["net_pnl"] for x in day_trades if pd.Timestamp(x["exit_time"]) <= entry_ts)
        # Reserve each open trade's initial risk against the daily loss budget.
        # This prevents adding fresh risk while existing positions already use
        # the remaining daily loss allowance.
        reserved_open_risk = sum(float(x["initial_risk"]) for x in active)
        if (len(day_trades) >= max_trades_day or len(active) >= max_positions
                or realized - reserved_open_risk <= -daily_loss_limit):
            continue
        if any(x["symbol"] == t["symbol"] for x in day_trades):
            continue
        day_trades.append(t)
        accepted.append(t)
    return accepted


def summarize(trades: list[dict[str, Any]], capital: float) -> dict[str, Any]:
    if not trades:
        return {"trade_count": 0, "warning": "No trades. Check data coverage and strategy filters."}
    t = pd.DataFrame(trades).sort_values("exit_time")
    pnl = t["net_pnl"].astype(float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    # Include starting capital as the initial equity point; otherwise a
    # first-trade loss would incorrectly show zero drawdown.
    equity = pd.concat(
        [pd.Series([capital], dtype=float), capital + pnl.cumsum().reset_index(drop=True)],
        ignore_index=True,
    )
    peak = equity.cummax()
    drawdown = equity - peak
    gross_profit = float(wins.sum())
    gross_loss = abs(float(losses.sum()))
    return {
        "trade_count": int(len(t)),
        "win_rate_pct": round(float((pnl > 0).mean() * 100), 2),
        "net_pnl": round(float(pnl.sum()), 2),
        "return_pct_on_starting_capital": round(float(pnl.sum() / capital * 100), 3),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
        "expectancy_per_trade": round(float(pnl.mean()), 2),
        "average_win": round(float(wins.mean()), 2) if len(wins) else 0,
        "average_loss": round(float(losses.mean()), 2) if len(losses) else 0,
        "max_drawdown": round(float(drawdown.min()), 2),
        "max_drawdown_pct": round(float((drawdown / peak).min() * 100), 3),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "exit_reasons": {str(k): int(v) for k, v in t["exit_reason"].value_counts().items()},
        "by_side": {
            side: {"trades": int(len(g)), "net_pnl": round(float(g["net_pnl"].sum()), 2),
                   "win_rate_pct": round(float((g["net_pnl"] > 0).mean() * 100), 2)}
            for side, g in t.groupby("side")
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default=str(ROOT / "data" / "intraday_5m"))
    p.add_argument("--output", default=str(ROOT / "data" / "intraday_backtest.json"))
    p.add_argument("--trades-csv", default=str(ROOT / "data" / "intraday_trades.csv"))
    p.add_argument("--capital", type=float, default=100000)
    p.add_argument("--risk", type=float, default=500)
    p.add_argument("--daily-loss-limit", type=float, default=1000)
    p.add_argument("--rvol", type=float, default=1.5)
    p.add_argument("--rr", type=float, default=1.5)
    p.add_argument("--max-stop-pct", type=float, default=0.01)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    p.add_argument("--cost-bps-per-side", type=float, default=6.0,
                   help="Estimated all-in variable charges per side; replace with broker tariff.")
    p.add_argument("--brokerage-per-order", type=float, default=20.0)
    p.add_argument("--max-positions", type=int, default=2)
    p.add_argument("--max-trades-day", type=int, default=3)
    args = p.parse_args()

    files = sorted(Path(args.data_dir).glob("*.csv"))
    if not files:
        raise SystemExit(f"No symbol CSVs found in {args.data_dir}. See docs/intraday_strategy_v1.md.")
    all_candidates: list[dict[str, Any]] = []
    symbols_loaded, failures = [], []
    for path in files:
        try:
            frame = add_features(load_symbol(path))
            all_candidates.extend(make_candidates(frame, args.rvol, args.rr, args.max_stop_pct, args.slippage_bps))
            symbols_loaded.append(path.stem)
        except Exception as exc:
            failures.append({"file": path.name, "error": str(exc)})
    simulated = [simulate_candidate(c, args.capital, args.risk, args.cost_bps_per_side, args.brokerage_per_order)
                 for c in all_candidates]
    simulated = [x for x in simulated if x is not None]
    accepted = apply_portfolio_limits(simulated, args.max_positions, args.max_trades_day, args.daily_loss_limit)
    summary = summarize(accepted, args.capital)
    result = {
        "strategy": "ORB_30M_VWAP_SLOT_RVOL_V1",
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "data_dir": str(args.data_dir), "symbols_loaded": symbols_loaded,
        "failed_files": failures, "candidate_count_before_portfolio_limits": len(simulated),
        "parameters": {
            "capital": args.capital, "risk_per_trade": args.risk,
            "daily_loss_limit": args.daily_loss_limit, "rvol_min": args.rvol,
            "reward_risk": args.rr, "max_stop_pct": args.max_stop_pct,
            "slippage_bps_each_side": args.slippage_bps,
            "estimated_variable_cost_bps_each_side": args.cost_bps_per_side,
            "brokerage_per_order": args.brokerage_per_order,
            "max_positions": args.max_positions, "max_trades_per_day": args.max_trades_day,
        },
        "execution_assumptions": [
            "Signals use completed 5-minute candles and enter at the next candle open.",
            "Same-bar stop and target collision resolves to stop (conservative).",
            "Only the first valid signal per symbol per session is considered.",
            "No look-ahead in same-time-slot relative volume: prior sessions only.",
            "No survivorship-bias-free universe or corporate-action adjustment is supplied by this engine.",
            "Costs are configurable estimates, not a broker contract-note calculation.",
        ],
        "summary": summary, "trades": accepted,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    csv_path = Path(args.trades_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(accepted).to_csv(csv_path, index=False)
    print(json.dumps({"symbols_loaded": len(symbols_loaded), "candidates": len(simulated),
                      "accepted_trades": len(accepted), "summary": summary,
                      "output": str(out), "trades_csv": str(csv_path)}, indent=2))


if __name__ == "__main__":
    main()
