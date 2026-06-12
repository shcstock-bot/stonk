import io
import os
import re
import time
import zipfile

import requests
from bs4 import BeautifulSoup

DART_API_KEY = os.getenv("DART_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

_cache: dict = {}
_TTL = 3600

_DART_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_SEC_HEADERS  = {"User-Agent": "CheckStonk shcstock@gmail.com", "Accept-Encoding": "gzip, deflate"}

_SEC_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def _is_sec(rcept_no: str) -> bool:
    return bool(_SEC_RE.match(rcept_no))


def _fetch_dart_text(rcept_no: str) -> str:
    if not DART_API_KEY:
        return ""
    try:
        url = (
            "https://opendart.fss.or.kr/api/document.xml"
            f"?crtfc_key={DART_API_KEY}&rcept_no={rcept_no}"
        )
        r = requests.get(url, headers=_DART_HEADERS, timeout=6)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = sorted(z.namelist(), key=lambda n: z.getinfo(n).file_size, reverse=True)
        for name in names:
            if any(name.lower().endswith(ext) for ext in (".xml", ".html", ".htm")):
                raw = z.read(name).decode("utf-8", errors="ignore")
                text = BeautifulSoup(raw, "lxml").get_text(" ", strip=True)
                return text[:2500]
    except Exception:
        pass
    return ""


def _fetch_sec_text(rcept_no: str, cik: str, primary_doc: str) -> str:
    try:
        acc_clean = rcept_no.replace("-", "")
        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{primary_doc}"
        r = requests.get(doc_url, headers=_SEC_HEADERS, timeout=8)
        text = BeautifulSoup(r.content, "lxml").get_text(" ", strip=True)
        return text[:3000]
    except Exception:
        pass
    return ""


def get_disclosure_detail_summary(
    rcept_no: str,
    title: str = "",
    date: str = "",
    cik: str = "",
    primary_doc: str = "",
) -> dict:
    if rcept_no in _cache and time.time() - _cache[rcept_no]["ts"] < _TTL:
        return _cache[rcept_no]["data"]

    if not GROQ_API_KEY:
        return {"summary": "GROQ_API_KEY가 설정되지 않았습니다."}

    sec = _is_sec(rcept_no)

    if sec:
        content_text = _fetch_sec_text(rcept_no, cik, primary_doc) if cik and primary_doc else ""
        guidelines = (
            "작성 규칙: "
            "① 반드시 한국어로 작성할 것 "
            "② 회사명은 절대 언급하지 말 것 "
            "③ 각 줄은 '•'로 시작, 한 줄 20자 이내 "
            "④ 서두 없이 바로 핵심만"
        )
        if content_text:
            prompt = (
                f"SEC 공시 문서 ({date} · {title}) 핵심을 한국어로 3줄 요약하세요.\n"
                f"{guidelines}\n\n{content_text}"
            )
        else:
            prompt = (
                f"SEC 공시 '{title}' ({date}) 의 투자자 관점 의미를 한국어로 3줄 설명하세요.\n"
                f"{guidelines}"
            )
    else:
        content_text = _fetch_dart_text(rcept_no)
        guidelines = (
            "작성 규칙: "
            "① 회사명은 절대 언급하지 말 것 "
            "② 인명은 한글 이름만 사용 (한자·영문 표기 제거, 예: 朴泰勳·PARKTAEHOON → 박태훈) "
            "③ 각 줄은 '•'로 시작, 한 줄 20자 이내 "
            "④ 서두 없이 바로 핵심만"
        )
        if content_text:
            prompt = (
                f"DART 공시 문서 ({date} · {title}) 핵심을 3줄로 요약하세요.\n"
                f"{guidelines}\n\n{content_text}"
            )
        else:
            prompt = (
                f"DART 공시 '{title}' ({date}) 의 투자자 관점 의미를 3줄로 설명하세요.\n"
                f"{guidelines}"
            )

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
        )
        summary = resp.choices[0].message.content.strip()
    except Exception as e:
        msg = str(e)
        if "429" in msg:
            return {"summary": "잠시 후 다시 클릭해주세요. (API 한도)"}
        summary = f"오류: {msg[:120]}"

    result = {"summary": summary}
    _cache[rcept_no] = {"data": result, "ts": time.time()}
    return result
