#!/usr/bin/env node
/**
 * Genera le pagine HTML di articoli e comunicazioni.
 *
 *   src/storage/articles.json        + docs/markdown/<file>.md  ->  docs/articles/<id>.html
 *   src/storage/communications.json  + docs/markdown/<file>.md  ->  docs/communications/<id>.html
 *
 * Uso:   node build-pages.mjs [--force] [--dry-run]
 *   --force    rigenera anche le pagine che esistono già (di default vengono saltate)
 *   --dry-run  controlla tutto e dice cosa farebbe, senza scrivere file
 *
 * Variabile d'ambiente SITE_ROOT: cartella radice del sito (default: due livelli sopra questo file).
 * Exit code 1 se un JSON, un markdown o un link non sono validi (in tal caso NON viene scritto nulla).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Marked } from 'marked';

const args = new Set(process.argv.slice(2));
const FORCE = args.has('--force');
const DRY = args.has('--dry-run');

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(process.env.SITE_ROOT || path.join(HERE, '..', '..'));
const MD_DIR = path.join(ROOT, 'docs', 'markdown');
const FILES_DIR = path.join(ROOT, 'docs', 'files');

// Dominio letto dal file CNAME (serve per og:url / og:image)
const BASE = (() => {
  try {
    const host = fs.readFileSync(path.join(ROOT, 'CNAME'), 'utf8').trim();
    return host ? `https://${host}` : '';
  } catch { return ''; }
})();

/** Le due "collezioni": ognuna ha il suo JSON, la sua cartella di output e il suo CSS. */
const KINDS = [
  {
    name: 'articles',
    json: 'src/storage/articles.json',
    outDir: 'docs/articles',
    css: 'articles.css',
    nav: 'showcase.html',
    backHref: '../../src/html/showcase.html',
    backLabel: 'Torna allo Showcase',
    section: 'Showcase',
  },
  {
    name: 'communications',
    json: 'src/storage/communications.json',
    outDir: 'docs/communications',
    css: 'communications.css',
    nav: 'bacheca.html',
    backHref: '../../src/html/bacheca.html',
    backLabel: 'Torna alla Bacheca',
    section: 'Bacheca studenti',
  },
];

// Pagine temporaneamente nascoste: tolte dal menu, e il pulsante "indietro" porta alla home. Svuota il Set per riattivarle.
const HIDDEN = new Set(['fattisentire.html', 'bacheca.html', 'showcase.html']);

const NAV = [
  ['../../index.html', 'Home', null],
  ['../../src/html/proposte.html', 'Proposte', 'proposte.html'],
  ['../../src/html/fattisentire.html', 'Fatti sentire', 'fattisentire.html'],
  ['../../src/html/bacheca.html', 'Bacheca studenti', 'bacheca.html'],
  ['../../src/html/showcase.html', 'Showcase', 'showcase.html'],
];

// ---------- utilità ----------
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const isStr = v => typeof v === 'string' && v.trim() !== '';
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;
const SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;
const rel = p => path.relative(ROOT, p).split(path.sep).join('/');

function validDate(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(typeof s === 'string' ? s.trim() : '');
  if (!m) return null;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3] ? d : null;
}
const fmtDate = new Intl.DateTimeFormat('it-IT', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });

