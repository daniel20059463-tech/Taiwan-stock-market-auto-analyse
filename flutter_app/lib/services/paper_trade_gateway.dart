import 'dart:async';
import 'dart:convert';
import 'dart:io';

class IntradayTrendPoint {
  const IntradayTrendPoint({
    required this.timeLabel,
    required this.price,
  });

  final String timeLabel;
  final double price;
}

class PaperTradeResult {
  const PaperTradeResult({
    required this.success,
    required this.message,
  });

  final bool success;
  final String message;
}

class OrderBookLevel {
  const OrderBookLevel({
    required this.level,
    required this.price,
    required this.volume,
  });

  final int level;
  final double price;
  final int volume;

  factory OrderBookLevel.fromJson(Map<String, dynamic> json) {
    return OrderBookLevel(
      level: (json['level'] as num?)?.toInt() ?? 0,
      price: (json['price'] as num?)?.toDouble() ?? 0,
      volume: (json['volume'] as num?)?.toInt() ?? 0,
    );
  }
}

class OrderBookSnapshot {
  const OrderBookSnapshot({
    required this.symbol,
    required this.timestamp,
    required this.asks,
    required this.bids,
  });

  final String symbol;
  final int timestamp;
  final List<OrderBookLevel> asks;
  final List<OrderBookLevel> bids;

  factory OrderBookSnapshot.fromJson(Map<String, dynamic> json) {
    return OrderBookSnapshot(
      symbol: json['symbol'] as String? ?? '',
      timestamp: (json['timestamp'] as num?)?.toInt() ?? 0,
      asks: (json['asks'] as List? ?? const <Object>[])
          .whereType<Map>()
          .map((row) => OrderBookLevel.fromJson(Map<String, dynamic>.from(row)))
          .toList(growable: false),
      bids: (json['bids'] as List? ?? const <Object>[])
          .whereType<Map>()
          .map((row) => OrderBookLevel.fromJson(Map<String, dynamic>.from(row)))
          .toList(growable: false),
    );
  }
}

enum TradeSide { outer, inner, neutral }

class TradeTapeRow {
  const TradeTapeRow({
    required this.time,
    required this.price,
    required this.volume,
    required this.side,
  });

  final String time;
  final double price;
  final int volume;
  final TradeSide side;

  factory TradeTapeRow.fromJson(Map<String, dynamic> json) {
    final sideRaw = (json['side'] as String? ?? '').toLowerCase();
    return TradeTapeRow(
      time: json['time'] as String? ?? '',
      price: (json['price'] as num?)?.toDouble() ?? 0,
      volume: (json['volume'] as num?)?.toInt() ?? 0,
      side: switch (sideRaw) {
        'outer' => TradeSide.outer,
        'inner' => TradeSide.inner,
        _ => TradeSide.neutral,
      },
    );
  }
}

class TradeTapeSnapshot {
  const TradeTapeSnapshot({
    required this.symbol,
    required this.timestamp,
    required this.rows,
  });

  final String symbol;
  final int timestamp;
  final List<TradeTapeRow> rows;

  factory TradeTapeSnapshot.fromJson(Map<String, dynamic> json) {
    return TradeTapeSnapshot(
      symbol: json['symbol'] as String? ?? '',
      timestamp: (json['timestamp'] as num?)?.toInt() ?? 0,
      rows: (json['rows'] as List? ?? const <Object>[])
          .whereType<Map>()
          .map((row) => TradeTapeRow.fromJson(Map<String, dynamic>.from(row)))
          .toList(growable: false),
    );
  }
}

class LiveQuoteSnapshot {
  const LiveQuoteSnapshot({
    required this.symbol,
    required this.price,
    required this.previousClose,
    required this.open,
    required this.high,
    required this.low,
    required this.totalVolume,
    required this.changePct,
  });

  final String symbol;
  final double price;
  final double previousClose;
  final double open;
  final double high;
  final double low;
  final int totalVolume;
  final double changePct;
}

