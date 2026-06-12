from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import requests
import os

try:
    import OpenDartReader as _odr_cls
except ImportError:
    from opendartreader import OpenDartReader as _odr_cls

DART_API_KEY = os.getenv("DART_API_KEY", "")
_HEADERS = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15"}

_dart_cache = {"dart": None, "codes": None, "ts": 0}
_DART_TTL = 24 * 3600


def _get_dart_instance():
    now = time.time()
    if _dart_cache["codes"] is None or now - _dart_cache["ts"] > _DART_TTL:
        dart = _odr_cls(DART_API_KEY)
        _dart_cache["dart"] = dart
        _dart_cache["codes"] = dart.corp_codes
        _dart_cache["ts"] = now
    return _dart_cache["dart"], _dart_cache["codes"]


def _naver_basic(ticker: str) -> dict:
    """현재가, 등락, 종목명"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/basic"
    r = requests.get(url, headers=_HEADERS, timeout=8)
    r.raise_for_status()
    return r.json()


def _naver_integration(ticker: str) -> dict:
    """PER/PBR/EPS/52주/시총/외인/배당"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/integration"
    r = requests.get(url, headers=_HEADERS, timeout=8)
    r.raise_for_status()
    return r.json()


def _fetch_finstate_year(dart, corp_code: str, year: int) -> dict | None:
    try:
        fs = dart.finstate(corp_code, year, "11011")
        if fs is None or fs.empty:
            fs = dart.finstate(corp_code, year, "11001")
        if fs is None or fs.empty:
            return None

        is_df = fs[fs["sj_div"] == "IS"]
        bs_df = fs[fs["sj_div"] == "BS"]

        def extract(df, keywords):
            for kw in keywords:
                m = df[df["account_nm"].str.contains(kw, na=False)]
                if not m.empty:
                    raw = str(m.iloc[0].get("thstrm_amount", "0") or "0")
                    try:
                        return int(raw.replace(",", ""))
                    except Exception:
                        return 0
            return 0

        rev    = extract(is_df, ["매출액", "수익(매출액)"])
        op     = extract(is_df, ["영업이익"])
        net    = extract(is_df, ["당기순이익"])
        equity = extract(bs_df, ["자본총계", "총자본"])
        liab   = extract(bs_df, ["부채총계", "총부채"])

        return {
            "year":   str(year),
            "rev":    rev    // 100_000_000,
            "op":     op     // 100_000_000,
            "net":    net    // 100_000_000,
            "equity": equity // 100_000_000,
            "liab":   liab   // 100_000_000,
        }
    except Exception:
        return None


def _dart_financials(ticker: str) -> list[dict]:
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


def _naver_income_fallback(ticker: str) -> list[dict]:
    try:
        url = f"https://m.stock.naver.com/api/stock/{ticker}/finance/summary"
        r = requests.get(url, headers=_HEADERS, timeout=8)
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


def get_korean_stock(ticker: str) -> dict:
    # 3개 소스 병렬 호출
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_basic = ex.submit(_naver_basic, ticker)
        f_integ = ex.submit(_naver_integration, ticker)
        f_dart  = ex.submit(_dart_financials, ticker)

        try:
            basic = f_basic.result(timeout=10)
        except Exception:
            return {"error": f"'{ticker}' 종목 데이터를 찾을 수 없습니다."}

        try:
            integ = f_integ.result(timeout=10)
        except Exception:
            integ = {}

        dart_rows = f_dart.result(timeout=30)

    if not basic.get("stockName"):
        return {"error": f"'{ticker}' 종목 데이터를 찾을 수 없습니다."}

    # income: DART 우선, 없으면 Naver fallback
    income = [{"year": r["year"], "rev": r["rev"], "op": r["op"], "net": r["net"]} for r in dart_rows] \
             if dart_rows else _naver_income_fallback(ticker)

    # ROE, 부채비율 — 최근 연도 BS 데이터에서 계산
    roe, debt = "N/A", "N/A"
    if dart_rows:
        latest = dart_rows[-1]
        eq = latest.get("equity", 0)
        lb = latest.get("liab", 0)
        nt = latest.get("net", 0)
        if eq and eq > 0:
            roe  = f"{nt / eq * 100:.1f}%"
            debt = f"{lb / eq * 100:.1f}%"

    # 가격 (basic)
    name      = basic.get("stockName", ticker)
    exchange  = basic.get("stockExchangeType", {}).get("nameKor", "N/A")
    close_str = basic.get("closePrice", "0").replace(",", "")
    chg_str   = basic.get("compareToPreviousClosePrice", "0").replace(",", "")
    ratio_str = basic.get("fluctuationsRatio", "0")
    direction = basic.get("compareToPreviousPrice", {}).get("code", "3")

    try:
        close      = int(close_str)
        change_val = int(chg_str)
        change_pct = float(ratio_str)
        pos        = direction in ("1", "2")
        if not pos:
            change_val = -abs(change_val)
            change_pct = -abs(change_pct)
    except Exception:
        close, change_val, change_pct, pos = 0, 0, 0.0, True

    # integration totalInfos
    info_map = {i["code"]: i["value"] for i in integ.get("totalInfos", [])}

    def gi(code):
        return info_map.get(code, "N/A")

    per    = gi("per").replace("배", "x")
    pbr    = gi("pbr").replace("배", "x")
    eps    = gi("eps")
    div    = gi("dividendYieldRatio")
    mktcap = gi("marketValue")
    foreign = gi("foreignRate")

    h52 = gi("highPriceOf52Weeks").replace(",", "")
    l52 = gi("lowPriceOf52Weeks").replace(",", "")
    high52 = f"{int(h52):,}원" if h52.isdigit() else "N/A"
    low52  = f"{int(l52):,}원" if l52.isdigit() else "N/A"

    vol_raw = gi("accumulatedTradingVolume").replace(",", "")
    vol = vol_raw if vol_raw.isdigit() else "0"

    # 평균 거래량: integration의 최근 5거래일 dealTrendInfos 평균
    avgvol = "N/A"
    try:
        trends = integ.get("dealTrendInfos", [])
        if trends:
            vols = [int(t["accumulatedTradingVolume"].replace(",", "")) for t in trends if t.get("accumulatedTradingVolume")]
            if vols:
                avgvol = str(sum(vols) // len(vols))
    except Exception:
        pass

    asof = datetime.now().strftime("%Y.%m.%d") + " 기준"

    return {
        "ticker":   ticker,
        "name":     name,
        "sector":   exchange,
        "price":    f"{close:,}원" if close else "N/A",
        "change":   f"{'+' if pos else ''}{change_val:,}원 ({'+' if pos else ''}{change_pct:.2f}%)",
        "pos":      pos,
        "asof":     asof,
        "per":      per,
        "pbr":      pbr,
        "eps":      eps,
        "mktcap":   mktcap,
        "roe":      roe,
        "debt":     debt,
        "evebitda": "N/A",
        "div":      div,
        "beta":     "N/A",
        "foreign":  foreign,
        "vol":      vol,
        "avgvol":   avgvol,
        "high52":   high52,
        "low52":    low52,
        "income":   income,
    }
