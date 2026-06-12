import re
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from services.korean_stock import get_korean_stock
from services.us_stock import get_us_stock
from services.search import search_stocks, name_to_code

app = FastAPI(title="CheckStonk API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

KR_TICKER_PATTERN = re.compile(r"^\d{6}$")
KR_NAME_PATTERN   = re.compile(r"[가-힣]")


@app.get("/api/search")
async def search(q: str = Query(default="")):
    if len(q) < 1:
        return []
    return search_stocks(q, limit=10)


@app.get("/api/stock/{ticker}")
async def get_stock(ticker: str):
    ticker = ticker.strip()

    # 한글 이름 입력 → 코드로 변환
    if KR_NAME_PATTERN.search(ticker):
        code = name_to_code(ticker)
        if not code:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"error": f"'{ticker}' 종목을 찾을 수 없습니다."})
        ticker = code

    ticker = ticker.upper()

    if KR_TICKER_PATTERN.match(ticker):
        data = get_korean_stock(ticker)
    else:
        data = get_us_stock(ticker)

    if "error" in data:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content=data)
    return data


@app.get("/api/disclosure-detail/{rcept_no}")
async def get_disclosure_detail(
    rcept_no: str,
    title: str = Query(default=""),
    date: str = Query(default=""),
    cik: str = Query(default=""),
    primary_doc: str = Query(default=""),
):
    from services.disclosure_detail import get_disclosure_detail_summary
    return get_disclosure_detail_summary(rcept_no, title, date, cik=cik, primary_doc=primary_doc)


@app.get("/api/disclosures/{ticker}")
async def get_disclosures(ticker: str):
    if KR_TICKER_PATTERN.match(ticker):
        from services.disclosures import get_disclosure_summary
        return get_disclosure_summary(ticker)
    else:
        from services.us_disclosures import get_us_disclosure_summary
        return get_us_disclosure_summary(ticker)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import os, uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
