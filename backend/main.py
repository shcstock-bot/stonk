import re
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from services.korean_stock import get_korean_stock
from services.us_stock import get_us_stock

app = FastAPI(title="EquiSynth API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

KR_TICKER_PATTERN = re.compile(r"^\d{6}$")


@app.get("/api/stock/{ticker}")
async def get_stock(ticker: str):
    ticker = ticker.strip().upper()
    if KR_TICKER_PATTERN.match(ticker):
        data = get_korean_stock(ticker)
    else:
        data = get_us_stock(ticker)

    if "error" in data:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content=data)
    return data


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import os, uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
