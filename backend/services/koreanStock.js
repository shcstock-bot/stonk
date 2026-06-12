import yahooFinance from 'yahoo-finance2';
import axios from 'axios';

const DART_API_KEY = process.env.DART_API_KEY || '';

function fmtKrw(val) {
    if (val == null || isNaN(val)) return 'N/A';
    return `${Math.round(val).toLocaleString('ko-KR')}원`;
}

function fmtLargeKrw(val) {
    if (val == null || isNaN(val)) return 'N/A';
    if (val >= 1e12) return `${(val / 1e12).toFixed(0)}조 원`;
    if (val >= 1e8) return `${(val / 1e8).toFixed(0)}억 원`;
    return `${val.toLocaleString('ko-KR')}원`;
}

function safe(val, fallback = 'N/A') {
    if (val == null || (typeof val === 'number' && isNaN(val))) return fallback;
    return val;
}

async function getDartCorpCode(ticker) {
    if (!DART_API_KEY) return null;
    try {
        const res = await axios.get('https://opendart.fss.or.kr/api/company.json', {
            params: { crtfc_key: DART_API_KEY, stock_code: ticker },
            timeout: 5000,
        });
        return res.data?.corp_code || null;
    } catch {
        return null;
    }
}

async function getDartFinancials(ticker) {
    if (!DART_API_KEY) return [];
    const corpCode = await getDartCorpCode(ticker);
    if (!corpCode) return [];

    const currentYear = new Date().getFullYear();
    const rows = [];

    for (let year = currentYear - 3; year < currentYear; year++) {
        try {
            const res = await axios.get('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json', {
                params: {
                    crtfc_key: DART_API_KEY,
                    corp_code: corpCode,
                    bsns_year: year,
                    reprt_code: '11011', // 사업보고서
                    fs_div: 'CFS',       // 연결재무제표
                },
                timeout: 8000,
            });

            const list = res.data?.list || [];
            const extract = (...keywords) => {
                const item = list.find(r =>
                    keywords.some(k => r.account_nm?.includes(k)) && r.sj_div === 'IS'
                );
                if (!item) return 0;
                return parseInt((item.thstrm_amount || '0').replace(/,/g, ''), 10) || 0;
            };

            // 연결 재무제표가 없으면 별도 재무제표로 재시도
            let rev = extract('매출액', '수익(매출액)');
            let op  = extract('영업이익');
            let net = extract('당기순이익');

            if (!rev) {
                const res2 = await axios.get('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json', {
                    params: {
                        crtfc_key: DART_API_KEY,
                        corp_code: corpCode,
                        bsns_year: year,
                        reprt_code: '11011',
                        fs_div: 'OFS', // 별도재무제표
                    },
                    timeout: 8000,
                });
                const list2 = res2.data?.list || [];
                const extract2 = (...keywords) => {
                    const item = list2.find(r =>
                        keywords.some(k => r.account_nm?.includes(k)) && r.sj_div === 'IS'
                    );
                    if (!item) return 0;
                    return parseInt((item.thstrm_amount || '0').replace(/,/g, ''), 10) || 0;
                };
                rev = extract2('매출액', '수익(매출액)');
                op  = extract2('영업이익');
                net = extract2('당기순이익');
            }

            // DART 금액 단위는 원 → 억 원으로 변환
            rows.push({ year: String(year), rev: Math.round(rev / 1e8), op: Math.round(op / 1e8), net: Math.round(net / 1e8) });
        } catch {
            // 해당 연도 데이터 없으면 스킵
        }
    }
    return rows;
}

export async function getKoreanStock(ticker) {
    const yfTicker = `${ticker}.KS`;

    let quote, summary;
    try {
        [quote, summary] = await Promise.all([
            yahooFinance.quote(yfTicker),
            yahooFinance.quoteSummary(yfTicker, {
                modules: ['defaultKeyStatistics', 'summaryDetail', 'financialData', 'assetProfile'],
            }),
        ]);
    } catch {
        // KOSDAQ 시도
        try {
            const yfTickerKQ = `${ticker}.KQ`;
            [quote, summary] = await Promise.all([
                yahooFinance.quote(yfTickerKQ),
                yahooFinance.quoteSummary(yfTickerKQ, {
                    modules: ['defaultKeyStatistics', 'summaryDetail', 'financialData', 'assetProfile'],
                }),
            ]);
        } catch (e) {
            return { error: `'${ticker}' 종목 데이터를 찾을 수 없습니다.` };
        }
    }

    const ks = summary?.defaultKeyStatistics || {};
    const sd = summary?.summaryDetail || {};
    const fd = summary?.financialData || {};
    const ap = summary?.assetProfile || {};

    const price      = safe(quote?.regularMarketPrice);
    const prevClose  = safe(quote?.regularMarketPreviousClose);
    const changeVal  = price !== 'N/A' && prevClose !== 'N/A' ? price - prevClose : null;
    const changePct  = changeVal != null && prevClose ? (changeVal / prevClose) * 100 : null;

    const per  = safe(sd?.trailingPE);
    const pbr  = safe(ks?.priceToBook);
    const eps  = safe(ks?.trailingEps);
    const mktcap = safe(quote?.marketCap);
    const roe  = safe(fd?.returnOnEquity);
    const debt = safe(fd?.debtToEquity);
    const evebitda = safe(ks?.enterpriseToEbitda);
    const div  = safe(sd?.dividendYield);
    const beta = safe(ks?.beta);
    const vol  = safe(quote?.regularMarketVolume, 0);
    const avgvol = safe(sd?.averageVolume, 0);
    const high52 = safe(sd?.fiftyTwoWeekHigh);
    const low52  = safe(sd?.fiftyTwoWeekLow);

    const income = await getDartFinancials(ticker);

    const now = new Date();
    const asof = `${now.getFullYear()}.${String(now.getMonth()+1).padStart(2,'0')}.${String(now.getDate()).padStart(2,'0')} 종가 기준`;

    return {
        ticker,
        name:    safe(quote?.longName || quote?.shortName, ticker),
        sector:  safe(ap?.sector || ap?.industry, 'N/A'),
        price:   price !== 'N/A' ? fmtKrw(price) : 'N/A',
        change:  changeVal != null
            ? `${changeVal >= 0 ? '+' : ''}${fmtKrw(changeVal)} (${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%)`
            : 'N/A',
        pos:     changeVal != null ? changeVal >= 0 : true,
        asof,
        per:      per !== 'N/A' ? `${Number(per).toFixed(1)}x` : 'N/A',
        pbr:      pbr !== 'N/A' ? `${Number(pbr).toFixed(1)}x` : 'N/A',
        eps:      eps !== 'N/A' ? fmtKrw(eps) : 'N/A',
        mktcap:   mktcap !== 'N/A' ? fmtLargeKrw(mktcap) : 'N/A',
        roe:      roe !== 'N/A' ? `${(roe * 100).toFixed(1)}%` : 'N/A',
        debt:     debt !== 'N/A' ? `${Number(debt).toFixed(1)}%` : 'N/A',
        evebitda: evebitda !== 'N/A' ? `${Number(evebitda).toFixed(1)}x` : 'N/A',
        div:      div !== 'N/A' ? `${(div * 100).toFixed(2)}%` : 'N/A',
        beta:     beta !== 'N/A' ? `${Number(beta).toFixed(2)}` : 'N/A',
        foreign:  'N/A',
        vol:      String(vol),
        avgvol:   String(avgvol),
        high52:   high52 !== 'N/A' ? fmtKrw(high52) : 'N/A',
        low52:    low52  !== 'N/A' ? fmtKrw(low52)  : 'N/A',
        income,
    };
}
