# NSE intraday research engine — v1

## Scope
Research-only 5-minute NSE cash-equity backtester. No orders are placed. First hypothesis: 30-minute Opening Range Breakout (ORB), filtered by session VWAP, same-time-slot relative volume and candle direction.

## Strategy
- Session: 09:15–15:30 IST.
- Opening range: first six 5-minute bars, labelled 09:15 through 09:40.
- Evaluate completed bars from 09:45 through 14:30.
- LONG: close above opening-range high and session VWAP, bullish candle, relative volume >= 1.5x the median for that clock-time slot over the previous 20 sessions (minimum 10 observations).
- SHORT: symmetric conditions below opening-range low and VWAP with a bearish candle.
- One first signal per symbol/session; enter at next bar open with adverse slippage.
- Stop: signal-bar extreme plus/minus max(0.05% of price, 0.10 ATR(14)); reject risk below 0.20% or above 1.00%.
- Target: 1.5R. Exit at stop, target or 15:25 close. If stop and target touch in the same bar, assume stop first.
- Size: floor(min(₹500 / per-share risk, ₹1,00,000 / entry)).
- Portfolio limits: two concurrent positions, three entries/day, ₹1,000 daily realized-loss stop.

## Data format
Put one CSV per symbol in `data/intraday_5m/`, named e.g. `RELIANCE.csv`. Required columns:
`timestamp,open,high,low,close,volume`.
Timestamps represent the **start** of each 5-minute bar. Naive timestamps are interpreted as Asia/Kolkata. Keep raw unadjusted prices; do not mix adjusted daily prices with unadjusted intraday data.

The engine needs at least 10 prior observations for each clock-time slot; 20+ sessions is preferable. For robust conclusions, target 1–3 years, a point-in-time universe, delisted stocks where possible, and corporate-action-aware symbol mapping.

## Run
```bash
pip install pandas numpy
python scripts/intraday_backtest.py --data-dir data/intraday_5m --output data/intraday_backtest.json --trades-csv data/intraday_trades.csv --capital 100000 --risk 500 --daily-loss-limit 1000 --rvol 1.5 --rr 1.5
```

## Assumptions and limitations
- Signals use completed bars; entry is next-bar open, never the signal-bar close.
- Same-bar stop/target collision resolves to stop.
- No look-ahead in relative volume: only earlier sessions feed the same-time-slot baseline.
- Default slippage: 2 bps per side. Default variable cost estimate: 6 bps per side plus ₹20 brokerage/order. These are placeholders, not an Angel One contract-note calculation.
- Daily loss guard uses realized P&L from completed trades; open-position mark-to-market is not yet included.
- Cash short trades are simulated as intraday shorts and must be squared off the same day.
- The repository has daily history but no 5-minute intraday history. Do not report intraday strategy performance until real 5-minute files are supplied. `scripts/download_dhan_5m.py` can retrieve DhanHQ 5-minute candles in 90-day request windows (Dhan documents up to five years for active instruments). It requires a valid `DHAN_ACCESS_TOKEN` environment variable and a user-maintained `instruments.csv` containing `symbol,security_id`; this is data retrieval only, not order execution.
- Yahoo Finance intraday history is limited to the most recent 60 days; it is suitable only for a plumbing smoke test, not robust validation.

## Validation
1. Validate timestamps, missing/duplicate bars, zero-volume bars and OHLC consistency.
2. Run a broad point-in-time universe.
3. Compare 1.2x/1.5x/2.0x relative-volume thresholds and 1.0R/1.5R/2.0R targets.
4. Use chronological train, validation and untouched test periods.
5. Report by year, symbol, side, month, market regime and entry time.
6. Include costs and adverse slippage; compare gross vs net.
7. Paper trade before considering real-money use.


## Historical research runner

Use `scripts/intraday_research.py` after downloading or importing candle CSVs. It compares nine combinations (relative-volume thresholds 1.2x/1.5x/2.0x and targets 1R/1.5R/2R) using the same execution/cost assumptions. It divides all trading dates chronologically into 60% train, 20% validation and 20% untouched holdout. Parameter selection uses validation expectancy only (minimum 10 validation trades); holdout metrics are reported separately and must not be used for repeated tuning.

```bash
python scripts/intraday_research.py --data-dir data/intraday_5m --output data/intraday_research.json
```

The starting-capital point is included in equity drawdown calculations. The engine remains a first research baseline, not a validated live-trading system.
