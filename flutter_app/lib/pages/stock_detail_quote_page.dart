import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../models/candle_bar.dart';
import '../services/paper_trade_gateway.dart';
import '../theme/app_colors.dart';
import '../widgets/intraday_trend_chart.dart';
import '../widgets/stock_k_chart_panel.dart';

class StockDetailQuotePage extends StatefulWidget {
  const StockDetailQuotePage({
    super.key,
    required this.symbol,
    required this.name,
    this.gateway,
  });

  final String symbol;
  final String name;
  final PaperTradeGateway? gateway;

  @override
  State<StockDetailQuotePage> createState() => _StockDetailQuotePageState();
}

class _StockDetailQuotePageState extends State<StockDetailQuotePage> {
  late final PaperTradeGateway _gateway;
  late final _QuoteSummary _summary;
  late final List<CandleBar> _dailyBars;
  List<IntradayTrendPoint> _trendPoints = const <IntradayTrendPoint>[];
  List<OrderBookLevel> _asks = const <OrderBookLevel>[];
  List<OrderBookLevel> _bids = const <OrderBookLevel>[];
  List<TradeTapeRow> _tradeTapeRows = const <TradeTapeRow>[];
  LiveQuoteSnapshot? _liveQuote;
  StreamSubscription<OrderBookSnapshot>? _orderBookSubscription;
  StreamSubscription<TradeTapeSnapshot>? _tradeTapeSubscription;
  StreamSubscription<LiveQuoteSnapshot>? _liveQuoteSubscription;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _gateway = widget.gateway ?? WsPaperTradeGateway();
    _summary = _mockSummary();
    _dailyBars = _mockDailyBars();
    _loadIntradayTrend();
    _subscribeQuoteDetail();
  }

  void _subscribeQuoteDetail() {
    _orderBookSubscription = _gateway.subscribeOrderBook(widget.symbol).listen((snapshot) {
      if (!mounted) {
        return;
      }
      setState(() {
        _asks = List<OrderBookLevel>.from(snapshot.asks)
          ..sort((a, b) => a.level.compareTo(b.level));
        _bids = List<OrderBookLevel>.from(snapshot.bids)
          ..sort((a, b) => a.level.compareTo(b.level));
      });
    });
    _tradeTapeSubscription = _gateway.subscribeTradeTape(widget.symbol).listen((snapshot) {
      if (!mounted) {
        return;
      }
      setState(() {
        _tradeTapeRows = snapshot.rows;
      });
    });
  }

  Future<void> _loadIntradayTrend() async {
    final points = await _gateway.loadIntradayTrend(widget.symbol);
    if (!mounted) {
      return;
    }
    setState(() {
      _trendPoints = points.isEmpty ? _fallbackTrendPoints(_summary.previousClose) : points;
    });
  }

  Future<void> _submitTrade(String action) async {
    if (_submitting) {
      return;
    }
    setState(() {
      _submitting = true;
    });
    final result = await _gateway.submitManualTrade(
      symbol: widget.symbol,
      action: action,
      shares: 1000,
    );
    if (!mounted) {
      return;
    }
    setState(() {
      _submitting = false;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        backgroundColor: result.success ? const Color(0xFF1F2B1F) : const Color(0xFF341C1C),
        content: Text(result.message),
      ),
    );
  }

  @override
  void dispose() {
    _orderBookSubscription?.cancel();
    _tradeTapeSubscription?.cancel();
    unawaited(_gateway.unsubscribeQuoteDetail(widget.symbol));
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        backgroundColor: AppColors.background,
        appBar: AppBar(
          backgroundColor: AppColors.surface,
          foregroundColor: AppColors.textPrimary,
          elevation: 0,
          titleSpacing: 12,
          title: Text('${widget.symbol} ${widget.name}'),
        ),
        bottomNavigationBar: SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
            child: _StockDetailActionBarSection(
              key: const Key('stock-detail-action-bar'),
              submitting: _submitting,
              onBuy: () => _submitTrade('BUY'),
              onSell: () => _submitTrade('SELL'),
            ),
          ),
        ),
        body: SafeArea(
          child: LayoutBuilder(
            builder: (context, constraints) {
              final availableHeight = constraints.maxHeight - 12;
              final headerHeight = (availableHeight * 0.15).clamp(110.0, 160.0);
              final chartHeight = (availableHeight * 0.30).clamp(220.0, 360.0);

              return Padding(
                padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
                child: Column(
                  children: [
                    SizedBox(
                      height: headerHeight,
                      child: _StockDetailHeaderSection(
                        key: const Key('stock-detail-header'),
                        symbol: widget.symbol,
                        name: widget.name,
                        summary: _summary,
                      ),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      height: chartHeight,
                      child: _StockDetailChartTabsSection(
                        key: const Key('stock-detail-chart-tabs'),
                        summary: _summary,
                        trendPoints: _trendPoints,
                        dailyBars: _dailyBars,
                      ),
                    ),
                    const SizedBox(height: 12),
                    Expanded(
                      child: _StockDetailQuotePanelsSection(
                        key: const Key('stock-detail-quote-panels'),
                        asks: _asks,
                        bids: _bids,
                        tradeTapeRows: _tradeTapeRows,
                      ),
                    ),
                  ],
                ),
              );
            },
          ),
        ),
      ),
    );
  }

  _QuoteSummary _mockSummary() {
    return const _QuoteSummary(
      lastPrice: 504.0,
      change: 4.0,
      changePercent: 0.80,
      open: 500.0,
      high: 509.0,
      low: 499.0,
      previousClose: 500.0,
      volume: 11222,
    );
  }

  List<CandleBar> _mockDailyBars() {
    return <CandleBar>[
      CandleBar(time: DateTime(2026, 3, 30), open: 507, high: 511, low: 505, close: 509, volume: 21234),
      CandleBar(time: DateTime(2026, 3, 31), open: 509, high: 512, low: 506, close: 510, volume: 22145),
      CandleBar(time: DateTime(2026, 4, 1), open: 509, high: 511, low: 503, close: 504, volume: 25444),
      CandleBar(time: DateTime(2026, 4, 2), open: 503, high: 506, low: 498, close: 500, volume: 24412),
      CandleBar(time: DateTime(2026, 4, 3), open: 500, high: 505, low: 499, close: 504, volume: 11222),
    ];
  }

  List<IntradayTrendPoint> _fallbackTrendPoints(double referencePrice) {
    return <IntradayTrendPoint>[
      IntradayTrendPoint(timeLabel: '09:00', price: referencePrice),
      IntradayTrendPoint(timeLabel: '09:30', price: referencePrice - 1.5),
      IntradayTrendPoint(timeLabel: '10:30', price: referencePrice + 0.5),
      IntradayTrendPoint(timeLabel: '11:30', price: referencePrice + 2.0),
      IntradayTrendPoint(timeLabel: '12:30', price: referencePrice + 1.2),
      IntradayTrendPoint(timeLabel: '13:30', price: referencePrice + 4.0),
    ];
  }
}

