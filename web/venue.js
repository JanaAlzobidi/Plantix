/* Plantix — venue supervisor (مشرف القاعات): venue status and problem reports. */
'use strict';

const S = { data: null, preview: null };
const U = { venue: null, kind: 'equipment', equipment: null, note: '', previewing: false };

function reportsOf(vid) { return S.data.reports.filter((r) => r.venue_id === vid && r.status !== 'resolved'); }
function brokenOf(vid) { return reportsOf(vid).filter((r) => r.kind === 'equipment').map((r) => r.equipment); }

function venueStatus(v) {
  const open = reportsOf(v.id);
  if (open.some((r) => r.kind === 'closed')) return { label: 'مغلقة', chip: 'chip-danger' };
  if (open.length) return { label: 'عطل مُبلَّغ', chip: 'chip-amber' };
  if (v.status === 'maintenance') return { label: 'تحت الصيانة', chip: '' };
  if (v.status !== 'available') return { label: v.status_label, chip: 'chip-danger' };
  return { label: 'متاحة', chip: 'chip-green' };
}

// ---------------------------------------------------------------- render
function render() {
  const d = S.data, ix = index(d);
  const counts = {};
  d.schedule.forEach((r) => { counts[r.venue_id] = (counts[r.venue_id] || 0) + 1; });
  const openReports = d.reports.filter((r) => r.status !== 'resolved');
  const available = d.venues.filter((v) => v.status === 'available' && !reportsOf(v.id).some((r) => r.kind === 'closed')).length;

  $('#kpis').innerHTML = [
    ['القاعات المتاحة', `${available} من ${d.venues.length}`, 'جاهزة لاستقبال الفعاليات', ''],
    ['بلاغات مفتوحة', openReports.length, openReports.length ? 'بانتظار الإصلاح' : 'لا أعطال حاليًا', openReports.length ? 'var(--amber-text)' : 'var(--ok)'],
    ['بانتظار اعتماد المنظم', d.reports.filter((r) => r.status === 'open').length, 'خطط بديلة جاهزة', 'var(--blue-text)'],
    ['فعاليات في القاعات', d.schedule.length, 'في الجدول المقترح', ''],
  ].map(([l, v, sub, c]) => `<div class="kpi"><div class="kpi-label">${l}</div><div class="kpi-value" style="${c ? 'color:' + c : ''}">${v}</div><div class="kpi-sub">${sub}</div></div>`).join('');

  $('#venues').innerHTML = d.venues.map((v) => {
    const st = venueStatus(v), broken = brokenOf(v.id);
    const eq = v.equipment.concat(broken.filter((b) => !v.equipment.includes(b)));
    const down = st.chip === 'chip-danger' || v.status !== 'available';
    return `<div class="vcard ${down ? 'hatch' : ''}">
      <div class="req-top"><b>${h(v.name)}</b><span class="chip ${st.chip}">${h(st.label)}</span></div>
      <div class="req-meta">سعة ${v.capacity} · تجهيز ${v.setup} د · ${counts[v.id] || 0} فعاليات</div>
      <div class="chips">${eq.map((e) => `<span class="tag ${broken.includes(e) ? 'tag-broken' : ''}">${h(eqLabel(d, e))}${broken.includes(e) ? ' · معطّل' : ''}</span>`).join('') || '<span class="muted" style="font-size:12px">لا معدات</span>'}</div>
      <div class="row-actions"><button type="button" class="btn btn-secondary btn-sm" data-act="pickVenue" data-id="${h(v.id)}">${ICON.wrench()}بلّغ عن مشكلة</button></div>
    </div>`;
  }).join('');

  const reports = d.reports.slice().reverse();
  $('#report-count').textContent = reports.length;
  $('#reports').innerHTML = reports.length ? reports.map((r) => {
    const step = (done, title, text, wait) => `<div class="g-step ${done ? '' : 'wait'}"><span class="n">${done ? svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 14) : '…'}</span><div><b>${title}</b>${text ? `<div class="req-sub">${text}</div>` : ''}</div></div>`;
    const planText = r.errors.length ? h('يحتاج قرار المنظم: ' + r.errors[0])
      : r.affected.length ? h(`تتأثر وتنتقل ${plural(r.affected.length, 'فعالية', 'فعاليات', 'فعالية', 'فعاليتان')}: ${r.affected.join('، ')}`) : 'لا تتأثر أي فعالية.';
    return `<div class="req">
      <div class="req-top"><b>${h(r.title)}</b><span class="chip ${r.status === 'resolved' ? 'chip-green' : r.status === 'approved' ? 'chip-blue' : 'chip-amber'}">${r.status === 'resolved' ? 'تم الإصلاح' : r.status === 'approved' ? 'الخطة معتمدة' : 'بانتظار المنظم'}</span></div>
      ${r.note ? `<div class="req-meta">ملاحظة: ${h(r.note)}</div>` : ''}
      <div class="g-steps">
        ${step(true, 'أُرسل البلاغ', `${h(r.time)} · وصل لفريق البرامج فورًا`)}
        ${step(true, 'جهّز المحرك خطة بديلة', planText)}
        ${step(r.status !== 'open', 'اعتماد فريق البرامج', r.status === 'open' ? 'بانتظار المراجعة' : h(r.approved_time || ''))}
        ${r.status === 'resolved' ? step(true, 'تم الإصلاح', h(r.resolved_time || '') + ' · القاعة جاهزة من جديد') : ''}
      </div>
      ${r.status !== 'resolved' ? `<div class="row-actions"><button type="button" class="btn btn-secondary btn-sm" data-act="resolve" data-id="${h(r.id)}">تم الإصلاح</button></div>` : ''}
    </div>`;
  }).join('') : '<div class="empty-note">لا بلاغات بعد. إذا تعطل جهاز أو أُغلقت قاعة، بلّغ عنها من النموذج.</div>';

  const notes = d.notifications.filter((n) => n.to === 'venue');
  $('#notif-count').textContent = notes.length;
  $('#notifs').innerHTML = notificationsHTML(notes, 'ستصلك هنا موافقة فريق البرامج على الخطط البديلة.');
  renderForm();
}

