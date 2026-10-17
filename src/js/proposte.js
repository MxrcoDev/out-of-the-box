(() => {
  'use strict';
  // 26 ottobre 2026, 00:00 Europe/Rome. Il 25/10/2026 finisce l'ora legale: a quella data Roma è in CET (+01:00),
  // quindi l'istante è 2026-10-25T23:00:00Z. L'offset è scritto esplicitamente, senza dipendere dal fuso del visitatore.
  const TARGET = Date.parse('2026-10-26T00:00:00+01:00');

  const $ = id => document.getElementById(id);
  const num = { d: $('cd-d'), h: $('cd-h'), m: $('cd-m'), s: $('cd-s') };
  const lab = { d: [$('cd-dl'), 'Giorno', 'Giorni'], h: [$('cd-hl'), 'Ora', 'Ore'], m: [$('cd-ml'), 'Minuto', 'Minuti'], s: [$('cd-sl'), 'Secondo', 'Secondi'] };
  const pad = n => String(n).padStart(2, '0');
  let lastMinute = -1, timer;

  function end() {
    clearTimeout(timer);
    for (const k in num) num[k].textContent = '00';
    $('cd').hidden = true;
    $('cd-done').hidden = false;
    $('cd-sr').textContent = 'Il conto alla rovescia è finito.';
  }

  function tick() {
    const left = TARGET - Date.now();
    if (!(left > 0)) return end();
    const t = Math.floor(left / 1000);
    const v = { d: Math.floor(t / 86400), h: Math.floor(t % 86400 / 3600), m: Math.floor(t % 3600 / 60), s: t % 60 };
    for (const k in v) {
      num[k].textContent = k === 'd' ? String(v[k]).padStart(2, '0') : pad(v[k]);
      lab[k][0].textContent = lab[k][v[k] === 1 ? 1 : 2];
    }
    // l'annuncio per screen reader cambia una volta al minuto, non ogni secondo
    const minuteKey = Math.floor(t / 60);
    if (minuteKey !== lastMinute) {
      lastMinute = minuteKey;
      $('cd-sr').textContent = `Mancano ${v.d} giorni, ${v.h} ore e ${v.m} minuti.`;
    }
    timer = setTimeout(tick, 1000 - (Date.now() % 1000)); // riallineo allo scatto del secondo
  }
  tick();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { clearTimeout(timer); tick(); } });
})();
