/* Plantix — event owner (صاحب الفعالية): my requests, their status, and new requests. */
'use strict';

const S = { data: null };
const U = { org: store('plantix-owner') || '', filter: 'all', panel: null, form: null, check: null, checking: false, withdraw: null };
const SLOTS = ['', '09:00-12:00', '12:00-15:00', '15:00-18:00'];

function same(a, b) { return a && b && a.date === b.date && a.start === b.start && a.venue_id === b.venue_id; }

function statusOf(ix, p) {
  const d = S.data, a = d.approved[p.id], s = ix.s[p.id];
  const un = d.unscheduled.find((u) => u.program_id === p.id);
  const notified = d.notified.includes(p.id);
  if (a && s && same(a, s)) return { key: 'scheduled', label: 'مجدولة', chip: 'chip-green', line: where(ix, a) };
  if (a && s) return { key: 'pending', label: 'تغيير قيد المراجعة', chip: 'chip-amber', line: 'موعدك المعتمد: ' + where(ix, a), sub: 'قد يتغير موعدها، وسيصلك إشعار بالتفاصيل عند الاعتماد.' };
  if (a) return { key: 'attention', label: 'تحتاج موعدًا بديلًا', chip: 'chip-danger', line: 'موعدك المعتمد: ' + where(ix, a), sub: 'يراجع فريق البرامج موعدًا بديلًا، وسيتواصل معك.' };
  if (s) return { key: 'pending', label: 'قيد المراجعة', chip: 'chip-blue', line: 'وصل طلبك لفريق البرامج، وسيصلك الموعد عند الاعتماد.' };
  if (notified && un) return { key: 'attention', label: 'لم تُجدول', chip: 'chip-danger', line: un.reason, sub: 'الحل المقترح: ' + un.suggestion };
  return { key: 'pending', label: 'قيد المراجعة', chip: 'chip-blue', line: 'وصل طلبك لفريق البرامج، وسيصلك الرد عند الاعتماد.' };
}

function mine() { return S.data.programs.filter((p) => p.owner === U.org); }

// ---------------------------------------------------------------- render
function render() {
  const d = S.data, ix = index(d), list = mine().map((p) => ({ p, st: statusOf(ix, p) }));
  const count = (k) => list.filter((x) => x.st.key === k).length;

  $('#org').innerHTML = d.owners.map((o) => `<option value="${h(o)}" ${o === U.org ? 'selected' : ''}>${h(o)}</option>`).join('');

  $('#kpis').innerHTML = [
    ['طلباتي', list.length, 'كل الفعاليات المسجلة باسمك', ''],
    ['مجدولة', count('scheduled'), 'في الجدول المعتمد', 'var(--ok)'],
    ['قيد المراجعة', count('pending'), 'بانتظار اعتماد فريق البرامج', 'var(--blue-text)'],
    ['تحتاج انتباهك', count('attention'), 'لم تُجدول أو تحتاج موعدًا بديلًا', count('attention') ? 'var(--danger-text)' : 'var(--ok)'],
  ].map(([l, v, sub, c]) => `<div class="kpi"><div class="kpi-label">${l}</div><div class="kpi-value" style="${c ? 'color:' + c : ''}">${v}</div><div class="kpi-sub">${sub}</div></div>`).join('');

  const filters = [['all', 'الكل', list.length], ['scheduled', 'مجدولة', count('scheduled')], ['pending', 'قيد المراجعة', count('pending')], ['attention', 'تحتاج انتباهك', count('attention')]];
  $('#filters').innerHTML = filters.map(([k, l, n]) => `<button type="button" aria-pressed="${U.filter === k}" data-act="filter" data-k="${k}">${l} (${n})</button>`).join('');

  const shown = list.filter((x) => U.filter === 'all' || x.st.key === U.filter);
  $('#list').innerHTML = shown.length ? shown.map(({ p, st }) => {
    const meta = [`${p.duration} دقيقة`, `${p.attendance} شخص`, p.admission === 'registration' ? 'تسجيل مسبق' : 'حضور عام', p.time_type === 'fixed' ? 'موعد ثابت' : 'موعد مرن'].join(' · ');
    const canWithdraw = !d.approved[p.id];
    return `<div class="req">
      <div class="req-top"><b>${h(p.name)}</b><span class="chip ${st.chip}">${st.label}</span></div>
      <div class="req-meta">${h(meta)}${p.equipment.length ? ' · ' + h(p.equipment.map((e) => eqLabel(d, e)).join('، ')) : ''}</div>
      <div class="req-line">${h(st.line)}</div>
      ${st.sub ? `<div class="req-sub">${h(st.sub)}</div>` : ''}
      ${p.forecast && p.forecast.applied ? `<div class="req-sub">عدّل فريق البرامج الحضور المتوقع من ${p.forecast.original} إلى ${p.forecast.predicted} بناءً على الدورات السابقة، لتُجهَّز قاعة تتسع.</div>` : ''}
      ${canWithdraw ? `<div class="row-actions"><button type="button" class="btn btn-ghost-danger btn-sm" data-act="withdraw" data-id="${h(p.id)}">سحب الطلب</button></div>` : ''}
    </div>`;
  }).join('') : `<div class="empty-note">${U.filter === 'all' ? 'لا توجد طلبات باسم هذه الجهة بعد. ابدأ بـ«طلب فعالية جديدة».' : 'لا توجد طلبات بهذه الحالة.'}</div>`;

  const notes = d.notifications.filter((n) => n.to === 'owner' && n.owner === U.org);
  $('#notif-count').textContent = notes.length;
  $('#notifs').innerHTML = notificationsHTML(notes, 'لا إشعارات بعد. ستصلك هنا مواعيد فعالياتك وأي تغيير عليها بعد اعتماد فريق البرامج.');
  renderOverlay();
}

