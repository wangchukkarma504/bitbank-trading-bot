"""The dashboard's Prediction page (/predict): live candles with predicted candles on top, and a profit calculator."""

PREDICT_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Prediction · Bitbank Bot</title>
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#0b0e14">
<style>
  :root {
    --bg: #0b0e14; --panel: #131722; --panel2: #1a2030; --border: #232a3a; --border2: #2e3648;
    --text: #e6e9ef; --muted: #8b93a7; --dim: #5f6880;
    --up: #26a69a; --down: #ef5350; --blue: #3b82f6; --blue2: #60a5fa; --amber: #f59e0b;
    --chart-bg: #131722; --radius: 16px;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body { margin: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, "Hiragino Sans", sans-serif;
         background: var(--bg); color: var(--text); min-height: 100vh; font-size: 14px; -webkit-font-smoothing: antialiased; }
  body.noscroll { overflow: hidden; }
  button, select, input { font-family: inherit; }

  /* top bar */
  .topbar { position: relative; z-index: 50; background: rgba(11,14,20,0.86); backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px); border-bottom: 1px solid var(--border);
            padding: max(10px, calc(env(safe-area-inset-top) + 6px)) max(14px, env(safe-area-inset-right)) 10px max(14px, env(safe-area-inset-left)); }
  .topbar-in { max-width: 1500px; margin: 0 auto; display: flex; align-items: center; gap: 12px; }
  .back { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; color: var(--text);
          background: var(--panel2); border: 1px solid var(--border); text-decoration: none; font-size: 18px; flex: none; }
  .ttl { flex: 1; min-width: 0; }
  .ttl h1 { font-size: 17px; margin: 0; font-weight: 800; letter-spacing: -0.01em; display: flex; align-items: center; gap: 8px; }
  .tag { font-size: 10px; font-weight: 800; letter-spacing: .06em; color: var(--amber); border: 1px solid rgba(245,158,11,0.4);
         background: rgba(245,158,11,0.1); padding: 2px 6px; border-radius: 6px; }
  .sub { color: var(--muted); font-size: 11.5px; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .px { text-align: right; flex: none; }
  .px .p { font-size: 18px; font-weight: 800; font-variant-numeric: tabular-nums; }
  .px .c { font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; }

  .wrap { max-width: 1500px; margin: 0 auto; padding: 12px max(12px, env(safe-area-inset-right)) 40px max(12px, env(safe-area-inset-left)); }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; margin-top: 12px; }
  .card h2 { font-size: 15px; margin: 0 0 12px; font-weight: 800; display: flex; align-items: center; gap: 8px; }
  .card h2 .muted { font-weight: 600; color: var(--muted); font-size: 12px; }

  /* chart card and its controls */
  #chartCard { padding: 10px; margin-top: 0; }
  .bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }
  .bar select { appearance: none; -webkit-appearance: none; background: var(--panel2) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%238b93a7' stroke-width='1.6' fill='none'/%3E%3C/svg%3E") no-repeat right 10px center;
                color: var(--text); border: 1px solid var(--border2); border-radius: 10px; padding: 8px 28px 8px 12px; font-weight: 800; font-size: 13px; }
  .seg { display: inline-flex; align-items: center; background: var(--panel2); border: 1px solid var(--border); border-radius: 11px; padding: 3px; gap: 2px; }
  .seg .lbl { font-size: 10px; font-weight: 800; color: var(--dim); text-transform: uppercase; letter-spacing: .06em; padding: 0 6px 0 5px; }
  .seg button { border: none; background: transparent; color: var(--muted); border-radius: 8px; padding: 6px 10px; font-weight: 800; font-size: 12.5px; cursor: pointer; }
  .seg button.on { background: var(--blue); color: #fff; box-shadow: 0 2px 8px rgba(59,130,246,0.35); }
  .seg button:disabled { opacity: 0.3; cursor: default; }
  .bar .grow { flex: 1; }
  .chip { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 700; color: var(--muted); cursor: pointer;
          background: var(--panel2); border: 1px solid var(--border); border-radius: 10px; padding: 7px 10px; }
  .chip input { accent-color: var(--blue); margin: 0; }
  .fsbtn { border: 1px solid var(--border2); background: var(--panel2); color: var(--text); border-radius: 10px; padding: 7px 12px;
           font-weight: 800; font-size: 12.5px; cursor: pointer; }
  .hint { font-size: 11px; color: var(--dim); margin: 8px 2px 0; text-align: center; }
  #chartBox { position: relative; width: 100%; height: 600px; background: var(--chart-bg); border-radius: 12px; overflow: hidden;
              touch-action: none; user-select: none; -webkit-user-select: none; cursor: grab; border: 1px solid var(--border); }
  #chartBox.drag { cursor: grabbing; }
  #chart { width: 100%; height: 100%; display: block; }

  #chartCard.fs { position: fixed; z-index: 1000; margin: 0; border-radius: 0; border: none; top: 0; left: 0;
                  width: 100vw; height: 100vh; height: 100dvh; background: var(--bg);
                  padding: max(6px, env(safe-area-inset-top)) max(8px, env(safe-area-inset-right))
                           max(6px, env(safe-area-inset-bottom)) max(8px, env(safe-area-inset-left)); }
  /* turned sideways on an upright phone: the card's left edge is the screen's top (status bar, notch) and its right
     edge the screen's bottom (home bar) */
  #chartCard.fs.rot { width: 100vh; width: 100dvh; height: 100vw; transform: rotate(90deg) translateY(-100%); transform-origin: top left;
                      padding: 6px max(8px, env(safe-area-inset-bottom)) 6px max(8px, calc(env(safe-area-inset-top) + 4px)); }
  #chartCard.fs .bar { margin-bottom: 6px; }
  #chartCard.fs .hint { display: none; }
  #chartCard.fs #chartBox { border-radius: 8px; }

  /* summary tiles */
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
  .kpi { background: var(--panel2); border: 1px solid var(--border); border-radius: 12px; padding: 12px; }
  .kpi .l { font-size: 10.5px; color: var(--muted); font-weight: 800; text-transform: uppercase; letter-spacing: .05em; }
  .kpi .v { font-size: 20px; font-weight: 800; margin-top: 6px; font-variant-numeric: tabular-nums; }
  .kpi .s { font-size: 11.5px; color: var(--muted); margin-top: 5px; line-height: 1.4; }

  /* calculator */
  .calc { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; align-items: end; }
  .field label { display: block; font-size: 10.5px; font-weight: 800; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
  .money { position: relative; }
  .money span { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: var(--muted); font-weight: 800; font-size: 16px; }
  .field input, .field select { width: 100%; background: var(--panel2); border: 1px solid var(--border2); border-radius: 11px; padding: 11px 12px;
         font-size: 17px; font-weight: 800; color: var(--text); font-variant-numeric: tabular-nums; outline: none; }
  .money input { padding-left: 28px; }
  .field input:focus, .field select:focus { border-color: var(--blue); box-shadow: 0 0 0 3px rgba(59,130,246,0.2); }
  .quick { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
  .quick button { background: transparent; border: 1px solid var(--border2); color: var(--muted); border-radius: 8px; padding: 4px 8px; font-size: 11.5px; font-weight: 800; cursor: pointer; }
  .toggle { display: flex; gap: 6px; background: var(--panel2); border: 1px solid var(--border); border-radius: 12px; padding: 3px; }
  .toggle button { flex: 1; border: none; background: transparent; color: var(--muted); border-radius: 9px; padding: 9px 8px;
                   font-size: 14.5px; font-weight: 800; cursor: pointer; }
  .toggle button.long.on { background: var(--up); color: #fff; }
  .toggle button.short.on { background: var(--down); color: #fff; }
  .toggle button.lev.on { background: var(--text); color: var(--bg); }
  .results { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin-top: 14px; }
  .res { border-radius: 12px; padding: 12px 14px; background: var(--panel2); border: 1px solid var(--border); position: relative; overflow: hidden; }
  .res::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--border2); }
  .res:has(.v.up)::before { background: var(--up); } .res:has(.v.down)::before { background: var(--down); }
  .res .l { font-size: 10.5px; color: var(--muted); font-weight: 800; text-transform: uppercase; letter-spacing: .05em; }
  .res .v { font-size: 24px; font-weight: 900; margin-top: 5px; font-variant-numeric: tabular-nums; }
  .res .s { font-size: 11.5px; color: var(--muted); margin-top: 5px; line-height: 1.4; }
  .res.main { grid-column: 1 / -1; background: linear-gradient(135deg, rgba(59,130,246,0.16), rgba(59,130,246,0.04)); border-color: rgba(59,130,246,0.45); }
  .res.main .v { font-size: 34px; }
  .up { color: var(--up); } .down { color: var(--down); }
  .note { font-size: 12.5px; color: var(--muted); line-height: 1.55; margin: 12px 0 0; }
  .note b { color: var(--text); }

  .warn { display: flex; gap: 10px; align-items: flex-start; background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.3);
          color: #fcd34d; border-radius: 12px; padding: 11px 12px; font-size: 12.5px; line-height: 1.5; }
  details { margin-top: 10px; }
  summary { cursor: pointer; font-weight: 800; font-size: 13px; color: var(--text); list-style: none; padding: 6px 0; }
  summary::-webkit-details-marker { display: none; }
  summary::before { content: "›"; display: inline-block; margin-right: 8px; transition: transform .15s; color: var(--muted); }
  details[open] summary::before { transform: rotate(90deg); }
  @media (max-width: 640px) { .res.main .v { font-size: 30px; } .px .p { font-size: 16px; } }
</style>
</head>
<body>
<div class="topbar"><div class="topbar-in">
  <a class="back" href="/" title="Dashboard">‹</a>
  <div class="ttl">
    <h1>Prediction <span class="tag">EXPERIMENTAL</span></h1>
    <div class="sub" id="sub">Loading…</div>
  </div>
  <div class="px" id="px"></div>
</div></div>

<div class="wrap">
  <div class="card" id="chartCard">
    <div class="bar">
      <select id="pair">
        <option value="btc_jpy">BTC / JPY</option><option value="eth_jpy">ETH / JPY</option><option value="xrp_jpy">XRP / JPY</option>
        <option value="sol_jpy">SOL / JPY</option><option value="doge_jpy">DOGE / JPY</option>
      </select>
      <span class="seg" id="tfs"><span class="lbl">Candles</span>
        <button data-v="5min">5m</button><button data-v="15min">15m</button><button data-v="1hour">1h</button><button data-v="4hour">4h</button>
      </span>
      <span class="seg" id="aheads"><span class="lbl">Predict</span>
        <button data-v="1h">1 hour</button><button data-v="4h">4 hours</button><button data-v="1d">1 day</button>
      </span>
      <label class="chip"><input type="checkbox" id="showPast" checked> Cone</label>
      <span class="grow"></span>
      <button class="fsbtn" id="fsBtn">⛶ Full screen</button>
    </div>
    <div id="chartBox"><svg id="chart" role="img" aria-label="Price chart with predicted candles"></svg></div>
    <div class="hint">Top: real price · Bottom: the model's candles (each past one predicted a candle ahead, then the future) · drag, pinch, double-tap to reset, tap for prices</div>
  </div>

  <div class="card">
    <h2>Forecast <span class="muted" id="fcLabel"></span></h2>
    <div class="tiles" id="kpis"></div>
  </div>

  <div class="card" id="calcCard">
    <h2>Profit / loss calculator</h2>
    <div class="calc">
      <div class="field"><label>Amount</label>
        <div class="money"><span>¥</span><input id="amt" type="number" inputmode="numeric" min="0" step="1000" value="10000"></div>
        <div class="quick"><button data-q="5000">5k</button><button data-q="10000">10k</button><button data-q="20000">20k</button><button data-q="50000">50k</button></div>
      </div>
      <div class="field"><label>Direction</label><div class="toggle">
        <button class="long" data-d="long">▲ Long</button><button class="short" data-d="short">▼ Short</button></div></div>
      <div class="field"><label>Leverage</label><div class="toggle">
        <button class="lev" data-l="1">1×</button><button class="lev" data-l="2">2×</button></div></div>
      <div class="field"><label>Hold for</label><select id="calcAhead">
        <option value="1h">1 hour</option><option value="4h">4 hours</option><option value="1d">1 day</option></select></div>
    </div>
    <div class="results" id="calcOut"></div>
    <p class="note" id="calcNote"></p>
  </div>

  <div class="card">
    <div class="warn"><span>⚠</span><div>This is a test page. The prediction is <b>not</b> used by the bot and places no orders.
      Short-term crypto moves are close to random: read the accuracy figures before trusting a predicted candle or a calculator result.</div></div>
    <details><summary>How the model works</summary><p class="note" id="how" style="margin-top:4px"></p></details>
  </div>
</div>

<script>
const LS = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
const SV = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
const S = { pair: LS('predPair', 'btc_jpy'), tf: LS('predTf2', '15min'), ahead: LS('predAhead', '1h'),
            dir: LS('calcDir', 'long'), lev: +LS('calcLev', '1'), data: null, status: null, calc: {},
            right: null, count: null, follow: true };
const OPTS = { '5min': ['1h', '4h'], '15min': ['1h', '4h', '1d'], '1hour': ['1h', '4h', '1d'], '4hour': ['4h', '1d'] };
const $ = (id) => document.getElementById(id);
const C = { bg: '#131722', grid: 'rgba(255,255,255,0.06)', axis: '#8b93a7', text: '#d1d4dc', up: '#26a69a', down: '#ef5350',
            upF: 'rgba(38,166,154,0.38)', downF: 'rgba(239,83,80,0.38)', ema20: '#f59e0b', ema50: '#22c55e', rsi: '#c084fc',
            pred: '#60a5fa', cone: 'rgba(96,165,250,0.10)', hit: '#26a69a', miss: '#f59e0b', entry: '#818cf8', stop: '#ef4444' };
const TF = { '5min': '5m', '15min': '15m', '1hour': '1h', '4hour': '4h' };
const AH = { '1h': '1 hour', '4h': '4 hours', '1d': '1 day' };
const MS = { '5min': 3e5, '15min': 9e5, '1hour': 36e5, '4hour': 144e5 }, AMS = { '1h': 36e5, '4h': 144e5, '1d': 864e5 };
const fmt = (v) => v == null || isNaN(v) ? '–' : (v >= 1000 ? Math.round(v).toLocaleString('en-US') : v >= 10 ? v.toFixed(2) : v.toFixed(3));
const yen = (v) => (v >= 0 ? '+' : '−') + '¥' + Math.abs(Math.round(v)).toLocaleString('en-US');
const pct = (v) => (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
const jst = (t, day) => new Date(t).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', ...(day ? { month: 'numeric', day: 'numeric' } : {}), hour: '2-digit', minute: '2-digit' });

function ema(v, p) { const o = [], k = 2 / (p + 1); let pr = null, s = 0;
  v.forEach((x, i) => { if (i < p) { s += x; pr = s / (i + 1); o.push(i === p - 1 ? pr : null); } else { pr = x * k + pr * (1 - k); o.push(pr); } }); return o; }
function rsi(v, p) { const o = [null]; let ag = 0, al = 0;
  for (let i = 1; i < v.length; i++) { const ch = v[i] - v[i - 1], g = Math.max(ch, 0), l = Math.max(-ch, 0);
    if (i <= p) { ag += g / p; al += l / p; o.push(i === p ? (al === 0 ? 100 : 100 - 100 / (1 + ag / al)) : null); }
    else { ag = (ag * (p - 1) + g) / p; al = (al * (p - 1) + l) / p; o.push(al === 0 ? 100 : 100 - 100 / (1 + ag / al)); } } return o; }

// ---------------------------------------------------------------- controls
function syncButtons() {
  if (!OPTS[S.tf].includes(S.ahead)) S.ahead = OPTS[S.tf][0];
  document.querySelectorAll('#tfs button').forEach(b => b.classList.toggle('on', b.dataset.v === S.tf));
  document.querySelectorAll('#aheads button').forEach(b => { b.classList.toggle('on', b.dataset.v === S.ahead); b.disabled = !OPTS[S.tf].includes(b.dataset.v); });
  document.querySelectorAll('.toggle [data-d]').forEach(b => b.classList.toggle('on', b.dataset.d === S.dir));
  document.querySelectorAll('.toggle [data-l]').forEach(b => b.classList.toggle('on', +b.dataset.l === S.lev));
  $('calcAhead').value = S.ahead;
}
$('pair').value = S.pair;
$('pair').onchange = () => { S.pair = $('pair').value; SV('predPair', S.pair); resetView(); load(); };
document.querySelectorAll('#tfs button').forEach(b => b.onclick = () => { S.tf = b.dataset.v; SV('predTf2', S.tf); syncButtons(); resetView(); load(); });
document.querySelectorAll('#aheads button').forEach(b => b.onclick = () => { if (b.disabled) return; S.ahead = b.dataset.v; SV('predAhead', S.ahead); syncButtons(); resetView(); load(); });
document.querySelectorAll('.toggle [data-d]').forEach(b => b.onclick = () => { S.dir = b.dataset.d; SV('calcDir', S.dir); syncButtons(); calc(); });
document.querySelectorAll('.toggle [data-l]').forEach(b => b.onclick = () => { S.lev = +b.dataset.l; SV('calcLev', S.lev); syncButtons(); calc(); });
$('amt').value = LS('calcAmt', '10000');
$('amt').oninput = () => { SV('calcAmt', $('amt').value); calc(); };
document.querySelectorAll('.quick [data-q]').forEach(b => b.onclick = () => { $('amt').value = b.dataset.q; SV('calcAmt', b.dataset.q); calc(); });
$('calcAhead').onchange = () => { const a = $('calcAhead').value; if (!OPTS[S.tf].includes(a)) S.tf = a === '1d' ? '1hour' : '15min';
  S.ahead = a; SV('predAhead', a); SV('predTf2', S.tf); syncButtons(); resetView(); load(); };
$('showPast').onchange = () => draw();
syncButtons();

// ---------------------------------------------------------------- full screen
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const rotated = () => $('chartCard').classList.contains('rot');
function setFs(on) {
  const card = $('chartCard');
  card.classList.toggle('fs', on); document.body.classList.toggle('noscroll', on);
  $('fsBtn').textContent = on ? '✕ Exit' : '⛶ Full screen';
  if (on && !isIOS && card.requestFullscreen && !document.fullscreenElement)
    card.requestFullscreen().then(() => { try { screen.orientation.lock('landscape').catch(() => {}); } catch (e) {} }).catch(() => {});
  if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  layout();
}
function layout() {
  const card = $('chartCard'), box = $('chartBox'), fs = card.classList.contains('fs');
  card.classList.toggle('rot', fs && !document.fullscreenElement && window.innerHeight > window.innerWidth);
  if (fs) { const cs = getComputedStyle(card);
    box.style.height = Math.max(200, card.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom) - card.querySelector('.bar').offsetHeight - 8) + 'px'; }
  else box.style.height = Math.round(window.innerWidth < 700 ? Math.max(560, window.innerHeight * 0.8) : Math.min(860, Math.max(640, window.innerHeight * 0.82))) + 'px';
  draw();
}
$('fsBtn').onclick = () => setFs(!$('chartCard').classList.contains('fs'));
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && $('chartCard').classList.contains('fs')) setFs(false); });
document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && $('chartCard').classList.contains('fs') && !isIOS) setFs(false); else layout(); });
window.addEventListener('resize', () => setTimeout(layout, 60));
window.addEventListener('orientationchange', () => setTimeout(layout, 250));

