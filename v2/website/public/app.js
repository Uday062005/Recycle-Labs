'use strict';
// ReSort v2 browser UI. Calls /api/proposal (surrogate + optimiser + sizing + cost). No Aspen at request time. All server text is inserted with textContent.
const $ = id => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
let META = null, FX = null;
const NF = (d) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d });
const fmt = (x, d = 1) => (x === null || x === undefined || !Number.isFinite(x)) ? '—' : NF(d).format(x);
const usd = x => { if (x === null || x === undefined) return '—'; const s = '$ ' + fmt(x, 0); return FX ? s + '  (₹ ' + fmt(x * FX, 0) + ')' : s; };
const VIEWS = { overview: 'Overview', calculator: 'Design calculator', insights: 'Simulation insights', method: 'Model & limitations' };
const LABEL = {
  PET_purity_dense: ['PET purity in DENSE', v => fmt(100 * v, 2) + ' %'], PE_PP_purity_light: ['PE+PP purity in LIGHT', v => fmt(100 * v, 2) + ' %'],
  PET_recovery_pct: ['PET recovery (to DENSE)', v => fmt(v, 1) + ' %'], PEPP_recovery_pct: ['PE+PP recovery (to LIGHT)', v => fmt(v, 1) + ' %'],
  PET_loss_to_light_pct: ['PET lost to LIGHT', v => fmt(v, 1) + ' %'], PEPP_loss_to_dense_pct: ['PE+PP lost to DENSE', v => fmt(v, 2) + ' %'],
  yield_pct: ['Flake yield (DENSE + LIGHT)', v => fmt(v, 1) + ' %'], fines_loss_pct: ['Fines loss', v => fmt(v, 1) + ' %'],
  recycle_ratio: ['Recycle ratio (oversize / feed)', v => fmt(v, 2)], d50_coarse_mm: ['Product d50', v => fmt(v, 2) + ' mm'],
  crusher_kWh_per_tonne_feed: ['Crusher energy', v => fmt(v, 1) + ' kWh / t feed']
};
const CONS_LABEL = { d50_min: 'Product d50 ≥', d50_max: 'Product d50 ≤', PET_purity_min: 'PET purity ≥', PE_PP_purity_min: 'PE+PP purity ≥', PET_recovery_min: 'PET recovery ≥', PEPP_recovery_min: 'PE+PP recovery ≥' };

function toast(msg, bad = false) { const t = $('toast'); t.textContent = msg; t.className = 'toast show' + (bad ? ' error' : ''); clearTimeout(toast.timer); toast.timer = setTimeout(() => t.className = 'toast', 5000); }
function go(view) { document.querySelectorAll('.view').forEach(x => x.classList.toggle('visible', x.id === 'view-' + view)); document.querySelectorAll('.nav').forEach(x => x.classList.toggle('active', x.dataset.view === view)); $('page-crumb').textContent = VIEWS[view]; window.scrollTo({ top: 0, behavior: 'smooth' }); }
document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => go(b.dataset.view)));
document.querySelectorAll('[data-go]').forEach(b => b.addEventListener('click', () => go(b.dataset.go)));

function updateCompo() {
  const ids = ['pet', 'hdpe', 'pp'], arr = ids.map(id => Number($(id).value));
  const total = arr.reduce((a, b) => a + b, 0);
  ids.forEach((id, i) => $('bar-' + id).style.width = (Math.max(0, arr[i]) / Math.max(100, total) * 100) + '%');
  const okay = arr.every(n => Number.isFinite(n) && n >= 0 && n <= 100) && Math.abs(total - 100) < 0.01;
  $('composition-status').textContent = okay ? 'Composition totals 100 %. The model uses the PET share (30–60 %).' : `Composition totals ${fmt(total, 2)} %; it must equal 100 %.`;
  $('composition-status').classList.toggle('error', !okay);
  return okay;
}
['pet', 'hdpe', 'pp'].forEach(id => $(id).addEventListener('input', updateCompo)); updateCompo();
$('mode').addEventListener('change', () => { $('manual-box').hidden = $('mode').value !== 'evaluate'; });

