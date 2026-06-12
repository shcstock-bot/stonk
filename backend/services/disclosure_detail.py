import io
import os
import time
import zipfile

import requests
from bs4 import BeautifulSoup

DART_API_KEY = os.getenv("DART_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

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

    if not GROQ_API_KEY:
        return {"summary": "GROQ_API_KEY가 설정되지 않았습니다."}

    content_text = _fetch_dart_text(rcept_no)

    try:
        from groq import Groq

        if content_text:
            prompt = (
                f"DART 공시 문서 ({date} · {title}) 핵심을 3줄로 요약하세요. "
                "각 줄 '•'로 시작, 한 줄에 20자 이내, 서두 없이 바로.\n\n"
                f"{content_text}"
            )
        else:
            prompt = (
                f"DART 공시 '{title}' ({date}) 의 투자자 관점 의미를 3줄로 설명하세요. "
                "각 줄 '•'로 시작, 한 줄에 20자 이내, 서두 없이 바로."
            )

        client = Groq(api_key=GROQ_API_KEY)
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
        )
        summary = resp.choices[0].message.content.strip()
    except Exception as e:
        msg = str(e)
        if "429" in msg:
            return {"summary": "잠시 후 다시 클릭해주세요. (API 한도)"}  # 429는 캐시 안 함
        summary = f"오류: {msg[:120]}"

    result = {"summary": summary}
    _cache[rcept_no] = {"data": result, "ts": time.time()}
    return result