// ---------------------------------------------------------------- data
async function load() {
  const key = `${S.pair}|${S.tf}|${S.ahead}`;
  try {
    const [r, st] = await Promise.all([fetch(`/api/forecast?pair=${S.pair}&tf=${S.tf}&ahead=${S.ahead}`), fetch('/api/status')]);
    if (r.status === 401 || st.status === 401) { location.href = '/login'; return; }
    const d = await r.json(); S.status = await st.json();
    if (key !== `${S.pair}|${S.tf}|${S.ahead}`) return;      // the user switched while this was loading
    S.data = d; draw(); kpis(); calc();
  } catch (e) { $('sub').textContent = 'Could not load: ' + e; }
}

// ---------------------------------------------------------------- view (zoom / pan)
function items() {           // actual candles, then the predicted ones, as one row of slots
  const d = S.data; if (!d || d.error) return [];
  const step = d.step_ms, a = d.candles, t0 = a[0].t;
  return { t0, step, n: Math.round((Math.max(a[a.length - 1].t, d.forecast.length ? d.forecast[d.forecast.length - 1].t : 0) - t0) / step) + 1 };
}
function resetView() { S.right = null; S.count = null; S.follow = true; }
function ensureView(W) {
  const it = items(); if (!it.n) return it;
  const def = Math.min(it.n + 2, W < 500 ? 48 : W < 900 ? 80 : 130);
  if (S.count == null) S.count = def;
  if (S.right == null || S.follow) S.right = it.n + 1.5;
  S.count = Math.max(12, Math.min(S.count, it.n + 30));
  S.right = Math.max(S.count * 0.25, Math.min(S.right, it.n + S.count * 0.6));
  return it;
}