// ---------------------------------------------------------------- new request form
function openForm() {
  U.form = { name: '', dur: '60', att: '30', adm: 'open', eq: ['projector'], prefDays: [], slot: '', field: '', audience: '' };
  U.check = null; U.panel = 'form';
  renderOverlay(true); queueCheck(0);
}
function body() {
  const f = U.form;
  return { name: f.name.trim(), duration: parseInt(f.dur, 10) || 0, attendance: parseInt(f.att, 10) || 0, equipment: f.eq,
    time_type: 'flexible', admission: f.adm, preferred_dates: f.prefDays, preferred_slot: f.slot, owner: U.org,
    field: f.field, audience: f.audience };
}
function clientErrors() {
  const f = U.form, out = [];
  if (!f.name.trim()) out.push('أدخل اسم الفعالية');
  if (!(parseInt(f.dur, 10) >= 15)) out.push('المدة 15 دقيقة على الأقل');
  if (!(parseInt(f.att, 10) >= 1)) out.push('أدخل عدد الحضور المتوقع');
  return out;
}
let checkTimer = null, seq = 0;
function queueCheck(delay = 300) {
  clearTimeout(checkTimer); U.checking = true; renderLive();
  checkTimer = setTimeout(async () => {
    if (!U.form || clientErrors().length) { U.checking = false; renderLive(); return; }
    const mySeq = ++seq;
    try { const r = await api('POST', '/api/check', { program_id: null, program: body() }); if (mySeq === seq) U.check = r; }
    catch (e) { if (mySeq === seq) U.check = { ok: false, errors: [e.message], compatible: [] }; }
    if (mySeq === seq) { U.checking = false; renderLive(); }
  }, delay);
}
function liveHTML() {
  const errs = clientErrors(), f = U.form;
  let rows;
  if (errs.length) rows = errs.map((e) => checkRow('bad', e)).join('');
  else if (!U.check) rows = checkRow('info', 'يتحقق المحرك من طلبك…');
  else if (!U.check.ok) rows = U.check.errors.map((e) => checkRow('bad', e)).join('');
  else {
    const c = U.check, out = [];
    out.push(c.compatible.length ? ['ok', `${c.compatible.length === 1 ? 'قاعة واحدة تناسب' : c.compatible.length + ' قاعات تناسب'} الحضور والمعدات`] : ['warn', 'لا توجد قاعة متاحة تجمع السعة والمعدات المطلوبة']);
    out.push(c.placement ? ['ok', 'يوجد موعد متاح، وسيقترحه المحرك على فريق البرامج'] : ['warn', 'قد لا يُجدول: ' + (c.reason ? c.reason.reason : 'لا يوجد وقت متاح')]);
    const fc = c.forecast;
    if (f.adm === 'registration' || (fc && fc.status === 'registration')) out.push(['info', 'تسجيل مسبق: العدد مؤكد']);
    else if (fc && fc.status === 'ok' && fc.increase_pct >= 15) out.push(['warn', `تشير الدورات السابقة إلى حضور أكبر من تقديرك (نحو ${fc.predicted} شخصًا)؛ قد يعدّله فريق البرامج، أو اختر التسجيل المسبق لضبط العدد`]);
    else if (fc && fc.status === 'ok') out.push(['ok', 'تقديرك للحضور قريب مما تشير إليه الدورات السابقة']);
    else out.push(['info', 'حضور عام: العدد تقديري، وقد يراجعه فريق البرامج حسب الدورات السابقة']);
    rows = out.map(([k, t]) => checkRow(k, t)).join('');
  }
  const blocked = errs.length > 0 || (U.check && !U.check.ok);
  const meta = U.checking ? '<span class="spinner sm"></span>' : '';
  return `<div class="live"><div class="live-head">فحص فوري قبل الإرسال<span class="muted" style="display:inline-flex">${meta}</span></div><div class="checks">${rows}</div></div>
    <div class="form-actions"><span class="muted" style="font-size:12.5px">التفضيلات ليست إلزامية: يحاول المحرك تحقيقها دون أن يُسقط فعالية أخرى.</span>
      <button type="button" class="btn btn-secondary btn-lg first" data-act="close">إلغاء</button>
      <button type="button" class="btn btn-primary btn-lg" data-act="submit" ${blocked ? 'disabled' : ''}>إرسال الطلب لفريق البرامج</button></div>`;
}
function renderLive() { const el = $('#form-live'); if (el && U.form) el.innerHTML = liveHTML(); }
function sel(key, label, value, options) {
  return `<label class="field">${label}<select class="input" data-input="${key}"><option value="">غير محدد</option>${options.map((o) => `<option value="${h(o)}" ${o === value ? 'selected' : ''}>${h(o)}</option>`).join('')}</select></label>`;
}
function formHTML() {
  const d = S.data, f = U.form;
  const chip = (act, val, on, label, dis) => `<button type="button" class="tchip" data-act="${act}" data-val="${h(val)}" aria-pressed="${on}" ${dis ? 'disabled' : ''}>${h(label)}</button>`;
  return `<div class="backdrop" data-backdrop><section class="dialog" id="form-dialog" role="dialog" aria-modal="true" aria-label="طلب فعالية جديدة" style="width:740px">
    <div class="head-row" style="align-items:center"><div><h2>طلب فعالية جديدة</h2><div class="muted" style="font-size:12.5px">باسم: ${h(U.org)}</div></div>
      <button type="button" class="close-x" data-act="close" aria-label="إغلاق">${ICON.close()}</button></div>
    <div class="form-grid">
      <label class="field span3">اسم الفعالية<input class="input" type="text" data-input="name" value="${h(f.name)}" placeholder="مثال: ورشة الواقع المعزّز" data-autofocus></label>
      <label class="field">المدة (دقيقة)<input class="input" type="number" min="15" step="15" data-input="dur" value="${h(f.dur)}"></label>
      <label class="field">الحضور المتوقع<input class="input" type="number" min="1" data-input="att" value="${h(f.att)}"></label>
      <div class="field">نوع الحضور<div class="chips" style="gap:6px">
        <button type="button" class="pill" data-act="adm" data-val="open" aria-pressed="${f.adm === 'open'}">حضور عام</button>
        <button type="button" class="pill" data-act="adm" data-val="registration" aria-pressed="${f.adm === 'registration'}">تسجيل مسبق</button></div></div>
      ${sel('field', 'المجال', f.field, (d.forecast && d.forecast.fields) || [])}
      ${sel('audience', 'الفئة المستهدفة', f.audience, (d.forecast && d.forecast.audiences) || [])}
      <div class="field muted" style="font-size:12px;font-weight:400;justify-content:end">يساعدان فريق البرامج على توقع الحضور من الدورات السابقة.</div>
      <div class="field span3">المعدات المطلوبة<div class="chips" style="gap:6px">${d.equipment.map((e) => chip('eq', e.id, f.eq.includes(e.id), e.label)).join('')}</div></div>
    </div>
    <div class="form-sect">
      <div class="opt-row"><span class="lbl">اليوم المفضّل</span>${d.days.map((x) => chip('day', x.date, f.prefDays.includes(x.date), x.label + (x.frozen ? ' · مجمّد' : ''), x.frozen)).join('')}
        <span class="muted" style="font-size:12px">(اختياري)</span></div>
      ${d.days.some((x) => x.frozen) ? '<div class="muted" style="font-size:12px">الأيام المجمّدة قريبة جدًا من موعدها، فلا تُضاف إليها فعاليات جديدة.</div>' : ''}
      <div class="opt-row"><span class="lbl">الفترة المفضّلة</span>${SLOTS.map((s) => chip('slot', s, f.slot === s, s ? s.replace('-', '–') : 'بدون')).join('')}</div>
    </div>
    <div id="form-live" class="stack">${liveHTML()}</div>
  </section></div>`;
}
function withdrawHTML() {
  const p = index(S.data).p[U.withdraw];
  if (!p) return '';
  return `<div class="backdrop" data-backdrop><section class="dialog" role="alertdialog" aria-modal="true" aria-label="سحب الطلب" style="width:440px;gap:10px">
    <h2>سحب «${h(p.name)}»؟</h2>
    <p style="margin:0;font-size:14px;color:var(--ink-2)">يُلغى الطلب ويُبلَّغ فريق البرامج. لم يُعتمد بعد، فلن يتأثر الجدول المعتمد.</p>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:4px">
      <button type="button" class="btn btn-secondary btn-lg" data-act="close" data-autofocus>تراجع</button>
      <button type="button" class="btn btn-danger btn-lg" data-act="confirmWithdraw">سحب الطلب</button></div></section></div>`;
}
let lastKey = '';
function renderOverlay(force) {
  const key = U.panel ? U.panel + (U.withdraw || '') : '';
  if (U.panel === 'form' && !force && $('#form-dialog')) return;
  $('#overlay').innerHTML = U.panel === 'form' ? formHTML() : U.panel === 'withdraw' ? withdrawHTML() : '';
  if (key && key !== lastKey) { const el = $('#overlay [data-autofocus]'); if (el) el.focus(); }
  lastKey = key;
}
function closePanel() { U.panel = null; U.form = null; U.withdraw = null; renderOverlay(true); }

