/* Plantix — organizer interface. Every number on this page comes from the
   scheduling engine through server.py; nothing is computed by guesswork here. */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const h = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const toMin = (t) => { const [a, b] = String(t).split(':').map(Number); return a * 60 + (b || 0); };
const fmt = (m) => String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
const plural = (n, one, few, many, two) => (n === 1 ? (one.endsWith('ة') ? `${one} واحدة` : `${one} واحد`) : n === 2 ? (two || `2 ${few}`) : n >= 3 && n <= 10 ? `${n} ${few}` : `${n} ${many}`);
const secs = (s) => (s == null ? '' : ` · أُعيدت الجدولة في ${Number(s).toFixed(2)} ث`);

const svg = (body, size = 16, extra = '') => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${body}</svg>`;
const ICON = {
  check: (c = 'var(--ok)') => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="سليم"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>`,
  bad: () => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--danger-text)" stroke-width="2.6" stroke-linecap="round" role="img" aria-label="مشكلة"><path d="M6 6l12 12M18 6L6 18"/></svg>`,
  warn: () => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--amber-text)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="تنبيه"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>`,
  info: () => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" stroke-width="2.2" stroke-linecap="round" role="img" aria-label="معلومة"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>`,
  lock: (s = 13) => svg('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>', s),
  close: () => svg('<path d="M6 6l12 12M18 6L6 18"/>'),
  moon: () => svg('<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>', 17),
  sun: () => svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>', 17),
  bell: () => svg('<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>', 18),
  download: () => svg('<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>'),
  chevron: () => svg('<path d="M6 9l6 6 6-6"/>', 12),
  plus: () => svg('<path d="M12 5v14M5 12h14"/>'),
  flask: () => svg('<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3"/>'),
  message: () => svg('<path d="M4 5h16v11H8l-4 3.5z"/>', 18, 'style="flex:none;margin-top:2px;color:var(--muted)"'),
};
const checkRow = (kind, text) => `<div class="check">${ICON[kind === 'ok' ? 'check' : kind]()}<span>${h(text)}</span></div>`;

const TYPE_LABEL = { new: 'جديدة', unchanged: 'معتمدة', moved: 'تغيّرت', not_scheduled: 'لم تُجدول', dropped: 'أُسقطت', removed: 'حُذفت' };
const TYPE_CHIP = { new: 'chip-blue', unchanged: 'chip-green', moved: 'chip-amber', not_scheduled: 'chip-danger', dropped: 'chip-danger', removed: '' };
const KIND_CLASS = { new: 'k-new', unchanged: 'k-approved', moved: 'k-moved' };
const SLOT_PRESETS = ['', '09:00-12:00', '12:00-15:00', '15:00-18:00'];
const WEEKDAYS = ['الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت'];
const MONTHS = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر'];

// ------------------------------------------------------------------ state

const S = { data: null, sc: null };
const U = {
  day: null, view: 'timeline', panel: null, selected: null,
  q: '', searchOpen: false, searchIndex: 0, dlOpen: false, unschedOpen: false,
  whatIf: null, scenario: { kind: 'close_venue', venue_id: '', program_id: '', value: '', day_end: '20:00' },
  form: null, check: null, checking: false,
  busy: '', toast: '', toastError: false,
  theme: document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light',
};

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

// ------------------------------------------------------------------ lookups