let geo = null;      // drawing geometry, for pointer handling
function draw() {
  const d = S.data, svg = $('chart');
  const W = Math.max(300, svg.clientWidth), H = Math.max(300, svg.clientHeight);
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  if (!d || d.error) { svg.innerHTML = `<rect width="${W}" height="${H}" fill="${C.bg}"/><text x="20" y="40" fill="${C.axis}" font-size="13">${d ? d.error : 'Loading…'}</text>`; return; }
  const it = ensureView(W), step = it.step, t0 = it.t0;
  const mobile = W < 640, fs = mobile ? 9.5 : 10.5;
  const all = d.candles, closes = all.map(c => c.c), e20 = ema(closes, 20), e50 = ema(closes, 50);
  const idx = (t) => Math.round((t - t0) / step);
  const lo = S.right - S.count, hi = S.right;
  const vis = (i) => i >= Math.floor(lo) - 1 && i <= Math.ceil(hi) + 1;
  const act = all.map((c, i) => ({ c, i: idx(c.t), e20: e20[i], e50: e50[i] })).filter(o => vis(o.i));
  const fut = d.forecast.map(c => ({ c, i: idx(c.t) })).filter(o => vis(o.i));
  const past = d.past.map(c => ({ c, i: idx(c.t) })).filter(o => vis(o.i));
  const pos = (S.status && S.status.open_positions || []).find(p => p.pair === S.pair) || null;
  const showCone = $('showPast').checked;

  // two panels on one time axis: real price on top, the model's candles below
  const padL = 4, padR = mobile ? 70 : 84, padT = mobile ? 40 : 34, padB = 22, gap = 30;
  const plotW = W - padL - padR, sp = plotW / S.count, cw = Math.max(1.5, Math.min(14, sp * 0.68));
  const avail = H - padT - padB - gap, topH = Math.round(avail * 0.56), botH = avail - topH;
  const topY = padT, botY = padT + topH + gap, volH = topH * 0.14;
  const x = (i) => padL + (i - lo + 0.5) * sp;
  geo = { padL, padR, padT, padB, W, H, sp, lo, t0, step };

  const range = (vals) => { let a = Infinity, b = -Infinity; vals.forEach(v => { if (v > 0) { a = Math.min(a, v); b = Math.max(b, v); } });
    if (a === Infinity) { a = d.anchor_close * 0.99; b = d.anchor_close * 1.01; }
    const s = Math.max(b - a, b * 0.0005); return [a - s * 0.07, b + s * 0.07]; };
  const entry = pos ? Number(pos.avg_price || 0) : 0, stop = pos ? Number(pos.stop_trigger_price || 0) : 0;
  const topVals = [];
  act.forEach(o => topVals.push(o.c.l, o.c.h));
  if (showCone) fut.forEach(o => topVals.push(o.c.band_lo, o.c.band_hi));
  const [pl0, ph0] = range(topVals); let pl = pl0, ph = ph0;
  [entry, stop].forEach(v => { if (v > 0 && v > pl * 0.97 && v < ph * 1.03) { pl = Math.min(pl, v); ph = Math.max(ph, v); } });
  const botVals = []; past.forEach(o => botVals.push(o.c.l, o.c.h)); fut.forEach(o => botVals.push(o.c.l, o.c.h));
  const [ql, qh] = range(botVals);
  const y = (v) => topY + (1 - (v - pl) / (ph - pl)) * topH, yb = (v) => botY + (1 - (v - ql) / (qh - ql)) * botH;

  let g = `<rect width="${W}" height="${H}" fill="${C.bg}"/><defs><clipPath id="cpT"><rect x="${padL}" y="${topY}" width="${plotW}" height="${topH}"/></clipPath>` +
          `<clipPath id="cpB"><rect x="${padL}" y="${botY}" width="${plotW}" height="${botH}"/></clipPath></defs>`;
  g += `<rect x="${padL}" y="${botY}" width="${plotW}" height="${botH}" fill="rgba(96,165,250,0.035)"/>`;
  const yGrid = (yf, a, b, y0, h) => { for (let k = 0; k <= 4; k++) { const v = a + (b - a) * k / 4, yy = yf(v);
    g += `<line x1="${padL}" x2="${W - padR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${C.grid}"/><text x="${W - padR + 6}" y="${(yy + 3.5).toFixed(1)}" fill="${C.axis}" font-size="${fs}">${fmt(v)}</text>`; } };
  yGrid(y, pl, ph); yGrid(yb, ql, qh);
  const every = Math.max(1, Math.ceil(80 / sp));
  for (let i = Math.ceil(lo / every) * every; i <= hi; i += every) { const xx = x(i);
    g += `<line x1="${xx.toFixed(1)}" x2="${xx.toFixed(1)}" y1="${topY}" y2="${botY + botH}" stroke="${C.grid}"/>` +
         `<text x="${xx.toFixed(1)}" y="${H - 7}" fill="${C.axis}" font-size="${fs}" text-anchor="middle">${jst(t0 + i * step, step >= 36e5 * 4 || (t0 + i * step) % 864e5 === 0)}</text>`; }
  const ai = idx(d.anchor_t), nowX = x(ai + 1) + sp / 2;
  [[topY, topH], [botY, botH]].forEach(([y0, h]) => {
    g += `<rect x="${nowX.toFixed(1)}" y="${y0}" width="${Math.max(0, W - padR - nowX).toFixed(1)}" height="${h}" fill="rgba(96,165,250,0.06)"/>`; });
  g += `<line x1="${nowX.toFixed(1)}" x2="${nowX.toFixed(1)}" y1="${topY}" y2="${botY + botH}" stroke="${C.pred}" stroke-dasharray="4 4" opacity="0.7"/>`;

  const candle = (c, xx, yf, style) => { const upc = c.c >= c.o, col = upc ? C.up : C.down, yo = yf(c.o), yc = yf(c.c);
    const top = Math.min(yo, yc), h = Math.max(1.2, Math.abs(yc - yo)), dash = style === 'future' ? ' stroke-dasharray="3 2"' : '';
    const fill = style === 'future' ? (upc ? C.upF : C.downF) : col;
    return `<line x1="${xx.toFixed(1)}" x2="${xx.toFixed(1)}" y1="${yf(c.h).toFixed(1)}" y2="${yf(c.l).toFixed(1)}" stroke="${col}"/>` +
           `<rect x="${(xx - cw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${cw.toFixed(1)}" height="${h.toFixed(1)}" fill="${fill}"${style === 'future' ? ` stroke="${col}" stroke-width="1.1"${dash}` : ''}/>`; };

  // top panel: real candles, volume, EMAs, the 80% cone, position lines
  let top = '';
  const maxV = Math.max(1e-9, ...act.map(o => o.c.v));
  act.forEach(o => { const xx = x(o.i), col = o.c.c >= o.c.o ? C.up : C.down, vh = o.c.v / maxV * volH;
    top += `<rect x="${(xx - cw / 2).toFixed(1)}" y="${(topY + topH - vh).toFixed(1)}" width="${cw.toFixed(1)}" height="${vh.toFixed(1)}" fill="${col}" opacity="0.22"/>` + candle(o.c, xx, y, 'real'); });
  const line = (arr, key, yf) => { let p = '', pen = false; arr.forEach(o => { const v = o[key]; if (v == null) { pen = false; return; } p += (pen ? 'L' : 'M') + x(o.i).toFixed(1) + ' ' + yf(v).toFixed(1) + ' '; pen = true; }); return p; };
  top += `<path d="${line(act, 'e50', y)}" fill="none" stroke="${C.ema50}" stroke-width="1.3"/><path d="${line(act, 'e20', y)}" fill="none" stroke="${C.ema20}" stroke-width="1.3"/>`;
  if (showCone && d.forecast.length) {
    const startY = y(d.forecast[0].o);
    const pts = [[x(ai + 1), startY]].concat(d.forecast.map(c => [x(idx(c.t)), y(c.band_hi)])).concat(d.forecast.slice().reverse().map(c => [x(idx(c.t)), y(c.band_lo)]));
    top += `<polygon points="${pts.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ')}" fill="${C.cone}" stroke="rgba(96,165,250,0.45)" stroke-dasharray="3 3"/>`;
  }
  const tags = [], last = all[all.length - 1];
  const level = (v, col, dash, label) => { if (!(v > 0) || v < pl || v > ph) return;
    top += `<line x1="${padL}" x2="${W - padR}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="${col}" stroke-width="1.2" ${dash ? `stroke-dasharray="${dash}"` : ''}/>`;
    if (label) top += `<text x="${padL + 6}" y="${(y(v) - 5).toFixed(1)}" fill="${col}" font-size="${fs}" font-weight="800">${label}</text>`;
    tags.push({ y: y(v), col, text: fmt(v) }); };
  level(last.c, last.c >= last.o ? C.up : C.down, '2 3');
  if (pos) { level(entry, C.entry, '', `${pos.position_side.toUpperCase()} ${pos.open_amount} @ ${fmt(entry)}`); level(stop, C.stop, '5 4', 'STOP'); }
  g += `<g clip-path="url(#cpT)">${top}</g>`;

  // bottom panel: the model's candles (each past candle predicted one candle ahead, then the future)
  let bot = '';
  past.forEach(o => bot += candle(o.c, x(o.i), yb, 'real'));
  fut.forEach(o => bot += candle(o.c, x(o.i), yb, 'future'));
  past.forEach(o => bot += `<circle cx="${x(o.i).toFixed(1)}" cy="${(botY + botH - 5).toFixed(1)}" r="${Math.max(1.4, Math.min(2.6, sp * 0.18)).toFixed(1)}" fill="${o.c.hit ? C.hit : C.miss}"/>`);
  g += `<g clip-path="url(#cpB)">${bot}</g>`;
  const lastF = d.forecast[d.forecast.length - 1];
  const btags = lastF ? [{ y: yb(lastF.c), col: '#2563eb', text: fmt(lastF.c) }] : [];

  // panel titles and axis tags
  g += `<text x="${padL + 6}" y="${topY + 13}" fill="${C.text}" font-size="${fs}" font-weight="800" opacity="0.85">REAL PRICE</text>`;
  g += `<text x="${padL + 6}" y="${botY - 8}" fill="${C.pred}" font-size="${fs}" font-weight="800">MODEL CANDLES <tspan fill="${C.axis}" font-weight="600">· own scale ${pct(qh / ql - 1)} tall · next ${AH[d.ahead]} after the line</tspan></text>`;
  const drawTags = (arr) => { arr.sort((a, b) => a.y - b.y); for (let k = 1; k < arr.length; k++) if (arr[k].y - arr[k - 1].y < 17) arr[k].y = arr[k - 1].y + 17;
    arr.forEach(t => g += `<rect x="${W - padR + 1}" y="${(t.y - 8.5).toFixed(1)}" width="${padR - 3}" height="17" rx="3" fill="${t.col}"/><text x="${W - padR + 6}" y="${(t.y + 3.6).toFixed(1)}" fill="#fff" font-size="${fs}" font-weight="700">${t.text}</text>`); };
  drawTags(tags); drawTags(btags);
  g += `<line id="xh" x1="0" x2="0" y1="${topY}" y2="${botY + botH}" stroke="rgba(255,255,255,0.3)" stroke-dasharray="3 3" visibility="hidden"/>`;
  g += `<text id="ro1" x="${padL + 6}" y="${mobile ? 14 : 18}" fill="${C.text}" font-size="${mobile ? 10.5 : 12}" font-weight="600"></text>`;
  g += `<text id="ro2" x="${padL + 6}" y="${mobile ? 29 : 18}" fill="${C.axis}" font-size="${mobile ? 10 : 11.5}" ${mobile ? '' : `text-anchor="end" transform="translate(${W - padR - padL - 12},0)"`}></text>`;
  svg.innerHTML = g;
  readout(S.sel);
}

