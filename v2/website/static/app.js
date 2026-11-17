'use strict';
// Recycle-Labs browser UI. Calls /api/proposal, /api/curves, /api/meta and /api/dataset (Python flowsheet model + optimiser + sizing + cost). No Aspen at request time. All server text is inserted with textContent.
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
{ const startView = location.hash.slice(1); if (VIEWS[startView]) go(startView); }      // e.g. /#calculator opens that page

const LIM = { pet: [20, 70], hdpe: [0, 70], pp: [0, 70] }, IDS = ['pet', 'hdpe', 'pp'];
let touched = [];                                           // sliders in the order the user last moved them (most recent last)
const clampTo = (id, x) => Math.min(LIM[id][1], Math.max(LIM[id][0], x));
const half = x => Math.round(x * 2) / 2;
function rebalance(changed) {
  const cur = {}; IDS.forEach(i => cur[i] = Number($(i).value));
  let x = clampTo(changed, half(cur[changed]));
  const others = IDS.filter(i => i !== changed);
  const pos = i => touched.lastIndexOf(i);
  const vals = { [changed]: x };
  if (pos(others[0]) < 0 && pos(others[1]) < 0) {           // nothing set yet: share the remainder in proportion
    const rest = 100 - x, sum = cur[others[0]] + cur[others[1]];
    vals[others[0]] = half(sum > 0 ? rest * cur[others[0]] / sum : rest / 2);
    vals[others[1]] = 100 - x - vals[others[0]];
  } else {                                                  // the slider moved most recently stays put; the other one absorbs the change
    const lockedId = pos(others[0]) > pos(others[1]) ? others[0] : others[1], freeId = lockedId === others[0] ? others[1] : others[0];
    let l = cur[lockedId], f = 100 - x - l;
    if (f < LIM[freeId][0] || f > LIM[freeId][1]) {          // not possible: stop the moved slider first, move the locked one only as a last resort
      f = clampTo(freeId, f); x = 100 - l - f;
      if (x < LIM[changed][0] || x > LIM[changed][1]) { x = clampTo(changed, x); l = clampTo(lockedId, 100 - x - f); }
    }
    vals[changed] = half(x); vals[lockedId] = half(l); vals[freeId] = 100 - vals[changed] - vals[lockedId];
  }
  IDS.forEach(i => { $(i).value = vals[i]; $('val-' + i).textContent = fmt(vals[i], 1); });
  touched = touched.filter(i => i !== changed).concat(changed);
}
function updateCompo() {
  const ids = ['pet', 'hdpe', 'pp'], arr = ids.map(id => Number($(id).value));
  const total = arr.reduce((a, b) => a + b, 0);
  ids.forEach((id, i) => $('bar-' + id).style.width = (Math.max(0, arr[i]) / Math.max(100, total) * 100) + '%');
  const okay = arr.every(n => Number.isFinite(n) && n >= 0 && n <= 100) && Math.abs(total - 100) < 0.01;
  $('composition-status').textContent = okay ? 'Composition totals 100 %. The model uses the PET share (20–70 %).' : `Composition totals ${fmt(total, 2)} %; it must equal 100 %.`;
  $('composition-status').classList.toggle('error', !okay);
  return okay;
}
IDS.forEach(id => $(id).addEventListener('input', () => { rebalance(id); updateCompo(); })); updateCompo();
$('mode').addEventListener('change', () => { $('manual-box').hidden = $('mode').value !== 'evaluate'; $('objective-box').hidden = $('mode').value === 'evaluate'; });

