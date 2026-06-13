# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**CheckStonk** — a stock research web app with a Korean/US stock lookup UI, AI-powered disclosure summaries, and a Telegram alert bot.

The frontend is a single static HTML page (`public/index.html`) served from the Python backend. The backend has two implementations:
- **`backend/main.py`** (FastAPI, Python) — the active production server. All features live here.
- **`backend/server.js`** (Express, Node.js) — a legacy/partial implementation; lacks disclosure, search, Telegram, and scheduler features.

**Always use and modify the Python backend.**

## Running the Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The frontend at `public/index.html` is served statically (open in browser directly or via any static server). It auto-detects `localhost`/`127.0.0.1` and points to `http://localhost:8000`; in production it hits `https://checkstonk.onrender.com`.

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in:

| Variable | Purpose |
|---|---|
| `DART_API_KEY` | Korean disclosures via [DART](https://opendart.fss.or.kr) |
| `GROQ_API_KEY` | AI summaries of disclosures |
| `TELEGRAM_BOT_TOKEN` | Telegram bot (`@CheckStonk_Bot`) |
| `TELEGRAM_WEBHOOK_URL` | Public URL for the Telegram webhook |

All features degrade gracefully when keys are absent.

## Architecture

### API Routes (`backend/main.py`)

| Endpoint | Description |
|---|---|
| `GET /api/stock/{ticker}` | Stock data; 6-digit number → Korean, otherwise US |
| `GET /api/search?q=` | Autocomplete; returns `[{code, name, market}]` |
| `GET /api/disclosures/{ticker}` | Recent disclosures (90 days) |
| `GET /api/disclosure-detail/{rcept_no}` | Fetches & AI-summarises a single disclosure |
| `POST /api/telegram/webhook` | Telegram bot webhook receiver |
| `GET /health` | Warmup endpoint |

### Data Sources

- **Korean stocks**: `pykrx` + `opendartreader` (price/financials), DART REST API (disclosures), Naver Finance (price for Telegram alerts)
- **US stocks**: `yfinance` (price, financials, income history), SEC EDGAR (disclosures)
- **AI summaries**: Groq API (`backend/services/disclosure_detail.py`)
- **Autocomplete**: `backend/services/search.py` uses a local KRX listing

### Telegram Bot (`backend/services/telegram_bot.py` + `scheduler.py`)

Bot commands: `/start`, `/add`, `/remove`, `/list`, `/report`, `/alerts`, `/disclosure`, `/report_toggle`, `/pricealert`, `/help`.

Scheduler (APScheduler, KST timezone):
- Disclosure check: weekdays 9–18h, every 30 min
- Market close report: weekdays 15:35
- Price spike/drop alerts (±5%): weekdays 9–15h, every 10 min

### Database (`backend/db.py`)

SQLite at `backend/checkstonk.db`. Tables: `users`, `watchlist`, `sent_disclosures`, `sent_price_alerts`, `user_prefs`. `init_db()` is called at FastAPI startup via the lifespan hook.

### Frontend (`public/index.html`)

Single-file app with vanilla JS + Tailwind CSS (CDN). Key JS functions:
- `startResearch()` — fetches stock data and calls `showResult()`
- `loadDisclosures(ticker)` — populates the AI disclosure sidebar
- `showDisclosureBubble(el)` — fetches AI summary on click
- Autocomplete with 250ms debounce against `/api/search`

Ticker routing: 6-digit strings → Korean; anything else → US. Korean input in hangul is resolved server-side to a ticker code.

## Korean vs US Differences

| Feature | Korean | US |
|---|---|---|
| Ticker format | 6-digit number (e.g. `005930`) | Alpha (e.g. `AAPL`) |
| Income statement | DART API (억 원) | Yahoo Finance `incomeStatementHistory` (millions USD) |
| Disclosures | DART REST API | SEC EDGAR full-text search |
| Price (Telegram) | Naver Finance mobile API | yfinance |
| Foreign ownership | Not yet implemented (returns `N/A`) | Not yet implemented |
