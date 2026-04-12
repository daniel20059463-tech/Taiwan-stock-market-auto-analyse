import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:taiwan_stock_watchlist/pages/stock_detail_quote_page.dart';
import 'package:taiwan_stock_watchlist/services/paper_trade_gateway.dart';

class _FakeGateway implements PaperTradeGateway {
  final List<String> calls = <String>[];
  final List<String> unsubscribedSymbols = <String>[];
  final StreamController<OrderBookSnapshot> _orderBookController =
      StreamController<OrderBookSnapshot>.broadcast();
  final StreamController<TradeTapeSnapshot> _tradeTapeController =
      StreamController<TradeTapeSnapshot>.broadcast();
  final StreamController<LiveQuoteSnapshot> _liveQuoteController =
      StreamController<LiveQuoteSnapshot>.broadcast();

  @override
  Future<List<IntradayTrendPoint>> loadIntradayTrend(String symbol) async {
    return <IntradayTrendPoint>[
      const IntradayTrendPoint(timeLabel: '09:00', price: 500.0),
      const IntradayTrendPoint(timeLabel: '10:00', price: 503.0),
      const IntradayTrendPoint(timeLabel: '11:00', price: 501.0),
      const IntradayTrendPoint(timeLabel: '12:00', price: 504.0),
      const IntradayTrendPoint(timeLabel: '13:30', price: 506.0),
    ];
  }

  @override
  Stream<OrderBookSnapshot> subscribeOrderBook(String symbol) {
    return _orderBookController.stream;
  }

  @override
  Stream<TradeTapeSnapshot> subscribeTradeTape(String symbol) {
    return _tradeTapeController.stream;
  }

  @override
  Stream<LiveQuoteSnapshot> subscribeLiveQuote(String symbol) {
    return _liveQuoteController.stream.where((snapshot) => snapshot.symbol == symbol);
  }

  @override
  Future<void> unsubscribeQuoteDetail(String symbol) async {
    unsubscribedSymbols.add(symbol);
  }

  @override
  Future<PaperTradeResult> submitManualTrade({
    required String symbol,
    required String action,
    required int shares,
  }) async {
    calls.add('$action:$symbol:$shares');
    return const PaperTradeResult(success: true, message: 'ok');
  }

  void emitOrderBook(OrderBookSnapshot snapshot) {
    _orderBookController.add(snapshot);
  }

  void emitTradeTape(TradeTapeSnapshot snapshot) {
    _tradeTapeController.add(snapshot);
  }

  void emitLiveQuote(LiveQuoteSnapshot snapshot) {
    _liveQuoteController.add(snapshot);
  }

  Future<void> dispose() async {
    await _orderBookController.close();
    await _tradeTapeController.close();
    await _liveQuoteController.close();
  }
}

