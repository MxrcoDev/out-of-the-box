(() => {
  'use strict';
  const { fetchJSON, url, el } = window.OOTB;
  const state = document.getElementById('sc-state'), grid = document.getElementById('sc-grid');
  const fmt = new Intl.DateTimeFormat('it-IT', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });

  function parseDate(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(typeof s === 'string' ? s.trim() : '');
    if (!m) return null;
    const t = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return t.getUTCFullYear() === +m[1] && t.getUTCMonth() === +m[2] - 1 && t.getUTCDate() === +m[3] ? t : null;
  }

  // Schema di src/storage/articles.json: { id, title, subtitle|null, author, date (YYYY-MM-DD), content, links[] }
  // La pagina di dettaglio è generata dal workflow in docs/articles/<id>.html
  function normalize(a) {
    if (!a || typeof a !== 'object') return null;
    const str = v => typeof v === 'string' ? v.trim() : '';
    const date = parseDate(a.date);
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(str(a.id)) || !str(a.title) || !str(a.author) || !date) return null;
    return { title: str(a.title), author: str(a.author), date, iso: a.date.trim(), description: str(a.subtitle), link: url('docs/articles/' + str(a.id) + '.html') };
  }

  function card(p) {
    return el('article', { class: 'card' },
      el('div', { class: 'card-body' },
        el('h2', { text: p.title }),
        el('p', { class: 'card-meta' }, el('span', { class: 'by', text: 'di ' + p.author }), el('time', { datetime: p.iso, text: fmt.format(p.date) })),
        p.description ? el('p', { class: 'd', text: p.description }) : null,
        p.link ? el('a', { class: 'btn', href: p.link, text: 'Leggi il progetto' }) : null));
  }

  async function load() {
    state.classList.remove('is-error'); state.textContent = 'Caricamento…'; state.hidden = false; grid.replaceChildren();
    try {
      const data = await fetchJSON('src/storage/articles.json');
      if (!Array.isArray(data)) throw new Error('src/storage/articles.json deve contenere un array.');
      const items = [];
      data.forEach((raw, i) => { const p = normalize(raw); if (p) items.push(p); else console.warn(`articles.json: voce #${i} ignorata (campi non validi)`, raw); });
      items.sort((a, b) => b.date - a.date);
      if (!items.length) { state.replaceChildren(el('p', { class: 'empty', text: 'NESSUN PROGETTO PUBBLICATO' })); state.className = ''; return; }
      state.hidden = true;
      items.forEach(p => grid.append(card(p)));
    } catch (err) {
      console.error(err);
      const b = el('button', { type: 'button', class: 'btn', text: 'Riprova' }); b.addEventListener('click', load);
      state.replaceChildren(el('span', { text: 'Non riesco a caricare i progetti. Controlla la connessione e riprova.' }), b);
      state.className = 'state is-error';
    }
  }
  load();
})();