function venueEquipment() {
  const v = index(S.data).v[U.venue];
  return v ? v.equipment : [];
}
function renderForm() {
  const d = S.data, eqs = venueEquipment();
  if (U.kind === 'equipment' && !eqs.includes(U.equipment)) U.equipment = eqs[0] || null;
  const chip = (act, val, on, label) => `<button type="button" class="tchip" data-act="${act}" data-val="${h(val)}" aria-pressed="${on}">${h(label)}</button>`;
  const p = S.preview;
  let impact;
  if (!U.venue) impact = checkRow('info', 'اختر القاعة');
  else if (U.kind === 'equipment' && !U.equipment) impact = checkRow('info', 'لا معدات مسجلة في هذه القاعة؛ اختر «إغلاق القاعة».');
  else if (U.previewing || !p) impact = checkRow('info', 'يحسب المحرك أثر البلاغ…');
  else if (!p.ok) impact = p.errors.map((e) => checkRow('warn', e)).join('') + checkRow('info', 'يُرسل البلاغ، ويقرر المنظم في الفعاليات الثابتة.');
  else if (!p.affected.length) impact = checkRow('ok', 'لا تتأثر أي فعالية بهذا البلاغ');
  else impact = checkRow('warn', `تتأثر ${plural(p.affected.length, 'فعالية', 'فعاليات', 'فعالية', 'فعاليتان')}`) + p.affected.map((a) => checkRow('info', a.name + (a.moved_to ? ' ← ' + where(index(d), { date: a.moved_to[0], start: a.moved_to[1], venue_id: a.moved_to[2] }) : ' ← بلا موعد'))).join('');
  if (p && p.ok && p.rearranged) impact += checkRow('info', `ويعيد المحرك ترتيب ${p.rearranged} من الفعاليات الجديدة (لم يُبلَّغ أصحابها بعد)`);
  const ready = U.venue && (U.kind === 'closed' || U.equipment);
  $('#report-form').innerHTML = `
    <div class="card-head"><h2>بلاغ عن مشكلة</h2></div>
    <div class="opt-row" role="group" aria-label="القاعة"><span class="lbl" style="width:auto">القاعة</span></div>
    <div class="chips" style="gap:6px">${d.venues.map((v) => chip('venue', v.id, U.venue === v.id, v.name)).join('')}</div>
    <div class="opt-row"><span class="lbl" style="width:auto">نوع المشكلة</span>
      <button type="button" class="pill" data-act="kind" data-val="equipment" aria-pressed="${U.kind === 'equipment'}">عطل جهاز</button>
      <button type="button" class="pill" data-act="kind" data-val="closed" aria-pressed="${U.kind === 'closed'}">إغلاق القاعة</button></div>
    ${U.kind === 'equipment' && U.venue ? `<div class="opt-row"><span class="lbl" style="width:auto">الجهاز المتعطل</span></div>
      <div class="chips" style="gap:6px">${eqs.map((e) => chip('equip', e, U.equipment === e, eqLabel(d, e))).join('') || '<span class="muted" style="font-size:12px">لا معدات</span>'}</div>` : ''}
    <label class="field">ملاحظات<input class="input" type="text" id="note" value="${h(U.note)}" placeholder="اختياري: وش اللي صار؟"></label>
    <div class="live"><div class="live-head">الأثر على الجدول<span class="muted" style="display:inline-flex">${U.previewing ? '<span class="spinner sm"></span>' : ''}</span></div><div class="checks">${impact}</div></div>
    <button type="button" class="btn btn-primary btn-lg" data-act="send" ${ready ? '' : 'disabled'}>إرسال البلاغ لفريق البرامج</button>`;
}

