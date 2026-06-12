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


def _naver_integration(ticker: str) -> dict:
    url = f"https://m.stock.naver.com/api/stock/{ticker}/integration"
    r = requests.get(url, headers=_HEADERS, timeout=8)
    r.raise_for_status()
    return r.json()


def _naver_income(ticker: str) -> list[dict]:
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


def _dart_income(ticker: str) -> list[dict]:
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


def get_korean_stock(ticker: str) -> dict:
    # Naver integration + DART income 병렬 호출
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_nav    = ex.submit(_naver_integration, ticker)
        f_income = ex.submit(lambda: _dart_income(ticker) or _naver_income(ticker))

        try:
            nav = f_nav.result(timeout=10)
        except Exception:
            return {"error": f"'{ticker}' 종목 데이터를 찾을 수 없습니다."}

        income = f_income.result(timeout=30)

    # 유효성 확인
    if not nav.get("stockName"):
        return {"error": f"'{ticker}' 종목 데이터를 찾을 수 없습니다."}

    # 기본 정보
    name     = nav.get("stockName", ticker)
    exchange = nav.get("stockExchangeType", {}).get("nameKor", "")

    # 가격
    close_str  = nav.get("closePrice", "0").replace(",", "")
    change_str = nav.get("compareToPreviousClosePrice", "0").replace(",", "")
    ratio_str  = nav.get("fluctuationsRatio", "0")
    direction  = nav.get("compareToPreviousPrice", {}).get("code", "3")
    try:
        close      = int(close_str)
        change_val = int(change_str)
        change_pct = float(ratio_str)
        pos        = direction in ("1", "2")  # 상한, 상승
        if not pos:
            change_val = -abs(change_val)
            change_pct = -abs(change_pct)
    except Exception:
        close, change_val, change_pct, pos = 0, 0, 0.0, True

    # totalInfos 파싱
    info_map = {i["code"]: i["value"] for i in nav.get("totalInfos", [])}

    def get_info(code: str) -> str:
        return info_map.get(code, "N/A")

    per    = get_info("per").replace("배", "x")
    pbr    = get_info("pbr").replace("배", "x")
    eps    = get_info("eps")
    div    = get_info("dividendYieldRatio")
    mktcap = get_info("marketValue")
    foreign = get_info("foreignRate")

    high52_raw = get_info("highPriceOf52Weeks").replace(",", "")
    low52_raw  = get_info("lowPriceOf52Weeks").replace(",", "")
    high52 = f"{int(high52_raw):,}원" if high52_raw.isdigit() else "N/A"
    low52  = f"{int(low52_raw):,}원"  if low52_raw.isdigit()  else "N/A"

    vol_raw = get_info("accumulatedTradingVolume").replace(",", "")
    vol = vol_raw if vol_raw.isdigit() else "0"

    asof = datetime.now().strftime("%Y.%m.%d") + " 기준"

    return {
        "ticker":   ticker,
        "name":     name,
        "sector":   exchange or "N/A",
        "price":    f"{close:,}원" if close else "N/A",
        "change":   f"{'+' if pos else ''}{change_val:,}원 ({'+' if pos else ''}{change_pct:.2f}%)",
        "pos":      pos,
        "asof":     asof,
        "per":      per,
        "pbr":      pbr,
        "eps":      eps,
        "mktcap":   mktcap,
        "roe":      "N/A",
        "debt":     "N/A",
        "evebitda": "N/A",
        "div":      div,
        "beta":     "N/A",
        "foreign":  foreign,
        "vol":      vol,
        "avgvol":   "N/A",
        "high52":   high52,
        "low52":    low52,
        "income":   income,
    }