class _StockDetailHeaderSection extends StatelessWidget {
  const _StockDetailHeaderSection({
    super.key,
    required this.symbol,
    required this.name,
    required this.summary,
  });

  final String symbol;
  final String name;
  final _QuoteSummary summary;

  @override
  Widget build(BuildContext context) {
    final changeColor = _tone(summary.change);
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: _panelDecoration(),
      child: SingleChildScrollView(
        physics: const ClampingScrollPhysics(),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '$symbol $name',
                        style: const TextStyle(
                          color: AppColors.textPrimary,
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        '個股總覽',
                        style: TextStyle(
                          color: AppColors.textSecondary,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
                Text(
                  summary.lastPrice.toStringAsFixed(2),
                  style: TextStyle(
                    color: changeColor,
                    fontSize: 30,
                    fontWeight: FontWeight.w800,
                    fontFeatures: const <ui.FontFeature>[ui.FontFeature.tabularFigures()],
                  ),
                ),
                const SizedBox(width: 14),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      _signed(summary.change),
                      style: TextStyle(
                        color: changeColor,
                        fontSize: 16,
                        fontWeight: FontWeight.w800,
                        fontFeatures: const <ui.FontFeature>[ui.FontFeature.tabularFigures()],
                      ),
                    ),
                    Text(
                      '${summary.changePercent >= 0 ? '+' : ''}${summary.changePercent.toStringAsFixed(2)}%',
                      style: TextStyle(
                        color: changeColor,
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        fontFeatures: const <ui.FontFeature>[ui.FontFeature.tabularFigures()],
                      ),
                    ),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(child: _MetricCell(label: '開', value: summary.open.toStringAsFixed(2), tone: Colors.white)),
                Expanded(child: _MetricCell(label: '高', value: summary.high.toStringAsFixed(2), tone: AppColors.upRed)),
                Expanded(child: _MetricCell(label: '低', value: summary.low.toStringAsFixed(2), tone: AppColors.downGreen)),
                Expanded(
                  child: _MetricCell(
                    label: '收',
                    value: summary.previousClose.toStringAsFixed(2),
                    tone: AppColors.flatYellow,
                  ),
                ),
                Expanded(child: _MetricCell(label: '量', value: '${summary.volume}', tone: Colors.white)),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _StockDetailChartTabsSection extends StatelessWidget {
  const _StockDetailChartTabsSection({
    super.key,
    required this.summary,
    required this.trendPoints,
    required this.dailyBars,
  });

  final _QuoteSummary summary;
  final List<IntradayTrendPoint> trendPoints;
  final List<CandleBar> dailyBars;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: _panelDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const TabBar(
            labelColor: AppColors.textPrimary,
            unselectedLabelColor: AppColors.textSecondary,
            indicatorColor: AppColors.upRed,
            tabs: [
              Tab(text: '走勢圖'),
              Tab(text: 'K線圖'),
              Tab(text: '技術指標'),
            ],
          ),
          const SizedBox(height: 10),
          Expanded(
            child: TabBarView(
              children: [
                IntradayTrendChart(
                  points: trendPoints,
                  referencePrice: summary.previousClose,
                ),
                StockKChartPanel(dailyBars: dailyBars),
                const _TechnicalIndicatorPlaceholder(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _TechnicalIndicatorPlaceholder extends StatelessWidget {
  const _TechnicalIndicatorPlaceholder();

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF0F141A),
        border: Border.all(color: AppColors.divider),
      ),
      child: const Center(
        child: Text(
          '技術指標區預留給 RSI、MACD、KD 等分析內容',
          style: TextStyle(
            color: AppColors.textSecondary,
            fontSize: 13,
          ),
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

class _StockDetailQuotePanelsSection extends StatelessWidget {
  const _StockDetailQuotePanelsSection({
    super.key,
    required this.asks,
    required this.bids,
    required this.tradeTapeRows,
  });

  final List<OrderBookLevel> asks;
  final List<OrderBookLevel> bids;
  final List<TradeTapeRow> tradeTapeRows;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(child: _OrderBookPanel(asks: asks, bids: bids)),
        const SizedBox(width: 12),
        Expanded(child: _TimeAndSalesPanel(rows: tradeTapeRows)),
      ],
    );
  }
}

class _StockDetailActionBarSection extends StatelessWidget {
  const _StockDetailActionBarSection({
    super.key,
    required this.submitting,
    required this.onBuy,
    required this.onSell,
  });

  final bool submitting;
  final VoidCallback onBuy;
  final VoidCallback onSell;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: _panelDecoration(),
      child: Row(
        children: [
          _ActionIconButton(
            icon: Icons.star_border,
            label: '自選',
            onPressed: () {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('已加入自選功能預留')),
              );
            },
          ),
          const SizedBox(width: 10),
          _ActionIconButton(
            icon: Icons.notifications_none,
            label: '警示',
            onPressed: () {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('警示設定功能預留')),
              );
            },
          ),
          const Spacer(),
          Expanded(
            child: FilledButton(
              onPressed: submitting ? null : onBuy,
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.upRed,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              ),
              child: Text(submitting ? '送出中' : '買進'),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: FilledButton(
              onPressed: submitting ? null : onSell,
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.downGreen,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              ),
              child: Text(submitting ? '送出中' : '賣出'),
            ),
          ),
        ],
      ),
    );
  }
}

