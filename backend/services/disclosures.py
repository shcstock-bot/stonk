import os
import time
from datetime import datetime, timedelta

DART_API_KEY = os.getenv("DART_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

_cache: dict = {}
_TTL = 3600  # 1시간


def get_disclosure_summary(ticker: str) -> dict:
    now = time.time()
    if ticker in _cache and now - _cache[ticker]["ts"] < _TTL:
        return _cache[ticker]["data"]

    if not DART_API_KEY:
        return {"items": [], "summary": "DART API 키가 설정되지 않았습니다."}

    try:
        from services.korean_stock import _get_dart_instance
        dart, codes = _get_dart_instance()
        match = codes[codes["stock_code"] == ticker]
        if match.empty:
            return {"items": [], "summary": "종목 정보를 찾을 수 없습니다."}

        corp_code = str(match.iloc[0]["corp_code"]).zfill(8)
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=90)

        disc = dart.list(
            corp_code,
            start=start_dt.strftime("%Y%m%d"),
            end=end_dt.strftime("%Y%m%d"),
        )
    except Exception as e:
        return {"items": [], "summary": f"공시 조회 실패 ({str(e)[:40]})"}

    if disc is None or disc.empty:
        result = {"items": [], "summary": "최근 90일간 공시가 없습니다."}
        _cache[ticker] = {"data": result, "ts": now}
        return result

    items = [
        {
            "rcept_no": str(row.get("rcept_no", "")),
            "date": str(row.get("rcept_dt", ""))[:8],
            "title": str(row.get("report_nm", "")),
        }
        for _, row in disc.head(8).iterrows()
    ]

    # 날짜 포맷: 20250612 → 2025.06.12
    for item in items:
        d = item["date"]
        if len(d) == 8:
            item["date"] = f"{d[:4]}.{d[4:6]}.{d[6:]}"

    summary = ""
    if GEMINI_API_KEY and items:
        try:
            from google import genai as _genai
            client = _genai.Client(api_key=GEMINI_API_KEY)
            titles = "\n".join(f"- {i['date']}: {i['title']}" for i in items)
            prompt = (
                f"다음은 {ticker} 종목의 최근 공시 목록입니다. "
                "투자자 관점에서 주요 내용을 2~3줄로 간결하게 요약해주세요. "
                "불필요한 서두 없이 핵심만 작성하세요.\n\n"
                f"{titles}"
            )
            resp = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            summary = resp.text
        except Exception as e:
            summary = f"[오류: {type(e).__name__}: {str(e)[:80]}]"

    result = {"items": items, "summary": summary, "corp_code": corp_code}
    _cache[ticker] = {"data": result, "ts": now}
    return result