function readout(i) {
  const d = S.data, ro1 = $('ro1'), ro2 = $('ro2'), xh = $('xh'); if (!d || d.error || !ro1) return;
  const step = d.step_ms, t0 = d.candles[0].t, lastF = d.forecast[d.forecast.length - 1], now = d.candles[d.candles.length - 1].c;
  const ohlc = (c) => { const col = c.c >= c.o ? C.up : C.down;
    return `O <tspan fill="${col}">${fmt(c.o)}</tspan> H <tspan fill="${col}">${fmt(c.h)}</tspan> L <tspan fill="${col}">${fmt(c.l)}</tspan> C <tspan fill="${col}">${fmt(c.c)}</tspan>`; };
  if (i == null || !geo) {
    ro1.innerHTML = `${S.pair.replace('_jpy', '').toUpperCase()}/JPY ${TF[d.tf]} · <tspan fill="${C.ema20}">EMA20</tspan> <tspan fill="${C.ema50}">EMA50</tspan> · tap a candle to compare`;
    ro2.innerHTML = lastF ? `<tspan fill="${C.pred}">now ${fmt(now)} → in ${AH[d.ahead]} ${fmt(lastF.c)} (${pct(lastF.c / now - 1)})</tspan>` : '';
    xh.setAttribute('visibility', 'hidden'); return; }
  const t = t0 + i * step, xx = geo.padL + (i - geo.lo + 0.5) * geo.sp;
  xh.setAttribute('x1', xx); xh.setAttribute('x2', xx); xh.setAttribute('visibility', 'visible');
  const a = d.candles.find(c => c.t === t), f = d.forecast.find(c => c.t === t), p = d.past.find(c => c.t === t);
  ro1.innerHTML = `${jst(t, true)} · real ` + (a ? ohlc(a) : '<tspan fill="#8b93a7">not yet</tspan>');
  ro2.innerHTML = f ? `<tspan fill="${C.pred}">model</tspan> ${ohlc(f)} <tspan fill="${C.pred}">· 80% ${fmt(f.band_lo)}–${fmt(f.band_hi)}</tspan>`
    : p ? `<tspan fill="${C.pred}">model</tspan> ${ohlc(p)} <tspan fill="${p.hit ? C.hit : C.miss}">· ${p.hit ? 'right' : 'wrong'} direction</tspan>` : '';
}

