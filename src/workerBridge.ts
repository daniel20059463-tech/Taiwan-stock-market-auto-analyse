/**
 * workerBridge.ts — 全站共用 Worker 參考
 *
 * MarketDataProvider 啟動 Worker 後呼叫 bindWorker()，
 * 任何頁面或元件都可以直接呼叫 postWorkerMessage() 而不需要 prop drilling。
 */
import type { WorkerInboundMessage } from "./types/market";

let _worker: Worker | null = null;
const _queuedMessages: WorkerInboundMessage[] = [];

export function bindWorker(w: Worker | null): void {
  _worker = w;
  if (!_worker || _queuedMessages.length === 0) {
    return;
  }
  while (_queuedMessages.length > 0) {
    const message = _queuedMessages.shift();
    if (message) {
      _worker.postMessage(message);
    }
  }
}

export function postWorkerMessage(msg: WorkerInboundMessage): void {
  if (!_worker) {
    _queuedMessages.push(msg);
    return;
  }
  _worker.postMessage(msg);
}