const opt = id => { const s = $(id).value.trim(); return s === '' ? null : Number(s); };
function buildRequest() {
  const prices = {}; [['dense_usd_t', 'p-dense'], ['light_usd_t', 'p-light'], ['scrap_usd_t', 'p-scrap'], ['electricity_usd_kwh', 'p-power'], ['wage_usd_h', 'p-wage']].forEach(([k, id]) => { const v = opt(id); if (v !== null) prices[k] = v; });
  const lf = {}; [['capex_factor', 'f-capex'], ['labour_factor', 'f-labour']].forEach(([k, id]) => { const v = opt(id); if (v !== null) lf[k] = v; });
  const req = {
    feed_rate_kg_h: opt('feed'), hours_per_day: opt('hours'), days_per_year: opt('days'), mode: $('mode').value,
    composition: { PET: opt('pet'), HDPE: opt('hdpe'), PP: opt('pp') }, feed_top_size_mm: opt('feed-size'),
    product_d50_min_mm: opt('d50min'), product_d50_max_mm: opt('d50max'), target: $('target').value, min_purity_pct: opt('purity'), min_recovery_pct: opt('recovery'),
    budget_usd: opt('budget'), prices, location_factors: lf, location_text: $('location').value.trim()
  };
  if (req.mode === 'evaluate') req.variables = { crusher_gap_mm: opt('v-gap'), screen1_cut_mm: opt('v-s1'), screen2_cut_mm: opt('v-s2'), residence_time_s: opt('v-tau') };
  return req;
}

function table(headers, rows, cls = 'rtable') {
  const t = el('table', cls), th = el('thead'), trh = el('tr');
  headers.forEach(h => trh.append(el('th', '', h))); th.append(trh); t.append(th);
  const tb = el('tbody'); rows.forEach(r => { const tr = el('tr'); r.forEach((c, i) => { const td = el('td', i ? 'num' : '', ''); if (c instanceof Node) td.append(c); else td.textContent = c; tr.append(td); }); tb.append(tr); }); t.append(tb);
  const w = el('div', 'table-wrap'); w.append(t); return w;
}
function section(title, ...nodes) { const s = el('div', 'res-section'); s.append(el('h3', '', title)); nodes.forEach(n => s.append(n)); return s; }
function gridItems(pairs) { const g = el('div', 'result-grid'); pairs.forEach(([k, v]) => { const d = el('div', 'result-item'); d.append(el('small', '', k), el('strong', '', v)); g.append(d); }); return g; }
function tag(ok, yes, no) { return el('span', 'tag ' + (ok ? 'tag-ok' : 'tag-bad'), ok ? yes : no); }
function list(items, cls = 'warn-list') { const u = el('ul', cls); items.forEach(i => u.append(el('li', '', i))); return u; }

