from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
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

    # 배당수익률: dividendRate/price 우선, 없으면 dividendYield(소수) fallback
    div_rate  = _safe(info.get("dividendRate"))
    div_yield = _safe(info.get("dividendYield"))
    if div_rate not in ("N/A", None) and div_rate and price not in ("N/A", None) and price > 0:
        div = f"{(div_rate / price) * 100:.2f}%"
    elif div_yield not in ("N/A", None) and div_yield:
        div = f"{div_yield * 100:.2f}%"
    else:
        div = "N/A"

    # 베타
    beta_raw = _safe(info.get("beta"))
    beta = f"{beta_raw:.2f}" if beta_raw != "N/A" else "N/A"

    # 거래대금 (USD) = volume × price
    def _fmt_usd_vol(v: float) -> str:
        if v >= 1_000_000_000_000:
            return f"${v / 1_000_000_000_000:.2f}T"
        if v >= 1_000_000_000:
            return f"${v / 1_000_000_000:.2f}B"
        if v >= 1_000_000:
            return f"${v / 1_000_000:.2f}M"
        return f"${v:,.0f}"

    vol_cnt = _safe(info.get("regularMarketVolume"), None)
    avg_cnt = _safe(info.get("averageVolume"), None)
    price_num = _safe(info.get("currentPrice") or info.get("regularMarketPrice"), None)

    vol = _fmt_usd_vol(vol_cnt * price_num) if vol_cnt and price_num else "N/A"
    avgvol = _fmt_usd_vol(avg_cnt * price_num) if avg_cnt and price_num else "N/A"

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

    _now = datetime.now(KST)
    _hour = _now.strftime("%I").lstrip("0") or "12"
    asof = _now.strftime(f"%Y.%m.%d {_hour}:%M") + _now.strftime("%p").upper() + " 기준"

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
        "foreign": (lambda v: f"{v*100:.1f}%" if v not in ("N/A", None) else "N/A")(_safe(info.get("heldPercentInstitutions"))),
        "vol": vol,
        "avgvol": avgvol,
        "high52": high52,
        "low52": low52,
        "income": income,
    }
