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
})();
