/* Plantix — event owner (صاحب الفعالية): my requests, their status, and new requests.
 *
 * A new request does not enter the schedule. It waits in the organizer's inbox,
 * and only an accepted request becomes an event the engine schedules.
 */
'use strict';

const S = { data: null };
const U = { org: store('plantix-owner') || '', filter: 'all', panel: null, form: null, check: null, checking: false, withdraw: null };

function same(a, b) { return a && b && a.date === b.date && a.start === b.start && a.venue_id === b.venue_id; }

function statusOf(ix, p) {
  const d = S.data, a = d.approved[p.id], s = ix.s[p.id];
  const un = d.unscheduled.find((u) => u.program_id === p.id);
  const notified = d.notified.includes(p.id);
  if (a && s && same(a, s)) return { key: 'scheduled', label: 'مجدولة', chip: 'chip-green', line: where(ix, a) };
  if (a && s) return { key: 'pending', label: 'تغيير قيد المراجعة', chip: 'chip-amber', line: 'موعدك المعتمد: ' + where(ix, a), sub: 'قد يتغير موعدها، وسيصلك إشعار بالتفاصيل عند الاعتماد.' };
  if (a) return { key: 'attention', label: 'تحتاج موعدًا بديلًا', chip: 'chip-danger', line: 'موعدك المعتمد: ' + where(ix, a), sub: 'يراجع فريق البرامج موعدًا بديلًا، وسيتواصل معك.' };
  if (notified && un) return { key: 'attention', label: 'لم تُجدول', chip: 'chip-danger', line: un.reason, sub: 'الحل المقترح: ' + un.suggestion };
  return { key: 'pending', label: 'قُبلت · بانتظار اعتماد الجدول', chip: 'chip-blue', line: 'قبلها فريق البرامج وأدخلها في الجدولة، وسيصلك موعدها عند اعتماد الجدول.' };
}

function requestStatus(r) {
  if (r.status === 'pending') return { key: 'pending', label: 'بانتظار قبول فريق البرامج', chip: 'chip-amber', line: `أُرسل الساعة ${r.time}. لا يدخل الجدولة قبل أن يقبله فريق البرامج.` };
  return { key: 'attention', label: 'اعتذر فريق البرامج', chip: 'chip-danger', line: r.note ? 'السبب: ' + r.note : 'لم يُذكر سبب.', sub: 'يمكنك تعديل الطلب وإرساله من جديد.' };
}

/** My events and my requests that have not become events (pending or declined). */
function myItems() {
  const d = S.data, ix = index(d);
  const events = d.programs.filter((p) => p.owner === U.org).map((p) => ({ kind: 'event', id: p.id, p, st: statusOf(ix, p) }));
  const reqs = (d.requests || []).filter((r) => r.owner === U.org && r.status !== 'accepted')
    .map((r) => ({ kind: 'request', id: r.id, r, p: r.program, st: requestStatus(r) }));
  return reqs.concat(events);
}

// ---------------------------------------------------------------- render
function render() {
  const d = S.data, list = myItems();
  const count = (k) => list.filter((x) => x.st.key === k).length;

  $('#org').innerHTML = d.owners.map((o) => `<option value="${h(o)}" ${o === U.org ? 'selected' : ''}>${h(o)}</option>`).join('');

  $('#kpis').innerHTML = [
    ['طلباتي', list.length, 'كل الطلبات والفعاليات باسمك', ''],
    ['مجدولة', count('scheduled'), 'في الجدول المعتمد', 'var(--ok)'],
    ['قيد المراجعة', count('pending'), 'بانتظار قبول الطلب أو اعتماد الجدول', 'var(--blue-text)'],
    ['تحتاج انتباهك', count('attention'), 'معتذر عنها، أو لم تُجدول، أو تحتاج موعدًا بديلًا', count('attention') ? 'var(--danger-text)' : 'var(--ok)'],
  ].map(([l, v, sub, c]) => `<div class="kpi"><div class="kpi-label">${l}</div><div class="kpi-value" style="${c ? 'color:' + c : ''}">${v}</div><div class="kpi-sub">${sub}</div></div>`).join('');

  const filters = [['all', 'الكل', list.length], ['scheduled', 'مجدولة', count('scheduled')], ['pending', 'قيد المراجعة', count('pending')], ['attention', 'تحتاج انتباهك', count('attention')]];
  $('#filters').innerHTML = filters.map(([k, l, n]) => `<button type="button" aria-pressed="${U.filter === k}" data-act="filter" data-k="${k}">${l} (${n})</button>`).join('');

  const shown = list.filter((x) => U.filter === 'all' || x.st.key === U.filter);
  $('#list').innerHTML = shown.length ? shown.map((x) => itemHTML(x)).join('')
    : `<div class="empty-note">${U.filter === 'all' ? 'لا توجد طلبات باسم هذه الجهة بعد. ابدأ بـ«طلب فعالية جديدة».' : 'لا توجد طلبات بهذه الحالة.'}</div>`;

  const notes = d.notifications.filter((n) => n.to === 'owner' && n.owner === U.org);
  $('#notif-count').textContent = notes.length;
  $('#notifs').innerHTML = notificationsHTML(notes, 'لا إشعارات بعد. يصلك هنا قبول طلباتك ومواعيد فعالياتك وأي تغيير عليها.');
  renderOverlay();
}

