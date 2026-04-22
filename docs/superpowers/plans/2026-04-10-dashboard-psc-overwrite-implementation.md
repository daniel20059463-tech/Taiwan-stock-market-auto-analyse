# Dashboard PSC Overwrite Implementation Plan

- Update Dashboard tests first to lock the four-pane PSC-style labels and viewport-safe behavior assumptions.
- Refactor the Dashboard header into a compact terminal toolbar and rename the panes to 報價列表 / 即時走勢 / 交易動態 / 技術與帳本.
- Constrain the dashboard root to the available viewport and make pane bodies scroll internally.
- Keep all existing chart, symbol-selection, portfolio, and market data logic intact.
- Clean visible mojibake titles in App.tsx that would leak into the homepage shell.
- Run targeted frontend tests, then full frontend tests, then build.
