Place one 5-minute OHLCV CSV per NSE cash symbol in this directory.

Required columns:
timestamp,open,high,low,close,volume

Timestamp is the candle START time in Asia/Kolkata. Example:
2026-10-01T09:15:00+05:30,100,101,99.8,100.5,12345

Use raw (unadjusted) intraday prices consistently. Keep source, retrieval date and instrument-token mapping in a separate manifest. Do not commit broker credentials or access tokens here.

Run the backtest from the repository root:
python scripts/intraday_backtest.py --data-dir data/intraday_5m
