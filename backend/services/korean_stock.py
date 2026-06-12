from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from pykrx import stock as pykrx_stock
import FinanceDataReader as fdr
try:
    import OpenDartReader as odr
except ImportError:
    from opendartreader import OpenDartReader as odr
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import os

DART_API_KEY = os.getenv("DART_API_KEY", "")
_NAVER_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}

# 모듈 레벨 캐시 (서버 재시작 전까지 유지)
_krx_cache = {"data": None, "ts": 0}
_dart_cache = {"dart": None, "codes": None, "ts": 0}
_KRX_TTL  = 6 * 3600   # 6시간
_DART_TTL = 24 * 3600  # 24시간


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _date_n_days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y%m%d")


def _fmt_krw(value: float) -> str:
    return f"{int(value):,}원"


def _fmt_large_krw(value: float) -> str:
    if value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.0f}조 원"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.0f}억 원"
    return _fmt_krw(value)


def _safe(val, fallback="N/A"):
    if val is None or (isinstance(val, float) and val != val):
        return fallback
    return val


def _get_krx_listing():
    now = time.time()
    if _krx_cache["data"] is None or now - _krx_cache["ts"] > _KRX_TTL:
        _krx_cache["data"] = fdr.StockListing("KRX")
        _krx_cache["ts"] = now
    return _krx_cache["data"]


def _get_dart_instance():
    now = time.time()
    if _dart_cache["codes"] is None or now - _dart_cache["ts"] > _DART_TTL:
        dart = odr(DART_API_KEY)
        _dart_cache["dart"] = dart
        _dart_cache["codes"] = dart.corp_codes
        _dart_cache["ts"] = now
    return _dart_cache["dart"], _dart_cache["codes"]


def _get_name_sector_mktcap(ticker: str) -> tuple[str, str, str]:
    try:
        listing = _get_krx_listing()
        row = listing[listing["Code"] == ticker]
        if not row.empty:
            name   = str(row.iloc[0].get("Name", "") or "")
            sector = str(row.iloc[0].get("Industry", "") or row.iloc[0].get("Sector", "") or "")
            mc     = float(row.iloc[0].get("Marcap", 0) or 0)
            mktcap = _fmt_large_krw(mc) if mc else "N/A"
            return name, sector, mktcap
    except Exception:
        pass
    return ticker, "", "N/A"