// pointer: drag to pan, pinch / wheel to zoom, tap for prices, double-tap to reset
(function gestures() {
  const box = $('chartBox'), ptrs = new Map();
  let start = null, moved = false, lastTap = 0, raf = 0;
  const local = (e) => { const r = box.getBoundingClientRect();     // position along the chart's own x axis
    return rotated() ? { x: e.clientY - r.top, y: r.right - e.clientX } : { x: e.clientX - r.left, y: e.clientY - r.top }; };
  const redraw = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); }); };
  const slotAt = (px) => geo ? Math.floor(geo.lo + (px - geo.padL) / geo.sp) : null;
  const zoomAt = (px, f) => { if (!geo) return; const at = geo.lo + (px - geo.padL) / geo.sp;
    const cnt = Math.max(12, Math.min(S.count * f, items().n + 30)); S.right = at + (S.right - at) * cnt / S.count; S.count = cnt;
    S.follow = false; redraw(); };
  box.addEventListener('pointerdown', (e) => { box.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, local(e));
    if (ptrs.size === 1) { start = { p: local(e), right: S.right }; moved = false; }
    if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; start = { dist: Math.hypot(a.x - b.x, a.y - b.y), count: S.count, mid: (a.x + b.x) / 2, right: S.right }; moved = true; } });
  box.addEventListener('pointermove', (e) => { const p = local(e);
    if (!ptrs.has(e.pointerId)) { if (e.pointerType === 'mouse') { S.sel = slotAt(p.x); readout(S.sel); } return; }
    ptrs.set(e.pointerId, p);
    if (ptrs.size === 1 && start && start.p && geo) { const dx = p.x - start.p.x;
      if (Math.abs(dx) > 4) { moved = true; box.classList.add('drag'); }
      if (moved) { S.right = start.right - dx / geo.sp; S.follow = false; redraw(); } }
    else if (ptrs.size === 2 && start && start.dist && geo) { const [a, b] = [...ptrs.values()];
      const f = start.dist / Math.max(10, Math.hypot(a.x - b.x, a.y - b.y));
      const at = geo.lo + (start.mid - geo.padL) / geo.sp, cnt = Math.max(12, Math.min(start.count * f, items().n + 30));
      S.right = at + (start.right - at) * cnt / S.count; S.count = cnt; S.follow = false; redraw(); } });
  const end = (e) => { const p = ptrs.get(e.pointerId); ptrs.delete(e.pointerId); box.classList.remove('drag');
    if (!ptrs.size && !moved && p) { const now = Date.now();
      if (now - lastTap < 300) { resetView(); S.sel = null; draw(); } else { S.sel = slotAt(p.x); readout(S.sel); }
      lastTap = now; }
    if (ptrs.size === 1) { const q = [...ptrs.values()][0]; start = { p: q, right: S.right }; } };
  box.addEventListener('pointerup', end); box.addEventListener('pointercancel', end);
  box.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse' && !ptrs.size) { S.sel = null; readout(null); } });
  box.addEventListener('wheel', (e) => { e.preventDefault(); const p = local(e);
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) { S.right += e.deltaX / (geo ? geo.sp : 10); S.follow = false; redraw(); }
    else zoomAt(p.x, Math.exp(e.deltaY * 0.0015)); }, { passive: false });
  box.addEventListener('dblclick', () => { resetView(); S.sel = null; draw(); });
})();

