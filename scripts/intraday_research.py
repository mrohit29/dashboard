#!/usr/bin/env python3
"""Chronological parameter study for the intraday ORB engine.

Uses identical candles, fills, sizing and estimated costs across parameter sets.
The final 20% of dates is a holdout and is never used to choose parameters.
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import pandas as pd

from intraday_backtest import (
    add_features, apply_portfolio_limits, load_symbol, make_candidates,
    simulate_candidate, summarize,
)


def evaluate(candidates, sessions, args):
    chosen = [c for c in candidates if c["session"] in sessions]
    simulated = [
        simulate_candidate(c, args.capital, args.risk,
                           args.cost_bps_per_side, args.brokerage_per_order)
        for c in chosen
    ]
    simulated = [t for t in simulated if t is not None]
    accepted = apply_portfolio_limits(
        simulated, args.max_positions, args.max_trades_day, args.daily_loss_limit
    )
    return summarize(accepted, args.capital)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default="data/intraday_5m")
    p.add_argument("--output", default="data/intraday_research.json")
    p.add_argument("--capital", type=float, default=100000)
    p.add_argument("--risk", type=float, default=500)
    p.add_argument("--daily-loss-limit", type=float, default=1000)
    p.add_argument("--max-stop-pct", type=float, default=0.01)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    p.add_argument("--cost-bps-per-side", type=float, default=6.0)
    p.add_argument("--brokerage-per-order", type=float, default=20.0)
    p.add_argument("--max-positions", type=int, default=2)
    p.add_argument("--max-trades-day", type=int, default=3)
    args = p.parse_args()

    files = sorted(Path(args.data_dir).glob("*.csv"))
    files = [f for f in files if f.name.lower() not in
             {"instruments.csv", "download_failures.csv"}]
    if not files:
        raise SystemExit(f"No symbol candle CSVs found in {args.data_dir}")

    frames, failures, all_sessions = [], [], set()
    for path in files:
        try:
            frame = add_features(load_symbol(path))
            frames.append(frame)
            all_sessions.update(frame["session"].unique())
        except Exception as exc:
            failures.append({"file": path.name, "error": str(exc)})

    dates = sorted(all_sessions)
    if len(dates) < 30:
        raise SystemExit(
            f"Only {len(dates)} trading sessions found. Need at least 30 for a "
            "meaningful 60/20/20 chronological split; collect more data."
        )
    n_train = int(len(dates) * 0.60)
    n_valid = int(len(dates) * 0.20)
    train = set(dates[:n_train])
    validation = set(dates[n_train:n_train + n_valid])
    test = set(dates[n_train + n_valid:])

    rows = []
    for rvol, rr in itertools.product((1.2, 1.5, 2.0), (1.0, 1.5, 2.0)):
        candidates = []
        for frame in frames:
            candidates.extend(make_candidates(
                frame, rvol, rr, args.max_stop_pct, args.slippage_bps
            ))
        rows.append({
            "rvol_min": rvol, "reward_risk": rr,
            "train": evaluate(candidates, train, args),
            "validation": evaluate(candidates, validation, args),
            "holdout_test": evaluate(candidates, test, args),
        })

    # Selection is based on validation expectancy, not on holdout performance.
    viable = [r for r in rows if r["validation"].get("trade_count", 0) >= 10]
    selected = max(
        viable,
        key=lambda r: r["validation"].get("expectancy_per_trade", float("-inf")),
        default=None,
    )
    result = {
        "strategy_family": "30m_ORB_VWAP_SLOT_RVOL",
        "data_period": {"first_session": dates[0], "last_session": dates[-1],
                        "sessions": len(dates)},
        "split": {"train_sessions": len(train), "validation_sessions": len(validation),
                  "holdout_test_sessions": len(test), "chronological": True},
        "selection_rule": "Highest validation expectancy among parameter sets with >=10 validation trades; holdout is not used for selection.",
        "selected_on_validation": selected,
        "all_parameter_results": rows,
        "failed_files": failures,
        "warnings": [
            "Holdout results are diagnostic and must not be used for repeated tuning.",
            "All symbols share date splits; indicators use only current/past bars.",
            "Universe survivorship bias and corporate actions depend on the supplied instrument list and data source.",
            "Costs and slippage are estimates; replace them with actual contract-note costs.",
            "This is not a recommendation to trade live.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "data_period": result["data_period"], "split": result["split"],
        "selected_on_validation": selected, "output": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()
