#!/usr/bin/env python3
"""Research-only NSE 5-minute scanner for completed-candle ORB/VWAP/RVOL setups.

Reads one CSV per symbol from data/intraday_5m. It creates a ranked watchlist;
it does not place orders or claim that a signal is executable. Candle timestamps
are candle START times in Asia/Kolkata.
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
    frame = pd.read_csv(path)
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    if "datetime" in frame and "timestamp" not in frame:
        frame = frame.rename(columns={"datetime": "timestamp"})
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    ts = pd.to_datetime(frame["timestamp"], errors="coerce")
    if ts.isna().any():
        raise ValueError("invalid timestamp")
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(IST)
    else:
        ts = ts.dt.tz_convert(IST)
    frame["timestamp"] = ts
    for col in REQUIRED - {"timestamp"}:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=list(REQUIRED - {"timestamp"}))
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    frame = frame[(frame["timestamp"].dt.strftime("%H:%M") >= "09:15") &
                  (frame["timestamp"].dt.strftime("%H:%M") <= "15:25")].copy()
    valid = (
        (frame[["open", "high", "low", "close"]] > 0).all(axis=1)
        & (frame["volume"] >= 0)
        & (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
        & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
    )
    frame = frame.loc[valid].reset_index(drop=True)
    if frame.empty:
        raise ValueError("no valid regular-session candles")
    frame["symbol"] = path.stem.replace(".NS", "").upper()
    frame["session"] = frame["timestamp"].dt.strftime("%Y-%m-%d")
    frame["slot"] = frame["timestamp"].dt.strftime("%H:%M")
    return frame


def add_features(frame: pd.DataFrame, min_history: int = 5) -> pd.DataFrame:
    frame = frame.copy()
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    pv = typical * frame["volume"]
    cum_vol = frame["volume"].groupby(frame["session"]).cumsum().replace(0, np.nan)
    frame["vwap"] = pv.groupby(frame["session"]).cumsum() / cum_vol
    prev_close = frame.groupby("session")["close"].shift(1)
    tr = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - prev_close).abs(),
        (frame["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    frame["atr14"] = tr.groupby(frame["session"]).transform(
        lambda s: s.rolling(14, min_periods=5).mean()
    )
    # Same clock-time slot, strictly prior observations only.
    frame["slot_median"] = frame.groupby("slot", sort=False)["volume"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=min_history).median()
    )
    frame["rvol"] = frame["volume"] / frame["slot_median"].replace(0, np.nan)
    opening = frame[frame["slot"].between("09:15", "09:40")]
    ranges = opening.groupby("session").agg(
        orb_high=("high", "max"), orb_low=("low", "min"), orb_count=("high", "count")
    )
    return frame.join(ranges, on="session")


def scan_frame(frame: pd.DataFrame, rvol_min: float = 1.5,
               min_price: float = 20.0, min_avg_value: float = 10_000_000,
               max_risk_pct: float = 1.0, reward_risk: float = 1.5,
               risk_cash: float = 500.0) -> tuple[dict[str, Any] | None, str]:
    latest_session = frame["session"].max()
    day = frame[frame["session"] == latest_session].sort_values("timestamp").reset_index(drop=True)
    if day.empty:
        return None, "no latest-session candles"
    if int(day["orb_count"].iloc[0]) != 6:
        return None, "opening range incomplete (expected six 5-minute bars)"
    last = day.iloc[-1]
    last_time = last["timestamp"]
    # Ignore the currently forming candle based on wall-clock time.
    now = pd.Timestamp.now(tz=IST)
    if last_time + pd.Timedelta(minutes=5) > now:
        day = day.iloc[:-1].copy()
        if day.empty:
            return None, "no completed candle available"
        last = day.iloc[-1]
        last_time = last["timestamp"]
    if now.date() == last_time.date() and (now - (last_time + pd.Timedelta(minutes=5))).total_seconds() > 15 * 60:
        return None, "latest completed candle is stale (>15 minutes)"
    if last_time.strftime("%H:%M") < "09:45" or last_time.strftime("%H:%M") > "14:30":
        return None, "outside scan window (09:45–14:30 IST)"
    if not np.isfinite(last["rvol"]) or float(last["rvol"]) < rvol_min:
        return None, "same-slot relative volume below threshold"
    if not np.isfinite(last["vwap"]) or not np.isfinite(last["atr14"]):
        return None, "insufficient indicator history"
    if float(last["close"]) < min_price:
        return None, "price below minimum"
    avg_value = float((day["close"] * day["volume"]).tail(20).mean())
    if avg_value < min_avg_value:
        return None, "recent traded value below liquidity threshold"

    side = None
    if (last["close"] > last["orb_high"] and last["close"] > last["vwap"]
            and last["close"] > last["open"]):
        side = "LONG"
    elif (last["close"] < last["orb_low"] and last["close"] < last["vwap"]
          and last["close"] < last["open"]):
        side = "SHORT"
    if side is None:
        return None, "no confirmed ORB + VWAP directional close"

    # Reject a broken 5-minute sequence immediately around the signal.
    idx = day.index[-1]
    if idx > 0 and (last_time - day.loc[idx - 1, "timestamp"]).total_seconds() > 305:
        return None, "gap before signal candle"
    atr = float(last["atr14"])
    buffer = max(float(last["close"]) * 0.0005, atr * 0.10)
    stop = float(last["low"] - buffer) if side == "LONG" else float(last["high"] + buffer)
    reference = float(last["close"])
    risk_per_share = reference - stop if side == "LONG" else stop - reference
    risk_pct = risk_per_share / reference * 100 if reference > 0 else math.inf
    if risk_per_share <= 0 or risk_pct < 0.10 or risk_pct > max_risk_pct:
        return None, "stop distance outside configured risk band"
    trigger = float(last["high"]) if side == "LONG" else float(last["low"])
    target = reference + reward_risk * risk_per_share if side == "LONG" else reference - reward_risk * risk_per_share
    quantity = max(0, math.floor(risk_cash / risk_per_share))
    score = 50 + min(25, max(0, (float(last["rvol"]) - rvol_min) * 12))
    score += min(15, abs(reference - float(last["orb_high"] if side == "LONG" else last["orb_low"])) / atr * 5)
    return ({
        "symbol": str(last["symbol"]), "setup": "ORB_30M_VWAP_SLOT_RVOL",
        "direction": side, "score": round(score, 2),
        "signal_candle_time_ist": last_time.isoformat(),
        "last_close": round(reference, 2), "trigger": round(trigger, 2),
        "stop": round(stop, 2), "target_1_5R": round(target, 2),
        "risk_per_share": round(risk_per_share, 4),
        "risk_pct": round(risk_pct, 3), "rvol_same_slot": round(float(last["rvol"]), 2),
        "vwap": round(float(last["vwap"]), 2),
        "orb_high": round(float(last["orb_high"]), 2),
        "orb_low": round(float(last["orb_low"]), 2),
        "recent_avg_traded_value": round(avg_value, 2),
        "illustrative_quantity_at_risk_budget": quantity,
        "risk_budget_inr": risk_cash,
        "status": "WATCHLIST_ONLY",
        "notes": ["Signal candle is complete; trigger is not a fill.",
                  "Wait for a fresh trigger and independently validate spread, news and costs."]
    }, "qualified")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(ROOT / "data" / "intraday_5m"))
    parser.add_argument("--output", default=str(ROOT / "data" / "nse_day_trader_scan.json"))
    parser.add_argument("--rvol", type=float, default=1.5)
    parser.add_argument("--min-price", type=float, default=20.0)
    parser.add_argument("--min-avg-value", type=float, default=10_000_000,
                        help="Minimum average 5-minute traded value in INR over latest session")
    parser.add_argument("--max-risk-pct", type=float, default=1.0)
    parser.add_argument("--reward-risk", type=float, default=1.5)
    parser.add_argument("--risk-cash", type=float, default=500.0)
    parser.add_argument("--session-date", help="Optional YYYY-MM-DD session to scan")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    files = sorted(data_dir.glob("*.csv"))
    signals: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    failures: list[dict[str, str]] = []
    loaded = 0
    for path in files:
        try:
            frame = add_features(load_symbol(path))
            if args.session_date:
                frame = frame[frame["session"] <= args.session_date]
                if frame.empty or frame["session"].max() != args.session_date:
                    rejected["requested session missing"] = rejected.get("requested session missing", 0) + 1
                    continue
            candidate, reason = scan_frame(
                frame, args.rvol, args.min_price, args.min_avg_value,
                args.max_risk_pct, args.reward_risk, args.risk_cash
            )
            loaded += 1
            if candidate:
                signals.append(candidate)
            else:
                rejected[reason] = rejected.get(reason, 0) + 1
        except Exception as exc:
            failures.append({"file": path.name, "error": str(exc)})
    signals.sort(key=lambda x: (x["score"], x["rvol_same_slot"], -x["risk_pct"]), reverse=True)
    now = pd.Timestamp.now(tz=IST)
    result = {
        "generated_at_ist": now.isoformat(),
        "mode": "HISTORICAL_RESEARCH" if args.session_date else "LOCAL_DATA_RESEARCH",
        "status": "watchlist" if signals else "no_qualifying_setups",
        "data_source": "local per-symbol 5-minute OHLCV CSV files; source provenance is not verified by this script",
        "session_date": args.session_date or (max((s["signal_candle_time_ist"][:10] for s in signals), default=None)),
        "universe_files": len(files), "symbols_loaded": loaded,
        "signals_count": len(signals), "signals": signals,
        "rejection_counts": rejected, "failed_files": failures,
        "parameters": {
            "rvol_min": args.rvol, "min_price": args.min_price,
            "min_avg_traded_value_inr_5m": args.min_avg_value,
            "max_stop_risk_pct": args.max_risk_pct, "reward_risk": args.reward_risk,
            "illustrative_risk_budget_inr": args.risk_cash,
        },
        "limitations": [
            "Research watchlist only; no broker connection, order placement or live execution.",
            "Only ORB + VWAP + same-slot RVOL is implemented in this first version.",
            "Relative-volume history is computed from the available files and may be insufficient for short histories.",
            "Yahoo Finance or other third-party candles are not exchange-certified.",
            "No corporate-action, event/news, spread, market-impact or survivorship-bias adjustment is performed.",
            "Illustrative quantity is a simple per-share risk calculation, not a portfolio risk approval.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "mode": result["mode"], "symbols_loaded": loaded,
        "signals_count": len(signals), "rejection_counts": rejected,
        "failed_files": len(failures), "output": str(output)
    }, indent=2))


if __name__ == "__main__":
    main()
