#!/usr/bin/env python3
"""NSE EOD range-breakout scanner using official CM UDiFF final bhavcopies."""
from __future__ import annotations
import argparse, io, json, math, os, random, time, zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"; DATA.mkdir(parents=True,exist_ok=True)
HISTORY=DATA/"eod_history.csv.gz"; OUTPUT=DATA/"eod_breakouts.json"
HOME="https://www.nseindia.com/"
URL="https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
WINDOWS={"1_month":21,"3_month":63,"6_month":126,"1_year":252}
TARGET_SESSIONS=280; MAX_CALENDAR_DAYS=500; MIN_TURNOVER_CR=0.50
HEADERS={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36","Accept":"*/*","Referer":HOME}

def session():
    s=requests.Session(); s.headers.update(HEADERS)
    r=s.get(HOME,timeout=30); r.raise_for_status()
    return s

def col(columns,*names):
    d={str(x).strip().upper():x for x in columns}
    for n in names:
        if n.upper() in d:return d[n.upper()]
    return None

def fetch_day(s,day):
    r=s.get(URL.format(yyyymmdd=day.strftime("%Y%m%d")),timeout=45)
    if r.status_code in (404,410):return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names=[n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:raise RuntimeError("No CSV in bhavcopy")
        raw=pd.read_csv(z.open(names[0]))
    names=[
        col(raw.columns,"TckrSymb","SYMBOL"),col(raw.columns,"SctySrs","SERIES"),
        col(raw.columns,"OpnPric","OPEN"),col(raw.columns,"HghPric","HIGH"),
        col(raw.columns,"LwPric","LOW"),col(raw.columns,"ClsPric","CLOSE"),
        col(raw.columns,"TtlTradgVol","TOTTRDQTY","TOTAL_TRADED_QUANTITY")]
    if any(x is None for x in names):raise RuntimeError(f"Unexpected UDiFF columns: {list(raw.columns)}")
    df=raw[names].copy(); df.columns=["symbol","series","open","high","low","close","volume"]
    df["symbol"]=df.symbol.astype(str).str.strip()
    df["series"]=df.series.astype(str).str.strip().str.upper()
    df=df[df.series.eq("EQ")].copy()
    for c in ("open","high","low","close","volume"):df[c]=pd.to_numeric(df[c],errors="coerce")
    df=df.dropna(subset=["symbol","open","high","low","close","volume"])
    df=df[df.symbol.ne("")&df.close.gt(0)&df.volume.gt(0)]
    df["date"]=day.isoformat(); df["turnover"]=df.close*df.volume
    return df[["date","symbol","open","high","low","close","volume","turnover"]]

def load():
    if not HISTORY.exists():return pd.DataFrame(columns=["date","symbol","open","high","low","close","volume","turnover"])
    d=pd.read_csv(HISTORY,compression="gzip",dtype={"symbol":str})
    if not d.empty:
        d["date"]=pd.to_datetime(d.date,errors="coerce")
        for c in ("open","high","low","close","volume","turnover"):d[c]=pd.to_numeric(d[c],errors="coerce")
        d=d.dropna(subset=["date","symbol","close","high","volume"])
    return d

def save(d):
    d=d.drop_duplicates(["date","symbol"],keep="last").sort_values(["symbol","date"])
    tmp=HISTORY.with_suffix(".csv.gz.tmp")
    d.to_csv(tmp,index=False,compression="gzip",date_format="%Y-%m-%d")
    os.replace(tmp,HISTORY)

def backfill(s):
    frames=[]; count=0; today=date.today()
    for offset in range(MAX_CALENDAR_DAYS):
        day=today-timedelta(days=offset)
        if day.weekday()>=5:continue
        try:
            d=fetch_day(s,day)
            if d is not None and not d.empty:
                frames.append(d); count+=1
                print(f"Backfilled {day}: {len(d)} EQ symbols ({count}/{TARGET_SESSIONS})")
                if count>=TARGET_SESSIONS:break
        except Exception as e:print(f"Skipping {day}: {e}")
        time.sleep(random.uniform(.12,.28))
    if count<253:raise RuntimeError(f"Only {count} sessions fetched; 253 required for 1-year scan.")
    return pd.concat(frames,ignore_index=True)

def update(s,d):
    dates=set(pd.to_datetime(d.date).dt.date) if not d.empty else set()
    for offset in range(8):
        day=date.today()-timedelta(days=offset)
        if day.weekday()>=5:continue
        try:
            latest=fetch_day(s,day)
            if latest is not None and not latest.empty:
                if day in dates:print(f"{day} already stored");return d
                print(f"Appending {day}: {len(latest)} EQ symbols")
                return pd.concat([d,latest],ignore_index=True)
        except Exception as e:print(f"Bhavcopy not ready for {day}: {e}")
    raise RuntimeError("Could not retrieve a recent NSE final bhavcopy")

def sf(x):
    try:
        v=float(x); return round(v,4) if math.isfinite(v) else None
    except (TypeError,ValueError):return None

def scan(d):
    d=d.copy(); d["date"]=pd.to_datetime(d.date,errors="coerce"); d=d.dropna(subset=["date"])
    latest=d.date.max(); rows=[]
    for symbol,g in d.groupby("symbol",sort=False):
        g=g.sort_values("date").drop_duplicates("date",keep="last")
        if g.date.iloc[-1]!=latest or len(g)<22:continue
        today=g.iloc[-1]; prev=g.iloc[:-1]
        p20=prev.tail(20)
        if len(p20)<20:continue
        avg_turn=float(p20.turnover.mean()); avg_vol=float(p20.volume.mean())
        vm=float(today.volume/avg_vol) if avg_vol>0 else 0
        sma50=float(prev.tail(50).close.mean()) if len(prev)>=50 else None
        sma200=float(prev.tail(200).close.mean()) if len(prev)>=200 else None
        item={"symbol":str(symbol),"date":latest.strftime("%Y-%m-%d"),"close":sf(today.close),
              "volume":int(today.volume),"volume_multiple":sf(vm),
              "avg_turnover_cr_20d":sf(avg_turn/1e7),"sma50":sf(sma50),"sma200":sf(sma200),
              "above_50dma":bool(sma50 is not None and today.close>sma50),
              "above_200dma":bool(sma200 is not None and today.close>sma200),
              "liquidity_flag":"LOW" if avg_turn<MIN_TURNOVER_CR*1e7 else "OK","ranges":{}}
        for label,n in WINDOWS.items():
            if len(prev)<n:continue
            resistance=float(prev.tail(n).high.max())
            distance=(float(today.close)/resistance-1)*100
            touched=float(today.high)>resistance; close_break=float(today.close)>resistance
            if close_break:status="CONFIRMED" if vm>=1.5 else "BREAKOUT_LOW_VOLUME"
            elif touched:status="FAILED_CLOSE"
            elif distance>=-2:status="NEAR_BREAKOUT"
            else:continue
            item["ranges"][label]={"window_sessions":n,"resistance":sf(resistance),
                "distance_from_resistance_pct":sf(distance),"status":status}
        if item["ranges"]:
            item["technical_score"]=(2 if item["above_50dma"] else 0)+(2 if item["above_200dma"] else 0)+(2 if vm>=1.5 else (1 if vm>=1.2 else 0))+(1 if item["liquidity_flag"]=="OK" else 0)
            rows.append(item)
    rows.sort(key=lambda x:(x["technical_score"],x["volume_multiple"] or 0),reverse=True)
    grouped={k:[] for k in WINDOWS}
    for row in rows:
        for k in WINDOWS:
            if k in row["ranges"]:
                x=dict(row); x["range"]=row["ranges"][k]; grouped[k].append(x)
    return {"as_of":latest.strftime("%Y-%m-%d"),"generated_utc":datetime.now(timezone.utc).isoformat(),
      "source":"NSE CM UDiFF final bhavcopy","history_sessions":int(d.date.nunique()),
      "symbols_with_full_history":sum(1 for _,g in d.groupby("symbol") if len(g)>=253),
      "counts":{k:len(v) for k,v in grouped.items()},"windows":grouped,
      "method":"Today's close is compared with the highest high in the preceding 21/63/126/252 sessions; current session excluded. Confirmed + volume means close above resistance and volume >=1.5x prior 20-session average.",
      "notes":["Regular NSE EQ series only; ETFs, SME and debt series excluded.",
      "Technical EOD screen, not a buy recommendation. Market cap and quarterly fundamentals are not yet joined.",
      "FII/DII ownership is quarterly and is not inferred from daily trading volume.",
      "Low-liquidity stocks are retained but flagged. All-time-high status is limited to retained history."]}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--mode",choices=["auto","backfill","daily"],default="auto"); args=ap.parse_args()
    s=session(); d=load()
    if args.mode=="backfill" or d.empty:
        print("Starting one-time NSE history backfill"); d=backfill(s)
    else:d=update(s,d)
    save(d); result=scan(load())
    OUTPUT.write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({"as_of":result["as_of"],"history_sessions":result["history_sessions"],
      "symbols_with_full_history":result["symbols_with_full_history"],"counts":result["counts"],
      "history_file_mb":round(HISTORY.stat().st_size/(1024*1024),2)},indent=2))

if __name__=="__main__":main()
