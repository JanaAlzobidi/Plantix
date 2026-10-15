/* Plantix — helpers shared by the event-owner and venue-supervisor pages. */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const h = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const plural = (n, one, few, many, two) => (n === 1 ? (one.endsWith('ة') ? `${one} واحدة` : `${one} واحد`) : n === 2 ? (two || `2 ${few}`) : n >= 3 && n <= 10 ? `${n} ${few}` : `${n} ${many}`);

const svg = (body, size = 16, extra = '') => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${body}</svg>`;
const ICON = {
  check: () => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--ok)" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="سليم"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>`,
  bad: () => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--danger-text)" stroke-width="2.6" stroke-linecap="round" role="img" aria-label="مشكلة"><path d="M6 6l12 12M18 6L6 18"/></svg>`,
  warn: () => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--amber-text)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="تنبيه"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>`,
  info: () => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" stroke-width="2.2" stroke-linecap="round" role="img" aria-label="معلومة"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>`,
  close: () => svg('<path d="M6 6l12 12M18 6L6 18"/>'),
  plus: () => svg('<path d="M12 5v14M5 12h14"/>'),
  moon: () => svg('<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>', 17),
  sun: () => svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>', 17),
  bell: () => svg('<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>', 16),
  wrench: () => svg('<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-2.4z"/>', 16),
};
const checkRow = (kind, text) => `<div class="check">${ICON[kind === 'ok' ? 'check' : kind]()}<span>${h(text)}</span></div>`;

async function api(method, url, body) {
  let res;
  try {
    res = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
  } catch (e) {
    throw Object.assign(new Error('تعذّر الاتصال بالخادم. تأكدي أن server.py يعمل.'), { data: null });
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    const msg = typeof d === 'string' ? d : (d && d.message) || 'تعذّر تنفيذ الطلب.';
    throw Object.assign(new Error(msg), { data: d });
  }
  return data;
}

function index(state) {
  const p = {}, v = {}, s = {}, d = {};
  state.programs.forEach((x) => { p[x.id] = x; });
  state.venues.forEach((x) => { v[x.id] = x; });
  state.schedule.forEach((x) => { s[x.program_id] = x; });
  state.days.forEach((x) => { d[x.date] = x; });
  return { p, v, s, d };
}
function where(ix, slot) {
  const day = ix.d[slot.date] ? ix.d[slot.date].long : slot.date;
  return `${day} · ${slot.start} · ${ix.v[slot.venue_id] ? ix.v[slot.venue_id].name : slot.venue_id}`;
}
function eqLabel(state, id) { const e = (state.equipment || []).find((x) => x.id === id); return e ? e.label : id; }

// ---------------------------------------------------------------- feedback
const FB = { busy: '', toast: '', error: false };
let fbTimer = null;
function renderFeedback() {
  const el = $('#feedback');
  if (FB.busy) el.innerHTML = `<div class="float busy" role="status"><span class="spinner"></span><span>${h(FB.busy)}</span></div>`;
  else if (FB.toast) el.innerHTML = `<div class="float toast ${FB.error ? 'error' : ''}" role="status">${FB.error ? '' : svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 16)}<span>${h(FB.toast)}</span></div>`;
  else el.innerHTML = '';
}
function toast(msg, error = false) {
  FB.toast = msg; FB.error = error; FB.busy = ''; renderFeedback();
  clearTimeout(fbTimer);
  fbTimer = setTimeout(() => { FB.toast = ''; renderFeedback(); }, error ? 6000 : 4200);
}
function busy(label) { FB.busy = label; FB.toast = ''; renderFeedback(); }
function idle() { FB.busy = ''; renderFeedback(); }

// ---------------------------------------------------------------- theme
function paintTheme() {
  const dark = document.documentElement.dataset.theme === 'dark';
  const b = $('#theme-btn');
  if (!b) return;
  b.innerHTML = `${dark ? ICON.sun() : ICON.moon()}<span>${dark ? 'صباحي' : 'ليلي'}</span>`;
  b.setAttribute('aria-label', dark ? 'التبديل إلى النمط الصباحي' : 'التبديل إلى النمط الليلي');
}
function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('plantix-theme', next); } catch (e) { /* storage unavailable */ }
  paintTheme();
}
function store(key, value) {
  try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (e) { /* storage unavailable */ }
  return null;
}

function notificationsHTML(list, empty) {
  if (!list.length) return `<div class="empty-note">${h(empty)}</div>`;
  return list.slice().reverse().map((n) => `<div class="notif">
      <span class="notif-dot">${ICON.bell()}</span>
      <div style="min-width:0"><div class="notif-head"><b>${h(n.title)}</b><span class="muted">${h(n.time)}</span></div>
      <div class="notif-text">${h(n.text)}</div></div></div>`).join('');
}
