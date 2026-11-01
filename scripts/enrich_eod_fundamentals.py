#!/usr/bin/env python3
"""Attach public Screener.in fundamentals to EOD breakout candidates.

The scanner remains usable if a company page is unavailable: missing fields stay
null and every record carries source/as-of metadata. A seven-day cache limits load.
"""
from __future__ import annotations
import json, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
SIGNALS=DATA/"eod_breakouts.json"
CACHE=DATA/"eod_fundamentals_cache.json"
OUTPUT=DATA/"eod_fundamentals.json"
CACHE_DAYS=7
HEADERS={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36","Accept":"text/html,application/xhtml+xml","Accept-Language":"en-US,en;q=0.9"}

def number(value):
    if value is None:return None
    s=str(value).strip().replace(",","").replace("₹","").replace("%","").replace("−","-")
    if not s or s in {"-","—","–","NA","N/A"}:return None
    mult=1.0
    if re.search(r"\bCr\.?\b",s,re.I):mult=1.0
    elif re.search(r"\bLakh\b",s,re.I):mult=0.01
    s=re.sub(r"\b(Cr\.?|Lakh|%|Rs\.?)\b","",s,flags=re.I).strip()
    neg=s.startswith("(") and s.endswith(")")
    s=s.strip("()")
    m=re.search(r"-?\d+(?:\.\d+)?",s)
    if not m:return None
    x=float(m.group())*mult
    return -x if neg else x

def ratio_map(soup):
    out={}
    for li in soup.select("#top-ratios li"):
        name=li.select_one(".name")
        val=li.select_one(".number")
        if name and val:out[" ".join(name.get_text(" ",strip=True).split())]=val.get_text(" ",strip=True)
    return out

def table_rows(soup, table_id):
    # Screener uses section/div IDs as anchors; the actual table is nested inside.
    container=soup.find(id=table_id)
    table=container if container and container.name=="table" else (container.find("table") if container else None)
    if table is None:
        # Fallback for markup changes where the anchor ID moved to a wrapper.
        candidates=soup.select(f"#{table_id} table")
        table=candidates[0] if candidates else None
    if table is None:return [],[]
    header=[]
    for tr in table.select("thead tr"):
        cells=tr.find_all(["th","td"],recursive=False)
        if cells:header=[c.get_text(" ",strip=True) for c in cells]
    rows=[]
    body_rows=table.select("tbody tr") or table.select("tr")
    for tr in body_rows:
        cells=tr.find_all(["th","td"],recursive=False)
        if not cells:continue
        vals=[c.get_text(" ",strip=True).replace("\\xa0"," ").strip() for c in cells]
        if len(vals)>=2:
            # If there is no explicit thead, the first row is the date header.
            if not header and all(re.search(r"\\b(?:Mar|Jun|Sep|Dec)\b",v,re.I) for v in vals[1:]):
                header=vals
                continue
            rows.append(vals)
    return header,rows

def clean_label(value):
    return re.sub(r"\\s+"," ",str(value).replace("\\xa0"," ").replace("+"," ")).strip(" .").lower()

def find_row(rows,*labels):
    wanted={clean_label(x) for x in labels}
    for row in rows:
        if clean_label(row[0]) in wanted:return row
    return None

def latest_value(row):
    return number(row[-1]) if row and len(row)>1 else None

def previous_value(row):
    return number(row[-2]) if row and len(row)>2 else None

def growth(row):
    # Screener tables are ordered oldest-to-newest: compare latest with four
    # quarters earlier (same quarter of the previous year).
    if not row or len(row)<6:return None
    latest=number(row[-1]); year_ago=number(row[-5])
    if latest is None or year_ago in (None,0):return None
    return round((latest/year_ago-1)*100,2)

def parse_company(symbol,html,url):
    soup=BeautifulSoup(html,"html.parser")
    ratios=ratio_map(soup)
    q_header,q_rows=table_rows(soup,"quarters")
    s_header,s_rows=table_rows(soup,"shareholding")
    sales=find_row(q_rows,"Sales")
    net_profit=find_row(q_rows,"Net Profit")
    eps=find_row(q_rows,"EPS")
    promoter=find_row(s_rows,"Promoters","Promoter")
    fii=find_row(s_rows,"FIIs","FII")
    dii=find_row(s_rows,"DIIs","DII")
    pledged=find_row(s_rows,"Pledged","Pledged shares","Promoter Pledge")
    def latest(row):return latest_value(row)
    def delta(row):
        a=latest_value(row); b=previous_value(row)
        return round(a-b,2) if a is not None and b is not None else None
    # Screener labels and reported periods are retained so stale/missing fields are visible.
    return {
      "symbol":symbol,"company_name":soup.select_one("h1").get_text(" ",strip=True) if soup.select_one("h1") else symbol,
      "source":"Screener.in","source_url":url,"fetched_utc":datetime.now(timezone.utc).isoformat(),
      "ratios_as_displayed":ratios,
      "market_cap_cr":number(ratios.get("Market Cap")),
      "pe":number(ratios.get("Stock P/E")),
      "roe_pct":number(ratios.get("ROE")),
      "roce_pct":number(ratios.get("ROCE")),
      "debt_to_equity":number(ratios.get("Debt to equity")),
      "dividend_yield_pct":number(ratios.get("Dividend Yield")),
      "quarterly_periods":q_header[1:] if len(q_header)>1 else [],
      "latest_quarter_sales":latest(sales),
      "sales_yoy_growth_pct":growth(sales),
      "latest_quarter_net_profit":latest(net_profit),
      "net_profit_yoy_growth_pct":growth(net_profit),
      "latest_quarter_eps":latest(eps),
      "shareholding_periods":s_header[1:] if len(s_header)>1 else [],
      "promoter_holding_pct":latest(promoter),
      "promoter_change_qoq_pp":delta(promoter),
      "fii_holding_pct":latest(fii),
      "fii_change_qoq_pp":delta(fii),
      "dii_holding_pct":latest(dii),
      "dii_change_qoq_pp":delta(dii),
      "promoter_pledge_pct":latest(pledged),
      "pledge_field_reported":pledged is not None,
      "quarterly_table_found":bool(q_rows),
      "shareholding_table_found":bool(s_rows)
    }

def main():
    if not SIGNALS.exists():raise SystemExit("Run eod_breakout_scanner.py first")
    payload=json.loads(SIGNALS.read_text(encoding="utf-8"))
    cache=json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    # Enrich the union of symbols in all four windows, not just the selected view.
    symbols=sorted({row["symbol"] for rows in payload.get("windows",{}).values() for row in rows})
    now=datetime.now(timezone.utc); session=requests.Session(); session.headers.update(HEADERS)
    fresh={}; errors={}
    for i,symbol in enumerate(symbols,1):
        old=cache.get(symbol,{})
        fetched=old.get("fetched_utc")
        try:
            age=(now-datetime.fromisoformat(fetched.replace("Z","+00:00"))).days if fetched else 9999
        except Exception:age=9999
        # Do not preserve recent but structurally incomplete cache entries from
        # the earlier parser (which looked for table IDs on <table> elements).
        cache_complete=bool(old.get("quarterly_table_found") and old.get("shareholding_table_found"))
        if old and age<CACHE_DAYS and cache_complete:
            fresh[symbol]=old; continue
        url="https://www.screener.in/company/"+quote(symbol,safe="")+"/"
        try:
            response=None
            for attempt in range(4):
                response=session.get(url,timeout=25)
                if response.status_code==429 or response.status_code>=500:
                    if attempt==3:response.raise_for_status()
                    retry_after=response.headers.get("Retry-After")
                    try:delay=min(60.0,float(retry_after)) if retry_after else (3.0*(2**attempt))
                    except ValueError:delay=3.0*(2**attempt)
                    print(f"[{i}/{len(symbols)}] {symbol}: HTTP {response.status_code}; retrying in {delay:.0f}s")
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                break
            record=parse_company(symbol,response.text,url)
            if not record["ratios_as_displayed"] and not record["quarterly_table_found"]:
                raise RuntimeError("Page loaded but expected financial tables were not found")
            fresh[symbol]=record
            print(f"[{i}/{len(symbols)}] {symbol}: fetched")
        except Exception as exc:
            errors[symbol]=str(exc)
            if old:fresh[symbol]=old
            else:fresh[symbol]={"symbol":symbol,"source":"Screener.in","source_url":url,"status":"unavailable","error":str(exc)}
            print(f"[{i}/{len(symbols)}] {symbol}: unavailable - {exc}")
        time.sleep(1.25)
    CACHE.write_text(json.dumps(fresh,indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    result={"as_of":payload.get("as_of"),"generated_utc":now.isoformat(),"source":"Screener.in public company pages",
      "cache_valid_days":CACHE_DAYS,"symbols_requested":len(symbols),
      "symbols_with_ratios":sum(bool(x.get("ratios_as_displayed")) for x in fresh.values()),
      "errors":errors,"items":fresh,
      "notes":["Quarterly sales/profit growth compares the latest reported quarter with the same quarter one year earlier, when both values are available.",
      "Shareholding changes are percentage-point changes between the latest two reported quarters, not daily flows.",
      "Promoter pledge is shown only if a separate pledge row is actually present in the source table; blank means not reported by this parser, not zero.",
      "Missing or stale fields are not treated as zero. Check each source period before acting."]}
    OUTPUT.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    print(json.dumps({"symbols_requested":len(symbols),"symbols_with_ratios":result["symbols_with_ratios"],"errors":len(errors)},indent=2))

if __name__=="__main__":main()
