import WebSocket from 'ws';
import { MarketStore } from './marketStore.js';
import { TickerEvent } from '../types/ticker.js';

const STREAM_URL = 'wss://fstream.binance.com/stream?streams=!ticker@arr';
const RECONNECT_DELAY_MS = 3000;
const PING_INTERVAL_MS = 20000;
const PONG_TIMEOUT_MS = 10000;

export class BinanceTickerClient {
  private ws: WebSocket | null = null;
  private pingTimer: NodeJS.Timeout | null = null;
  private pongTimer: NodeJS.Timeout | null = null;
  private stopped = false;

  constructor(private store: MarketStore) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    this.ws?.close();
  }

  private connect(): void {
    this.ws = new WebSocket(STREAM_URL);

    this.ws.on('open', () => {
      this.startPing();
    });

    this.ws.on('message', (data) => {
      try {
        const parsed = JSON.parse(data.toString());
        const arr: TickerEvent[] | undefined = parsed?.data;
        if (Array.isArray(arr)) {
          this.store.ingest(arr);
        }
      } catch (err) {
        console.error('Failed to parse message', err);
      }
    });

    this.ws.on('pong', () => {
      if (this.pongTimer) {
        clearTimeout(this.pongTimer);
        this.pongTimer = null;
      }
    });

    this.ws.on('close', () => {
      this.clearTimers();
      if (!this.stopped) {
        setTimeout(() => this.connect(), RECONNECT_DELAY_MS);
      }
    });

    this.ws.on('error', (err) => {
      console.error('WebSocket error', err);
      this.ws?.close();
    });
  }

  private startPing(): void {
    this.clearTimers();
    this.pingTimer = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      this.ws.ping();
      this.pongTimer = setTimeout(() => {
        this.ws?.terminate();
      }, PONG_TIMEOUT_MS);
    }, PING_INTERVAL_MS);
  }

  private clearTimers(): void {
    if (this.pingTimer) clearInterval(this.pingTimer);
    if (this.pongTimer) clearTimeout(this.pongTimer);
    this.pingTimer = null;
    this.pongTimer = null;
  }
}
