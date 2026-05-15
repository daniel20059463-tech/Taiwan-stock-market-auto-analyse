# -*- coding: utf-8 -*-
"""
台股模擬交易儀表板
執行：python run_dashboard.py
瀏覽：http://localhost:8080
"""
from __future__ import annotations
import json, os, glob, datetime, re
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
POSITIONS_PATH = os.path.join(BASE_DIR, "data", "paper_positions.json")
FLOW_CACHE_PATH  = os.path.join(BASE_DIR, "data", "flow_cache.json")
PRICE_CACHE_PATH = os.path.join(BASE_DIR, "data", "daily_price_cache.json")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
PORT = 8088

# 排除清單（指定不顯示的 log）
LOG_EXCLUDE = {"eod_20260513_215104.log"}

# log 分類規則：(顯示名稱, glob 樣式)
LOG_CATEGORIES = [
    ("盤前掃描",    "premarket_*.log"),
    ("盤後報告",    "eod_*.log"),
    ("盤中監控",    "run_live_*.out.log"),
    ("籌碼更新",    "institutional_flow_refresh_*.log"),
]


def load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_log_cards() -> list[dict]:
    """每個分類只取最新一個 log，且排除黑名單。"""
    result = []
    for label, pattern in LOG_CATEGORIES:
        files = sorted(
            glob.glob(os.path.join(LOGS_DIR, pattern)),
            key=os.path.getmtime,
            reverse=True,
        )
        # 跳過黑名單
        files = [f for f in files if os.path.basename(f) not in LOG_EXCLUDE]
        if not files:
            continue
        fp = files[0]
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%m/%d %H:%M")
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            # 去掉空行後取最後 25 行
            lines = [l for l in lines if l.strip()]
            tail = "".join(lines[-25:]).rstrip()
        except Exception:
            tail = "（無法讀取）"
        result.append({"label": label, "name": os.path.basename(fp), "mtime": mtime, "tail": tail})
    return result


def get_top_flow(n: int = 10) -> list[dict]:
    fc = load_json(FLOW_CACHE_PATH)
    rows = [
        {
            "symbol": sym,
            "name": d.get("name", ""),
            "flow_score": d.get("flow_score", 0),
            "trust":   d.get("trust", 0),
            "foreign": d.get("foreign", 0),
        }
        for sym, d in fc.get("stocks", {}).items()
    ]
    rows.sort(key=lambda x: x["flow_score"], reverse=True)
    return rows[:n]


def get_flow_date() -> str:
    return load_json(FLOW_CACHE_PATH).get("date", "未知")


def fmt_num(n: float, decimals: int = 0) -> str:
    return f"{n:,.{decimals}f}"