abstract class PaperTradeGateway {
  Future<List<IntradayTrendPoint>> loadIntradayTrend(String symbol);

  Stream<OrderBookSnapshot> subscribeOrderBook(String symbol);

  Stream<TradeTapeSnapshot> subscribeTradeTape(String symbol);

  Stream<LiveQuoteSnapshot> subscribeLiveQuote(String symbol);

  Future<void> unsubscribeQuoteDetail(String symbol);

  Future<PaperTradeResult> submitManualTrade({
    required String symbol,
    required String action,
    required int shares,
  });
}

class WsPaperTradeGateway implements PaperTradeGateway {
  WsPaperTradeGateway({
    this.endpoint = 'ws://127.0.0.1:8765',
    this.timeout = const Duration(seconds: 5),
  });

  final String endpoint;
  final Duration timeout;

  WebSocket? _quoteDetailSocket;
  String? _quoteDetailSymbol;
  Future<void>? _connectingQuoteDetail;
  WebSocket? _liveQuoteSocket;
  Future<void>? _connectingLiveQuote;
  StreamController<OrderBookSnapshot>? _orderBookController;
  StreamController<TradeTapeSnapshot>? _tradeTapeController;
  StreamController<LiveQuoteSnapshot>? _liveQuoteController;

  @override
  Future<List<IntradayTrendPoint>> loadIntradayTrend(String symbol) async {
    final socket = await WebSocket.connect(endpoint).timeout(timeout);
    try {
      socket.add(jsonEncode(<String, Object>{
        'type': 'session_bars',
        'symbol': symbol,
        'limit': 240,
      }));

      await for (final raw in socket.timeout(timeout)) {
        if (raw is! String) {
          continue;
        }
        final decoded = jsonDecode(raw);
        if (decoded is! Map<String, dynamic>) {
          continue;
        }
        if (decoded['type'] != 'SESSION_BARS') {
          continue;
        }
        final candles = decoded['candles'];
        if (candles is! List) {
          return const <IntradayTrendPoint>[];
        }
        return candles
            .whereType<Map>()
            .map((candle) {
              final mapped = Map<String, dynamic>.from(candle);
              final timeMs = (mapped['time'] as num?)?.toInt() ?? 0;
              final time = DateTime.fromMillisecondsSinceEpoch(timeMs);
              final price = (mapped['close'] as num?)?.toDouble() ?? 0.0;
              return IntradayTrendPoint(
                timeLabel:
                    '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}',
                price: price,
              );
            })
            .toList(growable: false);
      }
      return const <IntradayTrendPoint>[];
    } on TimeoutException {
      return const <IntradayTrendPoint>[];
    } finally {
      await socket.close();
    }
  }

  @override
  Stream<OrderBookSnapshot> subscribeOrderBook(String symbol) {
    _orderBookController ??= StreamController<OrderBookSnapshot>.broadcast();
    unawaited(_ensureQuoteDetailSubscription(symbol));
    return _orderBookController!.stream.where((snapshot) => snapshot.symbol == symbol);
  }

  @override
  Stream<TradeTapeSnapshot> subscribeTradeTape(String symbol) {
    _tradeTapeController ??= StreamController<TradeTapeSnapshot>.broadcast();
    unawaited(_ensureQuoteDetailSubscription(symbol));
    return _tradeTapeController!.stream.where((snapshot) => snapshot.symbol == symbol);
  }

  @override
  Stream<LiveQuoteSnapshot> subscribeLiveQuote(String symbol) {
    _liveQuoteController ??= StreamController<LiveQuoteSnapshot>.broadcast(
      onCancel: () {
        if (!(_liveQuoteController?.hasListener ?? false)) {
          unawaited(_closeLiveQuoteSocket());
        }
      },
    );
    unawaited(_ensureLiveQuoteSocket());
    return _liveQuoteController!.stream.where((snapshot) => snapshot.symbol == symbol);
  }