function itemHTML({ kind, id, p, r, st }) {
  const d = S.data;
  const meta = [p.category, `${p.duration} دقيقة`, `${p.attendance} ${p.admission === 'registration' ? 'مؤكد' : 'متوقع'}`,
    p.time_type === 'fixed' ? 'موعد محدد' : 'مرن'].filter(Boolean).join(' · ');
  const tags = [...(p.audiences || []), ...(p.fields || [])];
  const canWithdraw = kind === 'request' ? r.status === 'pending' : !d.approved[p.id];
  const actions = [];
  if (canWithdraw) actions.push(`<button type="button" class="btn btn-ghost-danger btn-sm" data-act="withdraw" data-kind="${kind}" data-id="${h(id)}">سحب الطلب</button>`);
  if (kind === 'request' && r.status === 'rejected') actions.push(`<button type="button" class="btn btn-secondary btn-sm" data-act="resend" data-id="${h(id)}">عدّل وأعد الإرسال</button>`);
  return `<div class="req">
      <div class="req-top"><b>${h(p.name)}</b><span class="chip ${st.chip}">${st.label}</span></div>
      <div class="req-meta">${h(meta)}${p.equipment.length ? ' · ' + h(p.equipment.map((e) => eqLabel(d, e)).join('، ')) : ''}</div>
      ${tags.length ? `<div class="chips" style="gap:4px">${tags.map((t) => `<span class="tag">${h(t)}</span>`).join('')}</div>` : ''}
      <div class="req-line">${h(st.line)}</div>
      ${st.sub ? `<div class="req-sub">${h(st.sub)}</div>` : ''}
      ${p.forecast && p.forecast.applied ? `<div class="req-sub">عدّل فريق البرامج الحضور المتوقع من ${p.forecast.original} إلى ${p.forecast.predicted} بناءً على الدورات السابقة، لتُجهَّز قاعة تتسع.</div>` : ''}
      ${actions.length ? `<div class="row-actions">${actions.join('')}</div>` : ''}
    </div>`;
}

