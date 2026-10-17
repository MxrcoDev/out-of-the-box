# OUT OF THE BOX – sito

## Struttura
```
index.html            home (il sito è servito dalla radice del repository)
CNAME  .nojekyll
src/
  html/  css/  js/  img/
  storage/            articles.json · communications.json · activities.json
docs/
  markdown/           testi (.md) di articoli e comunicazioni: SOLO il corpo
  files/              file scaricabili
  articles/           pagine GENERATE – non modificarle a mano
  communications/     pagine GENERATE – non modificarle a mano
.github/
  workflows/build-pages.yml
  scripts/build-pages.mjs  (+ package.json)
```
Tutti i percorsi nei JSON e nei markdown partono dalla **radice del sito**.

## Pubblicare un articolo o una comunicazione
1. Scrivi il corpo in `docs/markdown/nome.md` (niente titolo, autore, data: arrivano dal JSON).
2. (opz.) metti i file da scaricare in `docs/files/`.
3. Aggiungi una voce in `src/storage/articles.json` oppure `communications.json`:
```json
{
  "id": "mio-articolo",
  "title": "Titolo",
  "subtitle": null,
  "author": "Nome Cognome",
  "date": "2026-10-20",
  "content": "nome.md",
  "links": [
    { "type": "download", "uri": "dispensa.pdf" },
    { "type": "redirect", "uri": "https://example.com", "label": "Sito ufficiale" }
  ]
}
```
4. Commit/push su `main`: il workflow crea `docs/articles/mio-articolo.html` e lo committa.

| Campo | Note |
|---|---|
| `id` * | nome del file `.html`; solo lettere, numeri, `-`, `_`. Se la pagina esiste già viene saltata |
| `title` * `author` * | testo |
| `subtitle` | testo oppure `null` |
| `date` * | `AAAA-MM-GG` |
| `content` * | `.md` in `docs/markdown` (`nome.md` o `docs/markdown/nome.md`) |
| `links` | `download`: file in `docs/files` (`uri` = nome file). `redirect`: URL http(s) o pagina interna. `label` è facoltativo |

Nel markdown: `#` diventa `<h2>` (l'`<h1>` è il titolo); `![alt](src/img/x.png "didascalia")` crea una figura; i percorsi relativi partono dalla radice del sito.

## Modificare una pagina già creata
Le pagine esistenti non vengono toccate. Dopo aver cambiato JSON o markdown: **Actions → Genera pagine… → Run workflow → force**, oppure in locale `npm run build:force`.

## In locale
```
cd .github/scripts && npm install
node build-pages.mjs --dry-run   # solo controlli
node build-pages.mjs [--force]
```
Se i dati sono errati lo script elenca i problemi e non scrive nulla (il workflow fallisce).

Impostazioni GitHub: Settings → Actions → General → Workflow permissions = *Read and write*; Pages servite dal branch `main`, cartella `/ (root)`.

## Pagine nascoste
*Fatti sentire*, *Bacheca studenti* e *Showcase* sono nascoste: i tre file in `src/html` sono solo un reindirizzamento alla home e i loro contenuti (html, js, css) sono stati rimossi dal sito, quindi non sono più consultabili nemmeno da URL diretto. Il generatore usa `HIDDEN` in `build-pages.mjs` per menu e pulsante "indietro" delle pagine generate.

Per riattivarle: recupera i file dalla versione precedente (commit `af0988f`):
```
git checkout af0988f -- src/html src/js/bacheca.js src/js/showcase.js src/js/fattisentire.js src/css/bacheca.css src/css/showcase.css src/css/fattisentire.css
```
poi rimetti le voci nei menu di `index.html` e `src/html/proposte.html` e svuota `HIDDEN`.
