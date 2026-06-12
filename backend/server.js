import 'dotenv/config';
import express from 'express';
import { getKoreanStock } from './services/koreanStock.js';
import { getUsStock } from './services/usStock.js';

const app = express();
const PORT = process.env.PORT || 8000;

const KR_TICKER = /^\d{6}$/;

app.use((req, res, next) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET');
    next();
});

app.get('/api/stock/:ticker', async (req, res) => {
    const ticker = req.params.ticker.trim().toUpperCase();
    try {
        const data = KR_TICKER.test(ticker)
            ? await getKoreanStock(ticker)
            : await getUsStock(ticker);

        if (data.error) return res.status(404).json(data);
        res.json(data);
    } catch (err) {
        res.status(500).json({ error: `서버 오류: ${err.message}` });
    }
});

app.get('/health', (_, res) => res.json({ status: 'ok' }));

app.listen(PORT, () => console.log(`EquiSynth API running at http://localhost:${PORT}`));
