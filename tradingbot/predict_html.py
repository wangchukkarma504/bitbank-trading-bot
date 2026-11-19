"""The dashboard's Prediction page (/predict): live candles with predicted candles on top, and a profit calculator."""

PREDICT_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Prediction · Bitbank Bot</title>
<link rel="manifest" href="/manifest.webmanifest">
<style>
  :root {
    --bg-grad: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 45%, #ede9fe 100%);
    --card: rgba(255,255,255,0.84); --text: #0f172a; --muted: #475569; --line: rgba(15,23,42,0.08);
    --up: #16a34a; --down: #dc2626; --amber: #d97706; --chart-bg: #131722; --blue: #2563eb;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: var(--bg-grad); color: var(--text); min-height: 100vh; }
  body.noscroll { overflow: hidden; }
  .wrap { max-width: 1500px; margin: 0 auto; padding: 12px 12px 40px; }
  .top { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  h1 { font-size: 21px; margin: 0; }
  h2 { font-size: 17px; margin: 0 0 10px; }
  .sub { color: var(--muted); font-size: 12.5px; margin-top: 3px; }
  a.btn { border: 1px solid rgba(15,23,42,0.12); background: rgba(255,255,255,0.9); color: var(--text);
          border-radius: 10px; padding: 8px 14px; font-weight: 700; font-size: 13.5px; text-decoration: none; }
  .card { background: var(--card); border: 1px solid rgba(255,255,255,0.7); border-radius: 18px; padding: 14px;
          box-shadow: 0 10px 30px rgba(15,23,42,0.07); margin-top: 12px; }

  #chartCard { padding: 10px; }
  .bar { display: flex; flex-wrap: wrap; gap: 6px 8px; align-items: center; margin-bottom: 8px; }
  .bar select, .bar button, .seg button { border: 1px solid rgba(15,23,42,0.16); background: rgba(255,255,255,0.95); color: var(--text);
          border-radius: 9px; padding: 6px 10px; font-weight: 700; font-size: 12.5px; cursor: pointer; }
  .seg { display: inline-flex; gap: 4px; align-items: center; }
  .seg .lbl { font-size: 11.5px; font-weight: 800; color: var(--muted); text-transform: uppercase; margin-right: 2px; }
  .seg button.on { background: var(--blue); color: #fff; border-color: var(--blue); }
  .seg button:disabled { opacity: 0.35; cursor: default; }
  .bar .grow { flex: 1; }
  .bar .fsbtn { background: #0f172a; color: #fff; border-color: #0f172a; }
  .bar label { font-size: 12.5px; font-weight: 700; color: var(--muted); display: inline-flex; gap: 5px; align-items: center; }
  .hint { font-size: 11.5px; color: var(--muted); margin: 6px 2px 0; }
  #chartBox { position: relative; width: 100%; height: 600px; background: var(--chart-bg); border-radius: 12px; overflow: hidden;
              touch-action: none; user-select: none; -webkit-user-select: none; cursor: grab; }
  #chartBox.drag { cursor: grabbing; }
  #chart { width: 100%; height: 100%; display: block; }

  #chartCard.fs { position: fixed; z-index: 1000; margin: 0; border-radius: 0; background: var(--chart-bg); border: none;
                  top: 0; left: 0; width: 100vw; height: 100vh; height: 100dvh; padding: 6px 8px;
                  padding-left: max(8px, env(safe-area-inset-left)); padding-right: max(8px, env(safe-area-inset-right)); }
  #chartCard.fs.rot { width: 100vh; width: 100dvh; height: 100vw; transform: rotate(90deg) translateY(-100%); transform-origin: top left; }
  #chartCard.fs .bar select, #chartCard.fs .seg button:not(.on), #chartCard.fs .bar button:not(.fsbtn) { background: #1e2433; color: #d1d4dc; border-color: #2a3142; }
  #chartCard.fs .bar label, #chartCard.fs .seg .lbl, #chartCard.fs .hint { color: #8b93a7; }
  #chartCard.fs .hint { display: none; }

  /* calculator */
  .calc { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; align-items: end; }
  .field label { display: block; font-size: 12px; font-weight: 800; color: var(--muted); text-transform: uppercase; margin-bottom: 5px; }
  .field input, .field select { width: 100%; border: 1px solid rgba(15,23,42,0.16); border-radius: 10px; padding: 10px 12px;
                                font-size: 17px; font-weight: 800; background: #fff; color: var(--text); }
  .toggle { display: flex; gap: 6px; }
  .toggle button { flex: 1; border: 1px solid rgba(15,23,42,0.16); border-radius: 10px; padding: 10px; font-size: 15px; font-weight: 800;
                   background: #fff; cursor: pointer; color: var(--text); }
  .toggle button.long.on { background: var(--up); color: #fff; border-color: var(--up); }
  .toggle button.short.on { background: var(--down); color: #fff; border-color: var(--down); }
  .toggle button.lev.on { background: #0f172a; color: #fff; border-color: #0f172a; }
  .results { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-top: 12px; }
  .res { border-radius: 14px; padding: 12px 14px; border: 1px solid var(--line); background: rgba(255,255,255,0.8); }
  .res .l { font-size: 12px; color: var(--muted); font-weight: 800; text-transform: uppercase; }
  .res .v { font-size: 26px; font-weight: 900; margin-top: 4px; }
  .res .s { font-size: 12.5px; color: var(--muted); margin-top: 4px; line-height: 1.4; }
  .res.main { border: 2px solid var(--blue); }

  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
  .kpi { background: rgba(255,255,255,0.75); border-radius: 14px; padding: 12px 14px; border: 1px solid var(--line); }
  .kpi .l { font-size: 12px; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: .03em; }
  .kpi .v { font-size: 22px; font-weight: 800; margin-top: 4px; }
  .kpi .s { font-size: 12.5px; color: var(--muted); margin-top: 4px; line-height: 1.4; }
  .up { color: var(--up); } .down { color: var(--down); }
  .note { font-size: 13px; color: var(--muted); line-height: 1.5; margin: 10px 0 0; }
  .warn { background: rgba(217,119,6,0.1); border: 1px solid rgba(217,119,6,0.3); color: #92400e; border-radius: 12px;
          padding: 10px 12px; font-size: 13px; line-height: 1.45; }
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div>
      <h1>Price prediction <span style="font-size:12px;color:var(--amber);font-weight:800;">EXPERIMENTAL</span></h1>
      <div class="sub" id="sub">Loading…</div>
    </div>
    <a class="btn" href="/">← Dashboard</a>
  </div>

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
      <label><input type="checkbox" id="showPast"> past</label>
      <span class="grow"></span>
      <button class="fsbtn" id="fsBtn">⛶ Full screen</button>
    </div>
    <div id="chartBox"><svg id="chart" role="img" aria-label="Price chart with predicted candles"></svg></div>
    <div class="hint">Drag to move · pinch or scroll to zoom · double-tap to reset · tap a candle for its prices</div>
  </div>

  <div class="card" id="calcCard">
    <h2>Profit / loss calculator</h2>
    <div class="calc">
      <div class="field"><label>Amount (JPY)</label><input id="amt" type="number" inputmode="numeric" min="0" step="1000" value="10000"></div>
      <div class="field"><label>Direction</label><div class="toggle">
        <button class="long" data-d="long">Long ▲</button><button class="short" data-d="short">Short ▼</button></div></div>
      <div class="field"><label>Leverage</label><div class="toggle">
        <button class="lev" data-l="1">1×</button><button class="lev" data-l="2">2×</button></div></div>
      <div class="field"><label>Hold for</label><select id="calcAhead">
        <option value="1h">1 hour</option><option value="4h">4 hours</option><option value="1d">1 day</option></select></div>
    </div>
    <div class="results" id="calcOut"></div>
    <p class="note" id="calcNote"></p>
  </div>

  <div class="card">
    <div class="grid" id="kpis"></div>
  </div>

  <div class="card">
    <div class="warn">This is a test page. The prediction is <b>not</b> used by the bot and places no orders.
      Short-term crypto moves are close to random: read the accuracy figures before trusting a predicted candle or a calculator result.</div>
    <p class="note" id="how"></p>
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
  if (fs) box.style.height = (card.clientHeight - card.querySelector('.bar').offsetHeight - 20) + 'px';
  else box.style.height = Math.round(window.innerWidth < 700 ? Math.max(430, window.innerHeight * 0.62) : Math.min(680, Math.max(520, window.innerHeight * 0.68))) + 'px';
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
  const W = Math.max(300, svg.clientWidth), H = Math.max(240, svg.clientHeight);
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  if (!d || d.error) { svg.innerHTML = `<rect width="${W}" height="${H}" fill="${C.bg}"/><text x="20" y="40" fill="${C.axis}" font-size="13">${d ? d.error : 'Loading…'}</text>`; return; }
  const it = ensureView(W), step = it.step, t0 = it.t0;
  const mobile = W < 640, fs = mobile ? 9.5 : 10.5;
  const all = d.candles, closes = all.map(c => c.c), e20 = ema(closes, 20), e50 = ema(closes, 50), rs = rsi(closes, 14);
  const idx = (t) => Math.round((t - t0) / step);
  const lo = S.right - S.count, hi = S.right;
  const vis = (i) => i >= Math.floor(lo) - 1 && i <= Math.ceil(hi) + 1;
  const act = all.map((c, i) => ({ c, i: idx(c.t), e20: e20[i], e50: e50[i], r: rs[i] })).filter(o => vis(o.i));
  const fut = d.forecast.map(c => ({ c, i: idx(c.t) })).filter(o => vis(o.i));
  const past = $('showPast').checked ? d.past.map(c => ({ c, i: idx(c.t) })).filter(o => vis(o.i)) : [];
  const pos = (S.status && S.status.open_positions || []).find(p => p.pair === S.pair) || null;

  const padL = 4, padR = mobile ? 70 : 84, padT = mobile ? 40 : 34, padB = 22;
  const rsiH = H < 380 ? 0 : (mobile ? 54 : 68), gap = rsiH ? 10 : 0;
  const priceH = H - padT - padB - rsiH - gap, volH = priceH * 0.14, rsiTop = padT + priceH + gap;
  const plotW = W - padL - padR, sp = plotW / S.count, cw = Math.max(1.5, Math.min(14, sp * 0.68));
  const x = (i) => padL + (i - lo + 0.5) * sp;
  geo = { padL, padR, padT, padB, W, H, sp, lo, t0, step };

  let pl = Infinity, ph = -Infinity;
  const take = (v) => { if (v > 0) { pl = Math.min(pl, v); ph = Math.max(ph, v); } };
  act.forEach(o => { take(o.c.l); take(o.c.h); });
  fut.forEach(o => { take(o.c.l); take(o.c.h); take(o.c.band_lo); take(o.c.band_hi); });
  past.forEach(o => { take(o.c.l); take(o.c.h); });
  if (pl === Infinity) { pl = d.anchor_close * 0.99; ph = d.anchor_close * 1.01; }
  const entry = pos ? Number(pos.avg_price || 0) : 0, stop = pos ? Number(pos.stop_trigger_price || 0) : 0;
  [entry, stop].forEach(v => { if (v > 0 && v > pl * 0.97 && v < ph * 1.03) take(v); });
  const span = Math.max(1e-9, ph - pl); pl -= span * 0.06; ph += span * 0.06;
  const y = (v) => padT + (1 - (v - pl) / (ph - pl)) * priceH, yR = (v) => rsiTop + (1 - v / 100) * rsiH;

  let g = `<rect width="${W}" height="${H}" fill="${C.bg}"/><defs><clipPath id="cp"><rect x="${padL}" y="0" width="${plotW}" height="${H}"/></clipPath></defs>`;
  for (let k = 0; k <= 5; k++) { const v = pl + (ph - pl) * k / 5, yy = y(v);
    g += `<line x1="${padL}" x2="${W - padR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${C.grid}"/><text x="${W - padR + 6}" y="${(yy + 3.5).toFixed(1)}" fill="${C.axis}" font-size="${fs}">${fmt(v)}</text>`; }
  let body = '';
  // time grid: about one label per 80 px, on round slot numbers
  const every = Math.max(1, Math.ceil(80 / sp));
  for (let i = Math.ceil(lo / every) * every; i <= hi; i += every) { const xx = x(i);
    body += `<line x1="${xx.toFixed(1)}" x2="${xx.toFixed(1)}" y1="${padT}" y2="${padT + priceH}" stroke="${C.grid}"/>`;
    g += `<text x="${xx.toFixed(1)}" y="${H - 7}" fill="${C.axis}" font-size="${fs}" text-anchor="middle">${jst(t0 + i * step, step >= 36e5 * 4 || (t0 + i * step) % 864e5 === 0)}</text>`; }
  // the future: shaded area and the 80% cone
  const ai = idx(d.anchor_t), nowX = x(ai + 1) + sp / 2;
  body += `<rect x="${nowX.toFixed(1)}" y="${padT}" width="${Math.max(0, W - padR - nowX).toFixed(1)}" height="${priceH}" fill="rgba(96,165,250,0.05)"/>`;
  const cone = [[x(ai + 1), y(d.forecast.length ? d.forecast[0].o : d.anchor_close)]].concat(d.forecast.map(c => [x(idx(c.t)), y(c.band_hi)]))
    .concat(d.forecast.slice().reverse().map(c => [x(idx(c.t)), y(c.band_lo)]));
  body += `<polygon points="${cone.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ')}" fill="${C.cone}" stroke="rgba(96,165,250,0.4)" stroke-dasharray="3 3"/>`;
  body += `<line x1="${nowX.toFixed(1)}" x2="${nowX.toFixed(1)}" y1="${padT}" y2="${padT + priceH}" stroke="${C.pred}" stroke-dasharray="4 4" opacity="0.8"/>`;
  if (nowX < W - padR - 40) body += `<text x="${(nowX + 5).toFixed(1)}" y="${padT + 13}" fill="${C.pred}" font-size="${fs}" font-weight="800">PREDICTION ▸</text>`;
  const maxV = Math.max(1e-9, ...act.map(o => o.c.v));
  const candle = (c, xx, faded) => { const upc = c.c >= c.o, col = upc ? C.up : C.down, yo = y(c.o), yc = y(c.c);
    const top = Math.min(yo, yc), h = Math.max(1, Math.abs(yc - yo));
    return `<line x1="${xx.toFixed(1)}" x2="${xx.toFixed(1)}" y1="${y(c.h).toFixed(1)}" y2="${y(c.l).toFixed(1)}" stroke="${col}" ${faded ? 'opacity="0.6"' : ''}/>` +
           `<rect x="${(xx - cw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${cw.toFixed(1)}" height="${h.toFixed(1)}" fill="${faded ? (upc ? C.upF : C.downF) : col}" ${faded ? `stroke="${col}" stroke-width="1"` : ''}/>`; };
  act.forEach(o => { const xx = x(o.i), col = o.c.c >= o.c.o ? C.up : C.down, vh = o.c.v / maxV * volH;
    body += `<rect x="${(xx - cw / 2).toFixed(1)}" y="${(padT + priceH - vh).toFixed(1)}" width="${cw.toFixed(1)}" height="${vh.toFixed(1)}" fill="${col}" opacity="0.22"/>` + candle(o.c, xx, false); });
  const line = (arr, key, yf) => { let p = '', pen = false; arr.forEach(o => { const v = o[key]; if (v == null) { pen = false; return; } p += (pen ? 'L' : 'M') + x(o.i).toFixed(1) + ' ' + yf(v).toFixed(1) + ' '; pen = true; }); return p; };
  body += `<path d="${line(act, 'e50', y)}" fill="none" stroke="${C.ema50}" stroke-width="1.3"/><path d="${line(act, 'e20', y)}" fill="none" stroke="${C.ema20}" stroke-width="1.3"/>`;
  past.forEach(o => { const xx = x(o.i), col = o.c.hit ? C.hit : C.miss;
    body += `<rect x="${(xx - cw / 2 - 2).toFixed(1)}" y="${Math.min(y(o.c.o), y(o.c.c)).toFixed(1)}" width="${(cw + 4).toFixed(1)}" height="${Math.max(1.5, Math.abs(y(o.c.c) - y(o.c.o))).toFixed(1)}" fill="none" stroke="${col}" stroke-dasharray="2 2"/>`; });
  fut.forEach(o => body += candle(o.c, x(o.i), true));
  // levels
  const tags = [], last = all[all.length - 1], lastF = d.forecast[d.forecast.length - 1];
  const level = (v, col, dash, label) => { if (!(v > 0) || v < pl || v > ph) return;
    body += `<line x1="${padL}" x2="${W - padR}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="${col}" stroke-width="1.2" ${dash ? `stroke-dasharray="${dash}"` : ''}/>`;
    if (label) body += `<text x="${padL + 6}" y="${(y(v) - 5).toFixed(1)}" fill="${col}" font-size="${fs}" font-weight="800">${label}</text>`;
    tags.push({ y: y(v), col, text: fmt(v) }); };
  level(last.c, last.c >= last.o ? C.up : C.down, '2 3');
  if (pos) { level(entry, C.entry, '', `${pos.position_side.toUpperCase()} ${pos.open_amount} @ ${fmt(entry)}`); level(stop, C.stop, '5 4', 'STOP'); }
  if (lastF && lastF.c >= pl && lastF.c <= ph) tags.push({ y: y(lastF.c), col: '#2563eb', text: fmt(lastF.c) });
  g += `<g clip-path="url(#cp)">${body}</g>`;
  tags.sort((a, b) => a.y - b.y);
  for (let k = 1; k < tags.length; k++) if (tags[k].y - tags[k - 1].y < 17) tags[k].y = tags[k - 1].y + 17;
  tags.forEach(t => g += `<rect x="${W - padR + 1}" y="${(t.y - 8.5).toFixed(1)}" width="${padR - 3}" height="17" rx="3" fill="${t.col}"/><text x="${W - padR + 6}" y="${(t.y + 3.6).toFixed(1)}" fill="#fff" font-size="${fs}" font-weight="700">${t.text}</text>`);
  if (rsiH) {
    g += `<g clip-path="url(#cp)"><rect x="${padL}" y="${rsiTop}" width="${plotW}" height="${rsiH}" fill="rgba(255,255,255,0.02)"/><path d="${line(act, 'r', yR)}" fill="none" stroke="${C.rsi}" stroke-width="1.2"/></g>`;
    [30, 70].forEach(v => g += `<line x1="${padL}" x2="${W - padR}" y1="${yR(v).toFixed(1)}" y2="${yR(v).toFixed(1)}" stroke="${C.grid}" stroke-dasharray="3 3"/><text x="${W - padR + 6}" y="${(yR(v) + 3.5).toFixed(1)}" fill="${C.axis}" font-size="${fs}">${v}</text>`);
    g += `<text x="${padL + 6}" y="${rsiTop + 11}" fill="${C.rsi}" font-size="${fs}" font-weight="700">RSI 14</text>`;
  }
  g += `<line id="xh" x1="0" x2="0" y1="${padT}" y2="${H - padB}" stroke="rgba(255,255,255,0.3)" stroke-dasharray="3 3" visibility="hidden"/>`;
  g += `<text id="ro1" x="${padL + 6}" y="${mobile ? 14 : 18}" fill="${C.text}" font-size="${mobile ? 10.5 : 12}" font-weight="600"></text>`;
  g += `<text id="ro2" x="${padL + 6}" y="${mobile ? 29 : 18}" fill="${C.axis}" font-size="${mobile ? 10 : 11.5}" ${mobile ? '' : `text-anchor="end" transform="translate(${W - padR - padL - 12},0)"`}></text>`;
  svg.innerHTML = g;
  readout(S.sel);
}

function readout(i) {
  const d = S.data, ro1 = $('ro1'), ro2 = $('ro2'), xh = $('xh'); if (!d || d.error || !ro1) return;
  const step = d.step_ms, t0 = d.candles[0].t, lastF = d.forecast[d.forecast.length - 1];
  const name = `${S.pair.replace('_jpy', '').toUpperCase()}/JPY ${TF[d.tf]}`;
  if (i == null || !geo) {
    ro1.innerHTML = `${name} · <tspan fill="${C.ema20}">EMA20</tspan> <tspan fill="${C.ema50}">EMA50</tspan> · <tspan fill="${C.pred}">next ${AH[d.ahead]}: ${d.forecast.length} candles</tspan>`;
    ro2.textContent = lastF ? `now ${fmt(d.candles[d.candles.length - 1].c)} → ${fmt(lastF.c)} (${pct(lastF.c / d.candles[d.candles.length - 1].c - 1)})` : '';
    xh.setAttribute('visibility', 'hidden'); return; }
  const t = t0 + i * step, xx = geo.padL + (i - geo.lo + 0.5) * geo.sp;
  xh.setAttribute('x1', xx); xh.setAttribute('x2', xx); xh.setAttribute('visibility', 'visible');
  const a = d.candles.find(c => c.t === t), f = d.forecast.find(c => c.t === t), p = d.past.find(c => c.t === t);
  const c = a || f, col = c && c.c >= c.o ? C.up : C.down;
  ro1.innerHTML = `${jst(t, true)} ${f && !a ? '<tspan fill="' + C.pred + '">predicted</tspan> ' : ''}` + (c ? `O <tspan fill="${col}">${fmt(c.o)}</tspan> H <tspan fill="${col}">${fmt(c.h)}</tspan> L <tspan fill="${col}">${fmt(c.l)}</tspan> C <tspan fill="${col}">${fmt(c.c)}</tspan>` : '');
  ro2.innerHTML = f ? `<tspan fill="${C.pred}">80% range ${fmt(f.band_lo)} – ${fmt(f.band_hi)}</tspan>` : p ? `<tspan fill="${p.hit ? C.hit : C.miss}">predicted beforehand ${fmt(p.c)} · ${p.hit ? 'right' : 'wrong'} direction</tspan>` : '';
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
  $('sub').textContent = `${S.pair.replace('_jpy', '').toUpperCase()} · ${TF[d.tf]} candles · next ${AH[d.ahead]} = ${d.forecast.length} candles · model trained ${d.trained || '?'} · bot ${S.status ? S.status.state : ''} · updates every 30 s`;
  const k = (l, v, s, cls) => `<div class="kpi"><div class="l">${l}</div><div class="v ${cls || ''}">${v}</div><div class="s">${s}</div></div>`;
  $('kpis').innerHTML =
    k(`Predicted in ${AH[d.ahead]}`, fmt(last.c), `${pct(ch)} from now (${fmt(now)})`, ch >= 0 ? 'up' : 'down') +
    k('80% range', `${fmt(last.band_lo)} – ${fmt(last.band_hi)}`, `On test data the price ended inside this range ${m.coverage != null ? (m.coverage * 100).toFixed(0) : 80}% of the time`) +
    k(`Direction right (test, ${AH[d.ahead]})`, m.hit != null ? `${(m.hit * 100).toFixed(1)}%` : '–',
      `${m.test_samples.toLocaleString()} predictions since ${m.test_from} it never saw. Always guessing the more common direction: ${m.majority != null ? (m.majority * 100).toFixed(1) + '%' : '–'}.`) +
    k('Last 40 candles', d.recent_hit_rate == null ? '–' : `${(d.recent_hit_rate * 100).toFixed(0)}%`, 'One-candle-ahead direction right (tick "past" to see them on the chart: teal right, amber wrong)');
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
