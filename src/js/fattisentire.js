(() => {
  'use strict';

  // URL /exec del deployment Web App di Google Apps Script (vedi Code.gs). Finché resta il placeholder,
  // il form NON invia nulla e lo dichiara apertamente.
  const ENDPOINT = 'https://script.google.com/macros/s/AKfycbyKHGr0xwu-v-fQ2eYXo1spnHQVz9tVbVXOiDut59MgZLSPb9-7f5UBJo2LkxA6Cn1QGg/exec';
  const TIMEOUT_MS = 20000;

  const IMPORTANCE = ['Utile - sarebbe un miglioramento', 'Importante - migliorerebbe la vita scolastica', 'Prioritaria - il problema va affrontato'];
  const CATEGORIES = ['Rientro e Pausa Pranzo', 'Benessere e Sicurezza', 'Eventi e Attività', 'Rappresentanza e Ascolto', 'Altro'];
  const LABELS = { category: 'Categoria', title: 'Titolo della proposta', problem: 'Qual è il problema?', solution: 'La tua soluzione', importance: 'Quanto è importante per te?', phone: 'Contatto' };

  const $ = id => document.getElementById(id);
  const form = $('ff'), submitBtn = $('ff-submit'), status = $('ff-status'), summary = $('ff-summary');
  let sending = false;
  let submissionId = null; // resta uguale ai tentativi ripetuti degli stessi dati: il server evita i doppioni

  const newId = () => (crypto.randomUUID ? crypto.randomUUID() : 'id-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12));

  const validators = {
    category: v => !v ? 'Scegli una categoria.' : CATEGORIES.includes(v) ? '' : 'Categoria non valida.',
    title: v => { v = v.trim(); return !v ? 'Scrivi il titolo della proposta.' : v.length > 100 ? 'Il titolo può avere al massimo 100 caratteri.' : ''; },
    problem: v => v.trim() ? (v.trim().length > 3000 ? 'Massimo 3000 caratteri.' : '') : 'Descrivi il problema.',
    solution: v => v.trim() ? (v.trim().length > 3000 ? 'Massimo 3000 caratteri.' : '') : 'Scrivi la tua soluzione.',
    importance: v => !v ? 'Scegli quanto è importante per te.' : IMPORTANCE.includes(v) ? '' : 'Scelta non valida.',
    phone: v => {
      v = v.trim();
      if (!v) return '';
      const digits = v.replace(/\D/g, '').length;
      return /^\+?[0-9 ()./-]{6,20}$/.test(v) && digits >= 6 && digits <= 15 ? '' : 'Numero non valido. Esempio: 333 1234567 oppure +39 333 1234567.';
    }
  };

  const read = () => {
    const f = new FormData(form);
    const o = {};
    for (const k in validators) o[k] = String(f.get(k) || '');
    return o;
  };

  function setError(name, msg) {
    const wrap = form.querySelector(`[data-field="${name}"]`);
    const err = $(name + '-err');
    err.textContent = msg;
    err.hidden = !msg;
    wrap.classList.toggle('has-err', !!msg);
    const ctl = name === 'importance' ? form.querySelectorAll('input[name="importance"]') : [$(name)];
    ctl.forEach(c => msg ? c.setAttribute('aria-invalid', 'true') : c.removeAttribute('aria-invalid'));
  }

  function validateAll() {
    const v = read(), errors = {};
    for (const k in validators) { const m = validators[k](v[k]); setError(k, m); if (m) errors[k] = m; }
    return { values: v, errors };
  }

  function showSummary(errors) {
    summary.replaceChildren();
    const b = document.createElement('b'); b.textContent = 'Controlla questi campi';
    const ul = document.createElement('ul');
    for (const k in errors) {
      const li = document.createElement('li'), a = document.createElement('a');
      a.href = '#' + (k === 'importance' ? 'importance-err' : k);
      a.textContent = `${LABELS[k]}: ${errors[k]}`;
      a.addEventListener('click', e => { e.preventDefault(); focusField(k); });
      li.append(a); ul.append(li);
    }
    summary.append(b, ul);
    summary.hidden = false;
    summary.focus();
  }

  function focusField(k) {
    (k === 'importance' ? form.querySelector('input[name="importance"]') : $(k)).focus();
  }

  function setStatus(kind, msg) {
    if (!msg) { status.hidden = true; status.textContent = ''; return; }
    status.className = 'ff-status is-' + kind;
    status.textContent = msg;
    status.hidden = false;
  }

  function setSending(on) {
    sending = on;
    submitBtn.disabled = on;
    submitBtn.textContent = on ? 'Invio in corso…' : 'Invia la proposta';
    form.setAttribute('aria-busy', String(on));
  }

  async function send(values) {
    if (!ENDPOINT.startsWith('https://script.google.com/') || !ENDPOINT.endsWith('/exec')) {
      return { kind: 'config' };
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    try {
      // Content-Type "text/plain" = richiesta CORS "semplice": nessun preflight, che Apps Script non gestisce.
      // NON si usa no-cors: serve poter leggere la risposta per sapere se l'invio è davvero riuscito.
      const res = await fetch(ENDPOINT, {
        method: 'POST', redirect: 'follow', credentials: 'omit', signal: ctrl.signal,
        headers: { 'Content-Type': 'text/plain;charset=utf-8' },
        body: JSON.stringify({ ...values, submissionId, website: form.elements.website.value })
      });
      let data = null;
      try { data = JSON.parse(await res.text()); } catch { /* risposta non JSON */ }
      if (data && data.ok === true) return { kind: 'ok' };
      if (data && data.ok === false) return { kind: 'rejected', errors: data.errors || {}, message: data.message || '' };
      return { kind: 'bad', status: res.status };
    } catch (err) {
      // rete assente, timeout o risposta non leggibile dal browser: l'esito è SCONOSCIUTO
      return { kind: 'unknown', aborted: err && err.name === 'AbortError' };
    } finally { clearTimeout(timer); }
  }

  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (sending) return;
    summary.hidden = true;
    setStatus();
    const { values, errors } = validateAll();
    if (Object.keys(errors).length) { showSummary(errors); return; }

    if (!submissionId) submissionId = newId();
    setSending(true);
    setStatus('pending', 'Invio in corso…');
    const r = await send(values);
    setSending(false);

    if (r.kind === 'ok') {
      setStatus();
      form.reset(); submissionId = null; $('title-count').textContent = '0/100';
      form.hidden = true;
      const ok = $('ff-ok'); ok.hidden = false; ok.focus();
      return;
    }
    // in tutti i casi di errore i dati restano nel form
    if (r.kind === 'rejected') {
      const known = {};
      for (const k in r.errors) if (validators[k]) { setError(k, String(r.errors[k])); known[k] = String(r.errors[k]); }
      if (Object.keys(known).length) showSummary(known);
      setStatus('error', r.message || 'Il server ha rifiutato la proposta. Controlla i campi e riprova.');
    } else if (r.kind === 'config') {
      setStatus('error', 'Invio non ancora attivo: manca l\'URL del servizio. La proposta non è stata inviata e i dati sono ancora qui.');
    } else if (r.kind === 'unknown') {
      setStatus('error', (r.aborted ? 'Il server non ha risposto in tempo. ' : 'Non riesco a contattare il server. ') + 'Non so se la proposta è arrivata. I dati sono ancora qui: premi di nuovo "Invia la proposta" (se era già arrivata non verrà duplicata).');
    } else {
      setStatus('error', 'Risposta del server non valida (codice ' + r.status + '). La proposta non risulta inviata: riprova tra poco.');
    }
  });

  // dati cambiati = nuova proposta: serve un nuovo identificativo, altrimenti il server la scambierebbe per un doppione
  form.addEventListener('input', e => {
    submissionId = null;
    if (e.target.id === 'title') $('title-count').textContent = e.target.value.length + '/100';
    const n = e.target.name;
    if (validators[n] && !$(n + '-err').hidden) setError(n, validators[n](read()[n]));
  });
  form.addEventListener('focusout', e => {
    const n = e.target.name;
    if (validators[n] && n !== 'importance') setError(n, validators[n](read()[n]));
  });
  $('ff-again').addEventListener('click', () => { $('ff-ok').hidden = true; form.hidden = false; setStatus(); summary.hidden = true; $('category').focus(); });
})();
