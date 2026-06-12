import yahooFinance from 'yahoo-finance2';

function safe(val, fallback = 'N/A') {
    if (val == null || (typeof val === 'number' && isNaN(val))) return fallback;
    return val;
}

function fmtLargeUsd(val) {
    if (val == null || isNaN(val)) return 'N/A';
    if (val >= 1e12) return `$${(val / 1e12).toFixed(2)}T`;
    if (val >= 1e9)  return `$${(val / 1e9).toFixed(2)}B`;
    if (val >= 1e6)  return `$${(val / 1e6).toFixed(2)}M`;
    return `$${val.toLocaleString()}`;
}

export async function getUsStock(ticker) {
    let quote, summary, financials;
    try {
        [quote, summary] = await Promise.all([
            yahooFinance.quote(ticker),
            yahooFinance.quoteSummary(ticker, {
                modules: ['defaultKeyStatistics', 'summaryDetail', 'financialData', 'assetProfile'],
            }),
        ]);
    } catch (e) {
        return { error: `'${ticker}' 종목 데이터를 찾을 수 없습니다.` };
    }

    if (!quote?.regularMarketPrice) {
        return { error: `'${ticker}' 종목 데이터를 찾을 수 없습니다.` };
    }

    const ks = summary?.defaultKeyStatistics || {};
    const sd = summary?.summaryDetail || {};
    const fd = summary?.financialData || {};
    const ap = summary?.assetProfile || {};

    const price     = safe(quote.regularMarketPrice);
    const prevClose = safe(quote.regularMarketPreviousClose);
    const changeVal = price !== 'N/A' && prevClose !== 'N/A' ? price - prevClose : null;
    const changePct = changeVal != null && prevClose ? (changeVal / prevClose) * 100 : null;

    // 3년 손익 (incomeStatementHistory)
    let income = [];
    try {
        const incomeData = await yahooFinance.quoteSummary(ticker, {
            modules: ['incomeStatementHistory'],
        });
        const stmts = incomeData?.incomeStatementHistory?.incomeStatementHistory || [];
        income = stmts
            .slice(0, 3)
            .reverse()
            .map(s => ({
                year: new Date(s.endDate).getFullYear().toString(),
                rev: Math.round(safe(s.totalRevenue, 0) / 1e6),
                op:  Math.round(safe(s.totalOperatingExpenses ? (s.totalRevenue - s.totalOperatingExpenses) : s.operatingIncome, 0) / 1e6),
                net: Math.round(safe(s.netIncome, 0) / 1e6),
            }));
    } catch {
        // 손익 데이터 없으면 빈 배열
    }

    const asofTs = quote.regularMarketTime;
    const asof = asofTs
        ? `As of ${new Date(asofTs).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })} close`
        : `As of ${new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;

    const per  = safe(sd.trailingPE);
    const pbr  = safe(ks.priceToBook);
    const eps  = safe(ks.trailingEps);
    const mktcap  = safe(quote.marketCap);
    const roe  = safe(fd.returnOnEquity);
    const debt = safe(fd.debtToEquity);
    const evebitda = safe(ks.enterpriseToEbitda);
    const div  = safe(sd.dividendYield);
    const beta = safe(ks.beta);
    const high52 = safe(sd.fiftyTwoWeekHigh);
    const low52  = safe(sd.fiftyTwoWeekLow);

    return {
        ticker,
        name:    safe(quote.longName || quote.shortName, ticker),
        sector:  safe(ap.sector || ap.industry, 'N/A'),
        price:   price !== 'N/A' ? `$${Number(price).toFixed(2)}` : 'N/A',
        change:  changeVal != null
            ? `${changeVal >= 0 ? '+' : ''}$${Math.abs(changeVal).toFixed(2)} (${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%)`
            : 'N/A',
        pos:     changeVal != null ? changeVal >= 0 : true,
        asof,
        per:      per !== 'N/A' ? `${Number(per).toFixed(1)}x` : 'N/A',
        pbr:      pbr !== 'N/A' ? `${Number(pbr).toFixed(1)}x` : 'N/A',
        eps:      eps !== 'N/A' ? `$${Number(eps).toFixed(2)}` : 'N/A',
        mktcap:   mktcap !== 'N/A' ? fmtLargeUsd(mktcap) : 'N/A',
        roe:      roe !== 'N/A' ? `${(roe * 100).toFixed(1)}%` : 'N/A',
        debt:     debt !== 'N/A' ? `${Number(debt).toFixed(1)}%` : 'N/A',
        evebitda: evebitda !== 'N/A' ? `${Number(evebitda).toFixed(1)}x` : 'N/A',
        div:      div !== 'N/A' ? `${(div * 100).toFixed(2)}%` : 'N/A',
        beta:     beta !== 'N/A' ? `${Number(beta).toFixed(2)}` : 'N/A',
        foreign:  'N/A',
        vol:      String(safe(quote.regularMarketVolume, 0)),
        avgvol:   String(safe(sd.averageVolume, 0)),
        high52:   high52 !== 'N/A' ? `$${Number(high52).toFixed(2)}` : 'N/A',
        low52:    low52  !== 'N/A' ? `$${Number(low52).toFixed(2)}`  : 'N/A',
        income,
    };
}
