import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "checkstonk.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id   INTEGER PRIMARY KEY,
                username  TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER,
                ticker     TEXT,
                name       TEXT DEFAULT '',
                added_at   TEXT DEFAULT (datetime('now')),
                UNIQUE(chat_id, ticker)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_disclosures (
                ticker   TEXT,
                rcept_no TEXT,
                PRIMARY KEY (ticker, rcept_no)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_price_alerts (
                chat_id   INTEGER,
                ticker    TEXT,
                alert_date TEXT,
                PRIMARY KEY (chat_id, ticker, alert_date)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_prefs (
                chat_id          INTEGER PRIMARY KEY,
                disclosure_alert INTEGER DEFAULT 1,
                close_report     INTEGER DEFAULT 1,
                price_alert      INTEGER DEFAULT 1
            )
        """)
        conn.commit()


# ── 유저 ─────────────────────────────────────────
def add_user(chat_id: int, username: str = "", first_name: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (chat_id, username, first_name) VALUES (?,?,?)",
            (chat_id, username, first_name),
        )
        conn.commit()


def get_all_users() -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM users").fetchall()]


# ── 관심종목 ──────────────────────────────────────
def add_to_watchlist(chat_id: int, ticker: str, name: str = "") -> bool:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO watchlist (chat_id, ticker, name) VALUES (?,?,?)",
                (chat_id, ticker.upper(), name),
            )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_from_watchlist(chat_id: int, ticker: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM watchlist WHERE chat_id=? AND ticker=?",
            (chat_id, ticker.upper()),
        )
        conn.commit()
        return cur.rowcount > 0


def get_watchlist(chat_id: int) -> list:
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT ticker, name FROM watchlist WHERE chat_id=? ORDER BY added_at",
                (chat_id,),
            ).fetchall()
        ]


def get_all_watched_tickers() -> list[str]:
    with get_conn() as conn:
        return [r["ticker"] for r in conn.execute("SELECT DISTINCT ticker FROM watchlist").fetchall()]


def get_users_watching(ticker: str) -> list[int]:
    with get_conn() as conn:
        return [
            r["chat_id"]
            for r in conn.execute(
                "SELECT DISTINCT chat_id FROM watchlist WHERE ticker=?",
                (ticker.upper(),),
            ).fetchall()
        ]


# ── 공시 발송 이력 ────────────────────────────────
def is_disclosure_sent(ticker: str, rcept_no: str) -> bool:
    with get_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM sent_disclosures WHERE ticker=? AND rcept_no=?",
            (ticker, rcept_no),
        ).fetchone() is not None


def mark_disclosure_sent(ticker: str, rcept_no: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sent_disclosures (ticker, rcept_no) VALUES (?,?)",
            (ticker, rcept_no),
        )
        conn.commit()


# ── 급등락 알림 이력 (당일 1회) ──────────────────
def is_price_alert_sent(chat_id: int, ticker: str, today: str) -> bool:
    with get_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM sent_price_alerts WHERE chat_id=? AND ticker=? AND alert_date=?",
            (chat_id, ticker, today),
        ).fetchone() is not None


def mark_price_alert_sent(chat_id: int, ticker: str, today: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sent_price_alerts (chat_id, ticker, alert_date) VALUES (?,?,?)",
            (chat_id, ticker, today),
        )
        conn.commit()


# ── 유저 알림 설정 ────────────────────────────────
def get_prefs(chat_id: int) -> dict:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM user_prefs WHERE chat_id=?", (chat_id,)).fetchone()
        if r:
            return dict(r)
        return {"chat_id": chat_id, "disclosure_alert": 1, "close_report": 1, "price_alert": 1}


def ensure_prefs(chat_id: int):
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO user_prefs (chat_id) VALUES (?)", (chat_id,))
        conn.commit()


def toggle_pref(chat_id: int, key: str) -> bool:
    ensure_prefs(chat_id)
    with get_conn() as conn:
        cur = conn.execute(f"SELECT {key} FROM user_prefs WHERE chat_id=?", (chat_id,)).fetchone()
        new_val = 0 if cur[0] else 1
        conn.execute(f"UPDATE user_prefs SET {key}=? WHERE chat_id=?", (new_val, chat_id))
        conn.commit()
        return bool(new_val)
