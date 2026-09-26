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

FII_DII_SECONDARY = [
    "https://www.icicidirect.com/share-market-today",
    "https://www.kotakneo.com/share-market-today/fii-dii-data/",
]
DELIVERY_FULL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
CDSL_INDEX = "https://www.cdslindia.com/Publications/ForeignPortInvestor.html"


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


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def write_json(name: str, payload: dict) -> None:
    safe = _json_safe(payload)
    (DATA / name).write_text(
        json.dumps(safe, indent=2, ensure_ascii=False, allow_nan=False),
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


def normalize_fii_dii(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        date_text = str(
            row.get("date")
            or row.get("Date")
            or row.get("DATE")
            or row.get("reportingDate")
            or ""
        ).strip()
        if not date_text:
            continue

        def num(*keys: str) -> float:
            for key in keys:
                value = row.get(key)
                if value is None or value == "":
                    continue
                try:
                    return float(str(value).replace(",", "").replace("₹", ""))
                except Exception:
                    pass
            return 0.0

        out.append({
            "date": date_text,
            "fii_buy": num("fiiBuy", "fii_buy", "FII BUY"),
            "fii_sell": num("fiiSell", "fii_sell", "FII SELL"),
            "fii_net": num("fiiNet", "fii_net", "FII NET"),
            "dii_buy": num("diiBuy", "dii_buy", "DII BUY"),
            "dii_sell": num("diiSell", "dii_sell", "DII SELL"),
            "dii_net": num("diiNet", "dii_net", "DII NET"),
        })
    if not out:
        raise RuntimeError("FII/DII payload contained no usable sessions")
    return out


def parse_secondary_fii_dii(html: str) -> list[dict]:
    tables = pd.read_html(io.StringIO(html))
    for table in tables:
        table.columns = [
            "_".join(str(x) for x in c) if isinstance(c, tuple) else str(c)
            for c in table.columns
        ]
        cols = [str(c).strip().lower() for c in table.columns]
        joined = " | ".join(cols)
        if "date" not in joined or "fii" not in joined or "dii" not in joined:
            continue

        date_col = next((c for c in table.columns if "date" in str(c).lower()), None)

        def find_col2(who: str, what: str):
            for c in table.columns:
                lc = str(c).lower()
                if who in lc and what in lc:
                    return c
            return None

        fii_buy = find_col2("fii", "gross purchase") or find_col2("fii", "buy")
        fii_sell = find_col2("fii", "gross sales") or find_col2("fii", "sell")
        fii_net = find_col2("fii", "net")
        dii_buy = find_col2("dii", "gross purchase") or find_col2("dii", "buy")
        dii_sell = find_col2("dii", "gross sales") or find_col2("dii", "sell")
        dii_net = find_col2("dii", "net")

        if not date_col or not fii_net or not dii_net:
            continue

        rows = []
        for _, row in table.iterrows():
            d = pd.to_datetime(row[date_col], errors="coerce")
            if pd.isna(d):
                continue

            def fv(col):
                if not col:
                    return 0.0
                try:
                    return float(str(row[col]).replace(",", "").replace("₹", "").replace("−", "-"))
                except Exception:
                    return 0.0

            rows.append({
                "date": d.strftime("%d-%b-%Y"),
                "fiiBuy": fv(fii_buy),
                "fiiSell": fv(fii_sell),
                "fiiNet": fv(fii_net),
                "diiBuy": fv(dii_buy),
                "diiSell": fv(dii_sell),
                "diiNet": fv(dii_net),
            })

        if rows:
            return rows

    raise RuntimeError("Secondary FII/DII page had no usable daily table")


def fetch_fii_dii_fallback() -> list[dict]:
    last_error = None
    for url in FII_DII_SECONDARY:
        try:
            r = requests.get(
                url,
                timeout=45,
                headers={"User-Agent": HEADERS["User-Agent"]},
            )
            r.raise_for_status()
            return parse_secondary_fii_dii(r.text)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"No usable FII/DII secondary source: {last_error}")


def fetch_fii_dii() -> tuple[list[dict], str]:
    try:
        return normalize_fii_dii(fetch_fii_dii_official()), "NSE official"
    except Exception as official_error:
        rows = fetch_fii_dii_fallback()
        return normalize_fii_dii(rows), f"secondary source (NSE blocked: {official_error})"



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
    url = DELIVERY_FULL.format(ddmmyyyy=d.strftime("%d%m%Y"))
    r = requests.get(
        url,
        timeout=60,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "text/csv,*/*",
            "Referer": "https://www.nseindia.com/",
        },
    )
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))

    sym = find_col(df, "TckrSymb", "SYMBOL")
    close = find_col(df, "ClsPric", "CLOSE", "CLOSE_PRICE")
    vol = find_col(df, "TtlTradgVol", "TTL_TRD_QNTY", "TOTAL_TRADED_QUANTITY", "TOTTRDQTY")
    deliv = find_col(df, "DlvryQty", "DELIV_QTY", "DELIVERABLE_QTY")
    pct = find_col(df, "DlvryPct", "DELIV_PER", "DELIVERY_PERCENT")

    if not sym or not close or not vol or not deliv:
        raise RuntimeError(f"Unexpected full bhavcopy columns: {list(df.columns)[:30]}")

    rows = []
    for _, row in df.iterrows():
        symbol = str(row.get(sym, "")).strip()
        if not symbol or symbol.lower() == "nan":
            continue

        def fv(col):
            try:
                v = float(row[col])
                return None if math.isnan(v) else v
            except Exception:
                return None

        volume = fv(vol)
        delivery_qty = fv(deliv)
        delivery_pct = fv(pct) if pct else None
        if delivery_pct is None and delivery_qty is not None and volume:
            delivery_pct = 100.0 * delivery_qty / volume

        rows.append({
            "date": d.isoformat(),
            "symbol": symbol,
            "close": fv(close),
            "volume": volume,
            "delivery_qty": delivery_qty,
            "delivery_pct": delivery_pct,
        })
    return d, rows



