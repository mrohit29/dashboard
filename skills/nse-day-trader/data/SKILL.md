# NSE Market Data Quality

Expected research format: one CSV per symbol with timestamp, open, high, low, close, volume. Normalize to Asia/Kolkata and sort chronologically.

Validate timestamps, numeric OHLCV, nonnegative volume, valid OHLC relationships, duplicate timestamps, regular-session coverage (09:15–15:30), missing bars, zero-volume bars, stale last candles and gaps between consecutive bars. Never assume the next row is the next 5-minute candle if a gap exists.

Flag corporate actions, symbol changes, adjusted/unadjusted prices and survivorship bias. Current Nifty 500 constituents are not a survivorship-free historical universe. Keep raw data out of Git; commit code, docs and small aggregate results only.

Compute indicators only from data available at the signal time. Document whether indicators reset daily or carry across sessions. Same-slot relative volume must use only prior sessions and define handling of missing slots. Test indicators against hand-calculated fixtures or a trusted reference.

Output rows loaded, symbols covered, date range, duplicates, invalid rows, missing/zero-volume bars, stale symbols and unresolved limitations.