  Future<void> _ensureLiveQuoteSocket() async {
    if (_liveQuoteSocket != null) {
      return;
    }
    if (_connectingLiveQuote != null) {
      await _connectingLiveQuote;
      if (_liveQuoteSocket != null) {
        return;
      }
    }
    _connectingLiveQuote = _openLiveQuoteSocket();
    try {
      await _connectingLiveQuote;
    } finally {
      _connectingLiveQuote = null;
    }
  }

  Future<void> _openLiveQuoteSocket() async {
    await _closeLiveQuoteSocket();
    final socket = await WebSocket.connect(endpoint).timeout(timeout);
    _liveQuoteSocket = socket;

    unawaited(_listenLiveQuoteSocket(socket));
  }

  Future<void> _listenLiveQuoteSocket(WebSocket socket) async {
    try {
      await for (final raw in socket.timeout(timeout)) {
        if (raw is! String) {
          continue;
        }
        final decoded = jsonDecode(raw);
        if (decoded is List) {
          for (final item in decoded.whereType<Map>()) {
            final snapshot = _tryParseLiveQuoteSnapshot(Map<String, dynamic>.from(item));
            if (snapshot != null) {
              _liveQuoteController?.add(snapshot);
            }
          }
          continue;
        }
        if (decoded is! Map<String, dynamic>) {
          continue;
        }

        final snapshot = _tryParseLiveQuoteSnapshot(decoded);
        if (snapshot != null) {
          _liveQuoteController?.add(snapshot);
        }
      }
    } on TimeoutException {
      // Ignore stale sockets; callers will reconnect on the next subscribe.
    } catch (error) {
      _liveQuoteController?.addError(error);
    } finally {
      if (identical(_liveQuoteSocket, socket)) {
        _liveQuoteSocket = null;
      }
      await socket.close();
    }
  }

  Future<void> _closeLiveQuoteSocket() async {
    final socket = _liveQuoteSocket;
    _liveQuoteSocket = null;
    if (socket == null) {
      return;
    }
    await socket.close();
  }

  LiveQuoteSnapshot? _tryParseLiveQuoteSnapshot(Map<String, dynamic> json) {
    final symbol = _asString(json['symbol']);
    final price = _asDouble(json['price']);
    if (symbol == null || price == null) {
      return null;
    }

    return LiveQuoteSnapshot(
      symbol: symbol,
      price: price,
      previousClose: _asDouble(json['previousClose']) ?? 0,
      open: _asDouble(json['open']) ?? 0,
      high: _asDouble(json['high']) ?? 0,
      low: _asDouble(json['low']) ?? 0,
      totalVolume: _asInt(json['totalVolume']) ?? 0,
      changePct: _asDouble(json['changePct']) ?? 0,
    );
  }

  String? _asString(dynamic value) {
    return value is String && value.isNotEmpty ? value : null;
  }

  double? _asDouble(dynamic value) {
    if (value is num) {
      return value.toDouble();
    }
    if (value is String) {
      return double.tryParse(value);
    }
    return null;
  }

  int? _asInt(dynamic value) {
    if (value is num) {
      return value.toInt();
    }
    if (value is String) {
      return int.tryParse(value);
    }
    return null;
  }

  Future<void> _ensureQuoteDetailSubscription(String symbol) async {
    if (_quoteDetailSocket != null && _quoteDetailSymbol == symbol) {
      return;
    }
    if (_connectingQuoteDetail != null) {
      await _connectingQuoteDetail;
      if (_quoteDetailSocket != null && _quoteDetailSymbol == symbol) {
        return;
      }
    }
    _connectingQuoteDetail = _openQuoteDetailSocket(symbol);
    try {
      await _connectingQuoteDetail;
    } finally {
      _connectingQuoteDetail = null;
    }
  }

