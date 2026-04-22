import { beforeEach, describe, expect, it, vi } from "vitest";
import { bindWorker, postWorkerMessage } from "./workerBridge";

describe("workerBridge", () => {
  beforeEach(() => {
    bindWorker(null);
  });

  it("queues messages posted before the worker is bound and flushes them on bind", () => {
    const postMessage = vi.fn();

    postWorkerMessage({
      type: "LOAD_HISTORY",
      symbol: "2330",
      months: 6,
    });
    postWorkerMessage({
      type: "SUBSCRIBE_QUOTE_DETAIL",
      symbol: "2330",
    });

    expect(postMessage).not.toHaveBeenCalled();

    bindWorker({ postMessage } as unknown as Worker);

    expect(postMessage).toHaveBeenNthCalledWith(1, {
      type: "LOAD_HISTORY",
      symbol: "2330",
      months: 6,
    });
    expect(postMessage).toHaveBeenNthCalledWith(2, {
      type: "SUBSCRIBE_QUOTE_DETAIL",
      symbol: "2330",
    });
  });

  it("sends messages directly once the worker is already bound", () => {
    const postMessage = vi.fn();
    bindWorker({ postMessage } as unknown as Worker);

    postWorkerMessage({
      type: "LOAD_SESSION",
      symbol: "2330",
      limit: 240,
    });

    expect(postMessage).toHaveBeenCalledWith({
      type: "LOAD_SESSION",
      symbol: "2330",
      limit: 240,
    });
  });
});
