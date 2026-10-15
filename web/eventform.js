/* Plantix — the add-event form, shared by the event owner and the program organizer pages.
 *
 * Four sections: basic information, audience and domain, venue requirements, schedule.
 * Fields marked * are required. Each page keeps its own live check and action buttons;
 * this file only knows the fields, their validation, and the body sent to the server.
 */
'use strict';

const EF = (() => {
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const toggle = (arr, v) => (arr.includes(v) ? arr.filter((x) => x !== v) : arr.concat([v]));
  const star = '<span class="req-star" aria-hidden="true">*</span>';

  function blank(d, org) {
    return {
      pid: null, name: '', org: org || '', category: '', dur: '60', att: '', adm: '', desc: '',
      audiences: [], domains: [], eq: [], type: 'flexible',
      prefDays: [], anyDay: false, slots: [], anyTime: false,
      fd: (d.days.find((x) => !x.frozen) || d.days[0]).date, ft: '', fv: '',
    };
  }

  function fromProgram(p, slot, d) {
    return {
      pid: p.id, name: p.name, org: p.owner || '', category: p.category || '', dur: String(p.duration), att: String(p.attendance),
      adm: p.admission, desc: p.description || '', audiences: (p.audiences || []).slice(), domains: (p.fields || []).slice(),
      eq: p.equipment.slice(), type: p.time_type,
      prefDays: p.preferred_dates.slice(), anyDay: !p.preferred_dates.length,
      slots: p.preferred_slots.slice(), anyTime: !p.preferred_slots.length,
      fd: (p.fixed && p.fixed.date) || (slot && slot.date) || d.days[0].date,
      ft: (p.fixed && p.fixed.start) || (slot && slot.start) || '',
      fv: (p.fixed && p.fixed.venue_id) || (slot && slot.venue_id) || '',
    };
  }

  /** Missing or invalid required fields, in form order. */
  function errors(f) {
    const out = [];
    if (!f.name.trim()) out.push('اسم الفعالية');
    if (!f.org.trim()) out.push('الجهة المنظِّمة');
    if (!f.category) out.push('التصنيف');
    if (!(parseInt(f.dur, 10) >= 15)) out.push('المدة (15 دقيقة على الأقل)');
    if (!(parseInt(f.att, 10) >= 1)) out.push('عدد الحضور');
    if (!f.adm) out.push('نوع العدد');
    if (!f.desc.trim()) out.push('الوصف');
    if (!f.audiences.length) out.push('الجمهور المستهدف');
    if (!f.domains.length) out.push('مجال الفعالية');
    if (f.type === 'flexible') {
      if (!f.anyDay && !f.prefDays.length) out.push('التواريخ المناسبة');
      if (!f.anyTime && !f.slots.length) out.push('الفترات المناسبة');
    } else {
      if (!f.fd) out.push('تاريخ الفعالية');
      if (!/^\d{2}:\d{2}$/.test(f.ft)) out.push('وقت البداية');
      if (!f.fv) out.push('القاعة');
    }
    return out;
  }

  /** Enough to ask the engine where the event would go. */
  function checkable(f) {
    return parseInt(f.dur, 10) >= 15 && parseInt(f.att, 10) >= 1 &&
      (f.type === 'flexible' || (f.fd && /^\d{2}:\d{2}$/.test(f.ft) && f.fv));
  }

  function body(f) {
    const fixed = f.type === 'fixed';
    return {
      name: f.name.trim() || 'فعالية بلا اسم', owner: f.org.trim(), category: f.category, description: f.desc.trim(),
      duration: parseInt(f.dur, 10) || 0, attendance: parseInt(f.att, 10) || 0, admission: f.adm || 'open',
      audience: f.audiences, field: f.domains, equipment: f.eq, time_type: f.type,
      preferred_dates: fixed || f.anyDay ? [] : f.prefDays, preferred_slots: fixed || f.anyTime ? [] : f.slots, preferred_slot: '',
      fixed_date: fixed ? f.fd : null, fixed_start: fixed ? f.ft : null, fixed_venue: fixed ? f.fv : null,
    };
  }

  /** Engine messages name the new event by its id; the owner never sees ids. */
  function cleanError(msg) { return String(msg).replace(/^البرنامج P\d+: /, '').replace(/P\d+ \(([^)]*)\)/g, '«$1»'); }

  const chip = (act, val, on, label, dis) => `<button type="button" class="tchip" data-act="${act}" data-val="${esc(val)}" aria-pressed="${on}" ${dis ? 'disabled' : ''}>${esc(label)}</button>`;
  const pill = (act, val, on, label) => `<button type="button" class="pill" data-act="${act}" data-val="${esc(val)}" aria-pressed="${on}">${label}</button>`;
  const sect = (n, title, hint, inner) => `<section class="ef-sect" aria-label="${esc(title)}">
      <div class="ef-head"><span class="ef-num">${n}</span><h3>${esc(title)}</h3>${hint ? `<span class="muted">${esc(hint)}</span>` : ''}</div>${inner}</section>`;

  /**
   * opts.mode: 'owner' (organization fixed to the signed-in party; frozen days closed)
   *            'organizer' (organization editable; frozen days allowed)
   */
  function html(f, d, opts) {
    const o = d.options || {}, owner = opts.mode === 'owner';
    const learned = new Set([...(o.learned_domains || []), ...(o.learned_audiences || [])]);
    const slotOpts = (o.time_slots || []).concat(f.slots.filter((s) => !(o.time_slots || []).includes(s)));
    const venues = d.venues.filter((v) => v.status === 'available');
    const confirmed = f.adm === 'registration';

    const basic = `<div class="form-grid">
        <label class="field span2"><span class="ef-flabel">اسم الفعالية ${star}</span><input class="input" type="text" data-input="name" value="${esc(f.name)}" placeholder="مثال: ورشة الذكاء الاصطناعي" data-autofocus></label>
        <label class="field"><span class="ef-flabel">الجهة المنظِّمة ${star}</span>${owner
          ? `<input class="input" type="text" value="${esc(f.org)}" readonly aria-readonly="true" title="تُعبّأ تلقائيًا باسم جهتك">`
          : `<input class="input" type="text" data-input="org" value="${esc(f.org)}" list="ef-owners" placeholder="مثال: إدارة المعرض"><datalist id="ef-owners">${(d.owners || []).map((x) => `<option value="${esc(x)}">`).join('')}</datalist>`}</label>
        <label class="field"><span class="ef-flabel">التصنيف ${star}</span><select class="input" data-input="category"><option value="">اختر التصنيف</option>
          ${(o.categories || []).map((c) => `<option value="${esc(c)}" ${c === f.category ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label>
        <label class="field"><span class="ef-flabel">المدة (دقيقة) ${star}</span><input class="input" type="number" min="15" step="15" data-input="dur" value="${esc(f.dur)}"></label>
        <label class="field"><span class="ef-flabel">${confirmed ? 'العدد المؤكد' : 'العدد المتوقع'} ${star}</span><input class="input" type="number" min="1" data-input="att" value="${esc(f.att)}" placeholder="مثال: 80"></label>
        <div class="field span3"><span class="ef-flabel">نوع العدد ${star}</span><div class="chips" role="group" aria-label="نوع العدد" style="gap:6px">
          ${pill('efAdm', 'open', f.adm === 'open', 'تقديري <span class="pill-sub">حضور عام</span>')}
          ${pill('efAdm', 'registration', f.adm === 'registration', 'مؤكد <span class="pill-sub">تسجيل مسبق</span>')}
          <span class="muted ef-note">${f.adm === 'open' ? 'العدد التقديري يراجعه نموذج توقع الحضور من الدورات السابقة.' : f.adm === 'registration' ? 'العدد المؤكد لا يتنبأ له النموذج.' : ''}</span></div></div>
        <label class="field span3"><span class="ef-flabel">الوصف ${star}</span><textarea class="input textarea" rows="2" data-input="desc" placeholder="أهداف الفعالية وما سيستفيده الحضور">${esc(f.desc)}</textarea></label>
      </div>`;

    const audience = `<div class="ef-group"><div class="ef-label">الجمهور المستهدف ${star}<span class="muted">يمكن اختيار أكثر من فئة</span></div>
        <div class="chips" role="group" aria-label="الجمهور المستهدف" style="gap:6px">${(o.audiences || []).map((a) => chip('efAud', a, f.audiences.includes(a), a)).join('')}</div></div>
      <div class="ef-group"><div class="ef-label">مجال الفعالية ${star}<span class="muted">يمكن اختيار أكثر من مجال</span></div>
        <div class="chips" role="group" aria-label="مجال الفعالية" style="gap:6px">${(o.domains || []).map((x) => chip('efDom', x, f.domains.includes(x), x)).join('')}</div></div>
      ${f.domains.length && f.audiences.length && f.adm === 'open' && !f.domains.some((x) => learned.has(x)) ? '<div class="muted ef-note">لا توجد بيانات سابقة لهذا المجال بعد، فلن يتنبأ النموذج بحضورها.</div>' : ''}`;

    const equipment = `<div class="ef-group"><div class="ef-label">المعدات المطلوبة<span class="muted">اختياري</span></div>
        <div class="chips" role="group" aria-label="المعدات المطلوبة" style="gap:6px">${d.equipment.map((e) => chip('efEq', e.id, f.eq.includes(e.id), e.label)).join('')}</div></div>`;

    const dayChip = (act, x, on) => chip(act, x.date, on, x.label + (x.frozen ? ' · مجمّد' : ''), owner && x.frozen);
    const schedule = `<div class="chips" role="group" aria-label="نوع الجدولة" style="gap:6px">
        ${pill('efType', 'flexible', f.type === 'flexible', 'مرن <span class="pill-sub">يختار فريق المعرض الموعد والقاعة</span>')}
        ${pill('efType', 'fixed', f.type === 'fixed', 'موعد محدد <span class="pill-sub">أحدد التاريخ والوقت والقاعة</span>')}</div>
      ${f.type === 'flexible' ? `
        <div class="opt-row"><span class="lbl">التواريخ المناسبة ${star}</span>${d.days.map((x) => dayChip('efDay', x, !f.anyDay && f.prefDays.includes(x.date))).join('')}${chip('efAnyDay', '1', f.anyDay, 'أي يوم')}</div>
        <div class="opt-row"><span class="lbl">الفترات المناسبة ${star}</span>${slotOpts.map((s) => chip('efSlot', s, !f.anyTime && f.slots.includes(s), s.replace('-', '–'))).join('')}${chip('efAnyTime', '1', f.anyTime, 'أي وقت')}</div>
        ${owner && d.days.some((x) => x.frozen) ? '<div class="muted ef-note">الأيام المجمّدة قريبة جدًا من موعدها، فلا تُضاف إليها فعاليات جديدة.</div>' : ''}`
      : `
        <div class="opt-row"><span class="lbl">تاريخ الفعالية ${star}</span>${d.days.map((x) => dayChip('efFixDay', x, f.fd === x.date)).join('')}</div>
        <div class="opt-row"><span class="lbl">وقت البداية ${star}</span><input class="input ef-time" type="time" step="900" data-input="ft" value="${esc(f.ft)}" aria-label="وقت البداية"></div>
        <div class="opt-row"><span class="lbl">القاعة ${star}</span>${venues.map((v) => chip('efVenue', v.id, f.fv === v.id, `${v.name} · ${v.capacity}`)).join('')}</div>
        <div class="muted ef-note">اختيار القاعة لا يعني تأكيد الحجز؛ يُتحقق من توفرها أثناء المراجعة.</div>`}`;

    return `<div class="muted ef-legend">الحقول التي عليها ${star} إلزامية.</div>
      ${sect(1, 'المعلومات الأساسية', '', basic)}
      ${sect(2, 'الجمهور والمجال', '', audience)}
      ${sect(3, 'متطلبات القاعة', '', equipment)}
      ${sect(4, 'الجدولة', '', schedule)}`;
  }

  /** Handles a form click. Returns true when the form changed and should be redrawn. */
  function act(name, ds, f) {
    switch (name) {
      case 'efAdm': f.adm = ds.val; return true;
      case 'efAud': f.audiences = toggle(f.audiences, ds.val); return true;
      case 'efDom': f.domains = toggle(f.domains, ds.val); return true;
      case 'efEq': f.eq = toggle(f.eq, ds.val); return true;
      case 'efType': f.type = ds.val; return true;
      case 'efDay': f.anyDay = false; f.prefDays = toggle(f.prefDays, ds.val); return true;
      case 'efAnyDay': f.anyDay = !f.anyDay; if (f.anyDay) f.prefDays = []; return true;
      case 'efSlot': f.anyTime = false; f.slots = toggle(f.slots, ds.val); return true;
      case 'efAnyTime': f.anyTime = !f.anyTime; if (f.anyTime) f.slots = []; return true;
      case 'efFixDay': f.fd = ds.val; return true;
      case 'efVenue': f.fv = ds.val; return true;
      default: return false;
    }
  }

  /** Handles typing. Returns true when the change matters to the engine check. */
  const INPUTS = { name: 'name', org: 'org', category: 'category', dur: 'dur', att: 'att', desc: 'desc', ft: 'ft' };
  function input(key, value, f) {
    if (!(key in INPUTS)) return null;
    f[INPUTS[key]] = value;
    return key;
  }

  /** "أكمل: …" line for the footer. */
  function missingLine(f) {
    const e = errors(f);
    return e.length ? `أكمل الحقول الإلزامية: ${e.join('، ')}` : 'كل الحقول الإلزامية مكتملة';
  }

  return { blank, fromProgram, errors, checkable, body, cleanError, html, act, input, missingLine, esc };
})();
