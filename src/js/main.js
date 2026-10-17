(() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // menu mobile
  const burger = document.querySelector('.burger');
  const menu = document.getElementById('menu');
  const setMenu = open => {
    burger.setAttribute('aria-expanded', open);
    burger.setAttribute('aria-label', open ? 'Chiudi il menu' : 'Apri il menu');
    menu.classList.toggle('open', open);
    document.body.style.overflow = open ? 'hidden' : '';
  };
  burger.addEventListener('click', () => setMenu(burger.getAttribute('aria-expanded') !== 'true'));
  menu.querySelectorAll('a').forEach(a => a.addEventListener('click', () => setMenu(false)));
  addEventListener('keydown', e => { if (e.key === 'Escape') setMenu(false); });

  // reveal allo scroll
  const items = document.querySelectorAll('.rv');
  if (reduce || !('IntersectionObserver' in window)) {
    items.forEach(el => el.classList.add('in'));
  } else {
    const io = new IntersectionObserver(entries => {
      entries.forEach(en => {
        if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
      });
    }, { threshold: .15 });
    items.forEach((el, i) => { el.style.transitionDelay = (i % 2) * 120 + 'ms'; io.observe(el); });
  }

  // parallax del casco col mouse
  const helmet = document.querySelector('.helmet');
  if (!reduce && helmet && matchMedia('(hover: hover)').matches) {
    addEventListener('mousemove', e => {
      helmet.style.setProperty('--mx', (e.clientX / innerWidth - .5).toFixed(3));
      helmet.style.setProperty('--my', (e.clientY / innerHeight - .5).toFixed(3));
    });
  }
  // altezza barra (per il menu mobile) e adattamento dei titoli giganti
  const bar = document.querySelector('.bar');
  const fs = el => parseFloat(getComputedStyle(el).fontSize);
  const fit = () => {
    document.documentElement.style.setProperty('--bar-h', bar.offsetHeight + 'px');
    const all = document.querySelectorAll('[data-fit],[data-fit-group]');
    all.forEach(e => e.style.fontSize = '');
    document.querySelectorAll('[data-fit]').forEach(e => {
      const r = e.clientWidth / e.scrollWidth;
      if (r < 1) e.style.fontSize = fs(e) * r * .98 + 'px';
    });
    const m = Math.min(1, ...[...document.querySelectorAll('[data-fit-group]')].map(e => e.clientWidth / e.scrollWidth));
    if (m < 1) document.querySelectorAll('[data-fit-group]').forEach(e => e.style.fontSize = fs(e) * m * .98 + 'px');
  };
  let raf;
  const refit = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(fit); };
  fit();
  addEventListener('resize', refit);
  addEventListener('orientationchange', refit);
  addEventListener('load', fit);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);
  matchMedia('(min-width: 900px)').addEventListener('change', e => { if (e.matches) setMenu(false); });

  // su touch non esiste l'hover: la riga al centro dello schermo si accende
  if (matchMedia('(hover: none)').matches && 'IntersectionObserver' in window && !reduce) {
    const ro = new IntersectionObserver(es => es.forEach(e => e.target.classList.toggle('hot', e.isIntersecting)),
      { rootMargin: '-42% 0px -42% 0px' });
    document.querySelectorAll('.row').forEach(r => ro.observe(r));
  }
  // utilità condivise dalle pagine interne (bacheca, showcase)
  // I percorsi nei JSON sono relativi alla radice del sito; <body data-root> indica dove si trova la radice.
  const root = new URL(document.body.dataset.root || './', location.href);
  window.OOTB = {
    root,
    async fetchJSON(path) {
      const r = await fetch(new URL(path, root), { cache: 'no-cache' });
      if (!r.ok) throw new Error('HTTP ' + r.status + ' su ' + path);
      return r.json();
    },
    // restituisce un URL http(s) assoluto oppure null (blocca javascript:, data:, ecc.)
    url(path) {
      if (typeof path !== 'string' || !path.trim()) return null;
      try { const u = new URL(path.trim(), root); return /^https?:$/.test(u.protocol) ? u.href : null; } catch { return null; }
    },
    // crea elementi DOM senza innerHTML: i testi passano sempre da textContent
    el(tag, attrs = {}, ...kids) {
      const n = document.createElement(tag);
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === 'text') n.textContent = v; else if (k === 'class') n.className = v; else n.setAttribute(k, v === true ? '' : v);
      }
      kids.flat().forEach(c => { if (c != null) n.append(c); });
      return n;
    }
  };
})();
