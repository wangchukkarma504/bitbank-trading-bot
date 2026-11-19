"""Bright Glassmorphism HTML Dashboard for Bitbank Autonomous Trading Desk."""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover" />
<title>Bitbank Autonomous AI Trading Desk</title>
<link rel="manifest" href="/manifest.webmanifest" />
<meta name="theme-color" content="#0f172a" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
<meta name="apple-mobile-web-app-title" content="Bitbank Bot" />
<link rel="apple-touch-icon" href="/static/icon-180.png" />
<link rel="icon" type="image/png" sizes="192x192" href="/static/icon-192.png" />
<style>
  :root {
    --bg-grad: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 45%, #ede9fe 100%);
    --glass: rgba(255, 255, 255, 0.68);
    --glass-strong: rgba(255, 255, 255, 0.88);
    --glass-border: rgba(255, 255, 255, 0.85);
    --shadow: 0 8px 32px rgba(31, 41, 55, 0.08);
    --text: #0f172a; --muted: #475569; --line: rgba(15, 23, 42, 0.08);
    --green: #16a34a; --red: #dc2626; --amber: #d97706; --blue: #2563eb;
  }
  * { box-sizing: border-box; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }
  html, body {
    touch-action: manipulation;
    overflow-x: hidden;
    max-width: 100%;
  }
  body {
    margin: 0; padding: 24px; min-height: 100vh;
    background: var(--bg-grad); color: var(--text);
    background-attachment: fixed;
  }
  .wrap { max-width: 1280px; width: 100%; margin: 0 auto; }
  .topbar {
    position: relative; z-index: 950;
    display: flex; flex-wrap: wrap; gap: 16px; justify-content: space-between; align-items: center;
    margin-bottom: 20px; padding: 16px 20px; border-radius: 18px;
    background: var(--glass); backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
    border: 1px solid var(--glass-border); box-shadow: var(--shadow);
  }
  .title h1 { margin: 0; font-size: 22px; font-weight: 800; letter-spacing: -0.2px; }
  .title .sub { color: var(--muted); font-size: 13px; margin-top: 4px; font-weight: 500; }
  .controls { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .badge {
    padding: 7px 13px; border-radius: 999px; font-weight: 700; font-size: 12px;
    background: rgba(255,255,255,0.75); border: 1px solid rgba(15,23,42,0.1);
    display: inline-flex; align-items: center; gap: 6px;
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .dot.online { background: var(--green); box-shadow: 0 0 8px rgba(22,163,74,0.6); }
  .dot.offline { background: var(--red); }
  .badge.RUNNING { color: var(--green); border-color: rgba(22,163,74,0.35); }
  .badge.PAUSED { color: var(--amber); border-color: rgba(217,119,6,0.35); }
  .badge.EMERGENCY_STOPPED { color: var(--red); border-color: rgba(220,38,38,0.45); }
  button { cursor: pointer; border: none; border-radius: 10px; font-weight: 700; transition: all 0.15s ease; }
  button:active { transform: scale(0.97); }
  .btn-glass {
    background: rgba(255,255,255,0.85); color: var(--text); padding: 10px 16px;
    border: 1px solid rgba(15,23,42,0.12); box-shadow: 0 2px 8px rgba(15,23,42,0.05);
  }
  .btn-glass:hover { background: #ffffff; transform: translateY(-1px); }
  .btn-primary {
    background: linear-gradient(135deg, #2563eb, #1d4ed8); color: #fff; padding: 10px 18px;
    box-shadow: 0 4px 14px rgba(37,99,235,0.28);
  }
  .btn-danger-sm {
    background: rgba(220,38,38,0.1); color: var(--red); padding: 8px 14px;
    border: 1px solid rgba(220,38,38,0.3);
  }
  .btn-danger-sm:hover { background: rgba(220,38,38,0.18); }
  .btn-stop {
    background: linear-gradient(135deg, #ef4444, #b91c1c);
    color: #fff; padding: 12px 24px; font-size: 14px; letter-spacing: 0.5px;
    box-shadow: 0 6px 20px rgba(220, 38, 38, 0.38); border: 1px solid rgba(255,255,255,0.5);
  }
  .btn-stop:hover { box-shadow: 0 8px 26px rgba(220, 38, 38, 0.55); transform: translateY(-1px); }
  .grid-kpi { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 18px; }
  .hero-pnl {
    display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 16px;
    margin-bottom: 16px; padding: 22px 24px; border-radius: 20px;
    background: rgba(255, 255, 255, 0.78); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
    border: 1.5px solid rgba(255, 255, 255, 0.92); box-shadow: 0 12px 36px rgba(15, 23, 42, 0.1);
  }
  .hero-pnl.is-pos { border-color: rgba(22, 163, 74, 0.35); background: linear-gradient(135deg, rgba(255,255,255,0.85), rgba(220,252,231,0.55)); }
  .hero-pnl.is-neg { border-color: rgba(220, 38, 38, 0.35); background: linear-gradient(135deg, rgba(255,255,255,0.85), rgba(254,226,226,0.55)); }
  .hero-label { font-size: 12px; font-weight: 800; letter-spacing: 0.8px; text-transform: uppercase; color: var(--muted); }
  .hero-main { display: flex; align-items: baseline; flex-wrap: wrap; gap: 12px; margin-top: 4px; }
  .hero-val { font-size: 42px; font-weight: 900; letter-spacing: -1px; line-height: 1.05; }
  .hero-pct {
    font-size: 15px; font-weight: 800; padding: 5px 12px; border-radius: 999px;
    background: rgba(255,255,255,0.85); border: 1px solid rgba(15,23,42,0.08);
  }
  .hero-sub { font-size: 13px; color: var(--muted); margin-top: 6px; font-weight: 600; }
  .hero-side { display: flex; gap: 20px; flex-wrap: wrap; align-items: center; }
  .hero-stat {
    padding: 12px 16px; border-radius: 14px; background: rgba(255,255,255,0.72);
    border: 1px solid rgba(15,23,42,0.08); min-width: 155px;
  }
  .hero-stat-val { font-size: 20px; font-weight: 800; margin-top: 4px; }
  .table-wrap { width: 100%; max-width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .table-wrap table { width: 100%; }
  .header-actions { display: flex; align-items: center; gap: 8px; position: relative; }
  .btn-stop-sm {
    background: linear-gradient(135deg, #ef4444, #b91c1c);
    color: #fff; padding: 9px 14px; font-size: 12px; letter-spacing: 0.4px;
    box-shadow: 0 4px 14px rgba(220, 38, 38, 0.32); border: 1px solid rgba(255,255,255,0.45);
    white-space: nowrap;
  }
  .btn-stop-sm:hover { box-shadow: 0 6px 18px rgba(220, 38, 38, 0.48); transform: translateY(-1px); }
  .menu-btn {
    display: inline-flex; align-items: center; gap: 7px; padding: 9px 13px; font-size: 12px;
    background: rgba(255,255,255,0.88); color: var(--text);
    border: 1px solid rgba(15,23,42,0.12); box-shadow: 0 2px 8px rgba(15,23,42,0.06);
  }
  .menu-popover {
    position: absolute; top: calc(100% + 10px); right: 0; width: 250px; z-index: 900;
    background: var(--glass-strong); backdrop-filter: blur(22px); -webkit-backdrop-filter: blur(22px);
    border: 1px solid #fff; border-radius: 16px; padding: 12px;
    box-shadow: 0 18px 42px rgba(15, 23, 42, 0.18); display: none; flex-direction: column; gap: 8px;
  }
  .menu-popover.open { display: flex; }
  .menu-popover .badge { width: 100%; justify-content: flex-start; }
  .menu-popover .btn-glass { width: 100%; text-align: left; padding: 9px 12px; font-size: 13px; }
  body { padding-top: max(24px, calc(env(safe-area-inset-top) + 8px)); padding-left: max(24px, env(safe-area-inset-left));
         padding-right: max(24px, env(safe-area-inset-right)); padding-bottom: max(24px, env(safe-area-inset-bottom)); }
  @media (max-width: 720px) {
    body { padding: max(12px, calc(env(safe-area-inset-top) + 6px)) max(12px, env(safe-area-inset-right))
                    max(12px, env(safe-area-inset-bottom)) max(12px, env(safe-area-inset-left)); }
    .table-wrap table { font-size: 11px; }
    .table-wrap th, .table-wrap td { padding: 6px 4px; white-space: nowrap; }
    .topbar { padding: 12px 14px; gap: 10px; margin-bottom: 12px; flex-wrap: nowrap; }
    .title { min-width: 0; flex: 1; }
    .title h1 { font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .title .sub { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .btn-stop-sm { padding: 8px 10px; font-size: 11px; }
    .menu-btn { padding: 8px 10px; font-size: 11px; }
    .hero-pnl { padding: 16px; gap: 12px; margin-bottom: 12px; }
    .hero-val { font-size: 32px; }
    .hero-pct { font-size: 13px; padding: 4px 10px; }
    .hero-side { width: 100%; display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
    .hero-stat { min-width: 0; padding: 10px 12px; }
    .hero-stat-val { font-size: 17px; }
    .grid-kpi { grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 12px; }
    .card { padding: 14px; border-radius: 16px; }
    .kpi-val { font-size: 19px; }
    .kpi-sub { font-size: 12px; }
    .chart-wrap { height: 185px; }
    .field input { font-size: 16px; }
  }
  .card {
    min-width: 0;
    background: var(--glass); backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
    border: 1px solid var(--glass-border); border-radius: 18px; padding: 18px; box-shadow: var(--shadow);
  }
  .kpi-label { color: var(--muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.6px; }
  .kpi-val { font-size: 25px; font-weight: 800; margin-top: 6px; color: var(--text); }
  .kpi-sub { font-size: 13px; color: var(--muted); margin-top: 4px; font-weight: 500; }
  .pos { color: var(--green); } .neg { color: var(--red); }
  .grid-2 { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 18px; }
  @media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }
  h2 { margin: 0 0 12px 0; font-size: 13px; font-weight: 800; color: var(--muted); text-transform: uppercase; letter-spacing: 0.7px; }
  .ms-row { margin-bottom: 12px; }
  .ms-head { display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; margin-bottom: 6px; }
  .bar-bg { height: 10px; background: rgba(15,23,42,0.08); border-radius: 999px; overflow: hidden; }
  .bar-fill { height: 100%; background: linear-gradient(90deg, #3b82f6, #10b981); transition: width 0.3s ease; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 9px 6px; border-bottom: 1px solid var(--line); }
  th { color: var(--muted); font-weight: 700; font-size: 12px; }
  .chart-wrap { width: 100%; height: 220px; position: relative; overflow-x: auto; overflow-y: hidden; -webkit-overflow-scrolling: touch; }
  svg { width: 100%; height: 100%; display: block; }
  .alert {
    padding: 12px 16px; border-radius: 12px; margin-bottom: 16px; font-size: 13px; font-weight: 600;
    background: rgba(239,68,68,0.12); border: 1px solid rgba(220,38,38,0.35); color: #991b1b; display: none;
  }
  .modal-backdrop {
    position: fixed; inset: 0; background: rgba(15, 23, 42, 0.32);
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
    display: none; align-items: center; justify-content: center; z-index: 1000; padding: 16px;
  }
  .modal-backdrop.open { display: flex; }
  .modal {
    width: 100%; max-width: 520px; max-height: 90vh; overflow-y: auto; -webkit-overflow-scrolling: touch;
    background: var(--glass-strong); backdrop-filter: blur(22px); border: 1px solid #fff; border-radius: 20px;
    padding: 0 22px 20px; box-shadow: 0 20px 50px rgba(15,23,42,0.22);
  }
  .modal-head {
    position: sticky; top: 0; z-index: 10; background: rgba(255,255,255,0.95);
    backdrop-filter: blur(12px); display: flex; justify-content: space-between; align-items: center;
    padding: 18px 0 12px; margin-bottom: 14px; border-bottom: 1px solid rgba(15,23,42,0.08);
  }
  .modal-head h3 { margin: 0; font-size: 18px; font-weight: 800; }
  .modal-foot {
    position: sticky; bottom: 0; z-index: 10; background: rgba(255,255,255,0.95);
    backdrop-filter: blur(12px); display: flex; gap: 10px; justify-content: flex-end;
    padding: 12px 0 4px; margin-top: 14px; border-top: 1px solid rgba(15,23,42,0.08);
  }
  .sec-card {
    background: rgba(255,255,255,0.72); border: 1px solid rgba(15,23,42,0.09);
    border-radius: 14px; padding: 14px; margin-bottom: 12px;
  }
  .sec-title { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.7px; color: #2563eb; margin-bottom: 10px; }
  .field { margin-bottom: 12px; }
  .field:last-child { margin-bottom: 0; }
  .field-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 6px; }
  .field label { display: block; font-size: 13px; font-weight: 700; color: var(--text); margin: 0; }
  .val-pill { font-size: 12px; font-weight: 800; color: #2563eb; background: rgba(37,99,235,0.1); padding: 3px 9px; border-radius: 999px; white-space: nowrap; }
  .hint { font-size: 11.5px; color: var(--muted); margin-top: 4px; line-height: 1.35; }
  .field input[type="number"], .field input[type="text"], .field input[type="password"] {
    width: 100%; padding: 10px 12px; border-radius: 10px; font-size: 15px;
    border: 1px solid rgba(15,23,42,0.14); background: rgba(255,255,255,0.95); color: var(--text);
  }
  .range-slider {
    width: 100%; height: 8px; -webkit-appearance: none; appearance: none;
    background: rgba(37,99,235,0.18); border-radius: 999px; outline: none; margin: 8px 0; cursor: pointer;
  }
  .range-slider::-webkit-slider-thumb {
    -webkit-appearance: none; appearance: none; width: 22px; height: 22px; border-radius: 50%;
    background: #2563eb; border: 2px solid #fff; box-shadow: 0 2px 8px rgba(37,99,235,0.4); cursor: pointer;
  }
  .range-slider::-moz-range-thumb {
    width: 22px; height: 22px; border-radius: 50%;
    background: #2563eb; border: 2px solid #fff; box-shadow: 0 2px 8px rgba(37,99,235,0.4); cursor: pointer;
  }
  .chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
  .chip-btn {
    padding: 5px 10px; border-radius: 999px; font-size: 11.5px; font-weight: 700;
    background: rgba(15,23,42,0.06); color: var(--text); border: 1px solid rgba(15,23,42,0.1); cursor: pointer;
  }
  .chip-btn.active { background: #2563eb; color: #fff; border-color: #2563eb; }
  .seg-group { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; background: rgba(15,23,42,0.06); padding: 4px; border-radius: 12px; }
  .seg-btn {
    padding: 9px 10px; border-radius: 9px; font-size: 12.5px; font-weight: 700; text-align: center;
    background: transparent; color: var(--muted); border: none; cursor: pointer;
  }
  .seg-btn.active { background: #fff; color: var(--text); box-shadow: 0 2px 8px rgba(15,23,42,0.1); }
  details.api-details summary { cursor: pointer; font-size: 12.5px; font-weight: 700; color: var(--muted); list-style: none; display: flex; justify-content: space-between; align-items: center; }
  @media (max-width: 720px) {
    .modal-backdrop { align-items: flex-end; padding: 0; }
    .modal { max-width: 100%; max-height: 88vh; border-radius: 22px 22px 0 0; padding: 0 16px 18px; }
    .field input[type="number"], .field input[type="text"], .field input[type="password"] { font-size: 16px; }
  }
  .key-banner {
    display: flex; justify-content: space-between; align-items: center; gap: 10px;
    padding: 12px 14px; border-radius: 12px; margin-bottom: 12px;
    background: rgba(255,255,255,0.8); border: 1px solid rgba(15,23,42,0.1);
  }
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <div class="title">
      <h1>Bitbank Autonomous AI Trading Desk</h1>
      <div class="sub" id="subtitle">Connecting to live FastAPI engine...</div>
    </div>
    <div class="header-actions">
      <button class="btn-stop-sm" onclick="emergencyStopAll()">STOP ALL TRADES</button>
      <button class="menu-btn" id="menuToggleBtn" onclick="toggleHeaderMenu(event)"><span class="dot online" id="menuDot"></span>Menu ▾</button>
      <div class="menu-popover" id="headerMenu">
        <span class="badge" id="apiBadge"><span class="dot offline"></span>API: CHECKING</span>
        <span class="badge" id="stateBadge">LOADING</span>
        <button class="btn-glass" onclick="window.location.href='/predict'" style="color:#2563eb;font-weight:700;">Prediction (ML test)</button>
        <button class="btn-glass" onclick="closeHeaderMenu(); openSettings()">Settings</button>
        <button class="btn-glass" onclick="closeHeaderMenu(); scrollToTax()">Japan Tax (確定申告)</button>
        <button class="btn-glass" onclick="togglePause()" id="pauseBtn">Pause Bot</button>
        <button class="btn-glass" id="installPwaBtn" onclick="installPwa()" style="display:none;color:#2563eb;font-weight:700;">Install App</button>
        <button class="btn-glass" onclick="window.location.href='/logout'">Logout</button>
      </div>
    </div>
  </div>

  <div class="alert" id="alertBox"></div>

  <div class="hero-pnl" id="heroPnlCard">
    <div>
      <div class="hero-label" id="heroTradeLabel">Live Current Trade Profit</div>
      <div class="hero-main">
        <div class="hero-val" id="heroInTradeVal">--</div>
        <span class="hero-pct" id="heroInTradePct">--%</span>
      </div>
      <div class="hero-sub" id="heroTradeSub">Checking live positions...</div>
      <div id="heroCloseWrap" style="display:none;margin-top:10px;gap:10px;align-items:center;flex-wrap:wrap;">
        <button class="btn-danger-sm" id="heroCloseBtn" onclick="closeOpenPosition(0)">Close Position</button>
        <span id="heroEstClose" style="font-size:12px;font-weight:700;color:var(--muted);"></span>
      </div>
    </div>
    <div class="hero-side">
      <div class="hero-stat">
        <div class="hero-label">Overall Profit &amp; Loss</div>
        <div class="hero-stat-val" id="heroPnlVal">--</div>
        <div class="kpi-sub" id="heroPnlPct">--</div>
      </div>
      <div class="hero-stat">
        <div class="hero-label">Total Equity</div>
        <div class="hero-stat-val" id="heroEqVal">--</div>
        <div class="kpi-sub" id="heroEqSub">Baseline: --</div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px;">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:10px;">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <h2 style="margin:0;">Live Bitbank Price Chart</h2>
        <a href="/predict" style="font-size:12px;font-weight:800;color:#2563eb;text-decoration:none;border:1px solid rgba(37,99,235,0.3);border-radius:8px;padding:4px 9px;background:rgba(255,255,255,0.9);">Prediction →</a>
        <select id="chartPairSel" onchange="onChartPairChange(this.value)" style="padding:5px 10px;border-radius:8px;border:1px solid rgba(15,23,42,0.16);background:rgba(255,255,255,0.9);font-weight:700;font-size:12px;">
          <option value="btc_jpy">BTC / JPY</option>
          <option value="eth_jpy">ETH / JPY</option>
          <option value="sol_jpy">SOL / JPY</option>
          <option value="doge_jpy">DOGE / JPY</option>
          <option value="xrp_jpy">XRP / JPY</option>
          <option value="ada_jpy">ADA / JPY</option>
          <option value="link_jpy">LINK / JPY</option>
          <option value="avax_jpy">AVAX / JPY</option>
          <option value="dot_jpy">DOT / JPY</option>
          <option value="ltc_jpy">LTC / JPY</option>
          <option value="boba_jpy">BOBA / JPY</option>
        </select>
        <div id="tfBtns" style="display:flex;gap:4px;">
          <button class="btn-glass" style="padding:4px 9px;font-size:11px;" onclick="setChartTf('5min', this)">5m</button>
          <button class="btn-primary" style="padding:4px 9px;font-size:11px;" onclick="setChartTf('15min', this)">15m</button>
          <button class="btn-glass" style="padding:4px 9px;font-size:11px;" onclick="setChartTf('1hour', this)">1h</button>
          <button class="btn-glass" style="padding:4px 9px;font-size:11px;" onclick="setChartTf('4hour', this)">4h</button>
        </div>
      </div>
      <div id="marketChartLegend" style="display:flex;gap:10px;flex-wrap:wrap;font-size:12px;font-weight:700;color:var(--muted);"></div>
    </div>
    <div id="marketChartWrap" style="width:100%;height:430px;position:relative;background:#131722;border-radius:12px;overflow:hidden;">
      <div style="color:#8b93a7;padding-top:150px;text-align:center;">Loading Bitbank candles...</div>
    </div>
    <div id="marketChartInfo" style="display:none;gap:8px;flex-wrap:wrap;margin-top:10px;"></div>
  </div>

  <div class="grid-kpi">
    <div class="card">
      <div class="kpi-label">Total Equity</div>
      <div class="kpi-val" id="equityVal">--</div>
      <div class="kpi-sub" id="baselineSub">Baseline: --</div>
    </div>
    <div class="card">
      <div class="kpi-label">Total Profit / Loss</div>
      <div class="kpi-val" id="totalPnlVal">--</div>
      <div class="kpi-sub" id="totalPnlPct">--</div>
    </div>
    <div class="card">
      <div class="kpi-label">In-Trade Unrealized PnL</div>
      <div class="kpi-val" id="inTradeVal">--</div>
      <div class="kpi-sub" id="inTradePct">--</div>
    </div>
    <div class="card">
      <div class="kpi-label">2.0x Buying Power</div>
      <div class="kpi-val" id="bpVal">--</div>
      <div class="kpi-sub" id="freeCashSub">Free JPY: --</div>
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:8px;">
        <h2 style="margin:0;">Per-Trade Profit &amp; Loss (JPY)</h2>
        <div id="tradeChartLegend" style="font-size:11.5px;font-weight:700;color:var(--muted);"></div>
      </div>
      <div class="chart-wrap" id="chartWrap"></div>
    </div>
    <div class="card">
      <h2>Capital Milestones</h2>
      <div id="milestonesBox"></div>
      <h2 style="margin-top:18px;">How the bot trades</h2>
      <div id="macroBox" style="font-size:13px;color:var(--muted);">Loading...</div>
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <h2>Active Positions & Exchange Stops</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Pair</th><th>Side</th><th>Amount</th><th>Entry</th><th>Last</th><th>uPnL</th><th>Est. Close</th><th>Action</th></tr></thead>
          <tbody id="posBody"><tr><td colspan="8" style="color:var(--muted)">No open positions</td></tr></tbody>
        </table>
      </div>
      <div style="margin-top:10px;font-size:12px;color:var(--muted);" id="stopsLine">Active Stops: 0</div>
    </div>
    <div class="card">
      <h2>Closed trades (bot)</h2>
      <div id="lessonsBox" style="font-size:13px;color:var(--muted);">No closed trades recorded yet.</div>
    </div>
  </div>

  <div class="card">
    <h2>Breakout watch</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Coin</th><th>State</th><th>4h close</th><th>20-day high</th><th>Gap to breakout</th><th>Stop distance</th><th>Detail</th></tr></thead>
        <tbody id="radarBody"></tbody>
      </table>
    </div>
  </div>

  <div class="card" id="taxCard" style="margin-top:16px;">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px;">
      <div>
        <h2 style="margin:0;">Japan Crypto Tax Center (確定申告 / 雑所得)</h2>
        <div id="taxDataSourceNote" style="font-size:12px;color:var(--muted);margin-top:4px;">Loading Bitbank realized trade ledger...</div>
      </div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
        <span class="badge" id="taxFilingBadge">CHECKING...</span>
        <button class="btn-glass" style="padding:7px 12px;font-size:12px;" onclick="loadTaxReport()">Refresh Data</button>
        <button class="btn-primary" style="padding:7px 12px;font-size:12px;" onclick="downloadTaxCsv()">Download CSV</button>
      </div>
    </div>

    <div class="ms-row" style="margin-bottom:12px;">
      <div class="ms-head">
        <span id="taxThresholdLabel">¥200,000 Salaried National Filing Threshold</span>
        <span id="taxThresholdPct">0%</span>
      </div>
      <div class="bar-bg"><div id="taxThresholdBar" style="height:100%;width:0%;background:linear-gradient(90deg,#16a34a,#22c55e);border-radius:999px;transition:width .35s ease;"></div></div>
    </div>

    <div id="taxVerdictBox" style="padding:11px 14px;border-radius:12px;margin-bottom:14px;font-size:13px;font-weight:700;line-height:1.45;background:rgba(22,163,74,0.1);border:1px solid rgba(22,163,74,0.28);color:#14532d;">Checking filing requirement...</div>

    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:16px;">
      <div style="padding:12px;border-radius:14px;background:rgba(255,255,255,0.65);border:1px solid rgba(15,23,42,0.08);">
        <div class="kpi-label">Net Taxable Profit (雑所得)</div>
        <div class="kpi-val" id="taxNetVal" style="font-size:20px;">--</div>
        <div class="kpi-sub" id="taxGrossSub" style="font-size:11.5px;">Gross: --</div>
      </div>
      <div style="padding:12px;border-radius:14px;background:rgba(255,255,255,0.65);border:1px solid rgba(15,23,42,0.08);">
        <div class="kpi-label">Fees / Maker Rebates</div>
        <div class="kpi-val" id="taxFeesVal" style="font-size:20px;">--</div>
        <div class="kpi-sub" id="taxIntSub" style="font-size:11.5px;">Interest: --</div>
      </div>
      <div style="padding:12px;border-radius:14px;background:rgba(255,255,255,0.65);border:1px solid rgba(15,23,42,0.08);">
        <div class="kpi-label">Est. Tax Reserve (納税目安)</div>
        <div class="kpi-val" id="taxEstVal" style="font-size:20px;">--</div>
        <div class="kpi-sub" id="taxRateSub" style="font-size:11.5px;">Eff. Rate: --</div>
      </div>
      <div style="padding:12px;border-radius:14px;background:rgba(255,255,255,0.65);border:1px solid rgba(15,23,42,0.08);">
        <div class="kpi-label">Remaining Under ¥200k</div>
        <div class="kpi-val" id="taxRemVal" style="font-size:20px;">--</div>
        <div class="kpi-sub" id="taxTradesSub" style="font-size:11.5px;">Trades: 0</div>
      </div>
    </div>

    <div class="sec-card" style="margin-bottom:14px;">
      <div class="sec-title">Your Japan Tax Profile (Saved Locally, Never Uploaded)</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:10px;">
        <div class="field" style="margin:0;">
          <label for="taxYearSel">Tax Year</label>
          <select id="taxYearSel" onchange="loadTaxReport(this.value)" style="width:100%;padding:10px 12px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:rgba(255,255,255,0.95);font-size:14px;">
            <option value="2026">2026 (令和8年)</option>
            <option value="2025">2025 (令和7年)</option>
            <option value="2024">2024 (令和6年)</option>
          </select>
        </div>
        <div class="field" style="margin:0;">
          <label for="taxEmpSel">Work / Filing Status</label>
          <select id="taxEmpSel" style="width:100%;padding:10px 12px;border-radius:10px;border:1px solid rgba(15,23,42,0.14);background:rgba(255,255,255,0.95);font-size:14px;">
            <option value="salary">Company Does Job Tax (年末調整あり・¥200k rule)</option>
            <option value="other">Self-Employed / Own Filing</option>
          </select>
        </div>
        <div class="field" style="margin:0;">
          <label for="taxSalaryJpy">Annual Salary (JPY, optional)</label>
          <input id="taxSalaryJpy" type="number" min="0" step="100000" placeholder="e.g. 5000000" />
        </div>
        <div class="field" style="margin:0;">
          <label for="taxOtherMiscJpy">Other Side / Misc Income (JPY)</label>
          <input id="taxOtherMiscJpy" type="number" min="0" step="1000" placeholder="0" />
        </div>
        <div class="field" style="margin:0;">
          <label for="taxName">Taxpayer Name (optional)</label>
          <input id="taxName" type="text" placeholder="For CSV export" />
        </div>
        <div class="field" style="margin:0;">
          <label for="taxOffice">Tax Office / 税務署 (optional)</label>
          <input id="taxOffice" type="text" placeholder="e.g. Shibuya / 新宿" />
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:12px;">
        <button class="btn-primary" style="padding:9px 16px;" onclick="saveTaxProfile()">Save Tax Details &amp; Recalculate</button>
        <span id="taxMsg" style="font-size:12.5px;font-weight:700;color:var(--green);"></span>
      </div>
      <div id="taxResidentNote" class="hint" style="margin-top:8px;"></div>
    </div>

    <details style="margin-bottom:10px;">
      <summary style="cursor:pointer;font-size:13px;font-weight:800;color:var(--text);">Monthly Breakdown &amp; Realized Bitbank Trade Ledger</summary>
      <div style="margin-top:10px;">
        <div style="font-size:12px;font-weight:700;color:var(--muted);margin-bottom:6px;">MONTHLY SUMMARY (JST)</div>
        <div class="table-wrap" style="margin-bottom:14px;">
          <table>
            <thead><tr><th>Month</th><th>Trades</th><th>Gross PnL</th><th>Fees/Rebate</th><th>Interest</th><th>Net Profit</th></tr></thead>
            <tbody id="taxMonthlyBody"></tbody>
          </table>
        </div>
        <div style="font-size:12px;font-weight:700;color:var(--muted);margin-bottom:6px;">REALIZED TRADE LEDGER (LATEST 100)</div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Time (JST)</th><th>Pair</th><th>Side</th><th>Amount</th><th>Price</th><th>Gross PnL</th><th>Fee</th><th>Net PnL</th></tr></thead>
            <tbody id="taxLedgerBody"></tbody>
          </table>
        </div>
      </div>
    </details>
    <div class="hint">Uses Bitbank realized PnL for margin trades and moving-average cost basis (移動平均法) for spot sells. Estimate only — even if national 所得税 is exempt under ¥200k, ~10% local 住民税 still applies. Confirm final filing via e-Tax / 確定申告書等作成コーナー or a licensed 税理士.</div>
  </div>
</div>

<!-- Settings Popup Modal -->
<div class="modal-backdrop" id="settingsModal" onclick="if(event.target===this) closeSettings()">
  <div class="modal">
    <div class="modal-head">
      <h3>Trading Desk Settings</h3>
      <button class="btn-glass" style="padding:6px 12px;" onclick="closeSettings()">Close</button>
    </div>

    <div class="key-banner">
      <div>
        <div style="font-size:12px;color:var(--muted);font-weight:700;">BITBANK API STATUS</div>
        <div id="modalApiStatus" style="font-size:14px;font-weight:800;margin-top:2px;">Checking...</div>
      </div>
      <button class="btn-danger-sm" id="removeKeyBtn" onclick="removeApiKey()" style="display:none;">Remove API Key</button>
    </div>

    <div class="sec-card" style="display:none;">
      <div class="sec-title">Trading Mode &amp; Auto Take-Profit</div>

      <div class="field">
        <div class="field-row"><label>Account Trading Mode</label></div>
        <div class="seg-group">
          <button type="button" class="seg-btn active" id="modeBothBtn" onclick="setModeToggle(true)">Long + Short (Margin)</button>
          <button type="button" class="seg-btn" id="modeSpotBtn" onclick="setModeToggle(false)">Spot Long-Only</button>
        </div>
        <input type="hidden" id="cfgAllowShorts" value="true" />
        <div class="hint">Use <b>Spot Long-Only</b> if your Bitbank account does not have margin/short access.</div>
      </div>

      <div class="field">
        <div class="field-row">
          <label for="cfgForceProfitJpy">Force Profit Close</label>
          <span class="val-pill" id="fpcBadge">Off (Normal Flow)</span>
        </div>
        <input type="range" class="range-slider" id="cfgForceProfitSlider" min="0" max="10000" step="500" value="0" oninput="onForceProfitSlider(this.value)" />
        <div class="chip-row">
          <button type="button" class="chip-btn" onclick="setForceProfit(0)">Off</button>
          <button type="button" class="chip-btn" onclick="setForceProfit(1000)">¥1,000</button>
          <button type="button" class="chip-btn" onclick="setForceProfit(2000)">¥2,000</button>
          <button type="button" class="chip-btn" onclick="setForceProfit(5000)">¥5,000</button>
          <input id="cfgForceProfitJpy" type="number" min="0" step="100" placeholder="Custom JPY" style="width:110px;padding:5px 9px;font-size:13px;" oninput="onForceProfitInput(this.value)" />
        </div>
        <div class="hint">Auto-closes when net profit (after 0.12% fee) hits this target. Trailing stop still protects you below it.</div>
      </div>
    </div>

    <div class="sec-card">
      <div class="sec-title">Capital &amp; Goal Targets</div>

      <div class="field">
        <div class="field-row">
          <label for="cfgCapJpy">Max Capital to Trade</label>
          <span class="val-pill" id="capBadge">100% Equity</span>
        </div>
        <input type="range" class="range-slider" id="cfgCapSlider" min="0" max="500000" step="10000" value="0" oninput="onCapSlider(this.value)" />
        <div style="display:flex;gap:8px;align-items:center;">
          <button type="button" class="chip-btn" onclick="setCapPreset(0)">100% (No Cap)</button>
          <input id="cfgCapJpy" type="number" min="0" step="1000" placeholder="0 = use 100%" style="flex:1;" oninput="onCapInput(this.value)" />
        </div>
        <div class="hint" id="capStatus">100% Account Equity</div>
      </div>

      <div class="field">
        <div class="field-row">
          <label for="cfgBaselineJpy">Starting Baseline (JPY)</label>
          <span class="val-pill" id="baseBadge">--</span>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
          <input id="cfgBaselineJpy" type="number" min="0" step="100" placeholder="e.g. 98874.1" style="flex:1;min-width:120px;" oninput="this.dataset.dirty='1'" />
          <button type="button" class="chip-btn" onclick="addDeposit(10000)">+¥10,000</button>
          <button type="button" class="chip-btn" onclick="useLiveEquityBaseline()">Match Live</button>
        </div>
        <div class="hint">Used to calculate your overall PnL and auto-scale 2x / 5x / 10x goals.</div>
      </div>

      <div class="field">
        <div class="field-row">
          <label for="cfgGoalJpy">Custom Goal Target</label>
          <span class="val-pill" id="goalBadge">Auto (2x/5x/10x)</span>
        </div>
        <input type="range" class="range-slider" id="cfgGoalSlider" min="0" max="1000000" step="10000" value="0" oninput="onGoalSlider(this.value)" />
        <div style="display:flex;gap:8px;align-items:center;">
          <button type="button" class="chip-btn" onclick="setGoalPreset(0)">Auto 2x/5x/10x</button>
          <input id="cfgGoalJpy" type="number" min="0" step="1000" placeholder="0 = Auto" style="flex:1;" oninput="onGoalInput(this.value)" />
        </div>
      </div>
    </div>

    <div class="sec-card">
      <details class="api-details">
        <summary>
          <span>Bitbank API Keys (Optional Update)</span>
          <span style="font-size:11px;color:#2563eb;">Expand ▾</span>
        </summary>
        <div style="margin-top:12px;">
          <div class="field">
            <label id="keyActionLabel">Add / Replace Bitbank API Key</label>
            <input id="cfgApiKey" type="text" placeholder="Paste Bitbank API Key" />
          </div>
          <div class="field">
            <label>Bitbank API Secret</label>
            <input id="cfgApiSecret" type="password" placeholder="Paste Bitbank API Secret" />
          </div>
        </div>
      </details>
    </div>

    <div id="cfgMsg" style="margin-top:6px;font-size:13px;font-weight:700;color:var(--green);"></div>
    <div class="modal-foot">
      <button class="btn-glass" onclick="closeSettings()">Cancel</button>
      <button class="btn-primary" style="flex:1;" onclick="saveConfig()">Save &amp; Apply</button>
    </div>
  </div>
</div>

<script>
const fmtJpy = (n) => '¥' + Number(n || 0).toLocaleString('en-US', {maximumFractionDigits: 1});
let currentState = 'RUNNING';
let latestPositions = [];
let chartPair = 'btc_jpy';
let chartPairManual = false;
let chartTf = '15min';
let latestCandles = [];
let latestStatusData = null;
let lastCandleFetchTs = 0;

function openSettings() { document.getElementById('settingsModal').classList.add('open'); }
function closeSettings() { document.getElementById('settingsModal').classList.remove('open'); }
function toggleHeaderMenu(e) {
  e.stopPropagation();
  document.getElementById('headerMenu').classList.toggle('open');
}
function closeHeaderMenu() { document.getElementById('headerMenu').classList.remove('open'); }
document.addEventListener('click', (e) => {
  const menu = document.getElementById('headerMenu');
  const btn = document.getElementById('menuToggleBtn');
  if (menu && !menu.contains(e.target) && btn && !btn.contains(e.target)) closeHeaderMenu();
});

function _smoothPath(coords) {
  if (coords.length < 2) return '';
  let d = `M ${coords[0].x.toFixed(1)},${coords[0].y.toFixed(1)}`;
  for (let i = 0; i < coords.length - 1; i++) {
    const p0 = coords[Math.max(0, i - 1)];
    const p1 = coords[i];
    const p2 = coords[i + 1];
    const p3 = coords[Math.min(coords.length - 1, i + 2)];
    const cp1x = p1.x + (p2.x - p0.x) / 6;
    const cp1y = p1.y + (p2.y - p0.y) / 6;
    const cp2x = p2.x - (p3.x - p1.x) / 6;
    const cp2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C ${cp1x.toFixed(1)},${cp1y.toFixed(1)} ${cp2x.toFixed(1)},${cp2y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)}`;
  }
  return d;
}

function renderChart(trades, baseline, openPositions, inTradePnl) {
  const wrap = document.getElementById('chartWrap');
  const legend = document.getElementById('tradeChartLegend');
  if (!wrap) return;

  const pts = [{ label: 'Start', shortLbl: '0', pnl: 0, pair: '', isStart: true, isLive: false }];
  (trades || []).forEach((t, idx) => {
    const pName = (t.pair || '').toUpperCase().replace('_JPY', '');
    pts.push({
      label: `#${idx + 1}${pName ? ' ' + pName : ''}${t.source === 'manual' ? ' (Manual)' : ''}`,
      shortLbl: `#${idx + 1}`,
      pnl: Number(t.pnl_jpy || 0),
      pair: pName,
      isStart: false,
      isLive: false,
    });
  });
  if (openPositions && openPositions.length > 0) {
    const oName = (openPositions[0].pair || '').toUpperCase().replace('_JPY', '');
    pts.push({
      label: `LIVE${oName ? ' ' + oName : ''}`,
      shortLbl: 'LIVE',
      pnl: Number(inTradePnl || 0),
      pair: oName,
      isStart: false,
      isLive: true,
    });
  }

  const lastPt = pts[pts.length - 1];
  const setLegend = (pt) => {
    if (!legend) return;
    if (pts.length === 1) {
      legend.textContent = `Baseline ${fmtJpy(baseline)}`;
      return;
    }
    const col = pt.isStart ? '#475569' : (pt.pnl >= 0 ? '#16a34a' : '#dc2626');
    const sign = pt.pnl >= 0 ? '+' : '';
    legend.innerHTML = `<span style="color:#64748b;">Base ${fmtJpy(baseline)}</span> · <span style="color:${col};">${pt.label}: ${sign}${fmtJpy(pt.pnl)}</span>`;
  };
  setLegend(lastPt);

  if (pts.length === 1) {
    wrap.innerHTML = `<div style="color:var(--muted);padding-top:85px;text-align:center;">Initial Capital: ${fmtJpy(baseline)} (¥0) — waiting for first trade...</div>`;
    return;
  }

  const wrapW = Math.max(260, Math.floor(wrap.clientWidth || 720));
  const isMobile = wrapW < 640;
  const h = isMobile ? 205 : 225;
  wrap.style.height = h + 'px';
  const padL = 22;
  const padR = 58;
  const padTop = 26;
  const padBot = 30;
  const pxPerPt = isMobile ? 66 : 76;
  const w = Math.max(wrapW, padL + Math.max(1, pts.length - 1) * pxPerPt + padR);
  const wasNearRight = !wrap.dataset.scrolledOnce || (wrap.scrollWidth - wrap.clientWidth - wrap.scrollLeft) < 36;
  const prevScroll = wrap.scrollLeft;

  const vals = pts.map(p => p.pnl);
  let maxV = Math.max(...vals, 100), minV = Math.min(...vals, -100);
  if (maxV < 0) maxV = 0;
  if (minV > 0) minV = 0;
  const span = Math.max(100, maxV - minV);
  const plotW = w - padL - padR;
  const plotH = h - padTop - padBot;
  const x = (i) => padL + (i / (pts.length - 1)) * plotW;
  const y = (v) => padTop + ((maxV - v) / span) * plotH;
  const zeroY = y(0);

  const coords = pts.map((p, i) => ({ x: x(i), y: y(p.pnl), ...p }));
  const pathD = _smoothPath(coords);
  const last = coords[coords.length - 1];
  const strokeColor = last.pnl >= 0 ? '#16a34a' : '#dc2626';
  const areaD = `${pathD} L ${last.x.toFixed(1)},${zeroY.toFixed(1)} L ${coords[0].x.toFixed(1)},${zeroY.toFixed(1)} Z`;

  const fmtShort = (v) => {
    const abs = Math.abs(v);
    const s = v > 0 ? '+' : (v < 0 ? '-' : '');
    if (abs >= 1000) return `${s}¥${(abs / 1000).toFixed(1)}k`;
    return `${s}¥${Math.round(abs)}`;
  };
  const gridTicks = [maxV, 0, minV].filter((v, i, arr) => i === 0 || Math.abs(v - arr[i - 1]) > span * 0.12);
  const gridHtml = gridTicks.map(v => {
    const gy = y(v);
    const isZero = Math.abs(v) < 1e-6;
    return `<line x1="${padL}" y1="${gy.toFixed(1)}" x2="${(w - padR).toFixed(1)}" y2="${gy.toFixed(1)}" stroke="${isZero ? '#64748b' : 'rgba(15,23,42,0.08)'}" stroke-dasharray="${isZero ? '4 4' : '2 3'}" stroke-width="1"/>
      <text x="${(w - padR + 6).toFixed(1)}" y="${(gy + 3.5).toFixed(1)}" fill="${isZero ? '#334155' : '#64748b'}" font-size="10" font-weight="${isZero ? 800 : 600}">${isZero ? '¥0' : fmtShort(v)}</text>`;
  }).join('');

  const dots = coords.map((p, idx) => {
    const isEnd = idx === coords.length - 1;
    const col = p.isStart ? '#64748b' : (p.isLive ? '#2563eb' : (p.pnl >= 0 ? '#16a34a' : '#dc2626'));
    const anchor = isEnd ? 'end' : (idx === 0 ? 'start' : 'middle');
    const rDot = p.isStart ? 3.5 : (isEnd ? 5.5 : 4.5);
    const sign = p.pnl >= 0 ? '+' : '';
    const valTxt = p.isStart ? '¥0' : `${sign}${fmtJpy(p.pnl)}`;
    const valY = p.pnl >= 0 ? Math.max(15, p.y - 10) : Math.min(h - 24, p.y + 16);
    return `<g>
      <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${rDot}" fill="${col}" stroke="#fff" stroke-width="1.6"/>
      ${p.isStart ? '' : `<text x="${p.x.toFixed(1)}" y="${valY.toFixed(1)}" text-anchor="${anchor}" fill="${col}" font-size="10.5" font-weight="800">${valTxt}</text>`}
      <text x="${p.x.toFixed(1)}" y="${h - 7}" text-anchor="${anchor}" fill="#475569" font-size="10" font-weight="700">${p.shortLbl}</text>
    </g>`;
  }).join('');

  wrap.innerHTML = `<svg id="tradeSvg" viewBox="0 0 ${w} ${h}" style="width:${w}px;min-width:${w}px;height:${h}px;display:block;cursor:crosshair;touch-action:pan-x pan-y;">
    <defs>
      <linearGradient id="tradeGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${strokeColor}" stop-opacity="0.18"/>
        <stop offset="100%" stop-color="${strokeColor}" stop-opacity="0.02"/>
      </linearGradient>
    </defs>
    ${gridHtml}
    <path d="${areaD}" fill="url(#tradeGrad)" />
    <path d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="2.5" stroke-linecap="round" />
    <line id="tradeCrossV" x1="0" y1="${padTop}" x2="0" y2="${(h - padBot).toFixed(1)}" stroke="rgba(15,23,42,0.3)" stroke-width="1" stroke-dasharray="3 3" style="display:none;"/>
    ${dots}
  </svg>`;

  if (wasNearRight) {
    wrap.scrollLeft = w;
    wrap.dataset.scrolledOnce = '1';
  } else {
    wrap.scrollLeft = prevScroll;
  }

  const svg = document.getElementById('tradeSvg');
  const crossV = document.getElementById('tradeCrossV');
  if (svg && crossV) {
    const inspectAt = (clientX) => {
      const rect = svg.getBoundingClientRect();
      const relX = ((clientX - rect.left) / rect.width) * w;
      const tNorm = Math.max(0, Math.min(1, (relX - padL) / Math.max(1, plotW)));
      const idx = Math.round(tNorm * (coords.length - 1));
      const p = coords[idx];
      if (!p) return;
      crossV.setAttribute('x1', p.x.toFixed(1));
      crossV.setAttribute('x2', p.x.toFixed(1));
      crossV.style.display = 'block';
      setLegend(p);
    };
    const resetLegend = () => {
      crossV.style.display = 'none';
      setLegend(lastPt);
    };
    svg.addEventListener('mousemove', (ev) => inspectAt(ev.clientX));
    svg.addEventListener('mouseleave', resetLegend);
    svg.addEventListener('touchstart', (ev) => { if (ev.touches && ev.touches[0]) inspectAt(ev.touches[0].clientX); }, { passive: true });
    svg.addEventListener('touchmove', (ev) => { if (ev.touches && ev.touches[0]) inspectAt(ev.touches[0].clientX); }, { passive: true });
    svg.addEventListener('touchend', resetLegend);
  }
}

async function refresh() {
  try {
    const r = await fetch('/api/status');
    if (r.status === 401) { window.location.href = '/login'; return; }
    const d = await r.json();
    currentState = d.state;
    const capTxt = d.capital_limit_jpy ? ` | Capital Cap: ${fmtJpy(d.capital_limit_jpy)}` : '';
    document.getElementById('subtitle').textContent = `Mode: ${d.mode} | Tick #${d.tick_count}${capTxt}` +
      (d.circuit_breaker_sec > 0 ? ` | CIRCUIT BREAKER: ${d.circuit_breaker_sec}s` : '') +
      (d.daily_loss_halted ? ' | DAILY LOSS LIMIT: no new entries until tomorrow (JST)' : '') +
      (d.news_override ? ` | NEWS OVERRIDE ${d.news_override.bias}: ${d.news_override.headline}` : '') +
      (d.equity_floor_hit ? ` | EQUITY FLOOR ¥${Math.round(d.equity_floor_jpy).toLocaleString('en-US')} HIT: no new entries` : '') +
      (d.state !== 'RUNNING' ? ' | New entries OFF (open positions keep their stops)' : '') +
      (d.cooldown_sec > 0 ? ` | Cooldown: ${d.cooldown_sec}s` : '');

    const apiBadge = document.getElementById('apiBadge');
    const modalApi = document.getElementById('modalApiStatus');
    const rmBtn = document.getElementById('removeKeyBtn');
    const keyLabel = document.getElementById('keyActionLabel');
    if (d.api_key_configured) {
      apiBadge.innerHTML = `<span class="dot online"></span>API: ONLINE (${d.api_key_masked})`;
      apiBadge.style.color = '#16a34a';
      modalApi.innerHTML = `<span style="color:#16a34a;">ONLINE</span> (${d.api_key_masked})`;
      rmBtn.style.display = 'inline-block';
      keyLabel.textContent = 'Replace Bitbank API Key (or remove existing above)';
    } else {
      apiBadge.innerHTML = `<span class="dot offline"></span>API: OFFLINE`;
      apiBadge.style.color = '#dc2626';
      modalApi.innerHTML = `<span style="color:#dc2626;">OFFLINE</span> (No API Key configured)`;
      rmBtn.style.display = 'none';
      keyLabel.textContent = 'Add Bitbank API Key';
    }

    const badge = document.getElementById('stateBadge');
    badge.textContent = d.state;
    badge.className = 'badge ' + d.state;
    const mDot = document.getElementById('menuDot');
    if (mDot) mDot.className = 'dot ' + (d.api_key_configured && d.state === 'RUNNING' ? 'online' : 'offline');
    document.getElementById('pauseBtn').textContent = d.state === 'RUNNING' ? 'Pause Bot' : 'Resume Bot';

    document.getElementById('equityVal').textContent = fmtJpy(d.equity_jpy);
    document.getElementById('baselineSub').textContent = `Baseline: ${fmtJpy(d.baseline_jpy)}`;

    const tp = document.getElementById('totalPnlVal');
    const pnlSign = d.total_pnl_jpy >= 0 ? '+' : '';
    const pnlCls = d.total_pnl_jpy >= 0 ? 'pos' : 'neg';
    tp.textContent = pnlSign + fmtJpy(d.total_pnl_jpy);
    tp.className = 'kpi-val ' + pnlCls;
    document.getElementById('totalPnlPct').textContent = `${d.total_pnl_pct >= 0 ? '+' : ''}${d.total_pnl_pct.toFixed(2)}%`;

    const hasOpen = d.open_positions && d.open_positions.length > 0;
    const inSign = d.in_trade_pnl_jpy >= 0 ? '+' : '';
    const inCls = d.in_trade_pnl_jpy >= 0 ? 'pos' : 'neg';
    const heroVal = document.getElementById('heroInTradeVal');
    heroVal.textContent = inSign + fmtJpy(d.in_trade_pnl_jpy);
    heroVal.className = 'hero-val ' + inCls;
    const heroPct = document.getElementById('heroInTradePct');
    heroPct.textContent = `${d.in_trade_pnl_pct >= 0 ? '+' : ''}${d.in_trade_pnl_pct.toFixed(2)}%`;
    heroPct.className = 'hero-pct ' + inCls;

    const heroCard = document.getElementById('heroPnlCard');
    const heroPosFlag = hasOpen ? (d.in_trade_pnl_jpy >= 0) : (d.total_pnl_jpy >= 0);
    heroCard.className = 'hero-pnl ' + (heroPosFlag ? 'is-pos' : 'is-neg');

    const tradeLbl = document.getElementById('heroTradeLabel');
    const tradeSub = document.getElementById('heroTradeSub');
    const heroCloseWrap = document.getElementById('heroCloseWrap');
    const heroEstClose = document.getElementById('heroEstClose');
    latestPositions = d.open_positions || [];
    if (hasOpen) {
      const p0 = d.open_positions[0];
      const extra = d.open_positions.length > 1 ? ` (+${d.open_positions.length - 1} more)` : '';
      const stopTxt = (d.active_stops && d.active_stops.length) ? ` | Stop: ¥${d.active_stops[0].trigger_price}` : '';
      tradeLbl.textContent = `LIVE CURRENT TRADE • ${p0.pair.toUpperCase()} ${p0.position_side.toUpperCase()}${extra}`;
      tradeSub.textContent = `${p0.open_amount} @ ¥${p0.avg_price} → Now ¥${p0.last_price}${stopTxt}`;
      const estNet = Number(p0.est_net_close_pnl_jpy !== undefined ? p0.est_net_close_pnl_jpy : p0.unrealized_pnl_jpy || 0);
      const estSign = estNet >= 0 ? '+' : '';
      const stopEstTxt = (p0.est_stop_pnl_jpy !== undefined) ? ` | If Stop Hits: ${p0.est_stop_pnl_jpy >= 0 ? '+' : ''}${fmtJpy(p0.est_stop_pnl_jpy)}` : '';
      heroEstClose.innerHTML = `Est. Close (after 0.12% fee): <span class="${estNet >= 0 ? 'pos' : 'neg'}">${estSign}${fmtJpy(estNet)}</span>${stopEstTxt}`;
      heroCloseWrap.style.display = 'flex';
    } else {
      tradeLbl.textContent = 'LIVE CURRENT TRADE • NO OPEN POSITION';
      tradeSub.textContent = 'Flat (100% protected) — scanning 10 pairs for high-conviction setups';
      heroCloseWrap.style.display = 'none';
    }

    const hPnl = document.getElementById('heroPnlVal');
    hPnl.textContent = pnlSign + fmtJpy(d.total_pnl_jpy);
    hPnl.className = 'hero-stat-val ' + pnlCls;
    document.getElementById('heroPnlPct').textContent = `${d.total_pnl_pct >= 0 ? '+' : ''}${d.total_pnl_pct.toFixed(2)}% overall`;
    document.getElementById('heroEqVal').textContent = fmtJpy(d.equity_jpy);
    document.getElementById('heroEqSub').textContent = `Baseline: ${fmtJpy(d.baseline_jpy)}`;

    const itp = document.getElementById('inTradeVal');
    itp.textContent = (d.in_trade_pnl_jpy >= 0 ? '+' : '') + fmtJpy(d.in_trade_pnl_jpy);
    itp.className = 'kpi-val ' + (d.in_trade_pnl_jpy >= 0 ? 'pos' : 'neg');
    document.getElementById('inTradePct').textContent = `${d.in_trade_pnl_pct >= 0 ? '+' : ''}${d.in_trade_pnl_pct.toFixed(2)}% on open notional`;

    document.getElementById('bpVal').textContent = fmtJpy(d.buying_power_jpy);
    document.getElementById('freeCashSub').textContent = `Free JPY: ${fmtJpy(d.free_cash_jpy)}`;

    const alertBox = document.getElementById('alertBox');
    if (d.last_error) {
      alertBox.style.display = 'block';
      alertBox.textContent = 'Last Tick Error: ' + d.last_error;
    } else if (d.state === 'EMERGENCY_STOPPED') {
      alertBox.style.display = 'block';
      alertBox.textContent = 'EMERGENCY STOP ACTIVE: All orders cancelled & positions closed. Click Resume Bot to restart.';
    } else {
      alertBox.style.display = 'none';
    }

    renderChart(d.trade_history, d.baseline_jpy, d.open_positions, d.in_trade_pnl_jpy);
    latestStatusData = d;
    const focusPair = (d.open_positions && d.open_positions.length > 0) ? d.open_positions[0].pair
      : ((d.pending_orders && d.pending_orders.length > 0) ? d.pending_orders[0].pair : null);
    if (!chartPairManual && focusPair) {
      const openPair = focusPair;
      if (openPair && openPair !== chartPair) {
        chartPair = openPair;
        const sel = document.getElementById('chartPairSel');
        if (sel) sel.value = chartPair;
        lastCandleFetchTs = 0;
      }
    }
    if (Date.now() - lastCandleFetchTs > 12000 || latestCandles.length === 0) {
      loadCandles();
    } else {
      renderMarketChart();
    }

    const ms = d.milestones;
    document.getElementById('milestonesBox').innerHTML = ['x2', 'x5', 'x10'].map((k, idx) => {
      const m = ms[k];
      const label = (idx === 0 && d.goal_target_jpy) ? 'GOAL' : ['2X', '5X', '10X'][idx];
      return `<div class="ms-row">
        <div class="ms-head"><span>${label} [${fmtJpy(m.target)}]</span><span>${m.pct.toFixed(1)}% (${fmtJpy(m.remaining)} left)</span></div>
        <div class="bar-bg"><div class="bar-fill" style="width:${m.pct}%"></div></div>
      </div>`;
    }).join('');

    if (d.rule) {
      document.getElementById('macroBox').textContent = d.rule.summary;
    }

    const posBody = document.getElementById('posBody');
    if (!d.open_positions || d.open_positions.length === 0) {
      posBody.innerHTML = '<tr><td colspan="8" style="color:var(--muted)">No open positions</td></tr>';
    } else {
      posBody.innerHTML = d.open_positions.map((p, idx) => {
        const up = Number(p.unrealized_pnl_jpy || 0);
        const estNet = Number(p.est_net_close_pnl_jpy !== undefined ? p.est_net_close_pnl_jpy : up);
        const estFee = Number(p.est_close_fee_jpy || 0);
        return `<tr><td>${p.pair}</td><td>${p.position_side}</td><td>${p.open_amount}</td><td>${p.avg_price}</td><td>${p.last_price}</td><td class="${up>=0?'pos':'neg'}">${up>=0?'+':''}${fmtJpy(up)}</td><td class="${estNet>=0?'pos':'neg'}" title="After ~${fmtJpy(estFee)} taker fee">${estNet>=0?'+':''}${fmtJpy(estNet)}</td><td><button class="btn-danger-sm" style="padding:4px 10px;font-size:11px;" onclick="closeOpenPosition(${idx})">Close</button></td></tr>`;
      }).join('');
    }
    document.getElementById('stopsLine').textContent = 'Active Exchange Stops: ' +
      (d.active_stops && d.active_stops.length ? d.active_stops.map(s => `${s.pair} #${s.order_id} @ ${s.trigger_price}`).join(', ') : '0');

    const lb = document.getElementById('lessonsBox');
    lb.innerHTML = (d.lessons && d.lessons.length)
      ? d.lessons.map(l => `<div style="margin-bottom:6px;"><b>${l.pair}</b> (${l.pnl_jpy>=0?'+':''}${fmtJpy(l.pnl_jpy)}) — ${l.cause} → <span style="color:#2563eb">${l.fix}</span></div>`).join('')
      : 'No closed trades recorded yet.';

    document.getElementById('radarBody').innerHTML = (d.signals || []).map(s =>
      `<tr><td>${s.pair}</td><td><b>${s.action}</b></td><td>${s.close ?? '--'}</td><td>${s.breakout ?? '--'}</td><td>${s.gap_pct === null ? '--' : (s.gap_pct > 0 ? s.gap_pct + '%' : 'broken out')}</td><td>${s.stop_pct === null ? '--' : s.stop_pct + '%'}</td><td>${s.note}</td></tr>`
    ).join('');

    document.getElementById('capStatus').textContent = (d.capital_limit_jpy
      ? `Cap: ${fmtJpy(d.capital_limit_jpy)} (Live Equity: ${fmtJpy(d.equity_jpy)})`
      : `100% Account Equity (Live: ${fmtJpy(d.equity_jpy)})`) + (d.rule ? ` • ${d.rule.risk_per_trade_pct}% risk per trade, up to ${d.rule.max_positions} positions` : '');
    const capInput = document.getElementById('cfgCapJpy');
    capInput.placeholder = `Current Live: ${fmtJpy(d.equity_jpy)} (0 = use 100%)`;
    if (!capInput.dataset.dirty && document.activeElement !== capInput) {
      const capV = Number(d.capital_limit_jpy || 0);
      capInput.value = capV > 0 ? capV : '';
      const cs = document.getElementById('cfgCapSlider');
      if (cs) cs.value = Math.min(500000, capV);
      document.getElementById('capBadge').textContent = capV > 0 ? fmtJpy(capV) : '100% Equity';
    }
    const baseInput = document.getElementById('cfgBaselineJpy');
    if (baseInput && document.activeElement !== baseInput && !baseInput.dataset.dirty) {
      baseInput.value = d.baseline_jpy;
      document.getElementById('baseBadge').textContent = fmtJpy(d.baseline_jpy);
    }
    const goalInput = document.getElementById('cfgGoalJpy');
    if (goalInput && document.activeElement !== goalInput && !goalInput.dataset.dirty) {
      const gV = Number(d.goal_target_jpy || 0);
      goalInput.value = gV > 0 ? gV : '';
      const gs = document.getElementById('cfgGoalSlider');
      if (gs) gs.value = Math.min(1000000, gV);
      document.getElementById('goalBadge').textContent = gV > 0 ? fmtJpy(gV) : 'Auto (2x/5x/10x)';
    }
    if (d.allow_shorts !== undefined && !document.getElementById('cfgAllowShorts').dataset.dirty) {
      setModeToggle(Boolean(d.allow_shorts), false);
    }
    const fpcInput = document.getElementById('cfgForceProfitJpy');
    if (fpcInput && document.activeElement !== fpcInput && !fpcInput.dataset.dirty) {
      const fV = Number(d.force_profit_close_jpy || 0);
      fpcInput.value = fV > 0 ? fV : '';
      const fs = document.getElementById('cfgForceProfitSlider');
      if (fs) fs.value = Math.min(10000, fV);
      document.getElementById('fpcBadge').textContent = fV > 0 ? fmtJpy(fV) : 'Off (Normal Flow)';
    }
  } catch (e) {
    console.error(e);
  }
}

async function togglePause() {
  const url = currentState === 'RUNNING' ? '/api/pause' : '/api/resume';
  await fetch(url, {method: 'POST'});
  refresh();
}

async function emergencyStopAll() {
  if (!confirm('EMERGENCY STOP: Pause bot, cancel ALL orders, and market-close ALL open positions?')) return;
  const r = await fetch('/api/emergency-stop', {method: 'POST'});
  const res = await r.json();
  alert(`STOPPED! Cancelled: ${res.cancelled_orders.length} orders | Closed: ${res.closed_positions.length} positions`);
  refresh();
}

async function closeOpenPosition(idx) {
  const p = latestPositions[idx];
  if (!p) return;
  const up = Number(p.unrealized_pnl_jpy || 0);
  const fee = Number(p.est_close_fee_jpy || (Number(p.notional_jpy || 0) * 0.0012));
  const estNet = Number(p.est_net_close_pnl_jpy !== undefined ? p.est_net_close_pnl_jpy : (up - fee));
  const msg = `CLOSE POSITION NOW?\n\n` +
    `Pair: ${p.pair.toUpperCase()} (${p.position_side.toUpperCase()})\n` +
    `Amount: ${p.open_amount}\n` +
    `Entry: ¥${p.avg_price} → Current: ¥${p.last_price}\n` +
    `Gross uPnL: ${up >= 0 ? '+' : ''}${fmtJpy(up)}\n` +
    `Est. Taker Fee (0.12%): -${fmtJpy(fee)}\n` +
    `Estimated Net Profit/Loss: ${estNet >= 0 ? '+' : ''}${fmtJpy(estNet)}`;
  if (!confirm(msg)) return;
  const r = await fetch('/api/close-position', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({pair: p.pair, position_side: p.position_side})
  });
  const res = await r.json();
  if (res.errors && res.errors.length) {
    alert(`Close completed with warnings: ${res.errors.join('; ')}`);
  } else {
    alert(`Closed ${p.pair.toUpperCase()} ${p.position_side.toUpperCase()} (cancelled ${res.cancelled_orders.length} stop/orders).`);
  }
  refresh();
}

async function removeApiKey() {
  if (!confirm('Remove the currently saved Bitbank API Key? You can add a new one right after.')) return;
  await fetch('/api/config/remove-key', {method: 'POST'});
  document.getElementById('cfgMsg').textContent = 'API Key removed. Enter a new key below to go ONLINE.';
  refresh();
}

function setModeToggle(allow, markDirty = true) {
  const el = document.getElementById('cfgAllowShorts');
  el.value = allow ? 'true' : 'false';
  if (markDirty) el.dataset.dirty = '1';
  document.getElementById('modeBothBtn').className = 'seg-btn' + (allow ? ' active' : '');
  document.getElementById('modeSpotBtn').className = 'seg-btn' + (!allow ? ' active' : '');
}

function onForceProfitSlider(v) { setForceProfit(Number(v)); }
function onForceProfitInput(v) {
  const n = Math.max(0, Number(v || 0));
  document.getElementById('cfgForceProfitJpy').dataset.dirty = '1';
  document.getElementById('cfgForceProfitSlider').value = Math.min(10000, n);
  document.getElementById('fpcBadge').textContent = n > 0 ? fmtJpy(n) : 'Off (Normal Flow)';
}
function setForceProfit(val) {
  const inp = document.getElementById('cfgForceProfitJpy');
  inp.value = val > 0 ? val : '';
  inp.dataset.dirty = '1';
  document.getElementById('cfgForceProfitSlider').value = Math.min(10000, val);
  document.getElementById('fpcBadge').textContent = val > 0 ? fmtJpy(val) : 'Off (Normal Flow)';
}

function onCapSlider(v) { setCapPreset(Number(v)); }
function onCapInput(v) {
  const n = Math.max(0, Number(v || 0));
  document.getElementById('cfgCapJpy').dataset.dirty = '1';
  document.getElementById('cfgCapSlider').value = Math.min(500000, n);
  document.getElementById('capBadge').textContent = n > 0 ? fmtJpy(n) : '100% Equity';
}
function setCapPreset(val) {
  const inp = document.getElementById('cfgCapJpy');
  inp.value = val > 0 ? val : 0;
  inp.dataset.dirty = '1';
  document.getElementById('cfgCapSlider').value = Math.min(500000, val);
  document.getElementById('capBadge').textContent = val > 0 ? fmtJpy(val) : '100% Equity';
}

function onGoalSlider(v) { setGoalPreset(Number(v)); }
function onGoalInput(v) {
  const n = Math.max(0, Number(v || 0));
  document.getElementById('cfgGoalJpy').dataset.dirty = '1';
  document.getElementById('cfgGoalSlider').value = Math.min(1000000, n);
  document.getElementById('goalBadge').textContent = n > 0 ? fmtJpy(n) : 'Auto (2x/5x/10x)';
}
function setGoalPreset(val) {
  const inp = document.getElementById('cfgGoalJpy');
  inp.value = val > 0 ? val : 0;
  inp.dataset.dirty = '1';
  document.getElementById('cfgGoalSlider').value = Math.min(1000000, val);
  document.getElementById('goalBadge').textContent = val > 0 ? fmtJpy(val) : 'Auto (2x/5x/10x)';
}

function addDeposit(amount) {
  const el = document.getElementById('cfgBaselineJpy');
  const cur = Number(el.value || 0);
  const next = (cur + amount).toFixed(1);
  el.value = next;
  el.dataset.dirty = '1';
  document.getElementById('baseBadge').textContent = fmtJpy(next);
}

function useLiveEquityBaseline() {
  if (!latestStatusData || !latestStatusData.equity_jpy) return;
  const el = document.getElementById('cfgBaselineJpy');
  el.value = latestStatusData.equity_jpy;
  el.dataset.dirty = '1';
  document.getElementById('baseBadge').textContent = fmtJpy(latestStatusData.equity_jpy);
}

async function saveConfig() {
  const apiKey = document.getElementById('cfgApiKey').value.trim();
  const apiSecret = document.getElementById('cfgApiSecret').value.trim();
  const capRaw = document.getElementById('cfgCapJpy').value.trim();
  const baseRaw = document.getElementById('cfgBaselineJpy').value.trim();
  const goalRaw = document.getElementById('cfgGoalJpy').value.trim();
  const fpcRaw = document.getElementById('cfgForceProfitJpy').value.trim();
  const allowShortsVal = document.getElementById('cfgAllowShorts').value;
  const payload = {};
  if (apiKey && apiSecret) {
    payload.api_key = apiKey;
    payload.api_secret = apiSecret;
  } else if (apiKey || apiSecret) {
    alert('Please enter both API Key and API Secret together.');
    return;
  }
  if (capRaw !== '') {
    payload.capital_limit_jpy = Number(capRaw);
  }
  if (baseRaw !== '' && Number(baseRaw) > 0) {
    payload.baseline_jpy = Number(baseRaw);
  }
  if (goalRaw !== '') {
    payload.goal_target_jpy = Number(goalRaw);
  }
  if (fpcRaw !== '') {
    payload.force_profit_close_jpy = Number(fpcRaw);
  } else if (document.getElementById('cfgForceProfitJpy').dataset.dirty) {
    payload.force_profit_close_jpy = 0;
  }
  payload.allow_shorts = (allowShortsVal === 'true');
  const r = await fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const res = await r.json();
  document.getElementById('cfgApiKey').value = '';
  document.getElementById('cfgApiSecret').value = '';
  delete document.getElementById('cfgCapJpy').dataset.dirty;
  delete document.getElementById('cfgBaselineJpy').dataset.dirty;
  delete document.getElementById('cfgGoalJpy').dataset.dirty;
  delete document.getElementById('cfgForceProfitJpy').dataset.dirty;
  delete document.getElementById('cfgAllowShorts').dataset.dirty;
  document.getElementById('cfgMsg').textContent = 'Saved: ' + (res.updated && res.updated.length ? res.updated.join(', ') : 'no changes');
  refresh();
}

function onChartPairChange(pair) {
  chartPair = pair;
  chartPairManual = true;
  lastCandleFetchTs = 0;
  loadCandles();
}

function setChartTf(tf, btn) {
  chartTf = tf;
  document.querySelectorAll('#tfBtns button').forEach(b => b.className = 'btn-glass');
  if (btn) btn.className = 'btn-primary';
  lastCandleFetchTs = 0;
  loadCandles();
}

async function loadCandles() {
  try {
    lastCandleFetchTs = Date.now();
    const r = await fetch(`/api/candles?pair=${encodeURIComponent(chartPair)}&tf=${encodeURIComponent(chartTf)}`);
    const res = await r.json();
    if (res && Array.isArray(res.candles)) {
      latestCandles = res.candles;
      renderMarketChart();
    }
  } catch (e) {
    console.error('Candle fetch failed:', e);
  }
}

function fmtPx(px) {
  const n = Number(px || 0);
  if (n >= 1000) return '¥' + Math.round(n).toLocaleString('en-US');
  if (n >= 10) return '¥' + n.toFixed(2);
  return '¥' + n.toFixed(4);
}

function emaSeries(vals, period) {
  const out = [];
  const k = 2 / (period + 1);
  let prev = null, sum = 0;
  for (let i = 0; i < vals.length; i++) {
    if (i < period) {
      sum += vals[i];
      prev = sum / (i + 1);
      out.push(i === period - 1 ? prev : null);
    } else {
      prev = vals[i] * k + prev * (1 - k);
      out.push(prev);
    }
  }
  return out;
}

function bollinger(vals, period, mult) {
  const mid = [], up = [], lo = [];
  for (let i = 0; i < vals.length; i++) {
    if (i < period - 1) { mid.push(null); up.push(null); lo.push(null); continue; }
    let s = 0;
    for (let j = i - period + 1; j <= i; j++) s += vals[j];
    const m = s / period;
    let v = 0;
    for (let j = i - period + 1; j <= i; j++) v += (vals[j] - m) * (vals[j] - m);
    const sd = Math.sqrt(v / period);
    mid.push(m); up.push(m + mult * sd); lo.push(m - mult * sd);
  }
  return {mid, up, lo};
}

function rsiSeries(vals, period) {
  const out = [null];
  let ag = 0, al = 0;
  for (let i = 1; i < vals.length; i++) {
    const ch = vals[i] - vals[i - 1];
    const g = Math.max(ch, 0), l = Math.max(-ch, 0);
    if (i <= period) {
      ag += g / period; al += l / period;
      out.push(i === period ? (al === 0 ? 100 : 100 - 100 / (1 + ag / al)) : null);
    } else {
      ag = (ag * (period - 1) + g) / period;
      al = (al * (period - 1) + l) / period;
      out.push(al === 0 ? 100 : 100 - 100 / (1 + ag / al));
    }
  }
  return out;
}

function yenSigned(v) {
  const n = Number(v || 0);
  return (n >= 0 ? '+' : '-') + '¥' + Math.abs(Math.round(n)).toLocaleString('en-US');
}

function renderMarketChart() {
  const wrap = document.getElementById('marketChartWrap');
  const legend = document.getElementById('marketChartLegend');
  const info = document.getElementById('marketChartInfo');
  if (!wrap) return;
  if (!latestCandles || latestCandles.length === 0) {
    wrap.innerHTML = '<div style="color:#8b93a7;padding-top:150px;text-align:center;">Waiting for Bitbank candle data...</div>';
    return;
  }

  const C = {
    bg: '#131722', grid: 'rgba(255,255,255,0.06)', axis: '#8b93a7', text: '#d1d4dc',
    up: '#26a69a', down: '#ef5350', bb: '#2f81f7', ema20: '#f59e0b', ema50: '#22c55e', rsi: '#c084fc',
    entry: '#6366f1', stop: '#ef4444', tp: '#16a34a', orderShort: '#e5484d', orderLong: '#16a34a'
  };

  const d = latestStatusData || {};
  const openPos = (d.open_positions || []).find(p => p.pair === chartPair) || null;
  const pending = (d.pending_orders || []).find(o => o.pair === chartPair) || null;

  const all = latestCandles;
  const closesAll = all.map(c => c.c);
  const ema20All = emaSeries(closesAll, 20);
  const ema50All = emaSeries(closesAll, 50);
  const bbAll = bollinger(closesAll, 20, 2);
  const rsiAll = rsiSeries(closesAll, 14);

  const W = Math.max(300, Math.floor(wrap.clientWidth || 1040));
  const isMobile = W < 640;
  const H = isMobile ? 430 : 480;
  wrap.style.height = H + 'px';
  const view = Math.min(all.length, isMobile ? 60 : 130);
  const off = all.length - view;
  const candles = all.slice(off);
  const n = candles.length;
  const sl = (arr) => arr.slice(off);
  const ema20 = sl(ema20All), ema50 = sl(ema50All), rsi = sl(rsiAll);
  const bbUp = sl(bbAll.up), bbLo = sl(bbAll.lo), bbMid = sl(bbAll.mid);

  const lastPx = openPos && Number(openPos.last_price || 0) > 0 ? Number(openPos.last_price) : Number(candles[n - 1].c || 0);
  const entryPx = openPos ? Number(openPos.avg_price || openPos.average_price || 0) : 0;
  const stopPx = openPos ? Number(openPos.stop_trigger_price || 0) : 0;
  const tpPx = openPos ? Number(openPos.take_profit_price || 0) : 0;
  const side = openPos ? String(openPos.position_side || 'short') : (pending ? pending.side : '');

  const padL = 6, padR = isMobile ? 74 : 86, padT = isMobile ? 46 : 30, padB = 22;  // padT leaves room for the OHLC readout
  const plotW = W - padL - padR;
  const rsiH = isMobile ? 62 : 74;
  const gap = 10;
  const priceH = H - padT - padB - rsiH - gap;
  const volH = priceH * 0.16;
  const rsiTop = padT + priceH + gap;

  const lows = candles.map(c => c.l), highs = candles.map(c => c.h);
  bbUp.forEach(v => { if (v !== null) highs.push(v); });
  bbLo.forEach(v => { if (v !== null) lows.push(v); });
  const levels = [lastPx, entryPx, stopPx, tpPx];
  if (pending) levels.push(pending.price, pending.planned_stop_price, pending.planned_take_profit_price);
  levels.forEach(v => { if (v > 0) { lows.push(v); highs.push(v); } });
  let minP = Math.min(...lows), maxP = Math.max(...highs);
  const span = Math.max(1e-9, maxP - minP);
  minP -= span * 0.05; maxP += span * 0.05;
  const pSpan = maxP - minP;

  const step = plotW / n;
  const cw = Math.max(2, Math.min(11, step * 0.7));
  const xOf = (i) => padL + i * step + step / 2;
  const yOf = (p) => padT + (1 - (p - minP) / pSpan) * priceH;
  const yRsi = (v) => rsiTop + (1 - v / 100) * rsiH;
  const fs = isMobile ? 9.5 : 10.5;

  let grid = '';
  for (let i = 0; i <= 5; i++) {
    const pv = minP + pSpan * i / 5;
    const gy = yOf(pv);
    grid += `<line x1="${padL}" y1="${gy.toFixed(1)}" x2="${W - padR}" y2="${gy.toFixed(1)}" stroke="${C.grid}"/>`;
    grid += `<text x="${W - padR + 6}" y="${(gy + 3.5).toFixed(1)}" fill="${C.axis}" font-size="${fs}">${fmtPx(pv).replace('¥', '')}</text>`;
  }

  const linePath = (arr, yf) => {
    let p = '', pen = false;
    arr.forEach((v, i) => {
      if (v === null || v === undefined) { pen = false; return; }
      p += (pen ? 'L' : 'M') + xOf(i).toFixed(1) + ' ' + yf(v).toFixed(1) + ' ';
      pen = true;
    });
    return p;
  };

  let bbFill = '';
  const firstBb = bbUp.findIndex(v => v !== null);
  if (firstBb >= 0) {
    let top = '', bot = '';
    for (let i = firstBb; i < n; i++) top += (i === firstBb ? 'M' : 'L') + xOf(i).toFixed(1) + ' ' + yOf(bbUp[i]).toFixed(1) + ' ';
    for (let i = n - 1; i >= firstBb; i--) bot += 'L' + xOf(i).toFixed(1) + ' ' + yOf(bbLo[i]).toFixed(1) + ' ';
    bbFill = `<path d="${top}${bot}Z" fill="rgba(47,129,247,0.07)"/>`;
  }

  const maxVol = Math.max(1e-9, ...candles.map(c => c.v));
  let body = '';
  candles.forEach((c, i) => {
    const cx = xOf(i);
    const col = c.c >= c.o ? C.up : C.down;
    const yO = yOf(c.o), yC = yOf(c.c);
    const vh = (c.v / maxVol) * volH;
    body += `<rect x="${(cx - cw / 2).toFixed(1)}" y="${(padT + priceH - vh).toFixed(1)}" width="${cw.toFixed(1)}" height="${vh.toFixed(1)}" fill="${col}" opacity="0.28"/>`;
    body += `<line x1="${cx.toFixed(1)}" y1="${yOf(c.h).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${yOf(c.l).toFixed(1)}" stroke="${col}" stroke-width="1"/>`;
    body += `<rect x="${(cx - cw / 2).toFixed(1)}" y="${Math.min(yO, yC).toFixed(1)}" width="${cw.toFixed(1)}" height="${Math.max(1, Math.abs(yC - yO)).toFixed(1)}" fill="${col}"/>`;
  });

  const indicators = `
    ${bbFill}
    <path d="${linePath(bbUp, yOf)}" fill="none" stroke="${C.bb}" stroke-width="1.1"/>
    <path d="${linePath(bbLo, yOf)}" fill="none" stroke="${C.bb}" stroke-width="1.1"/>
    <path d="${linePath(bbMid, yOf)}" fill="none" stroke="${C.bb}" stroke-width="0.8" opacity="0.5"/>
    <path d="${linePath(ema50, yOf)}" fill="none" stroke="${C.ema50}" stroke-width="1.3"/>
    <path d="${linePath(ema20, yOf)}" fill="none" stroke="${C.ema20}" stroke-width="1.3"/>`;

  // Horizontal trade levels: a line across the plot plus a price tag on the right axis
  const tags = [];
  let lines = '';
  const addLevel = (px, color, dash, width) => {
    if (!px || px <= 0) return;
    const y = yOf(px);
    lines += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" stroke="${color}" stroke-width="${width || 1.2}" ${dash ? `stroke-dasharray="${dash}"` : ''}/>`;
    tags.push({y, color, text: fmtPx(px).replace('¥', '')});
  };
  // A labelled box sitting on the line, like the exchange app's order marker
  const boxes = [];
  const addBox = (px, color, label, value) => {
    if (!px || px <= 0) return;
    boxes.push({y: yOf(px), color, label, value});
  };

  const lastCol = candles[n - 1].c >= candles[n - 1].o ? C.up : C.down;
  addLevel(lastPx, lastCol, '2 3', 1);
  if (openPos && entryPx > 0) {
    addLevel(tpPx, C.tp, '5 4');
    addLevel(stopPx, C.stop, '5 4');
    addLevel(entryPx, C.entry, '', 1.5);
    addBox(entryPx, C.entry, `${side.toUpperCase()} ${openPos.open_amount || openPos.amount || ''}`, yenSigned(openPos.unrealized_pnl_jpy));
    if (tpPx > 0) addBox(tpPx, C.tp, 'TP', openPos.est_tp_pnl_jpy !== undefined ? yenSigned(openPos.est_tp_pnl_jpy) : '');
    if (stopPx > 0) addBox(stopPx, C.stop, 'SL', openPos.est_stop_pnl_jpy !== undefined ? yenSigned(openPos.est_stop_pnl_jpy) : '');
  } else if (pending) {
    const oc = pending.side === 'short' ? C.orderShort : C.orderLong;
    if (pending.planned_take_profit_price > 0) addLevel(pending.planned_take_profit_price, C.tp, '2 4', 1);
    addLevel(pending.planned_stop_price, C.stop, '2 4', 1);
    addLevel(pending.price, oc, '', 1.4);
    addBox(pending.price, oc, `${pending.side === 'short' ? 'SELL' : 'BUY'} LIMIT`, String(pending.amount));
    if (pending.planned_take_profit_price > 0) addBox(pending.planned_take_profit_price, C.tp, 'TP plan', yenSigned(pending.est_tp_pnl_jpy));
    addBox(pending.planned_stop_price, C.stop, 'SL plan', yenSigned(pending.est_stop_pnl_jpy));
  }

  // Keep axis tags from overlapping
  tags.sort((a, b) => a.y - b.y);
  for (let i = 1; i < tags.length; i++) if (tags[i].y - tags[i - 1].y < 17) tags[i].y = tags[i - 1].y + 17;
  let tagHtml = '';
  tags.forEach(t => {
    tagHtml += `<rect x="${W - padR + 1}" y="${(t.y - 8.5).toFixed(1)}" width="${padR - 3}" height="17" rx="3" fill="${t.color}"/>`;
    tagHtml += `<text x="${W - padR + 6}" y="${(t.y + 3.6).toFixed(1)}" fill="#ffffff" font-size="${fs}" font-weight="700">${t.text}</text>`;
  });

  boxes.sort((a, b) => a.y - b.y);
  for (let i = 1; i < boxes.length; i++) if (boxes[i].y - boxes[i - 1].y < 19) boxes[i].y = boxes[i - 1].y + 19;
  let boxHtml = '';
  const boxFs = isMobile ? 9.5 : 10.5;
  boxes.forEach(b => {
    const w1 = b.label.length * boxFs * 0.62 + 12;
    const w2 = b.value ? b.value.length * boxFs * 0.62 + 12 : 0;
    const x0 = Math.max(padL + 4, W - padR - w1 - w2 - (isMobile ? 8 : 60));
    boxHtml += `<rect x="${x0.toFixed(1)}" y="${(b.y - 9).toFixed(1)}" width="${w1.toFixed(1)}" height="18" fill="#ffffff" stroke="${b.color}" stroke-width="1"/>`;
    boxHtml += `<text x="${(x0 + 6).toFixed(1)}" y="${(b.y + 3.8).toFixed(1)}" fill="${b.color}" font-size="${boxFs}" font-weight="800">${b.label}</text>`;
    if (b.value) {
      boxHtml += `<rect x="${(x0 + w1).toFixed(1)}" y="${(b.y - 9).toFixed(1)}" width="${w2.toFixed(1)}" height="18" fill="${b.color}"/>`;
      boxHtml += `<text x="${(x0 + w1 + 6).toFixed(1)}" y="${(b.y + 3.8).toFixed(1)}" fill="#ffffff" font-size="${boxFs}" font-weight="800">${b.value}</text>`;
    }
  });

  // RSI pane
  const lastRsi = [...rsi].reverse().find(v => v !== null && v !== undefined);
  let rsiHtml = `<rect x="${padL}" y="${yRsi(70).toFixed(1)}" width="${plotW}" height="${(yRsi(30) - yRsi(70)).toFixed(1)}" fill="rgba(192,132,252,0.08)"/>`;
  [70, 50, 30].forEach(v => {
    rsiHtml += `<line x1="${padL}" y1="${yRsi(v).toFixed(1)}" x2="${W - padR}" y2="${yRsi(v).toFixed(1)}" stroke="rgba(255,255,255,0.18)" stroke-dasharray="4 4"/>`;
    rsiHtml += `<text x="${W - padR + 6}" y="${(yRsi(v) + 3.5).toFixed(1)}" fill="${C.axis}" font-size="${fs}">${v}</text>`;
  });
  rsiHtml += `<path d="${linePath(rsi, yRsi)}" fill="none" stroke="${C.rsi}" stroke-width="1.3"/>`;
  rsiHtml += `<text x="${padL + 4}" y="${rsiTop + 12}" fill="${C.axis}" font-size="${fs}" font-weight="700">RSI 14</text>`;
  if (lastRsi !== undefined) {
    const ry = yRsi(lastRsi);
    rsiHtml += `<rect x="${W - padR + 1}" y="${(ry - 8.5).toFixed(1)}" width="${padR - 3}" height="17" rx="3" fill="${C.rsi}"/>`;
    rsiHtml += `<text x="${W - padR + 6}" y="${(ry + 3.6).toFixed(1)}" fill="#1e1033" font-size="${fs}" font-weight="800">${lastRsi.toFixed(2)}</text>`;
  }

  // Time axis
  const tfDaily = chartTf === '1hour' || chartTf === '4hour';
  const fmtT = (ms) => {
    const dt = new Date(ms);
    return tfDaily ? `${dt.getMonth() + 1}/${dt.getDate()}` : dt.toLocaleTimeString('ja-JP', {hour: '2-digit', minute: '2-digit'});
  };
  let timeHtml = '';
  const ticks = isMobile ? 4 : 7;
  for (let i = 0; i < ticks; i++) {
    const idx = Math.min(n - 1, Math.round((n - 1) * i / (ticks - 1)));
    const anchor = i === 0 ? 'start' : (i === ticks - 1 ? 'end' : 'middle');
    timeHtml += `<text x="${xOf(idx).toFixed(1)}" y="${H - 6}" fill="${C.axis}" font-size="${fs}" text-anchor="${anchor}">${fmtT(candles[idx].t)}</text>`;
  }

  const ohlcText = (c, i) => {
    const chg = c.o > 0 ? (c.c - c.o) / c.o * 100 : 0;
    const col = c.c >= c.o ? C.up : C.down;
    const r = rsi[i];
    const ohlc = isMobile
      ? `H ${fmtPx(c.h).replace('¥', '')} L ${fmtPx(c.l).replace('¥', '')} C ${fmtPx(c.c).replace('¥', '')} (${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%)`
      : `O ${fmtPx(c.o).replace('¥', '')} H ${fmtPx(c.h).replace('¥', '')} L ${fmtPx(c.l).replace('¥', '')} C ${fmtPx(c.c).replace('¥', '')} (${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%)`;
    return `<span style="color:${C.text};">${new Date(c.t).toLocaleString('ja-JP', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'})}</span>
      <span style="color:${col};">${ohlc}</span>
      <span style="color:${C.ema20};">EMA20 ${ema20[i] ? fmtPx(ema20[i]).replace('¥', '') : '--'}</span>
      <span style="color:${C.ema50};">EMA50 ${ema50[i] ? fmtPx(ema50[i]).replace('¥', '') : '--'}</span>
      ${isMobile ? '' : `<span style="color:${C.bb};">BB ${bbLo[i] ? fmtPx(bbLo[i]).replace('¥', '') : '--'} – ${bbUp[i] ? fmtPx(bbUp[i]).replace('¥', '') : '--'}</span>`}
      <span style="color:${C.rsi};">RSI ${r !== null && r !== undefined ? r.toFixed(1) : '--'}</span>`;
  };

  wrap.style.background = C.bg;
  wrap.style.borderRadius = '12px';
  wrap.style.overflow = 'hidden';
  wrap.innerHTML = `
    <div id="marketTooltip" style="position:absolute;top:6px;left:10px;right:${isMobile ? 8 : padR + 6}px;display:flex;flex-wrap:wrap;gap:${isMobile ? '1px 8px' : '4px 10px'};font-size:${isMobile ? 9.5 : 11}px;font-weight:700;pointer-events:none;z-index:5;line-height:1.3;max-height:${isMobile ? 38 : 22}px;overflow:hidden;"></div>
    <svg id="marketSvg" viewBox="0 0 ${W} ${H}" width="100%" height="100%" style="cursor:crosshair;display:block;">
      <rect x="0" y="0" width="${W}" height="${H}" fill="${C.bg}"/>
      ${grid}
      ${indicators}
      ${body}
      ${lines}
      ${rsiHtml}
      <line x1="${padL}" y1="${(rsiTop - gap / 2).toFixed(1)}" x2="${W}" y2="${(rsiTop - gap / 2).toFixed(1)}" stroke="rgba(255,255,255,0.14)"/>
      <line id="crossV" x1="0" y1="${padT}" x2="0" y2="${rsiTop + rsiH}" stroke="rgba(255,255,255,0.35)" stroke-dasharray="3 3" style="display:none;"/>
      ${boxHtml}
      ${tagHtml}
      ${timeHtml}
    </svg>`;

  const svg = document.getElementById('marketSvg');
  const tip = document.getElementById('marketTooltip');
  const crossV = document.getElementById('crossV');
  tip.innerHTML = ohlcText(candles[n - 1], n - 1);
  if (svg && crossV) {
    const showAt = (clientX) => {
      const rect = svg.getBoundingClientRect();
      const relX = ((clientX - rect.left) / rect.width) * W;
      const idx = Math.max(0, Math.min(n - 1, Math.floor((relX - padL) / step)));
      crossV.setAttribute('x1', xOf(idx).toFixed(1));
      crossV.setAttribute('x2', xOf(idx).toFixed(1));
      crossV.style.display = 'block';
      tip.innerHTML = ohlcText(candles[idx], idx);
    };
    const hide = () => { crossV.style.display = 'none'; tip.innerHTML = ohlcText(candles[n - 1], n - 1); };
    svg.addEventListener('mousemove', (ev) => showAt(ev.clientX));
    svg.addEventListener('mouseleave', hide);
    svg.addEventListener('touchstart', (ev) => { if (ev.touches && ev.touches[0]) showAt(ev.touches[0].clientX); }, {passive: true});
    svg.addEventListener('touchmove', (ev) => { if (ev.touches && ev.touches[0]) showAt(ev.touches[0].clientX); }, {passive: true});
    svg.addEventListener('touchend', hide);
  }

  // Header legend and the trade summary strip under the chart
  if (legend) {
    const state = openPos ? `<span style="color:${C.entry};">● ${side.toUpperCase()} position open</span>`
      : (pending ? `<span style="color:${pending.side === 'short' ? C.orderShort : C.orderLong};">● ${pending.side === 'short' ? 'Sell' : 'Buy'} limit waiting to fill</span>`
        : '<span>No position or order on this pair</span>');
    legend.innerHTML = `<span style="color:#0f172a;">Last: <b>${fmtPx(lastPx)}</b></span>${state}`;
  }
  if (info) {
    const chip = (label, value, color) => `<div style="padding:6px 10px;border-radius:9px;background:rgba(15,23,42,0.05);min-width:92px;">
      <div style="font-size:10.5px;font-weight:700;color:var(--muted);">${label}</div>
      <div style="font-size:13px;font-weight:800;color:${color || '#0f172a'};">${value}</div></div>`;
    let html = '';
    if (openPos && entryPx > 0) {
      const gainPct = side === 'short' ? (entryPx - lastPx) / entryPx * 100 : (lastPx - entryPx) / entryPx * 100;
      const upnl = Number(openPos.unrealized_pnl_jpy || 0);
      html += chip('Position', `${side.toUpperCase()} ${openPos.open_amount || openPos.amount || ''}`, C.entry);
      html += chip('Entry', fmtPx(entryPx));
      html += chip('Last', fmtPx(lastPx));
      html += chip('Unrealized', `${yenSigned(upnl)} (${gainPct >= 0 ? '+' : ''}${gainPct.toFixed(2)}%)`, upnl >= 0 ? C.tp : C.stop);
      html += chip('Stop loss', stopPx > 0 ? `${fmtPx(stopPx)}${openPos.est_stop_pnl_jpy !== undefined ? ' · ' + yenSigned(openPos.est_stop_pnl_jpy) : ''}` : 'NOT SET', C.stop);
      html += chip(tpPx > 0 ? 'Take profit' : 'Exit', tpPx > 0 ? `${fmtPx(tpPx)}${openPos.est_tp_pnl_jpy !== undefined ? ' · ' + yenSigned(openPos.est_tp_pnl_jpy) : ''}` : (openPos.owner === 'manual' ? 'manual position: the bot only keeps a stop on it' : 'trailing stop (no fixed target)'), C.tp);
      if (stopPx > 0 && tpPx > 0 && Math.abs(stopPx - entryPx) > 0) {
        html += chip('Reward : risk', (Math.abs(entryPx - tpPx) / Math.abs(stopPx - entryPx)).toFixed(2) + ' : 1');
      }
    } else if (pending) {
      const oc = pending.side === 'short' ? C.orderShort : C.orderLong;
      const dist = lastPx > 0 ? (pending.price - lastPx) / lastPx * 100 : 0;
      html += chip('Pending order', `${pending.side === 'short' ? 'SELL' : 'BUY'} LIMIT ${pending.amount}`, oc);
      html += chip('Order price', `${fmtPx(pending.price)} (${dist >= 0 ? '+' : ''}${dist.toFixed(2)}% from last)`);
      html += chip('Planned stop', `${fmtPx(pending.planned_stop_price)} · ${yenSigned(pending.est_stop_pnl_jpy)}`, C.stop);
      if (pending.planned_take_profit_price > 0) html += chip('Planned target', `${fmtPx(pending.planned_take_profit_price)} · ${yenSigned(pending.est_tp_pnl_jpy)}`, C.tp);
    }
    info.innerHTML = html;
    info.style.display = html ? 'flex' : 'none';
  }
}

window.addEventListener('resize', () => {
  if (latestCandles && latestCandles.length) renderMarketChart();
  if (latestStatusData) renderChart(latestStatusData.trade_history, latestStatusData.baseline_jpy, latestStatusData.open_positions, latestStatusData.in_trade_pnl_jpy);
});

refresh();
setInterval(refresh, 5000);
loadTaxReport();

function scrollToTax() {
  const el = document.getElementById('taxCard');
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  loadTaxReport();
}

function renderTaxReport(rep) {
  if (!rep) return;
  const est = rep.tax_estimate || {};
  const prof = rep.profile || {};

  const yrSel = document.getElementById('taxYearSel');
  if (yrSel && prof.tax_year) yrSel.value = String(prof.tax_year);
  const empSel = document.getElementById('taxEmpSel');
  if (empSel && prof.employment_type) empSel.value = prof.employment_type;
  const salIn = document.getElementById('taxSalaryJpy');
  if (salIn && document.activeElement !== salIn) salIn.value = prof.annual_salary_jpy > 0 ? Math.round(prof.annual_salary_jpy) : '';
  const othIn = document.getElementById('taxOtherMiscJpy');
  if (othIn && document.activeElement !== othIn) othIn.value = prof.other_misc_income_jpy > 0 ? Math.round(prof.other_misc_income_jpy) : '';
  const nameIn = document.getElementById('taxName');
  if (nameIn && document.activeElement !== nameIn) nameIn.value = prof.taxpayer_name || '';
  const offIn = document.getElementById('taxOffice');
  if (offIn && document.activeElement !== offIn) offIn.value = prof.tax_office || '';

  const req = !!est.national_filing_required;
  const badge = document.getElementById('taxFilingBadge');
  if (badge) {
    if (req) {
      badge.textContent = 'FILING REQUIRED (確定申告)';
      badge.style.background = 'rgba(220,38,38,0.12)';
      badge.style.color = '#b91c1c';
    } else {
      badge.textContent = 'UNDER ¥200K THRESHOLD';
      badge.style.background = 'rgba(22,163,74,0.12)';
      badge.style.color = '#15803d';
    }
  }

  const pct = Math.max(0, Math.min(100, Number(est.threshold_pct || 0)));
  const pctEl = document.getElementById('taxThresholdPct');
  if (pctEl) pctEl.textContent = pct.toFixed(1) + '% of ¥200,000';
  const barEl = document.getElementById('taxThresholdBar');
  if (barEl) {
    barEl.style.width = pct + '%';
    barEl.style.background = req
      ? 'linear-gradient(90deg,#ef4444,#b91c1c)'
      : 'linear-gradient(90deg,#16a34a,#22c55e)';
  }

  const net = Number(rep.net_realized_profit_jpy || 0);
  const verdictEl = document.getElementById('taxVerdictBox');
  if (verdictEl) {
    verdictEl.textContent = est.filing_advice || est.resident_tax_note || '';
    if (req) {
      verdictEl.style.background = 'rgba(239,68,68,0.12)';
      verdictEl.style.borderColor = 'rgba(220,38,38,0.35)';
      verdictEl.style.color = '#991b1b';
    } else if (net > 0) {
      verdictEl.style.background = 'rgba(245,158,11,0.12)';
      verdictEl.style.borderColor = 'rgba(217,119,6,0.35)';
      verdictEl.style.color = '#92400e';
    } else {
      verdictEl.style.background = 'rgba(22,163,74,0.1)';
      verdictEl.style.borderColor = 'rgba(22,163,74,0.28)';
      verdictEl.style.color = '#14532d';
    }
  }
  const netEl = document.getElementById('taxNetVal');
  if (netEl) {
    netEl.textContent = (net >= 0 ? '+' : '') + fmtJpy(net);
    netEl.className = 'kpi-val ' + (net >= 0 ? 'pos' : 'neg');
  }
  const grossSub = document.getElementById('taxGrossSub');
  if (grossSub) grossSub.textContent = 'Gross PnL: ' + fmtJpy(rep.gross_realized_pnl_jpy || 0);

  const fees = Number(rep.total_fees_jpy || 0);
  const feesEl = document.getElementById('taxFeesVal');
  if (feesEl) {
    feesEl.textContent = (fees > 0 ? '-' : fees < 0 ? '+' : '') + fmtJpy(Math.abs(fees));
    feesEl.className = 'kpi-val ' + (fees <= 0 ? 'pos' : '');
  }
  const intSub = document.getElementById('taxIntSub');
  if (intSub) intSub.textContent = (fees < 0 ? 'Maker rebates earned! ' : '') + 'Interest: ' + fmtJpy(rep.total_interest_jpy || 0);

  const estEl = document.getElementById('taxEstVal');
  if (estEl) estEl.textContent = fmtJpy(est.estimated_tax_jpy || 0);
  const rateSub = document.getElementById('taxRateSub');
  if (rateSub) rateSub.textContent = 'Eff. Rate: ' + Number(est.effective_rate_pct || 0).toFixed(1) + '%';

  const remEl = document.getElementById('taxRemVal');
  if (remEl) remEl.textContent = fmtJpy(est.remaining_to_threshold_jpy || 0);
  const trSub = document.getElementById('taxTradesSub');
  if (trSub) trSub.textContent = 'Fills this year: ' + (rep.total_trades || 0);

  const srcNote = document.getElementById('taxDataSourceNote');
  if (srcNote) {
    srcNote.textContent = rep.data_source === 'bitbank_trade_history'
      ? `Synced directly from Bitbank ${rep.tax_year} JST trade history`
      : `Offline/Fallback source (${rep.data_source || 'local'})`;
  }
  const resNote = document.getElementById('taxResidentNote');
  if (resNote) resNote.textContent = est.resident_tax_note || '';

  const mBody = document.getElementById('taxMonthlyBody');
  if (mBody) {
    const mRows = rep.monthly_breakdown || [];
    mBody.innerHTML = mRows.length === 0
      ? '<tr><td colspan="6" style="color:var(--muted);">No realized trades recorded for this year yet.</td></tr>'
      : mRows.map(m => `<tr>
          <td><b>${m.month}</b></td>
          <td>${m.trades}</td>
          <td>${fmtJpy(m.gross_pnl_jpy)}</td>
          <td>${fmtJpy(m.fees_jpy)}</td>
          <td>${fmtJpy(m.interest_jpy)}</td>
          <td class="${m.net_pnl_jpy >= 0 ? 'pos' : 'neg'}"><b>${(m.net_pnl_jpy >= 0 ? '+' : '') + fmtJpy(m.net_pnl_jpy)}</b></td>
        </tr>`).join('');
  }

  const lBody = document.getElementById('taxLedgerBody');
  if (lBody) {
    const lRows = rep.recent_ledger || [];
    lBody.innerHTML = lRows.length === 0
      ? '<tr><td colspan="8" style="color:var(--muted);">No fills found for this tax year.</td></tr>'
      : lRows.map(r => `<tr>
          <td>${r.time_jst || ''}</td>
          <td><b>${(r.pair || '').toUpperCase().replace('_JPY', '')}</b></td>
          <td>${r.side || ''}</td>
          <td>${Number(r.amount || 0).toFixed(4)}</td>
          <td>${fmtPx(r.price_jpy || 0)}</td>
          <td>${fmtJpy(r.gross_pnl_jpy || 0)}</td>
          <td>${fmtJpy(r.fee_jpy || 0)}</td>
          <td class="${r.net_pnl_jpy >= 0 ? 'pos' : 'neg'}"><b>${(r.net_pnl_jpy >= 0 ? '+' : '') + fmtJpy(r.net_pnl_jpy)}</b></td>
        </tr>`).join('');
  }
}

async function loadTaxReport(yearVal) {
  try {
    const yr = yearVal || (document.getElementById('taxYearSel') ? document.getElementById('taxYearSel').value : '');
    const qs = yr ? ('?year=' + encodeURIComponent(yr)) : '';
    const r = await fetch('/api/tax' + qs);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const rep = await r.json();
    renderTaxReport(rep);
  } catch (e) {
    const el = document.getElementById('taxDataSourceNote');
    if (el) el.textContent = 'Could not load tax report: ' + (e.message || e);
    const badge = document.getElementById('taxFilingBadge');
    if (badge && badge.textContent === 'CHECKING...') badge.textContent = 'RETRY NEEDED';
  }
}

async function saveTaxProfile() {
  const msg = document.getElementById('taxMsg');
  try {
    const payload = {
      tax_year: Number(document.getElementById('taxYearSel').value || 2026),
      employment_type: document.getElementById('taxEmpSel').value || 'salary',
      annual_salary_jpy: Number(document.getElementById('taxSalaryJpy').value || 0),
      other_misc_income_jpy: Number(document.getElementById('taxOtherMiscJpy').value || 0),
      taxpayer_name: document.getElementById('taxName').value || '',
      tax_office: document.getElementById('taxOffice').value || '',
    };
    const r = await fetch('/api/tax/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const rep = await r.json();
    renderTaxReport(rep);
    if (msg) {
      msg.style.color = 'var(--green)';
      msg.textContent = 'Saved & recalculated!';
      setTimeout(() => { msg.textContent = ''; }, 3000);
    }
  } catch (e) {
    if (msg) {
      msg.style.color = 'var(--red)';
      msg.textContent = 'Save failed: ' + (e.message || e);
    }
  }
}

function downloadTaxCsv() {
  const yr = document.getElementById('taxYearSel') ? document.getElementById('taxYearSel').value : '';
  window.location.href = '/api/tax/csv' + (yr ? ('?year=' + encodeURIComponent(yr)) : '');
}

let deferredPwaPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPwaPrompt = e;
  const btn = document.getElementById('installPwaBtn');
  if (btn) btn.style.display = 'block';
});
async function installPwa() {
  if (!deferredPwaPrompt) return;
  deferredPwaPrompt.prompt();
  await deferredPwaPrompt.userChoice;
  deferredPwaPrompt = null;
  const btn = document.getElementById('installPwaBtn');
  if (btn) btn.style.display = 'none';
}
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
</script>
</body>
</html>"""


def render_login_html(error: str = "") -> str:
    err_block = f'<div class="err-box">{error}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
<title>Sign In — Bitbank Autonomous AI Trading Desk</title>
<style>
  :root {{
    --bg-grad: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 45%, #ede9fe 100%);
    --glass: rgba(255, 255, 255, 0.72);
    --glass-border: rgba(255, 255, 255, 0.9);
    --shadow: 0 20px 50px rgba(15, 23, 42, 0.12);
    --text: #0f172a; --muted: #475569;
  }}
  * {{ box-sizing: border-box; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }}
  body {{
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    padding: 24px; background: var(--bg-grad); color: var(--text);
  }}
  .login-card {{
    width: 100%; max-width: 420px; padding: 32px 28px; border-radius: 22px;
    background: var(--glass); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--glass-border); box-shadow: var(--shadow);
  }}
  .brand {{ display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; background: #16a34a; box-shadow: 0 0 8px rgba(22,163,74,0.6); }}
  h1 {{ margin: 0; font-size: 20px; font-weight: 800; letter-spacing: -0.2px; }}
  .sub {{ color: var(--muted); font-size: 13px; margin-bottom: 22px; }}
  .field {{ margin-bottom: 15px; }}
  .field label {{ display: block; font-size: 12px; font-weight: 700; color: var(--muted); margin-bottom: 6px; }}
  .field input {{
    width: 100%; padding: 11px 13px; border-radius: 10px; font-size: 14px;
    border: 1px solid rgba(15,23,42,0.14); background: rgba(255,255,255,0.92); color: var(--text);
    outline: none; transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }}
  .field input:focus {{ border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.15); }}
  .btn-submit {{
    width: 100%; margin-top: 6px; padding: 12px 16px; border: none; border-radius: 11px;
    background: linear-gradient(135deg, #2563eb, #1d4ed8); color: #fff;
    font-size: 14px; font-weight: 700; cursor: pointer;
    box-shadow: 0 6px 18px rgba(37,99,235,0.28); transition: transform 0.15s ease;
  }}
  .btn-submit:active {{ transform: scale(0.98); }}
  .err-box {{
    margin-bottom: 16px; padding: 10px 12px; border-radius: 10px; font-size: 13px; font-weight: 600;
    background: rgba(239,68,68,0.12); border: 1px solid rgba(220,38,38,0.35); color: #991b1b;
  }}
</style>
</head>
<body>
  <form class="login-card" method="post" action="/login">
    <div class="brand"><span class="dot"></span><h1>Bitbank Trading Desk</h1></div>
    <div class="sub">Sign in to access your autonomous trading controls</div>
    {err_block}
    <div class="field">
      <label for="username">Username</label>
      <input id="username" name="username" type="text" autocomplete="username" required autofocus />
    </div>
    <div class="field">
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required />
    </div>
    <button class="btn-submit" type="submit">Sign In</button>
  </form>
</body>
</html>"""
