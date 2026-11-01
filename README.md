# India Institutional Flow Dashboard

Static dashboard + JSON data layer + GitHub Actions refresh pipeline.

## EOD NSE breakout scanner

The separate EOD scanner uses the official NSE CM UDiFF final bhavcopy archive and scans regular NSE EQ-series shares.

- Initial build: GitHub Actions → EOD NSE Breakout Scanner → Run workflow → select \`backfill\`.
- Daily refresh: scheduled at 16:30 IST on weekdays, after the market close and a publication buffer.
- Breakout windows: 21, 63, 126 and 252 previous trading sessions.
- Resistance is the highest daily high in the preceding window; the current session is excluded.
- Confirmed breakout means a closing price above resistance; volume >=1.5x the prior 20-session average is highlighted.
- Compressed history: \`data/eod_history.csv.gz\`; results: \`data/eod_breakouts.json\`; page: \`eod-scanner.html\`.
- Historical breakout follow-through: `scripts/eod_breakout_backtest.py` writes `data/eod_breakout_backtest.json` with 5/10/20-session returns, win rates, and maximum favorable/adverse excursions.
- Fundamental enrichment: `scripts/enrich_eod_fundamentals.py` validates YoY growth when the comparison base is positive, attempts a balance-sheet debt/equity calculation, and adds a transparent available-data quality score.
- The EOD page supports click-to-sort on all displayed columns and shows historical breakout performance.

This first version is a technical EOD screen. Market capitalisation, quarterly financials, FII/DII ownership and promoter pledging are not fabricated; they will be added as a separately sourced fundamental layer.

## Local preview

\`\`\`bash
python -m http.server 8000
\`\`\`

Open http://localhost:8000.

## Existing market data model

- Daily: FII/FPI, DII, price, volume, delivery
- Fortnightly: sector-wise FPI flows
- Quarterly: FII/DII/promoter ownership
- Weekly metrics are derived by aggregating daily observations.
