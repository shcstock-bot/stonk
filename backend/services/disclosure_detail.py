import io
import os
import time
import zipfile

import requests
from bs4 import BeautifulSoup

DART_API_KEY = os.getenv("DART_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

_cache: dict = {}
_TTL = 3600

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _fetch_dart_text(rcept_no: str) -> str:
    """DART 문서 ZIP 에서 본문 텍스트 추출. 실패 시 빈 문자열."""
    if not DART_API_KEY:
        return ""
    try:
        url = (
            "https://opendart.fss.or.kr/api/document.xml"
            f"?crtfc_key={DART_API_KEY}&rcept_no={rcept_no}"
        )
        r = requests.get(url, headers=_HEADERS, timeout=6)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        # 가장 큰 파일 = 본문
        names = sorted(z.namelist(), key=lambda n: z.getinfo(n).file_size, reverse=True)
        for name in names:
            if any(name.lower().endswith(ext) for ext in (".xml", ".html", ".htm")):
                raw = z.read(name).decode("utf-8", errors="ignore")
                text = BeautifulSoup(raw, "lxml").get_text(" ", strip=True)
                return text[:2500]
    except Exception:
        pass
    return ""


def get_disclosure_detail_summary(rcept_no: str, title: str = "", date: str = "") -> dict:
    if rcept_no in _cache and time.time() - _cache[rcept_no]["ts"] < _TTL:
        return _cache[rcept_no]["data"]

    if not GEMINI_API_KEY:
        return {"summary": "Gemini API 키가 설정되지 않았습니다."}

    content_text = _fetch_dart_text(rcept_no)

    try:
        from google import genai as _genai

        client = _genai.Client(api_key=GEMINI_API_KEY)

        if content_text:
            prompt = (
                f"다음은 한국 상장기업의 DART 공시 문서입니다 ({date} · {title}).\n"
                "투자자가 꼭 알아야 할 핵심을 정확히 3줄로 요약하세요. "
                "각 줄은 '•' 으로 시작하고 줄바꿈으로 구분하세요. 서두 없이 바로 시작하세요.\n\n"
                f"{content_text}"
            )
        else:
            prompt = (
                f"한국 DART 공시 '{title}' ({date}) 가 투자자에게 의미하는 바를 "
                "정확히 3줄로 설명하세요. "
                "각 줄은 '•' 으로 시작하고 줄바꿈으로 구분하세요. 서두 없이 바로 시작하세요."
            )

        summary = client.models.generate_content(model="gemini-1.5-flash", contents=prompt).text.strip()
    except Exception as e:
        summary = f"오류: {type(e).__name__}: {str(e)[:120]}"

    result = {"summary": summary}
    _cache[rcept_no] = {"data": result, "ts": time.time()}
    return result
