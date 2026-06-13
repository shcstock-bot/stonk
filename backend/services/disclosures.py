import re
import time

import requests
from bs4 import BeautifulSoup

_cache: dict = {}
_TTL = 3600

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.naver.com/",
}


def _naver_disclosures(ticker: str) -> list[dict]:
    """네이버 금융 공시 탭을 직접 파싱 — 사용자가 보는 목록과 동일."""
    try:
        r = requests.get(
            "https://finance.naver.com/item/news_notice.naver",
            params={"code": ticker, "page": 1},
            headers=_HEADERS,
            timeout=10,
        )
        # 네이버 금융은 EUC-KR 인코딩
        r.encoding = "euc-kr"
        soup = BeautifulSoup(r.text, "lxml")

        table = soup.find("table", class_="type2")
        if not table:
            return []

        items = []
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue

            a = tds[0].find("a")
            if not a:
                continue

            title  = a.get_text(strip=True)
            href   = a.get("href", "")

            # href 예: /item/news_notice_detail.naver?code=005930&rcpNo=20250315001234&...
            m = re.search(r"rcpNo=(\d+)", href)
            rcept_no = m.group(1) if m else ""

            # 접수일자는 마지막 td
            date_raw = tds[-1].get_text(strip=True)
            date = date_raw.split()[0] if date_raw else ""  # "2025.03.15 09:30" → "2025.03.15"

            if not title or not rcept_no:
                continue

            items.append({"rcept_no": rcept_no, "date": date, "title": title})
            if len(items) >= 8:
                break

        return items
    except Exception:
        return []


def get_disclosure_summary(ticker: str) -> dict:
    now = time.time()
    if ticker in _cache and now - _cache[ticker]["ts"] < _TTL:
        return _cache[ticker]["data"]

    items  = _naver_disclosures(ticker)
    result = {"items": items, "corp_code": ticker}
    _cache[ticker] = {"data": result, "ts": now}
    return result
