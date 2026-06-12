from datetime import datetime, timedelta
from pykrx import stock as pykrx_stock
import FinanceDataReader as fdr
import OpenDartReader as odr
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import os

DART_API_KEY = os.getenv("DART_API_KEY", "")
_NAVER_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}


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


def _get_name_and_sector(ticker: str) -> tuple[str, str]:
    try:
        listing = fdr.StockListing("KRX")
        row = listing[listing["Code"] == ticker]
        if not row.empty:
            name = str(row.iloc[0].get("Name", "") or "")
            sector = str(row.iloc[0].get("Industry", "") or row.iloc[0].get("Sector", "") or "")
            return name, sector
    except Exception:
        pass
    return ticker, ""


def _get_naver_fundamentals(ticker: str) -> dict:
    """네이버 금융에서 PER, PBR, EPS, 시가총액, 배당수익률, 외국인보유 스크래핑"""
    try:
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        r = requests.get(url, headers=_NAVER_HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        def em(id_: str) -> str:
            tag = soup.find("em", id=id_)
            return tag.text.strip().replace(",", "") if tag else ""

        per     = em("_per")
        eps     = em("_eps")
        pbr     = em("_pbr")
        dvr     = em("_dvr")
        mktcap  = em("_market_sum")  # 조 단위 문자열 포함

        # 외국인 보유 비율
        foreign_tag = soup.select_one("div.section_company span.blind")
        foreign = ""
        for tag in soup.find_all("td", class_="cmp-table-cell"):
            pass  # 복잡한 구조, 별도 API로 처리

        return {
            "per":    f"{float(per):.1f}x"  if per  else "N/A",
            "pbr":    f"{float(pbr):.1f}x"  if pbr  else "N/A",
            "eps":    f"{int(eps):,}원"      if eps  else "N/A",
            "div":    f"{float(dvr):.2f}%"   if dvr  else "N/A",
            "mktcap_raw": mktcap,
        }
    except Exception:
        return {}


def _get_naver_foreign(ticker: str) -> str:
    """네이버 금융 외국인 보유 비율"""
    try:
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        r = requests.get(url, headers=_NAVER_HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        # 외국인 비율 위치: div.section_buy table에서 찾기
        for tr in soup.select("table.per_table tr"):
            th = tr.find("th")
            td = tr.find("td")
            if th and td and "외국인" in th.text:
                val = td.text.strip().replace("%", "").replace(",", "")
                return f"{float(val):.1f}%"
    except Exception:
        pass
    return "N/A"


def _get_yf_extra(ticker: str) -> dict:
    """yfinance로 ROE, 부채비율, EV/EBITDA, 베타 (한국 주식 .KS/.KQ)"""
    for suffix in [".KS", ".KQ"]:
        try:
            t = yf.Ticker(ticker + suffix)
            info = t.info
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


def get_dart_financials(ticker: str) -> list[dict]:
    """DART에서 최근 3개 연도 손익 데이터 (억 원 단위)"""
    if not DART_API_KEY:
        return []
    try:
        dart = odr(DART_API_KEY)
        codes = dart.corp_codes
        match = codes[codes["stock_code"] == ticker]
        if match.empty:
            return []
        corp_code = match.iloc[0]["corp_code"]

        rows = []
        current_year = datetime.now().year
        for year in range(current_year - 3, current_year):
            try:
                fs = dart.finstate(corp_code, year, "11011")  # 연결
                if fs is None or fs.empty:
                    fs = dart.finstate(corp_code, year, "11001")  # 별도
                if fs is None or fs.empty:
                    continue

                is_df = fs[fs["sj_div"] == "IS"]

                def extract(keywords: list[str]) -> int:
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
                rows.append({"year": str(year), "rev": rev // 100_000_000, "op": op // 100_000_000, "net": net // 100_000_000})
            except Exception:
                continue
        return rows
    except Exception:
        return []


def _get_naver_income(ticker: str) -> list[dict]:
    """네이버 금융에서 연간 손익 데이터 (DART 키 없을 때 사용)"""
    try:
        url = f"https://m.stock.naver.com/api/stock/{ticker}/finance/summary"
        r = requests.get(url, headers=_NAVER_HEADERS, timeout=10)
        data = r.json()
        annual = data.get("chartIncomeStatement", {}).get("annual", {})
        cols = annual.get("columns", [])
        if not cols or len(cols) < 3:
            return []

        years = cols[0][1:]    # 연도 라벨
        revs  = cols[1][1:]    # 매출액
        ops   = cols[2][1:]    # 영업이익

        rows = []
        for i, year_label in enumerate(years[:3]):  # 최근 실적 3개년
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


def get_korean_stock(ticker: str) -> dict:
    today  = _today()
    from_1m = _date_n_days_ago(30)
    from_1y = _date_n_days_ago(380)

    # 종목명, 섹터
    name, sector = _get_name_and_sector(ticker)

    # pykrx: 가격/거래량
    try:
        ohlcv = pykrx_stock.get_market_ohlcv_by_date(from_1m, today, ticker)
        if ohlcv.empty:
            raise ValueError("empty")
        latest    = ohlcv.iloc[-1]
        prev      = ohlcv.iloc[-2] if len(ohlcv) > 1 else latest
        close     = int(latest["종가"])
        prev_close = int(prev["종가"])
        change_val = close - prev_close
        change_pct = (change_val / prev_close * 100) if prev_close else 0
        vol        = int(latest["거래량"])
        asof       = ohlcv.index[-1].strftime("%Y.%m.%d") + " 종가 기준"
    except Exception:
        return {"error": f"'{ticker}' 종목 데이터를 찾을 수 없습니다."}

    # pykrx: 52주 고/저 + 평균거래량
    try:
        hist_1y = pykrx_stock.get_market_ohlcv_by_date(from_1y, today, ticker)
        high52  = int(hist_1y["고가"].max())
        low52   = int(hist_1y["저가"].min())
        avgvol  = int(hist_1y["거래량"].tail(20).mean()) if len(hist_1y) >= 20 else vol
    except Exception:
        high52, low52, avgvol = 0, 0, vol

    # 네이버 금융: PER, PBR, EPS, 배당수익률, 시가총액
    naver = _get_naver_fundamentals(ticker)
    mktcap_raw = naver.pop("mktcap_raw", "")

    # 시가총액 파싱 (네이버는 "X,XXX조" 형식)
    mktcap = "N/A"
    try:
        listing = fdr.StockListing("KRX")
        row = listing[listing["Code"] == ticker]
        if not row.empty:
            mc = float(row.iloc[0].get("Marcap", 0) or 0)
            mktcap = _fmt_large_krw(mc)
    except Exception:
        pass

    # yfinance: ROE, 부채비율, EV/EBITDA, 베타
    yf_extra = _get_yf_extra(ticker)

    # 외국인 보유 비율 (pykrx 시도)
    foreign = "N/A"
    try:
        f_df = pykrx_stock.get_exhaustion_rates_of_foreign_investment_by_date(from_1m, today, ticker)
        if not f_df.empty:
            col = "보유비율" if "보유비율" in f_df.columns else f_df.columns[-1]
            foreign = f"{float(f_df.iloc[-1][col]):.1f}%"
    except Exception:
        pass

    # 손익 데이터: DART (키 있을 때) 또는 네이버 금융
    income = get_dart_financials(ticker) or _get_naver_income(ticker)

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