const opt = id => { const s = $(id).value.trim(); return s === '' ? null : Number(s); };
function buildRequest() {
  const prices = {}; [['dense_usd_t', 'p-dense'], ['light_usd_t', 'p-light'], ['scrap_usd_t', 'p-scrap'], ['electricity_usd_kwh', 'p-power'], ['wage_usd_h', 'p-wage']].forEach(([k, id]) => { const v = opt(id); if (v !== null) prices[k] = v; });
  const lf = {}; [['capex_factor', 'f-capex'], ['labour_factor', 'f-labour']].forEach(([k, id]) => { const v = opt(id); if (v !== null) lf[k] = v; });
  const req = {
    feed_rate_kg_h: opt('feed'), hours_per_day: opt('hours'), days_per_year: opt('days'), mode: $('mode').value, objective: $('objective').value,
    composition: { PET: opt('pet'), HDPE: opt('hdpe'), PP: opt('pp') },
    product_d50_min_mm: opt('d50min'), product_d50_max_mm: opt('d50max'), target: $('target').value, min_purity_pct: opt('purity'), min_recovery_pct: opt('recovery'),
    budget_usd: opt('budget'), prices, location_factors: lf
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
  $('recommendation-subtitle').textContent = p.mode === 'optimise' ? ({ payback: 'Settings with the shortest payback that meet your requirements', profit: 'Settings with the highest annual profit that meet your requirements', recovery: 'Settings with the highest product recovery that meet your requirements', energy: 'Lowest-energy settings that meet your requirements' }[p.objective] || 'Optimised settings') : 'Predictions for your own settings';
  $('selection-method').textContent = (p.mode === 'optimise' ? 'OPTIMISED SETTINGS' : 'YOUR SETTINGS') + ' · PYTHON MODEL CHECKED AGAINST ASPEN · NOT A LIVE ASPEN RUN';
  body.append(section('Operating settings', gridItems([['Crusher gap', fmt(v.crusher_gap_mm, 2) + ' mm'], ['Screen 1 cut', fmt(v.screen1_cut_mm, 2) + ' mm'], ['Screen 2 cut', fmt(v.screen2_cut_mm, 2) + ' mm'], ['Tank residence', fmt(v.residence_time_s, 1) + ' s']])));
  if (p.why && p.why.length) body.append(section('Why these settings', list(p.why)));
  if (p.warnings.length) body.append(section('Notes for this case', list(p.warnings)));
  if (Object.keys(p.constraints_met).length) {
    body.append(section('Your requirements', table(['Requirement', 'Required', 'Predicted', ''], Object.entries(p.constraints_met).map(([k, m]) => {
      const pct = k.includes('purity'); const f = x => pct ? fmt(100 * x, 2) + ' %' : (k.includes('d50') ? fmt(x, 2) + ' mm' : fmt(x, 1) + ' %');
      return [CONS_LABEL[k], f(m.required), f(m.predicted), tag(m.ok, 'met', 'not met')];
    }))));
  }
  const rows = Object.entries(LABEL).map(([k, [name, f]]) => [name, f(p.predicted[k].value)]);
  body.append(section('Predicted performance', table(['Output', 'Value'], rows),
    el('p', 'help', 'The Python model reproduces the Aspen results to about 1e-4, so no numerical uncertainty band is shown. The real uncertainty is in the assumptions (tank spread, crusher energy, prices): see the sensitivity table below and the Model & limitations page.')));
  if (p.nearest_aspen_case) {
    const n = p.nearest_aspen_case, a = n.aspen, m = n.model_at_case, ks = ['PET_recovery_pct', 'PET_purity_dense', 'recycle_ratio', 'd50_coarse_mm', 'crusher_kWh_per_tonne_feed'];
    const s0 = n.settings;
    body.append(section('Closest simulated Aspen case (precomputed result)', table(['Output', 'This proposal', 'Aspen case ' + n.case_id, 'Model at that case'],
      ks.map(k => [LABEL[k][0], LABEL[k][1](p.predicted[k].value), LABEL[k][1](a[k]), LABEL[k][1](m[k])])),
      el('p', 'help', `Case ${n.case_id}: PET ${fmt(s0.PET_frac_pct, 0)} %, gap ${fmt(s0.crusher_gap_mm, 1)} mm, SCREEN1 ${fmt(s0.screen1_cut_mm, 1)} mm, SCREEN2 ${fmt(s0.screen2_cut_mm, 1)} mm, tank ${fmt(s0.residence_time_s, 0)} s. Distance to your settings: ${fmt(n.distance, 2)} (0 = identical; each setting is scaled to its simulated range). The last two columns agree, which shows the Python model reproduces the Aspen run at that case.`)));
  }
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

function rangeProblems() {
  const out = []; document.querySelectorAll('#design-form input').forEach(i => i.classList.remove('invalid'));
  document.querySelectorAll('#design-form input[type=number]').forEach(i => {
    if (i.closest('[hidden]') || i.value.trim() === '') return;
    const v = Number(i.value), lo = i.min === '' ? null : Number(i.min), hi = i.max === '' ? null : Number(i.max);
    if (!Number.isFinite(v) || (lo !== null && v < lo) || (hi !== null && v > hi)) {
      const name = (i.closest('label').childNodes[0].textContent || i.id).trim();
      out.push(name + ' must be ' + (lo !== null && hi !== null ? 'between ' + lo + ' and ' + hi : lo !== null ? lo + ' or more' : 'a number') + '.'); i.classList.add('invalid');
    }
  });
  const d1 = opt('d50min'), d2 = opt('d50max'); if (d1 !== null && d2 !== null && d1 > d2) { out.push('Product d50 min must not exceed d50 max.'); $('d50min').classList.add('invalid'); }
  const h = opt('hours'), d = opt('days'); if (h !== null && d !== null && h * d > 8760) { out.push('Operating hours per day x days per year must not exceed 8,760.'); $('hours').classList.add('invalid'); }
  return out;
}

async function submit(e) {
  e.preventDefault();
  const fe = $('form-errors'); fe.hidden = true; fe.replaceChildren();
  const problems = rangeProblems();
  if (problems.length) { fe.hidden = false; fe.append(el('strong', '', 'Please check your inputs:'), list(problems, 'err-list')); toast('Some inputs are outside their allowed range.', true); return; }
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
const COLORS = { 20: '#8a5fb0', 30: '#d98b3a', 45: '#3a8860', 60: '#3f6fb0', 70: '#b04a4a' };
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
const LCOL = ['#3a8860', '#d98b3a', '#3f6fb0', '#b04a4a', '#8a5fb0'];
function lineChart(id, xlabel, ylabel, series, o = {}) {
  const node = $(id); node.replaceChildren();
  const W = 620, H = 270, L = 58, R = 18, T = 14, B = 46;
  const xs = series.flatMap(s => s.x), ys = series.flatMap(s => s.y);
  const xmin = Math.min(...xs), xmax = Math.max(...xs); let ymin = Math.min(...ys), ymax = Math.max(...ys);
  const pad = (ymax - ymin) * 0.07 || 1; const lo = ymin, hi = ymax;
  ymin = o.ymin !== undefined ? o.ymin : (lo >= 0 ? Math.max(0, lo - pad) : lo - pad); ymax = o.ymax !== undefined ? o.ymax : hi + pad;
  const xp = x => L + (x - xmin) / (xmax - xmin) * (W - L - R), yp = y => H - B - (y - ymin) / (ymax - ymin) * (H - B - T);
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', `${ylabel} vs ${xlabel}`);
  const add = (tag, attrs, text) => { const n = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v)); if (text !== undefined) n.textContent = text; svg.append(n); return n; };
  for (let i = 0; i < 5; i++) { const y = ymin + (ymax - ymin) * i / 4; add('line', { x1: L, y1: yp(y), x2: W - R, y2: yp(y), stroke: '#e9eee7' }); add('text', { x: L - 7, y: yp(y) + 4, fill: '#879c8c', 'font-size': 11, 'text-anchor': 'end' }, fmt(y, Math.abs(ymax) < 5 ? 2 : Math.abs(ymax) < 50 ? 1 : 0)); }
  for (let i = 0; i < 5; i++) { const x = xmin + (xmax - xmin) * i / 4; add('text', { x: xp(x), y: H - 26, fill: '#879c8c', 'font-size': 11, 'text-anchor': 'middle' }, fmt(x, xmax - xmin < 20 ? 1 : 0)); }
  add('text', { x: (L + W - R) / 2, y: H - 8, fill: '#566a60', 'font-size': 11, 'text-anchor': 'middle' }, xlabel);
  add('text', { x: 13, y: (T + H - B) / 2, fill: '#566a60', 'font-size': 11, 'text-anchor': 'middle', transform: `rotate(-90 13 ${(T + H - B) / 2})` }, ylabel);
  series.forEach((s, k) => {
    const d = s.x.map((x, i) => (i ? 'L' : 'M') + xp(x).toFixed(1) + ' ' + yp(s.y[i]).toFixed(1)).join(' ');
    add('path', { d, fill: 'none', stroke: LCOL[k % LCOL.length], 'stroke-width': 2.4, 'stroke-linejoin': 'round' });
    const ly = T + 12 + k * 16; add('line', { x1: L + 12, y1: ly - 4, x2: L + 32, y2: ly - 4, stroke: LCOL[k % LCOL.length], 'stroke-width': 2.4 }); add('text', { x: L + 38, y: ly, fill: '#3f5a4c', 'font-size': 11 }, s.name);
  });
  node.append(svg);
}
const EX = [['ex-pet', 'pet', 'PET %'], ['ex-gap', 'gap', 'Crusher gap'], ['ex-s1', 's1', 'SCREEN1'], ['ex-s2', 's2', 'SCREEN2'], ['ex-tau', 'tau', 'Tank time'], ['ex-sig', 'spread', 'Tank spread']];
let curvesTimer = null;
async function loadCurves() {
  const ee = $('explorer-errors'); ee.hidden = true; ee.replaceChildren();
  const probs = [], q = new URLSearchParams();
  EX.forEach(([id, key, name]) => {
    const i = $(id), v = Number(i.value); i.classList.remove('invalid');
    if (i.value.trim() === '' || !Number.isFinite(v) || v < Number(i.min) || v > Number(i.max)) { probs.push(`${name} must be between ${i.min} and ${i.max}.`); i.classList.add('invalid'); } else q.set(key, String(v));
  });
  if (probs.length) { ee.hidden = false; ee.append(el('strong', '', 'Please check the values:'), list(probs, 'err-list')); return; }
  try {
    const r = await fetch('/api/curves?' + q.toString(), { cache: 'no-store' }); const c = await r.json();
    if (!r.ok) { ee.hidden = false; ee.append(el('strong', '', 'Please check the values:'), list(c.errors.map(x => x.message), 'err-list')); return; }
    lineChart('line-tau', 'tank residence time, s', 'PET recovery, %', Object.entries(c.tau.series).map(([s, v]) => ({ name: 'σ = ' + s, x: c.tau.x, y: v.PET_recovery_pct })), { ymin: 0, ymax: 100 });
    lineChart('line-s1', 'SCREEN1 cut, mm', 'recycle ratio', Object.entries(c.s1.series).map(([g, v]) => ({ name: 'gap ' + g + ' mm', x: c.s1.x, y: v.recycle_ratio })), { ymin: 0 });
    lineChart('line-s1d50', 'SCREEN1 cut, mm', 'product d50, mm', Object.entries(c.s1.series).map(([g, v]) => ({ name: 'gap ' + g + ' mm', x: c.s1.x, y: v.d50_coarse_mm })), { ymin: 0 });
    lineChart('line-gap', 'crusher gap, mm', 'crusher energy, kWh / t feed', [{ name: 'energy', x: c.gap.x, y: c.gap.kwh }], { ymin: 0 });
    lineChart('line-s2', 'SCREEN2 cut, mm', '% of fresh feed', [{ name: 'fines loss', x: c.s2.x, y: c.s2.fines_loss_pct }, { name: 'flake yield', x: c.s2.x, y: c.s2.yield_pct }], { ymin: 0, ymax: 100 });
    lineChart('line-pet', 'PET share of the feed, %', 'kg/h (feed 300 kg/h)', [{ name: 'PET-rich (DENSE)', x: c.pet.x, y: c.pet.dense }, { name: 'PE/PP-rich (LIGHT)', x: c.pet.x, y: c.pet.light }, { name: 'fines', x: c.pet.x, y: c.pet.fines }], { ymin: 0 });
  } catch (err) { toast('Could not draw the model curves.', true); }
}
EX.forEach(([id]) => $(id).addEventListener('input', () => { clearTimeout(curvesTimer); curvesTimer = setTimeout(loadCurves, 350); }));

async function loadData() {
  try {
    const [m, d] = await Promise.all([fetch('/api/meta', { cache: 'no-store' }).then(r => r.json()), fetch('/api/dataset', { cache: 'no-store' }).then(r => r.json())]);
    META = m; const sm = m.data.summary;
    const big = fmt(sm.model_rows, 0) + '+'; $('hero-total').textContent = big;
    const B = m.bounds, rr = [['Feed rate', fmt(B.feed_kg_h[0], 0) + ' – ' + fmt(B.feed_kg_h[1], 0), 'kg/h'], ['PET share of the feed', fmt(B.pet_pct[0], 0) + ' – ' + fmt(B.pet_pct[1], 0), '%'],
      ['Crusher gap', fmt(B.crusher_gap_mm[0], 0) + ' – ' + fmt(B.crusher_gap_mm[1], 0), 'mm'], ['SCREEN1 cut', fmt(B.screen1_cut_mm[0], 0) + ' – ' + fmt(B.screen1_cut_mm[1], 0), 'mm'],
      ['SCREEN2 cut', fmt(B.screen2_cut_mm[0], 0) + ' – ' + fmt(B.screen2_cut_mm[1], 0), 'mm'], ['Tank residence time', fmt(B.residence_time_s[0], 0) + ' – ' + fmt(B.residence_time_s[1], 0), 's'],
      ['Tank spread σ (assumed)', fmt(B.tank_spread[0], 2) + ' – ' + fmt(B.tank_spread[1], 2), '-'], ['Product d50 the model can reach', '3.3 – 10.8', 'mm']];
    const rt = $('range-table'), rth = el('thead'), rtr = el('tr'); ['Input', 'Valid range', 'Unit'].forEach(h => rtr.append(el('th', '', h))); rth.append(rtr); rt.replaceChildren(rth);
    const rtb = el('tbody'); rr.forEach(r => { const tr = el('tr'); r.forEach((x, i) => tr.append(el('td', i === 1 ? 'num' : '', x))); rtb.append(tr); }); rt.append(rtb);
    $('legend').replaceChildren(...[20, 30, 45, 60, 70].map(k => { const s = el('span', 'legend-item'); const i = el('i'); i.style.background = COLORS[k]; s.append(i, document.createTextNode(` PET ${k} %`)); return s; }));
    scatter('chart-recovery', 'residence_time_s', 'PET_recovery_pct', d.points, 'PET recovery, %', 'residence time, s');
    scatter('chart-petpurity', 'residence_time_s', 'PET_purity_dense', d.points, 'PET purity in DENSE', 'residence time, s');
    scatter('chart-purity', 'residence_time_s', 'PE_PP_purity_light', d.points, 'PE+PP purity in LIGHT', 'residence time, s');
    scatter('chart-energy', 'crusher_gap_mm', 'crusher_kWh_per_tonne_feed', d.points, 'kWh / t fresh feed', 'crusher gap, mm');
    scatter('chart-recycle', 'screen1_cut_mm', 'recycle_ratio', d.points, 'recycle ratio', 'screen 1 cut, mm');
    scatter('chart-d50', 'screen1_cut_mm', 'd50_coarse_mm', d.points, 'product d50, mm', 'screen 1 cut, mm');
    scatter('chart-fines', 'screen2_cut_mm', 'fines_loss_pct', d.points, 'fines loss, %', 'screen 2 cut, mm');
    scatter('chart-tradeoff', 'crusher_kWh_per_tonne_feed', 'PET_recovery_pct', d.points, 'PET recovery, %', 'crusher energy, kWh / t');
    loadCurves();
    $('quality-summary').textContent = `${fmt(sm.aspen_cases, 0)} Aspen cases; the Python model is checked against every one of them`;
    const cv = Object.entries(m.data.surrogate_cv).map(([k, v]) => [(LABEL[k] ? LABEL[k][0] : k), fmt(v.rmse, 4), fmt(v.r2, 3)]);
    $('quality-details').replaceChildren(el('p', '', `Every Aspen case passed: recycle loop converged (run-history file), no errors, fresh feed = fines + dense + light within 0.1 % (worst ${Number(sm.max_balance_error_pct).toExponential(1)} %), size distributions close. The Python model reproduces the Aspen results with the differences below.`), table(['Output', 'RMSE (model - Aspen)', 'R²'], cv));
    $('limits-list').replaceChildren(...m.limits.map(t => el('li', '', t)));
    const ct = $('cost-table'); const th = el('thead'), tr = el('tr'); ['Constant', 'Low', 'Base', 'High', 'Source / basis'].forEach(h => tr.append(el('th', '', h))); th.append(tr); ct.replaceChildren(th);
    const tb = el('tbody'); Object.entries(m.cost_constants).forEach(([k, c]) => { const r = el('tr'); [k, c.low, c.base, c.high, c.note].forEach((x, i) => r.append(el('td', i && i < 4 ? 'num' : '', String(x)))); tb.append(r); }); ct.append(tb);
  } catch (err) { toast('Cannot reach the Recycle-Labs data service.', true); }
}
loadData();
