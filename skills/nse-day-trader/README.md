# NSE Day Trader Skill

A modular, India-market adaptation of the workflow architecture in [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill).

## Modules
- `SKILL.md`: entry point, operating principles and workflow.
- `scanner/SKILL.md`: NSE watchlist and setup discovery.
- `entry/SKILL.md`: trigger confirmation and entry state machine.
- `exit/SKILL.md`: stop, target, time exit and fill assumptions.
- `risk/SKILL.md`: risk veto, portfolio limits and daily loss control.
- `budget/SKILL.md`: position sizing and capital allocation.
- `timemachine/SKILL.md`: historical analog replay.
- `news/SKILL.md`: India-specific exchange and corporate events.
- `alerts/SKILL.md`: alert lifecycle and trade journal.
- `broker/SKILL.md`: broker integration safety boundary.
- `analyst/SKILL.md`: pre/post-trade analysis and strategy review.
- `data/SKILL.md`: candle validation and indicator integrity.

## Local data and execution assumptions
Initial research universe is the configured Nifty 500 list. The current local dataset uses Yahoo Finance 5-minute candles; it is suitable for exploratory research only and must not be treated as exchange-grade live execution data. No Dhan account is assumed. The skill is research/paper-only and contains no live order execution.

## Workflow
Market context → scan → verify completed candle → plan entry/exit → risk approval → replay → journal/review.

Risk approval is mandatory and can veto any candidate. Missing, stale or inconsistent data results in NO TRADE / INSUFFICIENT DATA.

## What this is not
This directory defines the agent workflow and guardrails. It does not claim that any strategy is profitable, provide live prices, or place broker orders. Strategy code and data pipelines remain separate and must be validated independently.

## Source inspiration
The module separation follows the scanner, entry, exit, risk, budget, time-machine, news, alerts, broker and analyst concepts in the MIT-licensed reference repository. India-specific market rules and data limitations are explicitly handled here rather than copied from US-market broker assumptions.
