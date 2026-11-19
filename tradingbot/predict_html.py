"""The dashboard's Prediction page (/predict): live candles with the forecast model's predicted candles on top."""

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
    --card: rgba(255,255,255,0.82); --text: #0f172a; --muted: #475569; --line: rgba(15,23,42,0.08);
    --up: #16a34a; --down: #dc2626; --amber: #d97706;
    --chart-bg: #131722;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: var(--bg-grad); color: var(--text); min-height: 100vh; }
  body.noscroll { overflow: hidden; }
  .wrap { max-width: 1500px; margin: 0 auto; padding: 14px 12px 40px; }
  .top { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  h1 { font-size: 21px; margin: 0; }
  .sub { color: var(--muted); font-size: 12.5px; margin-top: 3px; }
  a.btn { border: 1px solid rgba(15,23,42,0.12); background: rgba(255,255,255,0.9); color: var(--text);
          border-radius: 10px; padding: 8px 14px; font-weight: 700; font-size: 13.5px; text-decoration: none; }
  .card { background: var(--card); border: 1px solid rgba(255,255,255,0.7); border-radius: 18px; padding: 14px;
          box-shadow: 0 10px 30px rgba(15,23,42,0.07); margin-top: 12px; }

  /* chart card */
  #chartCard { padding: 10px; }
  .bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px; }
  .bar select, .bar button { border: 1px solid rgba(15,23,42,0.16); background: rgba(255,255,255,0.95); color: var(--text);
          border-radius: 9px; padding: 6px 10px; font-weight: 700; font-size: 12.5px; cursor: pointer; }
  .bar button.on { background: #2563eb; color: #fff; border-color: #2563eb; }
  .bar .grow { flex: 1; }
  .bar .fsbtn { background: #0f172a; color: #fff; border-color: #0f172a; }
  .bar label { font-size: 12.5px; font-weight: 700; color: var(--muted); display: inline-flex; gap: 5px; align-items: center; }
  #chartBox { position: relative; width: 100%; height: 600px; background: var(--chart-bg); border-radius: 12px; overflow: hidden;
              touch-action: pan-y; }
  #chart { width: 100%; height: 100%; display: block; }

  /* full screen: the chart card covers the whole screen; on a phone held upright it is turned to landscape */
  #chartCard.fs { position: fixed; z-index: 1000; margin: 0; border-radius: 0; background: var(--chart-bg); border: none;
                  top: 0; left: 0; width: 100vw; height: 100vh; height: 100dvh; padding: 6px 8px;
                  padding-left: max(8px, env(safe-area-inset-left)); padding-right: max(8px, env(safe-area-inset-right)); }
  #chartCard.fs.rot { width: 100vh; width: 100dvh; height: 100vw; transform: rotate(90deg) translateY(-100%); transform-origin: top left; }
  #chartCard.fs .bar select, #chartCard.fs .bar button:not(.on):not(.fsbtn) { background: #1e2433; color: #d1d4dc; border-color: #2a3142; }
  #chartCard.fs .bar label { color: #8b93a7; }
  #chartCard.fs #chartBox { border-radius: 6px; }

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
      <span id="horizons">
        <button data-h="5min">5m</button>
        <button data-h="15min">15m</button>
        <button data-h="1hour">1h</button>
        <button data-h="4hour">4h</button>
      </span>
      <label><input type="checkbox" id="showPast"> past predictions</label>
      <span class="grow"></span>
      <button class="fsbtn" id="fsBtn" title="Full screen">⛶ Full screen</button>
    </div>
    <div id="chartBox"><svg id="chart" role="img" aria-label="Price chart with predicted candles"></svg></div>
  </div>

  <div class="card">
    <div class="grid" id="kpis"></div>
  </div>

  <div class="card">
    <div class="warn">This is a test page. The prediction is <b>not</b> used by the bot and places no orders.
      Short-term crypto moves are close to random: read the accuracy figures before trusting a predicted candle.</div>
    <p class="note" id="how"></p>
  </div>
</div>

<script>
const S = { pair: localStorage.getItem('predPair') || 'btc_jpy', h: localStorage.getItem('predTf') || '15min',
            data: null, status: null, hover: null };