// ---------------------------------------------------------------- actions
const toggle = (arr, v) => (arr.includes(v) ? arr.filter((x) => x !== v) : arr.concat([v]));
const ACT = {
  theme: toggleTheme,
  filter(ds) { U.filter = ds.k; render(); },
  new: openForm,
  close: closePanel,
  adm(ds) { U.form.adm = ds.val; renderOverlay(true); queueCheck(0); },
  eq(ds) { U.form.eq = toggle(U.form.eq, ds.val); renderOverlay(true); queueCheck(0); },
  day(ds) { U.form.prefDays = toggle(U.form.prefDays, ds.val); renderOverlay(true); queueCheck(0); },
  slot(ds) { U.form.slot = ds.val; renderOverlay(true); queueCheck(0); },
  async submit() {
    if (clientErrors().length) return;
    const b = body();
    busy('يرسل الطلب لفريق البرامج…');
    try {
      const r = await api('POST', '/api/programs', b);
      S.data = r.state; U.panel = null; U.form = null; U.filter = 'all';
      render(); renderOverlay(true);
      toast(`وصل طلب «${b.name}» لفريق البرامج، وسيصلك إشعار فور اعتماده`);
    } catch (e) {
      idle(); toast(e.message, true);
      if (e.data && e.data.errors && U.form) { U.check = { ok: false, errors: e.data.errors, compatible: [] }; renderLive(); }
    }
  },
  withdraw(ds) { U.withdraw = ds.id; U.panel = 'withdraw'; renderOverlay(true); },
  async confirmWithdraw() {
    const p = index(S.data).p[U.withdraw];
    U.panel = null; renderOverlay(true);
    busy('يسحب الطلب…');
    try { const r = await api('DELETE', `/api/programs/${encodeURIComponent(p.id)}`); S.data = r.state; render(); toast(`سُحب طلب «${p.name}»`); }
    catch (e) { idle(); toast(e.message, true); }
  },
};

document.addEventListener('click', (e) => {
  if (e.target.matches("[data-backdrop]")) { closePanel(); return; }
  const el = e.target.closest('[data-act]');
  if (el && !el.disabled && ACT[el.dataset.act]) ACT[el.dataset.act](el.dataset, e);
});
document.addEventListener('input', (e) => {
  const t = e.target;
  if (t.dataset.input && U.form) { U.form[t.dataset.input] = t.value; queueCheck(); }
});
document.addEventListener('change', (e) => {
  if (e.target.id === 'org') { U.org = e.target.value; store('plantix-owner', U.org); U.filter = 'all'; render(); }
});
document.addEventListener('keydown', (e) => { if (e.key === "Escape" && U.panel) closePanel(); });

(async function start() {
  paintTheme();
  try {
    S.data = await api('GET', '/api/state');
    if (!S.data.owners.includes(U.org)) U.org = S.data.owners[0] || '';
    render();
  } catch (e) { $('#list').innerHTML = `<div class="error-banner">${h(e.message)}</div>`; }
})();