function world() { return U.whatIf === 'result' && S.sc && S.sc.ok ? S.sc : S.data; }
function index(w) {
  const p = {}, v = {}, s = {}, d = {};
  w.programs.forEach((x) => { p[x.id] = x; });
  w.venues.forEach((x) => { v[x.id] = x; });
  w.schedule.forEach((x) => { s[x.program_id] = x; });
  w.days.forEach((x) => { d[x.date] = x; });
  return { p, v, s, d };
}
function where(ix, slot) { return `${ix.d[slot.date] ? ix.d[slot.date].label : slot.date} ${slot.start} · ${ix.v[slot.venue_id] ? ix.v[slot.venue_id].name : slot.venue_id}`; }
function currentDay(w) {
  if (U.day && w.days.some((d) => d.date === U.day)) return U.day;
  const open = w.days.find((d) => !d.frozen) || w.days[0];
  U.day = open ? open.date : null;
  return U.day;
}
function eqLabel(id) { const e = (S.data.equipment || []).find((x) => x.id === id); return e ? e.label : id; }
function nextDayLabel() {
  const last = S.data.days[S.data.days.length - 1].date;
  const d = new Date(last + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + 1);
  return `${WEEKDAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

// ------------------------------------------------------------------ feedback

let toastTimer = null;
function toast(msg, error = false) {
  U.toast = msg; U.toastError = error; renderFeedback();
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { U.toast = ''; renderFeedback(); }, error ? 6000 : 4000);
}
function renderFeedback() {
  const el = $('#feedback');
  if (U.busy) el.innerHTML = `<div class="float busy" role="status"><span class="spinner"></span><span>${h(U.busy)}</span></div>`;
  else if (U.toast) el.innerHTML = `<div class="float toast ${U.toastError ? 'error' : ''}" role="status">${U.toastError ? '' : svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 16)}<span>${h(U.toast)}</span></div>`;
  else el.innerHTML = '';
}
async function mutate(label, call, success) {
  U.busy = label; U.toast = ''; renderFeedback();
  try {
    const res = await call();
    if (res && res.state) S.data = res.state;
    U.busy = '';
    render(true);
    toast(typeof success === 'function' ? success(res) : success);
    return res;
  } catch (e) {
    U.busy = ''; renderFeedback();
    toast(e.message, true);
    throw e;
  }
}

// ------------------------------------------------------------------ header

function renderHeader() {
  const dark = U.theme === 'dark';
  $('#theme-btn').innerHTML = `${dark ? ICON.sun() : ICON.moon()}<span>${dark ? 'صباحي' : 'ليلي'}</span>`;
  $('#theme-btn').setAttribute('aria-label', dark ? 'التبديل إلى النمط الصباحي' : 'التبديل إلى النمط الليلي');
  const n = S.data ? S.data.unscheduled.length + S.data.reports.filter((r) => r.status === 'open').length : 0;
  $('#bell').innerHTML = ICON.bell() + (n ? `<span class="badge">${n}</span>` : '');
}
function searchResults() {
  const q = U.q.trim();
  if (!q || !S.data) return [];
  return S.data.programs.filter((p) => p.name.includes(q) || p.id.toLowerCase() === q.toLowerCase()).slice(0, 6);
}
function renderSearch() {
  const box = $('#search-results');
  if (!U.searchOpen || !S.data) { box.innerHTML = ''; $('#search').setAttribute('aria-expanded', 'false'); return; }
  $('#search').setAttribute('aria-expanded', 'true');
  const ix = index(S.data);
  const list = searchResults();
  const note = !U.q.trim() ? 'اكتب جزءًا من اسم الفعالية' : list.length ? '' : 'لا توجد فعالية بهذا الاسم';
  box.innerHTML = `<div class="menu" role="listbox" aria-label="نتائج البحث">
    ${note ? `<div class="menu-note">${note}</div>` : ''}
    ${list.map((p, i) => {
      const slot = ix.s[p.id];
      return `<button type="button" role="option" aria-selected="${i === U.searchIndex}" class="menu-item ${i === U.searchIndex ? 'active' : ''}" data-act="searchPick" data-id="${h(p.id)}">
        <b>${h(p.name)}</b><span style="font-size:12px;white-space:nowrap;color:${slot ? 'var(--muted)' : 'var(--danger-text)'}">${slot ? h(where(ix, slot)) : 'لم تُجدول'}</span></button>`;
    }).join('')}
  </div>`;
}

// ------------------------------------------------------------------ aside

function asideHTML() {
  if (U.whatIf) return whatIfHTML();
  const d = S.data;
  const inbox = d.unscheduled.map((u) => {
    const editLabel = ['EQUIPMENT', 'CAPACITY_AND_EQUIPMENT'].includes(u.reason_code) ? 'عدّل المتطلبات' : 'عدّل الفعالية';
    const primary = u.fix
      ? `<button type="button" class="btn btn-primary btn-sm" data-act="fix" data-id="${h(u.program_id)}">${h(u.fix.label)}</button>`
      : `<button type="button" class="btn btn-primary btn-sm" data-act="edit" data-id="${h(u.program_id)}">${editLabel}</button>`;
    return `<div class="inbox-item">
      <div style="display:flex;align-items:center;gap:6px"><span class="chip chip-danger">لم تُجدول</span><span class="muted" style="font-size:11.5px">السبب: ${h(u.label)}</span></div>
      <div class="name">${h(u.name)}</div>
      <div class="reason" title="${h(u.reason)}">${h(u.reason)}</div>
      <div class="row-actions">${primary}<button type="button" class="btn btn-secondary btn-sm" data-act="details" data-id="${h(u.program_id)}">التفاصيل</button></div>
    </div>`;
  }).join('');

  const ch = d.changes;
  const byType = {};
  ch.forEach((c) => { byType[c.type] = (byType[c.type] || 0) + 1; });
  const frozen = ch.filter((c) => c.in_freeze && ['moved', 'dropped', 'removed'].includes(c.type)).length;
  const chips = ['new', 'moved', 'not_scheduled', 'dropped', 'removed'].filter((k) => byType[k])
    .map((k) => `<span class="chip ${TYPE_CHIP[k]}">${byType[k]} ${TYPE_LABEL[k]}</span>`).join('');
  const approval = ch.length
    ? `<section class="card approval pending stack" aria-label="الاعتماد" style="gap:9px">
        <div class="card-head"><h2>مقترح غير معتمد</h2><span class="chip chip-amber">مسودة</span></div>
        <div style="font-size:13px;color:var(--ink-2)">${plural(ch.length, 'تغيير', 'تغييرات', 'تغييرًا', 'تغييران')} بانتظار مراجعتك · ${frozen ? frozen + ' داخل يوم مجمّد' : 'لا شيء داخل اليوم المجمّد'}</div>
        <div class="chips">${chips}</div>
        <div class="muted" style="font-size:12px">الجدول المعتمد لا يتغير قبل اعتمادك، والإشعارات تُرسل بعده.</div>
        <button type="button" class="btn btn-primary btn-lg" data-act="review" ${d.summary.can_approve ? '' : 'disabled'}>مراجعة واعتماد</button>
      </section>`
    : `<section class="card approval" aria-label="الاعتماد"><div class="approved-ok"><span class="dot">${svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 18)}</span>
        <div><div style="font-weight:700">الجدول معتمد</div><div class="muted" style="font-size:12.5px">لا تغييرات بانتظار الاعتماد</div></div></div></section>`;

  const reports = d.reports.filter((r) => r.status === 'open').map((r) => `<div class="inbox-item">
      <div style="display:flex;align-items:center;gap:6px"><span class="chip chip-amber">بلاغ من مشرف القاعات</span><span class="muted" style="font-size:11.5px">${h(r.time)}</span></div>
      <div class="name">${h(r.title)}</div>
      <div class="reason">${r.errors.length ? h('يحتاج قرارك: ' + r.errors[0]) : r.affected.length ? h(`جهّز المحرك خطة بديلة: تتأثر ${plural(r.affected.length, 'فعالية', 'فعاليات', 'فعالية', 'فعاليتان')} (${r.affected.join('، ')})`) : 'لا تتأثر أي فعالية.'}</div>
      ${r.note ? `<div class="fix">${h(r.note)}</div>` : ''}
      <div class="row-actions"><button type="button" class="btn btn-primary btn-sm" data-act="review" ${d.summary.can_approve ? '' : 'disabled'}>راجع الخطة واعتمد</button></div>
    </div>`).join('');
  const pendingCount = d.unscheduled.length + d.reports.filter((r) => r.status === 'open').length;
  return `<section class="card stack">
      <div class="card-head"><h2>يحتاج قرارك</h2><span class="count">${pendingCount}</span></div>
      ${reports + inbox || '<div class="all-good">كل الفعاليات مجدولة. لا شيء ينتظرك.</div>'}
    </section>${approval}`;
}

const SCENARIOS = [
  { kind: 'close_venue', label: 'أغلق قاعة', hint: 'كأنها تعطلت طوال المعرض' },
  { kind: 'open_venue', label: 'أعد تشغيل قاعة', hint: 'إنهاء صيانة قاعة غير متاحة' },
  { kind: 'attendance', label: 'غيّر حضور فعالية', hint: 'عدد حضور جديد' },
  { kind: 'hours', label: 'مدّد ساعات التشغيل', hint: 'وقت إغلاق أطول' },
  { kind: 'add_day', label: 'أضف يومًا للمعرض', hint: 'بنفس الساعات' },
];
function scenarioDefaults(kind) {
  const d = S.data, sc = { kind, venue_id: '', program_id: '', value: '', day_end: '20:00' };
  if (kind === 'close_venue') {
    const busy = new Set(d.programs.filter((p) => p.fixed).map((p) => p.fixed.venue_id));
    const open = d.venues.filter((v) => v.status === 'available');
    sc.venue_id = ((open.find((v) => !busy.has(v.id)) || open[0]) || {}).id || '';
  }
  if (kind === 'open_venue') sc.venue_id = (d.venues.find((v) => v.status !== 'available') || {}).id || '';
  if (kind === 'attendance') { const p = d.programs[0]; sc.program_id = p ? p.id : ''; sc.value = p ? String(p.attendance) : ''; }
  return sc;
}
function scenarioParams() {
  const d = S.data, sc = U.scenario;
  if (sc.kind === 'close_venue' || sc.kind === 'open_venue') {
    const list = d.venues.filter((v) => (sc.kind === 'close_venue') === (v.status === 'available'));
    if (!list.length) return `<div class="params muted" style="font-size:12.5px">${sc.kind === 'open_venue' ? 'كل القاعات متاحة.' : 'لا توجد قاعة متاحة.'}</div>`;
    return `<div class="params"><label class="sr-only" for="sc-venue">القاعة</label><select id="sc-venue" data-sc="venue_id">${list.map((v) =>
      `<option value="${h(v.id)}" ${v.id === sc.venue_id ? 'selected' : ''}>${h(v.name)}${v.status !== 'available' ? ' (' + h(v.status_label) + ')' : ''}</option>`).join('')}</select></div>`;
  }
  if (sc.kind === 'attendance') {
    return `<div class="params"><label class="sr-only" for="sc-prog">الفعالية</label><select id="sc-prog" data-sc="program_id">${d.programs.map((p) =>
      `<option value="${h(p.id)}" ${p.id === sc.program_id ? 'selected' : ''}>${h(p.name)} (${p.attendance})</option>`).join('')}</select>
      <label class="sr-only" for="sc-val">العدد الجديد</label><input id="sc-val" type="number" min="1" data-sc="value" value="${h(sc.value)}" aria-label="العدد الجديد"></div>`;
  }
  if (sc.kind === 'hours') {
    const cur = toMin(d.day_end);
    const opts = [1, 2, 3, 4].map((k) => fmt(cur + 60 * k));
    return `<div class="params"><label class="sr-only" for="sc-hours">وقت الإغلاق</label><select id="sc-hours" data-sc="day_end">${opts.map((t) =>
      `<option value="${t}" ${t === sc.day_end ? 'selected' : ''}>حتى ${t} بدل ${h(d.day_end)}</option>`).join('')}</select></div>`;
  }
  return `<div class="params muted" style="font-size:12.5px">${h(nextDayLabel())}</div>`;
}
function whatIfHTML() {
  const sc = U.scenario, r = S.sc;
  const opts = SCENARIOS.map((o) => `<button type="button" class="option" aria-pressed="${o.kind === sc.kind}" data-act="scKind" data-kind="${o.kind}">
      <span style="font-weight:600">${o.label}</span><span class="hint">${o.hint}</span></button>${o.kind === sc.kind ? scenarioParams() : ''}`).join('');
  let result = '';
  if (U.whatIf === 'setup') {
    result = `<button type="button" class="btn btn-primary btn-lg" data-act="runWhatIf">شغّل التجربة</button>`;
  } else if (r && !r.ok) {
    result = `<div class="error-banner"><b>لا تصلح هذه التجربة: تكسر قيودًا ثابتة</b><br>${r.notes.map(h).join('<br>')}</div>
      <button type="button" class="btn btn-secondary" data-act="scKind" data-kind="${sc.kind}">جرّب قيمة أخرى</button>`;
  } else if (r) {
    const c = r.compare, cls = (good) => (good === true ? 'good' : good === false ? 'bad-text' : '');
    const rows = [
      ['فعاليات مجدولة', `${c.scheduled[0]} ← ${c.scheduled[1]}`, c.scheduled[1] > c.scheduled[0] ? true : c.scheduled[1] < c.scheduled[0] ? false : null],
      ['التفضيلات المحققة', `${c.preferences[0]} ← ${c.preferences[1]}`, c.preferences[1] < c.preferences[0] ? false : null],
      ['معتمدة تتحرك', `${c.approved_moved}${c.approved_moved_frozen ? ' (في يوم مجمّد)' : ''}`, c.approved_moved ? false : true],
      ['جديدة يُعاد ترتيبها', String(c.rearranged), null],
      ['تعارضات', String(c.conflicts), c.conflicts ? false : true],
    ];
    result = `<div class="compare">
      <div style="display:flex;justify-content:space-between;font-size:12px" class="muted"><span>${h(r.label)}</span><span>الحالي ← التجربة</span></div>
      ${rows.map(([l, v, g]) => `<div class="compare-row"><span style="color:var(--ink-2)">${l}</span><b class="${cls(g)}">${h(v)}</b></div>`).join('')}
      <ul class="notes">${r.notes.map((n) => `<li>${h(n)}</li>`).join('')}</ul>
      <div style="display:flex;gap:6px;margin-top:2px">
        <button type="button" class="btn btn-primary" style="flex:1" data-act="applyWhatIf">حوّلها إلى مقترح</button>
        <button type="button" class="btn btn-secondary" data-act="exitWhatIf">تجاهل</button>
      </div></div>`;
  }
  return `<section class="card whatif stack" aria-label="ماذا لو" style="gap:9px">
    <div class="card-head"><h2>جرّب تغييرًا</h2><span class="chip chip-amber">تجربة</span></div>
    ${opts}${result}</section>`;
}

// ------------------------------------------------------------------ KPIs

function kpisHTML() {
  const s = S.data.summary, un = S.data.unscheduled, ch = S.data.changes;
  const prefs = s.date_met + s.time_met, prefsTotal = s.date_total + s.time_total;
  const frozen = ch.filter((c) => c.in_freeze && ['moved', 'dropped', 'removed'].includes(c.type)).length;
  const pct = (a, b) => Math.round((100 * a) / Math.max(1, b));
  const pop = U.unschedOpen && un.length ? `<div class="menu popover" role="region" aria-label="الفعاليات غير المجدولة">
      <div style="display:flex;align-items:center;gap:8px;padding:0 4px 2px"><b style="font-size:13.5px">لم تُجدول (${un.length})</b>
        <span class="muted" style="font-size:12px">اضغط فعالية لتفاصيلها</span>
        <button type="button" class="close-x" style="width:30px;height:30px" data-act="unsched" aria-label="إغلاق">${ICON.close()}</button></div>
      ${un.map((u) => `<button type="button" class="pop-item" data-act="details" data-id="${h(u.program_id)}">
        <span class="line"><b>${h(u.name)}</b><span class="chip chip-danger">${h(u.label)}</span></span>
        <span style="font-size:12.5px;color:var(--ink-2)">${h(u.reason)}</span>
        <span class="muted" style="font-size:12px">الحل: ${h(u.suggestion)}</span></button>`).join('')}
    </div>` : '';
  const scheduledSub = un.length
    ? `<button type="button" class="kpi-link" data-act="unsched" aria-expanded="${U.unschedOpen}"><span>عرض ${un.length} لم تُجدول وأسبابها</span>${ICON.chevron()}</button>`
    : '<div class="kpi-sub">كلها مجدولة</div>';
  return `
    <div class="kpi" id="kpi-scheduled"><div class="kpi-label">فعاليات مجدولة</div><div class="kpi-value">${s.scheduled} من ${s.total}</div>
      ${scheduledSub}<div class="kpi-bar"><span style="width:${pct(s.scheduled, s.total)}%"></span></div>${pop}</div>
    <div class="kpi"><div class="kpi-label">تعارضات</div><div class="kpi-value" style="color:${s.conflicts ? 'var(--danger-text)' : 'var(--ok)'}">${s.conflicts}</div>
      <div class="kpi-sub">القاعة والوقت ووقت التجهيز</div></div>
    <div class="kpi"><div class="kpi-label">التفضيلات المحققة</div><div class="kpi-value">${prefs} من ${prefsTotal}</div>
      <div class="kpi-sub">اليوم ${s.date_met}/${s.date_total} · الفترة ${s.time_met}/${s.time_total}</div>
      <div class="kpi-bar blue"><span style="width:${pct(prefs, prefsTotal)}%"></span></div></div>
    <div class="kpi"><div class="kpi-label">بانتظار الاعتماد</div><div class="kpi-value" style="color:${ch.length ? 'var(--amber-text)' : 'var(--ok)'}">${ch.length}</div>
      <div class="kpi-sub">${ch.length ? (frozen ? frozen + ' داخل يوم مجمّد' : 'لا شيء داخل اليوم المجمّد') : 'الجدول معتمد'}</div></div>`;
}

// ------------------------------------------------------------------ schedule

function scheduleHTML() {
  const w = world(), ix = index(w), day = currentDay(w);
  const inResult = U.whatIf === 'result' && S.sc && S.sc.ok;
  const affected = new Set(inResult ? S.sc.affected : []);
  const dayInfo = ix.d[day];

  const tabs = w.days.map((d) => `<button type="button" role="tab" class="pill" aria-selected="${d.date === day}" data-act="day" data-date="${d.date}">
      ${d.frozen ? ICON.lock(13) : ''}<span>${h(d.label)}</span></button>`).join('');
  const dl = U.dlOpen ? `<div class="menu" role="menu">
      <a role="menuitem" class="menu-item stack" href="/api/download/schedule.csv" download data-act="dlDone"><b>الجدولة كاملة (CSV)</b><span class="muted" style="font-size:12px">كل الأيام والقاعات، تفتح في Excel</span></a>
      <a role="menuitem" class="menu-item stack" href="/print/venues" target="_blank" rel="noopener" data-act="dlDone"><b>جداول القاعات للطباعة (PDF)</b><span class="muted" style="font-size:12px">صفحة لكل قاعة تُعلَّق على بابها</span></a>
    </div>` : '';

  const head = `<div class="sched-head">
      <h2>الجدولة</h2>
      ${inResult ? '<span class="chip chip-amber" style="font-size:12px">تعرض نتيجة التجربة</span>' : ''}
      <div class="tabs" role="tablist" aria-label="الأيام">${tabs}</div>
      <div class="tools">
        <div class="seg" role="group" aria-label="طريقة العرض">
          <button type="button" aria-pressed="${U.view === 'timeline'}" data-act="view" data-view="timeline">زمني</button>
          <button type="button" aria-pressed="${U.view === 'table'}" data-act="view" data-view="table">جدول</button>
        </div>
        <div id="dl-wrap"><button type="button" class="btn btn-secondary" data-act="dl" aria-haspopup="menu" aria-expanded="${U.dlOpen}">${ICON.download()}تحميل${ICON.chevron()}</button>${dl}</div>
        <button type="button" class="btn btn-dashed" data-act="whatIf" aria-pressed="${!!U.whatIf}">${ICON.flask()}ماذا لو؟</button>
        <button type="button" class="btn btn-primary" data-act="add">${ICON.plus()}إضافة فعالية</button>
      </div>
    </div>`;

  const errors = S.data.errors.length ? `<div class="error-banner"><b>البيانات فيها مشكلة تمنع الجدولة:</b><br>${S.data.errors.map(h).join('<br>')}</div>` : '';
  const frozen = dayInfo && dayInfo.frozen ? `<div class="frozen-banner hatch">${ICON.lock(14)}<span><b>يوم مجمّد</b> (داخل نافذة التجميد): لا تُضاف فيه فعاليات جديدة، وأي تغيير على فعالية معتمدة يُعلَّم للمراجعة ويُبلَّغ صاحبها.</span></div>` : '';

  const rows = w.schedule.filter((r) => r.date === day);
  let body;
  if (U.view === 'timeline') {
    const start = toMin(w.day_start), end = toMin(w.day_end), span = end - start, hours = span / 60;
    const axis = Array.from({ length: Math.floor(hours) + 1 }, (_, i) => {
      const tr = i === 0 ? '0' : i === hours ? '100%' : '50%';
      return `<span style="right:${(100 * i) / hours}%;transform:translateX(${tr})">${fmt(start + i * 60)}</span>`;
    }).join('');
    const grid = `background-image:repeating-linear-gradient(to left, var(--grid) 0, var(--grid) 1px, transparent 1px, transparent ${100 / hours}%)`;
    const venueRows = w.venues.map((v) => {
      const down = v.status !== 'available';
      const bars = rows.filter((r) => r.venue_id === v.id).map((r) => {
        const p = ix.p[r.program_id]; if (!p) return '';
        const s0 = toMin(r.start), e0 = toMin(r.end), b0 = toMin(r.busy_until);
        const right = (100 * (s0 - start)) / span, width = (100 * (e0 - s0)) / span;
        const tailRight = right + width, tailW = Math.max(0, Math.min((100 * (b0 - e0)) / span, 100 - tailRight));
        const kind = p.time_type === 'fixed' ? 'k-fixed' : KIND_CLASS[r.status] || 'k-new';
        const sel = U.selected === p.id && ['details', 'delete'].includes(U.panel);
        const label = `${p.name}، ${r.start}–${r.end}${p.time_type === 'fixed' ? '، ثابتة' : ''}، ${TYPE_LABEL[r.status]}`;
        return `<span class="tail" aria-hidden="true" style="right:${tailRight}%;width:${tailW}%"></span>
          <button type="button" class="bar ${kind} ${width < 10 ? 'narrow' : ''} ${sel ? 'selected' : ''} ${affected.has(p.id) ? 'affected' : ''}" style="right:${right}%;width:${width}%"
            data-act="details" data-id="${h(p.id)}" aria-label="${h(label)}" title="${h(label)}">
            <span class="t1">${p.locked || p.time_type === 'fixed' ? ICON.lock(11) : ''}<span>${h(p.name)}</span></span><span class="t2">${r.start}–${r.end}</span></button>`;
      }).join('');
      return `<div class="tl-row"><div class="venue-col"><div class="vname">${h(v.name)}</div><div class="vmeta">سعة ${v.capacity} · تجهيز ${v.setup} د</div></div>
        <div class="track ${down ? 'hatch' : ''}" style="${down ? '' : grid}">${down ? `<span class="track-down">${h(v.name)} ${h(v.status_label)}</span>` : ''}${bars}</div></div>`;
    }).join('');
    body = `<div class="timeline-scroll"><div class="timeline">
      <div class="tl-row"><div class="venue-col"></div><div class="axis" aria-hidden="true">${axis}</div></div>${venueRows}</div></div>`;
  } else {
    const sorted = rows.slice().sort((a, b) => toMin(a.start) - toMin(b.start) || a.venue_id.localeCompare(b.venue_id));
    body = `<div class="table-scroll"><div class="table" role="table" aria-label="جدول الفعاليات">
      <div class="tr head" role="row"><span role="columnheader">الفعالية</span><span role="columnheader">البداية</span><span role="columnheader">النهاية</span><span role="columnheader">القاعة</span><span role="columnheader">الحضور</span><span role="columnheader">الموعد</span><span role="columnheader">الحالة</span><span role="columnheader">إجراءات</span></div>
      ${sorted.length ? sorted.map((r) => {
        const p = ix.p[r.program_id]; if (!p) return '';
        return `<div class="tr" role="row">
          <span role="cell" style="min-width:0"><button type="button" class="link-btn" data-act="details" data-id="${h(p.id)}">${h(p.name)}</button></span>
          <span role="cell" class="num">${r.start}</span><span role="cell" class="num">${r.end}</span>
          <span role="cell" class="ellipsis">${h(ix.v[r.venue_id].name)}</span><span role="cell">${p.attendance}</span>
          <span role="cell" class="muted">${p.time_type === 'fixed' ? 'ثابتة' : p.locked ? 'مقفلة' : 'مرنة'}</span>
          <span role="cell"><span class="chip ${TYPE_CHIP[r.status]}">${TYPE_LABEL[r.status]}</span></span>
          <span role="cell" style="display:flex;gap:6px">
            <button type="button" class="btn btn-secondary btn-sm" data-act="edit" data-id="${h(p.id)}">تعديل</button>
            <button type="button" class="btn btn-ghost-danger btn-sm" data-act="del" data-id="${h(p.id)}">حذف</button></span></div>`;
      }).join('') : '<div class="empty">لا فعاليات مجدولة في هذا اليوم.</div>'}
    </div></div>`;
  }

  const legend = `<div class="legend">
      <span class="item"><span class="sw k-fixed"></span>ثابتة</span>
      <span class="item"><span class="sw k-approved"></span>معتمدة</span>
      <span class="item"><span class="sw k-new"></span>جديدة</span>
      <span class="item"><span class="sw k-moved"></span>تغيّرت</span>
      <span class="item"><span class="sw sw-tail"></span>تجهيز القاعة</span>
      ${inResult ? '<span class="item"><span class="sw sw-affected"></span>متأثرة بالتجربة</span>' : ''}
      <span class="end">اضغط أي فعالية لتفاصيلها</span></div>`;
  return head + errors + frozen + body + legend;
}

// ------------------------------------------------------------------ overlays

function detailsHTML() {
  const w = world(), ix = index(w), p = ix.p[U.selected] || index(S.data).p[U.selected];
  if (!p) return '';
  const slot = ix.s[p.id], un = w.unscheduled.find((u) => u.program_id === p.id);
  const approved = S.data.approved[p.id];
  const status = slot ? slot.status : 'not_scheduled';
  const chips = [p.time_type === 'fixed' ? 'موعد ثابت' : 'موعد مرن', `${p.duration} دقيقة`, `${p.attendance} شخص`,
    p.admission === 'registration' ? 'تسجيل مسبق · عدد مؤكد' : 'حضور عام · عدد تقديري'].map((c) => `<span class="tag">${h(c)}</span>`).join('');
  const equip = 'المعدات المطلوبة: ' + (p.equipment.length ? p.equipment.map(eqLabel).join('، ') : 'لا شيء');
  let main = '', why = '', lock = '', log, notify, editLabel = 'تعديل';

  if (slot) {
    const v = ix.v[slot.venue_id], day = ix.d[slot.date];
    main = `<div class="box"><div class="k">الموعد</div><div style="font-weight:700;font-size:15px">${h(day.long)} · ${slot.start}–${slot.end}</div>
      <div style="font-size:13px;color:var(--ink-2)">${h(v.name)} · سعة ${v.capacity} · تجهيز بعدها ${v.setup} دقيقة</div><div class="k">${h(equip)}</div></div>`;
    const items = [];
    if (p.time_type === 'fixed') items.push(['info', 'موعد ثابت حدّده صاحب الفعالية: لا يحرّكه المحرك']);
    if (p.locked) items.push(['info', 'مقفلة: لا يحرّكها المحرك في أي إعادة جدولة']);
    if (status === 'unchanged' && p.time_type !== 'fixed' && !p.locked) items.push(['ok', 'باقية في موعدها المعتمد']);
    if (p.time_type === 'flexible' && p.preferred_dates.length) {
      const names = p.preferred_dates.map((d) => (ix.d[d] ? ix.d[d].label : d)).join(' أو ');
      if (slot.pref_date_met) items.push(['ok', `اليوم المفضل (${names})`]);
      else if (!approved && p.preferred_dates.every((d) => ix.d[d] && ix.d[d].frozen)) items.push(['warn', `اليوم المفضل (${names}) مجمّد، والفعاليات الجديدة لا تُضاف لأيام مجمّدة`]);
      else items.push(['warn', `اليوم المفضل (${names}) لم يتسع لها`]);
    }
    if (p.time_type === 'flexible' && p.preferred_slots.length) {
      const names = p.preferred_slots.map((s) => s.replace('-', '–')).join('، ');
      items.push(slot.pref_time_met ? ['ok', `الفترة المفضلة (${names})`] : ['warn', `الفترة المفضلة (${names}) لم تتحقق`]);
    }
    if (p.time_type === 'flexible') items.push(['ok', `تشغل ${Math.round((100 * p.attendance) / v.capacity)}% من سعة القاعة، وفيها كل المعدات`]);
    if (day.frozen) items.push(['info', 'يومها مجمّد: أي تغيير عليها يُرفع للمراجعة']);
    why = `<div><div style="font-weight:600;margin-bottom:6px">لماذا وُضعت هنا؟</div><div class="checks">${items.map(([k, t]) => checkRow(k, t)).join('')}</div></div>`;
    if (p.time_type === 'flexible' && !U.whatIf) {
      lock = `<div class="lock-row"><div style="flex:1"><div style="font-weight:700;font-size:13.5px">${p.locked ? 'الموعد مقفل' : 'الموعد غير مقفل'}</div>
        <div class="muted" style="font-size:12px">${p.locked ? 'لن يحرّكها المحرك في أي إعادة جدولة' : 'قد يحرّكها المحرك إن احتاج لجدولة غيرها'}</div></div>
        <button type="button" class="btn btn-secondary" data-act="lock" aria-pressed="${p.locked}">${ICON.lock(15)}<span>${p.locked ? 'فك القفل' : 'قفل الموعد'}</span></button></div>`;
    }
    log = status === 'new' ? 'جديدة في هذا المقترح · بانتظار الاعتماد' : status === 'moved' && approved ? 'كانت: ' + where(ix, approved) : 'في الجدول المعتمد · لم تتغير';
    notify = status === 'unchanged' ? 'لا يلزم إشعار: موعدها لم يتغير' : status === 'new' ? 'يُبلَّغ بالموعد عند الاعتماد' : 'يُبلَّغ بالتغيير وسببه عند الاعتماد';
  } else {
    main = `<div class="box danger"><div style="font-weight:700;color:var(--danger-text)">لم تُجدول</div>
      <div style="font-size:13px">${h(un ? un.reason : '')}</div><div style="font-size:12.5px;color:var(--ink-2)">الحل المقترح: ${h(un ? un.suggestion : '')}</div>
      <div class="k">${h(equip)}</div>${un && un.fix && !U.whatIf ? `<div style="margin-top:6px"><button type="button" class="btn btn-secondary btn-sm" data-act="fix" data-id="${h(p.id)}">${h(un.fix.label)}</button></div>` : ''}</div>`;
    log = approved ? 'كانت: ' + where(index(S.data), approved) : 'جديدة · لم تُجدول بعد';
    notify = 'يُبلَّغ بالسبب عند الاعتماد';
    editLabel = 'عدّل لتُجدول';
  }
  return `<div class="backdrop side" data-backdrop><aside class="drawer" role="dialog" aria-modal="true" aria-label="تفاصيل الفعالية">
    <div class="head-row"><div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:5px">
      <span class="chip ${TYPE_CHIP[status]}">${p.time_type === 'fixed' ? 'ثابتة · ' : ''}${TYPE_LABEL[status]}</span><h2>${h(p.name)}</h2></div>
      <button type="button" class="close-x" data-act="close" aria-label="إغلاق" data-autofocus>${ICON.close()}</button></div>
    <div class="chips" style="gap:6px">${chips}</div>
    ${main}${lock}${why}
    <div class="grid2"><div class="box" style="border:0"><div class="k">سجل التغيير</div><div style="font-size:13px">${h(log)}</div></div>
      <div class="box" style="border:0"><div class="k">صاحب الفعالية</div><div style="font-size:13px">${h(notify)}</div></div></div>
    <div class="drawer-actions">
      <button type="button" class="btn btn-primary btn-lg" style="flex:1" data-act="edit" data-id="${h(p.id)}">${editLabel}</button>
      <button type="button" class="btn btn-ghost-danger btn-lg" data-act="del" data-id="${h(p.id)}">حذف</button></div>
  </aside></div>`;
}

function openForm(pid) {
  const d = S.data, ix = index(d), p = pid ? ix.p[pid] : null, slot = pid ? ix.s[pid] : null;
  const firstOpen = (d.days.find((x) => !x.frozen) || d.days[0]).date;
  U.form = p ? {
    pid, name: p.name, dur: String(p.duration), att: String(p.attendance), adm: p.admission, eq: p.equipment.slice(), type: p.time_type,
    prefDays: p.preferred_dates.slice(), slot: p.preferred_slots[0] || '',
    fd: (p.fixed && p.fixed.date) || (slot && slot.date) || firstOpen, ft: (p.fixed && p.fixed.start) || (slot && slot.start) || '13:00',
    fv: (p.fixed && p.fixed.venue_id) || (slot && slot.venue_id) || d.venues[0].id,
  } : { pid: null, name: '', dur: '60', att: '50', adm: 'open', eq: ['projector', 'microphone'], type: 'flexible', prefDays: [], slot: '', fd: firstOpen, ft: '13:00', fv: d.venues[0].id };
  U.check = null; U.panel = 'form'; U.whatIf = null; S.sc = null; U.searchOpen = false; U.unschedOpen = false;
  render(true);
  queueCheck(0);
}
function formBody() {
  const f = U.form;
  return {
    name: f.name.trim(), duration: parseInt(f.dur, 10) || 0, attendance: parseInt(f.att, 10) || 0, equipment: f.eq,
    time_type: f.type, admission: f.adm, preferred_dates: f.prefDays, preferred_slot: f.slot,
    fixed_date: f.type === 'fixed' ? f.fd : null, fixed_start: f.type === 'fixed' ? f.ft : null, fixed_venue: f.type === 'fixed' ? f.fv : null,
  };
}
function clientErrors() {
  const f = U.form, out = [];
  if (!f.name.trim()) out.push('أدخل اسم الفعالية');
  if (!(parseInt(f.dur, 10) >= 15)) out.push('المدة 15 دقيقة على الأقل');
  if (!(parseInt(f.att, 10) >= 1)) out.push('أدخل عدد الحضور');
  if (f.type === 'fixed' && !/^\d{2}:\d{2}$/.test(f.ft)) out.push('أدخل وقت البداية');
  return out;
}
let checkTimer = null, checkSeq = 0;
function queueCheck(delay = 300) {
  clearTimeout(checkTimer);
  U.checking = true; renderFormLive();
  checkTimer = setTimeout(async () => {
    if (!U.form || clientErrors().length) { U.checking = false; renderFormLive(); return; }
    const seq = ++checkSeq;
    try {
      const res = await api('POST', '/api/check', { program_id: U.form.pid, program: formBody() });
      if (seq !== checkSeq || !U.form) return;
      U.check = res;
    } catch (e) {
      if (seq !== checkSeq) return;
      U.check = { ok: false, errors: [e.message], compatible: [] };
    }
    U.checking = false; renderFormLive();
  }, delay);
}
function formLiveHTML() {
  const f = U.form, ix = index(S.data), errs = clientErrors();
  let rows = '';
  if (errs.length) rows = errs.map((e) => checkRow('bad', e)).join('');
  else if (!U.check) rows = checkRow('info', 'يفحصها المحرك الآن…');
  else if (!U.check.ok) rows = U.check.errors.map((e) => checkRow('bad', e)).join('');
  else {
    const c = U.check, out = [];
    out.push(c.compatible.length ? ['ok', `${c.compatible.length === 1 ? 'قاعة واحدة تناسب' : c.compatible.length + ' قاعات تناسب'} الحضور والمعدات`] : ['warn', 'لا توجد قاعة متاحة تجمع السعة والمعدات المطلوبة']);
    if (c.placement) {
      const pl = { date: c.placement.date, start: c.placement.start, venue_id: c.placement.venue_id };
      out.push(['ok', (c.placement.same_as_before ? 'تبقى في موعدها: ' : f.type === 'fixed' ? 'الموعد صالح: ' : 'الموعد الذي يختاره المحرك: ') + where(ix, pl)]);
      if (ix.d[pl.date] && ix.d[pl.date].frozen && f.pid && S.data.approved[f.pid] && !c.placement.same_as_before) out.push(['warn', 'يوم مجمّد: يُعلَّم التغيير للمراجعة ويُبلَّغ صاحبها']);
    } else if (c.reason) out.push(['warn', 'تُحفظ بدون موعد: ' + c.reason.reason]);
    if (c.moved_approved.length) out.push(['warn', 'ستتحرك فعاليات معتمدة: ' + c.moved_approved.join('، ')]);
    if (c.lost.length) out.push(['warn', 'تخرج من الجدول: ' + c.lost.join('، ')]);
    if (c.rearranged) out.push(['info', `يعيد المحرك ترتيب ${c.rearranged} من الفعاليات الجديدة (لم يُبلَّغ أصحابها بعد)`]);
    out.push(f.adm === 'registration' ? ['info', 'تسجيل مسبق: العدد مؤكد، فلا تخضع لتنبيهات الحضور'] : ['info', 'حضور عام: العدد تقديري، وقد تصلك تنبيهات حضور من الدورات السابقة']);
    rows = out.map(([k, t]) => checkRow(k, t)).join('');
  }
  const blocked = errs.length > 0 || (U.check && !U.check.ok);
  const meta = U.checking ? '<span class="spinner sm"></span>' : U.check && U.check.solve_seconds != null ? `فحصها المحرك في ${Number(U.check.solve_seconds).toFixed(2)} ث` : '';
  return `<div class="live"><div class="live-head">فحص فوري بالمحرك قبل الحفظ<span class="muted" style="display:inline-flex;align-items:center;gap:6px">${meta}</span></div><div class="checks">${rows}</div></div>
    <div class="form-actions"><span class="muted" style="font-size:12.5px">يدخل التعديل في المقترح، ولا يُعتمد إلا بعد مراجعتك.</span>
      <button type="button" class="btn btn-secondary btn-lg first" data-act="close">إلغاء</button>
      <button type="button" class="btn btn-primary btn-lg" data-act="save" ${blocked ? 'disabled' : ''}>حفظ وإعادة الجدولة</button></div>`;
}
function renderFormLive() { const el = $('#form-live'); if (el && U.form) el.innerHTML = formLiveHTML(); }
function formHTML() {
  const f = U.form, d = S.data;
  const chip = (act, val, on, label, extra = '') => `<button type="button" class="tchip" data-act="${act}" data-val="${h(val)}" aria-pressed="${on}" ${extra}>${h(label)}</button>`;
  const slots = SLOT_PRESETS.concat(f.slot && !SLOT_PRESETS.includes(f.slot) ? [f.slot] : []);
  const title = f.pid ? `تعديل «${(index(d).p[f.pid] || {}).name || ''}»` : 'إضافة فعالية';
  return `<div class="backdrop" data-backdrop><section class="dialog" id="form-dialog" role="dialog" aria-modal="true" aria-label="${h(title)}" style="width:760px">
    <div class="head-row" style="align-items:center"><h2>${h(title)}</h2><button type="button" class="close-x" data-act="close" aria-label="إغلاق">${ICON.close()}</button></div>
    <div class="form-grid">
      <label class="field span3">اسم الفعالية<input class="input" type="text" data-input="name" value="${h(f.name)}" placeholder="مثال: ورشة التسويق الرقمي" data-autofocus></label>
      <label class="field">المدة (دقيقة)<input class="input" type="number" min="15" step="15" data-input="dur" value="${h(f.dur)}"></label>
      <label class="field">الحضور المتوقع<input class="input" type="number" min="1" data-input="att" value="${h(f.att)}"></label>
      <div class="field">نوع الحضور<div class="chips" role="group" aria-label="نوع الحضور" style="gap:6px">
        <button type="button" class="pill" data-act="fAdm" data-val="open" aria-pressed="${f.adm === 'open'}">حضور عام</button>
        <button type="button" class="pill" data-act="fAdm" data-val="registration" aria-pressed="${f.adm === 'registration'}">تسجيل مسبق</button></div></div>
      <div class="field span3">المعدات المطلوبة<div class="chips" role="group" aria-label="المعدات" style="gap:6px">
        ${d.equipment.map((e) => chip('fEq', e.id, f.eq.includes(e.id), e.label)).join('')}</div></div>
    </div>
    <div class="form-sect">
      <div class="opt-row"><span style="font-size:13px;font-weight:600;color:var(--ink)">الموعد</span>
        <button type="button" class="pill" data-act="fType" data-val="flexible" aria-pressed="${f.type === 'flexible'}">مرنة: المحرك يختار</button>
        <button type="button" class="pill" data-act="fType" data-val="fixed" aria-pressed="${f.type === 'fixed'}">ثابتة: أحدد الموعد</button></div>
      ${f.type === 'fixed' ? `
        <div class="opt-row"><span class="lbl">اليوم</span>${d.days.map((x) => chip('fDay', x.date, f.fd === x.date, x.label + (x.frozen ? ' · مجمّد' : ''))).join('')}
          <label style="display:inline-flex;align-items:center;gap:6px;margin-inline-start:10px" class="muted">البداية
            <input class="input" style="min-height:36px;padding:0 8px;border:1px solid var(--line-strong);border-radius:9px;background:var(--surface-2);color:var(--ink)" type="time" step="900" data-input="ft" value="${h(f.ft)}"></label></div>
        <div class="opt-row"><span class="lbl">القاعة</span>${d.venues.map((v) => chip('fVenue', v.id, f.fv === v.id, v.name + (v.status !== 'available' ? ' · ' + v.status_label : ''))).join('')}</div>`
      : `
        <div class="opt-row"><span class="lbl">أيام مفضّلة</span>${d.days.map((x) => chip('fPref', x.date, f.prefDays.includes(x.date), x.label + (x.frozen ? ' · مجمّد' : ''))).join('')}</div>
        <div class="opt-row"><span class="lbl">فترة مفضّلة</span>${slots.map((s) => chip('fSlot', s, f.slot === s, s ? s.replace('-', '–') : 'بدون تفضيل')).join('')}</div>`}
    </div>
    <div id="form-live" class="stack">${formLiveHTML()}</div>
  </section></div>`;
}

function deleteHTML() {
  const p = index(S.data).p[U.selected];
  if (!p) return '';
  const approved = !!S.data.approved[p.id];
  return `<div class="backdrop" data-backdrop><section class="dialog" role="alertdialog" aria-modal="true" aria-label="تأكيد الحذف" style="width:440px;gap:10px">
    <h2>حذف «${h(p.name)}»؟</h2>
    <p style="margin:0;font-size:14px;color:var(--ink-2)">${approved ? 'تُزال من الجدول المقترح، ويُبلَّغ صاحبها عند الاعتماد. الجدول المعتمد لا يتغير قبل ذلك.' : 'تُزال من الجدول المقترح. لم تُعتمد بعد، فلن يتأثر الجدول المعتمد.'}</p>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:4px">
      <button type="button" class="btn btn-secondary btn-lg" data-act="close" data-autofocus>إلغاء</button>
      <button type="button" class="btn btn-danger btn-lg" data-act="confirmDel">حذف</button></div>
  </section></div>`;
}

function reviewHTML() {
  const d = S.data, ix = index(d), ch = d.changes;
  const frozen = ch.filter((c) => c.in_freeze && ['moved', 'dropped', 'removed'].includes(c.type)).length;
  const items = ch.map((c) => {
    const p = ix.p[c.program_id], sched = ix.s[c.program_id], un = d.unscheduled.find((u) => u.program_id === c.program_id);
    const pt = (x) => (x ? where(ix, x) : '');
    let msg = '', before = '', after = '';
    if (c.type === 'new') { after = pt(c.new); msg = `جُدولت «${c.name}» يوم ${ix.d[c.new.date].long} من ${c.new.start} إلى ${sched ? sched.end : ''} في ${ix.v[c.new.venue_id].name}.`; }
    else if (c.type === 'moved') {
      before = pt(c.old); after = pt(c.new);
      msg = c.old.date === c.new.date && c.old.start === c.new.start
        ? `تغيّرت قاعة «${c.name}» إلى ${ix.v[c.new.venue_id].name} في الموعد نفسه. لا يلزمك أي إجراء.`
        : `تغيّر موعد «${c.name}» إلى ${ix.d[c.new.date].long} ${c.new.start} في ${ix.v[c.new.venue_id].name}.`;
    } else if (c.type === 'dropped') { before = pt(c.old); after = 'بلا موعد'; msg = `تعذّر إبقاء «${c.name}» في موعدها المعتمد، وسنتواصل معك لموعد بديل.`; }
    else if (c.type === 'not_scheduled') { after = 'لم تُجدول'; msg = `تعذّرت جدولة «${c.name}»: ${un ? un.reason : ''}`; }
    else if (c.type === 'removed') { before = c.old ? `${ix.d[c.old.date] ? ix.d[c.old.date].label : c.old.date} ${c.old.start}` : ''; after = 'أُزيلت'; msg = `أُزيلت «${c.name}» من الجدول لأنها لم تعد ضمن البرامج.`; }
    const freezeTag = c.in_freeze && ['moved', 'dropped', 'removed'].includes(c.type) ? '<span class="chip chip-amber">يوم مجمّد</span>' : '';
    return `<div class="review-item"><div class="review-line"><span class="chip ${TYPE_CHIP[c.type]}">${TYPE_LABEL[c.type]}</span><b>${h(c.name)}</b>
        ${before ? `<span class="strike">${h(before)}</span><span class="muted">←</span>` : ''}<span style="font-weight:600">${h(after)}</span>${freezeTag}</div>
      <div class="notice">${ICON.message()}<div><div class="muted" style="font-size:12px">معاينة الإشعار إلى ${h(c.owner || 'صاحب الفعالية')}</div><div>${h(c.message || msg)}</div></div></div></div>`;
  }).join('');
  return `<div class="backdrop" data-backdrop><section class="dialog" role="dialog" aria-modal="true" aria-label="مراجعة واعتماد" style="width:880px;gap:12px">
    <div class="head-row" style="align-items:center"><div><h2>مراجعة المقترح قبل الاعتماد</h2>
      <div class="muted" style="font-size:13px">${plural(ch.length, 'تغيير', 'تغييرات', 'تغييرًا', 'تغييران')} · ${frozen ? frozen + ' داخل يوم مجمّد · ' : ''}سيُرسل ${plural(ch.length, 'إشعار', 'إشعارات', 'إشعارًا', 'إشعاران')}</div></div>
      <button type="button" class="close-x" data-act="close" aria-label="إغلاق" data-autofocus>${ICON.close()}</button></div>
    <div class="review-list">${items || '<div class="empty">لا تغييرات.</div>'}</div>
    <div class="form-actions" style="border-top:1px solid var(--line);padding-top:12px">
      <span class="muted" style="font-size:12.5px">تُرسل الإشعارات فقط بعد الاعتماد، ويُحفظ الجدول السابق في السجل.</span>
      <button type="button" class="btn btn-secondary btn-lg first" data-act="close">رجوع</button>
      <button type="button" class="btn btn-primary btn-lg" data-act="approve" ${d.summary.can_approve && ch.length ? '' : 'disabled'}>اعتماد وإرسال الإشعارات</button></div>
  </section></div>`;
}

let lastPanelKey = '';
function renderOverlay(force) {
  const key = U.panel ? `${U.panel}:${U.selected || ''}:${U.form ? U.form.pid : ''}` : '';
  if (U.panel === 'form' && !force && $('#form-dialog') && key === lastPanelKey) return;
  const html = U.panel === 'details' ? detailsHTML() : U.panel === 'form' && U.form ? formHTML() : U.panel === 'delete' ? deleteHTML() : U.panel === 'review' ? reviewHTML() : '';
  $('#overlay').innerHTML = html;
  if (key && key !== lastPanelKey) { const el = $('#overlay [data-autofocus]'); if (el) el.focus(); }
  lastPanelKey = key;
}

// ------------------------------------------------------------------ render

function render(force) {
  if (!S.data) return;
  renderHeader();
  renderSearch();
  $('#banner').innerHTML = U.whatIf ? `<div class="banner" role="status">${ICON.flask()}<b>وضع «ماذا لو؟»</b>
      <span style="color:var(--ink-2)">تجربة على المحرك الحقيقي: لا يتغير المقترح ولا الجدول المعتمد، ولا يُبلَّغ أحد.</span>
      <button type="button" class="btn btn-secondary btn-sm" data-act="exitWhatIf">خروج من التجربة</button></div>` : '';
  $('#aside').innerHTML = asideHTML();
  $('#kpis').innerHTML = kpisHTML();
  $('#schedule').innerHTML = scheduleHTML();
  renderOverlay(force);
  renderFeedback();
}
function closePanel() { U.panel = null; U.form = null; U.check = null; render(); }

// ------------------------------------------------------------------ actions

const ACT = {
  theme() {
    U.theme = U.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = U.theme;
    try { localStorage.setItem('plantix-theme', U.theme); } catch (e) { /* storage unavailable */ }
    renderHeader();
  },
  bell() { if (S.data.unscheduled.length) { U.unschedOpen = !U.unschedOpen; render(); } else toast('لا إشعارات جديدة'); },
  searchPick(ds) {
    const slot = index(S.data).s[ds.id];
    U.searchOpen = false; U.q = ''; $('#search').value = '';
    U.selected = ds.id; U.panel = 'details'; if (slot) U.day = slot.date;
    render();
  },
  day(ds) { U.day = ds.date; render(); },
  view(ds) { U.view = ds.view; render(); },
  dl() { U.dlOpen = !U.dlOpen; render(); },
  dlDone() { U.dlOpen = false; setTimeout(render, 0); toast('بدأ التحميل'); },
  unsched() { U.unschedOpen = !U.unschedOpen; render(); },
  details(ds) { U.selected = ds.id; U.panel = 'details'; U.unschedOpen = false; render(); },
  close: closePanel,
  add() { openForm(null); },
  edit(ds) { openForm(ds.id); },
  del(ds) { U.selected = ds.id; U.panel = 'delete'; render(); },
  review() { U.panel = 'review'; render(); },
  async lock() {
    const p = index(S.data).p[U.selected];
    await mutate(p.locked ? 'يفك القفل…' : 'يقفل الموعد…', () => api('POST', `/api/programs/${encodeURIComponent(p.id)}/lock`, { locked: !p.locked }),
      (r) => (p.locked ? `فُكّ قفل «${p.name}»` : `قُفل موعد «${p.name}»: لن يحرّكه المحرك`) + secs(r.state.summary.solve_seconds));
  },
  async confirmDel() {
    const p = index(S.data).p[U.selected];
    U.panel = null;
    await mutate('يعيد الجدولة…', () => api('DELETE', `/api/programs/${encodeURIComponent(p.id)}`), (r) => `حُذفت «${p.name}» من المقترح` + secs(r.state.summary.solve_seconds));
    U.selected = null; render();
  },
  async approve() {
    U.panel = null;
    await mutate('يعتمد ويرسل الإشعارات…', () => api('POST', '/api/approve'),
      (r) => (r.sent ? `اعتُمد الجدول وأُرسل ${plural(r.sent, 'إشعار', 'إشعارات', 'إشعارًا', 'إشعاران')}` : 'اعتُمد الجدول'));
  },
  async save() {
    if (clientErrors().length) return;
    const f = U.form, body = formBody();
    try {
      await mutate('يعيد الجدولة…', () => (f.pid ? api('PUT', `/api/programs/${encodeURIComponent(f.pid)}`, body) : api('POST', '/api/programs', body)), (r) => {
        const ix = index(r.state), slot = ix.s[r.program_id];
        U.selected = r.program_id; U.panel = null; U.form = null; if (slot) U.day = slot.date;
        return (slot ? `حُفظت «${body.name}» · ${where(ix, slot)}` : `حُفظت «${body.name}» بدون موعد`) + secs(r.state.summary.solve_seconds);
      });
      render(true);
    } catch (e) {
      if (e.data && e.data.errors && U.form) { U.check = { ok: false, errors: e.data.errors, compatible: [] }; renderFormLive(); }
    }
  },
  fAdm(ds) { U.form.adm = ds.val; renderOverlay(true); queueCheck(0); },
  fType(ds) { U.form.type = ds.val; renderOverlay(true); queueCheck(0); },
  fEq(ds) { const f = U.form; f.eq = f.eq.includes(ds.val) ? f.eq.filter((x) => x !== ds.val) : f.eq.concat([ds.val]); renderOverlay(true); queueCheck(0); },
  fPref(ds) { const f = U.form; f.prefDays = f.prefDays.includes(ds.val) ? f.prefDays.filter((x) => x !== ds.val) : f.prefDays.concat([ds.val]); renderOverlay(true); queueCheck(0); },
  fSlot(ds) { U.form.slot = ds.val; renderOverlay(true); queueCheck(0); },
  fDay(ds) { U.form.fd = ds.val; renderOverlay(true); queueCheck(0); },
  fVenue(ds) { U.form.fv = ds.val; renderOverlay(true); queueCheck(0); },
  whatIf() {
    if (U.whatIf) { U.whatIf = null; S.sc = null; }
    else { U.whatIf = 'setup'; U.panel = null; if (!U.scenario.venue_id && !U.scenario.program_id) U.scenario = scenarioDefaults(U.scenario.kind); }
    U.dlOpen = false; render();
  },
  scKind(ds) { if (ds.kind !== U.scenario.kind) U.scenario = scenarioDefaults(ds.kind); U.whatIf = 'setup'; S.sc = null; render(); },
  fix(ds) {
    const u = S.data.unscheduled.find((x) => x.program_id === ds.id);
    if (!u || !u.fix) return;
    U.scenario = Object.assign(scenarioDefaults(u.fix.kind), u.fix, { value: u.fix.value != null ? String(u.fix.value) : '' });
    U.whatIf = 'setup'; S.sc = null; U.panel = null; render();
  },
  async runWhatIf() {
    const sc = U.scenario;
    const body = { kind: sc.kind, venue_id: sc.venue_id || null, program_id: sc.program_id || null, value: sc.value ? parseInt(sc.value, 10) : null, day_end: sc.day_end || null };
    U.busy = 'يجرّب السيناريو على المحرك…'; renderFeedback();
    try {
      S.sc = await api('POST', '/api/whatif', body);
      U.busy = ''; U.whatIf = 'result';
      if (S.sc.ok && S.sc.days.length !== S.data.days.length) U.day = S.sc.days[S.sc.days.length - 1].date;
      render();
      toast(S.sc.ok ? `اكتملت التجربة في ${Number(S.sc.summary.solve_seconds || 0).toFixed(2)} ث · لم يتغير شيء في المقترح` : 'التجربة لا تصلح بهذه القيم', !S.sc.ok);
    } catch (e) { U.busy = ''; renderFeedback(); toast(e.message, true); }
  },
  async applyWhatIf() {
    const sc = U.scenario;
    const body = { kind: sc.kind, venue_id: sc.venue_id || null, program_id: sc.program_id || null, value: sc.value ? parseInt(sc.value, 10) : null, day_end: sc.day_end || null };
    U.whatIf = null; S.sc = null;
    await mutate('يحوّل التجربة إلى مقترح…', () => api('POST', '/api/whatif/apply', body), 'صارت التجربة هي المقترح · راجِعها ثم اعتمدها');
  },
  exitWhatIf() { U.whatIf = null; S.sc = null; render(); },
};

document.addEventListener('click', (e) => {
  const t = e.target;
  if (t.matches('[data-backdrop]')) { closePanel(); return; }
  let changed = false;
  if (U.searchOpen && !t.closest('#search-wrap')) { U.searchOpen = false; renderSearch(); }
  if (U.dlOpen && !t.closest('#dl-wrap')) { U.dlOpen = false; changed = true; }
  if (U.unschedOpen && !t.closest('#kpi-scheduled') && !t.closest('#bell')) { U.unschedOpen = false; changed = true; }
  const el = t.closest('[data-act]');
  if (el && !el.disabled && ACT[el.dataset.act]) { ACT[el.dataset.act](el.dataset, e); return; }
  if (changed) render();
});

document.addEventListener('input', (e) => {
  const t = e.target;
  if (t.id === 'search') { U.q = t.value; U.searchOpen = true; U.searchIndex = 0; renderSearch(); return; }
  if (t.dataset.input && U.form) {
    const key = t.dataset.input;
    U.form[key === 'name' ? 'name' : key === 'dur' ? 'dur' : key === 'att' ? 'att' : 'ft'] = t.value;
    queueCheck();
    return;
  }
  if (t.dataset.sc) { U.scenario[t.dataset.sc] = t.value; if (U.whatIf === 'result') { U.whatIf = 'setup'; S.sc = null; render(); } }
});
document.addEventListener('change', (e) => {
  const t = e.target;
  if (t.dataset.sc) {
    U.scenario[t.dataset.sc] = t.value;
    if (t.dataset.sc === 'program_id') { const p = index(S.data).p[t.value]; if (p) U.scenario.value = String(p.attendance); }
    U.whatIf = 'setup'; S.sc = null; render();
  }
});
document.addEventListener('focusin', (e) => { if (e.target.id === 'search' && S.data) { U.searchOpen = true; renderSearch(); } });
document.addEventListener('keydown', (e) => {
  if (e.target.id === 'search') {
    const list = searchResults();
    if (e.key === 'ArrowDown' && list.length) { e.preventDefault(); U.searchIndex = (U.searchIndex + 1) % list.length; renderSearch(); }
    else if (e.key === 'ArrowUp' && list.length) { e.preventDefault(); U.searchIndex = (U.searchIndex - 1 + list.length) % list.length; renderSearch(); }
    else if (e.key === 'Enter' && list[U.searchIndex]) { e.preventDefault(); ACT.searchPick({ id: list[U.searchIndex].id }); }
    else if (e.key === 'Escape') { U.searchOpen = false; renderSearch(); }
    return;
  }
  if (e.key !== 'Escape') return;
  if (U.panel) closePanel();
  else if (U.dlOpen || U.unschedOpen) { U.dlOpen = false; U.unschedOpen = false; render(); }
});

// ------------------------------------------------------------------ start

(async function start() {
  renderHeader();
  $('#schedule').innerHTML = '<div class="loading">يحمّل الجدولة من المحرك…</div>';
  try {
    S.data = await api('GET', '/api/state');
    render(true);
  } catch (e) {
    $('#schedule').innerHTML = `<div class="error-banner">${h(e.message)}</div>`;
  }
})();