const $ = (id) => document.getElementById(id);
const C = { bg: '#131722', grid: 'rgba(255,255,255,0.06)', axis: '#8b93a7', text: '#d1d4dc', up: '#26a69a', down: '#ef5350',
            ema20: '#f59e0b', ema50: '#22c55e', rsi: '#c084fc', pred: '#60a5fa', predFill: 'rgba(96,165,250,0.30)',
            cone: 'rgba(96,165,250,0.10)', hit: '#26a69a', miss: '#f59e0b', entry: '#818cf8', stop: '#ef4444', tp: '#16a34a' };
const fmt = (v) => v == null || isNaN(v) ? '–' : (v >= 1000 ? Math.round(v).toLocaleString('en-US') : v >= 10 ? v.toFixed(2) : v.toFixed(3));
const pct = (v) => (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
const jst = (t, withDay) => new Date(t).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', ...(withDay ? { month: 'numeric', day: 'numeric' } : {}), hour: '2-digit', minute: '2-digit' });
const TF = { '5min': '5m', '15min': '15m', '1hour': '1h', '4hour': '4h' };
const AHEAD = { '5min': 'next 1 hour', '15min': 'next 2 hours', '1hour': 'next 8 hours', '4hour': 'next day' };

function ema(vals, p) { const out = [], k = 2 / (p + 1); let prev = null, s = 0;
  vals.forEach((v, i) => { if (i < p) { s += v; prev = s / (i + 1); out.push(i === p - 1 ? prev : null); } else { prev = v * k + prev * (1 - k); out.push(prev); } });
  return out; }
function rsi(vals, p) { const out = [null]; let ag = 0, al = 0;
  for (let i = 1; i < vals.length; i++) { const ch = vals[i] - vals[i - 1], g = Math.max(ch, 0), l = Math.max(-ch, 0);
    if (i <= p) { ag += g / p; al += l / p; out.push(i === p ? (al === 0 ? 100 : 100 - 100 / (1 + ag / al)) : null); }
    else { ag = (ag * (p - 1) + g) / p; al = (al * (p - 1) + l) / p; out.push(al === 0 ? 100 : 100 - 100 / (1 + ag / al)); } }
  return out; }

// ---------------------------------------------------------------- controls
$('pair').value = S.pair;
document.querySelectorAll('#horizons button').forEach(b => {
  b.classList.toggle('on', b.dataset.h === S.h);
  b.onclick = () => { S.h = b.dataset.h; localStorage.setItem('predTf', S.h);
    document.querySelectorAll('#horizons button').forEach(x => x.classList.toggle('on', x === b)); load(); };
});
$('pair').onchange = () => { S.pair = $('pair').value; localStorage.setItem('predPair', S.pair); load(); };
$('showPast').onchange = () => draw();

// ---------------------------------------------------------------- full screen
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
function setFs(on) {
  const card = $('chartCard');
  card.classList.toggle('fs', on);
  document.body.classList.toggle('noscroll', on);
  $('fsBtn').textContent = on ? '✕ Exit' : '⛶ Full screen';
  if (on && !isIOS && card.requestFullscreen && !document.fullscreenElement) {
    card.requestFullscreen().then(() => { try { screen.orientation.lock('landscape').catch(() => {}); } catch (e) {} }).catch(() => {});
  }
  if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  layout();
}
function layout() {
  const card = $('chartCard'), box = $('chartBox'), fs = card.classList.contains('fs');
  // a phone held upright: turn the full-screen chart sideways so it shows in landscape
  card.classList.toggle('rot', fs && !document.fullscreenElement && window.innerHeight > window.innerWidth);
  if (fs) {
    const barH = card.querySelector('.bar').offsetHeight + 8;
    box.style.height = (card.clientHeight - barH - 12) + 'px';
  } else {
    box.style.height = Math.round(window.innerWidth < 700 ? Math.max(430, window.innerHeight * 0.62) : Math.min(680, Math.max(520, window.innerHeight * 0.68))) + 'px';
  }
  draw();
}
$('fsBtn').onclick = () => setFs(!$('chartCard').classList.contains('fs'));
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && $('chartCard').classList.contains('fs')) setFs(false); });
document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && $('chartCard').classList.contains('fs') && !isIOS) setFs(false); else layout(); });
window.addEventListener('resize', () => setTimeout(layout, 60));
window.addEventListener('orientationchange', () => setTimeout(layout, 250));

