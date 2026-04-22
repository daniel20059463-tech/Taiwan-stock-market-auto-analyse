# Dashboard Four-Pane Terminal Overwrite Design

Goal: Replace the current dashboard homepage with a denser PSC-style four-pane terminal layout while preserving the existing data flow, chart pipeline, worker/store contracts, and left-side market content.

Approved structure:
- Left top: 報價列表（全市場 / 類股熱度切換）
- Right top: 即時走勢（單一標的主圖）
- Left bottom: 交易動態（成交 / 平倉 / 持倉）
- Right bottom: 技術與帳本（摘要 / 技術 / 帳本）

Hard constraints:
- The homepage must not exceed the visible app viewport.
- Each pane must scroll internally instead of stretching the page.
- No backend, store, or worker protocol changes.
- Preserve symbol selection linkage across panes.
