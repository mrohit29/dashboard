# NSE Scanner

## Purpose
Find and rank candidate NSE cash equities. Scanning produces a watchlist, not a buy/sell instruction.

## Inputs
- Explicit universe and exclusions (default: configured Nifty 500 constituents).
- Completed 5-minute OHLCV candles and daily history.
- Session date/time in Asia/Kolkata.
- Optional market/index context and corporate-event calendar.

## Setup families to evaluate
1. Opening-range breakout: break of the first 15/30-minute range, confirmed by a completed candle.
2. VWAP reclaim/rejection: reclaim or rejection with follow-through and volume confirmation.
3. 20-day high/low breakout: daily close/price context plus intraday confirmation.
4. Bull/bear flag: impulse, controlled consolidation, and breakout confirmation.
5. Moving-average reclaim: reclaim/rejection of a configured daily or intraday moving average.
6. Relative-volume expansion: current completed slot volume versus prior sessions at the same clock time.
7. Oversold/overbought reversal: only with a defined reversal trigger; RSI alone is not a signal.

## Screening rules
- Exclude symbols with missing/stale candles, invalid OHLC, zero/very low liquidity, or suspicious spikes.
- Use only completed candles. Label the timestamp of the last complete bar.
- Relative volume baseline must use prior sessions only, same clock-time slot, and a minimum sample count.
- Do not treat Yahoo volume or prices as exchange-certified.
- Flag corporate actions, results, bulk/block deals, and exchange announcements when reliable data is available.

## Output
Ranked watchlist with symbol, setup, direction, trigger, last price/time, relative volume, liquidity, invalidation, data-quality flags, and reason for ranking. Include rejected candidates and rejection reasons when useful.

## Vetoes
No candidate proceeds if data is stale, a required candle is missing, the setup is not confirmed, or the symbol fails user-defined liquidity filters.