Future<void> _pumpStockDetailPage(
  WidgetTester tester, {
  required _FakeGateway gateway,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      home: StockDetailQuotePage(
        symbol: '2330',
        name: 'TSMC',
        gateway: gateway,
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('Stock detail header shows placeholders when no live quote exists', (tester) async {
    final gateway = _FakeGateway();

    addTearDown(gateway.dispose);

    await _pumpStockDetailPage(tester, gateway: gateway);

    final header = find.byKey(const Key('stock-detail-header'));

    expect(header, findsOneWidget);
    expect(find.descendant(of: header, matching: find.text('--')), findsNWidgets(8));
  });

  testWidgets('Stock detail header updates from a live quote snapshot', (tester) async {
    final gateway = _FakeGateway();

    addTearDown(gateway.dispose);

    await _pumpStockDetailPage(tester, gateway: gateway);

    gateway.emitLiveQuote(
      const LiveQuoteSnapshot(
        symbol: '2330',
        price: 780.0,
        previousClose: 770.0,
        open: 772.0,
        high: 785.0,
        low: 768.0,
        totalVolume: 34500,
        changePct: 1.30,
      ),
    );
    await tester.pumpAndSettle();

    final header = find.byKey(const Key('stock-detail-header'));

    expect(header, findsOneWidget);
    expect(find.descendant(of: header, matching: find.text('780.00')), findsOneWidget);
    expect(find.descendant(of: header, matching: find.text('+10.00')), findsOneWidget);
    expect(find.descendant(of: header, matching: find.text('+1.30%')), findsOneWidget);
    expect(find.descendant(of: header, matching: find.text('772.00')), findsOneWidget);
    expect(find.descendant(of: header, matching: find.text('785.00')), findsOneWidget);
    expect(find.descendant(of: header, matching: find.text('768.00')), findsOneWidget);
    expect(find.descendant(of: header, matching: find.text('770.00')), findsOneWidget);
    expect(find.descendant(of: header, matching: find.text('34500')), findsOneWidget);
  });
  testWidgets('個股詳細頁顯示中文區塊與分時線', (tester) async {
    final gateway = _FakeGateway();

    addTearDown(gateway.dispose);

    await tester.pumpWidget(
      MaterialApp(
        home: StockDetailQuotePage(
          symbol: '2330',
          name: '台積電',
          gateway: gateway,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('stock-detail-header')), findsOneWidget);
    expect(find.byKey(const Key('stock-detail-chart-tabs')), findsOneWidget);
    expect(find.byKey(const Key('stock-detail-quote-panels')), findsOneWidget);
    expect(find.byKey(const Key('stock-detail-action-bar')), findsOneWidget);
    expect(find.text('走勢圖'), findsOneWidget);
    expect(find.text('K線圖'), findsOneWidget);
    expect(find.text('技術指標'), findsOneWidget);
    expect(find.byKey(const Key('stock-detail-intraday-chart')), findsOneWidget);
  });

  testWidgets('個股詳細頁顯示 WebSocket 推播的最佳五檔與分時明細', (tester) async {
    final gateway = _FakeGateway();

    addTearDown(gateway.dispose);

    await tester.pumpWidget(
      MaterialApp(
        home: StockDetailQuotePage(
          symbol: '2330',
          name: '台積電',
          gateway: gateway,
        ),
      ),
    );
    await tester.pumpAndSettle();

    gateway.emitOrderBook(
      const OrderBookSnapshot(
        symbol: '2330',
        timestamp: 1700000000000,
        asks: <OrderBookLevel>[
          OrderBookLevel(level: 1, price: 504.0, volume: 342),
        ],
        bids: <OrderBookLevel>[
          OrderBookLevel(level: 1, price: 503.0, volume: 664),
        ],
      ),
    );
    gateway.emitTradeTape(
      const TradeTapeSnapshot(
        symbol: '2330',
        timestamp: 1700000000000,
        rows: <TradeTapeRow>[
          TradeTapeRow(time: '13:29:58', price: 504.0, volume: 7, side: TradeSide.outer),
        ],
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('最佳五檔'), findsOneWidget);
    expect(find.text('分時明細'), findsOneWidget);
    expect(find.text('342'), findsOneWidget);
    expect(find.text('13:29:58'), findsOneWidget);
  });

  testWidgets('個股詳細頁買進按鈕會送出手動模擬交易', (tester) async {
    final gateway = _FakeGateway();

    addTearDown(gateway.dispose);

    await tester.pumpWidget(
      MaterialApp(
        home: StockDetailQuotePage(
          symbol: '2330',
          name: '台積電',
          gateway: gateway,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('買進'));
    await tester.pump();

    expect(gateway.calls, <String>['BUY:2330:1000']);
  });

  testWidgets('個股詳細頁賣出按鈕會送出手動模擬交易', (tester) async {
    final gateway = _FakeGateway();

    addTearDown(gateway.dispose);

    await tester.pumpWidget(
      MaterialApp(
        home: StockDetailQuotePage(
          symbol: '2330',
          name: '台積電',
          gateway: gateway,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('賣出'));
    await tester.pump();

    expect(gateway.calls, <String>['SELL:2330:1000']);
  });

  testWidgets('個股詳細頁離開時會取消五檔與明細訂閱', (tester) async {
    final gateway = _FakeGateway();

    addTearDown(gateway.dispose);

    await tester.pumpWidget(
      MaterialApp(
        home: StockDetailQuotePage(
          symbol: '2330',
          name: '台積電',
          gateway: gateway,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.pumpWidget(const MaterialApp(home: SizedBox.shrink()));
    await tester.pumpAndSettle();

    expect(gateway.unsubscribedSymbols, <String>['2330']);
  });
}
