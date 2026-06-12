import FinanceDataReader as fdr
import requests
import time

_cache = {"data": None, "ts": 0}
_TTL = 6 * 3600
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

_EXCH_MAP = {
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NAS": "NASDAQ",
    "NYQ": "NYSE",   "PCX": "NYSE",
    "ASE": "AMEX",
}


def _yahoo_ac(query: str, limit: int = 10) -> list[dict]:
    """Yahoo Finance autocomplete — 미국 상장 주식 검색"""
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": query, "quotesCount": limit, "newsCount": 0, "enableFuzzyQuery": False},
            headers={**_HEADERS, "Accept": "application/json"},
            timeout=5,
        )
        results = []
        for q in r.json().get("quotes", []):
            if q.get("quoteType") not in ("EQUITY", "ETF"):
                continue
            symbol = q.get("symbol", "")
            if "." in symbol:  # .KS .HK 등 비미국 제외
                continue
            name = q.get("longname") or q.get("shortname") or symbol
            market = _EXCH_MAP.get(q.get("exchange", ""), q.get("exchange", "US"))
            results.append({"code": symbol, "name": name, "market": market})
        return results[:limit]
    except Exception:
        return []


def _get_listing():
    now = time.time()
    if _cache["data"] is None or now - _cache["ts"] > _TTL:
        df = fdr.StockListing("KRX")
        _cache["data"] = df[["Code", "Name", "Market"]].to_dict("records")
        _cache["ts"] = now
    return _cache["data"]


def _naver_ac(query: str, limit: int = 10) -> list[dict]:
    """네이버 금융 자동완성 API — 일반명(삼성SDS)도 검색 가능"""
    try:
        r = requests.get(
            "https://ac.finance.naver.com/ac",
            params={"q": query, "q_enc": "UTF-8", "st": "111", "t_koreng": "1", "r_lt": "111"},
            headers=_HEADERS,
            timeout=5,
        )
        items = r.json().get("items", [[]])[0]  # items[0] = 주식 목록
        results = []
        for item in items[:limit]:
            # item: [종목명, 코드, ...]
            if len(item) >= 2:
                results.append({"code": item[1], "name": item[0], "market": ""})
        return results
    except Exception:
        return []


def _has_korean(text: str) -> bool:
    return any("가" <= c <= "힣" or "ㄱ" <= c <= "ㆎ" for c in text)


def search_stocks(query: str, limit: int = 10) -> list[dict]:
    if not query:
        return []

    q = query.strip()
    q_lower = q.lower()
    results = []
    codes_seen = set()

    if _has_korean(q) or q.isdigit():
        # ── 국내 주식 검색 ──────────────────────────────
        listing = _get_listing()
        for item in listing:
            name = item.get("Name", "")
            code = item.get("Code", "")
            if q_lower in name.lower() or q_lower in code.lower():
                results.append({"code": code, "name": name, "market": item.get("Market", "")})
                codes_seen.add(code)
            if len(results) >= limit:
                break

        if len(results) < limit:
            for item in _naver_ac(q, limit):
                if item["code"] not in codes_seen:
                    results.append(item)
                    codes_seen.add(item["code"])
                if len(results) >= limit:
                    break
    else:
        # ── 미국 주식 검색 (Yahoo Finance) ───────────────
        for item in _yahoo_ac(q, limit):
            if item["code"] not in codes_seen:
                results.append(item)
                codes_seen.add(item["code"])
            if len(results) >= limit:
                break

    return results[:limit]


def name_to_code(name: str) -> str | None:
    listing = _get_listing()
    # 1차: 공식명 정확 매칭
    for item in listing:
        if item.get("Name", "") == name:
            return item.get("Code")
    # 2차: 네이버 AC fallback (삼성SDS 같은 일반명 처리)
    hits = _naver_ac(name, limit=1)
    if hits:
        return hits[0]["code"]
    return None
