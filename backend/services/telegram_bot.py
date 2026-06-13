import os
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

_ON  = "✅ 켜짐"
_OFF = "❌ 꺼짐"


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


def _prefs_text(prefs: dict) -> str:
    d = _ON if prefs["disclosure_alert"] else _OFF
    c = _ON if prefs["close_report"]     else _OFF
    p = _ON if prefs["price_alert"]      else _OFF
    return (
        f"🔔 <b>알림 설정 현황</b>\n\n"
        f"📢 공시 알림 + AI 요약  {d}\n"
        f"   /disclosure — 켜기/끄기\n\n"
        f"📊 장 마감 리포트  {c}\n"
        f"   /report_toggle — 켜기/끄기\n\n"
        f"🚀 급등·급락 알림 (±5%)  {p}\n"
        f"   /pricealert — 켜기/끄기"
    )


def handle_update(update: dict):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat_id    = msg["chat"]["id"]
    text       = msg.get("text", "").strip()
    username   = msg.get("from", {}).get("username", "")
    first_name = msg.get("from", {}).get("first_name", "")

    import db
    db.add_user(chat_id, username, first_name)
    db.ensure_prefs(chat_id)

    if not text:
        return

    # ── /start ────────────────────────────────────
    if text.startswith("/start"):
        send(chat_id, (
            "👋 <b>CheckStonk 알림봇</b>에 오신 걸 환영합니다!\n\n"
            "📌 <b>종목 관리</b>\n"
            "/add 삼성전자  — 관심 종목 추가 (국내·해외 모두 가능)\n"
            "/remove 005930  — 종목 삭제\n"
            "/list  — 관심 종목 목록\n"
            "/report  — 즉시 현황 리포트\n\n"
            "🔔 <b>알림 설정</b>\n"
            "/alerts  — 알림 설정 확인 및 켜기/끄기\n\n"
            "/help  — 전체 도움말"
        ))

    # ── /add ─────────────────────────────────────
    elif text.startswith("/add"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "사용법: /add 삼성전자  또는  /add NVDA")
            return
        _handle_add(chat_id, parts[1].strip())

    # ── /remove /del ──────────────────────────────
    elif text.startswith("/remove") or text.startswith("/del"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "사용법: /remove 삼성전자  또는  /remove 005930")
            return
        _handle_remove(chat_id, parts[1].strip())

    # ── /list ────────────────────────────────────
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

    # ── /report (즉시 리포트) ─────────────────────
    elif text.startswith("/report") and not text.startswith("/report_toggle"):
        send(chat_id, "⏳ 리포트 생성 중...")
        from services.scheduler import send_report_to_user
        send_report_to_user(chat_id)

    # ── /alerts (알림 설정 현황) ───────────────────
    elif text.startswith("/alerts"):
        prefs = db.get_prefs(chat_id)
        send(chat_id, _prefs_text(prefs))

    # ── /disclosure (공시 알림 토글) ──────────────
    elif text.startswith("/disclosure"):
        on = db.toggle_pref(chat_id, "disclosure_alert")
        send(chat_id, f"📢 공시 알림 + AI 요약: {'✅ 켜짐' if on else '❌ 꺼짐'}")

    # ── /report_toggle (마감 리포트 토글) ────────
    elif text.startswith("/report_toggle"):
        on = db.toggle_pref(chat_id, "close_report")
        send(chat_id, f"📊 장 마감 리포트: {'✅ 켜짐' if on else '❌ 꺼짐'}")

    # ── /pricealert (급등락 알림 토글) ───────────
    elif text.startswith("/pricealert"):
        on = db.toggle_pref(chat_id, "price_alert")
        send(chat_id, f"🚀 급등·급락 알림: {'✅ 켜짐' if on else '❌ 꺼짐'}")

    # ── /help ────────────────────────────────────
    elif text.startswith("/help"):
        send(chat_id, (
            "📌 <b>전체 명령어</b>\n\n"
            "<b>종목 관리</b>\n"
            "/add [종목명 또는 티커]  — 관심 종목 추가\n"
            "/remove [종목명 또는 티커]  — 관심 종목 삭제\n"
            "/list  — 관심 종목 전체 보기\n"
            "/report  — 즉시 현황 리포트\n\n"
            "<b>알림 설정</b>\n"
            "/alerts  — 알림 설정 확인\n"
            "/disclosure  — 공시 알림 켜기/끄기\n"
            "/report_toggle  — 장 마감 리포트 켜기/끄기\n"
            "/pricealert  — 급등·급락 알림 켜기/끄기\n\n"
            "<b>알림 기준</b>\n"
            "• 공시: 평일 30분마다 자동 확인\n"
            "• 마감: 매일 오후 3:35\n"
            "• 급등락: ±5% 초과 시 당일 1회"
        ))

    else:
        send(chat_id, "명령어를 인식하지 못했습니다. /help 를 입력해보세요.")


def _handle_remove(chat_id: int, query: str):
    from services.search import search_stocks
    import db

    results = search_stocks(query, limit=1)
    if results:
        ticker = results[0]["code"]
        name   = results[0]["name"]
    else:
        ticker = query.upper()
        name   = ""

    if db.remove_from_watchlist(chat_id, ticker):
        label = f"<b>{name}</b> ({ticker})" if name else f"<b>{ticker}</b>"
        send(chat_id, f"✅ {label} 관심 종목에서 삭제했습니다.")
    else:
        label = f"<b>{name}</b> ({ticker})" if name else f"<b>{ticker}</b>"
        send(chat_id, f"❌ {label} 은 등록된 종목이 아닙니다.")


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
