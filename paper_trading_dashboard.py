"""
Traqo — RAG Powered Quantitative Candlestick Intelligence by Prateek Tyagi
================================================
Zero external dependencies. Uses Python's built-in http.server.
All HTML/CSS/JS is server-rendered — no React, no Flask, no build step.

Run:
    python paper_trading_dashboard.py
    → Opens http://localhost:8521
"""

import os
import sys
import json
import sqlite3
import webbrowser
import subprocess
import urllib.parse
import threading
from datetime import date, datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

DB_PATH = "paper_trades/paper_trades.db"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# DATABASE QUERIES
# ============================================================
def get_db():
    conn = sqlite3.connect(os.path.join(SCRIPT_DIR, DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def q_stats():
    c = get_db()
    open_n = c.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0]
    closed_n = c.execute("SELECT COUNT(*) FROM trades WHERE status!='OPEN'").fetchone()[0]
    wins = c.execute("SELECT COUNT(*) FROM trades WHERE status IN ('WON','EXPIRED_WIN')").fetchone()[0]
    losses = c.execute("SELECT COUNT(*) FROM trades WHERE status IN ('LOST','EXPIRED_LOSS')").fetchone()[0]
    avg_w = c.execute("SELECT AVG(actual_return_pct) FROM trades WHERE status IN ('WON','EXPIRED_WIN')").fetchone()[0] or 0
    avg_l = c.execute("SELECT AVG(actual_return_pct) FROM trades WHERE status IN ('LOST','EXPIRED_LOSS')").fetchone()[0] or 0
    tot_ret = c.execute("SELECT SUM(actual_return_pct) FROM trades WHERE status!='OPEN'").fetchone()[0] or 0
    wr = (wins / closed_n * 100) if closed_n else 0
    pf = (abs(avg_w * wins) / abs(avg_l * losses)) if (losses and avg_l) else 0
    last_scan = c.execute("SELECT MAX(scan_date) FROM scan_log").fetchone()[0] or "Never"
    today_entered = c.execute("SELECT COUNT(*) FROM trades WHERE entry_date=?", (date.today().isoformat(),)).fetchone()[0]
    c.close()
    return {
        "open_trades": open_n, "closed_trades": closed_n, "total_trades": open_n + closed_n,
        "wins": wins, "losses": losses, "win_rate": round(wr, 1),
        "avg_win_pct": round(avg_w, 2), "avg_loss_pct": round(avg_l, 2),
        "profit_factor": round(pf, 2), "total_return_pct": round(tot_ret, 2),
        "last_scan": last_scan, "today_entered": today_entered,
    }


def q_open_trades():
    c = get_db()
    rows = [dict(r) for r in c.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY entry_date DESC, ticker").fetchall()]
    c.close()
    return rows


def q_closed_trades():
    c = get_db()
    rows = [dict(r) for r in c.execute("SELECT * FROM trades WHERE status!='OPEN' ORDER BY exit_date DESC LIMIT 200").fetchall()]
    c.close()
    return rows


def q_today_trades():
    c = get_db()
    today_str = date.today().isoformat()
    rows = [dict(r) for r in c.execute("SELECT * FROM trades WHERE entry_date=? ORDER BY ticker, horizon_days", (today_str,)).fetchall()]
    if not rows:
        last_date = c.execute("SELECT MAX(entry_date) FROM trades").fetchone()[0]
        if last_date:
            rows = [dict(r) for r in c.execute("SELECT * FROM trades WHERE entry_date=? ORDER BY ticker, horizon_days", (last_date,)).fetchall()]
    c.close()
    return rows


def q_stats_by_horizon():
    c = get_db()
    rows = [dict(r) for r in c.execute("""
        SELECT horizon_days, horizon_label,
               COUNT(*) as total,
               SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN 1 ELSE 0 END) as losses,
               AVG(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN actual_return_pct END) as avg_win,
               AVG(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN actual_return_pct END) as avg_loss,
               SUM(actual_return_pct) as total_ret
        FROM trades WHERE status!='OPEN'
        GROUP BY horizon_days ORDER BY horizon_days
    """).fetchall()]
    for r in rows:
        t = r["wins"] + r["losses"]
        r["win_rate"] = round(r["wins"] / t * 100, 1) if t else 0
    c.close()
    return rows


def q_stats_by_pattern():
    c = get_db()
    rows = [dict(r) for r in c.execute("""
        SELECT patterns,
               COUNT(*) as total,
               SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN 1 ELSE 0 END) as losses,
               AVG(actual_return_pct) as avg_ret
        FROM trades WHERE status!='OPEN'
        GROUP BY patterns ORDER BY total DESC LIMIT 20
    """).fetchall()]
    for r in rows:
        t = r["wins"] + r["losses"]
        r["win_rate"] = round(r["wins"] / t * 100, 1) if t else 0
    c.close()
    return rows


def q_stats_by_stock():
    c = get_db()
    rows = [dict(r) for r in c.execute("""
        SELECT ticker,
               COUNT(*) as total,
               SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN 1 ELSE 0 END) as losses,
               AVG(actual_return_pct) as avg_ret,
               SUM(actual_return_pct) as total_ret
        FROM trades WHERE status!='OPEN'
        GROUP BY ticker ORDER BY total DESC LIMIT 30
    """).fetchall()]
    for r in rows:
        t = r["wins"] + r["losses"]
        r["win_rate"] = round(r["wins"] / t * 100, 1) if t else 0
    c.close()
    return rows


def q_scan_log():
    c = get_db()
    rows = [dict(r) for r in c.execute("SELECT * FROM scan_log ORDER BY scan_date DESC LIMIT 30").fetchall()]
    c.close()
    return rows


def q_daily_summaries():
    c = get_db()
    rows = [dict(r) for r in c.execute("SELECT * FROM daily_summary ORDER BY report_date DESC LIMIT 60").fetchall()]
    c.close()
    return rows


def get_engine_log():
    log_path = os.path.join(SCRIPT_DIR, "paper_trades/logs/paper_trader.log")
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            return f.readlines()[-60:]
    return []


# ---- Live Engine Runner (background thread + polling) ----
_engine_state = {
    "running": False,
    "action": "",
    "output_lines": [],
    "done": False,
    "success": None,
    "started_at": None,
}
_engine_lock = threading.Lock()

STREAMLIT_NOISE = (
    "ScriptRunContext", "streamlit run", "Session state does not function",
    "missing ScriptRunContext", "warning can be ignored",
    "If you want to run a streamlit", "streamlit app",
)

def _is_noise(line: str) -> bool:
    return any(n in line for n in STREAMLIT_NOISE) or not line.strip()

def _engine_worker(action):
    global _engine_state
    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [sys.executable, os.path.join(SCRIPT_DIR, "paper_trader.py"), action],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=SCRIPT_DIR, env=env
        )
        for line in iter(proc.stdout.readline, ""):
            if not _is_noise(line):
                with _engine_lock:
                    _engine_state["output_lines"].append(line.rstrip())
        proc.stdout.close()
        ret = proc.wait(timeout=600)
        with _engine_lock:
            _engine_state["success"] = (ret == 0)
            _engine_state["done"] = True
            _engine_state["running"] = False
    except Exception as e:
        with _engine_lock:
            _engine_state["output_lines"].append(f"ERROR: {e}")
            _engine_state["success"] = False
            _engine_state["done"] = True
            _engine_state["running"] = False

def start_engine(action):
    global _engine_state
    with _engine_lock:
        if _engine_state["running"]:
            return False  # already running
        _engine_state = {
            "running": True,
            "action": action,
            "output_lines": [f"Starting engine: {action}..."],
            "done": False,
            "success": None,
            "started_at": datetime.now().isoformat(),
        }
    t = threading.Thread(target=_engine_worker, args=(action,), daemon=True)
    t.start()
    return True

def get_engine_status():
    with _engine_lock:
        return {
            "running": _engine_state["running"],
            "done": _engine_state["done"],
            "success": _engine_state["success"],
            "action": _engine_state["action"],
            "lines": list(_engine_state["output_lines"]),
            "started_at": _engine_state["started_at"],
        }


# ============================================================
# HTML HELPERS
# ============================================================
def _e(s):
    """Escape HTML."""
    if s is None:
        return "—"
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _price(v):
    if v is None:
        return "—"
    return f"₹{float(v):,.2f}"


def _pct(v, sign=True):
    if v is None:
        return "—"
    v = float(v)
    if sign and v > 0:
        return f"+{v:.2f}%"
    return f"{v:.2f}%"


def _date(d):
    if not d:
        return "—"
    try:
        return datetime.strptime(str(d), "%Y-%m-%d").strftime("%d %b %y")
    except Exception:
        return str(d)


def _ticker(t):
    return str(t).replace(".NS", "").replace(".BO", "") if t else ""


def _days_between(a, b):
    try:
        return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days
    except Exception:
        return 0


def _status_classes(s):
    m = {
        "OPEN": ("bg-blue-50 text-blue-700 border-blue-200", "Open"),
        "WON": ("bg-emerald-50 text-emerald-700 border-emerald-200", "Won"),
        "LOST": ("bg-red-50 text-red-700 border-red-200", "Lost"),
        "EXPIRED_WIN": ("bg-emerald-50 text-emerald-700 border-emerald-200", "Exp Win"),
        "EXPIRED_LOSS": ("bg-red-50 text-red-700 border-red-200", "Exp Loss"),
    }
    return m.get(s, ("bg-gray-100 text-gray-600", s))


# ============================================================
# HTML TEMPLATES
# ============================================================
def page_shell(title, active_tab, body_html):
    tabs = [
        ("dashboard", "Dashboard", "M4 5a1 1 0 011-1h4a1 1 0 011 1v5a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM14 5a1 1 0 011-1h4a1 1 0 011 1v2a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM4 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4zM14 12a1 1 0 011-1h4a1 1 0 011 1v7a1 1 0 01-1 1h-4a1 1 0 01-1-1v-7z"),
        ("signals", "Today's Signals", "M13 10V3L4 14h7v7l9-11h-7z"),
        ("positions", "Open Positions", "M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"),
        ("history", "Trade History", "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"),
        ("performance", "Performance", "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"),
        ("engine", "Engine Control", "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"),
    ]

    nav_items = ""
    for key, label, icon_path in tabs:
        is_active = key == active_tab
        cls = "bg-blue-50 text-blue-700 border border-blue-100" if is_active else "text-gray-500 hover:text-gray-800 hover:bg-gray-50"
        extra_icon = ""
        if key == "engine":
            extra_icon = f'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />'
        nav_items += f'''
        <a href="/{key}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all {cls}">
          <svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="{icon_path}" />{extra_icon}
          </svg>
          {label}
        </a>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_e(title)} — Traqo</title>
  <link rel="icon" type="image/png" href="data:image/png;base64,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">
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          fontFamily: {{ sans: ['Inter', 'sans-serif'] }},
        }}
      }}
    }}
  </script>
  <style>
    body {{ font-family: 'Inter', sans-serif; }}
    .scrollbar-thin::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    .scrollbar-thin::-webkit-scrollbar-track {{ background: transparent; }}
    .scrollbar-thin::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 3px; }}
    .glass {{ background: #ffffff; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
    @keyframes fade-in {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    .fade-in {{ animation: fade-in 0.25s ease-out; }}
    @keyframes pulse-dot {{ 0%,100% {{ box-shadow: 0 0 0 0 rgba(16,185,129,0.4); }} 50% {{ box-shadow: 0 0 0 6px rgba(16,185,129,0); }} }}
    .pulse-dot {{ animation: pulse-dot 2s infinite; }}
  </style>
</head>
<body class="bg-gray-50 text-gray-800 min-h-screen">
  <!-- Sidebar -->
  <aside class="fixed top-0 left-0 h-screen w-60 bg-white border-r border-gray-200 flex flex-col z-50 shadow-sm">
    <div class="px-5 py-5 border-b border-gray-200">
      <div class="flex items-center gap-3">
        <img src="data:image/png;base64,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" alt="Traqo" class="w-9 h-9 rounded-xl">
        <div>
          <div class="text-base font-bold text-gray-800">Traqo</div>
          <div class="text-[10px] text-blue-500 font-medium tracking-wide uppercase">Quantitative Candlestick Intelligence</div>
        </div>
      </div>
    </div>
    <nav class="flex-1 px-3 py-4 space-y-1 overflow-y-auto scrollbar-thin">
      {nav_items}
    </nav>
    <div class="px-4 py-4 border-t border-gray-200">
      <div class="flex items-center gap-2 text-xs text-gray-400 mb-2">
        <div class="w-2 h-2 rounded-full bg-emerald-500 pulse-dot"></div>
        System Online
      </div>
      <div class="text-[10px] text-gray-300">by Prateek Tyagi</div>
    </div>
  </aside>

  <!-- Main Content -->
  <main class="ml-60 min-h-screen flex flex-col">
    <div class="p-8 max-w-[1400px] mx-auto fade-in flex-1 w-full">
      {body_html}
    </div>
    <footer class="border-t border-gray-200 py-4 px-8 text-center">
      <p class="text-sm text-blue-400"><span class="font-bold text-blue-600">TRAQO</span> &mdash; RAG Powered Quantitative Candlestick Intelligence by <span class="font-medium text-blue-500">Prateek Tyagi</span></p>
    </footer>
  </main>
</body>
</html>'''


def stat_card(label, value, subtitle="", color="indigo"):
    color_map = {
        "indigo": "bg-white border-gray-200 shadow-sm",
        "green": "bg-white border-emerald-200 shadow-sm",
        "red": "bg-white border-red-200 shadow-sm",
        "amber": "bg-white border-amber-200 shadow-sm",
        "cyan": "bg-white border-blue-200 shadow-sm",
    }
    label_color = {
        "indigo": "text-blue-600",
        "green": "text-emerald-600",
        "red": "text-red-600",
        "amber": "text-amber-600",
        "cyan": "text-blue-600",
    }
    sub_html = f'<p class="mt-1 text-xs text-gray-400">{_e(subtitle)}</p>' if subtitle else ""
    return f'''<div class="rounded-xl {color_map.get(color, color_map["indigo"])} border p-5">
      <p class="text-xs font-medium uppercase tracking-wider {label_color.get(color, "text-blue-600")}">{_e(label)}</p>
      <p class="mt-2 text-2xl font-bold text-gray-800">{_e(str(value))}</p>
      {sub_html}
    </div>'''


def badge(text, variant="default"):
    styles = {
        "default": "bg-gray-100 text-gray-600 border border-gray-200",
        "success": "bg-emerald-50 text-emerald-700 border border-emerald-200",
        "danger": "bg-red-50 text-red-700 border border-red-200",
        "warning": "bg-amber-50 text-amber-700 border border-amber-200",
        "info": "bg-blue-50 text-blue-700 border border-blue-200",
        "bullish": "bg-emerald-50 text-emerald-600",
        "bearish": "bg-red-50 text-red-600",
    }
    return f'<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {styles.get(variant, styles["default"])}">{_e(text)}</span>'


def status_badge(status):
    cls, label = _status_classes(status)
    return f'<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border {cls}">{_e(label)}</span>'


# ============================================================
# PAGE RENDERERS
# ============================================================
def render_dashboard():
    s = q_stats()
    open_trades = q_open_trades()

    cards = f'''
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {stat_card("Open Trades", s["open_trades"], f'{s["today_entered"]} entered today', "indigo")}
      {stat_card("Closed Trades", s["closed_trades"], f'{s["wins"]}W / {s["losses"]}L', "cyan")}
      {stat_card("Win Rate", f'{s["win_rate"]}%', "of closed trades" if s["closed_trades"] else "no closed trades",
                 "green" if s["win_rate"] >= 55 else "amber" if s["win_rate"] >= 45 else "red")}
      {stat_card("Profit Factor", s["profit_factor"],
                 f'Avg W: {_pct(s["avg_win_pct"])} | L: {_pct(s["avg_loss_pct"])}',
                 "green" if s["profit_factor"] >= 1.5 else "amber" if s["profit_factor"] >= 1.0 else "red")}
    </div>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
      {stat_card("Total Return", _pct(s["total_return_pct"]), "", "green" if s["total_return_pct"] >= 0 else "red")}
      {stat_card("Last Scan", _date(s["last_scan"]) if s["last_scan"] != "Never" else "Never", "", "indigo")}
      {stat_card("Total Trades", s["total_trades"], "all time", "cyan")}
    </div>'''

    # Group open trades by stock
    by_stock = {}
    for t in open_trades:
        tk = _ticker(t["ticker"])
        if tk not in by_stock:
            by_stock[tk] = {"count": 0, "direction": t["direction"]}
        by_stock[tk]["count"] += 1

    stocks_html = ""
    if by_stock:
        stock_chips = ""
        for tk, info in sorted(by_stock.items()):
            dir_badge = badge("↑", "bullish") if info["direction"] == "BULLISH" else badge("↓", "bearish")
            stock_chips += f'''
            <div class="rounded-lg bg-white border border-gray-200 p-3 hover:border-blue-300 transition shadow-sm">
              <div class="flex items-center justify-between">
                <span class="text-sm font-semibold text-gray-800">{_e(tk)}</span>
                {dir_badge}
              </div>
              <p class="text-xs text-gray-400 mt-1">{info["count"]} active trade{"s" if info["count"] > 1 else ""}</p>
            </div>'''
        stocks_html = f'''
        <div class="glass rounded-xl p-6 mt-6">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">Open Positions by Stock</h3>
          <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">{stock_chips}</div>
        </div>'''

    body = f'''
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">Dashboard</h2>
        <p class="text-sm text-gray-500 mt-1">Overview of your paper trading engine</p>
      </div>
      <a href="/dashboard" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 text-sm transition shadow-sm">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
        Refresh
      </a>
    </div>
    {cards}
    {stocks_html}'''

    return page_shell("Dashboard", "dashboard", body)


def render_signals():
    trades = q_today_trades()
    entry_date = trades[0]["entry_date"] if trades else date.today().isoformat()

    # group by horizon
    by_hz = {}
    for t in trades:
        h = t.get("horizon_label") or f'{t["horizon_days"]}d'
        if h not in by_hz:
            by_hz[h] = []
        by_hz[h].append(t)

    summary_badges = f'''
    <div class="flex gap-3 flex-wrap mb-6">
      {badge(f'{len(trades)} signals', "info")}
      {badge(f'{sum(1 for t in trades if t["direction"]=="BULLISH")} bullish', "bullish")}
      {badge(f'{sum(1 for t in trades if t["direction"]=="BEARISH")} bearish', "bearish")}
    </div>'''

    tables = ""
    if not trades:
        tables = '''<div class="flex flex-col items-center justify-center py-16 text-center">
          <p class="text-lg font-medium text-gray-600">No signals yet</p>
          <p class="mt-1 text-sm text-gray-400">Run the engine to scan for signals</p>
        </div>'''
    else:
        for hz, hz_trades in by_hz.items():
            rows = ""
            for t in hz_trades:
                upside = ((t["target_price"] - t["entry_price"]) / t["entry_price"] * 100) if t["entry_price"] else 0
                dir_bdg = badge(t["direction"], "bullish" if t["direction"] == "BULLISH" else "bearish")
                conf_v = "success" if t.get("confidence") == "HIGH" else "warning" if t.get("confidence") == "MEDIUM" else "danger"
                patterns = (t.get("patterns") or "").replace(",", ", ")
                rows += f'''
                <tr class="hover:bg-blue-50/50 transition border-b border-gray-100">
                  <td class="px-4 py-3 font-semibold text-gray-800">{_e(_ticker(t["ticker"]))}</td>
                  <td class="px-4 py-3">{dir_bdg}</td>
                  <td class="px-4 py-3 text-right font-mono text-gray-700">{_price(t["entry_price"])}</td>
                  <td class="px-4 py-3 text-right"><span class="font-mono text-emerald-600">{_price(t["target_price"])}</span> <span class="text-xs text-gray-400">({_pct(upside)})</span></td>
                  <td class="px-4 py-3 text-right font-mono text-red-600">{_price(t["sl_price"])}</td>
                  <td class="px-4 py-3 text-right font-semibold text-gray-800">{t["rr_ratio"]:.1f}x</td>
                  <td class="px-4 py-3 text-right font-semibold text-gray-800">{t["predicted_win_rate"]:.0f}%</td>
                  <td class="px-4 py-3 text-gray-600 text-xs max-w-[200px] truncate">{_e(patterns)}</td>
                  <td class="px-4 py-3 text-center">{badge(t.get("confidence",""), conf_v)}</td>
                </tr>'''

            tables += f'''
            <div class="glass rounded-xl overflow-hidden mb-4">
              <div class="px-5 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                <h3 class="text-sm font-semibold text-gray-800">{_e(hz)}</h3>
                {badge(f'{len(hz_trades)} trades', "default")}
              </div>
              <div class="overflow-x-auto scrollbar-thin">
                <table class="w-full text-sm">
                  <thead><tr class="border-b border-gray-200">
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Stock</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Dir</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Entry</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Target</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Stop Loss</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">R:R</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Win Rate</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Pattern</th>
                    <th class="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Conf</th>
                  </tr></thead>
                  <tbody>{rows}</tbody>
                </table>
              </div>
            </div>'''

    body = f'''
    <div class="flex items-center justify-between mb-4">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">Today's Signals</h2>
        <p class="text-sm text-gray-500 mt-1">Signals from {_date(entry_date)} — {len(trades)} total</p>
      </div>
      <a href="/signals" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 text-sm transition shadow-sm">Refresh</a>
    </div>
    {summary_badges}
    {tables}'''
    return page_shell("Today's Signals", "signals", body)


def render_positions():
    trades = q_open_trades()
    today_str = date.today().isoformat()

    cards = ""
    if not trades:
        cards = '''<div class="flex flex-col items-center justify-center py-16 text-center">
          <p class="text-lg font-medium text-gray-600">No open positions</p>
          <p class="mt-1 text-sm text-gray-400">Trades will appear here after running the engine</p>
        </div>'''
    else:
        for i, t in enumerate(trades):
            days_held = _days_between(t["entry_date"], today_str)
            days_left = max(0, _days_between(today_str, t["expiry_date"]))
            total_days = t.get("horizon_days") or max(1, _days_between(t["entry_date"], t["expiry_date"]))
            pct_done = min(100, int(days_held / total_days * 100)) if total_days > 0 else 0
            upside = ((t["target_price"] - t["entry_price"]) / t["entry_price"] * 100) if t["entry_price"] else 0
            downside = ((t["entry_price"] - t["sl_price"]) / t["entry_price"] * 100) if t["entry_price"] else 0
            dir_cls = "bg-emerald-50 text-emerald-600" if t["direction"] == "BULLISH" else "bg-red-50 text-red-600"
            dir_arrow = "↑" if t["direction"] == "BULLISH" else "↓"
            bar_color = "bg-amber-500" if days_left <= 1 else "bg-blue-500"
            conf_v = "success" if t.get("confidence") == "HIGH" else "warning" if t.get("confidence") == "MEDIUM" else "danger"
            patterns_display = (t.get("patterns") or "").replace(",", " · ")

            cards += f'''
            <div class="glass rounded-xl p-5 hover:border-blue-300 transition-all">
              <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-3">
                  <div class="w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold {dir_cls}">{dir_arrow}</div>
                  <div>
                    <p class="font-bold text-gray-800 text-base">{_e(_ticker(t["ticker"]))}</p>
                    <p class="text-xs text-gray-400">{_e(t.get("sector") or "NSE")}</p>
                  </div>
                </div>
                {badge(t.get("horizon_label",""), "info")}
              </div>
              <div class="grid grid-cols-3 gap-3 mb-4">
                <div>
                  <p class="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Entry</p>
                  <p class="text-sm font-mono font-semibold text-gray-800">{_price(t["entry_price"])}</p>
                </div>
                <div>
                  <p class="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Target</p>
                  <p class="text-sm font-mono font-semibold text-emerald-600">{_price(t["target_price"])}</p>
                  <p class="text-[10px] text-emerald-500">+{upside:.1f}%</p>
                </div>
                <div>
                  <p class="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Stop Loss</p>
                  <p class="text-sm font-mono font-semibold text-red-600">{_price(t["sl_price"])}</p>
                  <p class="text-[10px] text-red-500">-{downside:.1f}%</p>
                </div>
              </div>
              <div class="mb-3">
                <div class="flex justify-between text-xs text-gray-400 mb-1.5">
                  <span>Day {days_held} of {total_days}</span>
                  <span>{days_left}d left</span>
                </div>
                <div class="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div class="h-full rounded-full {bar_color} transition-all" style="width:{pct_done}%"></div>
                </div>
              </div>
              <div class="flex items-center justify-between pt-3 border-t border-gray-100">
                <span class="text-xs text-gray-500">R:R {t.get("rr_ratio",0):.1f}x</span>
                <span class="text-xs text-gray-500">WR {t.get("predicted_win_rate",0):.0f}%</span>
                {badge(t.get("confidence",""), conf_v)}
              </div>
              <div class="mt-2">
                <p class="text-[10px] text-gray-400 truncate" title="{_e(t.get('patterns',''))}">{_e(patterns_display)}</p>
              </div>
            </div>'''

    body = f'''
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">Open Positions</h2>
        <p class="text-sm text-gray-500 mt-1">{len(trades)} active trades</p>
      </div>
      <a href="/positions" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 text-sm transition shadow-sm">Refresh</a>
    </div>
    <div class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
      {cards}
    </div>'''
    return page_shell("Open Positions", "positions", body)


def render_history():
    trades = q_closed_trades()

    wins = sum(1 for t in trades if t["status"] in ("WON", "EXPIRED_WIN"))
    losses = sum(1 for t in trades if t["status"] in ("LOST", "EXPIRED_LOSS"))
    wr = (wins / len(trades) * 100) if trades else 0

    summary = f'''
    <div class="grid grid-cols-4 gap-4 mb-6">
      {stat_card("Total", len(trades), "", "indigo")}
      {stat_card("Wins", wins, "", "green")}
      {stat_card("Losses", losses, "", "red")}
      {stat_card("Win Rate", f"{wr:.1f}%", "", "green" if wr >= 55 else "amber")}
    </div>'''

    if not trades:
        table = '''<div class="flex flex-col items-center justify-center py-16 text-center">
          <p class="text-lg font-medium text-gray-600">No closed trades yet</p>
          <p class="mt-1 text-sm text-gray-400">Trades will appear here once they hit SL, target, or expire</p>
        </div>'''
    else:
        rows = ""
        for t in trades:
            ret = t.get("actual_return_pct", 0) or 0
            ret_cls = "text-emerald-600" if ret >= 0 else "text-red-600"
            dir_bdg = badge(t["direction"][0] if t.get("direction") else "?", "bullish" if t.get("direction") == "BULLISH" else "bearish")
            rows += f'''
            <tr class="hover:bg-blue-50/50 transition border-b border-gray-100">
              <td class="px-4 py-3">{status_badge(t["status"])}</td>
              <td class="px-4 py-3 font-semibold text-gray-800">{_e(_ticker(t["ticker"]))}</td>
              <td class="px-4 py-3 text-gray-600">{_e(t.get("horizon_label",""))}</td>
              <td class="px-4 py-3">{dir_bdg}</td>
              <td class="px-4 py-3 text-right font-mono text-gray-600">{_price(t["entry_price"])}</td>
              <td class="px-4 py-3 text-right font-mono text-gray-600">{_price(t.get("exit_price"))}</td>
              <td class="px-4 py-3 text-right font-mono font-semibold {ret_cls}">{_pct(ret)}</td>
              <td class="px-4 py-3 text-xs text-gray-500">{_e(t.get("exit_reason",""))}</td>
              <td class="px-4 py-3 text-xs text-gray-500">{_date(t["entry_date"])}</td>
              <td class="px-4 py-3 text-xs text-gray-500">{_date(t.get("exit_date"))}</td>
              <td class="px-4 py-3 text-xs text-gray-500 max-w-[150px] truncate">{_e(t.get("patterns",""))}</td>
            </tr>'''

        table = f'''
        <div class="glass rounded-xl overflow-hidden">
          <div class="overflow-x-auto scrollbar-thin">
            <table class="w-full text-sm">
              <thead><tr class="border-b border-gray-200">
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Stock</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Horizon</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Dir</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Entry</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Exit</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Return</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Reason</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Entry</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Exit</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Pattern</th>
              </tr></thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
        </div>'''

    body = f'''
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">Trade History</h2>
        <p class="text-sm text-gray-500 mt-1">{len(trades)} closed trades</p>
      </div>
      <a href="/history" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 text-sm transition shadow-sm">Refresh</a>
    </div>
    {summary}
    {table}'''
    return page_shell("Trade History", "history", body)


def render_performance():
    s = q_stats()
    hz_stats = q_stats_by_horizon()
    pat_stats = q_stats_by_pattern()
    stock_stats = q_stats_by_stock()

    kpis = f'''
    <div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
      {stat_card("Total Trades", s["total_trades"], "", "indigo")}
      {stat_card("Win Rate", f'{s["win_rate"]}%', "", "green" if s["win_rate"] >= 55 else "amber")}
      {stat_card("Profit Factor", s["profit_factor"], "", "green" if s["profit_factor"] >= 1.5 else "amber")}
      {stat_card("Avg Win", _pct(s["avg_win_pct"]), "", "green")}
      {stat_card("Avg Loss", _pct(s["avg_loss_pct"]), "", "red")}
    </div>'''

    # Horizon table
    hz_html = ""
    if hz_stats:
        hz_rows = ""
        for h in hz_stats:
            hz_rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2 font-medium text-gray-800">{_e(h.get("horizon_label",""))}</td>
              <td class="px-4 py-2 text-right text-gray-600">{h["total"]}</td>
              <td class="px-4 py-2 text-right text-emerald-600">{h["wins"]}</td>
              <td class="px-4 py-2 text-right text-red-600">{h["losses"]}</td>
              <td class="px-4 py-2 text-right font-semibold text-gray-800">{h["win_rate"]}%</td>
              <td class="px-4 py-2 text-right text-emerald-600">{_pct(h.get("avg_win"))}</td>
              <td class="px-4 py-2 text-right text-red-600">{_pct(h.get("avg_loss"))}</td>
            </tr>'''
        hz_html = f'''
        <div class="glass rounded-xl p-6 mb-6">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">Performance by Horizon</h3>
          <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
            <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Horizon</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Trades</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Wins</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Losses</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Win Rate</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Avg Win</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Avg Loss</th>
          </tr></thead><tbody>{hz_rows}</tbody></table>
        </div>'''

    # Pattern table
    pat_html = ""
    if pat_stats:
        pat_rows = ""
        for p in pat_stats:
            ret_cls = "text-emerald-600" if (p.get("avg_ret") or 0) >= 0 else "text-red-600"
            pat_rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2 text-gray-800 text-xs">{_e((p.get("patterns","") or "").replace(",", " · "))}</td>
              <td class="px-4 py-2 text-right text-gray-600">{p["total"]}</td>
              <td class="px-4 py-2 text-right text-gray-600">{p["wins"]} / {p["losses"]}</td>
              <td class="px-4 py-2 text-right font-semibold text-gray-800">{p["win_rate"]}%</td>
              <td class="px-4 py-2 text-right font-mono {ret_cls}">{_pct(p.get("avg_ret"))}</td>
            </tr>'''
        pat_html = f'''
        <div class="glass rounded-xl p-6 mb-6">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">Performance by Pattern</h3>
          <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
            <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Pattern</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Trades</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">W / L</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Win Rate</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Avg Return</th>
          </tr></thead><tbody>{pat_rows}</tbody></table>
        </div>'''

    # Stock table
    stk_html = ""
    if stock_stats:
        stk_rows = ""
        for st in stock_stats:
            avg_cls = "text-emerald-600" if (st.get("avg_ret") or 0) >= 0 else "text-red-600"
            tot_cls = "text-emerald-600" if (st.get("total_ret") or 0) >= 0 else "text-red-600"
            stk_rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2 font-semibold text-gray-800">{_e(_ticker(st["ticker"]))}</td>
              <td class="px-4 py-2 text-right text-gray-600">{st["total"]}</td>
              <td class="px-4 py-2 text-right text-gray-600">{st["wins"]} / {st["losses"]}</td>
              <td class="px-4 py-2 text-right font-semibold text-gray-800">{st["win_rate"]}%</td>
              <td class="px-4 py-2 text-right font-mono {avg_cls}">{_pct(st.get("avg_ret"))}</td>
              <td class="px-4 py-2 text-right font-mono font-semibold {tot_cls}">{_pct(st.get("total_ret"))}</td>
            </tr>'''
        stk_html = f'''
        <div class="glass rounded-xl p-6 mb-6">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">Performance by Stock</h3>
          <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
            <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Stock</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Trades</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">W / L</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Win Rate</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Avg Return</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Total Return</th>
          </tr></thead><tbody>{stk_rows}</tbody></table>
        </div>'''

    empty = ""
    if s["closed_trades"] == 0:
        empty = '''<div class="flex flex-col items-center justify-center py-16 text-center">
          <p class="text-lg font-medium text-gray-600">No performance data yet</p>
          <p class="mt-1 text-sm text-gray-400">Analytics will appear once trades are closed</p>
        </div>'''

    body = f'''
    <h2 class="text-2xl font-bold text-gray-800 mb-6">Performance Analytics</h2>
    {kpis}
    {hz_html}
    {pat_html}
    {stk_html}
    {empty}'''
    return page_shell("Performance", "performance", body)


def render_engine(action_result=None):
    scan_log = q_scan_log()
    log_lines = get_engine_log()
    status = get_engine_status()

    # Action buttons - disabled while engine is running
    disabled = 'opacity-50 pointer-events-none' if status['running'] else ''
    buttons = f'''
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <form method="POST" action="/engine?action=run">
        <button type="submit" class="w-full glass rounded-xl p-6 text-left hover:border-blue-400 transition-all group {disabled}">
          <div class="flex items-center gap-3 mb-2">
            <div class="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center">
              <svg class="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            </div>
            <div>
              <p class="font-semibold text-gray-800 group-hover:text-blue-600 transition">Full Run</p>
              <p class="text-xs text-gray-400">Catch-up + Scan + Monitor + Report</p>
            </div>
          </div>
        </button>
      </form>
      <form method="POST" action="/engine?action=scan">
        <button type="submit" class="w-full glass rounded-xl p-6 text-left hover:border-emerald-400 transition-all group {disabled}">
          <div class="flex items-center gap-3 mb-2">
            <div class="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center">
              <svg class="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
            </div>
            <div>
              <p class="font-semibold text-gray-800 group-hover:text-emerald-600 transition">Scan Only</p>
              <p class="text-xs text-gray-400">Scan for new signals today</p>
            </div>
          </div>
        </button>
      </form>
      <form method="POST" action="/engine?action=monitor">
        <button type="submit" class="w-full glass rounded-xl p-6 text-left hover:border-amber-400 transition-all group {disabled}">
          <div class="flex items-center gap-3 mb-2">
            <div class="w-10 h-10 rounded-xl bg-amber-50 flex items-center justify-center">
              <svg class="w-5 h-5 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>
            </div>
            <div>
              <p class="font-semibold text-gray-800 group-hover:text-amber-600 transition">Monitor Only</p>
              <p class="text-xs text-gray-400">Check open positions for SL/target</p>
            </div>
          </div>
        </button>
      </form>
    </div>'''

    # Live output panel (shows when engine is running OR just finished)
    live_html = ""
    if status['running'] or status['done']:
        status_label = '<span class="inline-flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span> Running...</span>' if status['running'] else (
            '<span class="text-emerald-600 font-semibold">Completed Successfully</span>' if status['success'] else '<span class="text-red-600 font-semibold">Failed</span>'
        )
        lines_text = _e("\n".join(status['lines']))
        live_html = f'''
        <div id="live-output" class="glass rounded-xl p-5 border-blue-300 mb-6 fade-in">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-3">
              <h3 class="text-lg font-semibold text-gray-800">Engine Output</h3>
              <span class="text-xs px-2 py-1 rounded-full bg-blue-50 text-blue-700">{_e(status['action']).upper()}</span>
            </div>
            <div id="status-indicator" class="text-sm">{status_label}</div>
          </div>
          <pre id="output-log" class="text-xs text-gray-700 bg-gray-50 rounded-lg p-4 max-h-96 overflow-y-auto scrollbar-thin whitespace-pre-wrap font-mono leading-relaxed border border-gray-200">{lines_text}</pre>
          <div class="flex items-center justify-between mt-3">
            <span id="line-count" class="text-xs text-gray-400">{len(status['lines'])} lines</span>
            <span class="text-xs text-gray-400">Started: {status['started_at'][:19] if status['started_at'] else ''}</span>
          </div>
        </div>
        '''
        # Add polling JS only while running
        if status['running']:
            live_html += '''
        <script>
        (function() {
          let prevLen = 0;
          function poll() {
            fetch('/engine/stream')
              .then(r => r.json())
              .then(data => {
                const el = document.getElementById('output-log');
                const si = document.getElementById('status-indicator');
                const lc = document.getElementById('line-count');
                if (el) {
                  el.textContent = data.lines.join('\\n');
                  el.scrollTop = el.scrollHeight;
                }
                if (lc) lc.textContent = data.lines.length + ' lines';
                if (data.done) {
                  if (si) si.innerHTML = data.success
                    ? '<span class="text-emerald-600 font-semibold">Completed Successfully</span>'
                    : '<span class="text-red-600 font-semibold">Failed</span>';
                  // Re-enable buttons
                  document.querySelectorAll('form button').forEach(b => {
                    b.classList.remove('opacity-50', 'pointer-events-none');
                  });
                } else {
                  setTimeout(poll, 800);
                }
              })
              .catch(() => setTimeout(poll, 2000));
          }
          setTimeout(poll, 800);
        })();
        </script>'''

    # Action result (legacy — for non-streaming fallback)
    result_html = ""

    # Scan history
    scan_html = ""
    if scan_log:
        scan_rows = ""
        for s in scan_log:
            scan_rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2 text-gray-800">{_date(s["scan_date"])}</td>
              <td class="px-4 py-2 text-right text-gray-600">{s["tickers_scanned"]}</td>
              <td class="px-4 py-2 text-right text-gray-600">{s["signals_found"]}</td>
              <td class="px-4 py-2 text-right text-emerald-600">{s["trades_entered"]}</td>
              <td class="px-4 py-2 text-right text-red-600">{s["errors"]}</td>
              <td class="px-4 py-2 text-right text-gray-600">{s.get("duration_seconds",0):.1f}s</td>
            </tr>'''
        scan_html = f'''
        <div class="glass rounded-xl p-6 mb-6">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">Scan History</h3>
          <div class="overflow-x-auto scrollbar-thin">
            <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
              <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Date</th>
              <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Scanned</th>
              <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Signals</th>
              <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Entered</th>
              <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Errors</th>
              <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Duration</th>
            </tr></thead><tbody>{scan_rows}</tbody></table>
          </div>
        </div>'''

    # Engine log
    log_text = _e("".join(log_lines)) if log_lines else '<span class="italic text-gray-400">No log entries yet</span>'
    log_html = f'''
    <div class="glass rounded-xl p-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-gray-800">Engine Log</h3>
        <a href="/engine" class="text-xs text-gray-400 hover:text-gray-800 transition">Refresh</a>
      </div>
      <div class="bg-gray-50 rounded-lg p-4 max-h-80 overflow-y-auto scrollbar-thin border border-gray-200">
        <pre class="text-xs text-gray-600 font-mono leading-relaxed whitespace-pre-wrap">{log_text}</pre>
      </div>
    </div>'''

    body = f'''
    <h2 class="text-2xl font-bold text-gray-800 mb-2">Engine Control</h2>
    <p class="text-sm text-gray-500 mb-6">Run the paper trading engine manually or view logs</p>
    {buttons}
    {live_html}
    {scan_html}
    {log_html}'''
    return page_shell("Engine Control", "engine", body)


# ============================================================
# HTTP REQUEST HANDLER
# ============================================================
class DashboardHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.strip("/")

        routes = {
            "": ("dashboard", render_dashboard),
            "dashboard": ("dashboard", render_dashboard),
            "signals": ("signals", render_signals),
            "positions": ("positions", render_positions),
            "history": ("history", render_history),
            "performance": ("performance", render_performance),
            "engine": ("engine", lambda: render_engine()),
        }

        if path == "engine/stream":
            # JSON endpoint for live polling
            status = get_engine_status()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode("utf-8"))
        elif path in routes:
            _, renderer = routes[path]
            try:
                html = renderer()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"<h1>Error</h1><pre>{_e(str(e))}</pre>".encode("utf-8"))
        elif path == "favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_response(302)
            self.send_header("Location", "/dashboard")
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.strip("/")
        params = urllib.parse.parse_qs(parsed.query)

        if path == "engine":
            action = params.get("action", ["run"])[0]
            if action in ("run", "scan", "monitor"):
                start_engine(action)
                # Redirect to GET /engine so user sees live output
                self.send_response(302)
                self.send_header("Location", "/engine")
                self.end_headers()
                return

        self.send_response(302)
        self.send_header("Location", "/dashboard")
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress default logging noise
        pass


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    port = 8521
    print(f"\n  Traqo — RAG Powered Quantitative Candlestick Intelligence")
    print(f"  http://localhost:{port}\n")

    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)

    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()