function renderProposal(p) {
  const body = $('proposal-body'); body.replaceChildren();
  $('recommendation-empty').hidden = true; $('recommendation-content').hidden = false;
  if (p.status === 'infeasible') {
    $('recommendation-subtitle').textContent = 'No feasible setting';
    $('selection-method').textContent = 'INFEASIBLE · NO ANSWER INVENTED';
    body.append(el('p', 'result-note', p.message));
    const a = p.achievable_at_this_composition;
    body.append(section('Best values reachable at this composition (inside the simulated ranges)', table(['Quantity', 'Best reachable'], [
      ['PET purity in DENSE', fmt(a.max_PET_purity_pct, 2) + ' %'], ['PE+PP purity in LIGHT', fmt(a.max_PE_PP_purity_pct, 2) + ' %'],
      ['PET recovery', fmt(a.max_PET_recovery_pct, 1) + ' %'], ['PE+PP recovery', fmt(a.max_PEPP_recovery_pct, 1) + ' %'],
      ['Product d50 range', fmt(a.d50_range_mm[0], 1) + ' – ' + fmt(a.d50_range_mm[1], 1) + ' mm']])));
    body.append(el('p', 'help', 'Relax one or more requirements (each is checked separately) and try again. These maxima are not all reachable at the same time.'));
    body.append(section('Limits', list(p.limits)));
    return;
  }
  const v = p.variables, c = p.cost, z = c.sizing;
  $('recommendation-subtitle').textContent = p.mode === 'optimise' ? 'Lowest-energy settings that meet your requirements' : 'Predictions for your own settings';
  $('selection-method').textContent = (p.mode === 'optimise' ? 'OPTIMISED SETTINGS' : 'YOUR SETTINGS') + ' · SURROGATE PREDICTION · NOT A LIVE ASPEN RUN';
  body.append(section('Operating settings', gridItems([['Crusher gap', fmt(v.crusher_gap_mm, 2) + ' mm'], ['Screen 1 cut', fmt(v.screen1_cut_mm, 2) + ' mm'], ['Screen 2 cut', fmt(v.screen2_cut_mm, 2) + ' mm'], ['Tank residence', fmt(v.residence_time_s, 1) + ' s']])));
  if (p.warnings.length) body.append(section('Notes for this case', list(p.warnings)));
  if (Object.keys(p.constraints_met).length) {
    body.append(section('Your requirements', table(['Requirement', 'Required', 'Predicted', ''], Object.entries(p.constraints_met).map(([k, m]) => {
      const pct = k.includes('purity'); const f = x => pct ? fmt(100 * x, 2) + ' %' : (k.includes('d50') ? fmt(x, 2) + ' mm' : fmt(x, 1) + ' %');
      return [CONS_LABEL[k], f(m.required), f(m.predicted), tag(m.ok, 'met', 'not met')];
    }))));
  }
  const rows = Object.entries(LABEL).map(([k, [name, f]]) => { const m = p.predicted[k]; return [name, f(m.value), f(m.low) + ' – ' + f(m.high)]; });
  body.append(section('Predicted performance (± 2 × surrogate cross-validation error)', table(['Output', 'Value', 'Range'], rows)));
  const s = p.spread_sensitivity;
  body.append(section('Assumption sensitivity: tank turbulence spread σ', table(['σ', 'PET purity', 'PE+PP purity', 'PET recovery', 'PE+PP recovery'],
    ['low', 'default', 'high'].map(l => [`${s[l].spread} (${l})`, fmt(100 * s[l].PET_purity_dense, 2) + ' %', fmt(100 * s[l].PE_PP_purity_light, 2) + ' %', fmt(s[l].PET_recovery_pct, 1) + ' %', fmt(s[l].PEPP_recovery_pct, 1) + ' %'])),
    el('p', 'help', 'σ is an assumption (flake-shape spread, turbulence, bubbles). Purity and recovery depend on it; the table shows how much.')));
  const f = c.flows_kg_h, a = p.annual_t;
  body.append(section('Product flows', table(['Stream', 'kg/hr', 'tonnes/year'], [['PET-rich flakes (DENSE)', fmt(f.dense, 1), fmt(a.dense, 0)], ['PE/PP-rich flakes (LIGHT)', fmt(f.light, 1), fmt(a.light, 0)], ['Fines (loss)', fmt(f.fines, 1), fmt(a.fines, 0)], ['Crusher throughput incl. recycle', fmt(f.crusher_throughput, 0), '—']])));
  body.append(section('Equipment sizing', gridItems([
    ['Crusher motor', `${fmt(z.crusher.motor_kW, 1)} kW (calc. ${fmt(z.crusher.calculated_power_kW, 1)} kW, load ${fmt(100 * z.crusher.utilisation, 0)} %)`],
    ['Screen 1', `${fmt(z.screen1.aperture_mm, 1)} mm, ${fmt(z.screen1.area_m2, 2)} m²` + (z.screen1.area_calc_m2 < z.screen1.area_m2 ? ' (minimum size)' : '')],
    ['Screen 2', `${fmt(z.screen2.aperture_mm, 1)} mm, ${fmt(z.screen2.area_m2, 2)} m²` + (z.screen2.area_calc_m2 < z.screen2.area_m2 ? ' (minimum size)' : '')],
    ['Sink-float tank', `${fmt(z.tank.volume_m3, 2)} m³ (calc. ${fmt(z.tank.volume_calc_m3, 3)} m³)`]])));
  const sc = c.scenarios, S = ['optimistic', 'base', 'pessimistic'];
  const pb = x => x === null ? 'no payback' : fmt(x, 1) + ' years';
  body.append(section('Cost and payback (ranges, USD)', table(['', 'Optimistic', 'Base', 'Pessimistic'], [
    ['Installed capex', ...S.map(n => usd(sc[n].capex_usd))], ['Operating cost / year', ...S.map(n => usd(sc[n].opex_usd_per_year.total))],
    ['Scrap purchase / year', ...S.map(n => usd(sc[n].scrap_purchase_usd_per_year))], ['Product revenue / year', ...S.map(n => usd(sc[n].revenue_usd_per_year.total))],
    ['Net cash / year', ...S.map(n => usd(sc[n].net_usd_per_year))], ['Simple payback', ...S.map(n => pb(sc[n].payback_years))]]),
    el('p', 'help', 'Capex ±30 %, opex ±20 %, product prices and scrap cost at low/base/high. Payback is dominated by the price gap between products and scrap.')));
  const bd = c.budget; const bs = el('div', 'result-highlight'); bs.append(el('span', '', 'BUDGET CHECK'), el('strong', '', bd.status)); if (bd.shortfall_base_usd > 0) bs.append(el('span', '', 'Shortfall at the base estimate: ' + usd(bd.shortfall_base_usd)));
  body.append(bs);
  body.append(section('Limits of this proposal', list(p.limits)));
}

