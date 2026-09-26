"""
Live market-data refresh for the dashboard.

Sources:
- NSE: https://www.nseindia.com/api/fiidiiTradeReact (daily FII/FPI + DII, provisional)
- NSE: CM-UDiFF Common Bhavcopy Final (daily price/volume/delivery)
- CDSL: Fortnightly sector-wise FPI pages (official cadence)

The job writes compact JSON files consumed by the static GitHub Pages site.
"""
from __future__ import annotations

import io
import json
import math
import re
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)

NSE_HOME = "https://www.nseindia.com/"
NSE_FIIDII = "https://www.nseindia.com/api/fiidiiTradeReact"
NSE_BHAV = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
)
CDSL_SECTOR = (
    "https://www.cdslindia.com/publications/FII/"
    "FortnightlySecWisePages/{month}%20{day}%2C%20{year}.html"
)

FII_DII_FALLBACK = "https://chirag127.github.io/fii-dii-activity-api/data/{date}.json"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": NSE_HOME,
    "Connection": "keep-alive",
}


def write_json(name: str, payload: dict) -> None:
    (DATA / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.get(NSE_HOME, timeout=30)
    r.raise_for_status()
    return s


def fetch_fii_dii_official() -> list[dict]:
    s = nse_session()
    r = s.get(NSE_FIIDII, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("NSE FII/DII returned an unexpected payload")
    return payload


def fetch_fii_dii_fallback(days: int = 45) -> list[dict]:
    """
    Fallback for GitHub Actions when NSE blocks the runner.
    The fallback is a static mirror whose payloads are sourced from NSE/Groww/
    Moneycontrol; the dashboard labels this source as non-official.
    """
    rows: list[dict] = []
    today = date.today()
    for i in range(days):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        url = FII_DII_FALLBACK.format(date=d.isoformat())
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200:
                continue
            payload = r.json()
            eq = payload.get("equity", {})
            rows.append(
                {
                    "date": d.strftime("%d-%b-%Y"),
                    "fiiBuy": eq.get("fii_buy", 0),
                    "fiiSell": eq.get("fii_sell", 0),
                    "fiiNet": eq.get("fii_net", 0),
                    "diiBuy": eq.get("dii_buy", 0),
                    "diiSell": eq.get("dii_sell", 0),
                    "diiNet": eq.get("dii_net", 0),
                }
            )
        except Exception:
            continue
    if not rows:
        raise RuntimeError("Fallback FII/DII mirror returned no usable sessions")
    return rows


def fetch_fii_dii() -> tuple[list[dict], str]:
    try:
        return normalize_fii_dii(fetch_fii_dii_official()), "NSE official"
    except Exception as official_error:
        rows = fetch_fii_dii_fallback()
        return normalize_fii_dii(rows), f"fallback mirror ({official_error})"


    s = nse_session()
    r = s.get(NSE_FIIDII, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("NSE FII/DII returned an unexpected payload")
    return payload


def normalize_fii_dii(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        date_text = str(row.get("date", "")).strip()
        if not date_text:
            continue

        def num(*keys: str) -> float:
            for key in keys:
                value = row.get(key)
                if value is None or value == "":
                    continue
                try:
                    return float(str(value).replace(",", ""))
                except ValueError:
                    continue
            return 0.0

        out.append(
            {
                "date": date_text,
                "fii_buy": num("fiiBuy"),
                "fii_sell": num("fiiSell"),
                "fii_net": num("fiiNet", "fiinet"),
                "dii_buy": num("diiBuy"),
                "dii_sell": num("diiSell"),
                "dii_net": num("diiNet", "diinet"),
            }
        )
    return out


def iso_from_nse_date(value: str) -> date:
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return datetime.strptime(value, "%d-%b-%Y").date()


def week_end(d: date) -> date:
    # Friday, or the latest date in the data's Mon-Fri trading week.
    return d + timedelta(days=(4 - d.weekday()) % 7)


def aggregate_weeks(rows: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for r in rows:
        d = iso_from_nse_date(r["date"])
        wk = week_end(d).isoformat()
        g = grouped.setdefault(
            wk,
            {"week_ending": wk, "fii": 0.0, "dii": 0.0, "sessions": 0},
        )
        g["fii"] += r["fii_net"]
        g["dii"] += r["dii_net"]
        g["sessions"] += 1
    return sorted(grouped.values(), key=lambda x: x["week_ending"])


def fetch_bhavcopy(target: date) -> pd.DataFrame:
    url = NSE_BHAV.format(yyyymmdd=target.strftime("%Y%m%d"))
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "*/*",
            "Referer": NSE_HOME,
        }
    )
    r = s.get(url, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csvs:
            raise RuntimeError(f"No CSV in NSE bhavcopy ZIP for {target}")
        with zf.open(csvs[0]) as fh:
            return pd.read_csv(fh)


def find_col(df: pd.DataFrame, *needles: str) -> str | None:
    cols = {str(c).strip().upper(): c for c in df.columns}
    for needle in needles:
        n = needle.upper()
        for upper, original in cols.items():
            if upper == n or n in upper:
                return original
    return None


def clean_bhav(df: pd.DataFrame, target: date) -> list[dict]:
    sym = find_col(df, "TckrSymb", "SYMBOL")
    close = find_col(df, "ClsPric", "CLOSE", "CLOSE_PRICE")
    vol = find_col(df, "TtlTradgVol", "TOTAL_TRADED_QUANTITY", "TOTTRDQTY")
    deliv = find_col(df, "DlvryQty", "DELIVERABLE_QTY", "DELIV_QTY")
    dlypct = find_col(df, "DlvryPct", "DELIV_PER")

    if not sym or not close or not vol:
        raise RuntimeError(
            f"Unexpected bhavcopy columns: {list(df.columns)[:20]}"
        )

    out = []
    for _, row in df.iterrows():
        symbol = str(row.get(sym, "")).strip()
        if not symbol or symbol == "nan":
            continue

        def flt(col: str | None) -> float | None:
            if not col:
                return None
            try:
                v = float(row[col])
                if math.isnan(v):
                    return None
                return v
            except (ValueError, TypeError):
                return None

        close_v = flt(close)
        vol_v = flt(vol)
        deliv_v = flt(deliv)
        pct_v = flt(dlypct)

        if pct_v is None and deliv_v is not None and vol_v:
            pct_v = (deliv_v / vol_v) * 100.0

        out.append(
            {
                "date": target.isoformat(),
                "symbol": symbol,
                "close": close_v,
                "volume": vol_v,
                "delivery_qty": deliv_v,
                "delivery_pct": pct_v,
            }
        )
    return out


def latest_trading_date() -> date:
    # Try today, then up to 7 prior calendar days.
    for i in range(0, 8):
        d = date.today() - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            fetch_bhavcopy(d)
            return d
        except Exception:
            continue
    raise RuntimeError("Could not find a recent NSE bhavcopy")


def fetch_latest_delivery() -> tuple[date, list[dict]]:
    d = latest_trading_date()
    df = fetch_bhavcopy(d)
    return d, clean_bhav(df, d)


def parse_cdsl_sector(html: str, as_of: str) -> list[dict]:
    tables = pd.read_html(io.StringIO(html))
    chosen = None

    for table in tables:
        text = " ".join(str(x) for x in table.astype(str).fillna("").head(10).to_numpy().ravel())
        if "Sectors" in text or "sector" in text:
            chosen = table
            break

    if chosen is None or chosen.empty:
        raise RuntimeError("Could not identify CDSL sector table")

    # The CDSL table is a multi-header table. Locate rows by sector name and
    # extract the latest fortnight's Equity net-investment column.
    chosen.columns = [
        "_".join(str(x) for x in c) if isinstance(c, tuple) else str(c)
        for c in chosen.columns
    ]

    sector_col = None
    for c in chosen.columns:
        if "sector" in c.lower():
            sector_col = c
            break
    if sector_col is None:
        sector_col = chosen.columns[1]

    # Prefer the first numeric column after the sector name that looks like
    # "Net Investment ... Equity" and fall back to a numeric scan.
    numeric_cols = [c for c in chosen.columns if c != sector_col]
    candidate = None
    for c in numeric_cols:
        lc = c.lower()
        if "net investment" in lc and "equity" in lc:
            candidate = c
            break
    if candidate is None and numeric_cols:
        candidate = numeric_cols[0]

    items = []
    for _, row in chosen.iterrows():
        sector = str(row.get(sector_col, "")).strip()
        if not sector or sector.lower() in {"sectors", "nan", "total"}:
            continue
        raw = row.get(candidate)
        try:
            flow = float(str(raw).replace(",", "").replace("₹", ""))
        except (ValueError, TypeError):
            continue
        items.append({"sector": sector, "flow_cr": flow})

    if not items:
        raise RuntimeError("CDSL sector table contained no numeric sector flows")

    return items


def fetch_cdsl_latest_sector() -> dict:
    today = date.today()
    candidates = []
    # CDSL publishes 15th/30th/31st snapshots. Try most recent first.
    for day in (15, 30, 31):
        for months_back in range(0, 2):
            month_start = (today.replace(day=1) - pd.DateOffset(months=months_back)).date()
            month = month_start.strftime("%b")
            year = month_start.year
            if day == 15 and month_start > today.replace(day=1):
                continue
            candidates.append((year, month, day))

    for year, month, day in candidates:
        url = CDSL_SECTOR.format(month=month, day=day, year=year)
        try:
            r = requests.get(
                url,
                timeout=45,
                headers={
                    "User-Agent": HEADERS["User-Agent"],
                    "Referer": "https://www.cdslindia.com/Publications/ForeignPortInvestor.html",
                    "Accept": "text/html,application/xhtml+xml,*/*",
                },
            )
            if r.status_code != 200 or len(r.text) < 1000:
                continue
            items = parse_cdsl_sector(r.text, f"{day:02d}-{month}-{year}")
            return {
                "as_of": f"{year}-{datetime.strptime(month, '%b').month:02d}-{day:02d}",
                "cadence": "fortnightly",
                "items": items,
                "source_url": url,
            }
        except Exception:
            continue
    raise RuntimeError("Could not locate latest CDSL sector FPI page")


def main() -> None:
    errors: list[str] = []

    # 1) FII/DII
    try:
        fii_dii, flow_source = fetch_fii_dii()
        weeks = aggregate_weeks(fii_dii)
        if weeks:
            write_json(
                "weekly.json",
                {
                    "meta": {
                        "status": "live",
                        "last_updated_utc": datetime.utcnow().isoformat() + "Z",
                        "sources": [
                            "NSE FII/FPI & DII trading activity (provisional)",
                            "NSE CM-UDiFF bhavcopy",
                            "CDSL fortnightly sector FPI",
                        ],
                    },
                    "weeks": weeks[-26:],
                    "daily": fii_dii[:90],
                },
            )
    except Exception as exc:
        errors.append(f"FII/DII: {exc}")

    # 2) Delivery + daily price/volume
    try:
        d, rows = fetch_latest_delivery()
        write_json(
            "delivery.json",
            {
                "as_of": d.isoformat(),
                "source": "NSE CM-UDiFF Common Bhavcopy Final",
                "items": rows,
            },
        )
    except Exception as exc:
        errors.append(f"Delivery/bhavcopy: {exc}")

    # 3) Sector FPI
    try:
        sector = fetch_cdsl_latest_sector()
        write_json("sector_fpi.json", sector)
    except Exception as exc:
        errors.append(f"CDSL sector FPI: {exc}")

    # Keep stock ownership sample isolated until quarterly filing collector
    # is wired. This avoids presenting stale values as live.
    stock_path = DATA / "stocks.json"
    stocks = json.loads(stock_path.read_text(encoding="utf-8")) if stock_path.exists() else {"items": []}
    stocks["meta"] = {
        "status": "quarterly ownership collector pending; do not treat sample ownership as live",
        "last_refresh_utc": datetime.utcnow().isoformat() + "Z",
    }
    write_json("stocks.json", stocks)

    status = {"ok": not errors, "errors": errors, "updated_utc": datetime.utcnow().isoformat() + "Z"}
    write_json("refresh_status.json", status)
    if errors:
        print("Refresh completed with errors:")
        for error in errors:
            print(" -", error)
    else:
        print("Refresh completed successfully.")


if __name__ == "__main__":
    main()
