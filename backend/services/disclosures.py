import os
import time
from datetime import datetime, timedelta

import requests

DART_API_KEY = os.getenv("DART_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

_cache: dict = {}
_TTL = 3600

_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _corp_code(ticker: str) -> str | None:
    """ticker(6자리) → DART corp_code(8자리). 캐시된 dart 인스턴스 재사용."""
    try:
        from services.korean_stock import _get_dart_instance
        _, codes = _get_dart_instance()
        match = codes[codes["stock_code"] == ticker]
        if match.empty:
            return None
        return str(match.iloc[0]["corp_code"]).zfill(8)
    except Exception:
        return None


def _dart_list(corp_code: str, start: str, end: str) -> list[dict]:
    """DART REST API로 공시 목록 직접 조회."""
    try:
        r = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
                "bgn_de": start,
                "end_de": end,
                "page_no": 1,
                "page_count": 10,
            },
            headers=_HEADERS,
            timeout=10,
        )
        data = r.json()
        if data.get("status") != "000":
            return []
        return data.get("list", [])
    except Exception:
        return []


def get_disclosure_summary(ticker: str) -> dict:
    now = time.time()
    if ticker in _cache and now - _cache[ticker]["ts"] < _TTL:
        return _cache[ticker]["data"]

    if not DART_API_KEY:
        return {"items": [], "summary": "DART API 키가 설정되지 않았습니다."}

    corp_code = _corp_code(ticker)
    if not corp_code:
        return {"items": [], "summary": "종목 정보를 찾을 수 없습니다.", "corp_code": ""}

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=90)
    raw = _dart_list(corp_code, start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d"))

    if not raw:
        result = {"items": [], "summary": "최근 90일간 공시가 없습니다.", "corp_code": corp_code}
        _cache[ticker] = {"data": result, "ts": now}
        return result

    items = []
    for row in raw[:8]:
        d = str(row.get("rcept_dt", ""))
        date_fmt = f"{d[:4]}.{d[4:6]}.{d[6:]}" if len(d) == 8 else d
        items.append({
            "rcept_no": str(row.get("rcept_no", "")),
            "date": date_fmt,
            "title": str(row.get("report_nm", "")),
        })

    summary = ""
    if GROQ_API_KEY and items:
        try:
            from groq import Groq
            client = Groq(api_key=GROQ_API_KEY)
            titles = "\n".join(f"- {i['date']}: {i['title']}" for i in items)
            prompt = (
                f"다음은 {ticker} 종목의 최근 공시 목록입니다. "
                "투자자 관점에서 주요 내용을 2~3줄로 간결하게 요약해주세요. "
                "불필요한 서두 없이 핵심만 작성하세요.\n\n"
                f"{titles}"
            )
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
            )
            summary = resp.choices[0].message.content
        except Exception as e:
            msg = str(e)
            summary = "AI 요약을 잠시 후 다시 시도해주세요. (API 한도)" if "429" in msg else f"[오류: {msg[:80]}]"

    result = {"items": items, "summary": summary, "corp_code": corp_code}
    _cache[ticker] = {"data": result, "ts": now}
    return result
