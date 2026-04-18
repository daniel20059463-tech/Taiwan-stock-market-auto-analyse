# 2026-04-19 Tech Debt Remediation Log

## Task 2 worktree grouping snapshot

Source command:

```powershell
git status --short
```

Current grouping for active changes:

### runtime/python
- `auto_trader.py`
- `risk_manager.py`
- `run.py`
- `sinopac_bridge.py`
- `trading/market_state.py`
- `trading/positions.py`
- `backtest.py`
- `daily_price_cache.py`
- `historical_data.py`
- `institutional_flow_cache.py`
- `institutional_flow_provider.py`
- `market_calendar.py`
- `retail_flow_strategy.py`
- `sector_rotation.py`
- `swing_exit_judge.py`
- `test_analyst_context_enrichment.py`
- `test_auto_trader_decision_reports.py`
- `test_auto_trader_manual_orders.py`
- `test_auto_trader_market_hours.py`
- `test_auto_trader_short_flow.py`
- `test_disposition_filter.py`
- `test_institutional_flow_cache.py`
- `test_institutional_flow_provider.py`
- `test_limit_lock.py`
- `test_market_calendar.py`
- `test_position_persistence.py`
- `test_retail_flow_strategy.py`
- `test_run.py`
- `test_sinopac_bridge.py`

### web frontend
- `src/App.tsx`
- `src/components/Dashboard.test.tsx`
- `src/components/Dashboard.tsx`
- `src/components/ErrorBoundary.tsx`
- `src/components/MarketDataProvider.tsx`
- `src/index.css`
- `src/main.tsx`
- `src/types/market.ts`
- `src/workerBridge.ts`
- `src/workers/data.worker.ts`
- `src/components/ChartPanel.test.tsx`
- `src/components/ChartPanel.tsx`
- `src/components/InfoPane.test.tsx`
- `src/components/InfoPane.tsx`
- `src/components/QuoteDetailPane.test.tsx`
- `src/components/QuoteDetailPane.tsx`
- `src/components/QuoteTable.test.tsx`
- `src/components/QuoteTable.tsx`
- `src/components/TradePane.tsx`
- `src/workers/data.worker.test.ts`

### flutter frontend
- `flutter_app/lib/pages/stock_detail_quote_page.dart`
- `flutter_app/lib/services/paper_trade_gateway.dart`
- `flutter_app/test/stock_detail_quote_page_test.dart`
- `flutter_app/.gitignore`
- `flutter_app/README.md`
- `flutter_app/analysis_options.yaml`
- `flutter_app/lib/main.dart`
- `flutter_app/lib/models/`
- `flutter_app/lib/pages/watchlist_page.dart`
- `flutter_app/lib/screens/`
- `flutter_app/lib/theme/`
- `flutter_app/lib/widgets/`
- `flutter_app/pubspec.lock`
- `flutter_app/pubspec.yaml`
- `flutter_app/test/paper_trade_gateway_test.dart`
- `flutter_app/test/stock_data_grid_test.dart`
- `flutter_app/test/widget_test.dart`

### docs/specs/plans
- `docs/superpowers/plans/2026-04-09-dashboard-four-pane-overwrite-implementation.md`
- `docs/superpowers/plans/2026-04-10-dashboard-psc-overwrite-implementation.md`
- `docs/superpowers/plans/2026-04-10-flutter-stock-detail-layout-implementation.md`
- `docs/superpowers/plans/2026-04-10-flutter-watchlist-flash-cells-implementation.md`
- `docs/superpowers/plans/2026-04-10-flutter-watchlist-page-implementation.md`
- `docs/superpowers/plans/2026-04-10-psc-style-dashboard-overwrite-implementation.md`
- `docs/superpowers/plans/2026-04-12-flutter-stock-detail-ws-orderbook-tape-implementation.md`
- `docs/superpowers/plans/2026-04-12-flutter-stock-header-live-quote-implementation.md`
- `docs/superpowers/plans/2026-04-12-sinopac-native-quote-detail-implementation.md`
- `docs/superpowers/plans/2026-04-13-shioaji-full-universe-visible-subscription-implementation.md`
- `docs/superpowers/plans/2026-04-17-retail-flow-swing-strategy-implementation.md`
- `docs/superpowers/plans/2026-04-18-market-calendar-yearly-data-implementation.md`
- `docs/superpowers/plans/2026-04-18-retail-flow-swing-intraday-verifiable-implementation.md`
- `docs/superpowers/plans/2026-04-19-project-tech-debt-remediation.md`
- `docs/superpowers/specs/2026-04-09-dashboard-four-pane-overwrite-design.md`
- `docs/superpowers/specs/2026-04-10-dashboard-psc-overwrite-design.md`
- `docs/superpowers/specs/2026-04-10-flutter-stock-detail-layout-design.md`
- `docs/superpowers/specs/2026-04-10-flutter-watchlist-flash-cells-design.md`
- `docs/superpowers/specs/2026-04-10-flutter-watchlist-page-design.md`
- `docs/superpowers/specs/2026-04-10-psc-style-dashboard-overwrite-design.md`
- `docs/superpowers/specs/2026-04-12-flutter-stock-detail-ws-orderbook-tape-design.md`
- `docs/superpowers/specs/2026-04-12-flutter-stock-header-live-quote-design.md`
- `docs/superpowers/specs/2026-04-12-sinopac-native-quote-detail-design.md`
- `docs/superpowers/specs/2026-04-13-shioaji-full-universe-visible-subscription-design.md`
- `docs/superpowers/specs/2026-04-17-retail-flow-swing-strategy-design.md`
- `docs/superpowers/specs/2026-04-18-market-calendar-yearly-data-design.md`
- `docs/superpowers/specs/2026-04-18-retail-flow-swing-intraday-verifiable-design.md`

### generated artifacts
- `data/`
- `flutter_app/build/` (ignored)
- `src-tauri/target/` (ignored)
- `logs/` (ignored)
- `tmp/` (ignored)

## Notes

- Generated artifact ignore coverage was rechecked after updating root `.gitignore`.
- Runtime refactors should avoid mixing with the current web/flutter/doc buckets until they are batched into separate commits or branches.