// ---------------------------------------------------------------- calculator
const FEE = 0.0012, INTEREST_DAY = 0.0004;
function calc() {
  const d = S.data, out = $('calcOut'), note = $('calcNote');
  if (!d || d.error || !d.forecast.length) { out.innerHTML = ''; note.textContent = d && d.error ? d.error : ''; return; }
  const amt = Math.max(0, +$('amt').value || 0), lev = S.lev, notional = amt * lev, long = S.dir === 'long';
  const entry = d.candles[d.candles.length - 1].c, f = d.forecast[d.forecast.length - 1];
  const days = Math.max(1, Math.ceil(AMS[d.ahead] / 864e5));
  const cost = notional * FEE * 2 + notional * INTEREST_DAY * days;
  const pnl = (exitPx) => notional * (long ? exitPx / entry - 1 : 1 - exitPx / entry) - cost;
  const exp = pnl(f.c), good = pnl(long ? f.band_hi : f.band_lo), bad = pnl(long ? f.band_lo : f.band_hi);
  const m = d.metrics, hit = m.hit != null ? m.hit : null;
  const r = (cls, label, v, s) => `<div class="res ${cls}"><div class="l">${label}</div><div class="v ${v >= 0 ? 'up' : 'down'}">${yen(v)}</div><div class="s">${s}</div></div>`;
  out.innerHTML =
    r('main', `Predicted result in ${AH[d.ahead]}`, exp, `${long ? 'Long' : 'Short'} ¥${Math.round(notional).toLocaleString('en-US')} (${lev}×) at ${fmt(entry)} → predicted ${fmt(f.c)} (${pct(f.c / entry - 1)})`) +
    r('', 'Good case (1 in 10 does better)', good, `price ${fmt(long ? f.band_hi : f.band_lo)} · ${pct((long ? f.band_hi : f.band_lo) / entry - 1)}`) +
    r('', 'Bad case (1 in 10 does worse)', bad, `price ${fmt(long ? f.band_lo : f.band_hi)} · ${pct((long ? f.band_lo : f.band_hi) / entry - 1)}`) +
    `<div class="res"><div class="l">Fees and interest</div><div class="v down">−¥${Math.round(cost).toLocaleString('en-US')}</div><div class="s">0.12% to open and 0.12% to close (market orders), margin interest 0.04% a day; already taken off above</div></div>`;
  note.innerHTML = `How sure is this? On test data the model's direction for ${AH[d.ahead]} ahead was right <b>${hit != null ? (hit * 100).toFixed(1) + '%' : '–'}</b> of the time; ` +
    `always guessing the more common direction was right ${m.majority != null ? (m.majority * 100).toFixed(1) + '%' : '–'}. ` +
    `So treat the predicted result as roughly a coin flip, and the good and bad cases as the realistic spread: 8 in 10 outcomes landed between them.`;
}

