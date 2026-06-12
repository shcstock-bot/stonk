from datetime import datetime
import yfinance as yf


def _safe(val, fallback="N/A"):
    try:
        if val is None or (isinstance(val, float) and val != val):
            return fallback
        return val
    except Exception:
        return fallback


def _fmt_large(val: float) -> str:
    if val >= 1_000_000_000_000:
        return f"${val / 1_000_000_000_000:.2f}T"
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.2f}B"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.2f}M"
    return f"${val:,.0f}"


def get_us_stock(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.info
        if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
            return {"error": f"'{ticker}' 종목 데이터를 찾을 수 없습니다."}
    except Exception:
        return {"error": f"'{ticker}' 조회 중 오류가 발생했습니다."}

    price = _safe(info.get("currentPrice") or info.get("regularMarketPrice"))
    prev_close = _safe(info.get("previousClose") or info.get("regularMarketPreviousClose"))

    if price != "N/A" and prev_close != "N/A":
        change_val = price - prev_close
        change_pct = (change_val / prev_close * 100) if prev_close else 0
        price_str = f"${price:,.2f}"
        change_str = f"{'+' if change_val >= 0 else ''}${change_val:,.2f} ({'+' if change_pct >= 0 else ''}{change_pct:.2f}%)"
        pos = change_val >= 0
    else:
        price_str, change_str, pos = "N/A", "N/A", True

    # 시가총액
    mktcap_raw = _safe(info.get("marketCap"))
    mktcap = _fmt_large(mktcap_raw) if mktcap_raw != "N/A" else "N/A"

    # EPS
    eps_raw = _safe(info.get("trailingEps"))
    eps = f"${eps_raw:.2f}" if eps_raw != "N/A" else "N/A"

    # PER, PBR
    per_raw = _safe(info.get("trailingPE"))
    per = f"{per_raw:.1f}x" if per_raw != "N/A" else "N/A"
    pbr_raw = _safe(info.get("priceToBook"))
    pbr = f"{pbr_raw:.1f}x" if pbr_raw != "N/A" else "N/A"

    # ROE
    roe_raw = _safe(info.get("returnOnEquity"))
    roe = f"{roe_raw * 100:.1f}%" if roe_raw != "N/A" else "N/A"

    # 부채비율
    debt_raw = _safe(info.get("debtToEquity"))
    debt = f"{debt_raw:.1f}%" if debt_raw != "N/A" else "N/A"

    # EV/EBITDA
    evebitda_raw = _safe(info.get("enterpriseToEbitda"))
    evebitda = f"{evebitda_raw:.1f}x" if evebitda_raw != "N/A" else "N/A"

    # 배당수익률
    # 배당수익률: dividendRate / price 로 직접 계산 (dividendYield 필드는 부정확)
    div_rate = _safe(info.get("dividendRate"))
    if div_rate != "N/A" and price != "N/A" and price > 0:
        div = f"{(div_rate / price) * 100:.2f}%"
    else:
        div = "N/A"

    # 베타
    beta_raw = _safe(info.get("beta"))
    beta = f"{beta_raw:.2f}" if beta_raw != "N/A" else "N/A"

    # 거래량
    vol = str(_safe(info.get("regularMarketVolume"), 0))
    avgvol = str(_safe(info.get("averageVolume"), 0))

    # 52주 고/저
    high52_raw = _safe(info.get("fiftyTwoWeekHigh"))
    low52_raw = _safe(info.get("fiftyTwoWeekLow"))
    high52 = f"${high52_raw:,.2f}" if high52_raw != "N/A" else "N/A"
    low52 = f"${low52_raw:,.2f}" if low52_raw != "N/A" else "N/A"

    # 3년 손익 (yfinance income_stmt)
    income = []
    try:
        stmt = t.income_stmt
        if stmt is not None and not stmt.empty:
            cols = stmt.columns[:3]  # 최근 3개 연도
            for col in reversed(cols):
                year_label = col.strftime("%Y") if hasattr(col, "strftime") else str(col)[:4]
                rev = int(_safe(stmt.loc["Total Revenue", col], 0)) if "Total Revenue" in stmt.index else 0
                op = int(_safe(stmt.loc["Operating Income", col], 0)) if "Operating Income" in stmt.index else 0
                net = int(_safe(stmt.loc["Net Income", col], 0)) if "Net Income" in stmt.index else 0
                # 백만 달러 단위로 변환
                income.append({"year": year_label, "rev": rev // 1_000_000, "op": op // 1_000_000, "net": net // 1_000_000})
    except Exception:
        pass

    asof_ts = info.get("regularMarketTime")
    if asof_ts:
        asof = datetime.fromtimestamp(asof_ts).strftime("As of %b %d, %Y close")
    else:
        asof = f"As of {datetime.now().strftime('%b %d, %Y')}"

    return {
        "ticker": ticker,
        "name": _safe(info.get("longName") or info.get("shortName"), ticker),
        "sector": _safe(info.get("sector") or info.get("industry"), "N/A"),
        "price": price_str,
        "change": change_str,
        "pos": pos,
        "asof": asof,
        "per": per,
        "pbr": pbr,
        "eps": eps,
        "mktcap": mktcap,
        "roe": roe,
        "debt": debt,
        "evebitda": evebitda,
        "div": div,
        "beta": beta,
        "foreign": "N/A",
        "vol": vol,
        "avgvol": avgvol,
        "high52": high52,
        "low52": low52,
        "income": income,
    }