class _ActionIconButton extends StatelessWidget {
  const _ActionIconButton({
    required this.icon,
    required this.label,
    required this.onPressed,
  });

  final IconData icon;
  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return TextButton.icon(
      onPressed: onPressed,
      icon: Icon(icon, color: AppColors.textPrimary, size: 20),
      label: Text(
        label,
        style: const TextStyle(
          color: AppColors.textPrimary,
          fontWeight: FontWeight.w700,
        ),
      ),
      style: TextButton.styleFrom(
        backgroundColor: AppColors.surface,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: const BorderSide(color: AppColors.divider),
        ),
      ),
    );
  }
}

class _MetricCell extends StatelessWidget {
  const _MetricCell({
    required this.label,
    required this.value,
    required this.tone,
  });

  final String label;
  final String value;
  final Color tone;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: const BoxDecoration(
        border: Border(
          left: BorderSide(color: Color(0xFF212A36)),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 10),
          ),
          const SizedBox(height: 2),
          Text(
            value,
            style: TextStyle(
              color: tone,
              fontSize: 13,
              fontWeight: FontWeight.w700,
              fontFeatures: const <ui.FontFeature>[ui.FontFeature.tabularFigures()],
            ),
          ),
        ],
      ),
    );
  }
}

class _OrderBookPanel extends StatelessWidget {
  const _OrderBookPanel({
    required this.asks,
    required this.bids,
  });