async function submit(e) {
  e.preventDefault();
  const fe = $('form-errors'); fe.hidden = true; fe.replaceChildren();
  FX = opt('fx'); if (FX !== null && !(FX > 0)) FX = null;
  if (!updateCompo()) { toast('Polymer composition must total 100 %.', true); }
  const btn = $('go-btn'); btn.disabled = true;
  try {
    const r = await fetch('/api/proposal', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildRequest()) });
    const data = await r.json();
    if (r.status === 422) {
      fe.hidden = false; fe.append(el('strong', '', 'Please check your inputs:'), list(data.errors.map(x => x.message), 'err-list')); toast('Some inputs need attention.', true); return;
    }
    if (!r.ok) throw new Error('Server returned ' + r.status);
    renderProposal(data);
    if (data.status === 'infeasible') toast('No setting meets all requirements.', true);
  } catch (err) { toast('Could not generate the proposal: ' + err.message, true); }
  finally { btn.disabled = false; }
}
$('design-form').addEventListener('submit', submit);

// ------------------------------------------------------------------ plots and database status
const COLORS = { 30: '#d98b3a', 45: '#3a8860', 60: '#3f6fb0' };
function scatter(id, xk, yk, pts, ylabel, xlabel, yscale = 1) {
  const node = $(id); node.replaceChildren();
  const P = pts.map(p => ({ x: p[xk], y: p[yk] * yscale, c: COLORS[p.PET_frac_pct] || '#777' }));
  const W = 620, H = 260, L = 55, R = 15, T = 15, B = 44;
  let xmin = Math.min(...P.map(p => p.x)), xmax = Math.max(...P.map(p => p.x)), ymin = Math.min(...P.map(p => p.y)), ymax = Math.max(...P.map(p => p.y));
  const allPositive = ymin >= 0, pad = (ymax - ymin) * 0.05 || 1; ymin -= pad; ymax += pad; if (allPositive) ymin = Math.max(0, ymin);
  const xp = x => L + (x - xmin) / (xmax - xmin) * (W - L - R), yp = y => H - B - (y - ymin) / (ymax - ymin) * (H - B - T);
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', `${ylabel} vs ${xlabel}`);
  const add = (tag, attrs, text) => { const n = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v)); if (text !== undefined) n.textContent = text; svg.append(n); return n; };
  for (let i = 0; i < 5; i++) { const y = ymin + (ymax - ymin) * i / 4; add('line', { x1: L, y1: yp(y), x2: W - R, y2: yp(y), stroke: '#e9eee7' }); add('text', { x: L - 7, y: yp(y) + 4, fill: '#879c8c', 'font-size': 11, 'text-anchor': 'end' }, fmt(y, 2)); }
  for (let i = 0; i < 5; i++) { const x = xmin + (xmax - xmin) * i / 4; add('text', { x: xp(x), y: H - 24, fill: '#879c8c', 'font-size': 11, 'text-anchor': 'middle' }, fmt(x, 1)); }
  add('text', { x: (L + W - R) / 2, y: H - 6, fill: '#566a60', 'font-size': 11, 'text-anchor': 'middle' }, xlabel);
  add('text', { x: 12, y: (T + H - B) / 2, fill: '#566a60', 'font-size': 11, 'text-anchor': 'middle', transform: `rotate(-90 12 ${(T + H - B) / 2})` }, ylabel);
  P.forEach(p => { const c = add('circle', { cx: xp(p.x), cy: yp(p.y), r: 3.6, fill: p.c, opacity: 0.6 }); c.append(Object.assign(document.createElementNS(ns, 'title'), { textContent: `${fmt(p.x, 2)}: ${fmt(p.y, 3)}` })); });
  node.append(svg);
}
async function loadData() {
  try {
    const [m, d] = await Promise.all([fetch('/api/meta', { cache: 'no-store' }).then(r => r.json()), fetch('/api/dataset', { cache: 'no-store' }).then(r => r.json())]);
    META = m;
    $('side-status-text').textContent = `${d.n} Aspen cases • surrogate ready`; document.querySelector('.status-dot').classList.add('connected');
    $('overview-case-count').textContent = String(d.n); $('overview-case-caption').textContent = 'Aspen Plus cases, all converged and mass-balance checked';
    const worst = Math.min(...Object.values(m.data.surrogate_cv).map(x => x.r2)); $('overview-r2').textContent = fmt(worst, 2);
    $('legend').replaceChildren(...[30, 45, 60].map(k => { const s = el('span', 'legend-item'); const i = el('i'); i.style.background = COLORS[k]; s.append(i, document.createTextNode(` PET ${k} %`)); return s; }));
    scatter('chart-recovery', 'residence_time_s', 'PET_recovery_pct', d.points, 'PET recovery, %', 'residence time, s');
    scatter('chart-energy', 'crusher_gap_mm', 'crusher_kWh_per_tonne_feed', d.points, 'kWh / t fresh feed', 'crusher gap, mm');
    scatter('chart-recycle', 'screen1_cut_mm', 'recycle_ratio', d.points, 'recycle ratio', 'screen 1 cut, mm');
    scatter('chart-purity', 'residence_time_s', 'PE_PP_purity_light', d.points, 'PE+PP purity in LIGHT', 'residence time, s');
    $('quality-summary').textContent = `${d.n} Aspen cases; surrogate error from 10-fold cross-validation`;
    const cv = Object.entries(m.data.surrogate_cv).map(([k, v]) => [(LABEL[k] ? LABEL[k][0] : k), fmt(v.rmse, 4), fmt(v.r2, 3)]);
    $('quality-details').replaceChildren(el('p', '', 'Every case passed: recycle loop converged (run-history file), no errors, fresh feed = fines + dense + light within 0.1 % (worst 2.5e-7 %), size distributions close. The surrogate predicts the Aspen results with the errors below (held-out cases).'), table(['Output', 'RMSE', 'R²'], cv));
    $('limits-list').replaceChildren(...m.limits.map(t => el('li', '', t)));
    const ct = $('cost-table'); const th = el('thead'), tr = el('tr'); ['Constant', 'Low', 'Base', 'High', 'Source / basis'].forEach(h => tr.append(el('th', '', h))); th.append(tr); ct.replaceChildren(th);
    const tb = el('tbody'); Object.entries(m.cost_constants).forEach(([k, c]) => { const r = el('tr'); [k, c.low, c.base, c.high, c.note].forEach((x, i) => r.append(el('td', i && i < 4 ? 'num' : '', String(x)))); tb.append(r); }); ct.append(tb);
  } catch (err) { $('side-status-text').textContent = 'Data service unavailable'; toast('Cannot reach the ReSort data service.', true); }
}
loadData();