// ---------------------------------------------------------------- new request form
function openForm(fromRequest) {
  U.form = fromRequest ? Object.assign(EF.fromProgram(fromRequest.program, null, S.data), { pid: null, org: U.org }) : EF.blank(S.data, U.org);
  if (fromRequest && fromRequest.program.time_type === 'fixed' && S.data.days.find((x) => x.date === U.form.fd && x.frozen)) U.form.fd = '';
  U.check = null; U.panel = 'form';
  renderOverlay(true); queueCheck(0);
}
let checkTimer = null, seq = 0;
function queueCheck(delay = 300) {
  clearTimeout(checkTimer); U.checking = true; renderLive();
  checkTimer = setTimeout(async () => {
    if (!U.form || !EF.checkable(U.form)) { U.check = null; U.checking = false; renderLive(); return; }
    const mySeq = ++seq;
    try { const r = await api('POST', '/api/check', { program_id: null, program: EF.body(U.form) }); if (mySeq === seq) U.check = r; }
    catch (e) { if (mySeq === seq) U.check = { ok: false, errors: [e.message], compatible: [] }; }
    if (mySeq === seq) { U.checking = false; renderLive(); }
  }, delay);
}
function liveRows() {
  const f = U.form, c = U.check;
  if (!EF.checkable(f)) return [['info', f.type === 'fixed' ? 'أدخل المدة والعدد والتاريخ والوقت والقاعة ليتحقق المحرك من توفرها' : 'أدخل المدة وعدد الحضور ليتحقق المحرك من وجود مكان مناسب']];
  if (!c) return [['info', 'يتحقق المحرك من طلبك…']];
  if (!c.ok) return c.errors.map((e) => ['bad', EF.cleanError(e)]);
  const out = [];
  out.push(c.compatible.length ? ['ok', `${c.compatible.length === 1 ? 'قاعة واحدة تناسب' : c.compatible.length + ' قاعات تناسب'} العدد والمعدات`] : ['warn', 'لا توجد قاعة متاحة تجمع السعة والمعدات المطلوبة']);
  if (c.placement) out.push(['ok', f.type === 'fixed' ? 'التاريخ والوقت والقاعة متاحة حاليًا' : 'يوجد موعد مناسب حاليًا ضمن اختياراتك']);
  else out.push(['warn', 'قد يتعذر جدولتها: ' + (c.reason ? c.reason.reason : 'لا يوجد وقت متاح')]);
  const fc = c.forecast;
  if (f.adm === 'open' && fc && fc.status === 'ok' && fc.increase_pct >= 15) out.push(['warn', `تشير الدورات السابقة إلى حضور أكبر من تقديرك (نحو ${fc.predicted} شخصًا)؛ قد يعدّله فريق البرامج، أو اختر «مؤكد» مع التسجيل المسبق`]);
  else if (f.adm === 'open' && fc && fc.status === 'ok') out.push(['ok', 'تقديرك للحضور قريب مما تشير إليه الدورات السابقة']);
  return out;
}
function liveHTML() {
  const f = U.form, missing = EF.errors(f);
  const blocked = missing.length > 0 || (U.check && !U.check.ok) || U.checking;
  const meta = U.checking ? '<span class="spinner sm"></span>' : '';
  return `<div class="live"><div class="live-head">فحص فوري قبل الإرسال<span class="muted" style="display:inline-flex">${meta}</span></div>
      <div class="checks">${liveRows().map(([k, t]) => checkRow(k, t)).join('')}${missing.length ? checkRow('warn', EF.missingLine(f)) : ''}</div></div>
    <div class="form-actions"><span class="muted" style="font-size:12.5px">يصل الطلب لفريق البرامج ليقبله أو يعتذر عنه، ولا يدخل الجدولة قبل قبوله.</span>
      <button type="button" class="btn btn-secondary btn-lg first" data-act="close">إلغاء</button>
      <button type="button" class="btn btn-primary btn-lg" data-act="submit" ${blocked ? 'disabled' : ''}>إرسال الطلب لفريق البرامج</button></div>`;
}
function renderLive() { const el = $('#form-live'); if (el && U.form) el.innerHTML = liveHTML(); }
function formHTML() {
  return `<div class="backdrop" data-backdrop><section class="dialog" id="form-dialog" role="dialog" aria-modal="true" aria-label="طلب فعالية جديدة" style="width:780px">
    <div class="head-row" style="align-items:center"><div><h2>طلب فعالية جديدة</h2><div class="muted" style="font-size:12.5px">باسم: ${h(U.org)}</div></div>
      <button type="button" class="close-x" data-act="close" aria-label="إغلاق">${ICON.close()}</button></div>
    ${EF.html(U.form, S.data, { mode: 'owner' })}
    <div id="form-live" class="stack">${liveHTML()}</div>
  </section></div>`;
}
function withdrawHTML() {
  const w = U.withdraw, item = myItems().find((x) => x.id === w.id && x.kind === w.kind);
  if (!item) return '';
  const text = item.kind === 'request' ? 'يُلغى الطلب قبل أن يراجعه فريق البرامج.' : 'تُزال من الجدولة ويُبلَّغ فريق البرامج. لم تُعتمد بعد، فلن يتأثر الجدول المعتمد.';
  return `<div class="backdrop" data-backdrop><section class="dialog" role="alertdialog" aria-modal="true" aria-label="سحب الطلب" style="width:440px;gap:10px">
    <h2>سحب «${h(item.p.name)}»؟</h2>
    <p style="margin:0;font-size:14px;color:var(--ink-2)">${text}</p>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:4px">
      <button type="button" class="btn btn-secondary btn-lg" data-act="close" data-autofocus>تراجع</button>
      <button type="button" class="btn btn-danger btn-lg" data-act="confirmWithdraw">سحب الطلب</button></div></section></div>`;
}
let lastKey = '';
function renderOverlay(force) {
  const key = U.panel ? U.panel + (U.withdraw ? U.withdraw.id : '') : '';
  if (U.panel === 'form' && !force && $('#form-dialog')) return;
  const old = $('#form-dialog'), scroll = old ? old.scrollTop : 0;
  $('#overlay').innerHTML = U.panel === 'form' ? formHTML() : U.panel === 'withdraw' ? withdrawHTML() : '';
  const dlg = $('#form-dialog');
  if (dlg && key === lastKey) dlg.scrollTop = scroll;
  if (key && key !== lastKey) { const el = $('#overlay [data-autofocus]'); if (el) el.focus(); }
  lastKey = key;
}
function closePanel() { U.panel = null; U.form = null; U.withdraw = null; renderOverlay(true); }