// ---------------------------------------------------------------- data
async function load() {
  try {
    const [r, st] = await Promise.all([fetch(`/api/forecast?pair=${S.pair}&tf=${S.h}`), fetch('/api/status')]);
    if (r.status === 401 || st.status === 401) { location.href = '/login'; return; }
    S.data = await r.json(); S.status = await st.json();
    draw(); kpis();
  } catch (e) { $('sub').textContent = 'Could not load: ' + e; }
}

// ---------------------------------------------------------------- chart
function draw() {
  const d = S.data, svg = $('chart');
  const W = Math.max(300, svg.clientWidth), H = Math.max(260, svg.clientHeight);
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  if (!d || d.error) { svg.innerHTML = `<text x="20" y="40" fill="${C.axis}" font-size="13">${d ? d.error : 'Loading…'}</text>`; return; }
  const mobile = W < 640, fs = mobile ? 9.5 : 10.5;
  const all = d.candles, closes = all.map(c => c.c);
  const e20a = ema(closes, 20), e50a = ema(closes, 50), rsia = rsi(closes, 14);
  const view = Math.min(all.length, W < 500 ? 45 : W < 900 ? 70 : 110);
  const off = all.length - view, actual = all.slice(off), e20 = e20a.slice(off), e50 = e50a.slice(off), rs = rsia.slice(off);
  const fut = d.forecast, step = d.step_ms, t0 = actual[0].t;
  const lastT = Math.max(actual[actual.length - 1].t, fut[fut.length - 1].t);
  const slots = Math.round((lastT - t0) / step) + 3;
  const past = $('showPast').checked ? d.past.filter(p => p.t >= t0) : [];
  const pos = (S.status && S.status.open_positions || []).find(p => p.pair === S.pair) || null;

  const padL = 6, padR = mobile ? 70 : 84, padT = mobile ? 40 : 34, padB = 22;
  const rsiH = H < 380 ? 0 : (mobile ? 56 : 70), gap = rsiH ? 10 : 0;
  const priceH = H - padT - padB - rsiH - gap, volH = priceH * 0.15, rsiTop = padT + priceH + gap;
  const sp = (W - padL - padR) / slots, cw = Math.max(2, Math.min(12, sp * 0.68));
  const xi = (t) => padL + ((t - t0) / step + 0.5) * sp;

  let lo = Infinity, hi = -Infinity;
  const take = (v) => { if (v > 0) { lo = Math.min(lo, v); hi = Math.max(hi, v); } };
  actual.forEach(c => { take(c.l); take(c.h); });
  fut.forEach(c => { take(c.l); take(c.h); take(c.band_lo); take(c.band_hi); });
  past.forEach(p => { take(p.l); take(p.h); });
  const entry = pos ? Number(pos.avg_price || 0) : 0, stop = pos ? Number(pos.stop_trigger_price || 0) : 0;
  [entry, stop].forEach(v => { if (v > 0 && v > lo * 0.96 && v < hi * 1.04) take(v); });
  const span = Math.max(1e-9, hi - lo); lo -= span * 0.05; hi += span * 0.05;
  const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * priceH, yR = (v) => rsiTop + (1 - v / 100) * rsiH;

  let g = `<rect x="0" y="0" width="${W}" height="${H}" fill="${C.bg}"/>`;
  for (let i = 0; i <= 5; i++) { const v = lo + (hi - lo) * i / 5, yy = y(v);
    g += `<line x1="${padL}" x2="${W - padR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${C.grid}"/>` +
         `<text x="${W - padR + 6}" y="${(yy + 3.5).toFixed(1)}" fill="${C.axis}" font-size="${fs}">${fmt(v)}</text>`; }
  const every = Math.max(1, Math.ceil(slots / (W < 500 ? 4 : W < 900 ? 6 : 9)));
  for (let k = 0; k < slots; k += every) { const t = t0 + k * step;
    g += `<line x1="${xi(t).toFixed(1)}" x2="${xi(t).toFixed(1)}" y1="${padT}" y2="${padT + priceH}" stroke="${C.grid}"/>` +
         `<text x="${xi(t).toFixed(1)}" y="${H - 7}" fill="${C.axis}" font-size="${fs}" text-anchor="middle">${jst(t, step >= 14400000 || k === 0)}</text>`; }

  // the future side of the chart, shaded, with the 80% cone
  const nowX = xi(d.anchor_t) + sp / 2;
  g += `<rect x="${nowX.toFixed(1)}" y="${padT}" width="${(W - padR - nowX).toFixed(1)}" height="${priceH}" fill="rgba(96,165,250,0.05)"/>`;
  const ax = xi(d.anchor_t), ay = y(d.anchor_close);
  const top = fut.map(c => `${xi(c.t).toFixed(1)},${y(c.band_hi).toFixed(1)}`), bot = fut.map(c => `${xi(c.t).toFixed(1)},${y(c.band_lo).toFixed(1)}`).reverse();
  g += `<polygon points="${ax.toFixed(1)},${ay.toFixed(1)} ${top.join(' ')} ${bot.join(' ')}" fill="${C.cone}" stroke="rgba(96,165,250,0.45)" stroke-dasharray="3 3"/>`;
  g += `<line x1="${nowX.toFixed(1)}" x2="${nowX.toFixed(1)}" y1="${padT}" y2="${padT + priceH}" stroke="${C.pred}" stroke-dasharray="4 4" opacity="0.8"/>` +
       `<text x="${(nowX + 5).toFixed(1)}" y="${padT + 13}" fill="${C.pred}" font-size="${fs}" font-weight="800">PREDICTION ▸</text>`;

  // volume and candles
  const maxV = Math.max(1e-9, ...actual.map(c => c.v));
  actual.forEach(c => { const x = xi(c.t), col = c.c >= c.o ? C.up : C.down, vh = c.v / maxV * volH;
    g += `<rect x="${(x - cw / 2).toFixed(1)}" y="${(padT + priceH - vh).toFixed(1)}" width="${cw.toFixed(1)}" height="${vh.toFixed(1)}" fill="${col}" opacity="0.25"/>` +
         `<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${y(c.h).toFixed(1)}" y2="${y(c.l).toFixed(1)}" stroke="${col}"/>` +
         `<rect x="${(x - cw / 2).toFixed(1)}" y="${Math.min(y(c.o), y(c.c)).toFixed(1)}" width="${cw.toFixed(1)}" height="${Math.max(1, Math.abs(y(c.c) - y(c.o))).toFixed(1)}" fill="${col}"/>`; });
  const path = (arr, yf) => { let p = '', pen = false;
    arr.forEach((v, i) => { if (v == null) { pen = false; return; } p += (pen ? 'L' : 'M') + xi(actual[i].t).toFixed(1) + ' ' + yf(v).toFixed(1) + ' '; pen = true; }); return p; };
  g += `<path d="${path(e50, y)}" fill="none" stroke="${C.ema50}" stroke-width="1.3"/><path d="${path(e20, y)}" fill="none" stroke="${C.ema20}" stroke-width="1.3"/>`;
  // past one-candle-ahead predictions: outline, teal when the direction was right, amber when wrong
  past.forEach(p => { const x = xi(p.t), col = p.hit ? C.hit : C.miss;
    g += `<rect x="${(x - cw / 2 - 1.5).toFixed(1)}" y="${Math.min(y(p.o), y(p.c)).toFixed(1)}" width="${(cw + 3).toFixed(1)}" height="${Math.max(1.5, Math.abs(y(p.c) - y(p.o))).toFixed(1)}" fill="none" stroke="${col}" stroke-width="1.2" stroke-dasharray="2 2" opacity="0.9"/>`; });
  // predicted candles
  fut.forEach(c => { const x = xi(c.t), w = cw + 2;
    g += `<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${y(c.h).toFixed(1)}" y2="${y(c.l).toFixed(1)}" stroke="${C.pred}" stroke-width="1.4"/>` +
         `<rect x="${(x - w / 2).toFixed(1)}" y="${Math.min(y(c.o), y(c.c)).toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(4, Math.abs(y(c.c) - y(c.o))).toFixed(1)}" fill="${C.predFill}" stroke="${C.pred}" stroke-width="1.5" stroke-dasharray="3 2"/>`; });
  const fc = fut.map(c => `${xi(c.t).toFixed(1)},${y(c.c).toFixed(1)}`);
  g += `<polyline points="${ax.toFixed(1)},${ay.toFixed(1)} ${fc.join(' ')}" fill="none" stroke="${C.pred}" stroke-width="1.6"/>`;

  // levels and axis tags
  const tags = [], lastC = actual[actual.length - 1];
  const level = (v, col, dash, label) => { if (!(v > 0) || v < lo || v > hi) return;
    g += `<line x1="${padL}" x2="${W - padR}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="${col}" stroke-width="1.2" ${dash ? `stroke-dasharray="${dash}"` : ''}/>`;
    if (label) g += `<text x="${padL + 6}" y="${(y(v) - 5).toFixed(1)}" fill="${col}" font-size="${fs}" font-weight="800">${label}</text>`;
    tags.push({ y: y(v), col, text: fmt(v) }); };
  level(lastC.c, lastC.c >= lastC.o ? C.up : C.down, '2 3');
  if (pos) { level(entry, C.entry, '', `${pos.position_side.toUpperCase()} ${pos.open_amount} @ ${fmt(entry)}`); level(stop, C.stop, '5 4', 'STOP'); }
  tags.push({ y: y(fut[fut.length - 1].c), col: '#2563eb', text: fmt(fut[fut.length - 1].c) });
  tags.sort((a, b) => a.y - b.y);
  for (let i = 1; i < tags.length; i++) if (tags[i].y - tags[i - 1].y < 17) tags[i].y = tags[i - 1].y + 17;
  tags.forEach(t => { g += `<rect x="${W - padR + 1}" y="${(t.y - 8.5).toFixed(1)}" width="${padR - 3}" height="17" rx="3" fill="${t.col}"/>` +
                           `<text x="${W - padR + 6}" y="${(t.y + 3.6).toFixed(1)}" fill="#fff" font-size="${fs}" font-weight="700">${t.text}</text>`; });

  // RSI pane
  if (rsiH) {
    g += `<rect x="${padL}" y="${rsiTop}" width="${W - padL - padR}" height="${rsiH}" fill="rgba(255,255,255,0.02)"/>`;
    [30, 70].forEach(v => g += `<line x1="${padL}" x2="${W - padR}" y1="${yR(v).toFixed(1)}" y2="${yR(v).toFixed(1)}" stroke="${C.grid}" stroke-dasharray="3 3"/><text x="${W - padR + 6}" y="${(yR(v) + 3.5).toFixed(1)}" fill="${C.axis}" font-size="${fs}">${v}</text>`);
    g += `<path d="${path(rs, yR)}" fill="none" stroke="${C.rsi}" stroke-width="1.2"/><text x="${padL + 4}" y="${rsiTop + 11}" fill="${C.rsi}" font-size="${fs}" font-weight="700">RSI 14</text>`;
  }

  // hover / tap targets for every slot, and the readout at the top
  for (let k = 0; k < slots; k++) { const t = t0 + k * step;
    g += `<rect class="hit" data-t="${t}" x="${(xi(t) - sp / 2).toFixed(1)}" y="${padT}" width="${sp.toFixed(1)}" height="${(H - padT - padB).toFixed(1)}" fill="transparent"/>`; }
  g += `<line id="xh" x1="0" x2="0" y1="${padT}" y2="${H - padB}" stroke="rgba(255,255,255,0.25)" stroke-dasharray="3 3" visibility="hidden"/>`;
  g += `<text id="readout" x="${padL + 6}" y="${mobile ? 14 : 18}" fill="${C.text}" font-size="${mobile ? 10.5 : 12}" font-weight="600"></text>`;
  g += `<text id="readout2" x="${padL + 6}" y="${mobile ? 29 : 18}" fill="${C.axis}" font-size="${mobile ? 10 : 11.5}" ${mobile ? '' : `text-anchor="end" transform="translate(${W - padR - padL - 12},0)"`}></text>`;
  svg.innerHTML = g;

  const byT = {}; actual.forEach(c => byT[c.t] = { a: c }); fut.forEach(c => (byT[c.t] = byT[c.t] || {}).f = c);
  d.past.forEach(p => (byT[p.t] = byT[p.t] || {}).p = p);
  const name = S.pair.replace('_jpy', '').toUpperCase() + '/JPY ' + TF[d.tf];
  const show = (t) => { const e = byT[t] || {}, ro = $('readout'), ro2 = $('readout2'), xh = $('xh');
    if (t == null) { ro.innerHTML = `${name} · <tspan fill="${C.ema20}">EMA20</tspan> <tspan fill="${C.ema50}">EMA50</tspan> · <tspan fill="${C.pred}">predicted ${AHEAD[d.tf]}</tspan>`;
      ro2.textContent = `last ${fmt(lastC.c)} → predicted ${fmt(fut[fut.length - 1].c)} (${pct(fut[fut.length - 1].c / d.anchor_close - 1)})`; xh.setAttribute('visibility', 'hidden'); return; }
    xh.setAttribute('x1', xi(t)); xh.setAttribute('x2', xi(t)); xh.setAttribute('visibility', 'visible');
    const c = e.a, f = e.f, p = e.p;
    ro.innerHTML = `${jst(t, true)}  ` + (c ? `O <tspan fill="${c.c >= c.o ? C.up : C.down}">${fmt(c.o)}</tspan> H <tspan fill="${c.c >= c.o ? C.up : C.down}">${fmt(c.h)}</tspan> L <tspan fill="${c.c >= c.o ? C.up : C.down}">${fmt(c.l)}</tspan> C <tspan fill="${c.c >= c.o ? C.up : C.down}">${fmt(c.c)}</tspan>` : '<tspan fill="#8b93a7">no candle yet</tspan>');
    ro2.innerHTML = f ? `<tspan fill="${C.pred}">predicted C ${fmt(f.c)} · 80% range ${fmt(f.band_lo)} – ${fmt(f.band_hi)}</tspan>`
      : p ? `<tspan fill="${p.hit ? C.hit : C.miss}">predicted beforehand C ${fmt(p.c)} · direction ${p.hit ? 'right' : 'wrong'}</tspan>` : ''; };
  svg.querySelectorAll('.hit').forEach(el => { const t = +el.dataset.t;
    el.addEventListener('pointerenter', () => show(t)); el.addEventListener('pointerdown', () => show(t)); });
  svg.onpointerleave = () => show(null);
  show(null);
}

