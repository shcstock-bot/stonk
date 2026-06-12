import time
import requests

_HEADERS = {
    "User-Agent": "CheckStonk shcstock@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

_cik_cache: dict = {"data": None, "ts": 0}
_CIK_TTL = 24 * 3600

_cache: dict = {}
_TTL = 1800

_INCLUDE_FORMS = {"8-K", "10-K", "10-Q", "DEF 14A"}
_FORM_KR = {
    "8-K":     "수시공시",
    "10-K":    "연간보고서",
    "10-Q":    "분기보고서",
    "DEF 14A": "주주총회",
}


def _get_cik(ticker: str) -> str | None:
    now = time.time()
    if _cik_cache["data"] is None or now - _cik_cache["ts"] > _CIK_TTL:
        try:
            r = requests.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers=_HEADERS,
                timeout=10,
            )
            _cik_cache["data"] = r.json()
            _cik_cache["ts"] = now
        except Exception:
            return None

    for entry in (_cik_cache["data"] or {}).values():
        if entry.get("ticker", "").upper() == ticker.upper():
            return str(entry["cik_str"]).zfill(10)
    return None


def get_us_disclosure_summary(ticker: str) -> dict:
    now = time.time()
    if ticker in _cache and now - _cache[ticker]["ts"] < _TTL:
        return _cache[ticker]["data"]

    cik = _get_cik(ticker)
    if not cik:
        result = {"items": [], "summary": "", "corp_code": ""}
        _cache[ticker] = {"data": result, "ts": now}
        return result

    try:
        r = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=_HEADERS,
            timeout=10,
        )
        data = r.json()
    except Exception:
        result = {"items": [], "summary": "", "corp_code": cik}
        _cache[ticker] = {"data": result, "ts": now}
        return result

    recent       = data.get("filings", {}).get("recent", {})
    forms        = recent.get("form", [])
    dates        = recent.get("filingDate", [])
    descriptions = recent.get("primaryDocDescription", [])
    accessions   = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    items = []
    for i, form in enumerate(forms):
        if form not in _INCLUDE_FORMS:
            continue
        acc      = accessions[i]   if i < len(accessions)   else ""
        date_str = dates[i]        if i < len(dates)        else ""
        desc     = descriptions[i] if i < len(descriptions) else ""
        pdoc     = primary_docs[i] if i < len(primary_docs) else ""

        date_fmt = (
            f"{date_str[:4]}.{date_str[5:7]}.{date_str[8:]}"
            if len(date_str) >= 10 else date_str
        )
        label = _FORM_KR.get(form, form)
        title = f"[{label}] {desc}" if desc else f"[{label}]"

        items.append({
            "rcept_no":    acc,
            "date":        date_fmt,
            "title":       title,
            "cik":         cik.lstrip("0"),
            "primary_doc": pdoc,
        })
        if len(items) >= 8:
            break

    result = {"items": items, "summary": "", "corp_code": cik}
    _cache[ticker] = {"data": result, "ts": now}
    return result
