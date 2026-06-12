import FinanceDataReader as fdr
import requests
import time

_cache = {"data": None, "ts": 0}
_TTL = 6 * 3600
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


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


def search_stocks(query: str, limit: int = 10) -> list[dict]:
    if not query:
        return []

    listing = _get_listing()
    q = query.strip()
    q_lower = q.lower()

    results = []
    codes_seen = set()

    # 1차: 로컬 KRX 리스팅 (공식명 기준, 대소문자 무시)
    for item in listing:
        name = item.get("Name", "")
        code = item.get("Code", "")
        if q_lower in name.lower() or q_lower in code.lower():
            results.append({"code": code, "name": name, "market": item.get("Market", "")})
            codes_seen.add(code)
        if len(results) >= limit:
            break

    # 2차: 결과가 부족하면 네이버 AC fallback (일반명 처리)
    if len(results) < limit:
        for item in _naver_ac(q, limit):
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
