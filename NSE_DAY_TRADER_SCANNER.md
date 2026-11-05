# NSE Day Trader Scanner v1

This is the first executable module under `skills/nse-day-trader`. It is a local-data research scanner, not a live trading system.

## Run

From the repository root:

```bash
source .venv/bin/activate
python scripts/nse_day_trader_scanner.py
```

Defaults:
- Input: `data/intraday_5m/*.csv`
- Output: `data/nse_day_trader_scan.json` (ignored by Git)
- Setup: 30-minute opening-range breakout + session VWAP + same-clock-time relative volume
- Signal window: 09:45–14:30 Asia/Kolkata
- Relative volume: at least 1.5x the median volume of the same 5-minute slot in prior observations
- Illustrative risk budget: ₹500 per candidate; quantity is a simple risk-per-share calculation only

Example with explicit thresholds:

```bash
python scripts/nse_day_trader_scanner.py \
  --data-dir data/intraday_5m \
  --rvol 1.5 \
  --min-price 20 \
  --min-avg-value 10000000 \
  --max-risk-pct 1.0 \
  --risk-cash 500
```

Historical session:

```bash
python scripts/nse_day_trader_scanner.py --session-date 2026-10-01
```

Run tests:

```bash
python -m unittest discover -s tests -p 'test_nse_day_trader_scanner.py' -v
```

## Output interpretation

Each result is marked `WATCHLIST_ONLY`. It includes signal candle time, reference close, trigger level, stop, 1.5R reference target, same-slot RVOL, VWAP, opening range, recent traded value and illustrative quantity.

The trigger is the signal candle high for LONG or low for SHORT. It is not an order or fill. The scanner does not connect to a broker, fetch live candles, send Telegram messages, or place orders.

## Important limitations

- Input files must be present locally and have timestamp, open, high, low, close, volume columns.
- Timestamps may be naive IST or timezone-aware; candle timestamps are candle start times.
- Only the first setup family (ORB + VWAP + same-slot RVOL) is implemented.
- Source provenance, exchange data quality, spread, slippage, costs, corporate actions, news and portfolio-level risk are not validated here.
- The scanner's illustrative quantity is not a risk-manager approval.
- No strategy profitability is implied. Validate with chronological out-of-sample replay and paper trading before considering any execution workflow.
