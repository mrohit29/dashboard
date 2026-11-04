# Yahoo Finance 5-minute research dataset

The combined Yahoo download is intentionally kept outside Git history. Do not commit raw market-data CSVs or broker credentials to this repository.

## Current uploaded dataset validation

- Source: Yahoo Finance via yfinance
- Interval: 5 minutes
- Coverage: 2026-09-07 through 2026-11-04
- Trading dates present: 40
- Symbols with data: 2,606
- Symbols attempted: 2,627 (21 returned no data)
- Rows: 6,100,964
- Missing values in OHLCV: 0
- Duplicate symbol/timestamp rows: 0
- Zero-volume rows: 337,930 (5.539%)

This is the current listed NSE equity universe returned by the NSE symbol-list endpoint, not a point-in-time Nifty 500 constituent universe. It therefore must not be described as a Nifty 500 backtest. Yahoo data availability varies by symbol. Zero-volume rows are retained in the raw source and should be inspected/handled explicitly by each strategy.

## Import to the backtester

The backtester expects one CSV per symbol. Use the importer:

```bash
python -m pip install pandas
python scripts/import_yahoo_5m.py \
  --input /path/to/all_nse_5m.csv.gz \
  --output-dir data/intraday_5m
```

To restrict the import to a constituent file containing a `SYMBOL` column:

```bash
python scripts/import_yahoo_5m.py \
  --input /path/to/all_nse_5m.csv.gz \
  --symbols-file /path/to/nifty500_symbols.csv \
  --output-dir data/intraday_5m
```

Keep the source archive on local storage or object storage; keep code, manifests, validation summaries, and compact backtest outputs in Git. The 60-day Yahoo intraday sample is a prototype dataset, not enough for robust multi-regime validation.
