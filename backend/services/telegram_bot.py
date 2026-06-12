import os
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send(chat_id: int, text: str):
    if not BOT_TOKEN:
        return
    try:
        requests.post(
            f"{_API}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception:
        pass


def set_webhook(url: str):
    if not BOT_TOKEN:
        return
    try:
        requests.post(f"{_API}/setWebhook", json={"url": url}, timeout=10)
    except Exception:
        pass


def handle_update(update: dict):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat_id   = msg["chat"]["id"]
    text      = msg.get("text", "").strip()
    username  = msg.get("from", {}).get("username", "")
    first_name = msg.get("from", {}).get("first_name", "")

    import db
    db.add_user(chat_id, username, first_name)

    if not text:
        return

    if text.startswith("/start"):
        send(chat_id, (
            "👋 <b>CheckStonk 알림봇</b>에 오신 걸 환영합니다!\n\n"
            "📌 <b>명령어</b>\n"
            "/add 삼성전자  — 관심 종목 추가\n"
            "/add AAPL  — 미국 주식 추가\n"
            "/remove 005930  — 종목 삭제\n"
            "/list  — 관심 종목 목록\n"
            "/report  — 즉시 현황 리포트\n"
            "/help  — 도움말\n\n"
            "🔔 공시 알림, 장 마감 리포트, 급등·급락 알림을 자동으로 받아보세요!"
        ))

    elif text.startswith("/add"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "사용법: /add 삼성전자  또는  /add 005930")
            return
        _handle_add(chat_id, parts[1].strip())

    elif text.startswith("/remove") or text.startswith("/del"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "사용법: /remove 005930")
            return
        ticker = parts[1].strip().upper()
        if db.remove_from_watchlist(chat_id, ticker):
            send(chat_id, f"✅ <b>{ticker}</b> 관심 종목에서 삭제했습니다.")
        else:
            send(chat_id, f"❌ <b>{ticker}</b> 은 등록된 종목이 아닙니다.")

    elif text.startswith("/list"):
        watchlist = db.get_watchlist(chat_id)
        if not watchlist:
            send(chat_id, "등록된 관심 종목이 없습니다.\n/add 삼성전자 로 추가해보세요.")
        else:
            items = "\n".join(
                f"• <b>{w['name']}</b> ({w['ticker']})" if w["name"] else f"• <b>{w['ticker']}</b>"
                for w in watchlist
            )
            send(chat_id, f"📋 <b>관심 종목 {len(watchlist)}개</b>\n{items}")

    elif text.startswith("/report"):
        send(chat_id, "⏳ 리포트 생성 중...")
        from services.scheduler import send_report_to_user
        send_report_to_user(chat_id)

    elif text.startswith("/help"):
        send(chat_id, (
            "📌 <b>명령어 도움말</b>\n\n"
            "/add [종목명 또는 티커]  — 관심 종목 추가\n"
            "/remove [티커]  — 관심 종목 삭제\n"
            "/list  — 관심 종목 전체 보기\n"
            "/report  — 즉시 현황 리포트\n\n"
            "🔔 <b>자동 알림 종류</b>\n"
            "• 새 공시 발생 시 AI 3줄 요약 전송\n"
            "• 매일 오후 3:35 장 마감 리포트\n"
            "• 등락률 ±5% 초과 시 급등·급락 알림 (당일 1회)"
        ))

    else:
        send(chat_id, "명령어를 인식하지 못했습니다. /help 를 입력해보세요.")


def _handle_add(chat_id: int, query: str):
    from services.search import search_stocks
    import db

    results = search_stocks(query, limit=1)
    if results:
        ticker = results[0]["code"]
        name   = results[0]["name"]
    else:
        ticker = query.upper()
        name   = ""

    added = db.add_to_watchlist(chat_id, ticker, name)
    label = f"<b>{name}</b> ({ticker})" if name else f"<b>{ticker}</b>"
    if added:
        send(chat_id, f"✅ {label} 관심 종목에 추가했습니다.")
    else:
        send(chat_id, f"이미 등록된 종목입니다: {label}")