def build_html() -> str:
    pos_data  = load_json(POSITIONS_PATH)
    positions = pos_data.get("positions", {})
    capital   = pos_data.get("capital_total",    1_000_000)
    deployed  = pos_data.get("capital_deployed", 0)
    cash      = pos_data.get("capital_cash",     capital)
    trade_date = pos_data.get("trade_date", "—")
    now_str   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    deploy_pct = deployed / capital * 100 if capital else 0

    pc = load_json(PRICE_CACHE_PATH)

    # ── 持倉列 ────────────────────────────────────────────────
    pos_rows = ""
    for sym, p in positions.items():
        side    = p.get("side", "long")
        entry   = p.get("entry_price", 0)
        shares  = p.get("shares", 0)
        stop    = p.get("stop_price", 0)
        trail   = p.get("trail_stop_price", stop)
        target  = p.get("target_price", 0)
        batch   = p.get("partial_exit_batch", 0)
        name    = p.get("name", sym)
        sc      = p.get("final_score", 0)

        # 最新價（從價格快取取最近一天收盤）
        sym_bars = pc.get(sym, {})
        if sym_bars:
            latest_bar = sym_bars[sorted(sym_bars)[-1]]
            cur_price  = latest_bar.get("close", entry)
        else:
            cur_price = entry

        if side == "long":
            pnl     = (cur_price - entry) * shares
            pnl_pct = (cur_price - entry) / entry * 100 if entry else 0
        else:
            pnl     = (entry - cur_price) * shares
            pnl_pct = (entry - cur_price) / entry * 100 if entry else 0

        pnl_color  = "#00e676" if pnl >= 0 else "#ff3366"
        side_label = "多" if side == "long" else "空"
        side_color = "#00e676" if side == "long" else "#ff3366"
        batch_labels = ["持倉中", "已出第一批（50%）", "已出第二批（30%）"]
        batch_label  = batch_labels[min(batch, 2)]

        pos_rows += f"""
        <tr>
          <td><span class="tag" style="color:{side_color}">{side_label}</span>&nbsp;{sym}&nbsp;{name}</td>
          <td class="mono">{entry:.2f}</td>
          <td class="mono">{cur_price:.2f}</td>
          <td class="mono" style="color:{pnl_color}">{pnl:+,.0f}（{pnl_pct:+.2f}%）</td>
          <td class="mono">{shares // 1000} 張</td>
          <td class="mono">{stop:.2f}&nbsp;/&nbsp;{trail:.2f}</td>
          <td class="mono">{target:.2f}</td>
          <td><span class="badge">{batch_label}</span></td>
          <td class="mono muted">{sc:.3f}</td>
        </tr>"""

    if not pos_rows:
        pos_rows = '<tr><td colspan="9" style="text-align:center;color:#555;padding:24px">目前無持倉</td></tr>'

    # ── 籌碼列 ────────────────────────────────────────────────
    flow_date = get_flow_date()
    flow_rows = ""
    for r in get_top_flow():
        bar_w = int(min(r["flow_score"] * 100, 100))
        t_color = "#00e676" if r["trust"]   > 0 else "#ff3366"
        f_color = "#00e676" if r["foreign"] > 0 else "#ff3366"
        flow_rows += f"""
        <tr>
          <td class="mono">{r['symbol']}</td>
          <td>{r['name']}</td>
          <td>
            <div style="display:flex;align-items:center;gap:8px">
              <div style="width:70px;height:5px;background:#252528;border-radius:3px">
                <div style="width:{bar_w}%;height:100%;background:#00f5ff;border-radius:3px"></div>
              </div>
              <span class="mono" style="color:#00f5ff">{r['flow_score']:.3f}</span>
            </div>
          </td>
          <td class="mono" style="color:{t_color}">{r['trust']/1000:+,.0f}k</td>
          <td class="mono" style="color:{f_color}">{r['foreign']/1000:+,.0f}k</td>
        </tr>"""

    # ── Log 卡片 ──────────────────────────────────────────────
    log_cards_html = ""
    for card in get_log_cards():
        log_cards_html += f"""
        <div class="log-card">
          <div class="log-header">
            <div>
              <span class="log-label">{card['label']}</span>
              <span class="mono muted" style="font-size:11px;margin-left:8px">{card['name']}</span>
            </div>
            <span class="muted" style="font-size:11px">{card['mtime']}</span>
          </div>
          <pre class="log-body">{card['tail']}</pre>
        </div>"""
    if not log_cards_html:
        log_cards_html = '<div class="muted" style="padding:16px">尚無執行記錄</div>'

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>台股模擬交易儀表板</title>
<meta http-equiv="refresh" content="60">
<style>
  :root {{
    --bg:     #0e0e10;
    --panel:  #16161a;
    --border: #2a2a2e;
    --text:   #f0f0f0;
    --muted:  #6e6e7a;
    --accent: #00f5ff;
    --green:  #00e676;
    --red:    #ff3366;
    --gold:   #d4af37;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--text);
         font-family:'Segoe UI','PingFang TC','Microsoft JhengHei',sans-serif; font-size:14px; }}

  /* 頂欄 */
  .topbar {{
    background:var(--panel); border-bottom:1px solid var(--border);
    padding:12px 24px; display:flex; align-items:center; justify-content:space-between;
  }}
  .topbar h1 {{ font-size:17px; font-weight:700; color:var(--accent); letter-spacing:.04em; }}
  .topbar .meta {{ color:var(--muted); font-size:12px; }}

  .container {{ max-width:1380px; margin:0 auto; padding:20px 24px; }}

  /* 資金卡 */
  .grid-3 {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-bottom:24px; }}
  .stat-card {{
    background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:18px 22px;
  }}
  .stat-card .label {{ color:var(--muted); font-size:11px; letter-spacing:.1em;
                        text-transform:uppercase; margin-bottom:8px; }}
  .stat-card .value {{ font-size:22px; font-weight:700;
                        font-family:'Cascadia Code','Consolas',monospace; }}
  .stat-card .sub   {{ color:var(--muted); font-size:12px; margin-top:4px; }}
  .progress-bar  {{ width:100%; height:4px; background:#252528; border-radius:2px; margin-top:10px; }}
  .progress-fill {{ height:100%; border-radius:2px;
                    background:linear-gradient(90deg,#00f5ff,#00e676); transition:.3s; }}

  /* 區塊標題 */
  .section {{ margin-bottom:26px; }}
  .section-title {{
    font-size:12px; font-weight:600; letter-spacing:.1em; text-transform:uppercase;
    color:var(--muted); margin-bottom:12px; padding-bottom:8px;
    border-bottom:1px solid var(--border);
  }}

  /* 卡片 / 表格 */
  .card {{ background:var(--panel); border:1px solid var(--border); border-radius:8px; overflow:hidden; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{
    background:#1c1c20; color:var(--muted); font-size:11px; letter-spacing:.08em;
    text-transform:uppercase; padding:10px 14px; text-align:left; font-weight:500;
    border-bottom:1px solid var(--border);
  }}
  td {{ padding:11px 14px; border-bottom:1px solid rgba(255,255,255,.04); }}
  tr:last-child td {{ border-bottom:none; }}
  tr:hover td {{ background:rgba(255,255,255,.025); }}

  .mono  {{ font-family:'Cascadia Code','Consolas',monospace; }}
  .muted {{ color:var(--muted); }}
  .tag   {{ font-weight:700; font-size:13px; }}
  .badge {{
    background:rgba(255,255,255,.05); border:1px solid var(--border);
    border-radius:4px; padding:2px 8px; font-size:11px; color:var(--muted);
  }}

  /* 雙欄 */
  .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}

  /* 系統狀態 */
  .status-table td {{ padding:8px 16px 8px 0; }}
  .dot {{ width:7px; height:7px; border-radius:50%; display:inline-block; margin-right:5px; }}
  .dot-green {{ background:var(--green); box-shadow:0 0 5px var(--green); }}
  .dot-gold  {{ background:var(--gold);  box-shadow:0 0 5px var(--gold); }}

  /* Log 卡片 */
  .log-card {{ background:var(--panel); border:1px solid var(--border); border-radius:8px;
               margin-bottom:12px; overflow:hidden; }}
  .log-header {{
    display:flex; justify-content:space-between; align-items:center;
    padding:10px 14px; border-bottom:1px solid var(--border); background:#1c1c20;
  }}
  .log-label {{ color:var(--accent); font-size:12px; font-weight:600; }}
  .log-body {{
    font-family:'Cascadia Code','Consolas',monospace; font-size:11px; color:#999;
    padding:12px 14px; white-space:pre-wrap; word-break:break-all;
    max-height:220px; overflow-y:auto; background:#0b0b0d; line-height:1.6;
  }}

  .footer {{ color:var(--muted); font-size:11px; text-align:right; margin-top:16px; }}
  .footer a {{ color:var(--muted); }}

  @media(max-width:900px) {{
    .grid-3,.grid-2 {{ grid-template-columns:1fr; }}
  }}
</style>
</head>
<body>

<div class="topbar">
  <h1>▲ 台股模擬交易儀表板</h1>
  <div class="meta">更新時間：{now_str}　交易日期：{trade_date}</div>
</div>

<div class="container">

  <!-- 資金概覽 -->
  <div class="grid-3">
    <div class="stat-card">
      <div class="label">總資金（模擬）</div>
      <div class="value" style="color:var(--accent)">{fmt_num(capital)}</div>
      <div class="sub">新台幣</div>
    </div>
    <div class="stat-card">
      <div class="label">已動用</div>
      <div class="value" style="color:var(--green)">{fmt_num(deployed)}</div>
      <div class="sub">占比 {deploy_pct:.1f}%</div>
      <div class="progress-bar">
        <div class="progress-fill" style="width:{min(deploy_pct,100):.1f}%"></div>
      </div>
    </div>
    <div class="stat-card">
      <div class="label">可用現金</div>
      <div class="value">{fmt_num(cash)}</div>
      <div class="sub">持倉 {len(positions)} 檔</div>
    </div>
  </div>

  <!-- 持倉明細 -->
  <div class="section">
    <div class="section-title">持倉明細</div>
    <div class="card">
      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>成本</th>
            <th>現價</th>
            <th>損益</th>
            <th>張數</th>
            <th>停損 / 追蹤停損</th>
            <th>目標價</th>
            <th>分批狀態</th>
            <th>評分</th>
          </tr>
        </thead>
        <tbody>{pos_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="grid-2">

    <!-- 籌碼排行 -->
    <div class="section">
      <div class="section-title">籌碼評分前十名　<span style="font-weight:400;text-transform:none">（{flow_date}）</span></div>
      <div class="card">
        <table>
          <thead>
            <tr>
              <th>代號</th>
              <th>名稱</th>
              <th>評分</th>
              <th>投信</th>
              <th>外資</th>
            </tr>
          </thead>
          <tbody>{flow_rows}</tbody>
        </table>
      </div>
    </div>

    <!-- 系統狀態 -->
    <div class="section">
      <div class="section-title">系統狀態</div>
      <div class="card" style="padding:18px">
        <table class="status-table">
          <tr>
            <td class="muted">交易模式</td>
            <td><span class="dot dot-gold"></span><span style="color:var(--gold);font-weight:600">模擬交易（Paper Trading）</span></td>
          </tr>
          <tr>
            <td class="muted">策略名稱</td>
            <td><span class="mono" style="color:var(--accent)">retail_flow_swing</span></td>
          </tr>
          <tr>
            <td class="muted">籌碼日期</td>
            <td class="mono">{flow_date}</td>
          </tr>
          <tr>
            <td class="muted">盤前掃描</td>
            <td><span class="dot dot-green"></span>每日 08:50 自動執行</td>
          </tr>
          <tr>
            <td class="muted">盤中監控</td>
            <td><span class="dot dot-green"></span>每 30 分鐘執行一次</td>
          </tr>
          <tr>
            <td class="muted">盤後報告</td>
            <td><span class="dot dot-green"></span>每日 14:30 自動執行</td>
          </tr>
          <tr>
            <td class="muted">籌碼更新</td>
            <td><span class="dot dot-green"></span>每日 08:50 自動更新</td>
          </tr>
        </table>
      </div>
    </div>

  </div>

  <!-- 最新執行記錄（每類僅顯示最新一筆）-->
  <div class="section">
    <div class="section-title">最新執行記錄</div>
    {log_cards_html}
  </div>

  <div class="footer">每 60 秒自動刷新　｜　<a href="/">手動刷新</a></div>
</div>

</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = build_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/positions":
            body = json.dumps(load_json(POSITIONS_PATH), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass  # 靜音 HTTP 請求記錄


if __name__ == "__main__":
    print(f"台股模擬交易儀表板啟動：http://localhost:{PORT}")
    print("按 Ctrl+C 停止")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
