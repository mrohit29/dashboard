# Entry Validation

## Purpose
Convert a scanner candidate into a conditional, executable paper-trade plan.

## State machine
- WAITING: setup identified but trigger not confirmed.
- TRIGGERED: completed candle satisfies the trigger.
- READY: next-bar entry assumptions, stop, target and risk calculations are valid.
- EXPIRED: trigger window passed, price moved too far, data became stale, or setup invalidated.
- REJECTED: risk, liquidity, data or market constraints failed.

## Rules
- Never enter on an unfinished candle.
- Default historical fill: next 5-minute bar open, adjusted for adverse slippage. If the next bar is missing or separated by a material gap, reject or mark unfilled.
- Do not chase a gap beyond the configured maximum distance from trigger/ATR.
- Require a defined invalidation level before entry.
- Check spread/liquidity where data exists; otherwise explicitly state that it is unavailable.
- One setup should not create repeated entries unless the strategy explicitly defines re-entry rules.
- Record signal timestamp separately from assumed entry timestamp.

## Output
State, trigger conditions, assumed fill, gap/slippage check, stop, target, reward/risk, expiry, and reasons for rejection. The risk module must approve before a paper trade is accepted.