let pvTimer = null, pvSeq = 0;
function queuePreview() {
  clearTimeout(pvTimer);
  if (!U.venue || (U.kind === 'equipment' && !U.equipment)) { S.preview = null; renderForm(); return; }
  U.previewing = true; renderForm();
  pvTimer = setTimeout(async () => {
    const mine = ++pvSeq;
    try { const r = await api('POST', '/api/reports/preview', { venue_id: U.venue, kind: U.kind, equipment: U.equipment }); if (mine === pvSeq) S.preview = r; }
    catch (e) { if (mine === pvSeq) S.preview = { ok: false, errors: [e.message], affected: [] }; }
    if (mine === pvSeq) { U.previewing = false; renderForm(); }
  }, 200);
}

// ---------------------------------------------------------------- actions
const ACT = {
  theme: toggleTheme,
  venue(ds) { U.venue = ds.val; U.equipment = null; renderForm(); queuePreview(); },
  pickVenue(ds) { U.venue = ds.id; U.equipment = null; renderForm(); queuePreview(); const f = $('#report-form'); if (f) f.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); },
  kind(ds) { U.kind = ds.val; renderForm(); queuePreview(); },
  equip(ds) { U.equipment = ds.val; renderForm(); queuePreview(); },
  async send() {
    busy('يرسل البلاغ ويجهّز المحرك خطة بديلة…');
    try {
      const r = await api('POST', '/api/reports', { venue_id: U.venue, kind: U.kind, equipment: U.kind === 'equipment' ? U.equipment : null, note: U.note });
      S.data = r.state; S.preview = null; U.note = ''; U.venue = null;
      render();
      const n = r.report.affected.length;
      toast(`وصل البلاغ لفريق البرامج · ${n ? 'جهّز المحرك خطة بديلة: تتأثر ' + plural(n, 'فعالية', 'فعاليات', 'فعالية', 'فعاليتان') : 'لا تتأثر أي فعالية'}`);
    } catch (e) { idle(); toast(e.message, true); }
  },
  async resolve(ds) {
    busy('يحدّث حالة القاعة…');
    try { const r = await api('POST', `/api/reports/${encodeURIComponent(ds.id)}/resolve`); S.data = r.state; render(); toast('سُجّل الإصلاح، والقاعة متاحة من جديد'); }
    catch (e) { idle(); toast(e.message, true); }
  },
};

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (el && !el.disabled && ACT[el.dataset.act]) ACT[el.dataset.act](el.dataset, e);
});
document.addEventListener('input', (e) => { if (e.target.id === 'note') U.note = e.target.value; });

(async function start() {
  paintTheme();
  try { S.data = await api('GET', '/api/state'); render(); }
  catch (e) { $('#report-form').innerHTML = `<div class="error-banner">${h(e.message)}</div>`; }
})();