def parse_cdsl_sector(html: str, as_of: str) -> list[dict]:
    tables = pd.read_html(io.StringIO(html))
    candidates = []

    for table in tables:
        t = table.copy()
        t.columns = [
            "_".join(str(x) for x in c) if isinstance(c, tuple) else str(c)
            for c in t.columns
        ]
        cols = [str(c) for c in t.columns]

        sector_col = next((c for c in cols if "sector" in c.lower()), None)
        if not sector_col and len(cols) > 1:
            sector_col = cols[1]

        # CDSL table contains multiple numeric groups. We want the Equity
        # Net Investment column for the current fortnight, not the first
        # numeric column (which can be an AUC / count field).
        net_cols = [
            c for c in cols
            if "net investment" in c.lower() and "equity" in c.lower()
        ]
        if not sector_col or not net_cols:
            continue

        # Prefer a column whose header contains the current report date.
        current = [
            c for c in net_cols
            if str(as_of)[:7] in str(c) or str(as_of) in str(c)
        ]
        candidate = current[-1] if current else net_cols[-1]

        rows = []
        for _, row in t.iterrows():
            sector = str(row.get(sector_col, "")).strip()
            if not sector or sector.lower() in {"nan","sectors","grand total","total"}:
                continue

            raw = row.get(candidate)
            try:
                flow = float(str(raw).replace(",", "").replace("₹", "").strip())
            except Exception:
                continue

            if not math.isfinite(flow):
                continue
            rows.append({"sector": sector, "flow_cr": flow})

        # Real sector rows generally include multiple named sectors; reject
        # tables that clearly aren't the sector investment table.
        if len(rows) >= 10:
            candidates.append(rows)

    if not candidates:
        raise RuntimeError("Could not identify a valid CDSL sector net-investment table")

    return max(candidates, key=len)



def fetch_cdsl_latest_sector() -> dict:
    r = requests.get(
        CDSL_INDEX,
        timeout=45,
        headers={"User-Agent": HEADERS["User-Agent"]},
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        href = a["href"]
        if "Fortnightly" in text or "15, 2026" in text or "31, 2026" in text:
            links.append((text, href))

    # Prefer the newest date-like fortnightly sector link.
    candidates = []
    for text, href in links:
        m = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
            r"(\d{1,2}),\s*(\d{4})",
            text,
            re.I,
        )
        if not m:
            continue
        try:
            dt = datetime.strptime(m.group(0), "%B %d, %Y").date()
        except ValueError:
            continue
        full = requests.compat.urljoin(CDSL_INDEX, href)
        candidates.append((dt, full))

    # Some CDSL pages expose the date in href but not anchor text.
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "FortnightlySecWisePages" not in href:
            continue
        m = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)%20(\d{1,2}),%20(\d{4})",
            href,
            re.I,
        )
        if not m:
            m = re.search(
                r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})",
                href,
                re.I,
            )
        if m:
            try:
                dt = datetime.strptime(
                    f"{m.group(1)} {m.group(2)}, {m.group(3)}", "%B %d, %Y"
                ).date()
                candidates.append((dt, requests.compat.urljoin(CDSL_INDEX, href)))
            except ValueError:
                pass

    if not candidates:
        raise RuntimeError("Could not find fortnightly sector links on CDSL index")

    dt, url = max(candidates, key=lambda x: x[0])
    rr = requests.get(
        url,
        timeout=45,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": CDSL_INDEX,
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
    )
    rr.raise_for_status()

    items = parse_cdsl_sector(rr.text, dt.isoformat())
    return {
        "as_of": dt.isoformat(),
        "cadence": "fortnightly",
        "items": items,
        "source_url": url,
    }



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

    # 3) Sector FPI — official CDSL is fortnightly. Preserve the
    # last verified snapshot if no new release is available.
    try:
        sector = fetch_cdsl_latest_sector()
        write_json("sector_fpi.json", sector)
    except Exception as exc:
        sector_path = DATA / "sector_fpi.json"
        if sector_path.exists():
            existing = json.loads(sector_path.read_text(encoding="utf-8"))
            existing["warning"] = f"No newer CDSL snapshot fetched: {exc}"
            existing["status"] = "last verified snapshot retained"
            write_json("sector_fpi.json", existing)
            print(f"Sector FPI: retaining last verified snapshot ({exc})")
        else:
            errors.append(f"CDSL sector FPI: {exc}")

    # Stock ownership remains isolated until its quarterly filing collector is wired.
    stock_path = DATA / "stocks.json"
    stocks = json.loads(stock_path.read_text(encoding="utf-8")) if stock_path.exists() else {"items": []}
    stocks["meta"] = {
        "status": "quarterly ownership collector pending; do not treat sample ownership as live",
        "last_refresh_utc": datetime.utcnow().isoformat() + "Z",
    }
    write_json("stocks.json", stocks)

    warnings = []
    try:
        sector_state = json.loads((DATA / "sector_fpi.json").read_text(encoding="utf-8"))
        if sector_state.get("warning"):
            warnings.append(sector_state["warning"])
    except Exception:
        pass

    status = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "updated_utc": datetime.utcnow().isoformat() + "Z",
    }
    write_json("refresh_status.json", status)
    if errors:
        print("Refresh completed with errors:")
        for error in errors:
            print(" -", error)
    else:
        print("Refresh completed successfully.")


if __name__ == "__main__":
    main()