/** Risolve `name` dentro `dir` impedendo di uscirne (../ e percorsi assoluti). */
function safeJoin(dir, name) {
  const full = path.resolve(dir, name);
  return full === dir || !full.startsWith(dir + path.sep) ? null : full;
}

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`;
}

// ---------- markdown ----------
// Nel markdown i percorsi relativi (immagini, link) sono scritti a partire dalla RADICE del sito,
// es. ![foto](src/img/foto.png) oppure [pagina](src/html/proposte.html). Qui diventano relativi alla pagina generata.
function fixUrl(href) {
  if (!href) return href;
  if (/^\s*(javascript|data|vbscript):/i.test(href)) return '#';
  if (SCHEME_RE.test(href) || href.startsWith('//') || href.startsWith('#') || href.startsWith('/')) return href;
  return '../../' + href.replace(/^\.?\//, '');
}

const marked = new Marked({ gfm: true, breaks: false });
marked.use({
  renderer: {
    // Il titolo della pagina è l'unico <h1>: i titoli del markdown scalano di un livello (# -> h2, ## -> h3 ...)
    heading({ tokens, depth }) {
      const lvl = Math.min(depth + 1, 6);
      return `<h${lvl}>${this.parser.parseInline(tokens)}</h${lvl}>\n`;
    },
    link({ href, title, tokens }) {
      const url = fixUrl(href);
      const external = /^https?:\/\//i.test(url);
      return `<a href="${esc(url)}"${title ? ` title="${esc(title)}"` : ''}${external ? ' target="_blank" rel="noopener"' : ''}>${this.parser.parseInline(tokens)}</a>`;
    },
    image({ href, title, text }) {
      return `<img src="${esc(fixUrl(href))}" alt="${esc(text)}" loading="lazy">`;
    },
    // Un paragrafo che contiene solo un'immagine diventa <figure>; il titolo markdown ("...") è la didascalia.
    paragraph({ tokens }) {
      const only = tokens.length === 1 && tokens[0].type === 'image' ? tokens[0] : null;
      if (!only) return `<p>${this.parser.parseInline(tokens)}</p>\n`;
      return `<figure>${this.image(only)}${only.title ? `<figcaption>${esc(only.title)}</figcaption>` : ''}</figure>\n`;
    },
  },
});

// ---------- validazione ----------
function resolveMarkdown(content) {
  let name = content.trim().replace(/\\/g, '/');
  if (/^https?:\/\//i.test(name)) return { error: 'deve essere un file in docs/markdown, non un URL esterno' };
  name = name.replace(/^\.?\//, '').replace(/^docs\/markdown\//, '');
  if (!/\.md$/i.test(name)) return { error: 'deve terminare con .md' };
  const full = safeJoin(MD_DIR, name);
  if (!full) return { error: 'percorso non valido (deve restare dentro docs/markdown)' };
  if (!fs.existsSync(full) || !fs.statSync(full).isFile()) return { error: `file non trovato: docs/markdown/${name}` };
  return { full };
}

function resolveLink(link) {
  const type = link.type, uri = typeof link.uri === 'string' ? link.uri.trim() : '';
  if (type !== 'redirect' && type !== 'download') return { error: `type deve essere "redirect" o "download" (trovato: ${JSON.stringify(type)})` };
  if (!uri) return { error: 'uri mancante' };
  const label = isStr(link.label) ? link.label.trim() : null; // opzionale

  if (type === 'download') {
    let name = uri.replace(/\\/g, '/').replace(/^\.?\//, '').replace(/^docs\/files\//, '');
    const full = safeJoin(FILES_DIR, name);
    if (!full) return { error: `download "${uri}": percorso non valido (il file deve stare in docs/files)` };
    if (!fs.existsSync(full) || !fs.statSync(full).isFile()) return { error: `download "${uri}": file non trovato in docs/files/${name}` };
    const ext = path.extname(name).slice(1).toUpperCase();
    return { type, label: label || path.basename(name), info: [ext, humanSize(fs.statSync(full).size)].filter(Boolean).join(' · '),
      href: '../files/' + name.split('/').map(encodeURIComponent).join('/'), download: path.basename(name) };
  }

  // redirect: URL http(s) assoluto, oppure pagina/file interno del sito (percorso dalla radice)
  if (SCHEME_RE.test(uri)) {
    let u; try { u = new URL(uri); } catch { return { error: `redirect "${uri}": URL non valido` }; }
    if (!/^https?:$/.test(u.protocol)) return { error: `redirect "${uri}": sono ammessi solo http(s)` };
    return { type, label: label || u.hostname.replace(/^www\./, ''), href: u.href, external: true };
  }
  const clean = uri.replace(/^\.?\//, '').split(/[?#]/)[0];
  const full = safeJoin(ROOT, clean);
  if (!full || !fs.existsSync(full)) return { error: `redirect "${uri}": pagina interna non trovata` };
  return { type, label: label || uri, href: '../../' + uri.replace(/^\.?\//, '') };
}

function readCollection(kind, errors) {
  const file = path.join(ROOT, kind.json);
  let raw;
  try { raw = fs.readFileSync(file, 'utf8').replace(/^﻿/, ''); } catch { errors.push(`${kind.json}: file non trovato`); return []; }
  if (!raw.trim()) return [];
  let data;
  try { data = JSON.parse(raw); } catch (e) { errors.push(`${kind.json}: JSON non valido (${e.message})`); return []; }
  if (!Array.isArray(data)) { errors.push(`${kind.json}: deve contenere un array [ ... ]`); return []; }

  const seen = new Set(), items = [];
  data.forEach((e, i) => {
    const where = `${kind.json} #${i + 1}${e && typeof e.id === 'string' ? ` ("${e.id}")` : ''}`;
    const err = m => errors.push(`${where}: ${m}`);
    if (!e || typeof e !== 'object' || Array.isArray(e)) return err('la voce deve essere un oggetto');
    let ok = true;
    const bad = m => { err(m); ok = false; };

    if (!isStr(e.id)) bad('campo obbligatorio "id" mancante');
    else if (!ID_RE.test(e.id.trim())) bad('"id" può contenere solo lettere, numeri, "-" e "_" (è il nome del file .html)');
    else if (seen.has(e.id.trim())) bad(`"id" duplicato: "${e.id.trim()}"`);
    if (!isStr(e.title)) bad('campo obbligatorio "title" mancante');
    if (e.subtitle != null && typeof e.subtitle !== 'string') bad('"subtitle" deve essere una stringa oppure null');
    if (!isStr(e.author)) bad('campo obbligatorio "author" mancante');
    const date = validDate(e.date);
    if (!isStr(e.date)) bad('campo obbligatorio "date" mancante');
    else if (!date) bad(`"date" deve essere una data valida nel formato AAAA-MM-GG (trovato: "${e.date}")`);

    let md = null;
    if (!isStr(e.content)) bad('campo obbligatorio "content" mancante (file .md in docs/markdown)');
    else { const r = resolveMarkdown(e.content); if (r.error) bad(`"content" ${r.error}`); else md = r.full; }

    const links = [];
    if (e.links != null) {
      if (!Array.isArray(e.links)) bad('"links" deve essere un array');
      else e.links.forEach((l, j) => {
        if (!l || typeof l !== 'object') return bad(`links[${j}] deve essere un oggetto { type, uri }`);
        const r = resolveLink(l);
        if (r.error) bad(`links[${j}] ${r.error}`); else links.push(r);
      });
    }
    if (isStr(e.id)) seen.add(e.id.trim());
    if (ok) items.push({ id: e.id.trim(), title: e.title.trim(), subtitle: isStr(e.subtitle) ? e.subtitle.trim() : null, author: e.author.trim(), iso: e.date.trim(), date, md, links });
  });
  return items;
}

