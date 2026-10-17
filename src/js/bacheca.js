(() => {
  'use strict';
  const { fetchJSON, url, el } = window.OOTB;
  const $ = id => document.getElementById(id);
  const MONTHS = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre'];
  const WEEKDAYS = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'];
  const pad = n => String(n).padStart(2, '0');
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  const keyOf = (y, mo, d) => `${y}-${pad(mo + 1)}-${pad(d)}`;
  const compact = ({ y, mo, d }) => `${y}${pad(mo + 1)}${pad(d)}`;
  const nextDay = ({ y, mo, d }) => { const n = new Date(Date.UTC(y, mo, d + 1)); return { y: n.getUTCFullYear(), mo: n.getUTCMonth(), d: n.getUTCDate() }; };
  const fmtLong = new Intl.DateTimeFormat('it-IT', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
  const longDate = ({ y, mo, d }) => fmtLong.format(new Date(Date.UTC(y, mo, d)));

  // "oggi" secondo il fuso di Roma, non quello del dispositivo
  const todayRome = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Rome', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());

  function parseDate(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(typeof s === 'string' ? s.trim() : '');
    if (!m) return null;
    const y = +m[1], mo = +m[2] - 1, d = +m[3], t = new Date(Date.UTC(y, mo, d));
    return t.getUTCFullYear() === y && t.getUTCMonth() === mo && t.getUTCDate() === d ? { y, mo, d } : null;
  }

  // "all day", "HH:MM-HH:MM" oppure solo "HH:MM" (in tal caso nessuna fine inventata)
  function parseTime(raw) {
    const s = typeof raw === 'string' ? raw.trim() : '';
    if (/^all[ -]?day$/i.test(s)) return { allDay: true };
    const m = /^(\d{1,2})[:.](\d{2})(?:\s*[-–—]\s*(\d{1,2})[:.](\d{2}))?$/.exec(s);
    if (!m) return null;
    const h1 = +m[1], m1 = +m[2];
    if (h1 > 23 || m1 > 59) return null;
    if (m[3] === undefined) return { start: [h1, m1] };
    const h2 = +m[3], m2 = +m[4];
    if (h2 > 23 || m2 > 59 || h2 * 60 + m2 <= h1 * 60 + m1) return null;
    return { start: [h1, m1], end: [h2, m2] };
  }

  const hm = ([h, m]) => `${pad(h)}:${pad(m)}`;
  const timeLabel = t => t.allDay ? 'Tutto il giorno' : t.end ? `${hm(t.start)}–${hm(t.end)}` : `Dalle ${hm(t.start)}`;
  const sortKey = t => t.allDay ? -1 : t.start[0] * 60 + t.start[1];

  function normalize(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const id = (typeof raw.id === 'string' || typeof raw.id === 'number') ? String(raw.id).trim() : '';
    const d = parseDate(raw.date), t = parseTime(raw.time);
    const title = typeof raw.title === 'string' ? raw.title.trim() : '';
    if (!id || !d || !t || !title) return null;
    return { id, date: raw.date.trim(), d, t, title, description: typeof raw.description === 'string' ? raw.description.trim() : '', thumb: url(raw.thumbnail) };
  }

  // ---------- Google Calendar ----------
  function googleUrl(a) {
    const p = new URLSearchParams({ action: 'TEMPLATE', text: a.title });
    if (a.description) p.set('details', a.description);
    if (a.t.allDay) {
      p.set('dates', `${compact(a.d)}/${compact(nextDay(a.d))}`); // la data finale è esclusiva
    } else {
      const at = h => `${compact(a.d)}T${pad(h[0])}${pad(h[1])}00`;
      p.set('dates', `${at(a.t.start)}/${at(a.t.end || a.t.start)}`); // senza fine: durata zero, nessun orario inventato
      p.set('ctz', 'Europe/Rome');
    }
    return 'https://calendar.google.com/calendar/render?' + p.toString();
  }

  // ---------- ICS (RFC 5545) ----------
  const icsEscape = s => String(s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r\n|\r|\n/g, '\\n');
  const enc = new TextEncoder();
  function fold(line) { // righe max 75 ottetti UTF-8, continuazione con spazio
    if (enc.encode(line).length <= 75) return line;
    const out = []; let cur = '', len = 0;
    for (const ch of line) {
      const b = enc.encode(ch).length;
      if (len + b > 75) { out.push(cur); cur = ' '; len = 1; }
      cur += ch; len += b;
    }
    out.push(cur);
    return out.join('\r\n');
  }
  const VTIMEZONE = ['BEGIN:VTIMEZONE', 'TZID:Europe/Rome',
    'BEGIN:DAYLIGHT', 'TZOFFSETFROM:+0100', 'TZOFFSETTO:+0200', 'TZNAME:CEST', 'DTSTART:19700329T020000', 'RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU', 'END:DAYLIGHT',
    'BEGIN:STANDARD', 'TZOFFSETFROM:+0200', 'TZOFFSETTO:+0100', 'TZNAME:CET', 'DTSTART:19701025T030000', 'RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU', 'END:STANDARD',
    'END:VTIMEZONE'];

  function buildIcs(a) {
    const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
    const at = h => `${compact(a.d)}T${pad(h[0])}${pad(h[1])}00`;
    const L = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Out of the Box//ootb-lista.it//IT', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH'];
    if (!a.t.allDay) L.push(...VTIMEZONE);
    L.push('BEGIN:VEVENT', `UID:${a.id.replace(/[^\w.-]/g, '-')}-${a.date}@ootb-lista.it`, `DTSTAMP:${stamp}`, `SUMMARY:${icsEscape(a.title)}`);
    if (a.description) L.push(`DESCRIPTION:${icsEscape(a.description)}`);
    if (a.t.allDay) L.push(`DTSTART;VALUE=DATE:${compact(a.d)}`, `DTEND;VALUE=DATE:${compact(nextDay(a.d))}`);
    else { L.push(`DTSTART;TZID=Europe/Rome:${at(a.t.start)}`); if (a.t.end) L.push(`DTEND;TZID=Europe/Rome:${at(a.t.end)}`); }
    L.push('END:VEVENT', 'END:VCALENDAR');
    return L.map(fold).join('\r\n') + '\r\n';
  }

  function downloadIcs(a) {
    const href = URL.createObjectURL(new Blob([buildIcs(a)], { type: 'text/calendar;charset=utf-8' }));
    const link = el('a', { href, download: `ootb-${a.id.replace(/[^\w-]/g, '-')}.ics` });
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(href), 1500);
  }

  // ---------- stato ----------
  const todayKey = todayRome();
  const t0 = parseDate(todayKey);
  let view = { y: t0.y, mo: t0.mo }, selected = todayKey, openId = null, failed = false;
  let byDate = new Map();

  function showStatus(msg, { error = false, retry = null } = {}) {
    const s = $('cal-status');
    s.replaceChildren(el('span', { text: msg }));
    if (retry) { const b = el('button', { type: 'button', class: 'btn', text: 'Riprova' }); b.addEventListener('click', retry); s.append(b); }
    s.classList.toggle('is-error', error);
    s.hidden = false;
  }

  // ---------- calendario ----------
  function renderGrid() {
    $('cal-title').textContent = `${cap(MONTHS[view.mo])} ${view.y}`;
    const grid = $('cal-grid');
    grid.replaceChildren();
    WEEKDAYS.forEach(w => grid.append(el('div', { class: 'cal-wd', text: w, 'aria-hidden': 'true' })));
    const first = (new Date(Date.UTC(view.y, view.mo, 1)).getUTCDay() + 6) % 7; // lunedì = 0
    const n = new Date(Date.UTC(view.y, view.mo + 1, 0)).getUTCDate();
    const blank = () => el('div', { class: 'cal-blank', 'aria-hidden': 'true' });
    for (let i = 0; i < first; i++) grid.append(blank());
    for (let d = 1; d <= n; d++) {
      const k = keyOf(view.y, view.mo, d), count = (byDate.get(k) || []).length;
      grid.append(el('button', {
        type: 'button', 'data-date': k,
        class: 'day' + (k === todayKey ? ' today' : '') + (k === selected ? ' is-sel' : ''),
        'aria-pressed': String(k === selected), 'aria-current': k === todayKey ? 'date' : null,
        'aria-label': longDate({ y: view.y, mo: view.mo, d }) + (count ? `, ${count} attività` : '')
      }, el('span', { text: String(d) }), count ? el('span', { class: 'badge', 'aria-hidden': 'true', text: String(count) }) : null));
    }
    for (let i = (7 - (first + n) % 7) % 7; i > 0; i--) grid.append(blank());
  }

  function detail(a) {
    const kids = [];
    if (a.thumb) {
      const img = el('img', { src: a.thumb, alt: '', loading: 'lazy' });
      img.addEventListener('error', () => img.remove());
      kids.push(img);
    }
    kids.push(el('h4', { text: a.title }),
      el('p', { class: 'meta' }, el('span', { text: longDate(a.d) }), el('span', { class: 't', text: timeLabel(a.t) })));
    if (a.description) kids.push(el('p', { class: 'desc', text: a.description }));
    kids.push(el('div', { class: 'actions' },
      el('a', { class: 'btn', href: googleUrl(a), target: '_blank', rel: 'noopener', text: 'Google Calendar' }),
      el('button', { type: 'button', class: 'btn', 'data-ics': a.id, text: 'Apple Calendar (.ics)' })));
    return el('article', { class: 'detail', tabindex: '-1', 'aria-label': 'Dettagli: ' + a.title }, kids);
  }

  function renderPanel(focusDetail = false) {
    const p = $('day-panel');
    p.replaceChildren(el('h3', { text: cap(longDate(parseDate(selected))) }));
    const list = byDate.get(selected) || [];
    if (!list.length) {
      p.append(el('p', { class: 'muted', text: failed ? 'Le attività non sono disponibili al momento.' : 'Nessuna attività in questo giorno.' }));
      return;
    }
    const ul = el('ul', { class: 'acts' });
    list.forEach(a => ul.append(el('li', {}, el('button', { type: 'button', class: 'act', 'data-id': a.id, 'aria-expanded': String(a.id === openId) },
      el('span', { class: 'act-time', text: timeLabel(a.t) }), el('span', { text: a.title })))));
    p.append(ul);
    const open = list.find(a => a.id === openId);
    if (open) { const d = detail(open); p.append(d); if (focusDetail) d.focus(); }
  }

  function selectDate(k) {
    selected = k; openId = null;
    $('cal-grid').querySelectorAll('.day').forEach(b => { const on = b.dataset.date === k; b.classList.toggle('is-sel', on); b.setAttribute('aria-pressed', String(on)); });
    renderPanel();
  }

  function shiftMonth(delta) {
    const t = new Date(Date.UTC(view.y, view.mo + delta, 1));
    view = { y: t.getUTCFullYear(), mo: t.getUTCMonth() };
    renderGrid();
  }

  $('prev').addEventListener('click', () => shiftMonth(-1));
  $('next').addEventListener('click', () => shiftMonth(1));
  $('today').addEventListener('click', () => { view = { y: t0.y, mo: t0.mo }; renderGrid(); selectDate(todayKey); });
  $('cal-grid').addEventListener('click', e => { const b = e.target.closest('.day'); if (b) selectDate(b.dataset.date); });
  $('day-panel').addEventListener('click', e => {
    const act = e.target.closest('.act');
    if (act) { openId = openId === act.dataset.id ? null : act.dataset.id; renderPanel(!!openId); const again = $('day-panel').querySelector(`.act[data-id="${CSS.escape(act.dataset.id)}"]`); if (!openId && again) again.focus(); return; }
    const ics = e.target.closest('[data-ics]');
    if (ics) { const a = (byDate.get(selected) || []).find(x => x.id === ics.dataset.ics); if (a) downloadIcs(a); }
  });

  // ---------- dati ----------
  async function loadActivities() {
    try {
      const data = await fetchJSON('src/storage/activities.json');
      if (!Array.isArray(data)) throw new Error('src/storage/activities.json deve contenere un array.');
      const map = new Map(), ids = new Set();
      data.forEach((raw, i) => {
        const a = normalize(raw);
        if (!a || ids.has(a.id)) { console.warn(`activities.json: voce #${i} ignorata (campi non validi o id duplicato)`, raw); return; }
        ids.add(a.id);
        if (!map.has(a.date)) map.set(a.date, []);
        map.get(a.date).push(a);
      });
      map.forEach(l => l.sort((x, y) => sortKey(x.t) - sortKey(y.t)));
      byDate = map; failed = false;
      if (ids.size) $('cal-status').hidden = true; else showStatus('Nessuna attività in programma per ora.');
    } catch (err) {
      console.error(err);
      byDate = new Map(); failed = true;
      showStatus('Non riesco a caricare le attività. Controlla la connessione e riprova.', { error: true, retry: loadActivities });
    }
    renderGrid(); renderPanel();
  }

  async function loadComms() {
    const state = $('comms-state'), list = $('comms-list');
    list.replaceChildren();
    try {
      const data = await fetchJSON('src/storage/communications.json');
      if (!Array.isArray(data)) throw new Error('src/storage/communications.json deve contenere un array.');
      // Schema: { id, title, subtitle|null, author, date (YYYY-MM-DD), content, links[] }; pagina generata in docs/communications/<id>.html
      const str = v => typeof v === 'string' ? v.trim() : '';
      const items = data.map(c => {
        if (!c || typeof c !== 'object') return null;
        const d = parseDate(c.date);
        if (!/^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(str(c.id)) || !str(c.title) || !str(c.author) || !d) return null;
        return { title: str(c.title), description: str(c.subtitle), author: str(c.author), d, iso: c.date.trim(), link: url('docs/communications/' + str(c.id) + '.html') };
      }).filter(Boolean).sort((x, y) => keyOf(y.d.y, y.d.mo, y.d.d).localeCompare(keyOf(x.d.y, x.d.mo, x.d.d)));
      if (!items.length) { state.textContent = 'Nessuna comunicazione per ora.'; state.hidden = false; return; }
      state.hidden = true;
      items.forEach(c => list.append(el('article', { class: 'comm' },
        el('p', { class: 'comm-meta' }, el('span', { class: 'by', text: 'di ' + c.author }), el('time', { datetime: c.iso, text: longDate(c.d) })),
        el('h3', { text: c.title }),
        c.description ? el('p', { text: c.description }) : null,
        c.link ? el('a', { class: 'btn', href: c.link, text: 'Leggi la comunicazione' }) : null)));
    } catch (err) {
      console.error(err);
      state.replaceChildren(el('span', { text: 'Non riesco a caricare le comunicazioni.' }));
      const b = el('button', { type: 'button', class: 'btn', text: 'Riprova' }); b.addEventListener('click', loadComms);
      state.append(b); state.classList.add('is-error'); state.hidden = false;
      return;
    }
    state.classList.remove('is-error');
  }

  renderGrid(); renderPanel();
  loadActivities(); loadComms();
})();
