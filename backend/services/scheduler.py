import re
import requests
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
KR_PAT = re.compile(r"^\d{6}$")
_KR_HEADERS = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15"}


def _fetch_price(ticker: str) -> dict | None:
    try:
        if KR_PAT.match(ticker):
            r = requests.get(
                f"https://m.stock.naver.com/api/stock/{ticker}/basic",
                headers=_KR_HEADERS, timeout=5,
            )
            d = r.json()
            price_raw = d.get("closePrice", "").replace(",", "")
            ratio_raw = d.get("fluctuationsRatio", "0")
            direction = d.get("compareToPreviousPrice", {}).get("code", "3")
            pos = direction in ("1", "2")
            return {
                "ticker": ticker,
                "name":   d.get("stockName", ticker),
                "price":  f"{int(price_raw):,}원" if price_raw.isdigit() else price_raw + "원",
                "ratio":  float(ratio_raw) * (1 if pos else -1),
                "pos":    pos,
            }
        else:
            import yfinance as yf
            info = yf.Ticker(ticker).info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            prev  = info.get("previousClose")
            ratio = (price - prev) / prev * 100 if price and prev else 0.0
            return {
                "ticker": ticker,
                "name":   info.get("shortName", ticker),
                "price":  f"${price:,.2f}" if price else "N/A",
                "ratio":  ratio,
                "pos":    ratio >= 0,
            }
    except Exception:
        return None


# ── 1. 공시 확인 ──────────────────────────────────
def check_disclosures():
    import db
    from services.telegram_bot import send
    from services.disclosure_detail import get_disclosure_detail_summary

    tickers = db.get_all_watched_tickers()
    for ticker in tickers:
        try:
            if KR_PAT.match(ticker):
                from services.disclosures import get_disclosure_summary
                data = get_disclosure_summary(ticker)
            else:
                from services.us_disclosures import get_us_disclosure_summary
                data = get_us_disclosure_summary(ticker)

            for item in data.get("items", [])[:3]:
                rcept_no = item["rcept_no"]
                if db.is_disclosure_sent(ticker, rcept_no):
                    continue

                cik  = item.get("cik", "")
                pdoc = item.get("primary_doc", "")
                ai   = get_disclosure_detail_summary(rcept_no, item["title"], item["date"], cik=cik, primary_doc=pdoc)
                summary = ai.get("summary", "")

                msg = (
                    f"📢 <b>새 공시 알림</b>\n"
                    f"<b>{ticker}</b>  {item['date']}\n"
                    f"{item['title']}"
                )
                if summary:
                    msg += f"\n\n<b>AI 요약</b>\n{summary}"

                for chat_id in db.get_users_watching(ticker):
                    if db.get_prefs(chat_id).get("disclosure_alert", 1):
                        send(chat_id, msg)

                db.mark_disclosure_sent(ticker, rcept_no)
        except Exception:
            pass


# ── 2. 장 마감 리포트 ──────────────────────────────
def send_market_close_report():
    import db
    for user in db.get_all_users():
        if db.get_prefs(user["chat_id"]).get("close_report", 1):
            send_report_to_user(user["chat_id"])


def send_report_to_user(chat_id: int):
    import db
    from services.telegram_bot import send

    watchlist = db.get_watchlist(chat_id)
    if not watchlist:
        send(chat_id, "관심 종목이 없습니다. /add 종목명 으로 추가해보세요.")
        return

    now_str = datetime.now(KST).strftime("%Y.%m.%d %I:%M%p").replace("AM", "AM").replace("PM", "PM")
    lines = [f"📊 <b>리포트</b> ({now_str} 기준)\n"]

    for w in watchlist:
        d = _fetch_price(w["ticker"])
        if d:
            icon = "🔴" if not d["pos"] else "🟢"
            sign = "+" if d["pos"] else ""
            lines.append(f"{icon} <b>{d['name']}</b> ({w['ticker']})\n   {d['price']}  {sign}{d['ratio']:.2f}%")
        else:
            lines.append(f"• <b>{w['ticker']}</b>  —  조회 실패")

    send(chat_id, "\n".join(lines))


# ── 3. 급등·급락 알림 ──────────────────────────────
def check_price_alerts():
    import db

    THRESHOLD = 5.0
    today = datetime.now(KST).strftime("%Y-%m-%d")

    for ticker in db.get_all_watched_tickers():
        d = _fetch_price(ticker)
        if not d or abs(d["ratio"]) < THRESHOLD:
            continue

        from services.telegram_bot import send
        direction = "🚀 급등" if d["pos"] else "📉 급락"
        sign = "+" if d["pos"] else ""
        msg = (
            f"{direction} 알림!\n"
            f"<b>{d['name']}</b> ({ticker})\n"
            f"{d['price']}  ({sign}{d['ratio']:.2f}%)"
        )

        for chat_id in db.get_users_watching(ticker):
            if not db.get_prefs(chat_id).get("price_alert", 1):
                continue
            if db.is_price_alert_sent(chat_id, ticker, today):
                continue
            send(chat_id, msg)
            db.mark_price_alert_sent(chat_id, ticker, today)


# ── 스케줄러 시작 ─────────────────────────────────
def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler(timezone="Asia/Seoul")

    # 공시 확인: 평일 9~18시, 30분마다
    scheduler.add_job(
        check_disclosures,
        CronTrigger(day_of_week="mon-fri", hour="9-18", minute="0,30", timezone="Asia/Seoul"),
        id="disclosure_check", replace_existing=True,
    )

    # 장 마감 리포트: 평일 15:35
    scheduler.add_job(
        send_market_close_report,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=35, timezone="Asia/Seoul"),
        id="market_close_report", replace_existing=True,
    )

    # 급등·급락: 평일 9~15시, 10분마다
    scheduler.add_job(
        check_price_alerts,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/10", timezone="Asia/Seoul"),
        id="price_alerts", replace_existing=True,
    )

    scheduler.start()
    return scheduler
