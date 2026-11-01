#!/usr/bin/env python3
"""Historical EOD breakout follow-through analysis.

Uses only sessions after each signal date for forward returns. Signals require
a close above the prior rolling high and >=1.5x prior 20-session volume.
Prices are raw bhavcopy prices (not corporate-action adjusted).
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
HISTORY=DATA/"eod_history.csv.gz"
OUTPUT=DATA/"eod_breakout_backtest.json"
WINDOWS={"1_month":21,"3_month":63,"6_month":126,"1_year":252}
FORWARD=(5,10,20)

def main():
    if not HISTORY.exists():raise SystemExit("EOD history not found; run the scanner first")
    df=pd.read_csv(HISTORY,compression="gzip",dtype={"symbol":str})
    df["date"]=pd.to_datetime(df["date"],errors="coerce")
    for col in ("high","close","volume"):df[col]=pd.to_numeric(df[col],errors="coerce")
    df=df.dropna(subset=["date","symbol","high","close","volume"])
    events=[]
    for symbol,g in df.groupby("symbol",sort=False):
        g=g.sort_values("date").drop_duplicates("date",keep="last").reset_index(drop=True)
        if len(g)<max(WINDOWS.values())+max(FORWARD)+1:continue
        highs=g["high"]; closes=g["close"]; volumes=g["volume"]
        prior_avg_vol=volumes.shift(1).rolling(20,min_periods=20).mean()
        for label,n in WINDOWS.items():
            resistance=highs.shift(1).rolling(n,min_periods=n).max()
            signal=(closes>resistance)&(volumes>=1.5*prior_avg_vol)
            for idx in signal[signal].index:
                event={"symbol":symbol,"date":g.at[idx,"date"].strftime("%Y-%m-%d"),
                       "window":label,"close":round(float(closes.iloc[idx]),4),
                       "volume_multiple":round(float(volumes.iloc[idx]/prior_avg_vol.iloc[idx]),3)}
                for horizon in FORWARD:
                    end=idx+horizon
                    if end>=len(g):
                        event[f"return_{horizon}d_pct"]=None
                        event[f"mfe_{horizon}d_pct"]=None
                        event[f"mae_{horizon}d_pct"]=None
                        continue
                    future=g.iloc[idx+1:end+1]
                    entry=float(closes.iloc[idx])
                    event[f"return_{horizon}d_pct"]=round((float(closes.iloc[end])/entry-1)*100,3)
                    event[f"mfe_{horizon}d_pct"]=round((float(future["high"].max())/entry-1)*100,3)
                    event[f"mae_{horizon}d_pct"]=round((float(future["low"].min())/entry-1)*100,3)
                events.append(event)
    summaries={}
    for label in WINDOWS:
        subset=[e for e in events if e["window"]==label]
        summaries[label]={}
        for horizon in FORWARD:
            vals=[e[f"return_{horizon}d_pct"] for e in subset if e[f"return_{horizon}d_pct"] is not None]
            summaries[label][f"{horizon}_sessions"]={
                "sample_size":len(vals),
                "win_rate_pct":round(sum(v>0 for v in vals)/len(vals)*100,2) if vals else None,
                "average_return_pct":round(sum(vals)/len(vals),3) if vals else None,
                "median_return_pct":round(float(pd.Series(vals).median()),3) if vals else None,
                "average_mfe_pct":round(sum(e[f"mfe_{horizon}d_pct"] for e in subset if e[f"mfe_{horizon}d_pct"] is not None)/len(vals),3) if vals else None,
                "average_mae_pct":round(sum(e[f"mae_{horizon}d_pct"] for e in subset if e[f"mae_{horizon}d_pct"] is not None)/len(vals),3) if vals else None
            }
    result={"generated_from_latest_session":df["date"].max().strftime("%Y-%m-%d"),
            "source":"NSE CM UDiFF final bhavcopy history",
            "signal_definition":"Close above the highest high in the prior 21/63/126/252 sessions, with volume >=1.5x prior 20-session average.",
            "forward_horizons_sessions":list(FORWARD),
            "price_adjustment":"Raw bhavcopy prices; corporate actions such as splits and bonuses are not adjusted.",
            "methodology_note":"Only future sessions after the signal date are used. Incomplete forward windows are excluded from that horizon's sample. Historical performance is descriptive, not predictive.",
            "event_count":len(events),"summary":summaries,"events":events}
    OUTPUT.write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({"event_count":len(events),"summary":summaries},indent=2))

if __name__=="__main__":main()
