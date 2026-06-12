import FinanceDataReader as fdr
import time

_cache = {"data": None, "ts": 0}
_TTL = 6 * 3600


def _get_listing():
    now = time.time()
    if _cache["data"] is None or now - _cache["ts"] > _TTL:
        df = fdr.StockListing("KRX")
        _cache["data"] = df[["Code", "Name", "Market"]].to_dict("records")
        _cache["ts"] = now
    return _cache["data"]


def search_stocks(query: str, limit: int = 10) -> list[dict]:
    if not query:
        return []
    listing = _get_listing()
    q = query.strip()
    results = []
    for item in listing:
        name = item.get("Name", "")
        code = item.get("Code", "")
        if q in name or q in code:
            results.append({"code": code, "name": name, "market": item.get("Market", "")})
        if len(results) >= limit:
            break
    return results


def name_to_code(name: str) -> str | None:
    listing = _get_listing()
    for item in listing:
        if item.get("Name", "") == name:
            return item.get("Code")
    return None