// ---------------------------------------------------------------- actions
const ACT = {
  theme: toggleTheme,
  filter(ds) { U.filter = ds.k; render(); },
  new() { openForm(null); },
  resend(ds) { const r = S.data.requests.find((x) => x.id === ds.id); if (r) openForm(r); },
  close: closePanel,
  async submit() {
    if (EF.errors(U.form).length) return;
    const b = EF.body(U.form);
    busy('يرسل الطلب لفريق البرامج…');
    try {
      const r = await api('POST', '/api/requests', b);
      S.data = r.state; U.panel = null; U.form = null; U.filter = 'all';
      render(); renderOverlay(true);
      toast(`وصل طلب «${b.name}» لفريق البرامج، وسيصلك إشعار بقبوله`);
    } catch (e) {
      idle(); toast(e.message, true);
      if (e.data && e.data.errors && U.form) { U.check = { ok: false, errors: e.data.errors, compatible: [] }; renderLive(); }
    }
  },
  withdraw(ds) { U.withdraw = { id: ds.id, kind: ds.kind }; U.panel = 'withdraw'; renderOverlay(true); },
  async confirmWithdraw() {
    const w = U.withdraw, item = myItems().find((x) => x.id === w.id && x.kind === w.kind);
    U.panel = null; U.withdraw = null; renderOverlay(true);
    if (!item) return;
    busy('يسحب الطلب…');
    const url = item.kind === 'request' ? `/api/requests/${encodeURIComponent(item.id)}` : `/api/programs/${encodeURIComponent(item.id)}`;
    try { const r = await api('DELETE', url); S.data = r.state; render(); toast(`سُحب طلب «${item.p.name}»`); }
    catch (e) { idle(); toast(e.message, true); }
  },
};

document.addEventListener('click', (e) => {
  if (e.target.matches('[data-backdrop]')) { closePanel(); return; }
  const el = e.target.closest('[data-act]');
  if (!el || el.disabled) return;
  if (ACT[el.dataset.act]) { ACT[el.dataset.act](el.dataset, e); return; }
  if (U.form && EF.act(el.dataset.act, el.dataset, U.form)) { renderOverlay(true); queueCheck(0); }
});
document.addEventListener('input', (e) => {
  const t = e.target;
  if (!t.dataset.input || !U.form) return;
  const key = EF.input(t.dataset.input, t.value, U.form);
  if (key === 'category') { renderLive(); return; }
  if (key) queueCheck();
});
document.addEventListener('change', (e) => {
  if (e.target.id === 'org') { U.org = e.target.value; store('plantix-owner', U.org); U.filter = 'all'; render(); }
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && U.panel) closePanel(); });

(async function start() {
  paintTheme();
  try {
    S.data = await api('GET', '/api/state');
    if (!S.data.owners.includes(U.org)) U.org = S.data.owners[0] || '';
    render();
  } catch (e) { $('#list').innerHTML = `<div class="error-banner">${h(e.message)}</div>`; }
})();
