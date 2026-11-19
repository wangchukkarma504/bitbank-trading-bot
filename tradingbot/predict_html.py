"""The dashboard's Prediction page (/predict): live candles with the forecast model's predicted candles on top."""

PREDICT_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prediction · Bitbank Bot</title>
<link rel="manifest" href="/manifest.webmanifest">
<style>
  :root {
    --bg-grad: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 45%, #ede9fe 100%);
    --card: rgba(255,255,255,0.82); --text: #0f172a; --muted: #475569; --line: rgba(15,23,42,0.08);
    --up: #16a34a; --down: #dc2626; --pred: #2563eb; --pred-fill: rgba(37,99,235,0.18); --band: rgba(37,99,235,0.08);
    --amber: #d97706;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: var(--bg-grad); color: var(--text); min-height: 100vh; }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 18px 16px 40px; }
  .top { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  h1 { font-size: 22px; margin: 0; }
  .sub { color: var(--muted); font-size: 13px; margin-top: 4px; }
  a.btn, button.seg { border: 1px solid rgba(15,23,42,0.12); background: rgba(255,255,255,0.9); color: var(--text);
         border-radius: 10px; padding: 8px 14px; font-weight: 700; font-size: 13.5px; cursor: pointer; text-decoration: none; }
  .card { background: var(--card); border: 1px solid rgba(255,255,255,0.7); border-radius: 18px; padding: 16px;
          box-shadow: 0 10px 30px rgba(15,23,42,0.07); margin-top: 14px; }
  .controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  .segs { display: inline-flex; background: rgba(15,23,42,0.06); border-radius: 12px; padding: 3px; gap: 3px; flex-wrap: wrap; }
  button.seg { border: none; background: transparent; padding: 7px 12px; }
  button.seg.active { background: #fff; box-shadow: 0 2px 8px rgba(15,23,42,0.12); }
  select { border: 1px solid rgba(15,23,42,0.14); border-radius: 10px; padding: 8px 10px; font-weight: 700; background: #fff; }
  label.chk { font-size: 13px; font-weight: 600; color: var(--muted); display: inline-flex; gap: 6px; align-items: center; }
  #chart { width: 100%; height: 440px; display: block; }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12.5px; color: var(--muted); margin-top: 8px; }
  .sw { display: inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -2px; margin-right: 5px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
  .kpi { background: rgba(255,255,255,0.75); border-radius: 14px; padding: 12px 14px; border: 1px solid var(--line); }
  .kpi .l { font-size: 12px; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: .03em; }
  .kpi .v { font-size: 22px; font-weight: 800; margin-top: 4px; }
  .kpi .s { font-size: 12.5px; color: var(--muted); margin-top: 4px; line-height: 1.4; }
  .up { color: var(--up); } .down { color: var(--down); }
  .note { font-size: 13px; color: var(--muted); line-height: 1.5; }
  .warn { background: rgba(217,119,6,0.1); border: 1px solid rgba(217,119,6,0.3); color: #92400e; border-radius: 12px;
          padding: 10px 12px; font-size: 13px; line-height: 1.45; }
  #tip { position: fixed; pointer-events: none; background: rgba(15,23,42,0.92); color: #fff; font-size: 12px; padding: 8px 10px;
         border-radius: 8px; display: none; z-index: 10; line-height: 1.45; white-space: nowrap; }
  @media (max-width: 640px) { #chart { height: 360px; } h1 { font-size: 19px; } }
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div>
      <h1>Price prediction <span style="font-size:13px;color:var(--amber);font-weight:800;">EXPERIMENTAL</span></h1>
      <div class="sub" id="sub">Loading…</div>
    </div>
    <a class="btn" href="/">← Dashboard</a>
  </div>

  <div class="card">
    <div class="controls">
      <select id="pair">
        <option value="btc_jpy">BTC/JPY</option><option value="eth_jpy">ETH/JPY</option><option value="xrp_jpy">XRP/JPY</option>
        <option value="sol_jpy">SOL/JPY</option><option value="doge_jpy">DOGE/JPY</option>
      </select>
      <div class="segs" id="horizons">
        <button class="seg active" data-h="1h">Next 1 hour</button>
        <button class="seg" data-h="4h">Next 4 hours</button>
        <button class="seg" data-h="1d">Next day</button>
      </div>
      <label class="chk"><input type="checkbox" id="showPast" checked> Show past predictions</label>
    </div>
    <svg id="chart" role="img" aria-label="Price chart with predicted candles"></svg>
    <div class="legend">
      <span><span class="sw" style="background:var(--up)"></span>Actual candles</span>
      <span><span class="sw" style="background:var(--pred-fill);border:1.5px dashed var(--pred)"></span>Predicted candles</span>
      <span><span class="sw" style="background:var(--band)"></span>Range the price stayed in 80% of the time (test)</span>
      <span><span class="sw" style="border:1.5px solid var(--pred);background:transparent"></span>Past one-candle predictions</span>
      <span><span class="sw" style="background:#0f172a"></span>Your open trade: entry / stop</span>
    </div>
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
<div id="tip"></div>

<script>
const S = { pair: localStorage.getItem('predPair') || 'btc_jpy', h: localStorage.getItem('predH') || '1h', data: null, status: null };
const $ = (id) => document.getElementById(id);
const fmt = (v) => v == null ? '–' : (v >= 1000 ? Math.round(v).toLocaleString() : v >= 10 ? v.toFixed(2) : v.toFixed(3));
const pct = (v) => (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
const jst = (t) => new Date(t).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });

$('pair').value = S.pair;
document.querySelectorAll('#horizons .seg').forEach(b => {
  b.classList.toggle('active', b.dataset.h === S.h);
  b.onclick = () => { S.h = b.dataset.h; localStorage.setItem('predH', S.h);
    document.querySelectorAll('#horizons .seg').forEach(x => x.classList.toggle('active', x === b)); load(); };
});
$('pair').onchange = () => { S.pair = $('pair').value; localStorage.setItem('predPair', S.pair); load(); };
$('showPast').onchange = () => draw();

async function load() {
  try {
    const [r, st] = await Promise.all([
      fetch(`/api/forecast?pair=${S.pair}&horizon=${S.h}`), fetch('/api/status')]);
    if (r.status === 401 || st.status === 401) { location.href = '/login'; return; }
    S.data = await r.json(); S.status = await st.json();
    draw(); kpis();
  } catch (e) { $('sub').textContent = 'Could not load: ' + e; }
}

function draw() {
  const d = S.data, svg = $('chart');
  if (!d || d.error) { svg.innerHTML = `<text x="20" y="40" fill="#475569">${d ? d.error : ''}</text>`; return; }
  const W = svg.clientWidth || 900, H = svg.clientHeight || 440, padL = 8, padR = 70, padT = 14, padB = 26;
  const actual = d.candles.slice(-60), fut = d.forecast, past = $('showPast').checked ? d.past : [];
  const t0 = actual[0].t, step = d.step_ms, slots = actual.length + fut.length + 1;
  const cw = (W - padL - padR) / slots, x = (t) => padL + ((t - t0) / step + 0.5) * cw;
  const pos = (S.status && S.status.open_positions || []).filter(p => p.pair === S.pair);
  let lo = Infinity, hi = -Infinity;
  actual.forEach(c => { lo = Math.min(lo, c.l); hi = Math.max(hi, c.h); });
  fut.forEach(c => { lo = Math.min(lo, c.l, c.band_lo); hi = Math.max(hi, c.h, c.band_hi); });
  past.filter(p => p.t >= t0).forEach(p => { lo = Math.min(lo, p.l); hi = Math.max(hi, p.h); });
  pos.forEach(p => { [p.avg_price, p.stop_trigger_price].forEach(v => { if (v && v > lo * 0.97 && v < hi * 1.03) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }); });
  const padP = (hi - lo) * 0.06; lo -= padP; hi += padP;
  const y = (v) => padT + (hi - v) / (hi - lo) * (H - padT - padB);
  let g = '';
  for (let i = 0; i <= 5; i++) { const v = lo + (hi - lo) * i / 5, yy = y(v);
    g += `<line x1="${padL}" x2="${W - padR}" y1="${yy}" y2="${yy}" stroke="rgba(15,23,42,0.07)"/>` +
         `<text x="${W - padR + 6}" y="${yy + 4}" font-size="11" fill="#64748b">${fmt(v)}</text>`; }
  const every = Math.ceil(slots / 7);
  actual.concat(fut).forEach((c, i) => { if (i % every === 0)
    g += `<text x="${x(c.t)}" y="${H - 8}" font-size="11" fill="#64748b" text-anchor="middle">${jst(c.t)}</text>`; });
  // band (cone) from the anchor close through the predicted closes
  const ax = x(d.anchor_t), ay = y(d.anchor_close);
  const top = fut.map(c => `${x(c.t)},${y(c.band_hi)}`), bot = fut.map(c => `${x(c.t)},${y(c.band_lo)}`).reverse();
  g += `<polygon points="${ax},${ay} ${top.join(' ')} ${bot.join(' ')}" fill="var(--band)" stroke="rgba(37,99,235,0.25)" stroke-dasharray="3 3"/>`;
  const nowX = x(d.anchor_t) + cw / 2;
  g += `<line x1="${nowX}" x2="${nowX}" y1="${padT}" y2="${H - padB}" stroke="#94a3b8" stroke-dasharray="4 4"/>` +
       `<text x="${nowX + 4}" y="${padT + 10}" font-size="11" fill="#64748b">prediction →</text>`;
  const bw = Math.max(2, cw * 0.62);
  const candle = (c, cls, i, kind) => {
    const up = c.c >= c.o, col = kind === 'actual' ? (up ? 'var(--up)' : 'var(--down)') : 'var(--pred)';
    const yo = y(c.o), yc = y(c.c), top = Math.min(yo, yc), hgt = Math.max(1, Math.abs(yc - yo)), cx = x(c.t);
    const fill = kind === 'actual' ? col : (kind === 'pred' ? 'var(--pred-fill)' : 'none');
    const dash = kind === 'pred' ? ' stroke-dasharray="3 2"' : '';
    return `<g data-k="${kind}" data-i="${i}"><line x1="${cx}" x2="${cx}" y1="${y(c.h)}" y2="${y(c.l)}" stroke="${col}" stroke-width="${kind === 'past' ? 1 : 1.3}"${dash}/>` +
           `<rect x="${cx - bw / 2}" y="${top}" width="${bw}" height="${hgt}" rx="1.5" fill="${fill}" stroke="${col}" stroke-width="${kind === 'actual' ? 0 : 1.4}"${dash}/>` +
           `<rect x="${cx - cw / 2}" y="${padT}" width="${cw}" height="${H - padT - padB}" fill="transparent"/></g>`;
  };
  actual.forEach((c, i) => g += candle(c, '', i, 'actual'));
  past.forEach((c, i) => { if (c.t >= t0) g += candle(c, '', i, 'past'); });
  fut.forEach((c, i) => g += candle(c, '', i, 'pred'));
  pos.forEach(p => {
    [[p.avg_price, 'entry ' + p.position_side], [p.stop_trigger_price, 'stop']].forEach(([v, lbl]) => {
      if (!v || v < lo || v > hi) return;
      g += `<line x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}" stroke="#0f172a" stroke-width="1.2" stroke-dasharray="${lbl === 'stop' ? '6 4' : '0'}"/>` +
           `<text x="${padL + 4}" y="${y(v) - 4}" font-size="11" font-weight="700" fill="#0f172a">${lbl} ${fmt(v)}</text>`;
    });
  });
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.innerHTML = g;
  svg.querySelectorAll('g[data-k]').forEach(el => {
    el.onmousemove = (e) => {
      const k = el.dataset.k, c = (k === 'actual' ? actual : k === 'pred' ? fut : past)[+el.dataset.i];
      const name = k === 'actual' ? 'Actual' : k === 'pred' ? 'Predicted' : 'Predicted one candle ahead (' + (c.hit ? 'direction right' : 'direction wrong') + ')';
      const band = k === 'pred' ? `<br>80% range ${fmt(c.band_lo)} – ${fmt(c.band_hi)}` : '';
      $('tip').innerHTML = `<b>${name}</b> · ${jst(c.t)}<br>O ${fmt(c.o)} H ${fmt(c.h)} L ${fmt(c.l)} C ${fmt(c.c)}${band}`;
      const tp = $('tip'); tp.style.display = 'block';
      tp.style.left = Math.min(e.clientX + 14, window.innerWidth - tp.offsetWidth - 8) + 'px'; tp.style.top = (e.clientY + 14) + 'px';
    };
    el.onmouseleave = () => $('tip').style.display = 'none';
  });
}

function kpis() {
  const d = S.data; if (!d || d.error) { $('kpis').innerHTML = ''; $('sub').textContent = d ? d.error : ''; return; }
  const m = d.metrics, last = d.forecast[d.forecast.length - 1], ch = last.c / d.anchor_close - 1;
  const label = { '1h': 'in 1 hour', '4h': 'in 4 hours', '1d': 'in 1 day' }[d.horizon];
  const live = S.status ? S.status.state : '';
  $('sub').textContent = `${S.pair.replace('_jpy', '').toUpperCase()} · ${d.tf} candles · model trained ${d.trained || '?'} · bot state ${live} · updates every 30 s`;
  const k = (l, v, s, cls) => `<div class="kpi"><div class="l">${l}</div><div class="v ${cls || ''}">${v}</div><div class="s">${s}</div></div>`;
  $('kpis').innerHTML =
    k(`Predicted ${label}`, fmt(last.c), `${pct(ch)} from the last close ${fmt(d.anchor_close)}`, ch >= 0 ? 'up' : 'down') +
    k('80% range', `${fmt(last.band_lo)} – ${fmt(last.band_hi)}`, `On test data the price ended inside this range ${(m.band_coverage * 100).toFixed(0)}% of the time`) +
    k('Direction right (test)', `${(m.direction_hit_rate * 100).toFixed(1)}%`,
      `${m.test_samples.toLocaleString()} predictions since ${m.test_from} it never saw. Always guessing the more common direction: ${(m.always_up_hit_rate * 100).toFixed(1)}%. Strongest 10% of predictions: ${(m.direction_hit_rate_strongest_10pct * 100).toFixed(1)}%.`) +
    k('Last 40 candles', d.recent_hit_rate == null ? '–' : `${(d.recent_hit_rate * 100).toFixed(0)}%`, 'One-candle-ahead direction right, on the candles shown as outlines');
  $('how').innerHTML = `How it works: a ridge regression trained on ${m.train_samples.toLocaleString()} past ${d.tf} candles of all five coins reads 12 patterns of the candles so far ` +
    `(returns over 1–32 candles, distance from the 20- and 50-candle averages, volatility, RSI, where the candle closed in its range, volume) and predicts the close after each of the next ${d.forecast.length} candles. ` +
    `Wicks use the typical wick size for the current volatility. The shaded cone is where the price ended 80% of the time on test data.`;
}

load();
setInterval(load, 30000);
window.addEventListener('resize', () => draw());
</script>
</body>
</html>
"""
