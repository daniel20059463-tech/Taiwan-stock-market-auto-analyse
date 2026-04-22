# PSC-Style Dashboard Overwrite Design

Goal: Replace the current dashboard homepage with a desktop-terminal layout strongly inspired by the PSC screenshot while preserving the existing market data flow, selection linkage, charting, portfolio, and replay data.

Layout:
- Row 1: top market/category bar
- Row 2: sub-mode bar for homepage modules
- Main area: two columns
  - Left: large quote table on top, trade/position pane below
  - Right: main chart on top, info/technical/account pane below

Hard constraints:
- The homepage must fit within the visible viewport.
- All overflow must scroll inside panes, never on the page root.
- No backend/store/worker contract changes.
- Existing symbol selection continues to drive all panes.
