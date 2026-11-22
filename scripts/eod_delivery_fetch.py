#!/usr/bin/env python3
"""Fetch NSE full bhavcopy and publish latest delivery percentage by symbol."""
import csv, io, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"eod_delivery.json"
URL="https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"
HEADERS={"User-Agent":"Mozilla/5.0","Accept":"text/csv,*/*","Referer":"https://www.nseindia.com/"}

def find(row,*keys):
    normalized={str(k).strip().upper().replace(" ","_"):v for k,v in row.items()}
    for key in keys:
        if key in normalized:return normalized[key]
    return None

def num(value):
    try:
        s=str(value).strip().replace(",","")
        return float(s) if s and s not in ("-","NA","N/A") else None
    except (TypeError,ValueError):return None

def main():
    # NSE archive file date is DDMMYYYY. Try today then the preceding 7 calendar days.
    from datetime import date,timedelta
    session=requests.Session();session.headers.update(HEADERS)
    rows=None; source_date=None
    for offset in range(8):
        d=date.today()-timedelta(days=offset); ds=d.strftime("%d%m%Y")
        url=URL.format(date=ds)
        try:
            r=session.get(url,timeout=30)
            if r.status_code==404:continue
            r.raise_for_status()
            text=r.content.decode("utf-8-sig",errors="replace")
            parsed=list(csv.DictReader(io.StringIO(text)))
            if parsed:
                rows=parsed;source_date=d.isoformat();break
        except Exception as e:
            print(f"Try {ds}: {e}",file=sys.stderr)
    if not rows:raise RuntimeError("Could not download NSE full bhavcopy for recent sessions")
    items={}
    for row in rows:
        symbol=str(find(row,"SYMBOL","TCKR_SYMB") or "").strip()
        series=str(find(row,"SERIES","SCTY_SRS") or "").strip().upper()
        if not symbol or series not in ("EQ","BE","BZ"):continue
        qty=num(find(row,"DELIV_QTY","DELIVERABLE_QTY","DELIVERABLE_QUANTITY"))
        pct=num(find(row,"DELIV_PER","DELIVERY_PERCENT","DELIVERY_PERCENTAGE","DELIV_PCT"))
        if pct is None and qty is not None:
            traded=num(find(row,"TTL_TRD_QNTY","TOTTRDQTY","TOTAL_TRADED_QUANTITY"))
            pct=(qty/traded*100) if traded else None
        items[symbol]={"delivery_qty":int(qty) if qty is not None else None,"delivery_pct":round(pct,2) if pct is not None else None}
    payload={"as_of":source_date,"source":"NSE Full Bhavcopy and Security Deliverable data","items":items}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    print(f"Saved {len(items)} symbols delivery metrics for {source_date} to {OUT}")

if __name__=="__main__":main()