  final List<OrderBookLevel> asks;
  final List<OrderBookLevel> bids;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: _panelDecoration(),
      child: Column(
        children: [
          const _PanelHeader(title: '最佳五檔'),
          const _OrderBookHeaderRow(),
          Expanded(
            child: asks.isEmpty && bids.isEmpty
                ? const Center(
                    child: Text(
                      '暫無即時五檔資料',
                      style: TextStyle(color: AppColors.textSecondary, fontSize: 12),
                    ),
                  )
                : ListView(
                    padding: EdgeInsets.zero,
                    children: [
                      ...asks.map((level) => _OrderBookRow(level: level, isAsk: true)),
                      Container(
                        color: const Color(0xFF10141A),
                        padding: const EdgeInsets.symmetric(vertical: 6),
                        alignment: Alignment.center,
                        child: const Text(
                          '賣方 / 買方',
                          style: TextStyle(color: AppColors.textSecondary, fontSize: 11),
                        ),
                      ),
                      ...bids.map((level) => _OrderBookRow(level: level, isAsk: false)),
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}

class _OrderBookHeaderRow extends StatelessWidget {
  const _OrderBookHeaderRow();

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 32,
      color: const Color(0xFF11161D),
      padding: const EdgeInsets.symmetric(horizontal: 10),
      child: const Row(
        children: [
          Expanded(child: Text('檔位', style: _headerStyle, textAlign: TextAlign.left)),
          Expanded(child: Text('價格', style: _headerStyle, textAlign: TextAlign.right)),
          Expanded(child: Text('張數', style: _headerStyle, textAlign: TextAlign.right)),
        ],
      ),
    );
  }
}

class _OrderBookRow extends StatelessWidget {
  const _OrderBookRow({
    required this.level,
    required this.isAsk,
  });

  final OrderBookLevel level;
  final bool isAsk;

  @override
  Widget build(BuildContext context) {
    final priceColor = isAsk ? AppColors.upRed : AppColors.downGreen;
    return Container(
      height: 32,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0xFF212A36))),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              '${isAsk ? '賣' : '買'}${level.level}',
              style: const TextStyle(color: AppColors.textPrimary, fontSize: 12),
            ),
          ),
          Expanded(
            child: Text(
              level.price.toStringAsFixed(2),
              textAlign: TextAlign.right,
              style: TextStyle(
                color: priceColor,
                fontSize: 12,
                fontWeight: FontWeight.w700,
                fontFeatures: const <ui.FontFeature>[ui.FontFeature.tabularFigures()],
              ),
            ),
          ),
          Expanded(
            child: Text(
              '${level.volume}',
              textAlign: TextAlign.right,
              style: const TextStyle(
                color: Color(0xFFCCD6E0),
                fontSize: 12,
                fontFeatures: <ui.FontFeature>[ui.FontFeature.tabularFigures()],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TimeAndSalesPanel extends StatelessWidget {
  const _TimeAndSalesPanel({required this.rows});

  final List<TradeTapeRow> rows;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: _panelDecoration(),
      child: Column(
        children: [
          const _PanelHeader(title: '分時明細'),
          Container(
            height: 32,
            color: const Color(0xFF11161D),
            padding: const EdgeInsets.symmetric(horizontal: 10),
            child: const Row(
              children: [
                Expanded(child: Text('時間', style: _headerStyle, textAlign: TextAlign.left)),
                Expanded(child: Text('價格', style: _headerStyle, textAlign: TextAlign.right)),
                Expanded(child: Text('單量', style: _headerStyle, textAlign: TextAlign.right)),
                Expanded(child: Text('盤別', style: _headerStyle, textAlign: TextAlign.right)),
              ],
            ),
          ),
          Expanded(
            child: rows.isEmpty
                ? const Center(
                    child: Text(
                      '暫無逐筆成交資料',
                      style: TextStyle(color: AppColors.textSecondary, fontSize: 12),
                    ),
                  )
                : ListView.builder(
                    itemCount: rows.length,
                    itemBuilder: (context, index) {
                      final row = rows[index];
                      final priceColor = switch (row.side) {
                        TradeSide.outer => AppColors.upRed,
                        TradeSide.inner => AppColors.downGreen,
                        TradeSide.neutral => AppColors.flatYellow,
                      };
                      final sideText = switch (row.side) {
                        TradeSide.outer => '外盤',
                        TradeSide.inner => '內盤',
                        TradeSide.neutral => '平盤',
                      };

                      return Container(
                        height: 32,
                        padding: const EdgeInsets.symmetric(horizontal: 10),
                        decoration: const BoxDecoration(
                          border: Border(bottom: BorderSide(color: Color(0xFF212A36))),
                        ),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text(
                                row.time,
                                style: const TextStyle(
                                  color: Color(0xFFCCD6E0),
                                  fontSize: 12,
                                  fontFeatures: <ui.FontFeature>[ui.FontFeature.tabularFigures()],
                                ),
                              ),
                            ),
                            Expanded(
                              child: Text(
                                row.price.toStringAsFixed(2),
                                textAlign: TextAlign.right,
                                style: TextStyle(
                                  color: priceColor,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                  fontFeatures: const <ui.FontFeature>[ui.FontFeature.tabularFigures()],
                                ),
                              ),
                            ),
                            Expanded(
                              child: Text(
                                '${row.volume}',
                                textAlign: TextAlign.right,
                                style: const TextStyle(
                                  color: AppColors.textPrimary,
                                  fontSize: 12,
                                  fontFeatures: <ui.FontFeature>[ui.FontFeature.tabularFigures()],
                                ),
                              ),
                            ),
                            Expanded(
                              child: Text(
                                sideText,
                                textAlign: TextAlign.right,
                                style: TextStyle(
                                  color: priceColor,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

class _PanelHeader extends StatelessWidget {
  const _PanelHeader({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 36,
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      alignment: Alignment.centerLeft,
      decoration: const BoxDecoration(
        color: AppColors.surface,
        border: Border(bottom: BorderSide(color: AppColors.divider)),
      ),
      child: Text(
        title,
        style: const TextStyle(
          color: AppColors.textPrimary,
          fontSize: 13,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

const TextStyle _headerStyle = TextStyle(
  color: AppColors.textSecondary,
  fontSize: 11,
  fontWeight: FontWeight.w700,
);

BoxDecoration _panelDecoration() {
  return BoxDecoration(
    color: AppColors.surfaceAlt,
    border: Border.all(color: AppColors.divider),
  );
}

Color _tone(double value) {
  if (value > 0) return AppColors.upRed;
  if (value < 0) return AppColors.downGreen;
  return AppColors.flatYellow;
}

String _signed(double value) {
  final prefix = value > 0 ? '+' : '';
  return '$prefix${value.toStringAsFixed(2)}';
}

class _QuoteSummary {
  const _QuoteSummary({
    required this.lastPrice,
    required this.change,
    required this.changePercent,
    required this.open,
    required this.high,
    required this.low,
    required this.previousClose,
    required this.volume,
  });

  final double lastPrice;
  final double change;
  final double changePercent;
  final double open;
  final double high;
  final double low;
  final double previousClose;
  final int volume;
}