  Future<void> _openQuoteDetailSocket(String symbol) async {
    await _closeQuoteDetailSocket(sendUnsubscribe: true);
    _orderBookController ??= StreamController<OrderBookSnapshot>.broadcast();
    _tradeTapeController ??= StreamController<TradeTapeSnapshot>.broadcast();

    final socket = await WebSocket.connect(endpoint).timeout(timeout);
    _quoteDetailSocket = socket;
    _quoteDetailSymbol = symbol;

    unawaited(_listenQuoteDetailSocket(socket, symbol));
    socket.add(jsonEncode(<String, Object>{
      'type': 'subscribe_quote_detail',
      'symbol': symbol,
    }));
  }

  Future<void> _listenQuoteDetailSocket(WebSocket socket, String symbol) async {
    try {
      await for (final raw in socket.timeout(timeout)) {
        if (raw is! String) {
          continue;
        }
        final decoded = jsonDecode(raw);
        if (decoded is! Map<String, dynamic>) {
          continue;
        }
        final type = decoded['type'];
        if (type == 'ORDER_BOOK_SNAPSHOT') {
          final snapshot = OrderBookSnapshot.fromJson(decoded);
          if (snapshot.symbol == symbol) {
            _orderBookController?.add(snapshot);
          }
          continue;
        }
        if (type == 'TRADE_TAPE_SNAPSHOT') {
          final snapshot = TradeTapeSnapshot.fromJson(decoded);
          if (snapshot.symbol == symbol) {
            _tradeTapeController?.add(snapshot);
          }
        }
      }
    } on TimeoutException {
      _orderBookController?.addError('五檔資料逾時');
      _tradeTapeController?.addError('分時明細逾時');
    } catch (error) {
      _orderBookController?.addError(error);
      _tradeTapeController?.addError(error);
    } finally {
      if (identical(_quoteDetailSocket, socket)) {
        _quoteDetailSocket = null;
        _quoteDetailSymbol = null;
      }
      await socket.close();
    }
  }

  @override
  Future<void> unsubscribeQuoteDetail(String symbol) async {
    if (_quoteDetailSymbol != symbol) {
      return;
    }
    await _closeQuoteDetailSocket(sendUnsubscribe: true);
  }

  Future<void> _closeQuoteDetailSocket({required bool sendUnsubscribe}) async {
    final socket = _quoteDetailSocket;
    final symbol = _quoteDetailSymbol;
    _quoteDetailSocket = null;
    _quoteDetailSymbol = null;
    if (socket == null) {
      return;
    }
    try {
      if (sendUnsubscribe && symbol != null) {
        socket.add(jsonEncode(<String, Object>{
          'type': 'unsubscribe_quote_detail',
          'symbol': symbol,
        }));
      }
    } catch (_) {
      // Ignore websocket send errors during teardown.
    } finally {
      await socket.close();
    }
  }

  @override
  Future<PaperTradeResult> submitManualTrade({
    required String symbol,
    required String action,
    required int shares,
  }) async {
    final socket = await WebSocket.connect(endpoint).timeout(timeout);
    try {
      socket.add(jsonEncode(<String, Object>{
        'type': 'paper_trade',
        'symbol': symbol,
        'action': action,
        'shares': shares,
      }));

      await for (final raw in socket.timeout(timeout)) {
        if (raw is! String) {
          continue;
        }
        final decoded = jsonDecode(raw);
        if (decoded is! Map<String, dynamic>) {
          continue;
        }
        if (decoded['type'] != 'PAPER_TRADE_RESULT') {
          continue;
        }
        final success = decoded['status'] == 'ok';
        final error = decoded['error'];
        return PaperTradeResult(
          success: success,
          message: success
              ? '模擬${action == 'BUY' ? '買進' : '賣出'}送出成功'
              : (error is String && error.isNotEmpty ? error : '模擬交易送出失敗'),
        );
      }
      return const PaperTradeResult(success: false, message: '模擬交易回應逾時');
    } on TimeoutException {
      return const PaperTradeResult(success: false, message: '模擬交易回應逾時');
    } catch (_) {
      return const PaperTradeResult(success: false, message: '無法連線到模擬交易後端');
    } finally {
      await socket.close();
    }
  }
}