// ---------- template ----------
function renderLinks(links) {
  const redirects = links.filter(l => l.type === 'redirect'), downloads = links.filter(l => l.type === 'download');
  const box = (cls, title, list, item) => list.length
    ? `\n    <aside class="downloads ${cls}" aria-label="${esc(title)}">\n      <h2>${esc(title)}</h2>\n      <ul>\n${list.map(item).join('\n')}\n      </ul>\n    </aside>` : '';
  return box('links-redirect', 'Link', redirects, l =>
      `        <li><a class="btn" href="${esc(l.href)}"${l.external ? ' target="_blank" rel="noopener"' : ''}>${esc(l.label)} <span aria-hidden="true">&rarr;</span></a></li>`)
    + box('links-download', 'Download', downloads, l =>
      `        <li><a class="btn" href="${esc(l.href)}" download="${esc(l.download)}">${esc(l.label)}</a>${l.info ? ` <span class="file-info">${esc(l.info)}</span>` : ''}</li>`);
}

function renderPage(kind, it, bodyHtml) {
  const desc = it.subtitle || it.title;
  const url = BASE ? `${BASE}/${kind.outDir}/${it.id}.html` : '';
  const img = BASE ? `${BASE}/src/img/thumbnail.png` : '';
  const nav = NAV.filter(([, , key]) => !HIDDEN.has(key)).map(([href, label, key]) => `    <a href="${href}"${key === kind.nav ? ' aria-current="page"' : ''}>${label}</a>`).join('\n');
  return `<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>${esc(it.title)} | OUT OF THE BOX</title>
<meta name="description" content="${esc(desc)}">
<meta name="author" content="${esc(it.author)}">
<meta name="theme-color" content="#D92D25">
<meta property="og:type" content="article">
<meta property="og:title" content="${esc(it.title)} | OUT OF THE BOX">
<meta property="og:description" content="${esc(desc)}">${url ? `\n<meta property="og:url" content="${esc(url)}">` : ''}${img ? `\n<meta property="og:image" content="${esc(img)}">` : ''}
<meta property="article:published_time" content="${esc(it.iso)}">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Teko:wght@500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../../src/css/style.css">
<link rel="stylesheet" href="../../src/css/${kind.css}">
<script src="../../src/js/main.js" defer></script>
<link rel="icon" type="image/png" href="../../src/img/icon.png">
</head>
<body data-root="../../">
<!-- File generato automaticamente da .github/scripts/build-pages.mjs a partire da ${kind.json}: non modificarlo a mano. -->
<div class="grain" aria-hidden="true"></div>
<a class="skip" href="#main">Vai al contenuto</a>

<header class="bar" id="top">
  <a class="logo" href="../../index.html" aria-label="OUT OF THE BOX, torna alla home"><span>OO</span><span>TB</span></a>
  <p class="bar-claim">Fuori dagli schemi.<br>Dentro il cambiamento.</p>
  <button class="burger" aria-expanded="false" aria-controls="menu" aria-label="Apri il menu"><i></i><i></i><i></i></button>
  <nav class="menu" id="menu" aria-label="Principale">
${nav}
  </nav>
</header>

<main class="page" id="main">
  <article class="article">
    <p class="article-meta"><span class="by">di ${esc(it.author)}</span><time datetime="${esc(it.iso)}">${esc(fmtDate.format(it.date))}</time></p>
    <h1>${esc(it.title)}</h1>${it.subtitle ? `\n    <p class="subtitle">${esc(it.subtitle)}</p>` : ''}
    <div class="article-body">
${bodyHtml.trim()}
    </div>${renderLinks(it.links)}
    <a class="btn back" href="${HIDDEN.has(kind.nav) ? '../../index.html' : kind.backHref}">&larr; ${HIDDEN.has(kind.nav) ? 'Torna alla home' : kind.backLabel}</a>
  </article>
</main>

<footer>
  <p class="f-school"><b>ITTS Vito Volterra</b><span>Anno scolastico 2026/2027</span></p>
  <p class="f-site">${esc(BASE ? BASE.replace(/^https?:\/\//, '') : 'ootb-lista.it')}</p>
  <a class="f-ig" href="https://www.instagram.com/outofthebox_volterra/" target="_blank" rel="noopener">@outofthebox_volterra</a>
</footer>
</body>
</html>
`;
}