function kpis() {
  const d = S.data; if (!d || d.error) { $('kpis').innerHTML = ''; $('sub').textContent = d ? d.error : ''; return; }
  const m = d.metrics, last = d.forecast[d.forecast.length - 1], now = d.candles[d.candles.length - 1].c, ch = last.c / now - 1;
  $('sub').textContent = `${S.pair.replace('_jpy', '').toUpperCase()}/JPY · ${TF[d.tf]} · next ${AH[d.ahead]} (${d.forecast.length} candles) · bot ${S.status ? S.status.state.replace('_', ' ').toLowerCase() : ''}`;
  const first = d.candles.find(c => c.t >= d.candles[d.candles.length - 1].t - 864e5) || d.candles[0], chg = now / first.o - 1;
  $('px').innerHTML = `<div class="p">¥${fmt(now)}</div><div class="c ${chg >= 0 ? 'up' : 'down'}">${pct(chg)} 24h</div>`;
  $('fcLabel').textContent = `${TF[d.tf]} candles · next ${AH[d.ahead]} · updates every 30 s`;
  const k = (l, v, s, cls) => `<div class="kpi"><div class="l">${l}</div><div class="v ${cls || ''}">${v}</div><div class="s">${s}</div></div>`;
  $('kpis').innerHTML =
    k(`Predicted in ${AH[d.ahead]}`, fmt(last.c), `${pct(ch)} from now (${fmt(now)})`, ch >= 0 ? 'up' : 'down') +
    k('80% range', `${fmt(last.band_lo)} – ${fmt(last.band_hi)}`, `On test data the price ended inside this range ${m.coverage != null ? (m.coverage * 100).toFixed(0) : 80}% of the time`) +
    k(`Direction right (test, ${AH[d.ahead]})`, m.hit != null ? `${(m.hit * 100).toFixed(1)}%` : '–',
      `${m.test_samples.toLocaleString()} predictions since ${m.test_from} it never saw. Always guessing the more common direction: ${m.majority != null ? (m.majority * 100).toFixed(1) + '%' : '–'}.`) +
    k('Past predictions on the chart', d.recent_hit_rate == null ? '–' : `${(d.recent_hit_rate * 100).toFixed(0)}%`, `Direction right on the ${d.past.length} candles the lower chart predicted one candle ahead (dots: teal right, amber wrong)`);
  $('how').innerHTML = `How it works: a ridge regression trained on ${m.train_samples.toLocaleString()} past ${TF[d.tf]} candles of all five coins reads 12 patterns of the candles so far ` +
    `(returns over 1–32 candles, distance from the 20- and 50-candle averages, volatility, RSI, where the candle closed in its range, volume) and predicts the close of each coming candle. ` +
    `Wicks use the typical wick size for the current volatility. The shaded cone is where the price ended 80% of the time on test data.`;
}

layout();
load();
setInterval(load, 30000);
</script>
</body>
</html>
"""