function kpis() {
  const d = S.data; if (!d || d.error) { $('kpis').innerHTML = ''; $('sub').textContent = d ? d.error : ''; return; }
  const m = d.metrics, last = d.forecast[d.forecast.length - 1], ch = last.c / d.anchor_close - 1;
  const label = AHEAD[d.tf];
  $('sub').textContent = `${S.pair.replace('_jpy', '').toUpperCase()} · ${TF[d.tf]} candles · model trained ${d.trained || '?'} · bot ${S.status ? S.status.state : ''} · updates every 30 s`;
  const k = (l, v, s, cls) => `<div class="kpi"><div class="l">${l}</div><div class="v ${cls || ''}">${v}</div><div class="s">${s}</div></div>`;
  $('kpis').innerHTML =
    k(`Predicted ${label}`, fmt(last.c), `${pct(ch)} from the last close ${fmt(d.anchor_close)}`, ch >= 0 ? 'up' : 'down') +
    k('80% range', `${fmt(last.band_lo)} – ${fmt(last.band_hi)}`, `On test data the price ended inside this range ${(m.band_coverage * 100).toFixed(0)}% of the time`) +
    k('Direction right (test)', `${(m.direction_hit_rate * 100).toFixed(1)}%`,
      `${m.test_samples.toLocaleString()} predictions since ${m.test_from} it never saw. Always guessing the more common direction: ${(m.always_up_hit_rate * 100).toFixed(1)}%.`) +
    k('Last 40 candles', d.recent_hit_rate == null ? '–' : `${(d.recent_hit_rate * 100).toFixed(0)}%`, 'One-candle-ahead direction right (the dashed outlines on the chart: teal right, amber wrong)');
  $('how').innerHTML = `How it works: a ridge regression trained on ${m.train_samples.toLocaleString()} past ${TF[d.tf]} candles of all five coins reads 12 patterns of the candles so far ` +
    `(returns over 1–32 candles, distance from the 20- and 50-candle averages, volatility, RSI, where the candle closed in its range, volume) and predicts the close after each of the next ${d.forecast.length} candles. ` +
    `Wicks use the typical wick size for the current volatility. The shaded cone is where the price ended 80% of the time on test data.`;
}

layout();
load();
setInterval(load, 30000);
</script>
</body>
</html>
"""