def _get_naver_fundamentals(ticker: str) -> dict:
    try:
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        r = requests.get(url, headers=_NAVER_HEADERS, timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")

        def em(id_: str) -> str:
            tag = soup.find("em", id=id_)
            return tag.text.strip().replace(",", "") if tag else ""

        per = em("_per")
        eps = em("_eps")
        pbr = em("_pbr")
        dvr = em("_dvr")
        return {
            "per": f"{float(per):.1f}x" if per else "N/A",
            "pbr": f"{float(pbr):.1f}x" if pbr else "N/A",
            "eps": f"{int(eps):,}원"    if eps else "N/A",
            "div": f"{float(dvr):.2f}%" if dvr else "N/A",
        }
    except Exception:
        return {}


def _get_yf_extra(ticker: str) -> dict:
    for suffix in [".KS", ".KQ"]:
        try:
            info = yf.Ticker(ticker + suffix).info
            if info and info.get("returnOnEquity") is not None:
                roe  = _safe(info.get("returnOnEquity"))
                debt = _safe(info.get("debtToEquity"))
                ev   = _safe(info.get("enterpriseToEbitda"))
                beta = _safe(info.get("beta"))
                return {
                    "roe":      f"{roe * 100:.1f}%"  if roe  != "N/A" else "N/A",
                    "debt":     f"{debt:.1f}%"        if debt != "N/A" else "N/A",
                    "evebitda": f"{ev:.1f}x"          if ev   != "N/A" else "N/A",
                    "beta":     f"{beta:.2f}"          if beta != "N/A" else "N/A",
                }
        except Exception:
            continue
    return {"roe": "N/A", "debt": "N/A", "evebitda": "N/A", "beta": "N/A"}


def _fetch_finstate_year(dart, corp_code: str, year: int) -> dict | None:
    try:
        fs = dart.finstate(corp_code, year, "11011")
        if fs is None or fs.empty:
            fs = dart.finstate(corp_code, year, "11001")
        if fs is None or fs.empty:
            return None
        is_df = fs[fs["sj_div"] == "IS"]

        def extract(keywords):
            for kw in keywords:
                m = is_df[is_df["account_nm"].str.contains(kw, na=False)]
                if not m.empty:
                    raw = str(m.iloc[0].get("thstrm_amount", "0") or "0")
                    try:
                        return int(raw.replace(",", ""))
                    except Exception:
                        return 0
            return 0

        rev = extract(["매출액", "수익(매출액)"])
        op  = extract(["영업이익"])
        net = extract(["당기순이익"])
        return {"year": str(year), "rev": rev // 100_000_000, "op": op // 100_000_000, "net": net // 100_000_000}
    except Exception:
        return None


def get_dart_financials(ticker: str) -> list[dict]:
    if not DART_API_KEY:
        return []
    try:
        dart, codes = _get_dart_instance()
        match = codes[codes["stock_code"] == ticker]
        if match.empty:
            return []
        corp_code = match.iloc[0]["corp_code"]
        current_year = datetime.now().year
        years = range(current_year - 3, current_year)

        # 3개 연도 병렬 조회
        results = {}
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(_fetch_finstate_year, dart, corp_code, y): y for y in years}
            for f in as_completed(futs):
                y = futs[f]
                row = f.result()
                if row:
                    results[y] = row
        return [results[y] for y in sorted(results)]
    except Exception:
        return []


def _get_naver_income(ticker: str) -> list[dict]:
    try:
        url = f"https://m.stock.naver.com/api/stock/{ticker}/finance/summary"
        r = requests.get(url, headers=_NAVER_HEADERS, timeout=8)
        data = r.json()
        annual = data.get("chartIncomeStatement", {}).get("annual", {})
        cols = annual.get("columns", [])
        if not cols or len(cols) < 3:
            return []
        years = cols[0][1:]
        revs  = cols[1][1:]
        ops   = cols[2][1:]
        rows = []
        for i, year_label in enumerate(years[:3]):
            year = year_label.replace(".", "")[:4]
            try:
                rev = int(str(revs[i]).replace(",", "")) if revs[i] else 0
                op  = int(str(ops[i]).replace(",", ""))  if ops[i]  else 0
            except Exception:
                rev, op = 0, 0
            rows.append({"year": year, "rev": rev, "op": op, "net": 0})
        return rows
    except Exception:
        return []


def _get_foreign(ticker: str, from_1m: str, today: str) -> str:
    try:
        f_df = pykrx_stock.get_exhaustion_rates_of_foreign_investment_by_date(from_1m, today, ticker)
        if not f_df.empty:
            col = "보유비율" if "보유비율" in f_df.columns else f_df.columns[-1]
            return f"{float(f_df.iloc[-1][col]):.1f}%"
    except Exception:
        pass
    return "N/A"


def get_korean_stock(ticker: str) -> dict:
    today   = _today()
    from_1m = _date_n_days_ago(30)
    from_1y = _date_n_days_ago(380)

    # 가격/거래량 먼저 (ticker 유효성 확인)
    try:
        ohlcv = pykrx_stock.get_market_ohlcv_by_date(from_1m, today, ticker)
        if ohlcv.empty:
            raise ValueError("empty")
        latest     = ohlcv.iloc[-1]
        prev       = ohlcv.iloc[-2] if len(ohlcv) > 1 else latest
        close      = int(latest["종가"])
        prev_close = int(prev["종가"])
        change_val = close - prev_close
        change_pct = (change_val / prev_close * 100) if prev_close else 0
        vol        = int(latest["거래량"])
        asof       = ohlcv.index[-1].strftime("%Y.%m.%d") + " 종가 기준"
    except Exception:
        return {"error": f"'{ticker}' 종목 데이터를 찾을 수 없습니다."}

    # 나머지 5개 소스 병렬 호출
    with ThreadPoolExecutor(max_workers=5) as ex:
        f_hist    = ex.submit(pykrx_stock.get_market_ohlcv_by_date, from_1y, today, ticker)
        f_info    = ex.submit(_get_name_sector_mktcap, ticker)
        f_naver   = ex.submit(_get_naver_fundamentals, ticker)
        f_yf      = ex.submit(_get_yf_extra, ticker)
        f_income  = ex.submit(lambda: get_dart_financials(ticker) or _get_naver_income(ticker))
        f_foreign = ex.submit(_get_foreign, ticker, from_1m, today)

        try:
            hist_1y = f_hist.result(timeout=15)
            high52  = int(hist_1y["고가"].max())
            low52   = int(hist_1y["저가"].min())
            avgvol  = int(hist_1y["거래량"].tail(20).mean()) if len(hist_1y) >= 20 else vol
        except Exception:
            high52, low52, avgvol = 0, 0, vol

        name, sector, mktcap = f_info.result(timeout=15)
        naver    = f_naver.result(timeout=15)
        yf_extra = f_yf.result(timeout=15)
        income   = f_income.result(timeout=30)
        foreign  = f_foreign.result(timeout=15)

    return {
        "ticker":   ticker,
        "name":     name or ticker,
        "sector":   sector or "N/A",
        "price":    _fmt_krw(close),
        "change":   f"{'+' if change_val >= 0 else ''}{change_val:,}원 ({'+' if change_pct >= 0 else ''}{change_pct:.2f}%)",
        "pos":      change_val >= 0,
        "asof":     asof,
        "per":      naver.get("per", "N/A"),
        "pbr":      naver.get("pbr", "N/A"),
        "eps":      naver.get("eps", "N/A"),
        "mktcap":   mktcap,
        "roe":      yf_extra["roe"],
        "debt":     yf_extra["debt"],
        "evebitda": yf_extra["evebitda"],
        "div":      naver.get("div", "N/A"),
        "beta":     yf_extra["beta"],
        "foreign":  foreign,
        "vol":      str(vol),
        "avgvol":   str(avgvol),
        "high52":   _fmt_krw(high52) if high52 else "N/A",
        "low52":    _fmt_krw(low52)  if low52  else "N/A",
        "income":   income,
    }
