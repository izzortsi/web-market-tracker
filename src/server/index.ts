import express from 'express';
import cors from 'cors';
import path from 'path';
import { fileURLToPath } from 'url';
import capRanks from './market_caps.json' with { type: 'json' };
import { MarketStore } from './lib/marketStore.js';
import { BinanceTickerClient } from './lib/binanceClient.js';
import { MarketSummaryPayload } from './types/ticker.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
app.use(cors());
app.use(express.json());

const capWeights: Record<string, number> = capRanks;

const store = new MarketStore(capWeights);
const client = new BinanceTickerClient(store);

let latestSnapshot: MarketSummaryPayload | null = null;

const SNAPSHOT_INTERVAL_MS = 1000;

setInterval(() => {
  const now = Date.now();
  latestSnapshot = store.computeSnapshot(now);
}, SNAPSHOT_INTERVAL_MS);

app.get('/api/market/summary', (_req, res) => {
  if (!latestSnapshot) {
    return res.status(503).json({ message: 'warming up' });
  }
  res.json(latestSnapshot);
});

// Serve static client if built
const distClient = path.resolve(__dirname, '../../dist/client');
app.use(express.static(distClient));
app.get('*', (_req, res) => {
  res.sendFile(path.join(distClient, 'index.html'));
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server listening on ${PORT}`);
  client.start();
});