// ---------- main ----------
const errors = [];
const plan = [];
for (const kind of KINDS) {
  const items = readCollection(kind, errors);
  for (const it of items) {
    const out = path.join(ROOT, kind.outDir, `${it.id}.html`);
    let md = fs.readFileSync(it.md, 'utf8').replace(/^﻿/, '');
    if (!md.trim()) { errors.push(`${kind.json} ("${it.id}"): il file markdown ${rel(it.md)} è vuoto`); continue; }
    plan.push({ kind, it, out, exists: fs.existsSync(out), md });
  }
  // pagine presenti in cartella ma non più nel JSON: solo avviso, non cancello mai nulla
  const dir = path.join(ROOT, kind.outDir);
  if (fs.existsSync(dir)) {
    const ids = new Set(items.map(i => i.id));
    for (const f of fs.readdirSync(dir)) if (f.endsWith('.html') && !ids.has(f.slice(0, -5))) console.warn(`⚠ ${kind.outDir}/${f} non ha una voce in ${kind.json} (lasciato com'è)`);
  }
}

if (errors.length) {
  console.error(`\n✖ ${errors.length} problema/i trovato/i, nessun file scritto:\n`);
  errors.forEach(e => console.error('  • ' + e));
  console.error('');
  process.exit(1);
}

let created = 0, skipped = 0, updated = 0;
for (const p of plan) {
  const label = `${p.kind.outDir}/${p.it.id}.html`;
  if (p.exists && !FORCE) { skipped++; console.log(`= esiste già, salto: ${label}`); continue; }
  if (!DRY) {
    fs.mkdirSync(path.dirname(p.out), { recursive: true });
    fs.writeFileSync(p.out, renderPage(p.kind, p.it, marked.parse(p.md)), 'utf8');
  }
  if (p.exists) { updated++; console.log(`↻ ${DRY ? '[dry-run] ' : ''}rigenerato: ${label}`); }
  else { created++; console.log(`+ ${DRY ? '[dry-run] ' : ''}creato: ${label}`); }
}
console.log(`\nFatto: ${created} create, ${updated} rigenerate, ${skipped} già presenti.`);
