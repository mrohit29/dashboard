# Multi-factor intraday strategy — V1

This is a separate research strategy. It does not use the opening-range breakout (ORB) rules. The existing ORB scripts remain unchanged.

## Factors

All indicators are calculated from completed 5-minute candles for each symbol:

1. **Trend:** EMA20 above EMA50 for longs; below for shorts.
2. **Momentum:** RSI14 above 55 for longs; below 45 for shorts.
3. **Participation:** current volume at least 1.3 times the median volume for the same clock-time slot over the previous 20 sessions (at least 10 observations).
4. **Trend strength:** ADX14 above 20.

The research runner tests every 2-factor, 3-factor and 4-factor combination, separately for LONG, SHORT and BOTH directions. A signal enters at the next 5-minute candle open.

## Initial risk model

- Stop distance: 1.5 x ATR14 measured on the signal candle.
- Target: 1.5R.
- Risk budget: ₹500 per trade; starting capital ₹1,00,000.
- Portfolio constraints: two simultaneous positions, three trades per day, ₹1,000 daily loss limit.
- Estimated costs: 2 bps slippage per side, 6 bps variable cost per side and ₹20 brokerage per order. These are placeholders, not a broker contract-note calculation.
- If stop and target are both touched in the same candle, the shared simulator assumes the stop first.

## Run

From the repository root, with the project virtual environment activated:

```bash
python scripts/multifactor_backtest.py \
  --data-dir data/intraday_5m \
  --output data/multifactor_research.json \
  --trades-csv data/multifactor_trades.csv
```

The output JSON reports chronological 60% train / 20% validation / 20% holdout results. The script identifies the best validation expectancy only among combinations with at least 10 validation trades. Do not select or tune based on holdout results.

The trades CSV contains validation and holdout trades for each factor combination and direction. The script excludes sample instrument files from the data directory.

## Important limitations

- The current dataset covers only about 40 sessions. It is suitable for plumbing and exploratory testing, not for establishing a durable edge.
- Yahoo Finance 5-minute data has a limited history window and can have missing bars, adjustments or data-quality issues.
- The strategy does not yet include a point-in-time survivorship-bias-free universe, corporate-action reconciliation, market/sector regime filters, or broker-specific cost calculations.
- ADX and EMA are calculated on the available continuous intraday series. They are not reset each session.
- Simulated short trades are not proof that a cash-market short position can be carried or executed under the same conditions.
- This is research software only. Do not connect it to live order placement before independent validation and paper trading.
