/**
 * workerBridge.ts — 全站共用 Worker 參考
 *
 * MarketDataProvider 啟動 Worker 後呼叫 bindWorker()，
 * 任何頁面或元件都可以直接呼叫 postWorkerMessage() 而不需要 prop drilling。
 */
import type { WorkerInboundMessage } from "./types/market";

let _worker: Worker | null = null;

export function bindWorker(w: Worker | null): void {
  _worker = w;
}

export function postWorkerMessage(msg: WorkerInboundMessage): void {
  _worker?.postMessage(msg);
}
